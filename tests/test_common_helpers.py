"""Tests for make_sandbox_name (#20) and the SDK env blocklist (#13)."""
from app.agent import _build_sdk_env
from app.common import make_sandbox_name


def _valid_dns1123(name: str) -> bool:
    import re

    return bool(re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", name))


def test_sandbox_name_basic_shape():
    name = make_sandbox_name("duyet/infra", 7, 1719900000)
    assert name == "fix-duyet-infra-7-1719900000"
    assert _valid_dns1123(name)


def test_sandbox_name_never_ends_in_dash():
    # A repo whose sanitized form would otherwise leave a trailing dash.
    name = make_sandbox_name("Duyet/Infra_", 12, 1719900000)
    assert not name.endswith("-")
    assert _valid_dns1123(name)


def test_sandbox_name_preserves_timestamp_when_long():
    ts = 1719900000
    repo = "some-really-long-org-name/an-even-longer-repository-name-here"
    name = make_sandbox_name(repo, 4321, ts)
    assert len(name) <= 58
    assert name.endswith(f"-4321-{ts}")  # tail (number + ts) preserved intact
    assert _valid_dns1123(name)


def test_sandbox_name_distinct_repos_do_not_collide_when_hashed():
    ts = 1719900000
    a = make_sandbox_name("org-aaaaaaaaaaaaaaaaaaaa/repo-bbbbbbbbbbbbbbbbbbbb", 1, ts)
    b = make_sandbox_name("org-aaaaaaaaaaaaaaaaaaaa/repo-cccccccccccccccccccc", 1, ts)
    assert a != b
    assert _valid_dns1123(a) and _valid_dns1123(b)


def test_sdk_env_excludes_github_app_secrets():
    environ = {
        "ANTHROPIC_API_KEY": "sk-ant-123",
        "GH_TOKEN": "ghs_token",
        "GITHUB_TOKEN": "ghs_token",  # no relevant prefix but harmless to check
        "GH_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----",
        "GH_APP_ID": "1064078",
        "UNRELATED": "nope",
    }
    out = _build_sdk_env(environ)
    # Secrets must never be forwarded.
    assert "GH_PRIVATE_KEY" not in out
    assert "GH_APP_ID" not in out
    # Non-secret, prefixed vars are forwarded.
    assert out["ANTHROPIC_API_KEY"] == "sk-ant-123"
    assert out["GH_TOKEN"] == "ghs_token"
    # Unrelated vars are not forwarded.
    assert "UNRELATED" not in out


def test_sdk_env_skips_empty_values():
    out = _build_sdk_env({"ANTHROPIC_API_KEY": "", "CLAUDE_MAX_TURNS": "10"})
    assert "ANTHROPIC_API_KEY" not in out
    assert out["CLAUDE_MAX_TURNS"] == "10"
