# E11-C5 Charter: the keyboard-only trader (operable versus usable)

- Ticket: E11-Q06 (#518) · Format: session-based test management (`docs/plan/03-testing-strategy.md` §11.2) · Written:
  2026-11-04
- Status: **written, not yet run.** Pack index: `docs/qa/e11-regression-pack.md` section 5.
- Time box: 90 minutes, one session, pointer unplugged. Executor (BQ-7 †): an agent driving keys only through a headed
  browser; the owner reviews the sheet. Complements E11-Q05 (#517): conformance asks "does it meet the standard", this
  asks "is it workable for a whole session".

## Charter

Run a complete chart session without the pointer (open the chart, navigate history, change scales, read values, use the
data table, change panes and settings) to discover where the chart is **technically operable but not practically
usable**: too many keystrokes, lost focus, silent results, or a task that cannot be finished.

## Target

A mounted route with SCR-045 counts (BQ-6 †, G-04); the SCR-045 panel and the price-scale menu are not on the bench
page, so no dry run covers M3 or M4.

## Areas

| #   | Area             | Ideas to try                                                                                                              |
| --- | ---------------- | ------------------------------------------------------------------------------------------------------------------------- |
| A1  | Reach the chart  | from the app shell to a focused chart pane; count the keystrokes                                                          |
| A2  | Navigate         | arrows, `Home` / `End`, `+` / `-`; reach a bar from a date read in the news                                               |
| A3  | Read values      | the data cursor's readout (after #520), the live region's rate, the last price                                            |
| A4  | The data table   | `Alt+T` to SCR-045 and back; sort, filter, copy; focus kept across live updates (after #521)                              |
| A5  | Scales and menus | `Shift+F10` for the price-scale menu, every item, `Esc` back to the chart                                                 |
| A6  | Panes            | move focus between panes; resize with the splitter keys (after #446)                                                      |
| A7  | Screen reader    | one pass of A2 to A4 with NVDA on the reference machine; the scripts in `docs/qa/a11y/sr/scripts/10-chart-data-cursor.md` |

## What looks wrong (defined before probing)

- W1 **Focus**: lost, trapped, or invisible after a menu, a panel switch or a live update.
- W2 **Silent**: a key that changes something with no announcement, or announces nothing useful.
- W3 **Noise**: announcements faster than they can be heard, or the same one twice.
- W4 **Cost**: a routine task (find a bar, read its OHLCV, switch scale) that takes more than ten keystrokes.
- W5 **Dead end**: a task from the session that cannot be finished without the pointer.

## Session sheet

Header: build sha, browser and version, OS, screen reader and version (M7), target.

| #   | Probe            | How                               | Watch      | Executor      | Result       |
| --- | ---------------- | --------------------------------- | ---------- | ------------- | ------------ |
| M1  | Reach the chart  | A1, keystrokes counted            | W1, W4     | agent / owner | not executed |
| M2  | Navigate         | A2                                | W2, W4     | agent / owner | not executed |
| M3  | Read values      | A3; blocked until #520 is In Test | W2, W3     | agent / owner | not executed |
| M4  | The data table   | A4; blocked until #521 is In Test | W1, W2, W5 | agent / owner | not executed |
| M5  | Scales and menus | A5                                | W1, W5     | agent / owner | not executed |
| M6  | Panes            | A6; blocked until #446 is In Test | W1, W5     | agent / owner | not executed |
| M7  | Screen reader    | A7                                | W2, W3     | owner         | not executed |

## Session metrics (fill in when run)

- Start / end (UTC), executor, keystroke counts per task, areas covered and not covered.
- Findings with severity (`03` §11.3; an AA failure is P2 or higher) and owner.

## Debrief prompts

- Which task would a keyboard-only trader give up on?
- Which finding does E11-Q05's audit not see, and why?
