# claude-agent-runner

General-purpose [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) runner for Kubernetes. Receives webhook triggers, spawns ephemeral sandbox pods, and lets the agent work autonomously.

## How It Works

### Architecture Design

<img src="docs/architecture.svg" alt="Architecture Design" width="100%"/>

**Core Components:**

**⚙️ Receiver Service** — Long-running `claude-agent-runner` FastAPI pod with `/webhook/github` and `/webhook/custom` endpoints that calls Kubernetes API to create Sandbox CRs

**🤖 Agent Pod** — Ephemeral sandbox with core components:
- **Claude Agent SDK** — Tool execution (Read, Write, Edit, Bash, GitHub, WebSearch, WebFetch, Glob, Grep)
- **State Manager** — Run and session recording with configurable backend
- **Git Operations** — Clone, commit, push, create PR
- **Self-delete** — Removes Sandbox CR when done

**☸️ Kubernetes** — API server with CRD storage, PVC storage for shared volumes, and operator controller

**💾 State Backend** — Configurable persistence: isolated (ephemeral), shared (PVC + cache), or external (PostgreSQL/Redis)

### Flow Diagram

```mermaid
sequenceDiagram
    participant GH as 📝 GitHub
    participant PL as 🔄 Poller
    participant RP as ∞ Receiver Pod
    participant K8s as ☸️ K8s API
    participant OP as 👁️ Operator
    participant AG as ⏱️ Pod

    Note right of RP: Long-running
    Note right of PL: Pull mode (every 3m)
    Note right of OP: Long-running
    Note right of AG: Ephemeral

    loop Every 3 minutes
        PL->>GH: poll new issues
        GH-->>PL: new issues
        PL->>K8s: create Sandbox CR
    end

    GH->>RP: webhook (/fix comment, optional)
    RP->>RP: verify HMAC
    RP->>K8s: create Sandbox CR
    K8s->>OP: watch event
    OP->>AG: spawn pod
    
    AG->>AG: clone repo
    AG->>AG: run SDK (via AnyRouter)
    AG->>AG: track state

    AG->>K8s: delete Sandbox CR
    Note right of AG: Done
```

**Lifecycle Phases:**

**① Trigger** — GitHub issue with `/fix` comment sends webhook

**② Receiver** — Long-running FastAPI pod verifies HMAC and calls Kubernetes API to create Sandbox CR

**③ Operator** — Agent Sandbox Operator watches for CRs and spawns agent pods

**④ Agent Execution** — Ephemeral pod runs: Clone repository → Claude Agent SDK → State tracking → Git operations → Self-delete

**⑤ Cleanup** — Agent deletes its own Sandbox CR when complete

One Docker image, two entrypoints:
- **Receiver** (default): FastAPI webhook (long-running deployment)
- **Agent** (`python -m app.agent`): runs inside ephemeral sandbox pods

One Docker image, two entrypoints:
- **Receiver** (default): FastAPI webhook (long-running deployment)
- **Agent** (`python -m app.agent`): runs inside ephemeral sandbox pods

## Quickstart

```bash
# Build
docker build -t ghcr.io/duyet/claude-agent-runner:latest .

# Deploy to Kubernetes
helm upgrade --install agent-runner ./charts/agent-runner \
  -n agent-sandbox --create-namespace \
  -f values.yaml -f secrets.local.yaml
```

## Self-Improvement Loop

The runner creates a self-healing cycle for the homelab:

1. **Issue created** on `duyet/infra` GitHub repo
2. **Poller detects** it within 3 minutes (no public webhook needed)
3. **Agent spawns** — clones `duyet/infra`, analyzes the issue
4. **Claude fixes** the infrastructure config (values.yaml, manifests, etc.)
5. **PR opened** on `duyet/infra`
6. **ArgoCD reconciles** the cluster
7. Loop continues

Hermes (the cluster Telegram AI agent) can also trigger runs directly via `POST /api/v1/webhook/custom`.

## Configuration

All configuration is through environment variables. See [docs/configuration.md](docs/configuration.md) for the full reference.

### Required Secrets

Authentication with GitHub — choose either a **GitHub App** (fine-grained, recommended) or a **Personal Access Token** (simpler):

