# E07-D02 (#223): verification of the shipped `StorageUsage` payload

Status: verified, every result below is the outcome of the committed test file. Base: `584757638` <!-- BQ-02 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->.
Ticket: #223 `[E07-D02]`, Task, 2 pts, QA. Parents, all merged: E07-D01 (#166), E07-T05 (#225).
Served route: E16-T08 (#492). One PR, `Closes #223`. <!-- BQ-03 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->

Shorthand. `D01` = `docs/design/E07/E07-D01.md`. `HO` = `docs/design/E07/E07-D01-handoff.md`.
`22` = `docs/plan/22-api-openapi.yaml`. `T` = the ticket body. Test ids are functions of
`services/api/tests/contract/storage/test_storage_usage_verification.py`. Row ids are D01's and are
cited as written.

## 1. Scope and what was run

The check runs at the contract level. <!-- BQ-01 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) --> The real `DiskBudget.sample_once()` runs on a fake
meter. The real `GET /recording/storage` route serves the result through the real app. The test
reads that body. <!-- BQ-06 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->

The baseline path, with nothing hand-built. (1) The only fake is `FakeMeter`
(`tests/unit/recorder/_budget_fakes.py`): 300 GB recorded, a 1,000 GB volume half free, `BTCUSDT`
200 GB (pinned) and `ETHUSDT` 100 GB, a 600 GB cap. (2) The sampler is the real `DiskBudget` with the
real `BudgetConfig` and a fixed clock, one `sample_once()` call. (3) The route is the real
`GET /recording/storage` mounted by the real `create_app()` in the RBAC pack's world, called as the
Owner. (4) The body is written with `json.dumps(body, indent=2)` to
`packages/fixtures/golden/storage/storage_usage_baseline.golden.json`, the shared TS + Python golden
directory that `packages/fixtures/scripts/verify.mjs` gates, and the frozen reference for E16.
It is not the `22` example and not the output of `build_storage_usage` (D01 section 5). The figures
come from a fake meter and are not a measurement of any disk. One test compares a fresh run with the
committed bytes; a change to the shape, the key order or a sampler rule turns it red. To refresh the
file, run `python -m tests.contract.storage.test_storage_usage_verification --write-baseline` from
`services/api` on purpose; it is not a pytest option.

Run: 97 of 97 tests passed on 2026-11-01. Nothing touches the network.
No test sleeps. No test skips (AGENTS.md section 8 rule 4). <!-- BQ-04 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->

Not run, and not claimed:

- the live `make up` stack with a recorded symbol-day (it needs a live public feed, which the
  fixture rule forbids in tests);
- the eight state-forcing scenarios on real stores (a stopped QuestDB, a filled volume, a bad
  checksum, a bumped migration version). States with a field are driven on the fake meter. States
  without a field are pinned as gaps (section 5);
- the `21` section 14 measured values (they need a real run);
- the latency budget (E07-Q03 owns it).

All four are listed UNVERIFIED in section 9.

## 2. Field checklist: field, observed value, test, result (AC1) <!-- BQ-05 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->

One row per `CK` row of HO section A. "Observed" comes from the frozen baseline.
Accepted exceptions are copied from D01 section 4.2 and are not re-opened.

