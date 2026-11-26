# Local security and quality gates

GitHub Advanced Security (code scanning, secret scanning) and GitHub Code Quality stop on
2026-11-20: the operator dropped them for cost. This directory is the replacement. Every tool
here is free for private commercial use and runs both on a laptop and on the self-hosted ARC
runners, so a scan costs nothing and never waits on a GitHub-hosted minute.

## What replaces what

| Dropped | Replacement | Licence | Runs |
|---|---|---|---|
| GitHub secret scanning + push protection | `gitleaks` over the history, or over a pull request's change range limited to the files it changes | MIT | `scan.sh`, `security-local.yml` |
| CodeQL code scanning | `semgrep` (`p/default`) over an export of the tracked files | LGPL-2.1 engine, Semgrep Rules License for the registry rules (internal use) | `scan.sh`, `security-local.yml` |
| Dependabot alerts | `osv-scanner` over every lockfile in the tree | Apache-2.0 | `scan.sh`, `security-local.yml` |
| GitHub Code Quality (maintainability) | `clippy` / `ruff` / `eslint` / `tsc` (already in each repository) plus a `lizard` complexity and copy/paste report | MIT | `scan.sh --quality` |

Not yet built: a `pre-commit` secret check for the local hook (`hooks/pre-commit` covers the
python rules only). Until then the secret pass is the commit-time gate in CI, and `scan.sh`
locally before a push.

## Why not the CodeQL CLI

The CodeQL CLI is installed on this host, so running it locally looks like the obvious
replacement. It is not available to us. The GitHub CodeQL Terms and Conditions
(`~/.local/opt/codeql/LICENSE.md`, shipped with the CLI) allow the command-line toolchain
without a paid Advanced Security licence only for academic research, demonstrations, testing
OSI-licensed queries, and analysis of a codebase released under an OSI-approved licence. They
also forbid generating a CodeQL database "for or during automated analysis, CI or CD", and any
use "in connection with any codebase that is not an Open Source Codebase". Every Intrect
repository is private, so the CodeQL CLI may not scan them once the subscription ends.

Consequences to keep in mind:

- `de-artifact/.github/workflows/ci-rust.yml` had a `codeql` job (added 2026-11-17) that fetched
  the bundle with `github/codeql-action/init` and ran `scripts/codeql_check.sh`. It is removed
  with this change; `scripts/codeql_check.sh`, `scripts/codeql_sarif_gate.py` and their tests go
  with it, and AUD-3009's rule (fail on high-severity warnings too) moves into
  `security/findings.py`.
- Any other `codeql` script in the organisation (`cerebral/scripts/codeql_audit.sh`,
  `vega-agent*/scripts/run_codeql_audit.py`, `intrect-trade*/scripts/run_codeql_gate.sh`) has the
  same problem and needs the same replacement.
- There is nothing to configure on GitHub for this gate. It does not use code scanning, the
  security-events API or an upload, so it works with every repository feature switched off.

## Using it

```bash
# One-time: install the pinned tools into ~/.local/share/intrect-security
bash security/bootstrap.sh

# Whole repository: history, tracked tree, lockfiles
bash security/scan.sh --repo ~/dev/de-artifact

# Pull-request pass: the change range for secrets, the changed files for sast
bash security/scan.sh --repo . --profile pr --base origin/main

# Full profile, but only the commits one push introduced (the CI case)
bash security/scan.sh --repo . --range "$BEFORE..$AFTER"

# Add the report-only quality metrics
bash security/scan.sh --repo . --quality
```

Exit codes: `0` clean, `1` at least one blocking finding, `2` a tool or report could not be
used. A missing tool is `2`, never a pass (book.md Art. VI: a gate that cannot fail is not a
gate).

## What blocks, and what is only reported

- **secret** — every gitleaks finding blocks. The report carries the rule, file and line, never
  the secret value (`--redact`; `findings.py` keeps the description and drops `Secret`/`Match`).
- **sast** — a semgrep result blocks at severity `ERROR`, and at `WARNING` when the rule declares
  `metadata.confidence: high`. AUD-3009 was an error-only rule letting a high-severity warning
  through; the confidence check closes that gap without blocking the long tail of medium-confidence
  warnings.
- **deps** — every vulnerability osv-scanner reports blocks. Rust dependencies are also covered by
  each repository's existing `cargo-audit` job.
- **quality** — reported only. `lizard`'s complexity and copy/paste numbers have no baseline yet,
  and inventing thresholds from nothing would create a gate nobody can pass. The report is
  attached so a threshold can be set from measured numbers.

A finding that is genuinely acceptable goes into the repository's `security/baseline.json`, which
names it exactly and says why:

```json
{"accepted": [
  {"tool": "deps", "rule": "GHSA-xxxx-yyyy-zzzz", "path": "requirements.txt", "line": 0,
   "reason": "build-only dependency, not reachable from the shipped binary (AUD-0000)",
   "added": "2026-11-20"}
]}
```

