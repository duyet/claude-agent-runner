# Configuration Reference

All configuration is through environment variables. No YAML config files, no hardcoded values.

## Receiver (long-running service)

| Variable | Default | Description |
|---|---|---|
| `GITHUB_WEBHOOK_SECRET` | — | HMAC-SHA256 secret for GitHub webhook verification |
| `API_KEY` | — | API key for `/webhook/custom` endpoint auth |
| `ALLOWED_USERS` | (all) | Comma-separated GitHub usernames allowed to trigger. Empty = allow all |
| `TRIGGER_PHRASE` | `/fix` | Comment trigger phrase for issue_comment webhook |
| `LOG_LEVEL` | `INFO` | Log level: DEBUG, INFO, WARN, ERROR |

## Kubernetes Sandbox CR (receiver-side)

### Image

| Variable | Default | Description |
|---|---|---|
| `SANDBOX_NAMESPACE` | `agent-sandbox` | Namespace for Sandbox CRs |
| `SANDBOX_IMAGE` | `ghcr.io/duyetbot/claude-agent-runner:latest` | Image for sandbox pods |
| `SANDBOX_IMAGE_PULL_POLICY` | `Always` | Image pull policy |

### Container

| Variable | Default | Description |
|---|---|---|
| `SANDBOX_CONTAINER_NAME` | `agent` | Container name inside pod |
| `SANDBOX_CONTAINER_COMMAND` | `python -m app.agent` | Container entrypoint |
| `SANDBOX_CONTAINER_WORKDIR` | `/workspace` | Working directory |
| `SANDBOX_SERVICE_ACCOUNT` | `claude-agent-runner` | K8s service account |
| `SANDBOX_RUN_AS_USER` | `1000` | Container UID |
| `SANDBOX_RUN_AS_GROUP` | `1000` | Container FS group |
| `SANDBOX_RESTART_POLICY` | `Never` | Pod restart policy |
| `SANDBOX_DEADLINE_SECONDS` | `1200` | Pod timeout |

### Resources

| Variable | Default | Description |
|---|---|---|
| `SANDBOX_CPU_REQUEST` | `200m` | CPU request |
| `SANDBOX_CPU_LIMIT` | `1000m` | CPU limit |
| `SANDBOX_MEM_REQUEST` | `512Mi` | Memory request |
| `SANDBOX_MEM_LIMIT` | `2Gi` | Memory limit |

### Volumes

| Variable | Default | Description |
|---|---|---|
| `SANDBOX_STORAGE_CLASS` | `local-path` | PVC storage class |
| `SANDBOX_WORKSPACE_SIZE` | `2Gi` | PVC size |
| `SANDBOX_PVC_ACCESS_MODE` | `ReadWriteOnce` | PVC access mode |

### Secrets & Config

| Variable | Default | Description |
|---|---|---|
| `SANDBOX_SECRET_REF` | `claude-agent-runner-secret` | Secret name for envFrom |
| `SANDBOX_CONFIGMAP_REF` | `claude-agent-runner-config` | ConfigMap name for envFrom |
| `SANDBOX_APP_LABEL` | `claude-agent-runner` | App label for pod metadata |

## Agent (sandbox pod)

### Authentication

The Agent SDK reads authentication from the pod's environment. Set these via Secret/ConfigMap:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key (direct API or subscription) |
| `ANYROUTER_API_KEY` | API key for AnyRouter (used when ANTHROPIC_BASE_URL is set) |

For cloud provider auth, set the corresponding env vars in the pod (SDK auto-detects):

| Variable | Provider |
|---|---|
| `CLAUDE_CODE_USE_BEDROCK=1` + AWS credentials | Amazon Bedrock |
| `CLAUDE_CODE_USE_VERTEX=1` + GCP credentials | Google Vertex AI |
| `CLAUDE_CODE_USE_FOUNDRY=1` + Azure credentials | Azure AI Foundry |
| `CLAUDE_CODE_USE_ANTHROPIC_AWS=1` + AWS credentials | Claude Platform on AWS |

### Model & Behavior

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5-20250929` | Model ID |
| `ANTHROPIC_BASE_URL` | — | Custom base URL (e.g. `https://anyrouter.dev/api`). SDK appends `/v1/messages` |
| `CLAUDE_PERMISSION_MODE` | `bypassPermissions` | Permission mode: bypassPermissions, dontAsk, acceptEdits, default |
| `CLAUDE_MAX_TURNS` | `50` | Max conversation turns |

### Tools

| Variable | Default | Description |
|---|---|---|
| `ALLOWED_TOOLS` | `Read,Write,Edit,Bash,Glob,Grep,GitHub,WebSearch,WebFetch` | Comma-separated allowed tools |

Available tools: Read, Write, Edit, Bash, Glob, Grep, Git, GitHub, WebSearch, WebFetch, Monitor, Agent

### Skills & MCP

| Variable | Default | Description |
|---|---|---|
| `SKILLS_DIR` | — | Comma-separated paths to skill directories |
| `MCP_SERVERS` | — | JSON object of MCP server configs |
| `SYSTEM_PROMPT_PATH` | `/opt/persona/SYSTEM.md` | Path to system prompt file |

### Git

| Variable | Default | Description |
|---|---|---|
| `GIT_AUTHOR_NAME` | `agent` | Git author name for commits |
| `GIT_AUTHOR_EMAIL` | `agent@localhost` | Git author email |
| `GIT_COMMITTER_NAME` | `agent` | Git committer name |
| `GIT_COMMITTER_EMAIL` | `agent@localhost` | Git committer email |
| `CO_AUTHOR_NAME` | — | Co-author trailer added to commit messages |

### GitHub App

| Variable | Required | Description |
|---|---|---|
| `GH_APP_ID` | Yes | GitHub App ID |
| `GH_PRIVATE_KEY` | Yes | GitHub App private key (PEM, newlines as `\n`) |

### Task

| Variable | Description |
|---|---|
| `TASK_JSON` | Base64-encoded task payload (injected by receiver) |
