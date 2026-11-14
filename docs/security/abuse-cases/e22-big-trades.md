# E22-X02 — Abuse-case catalogue: the big-trade data surfaces

- Ticket: E22-X02 (#756). Threat source: `docs/security/threat-models/E22-big-trades.md` (E22-X01), its
  rows D1-D27 and its §9 cases AC1-AC19, keyed here by those ids. Control verdicts:
  `docs/security/reviews/e22-big-trades-review.md`. E17's catalogue (`docs/security/abuse-cases/e17-ws.md`)
  is referenced, not repeated.
- Method: white-box, in process, as E12-X02 ran its cases. REST cases drive `GET /market/trades` through the
  app's router with a raw client that ignores every client rule, so the server is what refuses; WS cases run
  on the `trades` topic's harness and the E17 gateway. The feed is the recorded `publicTrade` fixtures
  (C-13.5): no network, no staging host, no live account, no real key, no load against the live feed.
  "No query" in the model reads "no tape read": the route serves the in-memory hot tape.
- Test paths are under `services/api/` unless they start with `apps/`. New tests go under
  `services/api/tests/security/bigtrade/`.
- Status key: **COVERED** an existing test on `main` holds the leg, named · **DEFENDED** a test this
  ticket adds under `services/api/tests/security/bigtrade/` (or `tests/contract/`) runs the leg and it
  holds, named · **NEW** E22-X02 writes it against code on `main` (PR-2) · **WAITING** the code is not on `main`; the ticket that builds it is named ·
  **NOT RUN** with the reason. A case with several legs gives each leg its own status. No test is written
  for an open private finding until its fix lands (review record §2).
- Results: the DEFENDED legs of cases 1-4, 6 and 8 ran green in process (no 500, no read before a
  refusal, nothing held or clamped, the live subscription served). The NEW legs (AC19 and the PR-2
  rows) record their results and counters here when they run.

## The ticket's eight cases

<!-- prettier-ignore -->
| Ticket case | Model cases |
| --- | --- |
| 1 Enormous window and `limit` | AC1-AC3 (AC1's "no query" half as "no tape read") |
| 2 Out-of-range cluster options | AC8 |
| 3 `min_size=0` on the hottest symbol | AC4 |
| 4 Subscription flood | AC5-AC7 |
| 5 RBAC on `bigtrade.*` settings | AC14 |
| 6 Unauthenticated subscribe | AC16 |
| 7 Settings tampering | AC15 |
| 8 Log and analytics inspection | AC12-AC13 |

Cases 1-4, 6 and 8 rest on code on `main`; cases 5 and 7 wait on E22-S02 (#715) and the owner decision
D05-G-2 (#715 BQ-01). Case 5 asserts today's answers only (a Viewer `PATCH` `403` `rbac.denied`; a
target-user query parameter `422`; a view-as write `403 view_as_read_only`); its Owner-only leg waits for
the decision.

## Cases

<!-- prettier-ignore -->
| Case | Rows | Action | Expected | Status |
| --- | --- | --- | --- | --- |
| AC1 | D14 | `GET /market/trades` with `from` at the epoch and `to` now | `400 invalid_time_range`, counted in `bigtrade_range_rejected_total`; no tape read | COVERED for a window past 6 h, counted, nothing read: `tests/unit/api/test_trades_api.py::test_get_trades_refuses_out_of_bound_reads_before_reading`. DEFENDED, the epoch leg: `tests/security/bigtrade/test_rest_bounds.py::test_ac1_a_window_from_the_epoch_is_400_counted_and_reads_nothing` |
| AC2 | D14 | `limit` 501, 0, -1, 1.5; a cursor past 512 characters; one that does not decode | `422 validation_failed` for `limit` and the long cursor; `400` for the undecodable cursor; nothing read | COVERED for `limit` 501 (`test_trades_api.py::test_get_trades_keeps_its_bounds_at_their_edges`) and an undecodable cursor (`::test_get_trades_cursor_pages_without_overlap`). DEFENDED, `limit` 0, -1, 1.5 and the 513-character cursor: `test_rest_bounds.py::test_ac2_ac8_an_out_of_schema_parameter_is_422_naming_it_and_reads_nothing`; the 512-character cursor is no validation refusal: `::test_ac2_a_cursor_at_its_length_bound_is_not_a_validation_refusal` |
| AC2 C-CURSOR | D14 | A cursor's expiry and an edited or unissued cursor (`22` `Cursor`; QA plan C-CURSOR) | as `22` states | NOT RUN: routed to the `22` owner with E22-X02 (QA plan C-CURSOR) |
| AC3 | D14 | A window of exactly 6 h and 6 h + 1 ms; 15 min and 15 min + 1 ms past a 2 000 ms cluster window; `from` after `to` | the edges `200`; past them and the inverted window `400 invalid_time_range` | COVERED: the edges, `test_trades_api.py::test_get_trades_keeps_its_bounds_at_their_edges`; past them and the inverted window, `::test_get_trades_refuses_out_of_bound_reads_before_reading` |
| AC4 | D15 | Subscribe `trades` on the hot symbol with `min_size` 0, negative, `NaN`, `1e-30` and below the floor, beside a live subscription | rejected with `ws_subscribe_rejected_total{reason}`; first subscription unaffected | COVERED, 0 and below the floor refused `invalid_options` on `min_size` with nothing held: `tests/unit/ws/test_trades_publish.py::test_trades_out_of_range_options_are_refused_and_nothing_is_held`. DEFENDED, negative, `NaN` and `1e-30` refused `invalid_options` on `min_size` with nothing held, and the live subscription's frames unaffected: `tests/security/bigtrade/test_ws_options.py::test_ac4_ac8_a_refused_option_creates_nothing_and_a_live_subscription_is_unaffected` |
| AC5 | D17 | One user, one symbol, three distinct option sets | the third refused `subscription_limit`, counted, nothing held | COVERED: `test_trades_publish.py::test_trades_per_user_cap_and_option_set_cap_refuse_with_nothing_held` |
| AC6 | D17 | 41st distinct symbol on one connection; 201st subscription; 51 topics in one request | each refused per E17; the earlier subscriptions keep their frames | COVERED (E17): the 41st `trades` symbol and the 201st subscription with the socket still serving, `tests/security/ws/test_limits_abuse.py::test_x02_ws_d04_a_full_cap_refuses_the_next_topic_and_the_socket_keeps_serving`; 51 topics, `tests/unit/ws/test_gateway_limits.py::test_sub_frame_with_too_many_topics_is_refused_whole` |
| AC7 | D17 | A ninth connection for one user; a 61st `trades` subscription across connections | the ninth handled per `23`; the 61st refused | COVERED for the 61st: `test_trades_publish.py::test_trades_pending_leases_count_toward_both_caps`; the ninth connection (E17): `tests/security/ws/test_limits_abuse.py::test_x02_ac_15_the_ninth_socket_of_a_user_closes_the_oldest_idle_one_across_sessions` |
| AC8 | D16 | `cluster_window_ms` 5001 and 999999 on REST, 2001 on WS, -1, not an integer; tolerance 21 and 999 | REST `422 validation_failed` naming the field; WS refused `invalid_options` naming the field, counted `cluster_range`, no subscription created, no silent clamp | COVERED for REST 5001 and tolerance 21 (`test_trades_api.py::test_get_trades_keeps_its_bounds_at_their_edges`) and WS 2001, 999999 and tolerance 21 (`test_trades_publish.py::test_trades_out_of_range_options_are_refused_and_nothing_is_held`). DEFENDED, REST 999999, 999, -1 and non-integer: `test_rest_bounds.py::test_ac2_ac8_an_out_of_schema_parameter_is_422_naming_it_and_reads_nothing`; WS -1, 2.5, a string, 999 and -1 ticks refused naming the field with nothing created: `test_ws_options.py::test_ac4_ac8_a_refused_option_creates_nothing_and_a_live_subscription_is_unaffected`; the `22` and `23` bounds equal `orderflow/limits.py`: `tests/contract/test_trades_bounds_contract.py` |
| AC9 | D16, D19 | A hostile burst of same-side keys over the open-key cap at a 2 000 ms window | open keys at most 4096; `bigtrade_state_truncated_total` moves | COVERED (unit): `tests/unit/orderflow/test_bigtrade_cluster.py::test_open_key_cap_evicts_oldest_and_counts_truncation`. WAITING: the soak, E22-Q03 (#753) |
| AC10 | D18 | A subscriber that stops reading at full rate | budget held; `backpressure` snapshot; others on time | WAITING: G8 and E22-Q03 (#753) |
| AC11 | D3 | Non-positive, off-tick or extreme prints reach the engine | rejected and counted; the threshold unmoved beyond the trim | COVERED: `tests/unit/orderflow/test_bigtrade_engine.py::test_input_assert_rejects_off_tick_and_non_positive`, `tests/unit/orderflow/test_bigtrade_quantile.py::test_trimmed_wrapper_single_outlier_does_not_move_threshold` |
| AC12 | D9 | Scan WS frames, REST bodies, logs and metric labels of a two-user run; the `tape.*` analytics payloads | no user, account or key identifier | DEFENDED for frames, bodies, logs and labels: `tests/security/bigtrade/test_disclosure.py::test_ac12_no_identifier_in_frames_bodies_logs_or_metric_labels`. `tape.*`: no such analytics event on `main`; WAITING on the ticket that adds one |
| AC13 | D10 | Two users subscribe to one symbol with different options; diff their acks, errors and `effective` | each sees only their own options and the symbol's engine threshold | DEFENDED: `test_disclosure.py::test_ac13_each_user_sees_only_their_own_options` |
| AC14 | D13, D25 | As a Viewer, `PATCH /settings` with `bigtrade.*` keys; a target user in the query; a view-as write; read another user's thresholds | Viewer `403` `rbac.denied`; the query `422`; the view-as write `403 view_as_read_only`; nothing changed | COVERED for today's answers: `tests/unit/api/test_user_settings_router.py::test_settings_a_viewer_reads_and_is_refused_403_on_a_write`, `::test_settings_a_query_parameter_is_422_and_nothing_is_read_or_written`, `::test_settings_a_write_under_a_view_is_refused_before_anything_else`, `::test_settings_one_user_never_reads_or_writes_another_users`. WAITING on E22-S02 (#715): the `bigtrade.*` keys |
| AC15 | D25, D4 | A non-Owner changes a symbol's engine threshold; a settings write naming 201 symbols | `403`; `422`, nothing written | WAITING on E22-S02 (#715) and D05-G-2 (#715 BQ-01, due 2026-12-11) |
| AC16 | D1, D26 | No session, and a session without `marketdata:read`, on `GET /market/trades` and a `trades` subscribe | `401` / `403`; the subscribe refused | COVERED for REST: `test_trades_api.py::test_get_trades_error_paths`; for an unauthenticated subscribe: `tests/unit/ws/test_subscriptions_socket.py::test_socket_unauthenticated_sub_is_refused`. DEFENDED, a `trades.BTCUSDT` subscribe without the permission: `test_ws_options.py::test_ac16_a_session_without_marketdata_read_cannot_subscribe_to_trades` |
| AC17 | D21 | 5 000 simultaneous bubble pops | at most 3 Hz, frame time in budget | WAITING: E22-S03 (#716), E22-Q03, E22-Q04 |
| AC18 | D22 | A million prints into the client ring | stops at 50 000 prints or 32 MiB; trimmed state shown | COVERED for the count: `apps/web/test/features/tape/ring.test.ts`. WAITING: the bytes leg, E22-S05 (#718) |
| AC19 | D27 | Enumerate every E22 operation and topic from `22` and `23` | no non-GET other than the settings route and the engine-value writer | NEW |

## Not run

<!-- prettier-ignore -->
| Item | Reason |
| --- | --- |
| A manual abuse session on staging | No staging profile exists; the cases run in process over recorded fixtures (Deviation) |
| C-CURSOR (AC2) | Routed to the `22` owner with E22-X02 (QA plan C-CURSOR) |
| Budget #3 under load (WS to screen p95 < 100 ms) | E22-Q03 (#753); E22-X02 asserts in process only that other subscriptions are not degraded |
