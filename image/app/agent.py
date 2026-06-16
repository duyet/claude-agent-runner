"""Self-fix runner. Executes inside a Sandbox pod:

clone -> create branch -> run Claude Agent SDK (headless) -> commit -> push -> open PR.
"""
import asyncio
import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import gh_token, k8shelper
from .common import env, get_logger, load_task

log = get_logger("agent")
WORKDIR = Path("/workspace/repo")
SKILLS_SRC = Path("/opt/skills")


def sh(args, **kw):
    log.info("$ %s", " ".join(args))
    return subprocess.run(args, cwd=str(WORKDIR), capture_output=True, text=True, check=False, **kw)


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
    log.info("clone rc=%d %s", clone.returncode, clone.stderr[-400:])
    if clone.returncode != 0:
        _comment(task, token, f"clone failed:\n```\n{clone.stderr[-1000:]}\n```")
        k8shelper.delete_sandbox(task["sandbox_name"])
        sys.exit(1)

    branch = f"pr-{task['number']}" if task.get("is_pr") else f"fix/issue-{task['number']}"
    _git(["remote", "set-url", "origin", f"https://github.com/{repo_full}.git"])  # strip token
    _git(["config", "user.name", "duyetbot[bot]"])
    _git(["config", "user.email", "1064078+duyetbot[bot]@users.noreply.github.com"])
    _git(["checkout", "-B", branch])
    _seed_skills()  # project-local skills for the SDK to discover; never committed

    try:
        asyncio.run(run_agent_sdk(_build_prompt(task)))
    except Exception as e:  # noqa: BLE001
        log.exception("agent run failed: %s", e)

    # commit anything the agent left uncommitted
    status = _git(["status", "--porcelain"])
    if status.stdout.strip():
        _git(["add", "-A"])
        _git(["commit", "-m", _commit_msg(task)])

    # push (re-inject token for the push only)
    subprocess.run(["git", "-C", str(WORKDIR), "remote", "set-url", "origin", remote],
                   capture_output=True)
    push = subprocess.run(["git", "-C", str(WORKDIR), "push", "-u", "origin", branch],
                          capture_output=True, text=True)
    log.info("push rc=%d %s", push.returncode, push.stderr[-400:])

    if push.returncode == 0:
        pr_url = None if task.get("is_pr") else _create_pr(task, token, branch)
        _comment(task, token, f"Applied a fix on `{branch}`." + (f"\nPull request: {pr_url}" if pr_url else ""))
    elif not status.stdout.strip():
        _comment(task, token, "No changes produced. The agent could not determine a fix; see sandbox logs.")
    else:
        _comment(task, token, f"push failed:\n```\n{push.stderr[-1000:]}\n```")

    k8shelper.delete_sandbox(task["sandbox_name"])
    log.info("done")


def _git(args):
    return sh(["git", "-C", str(WORKDIR), *args])


def _seed_skills() -> None:
    """Copy bundled skills into the repo's .claude/skills (cwd-discovered by the SDK),
    and add a local-only git exclude so they are never committed."""
    if not SKILLS_SRC.exists():
        return
    dest = WORKDIR / ".claude" / "skills"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SKILLS_SRC, dest, dirs_exist_ok=True)
    exclude = WORKDIR / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with open(exclude, "a") as f:
        f.write("\n.claude/\n")


async def run_agent_sdk(prompt: str):
    from claude_agent_sdk import ClaudeAgentOptions, query

    opts = ClaudeAgentOptions(
        cwd=str(WORKDIR),
        system_prompt=Path("/opt/persona/SYSTEM.md").read_text(),
        permission_mode=env("CLAUDE_PERMISSION_MODE", "bypassPermissions"),
        allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "GitHub"],
        model=env("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"),
        max_turns=int(env("CLAUDE_MAX_TURNS", "30")),
        skills="all" if (WORKDIR / ".claude" / "skills").exists() else None,
    )
    base = env("ANTHROPIC_BASE_URL")
    if base:
        # Route Claude Code through the Anthropic-compatible gateway (e.g. AnRouter).
        # The key is sourced from ANYROUTER_API_KEY (homelab convention, never inline)
        # and exposed to Claude Code as its native ANTHROPIC_API_KEY.
        opts.env = {"ANTHROPIC_BASE_URL": base, "ANTHROPIC_API_KEY": env("ANYROUTER_API_KEY", "")}

    async for msg in query(prompt=prompt, options=opts):
        log.info("agent -> %s", type(msg).__name__)


def _build_prompt(task: dict) -> str:
    kind = "PR" if task.get("is_pr") else "issue"
    inst = task.get("instruction", "").strip()
    extra = f"\n\nAdditional instruction from the requester: {inst}" if inst else ""
    return f"""You are fixing GitHub {kind} #{task['number']} in the repository at the current working directory.

Title: {task['title']}

Description:
{task['body']}{extra}

Approach:
1. Explore the repo to find the relevant code.
2. Make minimal, correct changes that address the request.
3. If the repo has tests, run them and make sure they pass (use the run-tests skill if present).
4. Follow the repo's commit conventions (use the commit-conventions skill).
5. Leave your changes committed in the working tree. Do NOT push or open a PR yourself.

Keep changes focused. Do not reformat unrelated code."""


def _commit_msg(task: dict) -> str:
    co1 = env("CO_AUTHOR_1", "duyetbot <bot@duyet.net>")
    co2 = env("CO_AUTHOR_2", "minhagent <hi@minhagent.dev>")
    co3 = env("CO_AUTHOR_3", "Claude <noreply@anthropic.com>")
    return (
        f"fix(agent): address #{task['number']} {task['title'][:60]}\n\n"
        f"Via agent-runner (Claude Agent SDK).\n\n"
        f"Co-Authored-By: {co1}\n"
        f"Co-Authored-By: {co2}\n"
        f"Co-Authored-By: {co3}"
    )


def _create_pr(task: dict, token: str, branch: str):
    import httpx
    owner, repo = task["repo_full"].split("/")
    co1 = env("CO_AUTHOR_1", "duyetbot").split("<")[0].strip()
    co2 = env("CO_AUTHOR_2", "minhagent").split("<")[0].strip()
    co3 = env("CO_AUTHOR_3", "Claude").split("<")[0].strip()
    body = {
        "title": f"fix(agent): {task['title'][:60]}",
        "head": branch,
        "base": task["default_branch"],
        "body": f"Closes #{task['number']}\n\nVia agent-runner (Claude Agent SDK).\n\nCo-authors: {co1}, {co2}, {co3}\n\n{task.get('reason', '')}",
    }
    r = httpx.post(f"https://api.github.com/repos/{owner}/{repo}/pulls",
                   headers=gh_token.api_headers(token), json=body, timeout=30)
    if r.status_code in (200, 201):
        return r.json().get("html_url")
    log.warning("create PR %d %s", r.status_code, r.text[:300])
    return None


def _comment(task: dict, token: str, body: str):
    import httpx
    owner, repo = task["repo_full"].split("/")
    r = httpx.post(
        f"https://api.github.com/repos/{owner}/{repo}/issues/{task['number']}/comments",
        headers=gh_token.api_headers(token), json={"body": body}, timeout=30,
    )
    log.info("comment rc=%d", r.status_code)


if __name__ == "__main__":
    main()
