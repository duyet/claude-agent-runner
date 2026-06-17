"""GitLab poller for pull mode.

Periodically checks configured GitLab projects for newly opened issues and/or
merge requests and creates Sandbox CRs, mirroring the GitHub poller.

GitLab auth is a static token (`GITLAB_TOKEN`); self-hosted instances are
supported via `GITLAB_URL` (default `https://gitlab.com`). The `gitlab`
(python-gitlab) library is imported lazily inside the methods that need it, so
this module can always be imported even when python-gitlab isn't installed.
"""
import asyncio
import os
import time
from datetime import datetime

from . import k8shelper
from .common import get_logger
from .poller import LRUCache, ProcessedItem
from .state import StateManager, Trigger

log = get_logger("gl_poller")

# Configuration from environment
ENABLED = os.environ.get("PULL_MODE_GITLAB_ENABLED", "false").lower() == "true"
INTERVAL_MINUTES = int(os.environ.get("PULL_MODE_INTERVAL_MINUTES", "5"))
PROJECTS = [
    p.strip() for p in os.environ.get("PULL_MODE_GITLAB_PROJECTS", "").split(",") if p.strip()
]
EVENT_TYPES = [
    e.strip().lower()
    for e in os.environ.get("PULL_MODE_GITLAB_EVENTS", "issues").split(",")
    if e.strip()
]

ALLOWED_USERS = {u.strip().lower() for u in os.environ.get("ALLOWED_USERS", "").split(",") if u.strip()}

# GitLab API configuration
GITLAB_URL = os.environ.get("GITLAB_URL", "https://gitlab.com")
GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN")

# Safety limits per poll cycle
MAX_ISSUES_PER_CYCLE = 50
MAX_MRS_PER_CYCLE = 20


