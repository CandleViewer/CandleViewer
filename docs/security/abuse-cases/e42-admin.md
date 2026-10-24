# E42-X03 — Abuse-case catalogue: the admin area

- Ticket: E42-X03 (#1026), PR-1 of 2 (the suites). Threat sources:
  `docs/security/threat-models/e42-admin.md` §9.2 (AC-ADM-01 to AC-ADM-35) and the user-lifecycle
  annex `docs/security/threat-models/e42-user-lifecycle.md` §4 (UL-AC01 to UL-AC16), handed off on
  #890 (E42-X01). E09's cases are referenced, not repeated (`docs/security/abuse-cases/e09-auth.md`).
- Method: white-box and in-process, through the real `create_app()`, with the real `AuthService`
  (sessions, MFA, step-up and its B16 chart) over in-memory fakes, a fixed clock and no network
  (C-13.5). The audit stand-ins refuse an unregistered action as `AuditWriter.emit` does, so every
  asserted record is one production could write. The races and the append-only case run on real
  Postgres 16 in the integration lane. Every automated case is a permanent regression.
- Where they live: `services/api/tests/security/admin/` (the RBAC cells, the meta-tests and the
  abuse cases); `services/api/tests/integration/admin/test_admin_abuse_pg.py` (the last-owner
  races and the disabled invitee's old link);
  `services/api/tests/integration/audit/test_audit_guard_privileged_role.py`.
  `test_abuse_catalogue.py` fails when a seed of the model or the annex has no row here, when a
  cited test does not exist, when a verdict is not a word of the key below, when a waiting row
  names no issue, or when a row with any verdict word besides WAITING cites no test.
- Verdict key:
  - **SUITE**: an RBAC cell holds it (every admin and users route × every actor × every elevation
    state);
  - **NEW**: a case this ticket adds;
  - **COVERED**: an existing test holds it, cited;
  - **PIN**: `main` differs from the seed; an `xfail(strict=True)` names the issue (or, where no
    issue tracks the gap, its threat-model row, as X03-F6 does), so it turns red the day it is
    fixed;
  - **WAITING**: the route or the decision is not on `main`; the row names the ticket. Never
    skipped.
- Rule ids (verified in `CONSTITUTION.md`): C-2.9 (audit), C-4.14 (flags never gate a control),
  C-6.5 (the problem `code`), C-12.2, C-12.4 (RBAC server-side), C-13.5, C-13.7.

## Rules the RBAC cells hold

The cells (`test_cells_none.py`, `test_cells_stale.py`, `test_cells_fresh.py`) cover each executed
admin and users route of the route matrix (40 at the time of writing), and `rewrapKek` in the none
and stale states (rule 8). For each signed-in actor in each elevation state, they assert the
status, the problem `code`, the audit record and the denial count. Elevation is real session
state, decided by the production `StepUpService`:

- **none**: the session never stepped up;
- **fresh**: a live window for every grace class the routes demand, or a one-shot grant bound to
  the very request for a no-grace class (#2304);
- **stale**: every window past `GRACE_WINDOW`, or the one-shot grant past `SINGLE_USE_WINDOW`.

The expectations come from three reviewed sources: `matrix.yaml` (the role outcome), the step-up
registries of `api/step_up.py` (path-gated before RBAC, handler-gated after it), and the guard kind
(`admin_router`, found by its `admin_area` dependency, or the reviewed `OWN_GUARD` table).

1. A denial (403 `forbidden`) writes its record for the caller (on `admin_router`,
   `admin.area_entered`, outcome `denied`, naming the route) and adds one to
   `authz_denied_total{permission}` (SR-125). A silent denial fails.
2. A step-up challenge (403 `step_up_required`) is a challenge, not a denial (decision D6 on
   #1026). It is audited as `auth.step_up_required` naming its class; no denial counter is asserted.
3. An allowed call on `admin_router` writes `admin.area_entered`, outcome `success`, naming the
   route. A call let through by a grace window writes `auth.step_up_grace_used` naming its class.
   An allowed call on an own-guard route asserts no record: with the matrix's bodies most of them
   answer 4xx or `501` before acting, so their action records rest on their own tests until #2836
   moves them onto `admin_router` (SR-E42-09).
4. Elevation never stands in for a permission. A Manager or Viewer holding every grace window is
   still refused wherever the matrix refuses it.
5. The suite maintains itself (`test_suite_meta.py`). A served admin route that is neither on
   `admin_router` nor in `OWN_GUARD` fails, named. An `admin_router` permission that differs from
   the contract's `x-rbac` fails. Three failures are shown in memory: an unguarded probe route
   turns its cells red, an admin route whose `admin.area_entered` record is dropped fails its
   record cell, and a guard whose permission is edited away from the contract's fails the
   permission check. Each restores what it changed. A PR that mounts an admin or users route must
   put it on `admin_router` or give it an `OWN_GUARD` row, and a `GATE_REQUESTS` row if its gate
   needs a body; the in-flight #3084 and #3319 will meet this, as #2649's four routes and #3085's start (S13b) did.
6. A handler that answers before its gate in the app as wired today is listed, with that status and
   its reason, in `BEFORE_GATE` (`_cells.py`): `deleteBackup` answers `501` until the backup engine
   passes an artefact remover (#3319), and `downloadAuditExport` `404` for the cell's job id, which
   names no job (#889 S9). Its allowed caller must get exactly that status; a challenge
   or any other answer fails the cell, so the row cannot excuse a wired handler.
7. A route the matrix makes public runs for every caller, the one with no session included:
   `downloadBackup`, whose single-use token is the credential (#966 BK-11), is in `OWN_GUARD`.
8. The served `not_executable` rows: `rewrapKek` (`POST /admin/keys/kek-rewrap`) has none and stale
   cells, which its `keys` path guard answers before any body is read. Past the guard its body is
   validated before RBAC and the CI app wires no credential store, so it has no fresh cell; each
   actor is held by `tests/unit/api/test_admin_kek.py` (#2266 D2). `PUT /admin/log-level` has no
   cell: every signed-in caller gets `501` before any guard reads a role (X03-F5), and its guard is
   held by `tests/unit/observability/test_log_level_override.py::test_endpoint_viewer_denied_and_audited`.
9. What the cells do not assert: that state is unchanged after a denial (they read statuses and
   records; the abuse cases check the stores where a seed says so), and a record or a count for a
   caller with no session, refused with 401 or, on a write, the CSRF guard's 403: there is no
   principal to record (AC-ADM-02 requires none).

## The ticket's named cases

<!-- prettier-ignore -->
| Ticket case | Seed | Verdict | Evidence or ticket |
| --- | --- | --- | --- |
| Invite-link replay | AC-ADM-27 | NEW | `tests/security/admin/test_admin_abuse_cases.py::test_ac_adm_27_a_spent_invite_link_answers_as_an_unknown_one`; the service level is `tests/security/auth/test_stepup_invite_abuse.py::test_ac_inv_03_reuse_after_acceptance_rejected` |
| TOTP replay | AC-ADM-05 | NEW | `tests/security/admin/test_admin_abuse_cases.py::test_ac_adm_05_a_replayed_code_strikes_three_times_then_the_session_reads_only` |
| Grant self-assignment | AD-E05 | NEW | `tests/security/admin/test_admin_abuse_cases.py::test_parallel_grant_self_assignments_by_the_owner_all_fail_and_each_is_audited`. Testable today: `setUserAccountAccess` is served (E42-T08, #3267); the claim on #1026 thought it waited on E42-T08 |
| Role escalation under concurrent writes | AC-ADM-28, AC-ADM-29 | NEW | `tests/security/admin/test_admin_abuse_cases.py::test_parallel_self_promotions_by_a_manager_all_fail_and_each_is_audited`; `tests/integration/admin/test_admin_abuse_pg.py::test_ac_adm_28_mutual_demotions_leave_one_winner_and_an_owner_every_round`. Testable today: `setUserRoles` is served; the claim thought it waited on E42-T09 |
| Last-owner removal | AC-ADM-28, UL-AC03 | NEW | `tests/integration/admin/test_admin_abuse_pg.py::test_ac_adm_28_mutual_demotions_leave_one_winner_and_an_owner_every_round`, `::test_ul_ac03_a_disable_racing_a_demotion_leaves_one_winner_and_an_owner_every_round` (ten raced rounds each: a round counts only when the loser met the floor, 409; a round the race missed is retried and never counted) |
| Audit mutation attempts (API and database) | AC-ADM-15 | NEW | `tests/security/admin/test_admin_abuse_cases.py::test_ac_adm_15_no_route_mutates_the_audit_log`; `tests/integration/audit/test_audit_guard_privileged_role.py::test_a_privileged_role_that_is_not_the_owner_is_refused_by_the_triggers` |
| Export range and rate abuse | AC-ADM-20 | COVERED | `tests/unit/api/test_audit_export_route.py::test_a_request_the_contract_refuses_is_422_naming_no_value` (a window over the maximum, `max_export_range`), `::test_one_export_at_a_time_and_none_while_a_rotation_runs` (409), `::test_only_an_export_whose_job_is_created_counts_toward_the_hour` (429) (#889 S10, which replaced the 501) |
| View-as attempting a mutation | AC-ADM-22 | NEW, COVERED | `tests/security/admin/test_admin_abuse_cases.py::test_ac_adm_22_view_as_cannot_mutate`; the rest of the seed is held where its row below cites it (#3085) |
| Flag write without step-up | AC-ADM-06, AC-ADM-07 | SUITE, NEW | The cells (`PUT /admin/feature-flags/{flagKey}`, Owner none and stale); `tests/security/admin/test_admin_abuse_cases.py::test_ac_adm_06_the_live_gate_needs_its_own_step_up_and_its_evidence_first`, `::test_ac_adm_07_a_kill_switch_releases_only_on_its_own_class_and_maintenance_engages_on_flags` |
| Restore without maintenance mode | AC-ADM-23 | COVERED, WAITING | The service: `tests/unit/admin/test_restore_guard.py::test_maintenance_off_is_409_maintenance_mode_required_and_creates_no_job`. The route waits on #3084 (AD-F02) |
| Backup download URL reuse after expiry | AC-ADM-26 | COVERED | The store: `tests/unit/admin/test_download_links.py::test_consume_is_single_use_under_concurrency`, `::test_an_ended_link_is_gone_for_an_hour_then_unknown`. The route, since E42-T05 BK-11 (#966): `tests/unit/api/test_admin_backup_download_router.py::test_a_link_serves_the_artefact_once_as_an_attachment_then_is_410`; `tests/unit/admin/test_backup_fetch.py::test_a_spent_link_is_410_and_link_reused_once_within_its_hour_then_404`, `::test_an_expired_link_never_spent_is_410_with_no_record` |

## AC-ADM-01 to AC-ADM-35 (`e42-admin.md` §9.2)

Test paths are under `services/api/`; `::name` continues the path before it.

<!-- prettier-ignore -->
| Id | Verdict | Evidence or ticket |
| --- | --- | --- |
| AC-ADM-01 | SUITE, PIN | Every cell of M and V (`tests/security/admin/test_cells_none.py::test_route_answers_each_actor_as_the_matrix_and_gate_say`, `::test_answer_writes_the_audit_record_its_guard_owes`, `::test_denial_is_counted`); `tests/unit/admin/test_admin_http.py::test_rbac_cell_on_any_admin_route`. AD-F22 is fixed on `main` (`GET /admin/health` and `GET /admin/jobs/{jobId}` are on `admin_router`). Pins X03-F1 and X03-F2, #2836 |
| AC-ADM-02 | SUITE, PIN | `tests/security/admin/test_cells_none.py::test_caller_without_a_session_meets_the_guard_the_matrix_names`, `::test_no_session_refusal_carries_the_registry_code`. Pins AD-F24 (#2304), X03-F6 (no issue) and X03-F1 (#2836) |
| AC-ADM-03 | SUITE | The Owner cells in states none and stale; `tests/unit/api/test_dangerous_route_registry.py::test_every_mounted_step_up_operation_is_gated_or_allow_listed`; `tests/unit/api/test_step_up_audit_backups.py::test_audit_export_on_create_app_needs_step_up_then_reaches_the_handler` |
| AC-ADM-04 | COVERED | `tests/security/auth/test_stepup_invite_abuse.py::test_ac_stepup_01_elevation_not_transplantable_across_session_or_action`; `tests/unit/api/test_step_up_binding_router.py::test_bound_grant_refuses_a_swapped_payload`, `::test_mismatch_is_never_answered_unaudited` |
| AC-ADM-05 | NEW | `tests/security/admin/test_admin_abuse_cases.py::test_ac_adm_05_a_replayed_code_strikes_three_times_then_the_session_reads_only`; the service: `tests/unit/auth/test_step_up.py::test_replayed_code_is_rejected` |
| AC-ADM-06 | NEW | `tests/security/admin/test_admin_abuse_cases.py::test_ac_adm_06_the_live_gate_needs_its_own_step_up_and_its_evidence_first`: the challenge (`live_enablement`) and its `auth.step_up_required`, then the 422 before any step-up and its `flags.change` failure, the flag unchanged; the writer: `tests/unit/admin/test_flag_writes.py::test_invalid_writes_are_refused_before_the_gate_and_audited` |
| AC-ADM-07 | NEW | `tests/security/admin/test_admin_abuse_cases.py::test_ac_adm_07_a_kill_switch_releases_only_on_its_own_class_and_maintenance_engages_on_flags`: the release's challenge (`killswitch`) and its `auth.step_up_required`, the switch still engaged; then `maintenance.mode` engaged on the same `flags` grant, with its `auth.step_up_grace_used`, `flags.change` and `maintenance.enabled`. The engage's effects: `tests/unit/admin/test_flag_maintenance.py::test_entering_maintenance_cancels_algos_and_notifies_once` |
| AC-ADM-08 | COVERED | `tests/unit/admin/test_flag_writes.py::test_invalid_writes_are_refused_before_the_gate_and_audited` (`overrides_not_allowed`) |
| AC-ADM-09 | COVERED | `tests/unit/admin/test_flag_resolver.py::test_safety_flags_ignore_every_override_and_fail_closed`, `::test_an_unreadable_row_ignores_its_overrides_too`; `tests/unit/admin/test_flag_service.py::test_every_safety_flag_ignores_override_rows_at_resolution` |
| AC-ADM-10 | COVERED | `tests/unit/admin/test_flag_routes.py::test_a_stale_write_is_409_with_the_flag_as_it_stands`, `::test_a_conflict_answers_the_current_flag_resolved_for_the_callers_role` |
| AC-ADM-11 | COVERED | `tests/unit/ws/test_system_filter.py::test_a_nested_object_reaches_the_owner_whole`; `tests/unit/ws/test_system_topic_roles.py::test_a_manager_learns_an_all_roles_flag_and_never_an_owner_only_one` |
| AC-ADM-12 | COVERED, WAITING | The gate: `tests/unit/domain/test_order_entry.py::test_a_gate_cannot_be_built_without_its_maintenance_check`. The end-to-end case waits on `POST /orders`, served by E29-T07 (the OMS REST surface) |
| AC-ADM-13 | NEW | `tests/security/admin/test_admin_abuse_cases.py::test_ac_adm_13_create_app_refuses_a_flag_that_gates_authentication` (owed by E42-T03, #964, which closed without it); the registry: `tests/unit/admin/test_flag_registry.py::test_the_denied_category_truth_table`, `::test_registry_rechecks_every_spec_at_startup` |
| AC-ADM-14 | WAITING | E42-X03's PR-2 (#1026): Semgrep rule 2 with one fixture per protected package |
| AC-ADM-15 | NEW | `tests/security/admin/test_admin_abuse_cases.py::test_ac_adm_15_no_route_mutates_the_audit_log`; `tests/integration/audit/test_audit_guard_privileged_role.py::test_a_privileged_role_that_is_not_the_owner_is_refused_by_the_triggers` (owed by the model's §12.1); held already: `tests/integration/audit/test_audit_guard_cv_app.py::test_cv_app_cannot_rewrite_audit_history`, `tests/integration/audit/test_audit_repository.py::test_truncate_refused_even_for_owner` |
| AC-ADM-16 | COVERED | `tests/integration/audit/test_audit_repository.py::test_two_connection_inserts_link_in_id_order` (#889 S3: 1,000 inserts on two connections, one a raw INSERT, then verify), `::test_wal_path_and_in_transaction_inserts_interleave_into_one_verified_chain` |
| AC-ADM-17 | COVERED | `tests/unit/api/test_audit_router.py::test_cross_actor_filter_is_recorded_in_canonical_form_then_narrowed`, `::test_manager_query_sees_only_own_events_redacted` |
| AC-ADM-18 | COVERED | `tests/unit/api/test_audit_router.py::test_refusals_write_at_most_the_hourly_cap_and_the_owner_still_reads`, `::test_refusal_carries_retry_after_only_over_the_cap` |
| AC-ADM-19 | COVERED | `tests/unit/api/test_audit_router.py::test_verify_span_over_the_cap_is_422_naming_the_limit`, `::test_verify_rate_limit_is_checked_before_single_flight` |
| AC-ADM-20 | COVERED | `tests/unit/api/test_audit_export_route.py::test_a_request_the_contract_refuses_is_422_naming_no_value` (a window over the maximum, `max_export_range`), `::test_one_export_at_a_time_and_none_while_a_rotation_runs` (409), `::test_only_an_export_whose_job_is_created_counts_toward_the_hour` (429); the record before the job exists: `::test_the_request_is_recorded_before_its_job_exists_and_the_completion_after` (#889 S10) |
| AC-ADM-21 | COVERED | `tests/unit/api/test_audit_export_download.py::test_each_refusal_comes_in_the_contracts_order`, `::test_another_owner_gets_the_404_of_an_unknown_job`, `::test_served_downloads_count_against_the_hour`; `tests/unit/api/test_admin_jobs_router.py::test_every_404_is_not_found_with_rule_job_unknown` (#889 S9); end to end, `tests/unit/api/test_audit_export_route.py::test_end_to_end_one_digest_signed_by_the_pinned_key_and_no_other` (#889 S10) |
| AC-ADM-22 | NEW, COVERED | `tests/security/admin/test_admin_abuse_cases.py::test_ac_adm_22_view_as_cannot_mutate`: an Owner starts view-as on a Manager through the real `POST /admin/view-as` (201, read back `active` by `GET /auth/session/view-as`, with one `admin.view_as_started` naming the request's address, and the Manager's notice), then sends every state-changing operation the app serves, read from its router (64 of the 71; the other 7 are the viewer's own, the contract's list): each is 403 `view_as_read_only`, nothing changes (roles, grants, sessions, and an audit trail of the refusals alone) and each is one `admin.view_as_refused` naming the viewer and the viewer's session, counted in `auth_view_as_refused_total`. No protective write is registered, so none is carved out. A second start is 409 `view_as_active`, leaving is 204 with one `admin.view_as_ended` (reason `ended`, naming the leave's address), and the same write is then accepted. The rest of the seed: the Owner target and the second start, `tests/unit/api/test_view_as_start_route.py::test_each_refusal_comes_in_the_contracts_order`; a WS action frame, `tests/unit/ws/test_view_as_frames.py::test_a_viewing_sessions_action_frame_is_refused_recorded_and_the_socket_stays`; reads in the target's scope, `tests/contract/rbac/test_view_as_matrix.py::test_an_owner_viewing_as_a_target_reads_as_the_target`; the cap of 120 an hour, `tests/unit/api/test_view_as_refusals.py::test_recorder_writes_up_to_120_records_an_hour_per_viewer`; the 30 minutes ending on the server's clock with one `admin.view_as_ended` (reason `expired`), `tests/unit/admin/test_view_as_sweeper.py::test_expiry_ends_without_any_request`, and a held context answering a read, HEAD, OPTIONS or write 403 `view_as_expired`, `tests/unit/api/test_view_as_gate.py::test_held_read_refused_view_as_expired`, `::test_a_live_head_or_options_passes_as_the_target_and_a_held_one_is_refused`, `::test_held_write_refused_view_as_expired_and_changes_nothing`; the end, 204 with one record, and none for a held one, `tests/unit/api/test_view_as_routes.py::test_delete_ends_and_clears_a_live_context_and_records_it_once`, `::test_delete_clears_a_held_context_and_records_nothing`. The contract is pinned by `tests/contract/test_admin_view_as_contract.py` |
| AC-ADM-23 | COVERED, WAITING | `tests/unit/admin/test_restore_guard.py::test_maintenance_off_is_409_maintenance_mode_required_and_creates_no_job`, `::test_preconditions_are_checked_in_the_contract_order`. The route waits on #3084 (AD-F02) |
| AC-ADM-24 | WAITING | #3084, Owner decision D7 |
| AC-ADM-25 | COVERED, WAITING | The restore guard: `tests/unit/admin/test_restore_guard.py::test_a_backup_whose_digest_differs_from_its_bound_record_is_not_usable`; verify, digest first, since E42-T05 BK-9 (#966): `tests/unit/admin/test_backup_verify.py::test_digest_mismatch_fails_the_job_with_checksum_mismatch_and_marks_the_row_failed`, `::test_mismatch_never_calls_the_verifier`. Through the routes it waits: `verifyBackup` answers `501` until the backup engine wires a verifier (#3319), and `restoreBackup` is not mounted (E42-T05, #966) |
| AC-ADM-26 | COVERED | `tests/unit/admin/test_download_links.py::test_consume_is_single_use_under_concurrency`, `::test_expiry_is_five_minutes_on_the_server_clock`. The route and the service's steps, since E42-T05 BK-11 (#966): `tests/unit/api/test_admin_backup_download_router.py::test_a_link_serves_the_artefact_once_as_an_attachment_then_is_410`, `::test_a_bearer_is_optional_but_one_sent_must_resolve_and_names_its_user`; `tests/unit/admin/test_backup_fetch.py::test_a_spent_link_is_410_and_link_reused_once_within_its_hour_then_404`, `::test_the_oldest_spent_link_once_more_than_1024_ended_is_404_and_no_link_reused`, `::test_a_link_issued_before_a_restart_is_404_with_its_issued_record_alone`, `::test_the_events_that_end_the_grant_end_the_link_after_its_spend`, `::test_a_rotation_or_an_event_before_the_issue_does_not_end_the_link`, `::test_two_concurrent_fetches_serve_once`; the token in no log line: `tests/unit/observability/test_backup_token_never_logged.py::test_access_log_line_never_carries_the_token` |
| AC-ADM-27 | NEW, PIN | `tests/security/admin/test_admin_abuse_cases.py::test_ac_adm_27_a_spent_invite_link_answers_as_an_unknown_one`; the pin `::test_ac_adm_27_create_user_refuses_mfa_not_required` (AD-F10, #3086) |
| AC-ADM-28 | NEW | `tests/integration/admin/test_admin_abuse_pg.py::test_ac_adm_28_mutual_demotions_leave_one_winner_and_an_owner_every_round`: ten raced rounds, each loser 409 with one `rbac.denied` (`owner_floor`) and no change record (owed by E42-T09 in the model, whose case through the routes over the real stores has shipped too: `tests/integration/admin/test_user_admin_pg.py::test_ten_parallel_demotions_one_wins`, #2649) |
| AC-ADM-29 | COVERED | `tests/security/auth/test_role_revoked_mid_step_up.py::test_role_revoked_between_step_up_challenge_and_completion_refuses_the_retry`, `::test_role_revoked_while_the_action_awaits_authorisation_is_refused` |
| AC-ADM-30 | COVERED, WAITING | Today's behaviour is pinned by `tests/unit/admin/test_admin_http.py::test_a_missing_or_stale_step_up_never_refuses_the_route`; it flips with decision D8 (E42-T06, #1085) |
| AC-ADM-31 | WAITING | SR-E42-06, #3196 |
| AC-ADM-32 | SUITE, COVERED | `tests/unit/api/test_deny_by_default.py::test_unmatched_route_is_404_and_never_reaches_a_handler` |
| AC-ADM-33 | COVERED, WAITING | The override logic: `tests/unit/observability/test_log_level_override.py::test_override_scoped_and_expires`. The route answers 501: `create_app` mounts the log-level router with no principal resolver, under a comment naming E09-S03, which shipped. No open ticket owns the wiring: X03-F5 |
| AC-ADM-34 | COVERED, WAITING | `tests/unit/api/test_audit_router.py::test_manager_verify_audit_chain_returns_403`. `getSecuritySummary` waits on E43-S02 |
| AC-ADM-35 | COVERED, WAITING | `tests/unit/ws/test_system_filter.py::test_manager_and_viewer_receive_only_the_role_neutral_fields`; `tests/unit/ws/test_system_topic_roles.py::test_the_notices_after_the_first_auth_ok_follow_the_principal`. Engage-to-frame waits on #956 (E39-S03) |

## UL-AC01 to UL-AC16 (`e42-user-lifecycle.md` §4)

<!-- prettier-ignore -->
| Id | Verdict | Evidence or ticket |
| --- | --- | --- |
| UL-AC01 | COVERED | `tests/security/auth/test_disable_user_e2e.py::test_rest_401_ws_4403_within_5s`; `tests/security/auth/test_disable_user_drill.py::test_a_disable_through_the_route_ends_a_private_subscription_with_bye_and_4403`, `::test_a_disable_through_the_route_reaches_the_socket_within_the_sr029_bound` |
| UL-AC02 | COVERED | `tests/unit/test_user_cascade_wiring.py::test_disarms_owner_user_id_rules`, `::test_scope_refresh_failure_fails_closed`; `tests/integration/storage/test_rule_perms_status_pg.py::test_disabled_user_no_rule_perms` |
| UL-AC03 | COVERED, NEW | The store: `tests/integration/admin/test_user_lifecycle_pg.py::test_concurrent_demote_and_disable_keep_owner`; one disable: `tests/unit/api/test_users_delete.py::test_last_owner_409`; the route race of a disable against a demotion: `tests/integration/admin/test_admin_abuse_pg.py::test_ul_ac03_a_disable_racing_a_demotion_leaves_one_winner_and_an_owner_every_round` (ten raced rounds; the loser 409 with no change record, a losing demotion one `rbac.denied` `owner_floor`; in-process the disable reaches the lock first in nearly every round (195 of 200 in a replay), so the losing-disable half (no `rbac.denied`, UL-F13) is held on every run by the store test and `test_last_owner_409`, and by this test only in the rounds the demotion wins); of two demotions: `::test_ac_adm_28_mutual_demotions_leave_one_winner_and_an_owner_every_round`. The `PATCH` variant, since E42-T09 (#2649): `tests/integration/admin/test_user_admin_pg.py::test_patch_disable_vs_demote_keeps_owner` and `::test_ten_parallel_demotions_one_wins` (its `PATCH`-loser rounds), and at route level `tests/unit/api/test_user_admin_routes.py::test_last_owner_demotion_is_409_with_one_owner_floor_denial` and `::test_patch_disable_of_the_last_owner_is_409_and_audit_down_503` |
| UL-AC04 | COVERED | `tests/unit/api/test_users_delete.py::test_positions_unknown_409` |
| UL-AC05 | COVERED | `tests/unit/api/test_users_delete.py::test_audit_down_503`; `tests/unit/api/test_users_router.py::test_put_roles_audit_unavailable_rolls_back_with_503`; `tests/unit/api/test_users_account_access_put.py::test_stepup_and_audit_503` |
| UL-AC06 | COVERED, SUITE | `tests/unit/api/test_users_delete.py::test_forbidden_manager_viewer_audited`; `tests/unit/api/test_users_account_access_put.py::test_forbidden_manager_viewer_audited`; the cells of every lifecycle route |
| UL-AC07 | COVERED | `tests/integration/storage/test_account_access_store_pg.py::test_keeps_freeze_and_cap` |
| UL-AC08 | COVERED | `tests/unit/api/test_users_account_access_put.py::test_put_replaces_the_grants_and_pushes_after_the_commit`; `tests/contract/rbac/test_scope_and_ws.py::test_in_flight_subscription_gets_revoked_when_the_grant_is_withdrawn` |
| UL-AC09 | COVERED | `tests/unit/api/test_users_account_access_put.py::test_unknown_account_404` |
| UL-AC10 | COVERED | Since E42-T09 (#2649): `tests/unit/api/test_user_admin_routes.py::test_mfa_required_false_400`, `::test_invited_or_locked_400`, `::test_an_invited_or_locked_user_is_not_enabled` (each 400, nothing written) |
| UL-AC11 | COVERED | Since E42-T09 (#2649): `tests/unit/api/test_user_admin_routes.py::test_no_token_material`, `::test_other_users_session_404`; on the deployed app, `tests/security/auth/test_user_admin_e2e.py::test_other_users_session_404_on_both_paths` |
| UL-AC12 | WAITING | The purge reaper: E42-T10 (#2650) |
| UL-AC13 | WAITING | Re-enable has shipped (E42-T09, #2649); the reaper it races waits on E42-T10 (#2650) |
| UL-AC14 | NEW | `tests/integration/admin/test_admin_abuse_pg.py::test_ul_ac14_a_disabled_invitee_cannot_complete_the_old_invite`: on the deployed app, the old link's validate, redeem and confirm each answer 404 after the disable, the user stays `disabled`, and the disable wrote `users.invite_revoked`; the cascade step: `tests/unit/admin/test_user_disable.py::test_invited_revokes_invite` |
| UL-AC15 | COVERED, WAITING | `tests/unit/admin/test_user_disable.py::test_open_orders_left_and_counted`. The unbind waits on E42-T08 (#2648) |
| UL-AC16 | COVERED, SUITE | Without the step-up: the cells of `PATCH /users/{userId}`, Owner none and stale (the path guard challenges any body), and `tests/unit/api/test_user_admin_routes.py::test_patch_without_step_up_is_challenged_and_changes_nothing`; with it, since E42-T09 (#2649): `::test_enable_audited_ahead` (one `users.enable`, written ahead, before and after), `::test_enable_no_regrant` (no grant or session comes back), and its grant half over the real stores, `tests/integration/admin/test_user_admin_pg.py::test_enable_no_regrant` |

## Findings

Each was found by the suites on `main`. Under the filing freeze of 2026-10-19 none opens an issue:
each is pinned against the issue that owns its fix, or recorded for the orchestrator. Ratings use
the model's matrix (`e42-admin.md` §1.4). A disposition that names an owner reads `A:` (accepted
by the decision named), `M:` (routed by the threat model to the issue that owns the fix) or `T:`
(tracked by the issue filed for it); the others say what closed, fixed or recorded the finding.

<!-- prettier-ignore -->
| Id | Finding | STRIDE | L x I, risk | Disposition |
| --- | --- | --- | --- | --- |
| X03-F1 | `GET /admin/support-bundle/{job_id}` refuses a Manager or Viewer with no audit record, no denial count and no problem `code` (the `status` handler of `make_support_bundle_router`; its 401 has no `code` either) | R | M x L, Low | M: #2836 (SR-E42-09, one budgeted guard for every admin refusal). Pinned: the record, count and code cells |
| X03-F2 | The own guards of `/admin/audit*`, the support-bundle `POST`, recorder import, compact and purge audit their refusals but add nothing to `authz_denied_total`; the support-bundle and recorder refusals also carry no problem `code` (C-6.5; the `create` handler of `make_support_bundle_router`, the `import_archive` and `compact` handlers of `make_recorder_admin_router`, and the RBAC refusal of `make_recorder_purge_router`) | R (detection) | M x L, Low | M: #2836. Pinned: the count and code cells |
| X03-F3 | A `403 step_up_required` is audited (`auth.step_up_required`, by B16) but counted by no metric (`auth/metrics.py` counts grants and wrong codes only) | R (detection) | L x L, Low | A: decision D6 on #1026 (a challenge is not a denial); the cells assert its record |
| X03-F4 | Semgrep 1.181.0 matches no `async def` pattern in a file that uses PEP 695 generics, and reports a clean parse; every existing rule also carries a `def` alternative, so none was found blind on `main` | — (tooling) | Low | Recorded (D10). The PR-2 rules use `def` patterns, each with a `def f[T]` fixture |
| X03-F5 | `PUT /admin/log-level` is mounted with no principal resolver, so it answers 501 to everyone (`create_app` mounts the log-level router under a comment naming E09-S03, which shipped); its refusals carry no `code` | D (availability) | L x L, Low | Recorded for the orchestrator: no open ticket owns the wiring |
| AD-F24 | 401 `code` `unauthorized`, not the registry's `unauthenticated` (the `_session` helper of `make_step_up_router`) | contract | M x L, Low | M: #2304 (the model's routing; `api/users.py`'s half was met by #2649). Pinned: `test_no_session_refusal_carries_the_registry_code` |
| X03-F6 | `GET /users/invites` answers a caller with no session 401 with no problem `code` at all (the `_owner` check of `make_invites_router`). AD-F24's owners name `api/users.py` (#2649, met) and `api/step_up.py` (#2304), not the invites router, so no issue tracks it | contract | M x L, Low | Recorded under the filing freeze; the nearest finding is AD-F24 (`e42-admin.md` §13.1). Pinned: `test_no_session_refusal_carries_the_registry_code` |
| AD-F10 | `POST /users` accepts `mfa_required: false` (the default of `InviteCreateRequest.mfa_required`; C-12.2) | S | L x H, Medium | M: #3086. Pinned: `test_ac_adm_27_create_user_refuses_mfa_not_required` |
| X03-F7 | An admin refusal's record carries its request id only where the id reaches the emitter: the admin principal (`api/audit_principal.py`) reads `X-Request-Id`, the correlation middleware assigns `X-Correlation-Id`, the web client sends neither, and the invites router's owner check passes none to `enforce`. So the admin-area, support-bundle, recorder, retention and invites records of a real session carry `request_id` NULL (C-2.9). The nightly's first authenticated run matched 3 of 36 refusals by id | R | H x L, Medium | Closed by #3990 (#4001, #4042): every refusal record carries its request id. The nightly sends both headers, matches every refusal by id and fails on a denied record without one. For the step-up routes the gate proves the step-up refusal (`auth.step_up_required`, answered before RBAC), and the RBAC cells (`tests/security/admin/`) hold RBAC itself. Pinned: `tests/security/admin/test_audit_request_id.py` and `test_audit_request_id_stale.py` |
| X03-F8 | ZAP 2.17.0, which the admin profile pins and where this was verified, expands no `${VAR}` inside a replacer rule (its rules skip the plan's variable step), so the bearer reached the API as the literal placeholder: the scan ran signed out, and a CSRF 403 passed for a planned refusal. `.zap/rules-low-priv.yaml` and `.zap/market-data.yaml` pin ZAP 2.16.1 and still send their bearer that way: by the same code they run signed out too, but that is not verified on 2.16.1 | — (tooling) | Low | Fixed here for the admin profile (`security/zap/role_session.js`); T: #3991 for the other two |
| X03-F9 | The API's JSON responses carry no `X-Content-Type-Options: nosniff` (ZAP 10021, Low, on `GET /me` in the nightly's first full scan; only the backup download and the desktop shell's own files set it). The responses are `application/json` or `application/problem+json`, which a browser does not render as a document | I | L x L, Low | Closed by #3990 (#4001): `NoSniff` stamps every response. Pinned: `tests/unit/api/test_response_headers.py::test_every_http_answer_carries_nosniff_exactly_once`. The nightly cannot demonstrate a header or CSP check of the admin routes: at its default threshold ZAP's 10021 reads no error response, and the scanning roles got no 2xx from the admin surface in any run |

No Critical or High finding: none needs a remediation ticket before the epic closes.

## Traceability (`docs/plan/04-security-program.md`)

<!-- prettier-ignore -->
| Requirement | Held by |
| --- | --- |
| SR-017 (every route declares a capability) | The cells' classification, `test_guard_permission_matches_the_contract` and its in-memory drift control; deny-by-default at build (`tests/unit/api/test_deny_by_default.py::test_build_fails_for_route_without_declaration`) |
| SR-018, SR-151 (a matrix-driven authorisation test over every route and role) | The cells: route × actor × elevation state |
| SR-025 (step-up on dangerous actions) | The none, stale and fresh cells; AC-ADM-05, -06, -07 |
| SR-060 (every security-relevant event audited) | The record cells; AC-ADM-15 |
| SR-066 (append-only audit storage) | AC-ADM-15, both halves |
| SR-125 (denials counted) | The count cells; X03-F2, X03-F3 |
| SR-E42-07 (no flag reads in safety code; the boot refusal) | AC-ADM-13 now; Semgrep rule 2 in PR-2 |
| SR-E42-09 (one budgeted guard for every admin refusal) | The `OWN_GUARD` table, kept exhaustive by the meta-tests; X03-F1, X03-F2 |
| C-9.2 (a nightly DAST of the running app: OWASP ZAP; the ZAP row of `04-security-program.md` §12.1) | `dast-admin-nightly.yml` as a synthetic Manager and Viewer: the denial gate (AC5; `check_admin_denials.py`), the scan gate (`check_liveness.py`, `baseline_gate.py`); X03-F7 to X03-F9 |
| C-12.4 (RBAC server-side, deny by default) | The cells, and the probe-route meta-test |
