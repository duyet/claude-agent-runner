"""Webhook receiver. Verifies HMAC or API key, extracts triggers, creates Sandbox CR."""
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response

from . import k8shelper
from .common import build_task, get_logger, user_allowed
from .poller import start_poller

log = get_logger("receiver")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the background poller (if pull mode is enabled) on startup."""
    await start_poller()
    yield


app = FastAPI(title="claude-agent-runner webhook receiver", lifespan=lifespan)

WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "").encode()
GITLAB_WEBHOOK_SECRET = os.environ.get("GITLAB_WEBHOOK_SECRET", "")
API_KEY = os.environ.get("API_KEY", "")
ALLOWED = {u.strip().lower() for u in os.environ.get("ALLOWED_USERS", "").split(",") if u.strip()}
TRIGGER = os.environ.get("TRIGGER_PHRASE", "/fix").strip()
ISSUE_LABEL = os.environ.get("ISSUE_LABEL", "").strip().lower()


def _verify_hmac(raw: bytes, sig: str | None) -> bool:
    """Verify GitHub HMAC-SHA256 signature."""
    if not WEBHOOK_SECRET or not sig:
        return False
    mac = hmac.new(WEBHOOK_SECRET, raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={mac}", sig)


def _verify_api_key(request: Request) -> bool:
    """Verify API key from X-API-Key header or query param."""
    if not API_KEY:
        return False
    key = request.headers.get("x-api-key", "") or request.query_params.get("api_key", "")
    return hmac.compare_digest(key, API_KEY)


def _accepted(name: str) -> Response:
    """Build the 202 Accepted response returned after creating a Sandbox CR."""
    return Response(
        status_code=202,
        content=json.dumps({"accepted": True, "sandbox": name}),
        media_type="application/json",
    )


@app.get("/api/v1/healthz")
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/v1/webhook/github")
@app.post("/webhook/github")
async def github(request: Request):
    """GitHub webhook endpoint. Verifies HMAC-SHA256, handles issue_comment /fix."""
    raw = await request.body()
    if not _verify_hmac(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "invalid signature")

    event = request.headers.get("x-github-event", "")
    payload = json.loads(raw)

    if event == "ping":
        return {"ok": True, "event": "ping"}

    # Handle new issues with matching label
    if event == "issues" and ISSUE_LABEL:
        task = _extract_issue(payload)
        if task is not None:
            return _accepted(k8shelper.create_sandbox(task))
        return {"ok": True, "skipped": True}

    if event != "issue_comment":
        return {"ok": True, "skipped": True}

    task = _extract(payload)
    if task is None:
        return {"ok": True, "skipped": True}

    return _accepted(k8shelper.create_sandbox(task))


@app.post("/api/v1/webhook/custom")
@app.post("/webhook/custom")
async def custom(request: Request):
    """Custom webhook endpoint. Verifies API key, accepts arbitrary task payload.

    Expected JSON body:
    {
      "repo_full": "owner/repo",
      "number": 1,
      "title": "...",
      "body": "...",
      "instruction": "..."
    }
    """
    if API_KEY and not _verify_api_key(request):
        raise HTTPException(401, "invalid api key")

    body = await request.body()
    try:
        task_in = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid json")

    task = build_task(
        repo_full=task_in.get("repo_full", ""),
        number=task_in.get("number", 0),
        title=task_in.get("title", ""),
        body=task_in.get("body", ""),
        sender=task_in.get("sender", "api"),
        reason="custom trigger by api",
        default_branch=task_in.get("default_branch", "main"),
        clone_url=task_in.get("clone_url", ""),
        instruction=task_in.get("instruction", ""),
        is_pr=task_in.get("is_pr", False),
    )

    return _accepted(k8shelper.create_sandbox(task))


@app.post("/api/v1/webhook/gitlab")
@app.post("/webhook/gitlab")
async def gitlab(request: Request):
    """GitLab webhook endpoint. Verifies the X-Gitlab-Token secret, handles notes/issues."""
    token = request.headers.get("x-gitlab-token", "")
    if not GITLAB_WEBHOOK_SECRET or not hmac.compare_digest(token, GITLAB_WEBHOOK_SECRET):
        raise HTTPException(401, "invalid token")

    event = request.headers.get("x-gitlab-event", "")
    payload = json.loads(await request.body())

    if event == "Note Hook":
        task = _extract_gitlab_note(payload)
    elif event == "Issue Hook" and ISSUE_LABEL:
        task = _extract_gitlab_issue(payload)
    else:
        return {"ok": True, "skipped": True}

    if task is None:
        return {"ok": True, "skipped": True}

    return _accepted(k8shelper.create_sandbox(task))


def _extract_gitlab_note(p: dict) -> dict | None:
    """Extract task from a GitLab Note Hook (comment) carrying the trigger phrase."""
    attrs = p.get("object_attributes") or {}
    comment = (attrs.get("note") or "").strip()
    if not comment:
        return None
    first = comment.splitlines()[0].strip().lower()
    if not first.startswith(TRIGGER.lower()):
        return None

    sender = (p.get("user") or {}).get("username", "")
    if not user_allowed(sender, ALLOWED):
        return None

    noteable_type = attrs.get("noteable_type", "")
    if noteable_type == "MergeRequest":
        noteable = p.get("merge_request") or {}
    else:
        noteable = p.get("issue") or {}

    project = p.get("project") or {}
    return _build_gitlab_task(
        project=project,
        noteable=noteable,
        sender=sender,
        reason=f"{TRIGGER} by {sender}",
        instruction=comment[len(TRIGGER):].strip(),
        is_pr=(noteable_type == "MergeRequest"),
    )


def _extract_gitlab_issue(p: dict) -> dict | None:
    """Extract task from a GitLab Issue Hook when opened with the target label."""
    attrs = p.get("object_attributes") or {}
    if attrs.get("action") != "open":
        return None

    labels = {(lbl.get("title") or "").strip().lower() for lbl in p.get("labels") or [] if lbl.get("title")}
    if ISSUE_LABEL not in labels:
        return None

    sender = (p.get("user") or {}).get("username", "")
    if not user_allowed(sender, ALLOWED):
        return None

    project = p.get("project") or {}
    return _build_gitlab_task(
        project=project,
        noteable=attrs,
        sender=sender,
        reason=f"issue opened with label '{ISSUE_LABEL}'",
        instruction="",
        is_pr=False,
    )


def _build_gitlab_task(*, project: dict, noteable: dict, sender: str, reason: str,
                       instruction: str, is_pr: bool) -> dict:
    """Assemble a provider-tagged task from GitLab project + noteable objects."""
    task = build_task(
        repo_full=project.get("path_with_namespace", ""),
        number=noteable.get("iid"),
        title=noteable.get("title", ""),
        body=noteable.get("description", ""),
        sender=sender,
        reason=reason,
        default_branch=project.get("default_branch", "main"),
        clone_url=project.get("git_http_url", ""),
        instruction=instruction,
        is_pr=is_pr,
    )
    task["provider"] = "gitlab"
    return task


def _extract_issue(p: dict) -> dict | None:
    """Extract task from issues.opened webhook if it has the target label."""
    if p.get("action") != "opened":
        return None
    issue = p.get("issue", {})
    labels = {lbl.get("name", "").strip().lower() for lbl in issue.get("labels", []) if lbl.get("name")}
    if ISSUE_LABEL not in labels:
        return None

    sender = (p.get("sender") or {}).get("login", "")
    if not user_allowed(sender, ALLOWED):
        return None

    repo = p.get("repository", {})
    return build_task(
        repo_full=repo.get("full_name", ""),
        number=issue.get("number"),
        title=issue.get("title", ""),
        body=issue.get("body", ""),
        sender=sender,
        reason=f"issue opened with label '{ISSUE_LABEL}'",
        default_branch=repo.get("default_branch", "main"),
        clone_url=repo.get("clone_url", ""),
    )


def _extract(p: dict) -> dict | None:
    """Extract task from issue_comment webhook. Only handles trigger phrase."""
    if p.get("action") != "created":
        return None

    sender = (p.get("sender") or {}).get("login", "")
    if not user_allowed(sender, ALLOWED):
        return None

    comment = (p.get("comment") or {}).get("body", "").strip()
    if not comment:
        return None
    first = comment.splitlines()[0].strip().lower()
    if not first.startswith(TRIGGER.lower()):
        return None

    repo = p.get("repository", {})
    issue = p.get("issue", {})
    return build_task(
        repo_full=repo.get("full_name", ""),
        number=issue.get("number"),
        title=issue.get("title", ""),
        body=issue.get("body", ""),
        sender=sender,
        reason=f"{TRIGGER} by {sender}",
        default_branch=repo.get("default_branch", "main"),
        clone_url=repo.get("clone_url", ""),
        instruction=comment[len(TRIGGER):].strip(),
        is_pr="pull_request" in issue,
    )