**Option A — GitHub App:**
| Variable | Source | Purpose |
|---|---|---|
| `GH_APP_ID` | GitHub App settings | GitHub App authentication |
| `GH_PRIVATE_KEY` | GitHub App private key | JWT signing for installation tokens |
| `GITHUB_WEBHOOK_SECRET` | GitHub App settings | HMAC webhook verification |

**Option B — Personal Access Token:**
| Variable | Source | Purpose |
|---|---|---|
| `GH_TOKEN` | GitHub Settings → Developer settings | Fine-grained PAT with Contents+Issues+PRs write |
| `GITHUB_WEBHOOK_SECRET` | Your own secret | HMAC webhook verification |

Set `GH_TOKEN` instead of `GH_APP_ID` + `GH_PRIVATE_KEY` for simpler setup. The agent uses whichever is provided.

### Authentication

The agent sandbox needs API credentials. Set these via Kubernetes Secret:

**Claude API (direct):**
```yaml
ANTHROPIC_API_KEY: sk-ant-...
```

**AnyRouter (route through anyrouter.dev):**
```yaml
ANTHROPIC_BASE_URL: https://anyrouter.dev/api
ANYROUTER_API_KEY: sk-ar-...
```

The SDK appends `/v1/messages`, so the base URL must stop at `/api`. Keep the `anthropic-version: 2023-06-01` header — the SDK sends it automatically.

**Cloud providers** (SDK auto-detects from env):
- `CLAUDE_CODE_USE_BEDROCK=1` + AWS credentials → Amazon Bedrock
- `CLAUDE_CODE_USE_VERTEX=1` + GCP credentials → Google Vertex AI
- `CLAUDE_CODE_USE_FOUNDRY=1` + Azure credentials → Azure AI Foundry

### AnyRouter Gateway

