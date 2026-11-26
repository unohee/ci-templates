#!/usr/bin/env bash
# Created: 2026-11-20
# Purpose: test the wiring of security/scan.sh without network or the real scanners. Stub tools
#   record the arguments they were given and write canned reports, so the cases below (a missing
#   tool, a planted leak, a pull-request pass that narrows the targets) are deterministic.
# Dependencies: bash, git, python3.
# Test Status: this is the test. Run: bash security/test_scan.sh
#
# Why stubs: the real end-to-end run (semgrep registry + the OSV API) needs network and minutes.
# What this test protects is the part that can silently pass a bad change: a tool that cannot run
# must fail the scan, and the gate must fail on a report that has a finding in it.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
scan="$here/scan.sh"
work="$(mktemp -d "${TMPDIR:-/tmp}/security-scan-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT
pass=0
fail=0

ok() { echo "ok    $1"; pass=$((pass + 1)); }
bad() { echo "FAIL  $1 ${2:-}"; fail=$((fail + 1)); }
expect_exit() { # description wanted
  if [ "$status" = "$2" ]; then ok "$1"; else bad "$1" "(want exit $2, got $status)"; fi
}
contains() { # description haystack needle
  if printf '%s' "$2" | grep -Fq -- "$3"; then ok "$1"; else bad "$1" "'$3' not found"; fi
}
missing() { # description haystack needle
  if printf '%s' "$2" | grep -Fq -- "$3"; then bad "$1" "'$3' present"; else ok "$1"; fi
}

# --- fixture repository ------------------------------------------------------------
repo="$work/repo"
mkdir -p "$repo"
git -C "$repo" init -q -b main
git -C "$repo" config user.email t@example.com
git -C "$repo" config user.name t
echo "print('hello')" > "$repo/app.py"
echo "requests==2.19.0" > "$repo/requirements.txt"
git -C "$repo" add -A
git -C "$repo" commit -qm first
echo "print('changed')" >> "$repo/app.py"
git -C "$repo" add -A
git -C "$repo" commit -qm second

# --- stub tools --------------------------------------------------------------------
tools="$work/tools"
mkdir -p "$tools/bin" "$tools/venv/bin" "$work/args"
cat > "$tools/bin/gitleaks" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "${STUB_ARGS_DIR}/gitleaks"
for arg in "$@"; do case "$arg" in --report-path=*) out="${arg#--report-path=}" ;; esac; done
json="${STUB_GITLEAKS_JSON-}"
[ -n "$json" ] || json='[]'
printf '%s' "$json" > "${out:?}"
STUB
cat > "$tools/bin/osv-scanner" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "${STUB_ARGS_DIR}/osv-scanner"
while [ "$#" -gt 0 ]; do case "$1" in --output-file) out="$2"; shift ;; esac; shift; done
json="${STUB_OSV_JSON-}"
[ -n "$json" ] || json='{"results": []}'
printf '%s' "$json" > "${out:?}"
STUB
cat > "$tools/venv/bin/semgrep" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "${STUB_ARGS_DIR}/semgrep"
out=""
base=""
want_out=0
for arg in "$@"; do
  if [ "$want_out" = 1 ]; then out="$arg"; want_out=0; continue; fi
  case "$arg" in --output) want_out=1 ;; esac
  if [ -d "$arg" ]; then base="$arg"; fi
done
json="${STUB_SEMGREP_JSON-}"
[ -n "$json" ] || json='{"results": [], "errors": []}'
where="${base:-.}"
printf '%s' "${json//__EXPORT__/$where}" > "${out:?}"
STUB
chmod 0755 "$tools/bin/gitleaks" "$tools/bin/osv-scanner" "$tools/venv/bin/semgrep"
export STUB_ARGS_DIR="$work/args"

run_scan() { # args... ; sets out/status
  set +e
  out="$(STUB_ARGS_DIR="$work/args" bash "$scan" --repo "$repo" --tools-dir "$tools" "$@" 2>&1)"
  status=$?
  set -e
}

