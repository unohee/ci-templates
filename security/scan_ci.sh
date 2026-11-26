#!/usr/bin/env bash
# Created: 2026-11-26
# Purpose: run security/scan.sh in CI and turn its exit status into a decision, so the workflow
#   never has to disable errexit. book.md Art. VI forbids `set +e` inside a workflow: a status the
#   shell acts on instead of a value the script inspects. The report-only whole-history audit needs
#   exactly that decision — a blocking finding is news, not a failure — so it lives here.
# Dependencies: bash, and security/scan.sh next to this file ($SCAN_SH overrides it for tests).
# Test Status: security/test_scan_ci.sh
#
#   REPORT_ONLY=1 bash security/scan_ci.sh --repo . --profile full
#
# Exit: 0 clean, or report-only with findings; 1 blocking findings and not report-only; 2 a tooling
#   failure, in every mode — a scanner that could not run must never read as a clean scan.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
scan="${SCAN_SH:-$here/scan.sh}"
report_only="${REPORT_ONLY:-0}"

status=0
bash "$scan" "$@" || status=$?

[ "$status" = 0 ] && exit 0

if [ "$report_only" = 1 ] && [ "$status" = 1 ]; then
  echo "report-only: blocking findings above did not fail this run"
  exit 0
fi

if [ "$status" = 1 ]; then
  echo "blocking findings above stop this run (set REPORT_ONLY=1 for an audit that only reports)"
fi
exit "$status"
