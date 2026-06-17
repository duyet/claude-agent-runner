"""Tests for the GitHub App token-rotation logic in the poller.

Regression guard: installation tokens expire after ~1h, so the poller must
re-mint and rebuild its client instead of reusing one built at startup.
"""
import asyncio

from app import poller as poller_mod
from app.poller import GitHubPoller


def _enable_app_auth(monkeypatch):
    monkeypatch.setattr(poller_mod, "GH_APP_ID", "123")
    monkeypatch.setattr(poller_mod, "GH_PRIVATE_KEY", "key")


def test_refresh_builds_client_on_first_call(monkeypatch):
    _enable_app_auth(monkeypatch)
    monkeypatch.setattr(poller_mod.gh_token, "token_for", lambda repo: "tok-1")

    p = GitHubPoller()
    assert p.github is None
    p._refresh_github_client("duyet/infra")
    assert p.github is not None
    assert p._gh_token == "tok-1"


def test_refresh_rebuilds_only_when_token_rotates(monkeypatch):
    _enable_app_auth(monkeypatch)
    tokens = iter(["tok-1", "tok-1", "tok-2"])
    monkeypatch.setattr(poller_mod.gh_token, "token_for", lambda repo: next(tokens))

    p = GitHubPoller()
    p._refresh_github_client("duyet/infra")
    first = p.github
    p._refresh_github_client("duyet/infra")  # same token → same client
    assert p.github is first
    p._refresh_github_client("duyet/infra")  # rotated token → new client
    assert p.github is not first
    assert p._gh_token == "tok-2"


def test_refresh_keeps_old_client_when_mint_fails(monkeypatch):
    _enable_app_auth(monkeypatch)
    monkeypatch.setattr(poller_mod.gh_token, "token_for", lambda repo: "tok-1")
    p = GitHubPoller()
    p._refresh_github_client("duyet/infra")
    good = p.github

    def boom(repo):
        raise RuntimeError("github down")

    monkeypatch.setattr(poller_mod.gh_token, "token_for", boom)
    p._refresh_github_client("duyet/infra")
    assert p.github is good  # falls back to last valid client, no crash


def test_refresh_noop_without_app_creds(monkeypatch):
    monkeypatch.setattr(poller_mod, "GH_APP_ID", None)
    monkeypatch.setattr(poller_mod, "GH_PRIVATE_KEY", None)
    p = GitHubPoller()
    p._refresh_github_client("duyet/infra")
    assert p.github is None  # PAT path handled by _ensure_github_client instead


def test_load_processed_round_trips_via_state(monkeypatch, tmp_path):
    """Dedup must survive a restart: a persisted run repopulates the cache.

    Regression guard for the old _load_processed, which read non-existent
    AgentRun fields (task_id/trigger_context/created_at) and silently loaded
    nothing, so every restart re-created sandboxes for all open issues.
    """
    monkeypatch.setenv("STATE_MODE", "shared")
    monkeypatch.setenv("STATE_BACKEND", "file")
    monkeypatch.setenv("STATE_SHARED_PATH", str(tmp_path))

    from app.state import StateManager, Trigger

    # Writer persists an issue + a PR, as the poller does on sandbox creation.
    writer = StateManager()
    writer.create_run(
        sandbox_name="fix-duyet-infra-2-1", repo_full="duyet/infra",
        repo_url="https://github.com/duyet/infra.git", branch="main",
        trigger=Trigger(type="github_issue", user="duyet", issue_number=2),
        model="", max_turns=0,
    )
    writer.create_run(
        sandbox_name="fix-duyet-infra-9-1", repo_full="duyet/infra",
        repo_url="https://github.com/duyet/infra.git", branch="main",
        trigger=Trigger(type="github_pr", user="duyet", issue_number=9),
        model="", max_turns=0,
    )

    # A fresh poller (simulating a restart) must rebuild its dedup cache.
    p = GitHubPoller()
    asyncio.run(p._load_processed())
    assert p.processed.get("issue:duyet/infra:2") is not None
    assert p.processed.get("pr:duyet/infra:9") is not None
