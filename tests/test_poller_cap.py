"""Tests for poller per-cycle cap overflow handling (#17).

The old logic combined a per-cycle cap with break-on-first-processed, which
permanently skipped items beyond the cap. The fix keeps a per-repo backlog set
so the next cycle scans past already-processed items to drain the overflow, and
signals the cap so the watermark isn't advanced.
"""
import asyncio

from app import poller as poller_mod
from app.poller import GitHubPoller


class _Issue:
    def __init__(self, number: int):
        self.number = number
        self.pull_request = None
        self.title = f"issue {number}"
        self.body = ""

        class _User:
            login = "duyet"

        self.user = _User()


class _Repo:
    clone_url = "https://github.com/duyet/infra.git"
    default_branch = "main"

    def __init__(self, issues):
        self._issues = issues

    def get_issues(self, **kwargs):
        return list(self._issues)


def _run(coro):
    return asyncio.run(coro)


def test_cap_hit_sets_backlog_and_returns_true(monkeypatch):
    monkeypatch.setattr(poller_mod, "ALLOWED_USERS", set())
    monkeypatch.setattr(poller_mod.k8shelper, "create_sandbox", lambda task: task["sandbox_name"])

    p = GitHubPoller()
    # 60 fresh issues, newest-first — cap is 50.
    repo = _Repo([_Issue(n) for n in range(60, 0, -1)])

    cap_hit = _run(p._check_new_issues("duyet/infra", repo, None))
    assert cap_hit is True
    assert "duyet/infra" in p._issue_backlog
    # Exactly 50 processed this cycle.
    assert p.stats["sandboxes_created"] == 50


def test_draining_scans_past_processed_to_reach_overflow(monkeypatch):
    monkeypatch.setattr(poller_mod, "ALLOWED_USERS", set())
    monkeypatch.setattr(poller_mod.k8shelper, "create_sandbox", lambda task: task["sandbox_name"])

    p = GitHubPoller()
    issues = [_Issue(n) for n in range(60, 0, -1)]
    repo = _Repo(issues)

    # Cycle 1: processes newest 50, cap hit.
    _run(p._check_new_issues("duyet/infra", repo, None))
    assert p.stats["sandboxes_created"] == 50
    assert p._issue_backlog == {"duyet/infra"}

    # Cycle 2 (draining): must skip the 50 already-processed and drain the last 10.
    p.stats["sandboxes_created"] = 0  # _poll_once resets per cycle; emulate that here
    _run(p._check_new_issues("duyet/infra", repo, None))
    assert p.stats["sandboxes_created"] == 10
    # Backlog cleared once fully drained.
    assert "duyet/infra" not in p._issue_backlog

    # Every issue is now tracked as processed.
    for n in range(1, 61):
        assert p.processed.get(f"issue:duyet/infra:{n}") is not None
