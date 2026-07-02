"""Tests for FileStorage correctness across the UTC day boundary.

Regression guard for #16: get/update/delete used *today's* UTC date to build
the file path, so a run created before midnight became unreachable the next day.
The path must be derived from the record's creation date, and lookups must
search across date directories.

Also guards #18: list_runs must sort before applying the limit.
"""
from datetime import datetime, timedelta

from app.state import AgentRun, FileStorage, RunStatus, Trigger


def _run(started_at: str, run_id: str = "run-abc", repo="duyet/infra") -> AgentRun:
    return AgentRun(
        run_id=run_id,
        sandbox_name="fix-duyet-infra-1-1",
        repo_full=repo,
        repo_url="https://github.com/duyet/infra.git",
        branch="main",
        trigger=Trigger(type="github_issue", user="duyet", issue_number=1),
        status=RunStatus.RUNNING,
        started_at=started_at,
    )


def test_save_get_across_day_boundary(tmp_path):
    storage = FileStorage(tmp_path)
    # Run created "yesterday": file lands under yesterday's date directory.
    yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()
    run = _run(yesterday)
    storage.save_run(run)

    # get_run must find it regardless of today's date (searches all date dirs).
    got = storage.get_run("run-abc")
    assert got is not None
    assert got.repo_full == "duyet/infra"
    assert got.started_at == yesterday


def test_update_then_get_across_day_boundary(tmp_path):
    storage = FileStorage(tmp_path)
    two_days_ago = (datetime.utcnow() - timedelta(days=2)).isoformat()
    run = _run(two_days_ago)
    storage.save_run(run)

    # Simulate an update: mutate + re-save (same started_at -> same dir).
    fetched = storage.get_run("run-abc")
    fetched.status = RunStatus.COMPLETED
    storage.save_run(fetched)

    again = storage.get_run("run-abc")
    assert again is not None
    assert again.status == RunStatus.COMPLETED


def test_delete_across_day_boundary(tmp_path):
    storage = FileStorage(tmp_path)
    old = (datetime.utcnow() - timedelta(days=3)).isoformat()
    storage.save_run(_run(old))
    assert storage.get_run("run-abc") is not None

    storage.delete_run("run-abc")
    assert storage.get_run("run-abc") is None


def test_list_runs_sorts_before_limit(tmp_path):
    storage = FileStorage(tmp_path)
    base = datetime.utcnow()
    # Save 5 runs with increasing started_at; the newest should survive limit=2.
    for i in range(5):
        ts = (base - timedelta(days=10) + timedelta(minutes=i)).isoformat()
        storage.save_run(_run(ts, run_id=f"run-{i}"))

    top = storage.list_runs(limit=2)
    assert len(top) == 2
    # Newest-first: run-4 then run-3.
    assert [r.run_id for r in top] == ["run-4", "run-3"]