# 1. A tool that is not installed fails the scan; it never passes silently.
mv "$tools/bin/gitleaks" "$tools/bin/gitleaks.off"
run_scan
expect_exit "missing tool exits 2" 2
contains "missing tool names the fix" "$out" "bootstrap.sh"
mv "$tools/bin/gitleaks.off" "$tools/bin/gitleaks"

# 2. Clean reports pass.
run_scan
expect_exit "clean reports exit 0" 0

# 3. A planted leak fails the scan, is named, and is never printed.
secret="stub-secret-value-1234567890"
STUB_GITLEAKS_JSON="$(printf '[{"RuleID":"aws-access-token","Description":"AWS access token","File":"app.py","StartLine":1,"Secret":"%s","Match":"x"}]' "$secret")" run_scan
expect_exit "planted secret exits 1" 1
contains "planted secret names the rule" "$out" "aws-access-token"
missing "planted secret is not printed" "$out" "$secret"

# 4. The pull-request profile requires a base commit that exists.
run_scan --profile pr
expect_exit "pr profile without base exits 2" 2
run_scan --profile pr --base does-not-exist
expect_exit "pr profile with unknown base exits 2" 2

# 5. The pull-request profile scans the changed files, not the whole tree.
: > "$work/args/semgrep"
run_scan --profile pr --base HEAD~1
expect_exit "pr profile exits 0" 0
contains "pr semgrep target is the changed file" "$(cat "$work/args/semgrep")" "app.py"
if grep -Eq '(^| )[^ ]*/src( |$)' "$work/args/semgrep"; then
  bad "pr semgrep did not scan the whole tree" "(a bare /src target was passed)"
else
  ok "pr semgrep did not scan the whole tree"
fi

# 6. The full profile scans the exported tree.
: > "$work/args/semgrep"
run_scan
expect_exit "full profile exits 0" 0
if grep -Eq '(^| )[^ ]*/src( |$)' "$work/args/semgrep"; then
  ok "full semgrep scans the export"
else
  bad "full semgrep scans the export" "(no /src target)"
fi

# 7. The full profile reads the whole history. The pull-request profile reads the change range and
#    reports only the files the change touches: a merge commit in the range carries the base
#    branch's copy of every file it merges, so a token the base branch moved to a new line would
#    otherwise be judged at the line it had when the branch was cut (intrect-platform PR #1781).
: > "$work/args/gitleaks"
run_scan
contains "full gitleaks reads --all" "$(cat "$work/args/gitleaks")" "--log-opts=--all"
: > "$work/args/gitleaks"
run_scan --profile pr --base HEAD~1
contains "pr gitleaks reads the change range" "$(cat "$work/args/gitleaks")" "--log-opts=HEAD~1..HEAD"
missing "pr gitleaks does not read the whole history" "$(cat "$work/args/gitleaks")" "--log-opts=--all"

# 7c. --range narrows the full profile to the commits one push introduced: content that lives only
#     on another branch must not fail a main push (measured 2026-11-26 on de-artifact). When the
#     range cannot be measured — a new branch reports an all-zero tip, a force push dropped it — the
#     scan reads every commit on the checked-out ref instead, never a shorter list.
first="$(git -C "$repo" rev-parse HEAD~1)"
head_sha="$(git -C "$repo" rev-parse HEAD)"
: > "$work/args/gitleaks"
run_scan --range "$first..$head_sha"
expect_exit "push range exits 0" 0
contains "push range scans only the pushed commits" "$(cat "$work/args/gitleaks")" "--log-opts=$first..$head_sha"
missing "push range does not read every ref" "$(cat "$work/args/gitleaks")" "--log-opts=--all"
: > "$work/args/gitleaks"
run_scan --range "0000000000000000000000000000000000000000..$head_sha"
expect_exit "an unmeasurable range still exits 0" 0
contains "an unmeasurable range falls back to every commit on HEAD" "$(cat "$work/args/gitleaks")" "--log-opts=HEAD"
contains "an unmeasurable range is announced" "$out" "reading every commit on the checked-out ref"
: > "$work/args/gitleaks"
run_scan --range "$head_sha..$first"
contains "a range whose ends are reversed falls back" "$(cat "$work/args/gitleaks")" "--log-opts=HEAD"

