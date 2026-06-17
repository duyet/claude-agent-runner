# CLAUDE.md — Project Instructions for claude-agent-runner

@docs/configuration.md
@docs/architecture.md

## What This Is

General-purpose Claude Agent SDK runner for Kubernetes. Receives webhook triggers (`/fix` on issue comments), spawns ephemeral Sandbox pods, and lets the agent handle everything via its built-in tools.

**Supports both GitHub and GitLab** (webhook + pull mode). The provider is selected per-task via a `provider` field on the task payload, defaulting to GitHub.

**NOT a code-fixing tool specifically** — it's a general-purpose runner. The default system prompt is embedded in `app/agent.py`. Override via `SYSTEM_PROMPT_PATH` env var or `APPEND_SYSTEM_PROMPT`.

## Repo Layout

```
app/
  __init__.py
  agent.py          # Clone repo → run Claude Agent SDK → delete sandbox
  common.py         # Env helpers, logging, task decoding
  gh_token.py       # GitHub App JWT → installation token (cached, 60-min TTL)
  gl_token.py       # GitLab token + clone-remote helper (analogue of gh_token.py)
  gl_poller.py      # GitLab pull-mode poller (analogue of poller.py)
  k8shelper.py      # Create/delete Sandbox CRs (agents.x-k8s.io/v1alpha1)
  receiver.py       # FastAPI webhook receiver — HMAC verify, /fix extract, CR create

Dockerfile          # Single image, two entrypoints: receiver (default) or agent
pyproject.toml       # Project metadata + dependencies
uv.lock              # Locked dependency versions
.github/
  workflows/
    build-push.yml    # Docker multi-arch CI → ghcr.io
    release-please.yml  # Auto-release on conventional commits
docs/
  architecture.md     # System architecture
  configuration.md    # Runtime env var reference
```

## Architecture

```
GitHub Webhook (issue_comment with /fix)
  ↓ HMAC verify
receiver.py (FastAPI — long-running service)
  ↓ Create Sandbox CR
agent-sandbox operator (kubernetes-sigs/agent-sandbox)
  ↓ Spawn ephemeral pod
agent.py (inside pod — clone repo → run Claude Agent SDK → self-delete)
```

**One image, two entrypoints:**
- Default (`CMD`): `uvicorn app.receiver:app` — webhook receiver
- Sandbox (`command`): `python -m app.agent` — ephemeral agent runner

## Key Files

| File | Purpose |
|------|---------|
| `app/receiver.py` | FastAPI — `/webhook/github` and `/webhook/custom`, HMAC/API key verify |
| `app/agent.py` | Runs in sandbox — clones repo, launches Claude Agent SDK |
| `app/gh_token.py` | GitHub App JWT → installation access token (cached) |
| `app/gl_token.py` | GitLab token + clone-remote helper (analogue of `gh_token.py`) |
| `app/gl_poller.py` | GitLab pull-mode poller (analogue of `poller.py`) |
| `app/k8shelper.py` | Sandbox CR lifecycle — pod template, PVC, env from secret/configmap |
| `app/agent.py` (`DEFAULT_SYSTEM_PROMPT`) | Embedded system prompt (or `SYSTEM_PROMPT_PATH`) |
| `docs/configuration.md` | Full env var reference |

## Env Config Quickref

Full reference at [docs/configuration.md](docs/configuration.md).

**Receiver:** `GITHUB_WEBHOOK_SECRET`, `API_KEY`, `ALLOWED_USERS`, `TRIGGER_PHRASE`

**GitLab:** `GITLAB_TOKEN` (fallback `GL_TOKEN`), `GITLAB_URL` (default `https://gitlab.com`), `GITLAB_WEBHOOK_SECRET`. Pull mode: `PULL_MODE_GITLAB_ENABLED`, `PULL_MODE_GITLAB_PROJECTS`, `PULL_MODE_GITLAB_EVENTS`. The receiver also exposes `/webhook/gitlab` (plain `X-Gitlab-Token` header auth, not HMAC).

**Sandbox pod template:** `SANDBOX_NAMESPACE`, `SANDBOX_IMAGE`, `SANDBOX_SERVICE_ACCOUNT`, `SANDBOX_CPU_REQUEST`, `SANDBOX_MEM_REQUEST`, `SANDBOX_DEADLINE_SECONDS`, etc.

**Agent:** `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `CLAUDE_PERMISSION_MODE`, `CLAUDE_MAX_TURNS`, `ALLOWED_TOOLS`, `SKILLS_DIR`, `SETTING_SOURCES`, `SKILLS`, `PLUGINS`, `MCP_SERVERS`, `SYSTEM_PROMPT_PATH`, `APPEND_SYSTEM_PROMPT`, `ANTHROPIC_PLUGIN_MARKETPLACES`, `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `CO_AUTHOR_NAME`, `GH_APP_ID`, `GH_PRIVATE_KEY`

**AnyRouter / custom LLM:** `ANTHROPIC_BASE_URL` + `ANYROUTER_API_KEY`

**SDK env-forwarding prefixes** (auto-forwarded to the SDK subprocess) now also include `GITLAB_*` and `GL_*`, alongside `ANTHROPIC_*`, `CLAUDE_*`, `ANYROUTER_*`, `GIT_*`, `GH_*`, `SKILLS_*`, `MCP_*`.

**CLI args (override env):** `--model`, `--max-turns`, `--append-system-prompt` — passed via `SANDBOX_CONTAINER_ARGS`

## Rules

1. **No hardcoded values** — all config via env vars. Behavior driven by SYSTEM.md, not Python.
2. **One image, two entrypoints** — receiver (default CMD) and agent (`python -m app.agent`).
3. **GitHub App auth** — JWT-minted installation tokens (60-min TTL, cached 5-min buffer).
4. **Sandbox isolation** — non-root (UID 1000), read-only rootfs, dropped capabilities, activeDeadlineSeconds.
5. **Self-delete** — agent pod deletes its own Sandbox CR on completion or failure.
6. **Semantic commits**: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`.
7. **Public-safe** — no secrets committed. All secrets via Kubernetes Secret + ConfigMap.
