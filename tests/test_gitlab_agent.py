"""Tests for GitLab-aware agent execution paths.

These run WITHOUT app/gl_token.py present (it's a sibling unit). We exercise
only paths that don't require the real module, satisfying the lazy
`from . import gl_token` by injecting a stub into sys.modules where needed.
"""
import sys
import types
from urllib.parse import quote_plus

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


def _install_gl_token_stub(monkeypatch):
    """Inject a minimal app.gl_token stub so the lazy import resolves."""
    stub = types.ModuleType("app.gl_token")
    stub.api_base = lambda: "https://gitlab.com/api/v4"
    stub.api_headers = lambda token: {"PRIVATE-TOKEN": token}
    stub.token_for = lambda project: "gltok"
    stub.git_remote = lambda project, token: (
        f"https://oauth2:{token}@gitlab.com/{project}.git"
    )
    monkeypatch.setitem(sys.modules, "app.gl_token", stub)
    return stub


def test_fallback_comment_routes_to_gitlab(monkeypatch):
    _install_gl_token_stub(monkeypatch)
    calls = _capture_httpx(monkeypatch)
    task = {
        "number": 7,
        "repo_full": "group/sub/proj",
        "sandbox_name": "fix-gitlab-7-1",
        "is_pr": False,
        "provider": "gitlab",
    }
    agent_mod._post_failure_comment(task, "gltok", "executed 0 tools")

    assert len(calls) == 1
    expected_path = quote_plus("group/sub/proj")
    assert calls[0]["url"] == (
        f"https://gitlab.com/api/v4/projects/{expected_path}/issues/7/notes"
    )
    assert calls[0]["headers"]["PRIVATE-TOKEN"] == "gltok"
    assert "executed 0 tools" in calls[0]["json"]["body"]


def test_fallback_comment_gitlab_skips_mrs(monkeypatch):
    _install_gl_token_stub(monkeypatch)
    calls = _capture_httpx(monkeypatch)
    task = {
        "number": 9,
        "repo_full": "group/proj",
        "is_pr": True,
        "provider": "gitlab",
    }
    agent_mod._post_failure_comment(task, "gltok", "failed")
    assert calls == []  # merge requests are not commented via the notes API here


def test_fallback_comment_defaults_to_github(monkeypatch):
    calls = _capture_httpx(monkeypatch)
    # No provider key -> GitHub behavior (existing default).
    task = {"number": 2, "repo_full": "duyet/infra", "is_pr": False}
    agent_mod._post_failure_comment(task, "tok", "executed 0 tools")

    assert len(calls) == 1
    assert calls[0]["url"] == (
        "https://api.github.com/repos/duyet/infra/issues/2/comments"
    )
    assert calls[0]["headers"]["Authorization"] == "Bearer tok"
    assert "executed 0 tools" in calls[0]["json"]["body"]


def test_fallback_comment_explicit_github(monkeypatch):
    calls = _capture_httpx(monkeypatch)
    task = {
        "number": 3,
        "repo_full": "duyet/infra",
        "is_pr": False,
        "provider": "github",
    }
    agent_mod._post_failure_comment(task, "tok", "failed")

    assert len(calls) == 1
    assert calls[0]["url"] == (
        "https://api.github.com/repos/duyet/infra/issues/3/comments"
    )
    assert calls[0]["headers"]["Authorization"] == "Bearer tok"


def test_prompt_gitlab_wording():
    task = {
        "number": 5,
        "repo_full": "group/proj",
        "title": "Bug",
        "body": "Something is broken",
        "provider": "gitlab",
    }
    prompt = agent_mod._prompt(task)
    assert "glab" in prompt
    assert "merge request" in prompt.lower()
    assert "gh issue comment" not in prompt


def test_prompt_gitlab_custom_trigger():
    task = {
        "repo_full": "group/proj",
        "title": "Task",
        "body": "Do the thing",
        "reason": "scheduled",
        "provider": "gitlab",
    }
    prompt = agent_mod._prompt(task)
    assert "merge request" in prompt.lower()
    assert "GitHub tool" not in prompt


def test_prompt_github_wording_default():
    task = {
        "number": 5,
        "repo_full": "duyet/infra",
        "title": "Bug",
        "body": "Something is broken",
    }
    prompt = agent_mod._prompt(task)
    assert "gh issue comment" in prompt
    assert "glab" not in prompt


def test_relevant_env_prefixes_include_gitlab():
    assert "GITLAB_" in agent_mod._RELEVANT_ENV_PREFIXES
    assert "GL_" in agent_mod._RELEVANT_ENV_PREFIXES