| Id           | Field                  | Observed                                                                | Test id                                                                                                                                                                                            | Result |
| ------------ | ---------------------- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| CK-01        | `disk_total_bytes`     | 1000000000000 bytes                                                     | test_baseline_field_has_its_schema_type                                                                                                                                                            | PASS   |
| CK-02        | `disk_used_bytes`      | 500000000000 bytes                                                      | test_baseline_field_has_its_schema_type, test_baseline_disk_used_is_total_minus_free_x1                                                                                                            | PASS   |
| CK-03        | `disk_free_bytes`      | 500000000000 bytes                                                      | test_baseline_field_has_its_schema_type                                                                                                                                                            | PASS   |
| CK-04        | `projected_full_at`    | null                                                                    | test_baseline_field_has_its_schema_type, test_first_sample_has_no_projection_and_zero_growth_em08_f04, test_projection_is_null_beyond_one_hundred_years_u05                                        | PASS   |
| CK-05        | `daily_growth_bytes`   | 0 bytes per day                                                         | test_baseline_field_has_its_schema_type, test_first_sample_has_no_projection_and_zero_growth_em08_f04                                                                                              | PASS   |
| CK-06        | `tiers[]`              | questdb 150 GB (7 days), parquet 150 GB (30 days), postgres 1 GB (null) | test_baseline_tier_rows_follow_the_tier_order, test_baseline_retention_days_are_7_30_and_null, test_tier_rows_carry_no_growth_d04_g1_not_expressible                                               | PASS   |
| CK-07        | `symbols[]`            | BTCUSDT 200 GB pinned, ETHUSDT 100 GB                                   | test_baseline_symbols_are_sorted_largest_first, test_symbols_are_capped_at_64_largest_first_x2                                                                                                     | PASS   |
| CK-07.pinned | `symbols[].pinned`     | BTCUSDT true, ETHUSDT false                                             | test_baseline_symbol_rows_carry_the_pinned_flag_ck_07_pinned, test_pinned_flag_follows_the_pin_source_ck_07_pinned, test_level_three_payload_has_no_pinned_exemption_field_d01_c_c_not_expressible | PASS   |
| CK-08        | `generated_at`         | `2026-09-21T14:13:20Z`                                                  | test_baseline_timestamps_are_utc_date_times                                                                                                                                                        | PASS   |
| CK-09        | `cap_bytes`            | 600000000000 bytes                                                      | test_baseline_cap_bytes_is_at_least_one                                                                                                                                                            | PASS   |
| CK-10        | `level`                | 0                                                                       | test_baseline_enum_values_are_in_the_schema_set, test_state_payload_names_level_gate_reason_and_flag                                                                                               | PASS   |
| CK-11        | `write_gate`           | `open`                                                                  | test_baseline_enum_values_are_in_the_schema_set, test_state_payload_names_level_gate_reason_and_flag                                                                                               | PASS   |
| CK-12        | `write_gate_reason`    | `null`                                                                  | test_baseline_enum_values_are_in_the_schema_set, test_write_gate_reason_stays_in_the_closed_set_d01_g1_not_expressible                                                                             | PASS   |
| CK-13        | `accelerate_retention` | False                                                                   | test_state_payload_names_level_gate_reason_and_flag                                                                                                                                                | PASS   |

What every row also asserts: the field is present, the JSON type is the schema's, the field set is
exactly the 13 names (`test_baseline_field_set_is_exactly_the_schema_fields`), the body validates
against the `22` schema, and the only nullable fields are `projected_full_at`, `write_gate_reason`
and `tiers[].retention_days` (`test_nullable_fields_are_exactly_the_schema_nullable_fields`).

Units, by name, as D01 section 4.1 gives them: bytes, bytes per day, UTC date-time, a level 0 to 3,
a bool. The unit is a property of the field, not of the value.

Accepted exceptions: X-1 `disk_used_bytes` (derivable, kept for the volume meter; the test pins the
arithmetic). X-2 the `symbols[]` cap of 64 (the test pins it; the schema is silent, D01-G5).

## 3. Decision rows: every decision has fields or a gap (AC1)

Test: `test_decision_row_names_real_fields_or_a_recorded_gap`, one case per `DL` row.
Result of the whole table: PASS.

