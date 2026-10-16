#!/usr/bin/env python3
"""Fixture tests for the constitution gates.

Every case here is a boundary that was wrong in review before it was right: each one
reproduces a defect that shipped in the first draft. They are kept in version control so
the next change to a gate has to pass them rather than re-derive them.

Run: python3 scripts/gates/test_gates.py
Exit 0 all pass, 1 otherwise. Plain unittest, no dependencies (ARCHITECTURE.md invariant 3).
"""

from __future__ import annotations

import ast
import os
import subprocess
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

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


def days_ago(days: int) -> str:
    """A git date `days` before the real now, in git's raw `<epoch> <tz>` form.

    Every gate that measures age compares commit dates with `time.time()`, so a fixture
    that writes an absolute date is correct only on the day it was written. This one
    committed `2026-08-31` as "today" and went red for every caller on 2026-10-01, when
    that date became 31 days old — with no change to any gate or caller. Dates are built
    from the offset the case is about (30-day window, age of the oversized file), never
    from the calendar.
    """
    return f"{int(time.time()) - days * 86400} +0000"


def init_repo(repo: Path) -> None:
    """Create a fixture repository with main as its initial branch."""
    try:
        git(repo, "init", "-q", "-b", "main")
    except subprocess.CalledProcessError as exc:
        # Git before 2.28 does not support `git init -b`. Keep the fixture
        # branch invariant instead of failing self-hosted Ubuntu 20.04 jobs.
        if exc.returncode != 129:
            raise
        git(repo, "init", "-q")
        git(repo, "checkout", "-q", "-b", "main")


def new_repo(tmp: str) -> Path:
    repo = Path(tmp)
    init_repo(repo)
    git(repo, "config", "user.email", "gate@test")
    git(repo, "config", "user.name", "Gate Test")
    return repo


def write_workflow(repo: Path, name: str, body: str) -> None:
    d = repo / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")


