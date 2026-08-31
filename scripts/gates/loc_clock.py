#!/usr/bin/env python3
"""Article III gate — file size ceiling with a 30-day clock.

book.md Art. III: no file stays above the ceiling for more than a month. Crossing the
ceiling starts a clock at the commit that crossed it; going back under resets it.

The measure is code lines — blank lines and whole-line comments excluded — matching
`cxt loc --no-blank --no-comments`. `cxt loc` itself is not called here: it has no JSON
output, its report is ANSI-formatted with thousands separators, and it truncates to the
top N files, so it cannot be parsed reliably in CI. Measured 2026-08-30.

Exit codes:
    0  every oversized file is still inside its 30-day window
    1  at least one file has been over the ceiling for more than 30 days
    2  the gate itself could not run (Art. VI: that is a failure, not a pass)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass

# Whole-line comment prefixes per extension. Deliberately conservative: a prefix inside a
# string literal would be miscounted as a comment, which can only make a file look
# SMALLER. That direction is unsafe for a ceiling gate, so block-comment bodies are
# tracked for c-like languages where the bulk of comment volume lives.
LINE_COMMENT = {
    "py": ("#",), "sh": ("#",), "bash": ("#",), "rb": ("#",), "yml": ("#",),
    "yaml": ("#",), "toml": ("#",), "r": ("#",), "pl": ("#",),
    "c": ("//",), "h": ("//",), "cpp": ("//",), "hpp": ("//",), "cc": ("//",),
    "java": ("//",), "js": ("//",), "mjs": ("//",), "cjs": ("//",), "jsx": ("//",),
    "ts": ("//",), "tsx": ("//",), "go": ("//",), "rs": ("//",), "cs": ("//",),
    "swift": ("//",), "kt": ("//",), "scala": ("//",), "php": ("//", "#"),
    "sql": ("--",), "lua": ("--",), "hs": ("--",),
}
BLOCK_COMMENT = {"/*": "*/"}
CLIKE = {
    "c", "h", "cpp", "hpp", "cc", "java", "js", "mjs", "cjs", "jsx", "ts", "tsx",
    "go", "rs", "cs", "swift", "kt", "scala", "php",
}
DEFAULT_EXCLUDE = (
    "node_modules/", "vendor/", "dist/", "build/", "target/", ".venv/", "venv/",
    "third_party/", "generated/", ".min.js", ".lock",
)


def git(*args: str, cwd: str = ".") -> str:
    """Run git and return stdout. Raises on failure so the caller can exit 2."""
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def strip_block_comments(line: str, in_block: bool) -> tuple[str, bool]:
    """Remove every `/* ... */` span from one line.

    Returns what is left and whether a block is still open at end of line. A span may
    open and close on the same line more than once, which is why this is a scan rather
    than a startswith test.

    A `/*` inside a string literal is stripped too. That undercounts rather than
    overcounts, so it can only hide a breach in a file that writes `/*` in a string —
    noted rather than solved, because solving it means lexing six languages.
    """
    out: list[str] = []
    i = 0
    while i < len(line):
        if in_block:
            end = line.find("*/", i)
            if end < 0:
                return "".join(out), True
            i, in_block = end + 2, False
        else:
            start = line.find("/*", i)
            if start < 0:
                out.append(line[i:])
                return "".join(out), False
            out.append(line[i:start])
            i, in_block = start + 2, True
    return "".join(out), in_block


def code_lines(text: str, ext: str) -> int:
    """Count lines that are neither blank nor comment-only.

    Code after a block comment closes on the same line counts. An earlier version
    dropped any line beginning with `/*`, so a file of 1,501 `/**/int x = 1;` lines
    measured as zero and passed a 1,500 ceiling that `cxt loc --no-blank --no-comments`
    — the measure Art. III actually names — reported as a breach.
    """
    prefixes = LINE_COMMENT.get(ext, ())
    in_block = False
    count = 0
    for raw in text.splitlines():
        line = raw.strip()
        if ext in CLIKE:
            line, in_block = strip_block_comments(line, in_block)
            line = line.strip()
        if not line:
            continue
        if prefixes and line.startswith(prefixes):
            continue
        count += 1
    return count


# Returned by blob_at when the path is known not to exist at that revision, which is a
# different fact from "the blob could not be read" and has the opposite effect on the
# clock: a file that is not there cannot be over the ceiling.
ABSENT = object()


def blob_at(rev: str, path: str, cwd: str) -> str | object | None:
    """File content at a revision, ABSENT if the path was not there, None if unreadable.

    Collapsing those two into None makes a delete-and-re-add look like continuous
    presence: the deleted revisions are skipped, the walk reaches the original oversized
    commit, and a file added today is reported as months over the ceiling.
    """
    proc = subprocess.run(
        ["git", "show", f"{rev}:{path}"], cwd=cwd, capture_output=True, text=True
    )
    if proc.returncode == 0:
        return proc.stdout
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{rev}:{path}"], cwd=cwd, capture_output=True, text=True
    )
    return None if exists.returncode == 0 else ABSENT


@dataclass
class Offender:
    path: str
    lines: int
    days_over: int      # days since the commit that pushed it over the ceiling
    since_sha: str
    exact: bool         # False when history was unreadable and the age is a lower bound


def tracked_files(cwd: str, exclude: tuple[str, ...]) -> list[tuple[str, str]]:
    out = []
    for path in git("ls-files", cwd=cwd).splitlines():
        if any(frag in path for frag in exclude):
            continue
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext in LINE_COMMENT:
            out.append((path, ext))
    return out


def find_crossing(
    history: list[tuple[str, int]], path: str, ext: str, ceiling: int, cwd: str
) -> tuple[str, int, bool]:
    """The commit that most recently pushed the file over the ceiling.

    `history` is newest-first. Walking back, the first commit where the file was at or
    under the ceiling means the commit visited just before it is the crossing point.

