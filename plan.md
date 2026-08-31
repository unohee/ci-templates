# Plan — Constitution Gate (common CI workflow for `book.md`)

- **Target repo**: `ci-templates` (branch `main`, remote `unohee/ci-templates`)
- **Constitution**: `~/dev/dev_runbook/book.md`
- **Placement decision**: operator chose `ci-templates` over `dev_runbook` (2026-08-30) so the
  existing `uses:` convention and kis-agent's caller keep working.

## Why

`ci-templates/.github/workflows/python-ci.yml` is the current "common CI" and **it cannot
fail**:

| Line | Construct | Effect |
|---|---|---|
| 110 | `pytest ... \|\| true` | test job always green |
| 65, 70 | `continue-on-error: true` (ruff, black) | lint never blocks |
| 74, 164 | `\|\| true` (bandit, mypy) | security/type never block |
| 199 | `quality-gate` is `if: always()` + prints a table | the gate is decorative |

Under book.md that is Art. V (green CI is a floor, not an achievement) and Art. VI
(a gate that cannot fail is not a gate).

## Measured facts this plan rests on (2026-08-30)

- `@intrect/cxt` is published on npm at **0.3.0** → `cxt bs` is runnable in CI.
- `cxt bs --json` emits `{filesScanned, bsScore, critical, warning, minor, errors[], issues[]}`
  → gate on `critical > 0` directly, no text parsing.
- `cxt loc` has **no `--json`**; its output is ANSI-coloured with thousands separators and
  truncated to the top N → **not parseable in CI**. The LOC gate implements its own counter.
- `ci-templates` is referenced by exactly **one** repo today: `kis-agent`.

## Steps

1. **LOC ceiling + 30-day clock** — `scripts/gates/loc_clock.py` (Art. III)
   → *Verify*: run against `~/dev/cxt` and `~/dev/vega-agent`; hand-check one reported
     crossing commit against `git log` for that file.
2. **ARCHITECTURE.md gate** — `scripts/gates/architecture_doc.py` (Art. IV)
   → *Verify*: run against a repo that has the file and one that does not; feed a
     synthetic structural diff and confirm it demands the doc.
3. **Commit trailer gate** — `scripts/gates/commit_trailers.py` (§5.5)
   → *Verify*: run against a synthetic range containing `Co-Authored-By: Claude`.
4. **`constitution-gate.yml` wiring** (Art. II via `cxt bs`, Art. VI via integrity job)
   → *Verify*: YAML parses; every gate job appears in the integrity job's `needs`;
     zero `|| true` / `continue-on-error` in the file.
5. **Fix `python-ci.yml`** — remove all 7 gate-defeating constructs; `quality-gate` exits 1.
   → *Verify*: grep returns 0 hits on gating paths; YAML parses.
6. **Caller template + README**
   → *Verify*: the `uses:` path matches the real repo and branch.

## Non-goals (explicit)

- **CodeQL is not added here.** book.md §5.4 scopes it to release/cutover/major refactor/
  audit — not routine commits. Forcing it per-push would contradict the constitution.
- `hooks/pre-commit` (`MAX_LINES=800`, raw `wc -l`) is **reported, not changed** — it
  measures differently from Art. III (1500, code lines) and needs its own decision.
- `kis-agent`'s caller is not migrated in this pass.

## Concurrency

`ci-templates` is a checkout separate from the session cwd; `git status` is verified clean
before writing. The gate scripts read git history only and hold no shared mutable state.
The 30-day clock reads committed history, so it is deterministic for a given SHA — it does
not depend on wall-clock ordering between parallel CI runs.

---

# Plan — Art. VI workflow-integrity gate (2026-08-31)

## Why now

The 2026-08-31 amendment to `book.md` added a sentence to Art. VI's Enforcement: **CI
additionally fails any workflow file containing a gate-defeating construct.** That
sentence was written from measurement, not taste — the Article held in 8 of 12 measured
cases on prose alone, and both failures shipped `continue-on-error: true` beside a comment
explaining why this particular hatch was reasonable (`measurements.md` §4). The
constitution now requires a check that does not exist: none of `loc_clock`,
`architecture_doc`, or `commit_trailers` reads workflow files.