class WorkflowIntegrity(unittest.TestCase):
    """Art. VI — the first draft anchored `|| true` to end of line and leaked."""

    def test_old_git_initializes_main_branch_without_init_dash_b(self):
        repo = Path("/fixture")
        unsupported = subprocess.CalledProcessError(129, ["git", "init", "-b", "main"])
        with mock.patch(f"{__name__}.git", side_effect=[unsupported, None, None]) as invoke:
            init_repo(repo)

        self.assertEqual(invoke.call_args_list, [
            mock.call(repo, "init", "-q", "-b", "main"),
            mock.call(repo, "init", "-q"),
            mock.call(repo, "checkout", "-q", "-b", "main"),
        ])

    def test_runner_does_not_require_path_is_relative_to(self):
        """Ubuntu 20.04's Python 3.8 has relative_to(), but not is_relative_to()."""
        source = (GATES / "workflow_integrity.py").read_text(encoding="utf-8")
        calls = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "is_relative_to"
        ]
        self.assertEqual(calls, [])

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
        """The first add is 90 days old, well past the 30-day window, so a clock that walks
        through the delete and back to it reports a breach; the re-add is one day old, so
        a clock that resets at the re-add reports a file on the clock."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(tmp)
            self._big(repo, "over.py", "x")
            git(repo, "add", "-A", when=days_ago(90))
            git(repo, "commit", "-qm", "big", when=days_ago(90))
            git(repo, "rm", "-q", "over.py")
            git(repo, "commit", "-qm", "delete", when=days_ago(60))
            self._big(repo, "over.py", "y")
            git(repo, "add", "-A", when=days_ago(1))
            git(repo, "commit", "-qm", "re-add", when=days_ago(1))
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


class RunnerSelection(unittest.TestCase):
    """A caller-selected runner must govern every reusable workflow job."""

    def test_every_job_uses_the_configurable_runner_label(self):
        workflow = GATES.parents[1] / ".github" / "workflows" / "constitution-gate.yml"
        body = workflow.read_text(encoding="utf-8")
        self.assertIn("runner-label:", body)
        self.assertIn("default: 'ubuntu-latest'", body)
        # Every runs-on line, however many jobs there are, takes the caller's label.
        self.assertGreaterEqual(body.count("runs-on:"), 1)
        self.assertEqual(body.count("runs-on:"), body.count("runs-on: ${{ inputs.runner-label }}"))

    def test_python_job_uses_the_configurable_runner_label(self):
        workflow = GATES.parents[1] / ".github" / "workflows" / "python-ci.yml"
        body = workflow.read_text(encoding="utf-8")
        self.assertIn("runner-label:", body)
        self.assertIn('default: "ubuntu-latest"', body)
        self.assertEqual(body.count("runs-on: ${{ inputs.runner-label }}"), 1)

    def test_python_pip_cache_is_only_for_github_hosted_runners(self):
        # On a self-hosted runner `cache: pip` uploaded the runner user's whole
        # ~/.cache/pip — 4.6 GB, 82 s per run on vega-cli (2026-10-16).
        workflow = GATES.parents[1] / ".github" / "workflows" / "python-ci.yml"
        body = workflow.read_text(encoding="utf-8")
        self.assertNotRegex(body, r"(?m)^\s+cache:\s*pip\s*$")
        line = re.search(r"(?m)^\s+cache:\s*(.+)$", body).group(1)
        for hosted in ("ubuntu", "macos", "windows"):
            self.assertIn(f"startsWith(inputs.runner-label, '{hosted}')", line)
        self.assertTrue(line.endswith("&& 'pip' || '' }}"), line)


class OneGateJob(unittest.TestCase):
    """The gates run as steps of one job (AGT-4747), so their wiring is checked here.

    Seven jobs billed a minute each for checks that take seconds. As steps, two things
    can silently break that jobs gave for free: a failed gate stopping the gates after it,
    and the integrity step not looking at a gate that was added later.
    """

    def _steps(self):
        workflow = GATES.parents[1] / ".github" / "workflows" / "constitution-gate.yml"
        body = workflow.read_text(encoding="utf-8")
        jobs = body[body.index("\njobs:\n"):]
        chunks = jobs.split("\n      - ")[1:]
        return body, jobs, chunks

    def test_there_is_one_job(self):
        _, jobs, _ = self._steps()
        top = [ln for ln in jobs.splitlines() if ln.startswith("  ") and not ln.startswith("   ")
               and ln.rstrip().endswith(":")]
        self.assertEqual(top, ["  gate:"])

    def test_every_gate_step_runs_after_an_earlier_failure_and_is_checked(self):
        _, _, chunks = self._steps()
        gates = [c for c in chunks if "\n        id: " in c]
        self.assertEqual(len(gates), 6, "six gates, each a step with an id")
        integrity = chunks[-1]
        self.assertIn("every gate ran and passed", integrity)
        self.assertIn("if: ${{ !cancelled() }}", integrity)
        for gate in gates:
            step_id = gate.split("\n        id: ")[1].split("\n")[0].strip()
            self.assertIn("if: ${{ !cancelled() }}", gate, step_id)
            self.assertIn(f"steps.{step_id}.outcome", integrity, step_id)

    def test_the_integrity_step_fails_on_anything_but_success(self):
        _, _, chunks = self._steps()
        integrity = chunks[-1]
        self.assertIn('if [ "$result" != "success" ]', integrity)
        self.assertIn("exit $fail", integrity)


class WasteGuards(unittest.TestCase):
    """Billing waste, kept out by shape (AGT-4747).

    CI minutes are billed per job, rounded up, so the waste is structural: a hung job with
    no timeout, and a duplicate run of the same commit. Each guard checks the *shape* of
    the workflow or the README, never its exact wording. This suite runs on every caller's
    CI and ci-templates' main has no branch protection, so a test that broke on a reworded
    sentence would turn every caller red. Each guard also refuses to pass when its parser
    found nothing, so a changed file layout cannot make it vacuous.
    """

    WORKFLOWS = GATES.parents[1] / ".github" / "workflows"
    README = GATES.parents[1] / "README.md"

    @staticmethod
    def _jobs(body):
        """Map job id -> the lines of its block.

        Text parsing on purpose: gate scripts depend on nothing but Python 3 (invariant 3)
        and PyYAML is not guaranteed on a caller's runner. Job ids sit at two spaces and
        job keys at four, which is what every workflow here uses.
        """
        lines = body.splitlines()
        start = next((i for i, ln in enumerate(lines) if ln.rstrip() == "jobs:"), None)
        if start is None:
            return {}
        jobs, current = {}, None
        for ln in lines[start + 1:]:
            if not ln.strip() or ln.lstrip().startswith("#"):
                if current is not None:
                    jobs[current].append(ln)
                continue
            if not ln.startswith(" "):
                break  # the next top-level key ends the jobs block
            match = re.match(r"^  ([A-Za-z0-9_-]+):\s*(#.*)?$", ln)
            if match:
                current = match.group(1)
                jobs[current] = []
            elif current is not None:
                jobs[current].append(ln)
        return jobs

    @staticmethod
    def _has_job_key(lines, key):
        return any(re.match(r"^    " + re.escape(key) + r":", ln) for ln in lines)

    @staticmethod
    def _value(body, key):
        match = re.search(r"^\s*" + re.escape(key) + r":\s*(.+?)\s*$", body, re.MULTILINE)
        return match.group(1) if match else ""

    def _assert_pr_only_cancel(self, body, where):
        """Only a pull request may be cancelled; a push must get a group of its own."""
        group = self._value(body, "group")
        cancel = self._value(body, "cancel-in-progress")
        self.assertIn("github.event_name", group, f"{where}: group must branch on the event")
        self.assertIn("github.sha", group, f"{where}: a push needs a group per commit")
        self.assertIn("github.event_name", cancel, f"{where}: cancel must depend on the event")
        self.assertIn("pull_request", cancel, f"{where}: only pull requests are cancelled")

    def test_every_job_has_a_timeout_unless_it_only_calls_a_workflow(self):
        workflows = sorted(self.WORKFLOWS.glob("*.yml"))
        self.assertTrue(workflows, "no workflow files found")
        for workflow in workflows:
            body = workflow.read_text(encoding="utf-8")
            jobs = self._jobs(body)
            self.assertTrue(jobs, f"{workflow.name}: parsed no jobs")
            own = {name: lines for name, lines in jobs.items()
                   if not self._has_job_key(lines, "uses")}
            # A job that calls a reusable workflow cannot carry timeout-minutes; its callee does.
            runs_on = len(re.findall(r"^    runs-on:", body, re.MULTILINE))
            self.assertEqual(runs_on, len(own),
                             f"{workflow.name}: {runs_on} runs-on lines but {len(own)} jobs "
                             "parsed, so the parser lost track of a job")
            for name, lines in own.items():
                self.assertTrue(self._has_job_key(lines, "timeout-minutes"),
                                f"{workflow.name}: job '{name}' has no timeout-minutes")

    def test_python_ci_timeout_is_an_input_with_a_default(self):
        body = (self.WORKFLOWS / "python-ci.yml").read_text(encoding="utf-8")
        self.assertIn("timeout-minutes: ${{ inputs.timeout-minutes }}", body)
        self.assertRegex(body, r"(?s)\n      timeout-minutes:.*?default:\s*\d+\s*\n")

    def test_the_self_workflow_cancels_only_pull_requests(self):
        body = (self.WORKFLOWS / "self.yml").read_text(encoding="utf-8")
        self._assert_pr_only_cancel(body, "self.yml")

    def test_readme_callers_do_not_run_every_commit_twice(self):
        blocks = re.findall(r"```yaml\n(.*?)```", self.README.read_text(encoding="utf-8"),
                            re.DOTALL)
        callers = [b for b in blocks if "unohee/ci-templates/.github/workflows/" in b]
        self.assertTrue(callers, "README has no caller example")
        whole_files = 0
        for block in callers:
            if re.search(r"^\s*push:", block, re.MULTILINE):
                match = re.search(r"push:\s*\n\s*branches:\s*\[([^\]]*)\]", block)
                self.assertIsNotNone(match, "a caller's push trigger must name its branches")
                branches = [b.strip(" '\"") for b in match.group(1).split(",")]
                # feature/** and fix/** pushes arrive with a pull request that runs them again.
                self.assertEqual(branches, ["main"], "push must be limited to main")
            if re.search(r"^on:", block, re.MULTILINE):
                whole_files += 1
                self._assert_pr_only_cancel(block, "README caller")
        self.assertGreaterEqual(whole_files, 1, "no README caller shows its `on:` block")


class FixtureClock(unittest.TestCase):
    """A fixture's dates must be offsets from now, not entries in the calendar."""

    def test_no_fixture_writes_an_absolute_date(self):
        """The age gates compare commit dates with the real clock, so an absolute date in a
        fixture is a countdown: `2026-08-31` passed for 31 days and then failed every
        caller's PR gate without any change to a gate. Docstrings are prose and skipped."""
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        prose = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        calendar = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
        offenders = [
            f"line {node.lineno}: {node.value!r}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in prose
            and calendar.search(node.value)
        ]
        self.assertEqual(offenders, [], "use days_ago(n) instead of a calendar date")


if __name__ == "__main__":
    unittest.main(verbosity=2)
