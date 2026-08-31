#!/usr/bin/env python3
"""Article II gate — no CRITICAL smell reported by `cxt bs`.

book.md Art. II: `cxt bs` runs before commit and a CRITICAL finding is critical —
disagree in writing with evidence or fix it, never drop it silently from the count.

This exists as a script rather than a shell step because the shell version needed
`cxt bs --json > bs.json || true` to keep a findings exit code from failing the step
before the JSON could be read. Under Art. VI that construct is not allowed in a workflow
file at all, and a comment explaining why this one is fine is the violation rather than a
mitigation. Running the tool from Python removes the need: a non-zero exit is just a
number here, and the parse decides.

Exit codes:
    0  no CRITICAL findings
    1  at least one CRITICAL finding
    2  the gate itself could not run (Art. VI: that is a failure, not a pass)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="book.md Art. II — cxt bs, no CRITICAL smells")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--command", default="cxt", help="cxt executable")
    ap.add_argument("--github", action="store_true")
    args = ap.parse_args()

    try:
        proc = subprocess.run([args.command, "bs", "--json"], cwd=args.repo,
                              capture_output=True, text=True)
    except OSError as exc:
        print(f"::error::Art. II gate could not run {args.command}: {exc}", file=sys.stderr)
        return 2

    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        # An unparseable report means the gate did not run. Art. VI: that is a failure.
        detail = (proc.stdout or proc.stderr).strip()[:500]
        print(f"::error::cxt bs produced no parseable JSON (exit {proc.returncode}):\n{detail}",
              file=sys.stderr)
        return 2

    scanned = report.get("filesScanned", 0)
    if scanned == 0:
        # A scan of nothing reports zero criticals and goes green — the fake-gate shape
        # this workflow exists to remove.
        print("::error::cxt bs scanned 0 files. The gate did not actually run (Art. VI).",
              file=sys.stderr)
        return 2
    if report.get("errors"):
        for err in report["errors"]:
            print(f"::error::cxt bs error: {err}", file=sys.stderr)
        return 2

    critical = [i for i in report.get("issues", []) if i.get("severity") == "critical"]
    for issue in critical:
        msg = f"[{issue.get('category')}] {issue.get('message')}"
        print(f"::error file={issue.get('file')},line={issue.get('line', 1)}::{msg}"
              if args.github else f"BREACH {issue.get('file')}:{issue.get('line', 1)} {msg}")

    print(f"\nArt. II: {len(critical)} critical, {report.get('warning', 0)} warning, "
          f"{report.get('minor', 0)} minor across {scanned} files")
    return 1 if critical else 0


if __name__ == "__main__":
    sys.exit(main())
