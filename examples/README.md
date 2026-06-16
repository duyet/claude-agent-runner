# Agent Runner Examples

This directory contains example Sandbox configurations for various use cases and deployment scenarios.

## Available Examples

### 1. Simple Code Fix (`simple/`)

**Purpose**: Basic code fixing agent with minimal configuration

**Use Cases**:
- Quick bug fixes
- Simple feature additions
- Documentation updates
- Commit message improvements

**Features**:
- Basic tool set (Read, Write, Edit, Bash, Git, GitHub)
- Default system prompt
- Standard resource limits
- 30-minute timeout

**Usage**:
```bash
kubectl apply -f examples/simple/sandbox.yaml
```

**Trigger**:
```bash
# Comment on an issue or PR
/fix Simple description of the issue
```

---

### 2. With Custom Tools (`with-tools/`)

**Purpose**: Enhanced agent with advanced tooling capabilities

**Use Cases**:
- Comprehensive code analysis
- Test coverage reporting
- Static code analysis
- Performance optimization

**Features**:
- Extended tool set (18 tools including Test, HTTP, Analyze, Coverage)
- Advanced system prompt with tool usage guidance
- Higher resource limits (4Gi memory)
- Test result generation
- Coverage reporting
- 45-minute timeout

**Usage**:
```bash
kubectl apply -f examples/with-tools/sandbox.yaml
```

**Tools Available**:
```
Read, Write, Edit, Bash, Glob, Grep, Git, File, Search,
Replace, Test, HTTP, Analyze, Coverage
```

---

### 3. With Custom Skills (`with-skills/`)

**Purpose**: Agent with specialized skills for complex workflows

**Use Cases**:
- Security scanning and fixes
- Code refactoring projects
- Documentation generation
- Performance optimization
- Complex multi-step tasks

**Features**:
- 8 specialized skills (run-tests, security-scan, refactor, etc.)
- Skill-specific configurations
- Sidecar containers for specialized tools
- Comprehensive analysis capabilities
- Security scanning integration
- 60-minute timeout

**Skills Available**:
```
run-tests, commit-conventions, self-fix, analyze,
refactor, document, optimize, security-scan
```

**Usage**:
```bash
kubectl apply -f examples/with-skills/sandbox.yaml
```

**Example Workflow**:
```bash
# Security-focused fix
/fix Security scan reveals XSS vulnerability in login form

# Refactoring task
/fix Refactor user authentication module for better performance

# Documentation task
/fix Generate API documentation for billing module
```

---

### 4. With MCP Servers (`with-mcp/`)

**Purpose**: Agent enhanced with Model Context Protocol servers

**Use Cases**:
- Complex web scraping and analysis
- Database-backed applications
- GitHub-integrated workflows
- Multi-source data analysis
- Web automation and testing

**Features**:
- 5 MCP servers (filesystem, fetch, github, database, web)
- Enhanced capabilities via MCP protocol
- Sidecar containers for each MCP server
- Multi-source information gathering
- Advanced GitHub API integration
- 60-minute timeout

**MCP Servers**:
- **filesystem**: Enhanced file operations
- **fetch**: Web content fetching and conversion
- **github**: Direct GitHub API access
- **database**: Database query and analysis
- **web**: Browser automation and scraping

**Usage**:
```bash
kubectl apply -f examples/with-mcp/sandbox.yaml
```

**Example Tasks**:
```bash
# Web scraping and analysis
/fix Fetch competitor pricing and update our database

# GitHub-integrated fix
/fix Analyze similar issues across all our repos and fix pattern

# Database-backed fix
/fix Fix data migration script based on production schema
```

---

### 5. MCP Server Development (`mcp-server-sandbox/`)

**Purpose**: Specialized environment for developing MCP servers

**Use Cases**:
- Creating new MCP server implementations
- Debugging existing MCP servers
- Adding new tools/resources to MCP servers
- MCP protocol compliance testing
- MCP documentation generation

**Features**:
- MCP server development mode
- Development tooling (Python, Node.js, Go)
- MCP test client sidecar
- MCP inspector for debugging
- Build artifact management
- Comprehensive testing framework
- 90-minute timeout

