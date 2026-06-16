# CLAUDE.md — Project Instructions for claude-agent-runner

@docs/configuration.md
@docs/architecture.md

## What This Is

General-purpose Claude Agent SDK runner for Kubernetes. Receives webhook triggers (`/fix` on issue comments), spawns ephemeral Sandbox pods, and lets the agent handle everything via its built-in tools.

**NOT a code-fixing tool specifically** — it's a general-purpose runner. The system prompt (persona/SYSTEM.md) controls agent behavior. Change the prompt, change the behavior.

## Repo Layout

```
app/
  __init__.py
  agent.py          # Clone repo → run Claude Agent SDK → delete sandbox
  common.py         # Env helpers, logging, task decoding
  gh_token.py       # GitHub App JWT → installation token (cached, 60-min TTL)
  k8shelper.py      # Create/delete Sandbox CRs (agents.x-k8s.io/v1alpha1)
  receiver.py       # FastAPI webhook receiver — HMAC verify, /fix extract, CR create
persona/
  SYSTEM.md         # Agent system prompt — controls behavior
Dockerfile          # Single image, two entrypoints: receiver (default) or agent
requirements.txt    # Python deps
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
| `app/k8shelper.py` | Sandbox CR lifecycle — pod template, PVC, env from secret/configmap |
| `persona/SYSTEM.md` | Agent system prompt |
| `docs/configuration.md` | Full env var reference |

## Env Config Quickref

Full reference at [docs/configuration.md](docs/configuration.md).

**Receiver:** `GITHUB_WEBHOOK_SECRET`, `API_KEY`, `ALLOWED_USERS`, `TRIGGER_PHRASE`

**Sandbox pod template:** `SANDBOX_NAMESPACE`, `SANDBOX_IMAGE`, `SANDBOX_SERVICE_ACCOUNT`, `SANDBOX_CPU_REQUEST`, `SANDBOX_MEM_REQUEST`, `SANDBOX_DEADLINE_SECONDS`, etc.

**Agent:** `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `CLAUDE_PERMISSION_MODE`, `CLAUDE_MAX_TURNS`, `ALLOWED_TOOLS`, `SKILLS_DIR`, `MCP_SERVERS`, `SYSTEM_PROMPT_PATH`, `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `CO_AUTHOR_NAME`, `GH_APP_ID`, `GH_PRIVATE_KEY`

**AnyRouter / custom LLM:** `ANTHROPIC_BASE_URL` + `ANYROUTER_API_KEY`

## Rules

1. **No hardcoded values** — all config via env vars. Behavior driven by SYSTEM.md, not Python.
2. **One image, two entrypoints** — receiver (default CMD) and agent (`python -m app.agent`).
3. **GitHub App auth** — JWT-minted installation tokens (60-min TTL, cached 5-min buffer).
4. **Sandbox isolation** — non-root (UID 1000), read-only rootfs, dropped capabilities, activeDeadlineSeconds.
5. **Self-delete** — agent pod deletes its own Sandbox CR on completion or failure.
6. **Semantic commits**: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`.
7. **Public-safe** — no secrets committed. All secrets via Kubernetes Secret + ConfigMap.
