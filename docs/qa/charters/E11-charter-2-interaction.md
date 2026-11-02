# E11-C2 Charter: chart interaction (navigation, scales, axes, crosshair)

- Ticket: E11-Q01 (#384) · Format: session-based test management (`docs/plan/03-testing-strategy.md` §11.2) · Written:
  2026-11-02
- Status: **written, not yet run.** The scripted cases are in the plan
  `packages/chart-engine/test/plans/e11-interaction.md`; this charter and its session sheet cover what the scripted cases
  cannot: the combinations a trader reaches without trying. No result is claimed until a session runs.
- Time box: 90 minutes, one session, by QA or the owner, once E11-S07 (#388) is In Test. A session run earlier covers the
  S04 and S05 areas only and says so in its header.

## Charter

Explore the chart's navigation and price scales as a trader would in a fast session (pan, zoom, flick, drag the price
axis, switch scale modes, use the keyboard only, switch reduced motion on and off) to discover any state in which the
chart **shows a range, a label or a scale mode that differs from what the user asked for**, loses the lock or the
autoscale state without saying so, or stops responding to the keyboard.

## Target

No app route mounts the chart yet (SCR-030 is the first, `apps/web/test/composition-guard.test.ts`). Until one does, the
target is the bench matrix page `packages/chart-engine/bench/matrix/page/matrix.html` served by
`node packages/chart-engine/bench/matrix/run-matrix.mjs --runtime chromium --headed`, as E11-C1 does; the price-scale
menu (SCR-043) is out of reach there, so mode switches go through the engine API from the console. When a route mounts
the chart, re-target the session at that route so the menu, the badge and the DOM mirror are in the session too.

Data: the plan's FX-100K † (section 6; a seeded generator, not recorded data). No live exchange, no account, no key.

## Areas

| #   | Area                   | Ideas to try                                                                                                                      |
| --- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| A1  | Scale-mode churn       | switch modes while panning, mid-glide, mid-axis-drag; log on data near zero; percent while panning back and forth over the anchor |
| A2  | Lock and autoscale     | lock in one mode, switch mode, unlock; lock, then load more history; double-click on the axis versus on the plot                  |
| A3  | Edges                  | the first and last bar, the spacing clamps, a single bar, a flat stretch, the forming bar at the right edge                       |
| A4  | Keyboard only          | every navigation with the mouse unplugged; focus after a menu closes; keys during a glide                                         |
| A5  | Reduced motion         | toggle the app's motion setting mid-glide, mid-drag, with the menu open; compare the OS setting with the in-app override          |
| A6  | Mixed input            | trackpad pinch plus a key; wheel over a gutter edge; a touch during a glide; pointer leaving the window mid-drag                  |
| A7  | Crosshair (after #388) | readout against the bar's data, magnet near a gap, countdown at close, the keyboard crosshair while held                          |

## Oracles (defined before probing)

- O1 **Asked versus shown**: `PriceScale.getState()` (`mode`, `requestedMode`, `autoScale`, `inverted`) disagrees with
  what is drawn or with the menu.
- O2 **Silent state change**: the lock or autoscale changes with no badge change; log falls back without the D5
  sentence.
- O3 **Numeric breakage**: a NaN, Infinity, blank plot, a collapsed axis (fewer than two labelled ticks) or a range that
  jumps on an input that should not move it.
- O4 **Anchor drift**: the bar under the cursor moves during a zoom; the view drifts after a symmetric zoom in and out.
- O5 **Motion**: any glide or animated jump under reduced motion; a glide that resumes after reduce is switched off.
- O6 **Keyboard**: focus lost or trapped; a key that does nothing with no reason; a key that changes something the help
  text does not list.

## Session sheet

Record the build sha, the browser and version, the GPU and driver, the OS, and the motion setting in the header. One row
per area (M1 to M7 follow A1 to A7); "Executor" is who ran it; leave the result blank until a session runs, and link each
finding to its defect and the plan case that should have caught it.

| #   | Probe                  | How                                                          | Watch (oracles) | Executor   | Result       |
| --- | ---------------------- | ------------------------------------------------------------ | --------------- | ---------- | ------------ |
| M1  | Scale-mode churn       | A1's ideas, each mode switch from the console API            | O1, O2, O3      | owner / QA | not executed |
| M2  | Lock and autoscale     | A2's ideas; read `getState()` and the badge after each step  | O1, O2          | owner / QA | not executed |
| M3  | Edges                  | A3's ideas on FX-100K, then a single bar and a flat stretch  | O3, O4          | owner / QA | not executed |
| M4  | Keyboard only          | A4's ideas with the mouse unplugged, `Home` / `End` included | O6              | owner / QA | not executed |
| M5  | Reduced motion         | A5's ideas, toggling `data-motion` and the OS setting        | O5              | owner / QA | not executed |
| M6  | Mixed input            | A6's ideas, trackpad, wheel and touch together               | O3, O4, O6      | owner / QA | not executed |
| M7  | Crosshair (after #388) | A7's ideas; blocked until E11-S07 (#388) is In Test          | O1, O3, O6      | owner / QA | not executed |

## Session metrics (fill in when run)

- Start / end (UTC), executor:
- Build sha, machine, GPU and driver:
- Areas covered and not covered; findings filed (priority and owner per `03` §11.3), each linked to the plan case that
  should have caught it, or a new case proposed for the plan.

## Debrief prompts

- Which combination surprised you, and does the plan's matrix (section 2) have a cell for it?
- Which state did the chart change without telling you?
- What would make the next session cheaper (a mounted route, a scripted fixture loader, the menu on the bench page)?
