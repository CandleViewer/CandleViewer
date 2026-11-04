# E11-C7 Charter: cross-story seams

- Ticket: E11-Q06 (#518) · Format: session-based test management (`docs/plan/03-testing-strategy.md` §11.2) · Written:
  2026-11-04
- Status: **written, not yet run.** Pack index: `docs/qa/e11-regression-pack.md` section 5 (BQ-8 †).
- Time box: 90 minutes, one session. Executor (BQ-7 †): an agent through a headed browser; the owner reviews the sheet.

## Charter

Exercise two stories' behaviours at the same moment, where neither story's acceptance criteria apply, to discover any
seam where the chart **stops being correct or fails to recover**. A seam defect is filed against the pair of stories it
sits between (ticket scenario 5).

## Target

A mounted route counts (BQ-6 †, G-04). The bench matrix page is a labelled dry run for S1, S4 and S5 only.

## Seams

| #   | Seam                                    | Stories   | How to stage it                                                                                  | Waits on   |
| --- | --------------------------------------- | --------- | ------------------------------------------------------------------------------------------------ | ---------- |
| S1  | theme change during a pan               | T04 × S04 | start a flick, switch theme mid-glide; repeat with density                                       | nothing    |
| S2  | LOD step-down while the table is open   | S12 × S14 | open SCR-045, zoom out until LOD steps down; read the table's rows and the disclosure            | #418, #521 |
| S3  | context loss during a sync propagation  | S02 × S09 | two synced panes, start a pan in one, force `WEBGL_lose_context` mid-propagation                 | #446       |
| S4  | memory pressure during atlas generation | S15 × S11 | clear the atlas cache, start the chart under the memory budget's edge, change font size          | #448, #336 |
| S5  | DPR change mid-momentum                 | S10 × S04 | flick, then move the window to a display with another scale (or change the zoom level) mid-glide | nothing    |

## What looks wrong (defined before probing)

- W1 **Incorrect after the seam**: bars, axes or labels differ from the same view reached without the seam.
- W2 **No recovery**: the chart does not return to a correct, responsive state within 2 s of the second event.
- W3 **Disagreement**: the table, the readout, `getState()` and the drawing disagree.
- W4 **Silent**: an LOD step or a loss with no disclosure.
- W5 **Console**: any uncaught error in the page or the worker.

## Session sheet

Header: build sha, browser and version, GPU and driver, OS, display scale, target.

| #   | Probe | How                                     | Watch      | Executor      | Result       |
| --- | ----- | --------------------------------------- | ---------- | ------------- | ------------ |
| M1  | S1    | five times each for theme and density   | W1, W2     | agent / owner | not executed |
| M2  | S2    | blocked until #418 and #521 are In Test | W3, W4     | agent / owner | not executed |
| M3  | S3    | blocked until #446 is In Test           | W1, W2, W3 | agent / owner | not executed |
| M4  | S4    | blocked until #448 and #336 are In Test | W2, W4, W5 | agent / owner | not executed |
| M5  | S5    | five times                              | W1, W2     | agent / owner | not executed |

## Session metrics (fill in when run)

- Start / end (UTC), executor, seams covered and not covered.
- Findings with severity (`03` §11.3), the story pair, and the owner of each story.

## Debrief prompts

- Which seam has no owner, because neither story thought it was theirs?
- Which seam should become a scripted case, and in which suite?
