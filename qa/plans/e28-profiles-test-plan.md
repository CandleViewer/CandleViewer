# E28 per-account profiles, sizing and trade groups — black-box test plan

Ticket: E28-Q01 (issue #904), slice B: this plan and its exploratory charters
(`qa/plans/e28-exploratory-charters.md`). Slice A is the fixture set and the golden sizing vectors
under `tests/fixtures/e28/` (its own commit); every precondition below names its handles. Owner:
QA. Status: **Authored — peer review, Owner and Architect agreement, and the dry run pending
(§14, §15).**

Path: the ticket names `qa/plans/e28/test-plan.md`. This file follows the repository's flat
convention instead (`qa/plans/e27-accounts-test-plan.md`, `qa/plans/e09-auth-rbac-test-plan.md`),
as E27 recorded on #833. The deviation is recorded on #904, in
[its record comment](https://github.com/CandleViewer/CandleViewer/issues/904#issuecomment-6391566939)
("Path"), which also numbers the orchestrator's rulings 1 to 12 that §13 cites.

Written against the observable surface only:

- **Stories:** `US-PROF-001..008`, 25 Gherkin scenarios with their NFRs
  (`docs/plan/11-user-stories.md` §3), and the Gherkin of E28-S01 to E28-S05 where a case cites it
  (`docs/plan/backlog/E28.json`).
- **Screens:** `SCR-061`, `SCR-062`, `SCR-130`, `SCR-131`, `SCR-132`, `SCR-133`, with `SCR-060`,
  `SCR-071` and `SCR-114` as observation points (`docs/plan/14-screens-catalogue.md`; story map
  `docs/plan/18-traceability-matrix.md` §2.3).
- **Components** (`docs/plan/15-component-catalogue.md`): `CMP-001`, `CMP-005`, `CMP-011`,
  `CMP-040`, `CMP-041`, `CMP-044`, `CMP-049`, `CMP-050`, `CMP-055`, `CMP-065`, `CMP-075`, `CMP-087`,
  `CMP-093`, `CMP-100`, `CMP-101`, `CMP-102`, `CMP-104`, `CMP-105`, `CMP-106`, `CMP-107`, `CMP-119`,
  `CMP-121`, `CMP-123`, `CMP-124`, `CMP-138`, `CMP-158`, `CMP-229`, `CMP-231`, `CMP-232`.
- **REST** (`docs/plan/22-api-openapi.yaml`): `/exchange-accounts/{accountId}/profiles`,
  `/exchange-accounts/{accountId}/profiles/{profileId}`,
  `/exchange-accounts/{accountId}/default-profile`, `/trade-group-definitions`,
  `/trade-group-definitions/{definitionId}`, `/trade-groups`, `/trade-groups/preview`,
  `/trade-groups/{tradeGroupId}`, `/trade-groups/{tradeGroupId}/amend`,
  `/trade-groups/{tradeGroupId}/cancel`, `/orders`. In the case tables `.../profiles` is short for
  `/exchange-accounts/{accountId}/profiles`. Observation and setup routes: `/admin/audit`,
  `/risk/summary`, `/risk/lockouts/{accountId}/override`, `/positions`, `/notifications`,
  `/exchange-accounts/{accountId}/keys`, `/users/{userId}/account-access`, `/auth/step-up`.
- **WS** (`docs/plan/23-ws-protocol.md` §5.2, §6.2, §6.3, §15.5, §15.9): private topics
  `trade_groups` (100 ms throttle, `orders:read`, granted accounts); for CAP-03, `orders` and
  `rules`, each needing `exchange_account_ids` on `sub` (23:840), `alerts`, which takes no
  accounts (23:830), and `system`, auto-subscribed at `auth_ok` (23:836); and the error
  `account_scope_denied`.
- **Documented behaviour:** `docs/plan/21-database-schema.md` §3.2.4, §3.3.2, §3.3.3, §3.3.3a (the
  constraints the boundary catalogue probes); `docs/plan/24-internal-schemas.md` §9.1 to §9.3.3;
  ADR-0008 with its amendments 1 to 3; ADR-0040, proposed until its sign-off on #2701 (the
  override table and its comparator R); `docs/plan/04-security-program.md` (A-08, A-09; threats O3,
  F1, F2, F6, R2; SR-025, SR-052, SR-053, SR-054, SR-056, SR-064, SR-072); the E28 threat model
  `docs/security/threat-models/E28-profiles-trade-groups.md` (SR-E28 ids, PF rows, abuse cases
  AC-01 to AC-33, decisions D6 to D11); `docs/plan/06-performance-and-load-standard.md` §5.2;
  `docs/plan/05-accessibility-standard.md`; `docs/plan/03-testing-strategy.md` §11 and §16.

The plan was written without reading the implementation. No case names an internal function,
module path or private field, so it survives refactors of E28-T02 to E28-T05, E28-S01 to E28-S05
and the E34 fan-out it reaches into.

## 0. How to use this plan

- **Audience:** a QA engineer with a staging URL, the fixture set loaded (§12.1) and the seeded
  users (§12.2). No step needs backend source to decide pass or fail.
- **Fixtures, never a live exchange (C-13.5).** Two stacks run the cases. The **stub stack** serves
  exchange-side state from the E27 account pack through #2893's stub transport (wallet equity
  10000 USDT, fee rate and positions as the pack's `_base` and overlays say): golden-vector
  equality is asserted there. On the **Bybit demo stack** equity and prices are the demo account's,
  so QA recomputes each leg by hand from the equity, reference price, fee and instrument the
  response reports, with the rules R1 to R14 of slice A's `sizing_recomputation.md`.
- **Case id:** `TC-E28-<group>-<nn>`, stable for E28-Q02 to E28-Q05, E28-X03 and defect reports.
  Groups: `PRO` profile definition and sizing, `SYM` symbol restriction, `CAP` risk caps, `GRP`
  trade groups, `FAN` fan-out, `PRV` preview, `OVR` overrides, `AX` accessibility; the catalogues
  use `BND-nn` and `HOS-nnx`. Never renumber; retire a case by marking it withdrawn.
- **Columns:** Case · Covers (story id and scenario title, verbatim, or the E28 story's Gherkin) ·
  Preconditions · Steps · Expected result · Evidence · Audit · metric · By (the executing ticket:
  `Q02` automation, `Q03` performance and chaos, `Q04` accessibility and charters, `X03` abuse and
  RBAC; all E28) · Status. The accessibility cases (§11.3) leave out Audit · metric: they assert
  no telemetry.
- **Status:** every case is **mapped, not executed**, and BND-19 is also blocked on a live
  `instruments-info` recording (§13 C-04). Only E28-T01 (schema) and E28-X01 (threat model) are
  Done; E28-T02 (profile routes) is in progress; E28-T03, T04, T05 and S01 to S05 have not started,
  and the fan-out cases also wait on E34. §14 records each run.
- **Oracles.** API: the contract (C-6.1). UI copy and states: the SCR spec until E28-D02 is signed
  off ("per SCR-nnn; confirm against E28-D02"). Sizing: the golden vectors V01 to V14 and the hand
  recomputation, never the UI's or the API's own numbers. Where documents disagree, the case names
  the source it follows and §13 lists the conflict; a recorded answer is never a pass by default.
- **Evidence codes:** `HAR` network export or curl transcript · `SS` screenshot · `A11Y`
  accessibility-tree snapshot or screen-reader transcript · `AUD` `GET /admin/audit` extract · `MET`
  `GET /metrics` before and after (the Prometheus scrape, which 22 keeps out of its API surface,
  22:10439) · `WS` captured frames · `T` timing · `LOG` the stub request log (#2893) · `VEC` the
  case's figures beside the vector's and the hand recomputation.
- **Audit step:** query `GET /admin/audit?subject_type=<kind>&subject_id=<id>`, or by `action` and
  `actor_user_id` where the subject has no id (a refused create). Expect each listed event once per
  action that causes it, under a name in §11.1, with the acting user and no secret. **Every refusal
  from authorisation on (RBAC, scope, step-up, a cap, the allow-list, the native stop, the
  environment) writes an audit row** (#904 Observability, as narrowed by #904 record, ruling 9
  (2026-10-25); 11 global AC 1). A refusal of shape before authorisation (a schema `400` or `422`)
  is not an audited action under C-2.9, and the contract leaves the profile routes' rules of shape
  unaudited (`ProfileRejected`, 22:15411-15413): those cases expect no row and record one if found
  (§13 C-23). `POST /orders` reads its body after RBAC (24:1670), so a `400` of that read is
  audited as `orders.submit` with outcome `denied` (24:1673); only a body whose
  `exchange_account_id` cannot be read is refused before RBAC, unaudited (24:1661).
- **Step-up, idempotency, versions:** profile writes, the default binding and definition writes need
  a live step-up of class `risk_caps` (SR-025, SR-E28-02); the procedure is E27's (§9.4 of its
  plan). `POST /trade-groups`, `/amend`, `/cancel` and `POST /orders` send a fresh
  `Idempotency-Key`; the preview takes none. Profile `PUT`/`DELETE` and the binding's `PUT` send
  `If-Match`.
- **Clock:** the daily-loss and rollover cases use E28-Q02's clock-injection fixture; manual runs
  may stopwatch second-scale waits; automation never sleeps (C-13.7).
- **State:** a case that changes a fixture profile, binding or definition restores it in teardown
  (versions never rewind); a fresh test database with the seed is the clean state (§12.1).
- **Out of scope:** writing the automation (E28-Q02), load, soak and chaos (E28-Q03), the
  accessibility audit (E28-Q04), the abuse-case suite (E28-X03, which §10 feeds), fan-out
  submission, the rate governor and the unwind (E34), the OMS (E29), the native-SL attach (E32),
  lockouts and the kill switch (E39), the journal (E41).

## 0.1 Defect conventions and triage for this epic

Severity follows `docs/plan/03-testing-strategy.md` §11.3. Epic overrides (E28 threat model §1.3:
a sizing defect repeats on every leg, H\*):

<!-- prettier-ignore -->
| Observation | Severity and handling |
| --- | --- |
| **A sizing error:** any quantity, notional, stop, take-profit, leverage, margin or risk figure that differs from the golden vector or the hand recomputation in any digit, in either direction, in a preview, a ticket, a leg or an order | **`priority/p0-critical`**, whatever the size of the difference. A vector mismatch is raised as a Bug against E28-T03 before the sizer merges (#904) |
| A position-opening order or leg without a native stop-loss, or `require_native_stop` stored false (C-2.6) | `priority/p0-critical` |
| An order or leg accepted that the profile forbids: a symbol outside the allow-list, a cap exceeded, a widening override, a group spanning demo and live, a leg on a not-ready member | `priority/p0-critical` |
| A preview that writes a row or calls the exchange (SR-E28-22) | `priority/p0-critical` |
| The existence, sizing or equity of an account outside the caller's grants disclosed | `priority/p0-critical`; reported privately (`SECURITY.md`), never in a public issue |
| An accessible path past step-up, the diff summary, the send block or a disabled control (E28 threat model D9) | Security finding, escalated to E28-X02; at least `priority/p1-high` |
| A refusal from authorisation on without its audit row, or a malformed one (C-2.9) | `priority/p1-high`, filed against the acting case |
| A budget in §0.3 missed | `priority/p2-normal`; `priority/p1-high` for the guard and the fan-out overhead (R3 hard gate) or when it blocks the flow |
| An AX-04 task not completable keyboard-only | `priority/p2-normal`; `priority/p1-high` for save, step-up, send, flatten or delete |
| Copy that differs from the story or spec without misstating a limit | `priority/p3-low`; `priority/p2-normal` when it misstates a limit or a reason |

**Every report** uses `.github/ISSUE_TEMPLATE/bug_report.yml` and names: the case id; the story id
and scenario title; reproduction steps as the case's numbered steps; the environment (stub or demo
stack, build sha, `CV_ENV`, the seed's commit, the scenario and overlays loaded, the vector id for
a sizing defect); the exact request and response or frame, redacted; expected (with the source the
case follows) against actual; and the evidence codes.

**Who triages.** The QA owner of E28-Q05 triages within the §11.3 SLA, at the weekly ritual
(`docs/plan/backlog/artifacts/e49-triage-ritual.md`) or sooner, and assigns the defect to the
implementing ticket. A sizing, native-stop or cap-bypass defect is raised to the Owner and the
Architect the same day, and a bypass or a disclosure to the Security engineer (E28-X02). A defect
against a §13 row cites the row and is triaged as needs-clarification until the row is settled.

## 0.2 Entry and exit criteria

Each criterion is checked by the artefact named.

<!-- prettier-ignore -->
| Id | Entry criterion (before a group is executed) | Checked by |
| --- | --- | --- |
| EN-1 | The implementing ticket is merged and In Test (03 §16), on a build with CI green | the ticket's status and the build sha in §14 |
| EN-2 | Every route the group calls answers: not `501`, and not the plain `404` of a route not mounted | a probe call per route |
| EN-3 | The fixture set loads once into a clean migrated test database with one command; a second run is refused at its first key and writes nothing, so reloading means a fresh database | slice A's README command and its integration test in CI, which runs the seed twice |
| EN-4 | The stub transport serves the account pack and the overlays §12.6 lists for the group | a scenario-load check row in §14 |
| EN-5 | Before any sizing case: E28-T03's sizer, run over V01 to V14, gives every value exactly | E28-T03's run over slice A's vector file, recorded in §14 |
| EN-6 | This plan is peer-reviewed and the criteria are agreed with the Owner and the Architect | §15 boxes ticked |

<!-- prettier-ignore -->
| Id | Exit criterion (before E28 is Done) | Checked by |
| --- | --- | --- |
| EX-1 | Every scenario in §8 has an executed case with pass or fail recorded on its story (03 §16) | §14 rows and the story comments |
| EX-2 | Zero open `priority/p0-critical` or `priority/p1-high` defects from this plan | the board's E28 Bug view |
| EX-3 | Ten or more golden vectors recomputed by QA match E28-T03's values exactly; every mismatch was a Bug before the sizer merged | slice A's spreadsheet and T03's run |
| EX-4 | Every boundary (§9) and hostile (§10) entry executed, each refusal's audit row asserted where §11 names one and recorded otherwise (§13 C-23) | E28-Q02 and E28-X03 reports |
| EX-5 | Every §0.3 assertion measured by its named ticket and within budget | E28-Q03, E34-Q03, E28-S02 and E28-Q02 reports; E28-D07's confirmation |
| EX-6 | AX-01 to AX-05 executed by E28-Q04 with axe clean (no serious or critical) | E28-Q04 report |
| EX-7 | The four charters executed with debriefs | `qa/plans/e28-exploratory-charters.md` session sheets |
| EX-8 | The automated suites green on three consecutive CI runs | E28-Q02's CI history |
| EX-9 | Each §13 row settled by its owner (a contract or docs change, or a ruling), or accepted with a named owner and expiry | the change or ruling, linked from the row |
| EX-10 | QA sign-off comment on epic E28, referencing E28-Q05 | the epic issue |

## 0.3 Perceived-performance assertions

A missed budget is a functional defect (§0.1). Each assertion names the ticket that measures it.

<!-- prettier-ignore -->
| Id | Budget | Source | Assertion | Measured by | Cases |
| --- | --- | --- | --- | --- | --- |
| PA-1 | Preview ≤300 ms | SCR-061; E28 threat model §6 | p95 of `POST /trade-groups/preview` ≤300 ms at 5 accounts with warm caches, and the per-account slope reported at 1, 3, 5 and 20 accounts; on SCR-061 the preview re-runs within 300 ms of the last keystroke | E28-Q03 (server); E28-Q02 (UI, `T`) | PRV-03 |
| PA-2 | Profile save ≤2 s | SCR-131; E28-T02 | p95 from Save to the rendered result ≤2 s, revalidation against the exchange's limits included, under concurrent editors | E28-Q03 | PRO-01 |
| PA-3 | Matrix render ≤600 ms | SCR-133; E28-S02 | SCR-133 with 6 accounts and about 400 symbols renders within 600 ms and scrolls without jank | E28-S02, in its browser perf harness (E28-S02 "The matrix is usable at full universe size"); confirmed by E28-D07 under the fixture load | SYM-05 |
| PA-4 | Guard ≤5 ms p95 | US-PROF-004 NFR; E28-T04 | the risk guard adds ≤5 ms p95 to the order path over at least 10 000 warm-cache evaluations; the cold-cache figure recorded separately | E28-Q03 | CAP-01 to CAP-03 |
| PA-5 | Fan-out overhead ≤50 ms + ≤10 ms/account | 06 §5.2 budget #4; R3 exit #3 | backend-added fan-out overhead p95: fitted fixed cost ≤50 ms and marginal cost ≤10 ms per account, at 1 to 5 accounts | E34-Q03 (§13 C-25) | FAN-01 |
| PA-6 | `trade_groups` throttle 100 ms | 23 §6.2 | the throttle holds at 50 groups × 5 legs for 60 min with flat memory and no lost frame | E28-Q03 | GRP-04 |
| PA-7 | Group acknowledged ≤1.5 s for 5 accounts | SCR-061; ADR-0008; US-PROF-006 NFR (its ≤400 ms ruled out) | the full group acknowledgement p95 ≤1.5 s for 5 accounts: ADR-0008's figure wins over the story's ≤400 ms (#904 record, ruling 12 (2026-10-25); §13 C-25) | E34-Q03 | FAN-01 |

---

## 1. Group PRO — Profile definition and sizing (US-PROF-001, US-PROF-002; E28-T02, E28-T03, E28-S01)

Screens SCR-130, SCR-131, SCR-060. Endpoints `GET`/`POST .../profiles`,
`GET`/`PUT`/`DELETE .../profiles/{profileId}`, `GET`/`PUT .../default-profile`,
`POST /trade-groups/preview`. Sizing cases run on the stub stack unless they say otherwise; the
reference intent RI and the reference order RO are §12.3.

<!-- prettier-ignore -->
| Case | Covers | Preconditions | Steps | Expected result | Evidence | Audit · metric | By | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TC-E28-PRO-01 | US-PROF-001 "Create profile" | E28-C bound to P-PCT; Owner with no live `risk_caps` step-up | 1. SCR-131 for E28-C, new profile `QA Swing 2`: leverage 10, `max_leverage_cap` 10, risk-based 0.5 %, stop 1.5 × ATR(14), take-profit 2 R, `max_daily_loss_pct` 2, `max_open_positions` 3, `max_concurrent_orders` 20, `max_position_notional_usd` 50000, allowed BTCUSDT and ETHUSDT, `trading_enabled` on; Save. 2. Answer the step-up; re-send. 3. `GET .../profiles`. 4. Bind it (`PUT .../default-profile`, the binding's `If-Match`). 5. Open SCR-060 and SCR-061 for E28-C. 6. Teardown: bind P-PCT again, delete `QA Swing 2`. | 1: `403 step_up_required`, `action_class: risk_caps`; nothing stored. 2: `201` `AccountProfile`, `version: 1`, `environment: demo`, an `ETag`, `profile` holding every member with its default (`require_native_stop: true`, `slippage_tolerance_bps: 10`). 3: listed after the default, by name. 4: `200`, binding `version` + 1; `profile.bound` labelled `relaxing` exactly when a cap is higher than P-PCT's, judged cap by cap with `null` as no bound (record the label). 5: both tickets name `QA Swing 2` for E28-C. | HAR, SS, AUD, T | `auth.step_up_required` (1), `profile.created` (2), `profile.unbound` + `profile.bound` (4, teardown), `profile.deleted` (teardown) · `cv_profile_saves_total{result}` +1 ok | Q02 | mapped, not executed |
| TC-E28-PRO-02 | US-PROF-001 "Create profile" | M and V (§12.2) | 1. As M, `POST .../profiles` on E28-C with PRO-01's body; then again after a step-up. 2. As M, `PUT .../profiles/{P-PCT}` with its `ETag`. 3. As M, step 1 on E28-B (not granted). 4. As V, step 1 on E28-A. 5. As M, open `/admin/profiles`. | 1–4: `403 step_up_required`, then `403 forbidden` after the step-up (`accounts:write` is Owner-only; the route is path-gated); nothing stored on any account. 5: the router's not-found page (SCR-155), no profile data. | HAR, AUD | `auth.step_up_required`, then `rbac.denied` per refused call (§11.1) · `authz_denied_total` +1 per denial | X03 | mapped, not executed |
| TC-E28-PRO-03 | US-PROF-001 "Invalid combination" | E28-A; Owner with a live step-up | `POST .../profiles` and SCR-131 with `sizing: {mode: risk_based, risk_per_trade_pct: "0.5"}` and a) no `stop_loss`, b) `stop_loss: null`, c) `stop_loss: {unit: r_multiple, value: "1"}`. | Each `422 validation_failed` naming `stop_loss` (a: `required`; b: the validator's type rule; c: `stop_defines_r`); nothing stored. SCR-131 blocks Save with the message on the stop field itself, associated with the input for screen readers (S01). | HAR, SS, A11Y | none: refusals of shape (§13 C-23; a row found is recorded) · `cv_profile_validation_failures_total{rule}` +1 each | Q02 | mapped, not executed |
| TC-E28-PRO-04 | US-PROF-001 "Profile in use" | E28-A on P-RISK `version: 1`; G-CORE3's and G-PAIR's legs on E28-A sized from it (V01); E28-A's open BTCUSDT long; Owner with a live step-up | 1. `GET .../profiles/{P-RISK}`. 2. `PUT` it with `risk_caps.max_daily_loss_pct` "2" (it holds "3") and step 1's `ETag`. 3. Re-send step 2 with the old `ETag`, then with none. 4. `GET /trade-groups/{G-CORE3}`, `/trade-groups/{G-PAIR}`, `GET /positions` for E28-A. 5. `PUT` it with `sizing.risk_per_trade_pct` "0.4" and the new `ETag`. 6. `PUT` it with `risk_caps.max_daily_loss_pct` "3" and `sizing.risk_per_trade_pct` "0.5" and the newest `ETag`, which restores the seed's values. | 2: `200`, `version: 2`, a new `ETag`, not labelled `relaxing` (a cap narrowed); SCR-131 states the change applies to future orders only. 3: `412 version_conflict`, then `428 precondition_required`; nothing changed. 4: E28-A's legs unchanged: `account_profile_id` P-RISK, `target_qty` 0.416, `resolved.stop_loss_price` 63880.0, `resolved.leverage` 5; the position unchanged (0.001 at 63110.00, stop-loss 63080.00). No REST member shows a leg's profile version (§13 C-29): record any route that does. 5: `200`, `version: 3`, not labelled `relaxing` and no Owner notification: a replace is relaxing only when it loosens a cap or widens the symbols a trading profile allows, and a sizing amount is neither (`updateAccountProfile`, 22:3272-3279). 6: `version: 4`, labelled `relaxing` (the loss cap loosens from 2 to 3), the Owner notified once (`GET /notifications`; SR-E28-01). | HAR, SS, AUD | `profile.updated` with before and after (2, 5 and 6; only 6 labelled `relaxing`) · `cv_profile_saves_total{result}` +3 ok | Q02 | mapped, not executed |
| TC-E28-PRO-05 | US-PROF-002 "Risk-based sizing" | E28-A on P-RISK (0.5 %, 1200-tick stop); stub wallet equity 10000; the fee rate the stub serves | 1. `POST /trade-groups/preview` with RI and one leg, E28-A. 2. SCR-060 for E28-A, BTCUSDT, Limit 64000.0. 3. Compare with V01 (taker fee 0) or V02 (0.00055). | 1: `would_submit: true`; `resolved` at fee 0: qty 0.416 (0.41666… floored to the 0.001 step), `stop_loss_price` 63880.0, `notional_usd` 26624.0, `risk_usd` 49.92, leverage 5 (V01); at fee 0.00055: qty 0.262, notional 16768.0, risk 31.44 (V02); §13 Q-01 decides which the stack must serve. 2: the same quantity, with the implied risk in USDT and in R (the R figure recorded, §13 Q-09). Every digit equals the vector; its ladder has no REST member (§13 C-37). | HAR, SS, VEC | `tradegroup.preview` · `cv_sizer_outcomes_total{outcome="ok"}` +1 | Q02 | mapped, not executed |
| TC-E28-PRO-06 | US-PROF-002 "Risk-based sizing" | Stub stack; for each vector on P-RISK, P-QTY or P-NOTIONAL, E28-C bound in setup to a copy of the vector's profile (§12.3), with the vector's `set` fields as REST members (24 §9.2's table): `allowed_symbols` as written, and V13's `sl_offset_value` "100" as `stop_loss.value` "100" (unit `ticks`); V06 and V11 on E28-C's own P-PCT; the wallet, ATR and day's-loss state the vector names (§12.6); each vector's own taker fee: the zero-fee overlay for all but V02, which takes the `compliant` scenario's 0.00055 (slice A Q1) | For each of V02, V06, V07, V08, V09, V10, V11, V13 and V14: preview the vector's intent with one leg, E28-C; compare every expected field; rebind P-PCT in teardown. For V09, then submit the intent with a fresh `Idempotency-Key`; the stub fills the entry in full at 64000.0 (§12.6); read `GET /orders`; teardown clears the position. | Each field the preview carries (`resolved`, `estimated_margin_usd`, `rejection`) equals the vector: the floor to the step (R9), the stop rounded away from entry (V06 down, V07 up), V07's 2R take-profit, the day's room binding (V10), the instrument's `max_order_qty` binding (V11), fixed notional with no cap binding (V14), a skip with the minimum named (V08) and `insufficient_margin` (V13); V10's and V14's 100-tick take-profits are not compared (§13 Q-13). Two have no REST member (§13 C-37): V06's `stop_fallback` is read as `cv_sizer_stop_fallback_total` +1 beside its stop, 2462.12; V09's ladder only after the submit and the stub's fill, as two take-profit reduce-only orders in `GET /orders`, 0.207 at 64120.0 and 0.208 at 64240.0, the last taking the remainder (24 §9.3.3; whether a rung prices from the reference or the fill is §13 Q-06's question, and both are 64000.0 here); this part waits on E34 and E32. A skip or failure code the preview cannot carry is recorded (§13 C-14). | HAR, VEC, MET | `tradegroup.preview` each, and the expansion (§11.1) for V09's submit · `cv_sizer_outcomes_total{outcome,reason}`, `cv_sizer_clamped_total{cap}` (V10, V11), `cv_sizer_stop_fallback_total` (V06) | Q02 | mapped, not executed |
| TC-E28-PRO-07 | US-PROF-002 "Percent-of-equity" | E28-C on P-PCT (5 % of equity at 10x, stop 1.5 × ATR(14), fallback 2 %); equity 10000 | 1. Preview RI with one leg, E28-C. 2. SCR-060 for E28-C. | 1: qty 0.078 (0.078125 floored), `notional_usd` 4992.0, `estimated_margin_usd` 499.2, leverage 10 (V05; T03 AC 2's 5000 and 500 are the figures before the floor, §13 Q-05). The stop is 64000.0 − 1.5 × ATR rounded down to the 0.10 tick, with the ATR the explanation names (63400.0 at 400.0); with no ATR, the 2 % fallback stop, with `cv_sizer_stop_fallback_total` +1 standing for the `stop_fallback` flag, which no REST member carries (§13 C-37). 2: notional, quantity and initial margin shown. | HAR, SS, VEC, MET | `tradegroup.preview` · `cv_sizer_outcomes_total` +1; `cv_sizer_stop_fallback_total` +1 in the fallback branch only | Q02 | mapped, not executed |
| TC-E28-PRO-08 | US-PROF-002 "Below minimum lot" | E28-A on P-RISK; stub wallet equity 20 (V04) | 1. Preview RI with one leg, E28-A. 2. SCR-060 for E28-A; read the ticket; submit 0.001 BTC (RO with `sizing: {mode: fixed_qty, qty: "0.001"}`, §12.3). 3. SCR-061's row for E28-A. | 1: `would_submit: false`, the floored qty 0.000 and the minimum 0.001 reported (V04); the code recorded (§13 C-14). 2: submission blocked and the minimum 0.001 BTC explained, but not offered as a one-click choice: the ticket states that the 0.001 BTC minimum risks 0.12 USDT, above the 0.10 USDT budget; the 0.001 submit is refused `403 risk_limit_breached`, audited, never rounded up, and nothing is sent (ADR-0040's rule 5 and its scenario, ADR-0040:120-122, ADR-0040:268-273; proposed until its sign-off on #2701: §13 C-13). 3: the row reads excluded, with the computed quantity and the minimum. | HAR, SS, VEC | `tradegroup.preview`; a refusal row for step 2's submit (§11.1) · `cv_sizer_outcomes_total{outcome="skip",reason="below_min_notional"}` +1 | Q02 | mapped, not executed |

---

## 2. Group SYM — Symbol restriction (US-PROF-003; E28-T04, E28-S02)

Screens SCR-060, SCR-061, SCR-130, SCR-133. Endpoints `POST /orders`, `POST /trade-groups`,
`POST /trade-groups/preview`, `GET`/`PUT .../profiles/{profileId}`. The story's DOGEUSDT has no
recorded instrument row (§13 C-02), and every observable path reads the instrument before or with
the symbol gate (§13 C-36), so the cases assert on SOLUSDT, which is recorded and is not on
E28-A's allow-list. DOGEUSDT, P-PCT's blocked symbol on E28-C, is only sent and its answer
recorded (SYM-01 step 2, SYM-02 step 4).

<!-- prettier-ignore -->
| Case | Covers | Preconditions | Steps | Expected result | Evidence | Audit · metric | By | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TC-E28-SYM-01 | US-PROF-003 "Allowed" | M; E28-A allows BTCUSDT and ETHUSDT; E28-C allows every symbol but DOGEUSDT | 1. As M, open SCR-060 for SOLUSDT on E28-A. 2. The same for DOGEUSDT on E28-C, if the stack lists it. 3. Read the ticket by keyboard and screen reader. | 1: order entry disabled with "not permitted on this account" as text, which is also the disabled control's accessible description (AX-03); no order request leaves the client. 2: recorded (DOGEUSDT may not be listed at all). | SS, A11Y, HAR | — · — | Q02 | mapped, not executed |
| TC-E28-SYM-02 | US-PROF-003 "Server enforcement" | As SYM-01; keys imported for E28-A and E28-C | As M: 1. `POST /orders` RO with `symbol: SOLUSDT` on E28-A. 2. `POST /trade-groups` RI with `symbol: SOLUSDT`, one leg E28-A. 3. Step 2 as a preview. 4. Step 1 with DOGEUSDT on E28-C. | 1: `403` before any exchange call: the code is `risk_limit_breached` in the registry and `profile_forbidden` in E28-T04 (§13 C-10), recorded; no order create in `LOG`, no row in `GET /orders`. 2: nothing sent for the leg; the skip (`symbol_not_allowed`) or the refusal recorded. 3: the leg `would_submit: false`, `rejection.code: symbol_not_allowed`. 4: refused, nothing sent, by the profile gate or as an unlisted symbol (recorded). Each refusal names the account, the symbol and the gate. | HAR, LOG, AUD, MET | `order.refused_by_profile{gate, observed, limit}` per refusal (§11.1) · `cv_risk_guard_refusals_total{gate}` +1 each | X03 | mapped, not executed |
| TC-E28-SYM-03 | US-PROF-003 "Empty list allows nothing" | E28-D on P-NOTIONAL (empty allow-list, `all_symbols` false); key imported for E28-D; Owner | 1. `GET .../profiles/{P-NOTIONAL}`. 2. SCR-130's row for E28-D. 3. Preview RI with one leg, E28-D. 4. `POST /orders` RO on E28-D. | 1: `warnings[]` holds `no_symbols`. 2: the row flags that the profile allows no symbol, as text (D11). 3: `would_submit: false`, `symbol_not_allowed`, decided before any price is read (V12). 4: `403`, nothing sent. A build that permits any symbol here is P0 (§13 C-09). | HAR, SS, AUD | `order.refused_by_profile` (4) · `cv_sizer_outcomes_total{reason="symbol_not_allowed"}` +1 (3) | Q02 | mapped, not executed |
| TC-E28-SYM-04 | US-PROF-003 "All symbols is explicit" | E28-C on P-PCT (`all_symbols` true, no allow-list, DOGEUSDT blocked); Owner with a live step-up | 1. `GET .../profiles/{P-PCT}`; SCR-130's row. 2. Preview RI on E28-C for BTCUSDT, ETHUSDT, SOLUSDT and LUNAUSDT, one request each. 3. `PUT` P-PCT with `all_symbols: true` and `allowed_symbols: ["BTCUSDT"]`. 4. `POST` an alternate on E28-C with `allowed_symbols: ["*USDT"]`. | 1: `warnings[]` holds `all_symbols`; the row flags "allows all symbols" as text. 2: each leg `would_submit: true`. 3: `422 validation_failed`, `not_allowed` on `allowed_symbols`; nothing stored. 4: `201` with the `all_symbols` warning: a universal pattern counts as all symbols. | HAR, SS, AUD | `tradegroup.preview` (2), `profile.created` (4) · — | Q02 | mapped, not executed |
| TC-E28-SYM-05 | US-PROF-003 "Server enforcement"; E28-S02 "A symbol with an open position cannot be denied" | E28-A holds the open BTCUSDT long; E28-C has no ETHUSDT position; Owner with a live step-up | 1. SCR-133: deny ETHUSDT for E28-C; review the summary; save. 2. `POST /orders` RO with `symbol: ETHUSDT` on E28-C. 3. SCR-133: try to deny BTCUSDT for E28-A. 4. `PUT` P-RISK without BTCUSDT in `allowed_symbols`. | 1: the summary lists the removal; one server call; `200`, not `relaxing`. 2: `403`, nothing sent. 3: the (E28-A, BTCUSDT) cell is marked not deniable, glyph and text, and the attempt is refused with an explanation and recorded. 4: the answer recorded: the contract documents no refusal here (§13 C-30). SCR-133 renders within 600 ms (PA-3). | HAR, SS, A11Y, AUD, T | `profile.updated` (1), `symbol_permission.change_refused` (3), `order.refused_by_profile` (2) · `cv_risk_guard_refusals_total{gate}` +1 | Q02 | mapped, not executed |

---

## 3. Group CAP — Risk caps (US-PROF-004; E28-T04, with E39 for the lockout)

Screens SCR-060, SCR-071. Endpoints `POST /orders`, `POST /trade-groups/preview`,
`GET /risk/summary`, `PUT .../profiles/{profileId}` (setup). Each case binds its setup values on
E28-A or E28-C as the Owner, and restores them.

<!-- prettier-ignore -->
| Case | Covers | Preconditions | Steps | Expected result | Evidence | Audit · metric | By | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TC-E28-CAP-01 | US-PROF-004 "Position size cap" | E28-C bound to a copy of P-PCT (§12.3) with `sizing: {mode: fixed_qty, qty: "0.2"}`, `max_position_notional_usd` = 0.5 × the overlay's mark price and `max_position_pct_equity: null`, because P-PCT's 100 % of equity (10000 USDT) would cut the 0.2 order and refuse on that cap first, while the notional cap keeps the profile's position cap bounded (`cap_unbounded`); overlay: E28-C holds 0.4 BTC BTCUSDT long (§12.6); key imported | 1. `POST /orders` RO (profile sizing, 0.2) on E28-C. 2. The same as a one-leg preview. 3. RR selling 0.1 of the position (§12.3). | 1: refused before any exchange call, `403 risk_limit_breached` (E28-T04 writes 422, §13 C-10), with a message naming the cap and the current position: "would exceed max position 0.5 BTC (current 0.4)" (the cap is held in USDT, so the units shown are recorded, §13 C-22); nothing sent. 2: `would_submit: false`, `rejection.code: cap_breached` (an account-state cap marks its leg alone). 3: `202`: a reduction is never refused by a cap. | HAR, LOG, SS, AUD, MET | `order.refused_by_profile{gate, observed, limit}` (1) · `cv_risk_guard_refusals_total{gate}` +1 | Q02 | mapped, not executed |
| TC-E28-CAP-02 | US-PROF-004 "Concurrent positions cap" | E28-C bound to a copy of P-PCT (§12.3) with `max_open_positions` 3; overlay: open positions on BTCUSDT, ETHUSDT and SOLUSDT (§12.6) | 1. `POST /orders` RO for LUNAUSDT, a fourth symbol, on E28-C. 2. RR reducing the BTCUSDT position (§12.3). 3. An entry adding to ETHUSDT. | 1: refused before any exchange call (`403`, code recorded), nothing sent. 2: `202`; the exemption needs the exchange-enforced `reduceOnly` on the matching side (SR-E28-30). 3: no fourth symbol opens, so the open-positions gate passes; any other refusal recorded. | HAR, LOG, AUD, MET | `order.refused_by_profile{gate: open positions}` (1) · `cv_risk_guard_refusals_total{gate}` +1 | Q02 | mapped, not executed |
| TC-E28-CAP-03 | US-PROF-004 "Daily loss cap" | E28-A on P-RISK (`max_daily_loss_usd` 1000, `max_daily_loss_pct` 3: 300 USDT at equity 10000); the open BTCUSDT long; before the overlay, an `orders` and a `rules` subscription with `exchange_account_ids: [E28-A]`, and an `alerts` subscription, which takes no accounts; `system` is auto-subscribed (23:836, 23:840); then the overlay: today's realised plus unrealised loss on E28-A reaches 300.00 (§12.6) | 1. `POST /orders` RO entry on E28-A. 2. `GET /risk/summary`; `GET /notifications`, then again with `kind=risk`; read the frames the four topics carried since they were opened (22:12452-12454; 14:390). 3. RR closing the whole open position (`intent: flatten`, §12.3). 4. Preview RI on E28-A. | 1: refused, nothing sent: `403 risk_limit_breached`, or `403 trading_disabled` once E39's lockout stands (recorded, §13 Q-11). 2: E28-A `lockout.reason: daily_loss` with `since` (US-RULE-012); a `warning` notification raised for the breach (E28-T04: "a cap breach raises a `warning` notification"): the topic it arrived on, its `kind` in `GET /notifications` and how many are recorded, not asserted, until E28-T04 or E40 names the surface (§13 Q-15). 3: `202`: the guard never blocks a reduce-only close (SR-E28-24). 4: `would_submit: false`, `account_locked` or `cap_breached` (recorded). | HAR, LOG, SS, WS, AUD, MET | `risk.cap_breached`, `order.refused_by_profile{gate: daily loss}` · `cv_risk_guard_refusals_total{gate}` +1, `cv_account_daily_loss_usd{account}` at the cap | Q02 | mapped, not executed |

---

## 4. Group GRP — Trade groups (US-PROF-005; US-PROF-007, the definition half; E28-T05, E28-S03)

Screens SCR-062, SCR-061 (target selector). Endpoints `GET`/`POST /trade-group-definitions`,
`GET`/`PUT`/`DELETE /trade-group-definitions/{definitionId}`, `GET /trade-groups`,
`GET /trade-groups/{tradeGroupId}`, `POST /trade-groups/preview`; WS `trade_groups`. Definition
writes are Owner-only with a `risk_caps` step-up (D8, open: §13 Q-14).

<!-- prettier-ignore -->
| Case | Covers | Preconditions | Steps | Expected result | Evidence | Audit · metric | By | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TC-E28-GRP-01 | US-PROF-005 "Create group" | Owner; Core3 and Pair (seed); E28-A, E28-B, E28-C in demo | 1. SCR-062: new definition named `core3` with E28-A, B and C; save; answer the step-up. 2. Rename it `Core3-QA`; save. 3. `GET /trade-group-definitions`. 4. Open SCR-061's target selector. | 1: `409 conflict` (the name is Core3's, compared case-insensitively); the name field carries the error. 2: `201` `TradeGroupDefinition`, `definition.members` the three accounts, an `ETag`. 3: Core3, Pair and Core3-QA listed. 4: each with its member count: Core3 (3), Pair (2), Core3-QA (3). | HAR, SS, AUD | `auth.step_up_required` (1), `tradegroup.created` with the membership after (2) · `cv_tradegroup_members_gauge{group}` | Q02 | mapped, not executed |
| TC-E28-GRP-02 | US-PROF-005 "Mixed environments blocked" | Owner with a live step-up; E28-A (demo), E28-LIVE-SUB (live); Pair | 1. SCR-062: select E28-A, then E28-LIVE-SUB. 2. `POST /trade-group-definitions` with `environment: demo` and both. 3. `PUT` Pair adding E28-LIVE-SUB, with its `ETag`. 4. `PUT` Pair with `environment: live`. | 1: refused at selection with "a trade group cannot mix Demo and Live", naming the accounts. 2: `400 validation_failed`, one `errors[]` entry `rule: environment_mismatch` for E28-LIVE-SUB; nothing written. 3: the same; Pair's `ETag` unchanged. 4: `400 validation_failed`, `rule: write_once`. | HAR, SS, AUD | a refusal row per refused write (no event is named, §13 C-23) · — | Q02 | mapped, not executed |
| TC-E28-GRP-03 | US-PROF-005 "Inactive member" | Core3; E28-B disarmed by the key self-check (`trading_enabled` false, `policy_disarm_code` `key_ip_whitelist_mismatch`); keys imported for E28-A and E28-C | 1. SCR-062 and SCR-061's selector for Core3. 2. Preview RI for Core3's members. 3. `POST /trade-groups` RI for them. 4. `GET /trade-groups/{id}`; `LOG`. | 1: "2 of 3 ready"; E28-B carries "not ready: key self-check failed" as text, available to screen readers (§13 Q-10). 2: `totals.accounts_targeted` 3, `accounts_submittable` 2; E28-B `would_submit: false`, its code recorded; E28-A and E28-C sized as PRO-05 and PRO-07. 3–4: legs on E28-A and E28-C only, as in the seeded G-CORE3; no order for E28-B in `LOG`; the skip reported with its reason (REST and WS carry no skip count, §13 C-14). | HAR, SS, A11Y, LOG, AUD | `tradegroup.preview` (2); `tradegroup.created` + one `tradegroup.leg.result` per sent leg (3; SR-064) · `cv_tradegroup_legs_skipped_total{reason}` +1 | Q02 | mapped, not executed |
| TC-E28-GRP-04 | US-PROF-007 "Aggregate view" | G-CORE3 and G-PAIR (cancelled, legs on E28-A and E28-C); an open Trio group (§5) with E28-A's and E28-C's legs filled and E28-D's partly filled, its remainder working (§12.6), because the story's Given is a trade open across three accounts and step 3 needs a lot left to fill; a `trade_groups` subscription | 1. SCR-062: list; expand G-CORE3 and the Trio group. 2. `GET /trade-groups/{id}`; sum the legs by hand. 3. Fill one more lot of E28-D's remainder (the stub); watch the frames and the row. | 1: one row per group, its state as text (`cancelled`, `open`); expanding shows a nested per-account table; the Trio group shows aggregate size (Σ `filled_qty`), the weighted average entry (Σ qty × price / Σ qty) and the aggregate uPnL (E34-S05) beside its three per-account rows. 2: the aggregates equal the hand sums. 3: a `trade_groups` frame within its 100 ms throttle (23 §6.2), and the row updated within 200 ms of it, as SCR-062 coalesces updates to 5 Hz; focus stays where it was. | HAR, SS, WS, T | — · `cv_tradegroup_ws_frames_total` +1 per frame | Q02 | mapped, not executed |

---

## 5. Group FAN — Fan-out (US-PROF-006; US-PROF-007, the execution half; E34-S02, E34-S03, E34-S05, E32)

Screens SCR-061, SCR-062. Endpoints `POST /trade-groups`, `GET /trade-groups/{tradeGroupId}`,
`POST /trade-groups/{tradeGroupId}/cancel`, `GET /orders`, `GET /positions`; WS `trade_groups`.
**Trio** is a definition created in setup with E28-A, E28-C and E28-D, with keys imported for all
three. For the run (Owner, step-up; restored in teardown) E28-D's P-NOTIONAL takes
`allowed_symbols` `["BTCUSDT"]`, `slippage_tolerance_bps` 10 and `default_time_in_force` `GTC`,
P-RISK's values: as seeded it allows no symbol, and its slippage 0 and `PostOnly` may refuse a
market leg, while US-PROF-006 "Fan-out" needs three orders created.

<!-- prettier-ignore -->
| Case | Covers | Preconditions | Steps | Expected result | Evidence | Audit · metric | By | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TC-E28-FAN-01 | US-PROF-006 "Fan-out" | Trio, with E28-D at slippage 10 and `GTC` for the run (§5), because its seeded 0 and `PostOnly` may refuse a market leg and the scenario needs three orders; Owner | 1. Preview a BTCUSDT market buy with `defaults.sizing.mode: profile`, the profiles' stops and take-profits. 2. Submit it with a fresh `Idempotency-Key`. 3. Watch `trade_groups`; `GET /trade-groups/{id}`, `GET /orders`, `LOG`. 4. Re-send step 2 unchanged. | 2: `202` `TradeGroup` with three legs, one per account, each sized and levered by its own profile (E28-A 5x, E28-C 10x, E28-D 2x; each quantity recomputed by hand from the reference price its leg reports, §13 C-35), each with a non-null `stop_loss_price`: three orders created, E28-D's under the run's slippage and time in force (§5's Trio). 3: every order create in `LOG` carries `stopLoss` (C-2.6); each leg reaches `native_sl_confirmed: true`; the three orders link to one trade-group id. 4: the original answer with `Idempotency-Replayed: true`; no second group, nothing sent. | HAR, WS, LOG, AUD, VEC | `tradegroup.created` + one `tradegroup.leg.result` per leg (SR-064; registered today as `trade_group.submit`) · `cv_tradegroup_preview_total` +1 | Q02 | mapped, not executed |
| TC-E28-FAN-02 | US-PROF-006 "Partial failure" | Trio; E28-D's order create answered with an exchange rejection (§12.6) | 1. Submit as FAN-01. 2. Read SCR-061 and `GET /trade-groups/{id}`. 3. Choose "flatten group" (`POST .../cancel`, `flatten_filled: true`). 4. Retry E28-D. | 2: E28-A and E28-C stay live with their stops; E28-D `rejected` with the reason in domain language and the exchange code in details (`LegError`; 11 global AC 5); status `partially_open`; the summary is `role="alert"` and offers a retry of E28-D and "flatten group"; an alert raised (SR-072). 3: each filled leg closed reduce-only, its stop gone only once the leg is verified flat (SR-E28-33). 4: no route takes a per-leg retry: recorded (§13 C-19); a retry while E28-D's first attempt is unresolved is refused (E28 threat model AC-16). | HAR, SS, WS, LOG, AUD | `tradegroup.partial_failure`, `tradegroup.leg.result` per leg, `tradegroup.cancelled{flatten_filled}` naming each stop kept or gone · `unwind_incomplete_total` stays 0 | Q02 | mapped, not executed |
| TC-E28-FAN-03 | US-PROF-006 "Rate-limit budget" | Trio; E28-C's per-UID budget near empty (the stub's `rate_limited_10018` on E28-C, or a burst first) | 1. Preview, then submit as FAN-01. 2. Watch SCR-061, `LOG` and the metric. | No request is dropped silently: each leg is sent, queued per account with the delay shown, or refused with a reason (the story queues; the contract's pre-flight refuses the whole group: §13 C-18, recorded). The preview marks the starved leg `rate_budget_exhausted`. `LOG` shows no request beyond the budget and no entry drawn from the protective reserve (SR-E28-23). | HAR, SS, LOG, MET | `ratelimit.rejected` if refused · `oms_rate_tokens_available{account,bucket}` | Q02 | mapped, not executed |
| TC-E28-FAN-04 | US-PROF-007 "Group action" | An open Trio group, every leg filled (FAN-01 or §12.6) | 1. SCR-062: "close group 50%" on the group; confirm. 2. `GET /positions`; `LOG`; the requests SCR-062 sent. | Each account closes 50 % of its own position, rounded to its lot size (the direction recorded: the story names none), reduce-only; each remainder keeps its native stop; partial failures listed per account. No trade-group route takes a percentage close, though `closePosition` takes `pct` for one position (§13 C-20): record whether SCR-062 sends one group command, the one-command pattern it sets for Flatten-group (14:1445; 24 §9.6), or a `POST /positions/{positionId}/close` per leg; SCR-062 names no percentage-close control. | HAR, SS, LOG, AUD | one action with a result per leg (24 §9.6) · — | Q02 | mapped, not executed |
| TC-E28-FAN-05 | US-PROF-007 "Divergence warning" | An open Trio group; E28-C's position changed outside the app (the stub's position list answers another size); test clock | 1. Advance the clock 30 s; read SCR-062's row. | By the next REST reconciliation (at least every 30 s, US-PROF-007 NFR) the group shows a "divergent" badge as text naming E28-C and the difference. No field of `TradeGroup` or `TradeGroupUpdate` carries it (§13 C-21), so the UI is the oracle. | SS, A11Y, HAR | `reconciliation.mismatch` · — | Q02 | mapped, not executed |

