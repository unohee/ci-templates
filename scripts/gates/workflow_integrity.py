#!/usr/bin/env python3
"""Article VI gate — no gate-defeating construct in a workflow file.

book.md Art. VI: nothing ships that does not meet the standard, and CI fails any workflow
file containing a gate-defeating construct. A step that is allowed to fail is not a gate;
a workflow made of such steps is a status board.

This is a tripwire for the shapes that actually appear, not a shell semantics analyser.
It reads lines, because a gate script may not import a YAML parser (no dependencies), and
it will not catch every way a shell can hide a failure — `if ! cmd; then :; fi` and
friends are out of reach. What it does catch, it catches anywhere on the line rather than
only at the end, which is where the first draft leaked.

The construct is context-dependent and a regex cannot resolve the context. `|| true` on a
check defeats it; `|| true` on a setup step whose failure is caught downstream does not.
There is no exception mechanism, and that is deliberate. A first draft took an inline
`# constitution-allow: <reason>` marker, which review showed reopened exactly what the
Article forbids: `pytest || true` with a comment beside it passed. Art. VI's amended text
says a comment explaining why this particular escape hatch is reasonable is the violation,
not a mitigation of it — a gate whose bypass is a justifying comment contradicts the
sentence it exists to enforce.

The two legitimate uses this repository had were removed by restructuring rather than
exempting: `cxt bs` and the commit-range resolution moved into `cxt_bs.py` and
`commit_trailers.py --auto`, where a non-zero exit is a value the code inspects instead of
a status the shell acts on. That is the remedy Art. VIII prescribes — build the tool the
standard needs — applied to the standard's own enforcement.

Exit codes:
    0  clean (allowances, if any, are listed)
    1  at least one unmarked gate-defeating construct
    2  the gate itself could not run (Art. VI: that is a failure, not a pass)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Each pattern is matched against the code part of a line, comments stripped, so a
# construct named inside an explanation is not counted as one used — the same distinction
# that separates refusing a hatch from shipping one.
CONSTRUCTS: list[tuple[str, re.Pattern[str], str]] = [
    ("continue-on-error",
     re.compile(r"continue-on-error\s*:\s*true\b", re.IGNORECASE),
     "the step is allowed to fail, so it is not a gate"),
    ("continue-on-error-expression",
     re.compile(r"continue-on-error\s*:\s*\$\{\{"),
     "an expression cannot be shown to be false here; write the literal you mean"),
    # Not anchored to end of line. `cmd || true; echo ok` swallows the exit code exactly
    # as `cmd || true` does, and a first draft that required `$` let three of four
    # hand-written bypasses through.
    ("or-true",
     re.compile(r"\|\|\s*true\b"),
     "the exit code is swallowed, so the command cannot fail the job"),
    ("or-colon",
     re.compile(r"\|\|\s*:(\s|;|&|\||$)"),
     "`|| :` swallows the exit code exactly as `|| true` does"),
    ("set-plus-e",
     re.compile(r"\bset\s+\+e\b"),
     "errexit is disabled for the rest of the block"),
    ("exit-zero-flag",
     re.compile(r"--exit-zero\b"),
     "the linter is told to report findings and still succeed"),
    # The two moves someone reaches for once `|| true` is blocked. Leaving them out while
    # claiming this gate enforces Art. VI would be the same overclaim the Article forbids.
    ("or-exit-zero",
     re.compile(r"\|\|\s*exit\s+0\b"),
     "`|| exit 0` ends the step successfully after the command failed"),
    ("trailing-noop",
     re.compile(r"[;&]\s*(true|exit\s+0)\s*$"),
     "a trailing no-op becomes the step's exit status and masks whatever ran before it"),
]

def code_part(line: str) -> str:
    """Return the line with any trailing comment removed, respecting quotes.

    A first version cut at the first `#` anywhere. That was a working bypass, not a
    simplification: `printf '# ready'; pytest -q || true` is a valid step whose shell
    swallows a test failure, and the scanner saw only `printf '` and passed it.

    Both shells and YAML start a comment at a `#` that is outside quotes and begins a
    word, so that is the rule applied here. A `#` inside quotes is data. Backslash
    escapes are honoured everywhere except inside single quotes, because without that
    `echo "foo\" # fake" ; pytest -q || true` looked like it closed its quote at the
    escape and the rest of the line — which the shell really runs — was cut as a comment.
    """
    in_single = in_double = False
    escaped = False
    for i, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and not in_single:
            escaped = True
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if i == 0 or line[i - 1].isspace():
                return line[:i]
    return line


def logical_lines(lines: list[str]) -> list[tuple[int, str]]:
    """Join continuations so a construct split across lines is still one command.

    YAML folds a `run: >` block into a single line, and a shell continues a line ending
    in a backslash or a bare operator, so

        bandit -r . ||
        true

    executes as `bandit -r . || true`. Scanning line by line missed it entirely. The
    number reported is the line the construct starts on, which is where a reader looks.
    """
    out: list[tuple[int, str]] = []
    pending_no: int | None = None
    pending = ""
    for i, raw in enumerate(lines, start=1):
        code = code_part(raw).rstrip()
        if pending:
            code = pending + " " + code.strip()
        else:
            pending_no = i
        if code.endswith(("\\", "||", "&&", "|")):
            pending = code.rstrip("\\").rstrip()
            continue
        out.append((pending_no or i, code))
        pending = ""
        pending_no = None
    if pending:
        out.append((pending_no or len(lines), pending))
    return out


def scan(path: Path) -> list[tuple[int, str, str, str]]:
    """Return every gate-defeating construct in one workflow file."""
    breaches: list[tuple[int, str, str, str]] = []
    for line_no, code in logical_lines(
            path.read_text(encoding="utf-8", errors="replace").splitlines()):
        for name, pattern, why in CONSTRUCTS:
            if pattern.search(code):
                breaches.append((line_no, name, why, code.strip()))
    return breaches


def main() -> int:
    ap = argparse.ArgumentParser(description="book.md Art. VI — no gate-defeating construct in CI")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--dir", dest="workflow_dir", default=".github/workflows",
                    help="directory of workflow files, relative to --repo")
    ap.add_argument("--github", action="store_true")
    args = ap.parse_args()

    root = Path(args.repo) / args.workflow_dir
    if not root.is_dir():
        # Reached only when this gate runs somewhere it should not; a repository that can
        # call this workflow has a workflow directory by definition.
        print(f"::error::Art. VI gate could not run: {root} is not a directory.", file=sys.stderr)
        return 2

    files = sorted(p for p in root.iterdir()
                   if p.is_file() and p.suffix in (".yml", ".yaml"))
    if not files:
        # Zero files scanned would report zero breaches and go green — the fake-gate shape
        # this gate exists to remove, applied to itself.
        print(f"::error::Art. VI gate scanned 0 workflow files in {root}. "
              f"The gate did not actually run.", file=sys.stderr)
        return 2

    total_breaches = 0
    for path in files:
        try:
            breaches = scan(path)
        except OSError as exc:
            print(f"::error::Art. VI gate could not read {path}: {exc}", file=sys.stderr)
            return 2
        rel = path.relative_to(args.repo) if path.is_relative_to(args.repo) else path
        for line_no, name, why, text in breaches:
            total_breaches += 1
            msg = (f"{rel}:{line_no} [{name}] {why} — book.md Art. VI. There is no "
                   f"exception: move the command into a script where its exit code is a "
                   f"value you inspect, instead of a status the shell acts on. "
                   f"Offending line: {text}")
            print(f"::error file={rel},line={line_no}::{msg}" if args.github
                  else f"BREACH {msg}")

    print(f"\nArt. VI: {total_breaches} gate-defeating construct(s) "
          f"across {len(files)} workflow file(s)")
    return 1 if total_breaches else 0


if __name__ == "__main__":
    sys.exit(main())
