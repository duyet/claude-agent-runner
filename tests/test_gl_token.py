"""Tests for the GitLab static-token auth helper."""
import importlib

import pytest

from app import gl_token


def _reload(monkeypatch, **env):
    """Reload gl_token so module-level GITLAB_URL picks up env changes."""
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    return importlib.reload(gl_token)


def test_token_from_gitlab_token(monkeypatch):
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-primary")
    monkeypatch.delenv("GL_TOKEN", raising=False)
    assert gl_token.token_for("group/project") == "glpat-primary"


def test_token_falls_back_to_gl_token(monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.setenv("GL_TOKEN", "glpat-fallback")
    assert gl_token.token_for("group/project") == "glpat-fallback"


def test_gitlab_token_preferred_over_gl_token(monkeypatch):
    monkeypatch.setenv("GITLAB_TOKEN", "primary")
    monkeypatch.setenv("GL_TOKEN", "fallback")
    assert gl_token.token_for("group/project") == "primary"


def test_missing_token_raises_system_exit(monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("GL_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        gl_token.token_for("group/project")


def test_git_remote_default_host(monkeypatch):
    mod = _reload(monkeypatch, GITLAB_URL=None)
    try:
        assert mod.git_remote("group/project", "tok") == (
            "https://oauth2:tok@gitlab.com/group/project.git"
        )
    finally:
        _reload(monkeypatch, GITLAB_URL=None)


def test_git_remote_self_hosted(monkeypatch):
    mod = _reload(monkeypatch, GITLAB_URL="https://gitlab.example.com")
    try:
        assert mod.git_remote("group/sub/project", "tok") == (
            "https://oauth2:tok@gitlab.example.com/group/sub/project.git"
        )
    finally:
        _reload(monkeypatch, GITLAB_URL=None)


def test_git_remote_strips_trailing_slash(monkeypatch):
    mod = _reload(monkeypatch, GITLAB_URL="https://gitlab.example.com/")
    try:
        assert mod.git_remote("g/p", "tok") == (
            "https://oauth2:tok@gitlab.example.com/g/p.git"
        )
    finally:
        _reload(monkeypatch, GITLAB_URL=None)


def test_api_base_default(monkeypatch):
    mod = _reload(monkeypatch, GITLAB_URL=None)
    try:
        assert mod.api_base() == "https://gitlab.com/api/v4"
    finally:
        _reload(monkeypatch, GITLAB_URL=None)


def test_api_base_self_hosted(monkeypatch):
    mod = _reload(monkeypatch, GITLAB_URL="https://gitlab.example.com")
    try:
        assert mod.api_base() == "https://gitlab.example.com/api/v4"
    finally:
        _reload(monkeypatch, GITLAB_URL=None)


def test_api_headers():
    assert gl_token.api_headers("tok") == {
        "PRIVATE-TOKEN": "tok",
        "Content-Type": "application/json",
    }
