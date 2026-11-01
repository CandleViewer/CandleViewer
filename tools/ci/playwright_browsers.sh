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
# then killed 10 s later), so a slow CDN is retried and, if it never answers, fails here with the
# code instead of in a later step. The worst case (130 s of deps + 5 x 130 s + 130 s of waits = 910 s)
# is longer than a job's timeout-minutes, which alone bounds it and fails closed. The same retry shape as
# tools/ci/prepull_images.sh. The cache key and hit or miss go to $GITHUB_STEP_SUMMARY.
#
# #5275: every bounded command runs in its own session (`setsid`; the command records its process
# group id) and the bound kills that whole group, TERM then KILL after PW_KILL_GRACE (default 10)
# seconds, from outside it. coreutils `timeout` signalled only its own group: `sudo` ignores a signal sent
# from its parent's process group (it assumes the command got it too), but the runner user cannot
# signal the root `apt-get` that install-deps starts, so that `apt-get` outlived the bound and held
# /var/lib/apt/lists/lock through the vr job's font step (CI-A11Y-008). Sent from outside the group,
# the TERM is relayed by `sudo` to its `apt-get`. A bound that fires exits 124, as `timeout` did.
# The KILL after the grace cannot reach a root process (EPERM from the runner user), so the real
# apt-get dies only if `sudo` relays the TERM and apt-get honours it; when it outlasts that, the vr
# job's font step still waits up to 120 s for apt's locks before its own apt-get (CI-A11Y-008).
set -euo pipefail

summary=${GITHUB_STEP_SUMMARY:-/dev/null}
read -ra backoff <<<"${PW_BACKOFF-10 20 40 60}"
attempt_timeout=${PW_INSTALL_TIMEOUT:-120}
kill_grace=${PW_KILL_GRACE:-10}

fail() {
  msg="CI-A11Y-005: $* - Playwright browser setup failed; re-run the job, never change a budget"
  echo "::error::$msg" >&2
  drop_errf
  exit 1
}

# The install's stderr file goes when the script ends, removed by name here and never by an EXIT
# trap: every subshell inherits that trap until it resets it, and the bound's watchdog, killed in that
# window when the command ends first, ran it and unlinked the stderr it was meant to keep (#5275).
errf=""
drop_errf() {
  if [ -n "$errf" ]; then rm -f "$errf"; fi
}

# 0 would fire the bound at once (`read -t 0` returns immediately), so the bound is at least 1 s.
[[ "$attempt_timeout" =~ ^[1-9][0-9]*$ ]] || fail "PW_INSTALL_TIMEOUT must be whole seconds, at least 1"
[[ "$kill_grace" =~ ^[0-9]+$ ]] || fail "PW_KILL_GRACE must be whole seconds"
[ "${#backoff[@]}" -gt 0 ] || fail "PW_BACKOFF is empty"
for wait_s in "${backoff[@]}"; do
  [[ "$wait_s" =~ ^[0-9]+$ ]] || fail "PW_BACKOFF must be whole seconds"
done

# The bound's clock is `/bin/sleep` by its absolute path, so a stand-in `sleep` on PATH (the retry
# waits) never shortens it; its fds go to /dev/null so a sleep left behind holds no pipe of the step.

# bounded <command...>: runs the command in its own session and process group, and kills the whole
# group when it outlives attempt_timeout: TERM, then KILL once kill_grace seconds pass with any of
# the group left. Returns the command's status, or 124 when the bound sent its TERM.
# The command writes its own process group id (`$$` of the session leader `setsid` starts) to a file
# the watchdog signals, never `-$!`: when the background job already leads a group (job control),
# `setsid` forks and `$!` is the `setsid -w` wrapper, so `-$!` would kill only the wrapper (exit
# 143) and leave the command running (#5275).
# The two phases are marker files, never a flag rewritten in place: `>` truncates first, and a
# parent reading the empty file in that instant killed the watchdog before its KILL and kept the
# 143 (#5275, run 41265688180, reproduced on bash 5.2). "firing" is a `mkdir` claim that exactly
# one of the watchdog (the bound ran out) and the parent (the command ended) wins, so a watchdog
# that may have sent its TERM is never killed; "fired" is made once the TERM reached the group, so
# a command that ended by itself in the same instant keeps its own status.
bounded() {
  local pid watchdog st timer rc=0
  st=$(mktemp -d)
  setsid -w bash -c 'echo "$$" >"$1"; shift; exec "$@"' _ "$st/pgid" "$@" &
  pid=$!
  (
    /bin/sleep "$attempt_timeout" </dev/null >/dev/null 2>&1 &
    echo "$!" >"$st/timer"
    wait "$!" || true
    mkdir "$st/firing" 2>/dev/null || exit 0
    pgid=""
    for ((t = 0; t < 50; t++)); do
      pgid=$(cat "$st/pgid" 2>/dev/null || true)
      if [[ "$pgid" =~ ^[1-9][0-9]*$ ]]; then break; fi
      pgid=""
      /bin/sleep 0.1 </dev/null >/dev/null 2>&1
    done
    # Never written (the command could not start): the group `setsid` made in place.
    pgid=${pgid:-$pid}
    kill -TERM -- "-$pgid" 2>/dev/null || exit 0
    : >"$st/fired"
    for ((t = 0; t < kill_grace; t++)); do
      kill -0 -- "-$pgid" 2>/dev/null || exit 0
      /bin/sleep 1 </dev/null >/dev/null 2>&1
    done
    kill -KILL -- "-$pgid" 2>/dev/null || true
  ) &
  watchdog=$!
  wait "$pid" || rc=$?
  if mkdir "$st/firing" 2>/dev/null; then
    # The command ended before the bound: the watchdog has not fired and now never will.
    timer=$(cat "$st/timer" 2>/dev/null || true)
    kill "$watchdog" ${timer:+"$timer"} 2>/dev/null || true
    wait "$watchdog" 2>/dev/null || true
  else
    # The watchdog fired: it gives the rest of the group (sudo relaying the TERM to its apt-get)
    # its grace, then kills what is left.
    wait "$watchdog" 2>/dev/null || true
    if [ -e "$st/fired" ]; then rc=124; fi
  fi
  rm -rf "$st"
  return "$rc"
}

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
    # run_logged <label> <command...>: bounded run; stderr goes to $errf, and a failure prints its last
    # lines in a log group. Sets cause to a one-line reason.
    run_logged() {
      local label=$1
      rc=0
      shift
      : >"$errf"
      bounded "$@" 2>"$errf" || rc=$?
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
    drop_errf
    ;;
  *) fail "usage: playwright_browsers.sh version|install" ;;
esac
