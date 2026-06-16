# Agent Runner Architecture

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Webhook Sources                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  GitHub  │  │  GitLab  │  │  Custom  │  │    UI    │       │
│  │ Webhooks │  │ Webhooks │  │ Webhooks │  │   Form   │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
└───────┼────────────┼────────────┼────────────┼─────────────────┘
        │            │            │            │
        ▼            ▼            ▼            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Agent Runner Service                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │         FastAPI Webhook Receiver (long-running)          │   │
│  │  - Verify HMAC signatures                                 │   │
│  │  - Parse webhook payloads                                │   │
│  │  - Route to appropriate handlers                         │   │
│  │  - Create Sandbox CRs                                     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                  │
│                              ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │           Kubernetes Custom Resource (Sandbox)          │   │
│  │  - Pod template specification                            │   │
│  │  - Volume claim templates                               │   │
│  │  - Service account & RBAC                                 │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Agent Sandbox Operator                         │
│                   (kubernetes-sigs/agent-sandbox)                 │
│  - Watches for Sandbox CRs                                      │
│  - Creates pods per task                                       │
│  - Manages pod lifecycle                                       │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Sandbox Pod (Ephemeral)                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Claude Agent SDK Session (Fresh)              │   │
│  │  - Clone repository                                       │   │
│  │  - Analyze code                                           │   │
│  │  - Make changes                                           │   │
│  │  - Run tests                                              │   │
│  │  - Commit changes                                        │   │
│  │  - Push to remote                                         │   │
│  │  - Create/update PR                                      │   │
│  │  - Self-delete                                            │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Webhook Receiver Service

**Purpose**: Long-running FastAPI service that receives and processes webhooks

**Key Functions**:
- **Security**: HMAC verification for GitHub/GitLab, API key validation
- **Parsing**: Multi-format webhook payload parsing
- **Routing**: Event type routing to appropriate handlers
- **Validation**: Sender allowlist, action filtering
- **CRD Creation**: Generates Sandbox Custom Resources

**Deployment**: 
- Replicas: 1 (can be scaled)
- Resource requests: CPU 100m, Memory 128Mi
- Resource limits: CPU 500m, Memory 512Mi

### 2. Sandbox Custom Resource

**Purpose**: Kubernetes CRD that defines ephemeral agent sessions

**Spec Fields**:
```yaml
spec:
  podTemplate:      # PodSpec for the sandbox
    metadata:
      labels:
        app: agent-runner
    spec:
      restartPolicy: Never
      containers:
      - name: agent
        image: agent-runner:v0.1.0
        command: ["python", "-m", "app.agent"]
        env:
        - name: TASK_JSON
          value: "<base64-encoded-task>"
        volumeMounts:
        - name: workspace
          mountPath: /workspace
  volumeClaimTemplates:
  - metadata:
      name: workspace
    spec:
      accessModes: [ReadWriteOnce]
      resources:
        requests:
          storage: 2Gi
  service: false  # No clusterIP service needed
```

### 3. Sandbox Pod (Claude Agent SDK Session)

**Lifecycle** (20 minutes max):
1. **Start** → Pull image, mount volumes
2. **Init** → Load task, clone repository
3. **Execute** → Run Claude Agent SDK (max 30 turns)
4. **Commit** → Git commit with formatted message
5. **Push** → Push branch to remote
6. **PR** → Create/update pull request
7. **Cleanup** → Pod deletion (garbage collection)

**Isolation Features**:
- **User**: Non-root (UID 1000)
- **Filesystem**: Read-only root filesystem
- **Capabilities**: All capabilities dropped
- **Privilege**: No privilege escalation
- **Network**: Kubernetes pod network policies (optional)
- **Storage**: Ephemeral PVC (deleted with pod)

## Data Flow

### 1. GitHub Webhook Flow

```
GitHub Event
  ↓
HMAC-SHA256 Signature
  ↓
Agent Runner (verify signature)
  ↓
Parse event (issue_comment, issues, pull_request, etc.)
  ↓
Check sender allowlist
  ↓
Check trigger phrase or label
  ↓
Create Sandbox CR
  ↓
Agent Sandbox Operator sees CR
  ↓
Create Sandbox Pod
  ↓
Pod runs: git clone → Claude SDK → fix → commit → push → PR
  ↓
Pod self-deletes
```

### 2. GitLab Webhook Flow

Similar to GitHub, but:
- Uses HMAC-SHA256 (GitLab token)
- Different event payload structure
- GitLab API for MR operations

### 3. Custom Webhook Flow

```
Custom API Call
  ↓
API Key Verification
  ↓
Parse JSON payload
  ↓
Create Sandbox CR
  ↓
Proceed as GitHub flow
```

### 4. Manual UI Flow

```
User visits /api/v1/trigger
  ↓
Fills form (event_type, content, payload)
  ↓
API Key Verification
  ↓
Create Sandbox CR
  ↓
Proceed as GitHub flow
```

## Configuration Management

### ConfigMap
- **Purpose**: Runtime configuration (no rebuild required)
- **Contents**: Environment variables, feature flags, tool lists
- **Mount**: `/etc/config` or environment variables
- **Hot Reload**: Supported (pod restart required)

