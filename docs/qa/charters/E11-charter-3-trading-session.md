# E11-C3 Charter: a trading session (what degrades over an hour)

- Ticket: E11-Q06 (#518) · Format: session-based test management (`docs/plan/03-testing-strategy.md` §11.2) · Written:
  2026-11-04
- Status: **written, not yet run.** Pack index: `docs/qa/e11-regression-pack.md` section 5.
- Time box: 60 minutes, one session. Executor (BQ-7 †): an agent on the reference machine through a headed browser; the
  owner reviews the session sheet.

## Charter

Use the chart for an hour the way a trader does (switch symbols and intervals, pan deep into history, change scale
modes, open more panes, then leave it running) to discover anything that **gets slower, drifts or goes stale** as the
session goes on, rather than anything that is wrong on first use.

## Target

A session counts for sign-off only on a route that mounts the chart with the demo environment's public feed (BQ-6 †;
gap G-04 in the pack). Until then a dry run may target the bench matrix page
(`node packages/chart-engine/bench/matrix/run-matrix.mjs --runtime chromium --headed`) with the seeded generator; its
header says "dry run, bench page" and it does not count. No account, no key, no live-environment data in any capture.

## Areas

| #   | Area                | Ideas to try                                                                                   |
| --- | ------------------- | ---------------------------------------------------------------------------------------------- |
| A1  | Symbol and interval | ten switches in a row; switch back to the first; switch during a pan and during a history load |
| A2  | Deep history        | pan to the oldest loaded bar, keep going so more loads, return with `End`                      |
| A3  | Scale modes         | linear, log, percent, inverted, each with autoscale on and locked; switch while the feed ticks |
| A4  | Panes               | add and remove panes; resize them; collapse one to its minimum (after #446)                    |
| A5  | Idle with a feed    | leave it 15 minutes untouched with the feed running, then use it again                         |
| A6  | Theme and density   | switch theme and density once each mid-session                                                 |

## What looks wrong (defined before probing)

- W1 **Slower over time**: the SCR-046 frame time (after #523) or the bench frame stats at minute 55 above minute 5 by
  more than 5 %.
- W2 **Stale**: the last bar's close differs from the feed, or the forming bar stops updating while the feed runs.
- W3 **Wrong after a switch**: a bar, label or scale from the previous symbol or interval still drawn.
- W4 **Silent degradation**: an LOD step, a `degraded-2d` handoff or a context loss with no badge or chip.
- W5 **Input lag**: a pan or zoom that visibly trails the pointer after the idle period.

## Session sheet

Header: build sha, browser and version, GPU and driver, OS, display scale, target (route or dry run), feed.

| #   | Probe               | How                                     | Watch      | Executor      | Result       |
| --- | ------------------- | --------------------------------------- | ---------- | ------------- | ------------ |
| M1  | Symbol and interval | A1, frame stats read before and after   | W1, W3     | agent / owner | not executed |
| M2  | Deep history        | A2, three loads deep                    | W1, W3, W5 | agent / owner | not executed |
| M3  | Scale modes         | A3 with the feed ticking                | W2, W4     | agent / owner | not executed |
| M4  | Panes               | A4; blocked until #446 is In Test       | W1, W4     | agent / owner | not executed |
| M5  | Idle with a feed    | A5; frame stats at minutes 5, 30 and 55 | W1, W2, W5 | agent / owner | not executed |
| M6  | Theme and density   | A6                                      | W3, W4     | agent / owner | not executed |

## Session metrics (fill in when run)

- Start / end (UTC), executor, areas covered and not covered.
- Frame time and memory at minutes 5, 30 and 55 (the method used, written down).
- Findings with severity (`03` §11.3) and owner, each linked to the story pair or story it sits on.

## Debrief prompts

- What changed between minute 5 and minute 55 that no single-story test would see?
- Which switch left something of the old view behind?
