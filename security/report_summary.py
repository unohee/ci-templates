#!/usr/bin/env python3
"""Created: 2026-11-26
Purpose: render a scan summary (security/findings.py --summary) as markdown for a CI run summary.
  Used by the report-only whole-history audit, which must tell people what old history still holds
  without failing a job or blocking a merge.
Dependencies: python3 standard library.
Test Status: security/test_report_summary.py.
"""

from __future__ import annotations

import json
import sys


def render(summary: dict, limit: int = 50) -> str:
    findings = summary.get("findings") or []
    blocking = [f for f in findings if f.get("blocking")]
    lines = [
        "### Whole-history secret and dependency audit",
        "",
        f"- total findings: {summary.get('total', len(findings))}",
        f"- blocking: **{summary.get('blocking', len(blocking))}**",
    ]
    for finding in blocking[:limit]:
        lines.append(
            f"  - `{finding.get('rule', '?')}` "
            f"{finding.get('path', '?')}:{finding.get('line', '?')}"
        )
    if len(blocking) > limit:
        lines.append(f"  - and {len(blocking) - limit} more in the artifact")
    lines += [
        "",
        "This run is report-only: it never blocks a merge. What it reports is history that a pull "
        "request cannot reach.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: report_summary.py SUMMARY.json", file=sys.stderr)
        return 2
    try:
        with open(argv[1], encoding="utf-8") as handle:
            summary = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"No summary could be read ({error}); the scan did not reach its gate.", file=sys.stderr)
        return 2
    sys.stdout.write(render(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
