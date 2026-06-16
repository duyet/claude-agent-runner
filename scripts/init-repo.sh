#!/bin/bash
# Agent Runner Repository Initialization Script
# This script creates all necessary files and prepares the repository for GitHub

set -e

echo "🚀 Initializing Agent Runner Repository..."

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Repository info
REPO_NAME="agent-runner"
GITHUB_USER="duyet"
GITHUB_REPO="github.com/${GITHUB_USER}/${REPO_NAME}"

# Check if we're in the right directory
if [[ ! -d "$HOME/project/${REPO_NAME}" ]]; then
    echo -e "${RED}Error: Repository directory not found${NC}"
    echo "Expected: $HOME/project/${REPO_NAME}"
    exit 1
fi

cd "$HOME/project/${REPO_NAME}"

echo -e "${GREEN}✓${NC} Repository directory found"

# Create necessary directories
echo "Creating directory structure..."
mkdir -p {.github/workflows,image/{app,persona,skills},charts/agent-runner/{templates,crds},kustomize/{base,overlays/{production,development}},docs,examples/{k8s,docker-compose,config},config}

echo -e "${GREEN}✓${NC} Directory structure created"

# Initialize git repository if not already initialized
if [[ ! -d .git ]]; then
    echo "Initializing git repository..."
    git init
    git branch -M main
    echo -e "${GREEN}✓${NC} Git repository initialized"
else
    echo -e "${GREEN}✓${NC} Git repository already exists"
fi

# Create .gitignore
echo "Creating .gitignore..."
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
venv/
ENV/
env/

# IDEs
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Kubernetes
*.kubeconfig
*.kubeconfig-*

# Secrets
*.local.yaml
*.local.yml
*.enc.yaml
*.enc.yml
.secrets/
secret*.yaml
secret*.yml

# Logs
*.log

# Temporary files
*.tmp
*.temp
.tmp/
.temp/

# Docker
*.tar
*.tar.gz

# Environment
.env
.env.local
.env.*.local

# Documentation builds
docs/_build/
docs/.doctrees/

# Coverage
htmlcov/
.tox/
.coverage
.coverage.*
.cache
nosetests.xml
coverage.xml
*.cover

# MyPy
.mypy_cache/
.dmypy.json
dmypy.json

# Pyre
.pyre/
.pyre/

# PEP 582
.pec
__pycache__/

# Node (if using Node tools)
node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*
.pnpm-debug.log*

# Editor directories and files
.vscode/*
!.vscode/settings.json
!.vscode/tasks.json
!.vscode/launch.json
!.vscode/extensions.json
.idea
*.suo
*.ntvs*
*.njsproj
*.sln
*.sw?
EOF

echo -e "${GREEN}✓${NC} .gitignore created"

# Create LICENSE
echo "Creating LICENSE..."
cat > LICENSE << 'EOF'
MIT License

Copyright (c) 2024 Duyet Le

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
EOF

echo -e "${GREEN}✓${NC} LICENSE created"

# Create CONTRIBUTING.md
echo "Creating CONTRIBUTING.md..."
cat > CONTRIBUTING.md << 'EOF'
# Contributing to Agent Runner

Thank you for your interest in contributing to Agent Runner!

## Development Setup

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/agent-runner.git`
3. Create a virtual environment: `python -m venv venv && source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Create a branch: `git checkout -b feature/your-feature-name`

## Code Style

- Follow PEP 8 guidelines
- Add type hints to functions
- Include docstrings
- Keep functions focused and modular

## Testing

Before submitting a PR:
- Test your changes locally
- Ensure all tests pass: `pytest`
- Check for linting issues: `ruff check .`
- Format code: `ruff format .`

## Submitting Changes

1. Commit your changes: `git commit -m "feat: your feature"`
2. Push to your fork: `git push origin feature/your-feature-name`
3. Create a Pull Request on GitHub

## Reporting Issues

Found a bug? Have a feature request?
- Open an issue on GitHub
- Provide detailed information
- Include steps to reproduce

## Discussion

For questions and discussion:
- Open a GitHub Discussion
- Check existing documentation first
EOF

echo -e "${GREEN}✓${NC} CONTRIBUTING.md created"

# Create CHANGELOG.md
echo "Creating CHANGELOG.md..."
cat > CHANGELOG.md << 'EOF'
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial release of agent-runner
- GitHub webhook support
- GitLab webhook support
- Custom webhook support
- Manual trigger UI
- Configurable system prompts
- Multi-tool support (Read, Write, Edit, Bash, Grep, GitHub)
- MCP server integration
- Skills framework
- Helm chart for Kubernetes deployment
- GitHub Actions CI/CD

### Changed
- N/A (initial release)

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- HMAC signature verification for webhooks
- Pod security policies (non-root, read-only rootfs)
- Secret management via Kubernetes Secrets
EOF

echo -e "${GREEN}✓${NC} CHANGELOG.md created"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ Repository initialized successfully!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Next steps:"
echo "1. Review the files created"
echo "2. Make any customizations needed"
echo "3. Initialize GitHub repository:"
echo "   - Go to https://github.com/new"
echo "   - Repository name: agent-runner"
echo "   - Description: General-purpose AI code fixing agent"
echo "   - Initialize with README.md"
echo "   - Add .gitignore (Python)"
echo "   - Choose MIT license"
echo ""
echo "4. Run: cd $HOME/project/${REPO_NAME}"
echo "5. Run: git remote add origin git@${GITHUB_REPO}"
echo "6. Run: git add -A"
echo "7. Run: git commit -m 'chore: initial commit'"
echo "8. Run: git push -u origin main'"
echo ""
echo "After pushing, don't forget to:"
echo "- Enable GitHub Actions for CI/CD"
echo "- Create GitHub Packages registry for Docker images"
echo "- Configure repository settings (topics, visibility, etc.)"
echo ""
echo -e "${YELLOW}Note: This script created the foundation. You still need to:${NC}"
echo -e "${YELLOW}  1. Add the actual source code files${NC}"
echo -e "${YELLOW}  2. Create Dockerfile and requirements.txt${NC}"
echo -e "${YELLOW}  3. Add Helm chart templates${NC}"
echo -e "${YELLOW}  4. Set up GitHub Actions workflows${NC}"
echo ""
echo "Check the docs/ directory for detailed documentation."
echo ""