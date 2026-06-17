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


def test_get_logger_configures_once(monkeypatch):
    monkeypatch.setattr(common, "_configured", False)
    logging.getLogger().handlers.clear()

    common.get_logger("a")
    handlers_after_first = list(logging.getLogger().handlers)
    common.get_logger("b")

    # Second call must not re-add handlers (no duplicate log lines).
    assert logging.getLogger().handlers == handlers_after_first
    assert len(handlers_after_first) == 1
