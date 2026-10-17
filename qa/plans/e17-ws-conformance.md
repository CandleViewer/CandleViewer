# E17 WebSocket protocol — conformance suite and black-box test plan

Ticket: E17-Q01 (issue #409). Owner: QA. Status: **Delivered — every socket-driven row runs under both subprotocols;
dry run recorded in `e17-ws-conformance-dryrun-20261017.md`; Architect review and QA-lead sign-off pending the owner's
`approved` (§10).**

Written against the observable surface only: the `/ws` endpoint, the frames of `docs/plan/23-ws-protocol.md`
§3–§12 and the schemas of §13–§15 (bundled in `docs/plan/ws-schema.json`). Cases name wire fields, error codes
and close codes, never an internal class. The automated half lives in `services/api/tests/contract/ws/`
(§8); this plan is the human half required per story group by `03-testing-strategy.md` §11.1.

> **Deviations from the ticket** (recorded in the closing PR).
>
> - **Paths.** The ticket body names `tests/conformance/ws/` and `docs/qa/test-plans/e17-ws-protocol.md`.
>   This repo already keeps contract suites under `services/api/tests/contract/` and plans under `qa/plans/`
>   (every other epic; the required `contract` CI job collects the former), so both deliverables follow those
>   conventions. Branch prefix `chore/` because the pre-push hook rejects `test/`.
> - **In-process harness, no docker, no Bybit fixtures.** The ticket's harness drives a docker-compose server fed by
>   recorded Bybit fixtures (`03-testing-strategy.md` §4.1). This suite drives the real `make_ws_router` (with
>   `ConnectionRegistry`, `SequencingHub` and the topic emitters) in-process over a Starlette `TestClient`, with a fake
>   clock, fake identity and a fake snapshot source holding schema-derived samples and CVWB vectors. No Bybit payload
>   and no docker stack is involved. It asserts the transport contract only, as the ticket's out-of-scope list
>   asks; payload content stays with the producing epics.
> - **The schema bundle, not the generated types.** The ticket builds the harness on the generated `packages/protocol` types.
>   This one validates every frame it sends or receives against `docs/plan/ws-schema.json`, the bundle those types are
>   generated from, so a generator bug cannot mask a server bug either.
> - **No production `bucket_ms`.** AC5's bucket is computed by a reference algorithm in the suite, because the web client that
>   owns it (E21/E17-D03) does not exist yet. The rows, ladder, clamp and fallback are read from §6.1.1 and held against that
>   algorithm and the real server.
> - **C1–C12.** The ticket's Observability line names them. They are the client's obligations (E17-Q04), so the matrix prints a
>   pointer to E17-Q04, not a count.
> - **CI wiring.** See §10.

## 0. How to use this plan

- **Audience:** a QA engineer with a staging URL, a WS client of their own (e.g. `websocat`) and no source access.
- **Fixtures, not live Bybit.** Book/trade/bar state comes from the recorded corpus replayed into staging
  (`03-testing-strategy.md` §4.1); no case consumes exchange rate-limit budget. The automated half needs no corpus
  (see the deviations above).
- **Case id:** `E17-TC-<group><nn>`; groups A–E = §1–§5.
- **Case columns:** Case · Preconditions · Steps · Expected · Req (`S1`–`S14`, §16.1) · Automation (test name in
  `tests/contract/ws/`, a unit test named with its file, or `manual-only`).
- **Time:** cases that wait on a deadline (auth 10 s, heartbeat 45 s, token expiry) use the staging
  advanceable clock; no case depends on wall-clock luck.
- **Build status:** `shipped` = covered by a passing automated test; `pending` = needs a dependency not on
  `main` (marked, never counted as passing).
- **Client obligations C1–C12** are asserted from the client side in E17-Q04 (E2E); the §10.3 UI treatments each
  error class needs are recorded in §6 so Q04 can assert them.

## 0.1 Defect conventions

| Observation                                                                 | Severity                                 |
| --------------------------------------------------------------------------- | ---------------------------------------- |
| A frame violates its §13–§15 schema, or a sequence number is skipped/reused | `priority/p0` (R7 data accuracy)         |
| An undocumented error code reaches a client                                 | `priority/p0`                            |
| A server-initiated close without a preceding `bye`                          | `priority/p1`                            |
| Unknown option silently accepted                                            | `priority/p1`                            |
| Doc and server disagree on an optional field                                | `priority/p2` against whichever is wrong |

## 1. Group A — Lifecycle (§2, §4, §9; E17-S01)

| Case       | Preconditions               | Steps                                                                          | Expected                                                                          | Req      | Automation                                                                                                                   |
| ---------- | --------------------------- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------- |
| E17-TC-A01 | none                        | Open `/ws` with `Origin` not on the allow-list; separately with `Origin: null` | Upgrade refused before `accept`, close `4403`; the token verifier is never called | S13      | `test_s13_a_bad_origin_is_refused_before_accept_and_never_reaches_auth`                                                      |
| E17-TC-A02 | none                        | Open with only `cv.v2.json` offered                                            | Closed `1002`                                                                     | S13      | `test_s13_a_client_offering_no_recognised_subprotocol_is_closed_1002`                                                        |
| E17-TC-A03 | none                        | Offer `cv.v1.msgpack, cv.v1.json`                                              | `cv.v1.msgpack` echoed; the run speaks MessagePack                                | S13      | `test_s1_one_sub_ok_…[msgpack-preferred]`; the msgpack-only offer: `test_s13_f7_msgpack_only_offer_negotiates_cv_v1_msgpack` |
| E17-TC-A04 | none                        | `hello` then wait 10 s without `auth`                                          | `bye auth_timeout`, close `4401`                                                  | S11      | `test_s11_bye_precedes_close_for_a_client_that_never_authenticates`                                                          |
| E17-TC-A05 | none                        | Put a valid token in `?access_token=` and never send `auth`                    | Token never read; `auth_timeout` as A04                                           | S13      | `test_s13_a_token_in_the_query_string_is_never_read`                                                                         |
| E17-TC-A06 | `hello` done                | 3 `auth` frames with a bad token                                               | `err auth_failed` ×2 then `bye` + `4401`                                          | S10, S11 | `…_preceded_by_bye[*-auth_failed-4401]`                                                                                      |
| E17-TC-A07 | `hello` done                | 3 non-`auth` frames before `auth_ok`                                           | `err not_authenticated` ×2 then `bye` + `4401`                                    | S11      | `…_preceded_by_bye[*-not_authenticated-4401]`                                                                                |
| E17-TC-A08 | authenticated               | Send nothing for 45 s after the server's ping                                  | `bye heartbeat_timeout`, close `1001`                                             | S11      | `…_preceded_by_bye[*-heartbeat_timeout-1001]`                                                                                |
| E17-TC-A09 | authenticated               | Let the token expire with no re-`auth`                                         | `bye token_expired`, close `4401`                                                 | S11      | `test_integration_without_reauth_an_expired_token_closes_with_bye_4401`                                                      |
| E17-TC-A10 | subscribed to 2 topics      | Re-`auth` in place 60 s before expiry                                          | `auth_ok`; **no** `snap`, **no** `sub_ok`; sequences continue                     | §4.1     | `test_integration_token_expiry_reauth_in_place_preserves_subscriptions_and_sequences`                                        |
| E17-TC-A11 | authenticated               | Server planned shutdown                                                        | `d system shutdown_notice`, then `bye shutdown`, close `1001`                     | S11      | `…_preceded_by_bye[*-shutdown-1001]`                                                                                         |
| E17-TC-A12 | 8 sockets open for one user | Open a 9th                                                                     | Oldest idle gets `bye too_many_connections`, `4429`                               | S11      | `…_preceded_by_bye[*-too_many_connections-4429]`                                                                             |
| E17-TC-A13 | authenticated               | Disable the user / revoke the session in admin                                 | `bye user_disabled` `4403` / `bye session_revoked` `4401`                         | S7, S11  | `test_s7_user_disabled_…`, `test_s7_session_revocation_…`                                                                    |

## 2. Group B — Subscriptions and authorisation (§5, §6, §9.5; E17-S02)

| Case       | Preconditions                     | Steps                                                                                            | Expected                                                                                                                                                                                       | Req | Automation                                                                                  |
| ---------- | --------------------------------- | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- | ------------------------------------------------------------------------------------------- |
| E17-TC-B01 | authenticated                     | `sub` 7 topics mixing valid, unknown, bad depth, duplicate, unknown option and a scoped `orders` | One `sub_ok`, 7 results **in request order**, each `ok`/`error`; then one `snap` per accepted topic                                                                                            | S1  | `test_s1_one_sub_ok_result_per_requested_topic_in_request_order`                            |
| E17-TC-B02 | authenticated                     | `sub` whose every topic fails                                                                    | Still one result per topic, none `ok`                                                                                                                                                          | S1  | `test_s1_every_topic_failing_still_yields_one_result_each`                                  |
| E17-TC-B03 | authenticated                     | Per topic family and shape (all 20 registry rows), in `structured` and `binary`                  | `snap` (`s:1`, `reason:initial`) arrives before the first `d`                                                                                                                                  | S2  | `test_s2_snap_precedes_any_delta_on_every_topic_row` (generated from the topic registry)    |
| E17-TC-B04 | book not yet rebuilt              | `sub book…`, then upstream publishes                                                             | No `d` until a `snap` can be built                                                                                                                                                             | S2  | `test_s2_delta_is_suppressed_while_the_snapshot_cannot_be_built`                            |
| E17-TC-B05 | authenticated                     | `sub` with `snapshot:false` + provable/unprovable continuity                                     | Provable: deltas only. Unprovable: `snapshot_forced:true` and a `snap`                                                                                                                         | S2  | `test_s2_snapshot_false_…` (×2)                                                             |
| E17-TC-B06 | authenticated                     | Typo every declared option on every family                                                       | `invalid_options`, `field` = the bad key, nothing subscribed                                                                                                                                   | S12 | `test_s12_a_typo_of_every_declared_option_…` (130 generated rows)                           |
| E17-TC-B07 | subscribed                        | `ctl` with an unknown key; `ctl` widening `exchange_account_ids`                                 | `err invalid_options`                                                                                                                                                                          | S12 | `test_s12_unknown_options_on_ctl_…`, `test_s12_scope_options_cannot_be_widened_through_ctl` |
| E17-TC-B08 | manager with accounts A, B        | Withdraw B in admin while subscribed to `positions[A,B]`, `trades`, `orders[A]`                  | `permission_change`, then `revoked positions` (`account_scope_changed`, `removed_accounts:[B]`, `resubscribe_allowed:true`) within 1 s; `trades` and `orders` keep streaming with unbroken `s` | S7  | `test_s7_grant_withdrawal_emits_revoked_…`; `…_revoked_arrives_within_1s` (perf)            |
| E17-TC-B09 | subscribed to `orders` + `trades` | Remove `orders:read`                                                                             | `revoked orders` (`permission_revoked`, `resubscribe_allowed:false`); `trades` unaffected                                                                                                      | S7  | `test_s7_permission_loss_revokes_every_topic_of_that_family_only`                           |
| E17-TC-B10 | subscribed                        | Narrower permissions via in-place re-`auth`                                                      | `auth_ok` then `revoked`                                                                                                                                                                       | S7  | `test_s7_in_place_reauth_with_narrower_permissions_revokes_affected_topics`                 |
| E17-TC-B11 | subscribed                        | Engage the kill switch                                                                           | Every connected user re-evaluated                                                                                                                                                              | S7  | `test_s7_kill_switch_transition_reevaluates_every_connected_user`                           |
| E17-TC-B12 | authenticated                     | `sub orders` with no / another manager's account (raw frame)                                     | `account_scope_denied`/`forbidden` (adversarial depth is E17-X02)                                                                                                                              | S10 | `test_client_every_private_topic_requires_an_account_in_scope`                              |

## 3. Group C — Snapshot, sequence and resync (§7; E17-S03)

| Case       | Preconditions                                                               | Steps                                                                                                    | Expected                                                                                                                              | Req    | Automation                                                                                                                                       |
| ---------- | --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| E17-TC-C01 | 3 subscriptions                                                             | 8 concurrent writers, plus a client `resync` and a `ctl time_bucket_ms` mid-stream                       | Per `(ch, rs)`: `s` = 1,2,3… with no gap and no reuse; `previous_seq` = `s−1` on re-snaps                                             | S3     | `test_s3_sequence_increments_by_exactly_one_per_topic_under_concurrent_writes`, `test_s3_sequence_survives_resync_and_reconfigure_without_reuse` |
| E17-TC-C02 | `book` subscribed                                                           | Upstream `u` jumps 11 → 13                                                                               | `snap` `reason:upstream_desync`, `previous_seq` set, no `d` across the gap; deltas resume `s+1`                                       | §7.4   | `test_integration_upstream_u_gap_produces_snap_with_reason_upstream_desync`                                                                      |
| E17-TC-C03 | `book` subscribed                                                           | 5 `resync` in a minute, then a 6th                                                                       | 5 `snap client_resync`; 6th → `err resync_rate_limited` + `revoked`                                                                   | S10    | `test_s10_error_catalogue_is_closed_…` (path); behaviour: `test_sequencing_socket::test_socket_snap_follows_sub_ok_and_resync_loop_is_revoked`   |
| E17-TC-C04 | `bars` subscribed                                                           | Coalesced update (×4)                                                                                    | One `d`, `coalesced:true`, `coalesced_count:4`, **one** `s`                                                                           | S3     | `test_s4_coalescable_topics_do_mark_coalesced_deltas`                                                                                            |
| E17-TC-C05 | `orders`, `executions` subscribed with `throttle_ms:60000`, `coalesce:true` | Burst of 60 updates                                                                                      | `effective.throttle_ms:0`, `coalesce:false`; 60 individual `d`, `s` 2..61                                                             | S4     | `test_s4_orders_and_executions_are_never_coalesced_or_throttled`                                                                                 |
| E17-TC-C06 | 4 private topics for account A                                              | One fill event                                                                                           | Arrival order `executions → orders → positions → trade_groups`; other accounts see nothing                                            | S5     | `test_s5_private_frames_for_one_account_event_arrive_in_causal_order`                                                                            |
| E17-TC-C07 | a heuristic source: heatmap, a metrics series, a footprint imbalance        | Subscribe in each encoding                                                                               | `estimated:true`: heatmap field / header bit0; per metrics series; per footprint imbalance (structured only)                          | S8     | `test_s8_heuristic_heatmap_…`, `test_s8_metrics_payload_…`, `test_s8_footprint_imbalance_…`, `test_s8_every_estimated_field_…`                   |
| E17-TC-C08 | replay session `RS` (stub clock)                                            | `sub` with `replay_session_id`; publish recorded frames; seek                                            | `snap source:replay` with `rs` + `wt`; `d` has recorded `ts`; bit2 on binary; seek → `snap replay_seek` on every topic, `s` continues | S9     | `test_s9_replay_frames_…`, `test_integration_replay_subscribe_and_seek_emit_the_documented_series`                                               |
| E17-TC-C09 | replay reaches `to`                                                         | —                                                                                                        | `revoked replay_session_ended` per topic                                                                                              | §11    | **pending E26** (frame shape: `test_integration_replay_end_revoked_frame_shape_is_schema_valid`)                                                 |
| E17-TC-C10 | all six CVWB kinds                                                          | Decode each, validate against its structured schema; corrupt magic/version/kind/length                   | Valid decode ≡ structured form; every corruption → `frame_malformed`                                                                  | §16.4  | `test_contract_cvwb_kind_…`, `test_contract_a_corrupted_cvwb_layout_…`, `test_contract_binary_and_structured_snapshots_…`                        |
| E17-TC-C11 | —                                                                           | `heatmap_bucket_selection` over the six §6.1.1 rows, the 2500 ms clamp edge, and `time_bucket_ms` absent | 1000/1000/1000/1000/1000/5000; edge 2500→1000, 2500.1→5000; server applies 500; an edit to the document fails                         | §6.1.1 | `test_heatmap_bucket_selection_*`                                                                                                                |
| E17-TC-C12 | `book` subscribed                                                           | `ctl paused:true` (no `resnapshot`); two upstream updates; `ctl paused:false`                            | `ctl_ok resnapshot:true`, then `snap reason:reconfigure` holding the paused updates before any `d`; next `d` = `snap.s+1`             | §5.4   | `test_integration_ctl_pause_resume_resnapshots_with_the_paused_updates` (#2517, fixed by #2556)                                                  |

## 4. Group D — Backpressure and limits (§8.4, §16.2; E17-S01/T03)

| Case       | Preconditions                           | Steps                                                    | Expected                                                                                                  | Req     | Automation                                                                                                                                                 |
| ---------- | --------------------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| E17-TC-D01 | `orders` subscribed, client not reading | Produce more than the spec's 2 000-frame budget, at once | Queue never exceeds the budget; `bye slow_consumer`, close `4429`; `orders` is closed instead of degraded | S6, S11 | `test_s6_orders_overflow_is_bounded_by_the_spec_budget_then_slow_consumer_4429` (observable form against the spec's 2 000-frame budget; memory is E17-Q02) |
| E17-TC-D02 | authenticated                           | One frame > 256 KiB (text)                               | `bye frame_too_big`, close `1009`, never parsed                                                           | S11     | `…_preceded_by_bye[*-frame_too_big-1009]`                                                                                                                  |
| E17-TC-D03 | authenticated                           | > 30 frames in 1 s                                       | `err client_rate_limited`, then `bye` `4429` with `retry_after_ms:1000`                                   | S11     | `…_preceded_by_bye[*-client_rate_limited-4429]`                                                                                                            |
| E17-TC-D04 | authenticated                           | 51 topics in one `sub`                                   | The whole frame refused: one `err too_many_topics` (`field: topics`); nothing subscribed (#2292)          | S1      | `test_s1_a_sub_over_the_cap_is_refused_whole_and_is_no_strike`; behaviour: `test_gateway_limits::test_sub_frame_with_too_many_topics_is_refused_whole`     |
| E17-TC-D05 | authenticated                           | A queued backlog, then session revocation                | Queued frames dropped, `bye` still delivered                                                              | S11     | `test_s11_a_sealed_close_drops_queued_frames_but_still_delivers_bye`                                                                                       |

Chaos (60 s non-reading client, 5 000 msg/s burst, upstream kill) is E17-Q02; load is E17-Q03.

## 5. Group E — Client frames the server must reject (§4.4, §10; E17-S01)

| Case       | Steps                                                                                                 | Expected                                                    | Req | Automation                                                            |
| ---------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- | --- | --------------------------------------------------------------------- |
| E17-TC-E01 | Non-JSON text, truncated JSON, control bytes, 40-deep nesting, a binary WS frame                      | `err frame_malformed`, socket stays usable                  | S10 | `test_client_non_json_text_…`, `…deeply_nested…`, `…binary_ws_frame…` |
| E17-TC-E02 | Missing `t`; non-string `t`; unknown `t`; JSON array/string; every server-only `t` sent by the client | `err frame_malformed`                                       | S10 | `test_client_frames_the_server_must_reject_…` (20 rows)               |
| E17-TC-E03 | `resync` without `ch`, bad `reason`, unsubscribed `ch`; `ctl` on an unsubscribed `ch`; second `hello` | `frame_malformed` / `not_subscribed` / `protocol_violation` | S10 | same test                                                             |
| E17-TC-E04 | 3 bad frames                                                                                          | `bye bad_client`, `4400`                                    | S11 | `test_client_three_strikes_close_with_bye_4400`                       |
| E17-TC-E05 | Any frame before `hello`                                                                              | `bye protocol_violation`, `1002`                            | S11 | `test_client_frames_before_hello_close_with_bye_1002`                 |
| E17-TC-E06 | `snapshot:"yes"`, non-uuid `replay_session_id`                                                        | `invalid_options`                                           | S12 | `test_client_snapshot_and_replay_fields_are_type_checked`             |
| E17-TC-E07 | A frame of the other kind (text on msgpack, binary on JSON) holding a valid JSON frame                | `err frame_malformed`, socket stays usable                  | S10 | `test_client_ws_frame_of_the_other_kind_…`                            |

## 6. §10.3 UI treatment expected per error class (feeds E17-Q04)

| Class                   | Codes                                                        | Must the UI do                                                                              | Asserted by |
| ----------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------- | ----------- |
| Fatal, user must act    | `auth_failed`, `forbidden`, `user_disabled`                  | Modal; route to login or an explanatory screen; no auto-reconnect on `4403`                 | Q04         |
| Transient, self-healing | `degraded_data`, `exchange_unavailable`, `token_expired`     | Inline staleness badge + connection chip, no modal; `token_expired` → refresh and re-`auth` | Q04         |
| Client bug              | `protocol_violation`, `frame_malformed`, `invalid_options`   | Console error + "report a bug" toast; never swallowed                                       | Q04         |
| Capacity                | `slow_consumer`, `subscription_limit`, `client_rate_limited` | Toast advising fewer panes; auto-reduce throttles; full-jitter reconnect                    | Q04         |

Reconnect policy by close code (C7): do not auto-reconnect on `1002`, `4400`, `4403`.

## 7. Findings against the current build (carried to the ticket; see PR)

| #   | Observation                                                                                                                                                                                                                                                               | Where                                                                                        | Status                                                                                         |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| F1  | **Every server `err` frame omits `p.message`**, which `common.schema.json#/$defs/error` requires.                                                                                                                                                                         | any `err`, e.g. `{"t":"err","p":{"code":"frame_malformed","retryable":false,"close":false}}` | Closed by #2520 (#2395).                                                                       |
| F2  | **`sub_ok` echoes a malformed topic string in `results[].ch`**, which then fails `common.schema.json#/$defs/topic` (`^[a-z_]+(\.…)*$`, max 120). Repro: `sub ["Bad Topic"]`, or 130-char name.                                                                            | `permissions._fail`                                                                          | Closed by #2567 (#2396).                                                                       |
| F3  | **`permission_change` is emitted (§9.5 path) but is not in the §13.1 envelope `t` enum and has no §13 schema.**                                                                                                                                                           | `ConnectionAuthz.apply_snapshot`                                                             | Closed by #2569 (#2297, #2397): §13.1 enum + §13.4 schema; `recv_permission_change` validates. |
| F4  | Spec says a `sub` entry that is not a string/object is an error result; the server **silently drops** it, so `results` has fewer entries than `topics` (S1 "exactly one result per requested topic"). Repro: `topics:[123,{"opts":{}},null,"ticker.BTCUSDT"]` → 1 result. | `permissions.handle_sub` (`continue`)                                                        | Closed by #2567 (#2399).                                                                       |
| F5  | **`alerts` and `recorder` deltas can never be delivered** through `SequencingHub.publish`: `account_matches` requires an account for every private family, but these hold no accounts.                                                                                    | `sequencing.account_matches`                                                                 | Closed by #2521 (#2398).                                                                       |
| F6  | `sub` with an unknown key in `p` (e.g. `bogus`) is accepted and ignored (S12 covers _option_ keys; §13.5 `sub` has `additionalProperties:false`).                                                                                                                         | `permissions.handle_sub`                                                                     | Closed by #2567 (#2399).                                                                       |
| F7  | `cv.v1.msgpack` is not served (`SUPPORTED_SUBPROTOCOLS` is JSON-only), so the ticket AC "runs under cv.v1.msgpack" cannot execute.                                                                                                                                        | `lifecycle.py`                                                                               | Closed by #2897 (#377).                                                                        |

## 8. Automation map and coverage matrix

`services/api/tests/contract/ws/` (stacked across five parts, see §11): `_support.py` (self-contained fake clock, bounded
receive, per-family sample bodies; imports no other test module), `_harness.py` (real `make_ws_router` + `SequencingHub`,
fake identity/snapshot source, a client that validates both inbound and outbound frames, the §10.2 and §6.1.1 document
parsers), `conftest.py` (the `wire` fixture, and the matrix that prints which of S1-S14 ran, and under which wire, so a
skipped requirement is visible; it counts this directory's rows only, and ends with a pointer to E17-Q04 for C1-C12),
`test_ws_s1.py`, `test_ws_s2_s9.py`, `test_ws_s10_s13.py`, `test_ws_contract.py` (§16.4 contract/unit/integration rows and
client-rejection rows), and the later contract slices `test_ws_control_shapes.py`, `test_ws_sub_shape.py`,
`test_ws_break_glass_notice.py`, `test_ws_machines_state_contract.py` and `test_ws_s14.py` (S14, the
envelope span id `sp`, E17-T06).
Run: `cd services/api && uv run pytest -p no:cacheprovider tests/contract/ws -m "not integration" -q --no-cov`.

**Both subprotocols.** A test that names `World` or `connect` runs once under `cv.v1.json` and once with
`cv.v1.msgpack` preferred and JSON as the fallback (`[json]`, `[msgpack-preferred]` in the test id; `*` in a cited id
stands for either): `conftest.py` parametrises it by the `wire` fixture, and `connect()` offers that wire unless the test
names an offer. A test with its own `offer` parameter keeps it. `@json_only` (a plain function attribute, not a marker) keeps one test to JSON: the
65 526-name `unsub` fills the 256 KiB cap as JSON text, and MessagePack caps an array at 128 entries (SR-185). A
socket-driven test that no wire was set for fails in `connect()` instead of running under JSON alone.

## 9. Mutation record (the "each test can fail" bar)

Each production line below was broken in turn, the suite run, then the change reverted (`git status` clean outside the
test directory). Result is the first failing tests.

| Deliberate break                           | Caught by                                                                    |
| ------------------------------------------ | ---------------------------------------------------------------------------- |
| S1 `sub_ok` results reversed               | `test_s1_*` (3)                                                              |
| S2 `d` allowed while `snapshot_pending`    | `test_s2_delta_is_suppressed_…`                                              |
| S3 sequence skips a number                 | `test_s3_*`, `test_integration_*` (several)                                  |
| S4 `orders` throttled                      | `test_s4_orders_and_executions_…` (2)                                        |
| S5 causal sort removed                     | `test_s5_*` (2)                                                              |
| S6 outbound bound removed                  | `test_s6_orders_overflow_is_bounded_…`                                       |
| S8 gateway stops tagging `estimated`       | `test_s8_…[binary]` (found a vacuous test first; fixed)                      |
| S9 `wt` dropped on replay snap             | `test_s9_replay_frames_…` (2)                                                |
| S10 undocumented code emitted              | `test_s10_error_catalogue_is_closed_…`                                       |
| S7 `revoked` not emitted on a grant change | `test_s7_grant_withdrawal_…`, `test_s7_permission_loss_…`, frame-type matrix |
| S11 `bye` not queued before close          | 6+ tests                                                                     |
| S12 unknown option ignored                 | `test_s1_*`, `test_s12_*` (generated rows)                                   |
| S13 origin check skipped                   | `test_s13_a_bad_origin_is_refused_…` (2)                                     |
| §2.2 server prefers JSON over msgpack      | `connect()`'s echoed-subprotocol assert: the `msgpack-preferred` rows        |
| S14 `sp` on every delta, not 1 in 32       | `test_s14_sp_rides_only_…` (2), 11 unit rows                                 |
| S14 `sp` drawn while telemetry is off      | `test_s14_no_frame_carries_sp_while_…_off` (2), 2 unit rows                  |

### 9.1 Closing audit and closing PR (2026-10-17)

One production (or document) line broken per row, the control green first, the file restored after (`git status` clean outside the
PR's files); each pytest under `timeout 300`. MA to MS7 and MH ran at `daf09844c` (line numbers are that commit's). MS7 and MH
survived there; the closing change fixed both and re-ran them (so did MD). MX and MP1 to NW are its own, run at its head.

| ID  | Edit                                                                                                                           | Row                                                | Result                                                                                                                                                                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| MA  | `ws/cvwb_vectors.py:359` trades `size` becomes an int                                                                          | CVWB kind 3                                        | killed                                                                                                                                                                                                          |
| MB  | `ws/binary.py:277` magic check off                                                                                             | corrupted layout                                   | killed                                                                                                                                                                                                          |
| MC  | `ws/_generated/error_codes.py:156` admits REST codes                                                                           | registry equals §10.2                              | killed                                                                                                                                                                                                          |
| MD  | `ws/topics.py:641` default `500` becomes `250`                                                                                 | heatmap server `500`                               | killed; re-run at the head: `…server_applies_the_documented_fallback_if_absent` fails                                                                                                                           |
| ME  | `ws/sequencing.py:804` desync reason changed                                                                                   | u-gap                                              | killed                                                                                                                                                                                                          |
| MG  | `ws/sequencing.py:813` seek reason changed                                                                                     | replay seek                                        | killed                                                                                                                                                                                                          |
| MS3 | `ws/sequencing.py:571` skips every 7th number                                                                                  | S3                                                 | killed (2 of 3 `test_s3_sequence_*`)                                                                                                                                                                            |
| MF2 | `ws/gateway.py:797` (`run_auth`) re-auth treated as first auth                                                                 | re-auth                                            | killed only by `test_s7_in_place_reauth_…`                                                                                                                                                                      |
| MF  | `ws/gateway.py:863` (`run_auth`) emitter rebuilt on re-auth                                                                    | re-auth                                            | survives; equivalent, since sequence state lives on the subscription                                                                                                                                            |
| MS7 | `ws/permissions.py:810` revocation delayed 3 s (`grants_changed`)                                                              | S7 "within 1 s"                                    | survived (passed in 3.34 s); now **killed**: the `perf` row fails on both wires (2 of 2); the clock-free behaviour row passes                                                                                   |
| MH  | §6.1.1 row and clamp edited in the document                                                                                    | heatmap rows                                       | survived; now **killed**: row and clamp together 2 failures; the row, the clamp threshold and its complement alone 1 each                                                                                       |
| MX  | §6.1.1 row cells edited: a device px, a css px (+1), a pre-clamp rung                                                          | heatmap rows                                       | killed: 1 failure each                                                                                                                                                                                          |
| MP1 | `ws/codec.py` `encode_server_frame`: `use_bin_type=False` (CVWB bytes go out as `str`)                                         | every row that reads a binary body, on MessagePack | killed: 44 failures, 42 of them `[msgpack-preferred]` rows, the others being `test_contract_both_wires_carry_the_same_frames`, `test_contract_envelope_sp_is_a_string_under_both_codecs`; no `[json]` row fails |
| MP2 | `ws/codec.py` `encode_server_frame` drops `wt`                                                                                 | S9 replay rows, on MessagePack                     | survived the suite before this PR (495 passed at `origin/main`); killed now: the 2 S9 replay rows on MessagePack and the cross-wire row (3 failures, 0 `[json]`)                                                |
| MF3 | the gateway drops `footprint…imbalances[].estimated` (a patched `structured_payload`)                                          | S8 footprint row                                   | killed: 2 of 2 rows                                                                                                                                                                                             |
| MS8 | a fourth schema (`liquidations`) declares `estimated`: as a property, through `$defs` and `$ref`, under `additionalProperties` | S8 closure                                         | killed, in all three shapes                                                                                                                                                                                     |
| MW  | `use_wire` ignores its argument (the harness)                                                                                  | the `wire` fixture                                 | killed: 328 `[msgpack-preferred]` rows error in setup, 0 `[json]`                                                                                                                                               |
| MR  | §6.1.1's clamp sentence reworded (an equivalent text)                                                                          | module collection                                  | no collection error (0); 2 tests fail, naming the statement the parser could not find                                                                                                                           |
| NW  | a socket test whose helper hides `World` and `connect`                                                                         | the `wire` guard in `connect()`                    | fails with `no wire set`, instead of running under JSON alone                                                                                                                                                   |

## 10. Review, dry run and cross-links

- **Dry run:** `qa/plans/e17-ws-conformance-dryrun-20261017.md` records every case of §1-§5 against the suite at the closing
  slice's head. The human half against a staging URL is not run there: it needs a deployed server and a WS client.
- **Architect review of this plan and QA-lead sign-off: pending.** The owner's `approved` comment on #409 substitutes for both
  (agent-delivery adaptations; the E09-Q01 precedent, `e09-auth-rbac-test-plan.md` §11), and acknowledges the deferrals of §13.
  Merging moves #409 to In Test (C-10.4); QA moves it to Done.
- **CI wiring: no workflow change was needed.** The suite already runs in two PR checks: the `contract` job
  (`_job-contract.yml`: `uv run pytest tests/contract -m "not integration" --no-cov`), which `pr.yml` runs when
  `docs/plan/22-api-openapi.yaml`, `docs/plan/23-ws-protocol.md` or `packages/protocol/**` changes; and the `py` job's
  `db-chaos-contract` lane (`tools/ci/py-test-lanes.json` lists `tests/contract`), on every `services/api/**` change. The one
  `perf` row (S7's 1 s budget) is deselected from that covered lane and runs uncovered in the `py-perf` job (same trigger;
  `-m "perf and not flaky"`); the `contract` job's `-m` overrides the default deselection, so it runs it too. The
  `integration` job does not run it, because no row needs the docker stack (none is marked `integration`); the ticket's
  "contracts and integration jobs" is met by those two, and recorded as a deviation. A run takes under 20 seconds, against the
  5-minute limit.
- Cross-references: E17-Q02 (chaos), E17-Q03 (load), E17-Q04 (E2E, C1–C12), E17-X02 (adversarial security), E26 (replay end).

F1-F6 were each pinned by one `xfail(strict=True)` test (`test_*_xfail_fN_*`) until the gateway was fixed, and the PR that fixed each finding removed its marker. F1 (#2520), F2, F4 and F6 (#2567), F3 (#2569) and F5 (#2521) are closed: their tests now assert the fixed behaviour (F4 expects `err invalid_options`). F7 (#2897) is closed too: `test_s13_f7_msgpack_only_offer_negotiates_cv_v1_msgpack` asserts the msgpack-only offer, and the `msgpack-preferred` runs speak MessagePack.

## 11. Delivery in stacked parts

| Part       | Files                                                        | Requirements                                                 |
| ---------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| 1 (#2393)  | `_support.py`, `_harness.py`, `conftest.py`, `test_ws_s1.py` | S1; F2, F4, F6 closed by #2567                               |
| 2 (#2401)  | `test_ws_s2_s9.py`                                           | S2-S9; #2409/#2410 xfails flipped by #3102; F3, F5 closed    |
| 3 (#2402)  | `test_ws_s10_s13.py`                                         | S10-S13; F1 closed by #2520, F7 by #2897                     |
| 4 (#2403)  | `test_ws_contract.py`                                        | §16.4 rows                                                   |
| 5a (#3150) | `_harness.py`, `conftest.py`, `test_ws_*.py`                 | AC5, AC6, S7 budget, S8 footprint                            |
| 5b (#3151) | this plan, the dry-run record                                | DoD evidence: mutation record, deviations, xfail disposition |

Sections 1-5 and 9 describe the suite once all parts have landed.

## 12. Decisions recorded

- **F4 contract (decided in #2567).** A `sub` whose entries are not all objects or strings, or whose `p` carries an unknown key,
  is refused whole with `err invalid_options` naming the offending `topics[i]` or key, with no strike and no per-topic results
  (23 §5.2). `frame_malformed` stays reserved for a binary body inconsistent with its header, which closes and counts as a strike
  (§10.2).
- **F5 and `system`.** `system` is also a private family but is not affected: it is never a `Subscription` and the gateway pushes it
  itself. `alerts` and `recorder` were the undeliverable ones, until #2521 closed F5.
- **Outbound frames.** The harness validates frames it SENDS against §13 (`sub.schema.json` etc.) unless a test passes
  `conform=False` for a deliberately invalid one. `sub` entries use the `{ch, opts}` object form; the schema does not allow bare strings.
- **F7 / msgpack (closed by #2897, #377).** The `cv.v1.msgpack` subprotocol is the preferred transport (§2.2) and is served. The harness speaks whichever
  subprotocol the server echoed and decodes every frame before it checks it: binary MessagePack frames with raw `e: "b"` CVWB payloads (§3.2), a `bin` standing
  for its `contentEncoding: binary` string. So the AC "runs under both subprotocols" now runs: the `msgpack-preferred` cases execute under `cv.v1.msgpack`.
- **AC6 in full (part 5).** Before part 5 only the four `offer`-parameterised tests and the F7 offer ran under MessagePack. Now
  every socket-driven test does (§8). A row that sent a JSON text frame sends what its name says in the negotiated codec: a
  non-object, a 40-deep nest and a 256 KiB body are encoded as MessagePack (`send_raw`), and undecodable text is sent as a binary
  frame (`send_undecodable`; §2.2 gives each subprotocol one frame kind). Binary payloads are read through `raw_payload` and
  `cvwb_part` (raw `e: "b"` or base64 `e: "b64"`), never as one encoding.
- **AC5 read from the document (part 5).** §6.1.1's six reference rows (pane, device px, `ideal_ms`, the rung before the clamp
  where a row prints one, the rung selected), the formula's divisor and window, the ladder, the clamp and its complement, and the
  server fallback are parsed by `heatmap_reference()` (as `wire_error_codes()` parses §10.2) and held against a reference
  algorithm and the real server. An edit to any of them fails a test, and one test per kind of edit keeps that true
  (`test_heatmap_bucket_selection_an_edited_document_row_or_clamp_fails`). If a rewording stops the parser reading a statement,
  one test fails with the statement it could not find; the module still collects.

## 13. Known gaps and deferrals (reported, not hidden)

One row is `xfail(strict=True)`: the §11 replay finish. It is not a Gherkin scenario of #409 or a DoD item, so #409 closes with
it. It fails for its stated reason today, and an unexpected pass fails the suite, so the owner PR must flip it. The two S6 rows that
used to be strict xfails (#2409, #2410) were flipped by #3102 (#412, S2b) and pass; see the first bullet.

| Row                                                                                                | Today                                     | Owner                           | Flips when                                                                                                |
| -------------------------------------------------------------------------------------------------- | ----------------------------------------- | ------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Replay finish (§11): `test_integration_replay_finish_emits_revoked_replay_session_ended_per_topic` | no code ends a replay session on a socket | E26-T05 (#628); follow-up #2811 | #628 lands; the row pins a method name, `replay_finished`, that neither names, so that PR adapts the test |

- **S6 ladder (§8.4 steps 1-2), #2409, and bound, #2410.** With `CV_WS_BACKPRESSURE_ENABLED` on, the gateway runs the ladder (#412):
  `test_s6_coalescable_overflow_gets_backpressure_snap_and_no_close` and `test_s6_coalescable_topic_is_not_cut_below_the_spec_budget`
  assert both on a flag-on `World`, under both subprotocols. With the flag off (the default until #412 completes; #2900 removes it),
  the gateway still closes `slow_consumer` after 1 024 frames, with no `snap reason:backpressure`; that is pinned by
  `tests/unit/ws/test_backpressure_flag.py::test_router_without_backpressure_keeps_the_1024_frame_close`, not by a row here.
  #2409 (P1) and #2410 therefore stay open until the flag goes, and the owner's `approved` comment on #409 records the deferral
  (`03-testing-strategy.md` §16 asks a story for zero open P0/P1 at In Test → Done; #409 is a Task, but #2409 is P1).
- **S6, what else is asserted.** The `orders` branch (step 3: `bye slow_consumer`, `4429`), with the flag off, against the spec's
  2 000-frame budget, produced in one event-loop turn. The memory measurement is E17-Q02.
- **S7 "within 1 s"** is a real-time budget (`REVOKE_BUDGET_S`) around the grant change and the receive, in its own `perf` row
  (C-13.9: `py-perf` runs it uncovered and isolated on every `services/api/**` change, and the `contract` job runs it too). The S7
  behaviour row is clock-free. The harness's fake clock is never advanced, so it could not see a delay: a revocation delayed by 3 s
  used to pass. The row takes the best of 3 trials, and validates the frame outside the timed span. The bound is 152 times the
  slowest of 400 runs measured (median 1.4 ms, slowest 6.6 ms, on a loaded laptop). Chaos scenario 7
  (`tests/chaos/ws/test_s7_kill_switch_propagation.py`) holds the same 1 s bound for the kill switch, on loop time.
- **S8** is asserted for the three places the schemas declare `estimated`: `heatmap` (the payload field, and header bit0 on binary),
  `metrics` (per series) and `footprint` (`bars[].imbalances[].estimated`; structured only). `test_s8_every_estimated_field_…` walks
  the whole schema bundle (`$defs`, `oneOf`, `additionalProperties` included), so a fourth heuristic field fails until it has a row.
- **Open finding: S8 on a binary footprint.** A kind-5 body has no per-imbalance tag: its cell flags carry the imbalance direction,
  stack and POC bits only (§3.4). §3.4 defines header bit0 (`estimated`) for every kind but says nothing about when a footprint
  frame sets it. A heuristic imbalance on a footprint subscribed with `encoding: binary` is therefore untagged unless the producer
  sets the frame bit. This suite cannot assert it (no footprint producer exists, #2197); it is a spec decision for the footprint
  producer's slice, and a row is due with it.
- **Not in this suite (cross-referenced):** §16.4 coalescer and book-delta unit rows belong to E17-T03 and E17-S03; F7 is closed by
  #2897 (`test_s13_f7_msgpack_only_offer_negotiates_cv_v1_msgpack`).
