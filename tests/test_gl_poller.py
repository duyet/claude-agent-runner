"""Tests for the GitLab poller (pull mode).

These tests run fully offline: the python-gitlab client is replaced with a
fake, and Sandbox creation / state persistence are stubbed or pointed at a
tmp_path file backend.
"""
import asyncio

from app import gl_poller as gl_mod
from app.gl_poller import GitLabPoller


class FakeUser:
    def __init__(self, username):
        self.username = username


class FakeItem:
    """Stand-in for a python-gitlab Issue / MergeRequest object."""

    def __init__(self, iid, title, description, author):
        self.iid = iid
        self.title = title
        self.description = description
        # python-gitlab exposes author as a dict
        self.author = {"username": author}


class FakeProject:
    def __init__(self, path, issues=None, mrs=None):
        self.path_with_namespace = path
        self.default_branch = "main"
        self.http_url_to_repo = f"https://gitlab.com/{path}.git"
        self._issues = issues or []
        self._mrs = mrs or []
        self.issues = self._Manager(self._issues)
        self.mergerequests = self._Manager(self._mrs)

    class _Manager:
        def __init__(self, items):
            self._items = items

        def list(self, **kwargs):
            return list(self._items)


class FakeGitlab:
    def __init__(self, projects):
        self._projects = projects
        self.projects = self._ProjectsManager(projects)

    class _ProjectsManager:
        def __init__(self, projects):
            self._projects = projects

        def get(self, path):
            return self._projects[path]


def _patch_common(monkeypatch, project_path, issues=None, mrs=None):
    """Wire a poller up with a fake GitLab client and a fake sandbox creator."""
    project = FakeProject(project_path, issues=issues, mrs=mrs)
    fake_gl = FakeGitlab({project_path: project})

    created = []

    def fake_create_sandbox(task):
        name = f"fix-{task['number']}"
        created.append(task)
        return name

    monkeypatch.setattr(gl_mod.k8shelper, "create_sandbox", fake_create_sandbox)

    p = GitLabPoller()
    # Inject the fake client so _ensure_client is a no-op
    p.gitlab = fake_gl
    p._build_client = lambda: fake_gl
    return p, project, created


def test_process_issue_then_dedup(monkeypatch):
    """An issue is processed once; a second pass is skipped via the cache."""
    monkeypatch.setattr(gl_mod, "EVENT_TYPES", ["issues"])
    monkeypatch.setattr(gl_mod, "ALLOWED_USERS", set())
    # Avoid touching real state persistence
    monkeypatch.setattr(GitLabPoller, "_persist_processed", lambda *a, **k: None)

    issue = FakeItem(7, "Fix the thing", "details", "duyet")
    p, project, created = _patch_common(monkeypatch, "group/proj", issues=[issue])

    asyncio.run(p._poll_project("group/proj"))
    assert len(created) == 1
    assert created[0]["provider"] == "gitlab"
    assert created[0]["repo_full"] == "group/proj"
    assert created[0]["number"] == 7
    assert created[0]["is_pr"] is False
    assert p.processed.get("gl_issue:group/proj:7") is not None

    # Second pass: already processed, no new sandbox
    asyncio.run(p._poll_project("group/proj"))
    assert len(created) == 1


def test_process_mr_sets_is_pr(monkeypatch):
    monkeypatch.setattr(gl_mod, "EVENT_TYPES", ["mrs"])
    monkeypatch.setattr(gl_mod, "ALLOWED_USERS", set())
    monkeypatch.setattr(GitLabPoller, "_persist_processed", lambda *a, **k: None)

    mr = FakeItem(3, "Add feature", "body", "duyet")
    p, project, created = _patch_common(monkeypatch, "group/proj", mrs=[mr])

    asyncio.run(p._poll_project("group/proj"))
    assert len(created) == 1
    assert created[0]["is_pr"] is True
    assert created[0]["provider"] == "gitlab"
    assert p.processed.get("gl_mr:group/proj:3") is not None


def test_disallowed_user_skipped(monkeypatch):
    monkeypatch.setattr(gl_mod, "EVENT_TYPES", ["issues"])
    monkeypatch.setattr(gl_mod, "ALLOWED_USERS", {"alice"})
    monkeypatch.setattr(GitLabPoller, "_persist_processed", lambda *a, **k: None)

    issue = FakeItem(1, "nope", "x", "mallory")
    p, project, created = _patch_common(monkeypatch, "group/proj", issues=[issue])

    asyncio.run(p._poll_project("group/proj"))
    assert created == []
    assert p.processed.get("gl_issue:group/proj:1") is None


def test_load_processed_round_trips_via_state(monkeypatch, tmp_path):
    """Dedup survives a restart: persisted GitLab runs repopulate the cache."""
    monkeypatch.setenv("STATE_MODE", "shared")
    monkeypatch.setenv("STATE_BACKEND", "file")
    monkeypatch.setenv("STATE_SHARED_PATH", str(tmp_path))

    from app.state import StateManager, Trigger

    writer = StateManager()
    writer.create_run(
        sandbox_name="fix-group-proj-2-1", repo_full="group/proj",
        repo_url="https://gitlab.com/group/proj.git", branch="main",
        trigger=Trigger(type="gitlab_issue", user="duyet", issue_number=2),
        model="", max_turns=0,
    )
    writer.create_run(
        sandbox_name="fix-group-proj-9-1", repo_full="group/proj",
        repo_url="https://gitlab.com/group/proj.git", branch="main",
        trigger=Trigger(type="gitlab_mr", user="duyet", issue_number=9),
        model="", max_turns=0,
    )
    # A GitHub run must NOT leak into the GitLab poller's cache.
    writer.create_run(
        sandbox_name="fix-duyet-infra-5-1", repo_full="duyet/infra",
        repo_url="https://github.com/duyet/infra.git", branch="main",
        trigger=Trigger(type="github_issue", user="duyet", issue_number=5),
        model="", max_turns=0,
    )

    p = GitLabPoller()
    asyncio.run(p._load_processed())
    assert p.processed.get("gl_issue:group/proj:2") is not None
    assert p.processed.get("gl_mr:group/proj:9") is not None
    # GitHub run filtered out
    assert p.processed.get("gl_issue:duyet/infra:5") is None
    assert p.processed.get("issue:duyet/infra:5") is None


def test_start_gl_poller_noop_when_disabled(monkeypatch):
    """start_gl_poller does nothing when disabled (no task scheduled)."""
    monkeypatch.setattr(gl_mod, "ENABLED", False)

    async def run():
        await gl_mod.start_gl_poller()

    asyncio.run(run())  # must not raise