A baseline entry accepts that one tool+rule+path+line. A different vulnerability in the same file
still blocks. A static-analysis entry also keeps accepting one finding with the same rule and file
after a later edit moves its line: semgrep reports the line it parsed, so an insertion above
re-numbers everything below it, and an exact-line-only rule would turn that edit into a red gate
over code nobody touched. The count stays one entry per finding, so a second occurrence of the same
rule in the same file still blocks.

`security/baseline.json` is read automatically when it exists, both locally and in CI, so a
repository does not have to pass `--baseline` (and the reusable workflow does not). To record the
first run, let `scan.sh` write it — it passes the export directory as the root, so every entry
names the same path a later run will see:

```bash
# fix what should be fixed first, then record the rest; the run still reports what it recorded
bash security/scan.sh --repo . --write-baseline security/baseline.json \
  --baseline-reason "pre-existing before the gate was adopted (AUD-nnnn)"
```

Writing the file by hand through `findings.py --write-baseline` works only with `--root` set to
the exported tree; with any other root the entries come out absolute and can never match, so the
writer refuses them.

## In CI

`.github/workflows/security-local.yml` is the reusable workflow. A repository calls it:

```yaml
# .github/workflows/security.yml
name: security
on:
  push:
    branches: [main]
  pull_request:
permissions:
  contents: read
jobs:
  security:
    uses: unohee/ci-templates/.github/workflows/security-local.yml@main
```

The base ref is fetched whole, never shallow. A depth-1 fetch grafts the base tip, and a grafted
commit has no parents, so `git merge-base` reports "no merge base" for every branch that is behind
the base — the normal state of a pull request. `fetch_base.sh` fetches the one branch it needs and
fails with a clear message if the base still cannot be reached (AUD-3071).

It runs on the `vela-linux` scale set, exports the pull request's merge commit, and reads that
export for the dependency pass and the static-analysis pass. Nothing is uploaded to GitHub's
security features; the summary is written to the job log and kept as a runner-local artifact.

The secret pass reads the change range, and reports only the files that change touches. Both parts
matter: a baseline entry names a line, and a merge commit in the range carries the base branch's
copy of every file it merges, so a token the base branch moved to a new line is reported at the
line it had when the branch started, where no accepted entry matches it. Narrowing to the changed
files removes that whole class of false block — a file the change never touches cannot be where it
introduced a secret — and a secret the change adds still blocks.

The full profile reads the whole history of the checked-out ref, not every ref in the repository.
A push to the default branch passes `before..after`, so the scan reads only the commits that push
introduced:

```yaml
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: '0 20 * * 0'   # Sun 20:00 UTC = Mon 05:00 KST: the whole-history audit
jobs:
  security:
    uses: unohee/ci-templates/.github/workflows/security-local.yml@<pinned sha>
    with:
      profile: ${{ github.event_name == 'pull_request' && 'pr' || 'full' }}
      range: ${{ github.event_name == 'push' && format('{0}..{1}', github.event.before, github.sha) || '' }}
      report-only: ${{ github.event_name == 'schedule' }}
```

Measured 2026-11-26 on de-artifact: reading every ref made main's check red on three
`generic-api-key` hits inside `docs/design/figma-spec/*.md` — files that exist only on an unmerged
branch. A push cannot introduce what it does not contain, so other branches are not this check's
subject. Two rules keep the narrowing from losing cover:

- **A range that cannot be measured falls back to the safe side.** When the earlier end is missing
  (a new branch reports an all-zero tip), is not an ancestor of the later end (a force push that
  dropped the old tip), or does not exist at all, `scan.sh` reads every commit on the checked-out
  ref instead. It never shortens the list silently: it prints which fallback it used.
- **One scheduled run reads everything, and blocks nothing.** `report-only: true` keeps a finding
  from failing the job; the run summary lists what old history still holds. A tooling failure is
  still a failure in that mode, because a scanner that could not run must never read as a clean
  scan.

## Files

| Path | Holds |
|---|---|
| `tools.env` | pinned versions and checksums; the single place a scanner version changes |
| `bootstrap.sh` | installs the tools into one directory, checksum-verified, idempotent (`--check` to report) |
| `scan.sh` | the scan: secrets, sast, dependencies, optional quality |
| `findings.py` | reads the three reports, applies the baseline, decides the exit code, prints the table |
| `scan_ci.sh` | the CI wrapper: turns the scan's exit code into a pass/fail decision (report-only lives here, never as `set +e` in a workflow) |
| `test_scan_ci.sh` | tests for that decision (stub scan, no network) |
| `report_summary.py` | renders a summary as markdown for the report-only whole-history audit |
| `test_report_summary.py` | tests for that renderer (no network) |
| `test_findings.py` | unit tests for the gate decisions (no network) |
| `test_scan.sh` | wiring tests with stub tools (no network): missing tool, planted leak, pull-request narrowing |
| `fetch_base.sh` | fetches a pull request's base ref with its whole history, so `git merge-base` can find where the branch started |
| `test_fetch_base.sh` | tests that fetch (no network): a shallow fetch loses the merge base, the script keeps it |