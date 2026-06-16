"""Agent runner. Clones repo, runs Claude Agent SDK — agent handles everything via tools."""
import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import gh_token, k8shelper
from .common import env, get_logger, load_task

log = get_logger("agent")
WORKDIR = Path("/workspace/repo")

# Prefixes for env vars to forward to the SDK subprocess.
# Any env var matching these prefixes is passed through automatically —
# no need to cherry-pick individual variables.
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


def main() -> None:
    cli_args = _parse_args()
    task = load_task()
    log.info("task=%s", json.dumps({k: v for k, v in task.items() if k != "body"}))

    repo_full = task["repo_full"]
    token = gh_token.token_for(repo_full)
    remote = gh_token.git_remote(repo_full, token)

    WORKDIR.parent.mkdir(parents=True, exist_ok=True)
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)

    clone = subprocess.run(
        ["git", "clone", "--depth", "50", remote, str(WORKDIR)],
        capture_output=True, text=True,
    )
    if clone.returncode != 0:
        log.error("clone failed: %s", clone.stderr[-400:])
        k8shelper.delete_sandbox(task["sandbox_name"])
        sys.exit(1)

    os.environ["GH_TOKEN"] = token
    os.environ["GITHUB_TOKEN"] = token

    os.environ["GIT_AUTHOR_NAME"] = env("GIT_AUTHOR_NAME", "agent")
    os.environ["GIT_AUTHOR_EMAIL"] = env("GIT_AUTHOR_EMAIL", "agent@localhost")
    os.environ["GIT_COMMITTER_NAME"] = env("GIT_COMMITTER_NAME", "agent")
    os.environ["GIT_COMMITTER_EMAIL"] = env("GIT_COMMITTER_EMAIL", "agent@localhost")

    try:
        asyncio.run(run_agent_sdk(_prompt(task), cli_args))
    except Exception as e:  # noqa: BLE001
        log.exception("agent run failed: %s", e)

    k8shelper.delete_sandbox(task["sandbox_name"])
    log.info("done")


async def run_agent_sdk(prompt: str, cli_args: argparse.Namespace | None = None):
    from claude_agent_sdk import ClaudeAgentOptions, query

    system_prompt_path = env("SYSTEM_PROMPT_PATH", "/opt/persona/SYSTEM.md")
    allowed_tools_str = env(
        "ALLOWED_TOOLS",
        "Read,Write,Edit,Bash,Glob,Grep,GitHub,WebSearch,WebFetch",
    )
    allowed_tools = [t.strip() for t in allowed_tools_str.split(",") if t.strip()]

    system_prompt = Path(system_prompt_path).read_text()
    append = (
        cli_args.append_system_prompt
        if cli_args and cli_args.append_system_prompt
        else env("APPEND_SYSTEM_PROMPT", "")
    )
    if append:
        system_prompt += f"\n\n{append}"

    model = (
        cli_args.model
        if cli_args and cli_args.model
        else env("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
    )
    max_turns = (
        cli_args.max_turns
        if cli_args and cli_args.max_turns
        else int(env("CLAUDE_MAX_TURNS", "50"))
    )

    opts = ClaudeAgentOptions(
        cwd=str(WORKDIR),
        system_prompt=system_prompt,
        permission_mode=env("CLAUDE_PERMISSION_MODE", "bypassPermissions"),
        allowed_tools=allowed_tools,
        model=model,
        max_turns=max_turns,
    )

    # Forward relevant env vars to the SDK subprocess so it can read
    # ANTHROPIC_API_KEY, ANTHROPIC_PLUGIN_MARKETPLACES, etc. directly.
    # Any env var matching the configured prefixes is included automatically —
    # no need to add explicit support for each new variable.
    sdk_env = {
        k: v for k, v in os.environ.items()
        if k.startswith(_RELEVANT_ENV_PREFIXES) and v
    }
    if sdk_env:
        opts.env = sdk_env

    # Optional skills preload — comma-separated paths to skill directories
    skills_dir = env("SKILLS_DIR")
    if skills_dir:
        opts.skills_dir = [d.strip() for d in skills_dir.split(",") if d.strip()]

    # Optional MCP server config — JSON string
    mcp_servers = env("MCP_SERVERS")
    if mcp_servers:
        opts.mcp_servers = json.loads(mcp_servers)

    async for msg in query(prompt=prompt, options=opts):
        log.info("agent -> %s", type(msg).__name__)


def _prompt(task: dict) -> str:
    inst = task.get("instruction", "").strip()
    extra = f"\n\nAdditional instruction from the requester: {inst}" if inst else ""
    co_author = env("CO_AUTHOR_NAME", "")
    co_author_line = (
        f"\n5. Commit your changes (co-authored with {co_author})."
        if co_author else "\n5. Commit your changes."
    )
    return f"""Fix GitHub issue/PR #{task['number']} in the cloned repo at the current working directory.

Title: {task['title']}

Description:
{task['body']}{extra}

Steps:
1. Explore the codebase to understand the issue.
2. Make minimal, correct changes.
3. If tests exist, run them and verify they pass.
4. Commit your changes.{co_author_line}
5. Push to a new branch.
6. Create a pull request using the GitHub tool."""


if __name__ == "__main__":
    main()