A revision where the path was absent — before it was created, or between a delete and
    a re-add at the same path — counts as under the ceiling and stops the walk. A file
    that does not exist is not oversized, and treating absence as "keep looking" reports a
    file added today as months in breach.

    A commit whose blob cannot be *read* (a shallow clone) is different and is skipped:
    an unreadable revision must not reset the clock. If no under-ceiling revision is found
    at all, the oldest commit is returned with exact=False, so the age is reported as a
    lower bound instead of a fact.
    """
    newer = (history[0][0], history[0][1])
    for sha, ts in history:
        content = blob_at(sha, path, cwd)
        if content is ABSENT:
            return newer[0], newer[1], True
        if content is not None and code_lines(content, ext) <= ceiling:
            return newer[0], newer[1], True
        newer = (sha, ts)
    return history[-1][0], history[-1][1], False


def audit(cwd: str, ceiling: int, window_days: int, exclude: tuple[str, ...]) -> list[Offender]:
    now = time.time()
    offenders: list[Offender] = []

    for path, ext in tracked_files(cwd, exclude):
        head = blob_at("HEAD", path, cwd)
        if head is None:
            continue
        now_lines = code_lines(head, ext)
        if now_lines <= ceiling:
            continue

        # %at (author date), not %ct. A rebase rewrites committer dates, so a clock built
        # on %ct silently resets every time a long-lived branch is rebased — a breach
        # becomes clean through a routine operation. Author dates survive that. They can
        # be backdated, but that is deliberate falsification rather than a daily accident,
        # and failing open on the daily case is the worse trade.
        log = git("log", "--format=%H %at", "--follow", "--", path, cwd=cwd).split("\n")
        history = [(parts[0], int(parts[1])) for parts in
                   (line.split() for line in log if line.strip())]
        if not history:
            # Tracked but not yet committed. Treat as crossed now: it is on the clock,
            # not in breach, and the next run will date it properly.
            offenders.append(Offender(path, now_lines, 0, "uncommitted", True))
            continue

        sha, ts, exact = find_crossing(history, path, ext, ceiling, cwd)
        offenders.append(Offender(path, now_lines, int((now - ts) // 86400), sha[:12], exact))

    return offenders


def main() -> int:
    ap = argparse.ArgumentParser(description="book.md Art. III — LOC ceiling with a 30-day clock")
    ap.add_argument("--ceiling", type=int, default=1500)
    ap.add_argument("--window-days", type=int, default=30)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--exclude", default=",".join(DEFAULT_EXCLUDE))
    ap.add_argument("--github", action="store_true", help="emit ::error/::warning annotations")
    args = ap.parse_args()

    exclude = tuple(f for f in args.exclude.split(",") if f)
    try:
        offenders = audit(args.repo, args.ceiling, args.window_days, exclude)
    except subprocess.CalledProcessError as exc:
        # Art. VI: a gate that could not run has not passed.
        print(f"::error::Art. III gate could not run: {exc.stderr.strip() or exc}", file=sys.stderr)
        return 2

    breaches = [o for o in offenders if o.days_over > args.window_days]
    on_clock = [o for o in offenders if o.days_over <= args.window_days]

    for o in sorted(on_clock, key=lambda x: -x.days_over):
        left = args.window_days - o.days_over
        msg = (f"{o.path}: {o.lines} code lines (over {args.ceiling}) — crossed at "
               f"{o.since_sha} {o.days_over}d ago, {left}d left to split it")
        print(f"::warning file={o.path}::{msg}" if args.github else f"CLOCK  {msg}")

    for o in sorted(breaches, key=lambda x: -x.days_over):
        age = f"{o.days_over}" if o.exact else f">={o.days_over}"
        msg = (f"{o.path}: {o.lines} code lines, over the {args.ceiling} ceiling for "
               f"{age} days (limit {args.window_days}) — crossed at {o.since_sha}. "
               f"book.md Art. III: split it before the next feature that touches it.")
        print(f"::error file={o.path}::{msg}" if args.github else f"BREACH {msg}")

    considered = len(tracked_files(args.repo, exclude))
    if considered == 0:
        # Not fatal — a docs-only repo legitimately has nothing to measure — but it must
        # be visible. A silent "0 breach" over 0 files reads exactly like a clean pass.
        print("::warning::Art. III considered 0 files. No tracked file matched a known "
              "source extension; confirm that is expected for this repo."
              if args.github else
              "NOTE   Art. III considered 0 files (no known source extensions matched).")
    print(f"\nArt. III: {len(breaches)} breach, {len(on_clock)} on the clock "
          f"over {considered} files (ceiling {args.ceiling} code lines, "
          f"window {args.window_days}d)")
    return 1 if breaches else 0


if __name__ == "__main__":
    sys.exit(main())
