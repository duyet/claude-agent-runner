"""Shared helpers: logging, env, task decoding."""
import base64
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