---

## 6. Group PRV — Preview (the R3 simulation-preview scope; E28-T05, E28-S04)

Screen SCR-061. Endpoint `POST /trade-groups/preview` (`orders:write`, no arm token, no
`Idempotency-Key`). The hostile probes of the preview are §10 HOS-05.

<!-- prettier-ignore -->
| Case | Covers | Preconditions | Steps | Expected result | Evidence | Audit · metric | By | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TC-E28-PRV-01 | US-PROF-006 "Fan-out" (the mandatory preview, 24 §9.4 rule 1); E28-S04 "Preview resolves each account by its own profile"; US-PROF-005 "Inactive member" (E28-B excluded) | Core3; Owner; stub wallet equity 10000 | 1. SCR-061: select Core3; enter RI. 2. Capture the preview call. | Three rows, each with its DEMO badge as text: E28-A and E28-C sized as PRO-05 and PRO-07; E28-B excluded with its reason as text. `totals.total_qty` is the sum of the submittable legs (0.416 + 0.078 under the zero-fee overlay; 0.262 + 0.078 at the `compliant` 0.00055), and so are `total_notional_usd` and `total_risk_usd`; the totals line adds an estimated fee; Send names the account count, 2. | HAR, SS, VEC | `tradegroup.preview` · `cv_tradegroup_preview_seconds` observed | Q02 | mapped, not executed |
| TC-E28-PRV-02 | E28-S04 "Preview never places an order" | Core3; Owner; counts of `GET /trade-groups` and `GET /orders`; `LOG` | 1. On SCR-061 change the intent 20 times (price, side, BTCUSDT and ETHUSDT). 2. Call the preview 100 times by API. | No group, leg or order row is created or changed; no exchange call in `LOG` (SR-E28-22: caches only); every answer `200`, or `429` with `Retry-After`; no `Idempotency-Key` ever required. | HAR, LOG, MET | `tradegroup.preview` per call · `cv_tradegroup_preview_total{outcome}` | Q02, Q03 | mapped, not executed |
| TC-E28-PRV-03 | E28-S04 "Preview updates as the intent changes"; E28-S04 "Rate limiting is explained, not silent" | Core3; SCR-061 | 1. Type a new price keystroke by keystroke; time it. 2. Exceed the per-user preview rate. | 1: the preview re-runs within 300 ms of the last keystroke (PA-1); a response for an older intent is discarded, never shown as current. 2: a plain-language wait message with the retry time; the last good preview stays visible; focus does not move. | T, SS, HAR | — · `cv_ui_preview_latency_ms` | Q02, Q03 | mapped, not executed |

