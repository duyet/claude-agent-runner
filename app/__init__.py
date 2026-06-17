"""Claude Agent Runner - Kubernetes-based autonomous agent system.

This package provides two independent entrypoints that intentionally do NOT
share heavy dependencies:

- Receiver (FastAPI webhook server): handles GitHub/custom webhooks, creates
  Sandbox CRs. Needs FastAPI, PyGithub, kubernetes.
- Agent (CLI): runs inside ephemeral pods, clones repos, executes Claude Agent
  SDK tasks. Needs the Claude Agent SDK and kubernetes.

`webhook_app` is exposed lazily via module ``__getattr__`` so that importing
``app`` (or ``app.agent`` inside the sandbox) does not drag in the receiver's
web-server dependencies.

Example usage:
    # Start webhook receiver (default entrypoint)
    uvicorn app.receiver:app --reload --port 8080

    # Run agent in sandbox pod
    python -m app.agent
"""

from app.common import env, get_logger, load_task

__version__ = "0.1.0"
__all__ = ["webhook_app", "get_logger", "env", "load_task", "__version__"]


def __getattr__(name: str):
    # Lazy import keeps FastAPI/PyGithub out of the agent's import path.
    if name == "webhook_app":
        from app.receiver import app as webhook_app

        return webhook_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
