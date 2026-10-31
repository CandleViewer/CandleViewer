# E11-C1 Charter: chart-engine chaos (environment disturbances)

- Ticket: E11-Q04 (#516) · Format: session-based test management · Written: 2026-10-31
- Status: **session 1 run (2026-10-31), scripted cases only.** This file is the charter and its
  session sheet; session 1's results are in the record (`docs/qa/e11-chaos-charter.md` §4). The
  physical disturbances M1 to M7 are not run; no manual result is claimed for them.
- Cadence (ticket Test plan): once per release train, on the reference machine, by the owner or QA.
- Automated half: `packages/chart-engine/test/chaos/` (seeded, fake GL, fake clock) and the
  evidence-only browser lane `packages/chart-engine/test/chaos/browser/context-loss-lane.mjs`.

## Charter

Explore the chart engine through the disturbances a long trading session brings and no unit test
can stage (monitor disconnect, minimise and restore, sleep and wake, a real DPR change, a
10-minute background) to discover any state in which the chart comes back **subtly wrong**, stays
silent about a degradation, or loses keyboard focus.

## Target

No app route mounts the chart yet (SCR-030 is the first, `apps/web/test/composition-guard.test.ts`).
Until one does, the target is the bench matrix page `packages/chart-engine/bench/matrix/page/matrix.html`
served by `node packages/chart-engine/bench/matrix/run-matrix.mjs --runtime chromium --headed`
(software GL by default; on the reference machine use the real-GPU flag set its README names).
When a route mounts the chart, re-target the sheet at that route, so SCR-048 and the DOM mirror are
in the session too.

## Oracles (defined before probing)

- O1 **Silent wrongness** (P0 per the ticket): after recovery the chart shows bars, prices, a
  viewport or a crosshair that differ from the moment before the disturbance, with no notice.
- O2 **Silent degradation**: the chart draws in `degraded-2d` (or not at all) while nothing tells
  the user; or the app's `frameStats.renderProfile` disagrees with what is drawn (see D-01 in the
  record).
- O3 **Missing or repeated code**: a disturbance that should emit `ENGINE_CONTEXT_LOST`,
  `ENGINE_CONTEXT_RESTORED`, `ENGINE_CONTEXT_RESTORE_FAILED`, `ENGINE_NO_WEBGL2` or (once E11-S15
  #448 lands) `ENGINE_MEMORY_PRESSURE` emits none, or emits it more than once per episode.
- O4 **Animation storm or stale model** after foregrounding: frames replayed, or a model that
  believes it is current while the feed moved on.
- O5 **Focus or data cursor lost** after recovery (asserted once E11-S13 #520 lands; note it now).
- O6 **Leak**: the tab's memory or GPU memory climbing across repeated disturbances.

## Session sheet

One row per disturbance. "Executor" is who ran it; leave the result blank until a session runs.
Record the machine, OS, GPU and driver, browser or Electron version, and the build sha in the
header of each session.

| #   | Disturbance                        | How                                                           | Watch (oracles)    | Executor                      | Result       |
| --- | ---------------------------------- | ------------------------------------------------------------- | ------------------ | ----------------------------- | ------------ |
| M1  | Monitor disconnect mid-pan         | unplug the display the window is on, re-plug after 10 s       | O1, O2, O3, O5     | owner / QA, reference machine | not executed |
| M2  | Window minimise and restore        | minimise for 60 s with the feed running, restore              | O1, O4, O5         | owner / QA, reference machine | not executed |
| M3  | Machine sleep and wake             | sleep for 5 min, wake, unlock                                 | O1, O2, O3, O4, O6 | owner / QA, reference machine | not executed |
| M4  | Real DPR change mid-pan            | drag the window to a display with another scale while panning | O1, O5             | owner / QA, reference machine | not executed |
| M5  | Tab backgrounded for 10 min        | switch tab for 10 min with the feed running, switch back      | O1, O4             | owner / QA, reference machine | not executed |
| M6  | Driver reset (where the OS allows) | the OS's graphics-driver reset shortcut, once                 | O1, O2, O3         | owner / QA, reference machine | not executed |
| M7  | Repeated disturbance               | M2 and M5 alternately, 10 times                               | O6                 | owner / QA, reference machine | not executed |

## Session metrics (fill in when run)

- Time box: 90 min. Start / end (UTC):
- Build sha, machine, GPU and driver:
- Disturbances run, findings filed (as rows in the record's §6, priority per the ticket):

### Session 1 (2026-10-31)

- Executor: the E11-Q04 agent, ruling BQ-15. Build: this PR's head, `pnpm --filter
@candleviewer/chart-engine build`.
- Machine: WSL2 laptop; GPU NVIDIA RTX PRO 500 (Blackwell, laptop) through Mesa D3D12 and ANGLE's
  OpenGL backend (renderer string in the record §4). Not the reference machine; not a native driver.
- Target: the browser lane's page (same built engine as the bench matrix page), headless.
- Run: real `WEBGL_lose_context` at idle, mid-pan, three in 10 s, and the two F-14 fallbacks; all
  restored with each code once. Heap over 100 cycles: pending (API unavailable headless).
- M1 to M7: not run (each needs a headed window and a physical or OS-level disturbance).
- Findings: none new; D-01 (#5230) is a facade fault the lane does not observe.

## Debrief prompts

- Which disturbance came back wrong, and was the user told?
- Did any recovery take longer than the 2 s R1 budget (30-release-roadmap §5.3, criterion 8)?
- What would make the next session cheaper (a mounted route, a scripted DPR change)?
