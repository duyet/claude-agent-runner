# CLAUDE.md — Project Instructions for claude-agent-runner

@docs/ARCHITECTURE.md
@docs/CLAUDE_AGENT_SDK.md

## What This Is

General-purpose Claude Agent SDK runner for Kubernetes. Receives GitHub webhook triggers (`/fix` on issue comments), spawns ephemeral Sandbox pods, and lets the agent handle everything via its built-in tools (Read/Write/Edit/Bash/Glob/Grep/GitHub).

**NOT a code-fixing tool specifically** — it's a general-purpose runner. The system prompt (persona/SYSTEM.md) tells the agent what to do. Change the prompt, change the behavior.

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
    build-push.yml    # Multi-arch CI → ghcr.io/duyetbot/claude-agent-runner
docs/
  ARCHITECTURE.md     # System architecture deep-dive
  CLAUDE_AGENT_SDK.md # Agent SDK session lifecycle
  CONFIGURATION.md    # Runtime config reference
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
- Sandbox (`command`): `python -m app.agent` — ephemeral fix runner

## Key Files

| File | Purpose |
|------|---------|
| `app/receiver.py` | FastAPI service — handles `/webhook/github` POST, verifies HMAC, extracts `/fix` tasks, creates Sandbox CR |
| `app/agent.py` | Runs inside sandbox — clones repo (depth 50), sets `GH_TOKEN`/`GITHUB_TOKEN`, launches Claude Agent SDK |
| `app/gh_token.py` | GitHub App auth — JWT → installation access token, cached per repo, refreshed 5min before expiry |
| `app/k8shelper.py` | Sandbox CR lifecycle — pod template with security context, PVC, env from secret/configmap |
| `app/common.py` | Shared helpers — `get_logger()`, `env()`, `load_task()` (decodes base64 TASK_JSON) |
| `persona/SYSTEM.md` | Agent system prompt — tells agent to use GitHub/shell tools, commit co-authored, create PR |
| `.github/workflows/build-push.yml` | CI — multi-arch build (linux/amd64, linux/arm64) → ghcr.io |

## Env Config

All config via env vars (no hardcoded values in Python):

**Receiver:**
- `GITHUB_WEBHOOK_SECRET` — HMAC-SHA256 secret
- `ALLOWED_USERS` — comma-separated, e.g. `duyet,duyetbot`
- `TRIGGER_PHRASE` — default `/fix`

**Sandbox pod template (receiver-side):**
- `SANDBOX_NAMESPACE` — namespace for sandbox CRs, default `agent-sandbox`
- `SANDBOX_IMAGE` — image for sandbox pods, default `ghcr.io/duyetbot/claude-agent-runner:latest`
- `SANDBOX_IMAGE_PULL_POLICY` — default `Always`
- `SANDBOX_SERVICE_ACCOUNT` — k8s service account, default `agent-runner`
- `SANDBOX_DEADLINE_SECONDS` — pod timeout, default `1200`
- `SANDBOX_CPU_REQUEST` — default `200m`
- `SANDBOX_CPU_LIMIT` — default `1000m`
- `SANDBOX_MEM_REQUEST` — default `512Mi`
- `SANDBOX_MEM_LIMIT` — default `2Gi`
- `SANDBOX_RUN_AS_USER` — container UID, default `1000`
- `SANDBOX_RUN_AS_GROUP` — container FS group, default `1000`
- `SANDBOX_STORAGE_CLASS` — PVC storage class, default `local-path`
- `SANDBOX_WORKSPACE_SIZE` — PVC size, default `2Gi`

**Sandbox agent:**
- `TASK_JSON` — base64-encoded task (injected by receiver via Sandbox CR env)
- `GH_APP_ID` — GitHub App ID (required)
- `GH_PRIVATE_KEY` — GitHub App private key (required)
- `ANTHROPIC_MODEL` — default `claude-sonnet-4-5-20250929`
- `ANTHROPIC_BASE_URL` — optional, for routed/alternative LLM providers
- `ANYROUTER_API_KEY` — API key for the base URL provider
- `CLAUDE_PERMISSION_MODE` — default `bypassPermissions`
- `CLAUDE_MAX_TURNS` — default `50`

**Sandbox pod gets all secrets/configs via:**
- `secretRef: agent-runner-secret` → env vars from Kubernetes Secret
- `configMapRef: agent-runner-config` → env vars from ConfigMap

## System Prompt (persona/SYSTEM.md)

Tells the agent to:
- Use GitHub/shell tools for everything (explore, fix, commit, push, PR)
- Write minimal diffs, don't break tests
- Report concisely: what found, what changed, PR link

Change this file to change agent behavior. No Python changes needed.

## Install / Deploy

```bash
# Build image
docker build -t ghcr.io/duyetbot/claude-agent-runner:latest .

# Deploy to k3s (via homelab infra — charts/helm in duyet/infra repo)
# See: duyet/infra → homelab/agent-sandbox/agent-runner/
```

CI: pushes to `main` or `v*` tags trigger multi-arch build to `ghcr.io/duyetbot/claude-agent-runner`.

## Rules

1. **General purpose, no hardcode** — all config via env vars. Agent behavior driven by SYSTEM.md prompt, not Python.
2. **One image, two entrypoints** — receiver (default CMD) and agent (`python -m app.agent`).
3. **GitHub App auth** — JWT-minted installation tokens (60-min TTL, cached with 5-min buffer).
4. **Sandbox isolation** — non-root (UID 1000), read-only rootfs, dropped capabilities, `activeDeadlineSeconds`.
5. **Self-delete** — agent pod deletes its own Sandbox CR on completion or clone failure.
6. **Semantic commits**: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`.
7. **Public-safe** — no secrets committed. All secrets via Kubernetes Secret + ConfigMap.
