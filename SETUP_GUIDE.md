# 🚀 Agent Runner - Complete Setup Guide

## Overview

This guide will help you create a production-ready, general-purpose agent-runner repository that can be deployed to any Kubernetes cluster and integrated with multiple webhook sources (GitHub, GitLab, custom).

## What You'll Get

A complete repository with:
- ✅ **Multi-webhook support**: GitHub, GitLab, custom formats, manual UI
- ✅ **Flexible configuration**: ConfigMaps, Secrets, environment variables
- ✅ **Docker images**: Multi-arch builds pushed to GHCR
- ✅ **Helm chart**: Ready for Kubernetes deployment
- ✅ **CI/CD**: GitHub Actions for automated builds
- ✅ **Documentation**: Comprehensive guides for all components
- ✅ **No hardcoding**: Everything configurable at runtime

## Prerequisites

- **GitHub account** with admin access
- **Docker Hub** or **GitHub Container Registry** access
- **Kubernetes cluster** (local or production)
- **kubectl** configured for your cluster
- **Python 3.12+** (for development)
- **Helm 3.0+** (for deployment)

## Quick Start (5 Minutes)

### Step 1: Initialize Repository

```bash
cd ~/project/agent-runner
python3 scripts/bootstrap.py
```

This creates the complete repository structure with all configuration files, documentation, and CI/CD setup.

### Step 2: Create GitHub Repository

1. Go to https://github.com/new
2. Repository name: `agent-runner`
3. Description: `General-purpose AI code fixing agent`
4. Initialize with: 
   - ✅ README.md
   - ✅ .gitignore (Python)
   - ✅ License: MIT
5. Make it **Public**
6. Click "Create repository"

### Step 3: Push to GitHub

```bash
cd ~/project/agent-runner
git remote add origin git@github.com:duyet/agent-runner.git
git add -A
git commit -m "chore: initialize agent-runner repository"
git push -u origin main
```

### Step 4: Configure GitHub Settings

#### Enable GitHub Actions
- Settings → Actions → General → Workflow permissions
- ✅ **Read and write permissions**

#### Enable GitHub Container Registry
- Repository settings → Packages
- ✅ **Enable GitHub Container Registry**

#### Add Repository Topics
- Settings → General
- Topics: `kubernetes, agent, ai, claude, webhook, automation`

#### Create Environment
- Settings → Environments → New environment
- Name: `production`
- Protection rules: 
  - ✅ Required reviewers
  - ✅ Wait for approval before deploying
  - ✅ Prevent self-reviews

### Step 5: Add Secrets

Go to: Settings → Secrets and variables → Actions → New repository secret

**Required Secrets:**
1. `GITHUB_WEBHOOK_SECRET`: Generate with `openssl rand -hex 32`
2. `LLM_API_KEY`: Your Anthropic API key

**Optional Secrets:**
- `GITLAB_WEBHOOK_SECRET`: For GitLab integration
- `CUSTOM_API_KEY`: For manual triggers

### Step 6: Verify CI/CD

After pushing, the GitHub Actions workflow will automatically:
- Build Docker image
- Push to GHCR
- Tag with version and branch

Check: https://github.com/duyet/agent-runner/actions

## Detailed Setup

### 1. Application Components

The repository consists of:

```
agent-runner/
├── image/                    # Docker image source
│   ├── app/                 # Application code
│   │   ├── agent.py         # Claude Agent SDK runner
│   │   ├── receiver.py      # Webhook receiver
│   │   ├── gh_token.py      # GitHub token management
│   │   ├── k8shelper.py     # Kubernetes helper
│   │   └── common.py        # Shared utilities
│   ├── persona/              # System prompt templates
│   ├── skills/               # Optional skills
│   ├── Dockerfile           # Docker build
│   └── requirements.txt     # Python dependencies
├── charts/                   # Helm chart
│   └── agent-runner/        # Chart templates
├── docs/                     # Documentation
├── config/                   # Configuration templates
├── scripts/                  # Utility scripts
└── .github/workflows/        # CI/CD
```

### 2. Configuration System

**Configuration Priority** (highest to lowest):
1. Environment variables (per-deployment)
2. Kubernetes Secrets
3. Kubernetes ConfigMaps
4. Default values in code

**Key Configuration Files:**
- `config/default.yaml`: Complete configuration template
- `manifest.yaml`: Kubernetes deployment manifest
- `secrets.local.yaml`: Local secrets (git-ignored)

### 3. Docker Build Process

**Automatic** (via GitHub Actions):
```yaml
Push to main → Trigger workflow → Build → Push to GHCR
```

**Manual** (for development):
```bash
cd image
docker buildx build --platform linux/amd64,linux/arm64 \
  -t ghcr.io/duyet/agent-runner:latest \
  -t ghcr.io/duyet/agent-runner:v0.1.0 .
docker push ghcr.io/duyet/agent-runner:latest
```

### 4. Deployment Options

#### Option A: Helm Chart (Recommended)

```bash
# Add Helm repository (if self-hosted)
helm repo add agent-runner https://duyet.github.io/agent-runner

# Install
helm install agent-runner ./charts/agent-runner \
  --namespace agent-runner \
  --create-namespace \
  --set config.service.replicas=2 \
  --set config.sandbox.resources.requests.cpu=400m
```

#### Option B: Kustomize

```bash
kustomize build kustomize/overlays/production | kubectl apply -f -
```

#### Option C: Plain Kubernetes

```bash
kubectl apply -f manifest.yaml
```

## Integration Guides

### GitHub Integration

