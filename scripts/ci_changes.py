#!/usr/bin/env python3
"""Decide whether a pull request can affect the build, from the paths it changes.

Reads changed paths on stdin and prints GitHub Actions output lines (`heavy` is last on
purpose, see `printable`):

    reason=<one line>
    heavy=true|false

`heavy=false` means every changed path matches a skip glob, so the tests cannot be
affected. It is the ONLY answer that skips work, and it needs positive evidence: at least
one changed path, and every one of them matched. Everything else runs the tests — an empty
diff, a path no glob names, an empty skip list. A classifier that errs towards skipping
turns a new directory into a silent hole in CI; one that errs towards running costs a
minute. (Allowlist of what is safe to skip, never a list of what is relevant.)

Globs use fnmatch, so `*` also crosses `/`: `docs/*` covers `docs/a/b.md`, `*.md` covers a
markdown file at any depth. Matching is case-sensitive and anchored to the whole path.

Exit codes:
    0  classified (either answer)
    2  could not classify (bad usage) — Art. VI: the caller must treat that as failure
"""

from __future__ import annotations

import argparse
import fnmatch
import sys


def read_paths(raw: bytes, null_separated: bool) -> list[str]:
    sep = b"\0" if null_separated else b"\n"
    paths = []
    for chunk in raw.split(sep):
        text = chunk.decode("utf-8", errors="surrogateescape")
        if not null_separated:
            text = text.strip("\r")
        if text.startswith("./"):
            text = text[2:]
        if text:
            paths.append(text)
    return paths


def printable(text: str, limit: int = 160) -> str:
    """A path as one safe output line.

    File names are chosen by the pull request's author and may hold a newline. Printed raw
    into `$GITHUB_OUTPUT`, `x\\nheavy=false` would add a second `heavy` key that wins over
    ours and skip the tests, so control characters are escaped and the length is capped.
    """
    escaped = text.encode("unicode_escape", errors="backslashreplace").decode("ascii")
    return escaped if len(escaped) <= limit else escaped[:limit] + "..."


def parse_globs(spec: str) -> list[str]:
    return [line.strip() for line in spec.splitlines() if line.strip()]


def classify(paths: list[str], globs: list[str]) -> tuple[bool, str]:
    if not paths:
        return True, "no changed paths were reported: running everything"
    if not globs:
        return True, "no skip globs declared: running everything"
    for path in paths:
        if not any(fnmatch.fnmatchcase(path, glob) for glob in globs):
            return True, f"'{printable(path)}' is not covered by any skip glob"
    return False, f"all {len(paths)} changed path(s) match a skip glob"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--skip", default="", help="newline-separated globs that cannot affect the build")
    parser.add_argument("--null", action="store_true", help="paths on stdin are NUL-separated (git diff -z)")
    args = parser.parse_args(argv)

    heavy, reason = classify(read_paths(sys.stdin.buffer.read(), args.null), parse_globs(args.skip))
    # `heavy` last: if an unescaped line ever slipped into `reason`, the real verdict still
    # comes after it and wins.
    print(f"reason={reason}")
    print(f"heavy={'true' if heavy else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
