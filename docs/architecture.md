# Architecture

## System Architecture

```
GitHub Webhook (issue_comment with /fix)
  ↓ HMAC verify
receiver.py (FastAPI — long-running service)
  ↓ Create Sandbox CR
agent-sandbox operator (kubernetes-sigs/agent-sandbox)
  ↓ Spawn ephemeral pod
agent.py (inside pod — clone repo → run Claude Agent SDK → self-delete)
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
3. Launch Claude Agent SDK with configured tools, skills, MCP
4. Agent explores code, makes changes, commits, pushes, creates PR
5. Self-deletes the Sandbox CR on completion

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
