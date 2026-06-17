"""Tests for the GitLab webhook endpoint.

GitLab authenticates via a plain X-Gitlab-Token header (not an HMAC) and
dispatches on X-Gitlab-Event. Tasks are tagged provider="gitlab".
"""
import json

import pytest
from fastapi.testclient import TestClient

from app import receiver


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(receiver, "GITLAB_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setattr(receiver, "TRIGGER", "/fix")
    monkeypatch.setattr(receiver, "ISSUE_LABEL", "")
    monkeypatch.setattr(receiver, "ALLOWED", set())
    return TestClient(receiver.app)


@pytest.fixture
def captured(monkeypatch):
    """Patch create_sandbox to record the task and return a fake CR name."""
    seen = {}

    def fake_create(task):
        seen["task"] = task
        return "fix-fake-1-1"

    monkeypatch.setattr(receiver.k8shelper, "create_sandbox", fake_create)
    return seen


def _note_payload(*, note="/fix please", noteable_type="Issue", username="duyet"):
    noteable_key = "merge_request" if noteable_type == "MergeRequest" else "issue"
    return {
        "object_kind": "note",
        "object_attributes": {"note": note, "noteable_type": noteable_type},
        "user": {"username": username},
        "project": {
            "path_with_namespace": "group/repo",
            "default_branch": "main",
            "git_http_url": "https://gitlab.com/group/repo.git",
        },
        noteable_key: {"iid": 42, "title": "A thing", "description": "do it"},
    }


def _issue_payload(*, action="open", labels=("bug",), username="duyet"):
    return {
        "object_kind": "issue",
        "object_attributes": {
            "action": action,
            "iid": 7,
            "title": "An issue",
            "description": "fix me",
        },
        "labels": [{"title": t} for t in labels],
        "user": {"username": username},
        "project": {
            "path_with_namespace": "group/repo",
            "default_branch": "main",
            "git_http_url": "https://gitlab.com/group/repo.git",
        },
    }


def _post(client, payload, *, event, token="s3cret"):
    return client.post(
        "/webhook/gitlab",
        data=json.dumps(payload),
        headers={"X-Gitlab-Event": event, "X-Gitlab-Token": token},
    )


def test_wrong_token_401(client, captured):
    r = _post(client, _note_payload(), event="Note Hook", token="wrong")
    assert r.status_code == 401
    assert "task" not in captured


def test_missing_token_401(client, captured):
    r = client.post(
        "/webhook/gitlab",
        data=json.dumps(_note_payload()),
        headers={"X-Gitlab-Event": "Note Hook"},
    )
    assert r.status_code == 401
    assert "task" not in captured


def test_note_on_issue_with_trigger(client, captured):
    r = _post(client, _note_payload(noteable_type="Issue"), event="Note Hook")
    assert r.status_code == 202
    assert r.json() == {"accepted": True, "sandbox": "fix-fake-1-1"}
    task = captured["task"]
    assert task["provider"] == "gitlab"
    assert task["repo_full"] == "group/repo"
    assert task["number"] == 42
    assert task["is_pr"] is False
    assert task["clone_url"] == "https://gitlab.com/group/repo.git"
    assert task["instruction"] == "please"


def test_note_without_trigger_skipped(client, captured):
    r = _post(client, _note_payload(note="just a comment"), event="Note Hook")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "skipped": True}
    assert "task" not in captured


def test_note_on_merge_request_is_pr(client, captured):
    r = _post(client, _note_payload(noteable_type="MergeRequest"), event="Note Hook")
    assert r.status_code == 202
    assert captured["task"]["is_pr"] is True
    assert captured["task"]["number"] == 42


def test_note_disallowed_user_skipped(client, captured, monkeypatch):
    monkeypatch.setattr(receiver, "ALLOWED", {"someoneelse"})
    r = _post(client, _note_payload(username="duyet"), event="Note Hook")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "skipped": True}
    assert "task" not in captured


def test_issue_hook_with_label(client, captured, monkeypatch):
    monkeypatch.setattr(receiver, "ISSUE_LABEL", "bug")
    r = _post(client, _issue_payload(labels=("bug",)), event="Issue Hook")
    assert r.status_code == 202
    task = captured["task"]
    assert task["provider"] == "gitlab"
    assert task["number"] == 7
    assert task["is_pr"] is False


def test_issue_hook_without_label_skipped(client, captured, monkeypatch):
    monkeypatch.setattr(receiver, "ISSUE_LABEL", "bug")
    r = _post(client, _issue_payload(labels=("enhancement",)), event="Issue Hook")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "skipped": True}
    assert "task" not in captured


def test_issue_hook_not_open_skipped(client, captured, monkeypatch):
    monkeypatch.setattr(receiver, "ISSUE_LABEL", "bug")
    r = _post(client, _issue_payload(action="close", labels=("bug",)), event="Issue Hook")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "skipped": True}
    assert "task" not in captured


def test_issue_hook_no_label_configured_skipped(client, captured):
    # ISSUE_LABEL unset -> Issue Hook is ignored entirely
    r = _post(client, _issue_payload(labels=("bug",)), event="Issue Hook")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "skipped": True}
    assert "task" not in captured


def test_unknown_event_skipped(client, captured):
    r = _post(client, {}, event="Push Hook")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "skipped": True}
    assert "task" not in captured
