# CI Templates

Reusable CI/CD workflows and hooks for Python projects with **Fake Data Detection**.

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
      enable-fake-data-check: true
      feature-patterns: 'feature,program,arbitrage'
    secrets: inherit
```

### 2. Pre-commit Hook

Copy the hook to your project:

```bash
# From ci-templates repo
cp ~/dev/ci-templates/hooks/pre-commit .git/hooks/
chmod +x .git/hooks/pre-commit

# Or download directly
curl -o .git/hooks/pre-commit https://raw.githubusercontent.com/unohee/ci-templates/main/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

Configure via environment variables:

```bash
# Disable fake data check (not recommended)
export ENABLE_FAKE_DATA_CHECK=false

# Custom feature patterns
export FEATURE_PATTERNS="feature|program|model"

# Custom max lines
export MAX_LINES=1000

# Custom virtual env path
export PROJECT_VENV_PATH=~/my-venv
```

### 3. Fake Data Detector (Standalone)

Copy the detector script for local use:

```bash
mkdir -p scripts/quality
cp ~/dev/ci-templates/scripts/fake_data_detector.py scripts/quality/

# Run manually
python scripts/quality/fake_data_detector.py src/
python scripts/quality/fake_data_detector.py . --ci
python scripts/quality/fake_data_detector.py . --strict
```

## Features

### GitHub Actions Workflow

| Job | Description |
|-----|-------------|
| `fake-data-check` | **NEW** Detects np.random in feature code |
| `lint` | Ruff linting, Black formatting, Bandit security |
| `test` | pytest with coverage reporting |
| `type-check` | mypy type checking |
| `loc-gate` | Maximum lines per file check |
| `quality-gate` | Summary of all checks |

### Pre-commit Hook

1. **Fake Data Detection (CRITICAL)** - Blocks commit if:
   - `np.random.rand/randn/uniform/normal` in feature variables
   - `except: pass` exception hiding

2. **Magic Number Check (WARNING)** - Warns if:
   - Hardcoded ratios like `feature_x = 0.6 * something`

3. **Black Formatting** - Auto-fixes code style

4. **Ruff Linting** - Auto-fixes + syntax check

5. **LOC Gate** - Configurable max lines per file

### Fake Data Detector

Detects patterns that indicate fake/synthetic data in ML training code:

| Pattern | Severity | Example |
|---------|----------|---------|
| `np.random.rand` | CRITICAL | `feature_x = np.random.rand(100)` |
| `np.random.randn` | CRITICAL | `program_data = np.random.randn(n)` |
| `np.random.uniform` | CRITICAL | `arbitrage = np.random.uniform(0, 1, n)` |
| `except: pass` | CRITICAL | Silent exception hiding |
| Magic numbers | WARNING | `feature = 0.6 * base_value` |
| `print("완료")` | WARNING | Fake success messages |

**Allowed contexts** (not flagged):
- Test files (`test_*.py`)
- Seed setting (`random_state=42`, `np.random.seed()`)
- Data shuffling (`shuffle`)

## Inputs

### Workflow Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `python-version` | `'3.12'` | Python version |
| `src-path` | `'src/'` | Source directory |
| `test-path` | `'tests/unit/'` | Test directory |
| `coverage-threshold` | `0` | Minimum coverage % |
| `max-line-count` | `800` | Max lines per file |
| `enable-fake-data-check` | `true` | Enable fake data detection |
| `feature-patterns` | `'feature,program,arbitrage'` | Variable patterns to check |
| `strict-fake-data` | `false` | Treat warnings as errors |

### Environment Variables (Pre-commit)

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_LINES` | `800` | Max lines per file |
| `SRC_PATH` | `src/` | Source directory |
| `ENABLE_FAKE_DATA_CHECK` | `true` | Enable fake data detection |
| `FEATURE_PATTERNS` | `feature\|program\|arbitrage` | Variable patterns (regex) |
| `PROJECT_VENV_PATH` | (auto-detect) | Virtual environment path |

### Environment Variables (Detector Script)

| Variable | Default | Description |
|----------|---------|-------------|
| `FAKE_DATA_FEATURE_PATTERNS` | `feature,program,arbitrage` | Variable patterns (comma-separated) |
| `FAKE_DATA_EXCLUDE_PATHS` | (empty) | Paths to exclude (comma-separated) |

## Why Fake Data Detection?

ML models trained on fake data (e.g., `np.random` generated features) can appear to work during development but fail catastrophically in production. This happened in a real project where:

1. Features like `program_arbitrage` were generated with `np.random.uniform()`
2. Model trained successfully with AUC 0.96
3. In production, model predictions were meaningless
4. Detection: Random data has **skewness ≈ 0** (real data is usually skewed)

This CI check prevents such issues by:
- Blocking commits that use `np.random` for feature generation
- Warning about hardcoded magic numbers in feature code
- Detecting exception hiding (`except: pass`)

## Claude Code Integration

Use the `/setup-cicd` skill to automatically set up CI/CD in any project:

```
/setup-cicd
```

This will:
1. Create `.github/workflows/ci.yml`
2. Install pre-commit hook
3. Add fake data detector script
4. Configure pyproject.toml

## License

MIT
