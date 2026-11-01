# E12-X02 — Abuse-case catalogue: the bars and klines REST routes, the `bars.*` topic and the bar pipeline

- Ticket: E12-X02 (#452). Threat source: `docs/security/threat-models/E12-bars.md` (E12-X01), its §3
  bounds, §4 rows (BR-01 to BR-41), §7 requirements (SR-E12-01 to SR-E12-16) and §9 seeds (AC-01 to
  AC-14). Rulings of record: the BQ list and the orchestrator's rulings on #452 (6554826610).
- Path: the ticket's DoD names `docs/plan/security/abuse-cases/e12-bars.md`; that directory does not
  exist (the stale E12 paths #2794 records), so the report sits beside its siblings, as ruled (BQ-2).
- Method: white-box, in process. The REST cases drive E12-Q04's fixture-backed market app
  (`services/api/tests/contract/_market_world.py`: `GET /market/klines` and `GET /market/bars` as
  `create_app` composes them, error redaction included) through a `TestClient` or `httpx.ASGITransport`
  (no socket), with a spy on each of its four storage calls, so every refusal asserts its exact call
  set. The WS cases run on the E17-Q01 conformance gateway and the real `/ws` router. The upstream cases
  feed recorded frames through E08-X02's `Rig` (`tests/security/ingestion/_harness.py`) into the
  production `TradeStream`, a real `Bus` and a real `BarBuilderSet`. Recorded, redacted BTCUSDT data
  only (C-13.5); no network, no staging host, no live account, no real key.
- Test paths are under `services/api/tests/security/bars/` unless a row names another; `perf` and
  `fuzz` cases run outside the PR lane (below).
- Lanes: the PR `py` lanes run everything but `perf` and `fuzz`. `py-perf` runs the rejection-cost and
  the abuse-beside-ingestion legs. `fuzz-nightly.yml` runs the 5 000-query property in a step of its
  own (#452 PR-2); it is derandomised, so a red night replays from the commit, and the step prints no
  failing query. Deviation from BQ-8: the nightly makes 5 000 draws across both routes, not 5 000 per
  route; recorded, not resized. The 10-minute k6 battery (`tests/load/k6/bars_abuse.js`) is MANUAL: no workflow runs
  it; its CI run is carried to #528 (E12-Q05). It has no rebuild-flap and no ingestion-loss
  scenario: both are carried to #528 too (they run in process here, `test_exhaustion.py` and
  `test_exhaustion_perf.py`).
- Each defence is shown to fail when removed: `test_negative_controls.py` (caps, authz, deadline,
  revocation, 2 MiB ceiling) and the `*_control_*` cases of `test_integrity.py` and `test_exhaustion.py`
  (event window, checksum check, single-flight, per-user spec cap), each red for its named reason
  (`match=`).
- Verdict key: DEFENDED (the refusal holds as documented) · DEFENDED, leg NOT RUN (the NOT RUN table
  says why) · FINDING (a strict xfail pinned against the findings register below) · NOT RUN.
- Result: no executed case produced a 500, a stack trace, SQL or a path in a body, an unbounded read, a
  hostile print in a bar, a tampered row served, or a frame after revocation. Open: F3, F4b, F8, F9, and F2's bars half (#3287).

## Cases (the model's §9 seeds)

<!-- prettier-ignore -->
| Seed | Rows | Tests | Observed | Verdict |
| --- | --- | --- | --- | --- |
| AC-01 `from=0&limit=5000`, every bar type | BR-28 | `test_caps_and_cost.py::test_caps_boundary_holds_and_refuses_before_the_read` (time window, time estimate, non-time window, non-time estimate), `::test_caps_klines_window_over_400_days_refused_before_the_hot_read`, `::test_caps_pre_epoch_window_is_measured_from_its_from`; the oracle's span and estimate caps on every 200 (`test_param_fuzz.py`) | Each cap serves its boundary and refuses 1 µs past it, 422 `bar_window_too_large`, after the recording-start read only (plus the print count for the estimate); klines makes no call. The pre-epoch window is measured from `from` since #5348 (F1) | DEFENDED |
| AC-02 `tick:1`, `range:1`, `volume:1`, `renko:1`, 18 digits | BR-29 | `test_caps_and_cost.py::test_caps_param_bound_is_enforced_at_its_edge_on_rest` (21 edges), `::test_caps_param_bound_is_enforced_on_the_ws_subscribe_path`, `check_tick_1_refused_before_any_read`, `::test_caps_tick_1_refusal_costs_under_the_cpu_budget` (`perf`); `::test_caps_qty_floor_is_ten_qty_steps` | Every floor and ceiling refused 400 `validation_failed` (WS `invalid_topic_format`) with no storage call; `tick:1` over 30 d costs no read and under the 2 ms bound. The `volume`/`delta` floor applied is 1, not 10 qty steps (F8) | DEFENDED; FINDING F8 |
| AC-03 `param` fuzz | BR-25, BR-40 | `test_param_fuzz.py`: the dictionary (about 620 probes over both routes and every parameter), the derandomised property (300), the nightly property (5 000, `fuzz`); `::test_param_fuzz_last_microsecond_of_9999_is_served_for_time_bars` | Every answer a declared status with a catalogued code; no traceback, path, SQL, table name or echo over 32 characters; every 200 within the caps and 2 MiB. `to=9999-12-31T23:59:59.999999Z` was a 500 until #5348 (F7). Non-RFC 3339 instants are served (F6, accepted) | DEFENDED |
| AC-04 ninth spec per user, 33rd per symbol, churn | BR-30 | `test_exhaustion.py::test_exhaustion_ninth_bars_series_of_one_user_is_refused_and_holds_nothing` (both subprotocols); `tests/unit/bars/test_builder_set.py`, `test_builder_set_security.py` (per symbol, global, race, metric); churn: `tests/contract/ws/test_ws_rebuild_budget.py::test_ac30_a_ctl_loop_and_a_50_topic_churn_for_60_s_stay_within_the_budget` | The ninth series is `subscription_limit`, with no series hold and no lease; eight stay | DEFENDED |
| AC-05 rebuild storm; disconnect; foreign cancel | BR-31, BR-04 | `test_exhaustion.py::test_exhaustion_rebuild_flap_schedules_one_rebuild_per_series`; `tests/unit/bars/test_bars_persistence.py::test_rebuild_registry_*`; `tests/contract/ws/test_ws_rebuild_budget.py`; `test_rebuild_blocked.py` | 50 concurrent requests flapping 2 specs and 25 windows over stale rows: all served, one rebuild per series. The ADR-0033 Decision 2 legs are unbuilt | DEFENDED, leg NOT RUN |
| AC-06 slow `bars.*` consumer; 17th subscription; `history=1001` | BR-32, BR-38 | X01 assigns it to E12-Q05/Q06; cited: `tests/unit/ws/test_bars_share.py`, `tests/security/ws/test_flood_isolation.py`, `tests/unit/ws/test_subscriptions.py::test_the_17th_bars_topic_of_one_frame_is_refused_and_an_unsub_frees_a_slot`, `tests/unit/ws/test_topics.py` (`history` 1001) | Not rerun here | DEFENDED (cited), leg NOT RUN |
| AC-07 hostile kline page | BR-02 | Cited: `tests/unit/exchange/bybit/test_klines.py` (`oversized` before any row is parsed, `non_monotonic`, `high_below_body`, `negative_volume`, `gap`), `tests/unit/ingestion/test_kline_backfill_e12.py` (a rejected page stops the job, prior pages kept) | A page over the requested size is refused before a row is parsed, so a 100 000-row page allocates no events | DEFENDED |
| AC-08 stale rebuild over a newer generation; mutated builder | BR-09 | `test_rebuild_blocked.py` | Decision 2 is not built (#535) | NOT RUN |
| AC-09 hand-edited row; truncated, oversized, wrong-spec blob | BR-08, BR-12 | `test_integrity.py::test_integrity_hand_edited_row_is_withheld_never_served` (+ control); `::test_integrity_withheld_bar_is_named_to_the_client`; blobs: `tests/unit/bars/test_builder_set_persistence.py` (`too_large`, `truncated`, `wrong_series`) | The edited row is withheld, the rest of the page served unchanged, one `bars_checksum_mismatch_total{bars_time,mismatch}`. The 200 says nothing of the withheld bar (F9) | DEFENDED; FINDING F9 |
| AC-10 hostile and duplicate prints at the builder input | BR-06, BR-11 | `test_integrity.py::test_integrity_hostile_prints_between_recorded_ones_change_no_bar` (+ control); `tests/unit/bars/test_volume_print_cap.py` (10^6 bricks); late and out-of-order prints: `tests/unit/bars/test_activity_builders.py`, `test_time_builder.py` | Eight hostile kinds (negative and zero size, NaN and 1e308 price, string and year-3000 time, a 2099 print with a forged envelope, a list for the symbol) and a replayed print after every 40th recorded one: each frame counted once in `trade_prints_rejected_total`, each replay suppressed, every bar of three specs equal to the clean run's | DEFENDED |
| AC-11 no `marketdata:read`, REST and WS; `rebuild_id` IDOR | BR-21, BR-23 | `test_authz_and_revocation.py` (401, 403, no storage call; WS revocation); Q04's WS refusal; `test_rebuild_blocked.py` | Refused with no storage call; the IDOR leg needs `rebuild_id` (#535) | DEFENDED, leg NOT RUN |
| AC-12 production probe and debug surface | BR-26 | `test_prod_surface.py` (backend route table); the bundle half is E12-X03's `cv-no-debug-probe-in-prod` | No probe, debug or test-clock route in the production app | DEFENDED |
| AC-13, AC-14 store outage, feed gap, backfill under 10018 | BR-33 to BR-35 | E12-Q06 (#529) | Not X02's | NOT RUN |

## The ticket's scenarios and deliverables

<!-- prettier-ignore -->
| #452 scenario or deliverable | Where it is executed | Verdict |
| --- | --- | --- |
| No input produces a 500 or a stack trace | AC-03 (several thousand crafted requests a night: 5 000 draws across both routes, not per route; about 900 per PR run) | DEFENDED |
| An expensive request is refused, not served slowly | `tick:1` over 30 d: 400 before any storage call; the added CPU over an unauthenticated refusal under the BQ-5 bound (below) | DEFENDED |
| Abuse must not touch ingestion; a well-behaved p95 within budget #13 | `test_exhaustion_perf.py` (`perf`): 4 sessions looping maximal pages over stale rows beside the `Rig` feeding the tape into a `BarBuilderSet`: bars equal to the run alone, the four loss counters unmoved, one rebuild per series; the polite session's p95 67 ms (median 15 ms, 126 abusive pages) on a loaded 8-core box. The 10-minute k6 battery is built, MANUAL / NOT RUN; its CI run and the real-QuestDB leg are carried to #528 | DEFENDED in process, leg NOT RUN |
| Permission revoked mid-subscription, audited | `test_authz_and_revocation.py::test_authz_revoked_bars_subscription_is_announced_audited_and_silent`: `permission_change`, then `revoked` `permission_revoked`, no `snap` or `d` after it, one `ws.subscription.revoked` row with `sub_id`, `connection_id`, `session_id`; the lease released | DEFENDED |
| A hostile upstream payload never reaches a builder | AC-10 | DEFENDED |
| Parameter fuzzing, all ten parameters | AC-03 | DEFENDED |
| Exhaustion battery: maximal windows, `tick:1`, stampede, rebuild flap, slow consumer | AC-01, AC-02, `test_exhaustion.py` (stampede: F3), AC-05, AC-06 | FINDING F3 |
| Serve bars from an incomplete `build_version` | AC-08 | NOT RUN (#535) |
| Debug-surface check | AC-12 | DEFENDED |
| Every rejection counted and logged, escaped | `test_observability.py`: `api_request_rejected_total{route,reason}` and one `market_request_refused` log per refusal, client values `ascii()`-escaped and cut to 32 characters (F4a, #5348). A `limit` outside 1..5000 is answered 422 but neither counted nor logged (owned row) | DEFENDED; NOT COVERED: `limit` |
| An alert on rejection or rebuild rate | `test_observability.py::test_observability_an_alert_watches_the_rate` | FINDING F4b |
| Caps reconciled with X01 | `test_caps_match_model.py` (every X01 §3/§7 number equals its constant; the spec caps homed in `limits.py`, F5) | DEFENDED |
| SCR-048, the accessible error state | Front-end: `apps/web/src/features/chart-errors/` maps `bar_window_too_large` and `validation_failed`; no web test here (BQ-11) | Recorded |

**Rejection-cost bound (BQ-5): interim, ruled 2026-11-01, owner ratification on #2701.** A refused
`tick:1` request adds at most **2 ms** of CPU (median `process_time`) over an unauthenticated refusal, in
process (200 interleaved pairs), and makes no storage call. The structural half is primary; the number is in X01 §3 as SR-E12-01's bound and
in one constant, `REJECTION_CPU_BUDGET_S` (`test_caps_and_cost.py`).

## NOT RUN

<!-- prettier-ignore -->
| Leg | Why | What runs it |
| --- | --- | --- |
| ADR-0033 Decision 2: 1 concurrent and 6 per 10 min per user, 2 process-wide, disconnect cancels, foreign cancel refused, `rebuild_id` IDOR, rebuild audit, interrupted swap, stale generation, mutated builder at an unchanged version (AC-05, AC-08, AC-11; SR-E12-05, -06, -13) | The user rebuild and its generation swap are unbuilt (E12-S12 #535, contract first #2127); ten `pytest.skip` placeholders in `test_rebuild_blocked.py` | The #535 PR, carrying these cases as an explicit row on #535 (ruling BQ-6) |
| Cross-session p95 on real QuestDB under one session's maximal-page loop (F3) | Needs the compose stack; not built here, and **carried to #528 (E12-Q05)** with the k6 battery's CI run. No nightly leg watches F3 today | #528 (E12-Q05). F3's trigger: if budget #13 fails cross-session on real QuestDB → one security issue, contract-first fix |
| The 10-minute battery: `tests/load/k6/bars_abuse.js` (maximal pages, hostile parameters and concurrent sessions; loopback-only host guard, pinned without k6 by `scripts/tests/test_bars_abuse_k6.py`) | **Built; MANUAL / NOT RUN**: no workflow runs it, and no staging host or seeded dev session exists in this lane | A manual run on a loopback dev stack; its CI run is **carried to #528 (E12-Q05)**; its missing rebuild-flap and ingestion-loss scenarios are carried there too |
| AC-06 at load scale | X01 assigns it to E12-Q05/Q06 | E12-Q05 (#528), E12-Q06 (#529) |
| AC-13, AC-14 | X01 assigns them to E12-Q06 | E12-Q06 (#529) |
| A manual abuse session, recorded (`02-definition-of-ready-done.md` §3.2) | No staging profile exists (only `infra/compose` dev and deploy); everything automated runs in process | The first staging environment |

## Findings

Each was found by the suite on `main` at `8633cbecd` or by this PR. Under the filing freeze none opens an
issue: each is a row on #452, pinned against the issue that owns its fix where one exists, as ruled
(6554826610). A strict xfail names how its case fails (`raises=`); its fix removes the marker.

<!-- prettier-ignore -->
| Id | Finding | Rows | Pinned by | Status |
| --- | --- | --- | --- | --- |
| F1 | A pre-1970 `from` was measured from 1970-01-01, so `from=1900…to=1970-06` passed the 400-day cap and the bar read ran over 70 years | BR-28, SR-E12-02 | `test_caps_pre_epoch_window_is_measured_from_its_from`; the oracle's span cap | Fixed in #5348 |
| F2 | `/market/klines` has no SR-E12-01 deadline on its hot and recording-start reads, and a raw driver error from the hot read is a 500; `/market/bars` has neither for its recording-start read and maps only timeouts and socket errors on its bar read | BR-27, SR-E12-01 | `test_deadlines.py::test_deadline_faulted_store_call_is_503`: the klines cases pass; the bars half is two strict xfails (`pytest.fail.Exception` for a hang, `AssertionError` for a 500) | Klines half **fixed in #5348**: a deadline on every klines store read, answered 503, and exact from/to time. Bars half open with #3287 |
| F3 | No per-user rate limit and no single-flight on the two REST routes, which BR-36 names as its controls: 60 maximal pages meet no 429, and 50 identical requests in flight make 50 bar reads (measured) | BR-36 | `test_caps_and_cost.py::test_caps_one_session_looping_maximal_pages_is_throttled`; `test_exhaustion.py::test_exhaustion_identical_concurrent_reads_are_coalesced` (`NotCoalesced`) | Open, suspected cross-session. The nightly real-QuestDB leg is **carried to #528 (E12-Q05)**; trigger: if budget #13 fails cross-session on real QuestDB → one security issue, contract-first fix (ruling F3) |
| F4a | Refusals were neither counted by route and reason nor logged | Observability | `test_observability.py` | Fixed in #5348 (`api_request_rejected_total{route,reason}`, the escaped `market_request_refused` log) |
| F4b | No alert rule watches the bars rejection or rebuild rate | Observability | `test_observability.py::test_observability_an_alert_watches_the_rate` (strict xfail) | Open. Owner: the Security engineer, with infra-devops for the rule; trigger: filed when the filing freeze lifts, at the latest before the E12-X04 sign-off. #5348 does not fix it: it needs an alert rule with a runbook anchor and promtool tests |
| F5 | The spec caps lived in `bars/leases.py`, not the one home X01 §7 names | SR-E12-04, §7 | `test_caps_match_model.py::test_caps_match_model_spec_caps_live_in_limits` | Fixed in #5348 |
| F6 | `from`/`to` accept non-RFC 3339 forms (date-only, basic, week dates) | BR-25 | `test_caps_non_rfc_3339_time_*_accepted_f6` (served, and read as the instant they name) | ACCEPTED (ruling; the X01 §3 note) |
| F7 | `to=9999-12-31T23:59:59.999999Z` was a 500: the float conversion rounded into year 10000 | BR-25 | `test_param_fuzz_last_microsecond_of_9999_is_served_for_time_bars` | Fixed in #5348 (exact integer µs) |
| F8 | The `volume`/`delta` floor applied is the integer 1, so below a `qty_step` of 0.1 the documented 10 × `qty_step` floor is never the one applied, and over the no-dot wire grammar it is unreachable | BR-29, SR-E12-03 | `test_caps_and_cost.py::test_caps_qty_floor_is_ten_qty_steps` (`BarParamOutOfRange`) | Open. Owner: the E12-T05 limits owner (SR-E12-03); trigger: the X01 §3 per-liquidity-tier review of the floors, or the filing freeze lifting, whichever comes first |
| F9 | **New in PR-2.** A row withheld for a failed checksum leaves a silent gap: the 200 carries no sign of it (`meta` holds count, cursor, sources and times only; `coverage_holes` is not set), so a chart draws a bar-wide gap that reads as no trading. The event is counted and logged server-side | BR-08, SR-E12-11 | `test_integrity.py::test_integrity_withheld_bar_is_named_to_the_client` (`SilentGap`) | Open, **P2**, owned row on #452: owner vw1, trigger: the next E12 bars fix PR, which sets `meta.coverage_holes` for the withheld range and flips the xfail |
| — | NOT COVERED: a `limit` outside 1..5000 is answered 422 but neither counted nor logged | Observability | `test_observability.py` (`limit` strict xfails) | Open, P2, owned row on #452: owner vw1, trigger: the next E12 bars fix PR, which counts and logs it and flips the xfails |

No finding is Critical. F3 is the one with cross-session reach; it stays a strict xfail until the
real-QuestDB leg carried to #528 quantifies it (if budget #13 fails cross-session on real QuestDB → one security issue, contract-first fix). No nightly leg watches F3 today.

Every open finding (F2's bars half, F3, F4b, F8, F9), the NOT RUN legs and the follow-ups below are
carried, each with its owner, into the threat model's residual register (`E12-bars.md` §12), so they
outlive #452.

## Follow-ups (rows on #452)

- Klines converted `from`/`to` through a float (±1 µs, no 500): fixed in #5348, which reads both
  routes' times in exact integers (`api/market_time.py`).
- `bars_endpoint_param_rejected_total` now also counts 401, 403, 501 and 503: the F4b alert must exclude
  `reason="unavailable"`.
- One WARN per unauthenticated refusal: sample it if F3's limiter slips.
- The E08-X02 long parser fuzz (`tests/security/ingestion/test_fuzz_parsers.py`, `CV_FUZZ_LONG`) is
  not selected by `fuzz-nightly.yml`; seen while wiring the bars step, not changed here.
- BR-36's controls (a per-user limit, single-flight) are not built (F3); X01 changes when F3's fix lands.
