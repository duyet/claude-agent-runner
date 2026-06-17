"""State management for persistent agent sessions and run history.

This module provides a flexible state management system that supports two deployment modes:

**Isolated Mode** (default):
- Ephemeral state stored in pod memory
- Lost on pod deletion
- Fast, minimal overhead

**Shared Mode**:
- Persistent state stored on shared PVC
- In-memory cache for fast access
- Sessions preserved across runs
- Context continuity between runs

Storage Backends:
- `none`: In-memory only (default)
- `file`: File system (local or shared volume)
- `postgres`: PostgreSQL database (planned)
- `redis`: Redis cache (planned)

Example:
    ```python
    from app.state import get_state, RunStatus, Trigger

    # Get global state manager
    state = get_state()

    # Create a new run
    run = state.create_run(
        sandbox_name="fix-myrepo-123-1718456789",
        repo_full="owner/repo",
        repo_url="https://github.com/owner/repo",
        branch="fix/issue-123",
        trigger=Trigger(type="github_issue_comment", user="alice", issue_number=123),
        model="claude-sonnet-4-5-20250929",
        max_turns=50,
        metadata={"labels": ["bug", "auth"]},
    )

    # Add progress messages
    state.add_message("user", "Fix the authentication bug")
    state.add_message("assistant", "I'll analyze the code...", tools_used=["Read", "Grep"])

    # Mark as completed
    state.update_run(run.run_id, status=RunStatus.COMPLETED, actual_turns=15)
    ```

Environment Variables:
- `STATE_MODE`: Deployment mode (`isolated` or `shared`)
- `STATE_BACKEND`: Storage backend (`none`, `file`, `postgres`, `redis`)
- `STATE_PATH`: Local state path (isolated mode)
- `STATE_SHARED_PATH`: Shared state path (shared mode)
- `STATE_SHARED_PVC`: PVC name for shared state
- `STATE_MEMORY_CACHE_SIZE`: Max runs in memory cache (shared mode)
"""
from __future__ import annotations

import abc
import gzip
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from .common import env, get_logger

__all__ = [
    "get_state",
    "StateManager",
    "StateMode",
    "StorageBackend",
    "RunStatus",
    "AgentRun",
    "AgentSession",
    "Trigger",
    "RunResult",
    "SessionMessage",
]

log = get_logger("state")


class StateMode(str, Enum):
    """Deployment mode for state persistence.

    Attributes:
        ISOLATED: Ephemeral state, lost on pod deletion
        SHARED: Persistent state on shared PVC with in-memory cache
    """

    ISOLATED = "isolated"
    SHARED = "shared"


class StorageBackend(str, Enum):
    """Storage backend options.

    Attributes:
        NONE: In-memory only, fastest but no persistence
        FILE: File system, works with local or shared volumes
        POSTGRES: PostgreSQL database (planned)
        REDIS: Redis cache (planned)
    """

    NONE = "none"
    FILE = "file"
    POSTGRES = "postgres"
    REDIS = "redis"


