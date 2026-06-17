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
from .state import StateManager

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

# Rate limiting and caching
PROCESSED_CACHE_TTL = 3600  # Keep processed items for 1 hour
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
        while True:
            try:
                await self._poll_once()
            except Exception as e:
                log.error(f"Poll failed: {e}")

            # Wait for next interval (or shorter if rate limited)
            wait_time = self._get_wait_time()
            log.debug(f"Waiting {wait_time/60:.1f} minutes until next poll")
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

    async def _poll_once(self) -> None:
        """Poll all configured repos once."""
        log.info(f"Polling {len(REPOS)} repos...")

        for repo in REPOS:
            try:
                await self._poll_repo(repo)
            except Exception as e:
                log.error(f"Failed to poll {repo}: {e}")

    async def _poll_repo(self, repo_full: str) -> None:
        """Poll a single repo for events."""
        # Refresh auth before each poll. App installation tokens expire after ~1h,
        # so a client built once at startup eventually returns 401 Bad credentials.
        self._refresh_github_client(repo_full)

        if not self.github:
            log.warning("GitHub client not initialized")
            return

        try:
            repo = self.github.get_repo(repo_full)
        except GithubException as e:
            log.error(f"Failed to get repo {repo_full}: {e}")
            return

        # Update rate limit info from response headers
        self._update_rate_limit_info()

        # Get last poll time for this repo
        last_poll = self.last_poll_times.get(repo_full, 0)
        since_time = datetime.fromtimestamp(last_poll) if last_poll > 0 else None

        # Check for new issues
        if "issues" in EVENT_TYPES:
            await self._check_new_issues(repo_full, repo, since_time)

        # Check pull requests
        if "prs" in EVENT_TYPES:
            await self._check_pull_requests(repo_full, repo, since_time)

        # Update last poll time
        self.last_poll_times[repo_full] = time.time()

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

            processed_count = 0
            for issue in issues:
                # Skip pull requests (they're handled separately)
                if issue.pull_request is not None:
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

            if processed_count > 0:
                log.info(f"Processed {processed_count} new issues from {repo_full}")

        except GithubException as e:
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
            log.debug(f"Skipping issue {number} by disallowed user {sender}")
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
            log.info(f"Created sandbox {sandbox_name} for new issue {number}")
        except Exception as e:
            log.error(f"Failed to create sandbox for issue {number}: {e}")

    async def _check_pull_requests(self, repo_full: str, repo, since_time: datetime | None) -> None:
        """Check for recent pull requests since last poll."""
        try:
            kwargs = {"state": "open", "sort": "created", "direction": "desc"}

            cutoff = since_time + timedelta(seconds=-60) if since_time else None
            # get_pulls() has no `since` param — filter by created_at manually
            prs = repo.get_pulls(**kwargs)

            processed_count = 0
            for pr in prs:
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

            if processed_count > 0:
                log.info(f"Processed {processed_count} new PRs from {repo_full}")

        except GithubException as e:
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
            log.debug(f"Skipping PR {number} by disallowed user {sender}")
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
            log.info(f"Created sandbox {sandbox_name} for PR {number}")
        except Exception as e:
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
                log.debug(f"Rate limit: {self.remaining_requests} requests remaining, resets at {datetime.fromtimestamp(self.rate_limit_reset)}")
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

    async def _load_processed(self) -> None:
        """Load processed items from state manager."""
        try:
            runs = self.state_mgr.list_runs(limit=1000)
            for run in runs:
                # Reconstruct ProcessedItem from AgentRun
                if run.task_id:
                    try:
                        parts = run.task_id.split("-")
                        if len(parts) >= 3:
                            number = int(parts[-2]) if parts[-2].isdigit() else 0
                            repo_full = run.trigger_context.get("repo_full", "")
                            item_type = run.trigger_context.get("trigger_type", "issue")

                            key = f"{item_type}:{repo_full}:{number}"
                            item = ProcessedItem(
                                item_type, repo_full, number, run.created_at, run.sandbox_name
                            )
                            # Only add if not expired
                            if not item.is_expired():
                                self.processed.put(key, item)
                    except (ValueError, IndexError):
                        pass

            log.info(f"Loaded {len(self.processed.cache)} processed items from state")

        except Exception as e:
            log.warning(f"Failed to load processed items from state: {e}")


# Global poller instance
poller = GitHubPoller()


async def start_poller():
    """Start the poller in the background."""
    if ENABLED:
        asyncio.create_task(poller.start())
