# Agent Runner Configuration Guide

## Overview

Agent Runner is designed to be highly configurable without requiring code changes. All configuration is done through:
- **Environment Variables** (via ConfigMap/Secret)
- **YAML Configuration Files** (mounted as volumes)
- **Runtime Settings** (API-driven, where applicable)

## Configuration Layers

```
1. Default Values (in code)
   ↓
2. ConfigMap (runtime defaults)
   ↓
3. Environment Variables (per-deployment overrides)
   ↓
4. Secrets (sensitive data)
```

## Quick Configuration

### Method 1: Using ConfigMap (Recommended)

```bash
# Edit default configuration
cp config/default.yaml config/my-config.yaml
vim config/my-config.yaml

# Apply ConfigMap
kubectl create configmap agent-runner-config \
  --from-file=config/my-config.yaml \
  --namespace=agent-runner

# Or use kubectl apply
kubectl apply -f config/my-config.yaml
```

### Method 2: Using Environment Variables

Edit `deployments/agent-runner.yaml`:
```yaml
spec:
  template:
    spec:
      containers:
      - name: receiver
        env:
        - name: GITHUB_WEBHOOK_SECRET
          valueFrom:
            secretKeyRef:
              name: agent-runner-secret
              key: github-webhook-secret
        - name: ALLOWED_USERS
          value: "admin,duyet,bot"
```

## Configuration Sections

### 1. Service Configuration

Basic service settings:
- **SERVICE_NAME**: Service name (default: agent-runner)
- **NAMESPACE**: Kubernetes namespace
- **REPLICAS**: Number of receiver pods
- **IMAGE**: Docker image configuration

### 2. Webhook Configuration

Enable/disable webhook sources:
- **WEBHOOK_GITHUB_ENABLED**: Enable GitHub webhooks (default: true)
- **WEBHOOK_GITLAB_ENABLED**: Enable GitLab webhooks (default: false)
- **WEBHOOK_CUSTOM_ENABLED**: Enable custom webhooks (default: true)
- **WEBHOOK_UI_ENABLED**: Enable manual trigger UI (default: true)

### 3. Security Configuration

**Authentication**:
- **GITHUB_WEBHOOK_SECRET**: GitHub HMAC secret (required)
- **GITLAB_WEBHOOK_SECRET**: GitLab webhook token (optional)
- **CUSTOM_API_KEY**: Custom API key for manual triggers

**Authorization**:
- **ALLOWED_USERS**: Comma-separated list of authorized users
- **TRIGGER_PHRASE**: Command to trigger agent (default: "/fix")
- **ISSUE_LABEL**: Label for auto-triggering issues (default: "agent")

### 4. Agent Configuration

**Claude Agent SDK**:
- **MODEL**: LLM model to use (default: "anthropic/claude-sonnet-4.6")
- **MAX_TURNS**: Maximum conversation turns (default: 30)
- **TIMEOUT**: Session timeout in seconds (default: 1200)
- **PERMISSION_MODE**: Permission mode (default: "bypassPermissions")

**Tools**:
- **TOOLS**: Comma-separated list of enabled tools
  - Available: Read, Write, Edit, Bash, Glob, Grep, Git, GitHub
  - Default: "Read,Write,Edit,Bash,Glob,Grep,GitHub"

**Skills**:
- **SKILLS_ENABLED**: Enable skills framework (default: true)
- **SKILLS_PATH**: Path to skills directory (default: /opt/skills)

**MCP Servers**:
- **MCP_ENABLED**: Enable MCP servers (default: false)
- **MCP_SERVERS**: JSON object defining MCP servers

### 5. Sandbox Configuration

**Resources**:
- **SANDBOX_CPU_REQUEST**: CPU request (default: "200m")
- **SANDBOX_CPU_LIMIT**: CPU limit (default: "1000m")
- **SANDBOX_MEMORY_REQUEST**: Memory request (default: "512Mi")
- **SANDBOX_MEMORY_LIMIT**: Memory limit (default: "2Gi")

**Storage**:
- **SANDBOX_STORAGE_SIZE**: Storage size (default: "2Gi")
- **SANDBOX_STORAGE_CLASS**: Storage class (default: "local-path")

**Lifecycle**:
- **SANDBOX_DEADLINE_SECONDS**: Pod lifetime (default: 1200)
- **SANDBOX_SELF_DELETE**: Auto-delete after completion (default: true)

### 6. Git Configuration

**Git Settings**:
- **DEFAULT_BRANCH**: Repository default branch (default: "main")
- **GIT_USER_NAME**: Git user name
- **GIT_USER_EMAIL**: Git user email

**Commit Messages**:
- **COMMIT_MESSAGE_TEMPLATE**: Jinja2 template for commit messages
- **CO_AUTHOR_1**: Primary co-author
- **CO_AUTHOR_2**: Secondary co-author
- **CO_AUTHOR_3**: Tertiary co-author

### 7. LLM Configuration

**Provider Selection**:
- **LLM_PROVIDER**: "anthropic", "openai", or "custom"
- **LLM_BASE_URL**: Custom base URL
- **LLM_API_KEY**: API key (usually from Secret)

**Models**:
- **DEFAULT_MODEL**: Primary model
- **HAIKU_MODEL**: Fast model (for background tasks)
- **SONNET_MODEL**: Balanced model
- **OPUS_MODEL**: Advanced model

### 8. GitHub Integration

**GitHub App**:
- **GITHUB_APP_ID**: GitHub App ID
- **GITHUB_PRIVATE_KEY**: GitHub App private key (multiline)
- **GITHUB_INSTALLATION_TOKEN_TTL**: Token cache TTL

