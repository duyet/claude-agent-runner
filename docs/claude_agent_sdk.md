# Claude Agent SDK on Sandbox Agent Kubernetes

## Overview

This document explains how the Claude Agent SDK runs inside Kubernetes Sandbox pods, how sessions are managed, and how the agent-runner framework orchestrates the entire lifecycle.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Webhook Trigger                          │
│                  (GitHub/GitLab/Custom)                     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Agent Runner Receiver Service                   │
│              (Long-running FastAPI Service)                  │
│  - Validates webhook signature                              │
│  - Extracts task from event                                 │
│  - Creates Sandbox CRD                                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│               agent-sandbox Controller                        │
│              (Kubernetes Operator)                            │
│  - Watches Sandbox CRD                                      │
│  - Spawns ephemeral pods                                    │
│  - Mounts workspace and config                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Sandbox Pod (Ephemeral)                         │
│  - Clones repository                                        │
│  - Installs Claude Agent SDK                                │
│  - Spawns fresh Claude Agent SDK session                    │
│  - Executes task with tools/skills/MCP                      │
│  - Commits and pushes changes                               │
│  - Creates PR                                               │
│  - Self-deletes                                             │
└─────────────────────────────────────────────────────────────┘
```

## Session Management

### 1. Session Creation

Each webhook trigger creates a **completely isolated** Claude Agent SDK session:

```python
# In agent.py, inside the sandbox pod
from claude_agent_sdk import Agent

def create_fresh_session():
    """Create a fresh Claude Agent SDK session"""
    return Agent(
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_API_BASE"),
        model=os.getenv("LLM_MODEL"),
        max_tokens=4096,
        tools=get_allowed_tools(),     # Dynamically configured
        skills=get_enabled_skills(),   # Runtime configuration
        mcp_servers=get_mcp_config()   # Optional MCP servers
    )
```

### 2. Session Isolation

**Key Principle**: Each task gets a brand new session with no memory of previous tasks.

```yaml
# Each Sandbox pod is isolated:
spec:
  containers:
  - name: agent
    env:
    - name: SESSION_ID
      value: "unique-uuid-per-task"
    volumeMounts:
    - name: workspace
      mountPath: /workspace  # Fresh clone each time
```

**Why Fresh Sessions?**
- **Security**: No data leakage between tasks
- **Reliability**: Each task starts clean
- **Debugging**: Clear audit trail per session
- **Resource Management**: Pods self-delete after completion

### 3. Session Lifecycle

```
┌─────────────────┐
│  Webhook Arrive │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Create Sandbox  │ ← agent-runner creates CRD
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Pod Spawns     │ ← controller creates pod
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Clone Repo      │ ← Fresh git clone
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Initialize SDK  │ ← New session created
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Execute Task    │ ← Agent works with tools
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Commit & Push   │ ← Changes saved
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Create PR       │ ← Pull request opened
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Self-Delete     │ ← Pod deletes itself
└─────────────────┘
```

## Tool Integration

### Available Tools

The Claude Agent SDK in sandbox pods has access to these tools:

```python
DEFAULT_TOOLS = [
    "Read",      # Read files
    "Write",     # Write files
    "Edit",      # Edit files (string replacement)
    "Bash",      # Execute shell commands
    "Glob",      # File globbing
    "Grep",      # Search file contents
    "Git",       # Git operations
    "GitHub",    # GitHub API operations
    # ... more tools as configured
]
```

### Tool Configuration

Tools are configured at **runtime** via environment variables:

```yaml
# In Sandbox CRD
spec:
  env:
  - name: ALLOWED_TOOLS
    value: "Read,Write,Edit,Bash,Grep,Git,File,Search,Replace,Test"
  
  - name: ENABLE_CODE_ANALYSIS
    value: "true"
  
  - name: ENABLE_TESTING
    value: "true"
```

### Tool Usage in Agent

```python
# Agent uses tools automatically
agent = Agent(tools=["Read", "Write", "Bash", "GitHub"])

# Agent decides which tools to use based on task
response = agent.run(
    "Fix the authentication bug in login.py"
)

# Behind the scenes, agent might:
# 1. Use Read to examine login.py
# 2. Use Grep to find related code
# 3. Use Edit to fix the bug
# 4. Use Bash to run tests
# 5. Use GitHub to create PR
```

## Skills Integration

### Available Skills

Skills are pre-configured capabilities that the agent can use:

```python
DEFAULT_SKILLS = [
    "run-tests",           # Execute test suites
    "commit-conventions",  # Follow commit conventions
    "self-fix",           # Self-diagnose and fix issues
    "analyze",            # Code analysis
    # ... more skills as configured
]
```

### Skill Configuration

```yaml
# In Sandbox CRD
spec:
  env:
  - name: ENABLED_SKILLS
    value: "run-tests,commit-conventions,self-fix,analyze,refactor"
  
  - name: SKILL_RUN_TESTS_COMMAND
    value: "pytest -v --cov=. --cov-report=html"