---

## 7. Group OVR — Overrides (US-PROF-008; E28-K01, E28-S05)

Screens SCR-061, SCR-114. Endpoints `POST /trade-groups`, `POST /trade-groups/preview`. Each
account's bound profile is the ceiling: an override only narrows, and no leg may exceed the bound
profile's caps and risk budget (ADR-0008 amendment 3, D6, D7; 22:6302-6306; ADR-0040 Decision 1,
proposed until its sign-off on #2701). The widening probes, cap by cap, are §10 HOS-07.

<!-- prettier-ignore -->
| Case | Covers | Preconditions | Steps | Expected result | Evidence | Audit · metric | By | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TC-E28-OVR-01 | US-PROF-008 "Allowed override" | Pair; E28-A on P-RISK, which sizes 0.416 at RI under the zero-fee overlay (§12.6); E28-C on P-PCT, flat, with no open order and no loss today, which sizes 0.078 (V05) | 1. SCR-061: lower E28-A's quantity to 0.300 and raise E28-C's to 0.100 for this ticket; capture the preview call. 2. Submit. 3. Repeat with E28-A at 0.420, inside `max_position_notional_usd` 50000 but above 0.416, and E28-C at its own size. | 1: each row states that it is overridden and names its computed quantity, 0.416 on E28-A and 0.078 on E28-C; the preview admits both legs (`would_submit: true`), E28-C's at `resolved.qty` 0.100, `notional_usd` 6400.0 and `estimated_margin_usd` 640.0. 2: the legs send 0.300 and 0.100, each override audited and journal-tagged (the journal is E41: recorded). The raise stays within P-PCT's caps, the day's room and margin, so it is admitted (22:6302-6306; ADR-0040 (proposed) rows 9 and 10, ADR-0040:189-190, and its scenario, ADR-0040:257-260): a notional of 6400.0 within `max_position_pct_equity`, 100 % of 10000 (rule 1, ADR-0040:109-110); at fee 0, a risk of 60.0 USDT at V05's stop, 63400.0 (128.0 at the 2 % fallback stop), within the day's room of 200 USDT, `max_daily_loss_pct` 2 % of 10000 with nothing lost today or committed (rule 2, ADR-0040:111-113; the ceiling, ADR-0040:86-88); a margin of 640.0 at 10x within 0.98 × the available 10000 (rule 6, ADR-0040:123). 3: `403 risk_limit_breached`, refused whole: a widening override is refused, never clamped (#904 record, ruling 8 (2026-10-25)). Size may rise up to the bound profile's caps and budget (ADR-0040's OPEN-1, resolved, ADR-0040:479-481; §13 C-12), but 0.420 × 120 = 50.4 USDT at the stop is above P-RISK's 50 USDT budget at equity 10000 and fee 0 (rule 2, ADR-0040:111-113). | HAR, SS, AUD | `tradegroup.row_overridden{field, from, to}` per overridden leg, 0.416 to 0.300 and 0.078 to 0.100 (1–2); a refusal row (3) · `cv_override_applied_total{field}` +1 per overridden leg, `cv_override_refused_total{cap}` +1 (3; §13 C-40) | Q02 | mapped, not executed |
| TC-E28-OVR-02 | US-PROF-008 "Forbidden override" | E28-A on P-RISK (leverage 5, `max_leverage_cap` 10) | 1. SCR-061: try to raise E28-A's leverage to 11, by keyboard and by pointer. 2. Preview and submit with `legs[].overrides.leverage` "11", then "6". | 1: the control never accepts 11 and states "capped by profile" as its text and accessible description at its limit; whether that limit is the cap, 10, or the profile's 5 is recorded (§13 C-39). 2: for "11", `403 risk_limit_breached`, refused whole before any leg is sent, with one `errors[]` entry for E28-A naming the leverage override as `field`, `rule: max_leverage_cap` and `limit: "10"` (22:6306-6311; example `tradeGroupWidening`, 22:14881-14884); for "6", below the cap, the answer recorded, not failed, until OPEN-2 settles (§13 C-39). | HAR, SS, A11Y, AUD | a refusal row per refusal · `cv_override_refused_total{cap}` +1 per refusal, its value recorded (§13 C-40) | Q02, X03 | mapped, not executed |
| TC-E28-OVR-03 | US-PROF-008 "Override expiry" | OVR-01 step 1 applied, under its zero-fee overlay | 1. Cancel the ticket (`Esc`); reopen. 2. Apply the overrides again; submit; reopen. | Each time the next ticket shows each profile's value, 0.416 for E28-A and 0.078 for E28-C, and the reset is announced through a polite live region (E28-S05 "Override expiry"; its accessibility notes). | SS, A11Y | — · — | Q02 | mapped, not executed |

---

## 8. Coverage matrix (US-PROF-001..008 × cases)

Every Gherkin scenario of the eight stories, by its verbatim title, against the cases that cover
it; case numbers drop the `TC-E28-` prefix. 25 scenarios, no gap: each has at least one case.

| Story       | Scenario                   | Cases                    | By            |
| ----------- | -------------------------- | ------------------------ | ------------- |
| US-PROF-001 | Create profile             | PRO-01, PRO-02, AX-04    | Q02, X03, Q04 |
| US-PROF-001 | Invalid combination        | PRO-03                   | Q02           |
| US-PROF-001 | Profile in use             | PRO-04                   | Q02           |
| US-PROF-002 | Risk-based sizing          | PRO-05, PRO-06, BND-15   | Q02           |
| US-PROF-002 | Percent-of-equity          | PRO-07                   | Q02           |
| US-PROF-002 | Below minimum lot          | PRO-08, BND-16           | Q02           |
| US-PROF-003 | Allowed                    | SYM-01, AX-03            | Q02, Q04      |
| US-PROF-003 | Server enforcement         | SYM-02, SYM-05, HOS-02a  | Q02, X03      |
| US-PROF-003 | Empty list allows nothing  | SYM-03                   | Q02           |
| US-PROF-003 | All symbols is explicit    | SYM-04                   | Q02           |
| US-PROF-004 | Position size cap          | CAP-01                   | Q02           |
| US-PROF-004 | Concurrent positions cap   | CAP-02                   | Q02           |
| US-PROF-004 | Daily loss cap             | CAP-03, BND-17, BND-18   | Q02, Q03      |
| US-PROF-005 | Create group               | GRP-01                   | Q02           |
| US-PROF-005 | Mixed environments blocked | GRP-02, HOS-04a–d        | Q02, X03      |
| US-PROF-005 | Inactive member            | GRP-03, PRV-01, AX-01    | Q02, Q04      |
| US-PROF-006 | Fan-out                    | FAN-01, PRV-01           | Q02           |
| US-PROF-006 | Partial failure            | FAN-02                   | Q02           |
| US-PROF-006 | Rate-limit budget          | FAN-03                   | Q02           |
| US-PROF-007 | Aggregate view             | GRP-04                   | Q02           |
| US-PROF-007 | Group action               | FAN-04                   | Q02           |
| US-PROF-007 | Divergence warning         | FAN-05                   | Q02           |
| US-PROF-008 | Allowed override           | OVR-01                   | Q02           |
| US-PROF-008 | Forbidden override         | OVR-02, HOS-07a–n, AX-03 | Q02, X03, Q04 |
| US-PROF-008 | Override expiry            | OVR-03                   | Q02           |

Totals: 36 cases (8 PRO, 5 SYM, 3 CAP, 4 GRP, 5 FAN, 3 PRV, 3 OVR, 5 AX — the AX cases are §11.3),
19 boundary entries (§9) and 46 hostile entries (§10). Every case is mapped, not executed, and
BND-19 is also blocked on a live recording (§13 C-04).

---

## 9. Boundary catalogue

Each entry names the constraint or rule it probes; the bounds are the DDL's (21 §3.2.4) and the
recorded instrument rows'. For every entry the issue lists, its numbers equal the DDL's; BND-19
adds the exchange's leverage maximum (§13 C-04). Profile probes POST an alternate on E28-A as the
Owner with a live step-up, from this base: `name` `QA-BND-nn`, `leverage` "5",
`sizing: {mode: fixed_qty, qty: "0.001"}`, `stop_loss: {unit: ticks, value: "1200"}`,
`allowed_symbols: ["BTCUSDT"]`, `risk_caps.max_leverage_cap` "10", `trading_enabled` false, with
the members the row changes. **Accepted:** `201`, the member echoed, the alternate deleted in
teardown (`DELETE` with its `ETag`, `204`). **Refused:** `422 validation_failed` naming the member,
nothing stored (`GET .../profiles` unchanged), and no audit row unless the entry names one (a rule
of shape, which the contract leaves unaudited: 22:15411-15413, §13 C-23). Sizing probes (BND-15a,
BND-16a) are previews on the stub stack, BND-15a under the zero-fee overlay (§12.6). All are
executed by E28-Q02; BND-17 and BND-18 also by E28-Q03; BND-19 waits on a live recording.

<!-- prettier-ignore -->
| Id | Input | Constraint or rule probed | Expected result |
| --- | --- | --- | --- |
| BND-01 | `leverage` "1" | `ap_leverage` (`leverage BETWEEN 1 AND 100`); REST `range` | `201` |
| BND-02 | `leverage` "100" with `max_leverage_cap` "100" | `ap_leverage`; `ap_lev_cap` (cap 1..100, ≥ leverage); second pass `max_leverage` against BTCUSDT's recorded `maxLeverage` 100.00 | `201` |
| BND-03 | `leverage` "101" with `risk_caps.max_leverage_cap: null`, so no `above_leverage_cap` can join (the base cannot trade, so it needs no cap) | `ap_leverage`; REST `range` | `422`, one `errors[]` entry, `field: leverage`, `rule: range`, `limit: "100"`; no audit row, a refusal of shape (§13 C-23) |
| BND-04 | `risk_caps.max_open_positions` 1 | `ap_maxpos` (`BETWEEN 1 AND 50`) | `201` |
| BND-05 | `max_open_positions` 50 | `ap_maxpos` | `201` |
| BND-06 | `max_open_positions` 51 | `ap_maxpos`; the schema's `maximum: 50` | `422` naming the member (the validator's rule name recorded) |
| BND-07 | `slippage_tolerance_bps` 0 | `ap_slip` (`BETWEEN 0 AND 1000`) | `201` (P-NOTIONAL already holds 0) |
| BND-08 | `slippage_tolerance_bps` 1000 | `ap_slip` | `201` |
| BND-09 | `slippage_tolerance_bps` 1001 | `ap_slip`; the schema's `maximum: 1000` | `422` naming the member |
| BND-10 | `risk_caps.max_orders_per_minute` 1 | `ap_opm` (`BETWEEN 1 AND 600`) | `201` |
| BND-11 | `max_orders_per_minute` 600 | `ap_opm` | `201` |
| BND-12 | `max_orders_per_minute` 601 | `ap_opm`; the schema's `maximum: 600` | `422` naming the member |
| BND-13 | `take_profit_ladder` `[{qty_pct: "50", r: "1"}, {qty_pct: "50", r: "2"}]`, summing to exactly 100 | `trg_ap_ladder_sum` (Σ `pct` ≤ 100); REST `ladder_sum`; 24 §9.3.3 | `201`. Rungs are sized only after an entry fills (24 §9.3.3), never in a preview (§13 C-37): V09, P-RISK's own 50/50 ladder at equity 9980, gives 0.207 then 0.208, the last taking the remainder, read in PRO-06 |
| BND-14 | `take_profit_ladder` `[{qty_pct: "50", r: "1"}, {qty_pct: "50.000001", r: "2"}]`, summing to 100.000001 | `trg_ap_ladder_sum`; REST `ladder_sum` | `422`, `rule: ladder_sum` on `take_profit_ladder`; no audit row, a refusal of shape (§13 C-23) |
| BND-15 | Quantity exactly at the minimum lot: a) preview RI on E28-A at equity 30 under the zero-fee overlay (V03); b) `sizing.qty` "0.001" | 24 §9.3 steps 7–8; BTCUSDT's recorded `minOrderQty` 0.001 and `qtyStep` 0.001; second pass `min_order_qty`, `qty_step` | a) submittable, qty 0.001 (0.00125 floored), notional 64.0, risk 0.12; b) `201` |
| BND-16 | One step below: a) preview at equity 20 (V04); b) `sizing.qty` "0.0009" | As BND-15 | a) not submittable, qty 0.000, the minimum 0.001 reported; b) `422`, `min_order_qty` and `qty_step` naming BTCUSDT and its limit, audited `profile.save_refused` (a second-pass refusal) |
| BND-17 | Daily loss exactly at the cap: E28-A (cap the tighter of 1000 and 3 % × 10000, so 300) with today's loss 300.00; then 299.99 | US-PROF-004 "Daily loss cap" (the loss "reaches the daily cap"); the runtime comparison, E28-T04's daily-loss gate: realised plus unrealised loss against the tighter of `max_daily_loss_usd` and `max_daily_loss_pct` × equity; 24 §9.3.2 headroom | At 300.00: entries refused and audited (CAP-03). At 299.99: no cap refusal; the 0.01 USDT room at a 120 USDT stop floors to 0.000, a skip with the minimum named (V10's rule, on Q-03's reading) |
| BND-18 | An intent at 00:00:00 UTC: the cap breached at 23:59:59.999 (exchange time); an entry stamped 00:00:00.000; the same across a ±90 s skew | E28-T04's rollover; SR-E28-29 (an idempotent day key from exchange time); E28 threat model AC-20 | On the half-open reading, pending §13 Q-11, the intent is judged in the new day: the accumulator reset exactly once, the entry admitted unless E39's lockout still stands (recorded); one rollover across the skew (§13 Q-11, C-31) |
| BND-19 | `leverage` "25" with `max_leverage_cap` "25" and `allowed_symbols: ["SOLUSDT"]`: leverage above an allowed symbol's exchange maximum, where that maximum is below 100, as in SCR-131's example, SOLUSDT at most 20x | The second pass's `max_leverage` (`leverageAboveExchangeMax`, 22:15418-15432); SCR-131's validation | `422`, `rule: max_leverage` naming the symbol and its limit, audited `profile.save_refused`. **Mapped, blocked on a live `instruments-info` recording:** every recorded symbol allows 100x, and a capture is never patched (§13 C-04) |

