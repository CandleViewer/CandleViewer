# E08-C2 Charter: the order book under adversarial subscription patterns

- Ticket: E08-Q06 (#283) · Format: session-based test management · Date: 2026-10-19
- Tester: AI agent (hcl-worker-2, run8 aa6271c0). **Deviation (honest scope):** no staging build, no WS client against a running gateway, no docker stack and no 90-minute human time box. The session was in-process: existing suites re-run, the demand and book code read, and throwaway probes driven against `BookStream` with the recorded corpus and a fake clock. Items that need a running stack are under "Not probed".
- No credentials used; no network.

## Charter

Explore the book under adversarial subscription patterns (rapid depth changes, symbol thrash, duplicate subscribes) to discover leaks, orphaned subscriptions and desync.

## Oracles (defined before probing)

- O1 After any acquire and release sequence plus the grace period, the upstream topic set differs from the topics some consumer still holds (orphan or leak).
- O2 A duplicate acquire by one consumer double-counts, so one release leaves demand behind, or a release by one consumer drops another's demand.
- O3 A depth change publishes a mixed-tier or partial book.
- O4 A book whose frames are no longer applied is still served as live.

## Areas covered (in-process evidence)

| Probe                                           | Evidence                                                                                                                                                                                                      | Result                             |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| Refcount semantics                              | code read: `candleviewer/ingestion/planner.py` `DemandTracker` holds a set of consumers per topic, so a repeated acquire is idempotent and one release clears it                                              | O2 ok by construction              |
| One lease per WS key                            | code read: `candleviewer/ws_wiring.py` `IngestionUpstreamSink` takes one lease per `(symbol, family, params)` under `ws:<family>:<params>`                                                                    | ok; each depth is its own consumer |
| Atomic depth change                             | `services/api/tests/unit/book/` (tiers), `services/api/tests/unit/ingestion/test_book_stream.py`                                                                                                              | no mixed tier (O3 ok)              |
| Demand change on a live socket                  | `services/api/tests/chaos/ingestion/test_s01b_demand_change_while_live.py`, `services/api/tests/unit/ingestion/test_delist_topic_isolation.py` (#1915)                                                        | ok                                 |
| Sequence gap, resync backoff, out-of-live SLO   | `services/api/tests/chaos/ingestion/test_s03_book_sequence_gap.py`, `services/api/tests/unit/ingestion/test_book_resync_backoff.py`, `test_book_out_of_live.py`                                               | desync surfaced, never patched     |
| Release, grace runs out, the feed keeps flowing | probe `p2` (scratch), then the same through `GET /market/orderbook`; promoted as `services/api/tests/qa/test_e08_charter_findings.py::test_f2_a_released_book_is_never_served_frozen_as_live_after_its_grace` | **F2** (O1, O4)                    |

## Session metrics

- Time: about 10 minutes of agent time (09:42-09:45 UTC probe and code reading, re-run at 09:50), not a 90-minute human session.
- Tests re-run: book unit suites, book stream, resync backoff, out-of-live, the orderbook contract pack, chaos s01b and s03, delist isolation and the orderbook route: 98 passed, 1 deselected (`perf`), 9.4 s wall.
- Probes: 1 (with an HTTP variant). 1 promoted.

## Findings

**F2 — a released book whose grace runs out is frozen but still served as live, and its upstream topic stays subscribed (filed by the coordinator as #3807, P0, on 2026-10-19).** `BookStream` recomputes its upstream topics only inside `sync()`, which runs on an acquire, a release, a depth change or a completed tier swap; unlike `TickerStream` it has no periodic sync. After the last consumer releases a symbol and the 30 s grace passes with no other demand change, the topic stays in the desired set (O1, an orphaned upstream subscription) while `handle_frame` drops every frame for the symbol because it is no longer demanded. The book stays LIVE, and `GET /market/orderbook` for it answered 200 with the book of an hour earlier (`u` 100 while the feed was at 400) and `stale: false` (O4). The route's own acquire then revives demand, so the next delta exposes the sequence gap and the book resyncs: the stale answer is the first one after an idle period, and a new WS `book` subscription would snapshot the frozen book in the same way. Severity: P0 under the E08-Q01 rule for old data shown as current, without a signal. Reproduced on main `c21b2eb3`, in-process; the promoted test is a strict `xfail`. The trade stream has the same lazy grace (`TradeStream` drops frames for a symbol whose grace ran out), but its read surface is the stored tape, so no stale value is served from memory.

## Not probed (needs a running stack)

- Symbol thrash through the real WS gateway with several browser panes, and the gateway's 30 s grace stacked on the stream's (E17 scope; WS book deltas wait on #604).
- Memory growth of per-symbol state over hours of thrash: the soak harness (E08-Q04) covers steady state only; the 24 h profile has not run (#2825).

## Regression recommendation

Keep `test_f2_...` as a strict `xfail` until #3807 is fixed. With the fix, add a check that the desired topic set equals the held topics after the grace (O1), driven by the fake clock.
