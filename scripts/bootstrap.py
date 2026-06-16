#!/usr/bin/env python3
"""
Agent Runner Repository Bootstrap Script
Initializes a complete agent-runner repository ready for GitHub
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Colors
GREEN = '\033[0;32m'
YELLOW = '\033[0;33m'
RED = '\033[0;31m'
NC = '\033[0m'

REPO_PATH = Path.home() / "project" / "agent-runner"

def run_command(cmd, description=""):
    """Run shell command and display output"""
    if description:
        print(f"{YELLOW}▶{NC} {description}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"{RED}Error: {result.stderr}{NC}")
            return False
        if result.stdout and description:
            print(result.stdout.strip())
        return True
    except Exception as e:
        print(f"{RED}Exception: {e}{NC}")
        return False

def main():
    print(f"{GREEN}========================================{NC}")
    print(f"{GREEN}Agent Runner Repository Bootstrap{NC}")
    print(f"{GREEN}========================================{NC}\n")

    # Ensure we're in the right directory
    os.chdir(REPO_PATH)
    print(f"{GREEN}✓{NC} Working in: {REPO_PATH}")

    # Initialize git if not already
    if not (REPO_PATH / ".git").exists():
        print(f"{YELLOW}▶{NC} Initializing git repository...")
        run_command("git init", "Initializing git")
        run_command("git branch -M main", "Setting main branch")
        print(f"{GREEN}✓{NC} Git initialized")
    else:
        print(f"{GREEN}✓{NC} Git already initialized")

    # Stage all files
    print(f"{YELLOW}▶{NC} Staging files...")
    run_command("git add -A", "Staging files")

    # Check if there are changes to commit
    result = subprocess.run(
        ["git", "diff", "--staged", "--quiet"],
        capture_output=True
    )

    if result.returncode == 0:  # No staged changes
        print(f"{YELLOW}!{NC} No changes to commit")
    else:
        # Commit changes
        print(f"{YELLOW}▶{NC} Creating initial commit...")
        run_command(
            'git commit -m "chore: initialize agent-runner repository"',
            "Creating initial commit"
        )
        print(f"{GREEN}✓{NC} Initial commit created")

    print(f"\n{GREEN}========================================{NC}")
    print(f"{GREEN}✓ Repository Ready!{NC}")
    print(f"{GREEN}========================================{NC}\n")

    print("Next steps:\n")
    print(f"1. {YELLOW}Create GitHub Repository:{NC}")
    print("   - Go to https://github.com/new")
    print("   - Repository name: agent-runner")
    print("   - Description: General-purpose AI code fixing agent")
    print("   - Initialize with: README.md, .gitignore (Python)")
    print("   - License: MIT")
    print("   - Make it Public")
    print()

    print(f"2. {YELLOW}Initialize Git Remote:{NC}")
    print(f"   git remote add origin git@github.com:duyet/agent-runner.git")
    print(f"   git push -u origin main")
    print()

    print(f"3. {YELLOW}Configure GitHub:{NC}")
    print("   - Settings → Actions → General → Workflow permissions")
    print("   - Enable: 'Read and write permissions'")
    print("   - Settings → Environments → New: 'production'")
    print()

    print(f"4. {YELLOW}Create GitHub App (for GitHub webhooks):{NC}")
    print("   - Go to https://github.com/settings/apps")
    print("   - 'New GitHub App'")
    print("   - Name: agent-runner")
    print("   - Homepage: https://github.com/duyet/agent-runner")
    print("   - Webhook: Active (URL: https://your-domain/api/v1/webhook/github)")
    print("   - Permissions: Issues, Pull Requests, Repository (Contents, Issues, PRs)")
    print("   - Save the Webhook Secret!")
    print()

    print(f"5. {YELLOW}Create GitHub Personal Access Token (for testing):{NC}")
    print("   - Settings → Developer settings → Personal access tokens")
    print("   - Token name: agent-runner")
    print("   - Scopes: repo (full control), admin:repo_hook, workflow")
    print()

    print(f"6. {YELLOW}Add Secrets to GitHub Repository:{NC}")
    print("   - Settings → Secrets and variables → Actions")
    print("   - New repository secret:")
    print("     - Name: GITHUB_WEBHOOK_SECRET")
    print("     - Value: <your-webhook-secret>")
    print("   - New repository secret:")
    print("     - Name: LLM_API_KEY")
    print("     - Value: <your-llm-api-key>")
    print()

    print(f"7. {YELLOW}Enable GitHub Container Registry:{NC}")
    print("   - Repository settings → Packages")
    print("   - Enable GitHub Container Registry")
    print()

    print(f"8. {YELLOW}Add Repository Topics:{NC}")
    print("   - Settings → General")
    print("   - Topics: kubernetes, agent, ai, claude, webhook, automation")
    print()

    print(f"9. {YELLOW}Push to GitHub:{NC}")
    print(f"   git push -u origin main{NC}")
    print()

    print(f"10. {YELLOW}Verify GitHub Actions:{NC}")
    print("    - Go to: https://github.com/duyet/agent-runner/actions")
    print("    - Watch the 'Build and Push Docker Image' workflow")
    print()

if __name__ == "__main__":
    main()
