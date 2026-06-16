# Architecture

## System Architecture

```mermaid
flowchart LR
    subgraph Input["🔵 Inputs (external)"]
        GH["GitHub Webhook<br/>issue_comment"]
        CUSTOM["Custom API<br/>POST /webhook/custom"]
        POLL["GitHub Poller<br/>every 3 min"]
        HERMES["Hermes Agent<br/>Telegram trigger"]
    end

    subgraph Receiver["🔵 Receiver (long-lived Deployment)"]
        V["Verify → Allowlist → Create CR"]
    end

    subgraph CRD["🟡 Sandbox CR (per-task)"]
        POD["spec.podTemplate<br/>PodSpec + envFrom"]
        PVC["spec.volumeClaimTemplates<br/>ephemeral workspace"]
        META["metadata.annotations<br/>repo / issue / reason"]
    end

    subgraph Operator["🔵 agent-sandbox Operator (long-lived)"]
        W["Watch Sandbox CR"]
        S["Spawn ephemeral pod"]
        CL["CR deleted → cleanup pod"]
    end

    subgraph Agent["🟠 Sandbox Pod (ephemeral, one-shot)"]
        GIT["Clone repo"]
        SDK["Claude Agent SDK<br/>headless"]
        SCOPE["Tools / Skills /<br/>Plugins / MCP"]
        DONE["Commit → PR →<br/>Self-delete CR"]
        SDK --- SCOPE
    end

    Input -->|trigger| Receiver
    Receiver -->|create| CRD
    CRD -.->|watch| Operator
    Operator -->|spawn| Agent
    Agent -->|self-delete| CRD
    CRD -.->|cleanup| Operator

    style CRD fill:#1a1a2e,stroke:#e94560
    style Operator fill:#16213e,stroke:#0f3460
    style Agent fill:#3d1a1a,stroke:#e94560
    style Receiver fill:#16213e,stroke:#0f3460
```

## Component Details

### 1. Webhook Receiver (receiver.py)

FastAPI service that runs as a long-lived deployment.

- Verifies GitHub webhook HMAC-SHA256 signatures
- Supports optional API key auth for `/webhook/custom`
- Filters by sender allowlist and trigger phrase
- Creates Sandbox CR via Kubernetes API
- Two endpoints: `/webhook/github` and `/webhook/custom`

### 2. Sandbox CR (k8shelper.py)

Creates Kubernetes Custom Resources of kind `Sandbox` (`agents.x-k8s.io/v1alpha1`).

The CR includes:
- **Pod template**: full PodSpec with security context, resource limits, volumes
- **Volume claim templates**: ephemeral PVC for workspace
- **No ClusterIP service**: sandbox pods are headless

Env vars from Secret (`SANDBOX_SECRET_REF`) and ConfigMap (`SANDBOX_CONFIGMAP_REF`) are injected into the pod automatically.

### 3. Agent (agent.py)

Runs inside each sandbox pod as a one-shot task:

1. Clone the target repo (depth 50)
2. Set `GH_TOKEN` / `GITHUB_TOKEN` for GitHub tool
3. Launch Claude Agent SDK in headless mode with full SDK capabilities:
   - **Tools**: Read, Write, Edit, Bash, Glob, Grep, Git, GitHub, WebSearch, WebFetch, Monitor, Agent
   - **Skills**: Auto-discovered from `.claude/skills/` in the cloned repo
   - **Plugins**: Directories loaded via `SKILLS_DIR` / `PLUGINS` env
   - **MCP servers**: Configured via `MCP_SERVERS` JSON env var
4. Agent explores code, makes changes (governed by `CLAUDE_PERMISSION_MODE`), commits, pushes, creates PR
5. Self-deletes the Sandbox CR on completion → operator cleans up the pod

The agent is configured entirely through env vars — no hardcoded behaviour. All tools, permissions, model selection, and SDK settings come from the environment injected via `envFrom` (Secret + ConfigMap refs in the Sandbox CR).

### 4. GitHub App Auth (gh_token.py)

GitHub App JWT → installation access token flow:

- JWT minted with 9-minute expiry (max allowed: 10 min)
- Installation token cached with 60-min TTL, refreshed 5 min before expiry
- Uses `GH_APP_ID` and `GH_PRIVATE_KEY` env vars

## Data Flow

### GitHub Webhook Flow

```
issue_comment created with /fix
  ↓
HMAC-SHA256 signature verification
  ↓
Sender allowlist check
  ↓
Trigger phrase check (default: /fix)
  ↓
Create Sandbox CR with task payload
  ↓
agent-sandbox operator spawns pod
  ↓
Pod: clone repo → Claude SDK session → fix → commit → push → PR
  ↓
Pod self-deletes Sandbox CR
```

### Custom Webhook Flow

```
POST /webhook/custom
  ↓
API key verification
  ↓
Parse JSON payload
  ↓
Create Sandbox CR (same as GitHub flow)
```

## Security

- **HMAC-SHA256**: GitHub webhook signature verification (timing-safe compare)
- **API key auth**: Optional for `/webhook/custom` endpoint
- **Sender allowlist**: Restrict which GitHub users can trigger
- **Sandbox isolation**:
  - Non-root user (UID 1000)
  - Read-only root filesystem
  - All Linux capabilities dropped
  - No privilege escalation
  - Resource limits on CPU/memory
  - `activeDeadlineSeconds` pod timeout
- **GitHub App auth**: JWT-based with short-lived installation tokens

## Pull Mode Flow (homelab, no public webhook)

GitHub issue created on duyet/infra
  ↓
Poller checks every 3 minutes via GitHub API
  ↓
New issue detected → de-duplicated via persistent state
  ↓
Create Sandbox CR (same path as webhook flow)
  ↓
Agent spawns → analyzes → fixes → commit → PR → self-deletes
  ↓
ArgoCD reconciles duyet/infra → cluster updated
  ↓ (self-improvement loop)
