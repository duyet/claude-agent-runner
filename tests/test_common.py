"""Tests for shared env + logging helpers."""
import logging

import pytest

from app import common


def test_env_returns_value(monkeypatch):
    monkeypatch.setenv("FOO", "bar")
    assert common.env("FOO") == "bar"


def test_env_default_when_missing(monkeypatch):
    monkeypatch.delenv("MISSING", raising=False)
    assert common.env("MISSING", default="fallback") == "fallback"


def test_env_required_raises_when_absent(monkeypatch):
    monkeypatch.delenv("REQUIRED", raising=False)
    with pytest.raises(SystemExit):
        common.env("REQUIRED", required=True)


def test_slugify_lowercases_and_collapses():
    assert common.slugify("Duyet/Infra") == "duyet-infra"
    assert common.slugify("a_b.c") == "a-b-c"
    assert common.slugify("--Trim--") == "trim"


def test_sandbox_name_shape_and_length():
    name = common.sandbox_name("duyet/infra", 42)
    assert name.startswith("fix-duyet-infra-42-")
    assert len(name) <= 58


def test_user_allowed_empty_allowlist_permits_all():
    assert common.user_allowed("anyone", set()) is True


def test_user_allowed_matches_login_and_bot_suffix():
    allowed = {"duyet"}
    assert common.user_allowed("duyet", allowed) is True
    assert common.user_allowed("Duyet", allowed) is True  # case-insensitive
    assert common.user_allowed("duyet[bot]", allowed) is True  # bot suffix stripped
    assert common.user_allowed("stranger", allowed) is False


def test_build_task_defaults_and_overrides():
    task = common.build_task(
        repo_full="duyet/infra",
        number=7,
        title="t",
        body=None,
        sender="duyet",
        reason="because",
    )
    assert task["repo_full"] == "duyet/infra"
    assert task["number"] == 7
    assert task["body"] == ""  # None coerced to empty string
    assert task["default_branch"] == "main"
    assert task["is_pr"] is False
    assert task["instruction"] == ""
    assert task["reason"] == "because"
    assert task["sandbox_name"].startswith("fix-duyet-infra-7-")


def test_get_logger_configures_once(monkeypatch):
    monkeypatch.setattr(common, "_configured", False)
    logging.getLogger().handlers.clear()

    common.get_logger("a")
    handlers_after_first = list(logging.getLogger().handlers)
    common.get_logger("b")

    # Second call must not re-add handlers (no duplicate log lines).
    assert logging.getLogger().handlers == handlers_after_first
    assert len(handlers_after_first) == 1
