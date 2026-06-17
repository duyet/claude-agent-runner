"""GitLab auth: static Personal/Group/Project Access Token from env.

GitLab has no GitHub-App/installation-token concept — auth is a static token
supplied via `GITLAB_TOKEN` (falls back to `GL_TOKEN`). Self-hosted GitLab is
supported via `GITLAB_URL` (default `https://gitlab.com`).

This mirrors the shape of `app.gh_token` so callers can stay uniform: the
`project_full` argument is accepted for signature-parity even though a static
token ignores it.
"""
from .common import env, get_logger

log = get_logger("gl_token")

# GitLab base URL (scheme + host), trailing slash stripped. Default gitlab.com.
GITLAB_URL = (env("GITLAB_URL", "https://gitlab.com") or "https://gitlab.com").rstrip("/")


def token_for(project_full: str) -> str:
    """Return the GitLab access token.

    Reads `GITLAB_TOKEN`, falling back to `GL_TOKEN`. Raises SystemExit when
    neither is set. `project_full` is accepted for signature-parity with
    `gh_token.token_for` even though a static token ignores it.
    """
    tok = env("GITLAB_TOKEN") or env("GL_TOKEN", required=True)
    log.info("using GitLab token for %s", project_full)
    return tok


def git_remote(project_full: str, token: str) -> str:
    host = GITLAB_URL.split("://", 1)[-1]
    return f"https://oauth2:{token}@{host}/{project_full}.git"


def api_base() -> str:
    return f"{GITLAB_URL}/api/v4"


def api_headers(token: str) -> dict:
    return {"PRIVATE-TOKEN": token, "Content-Type": "application/json"}
