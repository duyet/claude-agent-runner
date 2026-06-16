"""Claude Agent Runner - Kubernetes-based autonomous agent system.

This package provides two main entrypoints:
- Receiver (FastAPI webhook server): Handles GitHub/custom webhooks, creates sandbox CRs
- Agent (CLI): Runs inside ephemeral pods, clones repos, executes Claude Agent SDK tasks

Example usage:
    # Start webhook receiver (default entrypoint)
    uvicorn app.receiver:app --reload --port 8080

    # Run agent in sandbox pod
    python -m app.agent
"""

from app.receiver import app as webhook_app
from app.common import get_logger, env, load_task

__version__ = "0.1.0"
__all__ = ["webhook_app", "get_logger", "env", "load_task", "__version__"]
