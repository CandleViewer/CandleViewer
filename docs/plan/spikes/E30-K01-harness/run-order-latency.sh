#!/usr/bin/env bash
# E30-K01 (#852) order-path latency run. Run from the spike branch `spike/e30-k01-order-latency`
# (the harness code lives only there, C-4.5). NOT a CI job and not in AGENTS.md section 4.
#
#   bash docs/plan/spikes/E30-K01-harness/run-order-latency.sh              # Electron, ~1.5-2 h
#   CV_K01_TARGETS=electron,browser bash .../run-order-latency.sh          # plus headless Chromium
#   CV_K01_SAMPLES=50 bash .../run-order-latency.sh                         # smoke: 50 samples/cell
#
# It refuses to start while a GitHub Actions job is running on this host (the cv-bench-01 perf
# runner shares it) unless CV_K01_FORCE_BUSY=1, and it only READS the process table to decide.
set -euo pipefail

if pgrep -f 'Runner.Worker' >/dev/null 2>&1 && [ "${CV_K01_FORCE_BUSY:-0}" != "1" ]; then
  echo "refusing: an Actions job is running on this host (perf runner busy). Retry when idle." >&2
  exit 3
fi

root="$(git rev-parse --show-toplevel)"
cd "$root"
branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$branch" != "spike/e30-k01-order-latency" ] && [ "${CV_K01_ANY_BRANCH:-0}" != "1" ]; then
  echo "refusing: run from spike/e30-k01-order-latency (the harness is not on $branch)." >&2
  exit 4
fi

# The flag adds the spike page as a second Vite entry; a normal build never has it. Vite is called
# directly: a turbo cache hit could replay a build made without the flag.
export CV_SPIKE_E30_K01=1
pnpm --filter @candleviewer/web exec vite build
pnpm --filter @candleviewer/desktop build

# Not under test-results/: Playwright empties that directory when a run starts.
export CV_PERF_REPORT_DIR="${CV_PERF_REPORT_DIR:-$root/apps/desktop/e30-k01-results}"
runner=()
if [ -z "${DISPLAY:-}" ]; then
  command -v xvfb-run >/dev/null 2>&1 || { echo "no DISPLAY and no xvfb-run" >&2; exit 5; }
  runner=(xvfb-run -a)
fi

# One heavy process at a time (the host is shared): the harness is the only thing running here.
"${runner[@]}" pnpm --filter @candleviewer/desktop perf order-latency

echo "results: $CV_PERF_REPORT_DIR/e30-k01-results-*.json"
echo "copy them to docs/plan/spikes/E30-K01-results.json (see README, 'After the run')."
