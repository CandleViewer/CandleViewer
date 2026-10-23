#!/usr/bin/env bash
# CI-A11Y-005: the Playwright browser install of the a11y jobs, behind a cache of
# ~/.cache/ms-playwright (docs/ci-runbook.md).
#
#   playwright_browsers.sh version   print `version=X.Y.Z` (the lockfile's Playwright) to $GITHUB_OUTPUT
#   playwright_browsers.sh install   install chromium; run from apps/web
#
# `version` is the cache key's only variable part: `pnpm exec playwright --version` of the installed
# lockfile (pnpm runs the lockfile's binary and never fetches one from a registry), accepted only as a plain X.Y.Z. `install` reads PW_CACHE_KEY, PW_CACHE_HIT ("true" on
# a restored cache) and PW_VERSION from the step's env. On a hit the browsers are on disk and only
# the apt dependencies are installed (`install-deps`); on a miss the full `install --with-deps`
# downloads them. Either runs up to 5 attempts (waits PW_BACKOFF, default 10 20 40 60 s), each bound
# to PW_INSTALL_TIMEOUT seconds (default 120, then killed 10 s later: 5 x 130 + 130 s of waits stays
# inside the 900 s job backstop), so a slow CDN is retried and, if it never answers,
# fails here with the code instead of in a later step. The same retry shape as
# tools/ci/prepull_images.sh. The cache key and hit or miss go to $GITHUB_STEP_SUMMARY.
set -euo pipefail

summary=${GITHUB_STEP_SUMMARY:-/dev/null}
read -ra backoff <<<"${PW_BACKOFF-10 20 40 60}"
attempt_timeout=${PW_INSTALL_TIMEOUT:-120}

fail() {
  msg="CI-A11Y-005: $* - Playwright browser setup failed; re-run the job, never change a budget"
  echo "::error::$msg" >&2
  exit 1
}

[[ "$attempt_timeout" =~ ^[0-9]+$ ]] || fail "PW_INSTALL_TIMEOUT must be whole seconds"
[ "${#backoff[@]}" -gt 0 ] || fail "PW_BACKOFF is empty"

current_version() {
  local out
  out=$(pnpm exec playwright --version) || out=""
  [[ "$out" =~ ^Version\ ([0-9]+\.[0-9]+\.[0-9]+)$ ]] || return 1
  echo "${BASH_REMATCH[1]}"
}

case "${1:-}" in
  version)
    v=$(current_version) || fail "cannot read the lockfile's Playwright version"
    echo "version=$v" >>"${GITHUB_OUTPUT:?GITHUB_OUTPUT is not set}"
    ;;
  install)
    key=${PW_CACHE_KEY:?PW_CACHE_KEY is not set}
    want=${PW_VERSION:?PW_VERSION is not set}
    if [ "${PW_CACHE_HIT:-}" = true ]; then
      state=hit
      args=(install-deps chromium)
      # A guard on the step order (the key's version came from this same binary), not a check of the
      # restored files: a missing browser fails the first test run.
      [ "$(current_version || true)" = "$want" ] || fail "the key's Playwright $want is not the lockfile's"
    else
      state=miss
      args=(install --with-deps chromium)
    fi
    ok=0
    for ((i = 1; i <= 5; i++)); do
      if timeout --kill-after=10 "$attempt_timeout" pnpm exec playwright "${args[@]}"; then
        ok=1
        break
      fi
      echo "playwright ${args[0]} failed (attempt $i of 5)" >&2
      if [ "$i" -lt 5 ]; then
        sleep "${backoff[$((i - 1 < ${#backoff[@]} ? i - 1 : ${#backoff[@]} - 1))]}"
      fi
    done
    if [ "$ok" != 1 ]; then
      if [ "$state" = hit ]; then
        fail "the system dependency install (playwright install-deps) failed 5 times"
      fi
      fail "the chromium download (playwright install) failed 5 times"
    fi
    echo "- Playwright browsers: cache key \`$key\`, cache $state (playwright $want)" >>"$summary"
    ;;
  *) fail "usage: playwright_browsers.sh version|install" ;;
esac
