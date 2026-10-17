# E35 — STRIDE threat model: Rule engine IR, compiler and runtime

- Ticket: E35-X01 (issue #945)
- Owner: Security engineer (CODEOWNER)
- Status: Draft - pending owner approval (Agent-delivery adaptation: Security engineer / Architect / rule-engine backend lead sign-off is replaced by owner approval, recorded in section 11)
- Extends `docs/plan/04-security-program.md` section 5 and follows the template of `docs/security/threat-models/e16-recorder.md`, so the R3 epic models are comparable at the train gate. Threat ids are prefixed `RE-`; new requirements are `E35-FR-nn`.
- Classification of this document: internal (it enumerates weaknesses; no credentials or host details).
- Authoritative design: `docs/plan/24-internal-schemas.md` section 11 (IR, E1-E13, vocabulary, safety limits), ADR-0007, `docs/plan/21-database-schema.md` section 3.4, B9 in `docs/plan/28-statechart-catalogue.md`.

## 1. Scope and assumptions

E35 is the only subsystem that can place, modify and cancel orders with no human present. A rule has a person only at authoring time, possibly weeks earlier, possibly under different permissions than that person holds now.

Components modelled:

| Id | Component | Ticket | Role |
| --- | --- | --- | --- |
| C1 | Editor clients (form / node) | E36, E37 (boundary only) | Produce IR + `graph_layout` / `form_model` |
| C2 | Compile / validate / vocabulary API | E35-T03, E35-T04 | `/rules/validate`, `/rules/{id}/compile`, `/rules/vocabulary` |
| C3 | Rule store | E35-T01, E35-T02, E35-S01 | `rules`, `rule_versions`, `ir_hash`, mode switch, arming |
| C4 | Evaluator | E35-S02 | Deterministic, snapshot-based, guarded, timeout-bounded |
| C5 | Action executor | E35-S03 | Actions to the OMS under per-rule limits |
| C6 | Scope enforcer | E35-S04 | Runtime scope / grant check on every action |
| C7 | `pre_trade_check` hook | E35-S02, E35-S03 | Synchronous veto path in order submission |
| C8 | Signal bus (`emit_signal` / `on_signal`) | E35-S02 | Rule-to-rule messaging |
| C9 | Firing log + `rules` WS topic | E35-S06 | `rule_runs`, append-only `rule_events`, 250 ms WS fan-out |
| C10 | Conflict arbitration | E35-S07 | Arming-time detection, runtime arbitration |
| C11 | Simulation / auto-backtest | E35-S05 | Executes nothing, records would-be actions |
| C12 | Import / export bundles | E35-S09 | Rule bundles crossing the instance boundary |
| C13 | Upcasters + built-in system rules | E35-T05 | IR version migration, `sys.*` rules |
| C14 | Metric bus | E25 / E26 consumer | Source of `MetricSnapshot` values |

Attacker model:
- **A1** lower-privileged authenticated user (Viewer, or Manager acting outside their account scope).
- **A2** compromised browser session of any role.
- **A3** malicious or corrupted rule bundle (import) or a hostile IR posted directly to the API.
- **A4** well-meaning author whose rule is wrong, or whose grants change after authoring (the permission-drift case).
- **A5** malicious or compromised Manager (AC-14 in `04-security-program.md`), the primary insider threat.

**Explicit assumption:** the product is reachable only over Tailscale (TB-1). An unauthenticated internet attacker is NOT modelled; if that boundary changes this model must be re-run.

Consumed, not repeated: OMS (E29), key vault (E27), RBAC (E09), kill switch (E39) models. This model relies on their conclusions: the OMS enforces profile and risk caps and the native SL after a rule acts (section 11.7 of the schemas doc, C-2.6); RBAC is server-side (C-12.4).

Out of scope: editors' own surface such as XSS in a node label (E36/E37; boundary noted at TB-R1), implementing controls (filed as findings, section 8), pen-test (E43).

## 2. Data-flow diagram and trust boundaries

Boundaries extend `04-security-program.md` section 4 (TB-1 browser to API, TB-3 backend to stores). Rule-engine-specific boundaries are `TB-R1..TB-R9`.

```text
 Editor C1 (A1/A2/A3) --TB-R1--> [C2 validate/compile] --typed IR--> [C3 rule store]
                                     ^ vocabulary (per-user availability)       |
                                     |                                  arm (step-up, ir_hash audit)
 Import bundle C12 (A3) --TB-R9--> [C2] (same path as API)                       v
 Metric bus C14 --TB-R4--> [C4 evaluator] <--TB-R3-- load armed versions -- [C3]
                              |  \__ emit_signal --TB-R6--> [C8 signal bus] --on_signal--> [C4] (other rules)
                              |  pre_trade_check (sync, TB-R5) <---- order submit path (all users)
                              v
                        [C6 scope enforcer] --TB-R5--> [C5 executor] ---> OMS (profile + risk caps, native SL)
                              |
                              +--TB-R7--> [C9 firing log: rule_runs / rule_events (append-only)]
                                              |--TB-R8--> WS topic `rules` (grant-intersected)
 Simulation C11: same pipeline, executor replaced by recorder of SimulatedAction (TB-R2 store access read-only)
```

Structural facts the diagram must not hide:
- `pre_trade_check` is a **synchronous** path inside every order submission (300 ms budget); a slow rule there degrades all users (shared fate).
- `emit_signal` is a second bus on which one rule triggers another; it is the only rule-to-rule channel.
- `graph_layout` and `form_model` are stored beside the IR but excluded from `ir_hash`.
- Import/export is a full second entry path for IR, and WS fan-out is a second egress path for firing data.

## 3. Rating scale

L = likelihood, I = impact (H/M/L). Risk: Critical (H/H), High, Medium, Low. Residual is after the listed control. "Detect" names the audit event or metric that would reveal the threat (SR-125); "none" is recorded where no detection exists. Severity is CVSS-informed: network-adjacent (Tailscale), authenticated, impact on integrity of orders.

Mitigations cite `Ticket` and `Test`. A `(pending: E35-FR-nn)` marker means no shipped control yet; the finding in section 8 owns it and the threat stays at its unmitigated rating until it ships.

## 4. STRIDE enumeration

Existing controls referenced: C-2.6 native SL, C-2.9 audit, C-2.21 sync code enforces, C-4.14, C-12.4 server-side RBAC, C-12.6 redaction, SR-125 security metrics, ADR-0007 principles R1-R6, schemas section 11.7 (limits, Panic, live gate, new-rule gate, feedback-loop guard, disconnect guard).

### 4.1 Spoofing

| T | Comp | Threat | A | L | I | Risk | Control (ticket / test) | Residual | Detect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RE-S1 | C3, C5 | A rule-originated order is attributed to the arming user current session identity or to a generic actor, so a Manager rule appears as an Owner action (or the reverse) | A5 | M | H | High | Every rule order carries actor `rule:<rule_id>@v<n>` plus `armed_by` user id and role as at arming; the OMS audit record stores both (E35-S03; `test_rule_order_audit_actor_is_rule_with_armer`). **E35-FR-01**: assert the executor never reads the current HTTP session | Low | audit `rule.order_submitted` |
| RE-S2 | C3 | Arming via a stolen/replayed session | A2 | L | H | Medium | Arming needs fresh step-up (TOTP) and records `ir_hash`, user, scopes (E35-S01; `test_arm_requires_step_up`); live scope adds a second confirmation (schemas 11.7) | Low | audit `rule.armed`, step-up failure metric |
| RE-S3 | C8 | `emit_signal` / `on_signal` used so rule A of user X triggers rule B of user Y, making Y act on X say-so | A1, A5 | M | H | High | Signals are namespaced by `owner_id`; delivered only to rules with the same owner (E35-S02, **E35-FR-02**; `test_signal_never_crosses_owner_boundary`). Cross-owner chaining is not a feature | Low | `rule_signal_cross_owner_rejected_total` |
| RE-S4 | C12 | Imported bundle claims an author/owner/`armed_by` it does not have | A3 | M | M | Medium | Import ignores every identity and mode field: imported rules are created as `draft`, owned by the importing user, never armed (E35-S09, **E35-FR-03**; `test_import_resets_owner_mode_and_arming`) | Low | audit `rule.import` |
| RE-S5 | C9 | WS client subscribes to `rules` for another user rules | A1 | L | M | Medium | Server-side topic ACL on subscribe and per frame (C-12.4; E35-S06; `test_rules_ws_rejects_foreign_rule_ids`) | Low | WS permission-failure metric |

### 4.2 Tampering

| T | Comp | Threat | A | L | I | Risk | Control (ticket / test) | Residual | Detect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RE-T1 | C3 | Stored IR changed after arming so executed logic differs from what the user approved | A1, A2 | L | H | Medium | `rule_versions` immutable once armed (R5; no UPDATE grant on armed rows); `ir_hash` of the canonical form recorded in the arming audit; evaluator recomputes and refuses a version whose hash differs, then auto-disables (E35-T01, E35-S01, **E35-FR-04**; `test_loader_rejects_ir_hash_mismatch`) | Low | `rule_ir_hash_mismatch_total`; audit `rule.auto_disabled` |
| RE-T2 | C3 | Semantic content smuggled in `graph_layout` / `form_model` (excluded from the hash), e.g. a threshold the evaluator later reads | A3, A5 | M | H | High | Evaluator and compiler read only the typed IR; `graph_layout` / `form_model` are opaque, size-capped, `extra="forbid"`-validated JSON never consumed by C4/C5 (E35-T01, **E35-FR-05**; `test_evaluator_ignores_layout_fields`, import-linter contract forbidding the evaluator from importing the layout models) | Low | none (test-only) |
| RE-T3 | C3 | jsonb key reordering changes stored text yet the hash matches, or equal IRs hash differently so a swap goes unnoticed | A5 | L | M | Low | Canonical serialisation (sorted keys, normalised numbers/Decimals) is the only hashed form; round-trip property suite (E35-K01, E35-T01, E35-Q02; `test_canonical_hash_stable_under_key_order`) | Low | round-trip corpus gate |
| RE-T4 | C12 | Bundle edited to carry a hostile IR (extreme bounds, widened stop, `all_accounts`) | A3 | M | H | High | Import runs the same compile/validate and semantic validator as the API; no trust from bundle provenance; arming gates still apply (E35-T04, E35-S09; `test_import_rejects_invalid_ir_same_as_api`) | Low | `rule_import_rejected_total` |
| RE-T5 | C13 | An upcaster silently changes semantics (e.g. default of `only_tighten`) | A4 | M | H | High | Upcasting force-disarms the rule, records a new `ir_hash`; golden-snapshot test per upcaster pair; a no-op upcaster to silence a mismatch is a defect (E35-T05; `test_upcaster_golden_semantics`, `test_upcast_forces_disarm`) | Low | audit `rule.upcast` |
| RE-T6 | C14 | Stale or manipulated metric input drives a rule to act | A4 | M | H | High | E3 None-is-false and stale handling; `sys.stale_feed_block`; disconnect guard pauses rules; metric trust is owned by E25/E26 and consumed here (E35-S02; `test_stale_metric_is_false_with_skipped_reason`) | Low | `rule_skipped_total{reason}` |

### 4.3 Repudiation

| T | Comp | Threat | A | L | I | Risk | Control (ticket / test) | Residual | Detect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RE-R1 | C5, C9 | A rule fires (order sent) with no corresponding `rule_events` / audit row | A4 | M | H | High | Write-ahead: the firing record and audit row are persisted before the OMS call; if the write fails the action is not sent (fail closed) (E35-S03, E35-S06; `test_action_not_sent_when_firing_log_write_fails`) | Low | `rule_orders_without_event_total` (**E35-FR-06**) |
| RE-R2 | C9 | Log disagrees with what the engine did (planned vs executed, mode mislabelled) | A4 | M | M | Medium | `rule_events` records `mode`, `rule_version`, `ir_hash`, snapshot id and executed-action ids; one code path produces both (E35-S06; shared with exploratory charter 5 in E35-Q07) | Low | reconciliation metric |
| RE-R3 | C9 | `rule_events` edited or deleted to hide a firing | A5 | L | H | Medium | App role has no UPDATE/DELETE grant (C-5.7); retention drops whole partitions only, with an audit entry (E35-T02; `test_rule_events_role_has_no_update_delete`) | Low | audit-chain verification |
| RE-R4 | C3 | Arming, mode change or scope change not attributable | A5 | L | H | Medium | Audit on arm/disarm/mode/scope/`only_tighten=false`/`all_accounts` with before/after and `ir_hash` (E35-S01; `test_mode_change_writes_audit`) | Low | audit |
| RE-R5 | C12 | Import/export performed without a record | A4 | M | M | Medium | Audit `rule.import` / `rule.export` with actor, bundle hash, rule count (E35-S09, **E35-FR-03**) | Low | audit |

### 4.4 Information disclosure

| T | Comp | Threat | A | L | I | Risk | Control (ticket / test) | Residual | Detect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RE-I1 | C9 | `rule_runs.input_snapshot` holds account equity and PnL (financial/confidential) and is returned to a user without that account grant | A1 | M | H | High | Runs/events endpoints filter snapshot fields by the caller current account grants; snapshot never in list views (E35-S06, **E35-FR-07**; `test_runs_snapshot_redacted_without_account_grant`) | Low | none |
| RE-I2 | C9 | WS `rules` options (`rule_ids`, `include_events`) intersect incorrectly with grants and leak events for accounts the user lost | A1 | M | H | High | Filter is the intersection of requested ids, ownership and current grants, re-evaluated on grant change (E35-S06; `test_ws_rules_revoked_grant_stops_events`) | Low | WS ACL metric |
| RE-I3 | C2 | Vocabulary per-user availability annotations reveal which accounts, permissions or metrics exist for others | A1 | L | L | Low | Annotations computed from the caller own grants only; no account names (E35-T03; `test_vocabulary_annotations_scoped_to_caller`) | Low | none |
| RE-I4 | C12 | Export bundle carries account ids, equity-derived snapshots, run history or armed state | A4 | M | M | Medium | Export contains the IR only; account scopes exported as symbolic placeholders, never real ids; no `rule_runs` (E35-S09, **E35-FR-08**; `test_export_bundle_contains_no_account_ids_or_runs`) | Low | audit |
| RE-I5 | C2, C3 | A 403 vs 404 reveals whether an account or rule exists | A1 | M | L | Low | Foreign and missing rule ids / ungranted accounts return an identical 404 shape (C-12.4; **E35-FR-09**; `test_foreign_and_missing_rule_indistinguishable`) | Low | none |
| RE-I6 | C4, C9 | A credential, key or token reaches a log line, firing record or export | A1 | L | H | Medium | The epic stores no secrets; rule params are typed and `extra="forbid"`; redaction filter on all loggers (C-12.6); `rules` may not import `secrets` (import-linter C-3.2; `test_rules_cannot_import_secrets`) | Low | log-scan CI |
| RE-I7 | C11 | Simulation output estimates reveal equity or size beyond the caller grants | A1 | L | M | Low | Simulation resolves targets through the same scope enforcer as live execution | Low | none |

### 4.5 Denial of service

| T | Comp | Threat | A | L | I | Risk | Control (ticket / test) | Residual | Detect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RE-D1 | C2, C4 | Pathological IR: huge node count, deep DAG, giant `n_of`, temporal windows that allocate unbounded history | A1, A3 | H | H | **Critical** | Hard bounds in validation (node count, depth, `n_of` size, window length, total window memory per rule and per user) rejected with typed errors; request body size cap (E35-T04, **E35-FR-10**; `test_validator_rejects_node_bound_exceeded`, `test_window_memory_budget_enforced`; benchmark E35-Q04) | Low | `rule_validation_rejected_total{code}` |
| RE-D2 | C3, C4 | Many rules per user exhaust evaluator CPU/memory | A1, A5 | M | H | High | Per-user and global armed-rule cap; per-rule evaluation time budget with timeout and auto-disable; evaluation off the order path (E35-S02, **E35-FR-11**; `test_per_user_rule_cap`; E35-Q04 load) | Low | `rule_eval_duration_seconds`, cap-hit counter |
| RE-D3 | C11 | Simulation / auto-backtest used as a compute sink | A1 | M | M | Medium | Queued, per-user concurrency limit and row/time budget, lower priority than live evaluation, worker pool (E35-S05; `test_simulation_concurrency_limit`) | Low | queue-depth metric |
| RE-D4 | C9 | Log write amplification: every evaluation including no-ops is logged (R4) | A1, A4 | H | M | High | Aggregated persistence of no-op evaluations with exact counters, full records for fires; batched writer with bounded queue (C-2.18); retention partitions (E35-T02, E35-S06, **E35-FR-12**; `test_noop_logging_bounded_under_flood`; E35-Q04) | Low | `rule_events_queue_depth` |
| RE-D5 | C7 | **Shared fate.** A slow or failing rule on `pre_trade_check` breaches the 300 ms submit budget and degrades all trading | A1, A4, A5 | M | H | **High** | `pre_trade_check` rules are compiled predicates over a prebuilt snapshot with a per-rule budget (default 5 ms) and an aggregate budget; a rule exceeding its budget N times is **ejected from the path** (never waited on) with an alert; `sys.*` vetoes are native code, not user rules (E35-S02, **E35-FR-13**; `test_slow_pre_trade_rule_is_ejected_not_waited_on`; chaos E35-Q05). Fail-open applies only to the user rule; OMS caps and native SL remain (C-2.6) | Low | `rule_pre_trade_eject_total`, hook p99 |
| RE-D6 | C5 | Self-inflicted rate-limit exhaustion: a rule fires at maximum rate and consumes the UID budget | A4, A5 | H | H | High | Per-rule `cooldown_ms` and fires-per-window caps, global rate cap (schemas 11.7); executor draws only from the normal bucket, never the stop/cancel reserve (C-12.7); breach auto-disables the rule (E35-S03; `test_rule_cannot_consume_rate_reserve`, `test_max_fire_rate_auto_disables`) | Low | `rule_rate_limited_total`; audit `rule.auto_disabled` |
| RE-D7 | C8 | **Signal amplification:** `emit_signal` to `on_signal` chains (or fan-out to many listeners) multiply per event | A4, A5 | M | H | High | Signal depth bound per causal chain (default 3), per-event emission cap, cycle detection at validation, bounded signal queue with drop-and-count (E35-S02, E35-T04, **E35-FR-14**; `test_signal_cycle_rejected_at_validate`, `test_signal_chain_depth_cap`) | Low | `rule_signal_dropped_total` |
| RE-D8 | C2 | Compile/validate endpoint flooded | A1, A2 | M | L | Low | Per-user rate limit, request size cap, CPU-bounded validator | Low | rate-limit metric |
| RE-D9 | C9 | WS `rules` topic flood to slow clients | A1 | L | L | Low | 250 ms coalesced cadence, bounded per-client queue (C-2.18) | Low | WS desync metric |

### 4.6 Elevation of privilege

| T | Comp | Threat | A | L | I | Risk | Control (ticket / test) | Residual | Detect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RE-E1 | C3, C6 | **Permission drift.** A rule armed while the user held a grant keeps acting after the grant is revoked | A4, A5 | H | H | **Critical** | Runtime enforcement per section 5: every action re-resolves the armer current grants and role at execution time; a revoked grant skips the action, logs `blocked_by=scope_revoked`, and auto-disarms after N hits (E35-S04; `test_revoked_grant_blocks_action_at_runtime`) | Low | `rule_scope_denied_total`; audit `rule.auto_disarmed` |
| RE-E2 | C5, C6 | Acting on accounts outside the user grants through explicit targets | A1, A5 | M | H | High | Targets resolved server-side against current grants; intersection, never union; ungranted ids rejected at save **and** at runtime (E35-S04; `test_action_on_ungranted_account_blocked`; IDOR case on every route) | Low | `rule_scope_denied_total` |
| RE-E3 | C5 | `targets: all_accounts` expands to accounts added later or beyond the armer grants | A5 | M | H | High | Means "all accounts the armer is granted at fire time"; needs an explicit permission plus confirmation; audited on use (E35-S04, **E35-FR-15**; `test_all_accounts_expands_to_current_grants_only`) | Low | audit `rule.all_accounts_used` |
| RE-E4 | C5 | `only_tighten=false` / `widen_stop` used without `rules.loosen_stop` and Owner | A1, A5 | M | H | High | Checked at save, at arming and again at execution; Owner-only; native SL invariant unaffected (C-2.6) (E35-S03, E35-S04; `test_widen_stop_requires_owner_at_runtime`) | Low | audit `rule.only_tighten_false_used` |
| RE-E5 | C3 | Arming preconditions bypassed: skip the simulate gate, arm via mode PATCH, or create/import a rule already `armed` | A5 | M | H | High | One arming code path enforces the new-rule gate, live gate and step-up; the override is Owner-only with an audited reason; DTOs reject `mode=armed` on create/import (E35-S01, E35-S05; `test_cannot_arm_without_simulation_gate`, `test_create_rejects_armed_mode`) | Low | audit |
| RE-E6 | C3, C5 | A Manager authors a rule that the Owner session effectively executes | A5 | M | H | High | A rule runs with the intersection of the armer grants and the author current grants; the version is bound to the approved `ir_hash`; arming shows a plain-language restatement (E35-S01, **E35-FR-16**; `test_rule_authority_is_intersection_of_author_and_armer`). Accessibility of the restatement: E35-D04, E35-Q06 | Low | audit `rule.armed` |
| RE-E7 | C3, C8 | A rule arms itself or another rule via `enable_rule` | A4, A5 | M | H | High | `enable_rule` may only move a rule toward simulate/disabled, never to `armed`, only within the same owner; self-targeting rejected at validate (E35-T04, E35-S02, **E35-FR-17**; `test_enable_rule_cannot_arm`, `test_enable_rule_self_target_rejected`) | Low | audit |
| RE-E8 | C13 | Disabling a non-disableable system rule (`sys.native_sl_watchdog`, `sys.clock_drift_block`) | A1, A5 | L | H | Medium | Server rejects disable of those ids regardless of role (E35-T05; `test_cannot_disable_non_disableable_system_rule`) | Low | audit |
| RE-E9 | C4 | Escape from the IR sandbox: eval of an expression string, user Python, template injection | A3 | L | H | Medium | R1: IR is data, no string parser/evaluator exists; `eval`/`exec`/`compile`/`ast` forbidden in the rules package by Semgrep (E35-X02; `test_no_dynamic_code_in_rules_package`) | Low | SAST |
| RE-E10 | C3, C4 | **Budget raise.** A Manager raises a rule's evaluation budget (IR `limits.max_fires_per_hour` / `max_fires_per_day`, SR-104) above its default, or anyone above the hard cap, so the rule fires more often than SR-104 allows | A5 | M | M | Medium | Synchronous check (C-2.21) at save, at activation and again at arming, the re-arm after a kill included: above a default needs the Owner role, at arming the arming actor's, whoever saved the version (403 `forbidden`, audited first); above a hard cap is refused for every role (422). A rule armed above a cap before the caps existed is skipped by the evaluator and disarmed with an audited reason, never clamped (#3232; `test_rule_limits_between_default_and_cap_need_the_owner`, `test_arm_manager_above_default_version_is_403_audited_and_chart_untouched`, `test_evaluable_rules_skips_and_disarms_an_armed_rule_above_the_cap`) | Low, one accepted residual (section 9) | audit `rules.scope_denied`, `rules.arm` denied, `rules.disarm` with reason `limits_above_cap` |

## 5. What "runtime enforcement" must cover (E35-S04 sufficiency criteria)

Time-of-authoring vs time-of-execution drift is the central case (RE-E1). Runtime enforcement is sufficient only if **all** hold:

1. Evaluated on **every action**, at execution time, not at trigger time, and not cached beyond one evaluation cycle (revocation latency bound: next evaluation, at most 1 s).
2. Resolves the **armer** (and, for RE-E6, the author) by id and reads their grants/role fresh from the RBAC store; a deleted or disabled user means every action is denied.
3. Covers every action type including `cancel_*`, `flatten_*`, `modify_*`, `halt_new_orders`, and covers every expanded target (`all_accounts`, symbol lists).
4. Covers environment: a rule whose `scope.environments` includes `live` re-checks the live gate each time (C-2.11).
5. A denial is **recorded** (`blocked_by`, `blocked_detail`) and counted; repeated denials auto-disarm the rule with an audit entry.
6. Fails closed: if grants cannot be read, the action is not executed. Exception recorded deliberately: protective reduce-only actions already authorised by the OMS stay with the OMS; they never widen exposure.
7. Applies identically in `simulate`, so simulation never reports an action as feasible that live would deny.

## 6. Data-flow gaps this model deliberately includes

The architecture text omits these; each is modelled above: `pre_trade_check` sync path (RE-D5), `emit_signal` bus (RE-S3, RE-D7, RE-E7), import/export (RE-S4, RE-T4, RE-I4), WS fan-out (RE-S5, RE-I2, RE-D9), firing-log writer (RE-R1, RE-D4), upcasters (RE-T5), simulation (RE-D3, RE-I7).

## 7. Abuse-case catalogue (executable by E35-X02, E35-Q07, E35-Q05)

| Id | Threat | Attack narrative | Expected system response |
| --- | --- | --- | --- |
| AC-01 | RE-E1 | Owner arms a Manager rule on account A, then revokes the grant; trigger fires | Action blocked `scope_revoked`; no order; denial logged; rule auto-disarms after N hits |
| AC-02 | RE-S3 | User X rule emits a signal that user Y rule listens for | Signal not delivered; cross-owner counter increments |
| AC-03 | RE-D7 | Rule A emits to B, B emits to A | Rejected at validate (cycle); if depth > cap at runtime, chain cut and counted |
| AC-04 | RE-D6 | Rule with `cooldown_ms=0` triggered on every tick | Rate cap holds, stop/cancel reserve untouched, rule auto-disabled |
| AC-05 | RE-E7 | Rule's action `enable_rule` targets itself or an armed-mode toggle | Rejected at validate; runtime cannot set `armed` |
| AC-06 | RE-D1 | Post an IR with 100k nodes / maximal `n_of` / giant window | 422 with typed code; no allocation spike |
| AC-07 | RE-D5 | Armed `pre_trade_check` rule engineered to be slow | Ejected after N breaches; submit p99 stays within budget; alert |
| AC-08 | RE-T2 | Put a `threshold: 1` in `graph_layout` hoping the evaluator reads it | Evaluator output identical with and without the field |
| AC-09 | RE-T1 | Edit stored `ir` of an armed version directly in the DB | Loader detects hash mismatch, refuses, auto-disables, alerts |
| AC-10 | RE-S4 | Import bundle with `mode: armed`, foreign `owner_id` | Created as draft owned by importer; fields ignored |
| AC-11 | RE-E4 | Manager creates `only_tighten=false` | 403 at save; runtime check also denies |
| AC-12 | RE-E3 | Armer granted accounts A,B arms `all_accounts`, later grant for B removed, account C added by Owner | Fires only on A |
| AC-13 | RE-I1 | Viewer without account grant calls `/rules/runs/{id}/events` | 404 identical to missing; no snapshot values |
| AC-14 | RE-R1 | Break the firing-log write during a fire | No order sent; error surfaced |
| AC-15 | RE-D4 | Flood a no-op trigger at 10 kHz | Counters exact, persisted rows bounded, queue bounded |
| AC-16 | RE-E5 | POST a new rule with `mode=armed` / PATCH mode straight to armed | 422 / gate refusal |

## 8. Findings raised as work

Every threat with no shipped control is filed against its owning ticket. Severity is the unmitigated rating; all are expected to reach Low residual when the owner ticket ships.

| Finding | Threats | Severity | Owning task | Disposition |
| --- | --- | --- | --- | --- |
| E35-FR-01 | RE-S1 | High | E35-S03 | Deferred: comment on E35-S03 (executor never reads session) |
| E35-FR-02 | RE-S3 | High | E35-S02 | Deferred: comment on E35-S02 (owner-namespaced signals) |
| E35-FR-03 | RE-S4, RE-R5 | Medium | E35-S09 | Deferred: comment on E35-S09 (import resets identity/mode, audited) |
| E35-FR-04 | RE-T1 | Medium | E35-S02 | Deferred: comment on E35-S02 (hash re-check at load) |
| E35-FR-05 | RE-T2 | High | E35-T01 | Deferred: comment on E35-T01 (layout fields opaque, import-linter contract) |
| E35-FR-06 | RE-R1 | High | E35-S06 | Deferred: comment on E35-S06 (reconciliation metric) |
| E35-FR-07, -09 | RE-I1, RE-I5 | High | E35-S06, E35-S01 | Deferred |
| E35-FR-08 | RE-I4 | Medium | E35-S09 | Deferred |
| E35-FR-10 | RE-D1 | Critical | E35-T04 | Deferred: window-memory budget; **blocks R3 gate until shipped** |
| E35-FR-11, -12 | RE-D2, RE-D4 | High | E35-S02, E35-S06 | Deferred |
| E35-FR-13 | RE-D5 | High | E35-S02 | Deferred; **blocks R3 gate until shipped** |
| E35-FR-14 | RE-D7 | High | E35-S02, E35-T04 | Deferred |
| E35-FR-15, -16 | RE-E3, RE-E6 | High | E35-S04, E35-S01 | Deferred |
| E35-FR-17 | RE-E7 | High | E35-T04, E35-S02 | Deferred |

Filing note: GitHub issues for these findings are created by the orchestrator at merge (agent-delivery adaptation); until then this table is the register. Threats with a control but no detection: RE-I3, RE-I5, RE-I7, RE-T2 (test-only; accepted, section 9).

Tests with no owner test yet (output of this ticket per its test plan): `test_signal_never_crosses_owner_boundary`, `test_evaluator_ignores_layout_fields`, `test_slow_pre_trade_rule_is_ejected_not_waited_on`, `test_window_memory_budget_enforced`, `test_all_accounts_expands_to_current_grants_only`, `test_enable_rule_cannot_arm`. Abuse cases AC-01..AC-16 are handed to E35-X02 (suite), E35-Q05 (chaos: AC-07, AC-14, AC-15), E35-Q07 (charters 1, 5, 6) and E35-Q04 (benchmarks for RE-D1, RE-D2, RE-D4, RE-D5).

## 9. Data classification, observability and residual risk

| Store | Class | Note |
| --- | --- | --- |
| Rule IR (`rule_versions.ir`) | internal | integrity-critical; hash-bound at arming |
| `graph_layout` / `form_model` | internal, non-semantic | never consumed by the engine |
| `rule_runs.input_snapshot` | financial / confidential | grant-filtered on read |
| `rule_events`, audit | evidentiary, append-only | no UPDATE/DELETE grant |
| Secrets / PII | none stored | confirmed (RE-I6): no path logs or exports a credential |

Security-relevant events that must be observable: arming (high severity), live-environment scope change, `only_tighten=false` use, `targets: all_accounts` use, import/export, quarantine on schema violation, auto-disable / auto-disarm, pre_trade eject, cross-owner signal rejection. Each is named in the Detect column above; any not implemented is part of its owning finding.

Residual risk: all rows Low after controls and findings land. **Until E35-FR-10 and E35-FR-13 ship, RE-D1 (Critical) and RE-D5/RE-E1 (High) stay open and block the R3 security gate** (`30-release-roadmap.md` section 7.4) unless the Owner accepts them in writing. RE-E1 is mitigated by E35-S04 once shipped; the sufficiency criteria are in section 5. Accepting owner: Owner (repository owner).

RE-E10 keeps one accepted residual (#3232, decision 9): a rule that a Manager armed above a default but under its hard cap before the caps existed keeps running until it is re-armed, when the Owner check applies. Managers reach only demo and testnet scopes, and no rule action runs until the action executor (E35-S03, #863) lands. The coordinator accepted it in the rulings on #3232; the cap values are interim until the Owner ratifies them (#2701).

## 10. Boundary notes

Editor-side threats (XSS in node labels, form injection) belong to E36/E37 and stop at TB-R1: the API treats all editor output as untrusted. Security controls that rely on a user reading a warning (the arming restatement) must be accessible (E35-D04, E35-Q06).

## 11. Sign-off

Per the Agent-delivery adaptation, Security engineer / Architect / rule-engine backend lead sign-off is replaced by owner approval. Pending: owner approval on this PR.
