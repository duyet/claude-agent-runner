"""GitHub poller for pull mode. Periodically checks repos for issues/PRs and creates Sandbox CRs."""
import asyncio
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from github import Github, GithubException
from github.Issue import Issue as PyGithubIssue
from github.PullRequest import PullRequest as PyGithubPR

from . import gh_token, k8shelper
from .common import get_logger
from .state import StateManager, Trigger

log = get_logger("poller")

# Configuration from environment
ENABLED = os.environ.get("PULL_MODE_ENABLED", "false").lower() == "true"
INTERVAL_MINUTES = int(os.environ.get("PULL_MODE_INTERVAL_MINUTES", "5"))
REPOS = [r.strip() for r in os.environ.get("PULL_MODE_REPOS", "").split(",") if r.strip()]
EVENT_TYPES = [e.strip().lower() for e in os.environ.get("PULL_MODE_EVENTS", "issues").split(",") if e.strip()]

ALLOWED_USERS = {u.strip().lower() for u in os.environ.get("ALLOWED_USERS", "").split(",") if u.strip()}

# GitHub API configuration
GH_APP_ID = os.environ.get("GH_APP_ID")
GH_PRIVATE_KEY = os.environ.get("GH_PRIVATE_KEY")
GH_TOKEN = os.environ.get("GH_TOKEN")

# Rate limiting and caching.
# TTL matches state retention so dedup survives receiver restarts (the in-memory cache is
# repopulated from persisted runs on startup); the LRU bound caps memory regardless of TTL.
PROCESSED_CACHE_TTL = int(os.environ.get("STATE_RETENTION_DAYS", "30")) * 86400
MAX_PROCESSED_ITEMS = 1000  # Maximum items to track in memory


@dataclass
class ProcessedItem:
    """Track processed items to avoid duplicates."""
    item_type: str  # "issue" or "pr"
    repo_full: str
    number: int
    timestamp: float = field(default_factory=time.time)
    sandbox_name: str = ""

    def key(self) -> str:
        """Unique key for this item."""
        return f"{self.item_type}:{self.repo_full}:{self.number}"

    def is_expired(self) -> bool:
        """Check if this item has expired (for cache cleanup)."""
        return time.time() - self.timestamp > PROCESSED_CACHE_TTL


class LRUCache:
    """Simple LRU cache with automatic expiration."""

    def __init__(self, max_size: int = MAX_PROCESSED_ITEMS):
        self.cache: OrderedDict[str, ProcessedItem] = OrderedDict()
        self.max_size = max_size

    def get(self, key: str) -> ProcessedItem | None:
        """Get item from cache."""
        if key not in self.cache:
            return None

        item = self.cache[key]
        if item.is_expired():
            del self.cache[key]
            return None

        # Move to end (most recently used)
        self.cache.move_to_end(key)
        return item

    def put(self, key: str, item: ProcessedItem) -> None:
        """Put item in cache."""
        # Remove expired items first
        self._cleanup_expired()

        # Add new item
        self.cache[key] = item
        self.cache.move_to_end(key)

        # Evict oldest if over limit
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

    def _cleanup_expired(self) -> None:
        """Remove expired items from cache."""
        expired_keys = [
            k for k, v in self.cache.items()
            if v.is_expired()
        ]
        for key in expired_keys:
            del self.cache[key]


