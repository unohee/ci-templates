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
printf '%s' "${STUB_GITLEAKS_JSON:-[]}" > "${out:?}"
STUB
cat > "$tools/bin/osv-scanner" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "${STUB_ARGS_DIR}/osv-scanner"
while [ "$#" -gt 0 ]; do case "$1" in --output-file) out="$2"; shift ;; esac; shift; done
printf '%s' "${STUB_OSV_JSON:-{\"results\": []}}" > "${out:?}"
STUB
cat > "$tools/venv/bin/semgrep" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "${STUB_ARGS_DIR}/semgrep"
while [ "$#" -gt 0 ]; do case "$1" in --output) out="$2"; shift ;; esac; shift; done
printf '%s' "${STUB_SEMGREP_JSON:-{\"results\": [], \"errors\": []}}" > "${out:?}"
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
STUB_GITLEAKS_JSON="$(printf '[{"RuleID":"aws-access-token","Description":"AWS access token","File":"%s/app.py","StartLine":1,"Secret":"%s","Match":"x"}]' "$repo" "$secret")" run_scan
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

# 7. The full profile reads the whole history; the pull-request profile reads the range.
: > "$work/args/gitleaks"
run_scan
contains "full gitleaks reads --all" "$(cat "$work/args/gitleaks")" "--log-opts=--all"
: > "$work/args/gitleaks"
run_scan --profile pr --base HEAD~1
contains "pr gitleaks reads the range" "$(cat "$work/args/gitleaks")" "--log-opts=HEAD~1..HEAD"

echo
echo "test_scan: $pass passed, $fail failed"
[ "$fail" = 0 ]
