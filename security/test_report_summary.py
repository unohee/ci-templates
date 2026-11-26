#!/usr/bin/env python3
"""Created: 2026-11-26
Purpose: test security/report_summary.py, the markdown renderer behind the report-only whole-history
  audit. The renderer must name blocking findings without printing their values, and must fail
  loudly (exit 2) when the summary is missing or unreadable, so a silent audit is never mistaken
  for a clean one.
Dependencies: python3 standard library.
Test Status: this is the test. Run: python3 -I security/test_report_summary.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
script = os.path.join(here, "report_summary.py")
passed = 0
failed = 0


def ok(name: str) -> None:
    global passed
    passed += 1
    print(f"ok    {name}")


def bad(name: str, detail: str = "") -> None:
    global failed
    failed += 1
    print(f"FAIL  {name} {detail}".rstrip())


def run(path: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, "-I", script, path], capture_output=True, text=True
    )
    return result.returncode, result.stdout + result.stderr


def write(directory: str, payload: object) -> str:
    path = os.path.join(directory, "summary.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path


with tempfile.TemporaryDirectory() as work:
    # A clean audit says so, and says it does not block.
    code, text = run(write(work, {"total": 0, "blocking": 0, "findings": []}))
    if code == 0:
        ok("a clean summary renders")
    else:
        bad("a clean summary renders", f"(exit {code})")
    if "never blocks a merge" in text:
        ok("the report says it does not block")
    else:
        bad("the report says it does not block")

    # A blocking finding is named by rule and place, never by value.
    secret = "stub-secret-value-1234567890"
    payload = {
        "total": 1,
        "blocking": 1,
        "findings": [
            {
                "tool": "secret",
                "rule": "generic-api-key",
                "path": "docs/design/figma-spec/toolbar.md",
                "line": 3,
                "message": "Generic API Key",
                "blocking": True,
            }
        ],
    }
    code, text = run(write(work, payload))
    if code == 0 and "generic-api-key" in text and "toolbar.md:3" in text:
        ok("a blocking finding is named")
    else:
        bad("a blocking finding is named", text[:200])
    if secret not in text:
        ok("the report carries no secret value")
    else:
        bad("the report carries no secret value")

    # More findings than the limit are counted, not dropped.
    many = {
        "total": 60,
        "blocking": 60,
        "findings": [
            {"tool": "secret", "rule": "r", "path": f"f{i}.txt", "line": 1, "blocking": True}
            for i in range(60)
        ],
    }
    code, text = run(write(work, many))
    if code == 0 and "and 10 more in the artifact" in text:
        ok("findings past the limit are counted")
    else:
        bad("findings past the limit are counted", text[-200:])

# A summary that cannot be read is a failure, never a clean audit.
code, text = run(os.path.join(tempfile.gettempdir(), "no-such-summary.json"))
if code == 2:
    ok("a missing summary exits 2")
else:
    bad("a missing summary exits 2", f"(exit {code}, want 2)")

print(f"\ntest_report_summary: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