**Supported Events**:
- **SUPPORTED_EVENTS**: List of GitHub event types
- See docs/WEBHOOKS.md for full list

### 9. Ingress Configuration

**TLS**:
- **INGRESS_TLS_ENABLED**: Enable TLS (default: true)
- **INGRESS_TLS_ISSUER**: cert-manager issuer
- **INGRESS_HOSTS**: List of hostnames

**Routing**:
- **INGRESS_CLASS_NAME**: Ingress class (default: "traefik")
- **INGRESS_PATHS**: HTTP path routing rules

## Customization Examples

### Example 1: Custom System Prompt

Create a ConfigMap with your prompt:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: agent-runner-persona
  namespace: agent-runner
data:
  SYSTEM.md: |
    You are CodeBot, an expert Python developer.
    
    Your specialties:
    - Python best practices
    - Type hints and docstrings
    - Test-driven development
    
    Always:
    - Add type hints
    - Write docstrings
    - Include unit tests
    - Follow PEP 8
```

Mount in deployment:
```yaml
volumeMounts:
- name: persona
  mountPath: /opt/persona
volumes:
- name: persona
  configMap:
    name: agent-runner-persona
```

### Example 2: Custom Tools

Enable specific tools:
```yaml
agent:
  tools: "Read,Write,Edit,Bash,Grep,File,Search,Replace"
```

### Example 3: Custom MCP Servers

```yaml
agent:
  mcp_enabled: true
  mcp_servers:
    filesystem:
      command: "/usr/local/bin/filesystem-mcp"
      args: "--directory=/workspace"
    database:
      command: "/usr/local/bin/database-mcp"
      args: "--connection-string=postgresql://..."
```

### Example 4: Custom Co-Authors

```yaml
co_authors:
  co_author_1: "Your Bot <bot@example.com>"
  co_author_2: "Another Author <author@example.com>"
  co_author_3: "Claude <noreply@anthropic.com>"
```

### Example 5: GitLab Integration

```yaml
webhook:
  gitlab:
    enabled: true
    path: /api/v1/webhook/gitlab

gitlab:
  access_token: "glpat-..."
  webhook_token: "..."
```

## Environment Variable Reference

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `GITHUB_WEBHOOK_SECRET` | Secret | Required | GitHub HMAC secret |
| `GITLAB_WEBHOOK_SECRET` | Secret | Optional | GitLab webhook token |
| `CUSTOM_API_KEY` | Secret | Optional | Custom webhook API key |
| `ALLOWED_USERS` | String | "duyet" | Authorized users list |
| `TRIGGER_PHRASE` | String | "/fix" | Trigger command |
| `ISSUE_LABEL` | String | "agent" | Auto-trigger label |
| `MODEL` | String | claude-sonnet-4.6 | LLM model |
| `MAX_TURNS` | Integer | 30 | Max conversation turns |
| `TIMEOUT` | Integer | 1200 | Session timeout (seconds) |
| `PERMISSION_MODE` | String | bypassPermissions | Permission mode |
| `TOOLS` | String | Read,Write,... | Enabled tools |
| `SKILLS_ENABLED` | Boolean | true | Enable skills |
| `MCP_ENABLED` | Boolean | false | Enable MCP servers |
| `SANDBOX_IMAGE` | String | agent-runner:v0.1.0 | Sandbox image |
| `SANDBOX_CPU_REQUEST` | String | 200m | CPU request |
| `SANDBOX_MEMORY_REQUEST` | String | 512Mi | Memory request |
| `SANDBOX_STORAGE_SIZE` | String | 2Gi | Storage size |
| `DEFAULT_BRANCH` | String | main | Git default branch |
| `LLM_PROVIDER` | String | anthropic | LLM provider |
| `LLM_API_KEY` | Secret | Required | LLM API key |
| `GITHUB_APP_ID` | String | Optional | GitHub App ID |
| `GITHUB_PRIVATE_KEY` | Secret | Optional | GitHub App key |
| `INGRESS_ENABLED` | Boolean | true | Enable ingress |
| `INGRESS_HOSTS` | List | [] | Ingress hosts |

## Secret Management

### Creating Secrets

**GitHub Webhook Secret**:
```bash
# Generate random secret
openssl rand -hex 32

# Create Kubernetes Secret
kubectl create secret generic agent-runner-secret \
  --from-literal=github-webhook-secret=<generated-secret> \
  --namespace=agent-runner
```

**LLM API Key**:
```bash
kubectl create secret generic agent-runner-secret \
  --from-literal=llm-api-key=<your-api-key> \
  --namespace=agent-runner
```

**GitHub App Private Key**:
```bash
kubectl create secret generic agent-runner-secret \
  --from-file=github-private-key=~/path/to/private-key.pem \
  --namespace=agent-runner
```

## Validation

### Test Configuration

```bash
# Test webhook endpoint
curl -X POST https://your-agent-runner/api/v1/webhook/github \
  -H "Content-Type: application/json" \
  -d '{"zen": "test"}'

# Check logs
kubectl logs -n agent-runner deployment/agent-runner

# Verify ConfigMap
kubectl get configmap agent-runner-config -n agent-runner -o yaml

# Verify Secrets
kubectl get secret agent-runner-secret -n agent-runner -o yaml
```

### Common Issues

**Issue**: Webhooks returning 401
- **Fix**: Verify GITHUB_WEBHOOK_SECRET matches GitHub App settings

**Issue**: Sandbox pods not starting
- **Fix**: Check SANDBOX_IMAGE is accessible and correct

**Issue**: Agent not responding
- **Fix**: Verify LLM_API_KEY is set and valid

**Issue**: Tools not available
- **Fix**: Check TOOLS environment variable format
