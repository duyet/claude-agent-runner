"""Agent runner. Clones repo, runs Claude Agent SDK — agent handles everything via tools.

This module provides the main agent execution logic with integrated state management:
- Parse task from environment
- Clone repository
- Initialize state tracking
- Run Claude Agent SDK
- Record results and messages
- Cleanup and update state
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from . import gh_token, k8shelper, state
from .common import env, get_logger, load_task

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["main", "run_agent_sdk"]

log = get_logger("agent")
WORKDIR = Path("/workspace/repo")

DEFAULT_SYSTEM_PROMPT = """You are an autonomous coding agent.

## Operating Principles
- **Evidence over guesses.** Read actual code before changing it.
- **Minimal diffs.** Fix the specific problem. Don't reformat unrelated code.
- **Don't break tests.** Run tests and verify they pass.
- **Say what you don't know.** If something is ambiguous, say so.

## Reporting
Report concisely: what you found, what you changed, the result."""

_RELEVANT_ENV_PREFIXES = (
    "ANTHROPIC_", "CLAUDE_", "ANYROUTER_", "GIT_", "GH_", "SKILLS_", "MCP_"
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="claude-agent-runner")
    p.add_argument("--model", help="Model ID (overrides ANTHROPIC_MODEL env)")
    p.add_argument(
        "--max-turns", type=int, help="Max conversation turns (overrides CLAUDE_MAX_TURNS env)"
    )
    p.add_argument(
        "--append-system-prompt",
        help="Extra text appended to the system prompt",
    )
    return p.parse_args(argv)


def _build_system_prompt(cli_args: argparse.Namespace | None = None) -> str:
    path = env("SYSTEM_PROMPT_PATH")
    if path:
        system_prompt = Path(path).read_text()
    else:
        system_prompt = DEFAULT_SYSTEM_PROMPT

    append = (
        cli_args.append_system_prompt
        if cli_args and cli_args.append_system_prompt
        else env("APPEND_SYSTEM_PROMPT", "")
    )
    if append:
        system_prompt += f"\n\n{append}"

    return system_prompt


def _build_plugins() -> list[dict]:
    plugins: list[dict] = []

    raw = env("PLUGINS")
    if raw:
        try:
            plugins.extend(json.loads(raw))
        except json.JSONDecodeError as e:
            log.warning("invalid PLUGINS JSON: %s", e)

    # Backward compat: SKILLS_DIR entries are loaded as local plugins
    skills_dir = env("SKILLS_DIR")
    if skills_dir:
        for d in skills_dir.split(","):
            d = d.strip()
            if d:
                plugins.append({"type": "local", "path": d})

    return plugins


def main() -> None:
    """Main entry point for the agent runner.

    Lifecycle:
    1. Parse CLI args and load task from environment
    2. Initialize state manager and create run record
    3. Clone repository
    4. Configure git environment
    5. Run Claude Agent SDK with state tracking
    6. Update run status (success/failure)
    7. Cleanup sandbox pod
    """
    print("=" * 60, flush=True)
    print("claude-agent-runner starting", flush=True)
    print("=" * 60, flush=True)

    cli_args = _parse_args()
    task = load_task()
    log.info("task=%s", json.dumps({k: v for k, v in task.items() if k != "body"}))

    # Initialize state management
    st = state.get_state()

    # Create trigger from task
    trigger = state.Trigger(
        type=task.get("reason", "custom").lower().replace(" ", "_"),
        user=task.get("sender", "api"),
        trigger_phrase=task.get("instruction", "")[:100],
        issue_number=task.get("number", 0),
        comment_body=task.get("body", "")[:500],
        reason=task.get("reason", ""),
    )

    repo_full = task["repo_full"]
    token = gh_token.token_for(repo_full)
    remote = gh_token.git_remote(repo_full, token)

    # Create run record
    model = (
        cli_args.model
        if cli_args and cli_args.model
        else env("ANTHROPIC_MODEL", "anthropic/claude-sonnet-4-6")
    )
    max_turns = (
        cli_args.max_turns
        if cli_args and cli_args.max_turns
        else int(env("CLAUDE_MAX_TURNS", "50"))
    )

    run = st.create_run(
        sandbox_name=task["sandbox_name"],
        repo_full=repo_full,
        repo_url=remote,
        branch=task.get("default_branch", "main"),
        trigger=trigger,
        model=model,
        max_turns=max_turns,
        metadata={
            "git_sha": task.get("git_sha", ""),
            "is_pr": task.get("is_pr", False),
        },
    )

    # Create session for message tracking
    session = st.create_session(run.run_id)

    # Record initial user message
    st.add_message("user", _prompt(task))

    WORKDIR.parent.mkdir(parents=True, exist_ok=True)
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)

    clone = subprocess.run(
        ["git", "clone", "--depth", "50", remote, str(WORKDIR)],
        capture_output=True, text=True,
    )
    if clone.returncode != 0:
        log.error("clone failed: %s", clone.stderr[-400:])
        st.update_run(run.run_id, status=state.RunStatus.FAILED, error="Clone failed")
        k8shelper.delete_sandbox(task["sandbox_name"])
        sys.exit(1)

    os.environ["GH_TOKEN"] = token
    os.environ["GITHUB_TOKEN"] = token

    os.environ["GIT_AUTHOR_NAME"] = env("GIT_AUTHOR_NAME", "agent")
    os.environ["GIT_AUTHOR_EMAIL"] = env("GIT_AUTHOR_EMAIL", "agent@localhost")
    os.environ["GIT_COMMITTER_NAME"] = env("GIT_COMMITTER_NAME", "agent")
    os.environ["GIT_COMMITTER_EMAIL"] = env("GIT_COMMITTER_EMAIL", "agent@localhost")

    try:
        result = asyncio.run(run_agent_sdk(_prompt(task), cli_args, session))
        st.update_run(run.run_id, status=state.RunStatus.COMPLETED, result=result)
        log.info("Run completed successfully")
    except Exception as exc:  # noqa: BLE001
        log.exception("agent run failed: %s", exc)
        st.update_run(run.run_id, status=state.RunStatus.FAILED, error=str(exc))

    k8shelper.delete_sandbox(task["sandbox_name"])
    log.info("done")


async def run_agent_sdk(
    prompt: str,
    cli_args: argparse.Namespace | None = None,
    session: state.AgentSession | None = None,
) -> state.RunResult:
    """Execute the Claude Agent SDK with state tracking.

    Args:
        prompt: User prompt for the agent
        cli_args: Parsed CLI arguments
        session: State session for message tracking

    Returns:
        RunResult with execution summary
    """
    from claude_agent_sdk import ClaudeAgentOptions, query

    allowed_tools_str = env(
        "ALLOWED_TOOLS",
        "Read,Write,Edit,Bash,Glob,Grep,GitHub,WebSearch,WebFetch",
    )
    allowed_tools = [t.strip() for t in allowed_tools_str.split(",") if t.strip()]

    system_prompt = _build_system_prompt(cli_args)

    model = (
        cli_args.model
        if cli_args and cli_args.model
        else env("ANTHROPIC_MODEL", "anthropic/claude-sonnet-4-6")
    )
    max_turns = (
        cli_args.max_turns
        if cli_args and cli_args.max_turns
        else int(env("CLAUDE_MAX_TURNS", "50"))
    )

    opts = ClaudeAgentOptions(
        cwd=str(WORKDIR),
        system_prompt=system_prompt,
        permission_mode=env("CLAUDE_PERMISSION_MODE", "auto"),
        allowed_tools=allowed_tools,
        model=model,
        max_turns=max_turns,
    )

    raw = env("SETTING_SOURCES", "user,project")
    setting_sources = [s.strip() for s in raw.split(",") if s.strip()]
    if setting_sources:
        opts.setting_sources = setting_sources

    skills_val = env("SKILLS", "all")
    if skills_val == "none":
        opts.skills = []
    elif skills_val == "all":
        opts.skills = "all"
    else:
        opts.skills = [s.strip() for s in skills_val.split(",") if s.strip()]

    # Plugin loading from env
    plugins = _build_plugins()
    if plugins:
        opts.plugins = plugins

    # Forward relevant env vars to the SDK subprocess so it can read
    # ANTHROPIC_API_KEY, ANTHROPIC_PLUGIN_MARKETPLACES, etc. directly.
    sdk_env = {
        k: v for k, v in os.environ.items()
        if k.startswith(_RELEVANT_ENV_PREFIXES) and v
    }
    if sdk_env:
        opts.env = sdk_env

    mcp_servers = env("MCP_SERVERS")
    if mcp_servers:
        opts.mcp_servers = json.loads(mcp_servers)

    st = state.get_state()
    turn_count = 0
    files_changed: list[str] = []
    commits: list[str] = []

    async for msg in query(prompt=prompt, options=opts):
        mtype = type(msg).__name__
        turn_count += 1

        # Track assistant messages in state
        if session and mtype in ("AssistantMessage", "ToolUseMessage"):
            content = str(msg.content) if hasattr(msg, "content") else ""
            tools_used = []
            if hasattr(msg, "tool_use") and msg.tool_use:
                tools_used = [msg.tool_use]

            st.add_message(
                role="assistant",
                content=content[:1000],  # Truncate for storage
                tools_used=tools_used,
                metadata={"msg_type": mtype},
            )

        # Logging
        if hasattr(msg, "content") and msg.content:
            detail = str(msg.content)
            if hasattr(msg, "subtype") and msg.subtype:
                detail = f"[{msg.subtype}] {detail}"
            log.info("agent -> %s: %.300s", mtype, detail.replace("\n", "\\n")[:300])

            # Extract file changes from content
            if "changed" in detail.lower() or "modified" in detail.lower():
                # Simple heuristic to extract file paths
                for word in detail.split():
                    if "." in word and len(word) < 100:
                        files_changed.append(word.strip(".,;:\"'()"))

        elif hasattr(msg, "subtype") and msg.subtype:
            data_str = str(msg.data)[:200] if hasattr(msg, "data") and msg.data else ""
            log.info("agent -> %s[%s]: %.200s", mtype, msg.subtype, data_str.replace("\n", "\\n")[:200])

        elif hasattr(msg, "result"):
            result_str = str(msg.result)[:200] if msg.result else ""
            log.info("agent -> %s: result=%.200s", mtype, result_str.replace("\n", "\\n"))

            # Extract commits from tool results
            if result_str and "commit" in result_str.lower():
                for word in result_str.split():
                    if len(word) == 40 and word.isalnum():  # SHA-like
                        commits.append(word)

        elif hasattr(msg, "duration_ms"):
            log.info("agent -> %s: done in %sms", mtype, msg.duration_ms)
        else:
            log.info("agent -> %s (no content)", mtype)

    # Update run with actual turn count
    if session:
        st.update_run(session.run_id, actual_turns=turn_count)

    # Build result
    return state.RunResult(
        exit_code=0,
        summary=f"Completed {turn_count} turns",
        files_changed=list(set(files_changed)),
        commits=list(set(commits)),
    )


def _prompt(task: dict) -> str:
    inst = task.get("instruction", "").strip()
    extra = f"\n\nAdditional instruction from the requester: {inst}" if inst else ""
    co_author = env("CO_AUTHOR_NAME", "")
    co_author_line = (
        f"\n5. Commit your changes (co-authored with {co_author})."
        if co_author else "\n5. Commit your changes."
    )
    title = task.get("title", "")
    body = task.get("body", "")
    number = task.get("number", 0)
    reason = task.get("reason", "")

    # Real GitHub issue — reference it
    if number and number < 1000000:
        return f"""Fix GitHub issue/PR #{number} in the cloned repo at the current working directory.

Title: {title}

Description:
{body}{extra}

Steps:
1. Explore the codebase to understand the issue.
2. Make minimal, correct changes.
3. If tests exist, run them and verify they pass.
4. Commit your changes.{co_author_line}
5. Push to a new branch.
6. Create a pull request using the GitHub tool."""

    # Custom / API trigger — describe the task directly
    header = f"Reason: {reason}" if reason else ""
    return f"""You are working on the cloned repo at the current working directory.

{header}
Title: {title}

Description:
{body}{extra}

Steps:
1. Explore the codebase to understand the context.
2. Make minimal, correct changes.
3. If tests exist, run them and verify they pass.
4. Commit your changes.{co_author_line}
5. Push to a new branch.
6. Create a pull request using the GitHub tool."""


if __name__ == "__main__":
    main()
