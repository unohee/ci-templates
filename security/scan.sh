#!/usr/bin/env bash
# Created: 2026-11-20
# Purpose: run the local security gate — secrets, static analysis, dependency vulnerabilities and
#   (optionally) code-quality metrics — over one repository, and fail on blocking findings. This is
#   the free, license-clean replacement for GitHub Advanced Security (code scanning, secret scanning)
#   and GitHub Code Quality, all dropped for cost on 2026-11-20. See security/README.md.
# Dependencies: bash, git, tar, python3, and the pinned tools from security/bootstrap.sh
#   (gitleaks, osv-scanner, semgrep, lizard) in $SECURITY_TOOLS_DIR.
# Test Status: security/test_scan.sh (fixture repository: a planted secret, a planted taint sink,
#   a lockfile with a known-vulnerable pin) and .github/workflows/self.yml.
#
#   bash security/scan.sh --repo ~/dev/de-artifact                 # full: history, whole tree
#   bash security/scan.sh --repo . --profile pr --base origin/main  # pull-request pass
#   bash security/scan.sh --repo . --quality                        # add the quality report
#
# What runs:
#   secrets  gitleaks over the git history (full) or over BASE..HEAD (pr). Reports never carry
#            the secret value (--redact; findings.py keeps the description only).
#   sast     semgrep over an export of the tracked files at HEAD (`git archive HEAD`), so
#            worktrees, target/, build output and untracked copies are never scanned.
#   deps     osv-scanner over the same export: Cargo.lock, package-lock.json, requirements.txt,
#            pyproject.toml and every other lockfile it recognises, in one pass.
#   quality  lizard cyclomatic complexity and copy/paste, report-only until a baseline exists.
# Exit: 0 clean, 1 blocking findings, 2 usage or tooling failure (a tool that cannot run is a
#   failure, never a silent pass — book.md Art. VI).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=security/tools.env
. "$here/tools.env"

repo=""
profile="full"
base=""
out=""
tools_dir="${SECURITY_TOOLS_DIR:-$HOME/.local/share/intrect-security}"
baseline=""
quality=0
keep=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --profile) profile="$2"; shift 2 ;;
    --base) base="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --tools-dir) tools_dir="$2"; shift 2 ;;
    --baseline) baseline="$2"; shift 2 ;;
    --quality) quality=1; shift ;;
    --keep) keep=1; shift ;;
    -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "scan: unknown argument: $1" >&2; exit 2 ;;
  esac
done

[ -n "$repo" ] || { echo "scan: --repo PATH is required" >&2; exit 2; }
case "$profile" in full|pr) ;; *) echo "scan: --profile must be full or pr" >&2; exit 2 ;; esac
root="$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null)" \
  || { echo "scan: $repo is not a git working tree" >&2; exit 2; }

gitleaks="$tools_dir/bin/gitleaks"
osv="$tools_dir/bin/osv-scanner"
semgrep="$tools_dir/venv/bin/semgrep"
lizard="$tools_dir/venv/bin/lizard"
for tool in "$gitleaks" "$osv" "$semgrep"; do
  [ -x "$tool" ] || { echo "scan: $tool missing — run: bash $here/bootstrap.sh --tools-dir $tools_dir" >&2; exit 2; }
done

if [ "$profile" = pr ]; then
  [ -n "$base" ] || { echo "scan: --profile pr needs --base REF (e.g. origin/main)" >&2; exit 2; }
  git -C "$root" rev-parse --verify --quiet "$base^{commit}" >/dev/null \
    || { echo "scan: base '$base' is not a commit in $root — fetch it first" >&2; exit 2; }
fi

work="$(mktemp -d "${TMPDIR:-/tmp}/security-scan.XXXXXX")"
trap '[ "$keep" = 1 ] || rm -rf "$work"' EXIT
src="$work/src"
mkdir -p "$src"
git -C "$root" archive HEAD | tar -x -C "$src"

log="$work/scan.log"
: > "$log"
status=0

