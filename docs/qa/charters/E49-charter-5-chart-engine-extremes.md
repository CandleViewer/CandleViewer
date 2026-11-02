# E49-C5 Charter: Chart engine at extremes

- Ticket: E49-Q02 (#1336) · Format: session-based, 90 min (45 QA alone, 45 paired with a domain engineer) · Status: run 1 (2026-11-01): not reached
- Cites: 03 §11.2 (chart-engine visual correctness at extreme zoom / density), §8 (engine FPS harness; frame findings route to E46), §9 (WebGL context loss)
- Mission: make the chart draw something false: a wrong bar, a misplaced cell, a stale pane after recovery.
- Areas:
  - maximum bar count (the `max_history_bars` setting) at full zoom out and in
  - extreme footprint density: every cell visible, imbalance markers on
  - rapid interval switching while data streams
  - multi-panel layouts at the pane-count budget
  - GPU context loss and recovery mid-pan and mid-upload
- Oracles:
  - O5.1 a drawn value differs from the data model (price, volume, time, cell)
  - O5.2 after context restore: lost viewport, selection or data, or more than a one-frame flash (03 §9)
  - O5.3 an interval switch that shows bars of the old interval
  - O5.4 frame time over budget: routed to E46 (#72) with its reproduction, not graded here
  - O-ALL.1 an uncaught page error or a console error (every charter)
- Keyboard-only segment (03 §12): the chart: pan, zoom, switch interval and read the crosshair summary with the keyboard alone.
- Seeded stack: tier A (bench pages) or B of `docs/qa/e49-exploratory-harness.md` §2. Recorded, redacted fixtures
  only, behind the egress guard (C-13.5); Demo environment flag; test accounts only.
- Automated neighbours: E11-Q04 charter session 1 (`docs/qa/charters/E11-charter-1-engine-chaos.md`, run 2026-10-31), the `engine-bench` scenes.

## Explorable at `origin/main` (2026-11-01)

| Surface                             | State                                                     |
| ----------------------------------- | --------------------------------------------------------- |
| A mounted chart in the app          | not built: no route mounts the chart (E11-Q04 record §0)  |
| Engine bench scenes and matrix page | `packages/chart-engine/bench/` (headless, synthetic data) |
| Context-loss browser lane           | `packages/chart-engine/test/chaos/browser/` (E11-Q04)     |

## Debrief (one block per session)

Mission · areas actually probed · oracles used · findings (with reproduction steps, rows in the
run record) · areas not reached · keyboard-only screens and dead ends · time spent.

- Run 1 (2026-11-01): not reached. Nearest evidence: E11-Q04 session 1 (2026-10-31). Next: tier A on
  the bench pages once a route mounts the chart.