---

## 10. Negative and hostile catalogue

The issue's seven hostile behaviours, each split into the probes that reach it. Each names the
control it probes (the E28 threat model's SR-E28 and PF ids, and its abuse case, so E28-X03 builds
on the same list), the expected refusal and the audit row. M is `manager-with-grants` (trade on
E28-A and E28-C only) and V is `viewer-granted` (view on E28-A); every other probe acts as the
Owner. "Nothing sent" means no order create in `LOG` and no new row in `GET /orders` or
`GET /trade-groups`; "nothing stored" means the resource's `GET`, version and `ETag` are unchanged.

<!-- prettier-ignore -->
| Id | Probe | Control probed | Expected refusal | Audit row | By |
| --- | --- | --- | --- | --- | --- |
| HOS-01a | `POST .../profiles` with `require_native_stop: false` | SR-E28-08, SR-056, C-2.6; PF-T09; AC-01; F6 | `422 validation_failed`, `rule: native_stop_mandatory`; nothing stored | `profile.save_refused` | X03 |
| HOS-01b | `PUT .../profiles/{P-RISK}` with `require_native_stop: false` | As HOS-01a | As HOS-01a | `profile.save_refused` | X03 |
| HOS-01c | A raw payload naming the column, `require_native_sl: false`, on create and on replace | As HOS-01a; `ap_native_sl` holds below | `422`, an unknown member; nothing stored | none: a refusal of shape, though AC-01 expects one (§13 C-23) | X03 |
| HOS-01d | SCR-131's Safety section; a template applied through SCR-132; a profile cloned | SR-E28-08; E28-S01 "The native stop-loss floor cannot be removed" | The control is shown permanently on, with its explanation; no interaction turns it off (SCR-131's typed acknowledgement is §13 C-24) | — | Q02 |
| HOS-01e | `POST /trade-groups`, the preview and `POST /orders` carrying `require_native_stop: false` at the top, in `defaults` or in `legs[].overrides` | SR-E28-05, SR-E28-08; C-2.6 | An unknown member, nothing sent: on `POST /trade-groups` and the preview `422 validation_failed`, as `createTradeGroup` documents (22:6329-6330) and the E28 threat model §10 sets for E28-X03, a `400` (the registry's status) recorded, not failed (§13 C-38); `400 validation_failed` on `POST /orders`, which reads its body after RBAC (24:1670) | `POST /orders`: `orders.submit`, outcome `denied`, code `validation_failed` (24:1673; 22:5538), asserted. The trade-group routes: none, ruling 9's reading of a refusal before authorisation; E28-X03 records whether they read the body before authorisation, which no contract line fixes (§13 C-23) | X03 |
| HOS-01f | `POST /trade-groups/{id}/amend` with `stop_loss: null` on an entry leg, at the top and in `legs` | SR-E28-33; PF-T20; AC-32 | `400 validation_failed`, `native_stop_required`; nothing amended | the refused amend, with a result per leg | X03 |
| HOS-01g | A leg whose stop cannot resolve: `legs[].overrides.stop_loss: {unit: price, value: "64000.0"}` at RI's price | SR-E28-08 (no leg without a resolvable stop) | Refused at validation, never sent; SCR-061 disables Send and names the row (E28-S04) | a refusal row | X03 |
| HOS-01h | `POST /trade-groups/{id}/cancel` without `flatten_filled` on a group with an open leg | SR-E28-33; C-2.6 | `200`; the working orders cancelled, the open leg's stop-loss and take-profits kept | `tradegroup.cancelled`, naming each stop kept | X03 |
| HOS-02a | As M, a crafted order for SOLUSDT on E28-A: `POST /orders`, `POST /trade-groups` and the preview (SYM-02) | SR-054, SR-E28-06, SR-052; O3; PF-T07; AC-02 | `403` before any exchange call (code recorded, §13 C-10); nothing sent; the preview marks the leg `symbol_not_allowed` | `order.refused_by_profile{gate, observed, limit}` | X03 |
| HOS-02b | Pair, SOLUSDT: E28-A does not allow it, E28-C does | SR-054; SR-E28-06; PF-T07 and 24:2434 (one matcher of the symbol lists); 24 §9.4 rule 1 (what is previewed is what is sent) | The preview marks E28-A's leg `symbol_not_allowed` and sizes E28-C's; a submit sends E28-C's leg only | `order.refused_by_profile` for E28-A's leg | X03 |
| HOS-03a | Preview of Core3 with `defaults.sizing: {mode: fixed_qty, qty: "50"}` | SR-052, SR-E28-03, SR-E28-05; F2; PF-T06; AC-03; D6 | `403 risk_limit_breached`, one `errors[]` entry per offending leg, never a leg returned with `would_submit: false` (AC-03 expects the preview to show the policy size: §13 C-11) | a refusal row | X03 |
| HOS-03b | The same as a submit | As HOS-03a | `403 risk_limit_breached`, refused whole; nothing sent | a refusal row | X03 |
| HOS-03c | `POST /orders` on E28-A with `sizing: {mode: fixed_qty, qty: "50"}` | As HOS-03a | `403 risk_limit_breached`; nothing sent | a refusal row | X03 |
| HOS-03d | `POST /orders` with a quantity above `max_order_qty` 100.000 (`"100.001"`) | SR-054 (instrument filters) | `400 lot_size_violation` (`rule: max_order_qty`), or `403 risk_limit_breached` if the profile check runs first (recorded); nothing sent | a refusal row: `orders.submit` with outcome `denied` and its code (24:1673; 22:5538), or the guard's (§11.1) | X03 |
| HOS-03e | A client `profile_snapshot`, `atr`, `risk_checked` or `rule_id` on submit and preview | SR-E28-05; PF-S01, PF-T06; AC-10, AC-14 | `422 validation_failed`, an unknown member, as `createTradeGroup` documents (22:6329-6330) and the E28 threat model expects (AC-10, AC-14; §10, E28-X03's case 10), a `400` (the registry's status) recorded, not failed (§13 C-38); nothing sent | none: a refusal of shape (§13 C-23) | X03 |
| HOS-04a | A definition with E28-A and E28-LIVE-SUB (GRP-02 step 2) | SR-E28-16, SR-E28-31; C-2.11; PF-T16; AC-05 | `400 validation_failed`, `rule: environment_mismatch`; nothing written | a refusal row (§13 C-23) | X03 |
| HOS-04b | Pair updated to add E28-LIVE-SUB (GRP-02 step 3) | As HOS-04a | As HOS-04a; Pair's `ETag` unchanged | a refusal row | X03 |
| HOS-04c | Pair's `environment` changed (GRP-02 step 4) | `trg_tgd_write_once`; SR-E28-16 | `400 validation_failed`, `rule: write_once` | a refusal row | X03 |
| HOS-04d | A preview and a submit with legs on E28-A and E28-LIVE-SUB | SR-E28-16 (re-checked at preview and every send); C-2.11; PF-S03 | Refused whole before any leg is sized; nothing sent; no live host in `LOG` (the answer is undocumented: §13 C-17) | a refusal row | X03 |
| HOS-04e | `PATCH /exchange-accounts/{E28-C}` carrying `environment` | SR-E28-16; `trg_ea_env_write_once`; C-2.11 | Refused, the member unknown; the account unchanged | none: a refusal of shape (§13 C-23) | X03 |
| HOS-05a | A preview body carrying `confirm: true`, `dry_run: false` or `execute: true` | SR-E28-22; PF-D01; AC-23 | `422 validation_failed`, an unknown member, as `createTradeGroup` documents for the body the preview takes (22:6329-6330, 22:12736-12737) and the E28 threat model §10 sets for E28-X03, a `400` (the registry's status) recorded, not failed (§13 C-38); nothing written or sent | none: a refusal of shape (§13 C-23) | X03 |
| HOS-05b | A preview sent with an `Idempotency-Key` and an arm token, twice | SR-E28-22 | Answered as previews; no `Idempotency-Replayed`; nothing written or sent | `tradegroup.preview` per call | X03 |
| HOS-05c | `GET`, `PUT` and `DELETE` on `/trade-groups/preview` | SR-E28-22 | `405` or `404` (recorded); nothing written | — | X03 |
| HOS-05d | 100 previews in one second | SR-E28-22; PF-D01, PF-R05; AC-23 | `429` with `Retry-After` past the per-user rate (§13 C-32); no exchange call in `LOG`; no row | `tradegroup.preview` per answer, `ratelimit.rejected` per `429` | X03, Q03 |
| HOS-05e | As V, a preview with one leg on E28-A, which V may read | SR-E28-22; PF-I03; AC-30 | `403 forbidden` (the preview takes `orders:write`, §13 C-08); no sizing or equity of E28-A in the answer | `rbac.denied` | X03 |
| HOS-06a | As M, `GET .../profiles` and `.../profiles/{P-QTY}` on E28-B; the same with a random account id | SR-E28-21; C-12.4; PF-I06 | `404` for both, the same shape | — (a read) | X03 |
| HOS-06b | As M, a preview with legs E28-A and E28-B; then E28-A and a random id | SR-E28-21, SR-E29-13; F1; PF-I01; AC-06 | `403 account_scope_denied`, identical for both; no sizing, equity or count of E28-B | `rbac.denied` | X03 |
| HOS-06c | As M, a submit with a leg on E28-B | SR-E29-13; F1; PF-E01 | `403 account_scope_denied`, refused whole; nothing sent | `rbac.denied` | X03 |
| HOS-06d | As M, `GET /trade-group-definitions`; `GET .../{Core3}` | SR-E28-21, SR-E28-31; PF-E02 | Pair listed, Core3 (its member E28-B ungranted) absent; `404` for Core3 | — (a read) | X03 |
| HOS-06e | As M, reads of FAN-01's Trio group (a leg on E28-D); a `trade_groups` subscription for E28-A and E28-D, then E28-D alone | SR-E28-21; PF-I02; AC-29 | The group absent from `GET /trade-groups` and `404` by id; the subscription narrowed to E28-A (`sub_ok.effective`), E28-D alone `account_scope_denied`; no frame of the group; never another user's `created_by`, `note` or `client_group_ref` | `ws.subscribe.denied` for each subscription: the narrowed one with reason `narrowed`, E28-D alone with `account_scope_denied` (23 §5.2, §6.2) | X03 |
| HOS-06f | As M with a live step-up, a profile write, a default-binding move and a definition write on E28-A, which M may trade | SR-025, SR-E28-02; D8 (open: §13 Q-14); PF-S02 | `403 forbidden` each (Owner-only; for the definition write, while D8 stands); nothing stored | `rbac.denied` each | X03 |
| HOS-06g | As M, `POST /risk/lockouts/{E28-A}/override` with a fresh `Idempotency-Key` and the mandatory body `{reason: "QA probe"}` (3 to 280 characters) | SR-E28-28; PF-E05; AC-18 | `403`; the lockout stands | `rbac.denied` | X03 |
| HOS-07a | `legs[].overrides.leverage` "6" and "11" on E28-A (P-RISK: 5, cap 10), on preview and submit (`POST /orders` has no leverage member: one sent is refused as unknown) | SR-E28-03, SR-E28-04, SR-053; C-12.5; D6, D7; PF-T03; AC-04 | For "11": `403 risk_limit_breached`, refused whole, nothing sent: above the effective `max_leverage_cap` (ADR-0040 (proposed) row 17, ADR-0040:197). For "6", below the cap: the answer recorded, not failed, until OPEN-2 settles (§13 C-39) | a refusal row per refusal | X03 |
| HOS-07b | `overrides.sizing: {mode: fixed_qty, qty: "0.5"}` (P-RISK sizes 0.416 at fee 0, 0.262 at 0.00055) | As HOS-07a | `403 risk_limit_breached`, refused whole, nothing sent: 0.5 × 120 = 60 USDT at the stop is above P-RISK's 50 USDT budget at fee 0 (ADR-0040 (proposed) rule 2, ADR-0040:111-113) | a refusal row | X03 |
| HOS-07c | `overrides.sizing: {mode: fixed_notional, notional_usd: "60000"}` (cap 50000) | SR-053; AC-04 | `403 risk_limit_breached`, refused whole, nothing sent: a notional above the 50000 cap (ADR-0040 (proposed) rule 1, ADR-0040:109-110); the `rule` `errors[]` names recorded | a refusal row | X03 |
| HOS-07d | `overrides.stop_loss: {unit: ticks, value: "1500"}` (profile 1200) | SR-E28-04 (the stop may not move further from entry) | `403 risk_limit_breached`, refused whole, nothing sent: the stop further from entry than P-RISK's own (ADR-0040 (proposed) rule 4, ADR-0040:118-119) | a refusal row | X03 |
| HOS-07e | `overrides.stop_loss: {unit: ticks, value: "600"}` under risk-based sizing | SR-E28-04; PF-T04; AC-12; ADR-0040 (proposed) row 21; §13 C-39 | Refused whole, `403 risk_limit_breached`, nothing sent: the stop is nearer entry (rule 4 holds), but the size it raises passes only within the caps (row 21, ADR-0040:201). At fee 0, 50 / 60 floors to 0.833, a notional of 53312.0 above the 50000 cap (rule 1); even the 0.781 that cap leaves needs 9996.8 of margin at 5x, above 0.98 × an available margin of at most 10000 (rule 6, ADR-0040:123). The `rule` `errors[]` names is recorded | a refusal row | X03 |
| HOS-07f | `overrides.profile_id` = an alternate of E28-A with leverage 10 and risk 1 % (setup); then E28-C's P-PCT; then a random id | SR-E28-03; PF-T03; AC-11 | The alternate refused whole (`403 risk_limit_breached`), nothing sent, on its risk: its 1 % is a 100 USDT budget at equity 10000, above P-RISK's 50 (ADR-0040 (proposed) row 13, ADR-0040:193); whether its leverage 10, at the cap, is refused too waits on OPEN-2 (§13 C-39), so the `rule` each `errors[]` entry names is recorded. `404 not_found` for the other two, the same answer | a refusal row | X03 |
| HOS-07g | A request member for `max_open_positions`, `max_daily_loss_usd`, `allowed_symbols` or `require_native_stop` | SR-E28-05; PF-T05 | `422 validation_failed`, an unknown member, as `createTradeGroup` documents (22:6329-6330) and the E28 threat model §10 sets for E28-X03, a `400` (the registry's status) recorded, not failed (§13 C-38): no request carries a cap; nothing sent | none: a refusal of shape (§13 C-23) | X03 |
| HOS-07h | `amendTradeGroup` raising an E28-A leg's `qty`, sized at P-RISK's budget, so any raise breaks it (22:6582-6584); moving its stop away from entry; then a smaller `qty` and a tighter stop | SR-E28-33; PF-T20; AC-32 | `403 risk_limit_breached`, nothing amended; the reduction and the tightening `200` | the refused amend with a result per leg | X03 |
| HOS-07i | SCR-114: a personal default leverage of 20 with a 10x cap | SR-E28-03; E28-S05 "Trading defaults cannot exceed the profile ceiling" | Refused with "Your profile caps leverage at 10x", the ceiling shown inline | a refusal row | Q02 |
| HOS-07j | SCR-061: each widening control on E28-A's row (quantity up, leverage up past its cap of 10, stop wider) | SR-E28-03, SR-E28-04; D6; E28-S05 "Forbidden override is disabled, not rejected late" | Disabled with "capped by profile"; the value never accepted (OVR-02); leverage raised from 6 to 10 recorded, not failed (§13 C-39) | — | Q02 |
| HOS-07k | An alternate of E28-A copying P-RISK (§12.3) but also allowing SOLUSDT, named by `overrides.profile_id` on a preview and a submit of RI with `symbol: SOLUSDT` and `defaults.price` "150.000", and by `profile_id` on `POST /orders` RO for SOLUSDT | SR-E28-03, SR-054; PF-T03; AC-11 | Refused: an alternate never relaxes the allowed symbols (`createTradeGroup`), so E28-A's leg is never sent; the preview marks it `symbol_not_allowed`; the submit's and the order's codes recorded (§13 C-10) | `order.refused_by_profile` | X03 |
| HOS-07l | Under CAP-02's setup (E28-C bound to a cap of 3, with three positions open), an alternate of E28-C copying that profile (§12.3) but `max_open_positions` 4, named by `profile_id` on CAP-02 step 1's order (RO for LUNAUSDT) and by `overrides.profile_id` on the same intent as a one-leg submit (RI with `symbol: LUNAUSDT` and RO's price as `defaults.price`), since only a fourth symbol meets the cap | SR-E28-03; PF-T03; AC-11 | The bound 3 applies: refused as CAP-02 step 1 is (`403` on `POST /orders`, a per-leg `risk_limit_breached` on a group; codes recorded); nothing sent | `order.refused_by_profile{gate, observed, limit}`, its `limit` the bound 3 | X03 |
| HOS-07m | Under CAP-03's setup (today's loss on E28-A at 300.00), run before E39's lockout stands, an alternate of E28-A copying P-RISK (§12.3) but `max_daily_loss_usd` 2000 and `max_daily_loss_pct` 5, named on CAP-03 step 1's order and on a one-leg submit of RI | SR-E28-03; PF-T03; AC-11 | The bound applies: the entry refused at today's 300.00, P-RISK's cap on §13 Q-03's reading, where the alternate's would leave 200 of room; nothing sent. Where E39's lockout stands, its refusal shows no cap: the refusing component is named and recorded (§13 Q-11) | `order.refused_by_profile{gate, observed, limit}`, its `observed` and `limit` recorded (§13 Q-15) | X03 |
| HOS-07n | An alternate of E28-A copying P-RISK (§12.3) but `max_position_notional_usd` 100000 and `sizing: {mode: fixed_notional, notional_usd: "60000"}`, named by `overrides.profile_id` on a preview and a submit of RI | SR-E28-03, SR-053; PF-T03; AC-11 | The bound 50000 applies: `403 risk_limit_breached`, refused whole, since the effective notional cap is the lesser of the two (ADR-0040 (proposed) row 29 and rule 1, ADR-0040:209, ADR-0040:109-110); nothing sent | a refusal row | X03 |

R3 gate evidence from this plan: exit criterion #2 (the native-SL invariant by every path) is
HOS-01a to HOS-01h with FAN-01; #3 (fan-out correctness) is covered partially, by FAN-01 at three
accounts where #3 names five, with PA-5 measuring the overhead at one to five; #4 (partial failure)
partially, by FAN-02's one failed leg of three where #4 fails two of five; #10 (RBAC) is sampled by
PRO-02 and HOS-06, the full route × role matrix being E28-X03's.

---

## 11. Audit events, metrics and accessibility

### 11.1 Audit vocabulary

The E28 threat model §8.1, the tickets and `04-security-program.md` §8.2 name these events
differently, and most are not registered yet (SR-E28-20). Until one vocabulary is registered, the
audit step passes when each listed event appears once per causing action under any name in its
row; record which name appeared.

<!-- prettier-ignore -->
| Event (this plan) | Ticket or threat-model name | 04 §8.2 | Registered today |
| --- | --- | --- | --- |
| `profile.created`, `profile.updated`, `profile.deleted` | same (E28-T02) | same | yes (#4087); legacy `profiles.update` kept |
| `profile.bound`, `profile.unbound` (`relaxing` when looser) | same (E28-T02) | same | yes (#4087) |
| `profile.save_refused{reason}` | same (E28-T02) | same | yes (#4087) |
| `auth.step_up_required` | the contract's step-up refusal | none (`auth.stepup.*` records the step-up itself) | yes |
| `tradegroup.created`, `.updated`, `.deleted` (definitions, membership before and after) | same (E28-T05) | `tradegroup.created` | no |
| `tradegroup.preview` | same (E28-T05) | none | no |
| `tradegroup.row_overridden{field, from, to}`, and a row per refused widening | same (E28-S05); a refused widening is `trade_group.override_refused` (21:3596; 20:1474) | none | only `trade_group.override_refused` (#4481) |
| `order.refused_by_profile{gate, observed, limit}` | same (E28-T04); on `POST /orders`, also the route's `orders.submit` with outcome `denied` (24:1673) | `risk.cap_breached` for a cap | no (`orders.submit` is) |
| `orders.submit` with outcome `denied` and its code: a `POST /orders` refusal from RBAC on that is not `rbac.denied` or the gate's, the body's `400` included | the order route (24:1673); the E29 threat model §9.1 | the Orders domain (`order.*`) | yes |
| The expansion: a parent and one child per leg | `tradegroup.created`, `tradegroup.leg.result`; SCR-061's `tradegroup.sent` (a group record plus one per account order) | same | only `trade_group.submit` |
| `tradegroup.partial_failure` | SCR-061 | same | no |
| `tradegroup.amended`, `tradegroup.cancelled{flatten_filled}` | the threat model (E34-S03) | none | no |
| `symbol_permission.changed`, `.bulk_changed`, `.change_refused` | E28-S02 | none | no |
| `rbac.denied`, `ws.subscribe.denied` | the threat model | `authz.denied` | yes |
| `risk.cap_breached`, `ratelimit.rejected`, `reconciliation.mismatch` | 04 | same | no |

### 11.2 Audit events and metrics per scenario

Each refusal from authorisation on in the scenario's cases writes its row, and a refusal of shape
before authorisation, or by a rule of shape of `ProfileRejected`, writes none (§0; §13 C-23);
"refusal row" names the event of §11.1 that fits.

<!-- prettier-ignore -->
| Scenario | Audit events | Metrics |
| --- | --- | --- |
| US-PROF-001 "Create profile" | `auth.step_up_required`; `profile.created`; `profile.bound`, `profile.unbound`; `rbac.denied` per Manager or Viewer refusal | `cv_profile_saves_total{result}`, `cv_profile_save_seconds`, `authz_denied_total` |
| US-PROF-001 "Invalid combination" | none: refusals of shape (§13 C-23) | `cv_profile_validation_failures_total{rule}` |
| US-PROF-001 "Profile in use" | `profile.updated` with before and after, `relaxing` only when a cap loosens or the symbols widen, never for a sizing amount | `cv_profile_saves_total{result}` |
| US-PROF-002 "Risk-based sizing" | `tradegroup.preview` | `cv_sizer_duration_seconds`, `cv_sizer_outcomes_total{outcome,reason}`, `cv_sizer_clamped_total{cap}`, `cv_sizer_stop_fallback_total` |
| US-PROF-002 "Percent-of-equity" | `tradegroup.preview` | as above |
| US-PROF-002 "Below minimum lot" | `tradegroup.preview`; a refusal row for the refused 0.001 submit (§13 C-13) | `cv_sizer_outcomes_total{outcome="skip"}` |
| US-PROF-003 "Allowed" | none (no request is sent) | — |
| US-PROF-003 "Server enforcement" | `order.refused_by_profile` per refusal; `profile.updated` (a matrix deny); `symbol_permission.change_refused` | `cv_risk_guard_refusals_total{gate}` |
| US-PROF-003 "Empty list allows nothing" | `order.refused_by_profile` | `cv_sizer_outcomes_total{reason="symbol_not_allowed"}` |
| US-PROF-003 "All symbols is explicit" | `profile.created`; `tradegroup.preview` | — |
| US-PROF-004 "Position size cap" | `order.refused_by_profile` | `cv_risk_guard_refusals_total{gate}`, `cv_risk_guard_seconds` |
| US-PROF-004 "Concurrent positions cap" | `order.refused_by_profile` | `cv_risk_guard_refusals_total{gate}`, `cv_account_open_positions{account}` |
| US-PROF-004 "Daily loss cap" | `risk.cap_breached`; `order.refused_by_profile` | `cv_risk_guard_refusals_total{gate}`, `cv_account_daily_loss_usd{account}`, `cv_risk_guard_fail_closed_total` (stays 0) |
| US-PROF-005 "Create group" | `auth.step_up_required`; `tradegroup.created` | `cv_tradegroup_members_gauge{group}` |
| US-PROF-005 "Mixed environments blocked" | a refusal row per refused write (§13 C-23) | — |
| US-PROF-005 "Inactive member" | `tradegroup.preview`; the expansion parent and a child per sent leg | `cv_tradegroup_legs_skipped_total{reason}` |
| US-PROF-006 "Fan-out" | the expansion parent and a child per leg | `cv_tradegroup_preview_total{outcome}`, `cv_tradegroup_preview_seconds` |
| US-PROF-006 "Partial failure" | `tradegroup.partial_failure`; a child per leg; `tradegroup.cancelled{flatten_filled}` | `unwind_incomplete_total` (stays 0) |
| US-PROF-006 "Rate-limit budget" | `ratelimit.rejected` when refused | `oms_rate_tokens_available{account,bucket}` |
| US-PROF-007 "Aggregate view" | none (reads) | `cv_tradegroup_ws_frames_total` |
| US-PROF-007 "Group action" | one action with a result per leg | — |
| US-PROF-007 "Divergence warning" | `reconciliation.mismatch` | — |
| US-PROF-008 "Allowed override" | `tradegroup.row_overridden` per overridden leg, a lowered and a raised quantity; a refusal row for a raise past the caps or the budget | `cv_override_applied_total{field}`, `cv_override_refused_total{cap}` |
| US-PROF-008 "Forbidden override" | a refusal row per refused call | `cv_override_refused_total{cap}` |
| US-PROF-008 "Override expiry" | none | — |

Metric labels carry internal account and group ids only (the threat model §8.2, SR-E27-16).

### 11.3 Accessibility acceptance points

The screen catalogue's points as cases that E28-Q04 executes in depth (axe-core, NVDA and
VoiceOver, keyboard-only), following `05-accessibility-standard.md` §3, §4 and §6.2. A state is
never conveyed by colour alone (11 global AC 3).

<!-- prettier-ignore -->
| Case | Covers | Preconditions | Steps | Expected result | Evidence | By | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-E28-AX-01 | US-PROF-005 "Inactive member"; text status chips | Core3 (E28-B not ready); G-CORE3; P-NOTIONAL and P-PCT rows | Read SCR-062, SCR-061 and SCR-130 with a screen reader and in grayscale. | Readiness reads "2 of 3 ready" and E28-B's reason as text; group and leg states are words (`cancelled`, `open`, `rejected`), never a pill alone; each preview row's DEMO badge is text; the `no_symbols` and `all_symbols` flags are text; the partial-failure summary is `role="alert"`. | A11Y, SS | Q04 | mapped, not executed |
| TC-E28-AX-02 | E28-S02 "A symbol with an open position cannot be denied"; matrix cell names | SCR-133; E28-A holds the open BTCUSDT long | Navigate the matrix by keyboard and screen reader; reach the (E28-A, BTCUSDT) cell. | Each cell is a checkbox whose accessible name combines the account and the symbol and states allowed or denied; the locked cell says it cannot be denied because of the open position; row and column headers stay announced and the row and column counts are sane past the rendered window. | A11Y, SS | Q04 | mapped, not executed |
| TC-E28-AX-03 | US-PROF-003 "Allowed"; US-PROF-008 "Forbidden override"; disabled-control reasons | SYM-01 and OVR-02 states; a preview row with no resolvable stop; the matrix's locked cell | Focus each disabled control. | The reason is programmatically associated and announced: "not permitted on this account", "capped by profile", Send's reason naming the row without a stop, the locked cell's reason, the native-stop control's permanent-on explanation. | A11Y | Q04 | mapped, not executed |
| TC-E28-AX-04 | US-PROF-001 "Create profile"; keyboard-only tasks | Owner | Without a pointer: create a profile, apply a template, bulk-edit the matrix, create a group, preview, apply and reset an override. | Every task completes with visible focus and no trap; the step-up dialog traps focus and returns it; no keyboard or screen-reader path skips step-up, the diff summary or the send block (D9: any found is a security finding). | A11Y, SS | Q04 | mapped, not executed |
| TC-E28-AX-05 | E28-S04 "Preview updates as the intent changes"; live updates | Core3 preview open; a readiness change and a preview refresh in flight | Keep focus on a row control while both arrive. | Focus does not move; the readiness change is announced politely once; preview refreshes are throttled, never one announcement per keystroke (05 §6.2). | A11Y | Q04 | mapped, not executed |

---

## 12. Test data appendix

### 12.1 The fixture set (slice A)

The world, the profiles and the vectors are slice A's: `tests/fixtures/e28/README.md` ("The world",
"The vectors") is the source of truth, and this plan copies no value it does not need. It loads into
a clean test database migrated to head with one command, given there under "Loading".

| Handle                      | What it is (slice A's README)                                                          |
| --------------------------- | -------------------------------------------------------------------------------------- |
| E28-LIVE-MAIN, E28-LIVE-SUB | Live main and sub-account; never armed                                                 |
| E28-A                       | Demo main; P-RISK (risk-based, 50/50 TP ladder); holds the open BTCUSDT long           |
| E28-B                       | Demo sub; P-QTY; disarmed by its failing key self-check                                |
| E28-C                       | Demo sub; P-PCT (all symbols but DOGEUSDT)                                             |
| E28-D                       | Demo sub; P-NOTIONAL with the empty allow-list                                         |
| Core3, Pair                 | Definitions: E28-A, B, C (2 of 3 ready) and E28-A, C (2 of 2)                          |
| G-CORE3, G-PAIR             | One BTCUSDT limit buy at 64000.0 fired from each, cancelled unfilled; legs V01 and V05 |
| `fx-e28-owner`              | The Owner who made them; signs in as nobody (its hash verifies no password)            |
| V01 to V14                  | The golden sizing vectors and their hand recomputation                                 |
| Instruments                 | BTCUSDT, ETHUSDT, SOLUSDT, LUNAUSDT, recorded; DOGEUSDT only as P-PCT's denied symbol  |

The matrix's locked cell is (E28-A, BTCUSDT). V14 pins fixed notional with no cap binding:
P-NOTIONAL with `allowed_symbols` `["*USDT"]`, SOLUSDT at 150.000, qty 6.666, notional 999.9, stop
149.500, risk 3.333 and margin 499.95.

### 12.2 Users and keys

| Fixture                  | Role    | Grants                                                                         | Source                                                |
| ------------------------ | ------- | ------------------------------------------------------------------------------ | ----------------------------------------------------- |
| `owner-enrolled`         | Owner   | All accounts; the acting Owner of every case                                   | E09 seed (`qa/plans/e09-auth-rbac-test-plan.md` §6.1) |
| M, `manager-with-grants` | Manager | `trade` on E28-A and E28-C only, set with `PUT /users/{userId}/account-access` | E09 seed plus setup                                   |
| `manager-without-grants` | Manager | None                                                                           | E09 seed                                              |
| V, `viewer-granted`      | Viewer  | View on E28-A                                                                  | Setup (invite, then grant), as E27 §9.1               |

Keys are imported through the API in suite setup, scenario `compliant` of the E27 account pack, for
E28-A, E28-C and, when a case uses it, E28-D. E28-B gets none: its disarm is account-level.

### 12.3 Reference intent, reference orders and profile copies

- **RI**, the reference intent: `POST /trade-groups` or `/trade-groups/preview` with
  `symbol: BTCUSDT`, `side: buy`, `order_type: limit`, `intent: entry`,
  `defaults: {sizing: {mode: profile}, price: "64000.0"}`, the case's `legs`, no stop in the request
  (each profile's stop applies) and, on a submit, a fresh `Idempotency-Key`. At 64000.0 the limit is
  marketable against the corpus's 63110.00, so a submit may fill.
- **RO**, the reference order: E27's reference order (§9.7 of its plan) on the case's account, with
  the case's symbol and `sizing: {mode: profile}`.
- **RR**, the reduce-only order: RO turned into a reduction of the case's open position, with the
  opposite `side`, `reduce_only: true`, `intent: scale_out` (`flatten` for the whole position),
  `sizing: {mode: fixed_qty, qty: ...}` with the case's quantity, no larger than the position, a
  `price` 10 % above the last trade for a sell (below for a buy), on the tick, so the `PostOnly`
  order rests as RO does, and no `stop_loss` or `take_profit`. A reduce-only order that names
  either is `400 validation_failed` / `reduce_only_tpsl`, and a reducing one labelled `entry` is
  `intent_mismatch` (22 `placeOrder`): either answer blocks the case, never passes it.
- **A copy** of a profile: the source's `profile` as `GET` reads it (REST units), posted with
  `POST .../profiles` on the case's account with `is_default: false`, a `name` the account does not
  hold (such as `QA-PRO-06-V09`) and the members the case changes; where the case binds it,
  `PUT .../default-profile` makes it the default, and teardown binds the original back and deletes
  the copy. A verbatim copy is refused: `is_default: true` as `default_has_own_operation`
  (22:3166-3168), and a name the account holds as `409 conflict` (22:3171-3172).

### 12.4 Step-up, idempotency and versions

As E27 §9.4: on `403 step_up_required`, `POST /auth/step-up` with the password, a `totp_gen` code
and the `challenge_id`, then re-send the held request unchanged. The `risk_caps` class has a
5-minute grace, so a case that asserts the challenge starts from a session without a live grant.

### 12.5 Clock

E28-Q02's clock-injection fixture drives BND-17, BND-18, CAP-03 and FAN-05; the stub's server time
follows it. No case waits on the wall clock in automation.

### 12.6 Setup the cases need beyond slice A (owed, §13 Q-12)

Stub wallet equities of 20, 30, 4000, 9980 and 10^9 USDT (BND-15, BND-16, PRO-06, PRO-08); the
**zero-fee overlay**, a taker fee of 0 beside the `compliant` scenario's 0.00055
(`_base/fee_rate.json`, V02's), for every vector but V02, as their own fee is 0 (slice A
Q1): the risk-based vectors' figures depend on it (V01, V03, V09, V13), and V10's would on §13
Q-03's contested reading; and for the cases that quote them (PRO-05's fee-0 branch, PRO-06,
PRV-01, OVR-01, OVR-03, BND-15a, HOS-07b, HOS-07e), pending §13 Q-01; a full fill of V09's entry
at 64000.0 on E28-C (PRO-06); a 0.4 BTC BTCUSDT position on E28-C (CAP-01); positions on BTCUSDT,
ETHUSDT and SOLUSDT on E28-C (CAP-02, HOS-07l); today's realised loss at the cap on E28-A (CAP-03,
BND-17, HOS-07m) and of 248 USDT on E28-C (V10); an entry rejected by the exchange for E28-D's key
(FAN-02); an open Trio group with every leg filled (FAN-04, FAN-05), and one fired with RI whose
E28-D leg is only partly filled, its remainder working (GRP-04); a position changed outside the
app (FAN-05); the ATR warm-up state (PRO-06, V06); and the stub serving E28-A's seeded position,
without which a boot reconcile would flatten it.

---

## 13. Documentation conflicts found

Two kinds of row, each numbered and citing its source; both are spec findings, recorded here and
not resolved here, except the rows marked **Ruled**, which carry the orchestrator's ruling or
ADR-0040's, proposed until its sign-off on #2701.
**Q-rows** are questions proposed to the named ticket's owner: they move with that ticket when it
lands. **C-rows** are conflicts between documents. Cases name the source they follow; a defect
against a row cites it. "#904 record, ruling N (date)" is ruling N of
[#904's record comment](https://github.com/CandleViewer/CandleViewer/issues/904#issuecomment-6391566939),
and a linked issue number is the pinned comment that carries a ruling to its ticket. "Slice A Qn"
is reading Qn of slice A's `tests/fixtures/e28/sizing_recomputation.md` (Q1 to Q7). Q-01 to Q-09
are proposed to E28-T03's owner under #904 record, ruling 4 (2026-10-24), as listed on
[#907](https://github.com/CandleViewer/CandleViewer/issues/907#issuecomment-6391264942).

### 13.1 Q-rows: proposed questions

<!-- prettier-ignore -->
| Id | To the owner of | Question | Source | Cases |
| --- | --- | --- | --- | --- |
| Q-01 | E28-T03 | The taker fee: 24 §9.3 step 5 needs the taker fee, which the sizer's documented inputs do not carry, and T03 AC 1's 0.416 holds only at a zero fee. The vectors take the fee as an input: 0, or 0.00055 in V02. Which fee does the sizer read, and is AC 1 stated at fee 0? | slice A Q1; V01, V02 | PRO-05 |
| Q-02 | E28-T03 | The leverage cap: §9.3.2 clamps at `max_leverage_cap` with no formula. The vectors read `qty ≤ max_leverage_cap × equity / price`, which is nearly dead: since `leverage ≤ max_leverage_cap` and available margin ≤ equity, a quantity the cap cuts fails the 0.98 margin check unless the floor removes more than 2 %. Confirm the formula, or what the cap means | slice A Q2; V13 | PRO-06 |
| Q-03 | E28-T03 | The other caps: `max_position_pct_equity` bounds the notional; the day's room is the tighter of `max_daily_loss` and `max_daily_loss_pct × equity`, less today's loss; a limit order reads `max_order_qty`, a market order `max_mkt_order_qty`. The room is measured at the stop without fees, which step 5's own reasoning contests (24:2553-2554: the real loss at the stop includes both taker fees); no expected value depends on it while each vector runs at its own fee, 0 for all but V02 (§12.6): at 0.00055, V10's room would give 2 / 0.665 → 3.007, not 4.000 | slice A Q3, which marks it contested; V05, V10, V11 | PRO-06, BND-17 |
| Q-04 | E28-T03 | Margin: §9.3.2 lists "available margin × 0.98" as the last clamp (24:2580), while step 8 and T03 AC 9 make it a failure (24:2570-2571). The vectors fail it. **Ruled (2026-10-24):** a failure, never a silent clamp; §9.3.2's wording is C-34 | slice A Q4; #904 record, ruling 4 (2026-10-24); pinned on [#907](https://github.com/CandleViewer/CandleViewer/issues/907#issuecomment-6391264942); V13 | PRO-06 |
| Q-05 | E28-T03 | T03 AC 2's notional 5000 and initial margin 500 are the figures before the floor; the sized leg's are 4992.0 and 499.2 | slice A Q5; V05 | PRO-07 |
| Q-06 | E28-T03 | The take-profit ladder: sized on a full fill; a rung that floors to 0 is unspecified, so V03 asserts no ladder; a TP price's rounding direction is unspecified (every TP price in the vectors lands on a tick); and so is its base: §9.3.3 computes an `r_multiple` take-profit "from the resolved stop distance" (24:2584) without saying from the reference price or the fill price. The vectors take the reference (slice A R13), and PRO-06 fills V09's entry at its reference price, 64000.0, where the two agree | slice A Q6 and R13; V03, V09 | BND-13, PRO-06 |
| Q-07 | E28-T03 | What a skip or a failure reports: 24 §9.3's skip and failure outcomes carry only a code (24:2569, 24:2571), and T03 AC 3 asks only that "the minimum is reported". The vectors pin the floored `qty`, and a notional on V08 and V13 | slice A Q7 | PRO-06, PRO-08 |
| Q-08 | E28-T03 | The shared vector set has none for: a binding `max_position_notional` (T03 AC 8's own example) or `max_position_pct_equity`; `symbol_denied`; `profile_disabled`; a market order (`max_mkt_order_qty`, and its reference price: C-35); a short with a ticks or ATR stop; a plain insufficient-margin case with low available margin and no cap. Proposed: T03's set covers them | slice A's README, "The vectors" (what is not covered) | PRO-06 |
| Q-09 | E28-T03 | 1R: the vectors take T03's notes, 1R = qty × stop distance without fees. What figure does "the implied risk ... in R" (US-PROF-002) show? | slice A's R14 (`sizing_recomputation.md`) | PRO-05 |
| Q-10 | E28-T05 | Readiness: E28-B is disarmed at account level (`trading_enabled` false, `policy_disarm_code` `key_ip_whitelist_mismatch`) rather than by a seeded broken key, because a boot it bricks is no fixture. Proposed: T05 reads it as "not ready: key self-check failed", and names the preview's `rejection.code` for it (`key_invalid` is the nearest value) | #904 record, ruling 6 (2026-10-24); slice A's README ("The failing self-check") | GRP-03, PRV-01 |
| Q-11 | E28-T04 | The day boundary: is 00:00:00.000 on exchange time the first instant of the new day? And once E39's lockout stands, is a refused entry `risk_limit_breached`, the gate's `trading_disabled` or E28-T04's own `account_locked_out` (with `account_disabled` for a disabled account; neither is in the registry, C-10)? | this plan; E28-T04's error codes | CAP-03, BND-18 |
| Q-12 | E28-Q02 | The setup slice A does not seed (§12.6), the zero-fee overlay and the filled Trio group included: proposed, E28-Q02 builds it with #2893's stub | this plan | §12.6 cases |
| Q-13 | E28-T03 | Take-profit units: 24 §9.3.3 (24:2584) resolves only an `r_multiple` take-profit and the ladder, while `tp_offset_unit` also takes `ticks`, `percent` and `atr` (24:2410; REST `take_profit.unit`). How are those resolved, and to which side of a tick? No vector pins one: V10's and V14's 100-tick take-profits are left unpinned for this reason | slice A Q6; V10, V14 | PRO-06 |
| Q-14 | the Owner | Decision D8, open: group definitions are Owner-only "until the Owner decides otherwise, before E28-T05 merges" (the E28 threat model §4.7; 22:6148-6149, queued on #2701). The plan assumes Owner-only. Does it stand? A change flips HOS-06f's definition write and GRP-01's step-up | the threat model §4.7; 22:6148-6149 | GRP-01, HOS-06f |
| Q-15 | E28-T04 | The guard's observables. A cap breach "raises a `warning` notification", and SCR-014 streams "risk events" from the `alerts`, `rules`, `orders` and `system` topics, with `GET /notifications` as their history (14:379, 14:390), but no line says which topic or `kind` carries the warning, or how many: the route unions `alert_deliveries`, `rule_events`, `order_events` and `system_events`, whose live equivalents arrive on those four topics, and names no cap-breach source (22:12452-12454), while its `kind` takes `risk` (22:12472, 22:21067), for which none of the four sources is named. And `order.refused_by_profile{gate, observed, limit}` carries "the gate that fired, the observed value and the cap", but no line says which cap `limit` holds for the daily-loss gate, whose cap has two members, or in which units: `max_daily_loss_usd` (1000 USDT on P-RISK), `max_daily_loss_pct` (3 %), that percentage of equity (300 USDT at 10000), or the tighter of the two (300 USDT, §13 Q-03's reading). Proposed: T04, or E40 for the notification, names each | E28-T04's Observability and its Scope ("Audit on every refusal"); 22:12452-12454, 22:12472, 22:21067; 14:379, 14:390 | CAP-03, HOS-07m |

### 13.2 C-rows: conflicts between documents

<!-- prettier-ignore -->
| Id | Conflict | Plan follows | Cases |
| --- | --- | --- | --- |
| C-01 | #904 asks for "one main, five subs; four demo, two live", which `ea_parent_shape` and `trg_ea_env_parent` (21 §3.2.1) make impossible: a sub-account sits in its parent's environment, and the ticket text predates the trigger. **Ruled (2026-10-24):** a live main and a live sub, plus demo main E28-A with demo subs E28-B, C and D. A Deviation from #904's text (#904 record, ruling 1 (2026-10-24)) | the ruling | all |
| C-02 | #904's instrument snapshot names DOGEUSDT, which no capture in the repository holds. **Ruled (2026-10-24):** the default stands: LUNAUSDT is the recorded fourth symbol and DOGEUSDT appears only as P-PCT's denied symbol, where no instrument row is read; a real DOGEUSDT capture with the recorder tool is a follow-up (C-13.5), never a patched or invented row (#904 record, ruling 2 (2026-10-24)) | the ruling; SOLUSDT stands in for the story's DOGEUSDT (C-36) | SYM-01, SYM-02 |
| C-03 | #904 asks for "real" tick, lot, min-notional and max-leverage values, but the only capture, `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`, is "documented-shape (exception #1778 A)" per its `manifest.json`, not a live recording; a live `instruments-info` recording is a follow-up beside DOGEUSDT's. **Ruled (2026-10-24):** the capture stands as documented-shape, and the live recording, with DOGEUSDT's, is one follow-up, below (#904 record, ruling 3 (2026-10-24)) | the capture, labelled as documented-shape (slice A's README) | BND-02, BND-15, BND-16, BND-19 |
| C-04 | The SOLUSDT 20x example of SCR-131, E28-T02, E28-S01 and the contract (`leverageAboveExchangeMax`) against the capture, where SOLUSDT, like every recorded symbol, allows 100x. **Ruled (2026-10-25):** never patch a capture (#904 record, ruling 10 (2026-10-25)). Case by case: BND-02 tests the DDL's bound at 100, which the capture's BTCUSDT maximum equals, so it needs no exchange refusal and runs on the capture; BND-19 and charter 2's 20x journey test the refusal above a lower exchange maximum, so they are mapped, blocked on a live `instruments-info` recording; OVR-02, HOS-07a, HOS-07i and HOS-07j test the profile's cap and reach it through `max_leverage_cap` 10, below the exchange's 100x | the ruling | BND-02, BND-19; OVR-02, HOS-07a, HOS-07i, HOS-07j; charter 2 |
| C-05 | The spelling of the margin failure: 24 §9.3 step 8 and the preview's `rejection.code` (22) write `insufficient_margin`; E28-T03's AC and 24 §9.5.1's "Skips vs failures" paragraph (which T03 cites as §9.6) write `INSUFFICIENT_MARGIN`. **Ruled (2026-10-24):** keep the lower case, 22's problem-code convention (#904 record, ruling 5 (2026-10-24); pinned on [#907](https://github.com/CandleViewer/CandleViewer/issues/907#issuecomment-6391264942)) | `insufficient_margin` | PRO-06 |
| C-06 | #904's link `24-internal-schemas.md#5-profile-model` points at §5, the volume-profile and TPO model; the account profile is §9.2 | §9.2 | — |
| C-07 | #904's path list omits `/trade-group-definitions` (US-PROF-005's named groups, ADR-0008 amendment 2) and `/exchange-accounts/{accountId}/default-profile`; E28-T05's scope still calls `POST /trade-groups` "definition/creation" | the contract | GRP-01 to GRP-03 |
| C-08 | The preview's permission: E28-T05 says `orders:read`; the contract and ADR-0008 amendment 2 settle SR-E28-22's "one permission" as `orders:write`, so a Viewer gets `403`; the threat model's AC-30 still waits on "the P-1 decision" | the contract | HOS-05e |
| C-09 | The empty allow-list allows nothing in US-PROF-003, D11, the contract and the DDL; E28-T04's scope and its AC "Empty allow-list permits every listed USDT perp", and E28-S01's AC that flags an empty list as allowing all symbols, read it as "all". **Ruled (2026-10-25):** an empty allow-list allows nothing and the check fails closed; E28-T04's AC and E28-S01's text are wrong (#904 record, ruling 7 (2026-10-25); pinned on [#908](https://github.com/CandleViewer/CandleViewer/issues/908#issuecomment-6391265282) and [#971](https://github.com/CandleViewer/CandleViewer/issues/971#issuecomment-6391265635)) | US-PROF-003; a build that permits is P0 | SYM-03 |
| C-10 | Refusal codes: the registry and `placeOrder` answer a non-allowed symbol with `403 risk_limit_breached`; E28-T04 and the threat model's AC-02 expect `403 profile_forbidden`, which the registry lacks; T04 maps a cap breach to `422 risk_limit_breached` (the registry's status is 403), and lists `account_locked_out` and `account_disabled`, which the registry lacks too; E28-T02's AC writes `412 precondition_failed` where the contract has `412 version_conflict` | the registry; the code recorded | SYM-02, CAP-01, CAP-03, PRO-04 |
| C-11 | Clamp or refuse: the contract, ADR-0008 amendment 3 and the threat model's D6 refuse a widening submitted value whole with `403 risk_limit_breached`; E28-S05's AC "clamps ... proceeds", E28-X03's cases 3 and 4 "clamped", SR-052's "clamped or rejected" and 04's F2 "clamped hint" clamp it; the threat model's AC-03 expects the preview to show the policy size, where the contract refuses the preview whole. **Ruled (2026-10-25):** a widening value is refused, never clamped (#904 record, ruling 8 (2026-10-25)) | the ruling, as the contract | HOS-03, HOS-07 |
| C-12 | US-PROF-008 "Allowed override" raises size within the risk cap; the contract's later-narrows rule (SR-E28-04) lets no quantity rise above the bound profile's. **Ruled (2026-10-25):** a widening override is refused, never clamped; the story's "raise size" collides with later narrows, and the E28-K01 ADR decides that collision, a spike input on #968 (#904 record, ruling 8 (2026-10-25)). **Ruled by ADR-0040, proposed until its sign-off on #2701 (ADR-0040:3-4):** OPEN-1 is resolved, so size may rise up to the bound profile's caps and is refused above them (R rules 1 and 2; ADR-0040:479-481), the ceiling being those caps and the risk budget (ADR-0040:83-85); since #4474, 22 reads "may not exceed the bound profile's caps and risk budget" (22:6302-6306; 24:2582). OVR-01 raises E28-C's P-PCT leg within them, from 0.078 to 0.100, and it is admitted (rows 9 and 10, ADR-0040:189-190; the scenario at ADR-0040:257-260); its raise of E28-A's leg breaks P-RISK's budget, at which P-RISK sizes | ADR-0040: a raise admitted within the caps and the budget (OVR-01 steps 1 and 2) and refused only above them; OVR-01 step 3 refused by the budget (rule 2, ADR-0040:111-113) | OVR-01 |
| C-13 | US-PROF-002 "Below minimum lot" and E28-S01 offer the minimum as a one-click choice, but where the minimum risks more than the budget (V04: 0.12 USDT against 0.10) the later-narrows rule refuses it; SCR-061 instead excludes a below-minimum row. **Ruled (2026-10-25):** a widening override is refused, never clamped; the one-click minimum collides with later narrows, and the E28-K01 ADR decides that collision, a spike input on #968 (#904 record, ruling 8 (2026-10-25)). **Ruled by ADR-0040, proposed until its sign-off on #2701 (ADR-0040:3-4), rule 5:** a minimum order that breaks rule 1 or 2 "is refused with its reason (coordinator ruling: a one-click minimum above the budget is refused, never rounded up; #904 QA plan (V04))" (ADR-0040:120-122); its scenario: "the ticket does not offer the minimum as a one-click choice", states the minimum's risk against the budget, and "a submit of 0.001 BTC is refused 403 risk_limit_breached and audited, never rounded up" (ADR-0040:268-273) | ADR-0040's rule 5: no one-click offer, the reason stated, `403 risk_limit_breached` for 0.001 | PRO-08 |
| C-14 | Skips: 24 §9.3, E28-T03 and E28-T05 skip a leg as `below_min_notional`, `symbol_denied` or `profile_disabled`, but the preview's `rejection.code` has none of these; no REST or WS leg status is `skipped`, and `totals` carry no skip count (24 §9.1 counts skips only in an aggregate it never stores) | the observable surface; the code recorded | PRO-06, PRO-08, GRP-03 |
| C-15 | Readiness ("2 of 3 ready") is in US-PROF-005, SCR-062, E28-T05 and E28-S03, but `TradeGroupDefinition` and `TradeGroupUpdate` carry no member for it; the preview's `accounts_submittable` is the nearest | the UI for the text, the preview for the count | GRP-03 |
| C-16 | SCR-062, E28-T05 and E28-S03 refuse a definition whose members share no symbol, but `createTradeGroupDefinition` documents no such refusal; a definition holding E28-D, which allows no symbol, probes it | SCR-062; the API answer recorded | charter 3 |
| C-17 | A trade-group leg on an account of another environment: the profile routes answer `404`, but `createTradeGroup` and `previewTradeGroup` document no answer, though SR-E28-16 re-checks the environment at preview and every send | refused whole with nothing sent; the answer recorded | HOS-04d |
| C-18 | US-PROF-006 "Rate-limit budget" queues per account with the delay shown; 24 §9.4 refuses the whole group before the first send (`RATE_BUDGET_EXCEEDED`), the preview marks `rate_budget_exhausted`, E28-T04 returns `rate_budget_exhausted` with a retry time | no request dropped silently; which path ran recorded | FAN-03 |
| C-19 | US-PROF-006 "Partial failure", SCR-061 and ADR-0008 rule 5 offer a per-leg retry, but no route takes one; "flatten group" is `cancelTradeGroup` with `flatten_filled`. **Ruled (2026-10-25):** a contract gap, which lands contract-first with the ticket that owns the route or field (#904 record, ruling 11 (2026-10-25); pinned on [#909](https://github.com/CandleViewer/CandleViewer/issues/909#issuecomment-6391266095) and [#999](https://github.com/CandleViewer/CandleViewer/issues/999#issuecomment-6391266457)) | the contract; the retry recorded | FAN-02 |
| C-20 | US-PROF-007 "Group action" closes 50 % of each account's position, but no trade-group route takes a percentage close: `cancelTradeGroup` with `flatten_filled` closes whole legs, though 24 §9.6 names "Close group". Per position, `closePosition` (`POST /positions/{positionId}/close`, 22:6942-6947) does take `pct`, but a group close built from it is one call per leg, the UI looping over the legs. SCR-062 names no percentage-close control; the pattern it sets is Flatten-group's, which "issues one backend command that fans out server-side - the UI never loops client-side over legs" (14:1445), as 24 §9.6 fans out group-level actions "the same way as entries". The gap is a trade-group-level percentage close. **Ruled (2026-10-25):** a contract gap, which lands contract-first with the ticket that owns the route or field (#904 record, ruling 11 (2026-10-25); pinned on [#909](https://github.com/CandleViewer/CandleViewer/issues/909#issuecomment-6391266095) and [#999](https://github.com/CandleViewer/CandleViewer/issues/999#issuecomment-6391266457)) | the story; the calls the UI makes recorded | FAN-04 |
| C-21 | US-PROF-007 "Divergence warning" has no field in `TradeGroup` or `TradeGroupUpdate`. **Ruled (2026-10-25):** a contract gap, which lands contract-first with the ticket that owns the route or field (#904 record, ruling 11 (2026-10-25); pinned on [#909](https://github.com/CandleViewer/CandleViewer/issues/909#issuecomment-6391266095) and [#999](https://github.com/CandleViewer/CandleViewer/issues/999#issuecomment-6391266457)) | the UI | FAN-05 |
| C-22 | US-PROF-004 "Position size cap" and E28-T04 state the cap in BTC ("0.5 BTC (current 0.4)"); a profile caps position by USDT notional or percent of equity only | the story's numbers, translated at the mark price; the units recorded | CAP-01 |
| C-23 | Audit of refusals: #904 wants every refusal audited (with 11 global AC 1 for RBAC and 04 §8.3 rule 5 for denials), but `ProfileRejected` audits only `native_stop_mandatory`, `above_leverage_cap`, `cap_unbounded` and second-pass refusals, so `range`, `ladder_sum`, `required`, `stop_defines_r` and an unknown member are not audited; the threat model's AC-01 expects even a raw payload audited; and a refused definition write has no named event. **Ruled (2026-10-25):** a shape refusal (a schema 400 or 422 before authorisation) is not an audited action under C-2.9, so "every refusal produces an audit row" means refusals from authorisation on (#904 record, ruling 9 (2026-10-25)); the definition write's event name stays open. Applied: `POST /orders` reads its body after RBAC (24:1670) and audits that refusal as `orders.submit` (24:1673), so its row is asserted; the profile routes keep the contract's unaudited rules of shape (22:15411-15413), though their writes are path-gated, a Manager meeting the step-up and then `403 forbidden` (22:3164-3165); no contract line fixes that order for the trade-group routes or `PATCH /exchange-accounts`, so ruling 9's reading stands there and E28-X03 records it (HOS-01e, HOS-03e, HOS-04e, HOS-05a, HOS-07g) | the ruling: the contract's audited set asserted, no row for a refusal of shape; the definition write's row recorded; `POST /orders`' row asserted | PRO-03, GRP-02, BND-03, BND-06, BND-09, BND-12, BND-14, HOS-01c, HOS-01e, HOS-03e, HOS-04e, HOS-05a, HOS-07g |
| C-24 | SCR-131 lets the mandatory-stop flag be disabled with a typed acknowledgement; C-2.6, the contract (`require_native_stop: const true`), SR-E28-08 and E28-S01 make it permanent | C-2.6 | HOS-01d |
| C-25 | Fan-out time: US-PROF-006 says submission p95 ≤400 ms for 5 accounts; SCR-061 and ADR-0008 say ≤1.5 s; 06 §5.2 bounds the backend-added overhead at ≤50 ms + ≤10 ms per additional account, which #904 writes per account. E28-Q03 lists the overhead in its notes but sends fan-out load to E34; E34-Q03 measures it. **Ruled (2026-10-25):** ADR-0008's ≤1.5 s wins over the story's 400 ms, and E34-Q03 measures it with the overhead (#904 record, ruling 12 (2026-10-25)) | the ruling: ≤1.5 s (PA-7) and the overhead (PA-5), both by E34-Q03 | FAN-01 |
| C-26 | Story references: SCR-062's audit line cites "US-GRP-011..013" (11 has no GRP domain) and its data names `/trade-groups` for definitions; 18 §2.3 maps US-PROF-005 to SCR-061 only, although SCR-062 edits groups; SCR-131's audit line cites US-PROF-003..006, its stories line US-PROF-001..004 | the stories in 11 | GRP group |
| C-27 | E28-K01 names its override ADR "ADR-0016", and E28-S05 cites "the override decision table from ADR-0016", but ADR-0016 is the statechart runtime. The override ADR is ADR-0040, proposed until its sign-off on #2701 (ADR-0040:3-4), whose numbering note records the ticket's ADR-0016 as taken (ADR-0040:14) | ADR-0040 | OVR group |
| C-28 | The shared vectors: SR-E28-09 and E28-T03 name `tests/golden/sizing/e28_vectors.json` (T03: at least 40 cases); #904 and slice A ship `tests/fixtures/e28/golden_sizing_vectors.json` (14 vectors) | slice A's file | PRO-05 to PRO-08 |
| C-29 | `updateAccountProfile` keeps the previous version "readable as a revision" and E28-T02's AC reads it "through the revisions projection", but no route reads a revision and the REST leg has no `profile_version` | unchanged leg values; the journal is E41's | PRO-04 |
| C-30 | SCR-133 and E28-S02 refuse denying a symbol with an open position (`symbol_permission.change_refused`), but the matrix writes through `updateAccountProfile`, which documents no such refusal | the screen; the API answer recorded | SYM-05 |
| C-31 | The daily rollover: E28-T04 rolls over at 00:00 UTC "configurable per deployment"; SR-E28-29 and AC-20 key the day on exchange time | exchange time | BND-18 |
| C-32 | The preview's per-user rate: 20 per second in E28-T05, 5 per second in E34-S01; the threat model's PF-D01 asks for one value | the `429` and its `Retry-After` recorded | HOS-05d |
| C-33 | `GET /me/limits` answers `RiskCaps` with `max_open_positions` 0..100 and the `max_consecutive_losses` and `lockout_minutes_after_breach` members that ADR-0008 amendment 1 removed from the profile; the DDL and `ProfileRiskCaps` bound it 1..50 | the DDL | BND-04 to BND-06 |
| C-34 | Margin: 24 §9.3.2 lists "available margin × 0.98" as the last clamp (24:2580), while §9.3 step 8 (24:2570-2571) and E28-T03 AC 9 make it a failure. **Ruled (2026-10-24):** a failure, never a silent clamp; the §9.3.2 text fix rides E28-T03's contract-first PR (#904 record, ruling 4 (2026-10-24); pinned on [#907](https://github.com/CandleViewer/CandleViewer/issues/907#issuecomment-6391264942)) | the ruling: `insufficient_margin` (V13) | PRO-06 |
| C-35 | A market order's reference price: E28-T03's notes take "the current mark price for market orders"; 24 §9.3 step 2 (24:2532) takes the order's price, else the ticker's mid, else its last price, and 24:2576 answers a symbol whose ticker is stale with `503 exchange_unavailable` | the reference price each leg reports, recorded; the hand recomputation uses it | FAN-01 |
| C-36 | US-PROF-003's DOGEUSDT, asserted on SOLUSDT. Ruling 2 keeps DOGEUSDT where no instrument row is read, but no observable path refuses before one is: 24 §9.4 loads "profiles + wallets + instrument" before the per-account loop (24:2598), E28-T03 takes the instrument snapshot "once per fan-out", E28-T05's preview loads it before the sizer runs, and E28-T04's guard sits "between validation and fan-out", whose validation holds price and quantity to the instrument (22 `placeOrder`). So an unrecorded DOGEUSDT would not isolate the allow-list. The story's mechanism is a symbol missing from the allow-list ("not on account B's allowed list"), which is E28-A without SOLUSDT; E28-C's DOGEUSDT is a `blocked_symbols` entry, the separate `symbol_denied` branch, so DOGEUSDT is only sent there and its answer recorded. Applies #904 record, ruling 2 (2026-10-24): SOLUSDT stands in wherever an instrument row is read; a live DOGEUSDT recording is the follow-up below | SOLUSDT on E28-A, asserted; DOGEUSDT on E28-C, recorded | SYM-01, SYM-02, HOS-02a, HOS-02b, HOS-07k |
| C-37 | What a sized leg shows: E28-T05's preview returns per-leg `take_profits` and a `status` of `ready`, `warn`, `skipped` or `blocked`, and E28-T03's explanation holds the implied risk in R, the rounding delta and the rules that fired; but `TradeGroupPreview` (22:21359-21404) and `ResolvedLegParams` (22:18543-18576) hold one `take_profit_price`, no ladder and no `stop_fallback` flag, with the explanation only as the `sizing_explanation` string. So a ladder's rungs are observable only as the take-profit reduce-only orders after the entry fills (24 §9.3.3), and `stop_fallback` only as `cv_sizer_stop_fallback_total` | the observable surface: the fields, the orders after a fill and the metric; `sizing_explanation` recorded | PRO-05 to PRO-07, BND-13 |
| C-38 | The status of an unknown member on the trade-group routes: the registry gives `validation_failed` `400` (22:499-501), and `UnprocessableEntity` says "the order routes answer `validation_failed` with `400`" (22:15535-15537); but `createTradeGroup`'s body "refuses any member it does not declare (`422 validation_failed`)" (22:6329-6330; `CreateTradeGroupRequest` sets `additionalProperties: false`, 22:18501), the preview takes that body "under the same rules" (22:12736-12737), and the E28 threat model expects `422`: AC-10 and AC-14, and its §10 row for E28-X03, whose "case 10 must expect 422 for a client `profile_snapshot`" | `createTradeGroup`'s documented `422`, as E27's plan takes each operation's documented status (its §10 DC-11): `validation_failed` and nothing sent asserted; the status recorded, and a `400` not failed, until the row settles | HOS-01e, HOS-03e, HOS-05a, HOS-07g |
| C-39 | Raising a value within its cap. 22 read "quantity, notional, leverage, margin and risk at the stop may not rise" until #4474 reworded it to "may not exceed the bound profile's caps and risk budget" (22:6302-6306; 24:2582; the amend's, 22:6582-6584), and the E28 threat model's AC-12 still reads so for a tighter stop under risk-based sizing: "Refused when quantity, notional, margin or risk at the stop rises". ADR-0040, proposed until its sign-off on #2701, rules as 22 now reads: row 10 lets a size be raised within R (ADR-0040:190), rule 2 holds the risk at the stop within the budget (ADR-0040:111-113), row 21 lets a tighter stop raise a risk-based size only within the caps (ADR-0040:201), and row 17 lets leverage rise up to the effective `max_leverage_cap`, the stop strictly inside the liquidation estimate (ADR-0040:197; rule 3, ADR-0040:114-117, as amended, ADR-0040:138-139). #2635's comparator follows the ADR (#4481), but OPEN-2 is open: unless the Security engineer confirms the estimate's source, row 17 narrows to `<= B.leverage` (ADR-0040:482-488). So P-RISK's leverage raised from 5 to 6, under its cap of 10, which OVR-02 and HOS-07a expected refused under SR-E28-04, may be admitted. HOS-07f's alternate raises leverage to 10, at the cap, so its refusal rests on its 1 % risk, a 100 USDT budget against P-RISK's 50 (row 13, ADR-0040:193), not on its leverage, which OPEN-2 leaves open; HOS-07e, which cites AC-12, is refused under either reading | ADR-0040: a size raise admitted within the caps and the budget (OVR-01's on E28-C) and refused only past them; leverage "11" refused, asserted; "6" recorded, not failed, until OPEN-2 settles and ADR-0040 is signed off; HOS-07f refused on its risk, the `rule` of each `errors[]` entry recorded | OVR-01, OVR-02, HOS-07a, HOS-07b, HOS-07e, HOS-07f, HOS-07h, HOS-07j |
| C-40 | The refused-override counter's label. **Resolved on `main` by #4505:** E28-S05 counted `cv_override_refused_total{field}` and now names `{cap}`, as the metric catalogue does ("a field of the override table", 20:1474), with ADR-0040 (proposed; ADR-0040:155) and the E28 threat model §8.2 | `{cap}`, its value recorded | OVR-01, OVR-02 |

**Follow-up, one, filed when the filing freeze lifts:** a live `instruments-info` recording with the
recorder tool, together with a DOGEUSDT recording (C-13.5; #904 record, ruling 3 (2026-10-24)). It
unblocks BND-19 and C-04's 20x journey, and lets C-36's cases assert on DOGEUSDT.

## 14. Dry-run execution record

**Status: pending, not executed.** Every case waits on its implementing ticket: E28-T02 (#906, in
progress) for the profile writes, E28-T03 (#907) for sizing, E28-T04 for the guard, E28-T05 (#909)
for definitions, preview and the projection, E28-S01 to E28-S05 for the screens, E34-S01 to E34-S03
and E32 for submission, and #2893 for the stub. No result below is fabricated. Rows are appended as
each dependency lands, never overwritten; a case whose route answers `501`, or the plain `404` of
a route not mounted, is recorded as `blocked-pending-dependency`, never as a pass or a fail.

| Group or cases                       | Build sha | Environment | Fixture        | Result                             | Evidence | Defect |
| ------------------------------------ | --------- | ----------- | -------------- | ---------------------------------- | -------- | ------ |
| Fixture load (EN-3), vectors (EN-5)  | —         | CI          | slice A        | pending (slice A merge; E28-T03)   | —        | —      |
| PRO-01 to PRO-08                     | —         | stub + demo | world, vectors | pending (E28-T02, T03, S01)        | —        | —      |
| SYM-01 to SYM-05                     | —         | stub        | world          | pending (E28-T04, S02)             | —        | —      |
| CAP-01 to CAP-03                     | —         | stub        | §12.6 overlays | pending (E28-T04, E39, §12.6)      | —        | —      |
| GRP-01 to GRP-04                     | —         | stub        | world          | pending (E28-T05, S03, E34-S05)    | —        | —      |
| FAN-01 to FAN-05                     | —         | stub + demo | Trio           | pending (E34-S02, S03, E32, #2893) | —        | —      |
| PRV-01 to PRV-03, OVR-01 to OVR-03   | —         | stub        | world          | pending (E28-T05, S04, S05, K01)   | —        | —      |
| BND-01 to BND-18, HOS-01a to HOS-07n | —         | stub        | world          | pending (as above; E28-X03)        | —        | —      |
| BND-19                               | —         | stub        | world          | blocked (live recording, §13 C-04) | —        | —      |
| AX-01 to AX-05                       | —         | staging     | world          | pending (E28-Q04)                  | —        | —      |
| Slice A merge (fixture set)          | 5d6378a5  | main        | slice A        | merged                             | #4459    | —      |

## 15. Sign-off

- [ ] Peer review by a second QA/SDET. No second human QA exists: under the owner's agent-delivery
      adaptations (decision 2026-09-25) an independent reviewer agent substitutes, and the owner's
      `approved` comment or merge records the sign-off. **Pending.**
- [ ] Entry and exit criteria (§0.2) and the triage convention (§0.1) agreed with the Owner and the
      Architect (#904). **Pending.**
- [ ] Dry run recorded with pass or fail and evidence per case (§14). **Pending.**
- [x] Every `US-PROF-001..008` Gherkin scenario maps to at least one case (§8), with no gap.
- [x] Every boundary and hostile entry names the constraint or control it probes (§9, §10).
- [x] Implementation-independent: no case names an internal function, module path or private field.
- [x] No live exchange in any case and no wall-clock sleep in automation (§0, §12.5).
- [ ] The fixture set consumed by at least one of E28-Q02, E28-D07 and E28-X03 before #904 closes.
      **Pending.**
- [ ] Ten golden vectors recomputed by QA match E28-T03's values exactly (EX-3). **Pending.**
- [ ] QA sign-off comment on epic E28, after E28-Q05. **Pending.**