A constitution that requires a gate nobody built is the same failure it forbids.

## The hard part: the construct is context-dependent

`|| true` on a check defeats it. `|| true` on a setup step whose failure is caught
downstream does not. `constitution-gate.yml` itself contains two of the second kind:

- `git fetch ... || true` — tolerates a network blip, and the ref check below exits 2 if
  the fetch really failed.
- `cxt bs --json > bs.json || true` — the exit code is deliberately discarded because the
  JSON parse decides the verdict.

A regex cannot tell these apart from a real bypass. So the gate takes an inline marker
carrying a reason — `# constitution-allow: <why>` — in the same idiom as `cxt-ignore`,
which this organisation already uses. **Every allowance is printed in the gate's summary.**
That is the difference between a documented substitute (Art. VI permits it) and a silent
skip (Art. VI forbids it): allowances stay countable and visible rather than accumulating
where nobody looks.

A marker without a reason does not allow anything.

## Steps

1. `scripts/gates/workflow_integrity.py` → verification: run against `ci-templates` itself
   (must pass, with its two documented allowances listed) and against a synthetic workflow
   carrying each construct (must fail, one finding per construct).
2. Wire it into `constitution-gate.yml` as `article-vi-workflow-integrity`, and add it to
   the aggregating job's `needs`. → verification: the aggregator lists it; YAML parses;
   the new job's own step carries no gate-defeating construct.
3. Update `ARCHITECTURE.md` in the same commit (Art. IV). → verification: the layout table
   and the direct-invocation examples name the new script.
4. Re-run every gate locally against a real repository. → verification: exit codes
   observed, not assumed (§3.3).

## Naming

The workflow already has a job called `gate-integrity`, meaning "every gate ran and
passed". The new one checks the integrity of *workflow files*, so it is
`article-vi-workflow-integrity` and `workflow_integrity.py`. Two different things should
not share a name in a file people read under time pressure.

## Verification (2026-08-31, run not assumed)

| repo | workflow_integrity | loc_clock | architecture_doc |
|---|---|---|---|
| ci-templates | 0 — 2 documented allowances | 0 | 0 (presence only) |
| inkblot | **2** — no workflow directory | 0 | **1** — no ARCHITECTURE.md |
| vega-agent | **1** — 6 constructs in 9 files | **1** — 2 LOC breaches | 0 (presence only) |
| dev_runbook | **2** — no workflow directory | 0 (0 files, warned) | **1** — no ARCHITECTURE.md |

Synthetic fixture: all six constructs detected one finding each; `continue-on-error: false`
and a construct named in a prose comment produce nothing; a marker with no reason allows
nothing; an empty workflow directory and a missing one both exit 2.

Two things caught by running rather than reasoning:

- The first exit-code table was wrong. It read `$?` after `cmd | tail -1`, which is
  `tail`'s status, so every gate looked like it returned 0 — book.md §5.1, in the very
  session that added a sentence about it to the constitution.
- `loc_clock` reporting `0 breach over 0 files` looked like the fail-open shape the other
  gates guard against. It is not: the script already prints a warning and its comment
  states the reasoning — a docs-only repo legitimately has nothing to measure. Reading the
  source stopped an unnecessary "fix".

**vega-agent carries 6 gate-defeating constructs** across `auto-version-bump.yml`,
`ci.yml` (three) and `release-dmg.yml` (two). Reported, not fixed — that repo is outside
this change.

## Review round 1 — REVISE, three findings, all reproduced

`openswarm review` returned `Decision: REVISE`. Each finding was re-derived here before
being accepted; all three held.

1. **`workflow_integrity` leaked (high).** The patterns were anchored to end of line, so
   `set +e; false`, `false || true; echo hidden` and `pytest || true && echo done` all
   passed. Three of four hand-written bypasses got through. Fixed by dropping the anchor —
   `cmd || true` swallows the exit code whatever follows it — and the docstring now says
   plainly that this is a tripwire for real shapes, not a shell semantics analyser.
