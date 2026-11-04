# E11-C6 Charter: the long session (four hours with a feed)

- Ticket: E11-Q06 (#518) · Format: session-based test management (`docs/plan/03-testing-strategy.md` §11.2) · Written:
  2026-11-04
- Status: **written, not yet run.** Pack index: `docs/qa/e11-regression-pack.md` section 5.
- Time box: 4 hours, one continuous session (BQ-5). A ticket-specific exception to `03` §11.2's 60 to 120 minute box (`03` is not edited, C-16.5), on purpose: the
  ticket states the long session cannot be shortened, because slow memory growth and frame-time creep only show over
  hours. B10's 30-minute soak (`packages/chart-engine/bench/engine/engine-lib.mjs`:86) catches fast growth only.
- Executor (BQ-7): an agent on the reference machine; the owner spot-checks the chart at the end.

## Charter

Leave the chart running for four hours on the Demo environment's public feed, using it lightly at fixed checkpoints, to discover **memory
growth, frame-time drift, stale or desynced state and recovery failures** that no shorter run shows.

## Target

A mounted route with the Demo environment (public market data is the live public stream, `docs/plan/20-architecture.md`:871) (BQ-6, G-04). No dry run substitutes: a bench-page run with
the seeded generator is recorded as a rehearsal only.

## Measurement

Readings are taken at minute 0 (after the first full render), then every 30 minutes, then at 240:

- frame time p50 and p95 over a scripted 20 s pan (B1's scripted pan, `packages/chart-engine/bench/engine/engine-lib.mjs`:306);
- engine memory: the engine's own estimate (`getStats()`), plus a heap reading by the method written into the session
  header (G-07 in the pack: SCR-046 after #523, or the E11-Q07 isolated page);
- correctness: the last ten bars in SCR-045 against the feed's own values; the axis range against `getState()`.

## Areas

| #   | Area              | Ideas to try                                                                         |
| --- | ----------------- | ------------------------------------------------------------------------------------ |
| A1  | Checkpoint use    | at each checkpoint: pan 2 000 bars back, return with `End`, switch interval and back |
| A2  | Background spells | minimise for 10 minutes twice; background the tab for 10 minutes once                |
| A3  | Feed disturbance  | one network drop of 60 s mid-session (the browser's offline switch), then back       |
| A4  | Display           | one theme switch at hour 2; one DPR change at hour 3 where the machine allows        |

## What looks wrong (defined before probing)

- W1 **Drift**: memory or frame time at minute 240 differs from minute 0 by more than 5 % (ticket scenario 4: within 5 percent of the starting values).
- W2 **Stale**: SCR-045 or the drawn bars disagree with the feed; the forming bar frozen.
- W3 **Desynced**: the axis range, the crosshair readout and the table disagree with each other.
- W4 **Recovery**: after A2 or A3, a gap or duplicate bar, a frozen chart, or no stale indication while the feed is off.
- W5 **Growth in counts**: GL objects, listeners or workers rising checkpoint over checkpoint.

## Session sheet

Header (ticket-specific exception: 4 hours, not `03` §11.2's 60 to 120 minutes): build sha, browser and version, GPU and driver, OS, display scale, feed, the heap method, executor, machine (GPU, driver, OS; below the `26` section 1 reference class is below-reference evidence under the #220 rule).

| #   | Probe             | How                                     | Watch      | Executor      | Result       |
| --- | ----------------- | --------------------------------------- | ---------- | ------------- | ------------ |
| M1  | Baseline          | readings at minute 0                    | —          | agent         | not executed |
| M2  | Checkpoints       | A1 and the readings every 30 minutes    | W1, W5     | agent         | not executed |
| M3  | Background spells | A2, readings before and after           | W2, W4     | agent         | not executed |
| M4  | Feed disturbance  | A3                                      | W2, W4     | agent         | not executed |
| M5  | Display           | A4                                      | W1, W3     | agent         | not executed |
| M6  | End state         | readings at 240; the owner's spot check | W1, W2, W3 | agent / owner | not executed |

## Session metrics (fill in when run)

- The reading table, one row per checkpoint, with the deltas from minute 0.
- Findings with severity (`03` §11.3) and owner.

## Debrief prompts

- Which reading moved steadily rather than in a step, and from which checkpoint?
- What would a shorter run have missed?
