"""Shared helpers: logging, env, task decoding."""
import base64
import hashlib
import json
import logging
import os
import sys

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


def make_sandbox_name(
    repo_full: str,
    number,
    ts: int,
    prefix: str = "fix",
    max_len: int = 58,
) -> str:
    """Build an RFC1123 (DNS-1123) valid Sandbox / pod name.

    Guarantees:
    - lowercase alphanumerics and '-' only, starts and ends with an alphanumeric
    - the trailing ``-<number>-<ts>`` is always preserved intact (naive
      truncation via ``[:58]`` could cut the timestamp, producing collisions or
      a trailing '-' which is an invalid DNS-1123 name)
    - if the assembled name exceeds ``max_len`` the repo portion is truncated and
      a short hash of the full repo is appended so distinct repos don't collide

    The name always ends in the numeric ``ts`` so it can never end in '-'.
    """
    safe = "".join(c.lower() if c.isalnum() else "-" for c in str(repo_full)).strip("-")
    suffix = f"-{number}-{ts}"
    name = f"{prefix}-{safe}{suffix}"

    if len(name) > max_len:
        h = hashlib.sha1(safe.encode()).hexdigest()[:6]
        keep = max_len - len(prefix) - 1 - len(h) - 1 - len(suffix)
        repo_part = safe[:keep].strip("-") if keep > 0 else ""
        mid = f"{repo_part}-{h}" if repo_part else h
        name = f"{prefix}-{mid}{suffix}"

    name = name.strip("-").lower()
    if not name or not name[0].isalnum():
        name = f"{prefix}-{name.strip('-')}".strip("-")
    return name


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
