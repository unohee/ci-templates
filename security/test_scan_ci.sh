#!/usr/bin/env bash
# Created: 2026-11-26
# Purpose: test security/scan_ci.sh, the exit-status decision in front of security/scan.sh. A stub
#   scan returns each code so every branch is checked without a real scan: clean passes, a finding
#   passes only in report-only mode, and a tooling failure fails in every mode.
# Dependencies: bash.
# Test Status: this is the test. Run: bash security/test_scan_ci.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
helper="$here/scan_ci.sh"
work="$(mktemp -d "${TMPDIR:-/tmp}/scan-ci-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT
pass=0
fail=0

ok() { echo "ok    $1"; pass=$((pass + 1)); }
bad() { echo "FAIL  $1 ${2:-}"; fail=$((fail + 1)); }
expected() { # description wanted actual
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "(want $2, got $3)"; fi
}

stub="$work/scan.sh"
cat > "$stub" <<'STUB'
#!/usr/bin/env bash
case "${STUB_STATUS:?}" in
  0) exit 0 ;;
  1) echo "findings: 1 blocking"; exit 1 ;;
  *) echo "scan: gitleaks failed" >&2; exit 2 ;;
esac
STUB
chmod 0755 "$stub"

run() { # STUB_STATUS REPORT_ONLY -> prints output, sets status
  set +e
  out="$(SCAN_SH="$stub" STUB_STATUS="$1" REPORT_ONLY="${2:-0}" bash "$helper" --repo . 2>&1)"
  status=$?
  set -e
}

run 0
expected "a clean scan exits 0" 0 "$status"
run 0 1
expected "a clean audit exits 0" 0 "$status"
run 1 0
expected "a finding stops a blocking run" 1 "$status"
run 1 1
expected "a finding passes a report-only run" 0 "$status"
case "$out" in
  *"report-only: blocking findings above did not fail this run"*) ok "the report-only pass is announced" ;;
  *) bad "the report-only pass is announced" "$out" ;;
esac
run 2 0
expected "a tooling failure exits 2" 2 "$status"
run 2 1
expected "a tooling failure still exits 2 in report-only" 2 "$status"

echo ""
echo "test_scan_ci: $pass passed, $fail failed"
[ "$fail" = 0 ] || exit 1
