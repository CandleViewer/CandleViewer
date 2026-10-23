#!/usr/bin/env bash
# CI-A11Y-005: the Playwright browser install of the a11y jobs, behind a cache of
# ~/.cache/ms-playwright (docs/ci-runbook.md).
#
#   playwright_browsers.sh version   print `version=X.Y.Z` (the lockfile's Playwright) to $GITHUB_OUTPUT
#   playwright_browsers.sh install   install chromium; run from apps/web
#
# `version` is the cache key's only variable part: `pnpm exec playwright --version` of the installed
# lockfile (pnpm runs the lockfile's binary and never fetches one from a registry), accepted only as a plain X.Y.Z. `install` reads PW_CACHE_KEY, PW_CACHE_HIT ("true" on
# a restored cache) and PW_VERSION from the step's env. `install-deps` (apt libraries and fonts) runs
# first, once, outside the retry loop and bound to PW_INSTALL_TIMEOUT: it is optional on the hosted
# image, so a failure is a ::warning:: with its exit code and cause (apt's stderr, kept in a file,
# last lines in a log group, one line in the step summary) and the step goes on. On a hit that is
# all; on a miss `install chromium` (no --with-deps) then downloads the browser in up to 5 attempts
# (waits PW_BACKOFF, default 10 20 40 60 s), each bound to PW_INSTALL_TIMEOUT seconds (default 120,
# then killed 10 s later: 130 s of deps + 5 x 130 s + waits stays inside the 900 s job backstop), so
# a slow CDN is retried and, if it never answers, fails here with the code instead of in a later step. The same retry shape as
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
for wait_s in "${backoff[@]}"; do
  [[ "$wait_s" =~ ^[0-9]+$ ]] || fail "PW_BACKOFF must be whole seconds"
done

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
      # A guard on the step order (the key's version came from this same binary), not a check of the
      # restored files: a missing browser fails the first test run.
      [ "$(current_version || true)" = "$want" ] || fail "the key's Playwright $want is not the lockfile's"
    else
      state=miss
    fi
    errf=$(mktemp)
    trap 'rm -f "$errf"' EXIT
    # run_logged <label> <command...>: bounded run; stderr goes to $errf, and a failure prints its last
    # lines in a log group. Sets cause to a one-line reason.
    run_logged() {
      local label=$1
      rc=0
      shift
      : >"$errf"
      timeout --kill-after=10 "$attempt_timeout" "$@" 2>"$errf" || rc=$?
      if [ "$rc" -ne 0 ]; then
        echo "::group::$label failed (exit $rc), last lines of its stderr" >&2
        tail -n 20 "$errf" >&2
        echo "::endgroup::" >&2
        cause=$(grep -v '^[[:space:]]*$' "$errf" | tail -n 1 || true)
        cause=${cause:-no stderr output}
      fi
      return "$rc"
    }
    cause=""
    rc=0
    # System libraries and fonts: optional on the hosted image (the libraries are already there), so
    # one bounded try outside the retry loop; a failure is a warning, never the job's failure.
    if ! run_logged "playwright install-deps" pnpm exec playwright install-deps chromium; then
      echo "::warning::playwright install-deps failed (exit $rc), continuing without it: $cause" >&2
      echo "- playwright install-deps failed (exit $rc: $cause); continued, the runner image has the libraries" >>"$summary"
    fi
    ok=1
    if [ "$state" = miss ]; then
      ok=0
      for ((i = 1; i <= 5; i++)); do
        if run_logged "playwright install chromium (attempt $i)" pnpm exec playwright install chromium; then
          ok=1
          break
        fi
        echo "playwright install failed (attempt $i of 5)" >&2
        if [ "$i" -lt 5 ]; then
          idx=$((i - 1))
          if [ "$idx" -ge "${#backoff[@]}" ]; then
            idx=$((${#backoff[@]} - 1))
          fi
          sleep "${backoff[$idx]}"
        fi
      done
      if [ "$ok" != 1 ]; then
        echo "- Playwright chromium download failed 5 times (last: $cause)" >>"$summary"
        fail "the chromium download (playwright install) failed 5 times"
      fi
    fi
    echo "- Playwright browsers: cache key \`$key\`, cache $state (playwright $want)" >>"$summary"
    ;;
  *) fail "usage: playwright_browsers.sh version|install" ;;
esac
