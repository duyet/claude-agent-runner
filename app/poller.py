"""GitHub poller for pull mode. Periodically checks repos for issues/PRs and creates Sandbox CRs."""
import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from github import Github, GithubException
from github.Issue import Issue as PyGithubIssue
from github.PullRequest import PullRequest as PyGithubPR

from . import k8shelper
from .common import get_logger
from .state import StateManager, AgentRun

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


class GitHubPoller:
    """Polls GitHub for issues/PRs and creates Sandbox CRs using PyGithub."""

    def __init__(self):
        self._state_mgr: StateManager | None = None
        self.processed: dict[str, ProcessedItem] = {}
        self.github: Github | None = None
        self._github_token_expires_at: float = 0

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

            # Wait for next interval
            await asyncio.sleep(INTERVAL_MINUTES * 60)

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
        if not self.github:
            log.warning("GitHub client not initialized")
            return

        try:
            repo = self.github.get_repo(repo_full)
        except GithubException as e:
            log.error(f"Failed to get repo {repo_full}: {e}")
            return

        # Check for new issues
        if "issues" in EVENT_TYPES:
            await self._check_new_issues(repo_full, repo)

        # Check pull requests
        if "prs" in EVENT_TYPES:
            await self._check_pull_requests(repo_full, repo)

    async def _check_new_issues(self, repo_full: str, repo) -> None:
        """Check for newly opened issues (all issues)."""
        try:
            # Get open issues, sorted by recently created
            issues = repo.get_issues(state="open", sort="created", direction="desc")

            for issue in issues:
                # Skip pull requests (they're handled separately)
                if issue.pull_request is not None:
                    continue

                await self._process_new_issue(repo_full, issue)

        except GithubException as e:
            log.error(f"GitHub API error fetching new issues: {e}")

    async def _process_new_issue(self, repo_full: str, issue: -> None:
        """Process a new issue (all issues, not just labeled)."""
        number = issue.number
        key = f"issue:{repo_full}:{number}"

        # Skip if already processed recently (within 1 hour)
        if key in self.processed:
            processed = self.processed[key]
            if time.time() - processed.timestamp < 3600:
                log.debug(f"Skipping recently processed issue {number}")
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
            self.processed[key] = ProcessedItem("issue", repo_full, number, time.time(), sandbox_name)
            log.info(f"Created sandbox {sandbox_name} for new issue {number}")
        except Exception as e:
            log.error(f"Failed to create sandbox for issue {number}: {e}")

    async def _check_pull_requests(self, repo_full: str, repo) -> None:
        """Check for recent pull requests."""
        try:
            # Get open PRs, sorted by recently created
            prs = repo.get_pulls(state="open", sort="created", direction="desc")

            for pr in prs:
                await self._process_pull_request(repo_full, pr)

        except GithubException as e:
            log.error(f"GitHub API error fetching PRs: {e}")

    async def _process_pull_request(self, repo_full: str, pr: PyGithubPR) -> None:
        """Process a pull request."""
        number = pr.number
        key = f"pr:{repo_full}:{number}"

        # Skip if already processed recently (within 1 hour)
        if key in self.processed:
            processed = self.processed[key]
            if time.time() - processed.timestamp < 3600:
                log.debug(f"Skipping recently processed PR {number}")
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
            self.processed[key] = ProcessedItem("pr", repo_full, number, time.time(), sandbox_name)
            log.info(f"Created sandbox {sandbox_name} for PR {number}")
        except Exception as e:
            log.error(f"Failed to create sandbox for PR {number}: {e}")

    def _is_allowed(self, sender: str) -> bool:
        """Check if sender is in allowed users list."""
        if not ALLOWED_USERS:
            return True
        base = sender.lower().removesuffix("[bot]")
        return sender.lower() in ALLOWED_USERS or base in ALLOWED_USERS

    def _ensure_github_client(self) -> None:
        """Ensure GitHub client is initialized with valid authentication."""
        if self.github is not None:
            return

        # Use GitHub App authentication if available
        if GH_APP_ID and GH_PRIVATE_KEY:
            try:
                from github import GithubIntegration
                import jwt

                # Generate JWT for GitHub App
                now = int(time.time())
                payload = {
                    "iat": now - 60,
                    "exp": now + 600,
                    "iss": int(GH_APP_ID),
                }
                jwt_token = jwt.encode(payload, GH_PRIVATE_KEY, algorithm="RS256")

                # Get installation token
                integration = GithubIntegration(jwt_token, GH_PRIVATE_KEY)
                installations = integration.get_installations()
                if installations:
                    installation_id = installations[0].id
                    token = integration.get_access_token(installation_id)
                    self.github = Github(token.token)
                    log.info("Initialized GitHub client with App authentication")
                    return
            except Exception as e:
                log.error(f"Failed to initialize GitHub App authentication: {e}")

        # Fall back to personal access token
        if GH_TOKEN:
            self.github = Github(GH_TOKEN)
            log.info("Initialized GitHub client with personal access token")
            return

        # No authentication - will have limited rate limits
        self.github = Github()
        log.warning("Initialized GitHub client without authentication (limited rate limits)")

    async def _load_processed(self) -> None:
        """Load processed items from state manager."""
        try:
            runs = await self.state_mgr.list_runs(limit=1000)
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
                            self.processed[key] = ProcessedItem(
                                item_type, repo_full, number, run.created_at, run.sandbox_name
                            )
                    except (ValueError, IndexError):
                        pass

            log.info(f"Loaded {len(self.processed)} processed items from state")

        except Exception as e:
            log.warning(f"Failed to load processed items from state: {e}")


# Global poller instance
poller = GitHubPoller()


async def start_poller():
    """Start the poller in the background."""
    if ENABLED:
        asyncio.create_task(poller.start())
