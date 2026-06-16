"""GitHub poller for pull mode. Periodically checks repos for issues/PRs and creates Sandbox CRs."""
import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx

from . import k8shelper
from .common import get_logger
from .state import StateManager, AgentRun

log = get_logger("poller")

# Configuration from environment
ENABLED = os.environ.get("PULL_MODE_ENABLED", "false").lower() == "true"
INTERVAL_MINUTES = int(os.environ.get("PULL_MODE_INTERVAL_MINUTES", "5"))
REPOS = [r.strip() for r in os.environ.get("PULL_MODE_REPOS", "").split(",") if r.strip()]
EVENT_TYPES = [e.strip().lower() for e in os.environ.get("PULL_MODE_EVENTS", "issues,issue_comments").split(",") if e.strip()]

TRIGGER_PHRASE = os.environ.get("TRIGGER_PHRASE", "/fix").strip()
ISSUE_LABEL = os.environ.get("ISSUE_LABEL", "").strip().lower()
ALLOWED_USERS = {u.strip().lower() for u in os.environ.get("ALLOWED_USERS", "").split(",") if u.strip()}

# GitHub API configuration
GH_APP_ID = os.environ.get("GH_APP_ID")
GH_PRIVATE_KEY = os.environ.get("GH_PRIVATE_KEY")
GH_TOKEN = os.environ.get("GH_TOKEN")


@dataclass
class ProcessedItem:
    """Track processed items to avoid duplicates."""
    item_type: str  # "issue" or "issue_comment" or "pr"
    repo_full: str
    number: int
    timestamp: float = field(default_factory=time.time)
    sandbox_name: str = ""

    def key(self) -> str:
        """Unique key for this item."""
        return f"{self.item_type}:{self.repo_full}:{self.number}"


