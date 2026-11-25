#!/usr/bin/env bash
# Created: 2026-11-25
# Purpose: fetch a pull request's base ref with its whole history, so `git merge-base` can find
#   the commit the change branched from.
# Dependencies: bash, git.
# Test Status: bash security/test_fetch_base.sh
#
# Why the history has to be whole: a shallow fetch grafts the fetched tip, which tells git the
# commit has no parents. `git merge-base origin/main HEAD` then fails with "no merge base" for
# every branch that does not already contain that tip — which is every branch that is behind the
# base, the normal state of a pull request. The gate would then die on a git error (exit 128)
# instead of reporting a finding (AUD-3071).
#
# One branch is fetched, so the cost is small: the caller has already checked the pull request out
# at full depth, and only the commits the base gained since then are new.
set -euo pipefail

base="${1:-origin/main}"
case "$base" in
  */*)
    remote="${base%%/*}"
    branch="${base#*/}"
    git fetch --no-tags "$remote" "+refs/heads/$branch:refs/remotes/$base"
    ;;
  *)
    remote=origin
    if ! git rev-parse --verify --quiet "$base^{commit}" >/dev/null; then
      # A bare sha or tag the checkout did not bring. GitHub serves a commit by id and a tag by
      # name, so ask the remote for it instead of dying on a missing object.
      git fetch --no-tags "$remote" "$base"
    fi
    ;;
esac

# A repository that arrived shallow (a caller overriding the checkout depth) keeps its old grafts
# even after the fetch above. Drop them, so the base's ancestry is complete again.
if [ "$(git rev-parse --is-shallow-repository)" = true ]; then
  git fetch --no-tags --unshallow "$remote"
fi

if ! merge_base="$(git merge-base "$base" HEAD 2>/dev/null)"; then
  echo "fetch-base: $base and HEAD share no commit even after fetching it whole." >&2
  echo "fetch-base: pass a branch ref such as origin/main, and keep the checkout at full depth." >&2
  exit 3
fi
echo "fetch-base: $base is complete, merge base $(printf '%s' "$merge_base" | cut -c1-12)"
