# E11-C4 Charter: the awkward user (state corruption from hostile interaction)

- Ticket: E11-Q06 (#518) · Format: session-based test management (`docs/plan/03-testing-strategy.md` §11.2) · Written:
  2026-11-04
- Status: **written, not yet run.** Pack index: `docs/qa/e11-regression-pack.md` section 5.
- Time box: 90 minutes, one session. Executor (BQ-7 †): an agent through a headed browser; the owner reviews the sheet.

## Charter

Interact with the chart badly on purpose (rapid mode switching, gestures interrupted halfway, keyboard and pointer at the
same time, resizing during a drag) to discover any **state the chart cannot get out of**, or any state where what it
draws disagrees with what it reports.

## Target

A mounted route counts (BQ-6 †, G-04); before that, the bench matrix page as a labelled dry run, with mode switches
through the engine API from the console, as E11-C2 does.

## Areas

| #   | Area                  | Ideas to try                                                                                        |
| --- | --------------------- | --------------------------------------------------------------------------------------------------- |
| A1  | Rapid mode switching  | log, percent, linear ten times a second; series kind switches mid-pan; theme switches mid-zoom      |
| A2  | Interrupted gestures  | release the pointer outside the window mid-drag; a wheel burst cut by a key; a flick cut by a touch |
| A3  | Keyboard plus pointer | hold an arrow key while dragging; `Home` mid-glide; `Esc` with the price-scale menu open mid-drag   |
| A4  | Resize during a drag  | resize the window and drag a splitter while panning; zero-height container, then restore            |
| A5  | Focus churn           | Tab out mid-drag; Alt+T to the table and back mid-glide; open and close the menu repeatedly         |
| A6  | Lifecycle             | unmount and remount the chart during a pan (route away and back)                                    |

## What looks wrong (defined before probing)

- W1 **Asked versus shown**: `PriceScale.getState()` disagrees with the drawing, the badge or the menu.
- W2 **Stuck**: a gesture that never ends (the plot keeps moving), a lock that cannot be undone, a menu that will not close.
- W3 **Numeric breakage**: NaN, Infinity, a blank plot, a collapsed axis.
- W4 **Lost input**: keys or pointer ignored after the sequence, with no reason shown.
- W5 **Console**: any uncaught error or unhandled rejection in the page or the worker.

## Session sheet

Header: build sha, browser and version, GPU and driver, OS, input devices, target.

| #   | Probe                 | How                                    | Watch      | Executor      | Result       |
| --- | --------------------- | -------------------------------------- | ---------- | ------------- | ------------ |
| M1  | Rapid mode switching  | A1, `getState()` read after each burst | W1, W3, W5 | agent / owner | not executed |
| M2  | Interrupted gestures  | A2                                     | W2, W4     | agent / owner | not executed |
| M3  | Keyboard plus pointer | A3                                     | W2, W4     | agent / owner | not executed |
| M4  | Resize during a drag  | A4                                     | W3, W5     | agent / owner | not executed |
| M5  | Focus churn           | A5                                     | W4         | agent / owner | not executed |
| M6  | Lifecycle             | A6, ten times                          | W3, W5     | agent / owner | not executed |

## Session metrics (fill in when run)

- Start / end (UTC), executor, areas covered and not covered.
- Each finding with the exact input sequence that reached it, its severity (`03` §11.3), its owner and the E11-Q01 case
  that should have caught it, or a proposed new case.

## Debrief prompts

- Which sequence left the chart in a state no story's Gherkin names?
- Which of these sequences should become a scripted E11-Q02 case?
