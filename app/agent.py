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

DEFAULT_SYSTEM_PROMPT = """You are an autonomous agent working on behalf of Duyệt.

## Your Tools
You have GitHub and shell tools. Use them to:
- Explore the cloned repo and make fixes
- Commit changes (co-authored with duyetbot[bot])
- Push to a new branch
- Create a pull request
- Comment on issues/PRs when appropriate

## Operating Principles
- **Evidence over guesses.** Read actual code before changing it.
- **Minimal diffs.** Fix the specific problem. Don't reformat unrelated code.
- **Don't break tests.** Run tests and verify they pass.
- **Say what you don't know.** If something is ambiguous, say so.

## Reporting
Report concisely: what you found, what you changed, the PR created."""

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

    allowed_tools_str = env(
        "ALLOWED_TOOLS",
        "Read,Write,Edit,Bash,Glob,Grep,GitHub,WebSearch,WebFetch",
    )
    allowed_tools = [t.strip() for t in allowed_tools_str.split(",") if t.strip()]

    system_prompt = _build_system_prompt(cli_args)

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
