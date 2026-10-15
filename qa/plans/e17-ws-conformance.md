# E17 WebSocket protocol — conformance suite and black-box test plan

Ticket: E17-Q01 (issue #409). Owner: QA. Status: **Authored — Architect review, per-group dry run and QA-lead
sign-off pending (§10).**

Written against the observable surface only: the `/ws` endpoint, the frames of `docs/plan/23-ws-protocol.md`
§3–§12 and the schemas of §13–§15 (bundled in `docs/plan/ws-schema.json`). Cases name wire fields, error codes
and close codes, never an internal class. The automated half lives in `services/api/tests/contract/ws/`
(§8); this plan is the human half required per story group by `03-testing-strategy.md` §11.1.

> **Path note.** The ticket body names `tests/conformance/ws/` and `docs/qa/test-plans/e17-ws-protocol.md`.
> This repo already keeps contract suites under `services/api/tests/contract/` and plans under `qa/plans/`
> (every other epic; the required `contract` CI job collects the former), so both deliverables follow those
> conventions. Branch prefix `chore/` because the pre-push hook rejects `test/`. Recorded as a deviation in each PR.

## 0. How to use this plan

- **Audience:** a QA engineer with a staging URL, a WS client of their own (e.g. `websocat`) and no source access.
- **Fixtures, not live Bybit.** Book/trade/bar state comes from the recorded corpus replayed into staging
  (`03-testing-strategy.md` §4.1); no case consumes exchange rate-limit budget.
- **Case id:** `E17-TC-<group><nn>`; groups A–E = §1–§5.
- **Case columns:** Case · Preconditions · Steps · Expected · Req (`S1`–`S13`, §16.1) · Automation (test name in
  `tests/contract/ws/`, or `manual-only`).
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
| E17-TC-A03 | none                        | Offer `cv.v1.msgpack, cv.v1.json`                                              | `cv.v1.json` echoed (msgpack not yet served)                                      | S13      | `test_s1_one_sub_ok_…[msgpack-preferred]`; **pending**: a msgpack-only offer cannot be tested until the codec lands (see F7) |
| E17-TC-A04 | none                        | `hello` then wait 10 s without `auth`                                          | `bye auth_timeout`, close `4401`                                                  | S11      | `test_s11_bye_precedes_close_for_a_client_that_never_authenticates`                                                          |
| E17-TC-A05 | none                        | Put a valid token in `?access_token=` and never send `auth`                    | Token never read; `auth_timeout` as A04                                           | S13      | `test_s13_a_token_in_the_query_string_is_never_read`                                                                         |
| E17-TC-A06 | `hello` done                | 3 `auth` frames with a bad token                                               | `err auth_failed` ×2 then `bye` + `4401`                                          | S10, S11 | `…_preceded_by_bye[auth_failed-4401]`                                                                                        |
| E17-TC-A07 | `hello` done                | 3 non-`auth` frames before `auth_ok`                                           | `err not_authenticated` ×2 then `bye` + `4401`                                    | S11      | `…_preceded_by_bye[not_authenticated-4401]`                                                                                  |
| E17-TC-A08 | authenticated               | Send nothing for 45 s after the server's ping                                  | `bye heartbeat_timeout`, close `1001`                                             | S11      | `…_preceded_by_bye[heartbeat_timeout-1001]`                                                                                  |
| E17-TC-A09 | authenticated               | Let the token expire with no re-`auth`                                         | `bye token_expired`, close `4401`                                                 | S11      | `test_integration_without_reauth_an_expired_token_closes_with_bye_4401`                                                      |
| E17-TC-A10 | subscribed to 2 topics      | Re-`auth` in place 60 s before expiry                                          | `auth_ok`; **no** `snap`, **no** `sub_ok`; sequences continue                     | §4.1     | `test_integration_token_expiry_reauth_in_place_preserves_subscriptions_and_sequences`                                        |
| E17-TC-A11 | authenticated               | Server planned shutdown                                                        | `d system shutdown_notice`, then `bye shutdown`, close `1001`                     | S11      | `…_preceded_by_bye[shutdown-1001]`                                                                                           |
| E17-TC-A12 | 8 sockets open for one user | Open a 9th                                                                     | Oldest idle gets `bye too_many_connections`, `4429`                               | S11      | `…_preceded_by_bye[too_many_connections-4429]`                                                                               |
| E17-TC-A13 | authenticated               | Disable the user / revoke the session in admin                                 | `bye user_disabled` `4403` / `bye session_revoked` `4401`                         | S7, S11  | `test_s7_user_disabled_…`, `test_s7_session_revocation_…`                                                                    |

## 2. Group B — Subscriptions and authorisation (§5, §6, §9.5; E17-S02)

| Case       | Preconditions                     | Steps                                                                                            | Expected                                                                                                                                                                                       | Req | Automation                                                                                  |
| ---------- | --------------------------------- | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- | ------------------------------------------------------------------------------------------- |
| E17-TC-B01 | authenticated                     | `sub` 7 topics mixing valid, unknown, bad depth, duplicate, unknown option, out-of-scope account | One `sub_ok`, 7 results **in request order**, each `ok`/`error`; then one `snap` per accepted topic                                                                                            | S1  | `test_s1_one_sub_ok_result_per_requested_topic_in_request_order`                            |
| E17-TC-B02 | authenticated                     | `sub` whose every topic fails                                                                    | Still one result per topic, none `ok`                                                                                                                                                          | S1  | `test_s1_every_topic_failing_still_yields_one_result_each`                                  |
| E17-TC-B03 | authenticated                     | Per topic family and shape (all 22 registry rows), in `structured` and `binary`                  | `snap` (`s:1`, `reason:initial`) arrives before the first `d`                                                                                                                                  | S2  | `test_s2_snap_precedes_any_delta_on_every_topic_row` (generated from the topic registry)    |
| E17-TC-B04 | book not yet rebuilt              | `sub book…`, then upstream publishes                                                             | No `d` until a `snap` can be built                                                                                                                                                             | S2  | `test_s2_delta_is_suppressed_while_the_snapshot_cannot_be_built`                            |
| E17-TC-B05 | authenticated                     | `sub` with `snapshot:false` + provable/unprovable continuity                                     | Provable: deltas only. Unprovable: `snapshot_forced:true` and a `snap`                                                                                                                         | S2  | `test_s2_snapshot_false_…` (×2)                                                             |
| E17-TC-B06 | authenticated                     | Typo every declared option on every family                                                       | `invalid_options`, `field` = the bad key, nothing subscribed                                                                                                                                   | S12 | `test_s12_a_typo_of_every_declared_option_…` (127 generated rows)                           |
| E17-TC-B07 | subscribed                        | `ctl` with an unknown key; `ctl` widening `exchange_account_ids`                                 | `err invalid_options`                                                                                                                                                                          | S12 | `test_s12_unknown_options_on_ctl_…`, `test_s12_scope_options_cannot_be_widened_through_ctl` |
| E17-TC-B08 | manager with accounts A, B        | Withdraw B in admin while subscribed to `positions[A,B]`, `trades`, `orders[A]`                  | `permission_change`, then `revoked positions` (`account_scope_changed`, `removed_accounts:[B]`, `resubscribe_allowed:true`) within 1 s; `trades` and `orders` keep streaming with unbroken `s` | S7  | `test_s7_grant_withdrawal_emits_revoked_within_1s_and_other_topics_continue`                |
| E17-TC-B09 | subscribed to `orders` + `trades` | Remove `orders:read`                                                                             | `revoked orders` (`permission_revoked`, `resubscribe_allowed:false`); `trades` unaffected                                                                                                      | S7  | `test_s7_permission_loss_revokes_every_topic_of_that_family_only`                           |
| E17-TC-B10 | subscribed                        | Narrower permissions via in-place re-`auth`                                                      | `auth_ok` then `revoked`                                                                                                                                                                       | S7  | `test_s7_in_place_reauth_with_narrower_permissions_revokes_affected_topics`                 |
| E17-TC-B11 | subscribed                        | Engage the kill switch                                                                           | Every connected user re-evaluated                                                                                                                                                              | S7  | `test_s7_kill_switch_transition_reevaluates_every_connected_user`                           |
| E17-TC-B12 | authenticated                     | `sub orders` with no / another manager's account (raw frame)                                     | `account_scope_denied`/`forbidden` (adversarial depth is E17-X02)                                                                                                                              | S10 | `test_client_every_private_topic_requires_an_account_in_scope`                              |

## 3. Group C — Snapshot, sequence and resync (§7; E17-S03)

| Case       | Preconditions                                                               | Steps                                                                                                    | Expected                                                                                                                              | Req    | Automation                                                                                                                                       |
| ---------- | --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| E17-TC-C01 | 3 subscriptions                                                             | 8 concurrent writers, plus a client `resync` and a `ctl time_bucket_ms` mid-stream                       | Per `(ch, rs)`: `s` = 1,2,3… with no gap and no reuse; `previous_seq` = `s−1` on re-snaps                                             | S3     | `test_s3_sequence_increments_by_exactly_one_per_topic_under_concurrent_writes`, `test_s3_sequence_survives_resync_and_reconfigure_without_reuse` |
| E17-TC-C02 | `book` subscribed                                                           | Upstream `u` jumps 11 → 13                                                                               | `snap` `reason:upstream_desync`, `previous_seq` set, no `d` across the gap; deltas resume `s+1`                                       | §7.4   | `test_integration_upstream_u_gap_produces_snap_with_reason_upstream_desync`                                                                      |
| E17-TC-C03 | `book` subscribed                                                           | 5 `resync` in a minute, then a 6th                                                                       | 5 `snap client_resync`; 6th → `err resync_rate_limited` + `revoked`                                                                   | S10    | `test_s10_error_catalogue_is_closed_…` (path)                                                                                                    |
| E17-TC-C04 | `bars` subscribed                                                           | Coalesced update (×4)                                                                                    | One `d`, `coalesced:true`, `coalesced_count:4`, **one** `s`                                                                           | S3     | `test_s4_coalescable_topics_do_mark_coalesced_deltas`                                                                                            |
| E17-TC-C05 | `orders`, `executions` subscribed with `throttle_ms:60000`, `coalesce:true` | Burst of 60 updates                                                                                      | `effective.throttle_ms:0`, `coalesce:false`; 60 individual `d`, `s` 2..61                                                             | S4     | `test_s4_orders_and_executions_are_never_coalesced_or_throttled`                                                                                 |
| E17-TC-C06 | 4 private topics for account A                                              | One fill event                                                                                           | Arrival order `executions → orders → positions → trade_groups`; other accounts see nothing                                            | S5     | `test_s5_private_frames_for_one_account_event_arrive_in_causal_order`                                                                            |
| E17-TC-C07 | heatmap with a heuristic source                                             | Subscribe in each encoding                                                                               | `estimated:true` / header bit0                                                                                                        | S8     | `test_s8_heuristic_heatmap_snapshot_is_tagged_estimated`                                                                                         |
| E17-TC-C08 | replay session `RS` (stub clock)                                            | `sub` with `replay_session_id`; publish recorded frames; seek                                            | `snap source:replay` with `rs` + `wt`; `d` has recorded `ts`; bit2 on binary; seek → `snap replay_seek` on every topic, `s` continues | S9     | `test_s9_replay_frames_…`, `test_integration_replay_subscribe_and_seek_emit_the_documented_series`                                               |
| E17-TC-C09 | replay reaches `to`                                                         | —                                                                                                        | `revoked replay_session_ended` per topic                                                                                              | §11    | **pending E26** (frame shape: `test_integration_replay_end_revoked_frame_is_schema_valid`)                                                       |
| E17-TC-C10 | all six CVWB kinds                                                          | Decode each, validate against its structured schema; corrupt magic/version/kind/length                   | Valid decode ≡ structured form; every corruption → `frame_malformed`                                                                  | §16.4  | `test_contract_cvwb_kind_…`, `test_contract_a_corrupted_cvwb_layout_…`, `test_contract_binary_and_structured_snapshots_…`                        |
| E17-TC-C11 | —                                                                           | `heatmap_bucket_selection` over the six §6.1.1 rows, the 2500 ms clamp edge, and `time_bucket_ms` absent | 1000/1000/1000/1000/1000/5000; edge 2500→1000, 2500.1→5000; server applies 500                                                        | §6.1.1 | `test_heatmap_bucket_selection_*`                                                                                                                |

## 4. Group D — Backpressure and limits (§8.4, §16.2; E17-S01/T03)

| Case       | Preconditions                           | Steps                                                    | Expected                                                                                                  | Req     | Automation                                                                                                                                                 |
| ---------- | --------------------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| E17-TC-D01 | `orders` subscribed, client not reading | Produce more than the outbound bound (1024) in one burst | Queue never exceeds the bound; `bye slow_consumer`, close `4429`; `orders` is closed rather than degraded | S6, S11 | `test_s6_orders_overflow_is_bounded_by_the_spec_budget_then_slow_consumer_4429` (observable form against the spec's 2 000-frame budget; memory is E17-Q02) |
| E17-TC-D02 | authenticated                           | One frame > 256 KiB (text)                               | `bye frame_too_big`, close `1009`, never parsed                                                           | S11     | `…_preceded_by_bye[frame_too_big-1009]`                                                                                                                    |
| E17-TC-D03 | authenticated                           | > 30 frames in 1 s                                       | `err client_rate_limited`, then `bye` `4429` with `retry_after_ms:1000`                                   | S11     | `…_preceded_by_bye[client_rate_limited-4429]`                                                                                                              |
| E17-TC-D04 | authenticated                           | 51 topics in one `sub`                                   | Excess topics `too_many_topics`; the rest processed                                                       | S1      | `test_s10_error_catalogue_is_closed_…` (path)                                                                                                              |
| E17-TC-D05 | authenticated                           | A queued backlog, then session revocation                | Queued frames dropped, `bye` still delivered                                                              | S11     | `test_s11_a_sealed_close_drops_queued_frames_but_still_delivers_bye`                                                                                       |

Chaos (60 s non-reading client, 5 000 msg/s burst, upstream kill) is E17-Q02; load is E17-Q03.

## 5. Group E — Client frames the server must reject (§4.4, §10; E17-S01)

| Case       | Steps                                                                                                 | Expected                                                    | Req | Automation                                                            |
| ---------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- | --- | --------------------------------------------------------------------- |
| E17-TC-E01 | Non-JSON text, truncated JSON, control bytes, 40-deep nesting, a binary WS frame                      | `err frame_malformed`, socket stays usable                  | S10 | `test_client_non_json_text_…`, `…deeply_nested…`, `…binary_ws_frame…` |
| E17-TC-E02 | Missing `t`; non-string `t`; unknown `t`; JSON array/string; every server-only `t` sent by the client | `err frame_malformed`                                       | S10 | `test_client_frames_the_server_must_reject_…` (19 rows)               |
| E17-TC-E03 | `resync` without `ch`, bad `reason`, unsubscribed `ch`; `ctl` on an unsubscribed `ch`; second `hello` | `frame_malformed` / `not_subscribed` / `protocol_violation` | S10 | same test                                                             |
| E17-TC-E04 | 3 bad frames                                                                                          | `bye bad_client`, `4400`                                    | S11 | `test_client_three_strikes_close_with_bye_4400`                       |
| E17-TC-E05 | Any frame before `hello`                                                                              | `bye protocol_violation`, `1002`                            | S11 | `test_client_frames_before_hello_close_with_bye_1002`                 |
| E17-TC-E06 | `snapshot:"yes"`, non-uuid `replay_session_id`                                                        | `invalid_options`                                           | S12 | `test_client_snapshot_and_replay_fields_are_type_checked`             |

## 6. §10.3 UI treatment expected per error class (feeds E17-Q04)

| Class                   | Codes                                                        | Must the UI do                                                                              | Asserted by |
| ----------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------- | ----------- |
| Fatal, user must act    | `auth_failed`, `forbidden`, `user_disabled`                  | Modal; route to login or an explanatory screen; no auto-reconnect on `4403`                 | Q04         |
| Transient, self-healing | `degraded_data`, `exchange_unavailable`, `token_expired`     | Inline staleness badge + connection chip, no modal; `token_expired` → refresh and re-`auth` | Q04         |
| Client bug              | `protocol_violation`, `frame_malformed`, `invalid_options`   | Console error + "report a bug" toast; never swallowed                                       | Q04         |
| Capacity                | `slow_consumer`, `subscription_limit`, `client_rate_limited` | Toast advising fewer panes; auto-reduce throttles; full-jitter reconnect                    | Q04         |

Reconnect policy by close code (C7): do not auto-reconnect on `1002`, `4400`, `4403`.

## 7. Findings against the current build (carried to the ticket; see PR)

| #   | Observation                                                                                                                                                                                                                                                               | Where                                                                                        | Status                                                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| F1  | **Every server `err` frame omits `p.message`**, which `common.schema.json#/$defs/error` requires.                                                                                                                                                                         | any `err`, e.g. `{"t":"err","p":{"code":"frame_malformed","retryable":false,"close":false}}` | Open; defect to file. Tests validate the envelope and `code` only on `err` (`Client.recv_err`). |
| F2  | **`sub_ok` echoes a malformed topic string in `results[].ch`**, which then fails `common.schema.json#/$defs/topic` (`^[a-z_]+(\.…)*$`, max 120). Repro: `sub ["Bad Topic"]`, or 130-char name.                                                                            | `permissions._fail`                                                                          | Open; defect to file. Tests avoid malformed names in `ch`.                                      |
| F3  | **`permission_change` is emitted (§9.5 path) but is not in the §13.1 envelope `t` enum and has no §13 schema.**                                                                                                                                                           | `ConnectionAuthz.apply_snapshot`                                                             | Open; spec or server. `Client.recv_permission_change` skips validation.                         |
| F4  | Spec says a `sub` entry that is not a string/object is an error result; the server **silently drops** it, so `results` has fewer entries than `topics` (S1 "exactly one result per requested topic"). Repro: `topics:[123,{"opts":{}},null,"ticker.BTCUSDT"]` → 1 result. | `permissions.handle_sub` (`continue`)                                                        | Open; S1 deviation for non-string `ch`. Not asserted.                                           |
| F5  | **`alerts` and `recorder` deltas can never be delivered** through `SequencingHub.publish`: `account_matches` requires an account for every private family, but these hold no accounts.                                                                                    | `sequencing.account_matches`                                                                 | Open; snapshot is asserted, delta is not.                                                       |
| F6  | `sub` with an unknown key in `p` (e.g. `bogus`) is accepted and ignored (S12 covers _option_ keys; §13.5 `sub` has `additionalProperties:false`).                                                                                                                         | `permissions.handle_sub`                                                                     | Open; clarify in spec. Not asserted.                                                            |
| F7  | `cv.v1.msgpack` is not served (`SUPPORTED_SUBPROTOCOLS` is JSON-only), so the ticket AC "runs under cv.v1.msgpack" cannot execute.                                                                                                                                        | `lifecycle.py`                                                                               | Known limitation, pending codec.                                                                |

## 8. Automation map and coverage matrix

`services/api/tests/contract/ws/` (stacked across four PRs, see §11): `_support.py` (self-contained fake clock, bounded
receive, per-family sample bodies; imports no other test module), `_harness.py` (real `make_ws_router` + `SequencingHub`,
fake identity/snapshot source, a client that validates both inbound and outbound frames), `conftest.py` (prints which of
S1-S13 ran, so a skipped requirement is visible), `test_ws_s1.py`, `test_ws_s2_s9.py`, `test_ws_s10_s13.py`,
`test_ws_contract.py` (§16.4 contract/unit/integration rows and client-rejection rows).
Run: `cd services/api && uv run pytest -p no:cacheprovider tests/contract/ws -q --no-cov`.

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
| S6 outbound bound removed                  | `test_s6_outbound_queue_…`                                                   |
| S8 gateway stops tagging `estimated`       | `test_s8_…[binary]` (found a vacuous test first; fixed)                      |
| S9 `wt` dropped on replay snap             | `test_s9_replay_frames_…` (2)                                                |
| S10 undocumented code emitted              | `test_s10_error_catalogue_is_closed_…`                                       |
| S7 `revoked` not emitted on a grant change | `test_s7_grant_withdrawal_…`, `test_s7_permission_loss_…`, frame-type matrix |
| S11 `bye` not queued before close          | 6+ tests                                                                     |
| S12 unknown option ignored                 | `test_s1_*`, `test_s12_*` (generated rows)                                   |
| S13 origin check skipped                   | `test_s13_a_bad_origin_is_refused_…` (2)                                     |

## 10. Review, dry run and cross-links

- Architect review of this plan and QA-lead sign-off: **pending** (substituted by owner approval per the agent-delivery adaptations).
- CI wiring as a required check on `contracts` and `integration`: **not done here** (workflow files are out of scope for this PR).
- Cross-references: E17-Q02 (chaos), E17-Q03 (load), E17-Q04 (E2E, C1–C12), E17-X02 (adversarial security), E26 (replay end).

F1-F6 are pinned by one `xfail(strict=True)` test each (`test_*_xfail_fN_*`); the marker must be removed when the gateway is fixed. F7 is pinned by the single strict xfail `test_s13_xfail_f7_msgpack_only_offer_negotiates_cv_v1_msgpack` (#377).

## 11. Delivery in stacked parts

| Part      | Files                                                        | Requirements                       |
| --------- | ------------------------------------------------------------ | ---------------------------------- |
| 1 (#2393) | `_support.py`, `_harness.py`, `conftest.py`, `test_ws_s1.py` | S1; xfails F2, F4, F6              |
| 2 (#2401) | `test_ws_s2_s9.py`                                           | S2-S9; xfails F5, F3, #2409, #2410 |
| 3 (#2402) | `test_ws_s10_s13.py`                                         | S10-S13; xfails F1, F7             |
| 4 (#2403) | `test_ws_contract.py`                                        | §16.4 rows                         |

Sections 1-5 and 9 describe the suite once all parts have landed.

## 12. Decisions recorded

- **F4 contract.** §5.2 says every requested topic gets one result, but a request whose entries are not objects/strings is also
  arguably a malformed frame. The xfail accepts either one result per entry (4 for the #2399 repro, `null` included) or a whole-frame
  `err frame_malformed`. Silently answering fewer entries is neither.
- **F5 and `system`.** `system` is also a private family but is not affected: it is never a `Subscription` and the gateway pushes it
  itself. Only `alerts` and `recorder` are undeliverable.
- **Outbound frames.** The harness validates frames it SENDS against §13 (`sub.schema.json` etc.) unless a test passes
  `conform=False` for a deliberately invalid one. `sub` entries use the `{ch, opts}` object form; the schema does not allow bare strings.
- **F7 / msgpack.** The `cv.v1.msgpack` subprotocol is the preferred transport (§2.2) and its codec is not on `main` (Agent B's msgpack subprotocol work, #377,
  is the owner). The AC "runs under both subprotocols" therefore stays open; the single pin is `test_s13_xfail_f7_…` (reason `#377: cv.v1.msgpack codec not implemented (F7)`).

## 13. Known gaps in S6 and S8 coverage (reported, not hidden)

- **S6 ladder (§8.4 steps 1-2), #2409.** The gateway does not implement the coalescable-topic branch: flooding `trades` past the budget closes the socket with `bye slow_consumer` after 1 024 frames, with no `snap reason:backpressure`. Pinned by `test_s6_xfail_coalescable_overflow_gets_backpressure_snap_and_no_close`. The `orders` branch (step 3) is asserted.
- **S6 bound, #2410.** The gateway bound is 1 024 frames, not the spec's 2 000 (§16.2); pinned by `test_s6_xfail_coalescable_topic_is_not_cut_below_the_spec_budget`.
- **S8** is asserted for `heatmap` (structured and binary) and `metrics` (structured `estimated` per series). Other families have no
  heuristic fields in §14.
- **Not in this suite (cross-referenced):** §16.4 coalescer and book-delta unit rows belong to E17-T03 and E17-S03; F7 msgpack runs to the codec work (#377); pinned by `test_s13_xfail_f7_msgpack_only_offer_negotiates_cv_v1_msgpack`.
