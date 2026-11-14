# E22 security review — big trades: the tape REST route, the `trades` topic, the engine and the threshold settings (E22-X02)

- Ticket: E22-X02 (#756). Threat model: `docs/security/threat-models/E22-big-trades.md` (E22-X01, #609),
  its rows D1-D27, requirements SR-E22-01 to SR-E22-15, gaps G1-G8 and abuse cases AC1-AC19, cited by
  those ids. Abuse cases: `docs/security/abuse-cases/e22-big-trades.md` (E22-X02).
- Reviewed against `main` at `1708e0ad3` (2026-11-04); the reviewed code is unchanged since `4c0821e73`.
  Code paths are relative to `services/api/candleviewer/` and test paths to `services/api/`, unless they
  start with `apps/`, `docs/` or `.semgrep/`. Line numbers are those of `1708e0ad3`.
- In-flight contracts: E22-S01 PR-B #5324 at `0a9f33845c5f429e6193ca2edd39995c676c97ad` (the tape panel),
  cited by file and symbol, never by line, and only "if it merges as is". E22-S02 (#715) has no PR: the rows
  that rest on it are pinned to `main` plus the coordinator's ruling 6623590812 on #715 and carry the status
  `PROPOSED (waits on E22-S02 #715)` with their ordinary rating (§1.4).
- Method: white-box review by the E22-X02 author of the files in the ticket's scope (`orderflow/bigtrade.py`,
  `bigtrade_cluster.py`, `bigtrade_tape.py`, `quantile.py`, `limits.py`, `api/trades.py`,
  `ws/trades_publish.py`, `ws/topics.py`, `api/user_settings.py`, `api/user_settings_models.py`) and of the
  client tape under `apps/web/src/features/tape/`, row by row against the model, with two review lenses
  (accuracy and form; security) on an earlier cut. Every test named below exists on `main` at the reviewed
  commit. This is not yet the Security-engineer record the ticket describes; that is §5.
- Disclosure: open findings carry only id, class, severity, status and tracker (`SECURITY.md` §1,
  C-12.13); their detail is held in the private E22 advisory draft. They are not paired with rows: a PASS
  below means the named control and its test hold, not that no finding is open under that row.

> **Status: In review.** The header moves to Approved only after both lens rounds of §5. No row is signed
> by the author.

Verdict key: **PASS** (control exists in code and a named test exercises it) · **PARTIAL** (some exists,
some gap; ticketed) · **FAIL-T** (missing, owning ticket named) · **PROPOSED** (rests on a ticket not on
`main`; ordinary rating, re-pinned per §1.4) · **R** (referenced, another epic's model owns it) ·
**A** (accepted in the model, §3) · **N/A** · **NOT EXECUTED**.

## 1. Control-by-control verdicts

### 1.1 The model's threat rows (D1-D27)

<!-- prettier-ignore -->
| Row | Risk | Implementation (file:line) | Proving test | Verdict |
| --- | --- | --- | --- | --- |
| D1 | Low | `api/trades.py:180-187` (no resolver 501, no session 401, no `marketdata:read` 403, before any parameter is read); WS session per subscribe (E17) | `tests/unit/api/test_trades_api.py::test_get_trades_error_paths`; `tests/unit/ws/test_subscriptions_socket.py::test_socket_unauthenticated_sub_is_refused`; `tests/contract/rbac/test_route_matrix.py` | PASS |
| D2 | Low | `sub_id` owned per connection by the E17 gateway | as `docs/security/threat-models/E17-ws-gateway.md` | R (E17) |
| D3 | High | E08 parse rejection and #1898; the engine's input assert (`orderflow/bigtrade.py`, SR-E22-13); trimmed estimator (`orderflow/quantile.py`, SR-E22-14) | `tests/unit/orderflow/test_bigtrade_engine.py::test_input_assert_rejects_off_tick_and_non_positive`; `tests/unit/orderflow/test_bigtrade_quantile.py::test_trimmed_wrapper_single_outlier_does_not_move_threshold` | R (E08) + PASS |
| D4 | High | REST: `api/trades.py:171-178` (query bounds from `orderflow/limits.py`), `:196-198` (window) and `:205-209` (floor), before the tape is read; WS: `ws/topics.py:319`, `ws/trades_publish.py:224-238` (refused with nothing held). Settings half: SR-E22-11, §1.4 | `test_trades_api.py::test_get_trades_refuses_out_of_bound_reads_before_reading`, `::test_get_trades_keeps_its_bounds_at_their_edges`; `tests/unit/ws/test_trades_publish.py::test_trades_out_of_range_options_are_refused_and_nothing_is_held`, `::test_trades_a_decimal_option_longer_than_32_characters_is_refused` | PASS (REST and WS); settings half PROPOSED (waits on E22-S02 #715) |
| D5 | Med | One evaluation in the engine; the ack carries the effective threshold; the client reads `is_big_trade` and never compares (`apps/web/src/features/tape/model/ingest.ts:144`, `model/ring.ts:18-19`) | `tests/unit/orderflow/test_bigtrade_tape.py::test_tape_options_never_move_the_threshold`; `test_trades_publish.py::test_trades_ack_echoes_the_options_and_the_engine_threshold`; `tests/unit/orderflow/test_bigtrade_golden_parity.py`; `tests/unit/ws/test_trades_rest_ws_agree.py::test_rest_and_ws_agree_on_flagged_prints_and_cluster_membership` | PASS (server); client half: implementation cited, rule in PR-2 |
| D6 | High | `cluster_size` end to end (`orderflow/bigtrade_tape.py`); a window with a cluster leaves structured | `test_bigtrade_tape.py::test_tape_cluster_item_takes_first_print_total_size_and_any_member_flag`; `test_trades_api.py::test_get_trades_clusters_same_side_same_price_in_window`; `test_trades_publish.py::test_trades_clusters_reach_binary_and_structured_subscribers_with_one_membership` | PARTIAL. G6 (frame-level `estimated`, `23` §14.2) open; the badge is FAIL-T E22-S04 (#717) |
| D7 | Low | `settings.change` written ahead of the commit for the route (`api/user_settings.py`); the `bigtrade` keys are refused until S02's contract (`api/user_settings_models.py:194-195`, an undeclared group refused) | `tests/unit/api/test_user_settings_router.py::test_patch_settings_writes_settings_change_ahead_of_its_commit`; `tests/unit/api/test_user_settings_models.py::test_leaves_are_exactly_the_leaves_22s_settings_declares` | PROPOSED (waits on E22-S02 #715) |
| D8 | Low | Request logs with `traceId` and user (C-12.6); `cv_ws_trades_subscribe_rejected_total{reason}` | `test_trades_publish.py::test_trades_out_of_range_options_are_refused_and_nothing_is_held` (the counter moves per refusal) | A (§3) |
| D9 | Low | No identity field in the data model; the WS `trades` schema is closed; metric labels are closed sets. Client copy and announcements: #5324 `apps/web/src/features/tape/copy.ts`, `announce.ts` `TapeAnnouncer` | `tests/unit/ws/test_ws_metrics_session_labels.py::test_label_names_are_the_catalogued_ones`; #5324 `apps/web/test/features/tape/copy.test.ts` "tape copy against the E22-D05 deck" (if it merges as is) | PASS for the server; the AC12 scan DEFENDED (cases) |
| D10 | Low | `effective` built from the caller's options plus the symbol's engine threshold (`ws/trades_publish.py`); caps per user; shared tapes keyed internally (SR-E22-15) | `test_trades_publish.py::test_trades_ack_echoes_the_options_and_the_engine_threshold`, `::test_trades_per_user_cap_and_option_set_cap_refuse_with_nothing_held` | PASS; the AC13 two-user diff DEFENDED (cases); the invariant of §1.2 SR-E22-15 |
| D11 | Low | `dropped` counts the caller's option set only | `test_trades_publish.py::test_trades_min_size_drops_are_counted_in_dropped_across_frame_boundaries` | A (§3) |
| D12 | Low | RFC 7807 at the edge, fixed problem text (`api/trades.py`); no SQL on this route (the hot tape) | `test_trades_api.py::test_get_trades_error_paths` | PASS |
| D13 | Low | Scope is the session's user; a query parameter `422`; never a body field (`api/user_settings.py`) | `test_user_settings_router.py::test_settings_one_user_never_reads_or_writes_another_users` (also `tests/contract/test_user_settings_contract.py`), `::test_settings_a_query_parameter_is_422_and_nothing_is_read_or_written` | PROPOSED (waits on E22-S02 #715) |
| D14 | High | `api/trades.py` `_window_refusal` (:245-257), called at :196-198 before the reader; the hot tape holds 1 000 prints per symbol | `test_trades_api.py::test_get_trades_refuses_out_of_bound_reads_before_reading`, `::test_get_trades_keeps_its_bounds_at_their_edges` | PASS |
| D15 | High | The floor (`orderflow/limits.py` `min_size_floor`) on REST (`api/trades.py:205-209`), subscribe and `ctl` (`ws/trades_publish.py:224-238`) | `test_trades_api.py::test_get_trades_reads_the_floor_per_request_and_names_it_in_the_detail`; `test_trades_publish.py::test_trades_ctl_min_size_moves_the_lease_and_never_resnapshots`; `tests/unit/orderflow/test_bigtrade_limits.py::test_min_size_floor_is_max_of_lot_and_tick_notional` | PASS; the load leg is NOT EXECUTED (E22-Q03 #753) |
| D16 | High | Ranges (`api/trades.py:177-178`, `ws/topics.py:319`); keyed open clusters with caps (`orderflow/bigtrade_cluster.py`) | `tests/unit/orderflow/test_bigtrade_cluster.py::test_open_key_cap_evicts_oldest_and_counts_truncation`, `::test_prints_buffer_effective_cap_evicts`; `test_bigtrade_engine.py::test_ws_surface_caps_cluster_window_at_2000` | PASS |
| D17 | High | E17 per-connection caps; 60 `trades` per user across connections and 2 option sets per symbol per user, refused with nothing held (`ws/trades_publish.py:224-238`, `:286-304`) | `test_trades_publish.py::test_trades_per_user_cap_and_option_set_cap_refuse_with_nothing_held`, `::test_trades_pending_leases_count_toward_both_caps`; `tests/unit/ws/test_gateway_limits.py::test_sub_over_subscription_cap_is_rejected_and_set_does_not_grow`; `tests/unit/ws/test_sub_entry_cap.py` | PASS |
| D18 | High | E17 per-connection budget and `backpressure` snapshot (`23` §8.4); the option tape's pending items bounded, shed prints counted (`ws/trades_publish.py` `PENDING_MAX`) | `test_trades_publish.py::test_trades_pending_is_bounded_and_an_overflow_is_counted_in_dropped` | PARTIAL. G8 (the `trades` gap marker, `23` §8.4 / §14.2) open; AC10 NOT EXECUTED (E22-Q03 #753) |
| D19 | High | Fixed-size percentile sketches (`orderflow/quantile.py`); bounded cluster state; bounded dedupe ring (`orderflow/bigtrade.py`) | `test_bigtrade_quantile.py::test_windowed_expiry_drops_old_buckets_and_flagged_fraction`; `test_bigtrade_engine.py::test_dedupe_ring_is_bounded_and_forgets_oldest` | PASS; the soak (AC9) NOT EXECUTED (E22-Q03 #753) |
| D20 | Med | E08 bounded ingress; the bus subscription invalidates on full and re-snapshots | `test_trades_publish.py::test_trades_a_lost_bus_batch_catches_up_and_resnapshots` | R (E08) |
| D21 | High | not built | — | FAIL-T E22-S03 (#716), E47-S04 |
| D22 | Med | Count ceiling 50 000 (`apps/web/src/features/tape/model/ring.ts:7-9`); the 32 MiB ceiling and trimmed state not built | `apps/web/test/features/tape/ring.test.ts` "holds 10 000 prints by default and refuses a capacity outside 1 to 50 000" | PARTIAL. Bytes ceiling FAIL-T E22-S05 (#718) |
| D23 | Med | not built | — | FAIL-T E22-S06 (#1398) |
| D24 | Low | Validation before the read; pages memoised per tape head (`api/trades.py`) | `test_trades_api.py::test_get_trades_memoises_a_page_until_the_tape_head_moves`; `tests/unit/orderflow/test_bigtrade_perf.py` | PASS in process; budgets NOT EXECUTED (E22-Q03 #753) |
| D25 | Medium | Own-scope writes; Viewer `PATCH` `403`, `rbac.denied` audited; a view-as write `403 view_as_read_only` (shipped). The engine value: the ruled proposal, Owner-only to write, Managers and Viewers read it | `test_user_settings_router.py::test_settings_a_viewer_reads_and_is_refused_403_on_a_write`, `::test_settings_a_write_under_a_view_is_refused_before_anything_else` | PROPOSED (waits on D05-G-2, #715 BQ-01, due 2026-12-11) |
| D26 | Low | `x-rbac` on every operation; the WS subscribe checks `marketdata:read` server-side (`ws/permissions.py:375-381` against the topic table, `ws/topics.py:263`) | `tests/contract/rbac/test_route_matrix.py::test_matrix_permissions_and_scope_agree_with_the_contract`; `test_subscriptions_socket.py::test_socket_unauthenticated_sub_is_refused` | PASS |
| D27 | n/a | Asserted absent apart from the settings write and the engine-value writer of D25 | AC19 enumeration (cases) | A (§3); AC19 NEW |

### 1.2 The model's requirements (SR-E22-01 to SR-E22-15)

<!-- prettier-ignore -->
| Requirement | Implementation | Proving test | Verdict |
| --- | --- | --- | --- |
| SR-E22-01 window 6 h, 15 min clustered | `api/trades.py` `_window_refusal`; `orderflow/limits.py` | as D14 | PASS |
| SR-E22-02 `limit` 500 | `api/trades.py:174` | `test_trades_api.py::test_get_trades_keeps_its_bounds_at_their_edges` | PASS |
| SR-E22-03 `min_size` floor | as D15 | as D15 | PASS |
| SR-E22-04 cluster ranges | as D16 | as D16 | PASS |
| SR-E22-05 cluster-state caps | `orderflow/bigtrade_cluster.py`, `bigtrade_state_truncated_total` | as D16 | PASS |
| SR-E22-06 per-user `trades` cap and 8 connections | `ws/trades_publish.py:227-231`; E17 | as D17 | PASS |
| SR-E22-07 2 option sets per symbol | `ws/trades_publish.py:296-304` | as D17 | PASS |
| SR-E22-08 queue policy | as D18 | as D18 | PARTIAL (G8) |
| SR-E22-09 client ceilings, 5 000 bubbles | as D22; bubbles not built | as D22 | PARTIAL (E22-S05 #718, E22-S03 #716) |
| SR-E22-10 bubble flashes at most 3 Hz | not built | — | FAIL-T E22-S03 (#716), E47-S04 |
| SR-E22-11 settings values | `bigtrade` keys refused until S02's contract (`api/user_settings_models.py:194-195`, an undeclared group refused) | `test_user_settings_models.py::test_leaves_are_exactly_the_leaves_22s_settings_declares` | PROPOSED (waits on E22-S02 #715) |
| SR-E22-12 estimated badge | not built | — | FAIL-T E22-S04 (#717); G6 open |
| SR-E22-13 engine input assert | `orderflow/bigtrade.py` | as D3 | PASS |
| SR-E22-14 trimmed estimator | `orderflow/quantile.py` | as D3 | PASS |
| SR-E22-15 nothing depends on another user's options | as D10 | as D10 | PASS; invariant below |

SR-E22-15 invariant (forward, for the PROPOSED rows): the REST page memo and the WS option tapes are shared
across users and keyed on the server's per-symbol config. A per-user `bigtrade.*` value never enters the
shared tape or the page memo; if the Owner decides otherwise, the memo and option-tape keys include the
user. AC13 and case 5 assert it once S02 lands.

### 1.3 `GET /market/metrics`

<!-- prettier-ignore -->
| Item | State | Verdict |
| --- | --- | --- |
| O-1 `GET /market/metrics`: `marketdata:read` checked first, and bounded windows validated before any read | Declared in `22`, not mounted (`tests/contract/rbac/matrix.yaml`, state `not_mounted`) | O: no review now; re-reviewed when mounted. Trackers #645 (E20-T02) and #658 (E23-T02). Out of the ZAP plan and the route corpus until mounted |

### 1.4 PROPOSED rows and the re-pin rule

Rows D4 (settings half), D7, D13 and SR-E22-11 wait on E22-S02 (#715); D25 waits on the owner decision
D05-G-2 (#715 BQ-01, due 2026-12-11). The contract-dependent rows (SR-E22-11, D4's settings half) re-pin at
S02's contract slice; the code-dependent rows (D7, D13, D25) at its closing slice. The client rows pinned to
#5324 (D9's client half) are re-read at its merge. E22-X02 carries its closing keyword only after the
re-pin (PR-2).

Counts for the 43 rows above (D1-D27, SR-E22-01..15, O-1): **PASS 24 · PARTIAL 5 · FAIL-T 4 ·
PROPOSED 4 · R 2 · A 3 · O 1**. D3 counts as PASS (its E08 half is R), D4 as PASS (its settings
half is PROPOSED).

## 2. Findings triage

Ids are public and stable. Scenario, mechanism, location and repro stay in the private E22 advisory draft
(C-12.13). None is High or Critical, so none opens a public bug issue (ruling 6637511507), and
none has a test in the public tree until its fix PR lands with the regression test.

<!-- prettier-ignore -->
| Id | Class | Severity | Status | Tracker |
| --- | --- | --- | --- | --- |
| PF-1 | Tampering | Low | Open | private E22 advisory draft; E22-X02 (#756) |
| PF-2 | Denial of service | Medium | Open | private E22 advisory draft; E22-X02 (#756) |
| PF-3 | Repudiation | Low | Open | private E22 advisory draft; E22-X02 (#756) |

## 3. Residual risks

Proposed for acceptance by the orchestrator under the 2026-10-29 delegation (Low and Medium only), review
date 2027-03-25, Owner ratification pending on #2701. None is accepted until recorded in §5.

<!-- prettier-ignore -->
| Residual | Rows | Severity | Rationale | State |
| --- | --- | --- | --- | --- |
| Read and subscription abuse attributable only through request logs | D8 | Low | Market data is public; C-2.9 records order, auth and key actions | proposed for acceptance; Owner sign-off pending: queued on #2701 |
| No cross-user side channel beyond the per-user caps | D11 | Low | `dropped` and responses are caller-scoped | proposed for acceptance; Owner sign-off pending: queued on #2701 |
| No privileged path beyond the own-scope settings write and the engine-value writer | D27 | Low | Asserted absent; AC19 enumerates | proposed for acceptance; Owner sign-off pending: queued on #2701 |
| A legitimate user at the per-user cap on hot symbols still costs real CPU; thin-symbol percentiles stay noisy | D17, D19; RSK-057 | Medium | Bounded, not removable; labelled | proposed for acceptance; Owner sign-off pending: queued on #2701 |

## 4. DAST, scans and drills

<!-- prettier-ignore -->
| Item | Where it runs | Verdict |
| --- | --- | --- |
| The eight cases of the ticket, in process over recorded `publicTrade` fixtures | `docs/security/abuse-cases/e22-big-trades.md` | per case there |
| A manual abuse session on staging | — | NOT EXECUTED: no staging profile exists (Deviation) |
| ZAP: `GET /market/trades` added to the existing `market` profile (`security/zap/nightly_plans.py`, `.zap/market-data.yaml` and its baseline) | the market nightly | PR-2 |
| Semgrep: threshold literals in `apps/web/src`; `asyncio.Queue()` without `maxsize` and unbounded print appends under `orderflow/` and `ws/` | `.semgrep/` with `ruleid:` / `ok:` fixtures | PR-2. The estimated-flag rule only for a construction site that bypasses the model; the `x-rbac` check is the RBAC route-matrix test (D26) |
| SAST, SCA and secret scans of the E22 paths | the required CI checks | PR-2 records the run |
| AC9, AC10, AC17, AC18 load and soak legs | E22-Q03 (#753), E22-Q04 | NOT EXECUTED |

## 5. Sign-off

Per the Agent-delivery adaptation and the 2026-10-29 delegation, sign-off is two lens rounds: a security
lens, then the Fable security pass as the Security-engineer record. Both are recorded here and as one row in
the model's review log; the model's header moves to Approved only after both. Low and Medium residuals (§3)
are accepted by the orchestrator under the delegation and recorded here with "Owner ratification pending on
#2701"; a High or Critical is never accepted, it is fixed first.

Process deviation: E22-X01's §12 asked for Security-engineer and Architect sign-off before E22-T01 and T02
started; neither was logged and both shipped. This review is that check.

<!-- prettier-ignore -->
| Round | Reviewer | Date | Head | Result |
| --- | --- | --- | --- | --- |
| Security lens | | | | pending |
| Fable security pass (Security-engineer record, 2026-10-29 delegation) | | | | pending |
| Residual acceptance (§3), orchestrator | | | | pending |
