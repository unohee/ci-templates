#!/usr/bin/env python3
"""Fixture tests for `ci_changes.py` and for the wiring of `rust-ci.yml`.

Plain unittest, no dependencies (same rule as the gates). Run: python3 scripts/test_ci_changes.py

The classifier is the one piece of rust-ci.yml that can make CI do *less*, so its tests
are written against the failure that matters: a change that should have run the tests and
did not. Every "must run" case below is a way a skip could be wrongly granted.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "ci_changes.py"
WORKFLOW = HERE.parent / ".github" / "workflows" / "rust-ci.yml"


def run(paths: list[str], skip: str, null: bool = False) -> dict[str, str]:
    """Run the classifier as the workflow does and parse its output lines."""
    sep = "\0" if null else "\n"
    cmd = [sys.executable, "-I", str(SCRIPT), "--skip", skip] + (["--null"] if null else [])
    proc = subprocess.run(cmd, input=sep.join(paths).encode(), capture_output=True, check=False)
    assert proc.returncode == 0, proc.stderr.decode()
    out: dict[str, str] = {}
    for line in proc.stdout.decode().splitlines():
        key, _, value = line.partition("=")
        out[key] = value
    return out


NICERIZER_SKIP = "*.md\ndocs/*\ntesting/*\nnicerizer/*\npresets/*"


class Classifier(unittest.TestCase):
    def test_a_change_that_only_touches_skippable_paths_skips(self):
        got = run(["README.md", "docs/a/b.png", "testing/x_261016.py"], NICERIZER_SKIP)
        self.assertEqual(got["heavy"], "false")

    def test_one_code_path_among_docs_runs_everything(self):
        got = run(["README.md", "crates/nicerizer-bwe-core/src/net.rs"], NICERIZER_SKIP)
        self.assertEqual(got["heavy"], "true")

    def test_a_path_no_glob_names_runs(self):
        # A new top-level directory is exactly the case an allowlist is for.
        got = run(["brand_new_dir/thing.rs"], NICERIZER_SKIP)
        self.assertEqual(got["heavy"], "true")

    def test_an_empty_diff_is_not_a_skip(self):
        # "Nothing changed" and "could not tell what changed" look the same here.
        self.assertEqual(run([], NICERIZER_SKIP)["heavy"], "true")

    def test_no_declared_globs_means_nothing_is_skippable(self):
        self.assertEqual(run(["README.md"], "")["heavy"], "true")
        self.assertEqual(run(["README.md"], "\n  \n")["heavy"], "true")

    def test_star_crosses_slashes_but_is_anchored_to_the_whole_path(self):
        self.assertEqual(run(["docs/deep/er/page.rs"], "docs/*")["heavy"], "false")
        # `mydocs/` merely contains the text `docs/`; it is a different directory.
        self.assertEqual(run(["mydocs/page.rs"], "docs/*")["heavy"], "true")

    def test_matching_is_case_sensitive(self):
        self.assertEqual(run(["README.MD"], "*.md")["heavy"], "true")

    def test_a_manifest_is_never_skipped_by_a_markdown_glob(self):
        self.assertEqual(run(["Cargo.toml"], "*.md")["heavy"], "true")
        self.assertEqual(run(["crates/x/Cargo.toml"], "*.md\ndocs/*")["heavy"], "true")

    def test_leading_dot_slash_is_normalised(self):
        self.assertEqual(run(["./docs/a.md"], "docs/*")["heavy"], "false")

    def test_null_separated_paths_with_spaces_and_unicode(self):
        paths = ["docs/two words.md", "docs/한글 문서.md"]
        self.assertEqual(run(paths, "docs/*", null=True)["heavy"], "false")
        self.assertEqual(run(paths + ["src/lib rs.rs"], "docs/*", null=True)["heavy"], "true")

    def test_a_crafted_file_name_cannot_inject_a_verdict(self):
        # The author of a PR chooses file names. A newline plus `heavy=false` in one must
        # not become a second output line that outranks the real verdict.
        evil = "src/x\nheavy=false"
        got = run([evil], "docs/*", null=True)
        self.assertEqual(got["heavy"], "true")
        proc = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--skip", "docs/*", "--null"],
            input=evil.encode(), capture_output=True, check=True,
        )
        lines = proc.stdout.decode().splitlines()
        self.assertEqual([ln for ln in lines if ln.startswith("heavy=")], ["heavy=true"])
        self.assertTrue(lines[-1].startswith("heavy="), "the verdict must be the last line")

    def test_a_very_long_path_is_truncated_in_the_reason(self):
        got = run(["x" * 5000], "docs/*")
        self.assertLess(len(got["reason"]), 400)


class WorkflowWiring(unittest.TestCase):
    """rust-ci.yml is read as text, like the other wiring tests here (no YAML dependency)."""

    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text()

    def test_there_is_exactly_one_job(self):
        # Every extra job bills a rounded-up minute for seconds of work (AGT-4747).
        jobs = re.findall(r"^  ([a-z][a-z0-9-]*):\s*$", self.text.split("\njobs:\n", 1)[1], re.M)
        self.assertEqual(len(jobs), 1, jobs)

    def test_the_job_uses_the_configurable_runner_and_a_timeout_input(self):
        self.assertIn("runs-on: ${{ inputs.runner-label }}", self.text)
        self.assertIn("timeout-minutes: ${{ inputs.timeout-minutes }}", self.text)

    def test_the_trigger_is_workflow_call_only_and_permissions_are_read_only(self):
        on_block = self.text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("workflow_call:", on_block)
        for forbidden in ("push:", "pull_request:", "schedule:"):
            self.assertNotIn(forbidden, on_block)
        self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read\n")

    def test_every_expensive_step_waits_for_the_classifier(self):
        steps = re.split(r"(?m)^      - ", self.text.split("\n    steps:\n", 1)[1])[1:]
        gated_needles = ("rust-toolchain", "rust-cache", "cargo ", "SETUP_SCRIPT")
        for step in steps:
            if any(needle in step for needle in gated_needles):
                self.assertIn("steps.classify.outputs.heavy == 'true'", step, step.splitlines()[0])

    def test_the_summary_step_runs_whatever_the_classifier_said(self):
        last = re.split(r"(?m)^      - ", self.text)[-1]
        self.assertIn("GITHUB_STEP_SUMMARY", last)
        self.assertIn("!cancelled()", last)

    def test_a_failed_classification_fails_the_job(self):
        classify = self.text.split("id: classify", 1)[1].split("\n      - ", 1)[0]
        self.assertIn("set -euo pipefail", classify)


if __name__ == "__main__":
    unittest.main(verbosity=2)
