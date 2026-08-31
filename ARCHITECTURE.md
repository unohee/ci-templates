# Architecture — `ci-templates`

Reusable GitHub Actions workflows and the gate scripts they run. Repositories across the
organisation call these instead of copying CI into each tree; changing a rule here changes
it everywhere at once.

The standard these enforce is [`book.md`](https://github.com/unohee/dev_runbook/blob/main/book.md),
the engineering constitution. Articles are cited in the workflows as `Art. III`, protocols
as `§5.5`.

## Layout

| Path | Holds |
|---|---|
| `.github/workflows/constitution-gate.yml` | **Language-agnostic** enforcement of book.md. The one every repo should call. |
| `.github/workflows/python-ci.yml` | Python lint / test / type / LOC. Language CI only. |
| `scripts/gates/` | The gate implementations the constitution workflow runs. Plain Python 3, no dependencies. |
| `.github/workflows/self.yml` | This repository calling its own constitution gate on push and PR. Without it the gates could change without ever running. |
| `scripts/gates/test_gates.py` | Fixture tests for the gates. Every case reproduces a defect review found in a first draft; §5.2 treats a test that *is* the gate as production code. |
| `hooks/pre-commit` | Local Python pre-commit hook (book.md Art. II layer 0). |

## Entry points

Callers reference the workflows by path and ref:

```yaml
jobs:
  constitution:
    uses: unohee/ci-templates/.github/workflows/constitution-gate.yml@main
```

The gate scripts are also runnable directly, which is how they are developed and tested:

```bash
python3 scripts/gates/loc_clock.py --repo ~/dev/some-repo --ceiling 1500
python3 scripts/gates/architecture_doc.py --repo . --base-ref origin/main
python3 scripts/gates/commit_trailers.py --repo . --range origin/main..HEAD
python3 scripts/gates/workflow_integrity.py --repo .
python3 scripts/gates/test_gates.py
```

## Invariants

1. **Whatever runs, blocks.** No `continue-on-error`, no `|| true` on a check, no
   summary-only job. A check a repository does not want is disabled through a declared
   workflow input, which is visible in the caller; it is never neutered in the template.
   (book.md Art. VI. This repo violated it until 2026-08-30 — see AGT-4135.)

   Since 2026-08-31 this invariant is enforced rather than asserted:
   `workflow_integrity.py` reads every workflow file and fails on the constructs above,
   **with no exception mechanism**. A first draft took an inline allow-marker; review
   showed it let `pytest || true` through with a comment beside it, which is the shape
   Art. VI's amended text names as the violation itself. The two places this repo needed
   one were removed by restructuring — `cxt_bs.py` and `commit_trailers.py --auto` run
   those commands from Python, where a non-zero exit is a value the code reads rather than
   a status the shell acts on.
2. **A gate that could not run has not passed.** Scripts exit `2` when they cannot do
   their job, and `gate-integrity` treats `skipped` and `cancelled` exactly like `failure`.
3. **Gate scripts depend on nothing but Python 3 and git.** They run before any project
   dependency is installed, so they cannot import from the repo under test.
4. **Tool versions are pinned** — `@intrect/cxt` via `cxt-version`, and ruff, black and
   bandit via `lint-versions`. A hard gate turns an upstream release into a red CI on an
   unrelated PR; bump deliberately. This invariant was asserted before it was true: the
   lint toolchain installed unpinned until 2026-08-31.

## What will bite you

- **`fetch-depth: 0` is load-bearing.** The Art. III clock walks each oversized file's
  history to find the commit that crossed the ceiling. Under a shallow clone every file
  looks freshly crossed, so a breach silently downgrades to a warning — fail-open.
- **`cxt loc` is not used by the LOC gate**, despite being the canonical measure in
  book.md. It has no JSON output, prints ANSI escapes and thousands separators, and
  truncates to the top N files. `scripts/gates/loc_clock.py` reimplements the count and
  was verified to agree with `cxt loc --no-blank --no-comments` exactly (1318 / 1029 / 917
  on three files of the `cxt` repo, 2026-08-30). **If you change the counter, re-check
  that agreement** — the two drifting apart silently is the failure mode.
- **Comment stripping is approximate.** A `#` or `//` inside a string literal is counted
  as a comment. That can only make a file look smaller, so it is unsafe in the
  fail-open direction; it is accepted because a full parser per language is not worth it
  at this ceiling. Block comments are handled for C-like languages, where comment volume
  actually lives.
- **The LOC gate measures source extensions only.** Its language table is the scope: a
  file whose extension is not in it (`.md`, an extensionless script) is never measured.
  Adding a language means adding its comment syntax there, not just its extension.
- **The clock reads author dates, not committer dates.** A rebase rewrites committer
  dates, which would reset a breach to clean through an everyday operation.

- **The AI-trailer gate deliberately ignores `@users.noreply.github.com`.** Humans use
  that address; matching it blocked legitimate PRs. Only vendor addresses and bracketed
  bot handles are matched.
- **`python-ci.yml` is now able to fail.** A repository that passed it before 2026-08-30
  passed nothing. Expect first red runs to be real findings, not regressions.
