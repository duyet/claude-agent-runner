# Skills Directory

This directory contains optional skills that can be loaded into the agent-runner at runtime.

## What Are Skills?

Skills are pre-configured capabilities that augment the Claude Agent SDK with specialized functionality. Examples include:

- `run-tests` - Execute test suites
- `commit-conventions` - Follow commit message conventions
- `self-fix` - Self-diagnose and fix issues
- `analyze` - Perform code analysis
- `refactor` - Refactor code
- `document` - Generate documentation
- `optimize` - Performance optimization
- `security-scan` - Security vulnerability scanning

## Adding Skills

To add a skill, create a Python file in this directory:

```python
# my_skill.py
def my_skill(context):
    """
    Implement my custom skill
    """
    # Your skill logic here
    return result
```

Skills are loaded at runtime based on the `ENABLED_SKILLS` environment variable.

## Default Skills

If no skills are specified, the agent will use basic tool-based operation without specialized skills.