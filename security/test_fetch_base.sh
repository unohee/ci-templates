#!/usr/bin/env bash
# Created: 2026-11-25
# Purpose: test security/fetch_base.sh against a small local remote. The case that matters is the
#   one that broke the gate: a shallow fetch of all the heads grafts the base tip, so a pull
#   request that is behind its base can no longer find the commit it branched from (AUD-3071).
# Dependencies: bash, git.
# Test Status: this is the test. Run: bash security/test_fetch_base.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fetch_base="$here/fetch_base.sh"
work="$(mktemp -d "${TMPDIR:-/tmp}/security-fetch-base-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT
pass=0
fail=0

ok() { echo "ok    $1"; pass=$((pass + 1)); }
bad() { echo "FAIL  $1 ${2:-}"; fail=$((fail + 1)); }

# --- fixture remote ----------------------------------------------------------------
# main:    first -- second -- third
# feature: first -- change          (branched before second, so it is behind main)
origin="$work/origin.git"
git init -q --bare "$origin"
# GitHub serves a commit by id (uploadpack.allowAnySHA1InWant); a local remote does not unless it
# is told to, so the fixture matches what fetch_base.sh meets in CI.
git -C "$origin" config uploadpack.allowAnySHA1InWant true
git clone -q "$origin" "$work/seed" 2>/dev/null
git -C "$work/seed" config user.email t@example.com
git -C "$work/seed" config user.name t
echo a > "$work/seed/a.txt"
git -C "$work/seed" add -A
git -C "$work/seed" commit -qm first
git -C "$work/seed" push -q origin HEAD:main
git -C "$work/seed" checkout -qb feature
echo f > "$work/seed/f.txt"
git -C "$work/seed" add -A
git -C "$work/seed" commit -qm change
git -C "$work/seed" push -q origin feature
git -C "$work/seed" checkout -q main
echo b > "$work/seed/b.txt"
git -C "$work/seed" add -A
git -C "$work/seed" commit -qm second
echo c > "$work/seed/c.txt"
git -C "$work/seed" add -A
git -C "$work/seed" commit -qm third
git -C "$work/seed" push -q origin main

clone_feature() { # directory
  git clone -q --branch feature "$origin" "$1"
  git -C "$1" config user.email t@example.com
  git -C "$1" config user.name t
}

# --- 1. the old way is the bug -----------------------------------------------------
# `git fetch --depth=1 origin +refs/heads/*` marks every fetched tip shallow. The base is then a
# graft with no parents, so the merge base disappears even though the history is present on disk.
old="$work/old"
clone_feature "$old"
git -C "$old" fetch -q --no-tags --depth=1 origin "+refs/heads/*:refs/remotes/origin/*"
if git -C "$old" merge-base origin/main HEAD >/dev/null 2>&1; then
  bad "a depth-1 fetch of the heads leaves no merge base" "(the regression no longer reproduces)"
else
  ok "a depth-1 fetch of the heads leaves no merge base"
fi

# --- 2. fetch_base.sh keeps the ancestry -------------------------------------------
fixed="$work/fixed"
clone_feature "$fixed"
if out="$(cd "$fixed" && bash "$fetch_base" origin/main 2>&1)"; then
  ok "fetch_base.sh succeeds on a branch that is behind its base"
else
  bad "fetch_base.sh succeeds on a branch that is behind its base" "($out)"
fi
if git -C "$fixed" merge-base origin/main HEAD >/dev/null 2>&1; then
  ok "the merge base is findable after the fetch"
else
  bad "the merge base is findable after the fetch"
fi
if [ "$(git -C "$fixed" diff --name-only origin/main...HEAD)" = "f.txt" ]; then
  ok "the change range is the one file the branch added"
else
  bad "the change range is the one file the branch added" "(got '$(git -C "$fixed" diff --name-only origin/main...HEAD)')"
fi
if git -C "$fixed" rev-parse --is-shallow-repository | grep -qx false; then
  ok "the repository is still complete, not shallow"
else
  bad "the repository is still complete, not shallow"
fi

# --- 3. running it again changes nothing ------------------------------------------
if (cd "$fixed" && bash "$fetch_base" origin/main >/dev/null 2>&1); then
  ok "a second run succeeds"
else
  bad "a second run succeeds"
fi

# --- 4. an unknown ref fails instead of passing silently --------------------------
if (cd "$fixed" && bash "$fetch_base" origin/nosuchbranch >/dev/null 2>&1); then
  bad "an unknown base ref fails" "(exit 0)"
else
  ok "an unknown base ref fails"
fi

# --- 5. a bare sha is fetched when the checkout did not bring it -------------------
# The clone carries the feature branch only, so the base tip is a missing object. GitHub serves a
# commit by id; the script asks for it rather than dying on the merge base.
sha="$(git -C "$work/seed" rev-parse main)"
sha_repo="$work/sha"
git clone -q --single-branch --branch feature "$origin" "$sha_repo"
git -C "$sha_repo" config user.email t@example.com
git -C "$sha_repo" config user.name t
if out="$(cd "$sha_repo" && bash "$fetch_base" "$sha" 2>&1)"; then
  ok "a sha that the checkout does not carry is fetched"
else
  bad "a sha that the checkout does not carry is fetched" "($out)"
fi
if git -C "$sha_repo" merge-base "$sha" HEAD >/dev/null 2>&1; then
  ok "the merge base is findable for a sha base"
else
  bad "the merge base is findable for a sha base"
fi

# --- 6. a shallow clone is repaired -----------------------------------------------
# A caller that overrode the checkout depth hands the gate a shallow repository. fetch_base.sh
# deepens it instead of failing on the graft it inherited.
shallow="$work/shallow"
git clone -q --branch feature --depth 1 "file://$origin" "$shallow"
git -C "$shallow" config user.email t@example.com
git -C "$shallow" config user.name t
if out="$(cd "$shallow" && bash "$fetch_base" origin/main 2>&1)"; then
  ok "a shallow clone is repaired"
else
  bad "a shallow clone is repaired" "($out)"
fi
if git -C "$shallow" merge-base origin/main HEAD >/dev/null 2>&1; then
  ok "the merge base is findable after repairing the shallow clone"
else
  bad "the merge base is findable after repairing the shallow clone"
fi

echo
echo "test_fetch_base: $pass passed, $fail failed"
[ "$fail" = 0 ]