**Create GitHub App:**
1. Go to https://github.com/settings/apps
2. Click "New GitHub App"
3. Name: `agent-runner`
4. Homepage: `https://github.com/duyet/agent-runner`
5. Webhook URL: `https://github.webhook.your-domain.com/api/v1/webhook`
6. Permissions: Issues, Pull Requests, Contents (Read/Write)
7. Save the webhook secret

**Configure Agent Runner:**
```bash
kubectl create secret generic agent-runner-secret \
  --from-literal=github-webhook-secret=<your-secret> \
  --namespace=agent-runner
```

### GitLab Integration

**Create GitLab Project Access Token:**
1. GitLab → Settings → Access Tokens
2. Token name: `agent-runner`
3. Scopes: api, read_api, read_repository

**Configure Agent Runner:**
```yaml
# In config/production.yaml
gitlab:
  enabled: true
  access_token: "glpat-..."
```

### Custom Webhook Integration

**Send Custom Webhooks:**
```bash
curl -X POST https://your-agent-runner/api/v1/webhook/custom \
  -H "Content-Type: application/json" \
  -H "x-api-key: <your-custom-key>" \
  -d '{
    "repo_full": "owner/repo",
    "clone_url": "https://github.com/owner/repo.git",
    "number": 123,
    "title": "Fix bug",
    "body": "Description...",
    "instruction": "Additional instructions"
  }'
```

## Development Workflow

### 1. Local Development

```bash
# Clone repository
git clone https://github.com/duyet/agent-runner.git
cd agent-runner

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r image/requirements.txt

# Run locally (for testing)
uvicorn image.app.receiver:app --reload
```

### 2. Making Changes

1. Create feature branch: `git checkout -b feature/my-feature`
2. Make changes
3. Test locally
4. Commit: `git commit -m "feat: add my feature"`
5. Push: `git push origin feature/my-feature`
6. Create PR on GitHub

### 3. Testing Changes

```bash
# Test webhook endpoint
curl -X POST http://localhost:8000/api/v1/webhook/github \
  -H "Content-Type: application/json" \
  -d '{"zen": "test"}'

# Test health endpoint
curl http://localhost:8000/healthz
```

### 4. Building Images

**Automatic**: Push to `main` → GitHub Actions builds image

**Manual**:
```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t agent-runner:test .
```

## Production Deployment

### 1. Prepare Secrets

```bash
# Generate secrets
GITHUB_SECRET=$(openssl rand -hex 32)
LLM_KEY="sk-ant-..."

# Create Kubernetes secret
kubectl create secret generic agent-runner-secret \
  --namespace=agent-runner \
  --from-literal=github-webhook-secret="$GITHUB_SECRET" \
  --from-literal=llm-api-key="$LLM_KEY"
```

### 2. Configure Environment

```bash
# Copy default config
cp config/default.yaml config/production.yaml

# Edit configuration
vim config/production.yaml
```

### 3. Deploy

```bash
# Using Helm
helm install agent-runner ./charts/agent-runner \
  -f config/production.yaml \
  --namespace agent-runner \
  --create-namespace

# Using Kustomize
kustomize build kustomize/overlays/production | kubectl apply -f -
```

### 4. Verify Deployment

```bash
# Check pods
kubectl get pods -n agent-runner

# Check logs
kubectl logs -n agent-runner deployment/agent-runner

# Test health endpoint
kubectl -n agent-runner port-forward svc/agent-runner 8080:8080
curl http://localhost:8080/healthz
```

## Advanced Configuration

### Custom System Prompt

Create a ConfigMap with your prompt:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: agent-runner-persona
data:
  SYSTEM.md: |
    You are CodeBot, a Python expert.
    
    Always:
    - Add type hints
    - Include docstrings
    - Write unit tests
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

### Custom Tools

Edit `config/production.yaml`:
```yaml
agent:
  tools: "Read,Write,Edit,Bash,Grep,File,Search,Replace,Test"
```

### MCP Servers

```yaml
agent:
  mcp_enabled: true
  mcp_servers:
    filesystem:
      command: "/usr/local/bin/filesystem-mcp"
      args: "--directory=/workspace"
```

## Troubleshooting

### Issue: Webhooks return 401

**Cause**: Signature mismatch
**Fix**:
```bash
# Verify secret matches GitHub App settings
kubectl get secret agent-runner-secret -n agent-runner \
  -o jsonpath='{.data.github-webhook-secret}'
```

### Issue: Sandbox pods not starting

**Cause**: Image not available
**Fix**:
```bash
# Verify image exists
docker pull ghcr.io/duyet/agent-runner:v0.1.0

# Check imagePullPolicy in deployment
kubectl get deployment agent-runner -n agent-runner -o yaml | grep imagePull
```

### Issue: Agent not responding

**Cause**: LLM API key invalid
**Fix**:
```bash
# Update secret
kubectl create secret generic agent-runner-secret \
  --from-literal=llm-api-key=<new-key> \
  --namespace=agent-runner \
  --dry-run=client

# Restart deployment
kubectl rollout restart deployment/agent-runner -n agent-runner
```

## Next Steps

1. **Complete the bootstrap**: Run `python3 scripts/bootstrap.py`
2. **Create GitHub repo**: Follow the steps above
3. **Add source code**: Copy the enhanced application files
4. **Test locally**: Verify functionality
5. **Push changes**: Trigger CI/CD
6. **Deploy to k3s**: Update duyet/infra to use external image
7. **Configure webhooks**: Set up GitHub App
8. **Test end-to-end**: Verify full workflow

## Support

For issues and questions:
- GitHub Issues: https://github.com/duyet/agent-runner/issues
- Documentation: See `docs/` directory
- Examples: See `examples/` directory

## License

MIT License - See LICENSE file for details
