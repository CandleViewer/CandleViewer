#!/usr/bin/env bash
# CI-A11Y-005: the Playwright browser install of the a11y jobs, behind a cache of
# ~/.cache/ms-playwright (docs/ci-runbook.md).
#
#   playwright_browsers.sh version   print `version=X.Y.Z` (the lockfile's Playwright) to $GITHUB_OUTPUT
#   playwright_browsers.sh install   install chromium; run from apps/web
#
# `version` is the cache key's only variable part: `npx playwright --version` of the installed
# lockfile, accepted only as a plain X.Y.Z. `install` reads PW_CACHE_KEY, PW_CACHE_HIT ("true" on
# a restored cache) and PW_VERSION from the step's env. On a hit the browsers are on disk and only
# the apt dependencies are installed (`install-deps`); on a miss the full `install --with-deps`
# downloads them. Either runs up to 5 attempts (waits PW_BACKOFF, default 10 20 40 60 s), each bound
# to PW_INSTALL_TIMEOUT seconds (default 300), so a slow CDN is retried and, if it never answers,
# fails here with the code instead of in a later step. The same retry shape as
# tools/ci/prepull_images.sh. The cache key and hit or miss go to $GITHUB_STEP_SUMMARY.
set -euo pipefail

summary=${GITHUB_STEP_SUMMARY:-/dev/null}
read -ra backoff <<<"${PW_BACKOFF:-10 20 40 60}"
attempt_timeout=${PW_INSTALL_TIMEOUT:-300}

fail() {
  echo "CI-A11Y-005: $* - Playwright browser setup failed; re-run the job, never change a budget" >&2
  exit 1
}

[[ "$attempt_timeout" =~ ^[0-9]+$ ]] || fail "PW_INSTALL_TIMEOUT must be whole seconds"

current_version() {
  local out
  out=$(npx playwright --version) || out=""
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
      [ "$(current_version || true)" = "$want" ] || fail "the restored cache is for Playwright $want, the lockfile has another"
    else
      state=miss
      args=(install --with-deps chromium)
    fi
    ok=0
    for ((i = 1; i <= 5; i++)); do
      if timeout "$attempt_timeout" npx playwright "${args[@]}"; then
        ok=1
        break
      fi
      echo "playwright ${args[0]} failed (attempt $i of 5)" >&2
      if [ "$i" -lt 5 ]; then
        sleep "${backoff[$((i - 1 < ${#backoff[@]} ? i - 1 : ${#backoff[@]} - 1))]}"
      fi
    done
    [ "$ok" = 1 ] || fail "the chromium download (playwright ${args[0]}) failed 5 times"
    echo "- Playwright browsers: cache key \`$key\`, cache $state (playwright $want)" >>"$summary"
    ;;
  *) fail "usage: playwright_browsers.sh version|install" ;;
esac
