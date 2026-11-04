# E30-K01 harness (THROWAWAY)

Spike #852 (E30-K01): measure order-path latency on the client. The harness is **throwaway**: not
product code, never merged, not promoted without a `feat/` ticket (C-4.5). This directory carries only
what a reader needs to reproduce the run (this README and the run script); the code is on the unmerged
branch `spike/e30-k01-order-latency` and is archived there. The finding is `../E30-K01.md`; the results
shape is `../E30-K01-results.schema.json`.

## What it measures

| Measure               | Start                           | End                                                           | Input                                                       | Budget (PROPOSED)                            |
| --------------------- | ------------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------- | -------------------------------------------- |
| `recompute_end_a`     | input event `timeStamp`         | the reducer returns (worker: its reply arrives)               | `dispatchEvent`                                             | 8 ms p95 (E30-T01's `size()` + `validate()`) |
| `recompute_end_b`     | the same                        | first `requestAnimationFrame` after the derived fields commit | `dispatchEvent`                                             | 8 ms p95 (SCR-060)                           |
| `click_to_fetch`      | `click` `timeStamp`             | `performance.now()` taken just before `fetch()`               | Playwright `page.mouse`                                     | 50 ms p95                                    |
| `hotkey_to_fetch`     | `keydown` `timeStamp`           | the same mark                                                 | Playwright `page.keyboard`: `Ctrl+Enter` and a stand-in key | 50 ms p95                                    |
| `ws_orders_to_render` | WebSocket `message` `timeStamp` | first rAF after the commit                                    | stub frame                                                  | information only                             |

Every figure is a duration inside **one renderer clock**; no number crosses a process clock. The stub's
receive time is counted only as a cross-check on the number of POSTs. `click` and `hotkey` also write a
`<kind>_resource_timing` row (the POST's Resource Timing `fetchStart` against the same gesture).
The budgets are constants in one file, `apps/desktop/e2e/perf/support/latency.ts` (BQ 2/3 are pending a
ruling): change a number there and nowhere else.

Matrix: 3 reducer placements (`sync` in the handler, `store` outside React on the main thread, `worker`
with a structured-clone hop) x 2 chart-engine `RunMode`s (`worker`, `inline`) x 2 runs, 1 000 samples per
trigger after 50 warm-up samples, paced at 20 Hz, under replayed WebSocket load. Two runs must agree
within 15 % at p95 or the cell is `noisy` and never PASS/FAIL. The worker's structured-clone cost of an
`OrderDraft` + `Instrument` + `Wallet` is reported separately (`cellMeta[].cloneCostMs`).

## What is real and what is a stand-in

- Real: Electron through Playwright `_electron` (headless Chromium as an optional cross-check),
  `KeymapHost` -> dispatcher -> registry for `Ctrl+Enter` (`ticket.submit`, armed through
  `setArmPort`), the `<Chart>` binding over the chart engine in both RunModes, the E10-Q04 loopback stub
  and `ELECTRON_EGRESS_GUARD`.
- Stand-ins (branch only): the order ticket (SCR-060 is not on `main`) and its reducer (`size()` +
  `validate()` over scaled bigints); the single-key buy command `ticket.spike_buy_market` (bound to `M`
  in `keymap.json` on the branch only); the spike page `apps/web/spike-e30-k01.html`, which does not boot
  the SCR-010 shell; a WS client that parses frames on the main thread (the real one is a shared worker,
  so contention here is pessimistic).
- The replayed load is the recorded, redacted `packages/fixtures/bybit/2026-10-05/ws/
clean_publicTrade_BTCUSDT.jsonl`, cycled at a rate scaled so the bytes reach 350 KiB/s (23 section
  16.3); the scale is written to the results (`load.scale`). No live feed, no network past loopback.
- No production code is changed except two dev-only edits, both behind `CV_SPIKE_E30_K01=1` or in a
  branch-only file: `apps/web/vite.config.ts` (second build entry only with the flag) and the stand-in
  entry in `apps/web/src/keymap/keymap.json`. There are no `performance.mark` hooks in product code.

## Run it

Only when the `cv-bench-01` perf runner is idle (the script refuses while an Actions job runs):

```bash
cd .claude/worktrees/vw1-852      # the spike worktree
bash docs/plan/spikes/E30-K01-harness/run-order-latency.sh
```

Environment: `CV_K01_TARGETS` (`electron` default, or `electron,browser`), `CV_K01_SAMPLES` (default
1000), `CV_K01_TRACE=1` (an Electron `contentTracing` file for 200 `Ctrl+Enter` presses per cell, plan
step 5), `CV_PERF_HOST_CLASS=reference` (only on the `06` section 3.1 machine; anything else is
`below-class`, so a miss reads INCONCLUSIVE and a pass reads PASS), `CV_PERF_REPORT_DIR`.

Output: `<report dir>/e30-k01-results-<target>.json` (shape: `../E30-K01-results.schema.json`) and a
markdown table on stdout.

## After the run

1. Copy the electron results to `docs/plan/spikes/E30-K01-results.json` (browser: `-browser` suffix).
2. Print every number in `../E30-K01.md` section 6 from that file; type none from memory.
3. Fill section 7 (the decision) and the "what E30-T01 needs" answers; the merging PR is
   `spike/e30-k01-finding`, which carries docs only.
4. The demo leg (budget #4 end to end) is **PENDING E29-K01 (#843)**; this harness does not run it.
