# E27 accounts and API-key vault — black-box test plan

Ticket: E27-Q01 (issue #833). This file is PR 1 of 2; PR 2 delivers the fault-injection fixture pack
whose scenarios §9.3 defines. Owner: QA. Status: **Authored — peer review and demo-stack dry run
pending (§11, §12).**

Path: the ticket names `qa/plans/e27/test-plan.md`. This file follows the repository's flat
convention instead (`qa/plans/e09-auth-rbac-test-plan.md`, `qa/plans/e08-market-data-test-plan.md`),
as recorded on #833.

Written against the observable surface only:

- **Stories:** `US-ACCT-001..010` with their Gherkin and NFRs (`docs/plan/11-user-stories.md` §2).
- **Screens:** `SCR-016` (step 3), `SCR-019`, `SCR-079`, `SCR-125`..`SCR-129`
  (`docs/plan/14-screens-catalogue.md`).
- **Components** (`docs/plan/15-component-catalogue.md`): `CMP-027`, `CMP-028`, `CMP-033`, `CMP-034`,
  `CMP-035`, `CMP-036`, `CMP-040`, `CMP-043`, `CMP-044`, `CMP-046`, `CMP-049`, `CMP-055`, `CMP-065`,
  `CMP-066`, `CMP-087`, `CMP-093`, `CMP-104`, `CMP-106`, `CMP-116`, `CMP-128`, `CMP-129`, `CMP-175`,
  `CMP-176`, `CMP-178`.
- **REST** (`docs/plan/22-api-openapi.yaml`): `/exchange-accounts`, `/exchange-accounts/{accountId}`,
  `/exchange-accounts/{accountId}/keys`, `/exchange-accounts/{accountId}/keys/{keyId}`,
  `/exchange-accounts/{accountId}/keys/{keyId}/rotate`, `/exchange-accounts/{accountId}/keys/{keyId}/test`,
  `/exchange-accounts/{accountId}/fee-rate`, `/positions/{positionId}/leverage`, `/me`, `/auth/step-up`.
  In the case tables `...` is short for `/exchange-accounts/{accountId}`, so `.../keys` is
  `/exchange-accounts/{accountId}/keys`.
- **WS** (`docs/plan/23-ws-protocol.md` §6.2, §9.5, §10.2): private topics `wallet`, `positions`,
  `system`; `revoked` reasons `key_revoked`, `account_disabled`, `account_scope_changed`; error
  `account_scope_denied`.
- **Documented behaviour:** `docs/plan/21-database-schema.md` §3.2 and §3.1.3 (the ticket's "§3.13"),
  ADR-0009, ADR-0010, `docs/plan/04-security-program.md` (SR ids, §5.14, §7.2, §8.2),
  `docs/plan/03-testing-strategy.md` and `docs/plan/30-release-roadmap.md` §7.3 (R3 exit criteria #9
  and #10).

The plan was written without reading the implementation. No case names an internal function, module
path or private field, so it survives refactors of E27-T03, E27-T04 and E27-S01..S05.

## 0. How to use this plan

- **Audience:** a QA engineer with a staging URL, the fixture pack (§9.3) and the seeded users (§9.1).
  No step needs backend source to decide pass or fail.
- **Fixtures, never a live exchange (C-13.5).** Hostile key states (withdrawal right, allowlist gaps,
  UID or UTA mismatch, clock skew, a dead private WS, 5xx, `10018`, the 48 h restriction) cannot be
  produced on demand on Bybit, so each case names its fault-injection scenario (§9.3). E27-Q02
  automation loads a scenario through PR 2's test-side loader. A manually run stack needs the
  `CV_ACCOUNT_FIXTURE=<scenario>` stub transport, a follow-up filed with PR 2: on `main` the
  synthetic feed (`CV_FEED=synthetic`) serves public market data only (#833 comment). Positive paths
  also run on the Bybit demo stack in the dry run (§11), with the Owner typing a demo key. QA never
  handles key material (C-12.2).
- **Case id:** `E27-TC-nnn`, stable for E27-Q02, E27-Q05 and defect reports. Blocks: Group A
  `001–099`, B `101–199`, C `201–299`, D `301–399`, E `401–499`. Never renumber; retire a case by
  marking it withdrawn.
- **Columns:** Case · Type (`pos` = happy path, `neg` = failure, edge or abuse) · US · Preconditions
  and scenario · Steps · Expected result · Evidence · Audit · metric · KB · Auto.
- **Oracles.** API behaviour: the contract (contract-first, C-6.1). UI copy and states: the SCR spec
  until E27-D02 (#733) is signed off; a case whose state depends on the open wireframes says "per
  SCR-nnn spec; confirm against E27-D02". Where documents disagree, the case names the source it
  follows and §10 lists the conflict. Balances and payloads are compared with the scenario's fixture,
  never with the UI's own numbers.
- **Evidence codes:** `HAR` network export or curl transcript of the named calls · `SS` screenshot of
  the named state · `A11Y` accessibility-tree snapshot or screen-reader transcript · `AUD`
  `GET /admin/audit` extract for the subject · `LOG` stub request log extract (§9.6) · `MET`
  `GET /metrics` before/after diff · `WS` captured frames · `T` timing (performance mark, stopwatch or
  screen capture).
- **Audit step:** a case with an audit event ends with "query
  `GET /admin/audit?subject_type=<exchange_account|api_key>&subject_id=<id>`; expect one new entry
  with the acting user as actor, the action in §8.1 and no secret in the payload".
- **Step-up:** §9.4. **Clock:** §9.5. Manual runs may stopwatch second-scale deadlines (30 s, 60 s)
  with a ±2 s tolerance; automation uses the test clock or event waiters, never a sleep (C-13.7).
- **KB:** `Y` = also execute keyboard-only, no pointer (`docs/plan/05-accessibility-standard.md` §3);
  `—` = API-only or no separate keyboard pass needed. The full audit is E27-Q04.
- **Auto:** `Q02` = automated by E27-Q02 · `Q02·clk` = automated, needs the test clock (§9.5) ·
  `+manual` = plus a manual part (timing, copy review or a restart) · `manual` = human only.
- **Out of scope:** writing the specs (E27-Q02), the accessibility audit (E27-Q04), load and chaos
  (E27-Q03), adversarial depth (E27-X02), the full route × role matrix (E27-X03), restore and
  compromise drills (E27-X04), profiles and trade groups (E28), the OMS (E29), the dead-man's switch
  (E45-Q01).

## 0.1 Defect conventions for this epic

Severity follows `docs/plan/03-testing-strategy.md` §11.3. Epic overrides (risk R7 Data accuracy):

<!-- prettier-ignore -->
| Observation | Severity and handling |
| --- | --- |
| **Visible secret material**: an API secret, a key id beyond the masked tail, a signature or KEK/DEK material in any UI state, API response, WS frame, error body, audit payload, metrics output or download | **`priority/p0-critical` regardless of any other impact.** Report privately (`SECURITY.md` §1, GitHub Private Vulnerability Reporting), never in a public issue; name the scenario, never paste the string |
| An account shown verified or left tradeable while its key has a withdrawal or transfer right, a missing or non-matching allowlist or the wrong environment, or after a stale or inconclusive self-check | `priority/p0-critical` |
| Rotation reports success while the old key stays primary; revoke or delete reports success while the key can still sign (`LOG`) | `priority/p0-critical` |
| A demo-bound account contacts a live host, or the reverse (C-2.11) | `priority/p0-critical` |
| Order entry accepted for a red, disabled or key-less account; leverage above the profile cap reaches the exchange | `priority/p0-critical` |
| A balance presented as current without a freshness marker, or without the stale badge after reconciliation failed | `priority/p0-critical` while risk-based sizing stays enabled for that account, otherwise `priority/p1` |
| Missing or malformed audit entry for an action in §8.1 (C-2.9) | `priority/p1`, filed against the acting case |
| A perceived-performance budget in §0.2 missed | Functional defect, `priority/p2` by default; `priority/p1` when it blocks the flow |
| A `KB = Y` case cannot be completed keyboard-only | `priority/p2` (AA violation); `priority/p1` for revoke, disable or delete |

Every report names the case id, US id, scenario, build sha and environment, the exact request and
response or frame (redacted), and the evidence codes.

## 0.2 Perceived-performance assertions

A missed budget is a functional defect (§0.1), not only a performance-ticket concern. Load is E27-Q03.

<!-- prettier-ignore -->
| Budget | Source | Case | Measured as |
| --- | --- | --- | --- |
| Key validation round-trip ≤3 s | SCR-126 | E27-TC-101 | `T` from the re-sent save to the rendered result; real figure on the demo stack, sanity only on the stub |
| Rotation ≤10 s, stages and elapsed time shown | SCR-127 | E27-TC-201 | `T` from submit to "switched over" |
| Account drawer opens ≤100 ms from cache and refreshes in place | SCR-079 | E27-TC-402 | `T` click → content, warm cache, five runs |
| Health refreshed on open and every 60 s, never per second | SCR-125 | E27-TC-413 | `HAR` over 5 min |
| Consequence summary ≤1 s; no confirm button before it loads | SCR-129 | E27-TC-308 | `T` + `SS` |
| REST reconciliation after 60 s without a wallet frame | US-ACCT-008 | E27-TC-403, E27-TC-406 | `LOG` timestamps |
| Red ≤30 s after WS and REST both fail; heartbeat age ≤10 s while healthy | US-ACCT-010 | E27-TC-410, E27-TC-408 | `LOG` + `HAR` timestamps |

---

## 1. Group A — Registration (US-ACCT-001; E27-S01)

Screens `SCR-125`, `SCR-126`, `SCR-016` (step 3), `SCR-019`. Endpoints `GET`/`POST /exchange-accounts`,
`GET`/`PATCH /exchange-accounts/{accountId}`, `POST /auth/step-up`, `GET /me`. Audit `account.created`,
`account.updated`. Registration never handles a secret. Actor `owner-enrolled` unless stated.

<!-- prettier-ignore -->
| Case | Type | US | Preconditions · scenario | Steps | Expected result | Evidence | Audit · metric | KB | Auto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E27-TC-001 | pos | US-ACCT-001 | No accounts | 1. SCR-125 → "+ Add account". 2. Label `QA Main`, UID `90000001`, kind main, environment Demo. 3. Save; answer the step-up (§9.4). 4. `GET /exchange-accounts`. | First save → `403 step_up_required` whose `action_summary` names the label, environment and UID (`accounts:write` needs step-up, 04 §7.2.1); the re-sent save → `201` with `environment: demo`, `kind: main`, `parent_account_id: null`. The row reads "no key — inactive" as text and shows no balance (per SCR-125 spec; confirm against E27-D02). | HAR, SS, AUD | `account.created` · — | Y | Q02 |
| E27-TC-002 | pos | US-ACCT-001 | TC-001 done | Add a sub-account: label `QA Sub 1`, UID `90000011`, kind sub, parent `QA Main`, Demo; step-up. | `201` with `parent_account_id` = QA Main; listed as a sub of QA Main, "no key — inactive". | HAR, SS, AUD | `account.created` · — | Y | Q02 |
| E27-TC-003 | neg | US-ACCT-001 | TC-001 done | Register UID `90000001` again in Demo as `QA Dup`. | `409 conflict`; the message names the existing label (US-ACCT-001: "This UID is already registered as `<label>`"; SCR-126 words it differently, §10 DC-16); no second row; no `account.created`. | HAR, SS, AUD | — · — | Y | Q02 |
| E27-TC-004 | pos | US-ACCT-001 | TC-001 done | Register UID `90000001` with environment Live as `QA Main (live)`. | `201`: a UID may be registered once per environment (21 §3.2.1). Both rows listed, each with its environment as text, demo and live visibly grouped (SCR-125). Account shell only: this plan never attaches a key to a live-bound row. | HAR, SS, AUD | `account.created` · — | Y | Q02 |
| E27-TC-005 | neg | US-ACCT-001 | Five demo subs under QA Main (§9.2); main at the regular KYC tier | 1. Start adding a sixth sub. 2. Try to save without acknowledging. 3. Acknowledge and save. | Step 1 shows the Bybit cap "5 regular / 20 Business KYC". Step 2: save unavailable until the explicit acknowledgement (US-ACCT-001; per SCR-125/SCR-126 spec, confirm against E27-D02). Step 3: `409 conflict` (the contract rejects the 6th and has no acknowledgement field, §10 DC-17). Sub count stays 5. | HAR, SS | — · — | Y | Q02+manual |
| E27-TC-006 | neg | US-ACCT-001 | TC-001 done | Register a demo account labelled `qa main`, UID `90000002`. | Rejected with a 4xx problem naming `label`: labels are unique per environment, ignoring case (21 §3.2.1); no row. | HAR | — · — | Y | Q02 |
| E27-TC-007 | pos | US-ACCT-001 | TC-001 done | Register a live account labelled `QA Main`, UID `90000003`. | `201`: the same label is allowed in the other environment. | HAR | `account.created` · — | — | Q02 |
| E27-TC-008 | neg | US-ACCT-001 | `manager-with-grants`, then `viewer-granted` | 1. `GET /me`. 2. Open `/admin/accounts`. 3. `POST /exchange-accounts` with a valid body. | 1: no `accounts:write`. 2: SCR-154 permission denied, no add control (hiding is not the control). 3: `403 forbidden` with `required_permissions: [accounts:write]`, no step-up challenge (RBAC is decided first, `/auth/step-up`), nothing created, denial audited (11 global AC 1). Same for the viewer. | HAR, SS, AUD | `authz.denied` · — | Y | Q02 |
| E27-TC-009 | neg | US-ACCT-001 | — | `POST /exchange-accounts` with: a) UID `12a4`; b) UID `123`; c) empty label; d) an 81-character label; e) kind sub without a parent; f) an extra property `acknowledged: true`. Repeat a–e in the SCR-126 form. | Each `422 validation_failed` naming the field (f: unknown property refused); nothing created; the form shows each error inline, linked to its field (CMP-040). | HAR, SS, A11Y | — · — | Y | Q02 |
| E27-TC-010 | neg | US-ACCT-001 | `QA Main (live)` from TC-004 | Register a demo sub-account whose parent is `QA Main (live)`. | Rejected, no row: a sub-account's environment must equal its parent's (21 §3.2.1, C-2.11). | HAR | — · — | — | Q02 |
| E27-TC-011 | pos | US-ACCT-001 | TC-001 done | 1. Rename `QA Main` to `QA Main A` (`PATCH` with `If-Match`; step-up). 2. `PATCH` carrying `exchange_uid` or `environment`. | 1: `200`; the new label shows on SCR-125 and in the drawer heading. 2: `422` (the request schema has neither field: UID and environment never change after registration). | HAR, SS, AUD | `account.updated` (label before/after) · — | Y | Q02 |
| E27-TC-012 | pos | US-ACCT-001, US-ACCT-003 | Empty install, Owner first run; scenario `compliant` | 1. Onboarding (SCR-016) to step 3. 2. Check the environment default. 3. Enter label, key and secret; Test connection. 4. Continue. | Demo preselected with "Live needs step-up later"; Continue disabled until the test passes; the result is a list ("read ok - trade ok - no-withdraw ok"); after Continue the account exists and its key is verified; the secret is never echoed after save. The stepper is a `<nav>` with `aria-current="step"`; focus moves to the step heading (per SCR-016 spec). | SS, A11Y, HAR, AUD | `account.created`, `account.updated` · `cv_key_verification_total` +1 pass | Y | Q02+manual |
| E27-TC-013 | pos | US-ACCT-001 | Empty install | 1. On step 3 choose "Skip for now"; finish the wizard. 2. Open the setup checklist (SCR-019). 3. Follow the account task's link and register an account as in TC-001. | The skip creates nothing; SCR-019 (`GET /onboarding/checklist`) lists the account task as pending with a link to the add-account screen; after step 3 the task shows done, announced politely (per SCR-019 spec). | SS, A11Y, HAR | `account.created` · — | Y | Q02 |