| Id    | Question                          | Fields                                                                                                            | Gap                        |
| ----- | --------------------------------- | ----------------------------------------------------------------------------------------------------------------- | -------------------------- |
| DL-01 | Am I about to run out of disk?    | `level`, `disk_free_bytes`, `disk_total_bytes`, `cap_bytes`, `daily_growth_bytes`, `tiers[]`, `projected_full_at` | none                       |
| DL-02 | What stops working first?         | `level`, `write_gate`, `write_gate_reason`, `accelerate_retention`                                                | none                       |
| DL-03 | Is a migration pending?           | none                                                                                                              | D04-G7                     |
| DL-04 | Is a tier lagging or unreachable? | none (health report, another surface)                                                                             | D04-G1 (see D01 section 3) |
| DL-05 | Is this symbol's data pinned?     | `symbols[].pinned`                                                                                                | none                       |
| DL-06 | Which symbol grows fastest?       | `symbols[].daily_growth_bytes`, `symbols[].used_bytes`                                                            | none                       |
| DL-07 | How old is this reading?          | `generated_at`                                                                                                    | none                       |
| DL-08 | Did an export fail verification?  | none                                                                                                              | D01-G1                     |
| DL-09 | How fast is each tier growing?    | `daily_growth_bytes` (net)                                                                                        | D04-G1                     |
| DL-10 | How long is each tier kept?       | `tiers[].retention_days`                                                                                          | none                       |

Zero rows are unowned. DL-03, DL-04 and DL-08 have no field. They are reported here once, as
"not expressible today", and are not a new defect (HO section C item 7).

## 4. States (AC2, AC4) <!-- BQ-07 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->

"Driven" means the test makes the sampler reach the state and reads the served body.
"Pinned" means the payload has no field for it today, so a closed-world test fails the day a field
appears. There is no skip and no expected-failure mark.

| Id    | State                                                  | How the test reaches it                                                | Test id                                                                                                    | Result |
| ----- | ------------------------------------------------------ | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ------ |
| ST-01 | healthy                                                | driven: half the volume free, 300 GB of 600 GB                         | test_state_payload_names_level_gate_reason_and_flag                                                        | PASS   |
| ST-02 | near limit                                             | driven: 500 GB of the 600 GB cap, level 1                              | test_state_payload_names_level_gate_reason_and_flag                                                        | PASS   |
| ST-03 | auto-record paused, accelerated retention              | driven: 10 % free, level 2, flag true                                  | test_state_payload_names_level_gate_reason_and_flag                                                        | PASS   |
| ST-04 | recording stopped for symbols without an open position | driven: 4 % free, level 3, gate closed, `disk_halt`                    | test_state_payload_names_level_gate_reason_and_flag                                                        | PASS   |
| ST-05 | recording volume refused                               | driven: refused flag, gate closed, `volume_refused`                    | test_state_payload_names_level_gate_reason_and_flag                                                        | PASS   |
| ST-06 | stale sample                                           | driven: the monotonic clock moves past 3 x 60 s                        | test_stale_sample_reads_level_three_with_the_old_generated_at_st06                                         | PASS   |
| ST-07 | export check failed, hot data kept                     | pinned: no field (D01-G1)                                              | test_payload_has_no_tier_alerts_d01_g1_not_expressible                                                     | PASS   |
| ST-08 | schema differs from the registry                       | pinned: no field (D01-G1)                                              | test_payload_has_no_tier_alerts_d01_g1_not_expressible                                                     | PASS   |
| ST-09 | a tier unreachable                                     | on another surface; the payload shows only an empty `tiers[]` (D02-F1) | test_failed_first_breakdown_gives_empty_tiers_with_valid_free_space_fields_d02_f1                          | PASS   |
| ST-10 | migration pending                                      | pinned: no field (D04-G7)                                              | test_payload_has_no_migration_field_d04_g7_not_expressible                                                 | PASS   |
| ST-11 | writes behind the feed                                 | on another surface; the 13-field set has no lag field                  | test_baseline_field_set_is_exactly_the_schema_fields                                                       | PASS   |
| ST-12 | figures not available yet                              | driven: 503 before the first sample or with no budget                  | test_no_sample_yet_is_a_503_problem_without_figures_st12_em01, test_no_budget_is_the_same_503_problem_em02 | PASS   |