```

### Skill Execution

```python
# Skills augment the agent's capabilities
agent = Agent(
    skills=["run-tests", "commit-conventions"]
)

# Agent automatically uses skills when appropriate
response = agent.run(
    "Fix the bug and ensure tests pass"
)

# Agent will:
# 1. Fix the bug using tools
# 2. Use run-tests skill to verify
# 3. Use commit-conventions for commit message
```

## MCP Integration

### MCP Servers

Model Context Protocol (MCP) servers extend agent capabilities:

```yaml
# In Sandbox CRD
spec:
  env:
  - name: MCP_ENABLED
    value: "true"
  
  - name: MCP_SERVERS_CONFIG
    value: |
      {
        "filesystem": {
          "command": "/usr/local/bin/mcp-server-filesystem",
          "args": ["--directory", "/workspace"]
        },
        "github": {
          "command": "/usr/local/bin/mcp-server-github",
          "args": []
        }
      }
```

### MCP Usage

```python
# MCP servers provide enhanced capabilities
agent = Agent(
    mcp_servers={
        "filesystem": {...},
        "github": {...}
    }
)

# Agent can now use MCP-provided tools
response = agent.run(
    "Analyze all PRs in the repository"
)

# Agent will use github MCP to:
# - Fetch PR data
# - Analyze patterns
# - Generate insights
```

## Sandbox Pod Details

### Pod Template

```yaml
apiVersion: agents.x-k8s.io/v1beta1
kind: Sandbox
metadata:
  name: my-task
spec:
  serviceAccountName: agent-sandbox-sa
  agent:
    name: agent-runner
    image: ghcr.io/duyet/agent-runner:latest
  env:
  - name: GITHUB_REPO
    value: "owner/repo"
  - name: LLM_API_KEY
    valueFrom:
      secretKeyRef:
        name: llm-key
        key: api-key
  - name: ALLOWED_TOOLS
    value: "Read,Write,Edit,Bash,Grep,Git,File,Search,Replace,Test"
  tasks:
  - name: fix-issue
    instruction: "Fix the reported issue"
    branchPattern: "fix/issue-{{number}}"
    createPR: true
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 2000m
      memory: 2Gi
  timeout:
    duration: 30m
```

### Volume Mounts

```yaml
volumes:
- name: workspace
  emptyDir: {}
- name: cache
  emptyDir:
    sizeLimit: 5Gi

volumeMounts:
- name: workspace
  mountPath: /workspace
- name: cache
  mountPath: /cache
```

### Security Context

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
  capabilities:
    drop:
    - ALL
    add: []
```

## Execution Flow

### 1. Webhook to Sandbox

```python
# receiver.py - handles webhook
@app.post("/api/v1/webhook/github")
async def github_webhook(event: GitHubEvent):
    # Validate signature
    if not verify_signature(event):
        raise HTTPException(401)
    
    # Extract task
    task = extract_task_from_event(event)
    
    # Create Sandbox CRD
    sandbox = create_sandbox_crd(task)
    k8s_client.create(sandbox)
    
    return {"status": "triggered", "sandbox": sandbox.metadata.name}
```

### 2. Sandbox to Agent

```python
# agent.py - runs inside sandbox pod
def main():
    # Clone repository
    repo = clone_repo(os.getenv("GITHUB_REPO"))
    
    # Create fresh Claude Agent SDK session
    agent = Agent(
        api_key=os.getenv("LLM_API_KEY"),
        tools=get_allowed_tools(),
        skills=get_enabled_skills()
    )
    
    # Execute task
    response = agent.run(
        instruction=task.instruction,
        context=load_context(repo)
    )
    
    # Commit changes
    commit_and_push(repo, response.changes)
    
    # Create PR
    create_pr(repo, task, response)
    
    # Self-delete pod
    delete_self()
```

## Best Practices

### Session Management

1. **Always use fresh sessions**: Never share sessions between tasks
2. **Clean resources**: Ensure pods self-delete after completion
3. **Monitor timeouts**: Set appropriate timeouts for tasks
4. **Log everything**: Capture session logs for debugging

### Tool Configuration

1. **Limit tools**: Only enable needed tools for security
2. **Resource limits**: Set appropriate CPU/memory limits
3. **Error handling**: Handle tool failures gracefully
4. **Audit trail**: Log all tool usage

