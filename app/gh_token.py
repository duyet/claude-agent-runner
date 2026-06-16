"""GitHub App auth: JWT -> installation access token (60-min TTL), cached.

Reuses the homelab duyetbot App pattern (App ID 1064078). The App must be
installed on the target repo with Contents/Pull-requests/Issues: write.
"""
import datetime as dt
import time

import httpx
import jwt

from .common import env, get_logger

log = get_logger("gh_token")
GH_API = "https://api.github.com"
_cache: dict[str, tuple[str, int]] = {}  # repo_full -> (token, exp_epoch)


def _headers(token: str, bearer: bool = False) -> dict:
    return {
        "Authorization": f"Bearer {token}" if bearer else f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _mint_jwt(app_id: int, private_key: str) -> str:
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + (9 * 60), "iss": str(app_id)}  # 9-min JWT (max 10)
    return jwt.encode(payload, private_key, algorithm="RS256")


def _installation_id(jwt_tok: str, owner: str, repo: str) -> int:
    r = httpx.get(f"{GH_API}/repos/{owner}/{repo}/installation",
                  headers=_headers(jwt_tok, bearer=True), timeout=20)
    r.raise_for_status()
    return r.json()["id"]


def _install_token(jwt_tok: str, inst_id: int) -> tuple[str, int]:
    r = httpx.post(f"{GH_API}/app/installations/{inst_id}/access_tokens",
                   headers=_headers(jwt_tok, bearer=True), timeout=20)
    r.raise_for_status()
    d = r.json()
    exp = dt.datetime.fromisoformat(d["expires_at"].replace("Z", "+00:00")).timestamp()
    return d["token"], int(exp)


def token_for(repo_full: str) -> str:
    """Cached installation token for repo_full ('owner/repo'), refreshed 5 min early."""
    app_id = int(env("GH_APP_ID", required=True))
    key = env("GH_PRIVATE_KEY", required=True).replace("\\n", "\n")

    cached = _cache.get(repo_full)
    if cached and time.time() < cached[1] - 300:
        return cached[0]

    jwt_tok = _mint_jwt(app_id, key)
    owner, repo = repo_full.split("/")
    inst = _installation_id(jwt_tok, owner, repo)
    tok, exp = _install_token(jwt_tok, inst)
    _cache[repo_full] = (tok, exp)
    log.info("minted token for %s (valid %ds)", repo_full, exp - int(time.time()))
    return tok


def git_remote(repo_full: str, token: str) -> str:
    return f"https://x-access-token:{token}@github.com/{repo_full}.git"


def api_headers(token: str) -> dict:
    return _headers(token, bearer=False)
