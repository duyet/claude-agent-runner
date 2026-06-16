"""Agent runner. Clones repo, runs Claude Agent SDK — agent handles everything via tools."""
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


def main() -> None:
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

    # Set git and token env for Claude SDK's GitHub tool
    os.environ["GH_TOKEN"] = token
    os.environ["GITHUB_TOKEN"] = token
    os.environ["GIT_AUTHOR_NAME"] = env("GIT_AUTHOR_NAME", "duyetbot[bot]")
    os.environ["GIT_AUTHOR_EMAIL"] = env("GIT_AUTHOR_EMAIL",
                                         "1064078+duyetbot[bot]@users.noreply.github.com")
    os.environ["GIT_COMMITTER_NAME"] = env("GIT_COMMITTER_NAME", "duyetbot[bot]")
    os.environ["GIT_COMMITTER_EMAIL"] = env("GIT_COMMITTER_EMAIL",
                                            "1064078+duyetbot[bot]@users.noreply.github.com")

    try:
        asyncio.run(run_agent_sdk(_prompt(task)))
    except Exception as e:  # noqa: BLE001
        log.exception("agent run failed: %s", e)

    k8shelper.delete_sandbox(task["sandbox_name"])
    log.info("done")


async def run_agent_sdk(prompt: str):
    from claude_agent_sdk import ClaudeAgentOptions, query

    system_prompt_path = env("SYSTEM_PROMPT_PATH", "/opt/persona/SYSTEM.md")
    allowed_tools = [
        t.strip()
        for t in env("ALLOWED_TOOLS", "Read,Write,Edit,Bash,Glob,Grep,GitHub").split(",")
        if t.strip()
    ]

    opts = ClaudeAgentOptions(
        cwd=str(WORKDIR),
        system_prompt=Path(system_prompt_path).read_text(),
        permission_mode=env("CLAUDE_PERMISSION_MODE", "bypassPermissions"),
        allowed_tools=allowed_tools,
        model=env("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"),
        max_turns=int(env("CLAUDE_MAX_TURNS", "50")),
    )

    # Optional skills preload — comma-separated paths to skill directories
    skills_dir = env("SKILLS_DIR")
    if skills_dir:
        opts.skills_dir = [d.strip() for d in skills_dir.split(",") if d.strip()]

    # Optional MCP server config — JSON string
    mcp_servers = env("MCP_SERVERS")
    if mcp_servers:
        opts.mcp_servers = json.loads(mcp_servers)

    base = env("ANTHROPIC_BASE_URL")
    if base:
        opts.env = {
            "ANTHROPIC_BASE_URL": base,
            "ANTHROPIC_API_KEY": env("ANYROUTER_API_KEY", ""),
        }

    async for msg in query(prompt=prompt, options=opts):
        log.info("agent -> %s", type(msg).__name__)


def _prompt(task: dict) -> str:
    inst = task.get("instruction", "").strip()
    extra = f"\n\nAdditional instruction from the requester: {inst}" if inst else ""
    co_author = env("GIT_AUTHOR_NAME", "duyetbot[bot]")
    return f"""Fix GitHub issue/PR #{task['number']} in the cloned repo at the current working directory.

Title: {task['title']}

Description:
{task['body']}{extra}

Steps:
1. Explore the codebase to understand the issue.
2. Make minimal, correct changes.
3. If tests exist, run them and verify they pass.
4. Commit your changes (co-authored with {co_author}).
5. Push to a new branch.
6. Create a pull request using the GitHub tool."""


if __name__ == "__main__":
    main()
