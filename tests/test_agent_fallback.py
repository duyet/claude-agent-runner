"""Tests for the Python-level fallback diagnostic comment.

When the agent finishes without executing any tool (broken model) or raises,
the requester must still get a response — posted directly via the GitHub API,
independent of the SDK tool loop.
"""
from app import agent as agent_mod


def _capture_httpx(monkeypatch):
    calls = []

    class _Resp:
        status_code = 201
        text = ""

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def test_fallback_comment_posts_for_issue(monkeypatch):
    calls = _capture_httpx(monkeypatch)
    task = {
        "number": 2,
        "repo_full": "duyet/infra",
        "sandbox_name": "fix-duyet-infra-2-1",
        "is_pr": False,
    }
    agent_mod._post_failure_comment(task, "tok", "executed 0 tools")

    assert len(calls) == 1
    assert calls[0]["url"] == (
        "https://api.github.com/repos/duyet/infra/issues/2/comments"
    )
    assert calls[0]["headers"]["Authorization"] == "Bearer tok"
    assert "executed 0 tools" in calls[0]["json"]["body"]


def test_fallback_comment_skips_prs(monkeypatch):
    calls = _capture_httpx(monkeypatch)
    task = {"number": 9, "repo_full": "duyet/infra", "is_pr": True}
    agent_mod._post_failure_comment(task, "tok", "failed")
    assert calls == []  # PRs are handled via review flow, not issue comments


def test_fallback_comment_skips_when_no_number(monkeypatch):
    calls = _capture_httpx(monkeypatch)
    agent_mod._post_failure_comment({"repo_full": "duyet/infra"}, "tok", "failed")
    assert calls == []


def test_fallback_comment_never_raises(monkeypatch):
    import httpx

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(httpx, "post", boom)
    # Must swallow errors — it runs inside the sandbox cleanup path.
    agent_mod._post_failure_comment(
        {"number": 2, "repo_full": "duyet/infra"}, "tok", "failed"
    )
