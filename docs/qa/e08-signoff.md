# E08 QA sign-off evidence pack (R0 exit)

Ticket: E08-Q06 (#283) for epic E08 (#35, Bybit adapter and ingestion skeleton). Prepared 2026-10-19 by hcl-worker-2 (AI agent, run8 aa6271c0) on main `4b5e1b6c` plus this change, and updated after review round 1 on main `99564c65`. QA supplies the evidence and a **proposed** verdict (section 12); the verdict line is the owner's, and so is the R0 release decision (`docs/plan/07-release-and-prr.md`). Security is referenced here, not signed off (section 9).

Reference note: the ticket points at `docs/plan/30-release-roadmap.md` §5 for the R0 exit criteria; R0's are in §4.3 (§5 is R1). The E08-relevant R0 exit items are #5 (24 h ingestion of three or more symbols, memory flat within ±5 %), #6 (data readable from QuestDB and archivable to Parquet) and #10 (Grafana shows ingestion and a synthetic alert fires).

## 1. Summary

| Area                              | State on 2026-10-19                                                                         | Evidence                                                 |
| --------------------------------- | ------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| Scripted regression (E08 pack)    | green: 2091 passed, 8 strict `xfail`s, 0 failed                                             | section 2; `qa/plans/e08-regression-pack.md` section D   |
| Fixed P0/P1 defects with a case   | 24 of 24                                                                                    | `qa/plans/e08-regression-pack.md` section B              |
| Exploratory charters              | 6 of 6 debriefed in-process (deviation); 3 new P0 candidates, 1 P1 candidate                | section 3; `docs/qa/charters/E08-charter-*.md`           |
| Cross-epic handshake              | 28 checks green; D2 fixed in the doc, D1 needs a decision, gaps G1 and G2, ledger gap L1    | section 4; `services/api/tests/qa/test_e08_handshake.py` |
| Chaos (E08-Q03, #280)             | suite green in the pack; #280 is still open on GitHub                                       | section 5                                                |
| Performance (E08-Q04)             | budget #13 fails nightly; flatness failed today (fix #3799 not re-measured); no 24 h soak   | section 6                                                |
| Accessibility (E08-Q05, #282)     | not run: no E2E, axe or screen-reader result for any E08 screen                             | section 7                                                |
| Coverage (E08 modules, pack only) | 96.97 % lines, 91.60 % branches                                                             | section 8                                                |
| Security deliverables             | X01, X02, X03 closed with QA passes; X02 long fuzz in no CI lane; no security sign-off      | section 9                                                |
| Open defects                      | 2 open P1 bugs (#2523 E08, #2167 E12), 3 P0 and 1 P1 candidates not yet filed, P2/P3 listed | section 10                                               |
| **Proposed verdict**              | **FAIL today**; conditional pass once B1-B4 close, with B5-B10 as named conditions          | section 12                                               |

## 2. Scripted results

Command (from `services/api`): `uv run pytest -p no:randomly --no-cov -m e08_regression`. The marker covers the E08 suites by path (`services/api/tests/_e08_regression_pack.py`), and its guard (`services/api/tests/qa/test_e08_regression_pack.py`) holds the pack document and the path list together.

| Run                                                                                               | Result                                             | Time                           |
| ------------------------------------------------------------------------------------------------- | -------------------------------------------------- | ------------------------------ |
| 2026-10-19, `99564c65` + this change after review round 1, loopback-only namespace, Python 3.14.4 | 2091 passed, 8 xfailed, 0 failed, 29435 deselected | 174.6 s tests, 3 min 3 s wall  |
| 2026-10-19, `4b5e1b6c` + this change before review round 1, same namespace and Python             | 1981 passed, 8 xfailed, 0 failed, 29180 deselected | 186.0 s tests, 3 min 17 s wall |
| 2026-10-19, `c21b2eb3` + the first commit (before the handshake and findings files)               | 1952 passed, 5 xfailed, 0 failed, 28789 deselected | 120.3 s tests, 2 min 11 s wall |
| 2026-10-19, `c21b2eb3` + the first three commits, with coverage (section 8)                       | 1979 passed, 8 xfailed, 0 failed, 28846 deselected | 133.7 s tests, 2 min 23 s wall |

The eight strict `xfail`s are five open defects (#1896 twice, #1900, #1893, all P2) and the three charter findings F1-F3 (section 3). Python 3.14.4 is the author's interpreter; CI uses 3.12. Runs are author runs by an agent, not an independent QA run. The guard: 67 passed (about 1 min). About 3 minutes in all, so the pack fits a nightly budget without a split.

E08-Q01 cases: the stable subset that E08-Q02 automated runs in the pack; `services/api/tests/contract/bybit/test_contract_q01_mapping.py::test_every_owned_case_is_tested_or_deferred_with_a_ticket` keeps the plan and the pack in step. Deferred: C07, D02, E05, E07, E08, F02 to #1878 (WS gateway, data-coverage route). Not automated: A05-A07, C05, F05 and every client half, which E08-Q05 owns (#282, not run).

Scheduling (deviation): no CI job selects `-m e08_regression` on its own, the same position as the E09 pack (#2716, `post-ga`); a lane edits `.github/workflows` and needs the `security-review` label. The same tests run in CI's `py` lane on every Python change, and the pack paths' `perf` items run in `py-perf`. Their one `fuzz` item, the E08-X02 long session, runs in no lane (section 9); they hold no `harness` item.

## 3. Exploratory debrief

Six sessions, run in-process by an AI agent on 2026-10-19 (about 1.5 h of agent time in all, not six 90-minute human sessions; no staging, docker, browser or screen reader). Every finding is either reported for filing or recorded with a reason.

| Charter                                                            | Tests re-run          | Probes | Findings   |
| ------------------------------------------------------------------ | --------------------- | ------ | ---------- |
| `docs/qa/charters/E08-charter-1-catalogue-metadata-churn.md`       | 123 passed, 2 xfailed | 2      | F1         |
| `docs/qa/charters/E08-charter-2-book-adversarial-subscriptions.md` | 98 passed             | 1      | F2         |
| `docs/qa/charters/E08-charter-3-backfill-awkward-ranges.md`        | 182 passed            | 2      | F3         |
| `docs/qa/charters/E08-charter-4-staleness-honesty.md`              | 60 passed             | 1      | F4, O-1    |
| `docs/qa/charters/E08-charter-5-clock-and-timestamps.md`           | 73 passed             | 1      | none new   |
| `docs/qa/charters/E08-charter-6-tape-bursts.md`                    | 118 passed, 1 xfailed | 1      | F6-1, F6-2 |

| Id   | Finding                                                                                                         | Severity (E08-Q01 §0.1)                           | Disposition                                                                                   |
| ---- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| F1   | A catalogue tick-size change on a live book applies later deltas on a second price grid, silently               | P0 candidate                                      | reported for filing; strict `xfail` `services/api/tests/qa/test_e08_charter_findings.py` (F1) |
| F2   | A released book whose grace runs out keeps its upstream topic and is served frozen with `stale: false`          | P0 candidate                                      | reported for filing; strict `xfail` (F2)                                                      |
| F3   | A klines window read before its bars exist is cached as covered; later reads return no rows and no hole         | P0 candidate (P1 if the owner rates exposure low) | reported for filing, with the `security` label for triage (see below); strict `xfail` (F3)    |
| F4   | `GET /market/orderbook` hard-codes `stale: false`; a stalled book topic is served as live                       | P1 candidate                                      | reported; the WS half is #2487 (P1, open)                                                     |
| F6-1 | 24 §2.1 names `md_duplicate_trades_total` and `md_out_of_order_total`; neither exists, inversions pass silently | P3                                                | recorded (doc or counter, owner's choice)                                                     |
| F6-2 | A trade frame over the 2 000-print cap is dropped whole without a gap event                                     | open question                                     | recorded; P0 if the venue can push more than 2 000 prints in one frame                        |
| O-1  | Catalogue freshness has no dashboard panel and no alert                                                         | P3                                                | recorded for the E08-T06 owner                                                                |

F3 is also an input-validation gap. The window comes from the client on an authenticated route: `services/api/candleviewer/api/market.py` refuses only a `from` after `to` and a window over 400 days, and the coverage entry such a read leaves behind is shared by every reader of that symbol and interval in the process. Design requirement for the fix: the read path never records coverage past the present (clamp the backfill window to now; rejecting such a window would need a 22-api change, because the 400-day cap is the route's only window refusal). The triggers are ordinary client behaviour (a clock ahead of the exchange, a viewport past the last bar) and callers must be authenticated, so it is recommended for the same `security` triage the E08-X02 robustness defects #1893 and #1896 got, not for private handling.

The Grafana session the ticket asks for became a static review of `infra/grafana/dashboards/ingestion.json` and `infra/prometheus/alerts/` (charter 4); the screen-reader run of charter 4 did not happen (section 7).

## 4. Cross-epic handshake

`services/api/tests/qa/test_e08_handshake.py` (28 checks, about 2 s, in the pack). A downstream epic re-runs it at its start, with the five suites it relies on, by the command in its module docstring; those suites are in the pack too, and a check fails if the command stops naming one of them.

| Contract                             | Check                                                                                                                                                                                                                                                                                                                                                                          | Result                    |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------- |
| (a) Adapter ports, 24 §14.1          | every `MarketDataPort` and `TradingPort` method fully annotated, never `Any`; method set pinned by `services/api/tests/unit/exchange/test_market_data_port_spec.py`                                                                                                                                                                                                            | pass                      |
| (b) Event envelope, 24 §1.4          | `DomainEvent`/`MarketEvent` fields equal the doc's; the 8 market families and `InstrumentUpdatedEvent` are versioned, frozen and closed                                                                                                                                                                                                                                        | pass                      |
| (b) Control payloads, 24 §1.1 C6     | `BookStatus`, `GapEvent` and `FeedHealthEvent` travel the bus without the C6 envelope                                                                                                                                                                                                                                                                                          | **drift D1**, pinned      |
| (c) Bus topics, 24 §2.9 "As shipped" | E08 publishes exactly trade, book, ticker, gap, `health.feed` and `instruments.{symbol}.updated`; E12's trade subscription is one of them                                                                                                                                                                                                                                      | pass after **doc fix D2** |
| (c) WS families, 23 §6.1             | `book`, `trades`, `ticker` (and `bars`) lease E08's streams with the gateway's `acquire`/`release` signature; E08's tier 200 is an offered depth; the §6.1 table itself is pinned by `services/api/tests/contract/ws/test_ws_topic_registry_as_built.py`                                                                                                                       | pass                      |
| (d) REST, 22-api                     | `GET /instruments` and `GET /instruments/{symbol}` bodies from the recorded corpus validate against `Page`, `InstrumentsPageMeta`, `Instrument`, `InstrumentDetail`, key sets included; trades, order book, ticker and klines are pinned by `services/api/tests/contract/bybit/test_pipeline_read_surface.py` and `services/api/tests/contract/test_market_klines_contract.py` | pass                      |

- **D1 (decision needed, not blocking R0 by itself):** C6 says every bus event carries `schema_version`; three E08 control payloads do not. Either add the envelope (a code change in book and ingestion) or amend C6 to exempt in-process control signals. The check fails as soon as one of them gains a version, so the record cannot go stale.
- **D2 (corrected here):** 24 §2.9 did not list `{env}.instruments.{symbol}.updated`, which the catalogue refresh has published since #1633. The check was red on main; this change adds the topic to the paragraph.
- **G1 (gap, tracked):** `POST /instruments/refresh` is declared in 22-api but not mounted (`services/api/tests/contract/rbac/matrix.yaml`, `not_mounted`); E08-TC-A05, A08 and A10 drive the scheduler directly.
- **G2 (gap for E17):** the gateway snaps `book` but sends no book deltas until #604, and has neither a snapshot source nor a publisher for `trades` and `ticker`; 23 §7.7 names no ticket for those two families. A downstream epic starting today gets no WS market data for them.
- **L1 (ledger gap, recorded, not filed):** the statechart gate's invariant ledgers still mark INV-B13-e (pong deadlines are absolute and re-armed on restore), INV-B14-a and INV-B14-b `deferred:E08` (`services/api/tests/xstate_contract/test_b13_ws_conn.py`, `services/api/tests/xstate_contract/test_b14_book.py`). The ledger rule (`services/api/tests/xstate_contract/membership.py`) defers an invariant only while its binding bodies are stubs, and E08's have shipped; `services/api/tests/xstate_contract/test_b14_book_health.py` already asserts INV-B14-a. The other two were not traced to a test in this session. P3, for the coordinator: map the three rows to tests, or add the tests.
- Known contract defects in E08 scope: #2863 (10016 mapping vs 24 §8.6, P3) and #3033 (book `ts_ingest`, P2).

## 5. Chaos (E08-Q03, #280)

The eleven scenarios (`services/api/tests/chaos/ingestion/`, s01 to s11 plus s01b, the visible-degradation pair and the rig guards) run in the pack in-process without docker and passed in every run of section 2. The [independent QA re-run of 2026-10-15](https://github.com/basiltt/CandleViewer/issues/280#issuecomment-6203304093) recorded 50 passed in 20 of 20 runs (3 fixed order, 17 shuffled) on main `16071506`, the four mutation records of #1976 (PR #2582) and rig parity through `IngestionService.start()` (#2583); its board status was set to Done that day, but **#280 is still open on GitHub**. Its nightly lane stays owner-waived (#1778 item P) and is not added here either (section 2).

## 6. Performance (E08-Q04) against budgets #5, #6, #8, #11, #12, #13

Source: `perf-ingestion-nightly` run 39228783180 (2026-10-19, `ff575f02`, artifact `ingestion-soak-results`, report `e08-smoke-20261019T091848Z.md`, Grafana range `from=1792401528786&to=1792401551180`) and run 39110945071 (2026-10-18, `ab01fb35`). Smoke profile on `ubuntu-latest`: a scaled virtual-clock soak, a synthetic feed and an in-process HTTP driver standing in for k6. Neither the 24 h soak nor k6 has run anywhere (#2825, no bench runner), so R0 exit #5 is not demonstrated.

| Budget                       | Measured 2026-10-19 (2026-10-18)                                                       | Limit       | Result                              |
| ---------------------------- | -------------------------------------------------------------------------------------- | ----------- | ----------------------------------- |
| #5 zero loss                 | undetected loss 0 in soak, aggregate and burst; canary 270 000 published = delivered   | 0           | pass (smoke scale only)             |
| #5 bounded queue, recovery   | burst backlog 200, recovery 3.3 s (200, 3.3 s)                                         | 400, 30 s   | pass                                |
| ±5 % memory flatness (R0 #5) | 5.60 % (2.23 %)                                                                        | 5 %         | **fail today**; see below           |
| #6 fan-out add-on            | E08 slice receipt to publish p95 0.127 ms (0.204 ms); E17's fan-out slice not measured | 20 ms       | pass with caveat (half of the span) |
| #8 RSS per symbol            | p95 64.2 MB (63.27 MB), whole process divided by 3, mostly import footprint (#3431)    | 300 MB      | pass                                |
| #11 vCPU per symbol          | p95 0.0127 (0.0167)                                                                    | 0.5         | pass                                |
| #12 storage growth           | 0.114 GB/day modelled from bytes per row, not measured on disk                         | 0.75 GB/day | pass with caveat (model only)       |
| #13 REST p95                 | klines cold 336.4 ms (423.9), page boundary 258 ms (349.7); others 0.8-14.8 ms         | 150 ms      | **fail**; #2523 (P1, open)          |

#3431 (this flatness failure and the import-heavy RSS figure) was closed at 10:59 UTC on 2026-10-19 by PR #3799, a bench-harness fix: budget #8 now counts what the lanes add, and memory flatness takes its base sample after the start-up warm-up. No `perf-ingestion-nightly` run has happened since, so neither figure is re-measured here.

## 7. Accessibility (E08-Q05, #282)

Not run. There is no `apps/web/e2e/market-data/` suite, no axe-core result for SCR-100 to SCR-104 or SCR-152, and no NVDA or VoiceOver report; the hi-fi and handoff tickets the screens depend on are open (E08-D05 to E08-D14: #126, #174 to #181, #277). **No a11y verdict exists**, and an epic with UI surface cannot be Done without one (`docs/plan/02-definition-of-ready-done.md` §2.2).

## 8. Coverage

Measured from the pack alone (`-m e08_regression` with coverage, 2026-10-19, `c21b2eb3` + the first three commits): the floor is 85 % lines and 75 % branches.

| E08 module                         | Lines                   | Branches                |
| ---------------------------------- | ----------------------- | ----------------------- |
| `candleviewer/exchange/base/`      | 99.84 % (626/627)       | 96.25 % (77/80)         |
| `candleviewer/exchange/bybit/`     | 96.25 % (1542/1602)     | 92.79 % (399/430)       |
| `candleviewer/exchange/policy.py`  | 98.39 % (61/62)         | 100 % (14/14)           |
| `candleviewer/ingestion/`          | 96.73 % (2571/2658)     | 90.39 % (602/666)       |
| `candleviewer/book/`               | 98.29 % (345/351)       | 93.48 % (86/92)         |
| `candleviewer/bus/`                | 97.03 % (229/236)       | 89.58 % (43/48)         |
| `candleviewer/orderbook_wiring.py` | 94.97 % (283/298)       | 88.37 % (76/86)         |
| **E08 total**                      | **96.97 % (5657/5834)** | **91.60 % (1297/1416)** |

The whole `services/api` package is held to the floor on every PR by CI (C-9.4); the last whole-package figure in the E08 QA records is 96.6 % at PR #2228's head (#281 QA record). It was not re-measured here.

## 9. Security deliverables (referenced, not signed off)

- **E08-X01** STRIDE (#187): closed 2026-09-28, [QA pass recorded 2026-09-29](https://github.com/basiltt/CandleViewer/issues/187#issuecomment-5881005142); that record marks the security-engineer sign-off as deferred, and no "Security sign-off" comment exists on #187 or #35.
- **E08-X02** abuse cases (#290): closed 2026-10-06 with a QA pass; the suite (`services/api/tests/security/ingestion/`) runs in the pack, apart from its long parser-fuzz session (`fuzz` marker, opt-in `CV_FUZZ_LONG=1`), which no CI lane runs: `fuzz-nightly` (for example run 39228860502, 2026-10-19, green) fuzzes only the WS binary-frame decoders, and #3523 recorded the gap (item 5) before it was closed as not planned. Author run of the long session on 2026-10-19 (`066c4449`, Python 3.14.4, 20 000 examples per parser, 243 s): ticker and trade passed; the book leg failed on the non-finite timestamp case of open #1900, which the pack already pins with a checked-in regression frame, so no new failure class. Residuals: #1893, #1896, #1900 (P2, strict `xfail`s), and #1895 (P2), which the findings register records as fixed by #2339 but is still open.
- **E08-X03** SAST, SCA, secrets and the vocabulary-leak gate (#226): closed 2026-09-29 with a QA pass. Not re-run for this pack; `sast`, `sca` and `secrets-scan` are required checks on every PR (C-9.1). Accepted risks in E08 scope: the three `cv-adapter-isolation` rows for the applied migration `services/api/candleviewer/migrations/versions/0004_instruments.py` in `security/accepted-risks.yaml` (owner security, expiring 2026-12-31, #1778). This change adds one in-source suppression of the same rule, for the contract pack's directory name in `services/api/tests/_e08_regression_pack.py` (class B5-b-harness, review 2026-12-31; the class goes from 42 to 43 markers).
- The epic DoD line "sign-off comment from Security engineer" is **not met**.

## 10. Open defects in E08 scope (GitHub, 2026-10-19)

| Issue                  | Sev      | Summary                                                                 | Disposition                                                             |
| ---------------------- | -------- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| F1, F2, F3 (not filed) | P0 cand. | section 3                                                               | **blocking**; coordinator to file                                       |
| F4 (not filed)         | P1 cand. | REST order book never `stale` (WS half #2487)                           | **blocking** unless the owner rates it lower                            |
| #2523                  | P1       | cold klines p95 above the 150 ms budget #13                             | **blocking** (budget #13 is hard)                                       |
| #2167                  | P1       | bar builders rebuild 1M prints in 28-39 s (E12 scope, `area/ingestion`) | not E08's verdict; E12                                                  |
| #3431                  | none     | perf pack regression, memory flatness                                   | closed by #3799 (harness fix), not re-measured yet                      |
| #1893, #1896, #1900    | P2       | X02 residuals (pump yield, malformed catalogue row, `ts` Infinity)      | fix before release or owner acceptance (`03-testing-strategy.md` §11.3) |
| #1895                  | P2       | signer repr                                                             | fixed by #2339; close-candidate                                         |
| #1933, #3033, #2844    | P2       | funding-interval default, book `ts_ingest`, a wall-clock test flake     | fix before release or owner acceptance                                  |
| #2703                  | P3       | 503 not declared on `/instruments`                                      | fixed by #2772; close-candidate                                         |
| L1 (not filed)         | P3       | three statechart invariants still `deferred:E08` (section 4)            | recorded for the coordinator                                            |
| #2863, #3287           | P3       | 10016 mapping; `/market/bars` read timeout (`post-ga`)                  | backlog                                                                 |
| #1862, #1899           | none     | crossed corpus fixture; order-dependent contract test                   | needs triage (no priority)                                              |

Open E08 children besides bugs: #280 (open, board Done), #282, #283, the design tickets E08-D05 to E08-D14, #2825 (`needs-owner`) and the follow-up tasks #1849, #1872, #1878, #1879, #1949, #1958 to #1960, #1966, #1967, #1974, #1977. The epic DoD's 100 % child rollup is not met.

## 11. Not tested

- Anything in a browser or with assistive technology (E08-Q05, #282); the Grafana session with real faults; any staging or docker run; the QuestDB and Parquet round trips (CI `integration`; R0 exit #6 not assessed here); a synthetic alert firing end to end (R0 exit #10, E04 drill).
- The 24 h soak, the full perf profile and k6 (#2825).
- The E08-X02 long fuzz session in any CI lane (one author run, section 9); the statechart invariants INV-B13-e and INV-B14-b (L1).
- Live-venue behaviour: maximum trade-frame size (F6-2), real tick-size changes (F1), real host sleep.

## 12. Proposed verdict and conditions

**Proposed: FAIL as of 2026-10-19.** The scripted pack is green and every fixed P0/P1 defect has a case, but three P0 candidates are open, a hard budget fails nightly and the a11y verdict does not exist. An unconditional pass would itself be a process defect (ticket AC). Once B1-B4 close, re-run the pack and propose a **conditional pass** with B5-B10 as named conditions.

| Id  | Condition                                                                           | Ticket                         |
| --- | ----------------------------------------------------------------------------------- | ------------------------------ |
| B1  | F1 fixed, or re-rated by the owner with a recorded reason                           | to be filed by the coordinator |
| B2  | F2 fixed, or re-rated                                                               | to be filed                    |
| B3  | F3 fixed (no coverage recorded past the present), or re-rated                       | to be filed                    |
| B4  | F4 fixed or folded into #2487 with the REST flag in scope                           | #2487 or a new issue           |
| B5  | budget #13 met, or an owner-accepted exception                                      | #2523                          |
| B6  | the 24 h soak run once with memory flat within ±5 % (R0 exit #5)                    | #2825                          |
| B7  | E08-Q05 run: axe green on the E08 screens and one screen-reader pass                | #282                           |
| B8  | security-engineer sign-off comment on #35 (STRIDE finalised, X02 residuals triaged) | #187, #290                     |
| B9  | drift D1 decided (envelope added, or C6 amended)                                    | to be filed                    |
| B10 | #280 closed on GitHub to match its board status                                     | #280                           |

## 13. Proposed QA comment for #35 (for the owner to post or amend)

> QA verdict for E08 (proposed by E08-Q06, #283): **fail** as of 2026-10-19. Evidence: `docs/qa/e08-signoff.md`. The E08 regression pack (`-m e08_regression`) is green apart from eight strict xfails pinning open defects and new findings, and all 24 P0/P1 defects fixed in the epic map to a regression case. Exploratory charters found three P0 candidates (F1 tick-size change on a live book, F2 a frozen book served as live after its grace, F3 a klines window cached as covered before its bars exist, also recommended for security triage) and one P1 candidate (F4 order book `stale` never set). Budget #13 fails nightly (#2523), the 24 h soak has not run (#2825), E08-Q05 has not run (#282), and no security-engineer sign-off is recorded. The verdict becomes a conditional pass when B1-B4 close, with B5-B10 tracked as named conditions.