The ticket's eight states map as: healthy ST-01; migration pending ST-10; lag warning ST-11;
accelerated retention ST-03; critical ST-04; `STORAGE_TIER_UNAVAILABLE` ST-09;
`STORAGE_EXPORT_VERIFY_FAILED` ST-07; `STORAGE_SCHEMA_DRIFT` ST-08.

Machine values. Every state a payload can show has a machine value in `level`, `write_gate` and
`write_gate_reason`. The words live in the D04 copy deck. No consumer has to read colour. This is the
only accessibility check made here. The WCAG audit is E16-Q05 and E16-D07.

Ordering. The critical states are `level` 3 and a closed gate. The consequence sentence is D04's
(`storage.degradation`, cited by key in D01 section 7.1). Open positions keep recording at level 3.
The ticket's claim that pinned symbols are exempt holds for retention only (D01 section 7.3, F-07).

## 5. Gaps pinned, one test each

| Gap    | What is missing                                  | Test id                                                                                                                       | Result |
| ------ | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- | ------ |
| D01-G1 | `tier_alerts[]`, and a wider `write_gate_reason` | test_payload_has_no_tier_alerts_d01_g1_not_expressible, test_write_gate_reason_stays_in_the_closed_set_d01_g1_not_expressible | PASS   |
| D01-G2 | the three tier codes in the error surface        | test_openapi_names_no_storage_tier_code_d01_g2_not_expressible                                                                | PASS   |
| D01-G3 | `daily_growth_bytes` nullable                    | test_daily_growth_is_never_null_d01_g3_not_expressible                                                                        | PASS   |
| D01-G4 | a tier-migration route                           | test_no_tier_migration_route_d01_g4_not_expressible                                                                           | PASS   |
| D01-G5 | the `symbols[]` cap in the schema                | test_symbols_schema_has_no_cap_d01_g5_not_expressible                                                                         | PASS   |
| D01-G6 | the metric `pg_migration_pending`                | test_pg_migration_pending_is_not_registered_d01_g6_not_expressible                                                            | PASS   |
| D01-G7 | `projection_wall`                                | test_payload_has_no_projection_wall_d01_g7_not_expressible                                                                    | PASS   |
| D04-G1 | per-tier growth and projection                   | test_tier_rows_carry_no_growth_d04_g1_not_expressible                                                                         | PASS   |
| D04-G7 | schema version, target version, pending count    | test_payload_has_no_migration_field_d04_g7_not_expressible                                                                    | PASS   |
| D04-G8 | a vacuum route and job kind                      | test_no_vacuum_route_d04_g8_not_expressible                                                                                   | PASS   |

How a pin closes. An owner ships the gap. The pin goes red. The same PR updates the test, this
report and the baseline. That is the re-verification the ticket asks for. Nothing is filed here.
<!-- BQ-10 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->

## 6. Unreachable versus empty, and the projection

### 6.1 Unreachable versus empty (AC2) <!-- BQ-08 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->

When the breakdown fails before any success, `tiers` and `symbols` are empty lists. The volume
fields and the level are valid. The payload cannot tell that case from a store that is reachable and
empty. This differs from D01's "yes, on another surface" (HO ST-09): the health report can tell, the
`StorageUsage` payload cannot, and the ticket's second Gherkin asks the response itself to
distinguish the two. When a later breakdown fails, the last sizes are kept. When the volume read fails, there is no
report and the route answers 503. Finding D02-F1.

Tests: `test_failed_first_breakdown_gives_empty_tiers_with_valid_free_space_fields_d02_f1`,
`test_failed_later_breakdown_keeps_the_last_tier_sizes`, `test_failed_volume_read_gives_no_report`.
Result: PASS.

### 6.2 The 503 as a state (EM-01, EM-02)

Status 503, content type `application/problem+json`, code `store_unavailable`, detail without a
number, and none of the 13 field names in the body. Tests: ST-12 row above. Result: PASS.