### Secret
- **Purpose**: Sensitive data (API keys, tokens)
- **Contents**: GitHub secrets, API keys, credentials
- **Mount**: Environment variables
- **Rotation**: Update secret + rolling restart

### System Prompt
- **Purpose**: Agent behavior and personality
- **Source**: ConfigMap or mounted volume
- **Format**: Markdown file
- **Customization**: Fully customizable per deployment

## Scalability

### Horizontal Scaling

**Webhook Receiver**:
```yaml
# Can scale horizontally
replicas: 3  # Handle more webhooks
```

**Agent Sandbox Operator**:
- Automatically handles concurrent sandboxes
- No limit on parallel pods (resource-based only)

### Resource Limits

**Per Sandbox Pod**:
- CPU: 200m → 1000m (5x burst)
- Memory: 512Mi → 2Gi (4x burst)
- Storage: 2Gi per pod

**Cluster Capacity**:
- Maximum concurrent sandboxes = Node resources / (200m CPU + 512Mi RAM)

## Security Architecture

### 1. Webhook Verification

**GitHub HMAC**:
```
X-Hub-Signature-256: sha256=<signature>
Secret: GITHUB_WEBHOOK_SECRET
Algorithm: HMAC-SHA256
Timing-safe: Yes
```

**GitLab HMAC**:
```
X-Gitlab-Token: <token>
Secret: GITLAB_WEBHOOK_TOKEN
```

**Custom API Key**:
```
X-API-Key: <key>
Secret: CUSTOM_API_KEY
```

### 2. Authorization Layers

**Layer 1 - Signature Verification**:
- Invalid signatures = 401 Unauthorized
- Prevents spoofed webhooks

**Layer 2 - Sender Allowlist**:
- Check `ALLOWED_USERS` environment variable
- Supports bot accounts (duyetbot[bot] → duyetbot)

**Layer 3 - Trigger Phrase**:
- Check comment body starts with `/fix`
- Optional: issue label check

**Layer 4 - Loop Prevention**:
- Agent's own comments never start with `/fix`
- Bot allowlist prevents other bots from triggering

### 3. Pod Security

**Sandbox Pod Isolation**:
- **Non-root user**: UID 1000
- **Read-only rootfs**: Prevents system modification
- **Dropped capabilities**: No Linux capabilities
- **No privilege escalation**: SecurityContext setting
- **Resource limits**: CPU/memory throttling

**Network Policies** (optional):
- Egress only to GitHub/GitLab APIs
- Ingress from webhook receiver only
- Inter-pod communication restrictions

## Failure Modes

### 1. Webhook Delivery Failure

**Scenario**: Agent Runner pod down
- **GitHub**: Retry with exponential backoff (up to 24 hours)
- **Mitigation**: Run 2+ replicas, health checks

### 2. Sandbox Creation Failure

**Scenario**: Kubernetes API unavailable
- **Detection**: 500 Internal Server Error
- **Impact**: Webhook returns error, GitHub retry
- **Mitigation**: Liveness probes, restart policy

### 3. Sandbox Execution Failure

**Scenario**: Agent SDK crash or timeout
- **Detection**: Pod marked as Failed
- **Impact**: No commit/PR, comment added to issue
- **Mitigation**: Retry manually, check logs

### 4. Git Push Failure

**Scenario**: Authentication, network, or conflict
- **Detection**: Non-zero git exit code
- **Impact**: Changes committed locally but not pushed
- **Mitigation**: Manual intervention, check pod logs

## Monitoring & Observability

### Metrics

**Webhook Receiver**:
- Request rate (per event type)
- Success/error rates
- Response times (p50, p95, p99)
- Active sandboxes count

**Sandbox Pods**:
- Creation latency
- Execution time
- Success/failure rate
- Resource usage (CPU, memory, storage)

### Logging

**Structured JSON Logs**:
```json
{
  "level": "info",
  "msg": "github_webhook_received",
  "deliveryId": "12345-67890",
  "event": "issue_comment",
  "action": "created",
  "repo": "owner/repo",
  "sender": "username",
  "installation": 12345678
}
```

**Log Levels**:
- `DEBUG`: Detailed execution flow
- `INFO`: Normal operations (webhooks, sandbox creation)
- `WARN`: Non-critical issues (unauthorized users, skipped events)
- `ERROR`: Failures (sandbox creation, git operations)
- `CRITICAL`: Service failures

## Performance Characteristics

### Latency Breakdown

**Webhook → Sandbox Creation**:
- Webhook receipt: 10ms
- Verification: 5ms
- CR creation: 100ms
- Pod startup: 5-10s (image pull)
- Total: ~10-15s

**Sandbox Execution**:
- Git clone: 2-5s (repo size dependent)
- Agent execution: 10-60s (complexity dependent)
- Commit/push: 2-5s
- PR creation: 1-2s
- Total: ~15-75s per task

### Throughput

**Webhook Receiver**:
- ~100 webhooks/second per replica
- Scale horizontally for higher load

**Sandbox Creation**:
- Limited by k3s API server
- ~10 sandboxes/second burst
- ~1-2 sandboxes/second sustained

**Sandbox Execution**:
- Limited by cluster resources (CPU, memory, storage)
- 100 concurrent sandboxes on 16CPU/12GB node
- Scale horizontally for higher capacity
