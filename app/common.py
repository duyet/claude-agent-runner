"""Shared helpers: logging, env, task decoding, and task construction."""
import base64
import json
import logging
import os
import sys
import time

# Aligned, readable format: "06:04:02.646 INFO     poller  message"
_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)-8s %(message)s"
_LOG_DATEFMT = "%H:%M:%S"
_configured = False


def _configure_logging() -> None:
    """Configure root logging once, unbuffered to stdout for live container logs."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_logging()
    return logging.getLogger(name)


def env(key: str, default=None, required: bool = False):
    v = os.environ.get(key, default)
    if required and not v:
        raise SystemExit(f"missing required env {key}")
    return v


def load_task() -> dict:
    """Decode the TASK_JSON env (base64-encoded JSON) that the receiver injected."""
    raw = os.environ.get("TASK_JSON", "")
    if not raw:
        raise SystemExit("TASK_JSON env not set")
    try:
        return json.loads(base64.b64decode(raw).decode())
    except Exception:
        # tolerate plain JSON for manual testing
        return json.loads(raw)


def slugify(text: str) -> str:
    """Lowercase a string and collapse non-alphanumeric runs into single dashes.

    Used to build DNS-safe Kubernetes object names from repo slugs.
    """
    return "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")


def sandbox_name(repo_full: str, number: int | str) -> str:
    """Build a unique, DNS-safe Sandbox CR name for a repo/issue at the current time."""
    return f"fix-{slugify(repo_full)}-{number}-{int(time.time())}"[:58]


def user_allowed(sender: str, allowed: set[str]) -> bool:
    """Return True if `sender` may trigger a run.

    An empty allowlist permits everyone. Both the raw login and its
    `[bot]`-stripped form are matched so bot accounts can be allow-listed
    by their human-readable name.
    """
    if not allowed:
        return True
    low = sender.lower()
    return low in allowed or low.removesuffix("[bot]") in allowed


def build_task(
    *,
    repo_full: str,
    number: int,
    title: str,
    body: str,
    sender: str,
    reason: str,
    default_branch: str = "main",
    clone_url: str = "",
    instruction: str = "",
    is_pr: bool = False,
) -> dict:
    """Build the task payload handed to the sandbox pod via TASK_JSON.

    Centralizes the shape shared by the webhook receiver and the poller so the
    sandbox always receives a consistent set of fields.
    """
    return {
        "sandbox_name": sandbox_name(repo_full, number),
        "repo_full": repo_full,
        "clone_url": clone_url,
        "default_branch": default_branch,
        "number": number,
        "title": title,
        "body": body or "",
        "instruction": instruction,
        "sender": sender,
        "is_pr": is_pr,
        "reason": reason,
    }
