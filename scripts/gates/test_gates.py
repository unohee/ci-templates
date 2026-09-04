#!/usr/bin/env python3
"""Fixture tests for the constitution gates.

Every case here is a boundary that was wrong in review before it was right: each one
reproduces a defect that shipped in the first draft. They are kept in version control so
the next change to a gate has to pass them rather than re-derive them.

Run: python3 scripts/gates/test_gates.py
Exit 0 all pass, 1 otherwise. Plain unittest, no dependencies (ARCHITECTURE.md invariant 3).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GATES = Path(__file__).resolve().parent


def run_gate(script: str, *args: str) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(GATES / script), *args],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def git(cwd: Path, *args: str, when: str | None = None) -> None:
    env = dict(os.environ)
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


def new_repo(tmp: str) -> Path:
    repo = Path(tmp)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "gate@test")
    git(repo, "config", "user.name", "Gate Test")
    return repo


def write_workflow(repo: Path, name: str, body: str) -> None:
    d = repo / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")


class WorkflowIntegrity(unittest.TestCase):
    """Art. VI — the first draft anchored `|| true` to end of line and leaked."""

    def test_catches_constructs_anywhere_on_the_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            write_workflow(repo, "bad.yml", """
jobs:
  a:
    steps:
      - run: set +e; false
      - run: false || true; echo hidden
      - run: pytest || true && echo done
      - run: bandit -r . || : ; echo next
      - name: x
        continue-on-error: true
      - name: y
        continue-on-error: ${{ matrix.experimental }}
      - run: flake8 --exit-zero .
""".lstrip())
            code, out = run_gate("workflow_integrity.py", "--repo", str(repo))
            self.assertEqual(code, 1, out)
            self.assertEqual(out.count("BREACH"), 7, out)

    def test_prose_and_explicit_false_are_not_breaches(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            write_workflow(repo, "good.yml", """
jobs:
  a:
    steps:
      # continue-on-error: true would defeat this gate, so it is not used
      - run: pytest -q
      - name: explicit
        continue-on-error: false
        run: ruff check .
""".lstrip())
            code, out = run_gate("workflow_integrity.py", "--repo", str(repo))
            self.assertEqual(code, 0, out)

    def test_no_comment_can_excuse_a_construct(self):
        """Review found the first draft's `# constitution-allow:` marker let `pytest ||
        true` pass. Art. VI's amended text calls the justifying comment the violation."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            write_workflow(repo, "marked.yml", """
jobs:
  a:
    steps:
      - run: pytest || true   # constitution-allow: we know what we are doing
      - run: ruff check . || true   # the parse below decides
""".lstrip())
            code, out = run_gate("workflow_integrity.py", "--repo", str(repo))
            self.assertEqual(code, 1, out)
            self.assertEqual(out.count("BREACH"), 2, out)

    def test_a_hash_inside_quotes_does_not_hide_the_rest_of_the_line(self):
        """Review round 3: cutting at the first `#` made
        `printf '# ready'; pytest -q || true` invisible to the scanner."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            write_workflow(repo, "quoted.yml", """
jobs:
  a:
    steps:
      - run: printf '# ready'; pytest -q || true
      - run: echo "# note" && ruff check . || true
      - run: echo "safe"   # || true is only discussed here
      # a comment line mentioning || true must not be a breach
      - run: pytest -q
""".lstrip())
            code, out = run_gate("workflow_integrity.py", "--repo", str(repo))
            self.assertEqual(code, 1, out)
            self.assertEqual(out.count("BREACH"), 2, out)

    def test_multiline_run_blocks_are_scanned_line_by_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            write_workflow(repo, "block.yml", """
jobs:
  a:
    steps:
      - run: |
          echo start
          mypy . || true
          echo end
      - run: >
          bandit -r .
          || true
""".lstrip())
            code, out = run_gate("workflow_integrity.py", "--repo", str(repo))
            self.assertEqual(code, 1, out)
            self.assertEqual(out.count("BREACH"), 2, out)

    def test_the_moves_reached_for_once_or_true_is_blocked(self):
        """Self-audit, not review: `|| exit 0` and a trailing `; true` do the same job."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            write_workflow(repo, "next.yml", """