2. **`loc_clock` reported a false breach (high).** `blob_at` returned `None` both for "the
   path was absent" and "the blob could not be read", so a delete-and-re-add at the same
   path walked past the deletion to the original oversized commit. A file added today
   reported `>=91 days` in breach. Fixed by distinguishing the two: absence resets the
   clock, unreadability still skips. A false breach is worse than a miss — it blocks
   correct work and teaches people to bypass the gate.
3. **`architecture_doc` claimed a pass it had not established (medium).** It checked the
   whole PR range, so structure in one commit and the map in another printed "updated with
   it". Art. IV says the same commit. Now checked per commit, merge commits skipped, with
   the offending SHA named.

`scripts/gates/test_gates.py` fixes all three boundaries plus the marker-needs-a-reason
and zero-files cases — 7 tests, no dependencies. It runs as its own gate job
(`gate-self-test`): §5.2 treats a test that *is* the gate as production code, and a broken
ruler makes every other job in the workflow unreliable.

`__pycache__/` is now ignored.

## Review round 2 — REVISE, four findings, all reproduced

1. **The allow-marker reopened what Art. VI forbids (high).** `pytest || true` with
   `# constitution-allow: we know what we are doing` beside it passed. The amendment I had
   just written to Art. VI says the justifying comment *is* the violation, so a gate whose
   bypass is a justifying comment contradicts the sentence it enforces. **The mechanism is
   gone.** The two places this repo needed it were restructured instead: `cxt_bs.py` runs
   `cxt bs` from Python and parses the report, and `commit_trailers.py --auto` resolves the
   commit range and does its own best-effort fetch. In both, a non-zero exit is a value the
   code reads rather than a status the shell acts on. Art. VIII applied to the standard's
   own enforcement.
2. **`loc_clock` disagreed with the measure Art. III names (high).** A line beginning with
   `/*` was dropped whole, so `/**/int x = 1;` counted as nothing: 1,501 such lines passed
   a 1,500 ceiling that `cxt loc --no-blank --no-comments` reported as a breach. The
   stripper now removes comment spans and keeps what is left.
3. **The Art. IV freshness half never ran on a push (high).** `BASE_SHA` came from
   `pull_request.base.sha` only, so a direct-push repository could add a directory and
   leave the map stale with a green check. It now falls back to `github.event.before`.
4. **This repository never ran its own gates (medium).** Both workflows declared
   `workflow_call` only, so a gate could be changed and merged without GitHub Actions
   executing it once — the templates enforcing book.md everywhere except where they are
   written. `.github/workflows/self.yml` calls the constitution gate on push and PR, with
   `gates-ref` following the branch so a PR is judged by the gates it proposes.

Also: ruff, black and bandit installed unpinned while `ARCHITECTURE.md` invariant 4
claimed they were pinned. Now a `lint-versions` input, defaulted to the versions measured
on this host (`ruff==0.15.7 black==24.10.0 bandit[toml]==1.9.4`), and the invariant records
that it was asserted before it was true.

`test_gates.py` is 9 cases now. Every one of them is a defect review found.

## Review round 3 — one finding, then escalation

`openswarm review` returned `REVISE` on a single high issue, and it was a working bypass:
`code_part()` cut at the first `#` anywhere, so `printf '# ready'; pytest -q || true` — a
valid step whose shell swallows a test failure — reached the scanner as `printf '` and
passed. The docstring had called that cut "naive on purpose" and reasoned it could only
hide a construct inside a string literal. It could hide the rest of the line. Comment
stripping is now quote-aware: a `#` counts only outside quotes and at the start of a word,
which is the rule both shells and YAML use.

§5.2 stops re-review at three rounds, so this change escalated to **layer 3, an inline
self-audit of the full diff**, announced here rather than run as a fourth round. Layer 2 —
an independent sub-agent reviewer — was not available in this session.

The self-audit found two things review had not:

- The `continue-on-error-expression` message still told the reader to "allow it", pointing
  at a mechanism deleted in round 2.
- `|| exit 0` and a trailing `; true` were undetected. They are the two moves someone
  reaches for once `|| true` is blocked, and shipping a gate that misses them while
  claiming to enforce Art. VI is the overclaim the Article forbids.

Both fixed, both fixtured. `test_gates.py` is 12 cases; every one reproduces a defect that
shipped in a draft of this change.