Route all LLM calls through [AnyRouter](https://anyrouter.dev) for unified billing:

| Variable | Value |
|---|---|
| `ANTHROPIC_BASE_URL` | `https://anyrouter.dev/api` |
| `ANTHROPIC_API_KEY` | Your AnyRouter key (`sk-ar-...`) |
| `ANTHROPIC_MODEL` | `anthropic/claude-sonnet-4-6` |

Model IDs use `provider/model` format: `anthropic/claude-sonnet-4-6`, `anthropic/claude-haiku-4-5`.

### Permissions & Tools

Default permission mode: `auto` (background safety checks, blocks dangerous actions).

Default allowed tools: `Read,Write,Edit,Bash,Glob,Grep,GitHub,WebSearch,WebFetch`

| Tool | Purpose |
|---|---|
| Read | Read files in working directory |
| Write | Create new files |
| Edit | Edit existing files |
| Bash | Run terminal commands, git, scripts |
| Glob | Find files by pattern |
| Grep | Search file contents with regex |
| Git | Git operations |
| GitHub | GitHub API (PRs, issues, etc.) |
| WebSearch | Search the web |
| WebFetch | Fetch and parse web page content |
| Monitor | Watch background script output |
| Agent | Spawn sub-agents |

Override with `ALLOWED_TOOLS` env var.

### Skills, Plugins & MCP

```yaml
# SDK skill discovery (auto-discovers .claude/skills/ in the cloned repo)
SETTING_SOURCES: user,project
SKILLS: all

# Load skills from directories as plugins (comma-separated paths)
SKILLS_DIR: /opt/skills/custom,/opt/skills/testing

# Extra plugin directories (JSON array)
PLUGINS: '[{"type": "local", "path": "/opt/plugins/my-plugin"}]'

# MCP servers (JSON)
MCP_SERVERS: '{"playwright": {"command": "npx", "args": ["@playwright/mcp@latest"]}}'
```

## Webhook Endpoints

### `POST /api/v1/webhook/github` (also `/webhook/github` for backward compatibility)

GitHub webhook receiver. Verifies HMAC-SHA256, handles `issue_comment` with trigger phrase (default: `/fix`). Creates a Sandbox CR for matching comments.

### `POST /api/v1/webhook/custom` (also `/webhook/custom`)

Generic webhook receiver. Verifies API key (`X-API-Key` header or `api_key` query param). Accepts:

```json
{
  "repo_full": "owner/repo",
  "number": 1,
  "title": "Fix the bug",
  "body": "Description of the issue",
  "instruction": "Extra instructions for the agent"
}
```

### `GET /api/v1/healthz` (also `/healthz`)

Health check — returns `{"ok": true}`.

## Pull Mode (for homelab without public endpoint)

When deployed in a homelab without a public endpoint, GitHub webhooks cannot reach the receiver. In this case, enable **pull mode** to periodically poll the GitHub API instead.

### Configuration

Enable pull mode with environment variables:

| Variable | Default | Description |
|---|---|---|
| `PULL_MODE_ENABLED` | `false` | Enable GitHub API polling mode |
| `PULL_MODE_INTERVAL_MINUTES` | `5` | Polling interval in minutes |
| `PULL_MODE_REPOS` | `""` | Comma-separated repos to poll (e.g., `duyet/infra,duyet/charts`) |
| `PULL_MODE_EVENTS` | `issues,issue_comments` | Event types: `issues`, `issue_comments`, `prs` |

### How Pull Mode Works

1. **Polls GitHub API** every N minutes for configured repos
2. **Issues with label**: Finds issues with the configured `ISSUE_LABEL`
3. **Issue comments**: Searches recent comments for `TRIGGER_PHRASE` (e.g., `/fix`)
4. **Pull requests**: Polls open PRs (if `prs` in `PULL_MODE_EVENTS`)
5. **Deduplication**: Tracks processed items to avoid duplicate Sandbox CRs
6. **State persistence**: Uses `STATE_BACKEND` to remember processed items across restarts

### Example Configuration

```yaml
# ConfigMap
PULL_MODE_ENABLED: "true"
PULL_MODE_INTERVAL_MINUTES: "3"
PULL_MODE_REPOS: "duyet/infra"
PULL_MODE_EVENTS: "issues,issue_comments"
TRIGGER_PHRASE: "/fix"
ISSUE_LABEL: "agent"
ALLOWED_USERS: "duyet,duyetbot"

# Secret (GitHub App authentication - recommended)
GH_APP_ID: "4027770"
GH_PRIVATE_KEY: |
  -----BEGIN RSA PRIVATE KEY-----
  ...
  -----END RSA PRIVATE KEY-----
```

### Authentication

Pull mode supports the same authentication methods as webhook mode:

- **GitHub App** (recommended): Fine-grained, automatic token refresh
- **Personal Access Token**: Simpler but requires manual rotation

The poller automatically refreshes GitHub App installation tokens before they expire.

### State Management

Pull mode relies on `STATE_BACKEND` to track processed items:

- **none** (default): In-memory only, resets on restart
- **file**: Local file storage in `STATE_PATH`
- **postgres** / **redis**: External storage for multi-pod deployments

Use `shared` mode with a PVC for persistent state across pod restarts.



## Sandbox Pod Spec

Each sandbox runs with:
- **Non-root**: UID/GID 1000
- **Read-only rootfs**: prevents system modification
- **No capabilities**: all Linux capabilities dropped
- **No privilege escalation**: `allowPrivilegeEscalation: false`
- **Resource limits**: CPU 200m request / 1000m limit, Memory 512Mi / 2Gi
- **Timeout**: `activeDeadlineSeconds: 1200` (20 min)
- **Ephemeral storage**: 2Gi PVC (deleted with pod)
- **Environment**: all vars from Secret + ConfigMap injected via `envFrom`

## GitHub App Setup

Create a GitHub App with:
- **Permissions**: Contents (R&W), Issues (R&W), Pull requests (R&W)
- **Subscribe to**: `issue_comment` events
- Install on target repos

Set `GH_APP_ID` and `GH_PRIVATE_KEY` in the sandbox Secret.

## Development

```bash
# Install dependencies (requires uv: https://docs.astral.sh/uv/)
uv sync

# Run receiver locally
uv run uvicorn app.receiver:app --reload --port 8080

# Test health
curl http://localhost:8080/healthz

# Run agent locally (with TASK_JSON env)
python -m app.agent
```

## License

MIT
