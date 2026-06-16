"""Webhook receiver. Verifies HMAC or API key, extracts triggers, creates Sandbox CR."""
import hashlib
import hmac
import json
import os
import time

from fastapi import FastAPI, HTTPException, Request, Response

from . import k8shelper
from .common import get_logger

log = get_logger("receiver")
app = FastAPI(title="claude-agent-runner webhook receiver")

WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "").encode()
API_KEY = os.environ.get("API_KEY", "")
ALLOWED = {u.strip().lower() for u in os.environ.get("ALLOWED_USERS", "").split(",") if u.strip()}
TRIGGER = os.environ.get("TRIGGER_PHRASE", "/fix").strip()


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


def _allowed(sender: str) -> bool:
    if not ALLOWED:
        return True
    base = sender.lower().removesuffix("[bot]")
    return sender.lower() in ALLOWED or base in ALLOWED


@app.get("/healthz")
def healthz():
    return {"ok": True}


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
    if event != "issue_comment":
        return {"ok": True, "skipped": True}

    task = _extract(payload)
    if task is None:
        return {"ok": True, "skipped": True}

    name = k8shelper.create_sandbox(task)
    return Response(
        status_code=202,
        content=json.dumps({"accepted": True, "sandbox": name}),
        media_type="application/json",
    )


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

    ts = int(time.time())
    safe = "".join(c.lower() if c.isalnum() else "-" for c in task_in.get("repo_full", "custom")).strip("-")
    task = {
        "sandbox_name": f"fix-{safe}-{task_in.get('number', 0)}-{ts}"[:58],
        "repo_full": task_in.get("repo_full", ""),
        "clone_url": task_in.get("clone_url", ""),
        "default_branch": task_in.get("default_branch", "main"),
        "number": task_in.get("number", 0),
        "title": task_in.get("title", ""),
        "body": task_in.get("body", "") or "",
        "instruction": task_in.get("instruction", ""),
        "sender": task_in.get("sender", "api"),
        "is_pr": task_in.get("is_pr", False),
        "reason": f"custom trigger by api",
    }

    name = k8shelper.create_sandbox(task)
    return Response(
        status_code=202,
        content=json.dumps({"accepted": True, "sandbox": name}),
        media_type="application/json",
    )


def _extract(p: dict) -> dict | None:
    """Extract task from issue_comment webhook. Only handles trigger phrase."""
    if p.get("action") != "created":
        return None

    sender = (p.get("sender") or {}).get("login", "")
    if not _allowed(sender):
        return None

    comment = (p.get("comment") or {}).get("body", "").strip()
    if not comment:
        return None
    first = comment.splitlines()[0].strip().lower()
    if not first.startswith(TRIGGER.lower()):
        return None

    repo = p.get("repository", {})
    issue = p.get("issue", {})
    num = issue.get("number")
    ts = int(time.time())
    safe = "".join(c.lower() if c.isalnum() else "-" for c in repo.get("full_name", "")).strip("-")

    return {
        "sandbox_name": f"fix-{safe}-{num}-{ts}"[:58],
        "repo_full": repo.get("full_name"),
        "clone_url": repo.get("clone_url"),
        "default_branch": repo.get("default_branch", "main"),
        "number": num,
        "title": issue.get("title", ""),
        "body": issue.get("body", "") or "",
        "instruction": comment[len(TRIGGER):].strip(),
        "sender": sender,
        "is_pr": "pull_request" in issue,
        "reason": f"{TRIGGER} by {sender}",
    }