class GitHubPoller:
    """Polls GitHub for issues/PRs and creates Sandbox CRs using PyGithub.

    Optimized to minimize GitHub API requests:
    - Uses since parameter to only fetch new/updated items
    - Caches processed items to avoid duplicates
    - Implements rate limit awareness
    - Uses conditional requests when available
    """

    def __init__(self):
        self._state_mgr: StateManager | None = None
        self.processed = LRUCache()
        self.github: Github | None = None
        self._gh_token: str | None = None  # current App installation token (for rotation)
        self.last_poll_times: dict[str, float] = {}  # repo_full -> timestamp
        self.rate_limit_reset: float = 0
        self.remaining_requests: int = 5000  # GitHub default for authenticated
        # Per-cycle counters, reset at the start of each _poll_once
        self.stats: dict[str, int] = {
            "issues_fetched": 0,
            "prs_fetched": 0,
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

    async def start(self) -> None:
        """Start the poller background task."""
        if not ENABLED:
            log.info("Pull mode disabled (PULL_MODE_ENABLED=false)")
            return

        if not REPOS:
            log.warning("Pull mode enabled but no repos configured (PULL_MODE_REPOS empty)")
            return

        log.info(f"Starting poller: interval={INTERVAL_MINUTES}m, repos={REPOS}, events={EVENT_TYPES}")

        # Load previously processed items from state
        await self._load_processed()

        # Initialize GitHub client
        self._ensure_github_client()

        # Start polling loop
        cycle = 0
        while True:
            cycle += 1
            started = time.time()
            try:
                await self._poll_once(cycle)
            except Exception as e:
                log.error(f"Poll cycle #{cycle} failed: {e}")

            elapsed = time.time() - started
            # Wait for next interval (or shorter if rate limited)
            wait_time = self._get_wait_time()
            log.info(
                f"Cycle #{cycle} done in {elapsed:.1f}s | "
                f"created={self.stats['sandboxes_created']} "
                f"skipped={self.stats['items_skipped']} "
                f"errors={self.stats['errors']} | "
                f"rate_limit={self.remaining_requests} remaining | "
                f"next poll in {wait_time/60:.1f}m"
            )
            await asyncio.sleep(wait_time)

    def _get_wait_time(self) -> float:
        """Calculate wait time considering rate limits."""
        # If we're rate limited, wait until reset
        if self.remaining_requests < 10 and time.time() < self.rate_limit_reset:
            wait_until_reset = self.rate_limit_reset - time.time()
            if wait_until_reset > 0:
                log.warning(f"Near rate limit, waiting {wait_until_reset/60:.1f} minutes for reset")
                return wait_until_reset

        # Normal interval
        return INTERVAL_MINUTES * 60

    async def _poll_once(self, cycle: int = 0) -> None:
        """Poll all configured repos once."""
        # Reset per-cycle counters
        for k in self.stats:
            self.stats[k] = 0

        log.info(
            f"Cycle #{cycle}: polling {len(REPOS)} repos {REPOS} | "
            f"events={EVENT_TYPES} | cache={len(self.processed.cache)} tracked items"
        )

        for repo in REPOS:
            try:
                await self._poll_repo(repo)
            except Exception as e:
                self.stats["errors"] += 1
                log.error(f"Failed to poll {repo}: {e}")

    async def _poll_repo(self, repo_full: str) -> None:
        """Poll a single repo for events."""
        repo_started = time.time()
        # Refresh auth before each poll. App installation tokens expire after ~1h,
        # so a client built once at startup eventually returns 401 Bad credentials.
        self._refresh_github_client(repo_full)

        if not self.github:
            log.warning("GitHub client not initialized")
            return

        try:
            repo = self.github.get_repo(repo_full)
        except GithubException as e:
            self.stats["errors"] += 1
            log.error(f"Failed to get repo {repo_full}: {e}")
            return

        # Update rate limit info from response headers
        self._update_rate_limit_info()

        # Get last poll time for this repo
        last_poll = self.last_poll_times.get(repo_full, 0)
        since_time = datetime.fromtimestamp(last_poll) if last_poll > 0 else None
        since_desc = since_time.isoformat() if since_time else "beginning (first poll)"
        log.info(f"Polling {repo_full} (since {since_desc})")

        issues_before = self.stats["issues_fetched"]
        prs_before = self.stats["prs_fetched"]

        # Check for new issues
        if "issues" in EVENT_TYPES:
            await self._check_new_issues(repo_full, repo, since_time)

        # Check pull requests
        if "prs" in EVENT_TYPES:
            await self._check_pull_requests(repo_full, repo, since_time)

        # Update last poll time
        self.last_poll_times[repo_full] = time.time()

        log.info(
            f"Polled {repo_full} in {time.time() - repo_started:.1f}s | "
            f"issues_scanned={self.stats['issues_fetched'] - issues_before} "
            f"prs_scanned={self.stats['prs_fetched'] - prs_before}"
        )

    async def _check_new_issues(self, repo_full: str, repo, since_time: datetime | None) -> None:
        """Check for newly opened issues since last poll."""
        try:
            # Build query parameters - only get issues created since last poll
            kwargs = {"state": "open", "sort": "created", "direction": "desc"}

            # Use since parameter if we have a last poll time
            if since_time:
                # Only fetch issues created after our last poll
                cutoff = since_time + timedelta(seconds=-60)  # 1 minute buffer to avoid missing edge cases
                kwargs["since"] = cutoff  # PyGithub expects datetime, not ISO string
                log.debug(f"Fetching issues created since {cutoff.isoformat()}")
            else:
                log.debug("Fetching all open issues (first poll)")

            # Paginate through issues (PyGithub handles this automatically)
            issues = repo.get_issues(**kwargs)

            scanned = 0
            skipped_prs = 0
            processed_count = 0
            for issue in issues:
                scanned += 1
                self.stats["issues_fetched"] += 1
                # Skip pull requests (they're handled separately)
                if issue.pull_request is not None:
                    skipped_prs += 1
                    continue

                # Stop if we've seen this issue before
                key = f"issue:{repo_full}:{issue.number}"
                if self.processed.get(key):
                    log.debug(f"Stopping at issue {issue.number} (already processed)")
                    break

                await self._process_new_issue(repo_full, repo, issue)
                processed_count += 1

                # Safety limit to avoid processing too many issues at once
                if processed_count >= 50:
                    log.warning("Hit safety limit of 50 issues per poll cycle")
                    break

            log.info(
                f"Issues from {repo_full}: scanned={scanned} "
                f"skipped_prs={skipped_prs} new_processed={processed_count}"
            )

        except GithubException as e:
            self.stats["errors"] += 1
            log.error(f"GitHub API error fetching new issues: {e}")

    async def _process_new_issue(self, repo_full: str, repo, issue: PyGithubIssue) -> None:
        """Process a new issue (all issues, not just labeled)."""
        number = issue.number
        key = f"issue:{repo_full}:{number}"

        # Check if already in cache
        if self.processed.get(key):
            log.debug(f"Skipping already processed issue {number}")
            return

        # Check if user is allowed
        sender = issue.user.login if issue.user else ""
        if ALLOWED_USERS and not self._is_allowed(sender):
            self.stats["items_skipped"] += 1
            log.info(f"Skipping issue {number} by disallowed user {sender}")
            return

        log.info(f"Found new issue: {repo_full}#{number} by {sender} - {issue.title[:50]}")

        # Create task
        ts = int(time.time())
        safe = "".join(c.lower() if c.isalnum() else "-" for c in repo_full).strip("-")
        task = {
            "sandbox_name": f"fix-{safe}-{number}-{ts}"[:58],
            "repo_full": repo_full,
            "clone_url": repo.clone_url,
            "default_branch": repo.default_branch,
            "number": number,
            "title": issue.title,
            "body": issue.body or "",
            "instruction": "",
            "sender": sender,
            "is_pr": False,
            "reason": f"new issue opened by {sender}",
        }

        # Create Sandbox CR
        try:
            sandbox_name = k8shelper.create_sandbox(task)
            self.processed.put(key, ProcessedItem("issue", repo_full, number, time.time(), sandbox_name))
            self._persist_processed("issue", repo_full, repo, number, sender, task["reason"], sandbox_name)
            self.stats["sandboxes_created"] += 1
            log.info(f"Created sandbox {sandbox_name} for new issue {repo_full}#{number}")
        except Exception as e:
            self.stats["errors"] += 1
            log.error(f"Failed to create sandbox for issue {number}: {e}")

    async def _check_pull_requests(self, repo_full: str, repo, since_time: datetime | None) -> None:
        """Check for recent pull requests since last poll."""
        try:
            kwargs = {"state": "open", "sort": "created", "direction": "desc"}

            cutoff = since_time + timedelta(seconds=-60) if since_time else None
            # get_pulls() has no `since` param — filter by created_at manually
            prs = repo.get_pulls(**kwargs)

            scanned = 0
            processed_count = 0
            for pr in prs:
                scanned += 1
                self.stats["prs_fetched"] += 1
                # Stop if PR was created before our cutoff
                if cutoff and pr.created_at.replace(tzinfo=None) < cutoff:
                    break

                # Stop if we've seen this PR before
                key = f"pr:{repo_full}:{pr.number}"
                if self.processed.get(key):
                    log.debug(f"Stopping at PR {pr.number} (already processed)")
                    break

                await self._process_pull_request(repo_full, pr)
                processed_count += 1

                if processed_count >= 20:
                    log.warning("Hit safety limit of 20 PRs per poll cycle")
                    break

            log.info(
                f"PRs from {repo_full}: scanned={scanned} new_processed={processed_count}"
            )

        except GithubException as e:
            self.stats["errors"] += 1
            log.error(f"GitHub API error fetching PRs: {e}")

    async def _process_pull_request(self, repo_full: str, pr: PyGithubPR) -> None:
        """Process a pull request."""
        number = pr.number
        key = f"pr:{repo_full}:{number}"

        # Check if already in cache
        if self.processed.get(key):
            log.debug(f"Skipping already processed PR {number}")
            return

        # Check if user is allowed
        sender = pr.user.login if pr.user else ""
        if ALLOWED_USERS and not self._is_allowed(sender):
            self.stats["items_skipped"] += 1
            log.info(f"Skipping PR {number} by disallowed user {sender}")
            return

        log.info(f"Found new PR: {repo_full}#{number} by {sender} - {pr.title[:50]}")

        # Create task
        ts = int(time.time())
        safe = "".join(c.lower() if c.isalnum() else "-" for c in repo_full).strip("-")
        task = {
            "sandbox_name": f"fix-{safe}-{number}-{ts}"[:58],
            "repo_full": repo_full,
            "clone_url": pr.base.repo.clone_url,
            "default_branch": pr.base.repo.default_branch,
            "number": number,
            "title": pr.title,
            "body": pr.body or "",
            "instruction": "",
            "sender": sender,
            "is_pr": True,
            "reason": f"PR opened by {sender}",
        }

        # Create Sandbox CR
        try:
            sandbox_name = k8shelper.create_sandbox(task)
            self.processed.put(key, ProcessedItem("pr", repo_full, number, time.time(), sandbox_name))
            self._persist_processed("pr", repo_full, pr.base.repo, number, sender, task["reason"], sandbox_name)
            self.stats["sandboxes_created"] += 1
            log.info(f"Created sandbox {sandbox_name} for PR {repo_full}#{number}")
        except Exception as e:
            self.stats["errors"] += 1
            log.error(f"Failed to create sandbox for PR {number}: {e}")

    def _is_allowed(self, sender: str) -> bool:
        """Check if sender is in allowed users list."""
        if not ALLOWED_USERS:
            return True
        base = sender.lower().removesuffix("[bot]")
        return sender.lower() in ALLOWED_USERS or base in ALLOWED_USERS

    def _update_rate_limit_info(self) -> None:
        """Update rate limit information from GitHub client."""
        if not self.github:
            return

        try:
            # PyGithub stores rate limit info from the last response
            rate_limit = self.github.get_rate_limit()
            core = getattr(rate_limit, "core", None)
            if core:
                self.remaining_requests = core.remaining
                self.rate_limit_reset = core.reset.timestamp()
                used = getattr(core, "limit", 0) - self.remaining_requests
                log.info(
                    f"Rate limit: {self.remaining_requests}/{getattr(core, 'limit', '?')} remaining "
                    f"({used} used), resets at {datetime.fromtimestamp(self.rate_limit_reset)}"
                )
        except Exception as e:
            log.debug(f"Failed to get rate limit info: {e}")

    def _ensure_github_client(self) -> None:
        """Ensure GitHub client is initialized with valid authentication."""
        # App auth is repo-scoped and token-expiry-aware; defer to per-poll refresh.
        if GH_APP_ID and GH_PRIVATE_KEY:
            return

        if self.github is not None:
            return

        # Fall back to personal access token
        if GH_TOKEN:
            self.github = Github(GH_TOKEN)
            log.info("Initialized GitHub client with personal access token")
            return

        # No authentication - will have limited rate limits
        self.github = Github()
        log.warning("Initialized GitHub client without authentication (limited rate limits)")

    def _refresh_github_client(self, repo_full: str) -> None:
        """Rebuild the GitHub client with a fresh App installation token when needed.

        gh_token.token_for caches per-repo and refreshes 5 min before expiry, so the
        returned token is always valid. We only rebuild the client when the token rotates.
        """
        if not (GH_APP_ID and GH_PRIVATE_KEY):
            return  # PAT / unauthenticated client built once in _ensure_github_client

        try:
            token = gh_token.token_for(repo_full)
        except Exception as e:
            log.error(f"Failed to mint GitHub App token for {repo_full}: {e}")
            return

        if token != self._gh_token:
            self.github = Github(token)
            self._gh_token = token
            log.info("Refreshed GitHub client with App installation token")

    def _persist_processed(
        self, item_type: str, repo_full: str, repo, number: int, sender: str,
        reason: str, sandbox_name: str,
    ) -> None:
        """Persist a processed item to the shared state so dedup survives restarts.

        Without this, a receiver restart wipes the in-memory cache and the first poll
        re-creates a sandbox for every open issue/PR.
        """
        try:
            self.state_mgr.create_run(
                sandbox_name=sandbox_name,
                repo_full=repo_full,
                repo_url=getattr(repo, "clone_url", ""),
                branch=getattr(repo, "default_branch", ""),
                trigger=Trigger(
                    type=f"github_{item_type}", user=sender,
                    issue_number=number, reason=reason,
                ),
                model="",
                max_turns=0,
            )
        except Exception as e:
            log.warning(f"Failed to persist processed {item_type} {number} to state: {e}")

    async def _load_processed(self) -> None:
        """Load processed items from the shared state manager (survives restarts)."""
        try:
            runs = self.state_mgr.list_runs(limit=1000)
            for run in runs:
                trigger = run.trigger
                if not trigger or not run.repo_full:
                    continue
                # trigger.type is "github_issue" / "github_pr"; map back to cache key prefix
                item_type = "pr" if trigger.type.endswith("pr") else "issue"
                number = trigger.issue_number
                if not number:
                    continue

                # Convert ISO started_at to epoch for ProcessedItem TTL math
                try:
                    ts = datetime.fromisoformat(run.started_at).timestamp()
                except (ValueError, TypeError):
                    ts = time.time()

                key = f"{item_type}:{run.repo_full}:{number}"
                item = ProcessedItem(item_type, run.repo_full, number, ts, run.sandbox_name)
                if not item.is_expired():
                    self.processed.put(key, item)

            log.info(f"Loaded {len(self.processed.cache)} processed items from state")

        except Exception as e:
            log.warning(f"Failed to load processed items from state: {e}")


# Global poller instance
poller = GitHubPoller()


async def start_poller():
    """Start the poller in the background."""
    if ENABLED:
        asyncio.create_task(poller.start())
