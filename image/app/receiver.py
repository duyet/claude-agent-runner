"""GitHub webhook receiver. Verifies HMAC, extracts /fix triggers, creates a Sandbox CR."""
import hashlib
import hmac
import json
import os
import time

from fastapi import FastAPI, HTTPException, Request, Response

from . import k8shelper
from .common import get_logger

log = get_logger("receiver")
app = FastAPI(title="agent-runner webhook receiver")

WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "").encode()
ALLOWED = {u.strip().lower() for u in os.environ.get("ALLOWED_USERS", "duyet").split(",") if u.strip()}
TRIGGER = os.environ.get("TRIGGER_PHRASE", "/fix").strip()
ISSUE_LABEL = os.environ.get("ISSUE_LABEL", "agent").strip().lower()
CUSTOM_API_KEY = os.environ.get("CUSTOM_API_KEY", "").encode()


def _verify(raw: bytes, sig: str | None) -> bool:
    if not WEBHOOK_SECRET or not sig:
        return False
    mac = hmac.new(WEBHOOK_SECRET, raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={mac}", sig)


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _verify_custom(raw: bytes, key: str | None) -> bool:
    if not CUSTOM_API_KEY or not key:
        return False
    return hmac.compare_digest(CUSTOM_API_KEY.decode(), key)


@app.post("/webhook/custom")
async def custom(request: Request):
    """Custom webhook endpoint for triggering agent runs via push data."""
    raw = await request.body()
    api_key = request.headers.get("x-api-key", "")
    if not _verify_custom(raw, api_key):
        raise HTTPException(401, "invalid api key")

    try:
        payload = json.loads(raw)
    except Exception:
        raise HTTPException(400, "invalid json")

    log.info("custom webhook: repo=%s", payload.get("repo_full"))

    task = _extract_custom(payload)
    if task is None:
        raise HTTPException(400, "invalid task payload")

    try:
        name = k8shelper.create_sandbox(task)
    except Exception as e:  # noqa: BLE001
        log.exception("create_sandbox failed")
        raise HTTPException(500, f"failed to create sandbox: {e}")

    return Response(
        status_code=202,
        content=json.dumps({"accepted": True, "sandbox": name, "reason": task["reason"]}),
        media_type="application/json",
    )


@app.post("/webhook/github")
async def github(request: Request):
    """GitHub webhook endpoint (private path)."""
    return await _github_handler(request)


@app.post("/api/v1/webhook/github")
async def github_public(request: Request):
    """Public GitHub webhook endpoint for minhagent.dev."""
    return await _github_handler(request)


async def _github_handler(request: Request):
    raw = await request.body()
    if not _verify(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "invalid signature")

    event = request.headers.get("x-github-event", "")
    try:
        payload = json.loads(raw)
    except Exception:
        raise HTTPException(400, "invalid json")

    if event == "ping":
        return {"ok": True, "event": "ping"}

    log.info("event=%s action=%s", event, payload.get("action"))

    task = _extract(event, payload)
    if task is None:
        return {"ok": True, "skipped": True, "event": event}

    try:
        name = k8shelper.create_sandbox(task)
    except Exception as e:  # noqa: BLE001
        log.exception("create_sandbox failed")
        raise HTTPException(500, f"failed to create sandbox: {e}")

    return Response(
        status_code=202,
        content=json.dumps({"accepted": True, "sandbox": name, "reason": task["reason"]}),
        media_type="application/json",
    )


def _extract(event: str, p: dict):
    """Extract task from GitHub webhook payload.

    Handles all GitHub event types and extracts relevant information for agent processing.
    Returns a task dict or None if the event should be skipped.
    """
    repo = p.get("repository", {})
    repo_full = repo.get("full_name", "")
    sender = (p.get("sender") or {}).get("login", "")
    # Match the allowlist against the login AND its "bot base", so a GitHub App
    # like duyetbot[bot] is authorized when 'duyetbot' is listed in ALLOWED_USERS.
    # This lets the Hermes agent (which acts as duyetbot[bot]) trigger runs.
    sender_base = sender.lower().removesuffix("[bot]")

    def _allowed() -> bool:
        return sender.lower() in ALLOWED or sender_base in ALLOWED

    def _basic_task(issue_number: int | None = None, pr_number: int | None = None,
                   title: str = "", body: str = "", instruction: str = "",
                   reason: str = "") -> dict:
        """Create a basic task structure with common fields."""
        num = issue_number or pr_number
        if not num:
            num = int(time.time())  # Fallback to timestamp for events without issue/PR numbers
        ts = int(time.time())
        safe = "".join(c.lower() if c.isalnum() else "-" for c in repo_full).strip("-")
        is_pr = pr_number is not None
        return {
            "sandbox_name": f"fix-{safe}-{num}-{ts}"[:58],
            "repo_full": repo_full,
            "clone_url": repo.get("clone_url", ""),
            "default_branch": repo.get("default_branch", "main"),
            "number": num,
            "title": title,
            "body": body or "",
            "instruction": instruction,
            "sender": sender,
            "is_pr": is_pr,
            "reason": reason,
            "event_type": event,
            "raw_payload": p,  # Include full payload for context
        }

    # Log all events for visibility
    action = p.get("action", "N/A")
    log.info("Processing GitHub event: %s (action: %s, sender: %s, repo: %s)",
             event, action, sender, repo_full)

    # ISSUE_COMMENT events - trigger with /fix or /trigger phrase
    if event == "issue_comment":
        if p.get("action") == "created":
            body = ((p.get("comment") or {}).get("body") or "").strip()
            first_line = body.splitlines()[0].strip().lower() if body else ""
            if not first_line.startswith(TRIGGER.lower()):
                log.info("Comment does not start with trigger phrase '%s'", TRIGGER)
                return None
            if not _allowed():
                log.info("Unauthorized sender %s for issue_comment", sender)
                return None
            issue = p.get("issue", {})
            instruction = body[len(TRIGGER):].strip()
            return _basic_task(
                issue_number=issue.get("number"),
                title=issue.get("title", ""),
                body=issue.get("body") or "",
                instruction=instruction,
                reason=f"{TRIGGER} by {sender}",
            )
        log.info("Skipping issue_comment action: %s", p.get("action"))
        return None

    # ISSUES events - labeled with agent label or opened
    if event == "issues":
        if p.get("action") in ("opened", "reopened"):
            if not _allowed():
                log.info("Unauthorized sender %s for issues", sender)
                return None
            issue = p.get("issue", {})
            return _basic_task(
                issue_number=issue.get("number"),
                title=issue.get("title", ""),
                body=issue.get("body") or "",
                reason=f"Issue {p.get('action')} by {sender}",
            )
        if p.get("action") == "labeled":
            labels = {(l.get("name") or "").lower() for l in issue.get("labels", [])}
            if ISSUE_LABEL not in labels:
                log.info("Issue not labeled with '%s'", ISSUE_LABEL)
                return None
            if not _allowed():
                log.info("Unauthorized sender %s for labeled issue", sender)
                return None
            issue = p.get("issue", {})
            return _basic_task(
                issue_number=issue.get("number"),
                title=issue.get("title", ""),
                body=issue.get("body") or "",
                reason=f"Issue labeled {ISSUE_LABEL} by {sender}",
            )
        log.info("Skipping issues action: %s", p.get("action"))
        return None

    # PULL_REQUEST events - opened, reopened, or ready for review
    if event == "pull_request":
        if p.get("action") in ("opened", "reopened", "ready_for_review"):
            if not _allowed():
                log.info("Unauthorized sender %s for pull_request", sender)
                return None
            pr = p.get("pull_request", {})
            # Check if PR body contains trigger phrase
            pr_body = (pr.get("body") or "").strip()
            if pr_body and TRIGGER.lower() in pr_body.lower():
                # Extract instruction after the trigger phrase
                lines = pr_body.splitlines()
                instruction = ""
                for i, line in enumerate(lines):
                    if TRIGGER.lower() in line.lower():
                        instruction = "\n".join(lines[i+1:]).strip()
                        break
                return _basic_task(
                    pr_number=pr.get("number"),
                    title=pr.get("title", ""),
                    body=pr.get("body") or "",
                    instruction=instruction,
                    reason=f"PR {p.get('action')} with {TRIGGER} by {sender}",
                )
            return _basic_task(
                pr_number=pr.get("number"),
                title=pr.get("title", ""),
                body=pr.get("body") or "",
                reason=f"PR {p.get('action')} by {sender}",
            )
        log.info("Skipping pull_request action: %s", p.get("action"))
        return None

    # PULL_REQUEST_REVIEW events - review submitted
    if event == "pull_request_review":
        if p.get("action") == "submitted":
            if not _allowed():
                log.info("Unauthorized sender %s for pull_request_review", sender)
                return None
            pr = p.get("pull_request", {})
            review = p.get("review", {})
            review_body = (review.get("body") or "").strip()
            if review_body and TRIGGER.lower() in review_body.lower():
                return _basic_task(
                    pr_number=pr.get("number"),
                    title=pr.get("title", ""),
                    body=f"Review by {sender}:\n{review_body}",
                    reason=f"PR review with {TRIGGER} by {sender}",
                )
        log.info("Skipping pull_request_review action: %s", p.get("action"))
        return None

    # PULL_REQUEST_REVIEW_COMMENT events - comment on PR review
    if event == "pull_request_review_comment":
        if p.get("action") == "created":
            comment = p.get("comment", {})
            body = (comment.get("body") or "").strip()
            if body and TRIGGER.lower() in body.lower():
                if not _allowed():
                    log.info("Unauthorized sender %s for pull_request_review_comment", sender)
                    return None
                pr = p.get("pull_request", {})
                return _basic_task(
                    pr_number=pr.get("number"),
                    title=pr.get("title", ""),
                    body=f"Review comment:\n{body}",
                    reason=f"PR review comment with {TRIGGER} by {sender}",
                )
        log.info("Skipping pull_request_review_comment action: %s", p.get("action"))
        return None

    # PUSH events - code pushed to branch
    if event == "push":
        # Only process pushes to main/master branch or if they contain trigger in commit messages
        ref = p.get("ref", "")
        branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
        commits = p.get("commits", [])

        # Check if any commit contains trigger phrase
        for commit in commits:
            message = (commit.get("message") or "").strip()
            if TRIGGER.lower() in message.lower():
                if not _allowed():
                    log.info("Unauthorized sender %s for push with trigger", sender)
                    return None
                return _basic_task(
                    title=f"Push to {branch}",
                    body=f"Branch: {branch}\nPusher: {p.get('pusher', {}).get('name', sender)}\nCommits: {len(commits)}",
                    reason=f"Push with {TRIGGER} by {sender}",
                )

        # Auto-trigger for main/master branch pushes
        if branch in ("main", "master"):
            if not _allowed():
                log.info("Unauthorized sender %s for push to main", sender)
                return None
            return _basic_task(
                title=f"Push to {branch}",
                body=f"Branch: {branch}\nPusher: {p.get('pusher', {}).get('name', sender)}\nCommits: {len(commits)}",
                reason=f"Push to {branch} by {sender}",
            )

        log.info("Skipping push to branch: %s", branch)
        return None

    # RELEASE events - new release published
    if event == "release":
        if p.get("action") == "published":
            if not _allowed():
                log.info("Unauthorized sender %s for release", sender)
                return None
            release = p.get("release", {})
            return _basic_task(
                title=f"Release {release.get('tag_name', '')}",
                body=release.get("body") or "",
                reason=f"Release published by {sender}",
            )
        log.info("Skipping release action: %s", p.get("action"))
        return None

    # FORK events - repository forked
    if event == "fork":
        if not _allowed():
            log.info("Unauthorized sender %s for fork", sender)
            return None
        forkee = p.get("forkee", {})
        return _basic_task(
            title=f"Repository forked by {sender}",
            body=f"Fork: {forkee.get('full_name', '')}\nOwner: {forkee.get('owner', {}).get('login', '')}",
            reason=f"Fork by {sender}",
        )

    # WATCH / STAR events - star added
    if event in ("watch", "star"):
        if p.get("action") == "created" or event == "star":
            if not _allowed():
                log.info("Unauthorized sender %s for %s", sender, event)
                return None
            return _basic_task(
                title=f"Repository {event}ed by {sender}",
                reason=f"{event.capitalize()} by {sender}",
            )
        log.info("Skipping %s action: %s", event, p.get("action"))
        return None

    # COMMIT_COMMENT events - comment on commit
    if event == "commit_comment":
        if p.get("action") == "created":
            comment = p.get("comment", {})
            body = (comment.get("body") or "").strip()
            if body and TRIGGER.lower() in body.lower():
                if not _allowed():
                    log.info("Unauthorized sender %s for commit_comment", sender)
                    return None
                return _basic_task(
                    title=f"Commit comment by {sender}",
                    body=f"Comment: {body}\nCommit: {comment.get('commit_id', '')}",
                    reason=f"Commit comment with {TRIGGER} by {sender}",
                )
        log.info("Skipping commit_comment action: %s", p.get("action"))
        return None

    # CREATE events - branch or tag created
    if event == "create":
        if p.get("ref_type") in ("branch", "tag"):
            if not _allowed():
                log.info("Unauthorized sender %s for create", sender)
                return None
            return _basic_task(
                title=f"{p.get('ref_type', '').capitalize()} created by {sender}",
                body=f"Name: {p.get('ref', '')}\nSHA: {p.get('master_branch', '')}",
                reason=f"{p.get('ref_type', '').capitalize()} created by {sender}",
            )
        log.info("Skipping create ref_type: %s", p.get("ref_type"))
        return None

    # DELETE events - branch or tag deleted
    if event == "delete":
        if p.get("ref_type") in ("branch", "tag"):
            if not _allowed():
                log.info("Unauthorized sender %s for delete", sender)
                return None
            return _basic_task(
                title=f"{p.get('ref_type', '').capitalize()} deleted by {sender}",
                body=f"Name: {p.get('ref', '')}",
                reason=f"{p.get('ref_type', '').capitalize()} deleted by {sender}",
            )
        log.info("Skipping delete ref_type: %s", p.get("ref_type"))
        return None

    # Generic handler for all other event types
    # Log the event but don't create a task unless explicitly configured
    log.info("GitHub event '%s' (action: %s) received but not configured for auto-processing",
             event, action)
    return None
        instruction = body[len(TRIGGER):].strip()
        return _task(repo, repo_full, issue, instruction, sender,
                     is_pr="pull_request" in issue, reason=f"{TRIGGER} by {sender}")

    if event == "issues" and p.get("action") == "opened":
        issue = p.get("issue", {})
        labels = {(l.get("name") or "").lower() for l in issue.get("labels", [])}
        if ISSUE_LABEL not in labels:
            return None
        if not _allowed():
            return None
        return _task(repo, repo_full, issue, "", sender, is_pr=False,
                     reason=f"issue labeled {ISSUE_LABEL} by {sender}")

    return None


def _extract_custom(p: dict) -> dict | None:
    """Extract task from custom webhook payload.

    Expected format:
    {
        "repo_full": "owner/repo",
        "clone_url": "https://github.com/owner/repo.git",
        "default_branch": "main",
        "number": 123,
        "title": "Issue title",
        "body": "Issue description",
        "instruction": "Additional instructions (optional)",
        "sender": "username",
        "is_pr": false,
        "reason": "Custom trigger via API"
    }
    """
    required = ["repo_full", "clone_url", "number", "title", "body"]
    if not all(k in p for k in required):
        log.warning("custom payload missing required fields: %s", required)
        return None

    repo_full = p["repo_full"]
    ts = int(time.time())
    safe = "".join(c.lower() if c.isalnum() else "-" for c in repo_full).strip("-")

    return {
        "sandbox_name": f"fix-{safe}-{p['number']}-{ts}"[:58],
        "repo_full": repo_full,
        "clone_url": p["clone_url"],
        "default_branch": p.get("default_branch", "main"),
        "number": p["number"],
        "title": p["title"],
        "body": p["body"] or "",
        "instruction": p.get("instruction", ""),
        "sender": p.get("sender", "api"),
        "is_pr": p.get("is_pr", False),
        "reason": p.get("reason", "Custom trigger via API"),
    }


def _task(repo: dict, repo_full: str, issue: dict, instruction: str, sender: str,
          is_pr: bool, reason: str) -> dict:
    num = issue.get("number")
    ts = int(time.time())
    safe = "".join(c.lower() if c.isalnum() else "-" for c in repo_full).strip("-")
    return {
        "sandbox_name": f"fix-{safe}-{num}-{ts}"[:58],
        "repo_full": repo_full,
        "clone_url": repo.get("clone_url", ""),
        "default_branch": repo.get("default_branch", "main"),
        "number": num,
        "title": issue.get("title", ""),
        "body": issue.get("body") or "",
        "instruction": instruction,
        "sender": sender,
        "is_pr": is_pr,
        "reason": reason,
    }
