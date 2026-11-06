# E29-X02 — Abuse-case catalogue: the OMS

- Ticket: E29-X02 (#982), slice S3 of three (S1, the OMS Semgrep rules and
  `docs/plan/security/ci-gates-e29.md`, #5680; S2, the route-by-role matrix and the WS scope
  cells, #5715). Threat source: `docs/security/threat-models/E29-oms.md` section 8.2 (AC-01 to
  AC-31), with its requirements (section 10) and findings (section 12.1); the ticket's nine named
  cases; the three rows posted on #982 on 2026-10-23 and 2026-10-24. Rulings: the orchestrator's
  on #982 of 2026-11-03 (BQ-1 to BQ-10; BQ-2, BQ-5, BQ-8 and BQ-9 as amended).
- Method: white-box and in process. The cells and the cases run through the real `create_app()`
  with the OMS composed on in-memory stores (`_world.py`); the venue-facing cases through the
  adapter's trading port over recorded replies (`packages/fixtures/bybit/`, C-13.5); the reserve
  cases on the real token-bucket governor, compressed, on an injected clock. No network, no sleeps
  (C-13.7). Every automated case is a permanent regression.
- Where they live: `services/api/tests/security/oms/`, in the `contract-security-2` lane on every PR
  that touches `services/api/**` (BQ-9: no workflow change). `test_abuse_catalogue.py` fails when a
  seed of the model has no row here, when a cited test does not exist, when a verdict is not a
  word of the key below, when a waiting or manual row names no ticket, when a pin names no owner
  ticket and accepted-risk record, when a record has no sign-off naming its owner ticket, or when
  an in-scope route or private topic is missing from the coverage table.