# 7b. A secret in a file the change does not touch does not block a pull request, and one in a
#     changed file still does.
leak() { printf '[{"RuleID":"generic-api-key","Description":"Generic API Key","File":"%s","StartLine":1,"Secret":"s","Match":"x"}]' "$1"; }
STUB_GITLEAKS_JSON="$(leak app.py)" run_scan --profile pr --base HEAD~1
expect_exit "a secret in a changed file blocks the pull request" 1
STUB_GITLEAKS_JSON="$(leak docs/record.json)" run_scan --profile pr --base HEAD~1
expect_exit "a secret in a file the change never touches does not block it" 0
STUB_GITLEAKS_JSON="$(leak docs/record.json)" run_scan
expect_exit "the same secret blocks the full profile" 1

# 8. A repository baseline at security/baseline.json is used without being asked for: the planted
#    secret passes once it is recorded as accepted. This is what keeps a first adoption from
#    failing on the findings that were already there, and what makes the workflow (which passes no
#    --baseline) and a local run agree.
mkdir -p "$repo/security"
python3 - "$repo" <<'PY'
import json, sys

repo = sys.argv[1]
entry = {
    "tool": "secret",
    "rule": "aws-access-token",
    "path": "app.py",
    "line": 1,
    "reason": "test fixture",
    "added": "2026-11-20",
}
with open(f"{repo}/security/baseline.json", "w", encoding="utf-8") as handle:
    json.dump({"accepted": [entry]}, handle)
PY
STUB_GITLEAKS_JSON="$(printf '[{"RuleID":"aws-access-token","Description":"AWS access token","File":"app.py","StartLine":1,"Secret":"%s","Match":"x"}]' "$secret")" run_scan
expect_exit "a baselined finding does not block" 0
contains "the baseline in use is named" "$out" "security/baseline.json"
rm -rf "$repo/security"

# 9. A repository that narrows the secret rules in security/gitleaks.toml has it passed
#    explicitly: gitleaks' own auto-discovery looks only at the repository root.
mkdir -p "$repo/security"
printf '[extend]\nuseDefault = true\n' > "$repo/security/gitleaks.toml"
: > "$work/args/gitleaks"
run_scan
contains "repo gitleaks config is passed" "$(cat "$work/args/gitleaks")" "--config $repo/security/gitleaks.toml"
rm -f "$repo/security/gitleaks.toml"

# 10. --write-baseline writes paths a later run can match: the entry names the file as the
#     scanners reported it, not the temporary export directory. findings.py is called with the
#     export as its root, so an absolute path is refused instead of being recorded.
STUB_SEMGREP_JSON='{"results": [{"check_id": "python.test.rule", "path": "__EXPORT__/app.py", "start": {"line": 1}, "extra": {"severity": "ERROR", "message": "test finding", "metadata": {}}}], "errors": []}' \
  run_scan --write-baseline "$work/written-baseline.json" --baseline-reason "fixture reason"
expect_exit "writing a baseline still reports the findings it recorded" 1
written_path="$(python3 -c "import json;print(json.load(open('$work/written-baseline.json'))['accepted'][0]['path'])" 2>/dev/null || echo MISSING)"
if [ "$written_path" = "app.py" ]; then
  ok "the written baseline names the file relative to the repository"
else
  bad "the written baseline names the file relative to the repository" "(got '$written_path')"
fi
contains "the written baseline carries the reason" "$(cat "$work/written-baseline.json")" "fixture reason"

echo
echo "test_scan: $pass passed, $fail failed"
[ "$fail" = 0 ]