### MCP Integration

1. **Validate inputs**: Sanitize MCP server responses
2. **Resource limits**: MCP servers should have resource limits
3. **Timeout handling**: Set timeouts for MCP operations
4. **Error recovery**: Handle MCP server failures

### Security

1. **Secrets management**: Use Kubernetes Secrets for credentials
2. **Network policies**: Restrict pod network access
3. **RBAC**: Use minimal permissions for service accounts
4. **Image verification**: Use signed images when possible

## Troubleshooting

### Session Issues

**Problem**: Agent not responding
```bash
# Check pod logs
kubectl logs -n agent-sandbox-system <pod-name>

# Check session initialization
kubectl logs -n agent-sandbox-system <pod-name> | grep "Claude Agent SDK"
```

**Problem**: Tools not working
```bash
# Check tool configuration
kubectl exec -n agent-sandbox-system <pod-name> -- env | grep TOOLS

# Verify tool installation
kubectl exec -n agent-sandbox-system <pod-name> -- python -c "import claude_agent_sdk"
```

### Resource Issues

**Problem**: Pod OOM killed
```bash
# Check resource usage
kubectl top pod -n agent-sandbox-system <pod-name>

# Increase limits in Sandbox CRD
resources:
  limits:
    memory: 4Gi  # Increase from 2Gi
```

### MCP Issues

**Problem**: MCP server not responding
```bash
# Check MCP sidecar logs
kubectl logs -n agent-sandbox-system <pod-name> -c mcp-server-name

# Verify MCP configuration
kubectl exec -n agent-sandbox-system <pod-name> -- cat /etc/mcp/config.json
```

## Example Scenarios

### 1. Simple Bug Fix

```yaml
# Trigger: /fix Fix login bug
apiVersion: agents.x-k8s.io/v1beta1
kind: Sandbox
metadata:
  name: fix-login-bug
spec:
  agent:
    image: ghcr.io/duyet/agent-runner:latest
  env:
  - name: ALLOWED_TOOLS
    value: "Read,Write,Edit,Bash,Grep,Git,Test"
  tasks:
  - instruction: "Fix the authentication bug in login.py"
```

### 2. Comprehensive Refactoring

```yaml
# Trigger: /fix Refactor user module
apiVersion: agents.x-k8s.io/v1beta1
kind: Sandbox
metadata:
  name: refactor-user-module
spec:
  agent:
    image: ghcr.io/duyet/agent-runner:latest
  env:
  - name: ALLOWED_TOOLS
    value: "Read,Write,Edit,Bash,Grep,Git,Test,Analyze,Coverage"
  - name: ENABLED_SKILLS
    value: "run-tests,analyze,refactor"
  tasks:
  - instruction: "Refactor the user module for better performance"
    runTests: true
    runCoverage: true
    analyzeCode: true
```

### 3. MCP-Enhanced Analysis

```yaml
# Trigger: /fix Analyze all PR patterns
apiVersion: agents.x-k8s.io/v1beta1
kind: Sandbox
metadata:
  name: analyze-pr-patterns
spec:
  agent:
    image: ghcr.io/duyet/agent-runner:latest
  env:
  - name: MCP_ENABLED
    value: "true"
  - name: MCP_SERVERS_CONFIG
    value: |
      {"github": {"command": "/usr/local/bin/mcp-server-github"}}
  tasks:
  - instruction: "Analyze patterns across all PRs in the repository"
    useMCP: true
    mcpServers: ["github"]
```

## Advanced Topics

### Custom Tool Development

```python
# Add custom tool to agent
class CustomTool:
    name = "custom_operation"
    
    def __call__(self, parameters):
        # Custom logic
        return result

agent = Agent(tools=[CustomTool()])
```

### Custom Skills

```python
# Define custom skill
def custom_skill(context):
    # Custom logic
    return result

agent = Agent(skills=[custom_skill])
```

### MCP Server Development

```python
# Create custom MCP server
class MyMCPServer:
    def handle_call(self, method, params):
        # Handle MCP method calls
        return response
```

## Conclusion

The Claude Agent SDK on Kubernetes Sandbox provides a powerful, isolated environment for running autonomous agents with:

- **Fresh sessions per task** - No state leakage
- **Configurable tools** - Runtime tool configuration
- **Extensible skills** - Custom skill support
- **MCP integration** - Enhanced capabilities via MCP
- **Self-managing** - Pods self-delete after completion
- **Production ready** - Resource limits, timeouts, security

This architecture ensures reliable, secure, and scalable autonomous agent execution in Kubernetes environments.