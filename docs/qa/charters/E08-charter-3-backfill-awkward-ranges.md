# E08-C3 Charter: backfill and coverage with awkward ranges

- Ticket: E08-Q06 (#283) · Format: session-based test management · Date: 2026-10-19
- Tester: AI agent (hcl-worker-2). **Deviation (honest scope):** no staging build, no QuestDB, no docker stack and no 90-minute human time box. The session was in-process: the kline backfill, coverage and read suites re-run, the read path read, and throwaway probes driven against `KlineBackfillService` and `KlineReadService` with an in-memory hot tier and a fake venue that only serves bars it has formed.
- No credentials used; no network.

## Charter

Explore backfill and coverage with awkward ranges (future dates, pre-listing dates, exactly-page-sized windows, overlapping requests) to discover cache and coverage defects.

## Oracles (defined before probing)

- O1 A duplicate or missing bar at a page boundary, or a phantom page after an exactly page-sized window.
- O2 A window recorded as covered although its bars could not have been fetched, so a later read serves a hole with no `coverage_holes` signal (silent gap, P0 under the E08-Q01 rule).
- O3 Overlapping concurrent requests that fetch the same span twice or store a bar twice.
- O4 Unbounded upstream calls for a pre-listing window.

## Areas covered (in-process evidence)

| Probe                                        | Evidence                                                                                                                                                                                  | Result                                  |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| Page boundaries, exact multiples, splits     | `services/api/tests/contract/bybit/test_contract_kline.py` (8 cases incl. #1861), `services/api/tests/unit/exchange/bybit/test_pagination.py`                                             | ok (O1 ok)                              |
| Exactly one page of 1000 bars                | probe `p3`: 1 upstream call, 1000 rows, window covered                                                                                                                                    | ok, no phantom page                     |
| Overlapping windows, concurrently            | probe `p3`: two calls, the second fetched only the 300 bars outside the overlap; 900 rows stored                                                                                          | ok (O3 ok)                              |
| Pre-listing window, read twice               | probe `p3`: one call, then served from coverage                                                                                                                                           | ok (O4 ok); no bar can ever exist there |
| Window ending after the venue's newest bar   | probe `p3`: the forming bar is returned and coverage stops before it                                                                                                                      | ok                                      |
| Window starting after the venue's newest bar | probes `p3`, `p3b` through `KlineReadService.read`; promoted as `services/api/tests/qa/test_e08_charter_findings.py::test_f3_a_window_read_before_its_bars_exist_is_fetched_once_they_do` | **F3** (O2)                             |
| Probe error, not a finding                   | a first probe served pages newest-first and `_backfill_hole` raised `ValueError`; the `KlineFetcher` port promises ascending order and the adapter honours it                             | recorded, no defect                     |

## Session metrics

- Time: about 3 minutes of agent time, 09:44-09:47 UTC (probes `p3` and `p3b`, code reading), plus this charter's share of the one suite re-run for all six charters at 09:50 and the debrief, written at 09:57; not a 90-minute human session. Times are from the agent's tool-call log.
- Tests re-run: kline backfill (E08 and E12 suites), coverage, read path, the kline contract pack, pagination, klines adapter, the klines route and its OpenAPI contract: 182 passed, 1 deselected (`perf`), 6.1 s wall.
- Probes: 2 (seven range shapes, then the read path). 1 promoted.

## Findings

**F3 — a klines window that starts after the venue's newest bar is cached as covered, so its bars are never fetched later and no hole is reported (filed by the coordinator as #3808, P0, on 2026-10-19).** `GET /market/klines` accepts `from`/`to` in the future (only `from <= to` and the window size are checked) and `KlineReadService.read` does not clamp the backfill window to the present. The venue answers such a window with an empty, short page, and `_backfill_hole` treats a short page as proof that the whole window holds no bars, so the in-memory coverage index marks it covered. Once time passes and the venue has those bars, every read of the window returns no rows, `holes` is empty and `backfilling` is false; nothing fetches them until the process restarts or the key is evicted. A client clock ahead of the exchange, or a viewport requested past the last bar, is enough. Severity: P0 under the E08-Q01 rule for missing data with no gap marker (P1 if the owner rates the exposure low); tape-built bars mask it for recorded symbols. Reproduced on main `c21b2eb3`, in-process; the promoted test is a strict `xfail`.

F3 is also an input-validation gap (security review, round 1). The window comes from the client on an authenticated route, `services/api/candleviewer/api/market.py` refuses only a `from` after `to` and a window over 400 days, and the coverage index is shared by every reader of the symbol and interval in the process. Design requirement for the fix: the read path never records coverage past the present (clamp the backfill window to now; rejecting the window instead would need a 22-api change, because the 400-day cap is the route's only window refusal). The coordinator filed it publicly as #3808, which had no `security` label at the round-2 query; the round-1 suggestion of the same security triage the E08-X02 robustness defects #1893 and #1896 got stays an open note for the coordinator.

## Not probed (needs QuestDB, staging or the coverage route owner)

- The same ranges against the real QuestDB hot tier and the Parquet cold tier (CI `integration` lane only).
- `GET /market/data-coverage` (E16-T04) for these ranges, and the E08-TC-F02 tail-only reload: deferred to #1878.
- Rate-limit (10018) storms in the middle of a long backfill: covered by `services/api/tests/chaos/ingestion/test_s05_rate_limit_10018.py`, not re-probed here.

## Regression recommendation

Keep `test_f3_...` as a strict `xfail` until #3808 is fixed.

**Deviation: two passing probe shapes not promoted.** Probe `p3`'s exactly-one-page and overlapping-concurrent windows checked oracles O1 and O3 and passed. They were not promoted: they found no defect, and their home, the E08 backfill suite (`services/api/tests/unit/ingestion/test_kline_backfill.py`), is the code the in-progress fix for #3808 changes, so this change leaves that suite to it. The page arithmetic is pinned already by `services/api/tests/contract/bybit/test_contract_kline.py::test_exact_multiple_of_limit_terminates_without_a_phantom_row`. Recommendation: the #3808 fix, or the next change to that suite, adds both shapes as plain tests.
