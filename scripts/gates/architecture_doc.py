#!/usr/bin/env python3
"""Article IV gate — ARCHITECTURE.md exists and keeps up with the structure.

book.md Art. IV: every repository's structure MUST be written in ARCHITECTURE.md, and it
is updated in the same commit that changes the structure. A stale map is worse than none,
because it is trusted.

Two checks:
  1. presence  — the file exists at the repo root.
  2. freshness — if the change adds or removes a directory (to --depth), the diff must
                 also touch ARCHITECTURE.md. Freshness needs a base ref, so it is skipped
                 outside pull requests, and says so rather than passing silently.

Exit codes:
    0  both checks satisfied (or freshness not applicable, stated)
    1  the file is missing, or structure moved without the map
    2  the gate itself could not run (Art. VI: that is a failure, not a pass)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DOC_NAMES = ("ARCHITECTURE.md", "docs/ARCHITECTURE.md")


def git(*args: str, cwd: str = ".") -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def dirs_at(rev: str, cwd: str, depth: int) -> set[str]:
    """Directory paths present at a revision, truncated to `depth` segments."""
    out = git("ls-tree", "-r", "-d", "--name-only", rev, cwd=cwd).splitlines()
    kept = set()
    for path in out:
        if path.startswith(".") or "node_modules" in path or "/vendor" in path:
            continue
        parts = path.split("/")
        if len(parts) <= depth:
            kept.add(path)
    return kept



def commits_moving_structure_without_doc(
    base: str, head: str, doc: str, depth: int, cwd: str
) -> list[tuple[str, str, str]]:
    """Commits in base..head that change structure without touching the map.

    Merge commits are skipped: their structural delta is their parents' work, already
    inspected on its own commit, and counting it again would demand a map update in a
    commit that wrote no code.
    """
    raw = git("log", "--no-merges", "--reverse", "--format=%H%x1f%s", f"{base}..{head}", cwd=cwd)
    out: list[tuple[str, str, str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        sha, subject = (line.split("\x1f") + [""])[:2]
        parent = f"{sha}^"
        before = dirs_at(parent, cwd, depth)
        after = dirs_at(sha, cwd, depth)
        added, removed = sorted(after - before), sorted(before - after)
        if not (added or removed):
            continue
        touched = set(git("diff", "--name-only", parent, sha, cwd=cwd).splitlines())
        if doc not in touched:
            moved = ", ".join([f"+{d}" for d in added] + [f"-{d}" for d in removed])
            out.append((sha[:12], subject, moved))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="book.md Art. IV — ARCHITECTURE.md presence and freshness")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base-ref", default="", help="PR base SHA/ref; empty disables the freshness check")
    ap.add_argument("--head-ref", default="HEAD")
    ap.add_argument("--depth", type=int, default=2, help="directory depth treated as structure")
    ap.add_argument("--github", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo)
    present = [name for name in DOC_NAMES if (repo / name).is_file()]
    if not present:
        msg = ("ARCHITECTURE.md is missing. book.md Art. IV: every repository's structure "
               "MUST be documented so onboarding does not require reading the source.")
        print(f"::error::{msg}" if args.github else f"BREACH {msg}")
        return 1
    doc = present[0]
    print(f"Art. IV: {doc} present")

    # A repository's first push sends `before` as forty zeros, not an empty string, and
    # `git diff 000...HEAD` is a fatal error rather than an empty diff. Passing it through
    # made the whole constitution gate exit 2 on the first push of a new repository —
    # which is the moment someone adopts it. Normalised here rather than in the workflow,
    # because the same event reaches every gate and only one of them was handling it.
    if args.base_ref and set(args.base_ref) == {"0"}:
        args.base_ref = ""

    if not args.base_ref:
        # Art. VI — say what did not run instead of implying it passed.
        print("Art. IV: freshness check NOT RUN (no base ref; presence check only)")
        return 0

    try:
        changed = set(git("diff", "--name-only", f"{args.base_ref}...{args.head_ref}",
                          cwd=args.repo).splitlines())
        before = dirs_at(args.base_ref, args.repo, args.depth)
        after = dirs_at(args.head_ref, args.repo, args.depth)
    except subprocess.CalledProcessError as exc:
        print(f"::error::Art. IV gate could not run: {exc.stderr.strip() or exc}", file=sys.stderr)
        return 2

    added, removed = sorted(after - before), sorted(before - after)
    if not (added or removed):
        print("Art. IV: no structural change in this diff")
        return 0

    moved = ", ".join([f"+{d}" for d in added] + [f"-{d}" for d in removed])
    if doc not in changed:
        msg = (f"structure changed ({moved}) but {doc} was not updated anywhere in this "
               f"range. book.md Art. IV: the map is updated in the commit that moves the "
               f"structure.")
        print(f"::error file={doc}::{msg}" if args.github else f"BREACH {msg}")
        return 1

    # The range-level check above only establishes that both happened somewhere. Art. IV
    # says "the same commit", and a range where the structure moved in one commit and the
    # map caught up in another leaves history with a commit whose map is wrong — which is
    # the stale map the Article calls worse than none. Saying "updated with it" on the
    # strength of the range alone reports a pass that was not established.
    try:
        offenders = commits_moving_structure_without_doc(
            args.base_ref, args.head_ref, doc, args.depth, args.repo)
    except subprocess.CalledProcessError as exc:
        print(f"::error::Art. IV per-commit check could not run: {exc.stderr.strip() or exc}",
              file=sys.stderr)
        return 2

    for sha, subject, moved_here in offenders:
        msg = (f"{sha} \"{subject}\" moved structure ({moved_here}) without touching {doc}. "
               f"book.md Art. IV: same commit. Amend it, or fold the map update into it.")
        print(f"::error::{msg}" if args.github else f"BREACH {msg}")
    if offenders:
        return 1

    print(f"Art. IV: structure moved ({moved}) and {doc} moved in the same commit(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