### 6.3 No projection (AC5, EM-08, F-04) <!-- BQ-09 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->

| Case                                             | Test id                                                            | Result |
| ------------------------------------------------ | ------------------------------------------------------------------ | ------ |
| first sample: `projected_full_at` null, growth 0 | test_first_sample_has_no_projection_and_zero_growth_em08_f04       | PASS   |
| growth unknown, zero or negative: null           | test_projection_is_null_when_growth_is_unknown_or_not_positive_u05 | PASS   |
| a wall over 100 years away: null, not a date     | test_projection_is_null_beyond_one_hundred_years_u05               | PASS   |
| a wall exactly 100 years away: a date            | test_projection_is_a_date_at_exactly_one_hundred_years             | PASS   |
| the nearer of the two walls                      | test_projection_names_the_nearer_wall_u03                          | PASS   |
| no estimate flag in the payload                  | test_route_marks_no_estimate_field_the_word_is_the_clients_u08     | PASS   |

The ticket asks that the response marks the projection as an estimate. The payload has no such
field. D01 ruled the label is the client's ("about", U-08) and that the payload carries no label
(Q-01). This is recorded as an accepted exception in the Deviations table of section 11 (row 4),
not as "met": the clause is read through a client rule, not through the response. No new gap row.

## 7. The no-path scan (AC6) <!-- BQ-11 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->

The patterns are D01's. The test loads `NOPATH_PATTERNS` and `nopath_hits` from the D01 tool by file
path, so there is one list. It fails if either name is missing.

Scanned: every string value of the baseline, of each state's body (ST-01 to ST-05), and the body of
the 503 problem. Not scanned: the text of `STORAGE_*` errors, because no route returns it (F-03).

| Scan                 | Test id                                                  | Result |
| -------------------- | -------------------------------------------------------- | ------ |
| the patterns load    | test_nopath_patterns_load_from_the_d01_tool              | PASS   |
| the baseline         | test_baseline_strings_have_no_path_or_credential_shape   | PASS   |
| every driven state   | test_every_state_payload_has_no_path_or_credential_shape | PASS   |
| the 503 problem body | test_503_problem_has_no_path_or_credential_shape         | PASS   |

## 8. Access, names and cadence

### 8.1 Access (RULED BQ-12) <!-- BQ-12 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->

