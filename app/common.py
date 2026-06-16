"""Shared helpers: logging, env, task decoding."""
import base64
import json
import logging
import os
import sys


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
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