jobs:
  a:
    steps:
      - run: pytest || exit 0
      - run: ruff check .; true
      - run: mypy . ; exit 0
      - run: echo fine && pytest -q
""".lstrip())
            code, out = run_gate("workflow_integrity.py", "--repo", str(repo))
            self.assertEqual(code, 1, out)
            self.assertEqual(out.count("BREACH"), 3, out)

    def test_escaped_quotes_and_split_operators(self):
        """Branch review: a `#` after an escaped quote hid the rest of the line, and an
        operator split across lines was not joined before scanning."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            write_workflow(repo, "esc.yml", r"""
jobs:
  a:
    steps:
      - run: echo "foo\" # fake" ; pytest -q || true
      - run: >
          bandit -r . ||
          true
      - run: |
          mypy .             || true
      - run: echo ok   # || true only in a comment
      - run: pytest -q
""".lstrip())
            code, out = run_gate("workflow_integrity.py", "--repo", str(repo))
            self.assertEqual(code, 1, out)
            self.assertEqual(out.count("BREACH"), 3, out)

    def test_no_workflow_files_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            (repo / ".github" / "workflows").mkdir(parents=True)
            code, _ = run_gate("workflow_integrity.py", "--repo", str(repo))
            self.assertEqual(code, 2)


class LocClock(unittest.TestCase):
    """Art. III — the clock and the count must both match what the Article measures."""

    def test_code_after_a_block_comment_closes_is_counted(self):
        """`/**/int x = 1;` is a code line. Dropping it made 1,501 such lines measure as
        zero while `cxt loc --no-blank --no-comments` reported a breach."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            (repo / "big.c").write_text(
                "\n".join(f"/**/int x{i} = 1;" for i in range(1501)) + "\n", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "c")
            code, out = run_gate("loc_clock.py", "--repo", str(repo), "--ceiling", "1500")
            self.assertIn("1501 code lines", out)
            self.assertEqual(code, 0, out)   # new file: on the clock, not yet a breach

    @staticmethod
    def _big(repo: Path, name: str, tag: str) -> None:
        (repo / name).write_text("\n".join(f"{tag}={i}" for i in range(1800)), encoding="utf-8")

    def test_readding_a_path_resets_the_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            self._big(repo, "over.py", "x")
            git(repo, "add", "-A", when="2026-06-01T10:00:00")
            git(repo, "commit", "-qm", "big", when="2026-06-01T10:00:00")
            git(repo, "rm", "-q", "over.py")
            git(repo, "commit", "-qm", "delete", when="2026-07-01T10:00:00")
            self._big(repo, "over.py", "y")
            git(repo, "add", "-A", when="2026-08-31T10:00:00")
            git(repo, "commit", "-qm", "re-add", when="2026-08-31T10:00:00")
            code, out = run_gate("loc_clock.py", "--repo", str(repo), "--ceiling", "1500")
            self.assertEqual(code, 0, out)
            self.assertIn("CLOCK", out)
            self.assertIn("0 breach", out)


