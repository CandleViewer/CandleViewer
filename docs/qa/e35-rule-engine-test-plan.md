# E35 Rule engine — black-box test plan and exploratory charters

Ticket: E35-Q01 (#941). Status: v1.0 (draft for QA/SDET + rule-engine backend lead review).

## 0. Conventions

- **Expectations are derived from the specification, not the implementation.** Each step cites its source:
  `S24 §n` = `docs/plan/24-internal-schemas.md`; `ADR-0007` = `docs/plan/27-adrs/ADR-0007-rule-ir.md`;
  `US-RULE-nnn` = `docs/plan/11-user-stories.md` §20; `API` = `docs/plan/22-api-openapi.yaml`;
  `WS` = `docs/plan/23-ws-protocol.md` §15.6; `DB` = `docs/plan/21-database-schema.md` §3.4.
- **Environment: staging / demo only.** Never run against live (`02-definition-of-ready-done.md` §8).
  No real API keys appear in any fixture or step; accounts are seeded demo accounts (section 6).
- **Ambiguities** are recorded in section 9 as questions against the implementing ticket, not guessed.
- Scenario IDs: `BB-<story>-<nn>`; boundary cases `BD-nn`; negative-requirement cases `NG-nn`;
  charters `CH-n`; regression pack members are tagged **[R]**.
- Every step list is: Preconditions -> Steps -> Expected. A tester who did not write the plan must be able
  to reach the precondition state using only section 6 and judge pass/fail without asking.
- Audit check (applies to every audited action): after the step, query the audit view (SCR audit log, or
  `GET /rules/{ruleId}/runs` + audit table) and confirm exactly one audit row for the action with actor,
  role, account, before/after and traceId. An audited action with no row is a defect.
- Keyboard smoke (a11y, per screen): complete the screen's primary action using keyboard only; full audit
  is E35-Q06 and is not duplicated here.

## 1. Seeded actors and data (summary; full plan in section 6)

| Handle | Meaning |
|---|---|
| OWNER | Owner role, TOTP enrolled, `rules:arm_live` |
| MGR-A | Manager granted ACC-1, ACC-2; no `rules:arm_live` |
| MGR-B | Manager granted ACC-3 only |
| ACC-1..ACC-3 | demo accounts; ACC-4 demo account granted to nobody but OWNER |
| SYM-REC | BTCUSDT, recorded window REC-W1 present |
| SYM-NOREC | a listed symbol with no recording (ETHUSDT in seed) |

## 2. Scenarios by user story

### US-RULE-001 Rule IR and single engine

**BB-001-01 Round trip [R]** (US-RULE-001 "Round trip", ADR-0007 rule 1)
- Pre: RULE-FORM-1 created in form editor and saved (v1).
- Steps: open in node editor, change nothing, save.
- Expected: no new version is created (or stored IR is byte-identical); `GET /rules/{id}/versions` hash for
  v1 unchanged (S24 §11.4 guarantee 1).

**BB-001-02 Node-only construct** (US-RULE-001 "Node-only construct")
- Pre: RULE-GRAPH-NESTED (nested arithmetic + `n_of`) saved from node editor.
- Steps: open in form editor.
- Expected: read-only view with banner "this rule uses graph-only features ..." (S24 §11.4 guarantee 2);
  nothing dropped; Save disabled for the node-only part.

**BB-001-03 Version migration** (US-RULE-001 "Version migration")
- Pre: RULE-OLDIR (stored under the previous IR version, seeded).
- Steps: open the rule.
- Expected: migrated on load; migration logged once; mode is disarmed; arm control requires review.

**BB-001-04 Canonical hash [R]** (US-RULE-001 "Canonical serialisation")
- Pre: RULE-FORM-1 and RULE-GRAPH-EQUIV (same semantics, authored in the node editor, different node ids,
  `1.50` vs `1.5`).
- Steps: `POST /rules/validate` for both; compare reported canonical hash; move a node and add a comment
  note in the graph; re-save.
- Expected: hashes equal; layout/comment edits create no new version (S24 §11.4 guarantee 3).

**BB-001-05 Presentation survives** — Pre: graph with hand-placed nodes + notes. Steps: open in form,
change a threshold, save, return to node editor. Expected: original layout and notes intact.

**BB-001-06 Schema violation on load** — Pre: RULE-CORRUPT (seeded row with truncated IR). Steps: open it.
Expected: quarantined read-only, force-disarmed, failing JSON path named, "export as JSON" offered, no
evaluation ever recorded for it (`rule_runs` empty).

**BB-001-07 Fuzz invariant** — Automated (E35-Q02). Manual spot check: take three vocabulary-heavy rules,
hop form->node->form; hash unchanged each hop.

### US-RULE-002 Metric vocabulary

**BB-002-01 Catalogue [R]** — Steps: `GET /rules/vocabulary`; open the metric picker. Expected: every
metric listed in US-RULE-002 present with unit and description; picker matches the API (S24 §11.6).
**BB-002-02 Unavailable metric** — Pre: SYM-NOREC. Steps: pick a recording-dependent metric (e.g. CVD).
Expected: disabled, names the missing dependency, one-click "start recording".
**BB-002-03 Estimated badge** — Steps: pick a heuristic metric (iceberg flag). Expected: "(estimated)" in
the picker and in the rule summary.
**BB-002-04 Stable identity** — Steps: compare metric ids from the vocabulary against the seeded
vocabulary snapshot. Expected: no id changed or removed.

### US-RULE-003 Action vocabulary

**BB-003-01 Catalogue [R]** - Steps: open action picker; compare with `GET /rules/vocabulary` and S24 §11.6
action table. Expected: all actions of US-RULE-003 present; each declares account/position scope shown in
the rule summary.
**BB-003-02 Forbidden action** - Pre: sign in as MGR-A. Steps: add `place_order`. Expected: available only
in simulate mode; restriction explained; setting mode to armed via `PUT /rules/{id}/mode` returns 403 (E12).
**BB-003-03 Loosen stop** - Steps: `modify_stop_loss` with `only_tighten=false` as MGR-A. Expected: refused
(needs `rules.loosen_stop`, S24 §11.6); OWNER allowed.
**BB-003-04 Self-targeting** - Steps: `enable_rule` / `pause_rule` pointing at the rule itself. Expected:
`enable_rule` self-target rejected with a validation issue; `pause_rule` self-target allowed (S24 §11.6).

### US-RULE-004 Form editor

**BB-004-01 Build [R]** - Steps: add "R-multiple >= 1" + "move SL to breakeven". Expected: validates;
plain-language summary shown.
**BB-004-02 Grouping** - Steps: build `A AND (B OR C)`. Expected: grouping explicit; IR is `all_of[A, any_of[B,C]]`.
**BB-004-03 Invalid rule** - Pre: metric without data source on SYM-NOREC. Steps: save. Expected: blocked
with a specific, actionable error naming the metric.
**BB-004-04 Keyboard** - complete BB-004-01 keyboard-only; the summary is the accessible description.

### US-RULE-005 Node editor

**BB-005-01 Build by graph** - drag metric/comparison/logic/action nodes; errors shown on the offending node.
**BB-005-02 Type mismatch** - connect boolean output to numeric input. Expected: refused, inline reason.
**BB-005-03 Auto-layout** - Expected: semantics unchanged (hash equal), undoable.
**BB-005-04 Cycle** - connect output to own upstream input. Expected: refused, cycle path highlighted; a
crafted `POST /rules/validate` with a cyclic IR returns a blocking issue (never accepted).
**BB-005-05 Orphans** - Expected: canvas warnings; save blocked; jump-to-node error list.
**BB-005-06 Keyboard construction** - palette, Enter on port, arrows, Enter. Expected: live region
"connected X output to AND input 1"; undo/redo shared with pointer edits.
**BB-005-07 Node-only badge** - fan one node output to two consumers. Expected: badge, header text, flag in IR.

### US-RULE-006 Round-trip switching

**BB-006-01 Switch [R]**, **BB-006-02 Unsaved prompt**, **BB-006-03 Read-only fallback** - as the stories.
**BB-006-04 Hash proof** - Pre: staging fault-injection toggle forcing a differing hash (gap if absent, see Q5).
Expected: switch aborted, rule untouched, error with both hashes and downloadable diff, high-severity telemetry.
**BB-006-05 Concurrent tabs [R]** - Pre: same rule open in two tabs. Steps: save tab 1, then save tab 2.
Expected: tab 2 gets an optimistic-concurrency error naming editor/session and offering reload-and-reapply;
no last-writer-wins (`rule_versions` has exactly one new row).
**BB-006-06 Switch while armed** - Expected: viewing allowed; first edit requires disarm or "edit as new draft
version"; running version immutable (`GET /rules/{id}/active-version` unchanged).
**BB-006-07 Unrepresentable after edit** - Expected: sub-tree read-only with description; saving from the form
preserves the node-only sub-tree byte-for-byte.
**BB-006-08 Migration during switch** - Pre: RULE-OLDIR. Expected: comparison against post-migration hash;
migration recorded once as its own version; rule stays disarmed.

### US-RULE-007 Scoping

**BB-007-01 Scope selection** - accounts or trade group, symbols or all, new/existing/both positions.
**BB-007-02 Out-of-permission [R]** - as MGR-B: ACC-1 not listed anywhere (picker, search, summary); a
crafted `POST /rules` scoping ACC-1 returns 403 (US-RULE-007). Audit row for the denied attempt.
**BB-007-03 Scope chip** - header shows e.g. "2 accounts · BTCUSDT · new positions".
**BB-007-04 Runtime scope** - grant revoked mid-life (BD-08): next firing suppressed with reason `scope`,
logged; no action for the revoked account.

### US-RULE-008 Simulate-only

**BB-008-01 Simulate [R]** - arm simulate on SYM-REC; trigger. Expected: firing recorded with would-be
action and inputs (S24 §11.9 `SimulatedAction`); zero exchange calls (mock-exchange/egress log empty, NG-05).
**BB-008-02 Visual distinction** - simulated markers/logs visibly distinct from real, with a text label
(not colour alone).
**BB-008-03 Promotion [R]** - promote to live: step-up auth required; high-severity audit row (E12).
**BB-008-04 New-rule gate [R]** - new/edited rule: `armed` not selectable until `min_simulation_fires` (5)
or `min_simulation_hours` (24); OWNER override requires a reason and is audited (S24 §11.7).

### US-RULE-009 Auto-backtest

**BB-009-01 Runs on save** - fire count, timestamps, estimated R impact.
**BB-009-02 Insufficient history** - recording shorter than lookback; true covered range stated.
**BB-009-03 Long backtest** - over 30 s: background with progress and completion notification.
**BB-009-04 Budget** - simulation completes within 60 s on REC-W1 (observed; instrumented in E35-Q04).

### US-RULE-010 Runtime and firing log

**BB-010-01 Firing logged [R]** - timestamp, rule id+version, metric snapshot, action, order ids, outcome.
**BB-010-02 Suppressed** - cooldown, scope, risk cap, permission each logged with a reason.
**BB-010-03 Filter/export** - by rule/account/outcome; keyboard navigable; export contains no account
ids (NG-06, see Q4).
**BB-010-04 Snapshot sufficiency** - replay the logged snapshot via `POST /rules/{id}/simulate`: same
decision (E2, E5).

### US-RULE-011 Conflict and precedence

**BB-011-01 Conflict at arming [R]** - two armed rules modify the same stop; explicit priority required.
**BB-011-02 Runtime arbitration** - both fire same tick: higher applied, other logged `superseded`.
**BB-011-03 Safety override** - `sys.daily_loss_lockout` / kill switch beats a discretionary rule regardless
of configured priority.
**BB-011-04 Conflict kinds matrix** - see BD-09.

## 3. Boundary and adversarial cases

| ID | Case | Expected (source) |
|---|---|---|
| BD-01 | 32 boolean children / 33 | 32 accepted; 33 rejected with issue naming path (S24 §11.3) |
| BD-02 | 8 arithmetic operands / 9 | same |
| BD-03 | 10 actions / 11 | same |
| BD-04 | `window_ms` = 100, 99, 86 400 000, 86 400 001 | bounds inclusive; outside rejected |
| BD-05 | `eval_interval_ms` = 50, 49, 3 600 000, 3 600 001 | same |
| BD-06 | metric still in warmup | condition false, `skipped_reason=warmup`; never 0 (E3) |
| BD-07 | SYM-NOREC recording-dependent metric | unavailable; false; reason logged |
| BD-08 | account grant revoked mid-life | next evaluation suppressed and logged (US-RULE-007 NFR) |
| BD-09 | two rules in each conflict kind: same stop, same TP, same size, flatten vs scale_in, place vs halt, opposing sides | deterministic arbitration, both logged (US-RULE-011) |
| BD-10 | `crosses_above` first eval after warmup/restart | false (S24 §11.6) |
| BD-11 | IR with unknown field / wrong type / duplicate node id | rejected with JSON path |
| BD-12 | `max_fires_per_hour` exceeded; `once_per=position` | skip reason `rate_limit` / `once` |

## 4. Negative requirements (frequently under-covered)

| ID | Requirement | Check |
|---|---|---|
| NG-01 | `None` never coerces to 0 (E3) | `metric < 5` with unavailable metric does not fire; log shows skipped, not 0 |
| NG-02 | Short-circuit still logs unevaluated children (E4) | `condition_trace` lists non-evaluated nodes |
| NG-03 | Reconnect does not replay missed triggers (E10) | drop private WS 3 times; one re-evaluation only; missed-trigger metric increments |
| NG-04 | Stale data skipped (E7) | freeze feed > 5 s: `skipped_reason=stale_data` |
| NG-05 | Simulation makes zero exchange calls | mock exchange / egress log empty |
| NG-06 | Export contains no account ids | search exported JSON for ACC ids: none |
| NG-07 | Imports land disarmed | import JSON exported from an armed rule: lands disarmed |
| NG-08 | Armed rules pause while private WS is down (S24 §11.7) | UI "rules paused - feed degraded"; no actions |
| NG-09 | No rule acts on another rule's algo children (E11) | children untouched |
| NG-10 | Live is never the default (E12) | new rule has `scope.environments == ["demo"]` |

## 5. Exploratory charters (session-based, 90 minutes each)

Each charter: mission, area, time box, evidence to capture, debrief template (tested / found / obstacles /
next). Staging (demo) only. CH-1 and CH-6 are abuse-case charters coordinated with **E35-X02**: X02 owns the
STRIDE-driven attack list; these charters probe by exploration, and findings from either feed the same
STRIDE model. Reviewed by the security engineer before execution.

| | Mission | Area | Evidence to capture |
|---|---|---|---|
| CH-1 | Try to make an armed rule act on an account you were never granted | scope, RBAC, REST `/rules`, `/mode`, WS `rules`, trade-group expansion, import | request/response pairs, rule JSON, audit rows, exchange-mock log of any order for the ungranted account |
| CH-2 | Try to make the form and graph representations of one rule disagree | editors, canonicalisation, presentation block, migrations | both canonical hashes, IR diffs, screenshots of each view |
| CH-3 | Try to make a simulation result misleading enough that you would arm a rule you should not | simulate, backtest, estimated metrics, coverage ranges | simulation report vs. recording, covered-range statement, any missing "(estimated)" or gap warning |
| CH-4 | Try to make the engine act on stale or missing data | E3, E7, E10, warmup, feed drop, clock drift | `skipped_reason` values, feed timestamps, any action taken on stale input |
| CH-5 | Try to lose a firing from the log, or make the log say something the engine did not do | `rule_events`, `rule_runs`, WS `include_events`, crash/restart, concurrent firings | event counts vs exchange-mock calls, sequence gaps, audit-vs-log reconciliation |
| CH-6 | Try to arm a rule without meeting the arming preconditions, by any path including crafted API calls | new-rule gate, live gate (E12), step-up auth, import, restore old version, direct `PUT /mode` | crafted requests, responses, resulting `mode`, audit rows |

Per charter, session notes use this template:

```
Charter: CH-n   Tester:   Date:   Build:   Start/End:
Setup (fixtures used):
Tested:
Found (bug ids / questions):
Obstacles:
Next:
Evidence links:
```

Seed ideas (non-exhaustive, so the charter is a mission and not an open poke): CH-1: clone a rule across
accounts; trade-group scope containing an ungranted account; revoke grant while armed; rule IDs from
another manager; WS subscribe with foreign `rule_ids`. CH-2: float formats, key order, duplicate-looking
nodes, comment-only edits, concurrent tabs. CH-3: window with a data gap, estimated metrics, symbol with
partial recording. CH-4: pause the feed 4.9 s vs 5.1 s, cross a restart, first `crosses_above`. CH-5: kill
the API mid-fire, two rules firing in one tick, failed action with `abort_remaining`. CH-6: edit after
simulate, version restore, import of armed export, missing `rules:arm_live`, expired step-up token.

## 6. Test-data seeding plan

All seeds are demo-only, created by the staging seed script (to be provided by the implementing tickets;
gaps in section 9). No real API keys anywhere.

| Seed | Content | Reaches |
|---|---|---|
| Accounts | ACC-1, ACC-2, ACC-3, ACC-4 (demo, fake keys) | scoping, IDOR |
| Users | OWNER, MGR-A (ACC-1, ACC-2), MGR-B (ACC-3) | RBAC, forbidden actions |
| Recordings | REC-W1 (BTCUSDT, 2 h, complete), REC-W2 (BTCUSDT, 20 min), REC-GAP (window with a 30 s gap); ETHUSDT none | backtest, insufficient history, unavailable metric |
| Rules | RULE-FORM-1, RULE-GRAPH-NESTED, RULE-GRAPH-EQUIV, RULE-OLDIR (previous IR version), RULE-CORRUPT (truncated IR), RULE-ARMED-1 (armed demo), RULE-CONFLICT-A/B (same stop) | corresponding scenarios |
| Positions | one open BTCUSDT long on ACC-1 with native SL | actions, conflicts |
| Fault toggles | feed pause, private-WS drop, hash-mismatch injector, clock skew | NG-03/04/08, BB-006-04 |

Any designed state not reachable with these seeds is raised as a gap on the implementing ticket **before**
the execution window (E35-Q07), per the acceptance criteria.

## 7. Regression pack (manual, target < 2 h; run before every R3 release candidate)

Members tagged **[R]** above: BB-001-01, 001-04, 002-01, 003-01, 004-01, 006-01, 006-05, 007-02, 008-01,
008-03, 008-04, 010-01, 011-01, plus NG-01, NG-03, NG-05, NG-07 and one keyboard-only traversal per screen
(SCR-080..SCR-089). Time budget: ~6 min per scenario x 19 + 15 min screen traversals = under 2 h.

## 8. Performance, observability and security observations

- Pass/fail observable budgets: simulation completes within 60 s; arming dialog confirms within 1 s
  (instrumented measurement is E35-Q04).
- Audit verification: every audited action (create, edit, arm, promote, disarm, import, delete, scope
  change, override) yields one audit row; absence is a defect.
- Out of scope: automated suites (E35-Q02..Q05), execution (E35-Q07), a11y audit (E35-Q06), editor test
  plans (E36/E37).

## 9. Questions raised against implementing tickets (specification ambiguities)

| # | Question | Raised against |
|---|---|---|
| Q1 | Exact numeric bounds for BD-01..BD-05 are quoted from the ticket; confirm they match the JSON Schema in S24 §11.3 | E35-T04 |
| Q2 | Is an IR cycle reported as a schema or a semantic issue code? Needed for BB-005-04 expected result | E35-T04 |
| Q3 | Out-of-permission rule/account reads: 403 or 404? Story says 403 for scope; not stated for read of foreign rule ids | RBAC/API owner |
| Q4 | Which exports are "no account ids" (rule export only, or firing-log export too)? | E35 API owner |
| Q5 | Is there a staging hash-mismatch fault injector for BB-006-04? | E36/E37 |
| Q6 | Staging seed script for section 6 fixtures: owning ticket? | E35-Q03 / infra |

## 10. Traceability

| Story | Plan scenarios | Automated coverage |
|---|---|---|
| US-RULE-001 | BB-001-01..07 | E35-Q02 (property/round-trip); `services/api/tests/rules/test_compiler_validator.py` partial |
| US-RULE-002 | BB-002-01..04 | `tests/rules/test_vocabulary.py` |
| US-RULE-003 | BB-003-01..04 | `tests/rules/test_validator_endpoints.py` (partial), E35-Q03 |
| US-RULE-006 | BB-006-01..08 | E35-Q02, E35-Q03 (E2E) |
| US-RULE-007 | BB-007-01..04, BD-08, CH-1 | E35-Q03 |
| US-RULE-008 | BB-008-01..04, NG-05, CH-6 | `tests/rules/test_evaluator*.py` (partial), E35-Q03 |
| US-RULE-009 | BB-009-01..04 | E35-Q04 |
| US-RULE-010 | BB-010-01..04, NG-02..04, CH-5 | `tests/rules/test_evaluator*.py` (partial), E35-Q05 |
| US-RULE-011 | BB-011-01..04, BD-09 | E35-Q03 |
| Boundaries | BD-01..12 | `tests/rules/test_compiler_validator.py` (partial) |
| Negatives | NG-01..10 | evaluator tests (NG-01, 02, 04 partial), E35-Q05 (NG-03, 08) |

Every Gherkin scenario of US-RULE-001/002/003/006/007/008/010/011 maps to at least one step above.
US-RULE-004, 005 and 009 are covered by BB-004/005/009 (editor-owned plans in E36/E37 remain separate).
