# CI Templates

Reusable CI/CD workflows and hooks for Python projects.

## Quick Start

### 1. GitHub Actions (Reusable Workflow)

Create `.github/workflows/ci.yml` in your project:

```yaml
name: CI
on:
  push:
    branches: [main, develop, 'feature/**']
  pull_request:
    branches: [main, develop]
  workflow_dispatch:

jobs:
  ci:
    uses: unohee/ci-templates/.github/workflows/python-ci.yml@main
    with:
      python-version: '3.12'
      src-path: 'src/'
      test-path: 'tests/unit/'
      coverage-threshold: 0
      max-line-count: 800
    secrets: inherit
```

### 2. Pre-commit Hook

Copy the hook to your project:

```bash
cp ~/dev/ci-templates/hooks/pre-commit .git/hooks/
chmod +x .git/hooks/pre-commit
```

Or with environment configuration:

```bash
# Set custom virtual env path
export PROJECT_VENV_PATH=~/my-venv

# Set custom max lines
export MAX_LINES=1000
```

## Features

### GitHub Actions Workflow

| Job | Description |
|-----|-------------|
| `lint` | Ruff linting, Black formatting, Bandit security |
| `test` | pytest with coverage reporting |
| `type-check` | mypy type checking |
| `loc-gate` | Maximum lines per file check |
| `quality-gate` | Summary of all checks |

### Pre-commit Hook

- Black auto-formatting
- Ruff auto-fix + syntax check
- Python compile check
- LOC gate (configurable max lines)
- Auto-stages fixed files

## Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `python-version` | `'3.12'` | Python version |
| `src-path` | `'src/'` | Source directory |
| `test-path` | `'tests/unit/'` | Test directory |
| `coverage-threshold` | `0` | Minimum coverage % |
| `max-line-count` | `800` | Max lines per file |

## Claude Code Integration

Use the `/setup-cicd` skill to automatically set up CI/CD in any project:

```
/setup-cicd
```

This will:
1. Create `.github/workflows/ci.yml`
2. Install pre-commit hook
3. Add pyproject.toml configurations