class ArchitectureDoc(unittest.TestCase):
    """Art. IV — the map moves in the same commit as the structure, not merely the PR."""

    @staticmethod
    def _seed(repo: Path) -> str:
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("x\n", encoding="utf-8")
        (repo / "ARCHITECTURE.md").write_text("# Architecture\n\nsrc/.\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "init")
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                              capture_output=True, text=True).stdout.strip()

    def test_doc_in_a_later_commit_is_a_breach(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            base = self._seed(repo)
            (repo / "adapters").mkdir()
            (repo / "adapters" / "b.py").write_text("y\n", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "split")
            (repo / "ARCHITECTURE.md").write_text("# Architecture\n\nsrc/ adapters/.\n", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "docs later")
            code, out = run_gate("architecture_doc.py", "--repo", str(repo),
                                 "--base-ref", base, "--head-ref", "HEAD")
            self.assertEqual(code, 1, out)
            self.assertIn("same commit", out)

    def test_push_event_still_runs_the_freshness_half(self):
        """The workflow passes `github.event.before` as the base on a push. Without it a
        direct-push repository skipped the structural check and exited 0."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            before = self._seed(repo)
            (repo / "adapters").mkdir()
            (repo / "adapters" / "b.py").write_text("y\n", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "push straight to main, no map")
            code, out = run_gate("architecture_doc.py", "--repo", str(repo),
                                 "--base-ref", before, "--head-ref", "HEAD")
            self.assertEqual(code, 1, out)

    def test_a_new_repos_first_push_is_not_an_error(self):
        """Branch review: GitHub sends forty zeros as `before` on a first push, and
        `git diff 000...HEAD` is fatal. The gate exited 2 and failed the whole
        constitution workflow at the moment a repository adopts it."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            self._seed(repo)
            code, out = run_gate("architecture_doc.py", "--repo", str(repo),
                                 "--base-ref", "0" * 40, "--head-ref", "HEAD")
            self.assertEqual(code, 0, out)
            self.assertIn("NOT RUN", out)

    def test_same_commit_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            base = self._seed(repo)
            (repo / "adapters").mkdir()
            (repo / "adapters" / "b.py").write_text("y\n", encoding="utf-8")
            (repo / "ARCHITECTURE.md").write_text("# Architecture\n\nsrc/ adapters/.\n", encoding="utf-8")
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "split and map together")
            code, out = run_gate("architecture_doc.py", "--repo", str(repo),
                                 "--base-ref", base, "--head-ref", "HEAD")
            self.assertEqual(code, 0, out)


class CommitTrailers(unittest.TestCase):
    """§5.5 — the judgement path itself, which no fixture covered before."""

    @staticmethod
    def _commit(repo: Path, subject: str, body: str = "") -> None:
        (repo / "f.txt").write_text(subject, encoding="utf-8")
        git(repo, "add", "-A")
        msg = subject if not body else f"{subject}\n\n{body}"
        git(repo, "commit", "-qm", msg)

    def test_ai_trailer_is_a_breach_and_a_human_name_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            self._commit(repo, "clean")
            base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                  capture_output=True, text=True).stdout.strip()
            self._commit(repo, "human co-author",
                         "Co-Authored-By: Claude Martin <claude.martin@example.com>")
            code, out = run_gate("commit_trailers.py", "--repo", str(repo),
                                 "--range", f"{base}..HEAD")
            self.assertEqual(code, 0, out)

            self._commit(repo, "agent trailer",
                         "Co-Authored-By: Claude <noreply@anthropic.com>")
            code, out = run_gate("commit_trailers.py", "--repo", str(repo),
                                 "--range", f"{base}..HEAD")
            self.assertEqual(code, 1, out)

    def test_an_empty_range_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            self._commit(repo, "only commit")
            code, _ = run_gate("commit_trailers.py", "--repo", str(repo),
                               "--range", "HEAD..HEAD")
            self.assertEqual(code, 2)

    def test_a_new_repos_first_push_inspects_its_full_history(self):
        """A repository's first push (intrect-ax, 2026-09-04): `before` was forty zeros and
        the pushed branch was the default branch itself, so `--auto` resolved
        `origin/main..HEAD`, which is empty, and the gate exited 2 at the moment the
        repository adopted it. The range must fall back to the full history — and still
        judge it, so a trailer on the bootstrap commit is caught."""
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as bare:
            origin = Path(bare)
            git(origin, "init", "-q", "--bare", "-b", "main")
            repo = new_repo(tmp)
            self._commit(repo, "bootstrap")
            git(repo, "remote", "add", "origin", str(origin))
            git(repo, "push", "-q", "origin", "main")
            auto = ("--auto", "--before", "0" * 40, "--head-sha", "HEAD", "--default-branch", "main")
            code, out = run_gate("commit_trailers.py", "--repo", str(repo), *auto)
            self.assertEqual(code, 0, out)
            self.assertIn("1 inspected", out)

            self._commit(repo, "bootstrap with agent trailer",
                         "Co-Authored-By: Claude <noreply@anthropic.com>")
            git(repo, "push", "-q", "origin", "main")
            code, out = run_gate("commit_trailers.py", "--repo", str(repo), *auto)
            self.assertEqual(code, 1, out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