- Verdict key:
  - **SUITE**: a cell holds it (every E29 route × every actor × every scope situation, and every
    private topic × every actor), and the row cites a test of `tests/security/oms/`;
  - **NEW**: a case this ticket adds;
  - **COVERED**: an existing test holds it, cited;
  - **PIN**: `main` does not meet the case yet; an `xfail(strict=True)` names its owner ticket and
    its accepted-risk record (below), so it turns red the day the control lands;
  - **WAITING**: the route or the decision is not on `main`; the row names the ticket. Never
    skipped;
  - **MANUAL**: not automated here; held on the E29-X03 (#1152) checklist.
- Rule ids (verified in `CONSTITUTION.md`): C-2.6, C-2.7, C-2.9, C-12.4, C-12.6, C-13.5, C-13.7.

## Coverage: the routes and topics in scope

BQ-8 as ruled: every operation of `22-api-openapi.yaml` on `/orders*`, `/positions*` and
`/executions*` carries `x-rbac` and is a row of `matrix.yaml`, and every private topic of
`23-ws-protocol.md` section 6.2 is run or named with its owner
(`tests/security/oms/test_suite_meta.py::test_every_e29_operation_of_22_carries_x_rbac_and_is_a_row_of_the_matrix`,
`::test_every_private_topic_of_23_is_run_here_or_named_with_its_owner`). Each is listed here once.

<!-- prettier-ignore -->
| Operation or topic | Route | Cells |
| --- | --- | --- |
| `listOrders` | `GET /orders` | every actor × no filter, granted, foreign, absent, mixed |
| `placeOrder` | `POST /orders` | every actor × granted, foreign, absent |
| `getOrder` | `GET /orders/{orderId}` | every actor × granted, foreign, absent |
| `amendOrder` | `PATCH /orders/{orderId}` | every actor × granted, foreign, absent |
| `cancelOrder` | `DELETE /orders/{orderId}` | every actor × granted, foreign, absent |
| `cancelAllOrders` | `POST /orders/cancel-all` | every actor × granted, foreign, absent, mixed |
| `getOrderDiagnostics` | `GET /orders/{orderId}/diagnostics` | every actor × granted, foreign, absent |
| `listPositions` | `GET /positions` | every actor × no filter, granted, foreign, absent, mixed |
| `getPosition` | `GET /positions/{positionId}` | every actor × granted, foreign, absent |
| `setPositionTpSl` | `PUT /positions/{positionId}/tpsl` | none while not mounted; owed by E32 the day it is served |
| `closePosition` | `POST /positions/{positionId}/close` | every actor × granted, foreign, absent |
| `reversePosition` | `POST /positions/{positionId}/reverse` | every actor × granted, foreign, absent |
| `setPositionLeverage` | `PUT /positions/{positionId}/leverage` | every actor × granted, foreign, absent |
| `closeAllPositions` | `POST /positions/close-all` | every actor × granted, foreign, absent, mixed |
| `listExecutions` | `GET /executions` | every actor × no filter, granted, foreign, absent, mixed |
| `listClosedPnl` | `GET /executions/closed-pnl` | every actor × no filter, granted, foreign, absent, mixed |
| topic `orders` | WS | every actor; frames of each account published |
| topic `executions` | WS | every actor; frames of each account published |
| topic `positions` | WS | every actor; frames of each account published |
| topic `wallet` | WS | every actor; frames of each account published |
| topic `machines.order` | WS | every actor × the granted and the foreign order's entity |

## The abuse cases (`E29-oms.md` section 8.2)

<!-- prettier-ignore -->
| Id | Verdict | Evidence or ticket |
| --- | --- | --- |
| AC-01 | SUITE, NEW | The `POST /orders` cells, foreign and absent: refused, audited, no store changed and nothing sent (`tests/security/oms/test_rbac_matrix.py::test_every_e29_cell_is_answered_as_the_matrix_and_the_scope_rule_say`); the two answers byte for byte: `tests/security/oms/test_abuse_cases.py::test_ac01_an_account_outside_the_grants_and_one_nothing_holds_are_refused_alike` |
| AC-02 | SUITE | The foreign cells of amend, cancel, close and reverse, and `tests/security/oms/test_rbac_matrix.py::test_an_ungranted_id_is_answered_byte_for_byte_as_an_absent_one`; leverage is the Owner's alone, a role cell |
| AC-03 | SUITE, NEW | `[A, B]` refused whole: the mixed cells and `tests/security/oms/test_suite_meta.py::test_every_list_and_every_write_naming_many_accounts_refuses_a_mixed_request`; `[]`: `tests/security/oms/test_abuse_cases.py::test_ac03_an_empty_account_list_reaches_the_callers_trade_grants_alone` |
| AC-04 | SUITE | The Viewer's cell of every write: 403, no store changed, `rbac.denied`; `tests/security/oms/test_suite_meta.py::test_every_mounted_write_has_its_forbidden_role_and_cross_account_cells` |
| AC-05 | SUITE, NEW | The list cells (exactly the caller's rows); `tests/security/oms/test_abuse_cases.py::test_ac05_a_page_of_one_row_counts_and_continues_over_the_callers_rows_alone` (a page of one row, the Owner's cursor refused), `::test_ac05_an_aggregate_sums_the_callers_own_positions_alone`, `::test_ac05_a_trade_group_spanning_both_accounts_lists_the_callers_rows_alone` |
| AC-06 | SUITE, NEW, COVERED, MANUAL | `tests/security/oms/test_ws_scope.py::test_a_private_sub_beyond_the_grants_is_narrowed_or_refused_and_never_echoed`, `::test_an_order_machine_on_a_foreign_account_is_refused_by_entity_and_never_sent`; a refused sub holds no subscription on the hub: `tests/security/oms/test_abuse_cases.py::test_ac06_a_refused_private_sub_holds_no_subscription_while_its_socket_is_open`; the grant withdrawn while subscribed: `tests/contract/rbac/test_scope_and_ws.py::test_in_flight_subscription_gets_revoked_when_the_grant_is_withdrawn`; the client dropping the rows and marks (SR-E29-11): E29-X03 (#1152) |
| AC-07 | COVERED, NEW | `tests/security/ws/test_account_notices.py::test_e29_ac_07_a_manager_granted_a_is_sent_nothing_that_names_or_counts_b`; with the real emitters: `tests/security/oms/test_account_notices_emitted.py::test_e29_ac_07_the_emitted_notices_of_b_never_reach_a_manager_granted_a`, `::test_e29_a_withdrawn_grant_stops_the_emitted_notices_of_b_and_s_has_no_gap` |
| AC-08 | COVERED | `tests/unit/oms/test_classify.py::test_effect_of_a_reduce_only_order_above_the_position_is_an_entry`, `::test_stop_errors_entry_without_a_stop_is_native_stop_required`; refused before anything is sent: `tests/unit/oms/test_submit.py::test_the_classify_step_refuses_with_the_rule_that_failed` |
| AC-09 | NEW | `tests/security/oms/test_abuse_cases.py::test_ac09_a_place_order_naming_a_field_the_server_sets_is_refused_and_persists_nothing`, `::test_ac09_the_same_body_without_it_passes_the_body_check` |
| AC-10 | COVERED | `tests/contract/test_place_order_contract.py::test_a_repeat_from_the_24h_record_is_the_first_202_replayed`; `tests/unit/api/test_orders_route.py::test_the_24h_record_answers_another_body_under_its_key_409`, `::test_another_principals_key_is_answered_as_one_never_seen`, `::test_an_anchors_replay_answers_its_entrys_rows_as_read_now_and_keeps_none`; `tests/unit/oms/test_idempotency.py::test_a_key_reused_with_another_body_is_refused_decided_or_not`; `tests/integration/oms/test_submission_pipeline_pg.py::test_idempotent_replay_after_a_restart` |
| AC-11 | NEW, COVERED | A mismatched id held, never bound, one create: `tests/security/oms/test_duplicate_link_id.py::test_a_squatted_link_id_is_held_never_bound_and_never_sent_twice`; the foreign order kept `untracked`: `tests/unit/oms/test_reconciler.py::test_3c_foreign_order_is_adopted_untracked_audited_ahead`, `::test_3a_unbound_unknown_row_binds_only_after_the_full_match` |
| AC-12 | COVERED | `tests/unit/exchange/bybit/test_rest_create_no_resend.py::test_a_create_that_left_is_ambiguous_and_sent_once`, `::test_a_create_10016_or_10019_is_counted_as_raised_never_as_a_rate_limit`, `::test_no_outcome_sequence_sends_a_create_again_after_it_left` |
| AC-13 | COVERED | `tests/unit/api/test_position_close_route.py::test_close_position_against_the_position_is_422_recorded_nothing_sent`, `::test_close_position_full_is_a_reduce_only_flatten_of_the_whole_size_answered_202`, `::test_close_position_a_body_breaking_a_rule_is_422_unrecorded`; `tests/unit/api/test_position_close_size.py::test_scenario_never_reverses_the_venue_read_refusal_is_422_unswept_uncached`; `tests/unit/oms/test_position_writes.py::test_close_request_full_takes_the_whole_size_reduce_only_on_the_opposite_side` |
| AC-14 | COVERED, WAITING | `tests/security/e28/test_abuse_cases.py::test_ac01_native_sl_off_is_refused_on_every_path_and_audited`; `tests/unit/oms/test_exits.py::test_native_sl_a_recorded_stops_cancel_is_403_while_its_position_is_open`; `tests/unit/oms/test_exits_amend.py::test_native_sl_each_refusal_is_audited_and_nothing_is_recorded_or_sent`; `tests/unit/oms/test_cancel_all.py::test_a_recorded_stop_and_a_conditional_member_never_reach_the_venues_cancel_all`. The foreign TP/SL and Full-mode repair halves wait on E32-X02 (#1173) and E39-T04 (#4208) |
| AC-15 | NEW, COVERED | `tests/security/oms/test_no_credential_stored.py::test_g5_no_seeded_credential_reaches_an_event_its_reads_an_audit_record_or_a_log`, `::test_g5_each_place_carries_its_seed_to_the_venues_answer_and_none_is_stored`; the port: `tests/unit/exchange/bybit/test_trading_secrets.py::test_no_seeded_credential_reaches_an_ack_a_record_an_exception_or_a_log`; the diagnostics: `tests/unit/api/test_oms_reads_route.py::test_diagnostics_never_leak_secrets` |
| AC-16 | COVERED, SUITE | `tests/unit/api/test_oms_reads_route.py::test_get_order_serves_fills_events_without_payload_and_its_etag`, `::test_diagnostics_serve_the_order_events_and_records_after_the_audit_row`, `::test_diagnostics_are_the_owners_alone_whatever_the_id`; `tests/contract/test_order_contract_threat_model.py::test_order_events_and_diagnostics_are_closed_and_events_carry_no_payload`; the diagnostics cells, every actor but the Owner refused (`tests/security/oms/test_rbac_matrix.py::test_every_e29_cell_is_answered_as_the_matrix_and_the_scope_rule_say`) |
| AC-17 | PIN | `tests/security/oms/test_protective_reserve.py::test_g3_a_stop_acquires_its_token_within_its_wait_while_the_budget_is_full` (`ac17`); X02-R1, #859 |
| AC-18 | PIN | `tests/security/oms/test_protective_reserve.py::test_g3_a_stop_acquires_its_token_within_its_wait_while_the_budget_is_full` (`ac18`); X02-R2, #859 |
| AC-19 | PIN, WAITING | The 429 and another user admitted: `tests/security/oms/test_abuse_ac19.py::test_ac19_a_burst_of_orders_from_one_session_meets_a_429_and_another_user_is_admitted`; X02-R4, #1152; what the burst meets today: `tests/security/oms/test_abuse_ac19.py::test_ac19_the_burst_meets_today_the_step_its_pin_stands_before`; the reserve is AC-17/18's. The per-symbol cap's alert at 80 % waits on E29-X03 (#1152), provisional until main-orchestrator confirms the owner (Deviations) |
| AC-20 | COVERED | Stale: `tests/unit/oms/test_reconcile_standing.py::test_the_standing_refuses_a_stale_accounts_entry_with_account_stale`, `tests/unit/oms/test_submit.py::test_the_switches_refuse_just_before_the_persist`, `::test_a_protective_close_passes_the_kill_switch_live_and_the_gate_c26`; Postgres: `tests/integration/oms/test_place_order_route_pg.py::test_order_entry_blocked_when_we_cannot_record_it_postgres_unreachable_at_boot`, `::test_order_entry_blocked_when_we_cannot_record_it_postgres_unreachable_once_ready`; the WAL: `tests/unit/audit/test_writer.py::test_writer_wal_full_with_postgres_down_refuses_never_drops`, `tests/unit/oms/test_submit.py::test_a_write_ahead_audit_refused_is_503_audit_unavailable`; the clock: `::test_a_clock_halt_refuses_before_anything_and_is_counted`, `::test_a_clock_drift_rejection_is_502_and_halts_the_next_request_until_resynced`. The stop owed after a fill during a full WAL is the accepted residual OM-D04 (`E29-oms.md` section 12.2) |
| AC-21 | WAITING | The algo half: E33-S06 (#1106); no human adopt action exists (BQ-17 resolved D6) |
| AC-22 | COVERED | `tests/unit/exchange/test_trading_read_models.py::test_a_private_event_refuses_a_payload_of_another_account`; `tests/unit/oms/test_order_lane_streams.py::test_two_accounts_streams_never_mix_across_the_hop`; `tests/unit/oms/test_reconciler.py::test_fetch_fails_on_a_row_of_another_account`, `::test_a_row_of_another_account_pages_once_per_episode`; `tests/unit/oms/test_reconciler_properties.py::test_any_row_of_another_account_fails_the_fetch_with_nothing_applied` |
| AC-23 | WAITING | The live gate: E44-T03 (#1246) |
| AC-24 | COVERED | `tests/unit/observability/test_redaction_order_link_id.py::test_redactor_ac24_keeps_the_id_and_redacts_a_secret_under_the_same_key`, `::test_logging_ac24_json_lines_keep_the_id_and_redact_the_secret` |
| AC-25 | COVERED | `tests/integration/storage/test_oms_core_migration.py::test_history_cannot_be_rewritten`, `::test_no_role_may_rewrite_order_history`; `tests/unit/migrations/test_0029_oms_core.py::test_append_only_tables_copy_the_audit_log_guards` |
| AC-26 | COVERED | `tests/unit/oms/test_execution.py::test_apply_execution_refuses_hostile_input`, `::test_apply_execution_keeps_inv_1`; `tests/unit/oms/test_stream_consumer.py::test_consumer_a_repeated_exec_id_writes_one_fill_row`; `tests/unit/oms/test_order_machine.py::test_s5_an_older_push_is_ignored_and_a_fill_never_is`, `::test_a_fill_for_a_final_machine_still_alive_is_b1s_anomaly`, `::test_an_anomaly_is_alerted_once_its_record_is_written` |
| AC-27 | SUITE, NEW | The CSRF cells of a caller with no session; with the Owner's session: `tests/security/oms/test_abuse_cases.py::test_ac27_an_owners_write_without_its_csrf_proof_is_refused_before_the_handler` |
| AC-28 | WAITING | The sized-order cap check and the lockout gate: E39-S01 (#954) |
| AC-29 | COVERED | `tests/unit/api/test_position_close_route.py::test_close_position_replay_the_anchor_answers_its_rows_as_read_now_unsent`; `tests/unit/api/test_position_reverse_route.py::test_reverse_position_replay_undecided_with_its_open_anchor_answers_reversed`; close-all's legs: `tests/unit/api/test_position_writes_edges.py::test_close_position_a_held_key_met_at_the_persist_answers_the_earlier_rows`; an expired access handle: `tests/unit/auth/test_session_service_edges.py::test_access_token_lookups_reject_unknown_expired_and_revoked` |
| AC-30 | PIN, COVERED | `tests/security/oms/test_protective_reserve.py::test_g3_a_stop_acquires_its_token_within_its_wait_while_the_budget_is_full` (`ac30`); X02-R3, #859. The `10018` half: `tests/unit/exchange/bybit/test_trading_port.py::test_a_10018_on_one_account_holds_every_other_account_and_the_public_client`, `::test_the_service_builds_one_governor_for_every_client` |
| AC-31 | COVERED | `tests/unit/exchange/bybit/test_trading_port_ac31.py::test_cancel_all_goes_on_the_order_class_in_the_critical_lane_without_an_id`, `::test_a_cancel_by_order_id_of_an_ext_order_goes_critical_without_an_id`, `::test_an_amend_by_order_id_of_a_partial_mode_stop_goes_critical_without_an_id`, `::test_a_create_without_an_id_is_refused_with_nothing_sent_and_no_token` |

## The ticket's named cases

<!-- prettier-ignore -->
| Ticket case | Seed | Verdict | Evidence or ticket |
| --- | --- | --- | --- |
| Manager on a non-granted account, REST and WS subscribe | AC-01, AC-02, AC-06 | SUITE | `tests/security/oms/test_rbac_matrix.py::test_every_e29_cell_is_answered_as_the_matrix_and_the_scope_rule_say`; `tests/security/oms/test_ws_scope.py::test_a_private_sub_beyond_the_grants_is_narrowed_or_refused_and_never_echoed` |
| Viewer on every mutating route | AC-04 | SUITE | `tests/security/oms/test_suite_meta.py::test_every_mounted_write_has_its_forbidden_role_and_cross_account_cells` |
| Forged `order_link_id` replay | AC-09, AC-11 | NEW | `tests/security/oms/test_duplicate_link_id.py::test_a_replayed_link_id_is_adopted_on_its_full_match_and_never_sent_twice`; no REST form: `tests/security/oms/test_abuse_cases.py::test_ac09_a_place_order_naming_a_field_the_server_sets_is_refused_and_persists_nothing` |
| Close quantity above the position | AC-13 | COVERED | `tests/unit/api/test_position_close_route.py::test_close_position_against_the_position_is_422_recorded_nothing_sent` |
| `reduce_only` stripped in transit | AC-13 | COVERED | `tests/unit/api/test_position_close_route.py::test_close_position_full_is_a_reduce_only_flatten_of_the_whole_size_answered_202`, `::test_close_position_a_body_breaking_a_rule_is_422_unrecorded` |
| Out-of-scope id smuggled in a batch or filter | AC-03, AC-05 | SUITE, NEW | `tests/security/oms/test_suite_meta.py::test_every_list_and_every_write_naming_many_accounts_refuses_a_mixed_request`; `tests/security/oms/test_abuse_cases.py::test_ac05_a_trade_group_spanning_both_accounts_lists_the_callers_rows_alone` |
| Order flood, protective traffic still gets a token | AC-17, AC-19 | PIN | `tests/security/oms/test_protective_reserve.py::test_g3_a_stop_acquires_its_token_within_its_wait_while_the_budget_is_full`, X02-R1, #859; `tests/security/oms/test_abuse_ac19.py::test_ac19_a_burst_of_orders_from_one_session_meets_a_429_and_another_user_is_admitted`, X02-R4, #1152 |
| Submit while the account is stale | AC-20 | COVERED | `tests/unit/oms/test_submit.py::test_the_switches_refuse_just_before_the_persist` |
| Submit while Postgres is unavailable | AC-20 | COVERED | `tests/integration/oms/test_place_order_route_pg.py::test_order_entry_blocked_when_we_cannot_record_it_postgres_unreachable_once_ready` |

## The rows posted on #982

<!-- prettier-ignore -->
| Row | Verdict | Evidence or ticket |
| --- | --- | --- |
| 2026-10-23, a per-user submit limit on `POST /orders` | PIN | `tests/security/oms/test_abuse_ac19.py::test_ac19_a_burst_of_orders_from_one_session_meets_a_429_and_another_user_is_admitted` (`entry`); X02-R4, #1152 |
| 2026-10-23, the reference price's demand kept per principal | PIN | `tests/security/oms/test_abuse_cases.py::test_982_row_2_one_principals_new_symbols_leave_another_principals_demand_admitted`; X02-R5, #1152; the budget spent today: `tests/security/oms/test_abuse_cases.py::test_982_row_2_one_principals_new_symbols_spend_the_window_today` |
| 2026-10-24, a burst of audited refusals shed by a per-user limit | PIN | `tests/security/oms/test_abuse_ac19.py::test_ac19_a_burst_of_orders_from_one_session_meets_a_429_and_another_user_is_admitted` (`refused_late`); X02-R4, #1152 |

## The ticket's Gherkin

<!-- prettier-ignore -->
| Scenario | Verdict | Evidence or ticket |
| --- | --- | --- |
| G1, every disallowed combination is proven | SUITE | `tests/security/oms/test_rbac_matrix.py::test_every_e29_cell_is_answered_as_the_matrix_and_the_scope_rule_say`; `tests/security/oms/test_ws_scope.py::test_a_private_sub_beyond_the_grants_is_narrowed_or_refused_and_never_echoed`; the code of each refusal class is the contract's (BQ-3, below) |
| G2, a replayed key creates no second order | NEW | `tests/security/oms/test_duplicate_link_id.py::test_a_replayed_link_id_is_adopted_on_its_full_match_and_never_sent_twice` |
| G3, the reserve cannot be starved | PIN | `tests/security/oms/test_protective_reserve.py::test_g3_a_stop_acquires_its_token_within_its_wait_while_the_budget_is_full`; X02-R1, #859 |
| G4, SAST rules have teeth | COVERED | S1's rule fixtures, run by `tools/ci/check_semgrep_rule_tests.py`; the reviewed markers: `tests/security/oms/test_suite_meta.py::test_the_oms_markers_are_exactly_the_reviewed_exceptions_of_the_rule_doc` |
| G5, no credential reaches storage | NEW | `tests/security/oms/test_no_credential_stored.py::test_g5_no_seeded_credential_reaches_an_event_its_reads_an_audit_record_or_a_log` |

## Negative controls

The ticket's test plan: each control removed in turn, its cases must turn red for the reason
named.

- NC-1, a scope check (the route's `enforce`, the store's scope, the gateway's `_may_view`, the
  fan-out's delivery filter):
  `tests/security/oms/test_negative_controls.py::test_negative_control_a_cell_fails_with_its_scope_layer_removed`,
  `::test_negative_control_a_sub_beyond_the_grants_is_served_without_may_view`,
  `::test_negative_control_a_narrowed_sub_is_sent_foreign_frames_without_the_delivery_filter`.
- NC-2, the store's redaction call; NC-3, the REST client's reply masking. Beside G5, as a
  module holding the OMS world cannot run B1 a second time (its ports are one per process,
  C-2.11):
  `tests/security/oms/test_no_credential_stored.py::test_negative_control_a_seeded_credential_is_stored_without_its_control`;
  what the record alone keeps out stays out:
  `::test_negative_control_the_record_alone_keeps_headers_and_unknown_fields_out`.
- NC-4, the reserve: lands with E34-T02 (#859); until then G3 and its cases are pins.
- NC-5, the `rbac.denied` record:
  `tests/security/oms/test_negative_controls.py::test_negative_control_a_refused_cell_fails_without_its_rbac_denied_record`.
- NC-6, a rule weakened: each S1 rule's fixture lines, run by the rule-test checker.

## Accepted risks and sign-off

BQ-5 as ruled: a case `main` does not meet is pinned only with this record and a sign-off naming
its owner ticket. Each pin's `reason` names its record and that ticket. Each record is accepted
until its owner ticket closes, and no longer: its control landing turns the record's strict xfail
XPASS, which fails the suite, and that ticket's PR removes the xfail and this row. Ratings use the
model's matrix (`E29-oms.md` section 1.3); H\* raises a cell one band. The Owner's acceptance for
the programme R3 release gate is owed on #2701.

<!-- prettier-ignore -->
| Record | Pinned | Pin (test) | Unmet requirement | STRIDE, risk | Owner ticket | Sign-off |
| --- | --- | --- | --- | --- | --- | --- |
| X02-R1 | AC-17, G3 | `tests/security/oms/test_protective_reserve.py::test_g3_a_stop_acquires_its_token_within_its_wait_while_the_budget_is_full` (`ac17`) | A stop placement acquires its `critical` token within the lane's wait while entries and polls fill the UID's budget (SR-E29-14, SR-071) | D, M x H\*, Critical (OM-D02; F-04 High) | #859 | main-orchestrator under the Owner's delegation, ruling of 2026-11-03 on #982, for #859; the Owner's veto window is the digest |
| X02-R2 | AC-18 | `tests/security/oms/test_protective_reserve.py::test_g3_a_stop_acquires_its_token_within_its_wait_while_the_budget_is_full` (`ac18`) | A stop attach holds a slice of `critical` that cancels cannot spend, and cancels are limited per user (SR-E29-14) | D, L x H\*, High (OM-D06; F-04 High) | #859 | main-orchestrator under the Owner's delegation, ruling of 2026-11-03 on #982, for #859; the Owner's veto window is the digest |
| X02-R3 | AC-30 | `tests/security/oms/test_protective_reserve.py::test_g3_a_stop_acquires_its_token_within_its_wait_while_the_budget_is_full` (`ac30`) | The process's IP bucket serves another UID's stop ahead of queued work, which no lane outside `critical` can spend or pass (SR-044c, SR-E29-14) | D, M x H\*, Critical (OM-D08; F-04 High) | #859 | main-orchestrator under the Owner's delegation, ruling of 2026-11-03 on #982, for #859; the Owner's veto window is the digest |
| X02-R4 | AC-19, #982 rows of 2026-10-23 and 2026-10-24 | `tests/security/oms/test_abuse_ac19.py::test_ac19_a_burst_of_orders_from_one_session_meets_a_429_and_another_user_is_admitted` (`entry`, `refused_late`) | The order routes keep a per-user limit, answered `429 rate_limited` with `Retry-After`, which another user's orders never meet (OM-D01, SR-044d) | D, M x H, High (OM-D01) | #1152 (E29-X03), named by main-orchestrator on 2026-11-05 (BQ-5) | main-orchestrator under the Owner's delegation, ruling of 2026-11-03 on #982, for #1152; the Owner's veto window is the digest |
| X02-R5 | #982 row of 2026-10-23 (the reference price) | `tests/security/oms/test_abuse_cases.py::test_982_row_2_one_principals_new_symbols_leave_another_principals_demand_admitted` | The reference price's budget of new symbols is kept per principal (CR-S3E4-02) | D, L x M, Low (no model row) | #1152 (E29-X03), named by main-orchestrator on 2026-11-05 (BQ-5) | main-orchestrator under the Owner's delegation, ruling of 2026-11-03 on #982, for #1152; the Owner's veto window is the digest |

The native stop attached at create (C-2.6) stays the floor of every open position throughout.
`32-risk-register.md` is E29-T09's to update (BQ-9 as ruled); these records are this suite's rows
for it.

## Manual checks (E29-X03, #1152)

- The web client drops a withdrawn account's rows and marks (AC-06, SR-E29-11).
- Anything CI uploads beyond the lanes' coverage data, and a capture not recorded yet (O-1,
  E29-K01 #843): the scan coverage's manual part (BQ-9 as ruled;
  `tests/security/oms/test_suite_meta.py::test_no_gitleaks_allowlist_path_covers_a_recorded_fixture_or_this_suite`).

## Deviations

- BQ-3: the Gherkin's "403 for every disallowed combination" is the contract's code per refusal
  class: `403 forbidden`, `403 account_scope_denied`, one byte-identical `404 not_found` for a
  foreign and a missing id (SR-E29-13), `401 unauthenticated`, `403 csrf_token_invalid`. A missing
  id writes no `rbac.denied` (the accepted Q12 residual); a 401 has no principal to record.
- BQ-4: `rbac_denied_total{route,role}` does not exist; the cells assert `authz_denied_total` and
  `authz_denied_by_route_total` as built, and the WS subscribe counters. The name is E29-T09's
  (#1029).
- The ticket's three roles are the matrix's five actors.
- AC-19 is split. Its 429 and its other user admitted are a pin (X02-R4). Its third expectation,
  the per-symbol cap's alert at 80 %, has no control on `main` to pin: it is WAITING on E29-X03
  (#1152), provisional until main-orchestrator confirms that owner on #982.