---

## 2. Group B — Key intake (US-ACCT-002, US-ACCT-003, US-ACCT-007; E27-S02, E27-T03)

Screens `SCR-126`, `SCR-016` (step 3), `SCR-125`, `SCR-128`, `SCR-079`. Endpoints `POST`/`GET .../keys`,
`POST .../keys/{keyId}/test`, `POST /auth/step-up`; WS `system`. Audit `account.updated` (key
attached), `account.tested`, `account.disabled_by_policy`; metric `cv_key_verification_total`. Unless
stated the account is `acct-demo-main` (Demo, UID `90000001`, no key), the actor is `owner-enrolled`,
and every save answers the `keys` step-up (§9.4).

<!-- prettier-ignore -->
| Case | Type | US | Preconditions · scenario | Steps | Expected result | Evidence | Audit · metric | KB | Auto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E27-TC-101 | pos | US-ACCT-002, US-ACCT-003 | Scenario `compliant` | 1. SCR-126 (edit mode): paste key and secret, read-only off, Save. 2. Time the re-sent save to the rendered result. 3. `GET .../keys`. 4. Restart the backend; `POST .../keys/{keyId}/test`. | `201`: `passed: true`, `withdraw_enabled: false`, `uid` = the account UID, `unified: true`, `ip_whitelist_matches_egress: true`, `probe_ret_code: 0`, `warnings: []`. The key is `active` and identified only by `key_id_masked` with at most 4 clear characters (SR-005, §10 DC-02). The account shows "verified" with the scope list and the allowlist, as a list, not colour (US-ACCT-003, SCR-126); ≤3 s (§0.2). Step 4 passes and the stub validates the signature against the scenario secret: the stored secret round-trips without ever being shown. | HAR, SS, T, LOG, AUD, MET | `account.updated` (fingerprint only) · `cv_key_verification_total` +1 pass | Y | Q02+manual |
| E27-TC-102 | neg | US-ACCT-003 | Scenario `withdraw_enabled` | Save. | `422 validation_failed` with `errors[].rule: key_withdraw_permission` (ticket AC 2). Not persisted: `GET .../keys` unchanged, `key_status: missing`. Hard-block copy "This key has withdrawal permission. Create a key with withdrawal disabled." (SCR-016, SCR-126); the withdrawal state is never rendered neutrally (CMP-175); no input echoed. | HAR, SS, LOG, AUD, MET | `key.verification_failed` · +1 fail | Y | Q02 |
| E27-TC-103 | neg | US-ACCT-003 | Scenario `transfer_enabled` | Save. | Refused like TC-102, with a transfer rule (C-2.8, SR-030a); not persisted. A `201` is P0 even though the contract's example stores `Wallet: [AccountTransfer]` (§10 DC-01). | HAR, MET | `key.verification_failed` · +1 fail | — | Q02 |
| E27-TC-104 | neg | US-ACCT-003 | Scenario `ip_missing` | Save. | Refused with an allowlist rule; not persisted; the copy says the allowlist must be set in the Bybit dashboard (browser-only, ADR-0009; per SCR-126 spec, confirm against E27-D02). The allowlist is mandatory in every environment (C-2.8, C-12.2): acceptance because `require_ip_whitelist` defaults off for demo is a defect (§10 DC-03). | HAR, SS, MET | `key.verification_failed` · +1 fail | Y | Q02 |
| E27-TC-105 | neg | US-ACCT-003 | Scenario `ip_mismatch` (allowlist `198.51.100.20`, egress `203.0.113.10`) | Save; use the copy control. | Refused ("egress IP not in allowlist"); not persisted. The current egress IP is shown with a copy control that announces "Copied" (CMP-033), labelled apart from any tailnet address (SR-033). | HAR, SS, A11Y, MET | `key.verification_failed` · +1 fail | Y | Q02+manual |
| E27-TC-106 | neg | US-ACCT-003 | Scenario `ip_extra_foreign` (egress plus `192.0.2.30`) | Save. | Refused: every allowlist entry must equal the egress IP, no wildcard (SR-030a). The contract says only "inside it" (§10 DC-03); a `201` is P0. | HAR, MET | `key.verification_failed` · +1 fail | — | Q02 |
| E27-TC-107 | neg | US-ACCT-003 | Scenario `uid_mismatch` (key reports UID `90000099`) | Save with `expected_uid` = `90000001`. | Refused; the reason names both UIDs; not persisted. | HAR, SS, MET | `key.verification_failed` · +1 fail | Y | Q02 |
| E27-TC-108 | neg | US-ACCT-003 | Scenario `non_uta` | Save. | Refused ("not a Unified Trading Account"); not persisted. | HAR, MET | `key.verification_failed` · +1 fail | — | Q02 |
| E27-TC-109 | neg | US-ACCT-003 | Scenario `clock_skew` | Save. | Refused; the reason names clock sync, the measured offset and the fix (sync the host clock); the exchange code only in a details disclosure (11 global AC 5); not persisted. | HAR, SS, MET | `key.verification_failed` · +1 fail | Y | Q02 |
| E27-TC-110 | neg | US-ACCT-003 | Scenario `wallet_probe_error` | Save. | Refused (the signed probe must return `retCode=0`); domain-language reason, exchange code in details; not persisted. | HAR, MET | `key.verification_failed` · +1 fail | — | Q02 |
| E27-TC-111 | neg | US-ACCT-003 | Scenario `missing_trade_scope`, `read_only: false` | Save. | Refused (required trade scopes absent); not persisted. | HAR, MET | `key.verification_failed` · +1 fail | — | Q02 |
| E27-TC-112 | neg | US-ACCT-003 | Scenario `extra_scope` | Save. | Refused: a trading key carries only the contract trade scopes (SR-030a; allow-list pending #2417, §10 DC-01); not persisted. | HAR, MET | `key.verification_failed` · +1 fail | — | Q02 |
| E27-TC-113 | neg | US-ACCT-007 | Demo-bound account; scenario `live_key_on_demo` | Paste the key; Save. | The self-check fails with "key does not belong to this environment" (US-ACCT-007); not persisted; `LOG` shows demo hosts only, zero live-host requests. | HAR, SS, LOG, MET | `key.verification_failed` · +1 fail | Y | Q02 |
| E27-TC-114 | pos | US-ACCT-007 | Account verified in TC-101 | 1. Read the SCR-125 row and the SCR-079 heading. 2. Test connection; keep the drawer open 2 min. 3. Read `LOG`. | The environment is text on the row and in the drawer heading (CMP-106 name `<label>, demo account`); every REST call and the private WS for the account used demo hosts only. | SS, A11Y, LOG | — · — | Y | Q02 |
| E27-TC-115 | neg | US-ACCT-007 | Account verified; scenario `demo_ws_unreachable` | 1. Restart, or wait for a reconnect cycle. 2. Watch SCR-125, SCR-079 and `system` for 2 min. 3. Read `LOG`. | The outage is reported (state per §5; `system` `exchange_state` frame). No fallback: zero connections or requests to live hosts (US-ACCT-007, C-2.11). | SS, WS, LOG | — · `cv_account_health_state` leaves healthy | — | Q02 |
| E27-TC-116 | pos | US-ACCT-003 | Scenario `expiring_13d` | Save; open SCR-125 and SCR-079. | `201` with a warning naming the expiry ("key expires in 13 days"). A warning, not a block: order entry stays enabled. SCR-125 shows the "key expiring (<14 d)" chip and SCR-079 "key expiring soon" (per spec; confirm against E27-D02). | HAR, SS | `account.updated`, `key.expiry_warning` · +1 pass | Y | Q02 |
| E27-TC-117 | neg | US-ACCT-003 | Scenario `expiring_15d` | Save. | `201`, `warnings: []`, no expiring chip: no false warning outside 14 days. | HAR, SS | `account.updated` · +1 pass | — | Q02 |
| E27-TC-118 | neg | US-ACCT-002 | Key active (TC-101) | 1. Reopen the key on SCR-126 (edit), SCR-125, SCR-128, SCR-127 step 1 and SCR-079; tab through every control. 2. `GET .../keys`, `GET /exchange-accounts/{accountId}`, `POST .../keys/{keyId}/test`. 3. Try `GET .../keys/{keyId}`, `GET .../keys/{keyId}/secret`, `GET .../keys?reveal=true`. 4. Search every captured response and frame, the DOM and `GET /metrics` for the scenario's key id and secret. 5. Read the `action_class` values of `POST /auth/step-up`. | No reveal path anywhere (US-ACCT-002, SR-005, R3 exit #9). The secret field is an empty write-only field described as such; there is no "Show secret", reveal or copy-secret control (§10 DC-22); identifiers are truncated. Step 2 returns metadata only; step 3 → `404`/`405` with no secret; step 4 finds neither string; step 5 offers no reveal class. Any hit is P0. | SS, A11Y, HAR, WS, MET | — · — | Y | Q02+manual |
| E27-TC-119 | neg | US-ACCT-002 | Scenarios `withdraw_enabled`, then `compliant` | 1. Submit the failing key. 2. Inspect the problem body, the UI error, the console, the frames and the attempt's audit entry. 3. Submit the compliant key; read its audit payload. | Nothing echoes the submitted key or secret (a 422 never echoes input, 04 §5.14 KV4); the audit payload holds the key fingerprint only (SCR-126). | HAR, AUD | `key.verification_failed`, `account.updated` · — | — | Q02 |
| E27-TC-120 | neg | US-ACCT-002 | Stored keys exist; backend started with no KEK available (ADR-0009 Amendment 1: no handle) | 1. Start; open the app. 2. `POST /orders` for a verified account. 3. `POST .../keys`, `POST .../keys/{keyId}/rotate`, `POST .../keys/{keyId}/test`. 4. `GET /exchange-accounts`. 5. Restore the KEK; restart. | Read-only start with a blocking banner: `system` notice with `severity: critical`, `reason: secrets.kek_unavailable` (23 §15.9). Step 2 refused (trading routes refused, US-ACCT-002); step 3 each `403` (ADR-0009 Amendment 1); step 4 still served; step 5 clears it ("Read-only mode cleared."). | SS, WS, HAR | — · — | Y | manual |
| E27-TC-121 | neg | US-ACCT-002 | Scenario `compliant` | 1. `POST .../keys` twice with the same `Idempotency-Key` and body. 2. Same key, different body. 3. No `Idempotency-Key`. | 1: one key only; the second answer is the original response with `Idempotency-Replayed: true`. 2: `409 idempotency_key_reuse`. 3: refused as invalid (the header is required); nothing stored. | HAR | one `account.updated` · +1 pass | — | Q02 |
| E27-TC-122 | neg | US-ACCT-003 | Scenario `bybit_5xx` | 1. Save. 2. Switch to `compliant`; save again with a new `Idempotency-Key`. | 1: a 5xx problem (`exchange_error` 502 as the operation documents, or `exchange_unavailable` 503), never `201` or `500`; not persisted; retry copy shown. 2: `201`. | HAR | `key.verification_failed` · +1 fail | — | Q02 |
| E27-TC-123 | neg | US-ACCT-003 | Scenario `rate_limited_10018` | Save. | Refused, not persisted; `exchange_rate_limited` with `retry_after_seconds` (registry status 429; `createApiKey` documents no 429, §10 DC-11); the UI says when to retry; `LOG` shows no retry loop. | HAR, LOG | `key.verification_failed` · +1 fail | — | Q02 |
| E27-TC-124 | pos | US-ACCT-003 | Account verified (`compliant`) | 1. SCR-125 Test connection (`POST .../keys/{keyId}/test`, `include_ws: true`). 2. Open SCR-128. | `200` with `passed: true`, `rest.ok`, `websocket.ok` and a new `checked_at`. SCR-125 summary "Withdrawal permission: OFF on all accounts (verified `<time>`)"; SCR-128 shows the last successful verification, key age, allowlist state and next rotation date; `LOG` shows no order placed. | HAR, SS, LOG, AUD | `account.tested` · +1 pass | Y | Q02 |
| E27-TC-125 | neg | US-ACCT-003 | Account verified; scenario `ws_auth_timeout` | Test connection. | `200` with `passed: false`, `websocket.ok: false` and an error from a fixed vocabulary, never free exchange text (#2417); the UI names the failed probe in text. | HAR, SS | `account.tested` · +1 fail | Y | Q02 |
| E27-TC-126 | neg | US-ACCT-003 | Two verified accounts; one key switched to `withdraw_enabled` after storage | 1. Trigger the self-check: restart (start-up) or the hourly run (C-12.2, §9.5). 2. Watch SCR-125, SCR-079, alerts and `system`. 3. `POST /orders` on both accounts. 4. Cancel an order and flatten on the affected account. | The affected account is force-disabled for trading with a critical alert and the reason shown verbatim; SCR-125 shows a red blocking banner and its summary no longer says "OFF on all accounts" (US-ACCT-003, SCR-125). Trading mode is refused system-wide, so step 3 is refused on both accounts (C-2.8, C-12.2; §10 DC-04). Step 4 risk-reducing actions still work (SR-032). | SS, WS, HAR, AUD, MET | `account.disabled_by_policy` · +1 fail | Y | Q02·clk+manual |
| E27-TC-127 | neg | US-ACCT-003 | Account verified; its key switched to `ip_mismatch` (egress changed) | Trigger the self-check (restart or hourly). | "IP mismatch" shown, trading blocked, and the current egress IP shown with a copy control (US-ACCT-003); SCR-079 shows the mismatch state with remediation text; trading mode as in TC-126. | SS, HAR, AUD | `account.disabled_by_policy` · +1 fail | Y | Q02·clk+manual |
| E27-TC-128 | neg | US-ACCT-003 | Three verified accounts; one key switched to `ip_missing` | Restart. | Every stored key is re-checked (SR-031, R3 exit #9): only that account is flagged and the other two still show verified; trading mode as in TC-126. | SS, HAR, MET | `account.disabled_by_policy` · +3 (one fail) | — | Q02+manual |
| E27-TC-129 | neg | US-ACCT-003 | Account verified; scenario `bybit_5xx` for every start-up check | Restart. | The inconclusive check counts as failed (04 §5.14 KV3): the account never shows "verified" from a check that did not finish; trading mode as in TC-126. | SS, HAR | `account.disabled_by_policy` · +1 fail | — | Q02+manual |
| E27-TC-130 | neg | US-ACCT-003 | Scenario `new_key_48h` (key created 2 h ago) | Save; open SCR-125 and SCR-079. | State "within Bybit's 48 h new-key restriction", key status "restricted", with the time it lifts; never shown as fully verified or tradeable before then (per SCR-125/SCR-079 spec; confirm against E27-D02). | HAR, SS | `account.updated` if stored · +1 | Y | Q02+manual |
| E27-TC-131 | neg | US-ACCT-002 | `manager-with-grants` (trade grant on the account) | `POST .../keys`, `GET .../keys`, `POST .../keys/{keyId}/test` on the granted account. | Each `403 forbidden` (`keys:manage` and `keys:read` are Owner-only, 04 §7.2.1); no challenge; denials audited. | HAR, AUD | `authz.denied` · — | — | Q02 |

---

## 3. Group C — Rotation and key-age policy (US-ACCT-004, US-ACCT-005; E27-S03, E27-T04)

Screens `SCR-127`, `SCR-128`, `SCR-125`. Endpoints `POST .../keys/{keyId}/rotate`, `GET .../keys`,
`DELETE .../keys/{keyId}`, `GET /orders`, `GET /positions`. Audit `account.key_rotated`. The key-age
policy is set explicitly to 90 days unless stated (SR-037 sets 180 days for demo keys, §10 DC-09).

<!-- prettier-ignore -->
| Case | Type | US | Preconditions · scenario | Steps | Expected result | Evidence | Audit · metric | KB | Auto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E27-TC-201 | pos | US-ACCT-004 | Account verified with the old key; scenario `rotation_ok`; `wallet` frames flowing | 1. SCR-127: follow the checklist, enter the new key, validate, switch over (step-up). 2. Time submit → switched. 3. `GET .../keys`. 4. Read `LOG` and the `wallet` stream across the switch. | `200`, `state: overlapping`, `overlap_until` = start + 15 min (US-ACCT-004, 21 §3.2.3; the contract default is 300 s, §10 DC-06). New key `active`, old key `rotating`. From the switch every new request uses the new key while the old one stays valid for the drain window; the private WS re-authenticates with the new key; every `wallet` frame the stub sends during the switch arrives (no interruption). Stages and elapsed time shown, ≤10 s (§0.2); steps are labelled regions with `aria-current="step"`. | HAR, SS, T, LOG, WS, AUD | `account.key_rotated` (fingerprints only) · +1 pass | Y | Q02+manual |
| E27-TC-202 | pos | US-ACCT-004 | TC-201 in overlap | 1. Let the drain window end (§9.5, or 15 min by hand). 2. `GET .../keys`; read `LOG`. 3. Read the last SCR-127 step. | Old key `revoked`; no request uses it after `overlap_until`, and it cannot be used again (`POST .../keys/{oldKeyId}/test` does not pass). SCR-127 reminds the owner to delete the old key at Bybit, with a confirmation checkbox. No exchange delete call is expected: the contract revokes locally only, while US-ACCT-004 says one is attempted (§10 DC-07). | HAR, LOG, SS, AUD | `key.revoked` · — | Y | Q02·clk |
| E27-TC-203 | pos | US-ACCT-004 | TC-201 in overlap | Revoke the old key early (SCR-127 or `DELETE .../keys/{oldKeyId}`; step-up). | `204`; the old key is revoked at once; the new key stays active and primary; trading continues; `LOG` shows no old-key request after the `204`. | HAR, LOG, AUD | `key.revoked` · — | Y | Q02 |
| E27-TC-204 | neg | US-ACCT-004 | Account verified; scenario `rotation_new_key_withdraw` | Rotate. | Promotion refused (`422`, `key_withdraw_permission`). The old key stays `active` and primary, the account stays verified and tradeable, the reason is shown, SCR-127 shows its rollback state, and the new key is not stored. Success here, or an old key left non-primary, is P0. | HAR, SS, LOG | `key.verification_failed` · +1 fail | Y | Q02 |
| E27-TC-205 | neg | US-ACCT-004 | Account verified with 2 open orders and 1 position carrying its native SL; scenario `rotation_ok` | Rotate as in TC-201; then `GET /orders` (`open_only`) and `GET /positions`. | The same 2 orders (ids and states unchanged) and the same position with its SL; `LOG` shows no cancel: rotation never cancels open orders (US-ACCT-004 NFR). | HAR, LOG | `account.key_rotated` · +1 pass | — | Q02 |
| E27-TC-206 | neg | US-ACCT-004 | A session with no live `keys` grant; then `manager-with-grants` | 1. Rotate. 2. The manager calls rotate. | 1: `403 step_up_required` with `action_class: keys` and `action_summary` `Rotate API key for account '<label>' (demo, UID <uid>)`; nothing started. 2: `403 forbidden`, no challenge. | HAR, AUD | `authz.denied` (step 2) · — | — | Q02 |
| E27-TC-207 | pos | US-ACCT-005 | Policy 90 d; key registered 76 days ago (§9.5) | Open SCR-125 and SCR-128. | Amber "rotate within 14 days" chip with icon and text; SCR-128 shows the rotation-due date; one alert raised; trading unaffected (per spec; confirm against E27-D02). | SS, A11Y | — · — | Y | Q02·clk |
| E27-TC-208 | neg | US-ACCT-005 | As TC-207 with the key 75 days old | Open SCR-125. | No chip and no alert. | SS | — · — | — | Q02·clk |
| E27-TC-209 | neg | US-ACCT-005 | Policy 90 d; key 91 days old | 1. Open SCR-125. 2. Advance the clock 24 h, twice. 3. `POST /orders` on the account. | Red "overdue" chip; exactly one alert per day; the order is accepted: trading is never disabled for age alone. | SS, HAR | — · — | Y | Q02·clk |
| E27-TC-210 | pos | US-ACCT-005 | TC-209 state | Set the policy to 180 days on SCR-128. | Every warning recomputes at once, with no reload and no 60 s wait: the 91-day key loses its red chip and its due date moves; the change is audited (SCR-128). No route for the policy is documented, so this runs through the UI (§10 DC-09). | SS, T, AUD | `admin.secrets_policy_changed` (before 90, after 180) · — | Y | manual |
| E27-TC-211 | neg | US-ACCT-005 | Key registered 80 days ago; scenario `compliant_far_expiry` (exchange expiry in 365 days) | Open SCR-125. | Amber chip: age counts from the registration date, never from the exchange expiry field (US-ACCT-005 NFR). | SS | — · — | — | Q02·clk |
| E27-TC-212 | neg | US-ACCT-005 | One key with scenario `expired_key` (exchange expiry passed); one key 91 days old | Run the self-check; `POST /orders` on each account. | The expired key's account is disabled for order placement (SR-034); the age-overdue account still trades (TC-209): expiry and age are not conflated. | HAR, SS, AUD | `account.disabled_by_policy` (expired key only) · +2 | — | Q02·clk |

---

## 4. Group D — Revoke, disable and delete (US-ACCT-006; E27-S04)

Screens `SCR-129`, `SCR-127` (revoke step), `SCR-079`, `SCR-125` row actions; the rules list
(`SCR-080`, `GET /rules`) is an observation point only. Endpoints `DELETE .../keys/{keyId}`,
`PATCH`/`DELETE /exchange-accounts/{accountId}`, `GET /positions`, `POST /positions/close-all`; WS
`revoked`. Audit `account.disabled`, `account.deleted` and the key events in §8.1.

**Shared setup:** `acct-demo-sub1` verified (`compliant`); `manager-with-grants` holds its `trade`
grant and has a WS session subscribed to `wallet`, `positions` and `orders` for it; two rules armed on
it and one on `acct-demo-sub2`.

<!-- prettier-ignore -->
| Case | Type | US | Preconditions · scenario | Steps | Expected result | Evidence | Audit · metric | KB | Auto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E27-TC-301 | pos | US-ACCT-006 | Shared setup; the account is flat with no orders | 1. SCR-125 → Revoke key; confirm; step-up. 2. Time confirm → inactive. 3. `GET .../keys`, `GET /exchange-accounts/{accountId}`, `LOG`, the manager's frames, `GET /rules`. | `204`; key `revoked`, `key_status: missing`, account inactive, private streams stopped. No request is signed with the key after the `204` (04 §5.14 KV14). The manager's subscriptions end with `revoked`, `reason: key_revoked` (23 §9.5), never silently emptied. Both bound rules are disarmed and the other rule is untouched. Elapsed time recorded ("in seconds", US-ACCT-006). | HAR, LOG, WS, SS, T, AUD | `key.revoked` · — | Y | Q02+manual |
| E27-TC-302 | pos | US-ACCT-006 | Shared setup plus one open BTCUSDT position with its native SL | 1. Revoke. 2. Choose "revoke and leave positions". 3. `GET /positions`; read `LOG`. | Before revoking, the position list and both choices are shown (US-ACCT-006). After "leave": key revoked; the position stays open with its native SL on the exchange, and the UI states that it was left open under that SL (per SCR-129 spec; confirm against E27-D02). | SS, HAR, LOG, AUD | `key.revoked` · — | Y | Q02+manual |
| E27-TC-303 | pos | US-ACCT-006 | As TC-302 | Choose "flatten first, then revoke". | Close-all for the account runs first and `GET /positions` is flat before the revoke (`LOG` order: close orders, then no further use of the key); then the key is revoked; both outcomes are shown. | HAR, LOG, SS, AUD | `position.flattened`, `key.revoked` · — | Y | Q02 |
| E27-TC-304 | neg | US-ACCT-006 | As TC-302 | `DELETE .../keys/{keyId}` with no position choice. | `409` with the consequence summary; the key is unchanged (#2417 SR-E27-06; the current contract is silent, §10 DC-07). | HAR | — · — | — | Q02 |
| E27-TC-305 | neg | US-ACCT-006 | As TC-302; scenario `close_rejected` | Choose "flatten first, then revoke". | The flatten failure is shown with the exchange's reason; the key is not reported revoked unless it was; the owner is offered the remaining choices (per SCR-129 spec; confirm against E27-D02). | SS, HAR, LOG | — · — | Y | Q02+manual |
| E27-TC-306 | neg | US-ACCT-006 | Account flat; scenario `key_delete_5xx` | Revoke (step-up). | Local deletion always happens: `204`, key `revoked`, it can no longer sign (US-ACCT-006 NFR). The contract and #2417 keep revocation local, so `LOG` should show no key-delete call and the UI tells the owner to revoke the key in the Bybit dashboard. If the build does call Bybit (the story's text), the exact error is shown with the same instruction (§10 DC-07). Usable key material left after a failed remote call is P0. | HAR, LOG, SS, AUD | `key.revoked` · — | Y | Q02 |
| E27-TC-307 | neg | US-ACCT-006 | A session with no live `keys` grant; then `manager-with-grants` | 1. Revoke. 2. The manager revokes the granted account's key. | 1: `403 step_up_required`; nothing revoked. 2: `403 forbidden`, no challenge. | HAR, AUD | `authz.denied` (step 2) · — | — | Q02 |
| E27-TC-308 | pos | US-ACCT-006 | Shared setup; account flat | 1. SCR-125 → Disable. 2. Read the dialog before typing. 3. Type the exact label; step-up; confirm. 4. Check the manager session, the rules and order entry. | `role="alertdialog"` with focus on Cancel, listing the consequences: open positions are not closed automatically (with a "flatten first" shortcut), working orders can be cancelled, the users who lose access, both rules by name, and that records are kept. The summary loads in ≤1 s and no confirm button shows before it (§0.2). After confirm: `enabled: false`, `connection_state: disabled`; both rules disarmed; `POST /orders` refused (403); the manager receives `revoked`, `reason: account_disabled`. | SS, A11Y, T, HAR, WS, AUD | `account.disabled` · — | Y | Q02+manual |
| E27-TC-309 | neg | US-ACCT-006 | As TC-308 | Type the label in another case, with a trailing space, and another account's label. | Confirm stays unavailable each time; nothing is sent and nothing changes. | SS, HAR | — · — | Y | Q02 |
| E27-TC-310 | neg | US-ACCT-006 | 1 open position and 2 working orders | 1. SCR-125 → Delete. 2. `DELETE /exchange-accounts/{accountId}` directly (step-up). | The dialog lists the blockers with counts and offers no delete confirm (SCR-129); the API answers `409 conflict`; nothing changes. | SS, HAR | — · — | Y | Q02 |
| E27-TC-311 | pos | US-ACCT-006 | Account flat, with order, execution and audit history | 1. Delete: typed label plus step-up. 2. `GET /exchange-accounts`; `GET /orders` and `GET /executions` for the account; `GET /admin/audit` for it. | `204`; the dialog stated that delete is irreversible and history is kept. The account is no longer active (the contract marks it `disabled`, the schema soft-deletes, §10 DC-10); its keys are revoked locally; its orders, executions and audit entries are still listed. | HAR, SS, AUD | `account.deleted` · — | Y | Q02 |
| E27-TC-312 | neg | US-ACCT-006 | TC-308 done | As the manager: `GET /exchange-accounts/{accountId}`; `sub` `wallet` for it. | REST `403 account_scope_denied` (or `404`, hidden by scope); WS `sub` → `account_scope_denied`; the earlier subscriptions had already ended with `revoked`. | HAR, WS | `authz.denied` · — | — | Q02 |
| E27-TC-313 | neg | US-ACCT-006 | Key revoked in TC-301 | Restart; let the start-up self-check run. | The key stays revoked and the account inactive; `LOG` shows no request with that key after the restart: local revocation is durable. | LOG, HAR | — · — | — | Q02+manual |

---

## 5. Group E — Health, balance and leverage (US-ACCT-008, US-ACCT-009, US-ACCT-010; E27-S05, E27-T04)

Screens `SCR-079`, `SCR-125`. Endpoints `GET /exchange-accounts`, `GET`/`PATCH
/exchange-accounts/{accountId}`, `GET /exchange-accounts/{accountId}/fee-rate`,
`PUT /positions/{positionId}/leverage`, `POST /orders`; WS `wallet`, `positions`, `system`. Metric
`cv_account_health_state` (per account: healthy, degraded, down). A health colour is always paired
with text (11 global AC 3).

<!-- prettier-ignore -->
| Case | Type | US | Preconditions · scenario | Steps | Expected result | Evidence | Audit · metric | KB | Auto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E27-TC-401 | pos | US-ACCT-008 | Verified account; scenario `compliant` | 1. Open SCR-079 from the account picker. 2. Compare with the scenario's wallet payload. 3. `GET /exchange-accounts/{accountId}`. | Equity, available balance, used margin, unrealised PnL, margin mode, position mode and leverage shown with units and a freshness timestamp; values equal the fixture payload. REST `balance.updated_at` is set and `balance_stale: false`. The heading names the account and environment; balances form a description list. | SS, A11Y, HAR, WS | — · — | Y | Q02 |
| E27-TC-402 | pos | US-ACCT-008 | Drawer opened once (warm cache) | Close and reopen SCR-079 five times. | Each open takes ≤100 ms from cache, then refreshes in place (§0.2). | T | — · — | Y | manual |
| E27-TC-403 | neg | US-ACCT-008 | Scenario `ws_auth_then_drop` | 1. Note the freshness time at T0 (last frame). 2. Wait 60 s. 3. Read `LOG`, SCR-079 and `GET /exchange-accounts/{accountId}`. | A REST wallet-balance reconciliation runs at T0 + 60 s and the freshness timestamp moves to it; the figures are not greyed (ticket AC 3). | LOG, SS, HAR | — · `cv_account_health_state` → degraded | — | Q02·clk+manual |
| E27-TC-404 | neg | US-ACCT-008 | Scenario `ws_drop_rest_fail` | Steps as in TC-403; this time the reconciliation fails. | Figures greyed with "stale since `<time of the last good snapshot>`" as text; `balance_stale: true` and `wallet` `stale: true` (ticket AC 3). The account also turns red (TC-410). | SS, HAR, WS | — · → down | Y | Q02·clk+manual |
| E27-TC-405 | neg | US-ACCT-008 | Scenario `ws_quiet_rest_fail` | 1. Wait 60 s plus the failed reconciliation. 2. Open the order ticket for the account. 3. `POST /orders` with risk-based sizing, then with a fixed quantity. 4. Switch to `compliant`. | "stale since" badge. Risk-based sizing is disabled for this account with the reason shown and refused server-side (C-2.12); fixed-quantity entry stays available, because the account is not red (its WS is healthy). After step 4 the badge clears and sizing returns. | SS, HAR | — · stays healthy | Y | Q02·clk+manual |
| E27-TC-406 | pos | US-ACCT-008 | Scenario `ws_quiet` | Wait 60 s; read `LOG` and SCR-079. | The REST truth-check runs at 60 s and the timestamp updates; the account stays green with no stale badge. | LOG, SS | — · stays healthy | — | Q02·clk |
| E27-TC-407 | neg | US-ACCT-008 | Scenario `ws_quiet` | `GET /exchange-accounts/{accountId}` 11 s and 61 s after the last wallet frame. | Contract: `balance_stale: true` once the snapshot is older than 10 s, `false` after the 60 s reconciliation. The UI does not grey the figures at 11 s (story). Recorded against §10 DC-12. | HAR, SS | — · — | — | Q02·clk |
| E27-TC-408 | pos | US-ACCT-010 | Scenario `compliant` | Keep SCR-125 and SCR-079 open 2 min. | Green "healthy" with text and the last heartbeat age, which never exceeds 10 s (§0.2); `connection_state: connected`. | SS, HAR | — · `cv_account_health_state` = healthy | Y | Q02 |
| E27-TC-409 | neg | US-ACCT-010 | Scenario `ws_auth_then_drop` | Watch SCR-125 and the rules list. | Amber "degraded — REST only"; rule actions that need sub-second reaction are flagged for this account; one polite live-region announcement for the change; `connection_state: degraded`. | SS, A11Y, HAR | — · → degraded | Y | Q02+manual |
| E27-TC-410 | neg | US-ACCT-010 | Scenario `ws_drop_rest_fail` from T0; a second, healthy account | 1. Watch until T0 + 30 s. 2. Open the order ticket for each account. 3. `POST /orders` for the red account. | By T0 + 30 s: `connection_state: disconnected` and the row red with text. Order entry is disabled for this account with the reason shown; the API refuses (403; nearest registry code `trading_disabled`, §10 DC-11) and `LOG` shows no order request. The other account still trades. The dead-man's switch is E45's (SR-059, E45-Q01). | SS, HAR, LOG, T | — · → down | Y | Q02·clk+manual |
| E27-TC-411 | neg | US-ACCT-010 | Scenario `ws_blip_20s` | Watch for 60 s. | Never red and order entry never disabled for a 20 s outage; amber is allowed. | SS, HAR | — · never down | — | Q02·clk |
| E27-TC-412 | pos | US-ACCT-010 | TC-410 state | Switch to `compliant`. | Back to green and order entry re-enabled; open orders and positions are reconciled before they are shown as live (03 §9.1); one announcement. | SS, HAR, LOG | — · → healthy | Y | Q02 |
| E27-TC-413 | pos | US-ACCT-010 | Three accounts; scenario `compliant` | Keep SCR-125 open 5 min with the network log recording. | Health fields are fetched on open and every 60 s, never per second; the browser never calls the exchange (SCR-125, SCR-128). | HAR | — · — | — | manual |
| E27-TC-414 | neg | US-ACCT-008 | `manager-with-grants` (grant on `acct-demo-sub1` only) | 1. `GET /exchange-accounts`. 2. `GET /exchange-accounts/{acct-demo-sub2}`. 3. WS `sub` `wallet` for sub2 alone, then for sub1 and sub2. | 1: sub1 only (reads narrow silently). 2: `403 account_scope_denied`. 3: error `account_scope_denied`, then `sub_ok.effective` = sub1. | HAR, WS, AUD | `authz.denied` · — | — | Q02 |
| E27-TC-415 | pos | US-ACCT-009 | Owner; open BTCUSDT position at 5x; scenario `leverage_ok`; profile cap 10x | Set 10x on the SCR-079 leverage slider and apply. | `PUT /positions/{positionId}/leverage` with `{"leverage": "10"}` → `200`; the drawer and the `positions` frame show 10. Risk-limit tiers are shown beside the choice (US-ACCT-009 NFR); the liquidation preview is text, announced politely (CMP-104); the change is audited (no catalogued event name, §10 DC-08). | HAR, SS, WS, A11Y, AUD | leverage change · — | Y | Q02 |
| E27-TC-416 | neg | US-ACCT-009 | As TC-415; scenario `leverage_refused_open_position` | Request 8x. | `502 exchange_error` carrying the exchange code and message. The UI shows the exact exchange reason (code in details) and the slider returns to 5x; the snapshot is unchanged. | HAR, SS | — · — | Y | Q02 |
| E27-TC-417 | neg | US-ACCT-009 | As TC-415 (cap 10x) | 1. Drag the slider past 10x. 2. `PUT /positions/{positionId}/leverage` with `{"leverage": "20"}` directly. | 1: refused client-side, with the cap stated. 2: refused server-side (`risk_limit_breached`, 403 in the registry, 422 in the contract example, §10 DC-11). `LOG` shows zero set-leverage requests; leverage unchanged. | HAR, SS, LOG | — · — | Y | Q02 |
| E27-TC-418 | neg | US-ACCT-009 | `manager-with-grants` (trade grant); a position on the granted account | `PUT /positions/{positionId}/leverage`. | `403` per 04 §7.2.2 row 18 (Owner only); nothing reaches the exchange. §7.2.1 and the story's "trader" persona disagree (§10 DC-15), so a `200` is raised as needs-clarification, not passed. | HAR, LOG, AUD | `authz.denied` · — | — | Q02 |
| E27-TC-419 | pos | US-ACCT-009 | No positions or orders on the account | `PATCH` with `margin_mode: isolated` (`If-Match`). | `200`; the drawer and CMP-128 show isolated. | HAR, SS | `account.updated` · — | Y | Q02 |
| E27-TC-420 | neg | US-ACCT-009 | One open position | `PATCH` with `margin_mode: cross`. | `409 conflict`; CMP-128 disabled with "cannot change margin mode with an open position."; mode unchanged. | HAR, SS | — · — | Y | Q02 |
| E27-TC-421 | neg | US-ACCT-009 | One working order | `PATCH` with `position_mode: hedge`. | `409 conflict`; CMP-129 disabled with its reason; mode unchanged. | HAR, SS | — · — | Y | Q02 |
| E27-TC-422 | pos | US-ACCT-008 | Verified account; scenario `compliant` | `GET .../fee-rate?symbol=BTCUSDT` twice within 15 min. | Maker and taker rates equal the fixture; the second answer carries the same `cached_at`; `LOG` shows one upstream call (15-minute cache). | HAR, LOG | — · — | — | Q02 |

---

## 6. Coverage matrix (US-ACCT-001..010 × cases × automation)

Computed from the case tables above; case numbers drop the `E27-TC-` prefix, and a case that
covers two stories appears under both. Every story has at least one positive and one negative or
failure case, and no case is marked "cannot be executed".

<!-- prettier-ignore -->
| Story | Title | Positive | Negative or failure | Automated (`Q02`, `Q02·clk`) | Automated plus a manual part | Manual only |
| --- | --- | --- | --- | --- | --- | --- |
| US-ACCT-001 | Register a Bybit account in the app | 001, 002, 004, 007, 011, 012, 013 | 003, 005, 006, 008, 009, 010 | 001, 002, 003, 004, 006, 007, 008, 009, 010, 011, 013 | 005, 012 | — |
| US-ACCT-002 | Store an API key with envelope encryption | 101 | 118, 119, 120, 121, 131 | 119, 121, 131 | 101, 118 | 120 |
| US-ACCT-003 | API key self-check | 012, 101, 116, 124 | 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 117, 122, 123, 125, 126, 127, 128, 129, 130 | 102, 103, 104, 106, 107, 108, 109, 110, 111, 112, 116, 117, 122, 123, 124, 125 | 012, 101, 105, 126, 127, 128, 129, 130 | — |
| US-ACCT-004 | Key rotation with overlap | 201, 202, 203 | 204, 205, 206 | 202, 203, 204, 205, 206 | 201 | — |
| US-ACCT-005 | Key rotation policy reminder | 207, 210 | 208, 209, 211, 212 | 207, 208, 209, 211, 212 | — | 210 |
| US-ACCT-006 | Revoke a key immediately | 301, 302, 303, 308, 311 | 304, 305, 306, 307, 309, 310, 312, 313 | 303, 304, 306, 307, 309, 310, 311, 312 | 301, 302, 305, 308, 313 | — |
| US-ACCT-007 | Environment binding per account | 114 | 113, 115 | 113, 114, 115 | — | — |
| US-ACCT-008 | Account balance & margin snapshot | 401, 402, 406, 422 | 403, 404, 405, 407, 414 | 401, 406, 407, 414, 422 | 403, 404, 405 | 402 |
| US-ACCT-009 | Leverage and margin mode control | 415, 419 | 416, 417, 418, 420, 421 | 415, 416, 417, 418, 419, 420, 421 | — | — |
| US-ACCT-010 | Account health & connection state | 408, 412, 413 | 409, 410, 411 | 408, 411, 412 | 409, 410 | 413 |

Totals: 91 cases, 30 positive and 61 negative or failure; 66 automated, 21 automated with a manual part, 4 manual only.

## 7. Negative and abuse-adjacent cases owned by QA, and the R3 gate

Deeper adversarial work (timing side channels, races between rotate and revoke, concurrent sessions,
malformed exchange payloads) belongs to E27-X02; the full route × role matrix to E27-X03.

| Behaviour                                          | Cases                             | Note                                                               |
| -------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------ |
| Withdrawal or transfer right at intake             | 102, 103, 112                     | C-2.8 names both rights; the contract example does not (§10 DC-01) |
| Allowlist missing, mismatched, foreign or wildcard | 104, 105, 106                     | Mandatory in every environment                                     |
| Wrong UID, wrong environment, non-UTA              | 107, 108, 113                     | `LOG` proves no live-host contact                                  |
| Clock skew, failed probe, 5xx, `10018`             | 109, 110, 122, 123                | Never persisted, never a `500`                                     |
| Permission drift after storage; inconclusive check | 126, 127, 128, 129                | System read-only per C-12.2                                        |
| Secret never revealed or echoed                    | 118, 119                          | P0 rule (§0.1)                                                     |
| KEK unavailable                                    | 120                               | Read-only start                                                    |
| Double submit                                      | 121                               | One key only                                                       |
| Rotation to a hostile key                          | 204                               | Old key stays primary                                              |
| Step-up and RBAC on writes and scoped reads        | 008, 131, 206, 307, 312, 414, 418 | Samples only; matrix in E27-X03                                    |
| Revoked key still signing or resurrected           | 301, 306, 313                     | Local revocation authoritative and durable                         |
| Cross-environment contact                          | 113, 115                          | C-2.11                                                             |
| Leverage cap bypass                                | 417                               | Refused before any exchange call                                   |

| R3 exit criterion (30 §7.3)                                               | Black-box evidence in this plan             | Owned elsewhere                                      |
| ------------------------------------------------------------------------- | ------------------------------------------- | ---------------------------------------------------- |
| #9 no API path returns a secret                                           | 118, 119                                    | Leak-assertion suite: E27-X02                        |
| #9 KEK separation demonstrated                                            | 120 (no KEK → read-only, nothing signs)     | Restore drill on a database without the KEK: E27-X04 |
| #9 every key verified withdrawal-OFF and IP-whitelisted by the self-check | 102–106, 124, 126–129                       | —                                                    |
| #10 every route × role denied with 403, no state change and an audit row  | 008, 131, 206, 307, 312, 414, 418 (samples) | Full matrix: E27-X03                                 |

## 8. Audit completeness, metrics and accessibility

### 8.1 Audit events

The ticket, the screens and `04-security-program.md` §8.2 name these events differently (§10 DC-08).
Until one registered vocabulary is published (SR-E27-09), the audit step passes when exactly one new
entry exists for the subject with the right actor and either name below; record which name appeared.
A missing or malformed entry is filed against the acting case (§0.1).

| Ticket or screen name                              | 04 §8.2 name                                            | Cases                             |
| -------------------------------------------------- | ------------------------------------------------------- | --------------------------------- |
| `account.created`                                  | `account.registered`                                    | 001, 002, 004, 007, 012, 013      |
| `account.updated` (key attached)                   | `key.created` and `key.verified`                        | 012, 101, 116, 117, 119, 121, 130 |
| `account.updated` (label, margin or position mode) | none catalogued                                         | 011, 419                          |
| `account.tested`                                   | `key.verified` / `key.verification_failed`              | 124, 125                          |
| `account.key_rotated`                              | `key.rotated`                                           | 201, 205                          |
| `account.disabled`                                 | none catalogued                                         | 308                               |
| `account.deleted`                                  | `account.removed`                                       | 311                               |
| `account.disabled_by_policy`                       | `key.disabled_for_trading`                              | 126, 127, 128, 129, 212           |
| none in the ticket                                 | `key.verification_failed`                               | 102–113, 119, 122, 123, 204       |
| none in the ticket                                 | `key.revoked` (`key.retired` at drain end)              | 202, 203, 301, 302, 303, 306      |
| none in the ticket                                 | `key.expiry_warning`                                    | 116                               |
| `admin.secrets_policy_changed` (SCR-128)           | `setting.changed`                                       | 210                               |
| none in the ticket                                 | `authz.denied`                                          | 008, 131, 206, 307, 312, 414, 418 |
| none in the ticket                                 | `position.flattened`                                    | 303                               |
| none in the ticket                                 | none catalogued for a leverage change (US-ACCT-009 NFR) | 415                               |

### 8.2 Metrics

Read `GET /metrics` before and after the case. Label values follow the E27-T03 and E27-T04 metric
definitions.

| Metric                      | Must move in                                        | Expected movement                                                              |
| --------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------ |
| `cv_key_verification_total` | 012, 101–113, 116, 117, 121–130, 201, 204, 205, 212 | +1 per verification run, as pass or fail                                       |
| `cv_account_health_state`   | 115, 403–406, 408–412                               | Per account: healthy → degraded → down and back, matching the row's text state |

### 8.3 Accessibility

`KB = Y` cases are also executed keyboard-only. The KB-critical paths are revoke and disable
(301, 302, 303, 306, 308, 309), the step-up dialog reached from every write, and the copy control for
the egress IP (105). Every state in this plan is asserted as text and never as colour alone (chips,
health states, verification results), following 11 global AC 3 and CMP-175's explicit "Withdrawal:
OFF" rule. Live-region checks (013, 409, 412, 415) are smoke checks only: the screen-reader protocol
run belongs to E27-Q04. A `KB = Y` case that needs a pointer is a defect (§0.1).

## 9. Test data and fixture appendix

### 9.1 Users

| Fixture                  | Role    | Grants                                                                              | Source                                                |
| ------------------------ | ------- | ----------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `owner-enrolled`         | Owner   | All accounts                                                                        | E09 seed (`qa/plans/e09-auth-rbac-test-plan.md` §6.1) |
| `manager-with-grants`    | Manager | `trade` on `acct-demo-sub1`, set in setup with `PUT /users/{userId}/account-access` | E09 seed plus setup                                   |
| `manager-without-grants` | Manager | None                                                                                | E09 seed                                              |
| `viewer-granted`         | Viewer  | View on `acct-demo-sub1`                                                            | Created in setup (invite, then grant)                 |

### 9.2 Accounts

UIDs are fabricated (`9000xxxx`); labels are fixed so the typed-confirmation cases are deterministic.

| Alias                                | Environment | Kind | UID                    | Label                  | Created by                                    |
| ------------------------------------ | ----------- | ---- | ---------------------- | ---------------------- | --------------------------------------------- |
| `acct-demo-main`                     | demo        | main | `90000001`             | `QA Main`              | TC-001 or setup                               |
| `acct-demo-sub1`                     | demo        | sub  | `90000011`             | `QA Sub 1`             | TC-002 or setup                               |
| `acct-demo-sub2` .. `acct-demo-sub5` | demo        | sub  | `90000012`..`90000015` | `QA Sub 2`..`QA Sub 5` | Setup (TC-005 needs five subs)                |
| `acct-live-main`                     | live        | main | `90000001`             | `QA Main (live)`       | TC-004; account shell only, never given a key |

### 9.3 Fault-injection scenarios (PR 2)

PR 2 implements one directory per scenario under `packages/fixtures/accounts/`, each with a
`manifest.json` naming the scenario, the endpoints it stubs and the expected outcome, selected by name
(`CV_ACCOUNT_FIXTURE=<scenario>`). Scenarios the ticket requires, by name or as one of its
verification verdicts, are marked `ticket`; the rest are this plan's additions. Rules for every
scenario:

- Payload shapes come from redacted recordings, never invented (C-13.5); error codes and messages are
  copied from recorded captures.
- Fabricated values only: UIDs `9000xxxx`; key ids `fixture-<scenario>-NNNN` (hyphenated, so they
  can never look like a real Bybit key, and ending in four alphanumerics for the masked tail); secrets
  `fixture-<scenario>-secret-not-real`; RFC 5737 addresses, with egress `203.0.113.10`.
- A scenario can be switched for a stored key at runtime (needed by 126–129, 204 and 212).
- "As `compliant`" means the `compliant` answers for everything the row does not change.

<!-- prettier-ignore -->
| Scenario | Origin | The stub must return | Cases |
| --- | --- | --- | --- |
| `compliant` | ticket (verdict) | `query-api`: trade scopes only, empty `Wallet`, `ips` = egress, UTA, UID = the account's, no expiry, created over 48 h ago. `wallet-balance`: `retCode` 0 within `recv_window`. Private WS: auth ok, a wallet snapshot, then a frame every 5 s; pongs. `fee-rate`, `set-leverage`, order and position calls succeed. | 012, 101, 114, 124, 401, 408, 413, 422, and setup |
| `compliant_alt` | plan | As `compliant`, with a second key id | Via `rotation_ok` |
| `withdraw_enabled` | ticket | `query-api` lists `Withdraw` under `Wallet` | 102, 119, 126 |
| `transfer_enabled` | plan | `query-api` lists `AccountTransfer` under `Wallet` | 103 |
| `ip_missing` | ticket | `ips` empty | 104, 128 |
| `ip_mismatch` | ticket | `ips` = `198.51.100.20` | 105, 127 |
| `ip_extra_foreign` | plan | `ips` = egress and `192.0.2.30` | 106 |
| `uid_mismatch` | ticket | `query-api` reports UID `90000099` | 107 |
| `non_uta` | ticket | `query-api` reports a non-UTA account | 108 |
| `clock_skew` | ticket | `wallet-balance` fails on `recv_window` (recorded `10002` capture) with a server time 6 s off | 109 |
| `wallet_probe_error` | ticket | `wallet-balance` returns a recorded non-zero `retCode` on every call | 110 |
| `missing_trade_scope` | plan | No contract `Order`/`Position` scopes | 111 |
| `extra_scope` | plan | `Spot`, `Options` or `Exchange` scopes present | 112 |
| `live_key_on_demo` | ticket (verdict) | Demo hosts reject the key id as unknown (recorded invalid-key capture); live hosts must never be called | 113 |
| `demo_ws_unreachable` | plan | REST as `compliant`; the demo private WS refuses connections | 115 |
| `expiring_13d` / `expiring_15d` | ticket (verdict) | Expiry 13 / 15 days ahead | 116 / 117 |
| `expired_key` | plan | Expiry 1 day in the past | 212 |
| `compliant_far_expiry` | plan | Expiry 365 days ahead | 211 |
| `new_key_48h` | ticket | Key created 2 h ago, plus the recorded 48 h restriction response | 130 |
| `bybit_5xx` | ticket | HTTP 503 on every REST call | 122, 129 |
| `rate_limited_10018` | ticket | Recorded `10018` response with its rate-limit headers | 123 |
| `ws_auth_timeout` | plan | REST as `compliant`; the private WS never answers `auth` | 125 |
| `ws_auth_then_drop` | ticket | WS: auth ok, one wallet snapshot, then the connection drops and reconnects are refused; REST healthy | 403, 409 |
| `ws_quiet` | plan | WS connected with pongs but no wallet frame after the snapshot; REST healthy | 406, 407 |
| `ws_quiet_rest_fail` | plan | `ws_quiet` plus `wallet_probe_error` | 405 |
| `ws_drop_rest_fail` | plan | `ws_auth_then_drop` plus HTTP 503 on every REST call | 404, 410, 412 |
| `ws_blip_20s` | plan | WS dropped and REST failing for 20 s, then everything recovers | 411 |
| `rotation_ok` | plan | Old key `compliant`, new key `compliant_alt` | 201, 202, 203, 205 |
| `rotation_new_key_withdraw` | plan | Old key `compliant`, new key `withdraw_enabled` | 204 |
| `key_delete_5xx` | plan | As `compliant`; any Bybit key-delete endpoint answers HTTP 503 | 306 |
| `close_rejected` | plan | As `compliant`; the position close is rejected (recorded capture) | 305 |
| `leverage_ok` | plan | `set-leverage` `retCode` 0 | 415 |
| `leverage_refused_open_position` | plan | `set-leverage` refused with the recorded open-position reason | 416 |

### 9.4 Step-up procedure

On `403 step_up_required`, call `POST /auth/step-up` with the password, a code from `totp_gen`
(E09 plan §6.2) and the `challenge_id`, then re-send the held request unchanged (same body and
`Idempotency-Key`). Key and account actions use a grace class: a second action within 5 minutes may
not be challenged again. Cases that assert the challenge (001, 206, 307) therefore start from a session
without a live grant: sign in fresh or let the grace expire.

### 9.5 Clock control

The E09 frozen clock (E09 plan §6.3) is refused while an exchange key is present (#2086), so it cannot
drive E27. Day-scale cases (`Q02·clk`: key age, daily alerts, the hourly self-check, the 15-minute
drain) need a test clock that works with stub keys. PR 2's loader must provide it for automation, and
the stub-transport follow-up for manual runs; until then these cases run in E27-Q02 only.
Second-scale cases (30 s, 60 s) may be stopwatched in manual runs (§0).

### 9.6 Stub request log

Every stub answer is logged with timestamp, host and environment, method, path, the fabricated key id
that signed the request, whether the signature verified against the scenario secret, and the scenario
name. Cases assert on it (`LOG`): host isolation (113–115), signing key (201–203, 301, 313), absence
of exchange calls (124, 205, 306, 410, 417) and upstream call counts (123, 422). It holds no real
secret, but it is still never pasted into a public issue (§0.1).

## 10. Documentation conflicts found while authoring

The plan follows the source named in the "Plan follows" column. Rows marked #2417 are already tracked
by the contract-first alignment issue; the rest are new and need an owner decision or a docs fix
before E27-Q02 automates the affected cases.

<!-- prettier-ignore -->
| Id | Conflict | Plan follows | Cases | Tracked |
| --- | --- | --- | --- | --- |
| DC-01 | C-2.8 and SR-030a refuse transfer rights and 21 §3.2.2 refuses them too, but `createApiKey` checks only `Withdraw` and its `201` example stores `Wallet: [AccountTransfer]`; the extra-scope rule is in SR-030a only | C-2.8, SR-030a | 103, 112 | #2417 |
| DC-02 | SR-005 allows at most 4 clear characters of a key id; the contract's `key_id_masked` shows the first 4 and the last 4 | SR-005 | 101, 118 | #2417 |
| DC-03 | C-2.8 and C-12.2 require an allowlist on every key; the contract makes `require_ip_whitelist` default on for live only and says the egress IP must be "inside" the list, where SR-030a says the list must equal it; SCR-125 shows "n/a" for a demo row | C-2.8, SR-030a | 104, 106 | #2417 |
| DC-04 | A failed stored-key check puts the whole system read-only in C-2.8 and C-12.2, force-disables one account in US-ACCT-003, and disables one credential in SR-032 | C-12.2 | 126–129 | new |
| DC-05 | Self-check cadence: hourly (C-12.2), every 6 h (US-ACCT-003 NFR, SR-031), nightly (`createApiKey`) | C-12.2 | 126, 127 | new |
| DC-06 | Rotation overlap: 15 min (US-ACCT-004), 900 s grace (21 §3.2.3), `overlap_seconds` default 300 (contract), 24 h (SR-035, ADR-0009 design item 5) | US-ACCT-004 | 201, 202 | #2417 |
| DC-07 | US-ACCT-004 and US-ACCT-006 attempt a Bybit revoke or delete; the contract revokes locally only, and #2417 keeps that because a compliant key cannot delete itself at Bybit; the open-position choice is missing from the contract | Contract (local only) with both outcomes recorded | 202, 304, 306 | #2417 |
| DC-08 | Audit vocabulary differs between the ticket and screens (`account.*`), 04 §8.2 (`account.registered`, `key.*`) and the audit route's examples (`key.rotate`); no event exists for a leverage change, and the ticket's list has none for a revoke | §8.1 mapping | All with audit | new (SR-E27-09) |
| DC-09 | The key-age policy (US-ACCT-005, SCR-128) has no documented route or setting; SR-037 sets 180 days for demo keys while the story assumes 90 | UI only; policy set explicitly | 207–212 | new |
| DC-10 | SCR-129 makes delete irreversible and separate from disable; the contract's `DELETE` "marks it `disabled`"; 21 §3.2.1 soft-deletes | Observable outcome only | 308, 311 | new |
| DC-11 | `createApiKey` documents no 429 although `exchange_rate_limited` is 429; `risk_limit_breached` is 403 in the registry but 422 in the `UnprocessableEntity` example; `trading_disabled` covers only the kill switch and live enablement, so no code exists for a red, disabled or key-policy refusal | Registry | 123, 410, 417 | new |
| DC-12 | The contract flags `balance_stale` after 10 s; US-ACCT-008 reconciles after 60 s of silence and greys the figures only when that fails. Bybit's wallet stream is change-driven, so a quiet, healthy account is flagged stale by the contract rule | Both, asserted separately | 403–407 | new |
| DC-13 | No per-account health push is documented: `system` carries one global `private_ws` state, `connection_state` is REST-only, and SCR-125 refreshes every 60 s, so the ≤30 s red deadline (US-ACCT-010) cannot be met on SCR-125 as specified | Deadline asserted on REST and order entry | 408–413 | new |
| DC-14 | US-ACCT-009 sets per-symbol leverage, but the contract only offers `PUT /positions/{positionId}/leverage`, which needs an open position; 18 §2.2 lists it as `PATCH` | Contract | 415–418 | new |
| DC-15 | Leverage RBAC: 04 §7.2.2 row 18 allows only the Owner, while §7.2.1 grants `positions:write` to a Manager with a trade grant and US-ACCT-009's persona is "a trader" | 04 §7.2.2 | 418 | new |
| DC-16 | Duplicate-UID copy: "This UID is already registered as `<label>`" (US-ACCT-001) against "This Bybit UID is already connected as `'<label>'`." (SCR-126) | Message names the label | 003 | new |
| DC-17 | US-ACCT-001 lets the owner acknowledge the cap and add a sixth sub-account; the contract rejects the sixth with `conflict` and has no acknowledgement field | Contract | 005 | new |
| DC-18 | SR-030 stores a failing credential "disabled with a blocking banner"; the contract, 30 §7.2 and the ticket never persist a rejected key | Contract | 102–113 | new |
| DC-19 | 04 §7.2.1 requires step-up for `accounts:write` (SR-E27-02), but the `action_class` enum (`keys`, `users`, `live_enablement`, `killswitch`, `risk_caps`) has no class for account routes and the routes do not say which applies | 04 §7.2.1 | 001, 011, 308, 311 | new |
| DC-20 | `setUserAccountAccess` closes subscriptions with an `unsubscribed` frame that `23-ws-protocol.md` does not define; §9.5 uses `revoked` | 23 §9.5 | 301, 308, 312 | new |
| DC-21 | Story references: SCR-129 cites US-ACCT-008 in its validation line (disable and delete are US-ACCT-006); SCR-126 cites `US-SEC-004`, and no SEC domain exists in 11; SCR-127 cites US-ACCT-003; the ticket cites 21 "§3.13", which is §3.1.3 | Story text | — | new |
| DC-22 | CMP-034 is a "secret reveal" component with a reveal toggle, CMP-033 lists "API key display", and SCR-126 and SCR-127 use CMP-034, against US-ACCT-002's "no reveal control anywhere" | US-ACCT-002 | 118 | #2417 (reveal scope) |
| DC-23 | ADR-0009 describes a ~48 h cooldown before a new account can create keys, and rotation that creates the new key through the Bybit API; SCR-125/126/127 describe a 48 h restriction on new keys and a key the owner creates by hand | Screens | 130, 201 | new |
| DC-24 | US-ACCT-010 invokes the dead-man's switch on red; SR-059 says Bybit's switch is inverse-only and E45-T05 owns an opt-in integration | Deferred to E45-Q01 | 410 | new |

## 11. Dry-run execution record

**Status: pending, not executed.** The ticket asks for a dry run in which each scenario is loaded once
against the running demo stack and confirmed to produce the state it claims, with the log committed
beside this plan. It cannot start yet. The routes arrive with E27-T03 (#836), E27-T04 (#837) and
E27-S01..S05 (#895–#899), which wait on the contract alignment (#2417); the scenarios arrive with
PR 2 and the stub-transport follow-up. No result below is fabricated. Rows are appended as each
dependency lands, never overwritten; a case whose dependency is missing is recorded as
`blocked-pending-dependency`, never as a pass.

| Group or cases                               | Build sha | Environment       | Scenario    | Result                                       | Evidence | Defect |
| -------------------------------------------- | --------- | ----------------- | ----------- | -------------------------------------------- | -------- | ------ |
| Scenario load check: each §9.3 scenario once | —         | demo stack + stub | all         | pending (PR 2, stub transport)               | —        | —      |
| A: 001–013                                   | —         | demo              | `compliant` | pending (E27-S01)                            | —        | —      |
| B: 101–131                                   | —         | demo + stub       | per case    | pending (E27-S02, E27-T03, PR 2)             | —        | —      |
| C: 201–212                                   | —         | stub              | per case    | pending (E27-S03, E27-T04, PR 2, §9.5 clock) | —        | —      |
| D: 301–313                                   | —         | demo + stub       | per case    | pending (E27-S04, PR 2)                      | —        | —      |
| E: 401–422                                   | —         | demo + stub       | per case    | pending (E27-S05, E27-T04, PR 2)             | —        | —      |

## 12. Sign-off

- [ ] Peer review by a second QA/SDET. No second human QA exists: under the owner's agent-delivery
      adaptations (decision 2026-09-25, recorded on the E27 tickets) an independent reviewer agent
      substitutes, and the owner's `approved` comment or merge records the sign-off. **Pending.**
- [ ] Dry run recorded with pass or fail and evidence per case (§11). **Pending.**
- [x] Every `US-ACCT-001..010` has at least one positive and one negative or failure case (§6), and
      no case is marked "cannot be executed".
- [x] Implementation-independent: no case names an internal function, module path or private field.
- [x] No live exchange in any case and no wall-clock sleep in automation (§0, §9.5).
- [ ] The fixture pack (PR 2) implements every scenario in §9.3. **Pending.**
- [ ] QA sign-off comment on epic E27 (#54), after E27-Q05. **Pending.**
