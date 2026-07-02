"""Tests for receiver auth + trigger extraction (security-critical paths).

Guards:
- HMAC verify accept/reject (GitHub webhook signature)
- API-key verify fails CLOSED when API_KEY is unset (#14)
- allowlist extraction (_allowed / _extract)
"""
import hashlib
import hmac

from app import receiver


def _sign(secret: bytes, body: bytes) -> str:
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


def test_hmac_accepts_valid_signature(monkeypatch):
    secret = b"topsecret"
    monkeypatch.setattr(receiver, "WEBHOOK_SECRET", secret)
    body = b'{"hello":"world"}'
    assert receiver._verify_hmac(body, _sign(secret, body)) is True


def test_hmac_rejects_bad_signature(monkeypatch):
    monkeypatch.setattr(receiver, "WEBHOOK_SECRET", b"topsecret")
    assert receiver._verify_hmac(b"body", "sha256=deadbeef") is False


def test_hmac_rejects_when_secret_unset(monkeypatch):
    # Fail closed: no configured secret -> reject everything.
    monkeypatch.setattr(receiver, "WEBHOOK_SECRET", b"")
    assert receiver._verify_hmac(b"body", "sha256=whatever") is False


def test_hmac_rejects_missing_signature(monkeypatch):
    monkeypatch.setattr(receiver, "WEBHOOK_SECRET", b"topsecret")
    assert receiver._verify_hmac(b"body", None) is False


def test_api_key_fails_closed_when_unset(monkeypatch):
    # #14: when API_KEY is unset the endpoint must NOT authenticate anonymously.
    monkeypatch.setattr(receiver, "API_KEY", "")

    class _Req:
        headers = {"x-api-key": "anything"}
        query_params = {}

    assert receiver._verify_api_key(_Req()) is False


def test_api_key_accepts_matching_key(monkeypatch):
    monkeypatch.setattr(receiver, "API_KEY", "secret-key")

    class _Req:
        headers = {"x-api-key": "secret-key"}
        query_params = {}

    assert receiver._verify_api_key(_Req()) is True


def test_api_key_rejects_wrong_key(monkeypatch):
    monkeypatch.setattr(receiver, "API_KEY", "secret-key")

    class _Req:
        headers = {"x-api-key": "nope"}
        query_params = {}

    assert receiver._verify_api_key(_Req()) is False


def test_allowlist_empty_allows_all(monkeypatch):
    monkeypatch.setattr(receiver, "ALLOWED", set())
    assert receiver._allowed("anybody") is True


def test_allowlist_permits_listed_and_bot_suffix(monkeypatch):
    monkeypatch.setattr(receiver, "ALLOWED", {"duyet"})
    assert receiver._allowed("duyet") is True
    assert receiver._allowed("duyet[bot]") is True
    assert receiver._allowed("stranger") is False


def test_extract_returns_task_for_trigger(monkeypatch):
    monkeypatch.setattr(receiver, "ALLOWED", set())
    monkeypatch.setattr(receiver, "TRIGGER", "/fix")
    payload = {
        "action": "created",
        "sender": {"login": "duyet"},
        "comment": {"body": "/fix please handle this"},
        "repository": {"full_name": "duyet/infra", "clone_url": "https://x", "default_branch": "main"},
        "issue": {"number": 7, "title": "bug"},
    }
    task = receiver._extract(payload)
    assert task is not None
    assert task["repo_full"] == "duyet/infra"
    assert task["number"] == 7
    assert task["instruction"] == "please handle this"
    # sandbox name must be RFC1123-valid and preserve the item number
    assert task["sandbox_name"].startswith("fix-duyet-infra-7-")
    assert task["sandbox_name"][-1].isalnum()


def test_extract_skips_non_trigger_comment(monkeypatch):
    monkeypatch.setattr(receiver, "ALLOWED", set())
    monkeypatch.setattr(receiver, "TRIGGER", "/fix")
    payload = {
        "action": "created",
        "sender": {"login": "duyet"},
        "comment": {"body": "just a normal comment"},
        "repository": {"full_name": "duyet/infra"},
        "issue": {"number": 7},
    }
    assert receiver._extract(payload) is None


def test_extract_skips_disallowed_user(monkeypatch):
    monkeypatch.setattr(receiver, "ALLOWED", {"duyet"})
    monkeypatch.setattr(receiver, "TRIGGER", "/fix")
    payload = {
        "action": "created",
        "sender": {"login": "stranger"},
        "comment": {"body": "/fix do it"},
        "repository": {"full_name": "duyet/infra"},
        "issue": {"number": 7},
    }
    assert receiver._extract(payload) is None