class GitHubPoller:
    """Polls GitHub for issues/PRs and creates Sandbox CRs."""

    def __init__(self):
        self.state_mgr = StateManager()
        self.processed: dict[str, ProcessedItem] = {}
        self.client: httpx.AsyncClient | None = None
        self.installation_token: str | None = None
        self.token_expires_at: float = 0

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
        await self._ensure_client()

        # Check issues with label (if configured)
        if "issues" in EVENT_TYPES and ISSUE_LABEL:
            await self._check_labeled_issues(repo_full)

        # Check issue comments with trigger phrase
        if "issue_comments" in EVENT_TYPES:
            await self._check_issue_comments(repo_full)

        # Check pull requests (if configured)
        if "prs" in EVENT_TYPES:
            await self._check_pull_requests(repo_full)

    async def _check_labeled_issues(self, repo_full: str) -> None:
        """Check for newly opened issues with the target label."""
        await self._ensure_client()
        if not self.client:
            return

        # Query for issues with the label, sorted by recently created
        query = f'repo:{repo_full} is:issue is:open label:"{ISSUE_LABEL}"'
        params = {
            "q": query,
            "sort": "created",
            "order": "desc",
            "per_page": 10,
        }

        try:
            response = await self.client.get(
                "https://api.github.com/search/issues",
                params=params,
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()

            for item in data.get("items", []):
                await self._process_labeled_issue(repo_full, item)

        except httpx.HTTPError as e:
            log.error(f"GitHub API error searching labeled issues: {e}")

    async def _check_issue_comments(self, repo_full: str) -> None:
        """Check for recent issue comments with trigger phrase."""
        await self._ensure_client()
        if not self.client:
            return

        owner, repo = repo_full.split("/", 1)

        # Get recent comments (last 10)
        params = {"sort": "created", "order": "desc", "per_page": 10}

        try:
            response = await self.client.get(
                f"https://api.github.com/repos/{owner}/{repo}/issues/comments",
                params=params,
                headers=self._headers(),
            )
            response.raise_for_status()

            for comment in response.json():
                await self._process_issue_comment(repo_full, comment)

        except httpx.HTTPError as e:
            log.error(f"GitHub API error fetching issue comments: {e}")

    async def _check_pull_requests(self, repo_full: str) -> None:
        """Check for recent pull requests."""
        await self._ensure_client()
        if not self.client:
            return

        owner, repo = repo_full.split("/", 1)

        # Get open PRs
        params = {"state": "open", "sort": "created", "order": "desc", "per_page": 10}

        try:
            response = await self.client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                params=params,
                headers=self._headers(),
            )
            response.raise_for_status()

            for pr in response.json():
                await self._process_pull_request(repo_full, pr)

        except httpx.HTTPError as e:
            log.error(f"GitHub API error fetching PRs: {e}")

    async def _process_labeled_issue(self, repo_full: str, issue: dict) -> None:
        """Process an issue with the target label."""
        number = issue.get("number")
        key = f"issue:{repo_full}:{number}"

        # Skip if already processed
        if key in self.processed:
            return

        # Check if user is allowed
        sender = (issue.get("user") or {}).get("login", "")
        if ALLOWED_USERS and not self._is_allowed(sender):
            log.debug(f"Skipping issue {number} by disallowed user {sender}")
            return

        log.info(f"Found labeled issue: {repo_full}#{number}")

        # Create task
        ts = int(time.time())
        safe = "".join(c.lower() if c.isalnum() else "-" for c in repo_full).strip("-")
        task = {
            "sandbox_name": f"fix-{safe}-{number}-{ts}"[:58],
            "repo_full": repo_full,
            "clone_url": issue.get("repository", {}).get("clone_url", ""),
            "default_branch": issue.get("repository", {}).get("default_branch", "main"),
            "number": number,
            "title": issue.get("title", ""),
            "body": issue.get("body", "") or "",
            "instruction": "",
            "sender": sender,
            "is_pr": False,
            "reason": f"issue opened with label '{ISSUE_LABEL}'",
        }

        # Create Sandbox CR
        try:
            sandbox_name = k8shelper.create_sandbox(task)
            self.processed[key] = ProcessedItem("issue", repo_full, number, time.time(), sandbox_name)
            log.info(f"Created sandbox {sandbox_name} for labeled issue {number}")
        except Exception as e:
            log.error(f"Failed to create sandbox for issue {number}: {e}")

    async def _process_issue_comment(self, repo_full: str, comment: dict) -> None:
        """Process an issue comment for trigger phrase."""
        # Get issue number from comment
        issue_url = comment.get("issue_url", "")
        if not issue_url:
            return

        # Extract issue number from URL (format: .../repos/{owner}/{repo}/issues/{number})
        parts = issue_url.split("/")
        try:
            number = int(parts[-1])
        except (ValueError, IndexError):
            return

        key = f"issue_comment:{repo_full}:{number}"

        # Skip if already processed recently (within 1 hour)
        if key in self.processed:
            processed = self.processed[key]
            if time.time() - processed.timestamp < 3600:
                return

        # Check for trigger phrase
        body = comment.get("body", "").strip()
        if not body.lower().startswith(TRIGGER_PHRASE.lower()):
            return

        # Check if user is allowed
        sender = (comment.get("user") or {}).get("login", "")
        if ALLOWED_USERS and not self._is_allowed(sender):
            log.debug(f"Skipping comment by disallowed user {sender}")
            return

        log.info(f"Found trigger comment: {repo_full}#{number} by {sender}")

        # Fetch full issue details
        await self._ensure_client()
        if not self.client:
            return

        owner, repo = repo_full.split("/", 1)

        try:
            response = await self.client.get(
                f"https://api.github.com/repos/{owner}/{repo}/issues/{number}",
                headers=self._headers(),
            )
            response.raise_for_status()
            issue = response.json()
        except httpx.HTTPError as e:
            log.error(f"Failed to fetch issue {number}: {e}")
            return

        # Create task
        ts = int(time.time())
        safe = "".join(c.lower() if c.isalnum() else "-" for c in repo_full).strip("-")
        task = {
            "sandbox_name": f"fix-{safe}-{number}-{ts}"[:58],
            "repo_full": repo_full,
            "clone_url": issue.get("repository", {}).get("clone_url", ""),
            "default_branch": issue.get("repository", {}).get("default_branch", "main"),
            "number": number,
            "title": issue.get("title", ""),
            "body": issue.get("body", "") or "",
            "instruction": body[len(TRIGGER_PHRASE):].strip(),
            "sender": sender,
            "is_pr": "pull_request" in issue,
            "reason": f"{TRIGGER_PHRASE} by {sender}",
        }

        # Create Sandbox CR
        try:
            sandbox_name = k8shelper.create_sandbox(task)
            self.processed[key] = ProcessedItem("issue_comment", repo_full, number, time.time(), sandbox_name)
            log.info(f"Created sandbox {sandbox_name} for issue comment {number}")
        except Exception as e:
            log.error(f"Failed to create sandbox for issue comment {number}: {e}")

    async def _process_pull_request(self, repo_full: str, pr: dict) -> None:
        """Process a pull request."""
        number = pr.get("number")
        key = f"pr:{repo_full}:{number}"

        # Skip if already processed
        if key in self.processed:
            return

        # Check if user is allowed
        sender = (pr.get("user") or {}).get("login", "")
        if ALLOWED_USERS and not self._is_allowed(sender):
            log.debug(f"Skipping PR {number} by disallowed user {sender}")
            return

        log.info(f"Found PR: {repo_full}#{number}")

        # Create task
        ts = int(time.time())
        safe = "".join(c.lower() if c.isalnum() else "-" for c in repo_full).strip("-")
        task = {
            "sandbox_name": f"fix-{safe}-{number}-{ts}"[:58],
            "repo_full": repo_full,
            "clone_url": pr.get("repository", {}).get("clone_url", ""),
            "default_branch": pr.get("repository", {}).get("default_branch", "main"),
            "number": number,
            "title": pr.get("title", ""),
            "body": pr.get("body", "") or "",
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

    async def _ensure_client(self) -> None:
        """Ensure HTTP client is initialized with valid auth."""
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=30.0)

        # Check if we need to refresh the installation token
        if GH_APP_ID and GH_PRIVATE_KEY and (not self.installation_token or time.time() >= self.token_expires_at):
            await self._refresh_installation_token()

    async def _refresh_installation_token(self) -> None:
        """Refresh GitHub App installation token."""
        import jwt

        # Generate JWT
        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + 600,
            "iss": int(GH_APP_ID),
        }
        jwt_token = jwt.encode(payload, GH_PRIVATE_KEY, algorithm="RS256")

        if not self.client:
            return

        try:
            # Get installation ID
            response = await self.client.get(
                "https://api.github.com/app/installations",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            response.raise_for_status()
            installations = response.json()

            if not installations:
                log.error("No GitHub App installations found")
                return

            installation_id = installations[0]["id"]

            # Get installation token
            response = await self.client.post(
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            response.raise_for_status()
            token_data = response.json()

            self.installation_token = token_data["token"]
            # Token expires in 1 hour, refresh 5 minutes early
            self.token_expires_at = time.time() + 3600 - 300
            log.info("Refreshed GitHub App installation token")

        except (httpx.HTTPError, KeyError) as e:
            log.error(f"Failed to refresh installation token: {e}")

    def _headers(self) -> dict[str, str]:
        """Get headers for GitHub API requests."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "claude-agent-runner/1.0",
        }

        if self.installation_token:
            headers["Authorization"] = f"token {self.installation_token}"
        elif GH_TOKEN:
            headers["Authorization"] = f"token {GH_TOKEN}"

        return headers

    async def _load_processed(self) -> None:
        """Load processed items from state manager."""
        try:
            runs = await self.state_mgr.list_runs(limit=1000)
            for run in runs:
                # Reconstruct ProcessedItem from AgentRun
                if run.task_id:
                    # Extract item type, repo, number from task_id
                    # task_id format: "fix-repo-name-123-timestamp"
                    parts = run.task_id.split("-")
                    if len(parts) >= 3:
                        # Try to parse number
                        try:
                            number = int(parts[-2]) if len(parts) >= 2 else 0
                            # Reconstruct repo from task name
                            repo_full = run.trigger_context.get("repo_full", "")
                            item_type = run.trigger_context.get("trigger_type", "issue")

                            key = f"{item_type}:{repo_full}:{number}"
                            self.processed[key] = ProcessedItem(item_type, repo_full, number, run.created_at, run.sandbox_name)
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