class RunStatus(str, Enum):
    """Status of an agent run.

    Attributes:
        RUNNING: Agent is currently executing
        COMPLETED: Run finished successfully
        FAILED: Run failed with error
        TIMEOUT: Run exceeded time limit
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class Trigger:
    """What triggered the agent run.

    Attributes:
        type: Trigger type (github_issue_comment, github_issue_labeled, custom_webhook)
        user: Username who triggered the run
        trigger_phrase: Command phrase used (e.g., "/fix")
        issue_number: GitHub issue/PR number
        comment_body: Full comment body
        reason: Human-readable reason for the trigger
    """

    type: str
    user: str
    trigger_phrase: str = ""
    issue_number: int = 0
    comment_body: str = ""
    reason: str = ""


@dataclass(frozen=True)
class RunResult:
    """Result of a completed agent run.

    Attributes:
        exit_code: Process exit code (0 = success)
        summary: Human-readable summary of changes
        files_changed: List of modified file paths
        commits: List of commit SHAs created
        pr_number: Pull request number (if created)
        pr_url: Pull request URL (if created)
    """

    exit_code: int = 0
    summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    pr_number: int = 0
    pr_url: str = ""
    tool_uses: int = 0


@dataclass
class AgentRun:
    """Record of a single agent execution.

    Attributes:
        run_id: Unique identifier for this run
        sandbox_name: Kubernetes pod/sandbox name
        repo_full: Repository in "owner/repo" format
        repo_url: Full repository URL
        branch: Git branch worked on
        trigger: What triggered this run
        status: Current run status
        started_at: ISO timestamp when run started
        completed_at: ISO timestamp when run completed
        duration_seconds: Total run duration
        model: Claude model used
        max_turns: Maximum conversation turns allowed
        actual_turns: Actual conversation turns used
        result: Run result (if completed)
        error: Error message (if failed)
        session_id: Associated session ID
        metadata: Additional metadata
    """

    run_id: str = field(default_factory=lambda: str(uuid4()))
    sandbox_name: str = ""
    repo_full: str = ""
    repo_url: str = ""
    branch: str = ""
    trigger: Optional[Trigger] = None
    status: RunStatus = RunStatus.RUNNING
    started_at: str = field(default_factory=lambda: _utc_now())
    completed_at: str = ""
    duration_seconds: int = 0
    model: str = ""
    max_turns: int = 0
    actual_turns: int = 0
    result: Optional[RunResult] = None
    error: Optional[str] = None
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for storage.

        Returns:
            Dictionary representation of this run
        """
        return {
            "run_id": self.run_id,
            "sandbox_name": self.sandbox_name,
            "repo_full": self.repo_full,
            "repo_url": self.repo_url,
            "branch": self.branch,
            "trigger": self.trigger.__dict__ if self.trigger else None,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "model": self.model,
            "max_turns": self.max_turns,
            "actual_turns": self.actual_turns,
            "result": self.result.__dict__ if self.result else None,
            "error": self.error,
            "session_id": self.session_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentRun:
        """Deserialize from dictionary.

        Args:
            data: Dictionary from storage

        Returns:
            AgentRun instance
        """
        trigger = Trigger(**data["trigger"]) if data.get("trigger") else None
        result = RunResult(**data["result"]) if data.get("result") else None
        return cls(
            run_id=data["run_id"],
            sandbox_name=data["sandbox_name"],
            repo_full=data["repo_full"],
            repo_url=data.get("repo_url", ""),
            branch=data.get("branch", ""),
            trigger=trigger,
            status=RunStatus(data["status"]),
            started_at=data["started_at"],
            completed_at=data.get("completed_at", ""),
            duration_seconds=data.get("duration_seconds", 0),
            model=data.get("model", ""),
            max_turns=data.get("max_turns", 0),
            actual_turns=data.get("actual_turns", 0),
            result=result,
            error=data.get("error"),
            session_id=data.get("session_id", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class SessionMessage:
    """Single message in an agent session.

    Attributes:
        role: Message role (user, assistant, system)
        content: Message content
        timestamp: ISO timestamp
        tools_used: Tools used in this message (assistant only)
        metadata: Additional metadata
    """

    role: str
    content: str
    timestamp: str = field(default_factory=lambda: _utc_now())
    tools_used: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentSession:
    """Session transcript for an agent run.

    Attributes:
        session_id: Unique session identifier
        run_id: Associated run ID
        started_at: ISO timestamp when session started
        messages: List of messages in the session
        compressed: Whether messages are compressed
        size_bytes: Size in bytes
    """

    session_id: str = field(default_factory=lambda: str(uuid4()))
    run_id: str = ""
    started_at: str = field(default_factory=lambda: _utc_now())
    messages: list[SessionMessage] = field(default_factory=list)
    compressed: bool = False
    size_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for storage.

        Returns:
            Dictionary representation of this session
        """
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "messages": [m.__dict__ for m in self.messages],
            "compressed": self.compressed,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentSession:
        """Deserialize from dictionary.

        Args:
            data: Dictionary from storage

        Returns:
            AgentSession instance
        """
        messages = [SessionMessage(**m) for m in data.get("messages", [])]
        return cls(
            session_id=data["session_id"],
            run_id=data["run_id"],
            started_at=data["started_at"],
            messages=messages,
            compressed=data.get("compressed", False),
            size_bytes=data.get("size_bytes", 0),
        )


class StorageBackendABC(abc.ABC):
    """Abstract base class for storage backends.

    Implementations:
        - NoneStorage: In-memory only
        - FileStorage: File system based
        - PostgresStorage: PostgreSQL (planned)
        - RedisStorage: Redis (planned)
    """

    @abc.abstractmethod
    def save_run(self, run: AgentRun) -> None:
        """Save a run record to storage.

        Args:
            run: Run to save
        """

    @abc.abstractmethod
    def get_run(self, run_id: str) -> Optional[AgentRun]:
        """Retrieve a run by ID.

        Args:
            run_id: Run identifier

        Returns:
            AgentRun if found, None otherwise
        """

    @abc.abstractmethod
    def list_runs(
        self,
        repo_full: Optional[str] = None,
        status: Optional[RunStatus] = None,
        limit: int = 100,
    ) -> list[AgentRun]:
        """List runs with optional filters.

        Args:
            repo_full: Filter by repository
            status: Filter by status
            limit: Maximum results

        Returns:
            List of matching runs, newest first
        """

    @abc.abstractmethod
    def save_session(self, session: AgentSession) -> None:
        """Save a session record to storage.

        Args:
            session: Session to save
        """

    @abc.abstractmethod
    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """Retrieve a session by ID.

        Args:
            session_id: Session identifier

        Returns:
            AgentSession if found, None otherwise
        """

    @abc.abstractmethod
    def delete_run(self, run_id: str) -> None:
        """Delete a run and its session.

        Args:
            run_id: Run identifier
        """


class NoneStorage(StorageBackendABC):
    """No-op storage backend - runs stored in memory only.

    Fastest option but all data is lost on restart.
    Suitable for isolated mode with no persistence requirements.
    """

    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}
        self._sessions: dict[str, AgentSession] = {}

    def save_run(self, run: AgentRun) -> None:
        self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> Optional[AgentRun]:
        return self._runs.get(run_id)

    def list_runs(
        self,
        repo_full: Optional[str] = None,
        status: Optional[RunStatus] = None,
        limit: int = 100,
    ) -> list[AgentRun]:
        runs = list(self._runs.values())
        if repo_full:
            runs = [r for r in runs if r.repo_full == repo_full]
        if status:
            runs = [r for r in runs if r.status == status]
        return sorted(runs, key=lambda r: r.started_at, reverse=True)[:limit]

    def save_session(self, session: AgentSession) -> None:
        self._sessions[session.session_id] = session

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        return self._sessions.get(session_id)

    def delete_run(self, run_id: str) -> None:
        self._runs.pop(run_id, None)
        self._sessions.pop(run_id, None)


class FileStorage(StorageBackendABC):
    """File system storage backend.

    Organizes data by date: runs/YYYY/MM/DD/run-id.json
    Sessions are gzip-compressed: sessions/YYYY/MM/DD/session-id.json.gz
    """

    def __init__(self, base_path: Path | str) -> None:
        """Initialize file storage.

        Args:
            base_path: Base directory for storage
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.runs_dir = self.base_path / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir = self.base_path / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _run_path(self, run_id: str) -> Path:
        """Get path for run file, organized by date.

        Args:
            run_id: Run identifier

        Returns:
            Path to run JSON file
        """
        date = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        path = self.runs_dir / date / f"{run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _session_path(self, session_id: str) -> Path:
        """Get path for session file, organized by date.

        Args:
            session_id: Session identifier

        Returns:
            Path to compressed session file
        """
        date = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        path = self.sessions_dir / date / f"{session_id}.json.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def save_run(self, run: AgentRun) -> None:
        path = self._run_path(run.run_id)
        path.write_text(json.dumps(run.to_dict(), indent=2))

    def get_run(self, run_id: str) -> Optional[AgentRun]:
        path = self._run_path(run_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return AgentRun.from_dict(data)
        except (json.JSONDecodeError, KeyError) as exc:
            log.warning("Failed to load run %s: %s", run_id, exc)
            return None

    def list_runs(
        self,
        repo_full: Optional[str] = None,
        status: Optional[RunStatus] = None,
        limit: int = 100,
    ) -> list[AgentRun]:
        runs: list[AgentRun] = []
        for path in self.runs_dir.rglob("*.json"):
            try:
                data = json.loads(path.read_text())
                run = AgentRun.from_dict(data)
                if repo_full and run.repo_full != repo_full:
                    continue
                if status and run.status != status:
                    continue
                runs.append(run)
                if len(runs) >= limit:
                    break
            except (json.JSONDecodeError, KeyError):
                continue
        return sorted(runs, key=lambda r: r.started_at, reverse=True)

    def save_session(self, session: AgentSession) -> None:
        path = self._session_path(session.session_id)
        data = json.dumps(session.to_dict())
        path.write_bytes(gzip.compress(data.encode()))

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            data = gzip.decompress(path.read_bytes()).decode()
            return AgentSession.from_dict(json.loads(data))
        except (gzip.BadGzipFile, json.JSONDecodeError, KeyError) as exc:
            log.warning("Failed to load session %s: %s", session_id, exc)
            return None

    def delete_run(self, run_id: str) -> None:
        self._run_path(run_id).unlink(missing_ok=True)
        self._session_path(run_id).unlink(missing_ok=True)


class StateManager:
    """State manager for tracking agent runs and sessions.

    Provides unified interface for state operations regardless of
    deployment mode or storage backend.

    Example:
        ```python
        state = StateManager()
        run = state.create_run(...)
        state.add_message("user", "Fix this bug")
        state.update_run(run.run_id, status=RunStatus.COMPLETED)
        ```
    """

    def __init__(self) -> None:
        """Initialize state manager from environment variables."""
        self.mode = StateMode(env("STATE_MODE", "isolated"))
        self.backend_type = StorageBackend(env("STATE_BACKEND", "none"))

        # Configure paths based on mode
        if self.mode == StateMode.SHARED:
            self.state_path = Path(env("STATE_SHARED_PATH", "/workspace/state-shared"))
        else:
            self.state_path = Path(env("STATE_PATH", "/workspace/state"))
        self.state_path.mkdir(parents=True, exist_ok=True)

        # Initialize storage backend
        self.storage = self._init_storage()

        # In-memory cache for shared mode
        self._cache_size = int(env("STATE_MEMORY_CACHE_SIZE", "100"))
        self._run_cache: dict[str, AgentRun] = {}

        # Current run/session (set by agent)
        self.current_run: Optional[AgentRun] = None
        self.current_session: Optional[AgentSession] = None

        log.info(
            "StateManager: mode=%s backend=%s path=%s",
            self.mode,
            self.backend_type,
            self.state_path,
        )

    def _init_storage(self) -> StorageBackendABC:
        """Initialize storage backend from configuration.

        Returns:
            Storage backend instance
        """
        if self.backend_type == StorageBackend.NONE:
            return NoneStorage()
        if self.backend_type == StorageBackend.FILE:
            return FileStorage(self.state_path)
        log.warning("Backend %s not implemented, using NoneStorage", self.backend_type)
        return NoneStorage()

    def create_run(
        self,
        sandbox_name: str,
        repo_full: str,
        repo_url: str,
        branch: str,
        trigger: Trigger,
        model: str,
        max_turns: int,
        metadata: dict[str, Any] | None = None,
    ) -> AgentRun:
        """Create a new run record.

        Args:
            sandbox_name: Kubernetes pod name
            repo_full: Repository in "owner/repo" format
            repo_url: Full repository URL
            branch: Git branch to work on
            trigger: What triggered this run
            model: Claude model to use
            max_turns: Maximum conversation turns
            metadata: Additional metadata

        Returns:
            Created AgentRun instance
        """
        run = AgentRun(
            sandbox_name=sandbox_name,
            repo_full=repo_full,
            repo_url=repo_url,
            branch=branch,
            trigger=trigger,
            model=model,
            max_turns=max_turns,
            metadata=metadata or {},
        )
        self.current_run = run
        self.storage.save_run(run)

        if self.mode == StateMode.SHARED:
            self._cache_run(run)

        log.info("Created run %s for %s", run.run_id, repo_full)
        return run

    def update_run(
        self,
        run_id: str,
        status: Optional[RunStatus] = None,
        actual_turns: Optional[int] = None,
        result: Optional[RunResult] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update an existing run.

        Args:
            run_id: Run identifier
            status: New status (optional)
            actual_turns: Actual turns used (optional)
            result: Run result (optional)
            error: Error message (optional)
        """
        run = self.storage.get_run(run_id)
        if not run:
            log.warning("Run %s not found for update", run_id)
            return

        if status:
            run.status = status
        if actual_turns is not None:
            run.actual_turns = actual_turns
        if result:
            run.result = result
        if error:
            run.error = error

        # Set completion timestamp for terminal states
        if status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.TIMEOUT):
            run.completed_at = _utc_now()
            run.duration_seconds = int(
                (
                    datetime.fromisoformat(run.completed_at)
                    - datetime.fromisoformat(run.started_at)
                ).total_seconds()
            )

        self.storage.save_run(run)
        if self.mode == StateMode.SHARED:
            self._cache_run(run)

    def create_session(self, run_id: str) -> AgentSession:
        """Create a new session for a run.

        Args:
            run_id: Associated run identifier

        Returns:
            Created AgentSession instance
        """
        session = AgentSession(run_id=run_id)
        self.current_session = session
        self.storage.save_session(session)
        log.info("Created session %s for run %s", session.session_id, run_id)
        return session

    def add_message(
        self,
        role: str,
        content: str,
        tools_used: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Add a message to the current session.

        Args:
            role: Message role (user, assistant, system)
            content: Message content
            tools_used: Tools used (assistant only)
            metadata: Additional metadata
        """
        if not self.current_session:
            log.warning("No current session")
            return

        msg = SessionMessage(
            role=role,
            content=content,
            tools_used=tools_used or [],
            metadata=metadata or {},
        )
        self.current_session.messages.append(msg)
        self.storage.save_session(self.current_session)

    def get_run(self, run_id: str) -> Optional[AgentRun]:
        """Get a run by ID.

        Args:
            run_id: Run identifier

        Returns:
            AgentRun if found, None otherwise
        """
        return self.storage.get_run(run_id)

    def list_runs(
        self,
        repo_full: Optional[str] = None,
        status: Optional[RunStatus] = None,
        limit: int = 100,
    ) -> list[AgentRun]:
        """List runs with optional filters.

        Args:
            repo_full: Filter by repository
            status: Filter by status
            limit: Maximum results

        Returns:
            List of matching runs, newest first
        """
        return self.storage.list_runs(repo_full, status, limit)

    def get_recent_runs(self, repo_full: str, limit: int = 10) -> list[AgentRun]:
        """Get recent runs for a repo from cache (shared mode).

        Args:
            repo_full: Repository in "owner/repo" format
            limit: Maximum results

        Returns:
            List of recent runs
        """
        if self.mode == StateMode.SHARED:
            cached = [r for r in self._run_cache.values() if r.repo_full == repo_full]
            return sorted(cached, key=lambda r: r.started_at, reverse=True)[:limit]
        return self.list_runs(repo_full, limit=limit)

    def _cache_run(self, run: AgentRun) -> None:
        """Cache a run in memory (shared mode).

        Args:
            run: Run to cache
        """
        self._run_cache[run.run_id] = run
        if len(self._run_cache) > self._cache_size:
            oldest = min(self._run_cache.keys(), key=lambda k: self._run_cache[k].started_at)
            self._run_cache.pop(oldest)

    def cleanup_old_runs(self, retention_days: int = 30) -> int:
        """Clean up runs older than retention period.

        Args:
            retention_days: Days to keep runs

        Returns:
            Number of runs deleted
        """
        if not isinstance(self.storage, FileStorage):
            log.info("Cleanup only supported for file backend")
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        deleted = 0

        for path in self.storage.runs_dir.rglob("*.json"):
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    path.unlink()
                    deleted += 1
            except OSError:
                continue

        log.info("Cleaned up %d runs (>%d days)", deleted, retention_days)
        return deleted


def _utc_now() -> str:
    """Get current UTC timestamp in ISO format.

    Returns:
        ISO 8601 timestamp string (timezone-aware, UTC)
    """
    return datetime.now(timezone.utc).isoformat()


# Global state manager instance
_state_manager: Optional[StateManager] = None


def get_state() -> StateManager:
    """Get the global state manager instance.

    Returns:
        StateManager singleton
    """
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager
