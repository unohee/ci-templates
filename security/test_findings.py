#!/usr/bin/env python3
"""Fixture tests for `security/findings.py`, the gate half of `security/scan.sh`.

Plain unittest, no dependencies. Run: python3 security/test_findings.py

These are the cases that decide whether a repository passes: a parser that silently drops a
finding turns the gate into decoration (book.md Art. VI), and a report that prints a secret
turns the log into a leak. Every test below is one of those two failures, or a baseline entry
that must not accept more than the one finding it names.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "findings.py"


def run(reports: dict[str, object], baseline: object | None = None) -> tuple[int, str, dict]:
    """Write the given reports to a temp dir, run the gate, return (exit, stdout, summary)."""
    with tempfile.TemporaryDirectory() as tmp:
        paths = {}
        for kind, payload in reports.items():
            path = Path(tmp) / f"{kind}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            paths[kind] = str(path)
        summary_path = Path(tmp) / "summary.json"
        cmd = [sys.executable, "-I", str(SCRIPT), "--root", tmp, "--summary", str(summary_path)]
        for kind, path in paths.items():
            cmd += [f"--{kind}", path]
        if baseline is not None:
            baseline_path = Path(tmp) / "baseline.json"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            cmd += ["--baseline", str(baseline_path)]
        proc = subprocess.run(cmd, capture_output=True, check=False)
        summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
        return proc.returncode, proc.stdout.decode(), summary


def gitleaks(leaks: list[dict]) -> list[dict]:
    return leaks


def semgrep(results: list[dict], errors: list | None = None) -> dict:
    return {"version": "test", "results": results, "errors": errors or []}


def semgrep_result(severity: str, confidence: str | None = None, line: int = 7) -> dict:
    metadata = {"confidence": confidence} if confidence else {}
    return {
        "check_id": "python.test.rule",
        "path": "scripts/thing.py",
        "start": {"line": line},
        "extra": {"severity": severity, "message": "a finding", "metadata": metadata},
    }


def osv(entries: list[dict]) -> dict:
    return {"results": entries}


def osv_entry(vuln_id: str = "GHSA-xxxx-yyyy-zzzz") -> dict:
    return {
        "source": {"path": "requirements.txt", "type": "lockfile"},
        "packages": [
            {
                "package": {"name": "requests", "version": "2.19.0", "ecosystem": "PyPI"},
                "vulnerabilities": [{"id": vuln_id, "summary": "a vulnerability"}],
            }
        ],
    }


class Gate(unittest.TestCase):
    def test_clean_reports_pass(self) -> None:
        code, out, summary = run({"gitleaks": gitleaks([]), "semgrep": semgrep([]), "osv": osv([])})
        self.assertEqual(code, 0, out)
        self.assertEqual(summary["blocking"], 0)

    def test_secret_blocks(self) -> None:
        leak = {
            "RuleID": "aws-access-token",
            "Description": "AWS",
            "File": "/repo/deploy/secrets.env",
            "StartLine": 3,
            "Secret": "AKIAIOSFODNN7EXAMPLE",
            "Match": "aws_access_key_id=AKIAIOSFODNN7EXAMPLE",
        }
        code, out, summary = run({"gitleaks": gitleaks([leak])})
        self.assertEqual(code, 1)
        self.assertIn("deploy/secrets.env", out)
        self.assertIn("aws-access-token", out)

    def test_report_never_carries_the_secret(self) -> None:
        """The summary is what a job uploads as an artifact; the secret must not be in it."""
        secret = "AKIAIOSFODNN7EXAMPLE"
        leak = {
            "RuleID": "aws-access-token",
            "Description": "AWS",
            "File": "/repo/.env",
            "StartLine": 1,
            "Secret": secret,
            "Match": f"aws_access_key_id={secret}",
        }
        code, out, summary = run({"gitleaks": gitleaks([leak])})
        self.assertEqual(code, 1)
        self.assertNotIn(secret, out)
        self.assertNotIn(secret, json.dumps(summary))

    def test_sast_error_blocks(self) -> None:
        code, out, _ = run({"semgrep": semgrep([semgrep_result("ERROR")])})
        self.assertEqual(code, 1, out)

    def test_sast_high_confidence_warning_blocks(self) -> None:
        """AUD-3009: an error-only gate let a high-confidence warning with a high
        security-severity through. Warnings the rule declares high-confidence block."""
        code, out, _ = run({"semgrep": semgrep([semgrep_result("WARNING", "high")])})
        self.assertEqual(code, 1, out)

    def test_sast_medium_warning_is_reported_not_blocking(self) -> None:
        code, out, summary = run({"semgrep": semgrep([semgrep_result("WARNING", "medium")])})
        self.assertEqual(code, 0, out)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["blocking"], 0)

    def test_sast_fatal_error_is_not_clean(self) -> None:
        """semgrep marks a scan that could not run with `level: error`."""
        code, out, _ = run(
            {"semgrep": semgrep([], errors=[{"level": "error", "message": "parse error"}])}
        )
        self.assertEqual(code, 2, out)

    def test_sast_warning_is_named_and_not_fatal(self) -> None:
        """A rule engine that could not finish one pattern is not a failed scan.

        Measured on de-artifact 2026-11-20: 79 entries, all `level: warn` (internal matching
        error on an embedded PowerShell block, partial YAML parse). The gate must not exit 2
        on those, and must not hide them either.
        """
        warning = {"level": "warn", "type": "Internal matching error", "code": 2}
        code, out, _ = run({"semgrep": semgrep([], errors=[warning])})
        self.assertEqual(code, 0, out)
        self.assertIn("non-fatal warning", out)
        self.assertIn("Internal matching error", out)

    def test_sast_warning_with_a_value_list_type_stays_short(self) -> None:
        """semgrep sets `type` to the rule's value list for a partial parse.

        Printing it whole put 15 KB of source into the log (de-artifact, 2026-11-20: 79 entries),
        which buries the finding table. Only the name survives.
        """
        warning = {
            "level": "warn",
            "type": ["PartialParsing", [{"path": "x.yml", "start": {"line": 1, "col": 1}}]],
        }
        code, out, _ = run({"semgrep": semgrep([], errors=[warning])})
        self.assertEqual(code, 0, out)
        note = next(line for line in out.splitlines() if "non-fatal warning" in line)
        self.assertIn("PartialParsing x1", note)
        self.assertLess(len(note), 120, note)

    def test_dependency_vulnerability_blocks(self) -> None:
        code, out, _ = run({"osv": osv([osv_entry()])})
        self.assertEqual(code, 1, out)
        self.assertIn("requests 2.19.0", out)

    def test_unreadable_report_is_tooling_failure(self) -> None:
        code, out, _ = run({"semgrep": "not an object"})
        self.assertEqual(code, 2, out)

    def test_baseline_accepts_only_the_named_finding(self) -> None:
        entry = {
            "tool": "deps",
            "rule": "GHSA-xxxx-yyyy-zzzz",
            "path": "requirements.txt",
            "line": 0,
            "reason": "not reachable from the shipped binary (AUD-0000)",
            "added": "2026-11-20",
        }
        accepted, out, summary = run({"osv": osv([osv_entry()])}, baseline={"accepted": [entry]})
        self.assertEqual(accepted, 0, out)
        self.assertIn("accepted", out)
        self.assertIn("not reachable", out)
        self.assertEqual(summary["blocking"], 0)
        # A different vulnerability in the same file must still block.
        other, out2, _ = run({"osv": osv([osv_entry("GHSA-1111-2222-3333")])},
                             baseline={"accepted": [entry]})
        self.assertEqual(other, 1, out2)

    def test_baseline_without_a_reason_still_records_one(self) -> None:
        entry = {"tool": "sast", "rule": "python.test.rule", "path": "scripts/thing.py", "line": 7}
        code, out, _ = run({"semgrep": semgrep([semgrep_result("ERROR")])}, baseline=[entry])
        self.assertEqual(code, 0, out)
        self.assertIn("(no reason recorded)", out)


    def test_write_baseline_records_the_reason_and_unblocks_the_next_run(self) -> None:
        """The first run on a repository full of pre-existing findings must be recordable,
        with the reason next to every entry, and the recorded baseline must be what the next
        run gates against."""
        with tempfile.TemporaryDirectory() as tmp:
            sem = Path(tmp) / "semgrep.json"
            sem.write_text(json.dumps(semgrep([semgrep_result("ERROR")])), encoding="utf-8")
            baseline_path = Path(tmp) / "security-baseline.json"

            def run_script(*extra: str) -> subprocess.CompletedProcess:
                return subprocess.run(
                    [sys.executable, "-I", str(SCRIPT), "--root", tmp, "--semgrep", str(sem), *extra],
                    capture_output=True,
                    check=False,
                )

            first = run_script(
                "--write-baseline", str(baseline_path),
                "--baseline-reason", "pre-existing before the gate existed (AUD-1)",
                "--today", "2026-11-20",
            )
            # The run that records the baseline still reports what it recorded as blocking;
            # a writer that also turned the run green would hide the state it just accepted.
            self.assertEqual(first.returncode, 1, first.stdout.decode())
            written = json.loads(baseline_path.read_text())
            self.assertEqual(len(written["accepted"]), 1)
            self.assertEqual(written["accepted"][0]["reason"], "pre-existing before the gate existed (AUD-1)")
            self.assertEqual(written["accepted"][0]["added"], "2026-11-20")
            self.assertEqual(written["accepted"][0]["tool"], "sast")

            second = run_script("--baseline", str(baseline_path))
            self.assertEqual(second.returncode, 0, second.stdout.decode())

    def test_write_baseline_refuses_an_absolute_path(self) -> None:
        """A baseline entry with an absolute path can never match: the export directory changes
        every run. This was measured the hard way — a baseline written with the repository as
        --root instead of the exported tree recorded /tmp/.../src/Cargo.lock and accepted
        nothing, so the gate failed on the same findings on every run afterwards.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            export = Path(tmp) / "export"
            export.mkdir()
            osv_report = Path(tmp) / "osv.json"
            entry = osv_entry()
            entry["source"] = {"path": str(export / "requirements.txt")}
            osv_report.write_text(json.dumps({"results": [entry]}), encoding="utf-8")
            target = Path(tmp) / "baseline.json"
            proc = subprocess.run(
                [sys.executable, "-I", str(SCRIPT), "--root", str(root), "--osv", str(osv_report),
                 "--write-baseline", str(target), "--baseline-reason", "test"],
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 2, proc.stdout.decode())
            self.assertIn("absolute path", proc.stderr.decode())
            self.assertFalse(target.exists())

    def test_write_baseline_without_a_reason_is_refused(self) -> None:
        code, out, _ = run({}, baseline=None)
        self.assertEqual(code, 0, out)  # sanity: no reports, nothing to gate
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, "-I", str(SCRIPT), "--root", tmp,
                 "--write-baseline", str(Path(tmp) / "b.json")],
                capture_output=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("--baseline-reason", proc.stderr.decode())


if __name__ == "__main__":
    unittest.main(verbosity=2)
