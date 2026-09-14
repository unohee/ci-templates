#!/usr/bin/env python3
"""Protocol §5.5 gate — no AI co-author trailers.

book.md §5.5: commit messages carry the operator's authorship only. No AI co-author
trailers, ever.

Matching is on the trailer value, against known agent identities rather than a loose
substring, so a human contributor whose name merely contains one of these words is not
flagged.

Exit codes:
    0  no AI trailer in the range
    1  at least one commit carries one
    2  the gate itself could not run (Art. VI: that is a failure, not a pass)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

TRAILER = re.compile(r"^\s*co-authored-by:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
# Identities, not words. `claude` alone would flag a person named Claude Martin; the
# address and the bracketed-bot forms are what actually appear in generated trailers.
# `@users.noreply.github.com` is deliberately NOT here: humans use that address, and
# flagging it would block legitimate PRs. Model names (opus/sonnet/haiku) are out for the
# same reason — they are ordinary words and given names. What remains is either a vendor
# address or a bracketed bot handle, both of which a person does not have.
AI_IDENTITY = re.compile(
    r"(noreply@anthropic\.com"          # Claude Code's generated trailer
    r"|@openai\.com"                    # Codex
    r"|\[bot\]"                         # github-actions[bot], dependabot[bot], ...
    r"|\bcopilot\b"
    r"|\bdevin\b"
    r"|\bcursor\s+agent\b)",
    re.IGNORECASE,
)


def resolve_range(base_sha: str, head_sha: str, before: str,
                  default_branch: str, cwd: str) -> str:
    """Pick the commit range this event should be judged on.

    Pull request: base..head. Push with a real `before`: before..head. Otherwise the
    branch's first push, where `before` is all zeros and there is no base — compare
    against the default branch, fetching it if the clone does not have it.

    A failed fetch is not swallowed into a pass: if the ref still does not resolve, the
    range falls back to the full history of head, which is a superset and therefore safe,
    and the choice is printed. That decision lives here instead of behind `git fetch ...
    || true` in the workflow, because Art. VI does not allow that construct in a workflow
    file and a comment explaining this particular one would be the violation, not a
    mitigation.
    """
    if base_sha:
        return f"{base_sha}..{head_sha}"
    if before and set(before) != {"0"}:
        return f"{before}..{head_sha}"
    subprocess.run(["git", "fetch", "--no-tags", "origin", default_branch],
                   cwd=cwd, capture_output=True, text=True)
    resolved = subprocess.run(["git", "rev-parse", "--verify", "-q",
                               f"origin/{default_branch}"],
                              cwd=cwd, capture_output=True, text=True)
    if resolved.returncode == 0:
        count = subprocess.run(["git", "rev-list", "--count", f"origin/{default_branch}..{head_sha}"],
                               cwd=cwd, capture_output=True, text=True)
        if count.returncode == 0 and count.stdout.strip() != "0":
            return f"origin/{default_branch}..{head_sha}"
        # The push created the default branch itself, so origin/<default> already points
        # at head and the range above is empty. Reporting that as "did not run" failed the
        # gate on a repository's very first push. Full history is the honest range here.
        print(f"origin/{default_branch} already contains {head_sha}; inspecting full history")
    # A repository's very first push has no default branch to compare against. Inspecting
    # the whole history is a superset, which is safe here; erroring would block the
    # bootstrap commit of every new repo.
    return head_sha


def main() -> int:
    ap = argparse.ArgumentParser(description="book.md §5.5 — no AI co-author trailers")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--range", dest="rev_range", default="HEAD~1..HEAD",
                    help="commit range to inspect, e.g. base...head")
    ap.add_argument("--github", action="store_true")
    ap.add_argument("--auto", action="store_true",
                    help="resolve the range from the event instead of taking --range. "
                         "Doing it here rather than in shell keeps `git fetch || true` out "
                         "of the workflow file, which Art. VI forbids outright.")
    ap.add_argument("--base-sha", default="", help="--auto: pull request base")
    ap.add_argument("--head-sha", default="HEAD", help="--auto: head being tested")
    ap.add_argument("--before", default="", help="--auto: push event's previous head")
    ap.add_argument("--default-branch", default="main", help="--auto: fallback comparison point")
    ap.add_argument("--allow-empty", action="store_true",
                    help="accept a range that resolves to no commits (a fresh repo with a "
                         "single root commit is the only expected case)")
    args = ap.parse_args()

    if args.auto:
        args.rev_range = resolve_range(args.base_sha, args.head_sha, args.before,
                                       args.default_branch, args.repo)
        print(f"Inspecting range: {args.rev_range}")

    try:
        raw = subprocess.run(
            ["git", "log", "--format=%H%x1f%s%x1f%b%x1e", args.rev_range],
            cwd=args.repo, check=True, capture_output=True, text=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        print(f"::error::§5.5 gate could not run: {exc.stderr.strip() or exc}", file=sys.stderr)
        return 2

    offenders = []
    inspected = 0
    for record in raw.split("\x1e"):
        if not record.strip():
            continue
        inspected += 1
        sha, subject, body = (record.strip().split("\x1f") + ["", ""])[:3]
        for value in TRAILER.findall(body):
            if AI_IDENTITY.search(value):
                offenders.append((sha[:12], subject, value.strip()))

    for sha, subject, value in offenders:
        msg = (f"{sha} \"{subject}\" carries an AI co-author trailer: {value} — "
               f"book.md §5.5 forbids it. Amend or rebase the trailer out.")
        print(f"::error::{msg}" if args.github else f"BREACH {msg}")

    print(f"\n§5.5: {len(offenders)} offending commit(s) in {inspected} inspected ({args.rev_range})")
    if offenders:
        return 1
    if inspected == 0 and not args.allow_empty:
        # A range that resolves to nothing reports "clean" and goes green — the same
        # fake-gate shape as a scan of zero files. Every real push and pull request has
        # at least one commit, so an empty range means the range was wrong (bad base ref,
        # shallow clone), not that the history is clean. Art. VI: that is a failure.
        print(f"::error::§5.5 inspected 0 commits in '{args.rev_range}'. "
              f"The gate did not actually run — check the base ref and clone depth.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
