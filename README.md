# Agent Runner - Kubernetes Sandbox Agent Framework

## Overview

Agent Runner is a production-ready, general-purpose **self-improvement agent framework** designed for Kubernetes sandbox environments. It provides a complete system for deploying autonomous AI agents that can receive webhook triggers, spawn isolated Claude Agent SDK sessions, and perform tasks ranging from code fixing to self-improvement.

## What It Is

**Agent Runner is NOT just a code fixing tool** - it's a **general-purpose framework for autonomous agents** that can:

- ✅ **Fix code issues** (bugs, features, refactoring)
- ✅ **Improve itself** (update its own codebase via webhooks)
- ✅ **Perform autonomous tasks** (documentation, testing, analysis)
- ✅ **Process GitHub/GitLab events** (issues, PRs, releases, etc.)
- ✅ **Handle custom workflows** (user-defined tasks via webhooks or UI)
- ✅ **Run in isolated sandboxes** (each task gets a fresh Claude Agent SDK session)

## Key Concept: Self-Improvement Loop

The framework enables agents to improve their own codebase:

```
┌──────────────────────┐
│ Agent Runner Service │ ← Currently fixing code issues
└──────────┬───────────┘
           │
           ▼
    GitHub Webhook: "/fix" comment on agent-runner repo
           │
           ▼
┌──────────────────────┐
│   Fresh Sandbox      │ ← Spawns new agent session
│   (Claude Agent SDK)  │   that can modify the
│                      │   agent-runner's own code!
└──────────┬───────────┘
           │
           ▼
    Modifies agent-runner code
           │
           ▼
    Commits + Push + PR
           │
           ▼
┌──────────────────────┐
│  Agent Runner v0.1.1   │ ← Improved version!
└──────────────────────┘
```

**Self-improvement use cases:**
- **Bug fixes**: Agent fixes bugs in its own codebase
- **Feature additions**: Agent adds new capabilities
- **Optimization**: Agent improves its performance
- **Documentation updates**: Agent updates its own docs
- **Test generation**: Agent creates tests for itself
- **Refactoring**: Agent improves code quality

## Architecture

```
┌─────────────────────┐
│   Webhook Sources    │
│  (GitHub, GitLab,    │
│   Custom, UI)        │
└──────────┬───────────┘
           │
           ▼
┌─────────────────────┐
│   Agent Runner      │ ← Long-running receiver
│   (FastAPI Service)  │
└──────────┬───────────┘
           │
           ▼
┌─────────────────────┐
│   Kubernetes CRD    │ ← agent-sandbox operator
│   (Sandbox pods)    │
└──────────┬───────────┘
           │
           ▼
┌─────────────────────┐
│   Sandbox Pod       │ ← Fresh Claude Agent SDK session
│   - Clone repo       │
│   - Run Claude SDK   │
│   - Make changes     │
│   - Commit & push   │
│   - Create PR       │
│   - Self-delete     │
└─────────────────────┘
```

## Features

### Core Capabilities
- ✅ **Self-Improvement Loop**: Agents can improve their own codebase via webhook triggers
- ✅ **Multi-Purpose Tasks**: Code fixing, documentation, testing, analysis, optimization
- ✅ **Webhook Triggers**: GitHub, GitLab, custom formats, manual UI
- ✅ **Isolated Execution**: Each task runs in a fresh Kubernetes sandbox pod
- ✅ **Flexible Configuration**: System prompts, tools, MCP, skills via ConfigMap/Secrets
- ✅ **Production Ready**: Docker images, Helm charts, Kustomize, CI/CD
- ✅ **No Hardcoding**: Everything configurable at runtime
- ✅ **Comprehensive Logging**: All event types, actions, audit trail

### Self-Improvement Use Cases
**Codebase Evolution:**
- Agent fixes bugs in its own code
- Agent adds new features and capabilities
- Agent refactors and optimizes its code
- Agent updates its own documentation

