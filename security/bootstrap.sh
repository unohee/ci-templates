#!/usr/bin/env bash
# Created: 2026-11-20
# Purpose: install the pinned local security scanners (gitleaks, osv-scanner, semgrep,
#   lizard) into one directory, verifying every download against security/tools.env.
#   They are the replacements for GitHub Advanced Security and Code Quality, which are
#   dropped for cost on 2026-11-20; see security/README.md and security/tools.env.
# Dependencies: bash, curl, tar, sha256sum (or shasum), python3 with venv.
# Test Status: exercised by .github/workflows/self.yml (bootstrap + --check).
#
#   bash security/bootstrap.sh                  # install into ~/.local/share/intrect-security
#   bash security/bootstrap.sh --tools-dir DIR  # install somewhere else (CI: $RUNNER_TEMP)
#   bash security/bootstrap.sh --check          # report what is installed, change nothing
#
# Idempotent: a tool already present at the pinned version is left alone. Exit 0 when
# everything wanted is present, 1 when a download or checksum failed, 2 on usage error.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=security/tools.env
. "$here/tools.env"

tools_dir="${SECURITY_TOOLS_DIR:-$HOME/.local/share/intrect-security}"
check_only=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --tools-dir) tools_dir="$2"; shift 2 ;;
    --check) check_only=1; shift ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "bootstrap: unknown argument: $1" >&2; exit 2 ;;
  esac
done

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)  platform=linux_x64;    osv_asset=osv-scanner_linux_amd64 ;;
  Darwin-arm64)  platform=darwin_arm64; osv_asset=osv-scanner_darwin_arm64 ;;
  *) echo "bootstrap: unsupported platform $(uname -s)-$(uname -m); install gitleaks, osv-scanner and semgrep by hand" >&2; exit 2 ;;
esac
case "$platform" in
  linux_x64)    gitleaks_sha="$GITLEAKS_LINUX_X64_SHA256";       osv_sha="$OSV_SCANNER_LINUX_AMD64_SHA256" ;;
  darwin_arm64) gitleaks_sha="$GITLEAKS_DARWIN_ARM64_SHA256";    osv_sha="$OSV_SCANNER_DARWIN_ARM64_SHA256" ;;
esac

bin_dir="$tools_dir/bin"
venv_dir="$tools_dir/venv"
mkdir -p "$bin_dir"

verify_sha256() { # file expected
  local actual
  if command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "$1" | cut -d' ' -f1)"
  else
    actual="$(shasum -a 256 "$1" | cut -d' ' -f1)"
  fi
  if [ "$actual" != "$2" ]; then
    echo "bootstrap: checksum mismatch for $1" >&2
    echo "  expected $2" >&2
    echo "  actual   $actual" >&2
    return 1
  fi
}

installed_version() { # path -> the first x.y.z token of --version output, or empty
  [ -x "$1" ] || return 0
  # `gitleaks version 8.30.1` and `osv-scanner version: 2.7.1`: take the version
  # token, never the whole line (stripping 'v' from the line would mangle "version").
  "$1" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true
}

# --- gitleaks (single static binary in a tarball) ---------------------------------
gitleaks_bin="$bin_dir/gitleaks"
gitleaks_have="$(installed_version "$gitleaks_bin")"
if [ "$check_only" = 0 ] && [ "$gitleaks_have" != "$GITLEAKS_VERSION" ]; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  url="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_${platform}.tar.gz"
  echo "bootstrap: fetching gitleaks $GITLEAKS_VERSION ($platform)"
  curl -fsSL "$url" -o "$tmp/gitleaks.tar.gz"
  verify_sha256 "$tmp/gitleaks.tar.gz" "$gitleaks_sha"
  tar -xzf "$tmp/gitleaks.tar.gz" -C "$tmp" gitleaks
  install -m 0755 "$tmp/gitleaks" "$gitleaks_bin"
  rm -rf "$tmp"; trap - EXIT
  gitleaks_have="$(installed_version "$gitleaks_bin")"
fi

# --- osv-scanner (single static binary) -------------------------------------------
osv_bin="$bin_dir/osv-scanner"
osv_have="$(installed_version "$osv_bin")"
if [ "$check_only" = 0 ] && [ "$osv_have" != "$OSV_SCANNER_VERSION" ]; then
  url="https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/${osv_asset}"
  echo "bootstrap: fetching osv-scanner $OSV_SCANNER_VERSION ($osv_asset)"
  curl -fsSL "$url" -o "$osv_bin.part"
  verify_sha256 "$osv_bin.part" "$osv_sha"
  chmod 0755 "$osv_bin.part"
  mv "$osv_bin.part" "$osv_bin"
  osv_have="$(installed_version "$osv_bin")"
fi

# --- semgrep + lizard (python virtualenv) -----------------------------------------
venv_have=""
[ -x "$venv_dir/bin/semgrep" ] && venv_have="$("$venv_dir/bin/semgrep" --version 2>/dev/null)"
lizard_have=""
[ -x "$venv_dir/bin/lizard" ] && lizard_have="$("$venv_dir/bin/lizard" --version 2>/dev/null)"
if [ "$check_only" = 0 ] && { [ "$venv_have" != "$SEMGREP_VERSION" ] || [ -z "$lizard_have" ]; }; then
  echo "bootstrap: installing semgrep $SEMGREP_VERSION and lizard $LIZARD_VERSION into $venv_dir"
  [ -x "$venv_dir/bin/python" ] || /usr/bin/python3 -m venv "$venv_dir"
  "$venv_dir/bin/pip" install --disable-pip-version-check -q \
    "semgrep==$SEMGREP_VERSION" "lizard==$LIZARD_VERSION"
  venv_have="$("$venv_dir/bin/semgrep" --version 2>/dev/null)"
  lizard_have="$("$venv_dir/bin/lizard" --version 2>/dev/null)"
fi

# --- report -----------------------------------------------------------------------
fail=0
report() { # name have wanted
  if [ "$2" = "$3" ]; then printf '  ok      %-12s %s\n' "$1" "$2"
  else printf '  MISSING %-12s have=%s want=%s\n' "$1" "${2:--}" "$3"; fail=1; fi
}
echo "bootstrap: $tools_dir"
report gitleaks    "$gitleaks_have" "$GITLEAKS_VERSION"
report osv-scanner "$osv_have"      "$OSV_SCANNER_VERSION"
report semgrep     "$venv_have"     "$SEMGREP_VERSION"
report lizard      "$lizard_have"   "$LIZARD_VERSION"
exit "$fail"