class GitLabPoller:
    """Polls GitLab for issues/MRs and creates Sandbox CRs using python-gitlab.

    Mirrors GitHubPoller but uses a static-token GitLab client and distinct
    cache-key prefixes (``gl_issue:`` / ``gl_mr:``) so it can share the dedup
    state with the GitHub poller without key collisions.
    """

    def __init__(self):
        self._state_mgr: StateManager | None = None
        self.processed = LRUCache()
        self.gitlab = None  # lazily built python-gitlab client
        self.stats: dict[str, int] = {
            "issues_fetched": 0,
            "mrs_fetched": 0,
            "items_skipped": 0,
            "sandboxes_created": 0,
            "errors": 0,
        }

    @property
    def state_mgr(self) -> StateManager:
        """Lazy initialization of StateManager."""
        if self._state_mgr is None:
            self._state_mgr = StateManager()
        return self._state_mgr

    def _is_allowed(self, sender: str) -> bool:
        """Check if sender is in the allowed users list (empty = allow all)."""
        if not ALLOWED_USERS:
            return True
        low = sender.lower()
        return low in ALLOWED_USERS or low.removesuffix("[bot]") in ALLOWED_USERS

    def _build_client(self):
        """Build a python-gitlab client. Imported lazily so module import never fails."""
        import gitlab  # lazy import

        return gitlab.Gitlab(GITLAB_URL, private_token=GITLAB_TOKEN)

    def _ensure_client(self) -> None:
        """Ensure the GitLab client is initialized."""
        if self.gitlab is None:
            self.gitlab = self._build_client()
            log.info(f"Initialized GitLab client for {GITLAB_URL}")

    async def start(self) -> None:
        """Start the poller background task."""
        if not ENABLED:
            log.info("GitLab pull mode disabled (PULL_MODE_GITLAB_ENABLED=false)")
            return

        if not PROJECTS:
            log.warning("GitLab pull mode enabled but no projects configured (PULL_MODE_GITLAB_PROJECTS empty)")
            return

        log.info(f"Starting GitLab poller: interval={INTERVAL_MINUTES}m, projects={PROJECTS}, events={EVENT_TYPES}")

        # Load previously processed items from state
        await self._load_processed()

        # Initialize GitLab client
        try:
            self._ensure_client()
        except Exception as e:
            log.error(f"Failed to initialize GitLab client: {e}")
            return

        # Start polling loop
        cycle = 0
        while True:
            cycle += 1
            started = time.time()
            try:
                await self._poll_once(cycle)
            except Exception as e:
                log.error(f"GitLab poll cycle #{cycle} failed: {e}")

            elapsed = time.time() - started
            wait_time = INTERVAL_MINUTES * 60
            log.info(
                f"GitLab cycle #{cycle} done in {elapsed:.1f}s | "
                f"created={self.stats['sandboxes_created']} "
                f"skipped={self.stats['items_skipped']} "
                f"errors={self.stats['errors']} | "
                f"next poll in {wait_time/60:.1f}m"
            )
            await asyncio.sleep(wait_time)

    async def _poll_once(self, cycle: int = 0) -> None:
        """Poll all configured projects once."""
        for k in self.stats:
            self.stats[k] = 0

        log.info(
            f"GitLab cycle #{cycle}: polling {len(PROJECTS)} projects {PROJECTS} | "
            f"events={EVENT_TYPES} | cache={len(self.processed.cache)} tracked items"
        )

        for project_path in PROJECTS:
            try:
                await self._poll_project(project_path)
            except Exception as e:
                self.stats["errors"] += 1
                log.error(f"Failed to poll {project_path}: {e}")

    async def _poll_project(self, project_path: str) -> None:
        """Poll a single GitLab project for events."""
        project_started = time.time()
        self._ensure_client()

        if not self.gitlab:
            log.warning("GitLab client not initialized")
            return

        try:
            project = self.gitlab.projects.get(project_path)
        except Exception as e:
            self.stats["errors"] += 1
            log.error(f"Failed to get project {project_path}: {e}")
            return

        # Key dedup on the canonical path GitLab returns (also what gets
        # persisted), so reload-from-state keys match the keys computed while
        # polling even when the configured PULL_MODE_GITLAB_PROJECTS entry uses
        # different casing or a numeric ID.
        repo_full = getattr(project, "path_with_namespace", project_path)
        log.info(f"Polling {repo_full}")

        if "issues" in EVENT_TYPES:
            await self._check_items(repo_full, project, is_mr=False)

        if "mrs" in EVENT_TYPES:
            await self._check_items(repo_full, project, is_mr=True)

        log.info(f"Polled {repo_full} in {time.time() - project_started:.1f}s")

    async def _check_items(self, repo_full: str, project, is_mr: bool) -> None:
        """Check for newly opened issues or merge requests (shared scan loop)."""
        prefix = "gl_mr" if is_mr else "gl_issue"
        kind = "MR" if is_mr else "issue"
        limit = MAX_MRS_PER_CYCLE if is_mr else MAX_ISSUES_PER_CYCLE
        manager = project.mergerequests if is_mr else project.issues
        stat_key = "mrs_fetched" if is_mr else "issues_fetched"

        try:
            items = manager.list(
                state="opened", order_by="created_at", sort="desc", get_all=False
            )
        except Exception as e:
            self.stats["errors"] += 1
            log.error(f"GitLab API error fetching {kind}s for {repo_full}: {e}")
            return

        scanned = 0
        processed_count = 0
        for item in items:
            scanned += 1
            self.stats[stat_key] += 1

            key = f"{prefix}:{repo_full}:{item.iid}"
            if self.processed.get(key):
                log.debug(f"Stopping at {kind} {item.iid} (already processed)")
                break

            await self._process_item(repo_full, project, item, is_mr=is_mr)
            processed_count += 1

            if processed_count >= limit:
                log.warning(f"Hit safety limit of {limit} {kind}s per poll cycle")
                break

        log.info(
            f"{kind}s from {repo_full}: scanned={scanned} new_processed={processed_count}"
        )

    async def _process_item(self, repo_full: str, project, item, is_mr: bool) -> None:
        """Process a new issue or merge request."""
        iid = item.iid
        prefix = "gl_mr" if is_mr else "gl_issue"
        item_type = "mr" if is_mr else "issue"
        kind = "MR" if is_mr else "issue"
        key = f"{prefix}:{repo_full}:{iid}"

        author = (item.author or {}).get("username", "") if getattr(item, "author", None) else ""
        if not self._is_allowed(author):
            self.stats["items_skipped"] += 1
            log.info(f"Skipping {kind} {iid} by disallowed user {author}")
            return

        title = item.title or ""
        log.info(f"Found new {kind}: {repo_full}!{iid} by {author} - {title[:50]}")

        reason = f"new {kind} opened by {author}"

        ts = int(time.time())
        safe = "".join(c.lower() if c.isalnum() else "-" for c in repo_full).strip("-")
        task = {
            "sandbox_name": f"fix-{safe}-{iid}-{ts}"[:58],
            "repo_full": repo_full,
            "clone_url": project.http_url_to_repo,
            "default_branch": project.default_branch,
            "number": iid,
            "title": title,
            "body": getattr(item, "description", "") or "",
            "instruction": "",
            "sender": author,
            "is_pr": is_mr,
            "reason": reason,
            "provider": "gitlab",
        }

        try:
            sandbox_name = k8shelper.create_sandbox(task)
            self.processed.put(key, ProcessedItem(item_type, repo_full, iid, time.time(), sandbox_name))
            self._persist_processed(item_type, project, iid, author, reason, sandbox_name)
            self.stats["sandboxes_created"] += 1
            log.info(f"Created sandbox {sandbox_name} for {kind} {repo_full}!{iid}")
        except Exception as e:
            self.stats["errors"] += 1
            log.error(f"Failed to create sandbox for {kind} {iid}: {e}")

    def _persist_processed(
        self, item_type: str, project, iid: int, author: str, reason: str, sandbox_name: str,
    ) -> None:
        """Persist a processed item to the shared state so dedup survives restarts."""
        try:
            self.state_mgr.create_run(
                sandbox_name=sandbox_name,
                repo_full=getattr(project, "path_with_namespace", ""),
                repo_url=getattr(project, "http_url_to_repo", ""),
                branch=getattr(project, "default_branch", ""),
                trigger=Trigger(
                    type=f"gitlab_{item_type}", user=author,
                    issue_number=iid, reason=reason,
                ),
                model="",
                max_turns=0,
            )
        except Exception as e:
            log.warning(f"Failed to persist processed {item_type} {iid} to state: {e}")

    async def _load_processed(self) -> None:
        """Load processed items from the shared state manager (survives restarts)."""
        try:
            runs = self.state_mgr.list_runs(limit=1000)
            for run in runs:
                trigger = run.trigger
                if not trigger or not run.repo_full:
                    continue
                # Only GitLab triggers belong in this poller's cache
                if not trigger.type.startswith("gitlab_"):
                    continue
                # trigger.type is "gitlab_issue" / "gitlab_mr"; map to cache key prefix
                item_type = "mr" if trigger.type.endswith("mr") else "issue"
                prefix = "gl_mr" if item_type == "mr" else "gl_issue"
                number = trigger.issue_number
                if not number:
                    continue

                try:
                    ts = datetime.fromisoformat(run.started_at).timestamp()
                except (ValueError, TypeError):
                    ts = time.time()

                key = f"{prefix}:{run.repo_full}:{number}"
                item = ProcessedItem(item_type, run.repo_full, number, ts, run.sandbox_name)
                if not item.is_expired():
                    self.processed.put(key, item)

            log.info(f"Loaded {len(self.processed.cache)} GitLab processed items from state")

        except Exception as e:
            log.warning(f"Failed to load GitLab processed items from state: {e}")


# Global poller instance
gl_poller = GitLabPoller()


async def start_gl_poller():
    """Start the GitLab poller in the background."""
    if ENABLED:
        asyncio.create_task(gl_poller.start())
