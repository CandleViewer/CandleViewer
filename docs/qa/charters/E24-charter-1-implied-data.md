# E24-C1 Charter: a place where the panel implies data we do not have

- Ticket: E24-Q01 (#771) · Format: session-based, **two** 90-minute sessions split by sub-pane · Status: **not yet run** (ready to run)
- Plan: `docs/qa/e24-derivatives-test-plan.md` (cases BB-xxx-nn, SM-n, CV-nn, NG-nn cited below; section 9). Cites `03` §11.2, §11.3.
- Mission: find a place where the SCR-054 panel implies data we do not have: a zero that is really unknown, a prediction that reads as settled, an estimate that reads as exchange fact, a source or interval that is not what the label says.
- Sessions: **1A** the OI and funding sub-panes and the symbol header; **1B** the liquidation and basis sub-panes and the zones overlay. Each 90 minutes, a tester who did not write the plan. **1A may overrun** (it holds more states than 1B): if it does, take these first and push the rest to a later session, never skipping the first three: the zero-versus-unknown reads (O1.1), the predicted-versus-settled reads (O1.2), the source and interval labels (O1.4), then the countdown (O1.6), then the table alternatives; the second 45 minutes paired with an E24 developer for the layer in which the fact was lost.
- Status of the surface: no OI, funding, liquidation or basis pane is merged at the plan's pins (S01 to S08 open, D05 in #5616 and #5617). The session waits for E24-S02, E24-S04, E24-D05 and a seeded stack; the closing slice of #771 adds the run record below. No screen reader and no browser exist on the build host: if that still holds at run time, the E08 precedent applies (an in-process run, the `Not probed` list kept honest, the QA lead rules whether it meets the AC "Charters executed", plan Q-10).

## Areas

- **1A:** the OI series (`rest` and `ws_ticker` points, native-granularity note, gaps, stale shading); delta and quadrants on bars with and without an OI sample; the funding rate, the predicted rate, `n/a`, the annualised toggle and its tooltip; the countdown in the header and the pane; the 4 h symbol; the table alternatives of both.
- **1B:** liquidation bars and the feed for a window before, across and after the recorder's first timestamp; a symbol never recorded; the boundary marker and the partial chip; basis and the long/short ratio with a failing or unpublished source; estimated zones on and off, the acknowledgement, the badge, the drawer; every empty and retry state; units at a 360 px width.
- Both: copy against the deck byte for byte; greyscale; text for every state that colour carries.

## Oracles (defined before probing)

- O1.1 A **zero** shown where the value is unknown or not recorded (a bar before the boundary, a bar with no OI sample, an empty list for an uncovered window). P1 (plan SM-1, SM-4).
- O1.2 A **predicted** or accruing value styled or worded as settled, or a previous predicted value reused when none is published. P1 (SM-2).
- O1.3 An **estimated** zone or value without its badge, its acknowledgement, or its methodology; any wording that says the exchange published it. P1 and a security finding (BB-007-03).
- O1.4 A **source or interval** that differs from its label: `ws_ticker` shown as REST history, an OI series spliced across sources, the 8 h factor or text on a 4 h symbol. P1 (SM-3, SM-6).
- O1.5 A **fabricated or flat series** for an unavailable source (basis, ratio), or a blank pane instead of the retry state with `derivatives.retry.last_loaded`. P1 (BB-008-04, BB-008-05).
- O1.6 A countdown more than 1 s from the replay clock, or two timers, or a stale shading that does not clear. P1 (SM-5, BB-001-04).
- O1.7 A **figure with no unit**, or a liquidated side stated only by colour or as "Buy" / "Sell". P1 / P2 (BB-PNL-03).
- O-ALL.1 An uncaught page error or a console error (every charter).
- Each finding is reported with the **layer where the fact was lost** (engine, REST, WS, props, DOM) and the **signal that would have caught it**, or "none" as an observability finding (ticket Observability).

## Seed ideas (so the charter is a mission and not an open poke)

- 1A: switch the chart interval across 1m, 5m and 15m while the ticker streams, and read each point's source; replay a funding response with `predicted` and `estimated` removed; take the predicted rate away and then give it back; step the clock offset from +3 s to -2 s with 90 s left; pause the ticker across a settlement; change symbol from the 8 h to the 4 h one with annualisation on and read the tooltip; read the table with the pane in each state.
- 1B: request a 24 h window on a recorder that started 2 h ago and walk back across the boundary; open a symbol never recorded; fail the coverage metadata; set a minimum notional and read the legend; switch bars to the heatmap and look for an "(estimated)" badge that must not be there; turn zones on, cancel, confirm, and check the audit row; fail the ratio source; open the pane at 360 px.

## Keyboard-only segment (`03` §12)

The whole of one sub-pane per session without a pointer: reach the toggles, the Retry action, the table alternative, a zone badge and the acknowledgement dialog; focus visible; every state's text reachable. Full a11y audit stays with E24-Q04.

## Seeded stack and fixtures

Tier B of `docs/qa/e49-exploratory-harness.md` §2: recorded and corpus fixtures from `packages/fixtures` only, behind the egress guard (C-13.5), Demo environment flag, test accounts only. No key, token or `.env` value in any evidence (C-2.7). Fixtures and toggles by plan id (section 8): FX-NORMAL, FX-4H, FX-NO-OI (incl. the stale-open case), FX-RECORDER-GAP, FX-NEVER-RECORDED, FX-NO-PREDICTED, FX-BACKFILL-FAIL, FX-ROLLOVER; toggles FT-REST-503, FT-FEED-PAUSE, FT-CLOCK-OFFSET, FT-ROLLOVER, FT-NO-PREDICTED. The corpus is "documented-shape", not captured: say so in the debrief.

## Automated neighbours

E24-Q02 (E2E, the badge and the chip), E24-X02 (abuse cases), T04 flag-preservation test and T06 parity harness; none exists yet for the panel. The golden cases in `packages/fixtures/golden/derivatives/` check the engine, not the pane.

## Explorable at the plan's pins (2026-11-04)

| Surface                                    | State                                                                      |
| ------------------------------------------ | -------------------------------------------------------------------------- |
| `/market/open-interest`, `/market/funding` | on `main`; funding `meta.coverage` and `annualised_pct` in #5699 (open)    |
| `/market/liquidations`, `/market/metrics`  | contracts on `main`; handlers in #5273 and #5341 (open)                    |
| SCR-054 panes                              | not built (E24-S01 to S08 open); design pack D05 in #5616 and #5617 (open) |

## Debrief (one block per session; the template is the plan's section 9)

Mission · areas actually probed · oracles used · findings (reproduction, layer, severity, signal) · each finding a defect ticket or a recorded non-issue with its reason · areas not reached · keyboard-only dead ends · time spent.

- Run 1A: **not yet run.**
- Run 1B: **not yet run.**