The assignment says Owner-only. The shipped rule is split. Writes are the Owner's alone
(`recording:write`, #5265). The read `GET /recording/storage` is `recording:read`, and all four roles
may read it. A non-Owner gets a reduced `symbols[]`: no symbol held only by a hidden cause. D01 section 10.2
says non-Owners get "no `symbols[]`"; the route only filters (finding D02-F2).
The screen SCR-142 is Owner-only in the UI (D01 section 10).

| Check                                                   | Test id                                                   | Result |
| ------------------------------------------------------- | --------------------------------------------------------- | ------ |
| owner, manager with grant, manager without, viewer: 200 | test_every_role_reads_storage_with_recording_read         | PASS   |
| the Owner sees every recorded symbol                    | test_owner_sees_every_recorded_symbol                     | PASS   |
| a non-Owner sees no symbol held only by a hidden cause  | test_non_owner_sees_no_symbol_held_only_by_a_hidden_cause | PASS   |
| unauthenticated: 401 problem                            | test_unauthenticated_storage_read_is_a_401_problem        | PASS   |
| no `recording:read`: 403 and an audit entry             | test_storage_without_recording_read_is_403_and_audited    | PASS   |
| compaction is Owner-only in the route matrix            | test_compaction_is_owner_only_in_the_route_matrix         | PASS   |

Vacuum and tier migration have no route (D04-G8, D01-G4): they are "no route" rows, not tests of
access. The audit row name of compaction is not re-tested here (D04-C1). The route matrix and the E16
tests own it.

### 8.2 Names (RULED BQ-13) <!-- BQ-13 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->

D01 section 11 lists 15 names: 10 are read here and found (8 metrics and the two audit names of `22`),
1 is pinned absent (`pg_migration_pending`), and the 4 `storage.*` audit names of `14` are catalogue
names not tested here (D01 counts 3 absent: that metric and two audit names with no route).
The metric names that exist are read from the default metrics registry, with the owner modules
imported, and from the metric catalogue (`questdb_write_seconds` is declared there only). `pg_migration_pending` is pinned
absent (D01-G6). The two audit names `recorder.import` and `retention.purge` are read from `22`.
The audit names `storage.panel_viewed`, `storage.compaction_triggered`, `storage.vacuum_triggered` and
`storage.tier_migration_triggered` are catalogue names in `14` and are not tested here.

| Name                                         | State at D01       | Test id                                                            | Result |
| -------------------------------------------- | ------------------ | ------------------------------------------------------------------ | ------ |
| `storage_export_rows_total`                  | exists             | test_listed_metric_name_is_registered                              | PASS   |
| `storage_export_duration_seconds`            | exists             | test_listed_metric_name_is_registered                              | PASS   |
| `storage_export_verify_failures_total`       | exists, not listed | test_listed_metric_name_is_registered                              | PASS   |
| `storage_retention_dropped_bytes_total`      | exists             | test_listed_metric_name_is_registered                              | PASS   |
| `storage_disk_free_ratio`                    | exists             | test_listed_metric_name_is_registered                              | PASS   |
| `questdb_write_seconds`                      | exists             | test_listed_metric_name_is_registered                              | PASS   |
| `recorder_disk_budget_breakdown_age_seconds` | exists, not listed | test_listed_metric_name_is_registered                              | PASS   |
| `disk_budget_sample_failed_total`            | exists, not listed | test_listed_metric_name_is_registered                              | PASS   |
| `pg_migration_pending`                       | absent (D01-G6)    | test_pg_migration_pending_is_not_registered_d01_g6_not_expressible | PASS   |
| `recorder.import`, `retention.purge`         | exists in `22`     | test_audit_name_is_in_the_openapi_document                         | PASS   |

The export verification failure event (a CRITICAL system event) is owned by the exporter's unit
test (`tests/unit/storage/cold/test_exporter.py`). It is cited, not repeated.

### 8.3 Cadence

The route serves the last sample and never measures per request. Test:
`test_route_serves_the_last_sample_without_measuring`. Result: PASS. <!-- BQ-14 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->

## 9. Findings from D01 and new findings

### 9.1 D01 findings, read into this check

Cited as written. A row with a test is traced. A row with `n/a` is a text finding with no payload
behaviour to test.

| Id   | Severity | Finding in one line                                        | Test id                                                                                                           | Result |
| ---- | -------- | ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------ |
| F-01 | Major    | export verification failure has no field                   | test_payload_has_no_tier_alerts_d01_g1_not_expressible                                                            | PASS   |
| F-02 | Major    | three owners state the thresholds three ways               | n/a (text finding, D01 section 6)                                                                                 | PASS   |
| F-03 | Major    | three tier codes are in no part of `20`, `22` or `24`      | test_openapi_names_no_storage_tier_code_d01_g2_not_expressible                                                    | PASS   |
| F-04 | Minor    | unknown and flat growth read the same                      | test_first_sample_has_no_projection_and_zero_growth_em08_f04                                                      | PASS   |
| F-05 | Minor    | `build_storage_usage` has 8 fields and one caller          | test_build_storage_usage_is_the_eight_field_shape_f05                                                             | PASS   |
| F-06 | Minor    | the schema is silent on the `symbols[]` cap and the wall   | test_symbols_schema_has_no_cap_d01_g5_not_expressible, test_payload_has_no_projection_wall_d01_g7_not_expressible | PASS   |
| F-07 | Minor    | the exemption of pinned symbols sits beside retention only | n/a (text finding, D01 section 7.3)                                                                               | PASS   |
| F-08 | Info     | `recording:write` is the Owner's alone                     | test_compaction_is_owner_only_in_the_route_matrix                                                                 | PASS   |
| F-09 | Minor    | `pg_migration_pending` exists nowhere                      | test_pg_migration_pending_is_not_registered_d01_g6_not_expressible                                                | PASS   |
| F-10 | Minor    | no vacuum or tier-migration route                          | test_no_vacuum_route_d04_g8_not_expressible, test_no_tier_migration_route_d01_g4_not_expressible                  | PASS   |
| F-11 | Info     | the ticket's sprint is past                                | n/a (calendar, section 11)                                                                                        | PASS   |
| F-12 | Info     | the sitemap has no SCR-142 route row                       | n/a (text finding, D01 section 14)                                                                                | PASS   |

F-05 evidence. At the base, `git grep build_storage_usage` outside `docs/` finds the definition
(`services/api/candleviewer/storage/retention/usage.py`) and one caller, its own unit test
(`tests/unit/storage/test_retention_schedule_usage.py`). This PR adds a second test caller, the shape pin. This PR does not retire it (a production edit
outside a test PR). The test pins its 8-field shape, so aligning or retiring it forces an update.

### 9.2 New findings (D02-F) <!-- BQ-10 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->

Severity set and owner tokens are D01's. Nothing is filed and nothing is fixed in this PR. The
orchestrator files what it chooses from this table.

| Id     | Severity | Finding                                                                                                                                                                                                                                 | Shown by                                                                          | Owner                                                          |
| ------ | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| D02-F1 | Major    | "tier unreachable" cannot be told from "reachable but empty" in the payload: a failed first breakdown gives `tiers: []`; the unreachable state lives on the health report only. Differs from D01's "yes, on another surface" (HO ST-09) | test_failed_first_breakdown_gives_empty_tiers_with_valid_free_space_fields_d02_f1 | `22 · area/backend-platform`, `E16-T07 · area/recorder-replay` |
| D02-F2 | Minor    | D01 section 10.2 says non-Owners get "no `symbols[]`", while the route only filters symbols held only by a hidden cause; a non-Owner still gets a `symbols[]` with the visible symbols                                                  | test_non_owner_sees_no_symbol_held_only_by_a_hidden_cause                         | `E07-D01 · area/backend-platform`                              |
| D02-F3 | Minor    | `build_storage_usage` is still in the tree with one caller, its own test (F-05 re-confirmed at the base)                                                                                                                                | test_build_storage_usage_is_the_eight_field_shape_f05                             | `E07-T05 · area/backend-platform`                              |
| D02-F4 | Info     | the ticket says Owner-only for the storage read; the shipped rule is `recording:read` for all four roles with a reduced view for non-Owners. The report uses the shipped rule                                                           | test_every_role_reads_storage_with_recording_read                                 | `E07-D02 · area/backend-platform`                              |
| D02-F5 | Info     | the live-stack run, the real-store state runs, the `21` section 14 values and the latency budget are not done here                                                                                                                      | none (section 1)                                                                  | `E07-Q01 / E07-Q03 / E07-Q04 · area/backend-platform`          |

Counts: D02-F 5 (Major 1, Minor 2,
Info 2). No row is Blocking: every decision with a field is answered, and the
decisions with no field are accepted gaps.

## 10. Defects and re-verification (AC7) <!-- BQ-03 RULED (orchestrator, 2026-11-01, #223 ruling of record 6555029325) -->

Ruling: `Closes #223`. The ticket's "defects filed, fixed and re-verified" is read under the filing
freeze as "recorded as D02-F rows in this report, with severity and owning area, re-verified where
the owning fix lands" (the D01 sections 17.2 and 17.4 precedent). None is filed or fixed in this PR.
The pins in section 5 and the test of D02-F1 turn red when an owner fixes the gap; that PR updates
the test, this report and the baseline, and that is the re-verification. What is not met is named in
the Deviations table of section 11, not claimed.

Sign-off. The orchestrator's design approval plus this QA record stand in for the Architect and CDO
re-review. The verified sample is frozen as the E16 reference fixture (see
`packages/fixtures/golden/storage/storage_usage_baseline.golden.json`). E07-D01 is confirmed by this check: no decision lacks an owner.
Whether #166 moves to Done is the orchestrator's call.

Owner walkthrough, post-Done, at most eight items, not a gate: (1) the `CK` table with observed
values; (2) the three decisions with no field; (3) the closed-world pins and why they are not skips;
(4) "No projection yet" and the estimate reading; (5) D02-F1; (6) the Owner-only wording for read
and write; (7) the 503 sentence; (8) the fixture path for E16. No participant is seen, no session is
run and no timing or quote is written. Test results are the only measured facts.

## 11. Consumers, calendar and deviations

Consumers: E16-D04 (closed); E16-S04 (#486, Sprint 08, 2026-11-13 to 2026-11-19), which takes
D01-G1, G3, G4 and G7 at its Ready gate; E16-Q05 (#482, Sprint 08); E16-D07 (#565, Sprint 09,
2026-11-20 to 2026-11-26). D02's own Sprint 03 ended 2026-10-15. Dates are D01's calendar lines,
not re-run through the calendar tool.

Out of scope, as the ticket states: any screen or React code; the WCAG 2.2 AA audit, axe, screen
reader and keyboard runs, live regions, contrast, reduced motion.

Deviations from the ticket. Ruled `Closes #223` (BQ-03, orchestrator, 2026-11-01, #223 ruling of
record 6555029325): each unmet or changed item is named here and none is claimed as met.

| #   | Ticket text                                                                             | What this PR does                                                                                                                       | Status                                           | Owner                 |
| --- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ | --------------------- |
| 1   | Branch `test/storage-contract-verification`, PR <= 300 lines                            | the branch is the claim's; the diff is about 1000 counted lines (test, report, fixtures README bullet)                                  | deviation, `large-pr-approved` requested at open | orchestrator          |
| 2   | DoD: "Defects filed, fixed and re-verified"                                             | defects are recorded as D02-F1..F5 with severity and owning area; re-verified where the owning fix lands                                | deviation under the filing freeze                | owners in section 9.2 |
| 3   | AC7: defects filed and fixed, Architect and CDO re-review, E07-D01 confirmed Done       | nothing is filed or fixed; the orchestrator's approval plus this record stand in for the re-review; the Done call is the orchestrator's | NOT met, named here                              | orchestrator          |
| 4   | AC5: "the response marks the projection as an estimate"                                 | the payload has no marker; the word is the client's rule (D01 U-08, Q-01)                                                               | accepted exception, not "met"                    | `E07-D01`, `E16-S04`  |
| 5   | DoD: `22` updated if the example diverged; `21` section 14 updated with measured values | no edit to `22` or `21`; the example was not compared with a live run and no measured value exists                                      | NOT met, named here (UNVERIFIED 1)               | `E07-Q01`, `E07-Q03`  |
| 6   | Eight state-forcing runs on real stores, live `make up` run                             | states with a field are driven on a fake meter; the rest are closed-world pins                                                          | deviation, listed in section 12                  | `E07-Q01`, `E07-Q04`  |

No new audit tool.

Coverage. No production code is added, so the floors of `services/api/**` are unchanged.

## 12. UNVERIFIED

1. The live `make up` run and the real-store states.
2. What the real meter returns for an empty store.
3. (Resolved by the run: the token-shaped pattern passes on the baseline's date-time strings.)
4. (Resolved by the run: the metric names are read from the registry and the catalogue, see 8.2.)
5. Which test pins the compaction audit name.
6. How `packages/fixtures/golden` is consumed by the TypeScript side.
7. The calendar lines of section 11.
8. Every result above is a run of the committed test file; nothing else was measured.
