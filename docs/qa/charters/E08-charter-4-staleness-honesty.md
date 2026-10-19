# E08-C4 Charter: staleness and reconnection honesty across every surface

- Ticket: E08-Q06 (#283) · Format: session-based test management · Date: 2026-10-19
- Tester: AI agent (hcl-worker-2, run8 aa6271c0). **Deviation (honest scope):** the ticket asks for this charter to run once with a screen reader attached and for one session against the Grafana "Ingestion" dashboard. Neither was possible: there is no running stack, no browser, no screen reader, and the E08 screens (SCR-100 to SCR-104, SCR-152) have no E2E or a11y run yet (E08-Q05, #282). The session was in-process over the backend read surfaces (REST bodies, `/readyz`, the bus feed-health signal), plus a static review of `infra/grafana/dashboards/ingestion.json` and `infra/prometheus/alerts/` against the faults the chaos suite injects. "Looks stale" and "announces stale" were not observed by anyone.
- No credentials used; no network.

## Charter

Explore staleness and reconnection honesty across every panel to discover any surface that shows old data as current.

## Oracles (defined before probing)

- O1 A read surface that returns a value while its feed is past the staleness threshold without a staleness marker (E08-Q01 C06: values changing with no stale or reconnecting signal is P0).
- O2 A marker that does not clear after recovery.
- O3 An order book served while DESYNCED.
- O4 A fault injected by the chaos suite that an operator cannot see on the Ingestion dashboard or an alert.

## Areas covered (in-process evidence)

| Surface                                    | Evidence                                                                                                                                                                                                                                                                               | Result                                             |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| `GET /instruments/{symbol}/ticker` `stale` | `services/api/tests/contract/bybit/test_contract_streams_extra.py::test_c06_stale_flag_and_staleness_gauge_during_a_drop_then_reset`                                                                                                                                                   | set on drop, cleared by the next frame (O1, O2 ok) |
| `GET /market/orderbook` while resyncing    | `services/api/tests/contract/bybit/test_pipeline_read_surface.py::test_book_gap_serves_503_while_resyncing_never_a_patched_book`                                                                                                                                                       | 503, never a patched book (O3 ok)                  |
| `GET /market/orderbook` `stale`            | code read: `candleviewer/orderbook_wiring.py` `view()` builds `BookView(snapshot, stale=False)` in every case                                                                                                                                                                          | **F4** (O1)                                        |
| Frozen book after a released grace         | charter 2 finding F2: an hour-old book answered with `stale: false`                                                                                                                                                                                                                    | **F2** (O1)                                        |
| `GET /instruments` `stale_since`           | `services/api/tests/unit/api/test_instruments_router.py`                                                                                                                                                                                                                               | ok                                                 |
| `/readyz` reasons and recovery             | `services/api/tests/unit/ingestion/test_service_health_degraded.py`, `test_ingestion_readyz.py`; chaos `test_visible_degradation.py`                                                                                                                                                   | degraded with reasons, back to ok (O2 ok)          |
| Per-topic stall signal                     | chaos `test_s02_ws_silent_stall.py`: the bus `stale` event fires within 2 s                                                                                                                                                                                                            | ok on the bus                                      |
| Scope of book invalidation                 | probe `p4`: a `resubscribing` event for an unrelated topic invalidates every book; code read shows that event is only emitted socket-wide, where every snapshot is re-sent                                                                                                             | no finding (probe assumption did not hold)         |
| Dashboard and alerts vs injected faults    | static review: panels for socket up, books LIVE, clock drift, staleness, queue depth, never-drop queue full, write-behind depth, resyncs, unrecovered gaps, rate-limit headroom, REST p95; alerts for staleness, resync rate, rejected frames, gaps, headroom, queue full, clock drift | **O-1** (O4)                                       |

## Session metrics

- Time: about 15 minutes of agent time (suites re-run at 09:50 UTC, probe, dashboard and alert review 09:55-10:05), not a 90-minute human session.
- Tests re-run: ticker and feed-rot contract packs, health and `/readyz`, feed-health end to end, ticker stream, chaos s02 and visible degradation, the pipeline read surface: 60 passed, 3.7 s wall.
- Probes: 1 (`p4`), plus the charter 2 reproduction. None promoted from this session (F2 is promoted under charter 2).

## Findings

**F4 — `GET /market/orderbook` never reports `stale` (reported to the coordinator; related to #2487).** `BookView` is always built with `stale=False`. When a book topic goes silent, the watchdog publishes `stale` for it on the bus within 2 s (chaos s02), but the book stays LIVE until a snapshot or a socket recycle, so the REST bootstrap of the DOM serves the last book with `stale: false` for the whole stall; the socket recycles only once every watched topic is stale. #2487 (P1, open) tracks the WS half (`meta.stale` from the book adapter, upstream-feed cause "has no producer yet", 23-ws-protocol section 7.7); the REST flag has no tracker. Severity: P1 as #2487 rates the same hazard; not P0 because the bus carries an honest signal, though no client consumes it yet.

**O-1 — an operator cannot see catalogue freshness on the dashboard or in an alert (recorded, P3, not filed).** `instruments_cache_age_seconds` and `instruments_refresh_total` appear in no panel and no rule, so a failing catalogue refresh (the `catalogue_stale` health reason, #2715) shows only in `/readyz`. Frame rejections, clock re-measures and write-behind drops have no panel either, but each has an alert or a health reason. Recommendation for the E08-T06 owner: one catalogue-age panel with a TTL threshold line.

## Not probed (needs a human, a browser, a screen reader or staging)

- Watchlist stale shading, the SCR-152 reconnect overlay and their `aria-live` announcements under NVDA or VoiceOver: E08-Q05 (#282, not run); the screens wait on design tickets E08-D05 to E08-D13 (#126, #174 to #181).
- A real Grafana session with injected faults on staging: no environment; the dashboard JSON was reviewed statically only.
- WS `book`, `trades` and `ticker` frames: the gateway snaps `book` but sends no book deltas until #604, and has no snapshot source or publisher for `trades` and `ticker` yet (`candleviewer/ws_wiring.py`).

## Regression recommendation

When F4 is fixed, add a REST case to the pack: stall the book topic on a fake clock past 2 s and assert `stale: true`, then recovery clears it. Keep F2's promoted test under charter 2.
