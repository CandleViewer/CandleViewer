# E08-C1 Charter: instrument catalogue under metadata churn

- Ticket: E08-Q06 (#283) · Format: session-based test management · Date: 2026-10-19
- Tester: AI agent (hcl-worker-2). **Deviation (honest scope):** no staging build, no browser, no docker stack and no 90-minute human time box. The session was in-process: the oracles below were checked by re-running the existing fakes-backed suites, reading the catalogue, policy and book code paths, and running throwaway probes against production classes with the recorded corpus (`packages/fixtures/bybit/2026-10-05`). Nothing was observed in a running app or a browser. Items that need a human or staging are under "Not probed" with the issue that owns them.
- No credentials used; no network: in-process only, and none of the suites re-run is one of the two pack tests that resolve a venue host name until #3826 lands (`docs/qa/e08-signoff.md` section 11).

## Charter

Explore the instrument catalogue with metadata churn to discover stale-rounding and stale-display defects.

## Oracles (defined before probing)

- O1 After a refresh changes a tick or lot size, any server path that still rounds, validates or keys data on the old grid (E08-Q01 rule: stale rounding is P1).
- O2 `metadata_version` that does not increase on a real change, or increases with no change.
- O3 A catalogue served past its refresh cadence with no `stale_since`, or a failed refresh that empties the catalogue.
- O4 Any book or price surface that carries data from two grids at once without a desync signal (E08-Q01 section 0.1: silent divergence is P0).

## Areas covered (in-process evidence)

| Probe                                                       | Evidence                                                                                                                                                                                                 | Result                                                      |
| ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Version bump, `changed_fields`, no-op refresh               | `services/api/tests/contract/bybit/test_contract_catalogue.py` (A08), `services/api/tests/unit/ingestion/test_instruments_refresh.py`                                                                    | bump only on change (O2 ok)                                 |
| Failed refresh keeps the previous catalogue, marks it stale | `services/api/tests/unit/ingestion/test_instruments_catalogue.py`, `services/api/tests/unit/api/test_instruments_router.py` (`stale_since`)                                                              | ok (O3 ok)                                                  |
| Server rounding after a change (E08-S02 policy)             | code read: `candleviewer/exchange/policy.py` takes one `Instrument`; no production caller caches a policy today (order path is E29)                                                                      | not reachable yet (O1: no server path)                      |
| Book tick grid after a change                               | code read: the book stream resolves the tick per frame from the current catalogue (`app.py` `_tick_size`); no book reacts to an instrument revision                                                      | probe below                                                 |
| Tick change on a live book, 3 delta shapes                  | probes `p1`, `p1b` (scratch), promoted as a strict `xfail`; since #3823, `services/api/tests/unit/ingestion/test_book_grid_resync.py::test_f1_a_coarser_tick_size_never_serves_173_levels_at_172_prices` | **F1** (O4), fixed                                          |
| Malformed or churned catalogue rows                         | `services/api/tests/security/ingestion/test_market_integrity.py` B-13 to B-15                                                                                                                            | per-row rejection holds except #1896 (open, strict `xfail`) |

## Session metrics

- Time: about 4 minutes of agent time, 09:38-09:42 UTC (code reading, probes `p1` and `p1b`), plus this charter's share of the one suite re-run for all six charters at 09:50 and the debrief, written at 09:56; not a 90-minute human session. Times are from the agent's tool-call log.
- Tests re-run: catalogue, instruments, precision and policy suites, `services/api/tests/unit/api/test_instruments_router.py` and the market-integrity abuse cases: 123 passed, 2 xfailed (#1896), 1 deselected (`perf`), 2.3 s wall.
- Probes: 2 (one bid-only delta; then both-sides update, bid update with ask delete, bid delete only). 1 promoted.

## Findings

**F1 — a tick-size change on a live book applies later deltas on a second price grid (filed by the coordinator as #3806, P0, on 2026-10-19; fixed by #3823 the same day).** The book keys levels by integer ticks computed with the tick size the catalogue holds when each frame is parsed. When a refresh moves BTCUSDT from 0.1 to 0.5 while the book is LIVE, the next delta is keyed on the 0.5 grid while the book still holds 0.1-grid keys: an update to a price both grids share lands as a second level at the same price, and a delete of such a price is a no-op, so the stale level stays. The book stays LIVE and is served with `stale: false`. A delta that also updates an ask happens to trip the crossed-book check and forces a resync, which bounds the window, but a frame that only deletes, or only touches bids, passes. Severity: P0 under the E08-Q01 rule for data that is wrong with no visible signal; exposure needs a venue tick change on a symbol with a live book. Reproduced on main `c21b2eb3`, in-process, and promoted as a strict `xfail`. #3823 (merged 2026-10-19 13:53 UTC) makes a tick-size change under a live book a resync and holds every book to one grid, and it promoted the same repro as its regression test, so review round 3 of this change removed the strict `xfail`. E08-TC-E08 (the WS `instrument_revision` snapshot) is deferred to #1878; #3823 covers the engine half.

No other anomaly. Absence of findings elsewhere is not evidence of absence: the scope was the server side only.

## Not probed (needs a human, a browser or staging)

- Client re-validation of an open order ticket after a tick change (E08-TC-A08 client half), the symbol drawer refresh (SCR-103) and the delisted banner (A05): E08-Q05, #282, which has not run.
- `POST /instruments/refresh` over HTTP: the route is declared in `docs/plan/22-api-openapi.yaml` but not mounted (`services/api/tests/contract/rbac/matrix.yaml` state `not_mounted`); the scheduler was exercised directly.
- A real 12-hour scheduled refresh on staging (E08-TC-A09 manual half).

## Regression recommendation

Done by #3823, whose tests are in the pack: the F1 repro through the stream's grid check and through the book's own invariant (`services/api/tests/unit/ingestion/test_book_grid_resync.py::test_f1_a_coarser_tick_size_never_serves_173_levels_at_172_prices`), probe `p1b`'s delete-only shape at the book level (`services/api/tests/unit/book/test_book_grid.py::test_book_state_delete_at_held_ticks_with_another_price_raises_grid`, `::test_book_state_delete_of_a_held_price_at_other_ticks_raises_grid`), one frame on two grids (`::test_engine_resyncs_with_reason_grid_on_a_mixed_grid_delta`) and a property over mixed grids (`::test_book_state_keeps_one_level_per_price_or_raises_grid`). The stream's check resyncs a delta parsed on a new grid before applying it, whatever its shape. The F1 strict `xfail` is gone.