**Development Environment**:
- Python 3.12
- Node.js 20
- Go 1.21
- Package managers: pip, npm, go
- Debug mode enabled
- Verbose logging

**Usage**:
```bash
kubectl apply -f examples/mcp-server-sandbox/sandbox.yaml
```

**Example Tasks**:
```bash
# Create new MCP server
/fix Create MCP server for Redis operations

# Fix MCP server bug
/fix Fix JSON-RPC response handling in filesystem MCP

# Add MCP tools
/fix Add database migration tools to postgres MCP server
```

---

## Choosing the Right Example

### For Quick Bug Fixes
Use `simple/` - fastest setup, minimal overhead

### For Comprehensive Development
Use `with-tools/` - analysis and testing capabilities

### For Specialized Tasks
Use `with-skills/` - security, refactoring, documentation

### For Complex Workflows
Use `with-mcp/` - multi-source data, external integrations

### For MCP Development
Use `mcp-server-sandbox/` - specialized development environment

---

## Configuration Customization

Each example can be customized by editing the Sandbox YAML:

### Adjust Resources
```yaml
resources:
  requests:
    cpu: "500m"      # Adjust CPU
    memory: "512Mi"  # Adjust memory
```

### Change Timeout
```yaml
timeout:
  duration: "45m"  # Adjust timeout
```

### Add Environment Variables
```yaml
env:
  - name: CUSTOM_VAR
    value: "custom-value"
```

### Mount Additional Volumes
```yaml
volumes:
  - name: custom-volume
    persistentVolumeClaim:
      claimName: my-pvc
```

---

## Common Patterns

### Production Deployment
```yaml
# Add resource limits and security
resources:
  limits:
    cpu: "2000m"
    memory: "4Gi"
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
```

### Development Mode
```yaml
# Enable debugging
env:
  - name: DEBUG
    value: "true"
  - name: LOG_LEVEL
    value: "debug"
```

### Testing Integration
```yaml
# Add test result volume
volumes:
  - name: test-results
    emptyDir:
      sizeLimit: "2Gi"
```

---

## Troubleshooting

### Pod Not Starting
```bash
kubectl get pod -n agent-sandbox-system
kubectl describe pod <pod-name> -n agent-sandbox-system
```

### Check Logs
```bash
kubectl logs -f <pod-name> -n agent-sandbox-system
```

### View Sandbox Status
```bash
kubectl get sandbox -n agent-sandbox-system
kubectl describe sandbox <sandbox-name> -n agent-sandbox-system
```

---

## Best Practices

1. **Start Simple**: Begin with `simple/` and enhance as needed
2. **Monitor Resources**: Adjust limits based on actual usage
3. **Test Thoroughly**: Use `with-tools/` for comprehensive testing
4. **Secure Secrets**: Always use Kubernetes Secrets for sensitive data
5. **Clean Up**: Delete completed Sandboxes to free resources
6. **Version Control**: Keep your Sandbox configs in git
7. **Document Changes**: Add comments for custom configurations

---

## Examples Reference

| Example | CPU | Memory | Timeout | Best For |
|---------|-----|--------|---------|----------|
| simple | 500m-2C | 512Mi-2Gi | 30m | Quick fixes |
| with-tools | 1C-3C | 1Gi-4Gi | 45m | Testing & analysis |
| with-skills | 1.5C-4C | 2Gi-6Gi | 60m | Specialized tasks |
| with-mcp | 1C-3C | 1Gi-4Gi | 60m | Complex workflows |
| mcp-server-sandbox | 2C-4C | 2Gi-6Gi | 90m | MCP development |

---

## Contributing Examples

To contribute a new example:

1. Create a new directory: `examples/your-example/`
2. Add `sandbox.yaml` with proper configuration
3. Document the use case and features
4. Update this README
5. Test the example thoroughly
6. Submit PR with description

Example structure:
```
examples/your-example/
├── sandbox.yaml
├── README.md (optional)
└── config/ (optional)
```

---

## Support

For issues with specific examples:
- Check the example's README (if available)
- Review the main documentation
- Open an issue on GitHub
- Check logs and describe the problem