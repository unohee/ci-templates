# ci-templates

# ci-templates

Reusable CI for the organisation: **constitution gate** enforcing [`book.md`](https://github.com/unohee/dev_runbook/blob/main/book.md), Python CI, Rust CI, and **fake data detection**.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the layout and the traps.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the layout and the traps.

## Constitution gate — every repository

Language-agnostic. Add this and the Articles are enforced on your repo:

```yaml
# .github/workflows/constitution.yml
name: constitution

on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

# Only a pull request is cancelled when a newer commit arrives. A push gets a group of its
# own: a shared group keeps one running and ONE pending run, and a newer push replaces the
# pending one, so the replaced push's commits would never be checked.
concurrency:
  group: ${{ github.workflow }}-${{ github.event_name == 'pull_request' && github.ref || github.sha }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  gate:
    uses: unohee/ci-templates/.github/workflows/constitution-gate.yml@main
```

**Why these triggers.** Billing is per job, rounded up to the minute, so a duplicate run is
the waste to avoid, not the gate itself.

- Do not list `feature/**`, `fix/**` and similar branches under `push`. Those pushes arrive
  with a pull request, which runs the same commit again.
- `push: [main]` plus `pull_request` gates every commit that lands on `main`, a direct push
  included, and a direct push bills a run (vega-cli, 2026-09-18: 23 direct pushes in one day,
  265 weighted minutes).
- A repository that enforces pull requests through branch protection can drop `push`. One
  without protection should keep it: a direct push the gate never sees is a gate that did
  not run, which book.md Art. VI does not count as a pass.
- The concurrency block is the caller's to own. A reusable workflow cannot set it for the
  caller: inside one, `github.workflow` is the caller's name, so the group would collide with
  the caller's own.

Every input is optional:

| Input | Default | Article |
|---|---|---|
| `loc-ceiling` | `1500` | III — max **code** lines per file (blank/comment excluded) |
| `loc-window-days` | `30` | III — days over the ceiling before it is a breach |
| `loc-exclude` | `''` | III — extra comma-separated path fragments to skip |
| `architecture-depth` | `2` | IV — directory depth treated as "structure" |
| `cxt-version` | `'0.3.0'` | II — pinned `@intrect/cxt` |
| `gates-ref` | `'main'` | which ref the gate scripts come from |
| `runner-label` | `'ubuntu-latest'` | runner label for the gate job |

### What it checks

One job, `Constitution Gate (book.md)`, with one step per gate. Every gate step runs even
when an earlier one failed, so a single red run names all of them. Seven separate jobs
used to bill a minute each for checks that take seconds (2026-10-16, AGT-4747).

| Step | Article | Fails when |
|---|---|---|
| `Art. III — LOC ceiling + 30-day clock` | III | a file has been over the ceiling for more than 30 days. Files inside the window are reported as warnings with the days remaining. |
| `Art. IV — ARCHITECTURE.md present and current` | IV | `ARCHITECTURE.md` is missing, or a PR adds/removes directories without updating it. |
| `§5.5 — no AI co-author trailers` | §5.5 | a commit in the range carries an AI co-author trailer. |
| `Art. II — cxt bs (no CRITICAL smells)` | II | `cxt bs` reports a CRITICAL smell — or scans zero files, which means the gate did not run. |
| `Art. VI — no gate-defeating construct in CI` | VI | a workflow file carries `continue-on-error: true`, `\|\| true`, `\|\| :`, `set +e`, `--exit-zero`, or a `continue-on-error` expression. **No exception mechanism** — if a command's non-zero exit is genuinely not a verdict, move it into a script and read the exit code there. |
| `Art. V — the gates’ own fixture tests` | V | a gate's own fixture test fails — the ruler is broken, so every other result here is unreliable. |
| `Art. VI — every gate ran and passed` | VI | **any** of the above is not `success`, including `skipped`. A cancelled run is cancelled, never green. |

## Python CI — Python repositories

```yaml
jobs:
  ci:
    uses: unohee/ci-templates/.github/workflows/python-ci.yml@main
    with:
      python-version: "3.12"
      runner-label: "ubuntu-latest"
      timeout-minutes: 30
```

All three inputs are optional. `runner-label` defaults to GitHub-hosted Linux; callers with an
approved self-hosted runner can select its custom label explicitly. `timeout-minutes`
defaults to 30 and exists so a hung test cannot bill the 360-minute default. The job installs
the repository's `.[dev]` extra and runs the complete `pytest -q` suite. Give this caller the
same `on:` and `concurrency:` blocks as the constitution caller above.

## Rust CI — Rust repositories

The tests, on the merge result. Trigger it on `pull_request` (which checks out the merge
commit) and `workflow_dispatch`, not on branch pushes:

```yaml
jobs:
  test:
    uses: unohee/ci-templates/.github/workflows/rust-ci.yml@main
    with:
      packages: my-crate
      test-profile: ci-test
      skip-paths: |
        *.md
        docs/*
```

Every input is optional:

| Input | Default | Meaning |
|---|---|---|
| `packages` | `''` | Space-separated package names, each `-p`. Empty tests the whole workspace. |
| `setup-script` | `''` | Script in the caller repository run first (stage fixtures, trim workspace members). Its exit code is the verdict. |
| `test-profile` | `'dev'` | Cargo profile. Name an optimised profile that inherits `dev` if unoptimised DSP/ML tests are slow. |
| `skip-paths` | `''` | Newline-separated globs for paths that cannot affect the build. Empty skips nothing. |
| `toolchain` | `'stable'` | `stable`, `beta`, `nightly` or a version. |
| `scope-note` | `''` | One line on what the run does **not** cover; printed in the summary. |
| `scripts-ref` | `'main'` | ref the classifier script is taken from; pin it with the workflow. |
| `runner-label` | `'ubuntu-latest'` | runner label |
| `timeout-minutes` | `30` | job timeout |

It is one job on purpose and it does **not** run fmt, clippy or cargo-audit: a hook can run
fmt and lint on the staged files, and audit belongs to the release gate, so a pull request
would pay twice for the same verdict (book.md Part III.2). If `Cargo.lock` is not committed
it runs `cargo generate-lockfile` first.

A pull request that touches only `skip-paths` still gets a green job; its summary says the
tests did not run. A change the classifier cannot read, an empty diff and any path not
matched by a glob all run the tests.

## Local hook

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

cp hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

## Developing a gate

The scripts are plain Python 3 with no dependencies and run standalone:

```bash
python3 scripts/gates/loc_clock.py --repo ~/dev/target --ceiling 1500
python3 scripts/gates/workflow_integrity.py --repo ~/dev/target
python3 scripts/gates/test_gates.py          # the gates' own fixtures; run before changing one
```

Exit codes are uniform: `0` pass, `1` breach, `2` the gate could not run. `2` is a
failure, not a pass — book.md Art. VI.
