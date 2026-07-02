"""Tests for gh_token.token_for input validation (#14).

A malformed repo_full must raise a clean ValueError instead of an opaque
unpacking error deep inside the token flow.
"""
import pytest

from app import gh_token


@pytest.mark.parametrize("bad", ["justowner", "", "/repo", "owner/", "/"])
def test_token_for_rejects_malformed_repo_full(monkeypatch, bad):
    monkeypatch.setenv("GH_APP_ID", "123")
    monkeypatch.setenv("GH_PRIVATE_KEY", "key")
    monkeypatch.setattr(gh_token, "_mint_jwt", lambda app_id, key: "jwt")
    # Should never reach the network — validation happens first.
    monkeypatch.setattr(
        gh_token, "_installation_id",
        lambda *a, **k: pytest.fail("should not reach installation lookup"),
    )
    gh_token._cache.clear()
    with pytest.raises(ValueError):
        gh_token.token_for(bad)


def test_git_remote_is_tokenized():
    assert gh_token.git_remote("duyet/infra", "tok") == (
        "https://x-access-token:tok@github.com/duyet/infra.git"
    )