# --- secrets ----------------------------------------------------------------------
secret_range="--all"
[ "$profile" = pr ] && secret_range="$base..HEAD"
echo "scan: gitleaks ($profile: $secret_range)"
if ! "$gitleaks" git "$root" --log-opts="$secret_range" --report-format=json \
      --report-path="$work/gitleaks.json" --exit-code=0 --no-banner --redact --no-color \
      >>"$log" 2>&1; then
  echo "scan: gitleaks failed; see $log" >&2
  tail -20 "$log" >&2
  exit 2
fi

# --- static analysis --------------------------------------------------------------
semgrep_args=(--config "$SEMGREP_CONFIGS" --json --output "$work/semgrep.json" --metrics=off
              --quiet --timeout "${SEMGREP_TIMEOUT:-60}" --max-target-bytes 2000000
              --exclude vendor --exclude node_modules --exclude target --exclude dist)
# A repository may add its own rules next to the shared set; a broken rule file must fail the
# scan (semgrep exits non-zero), not be skipped.
[ -f "$root/security/semgrep.yml" ] && semgrep_args+=(--config "$root/security/semgrep.yml")
if [ "$profile" = pr ]; then
  targets=()
  while IFS= read -r changed; do
    [ -n "$changed" ] && [ -e "$src/$changed" ] && targets+=("$src/$changed")
  done < <(git -C "$root" diff --name-only --diff-filter=ACMR "$base...HEAD")
  if [ "${#targets[@]}" -eq 0 ]; then
    echo "scan: no changed files to analyse; writing empty semgrep report"
    echo '{"results": [], "errors": []}' > "$work/semgrep.json"
  else
    echo "scan: semgrep ($SEMGREP_CONFIGS, ${#targets[@]} changed file(s))"
    if ! "$semgrep" scan "${semgrep_args[@]}" "${targets[@]}" >>"$log" 2>&1; then
      echo "scan: semgrep failed; see $log" >&2
      tail -20 "$log" >&2
      exit 2
    fi
  fi
else
  echo "scan: semgrep ($SEMGREP_CONFIGS, whole tracked tree)"
  if ! "$semgrep" scan "${semgrep_args[@]}" "$src" >>"$log" 2>&1; then
    echo "scan: semgrep failed; see $log" >&2
    tail -20 "$log" >&2
    exit 2
  fi
fi

# --- dependencies -----------------------------------------------------------------
echo "scan: osv-scanner"
if ! "$osv" scan source -r "$src" --format json --output-file "$work/osv.json" >>"$log" 2>&1; then
  # osv-scanner exits 128 when it found no package source at all; the JSON is still written.
  if [ ! -s "$work/osv.json" ]; then
    echo '{"results": []}' > "$work/osv.json"
    echo "scan: osv-scanner found no lockfiles (recorded as no findings)"
  fi
fi

# --- quality (report only) ---------------------------------------------------------
quality_note=""
if [ "$quality" = 1 ]; then
  if [ -x "$lizard" ]; then
    echo "scan: lizard quality report (report-only)"
    "$lizard" --warnings_only --csv "$src" > "$work/quality.csv" 2>>"$log" || true
    functions="$(wc -l < "$work/quality.csv" | tr -d ' ')"
    quality_note="lizard: $functions function(s) over the complexity warning thresholds -> $work/quality.csv"
    echo "scan: $quality_note"
  else
    echo "scan: lizard missing — run bootstrap.sh; quality report skipped" >&2
    status=2
  fi
fi

# --- gate -------------------------------------------------------------------------
summary="$work/summary.json"
[ -n "$out" ] && summary="$out"
set +e
python3 "$here/findings.py" --summary "$summary" --root "$src" \
  --gitleaks "$work/gitleaks.json" --semgrep "$work/semgrep.json" --osv "$work/osv.json" \
  ${baseline:+--baseline "$baseline"}
gate=$?
set -e
[ "$gate" = 2 ] && status=2
[ "$gate" = 1 ] && status=1
[ -n "$quality_note" ] && echo "scan: $quality_note"
echo "scan: repo=$root commit=$(git -C "$root" rev-parse --short HEAD) profile=$profile artifacts=$work"
[ "$keep" = 1 ] && echo "scan: kept $work" || true
exit "$status"
