# E08-C6 Charter: the tape under high-cadence bursts

- Ticket: E08-Q06 (#283) · Format: session-based test management · Date: 2026-10-19
- Tester: AI agent (hcl-worker-2). **Deviation (honest scope):** no live burst, no staging and no 90-minute human time box. The session was in-process: the trade stream, dispatch-lane, bus and chaos suites re-run, and a throwaway probe pushed synthetic bursts through the production `TradeStream` (`TradeHarness` from the contract pack) on a fake clock. The recorded corpus holds at most two prints per frame, so burst shapes were synthetic.
- No credentials used; no network: in-process only, and none of the suites re-run is one of the two pack tests that resolve a venue host name until #3826 lands (`docs/qa/e08-signoff.md` section 11).

## Charter

Explore the tape under high-cadence bursts to discover ordering, dedup and truncation defects.

## Oracles (defined before probing)

- O1 A trade id published twice inside the dedupe window, or a unique print suppressed.
- O2 A valid print dropped with no gap marker and no counter.
- O3 An order inversion within a symbol on the bus that 24 section 2.1 says is ordered or counted.
- O4 A burst on one symbol that starves another (#1916).

## Areas covered (in-process evidence)

| Probe                                         | Evidence                                                                                                                                                                  | Result                             |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| 20 frames x 500 prints, 50 repeats per frame  | probe `p6`: 10 000 unique published, 950 duplicates suppressed and counted                                                                                                | ok (O1 ok)                         |
| Duplicates after a reconnect                  | `services/api/tests/contract/bybit/test_contract_trades.py::test_reconnect_replay_duplicates_are_published_once` (order-dependent failure #1899 in some full-gate orders) | ok in this run                     |
| Gap, backfill, unrecovered window             | chaos `test_s04_trade_stream_gap.py`; `services/api/tests/unit/ingestion/test_trade_stream.py`                                                                            | gap marked, backfilled or reported |
| Per-symbol isolation under a stalled consumer | `services/api/tests/unit/ingestion/test_per_topic_dispatch.py` (#1905, #1916), chaos `test_s10_bus_backpressure.py`                                                       | ok (O4 ok)                         |
| A later frame stamped 3 s earlier             | probe `p6`: published in arrival order, no counter, no log line                                                                                                           | **F6-1** (O3)                      |
| A frame of 2 000 prints, then one of 2 001    | probe `p6`: the first is published whole; the second is rejected whole (`trade frame rejected`, counted) and no gap event is published                                    | **F6-2** (O2, question)            |

## Session metrics

- Time: about 2 minutes of agent time, 09:48-09:50 UTC (code reading and probe `p6`, after one read of the dedupe ring at 09:37), plus this charter's share of the one suite re-run for all six charters at 09:50 and the debrief, written at 10:00; not a 90-minute human session. Times are from the agent's tool-call log.
- Tests re-run: trade stream, per-topic dispatch, the trades contract pack, the bus suite, chaos s04 and s10, the resource-exhaustion abuse cases and the trade app end to end: 118 passed, 1 xfailed (#1893), 1 deselected (`perf`), 8.1 s wall.
- Probes: 1 (`p6`, three shapes). Not promoted: neither observation is a confirmed defect yet (below).

## Findings

**F6-1 — 24 section 2.1 promises counters the tape does not have (recorded, P3, not filed).** Section 2.1 (b) describes a 5-minute dedupe window counted in `md_duplicate_trades_total`; the stream keeps a 50 000-id ring per symbol and counts `trade_duplicates_suppressed_total`. Section 2.1 (c) says an inversion over 2 s increments `md_out_of_order_total` and logs both timestamps; no such counter or log exists, and the probe's 3 s inversion passed silently in arrival order. Realistic duplicate sources (a recent-trade backfill page of at most 1 000 prints) stay inside the ring, so no data defect follows from the window. Recommendation: the E08 owner aligns section 2.1 with the as-shipped names, or adds the out-of-order counter the doc promises.

**F6-2 — a frame over the 2 000-print cap is dropped whole without a gap marker (recorded as a question, not filed; condition B10 in `docs/qa/e08-signoff.md`).** The cap (`MAX_PRINTS_PER_BATCH`, E08-X02) guards against a hostile upstream, and the rejection is counted and logged; but the prints are lost with no `gap` event, unlike a print rejected after publish, which marks a gap (`services/api/tests/unit/ingestion/test_ingest_boundary.py::test_rejected_trade_after_publish_marks_gap`). Whether the venue can push more than 2 000 prints in one frame is not established in the repo (the corpus maximum is 2). If it can, the E08-Q01 rule makes this P0 (missing prints with no gap marker). Question for the E08 tech lead: confirm the venue's maximum push size, or mark a gap when a whole frame is refused.

## Not probed (needs a live burst, staging or another epic)

- A live liquidation-cascade burst on the real socket, and the 5x burst at full scale (E08-Q04's smoke profile runs it scaled; the 24 h and full profiles have not run, #2825).
- How E12's bar builders treat a cross-frame inversion (E12 scope).
- The WS `trades.{symbol}` batches (E08-TC-D02): no gateway publisher yet, #1878.

## Regression recommendation

None promoted. If F6-2 is confirmed as a defect, promote probe `p6`'s 2 001-print frame as a strict `xfail` asserting a gap event; if the doc is corrected for F6-1, no test is needed.