**Autonomous Testing:**
- Agent creates tests for new features
- Agent runs test suites and fixes failures
- Agent validates its own functionality

**Documentation Updates:**
- Agent updates README files
- Agent generates API documentation
- Agent creates usage examples

### Technical Features
- ✅ **Security**: HMAC verification, API keys, allowlist users
- ✅ **Multi-LLM Support**: Anthropic, OpenAI, custom providers
- ✅ **Runtime Configuration**: Configure tools, skills, MCP at deployment time
- ✅ **Predefined Sets**: Basic tool/skill/MCP sets included, extensible at runtime
- ✅ **MCP Integration**: Model Context Protocol servers for extended capabilities
- ✅ **Skills Framework**: Custom skills for specific tasks
- ✅ **Dynamic Tool Loading**: Load additional tools without code changes
- ✅ **Git Integration**: GitHub, GitLab API support
- ✅ **PR Management**: Automatic pull request creation and management

## Runtime Configuration: Tools, Skills, MCP

### Predefined Basic Sets (Included)

**Default Tools**:
```
Read, Write, Edit, Bash, Glob, Grep, Git, GitHub
```

**Default Skills**:
```
run-tests, commit-conventions, self-fix, analyze
```

**Default MCP Servers**:
```
filesystem: Basic filesystem access
```

### Runtime Extension

**Add More Tools** (via ConfigMap/Secret):
```yaml
# config/production.yaml
agent:
  tools: "Read,Write,Edit,Bash,Grep,Git,File,Search,Replace,Test,HTTP"
```

**Add More Skills** (mounted volume):
```yaml
# Mount custom skills directory
volumeMounts:
- name: custom-skills
  mountPath: /opt/skills
volumes:
- name: custom-skills
  configMap:
    name: agent-runner-skills
```

**Add MCP Servers** (runtime configuration):
```yaml
# config/production.yaml
agent:
  mcp_enabled: true
  mcp_servers:
    filesystem:
      command: "/usr/local/bin/filesystem-mcp"
      args: "--directory=/workspace"
    database:
      command: "/usr/local/bin/database-mcp"
      args: "--connection-string=postgresql://user:pass@localhost/db"
    web:
      command: "/usr/local/bin/web-mcp"
      args: "--allowed-domains=*"
```

### Configuration Priority

```
1. Default Sets (in code) → 2. ConfigMap → 3. Environment Variables → 4. Secrets
```

Each layer can extend or override the previous layer, allowing for flexible runtime configuration without code changes.

## Components

### 1. Receiver Service (`image/app/receiver.py`)
- FastAPI-based webhook receiver
- Supports multiple webhook formats
- Security verification (HMAC, API keys)
- Event routing and validation
- Kubernetes CRD creation

### 2. Agent Runner (`image/app/agent.py`)
- Executes inside Sandbox pods
- Claude Agent SDK integration
- Git operations (clone, commit, push, PR)
- GitHub/GitLab API interactions
- Session lifecycle management

### 3. Kubernetes Integration
- `agent-sandbox` CRD for pod management
- Helm chart for deployment
- Kustomize overlays for environments
- ConfigMaps/Secrets for configuration

### 4. CI/CD
- GitHub Actions for automated builds
- Multi-architecture Docker images
- Automated testing
- GHCR registry integration

## Quick Start

```bash
# Clone repository
git clone https://github.com/duyet/agent-runner.git
cd agent-runner

# Configure environment
cp config/default.yaml config/my-config.yaml
vim config/my-config.yaml  # Edit your settings

# Deploy to Kubernetes
helm install agent-runner ./charts/agent-runner \
  --namespace agent-runner \
  --create-namespace \
  -f config/my-config.yaml

# Or use Kustomize
kustomize build kustomize/overlays/production | kubectl apply -f -
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Webhooks](docs/WEBHOOKS.md)
- [Lifecycle](docs/LIFECYCLE.md)
- [Development](docs/DEVELOPMENT.md)

## License

MIT
