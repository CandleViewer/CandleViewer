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
  `/exchange-accounts/{accountId}/keys`. Observation and setup routes: `/admin/audit`,
  `/admin/capacity`, `/admin/support-bundle`, `/notifications`, `/onboarding/checklist`, `/orders`,
  `/positions`, `/positions/close-all`, `/executions`, `/rules`, `/users/{userId}/account-access`.
- **WS** (`docs/plan/23-ws-protocol.md` §6.2, §9.5, §10.2): private topics `wallet`, `positions`,
  `system`; `revoked` reasons `key_revoked`, `account_disabled`, `account_scope_changed`; error
  `account_scope_denied`.
- **Documented behaviour:** `docs/plan/21-database-schema.md` §3.2, §3.1.3 (the ticket's "§3.13")
  and §3.9 (the sub-account tier setting), ADR-0009, ADR-0010, `docs/plan/04-security-program.md`
  (SR ids, §5.14, §7.2, §8.2), the E27 threat model `docs/security/threat-models/E27-accounts.md`
  (SR-E27 ids, AC-13 to AC-15), `docs/plan/03-testing-strategy.md` and
  `docs/plan/30-release-roadmap.md` §7.3 (R3 exit criteria #9 and #10).

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
  `GET /admin/audit?subject_type=<exchange_account|api_key>&subject_id=<id>`; expect each event the
  case lists exactly once for its subject, under a name in §8.1, and no secret in the payload". The
  actor is the acting user (`actor_user_id`), except events marked `(system)`: time- or
  policy-driven events with no acting user, which carry `actor_user_id: null` (SR-062
  `actor_type: system`). A case that triggers several actions lists every event and every metric
  movement, with the step that causes it.
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
| **Visible secret material**: an API secret, more than 4 clear characters of a key id (SR-005; the pending last-4-only rule is SR-E27-03, #2417), a signature or KEK/DEK material in any UI state, API response, WS frame, error body, audit payload, metrics output, support bundle or download | **`priority/p0-critical` regardless of any other impact.** Report privately (`SECURITY.md` §1, GitHub Private Vulnerability Reporting), never in a public issue; name the scenario, never paste the string |
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
| REST reconciliation no later than 60 s after the last wallet frame | US-ACCT-008 | E27-TC-403, E27-TC-406 | `LOG` timestamps |
| Red ≤30 s after WS and REST both fail; heartbeat age ≤10 s while healthy | US-ACCT-010 | E27-TC-410, E27-TC-408 | `connection_state` and the order refusal by `HAR` + `LOG` timestamps; the SCR-125 row at its next 60 s refresh (§10 DC-13) |

---

## 1. Group A — Registration (US-ACCT-001; E27-S01)

Screens `SCR-125`, `SCR-126`, `SCR-016` (step 3), `SCR-019`. Endpoints `GET`/`POST /exchange-accounts`,
`GET`/`PATCH /exchange-accounts/{accountId}`, `POST /auth/step-up`, `GET /me`. Audit `account.created`,
`account.updated`. Registration never handles a secret and attaches no key, so cases need no
scenario unless they name one. Actor `owner-enrolled` unless stated.

<!-- prettier-ignore -->
| Case | Type | US | Preconditions · scenario | Steps | Expected result | Evidence | Audit · metric | KB | Auto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E27-TC-001 | pos | US-ACCT-001 | No accounts | 1. SCR-125 → "+ Add account". 2. Label `QA Main`, UID `90000001`, kind main, environment Demo. 3. Save; answer the step-up (§9.4). 4. `GET /exchange-accounts`. | First save → `403 step_up_required` with a non-empty, server-composed `action_summary` that names the environment `demo` and UID `90000001` bare. The label is expected only if the E27-S01 route template quotes it, escaped per the contract: a new account's label is request text, not a server-resolved label (`POST /auth/step-up`; `accounts:write` needs step-up, 04 §7.2.1; §10 DC-19). The re-sent save → `201` with `environment: demo`, `kind: main`, `parent_account_id: null`. The row reads "no key — inactive" as text (US-ACCT-001; the SCR-125 spec has no key-less state, confirm against E27-D02) and shows no balance. | HAR, SS, AUD | `account.created` · — | Y | Q02 |
| E27-TC-002 | pos | US-ACCT-001 | TC-001 done | Add a sub-account: label `QA Sub 1`, UID `90000011`, kind sub, parent `QA Main`, Demo; step-up. | `201` with `parent_account_id` = QA Main; listed as a sub of QA Main, "no key — inactive". | HAR, SS, AUD | `account.created` · — | Y | Q02 |
| E27-TC-003 | neg | US-ACCT-001 | TC-001 done | Register UID `90000001` again in Demo as `QA Dup`. | `409 conflict`; the message names the existing label (US-ACCT-001: "This UID is already registered as `<label>`"; SCR-126 words it differently, §10 DC-16); no second row; no `account.created`. | HAR, SS, AUD | — · — | Y | Q02 |
| E27-TC-004 | pos | US-ACCT-001 | TC-001 done | Register UID `90000001` with environment Live as `QA Main (live)`. | `201`: a UID may be registered once per environment (21 §3.2.1). Both rows listed, each with its environment as text, demo and live visibly grouped (SCR-125). Account shell only: this plan never attaches a key to a live-bound row. | HAR, SS, AUD | `account.created` · — | Y | Q02 |
| E27-TC-005 | neg | US-ACCT-001 | `accounts.subaccount_tier` recorded as `regular` in setup (no documented write route, §10 DC-17), so `GET /admin/capacity` shows `subaccounts` with `tier: regular`, `cap: 5`, `tier_source: recorded`; five live sub-account shells under `QA Main (live)` (§9.2), so `used: 5` (the cap binds live UIDs per main, `SubaccountCapacity`) | 1. Start adding a sixth live sub under `QA Main (live)`. 2. Try to save without acknowledging. 3. Acknowledge and save. 4. `GET /admin/capacity`. | Step 1 shows the cap "5 regular / 20 Business KYC" with the recorded tier stated (US-ACCT-001, US-ADMIN-014). Step 2: save unavailable until the explicit acknowledgement (US-ACCT-001; per SCR-125/SCR-126 spec, confirm against E27-D02). Step 3: `409 conflict` (the contract rejects the 6th and has no acknowledgement field, §10 DC-17). Step 4: `used` stays 5. | HAR, SS | — · — | Y | Q02+manual |
| E27-TC-006 | neg | US-ACCT-001 | TC-001 done | Register a demo account labelled `qa main`, UID `90000002`. | Rejected with a 4xx problem naming `label`: labels are unique per environment, ignoring case (21 §3.2.1); no row. | HAR | — · — | Y | Q02 |
| E27-TC-007 | pos | US-ACCT-001 | TC-001 done | Register a live account labelled `QA Main`, UID `90000003`. | `201`: the same label is allowed in the other environment. | HAR | `account.created` · — | — | Q02 |
| E27-TC-008 | neg | US-ACCT-001 | `manager-with-grants`, then `viewer-granted` | 1. `GET /me`. 2. Open `/admin/accounts`. 3. `POST /exchange-accounts` with a valid body. | 1: no `accounts:write`. 2: SCR-154 permission denied, no add control (hiding is not the control). 3: `403 forbidden` with `required_permissions: [accounts:write]`, no step-up challenge (RBAC is decided first, `/auth/step-up`), nothing created, denial audited (11 global AC 1). Same for the viewer. | HAR, SS, AUD | `authz.denied` · — | Y | Q02 |
| E27-TC-009 | neg | US-ACCT-001 | — | `POST /exchange-accounts` with: a) UID `12a4`; b) UID `123`; c) empty label; d) an 81-character label; e) kind sub without a parent; f) an extra property `acknowledged: true`. Repeat a–e in the SCR-126 form. | Each `422 validation_failed` naming the field (422 is the status `createExchangeAccount` documents; the registry lists 400, §10 DC-11; f: unknown property refused); nothing created; the form shows each error inline, linked to its field (CMP-040). | HAR, SS, A11Y | — · — | Y | Q02 |
| E27-TC-010 | neg | US-ACCT-001 | `QA Main (live)` from TC-004 | Register a demo sub-account whose parent is `QA Main (live)`. | Rejected, no row: a sub-account's environment must equal its parent's (21 §3.2.1, C-2.11). | HAR | — · — | — | Q02 |
| E27-TC-011 | pos | US-ACCT-001 | TC-001 done | 1. Rename `QA Main` to `QA Main A` (`PATCH` with `If-Match`; step-up). 2. `PATCH` carrying `exchange_uid` or `environment`. | 1: `200`; the new label shows on SCR-125 and in the drawer heading. 2: refused with a `validation_failed` problem naming the field, nothing changed (the request schema has neither field: UID and environment never change after registration). `updateExchangeAccount` documents neither 400 nor 422, so the status is recorded, not asserted (§10 DC-11). | HAR, SS, AUD | `account.updated` (label before/after) · — | Y | Q02 |
| E27-TC-012 | pos | US-ACCT-001, US-ACCT-003 | Empty install, Owner first run; scenario `compliant` | 1. Onboarding (SCR-016) to step 3. 2. Check the environment default. 3. Enter label, key and secret; Test connection. 4. Continue. | Demo preselected with "Live needs step-up later"; Continue disabled until the test passes; the result is a list ("read ok - trade ok - no-withdraw ok"); after Continue the account exists and its key is verified; the secret is never echoed after save. The stepper is a `<nav>` with `aria-current="step"`; focus moves to the step heading (per SCR-016 spec). | SS, A11Y, HAR, AUD | `account.created`, `account.updated` · `cv_key_verification_total` +1 pass per verification run, no fail (§8.2) | Y | Q02+manual |
| E27-TC-013 | pos | US-ACCT-001 | Empty install | 1. On step 3 choose "Skip for now"; finish the wizard. 2. Open the setup checklist (SCR-019; `GET /onboarding/checklist`). 3. Follow the "add a live account" task's link and register a live account shell as in TC-004 (no key). 4. `GET /onboarding/checklist` again. | The skip creates nothing. SCR-019 lists "add a live account" as pending with a deep link to the add-account screen; after step 3 that task shows done, announced politely (per SCR-019 spec; confirm against E27-D02). The contract's checklist has no such item (`items[].key` is one of `tailscale`, `totp`, `sub_account`, `api_key`, `profile_limits`, `demo_session`), so step 4 asserts only that the body matches `OnboardingChecklist` and records which item changed state, if any (§10 DC-25). | SS, A11Y, HAR | `account.created` · — | Y | Q02 |
| E27-TC-014 | pos | US-ACCT-001 | As TC-005, with the tier recorded as `business_kyc` (`cap: 20`) | 1. Add a sixth live sub (acknowledging if asked). 2. Seed to 20 live subs; add a 21st. 3. `GET /admin/capacity`. | 1: `201`; the cap shown is 20, with the recorded tier stated. 2: `409 conflict`. 3: `used: 20`, `cap: 20`. The contract's "rejects the 6th" is read against the recorded tier (`SubaccountCapacity`, §10 DC-17). | HAR, SS | `account.created` (step 1) · — | — | Q02 |
| E27-TC-015 | neg | US-ACCT-001 | No tier recorded; five live subs as in TC-005 | 1. `GET /admin/capacity`. 2. Open the add-account screen. 3. Add a sixth live sub. | 1: `tier: null`, `cap: null`, `tier_source: unrecorded`. 2: the screen states that no tier is recorded and never shows an inferred tier or cap (21 §3.9, US-ADMIN-014 NFR; per SCR-125 spec, confirm against E27-D02). 3: `409 conflict`: until the owner decides, the plan reads the contract's unqualified 6th rejection as the default (§10 DC-17). | HAR, SS | — · — | Y | Q02 |

---

## 2. Group B — Key intake (US-ACCT-002, US-ACCT-003, US-ACCT-007; E27-S02, E27-T03)

Screens `SCR-126`, `SCR-016` (step 3), `SCR-125`, `SCR-128`, `SCR-079`. Endpoints `POST`/`GET .../keys`,
`POST .../keys/{keyId}/test`, `POST /auth/step-up`; WS `system`. Audit `account.updated` (key
attached), `account.tested`, `account.disabled_by_policy`; metric `cv_key_verification_total`. Unless
stated the account is `acct-demo-main` (Demo, UID `90000001`, no key), the scenario is `compliant`,
the actor is `owner-enrolled`, and every save answers the `keys` step-up (§9.4). Terms used by the
cases:

- **Refused (check: X):** `422 validation_failed` (the status `createApiKey` documents for "Key
  rejected by the verification pipeline") with an `errors[]` entry whose `rule` names check X.
  Only `key_withdraw_permission` is documented; the other rule names are pending #2417, so the case
  records the value. It fails if the value is `key_withdraw_permission` for another check, or if two
  different checks named in this group share one rule (each check has its own rule, E27 threat model
  AC-15); variants that name the same check may share one. Nothing is persisted:
  `GET .../keys` is unchanged and `GET /exchange-accounts/{accountId}` still shows
  `key_status: missing`. No input is echoed (TC-119). Any other answer, a `201` or a
  `502 exchange_error` included, fails the case.
- **Read-only (C-12.2):** a `system` `notice` with `severity: critical` (23 §15.9; record the
  `reason`), and `POST /orders` refused on every account while cancel and flatten still work
  (SR-032; §10 DC-04).
- **Alert raised:** a new `critical` entry in `GET /notifications` (`kind` `system` or `alert`)
  naming the account and the failed check; in manual runs also the page on the configured alert
  channel (US-ACCT-003 NFR, C-12.2 P1).

<!-- prettier-ignore -->
| Case | Type | US | Preconditions · scenario | Steps | Expected result | Evidence | Audit · metric | KB | Auto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E27-TC-101 | pos | US-ACCT-002, US-ACCT-003 | Scenario `compliant`; no other key stored | 1. SCR-126 (edit mode): paste key and secret, read-only off, Save. 2. Time the re-sent save to the rendered result. 3. `GET .../keys`. 4. Restart the backend; `POST .../keys/{keyId}/test`. | `201`: `passed: true`, `withdraw_enabled: false`, `uid` = the account UID, `unified: true`, `ip_whitelist_matches_egress: true`, `probe_ret_code: 0`, `warnings: []`. The key is `active` and identified only by `key_id_masked` with at most 4 clear characters (SR-005, §10 DC-02). The account shows "verified" with the scope list and the allowlist, as a list, not colour (US-ACCT-003, SCR-126); ≤3 s (§0.2). Step 4 passes and the stub validates the signature against the scenario secret: the stored secret round-trips without ever being shown. | HAR, SS, T, LOG, AUD, MET | step 1 `account.updated` (fingerprint only); step 4 one start-up self-check result (system, SR-031) and `account.tested` · +3 pass (save, start-up check, test) | Y | Q02+manual |
| E27-TC-102 | neg | US-ACCT-003 | Scenario `withdraw_enabled` | Save. | Refused (check: withdrawal right): `422 validation_failed` with `errors[].rule: key_withdraw_permission` (ticket AC 2). Hard-block copy "This key has withdrawal permission. Create a key with withdrawal disabled." (SCR-016, SCR-126); the withdrawal state is never rendered neutrally (CMP-175); no input echoed. | HAR, SS, LOG, AUD, MET | `key.verification_failed` · +1 fail | Y | Q02 |
| E27-TC-103 | neg | US-ACCT-003 | One run per fund-moving right: a) `transfer_enabled`, b) `subtransfer_enabled`, c) `subtransfer_list_enabled`, d) `fiat_p2p_enabled`, e) `fiat_bitpay_enabled`, f) `fiat_convert_broker_enabled`, g) `bitcard_enabled` | Save. | Each Refused: a–c (check: transfer right; C-2.8, SR-030a, #2417), d–g (check: fund-moving group outside the allow-list; #2417, E27 threat model AC-15). A `201` for any variant is P0 (§0.1), even though the contract's example stores `Wallet: [AccountTransfer]` and its step 2 checks only `Withdraw` (§10 DC-01). | HAR, MET | `key.verification_failed` · +1 fail per variant | — | Q02 |
| E27-TC-104 | neg | US-ACCT-003 | Scenario `ip_missing` | Save. | Refused (check: allowlist present). The copy says the allowlist must be set in the Bybit dashboard (browser-only, ADR-0009; per SCR-126 spec, confirm against E27-D02). The allowlist is mandatory in every environment (C-2.8, C-12.2): acceptance because `require_ip_whitelist` defaults off for demo is a defect (§10 DC-03). | HAR, SS, MET | `key.verification_failed` · +1 fail | Y | Q02 |
| E27-TC-105 | neg | US-ACCT-003 | Scenario `ip_mismatch` (allowlist `198.51.100.20`, egress `203.0.113.10`) | Save; use the copy control. | Refused (check: egress IP in allowlist), shown as "egress IP not in allowlist". The current egress IP is shown with a copy control that announces "Copied" (CMP-033), labelled apart from any tailnet address (SR-033). | HAR, SS, A11Y, MET | `key.verification_failed` · +1 fail | Y | Q02+manual |
| E27-TC-106 | neg | US-ACCT-003 | a) `ip_extra_foreign` (egress plus `192.0.2.30`); b) `ip_wildcard` (`ips: ["*"]`) | Save. | a) Refused (check: every entry equals the egress IP); b) Refused (check: no wildcard) (SR-030a, #2417, E27 threat model AC-15). The contract says only "inside it" (§10 DC-03); a `201` is P0. | HAR, MET | `key.verification_failed` · +1 fail per variant | — | Q02 |
| E27-TC-107 | neg | US-ACCT-003 | Scenario `uid_mismatch` (key reports UID `90000099`) | Save with `expected_uid` = `90000001`. | Refused (check: UID); the reason names both UIDs. | HAR, SS, MET | `key.verification_failed` · +1 fail | Y | Q02 |
| E27-TC-108 | neg | US-ACCT-003 | Scenario `non_uta` | Save. | Refused (check: UTA), shown as "not a Unified Trading Account". | HAR, MET | `key.verification_failed` · +1 fail | — | Q02 |
| E27-TC-109 | neg | US-ACCT-003 | Scenario `clock_skew` | Save. | Refused (check: signed probe within `recv_window`); the reason names clock sync, the measured offset and the fix (sync the host clock); the exchange code only in a details disclosure (11 global AC 5). | HAR, SS, MET | `key.verification_failed` · +1 fail | Y | Q02 |
| E27-TC-110 | neg | US-ACCT-003 | Scenario `wallet_probe_error` | Save. | Refused (check: signed probe returns `retCode=0`); domain-language reason, exchange code in details. A pipeline verdict, so `422`, not `502` (contract). | HAR, MET | `key.verification_failed` · +1 fail | — | Q02 |
| E27-TC-111 | neg | US-ACCT-003 | Scenario `missing_trade_scope`, `read_only: false` | Save. | Refused (check: required trade scopes). | HAR, MET | `key.verification_failed` · +1 fail | — | Q02 |
| E27-TC-112 | neg | US-ACCT-003 | One run per group outside the trade scopes: `extra_scope_spot`, `extra_scope_options`, `extra_scope_exchange`, `extra_scope_nft`, `extra_scope_affiliate` | Save. | Each Refused (check: scopes outside the allow-list): a trading key carries only the contract trade scopes (SR-030a; allow-list pending #2417, §10 DC-01). | HAR, MET | `key.verification_failed` · +1 fail per variant | — | Q02 |
| E27-TC-113 | neg | US-ACCT-007 | Demo-bound account; scenario `live_key_on_demo` | Paste the key; Save. | Refused (check: environment; proposed rule `key_wrong_environment`, E27 threat model AC-14), with "key does not belong to this environment" (US-ACCT-007). `LOG` shows demo hosts only, zero live-host requests. The system cannot tell a live key from an unknown one without contacting live, so TC-133 must give the same status, rule and copy (§10 DC-29). | HAR, SS, LOG, MET | `key.verification_failed` · +1 fail | Y | Q02 |
| E27-TC-114 | pos | US-ACCT-007 | Account verified in TC-101 | 1. Read the SCR-125 row and the SCR-079 heading. 2. Test connection; keep the drawer open 2 min. 3. Read `LOG`. | The environment is text on the row and in the drawer heading (CMP-106 name `<label>, demo account`); every REST call and the private WS for the account used demo hosts only. | SS, A11Y, LOG, AUD, MET | `account.tested` (step 2) · +1 pass (step 2) | Y | Q02 |
| E27-TC-115 | neg | US-ACCT-007 | Account verified, the only stored key; scenario `demo_ws_unreachable` | 1. Restart. 2. Watch SCR-125, SCR-079 and `system` for 2 min. 3. Read `LOG`. | The outage is reported (state per §5; `system` `exchange_state` frame). No fallback: zero connections or requests to live hosts (US-ACCT-007, C-2.11). | SS, WS, LOG, AUD, MET | the start-up self-check result (system) · `cv_key_verification_total` +1 pass (REST is healthy); `cv_account_health_state` leaves healthy | — | Q02 |
| E27-TC-116 | pos | US-ACCT-003 | Scenario `expiring_13d` | Save; open SCR-125 and SCR-079. | `201` with a warning naming the expiry ("key expires in 13 days"). A warning, not a block: order entry stays enabled. SCR-125 shows the "key expiring (<14 d)" chip and SCR-079 "key expiring soon" (per spec; confirm against E27-D02). | HAR, SS | `account.updated`, `key.expiry_warning` · +1 pass | Y | Q02 |
| E27-TC-117 | neg | US-ACCT-003 | Scenario `expiring_15d` | Save. | `201`, `warnings: []`, no expiring chip: no false warning outside 14 days. | HAR, SS | `account.updated` · +1 pass | — | Q02 |
| E27-TC-118 | neg | US-ACCT-002 | Key active (TC-101); TC-119 run in the same window | 1. Reopen the key on SCR-126 (edit), SCR-125, SCR-128, SCR-127 step 1 and SCR-079; tab through every control. 2. `GET .../keys`, `GET /exchange-accounts/{accountId}`, `POST .../keys/{keyId}/test`. 3. Try `GET .../keys/{keyId}`, `GET .../keys/{keyId}/secret`, `GET .../keys?reveal=true`, `GET .../keys/{keyId}?include_secret=true`; WS `sub` to topics `keys` and `secrets`. 4. Search every captured response and frame, the DOM and `GET /metrics` for the scenario's key id and secret. 5. Read the `action_class` values of `POST /auth/step-up`. 6. `POST /admin/support-bundle` for a window covering TC-101, TC-119 and this case; poll `GET /admin/support-bundle/{job_id}`; search the archive for the same strings. | No reveal path anywhere (US-ACCT-002, SR-005, R3 exit #9). The secret field is an empty write-only field described as such; there is no "Show secret", reveal or copy-secret control (§10 DC-22); identifiers are truncated. Step 2 returns metadata only; step 3 → `404`/`405` with no secret, and `unknown_topic` for both topics; step 4 finds neither string; step 5 offers no reveal class. Step 6: the job ends `succeeded` and the archive holds neither string (US-ACCT-002 NFR, E27 threat model AC-13); a `failed` job with `error_code: BUNDLE_SECRET_DETECTED` means secret material reached the logs and is itself a P0 signal. Any hit is P0. | SS, A11Y, HAR, WS, AUD, MET | `account.tested` (step 2), `health.diagnostics_exported` (step 6, query by `action`) · +1 pass (step 2) | Y | Q02+manual |
| E27-TC-119 | neg | US-ACCT-002 | Scenarios `withdraw_enabled`, then `compliant` | 1. Submit the failing key. 2. Inspect the problem body, the UI error, the console, the frames and the attempt's audit entry. 3. Submit the compliant key; read its audit payload. | Nothing echoes the submitted key or secret (a 422 never echoes input, 04 §5.14 KV4); the audit payload holds the key fingerprint only (SCR-126). | HAR, AUD, MET | `key.verification_failed` (step 1), `account.updated` (step 3) · +1 fail (step 1), +1 pass (step 3) | — | Q02 |
| E27-TC-120 | neg | US-ACCT-002 | Stored keys exist; backend started with no KEK available (ADR-0009 Amendment 1: no handle) | 1. Start; open the app. 2. `POST /orders` for a verified account. 3. `POST .../keys`, `POST .../keys/{keyId}/rotate`, `POST .../keys/{keyId}/test`. 4. `GET /exchange-accounts`. 5. Restore the KEK; restart. | Read-only start with a blocking banner: `system` notice with `severity: critical`, `reason: secrets.kek_unavailable` (23 §15.9). Step 2 refused (trading routes refused, US-ACCT-002); step 3 each `403` (ADR-0009 Amendment 1); step 4 still served; step 5 clears it ("Read-only mode cleared."). | SS, WS, HAR | — · — | Y | manual |
| E27-TC-121 | neg | US-ACCT-002 | Scenario `compliant` | 1. `POST .../keys` twice with the same `Idempotency-Key` and body. 2. Same key, different body. 3. No `Idempotency-Key`. | 1: one key only; the second answer is the original response with `Idempotency-Replayed: true`. 2: `409 idempotency_key_reuse`. 3: refused as invalid (the header is required); nothing stored. | HAR | one `account.updated` · +1 pass | — | Q02 |
| E27-TC-122 | neg | US-ACCT-003 | Scenario `bybit_5xx` | 1. Save. 2. Switch to `compliant`; save again with a new `Idempotency-Key`. | 1: a 5xx problem (`exchange_error` 502 as the operation documents, or `exchange_unavailable` 503), never `201` or `500`; not persisted; retry copy shown. 2: `201`. | HAR, MET | `key.verification_failed` (step 1), `account.updated` (step 2) · +1 fail (step 1), +1 pass (step 2) | — | Q02 |
| E27-TC-123 | neg | US-ACCT-003 | Scenario `rate_limited_10018` | Save. | Refused, not persisted; `exchange_rate_limited` with `retry_after_seconds` (registry status 429; `createApiKey` documents no 429, §10 DC-11); the UI says when to retry; `LOG` shows no retry loop. | HAR, LOG | `key.verification_failed` · +1 fail | — | Q02 |
| E27-TC-124 | pos | US-ACCT-003 | Account verified (`compliant`) | 1. SCR-125 Test connection (`POST .../keys/{keyId}/test`, `include_ws: true`). 2. Open SCR-128. | `200` with `passed: true`, `rest.ok`, `websocket.ok` and a new `checked_at`. SCR-125 summary "Withdrawal permission: OFF on all accounts (verified `<time>`)"; SCR-128 shows the last successful verification, key age, allowlist state and next rotation date; `LOG` shows no order placed. | HAR, SS, LOG, AUD | `account.tested` · +1 pass | Y | Q02 |
| E27-TC-125 | neg | US-ACCT-003 | Account verified; scenario `ws_auth_timeout` | Test connection. | `200` with `passed: false`, `websocket.ok: false` and an error from a fixed vocabulary, never free exchange text (#2417); the UI names the failed probe in text. | HAR, SS | `account.tested` · +1 fail | Y | Q02 |
| E27-TC-126 | neg | US-ACCT-003 | Two verified accounts, the affected one holding `open_position_btcusdt_5x_sl` and `working_orders_2`; its key switched to `withdraw_enabled` after storage | 1. Restart (the start-up self-check; the hourly run is TC-132). 2. Watch SCR-125, SCR-079, alerts and `system`. 3. `POST /orders` on both accounts. 4. Cancel an order and flatten on the affected account. | The affected account is force-disabled for trading with the reason shown verbatim and an alert raised; SCR-125 shows a red blocking banner and its summary no longer says "OFF on all accounts" (US-ACCT-003, SCR-125). The system is Read-only (C-2.8, C-12.2), so step 3 is refused on both accounts and step 4 still works (SR-032). | SS, WS, HAR, AUD, MET | `account.disabled_by_policy` (system) + one self-check result per key (system, SR-031) · +2 (one fail) | Y | Q02+manual |
| E27-TC-127 | neg | US-ACCT-003 | Account verified, the only stored key; its key switched to `ip_mismatch` (egress changed) | Restart. | "IP mismatch" shown, trading blocked, and the current egress IP shown with a copy control (US-ACCT-003); SCR-079 shows the mismatch state with remediation text; an alert raised; Read-only as in TC-126. | SS, HAR, AUD, MET | `account.disabled_by_policy` (system) + the self-check result (system) · +1 fail | Y | Q02+manual |
| E27-TC-128 | neg | US-ACCT-003 | Three verified accounts; one key switched to `ip_missing` | Restart. | Every stored key is re-checked (SR-031, R3 exit #9): only that account is flagged, with an alert raised, and the other two still show verified; Read-only as in TC-126. | SS, HAR, AUD, MET | `account.disabled_by_policy` (system) + one self-check result per key (system) · +3 (one fail) | — | Q02+manual |
| E27-TC-129 | neg | US-ACCT-003 | Account verified, the only stored key; scenario `bybit_5xx` for every start-up check | Restart. | The inconclusive check counts as failed (04 §5.14 KV3): the account never shows "verified" from a check that did not finish; an alert raised; Read-only as in TC-126. | SS, HAR, AUD, MET | `account.disabled_by_policy` (system) + the self-check result (system) · +1 fail | — | Q02+manual |
| E27-TC-130 | neg | US-ACCT-003 | Scenario `new_key_48h` (`query-api` reports `createdAt` 2 h before load) | 1. Save. 2. Open SCR-125 and SCR-079. 3. `POST /orders` on the account. 4. Advance the clock past `createdAt` + 48 h (§9.5); reopen both screens. | 1: `201`, `verification.passed: true`, and one `warnings[]` entry naming the 48 h new-key restriction and its lift time, `createdAt` + 48 h (fixed vocabulary, #2417). The key `status` is a `KeyStatus` value, `active`; `restricted` is UI text only (§10 DC-23). 2: SCR-125 shows "within Bybit's 48 h new-key restriction" and SCR-079 key status "restricted", each with the lift time (per spec; confirm against E27-D02). 3: accepted: the restriction gates live use, and demo trading continues meanwhile (SCR-017, SCR-122). 4: the chip is gone and SCR-079 shows the key as valid. | HAR, SS, AUD, MET | `account.updated` (step 1) · +1 pass | Y | Q02·clk+manual |
| E27-TC-131 | neg | US-ACCT-002 | `manager-with-grants` (trade grant on the account) | `POST .../keys`, `GET .../keys`, `POST .../keys/{keyId}/test` on the granted account. | Each `403 forbidden` (`keys:manage` and `keys:read` are Owner-only, 04 §7.2.1); no challenge; denials audited. | HAR, AUD | `authz.denied` · — | — | Q02 |
| E27-TC-132 | neg | US-ACCT-003 | Two verified accounts, `acct-demo-main` (holding `open_position_btcusdt_5x_sl` and `working_orders_2`) and `acct-demo-sub1`; T0 = the last self-check (SCR-125 "verified `<time>`", `LOG`); test clock (§9.5) | 1. Without restarting, switch `acct-demo-main`'s key to a) `withdraw_enabled`, b) `ip_missing`. 2. Advance to T0 + 59 min; read `LOG` and SCR-125. 3. Advance to T0 + 60 min, plus 1 min scheduler tolerance; read `LOG`, SCR-125, SCR-079, alerts and `system`. 4. `POST /orders` on both accounts; cancel an order and flatten on `acct-demo-main`. | Step 2: while `LOG` shows no `query-api` call since T0, the account still shows verified (no verdict without a check). An earlier periodic run is allowed, because C-12.2 sets the longest interval; its time is recorded. By step 3: `LOG` shows a `query-api` call for each stored key since T0 (C-12.2 hourly; a 6 h or nightly cadence fails here, §10 DC-05); `acct-demo-main` is disabled by policy with the reason shown and an alert raised; SCR-125's verification time moves to the new run. Step 4: Read-only, so orders are refused on both accounts while cancel and flatten work. A build that checks only at start-up fails this case. | SS, WS, HAR, LOG, AUD, MET | `account.disabled_by_policy` (system) + one self-check result per key (system) · +2 (one fail) per variant | — | Q02·clk |
| E27-TC-133 | neg | US-ACCT-007 | Demo-bound account; scenario `unknown_key` (a key id no environment issued, such as a typo) | Paste the key; Save. | The same status, rule and copy as TC-113: Refused (check: environment) with "key does not belong to this environment"; `LOG` shows demo hosts only. A difference from TC-113 claims a determination the system cannot make without contacting live (§10 DC-29). | HAR, SS, LOG, MET | `key.verification_failed` · +1 fail | — | Q02 |

---

## 3. Group C — Rotation and key-age policy (US-ACCT-004, US-ACCT-005; E27-S03, E27-T04)

Screens `SCR-127`, `SCR-128`, `SCR-125`. Endpoints `POST .../keys/{keyId}/rotate`, `GET .../keys`,
`DELETE .../keys/{keyId}`, `GET /orders`, `GET /positions`. Audit `account.key_rotated`. The key-age
policy is set explicitly to 90 days unless stated (SR-037 sets 180 days for demo keys, §10 DC-09).
Every case needs a stored key: the scenario is `compliant` unless stated.

<!-- prettier-ignore -->
| Case | Type | US | Preconditions · scenario | Steps | Expected result | Evidence | Audit · metric | KB | Auto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E27-TC-201 | pos | US-ACCT-004 | Account verified with the old key; scenario `rotation_ok`; `wallet` frames flowing | 1. SCR-127: follow the checklist, enter the new key, validate, switch over (step-up). 2. Time submit → switched. 3. `GET .../keys`. 4. Read `LOG` and the `wallet` stream across the switch. | `200`, `state: overlapping`, `overlap_until` = start + 15 min (US-ACCT-004, 21 §3.2.3; the contract default is 300 s, §10 DC-06). New key `active`, old key `rotating`. From the switch every new request uses the new key while the old one stays valid for the drain window; the private WS re-authenticates with the new key; every `wallet` frame the stub sends during the switch arrives (no interruption). Stages and elapsed time shown, ≤10 s (§0.2); steps are labelled regions with `aria-current="step"`. | HAR, SS, T, LOG, WS, AUD | `account.key_rotated` (fingerprints only) · +1 pass | Y | Q02+manual |
| E27-TC-202 | pos | US-ACCT-004 | TC-201 in overlap | 1. Let the drain window end (§9.5, or 15 min by hand). 2. `GET .../keys`; read `LOG`. 3. Read the last SCR-127 step. | Old key `revoked`; no request uses it after `overlap_until`, and it cannot be used again (`POST .../keys/{oldKeyId}/test` does not pass). SCR-127 reminds the owner to delete the old key at Bybit, with a confirmation checkbox. No exchange delete call is expected: the contract revokes locally only, while US-ACCT-004 says one is attempted (§10 DC-07). | HAR, LOG, SS, AUD | `key.retired` (system, drain end; 04 §8.2) · — | Y | Q02·clk |
| E27-TC-203 | pos | US-ACCT-004 | TC-201 in overlap | Revoke the old key early (SCR-127 or `DELETE .../keys/{oldKeyId}`; step-up). | `204`; the old key is revoked at once; the new key stays active and primary; trading continues; `LOG` shows no old-key request after the `204`. | HAR, LOG, AUD | `key.revoked` · — | Y | Q02 |
| E27-TC-204 | neg | US-ACCT-004 | Account verified; scenario `rotation_new_key_withdraw` | Rotate. | Promotion refused (`422`, `key_withdraw_permission`). The old key stays `active` and primary, the account stays verified and tradeable, the reason is shown, SCR-127 shows its rollback state, and the new key is not stored. Success here, or an old key left non-primary, is P0. | HAR, SS, LOG | `key.verification_failed` · +1 fail | Y | Q02 |
| E27-TC-205 | neg | US-ACCT-004 | Account verified; scenario `rotation_ok` with the overlays `working_orders_2` and `open_position_btcusdt_5x_sl` | Rotate as in TC-201; then `GET /orders` (`open_only`) and `GET /positions`. | The same 2 orders (ids and states unchanged) and the same position with its SL; `LOG` shows no cancel: rotation never cancels open orders (US-ACCT-004 NFR). | HAR, LOG | `account.key_rotated` · +1 pass | — | Q02 |
| E27-TC-206 | neg | US-ACCT-004 | A session with no live `keys` grant; then `manager-with-grants` | 1. Rotate. 2. The manager calls rotate. | 1: `403 step_up_required` with `action_class: keys` and `action_summary` `Rotate API key for account '<label>' (demo, UID <uid>)`; nothing started. 2: `403 forbidden`, no challenge. | HAR, AUD | `authz.denied` (step 2) · — | — | Q02 |
| E27-TC-207 | pos | US-ACCT-005 | Policy 90 d; key registered 76 days ago (§9.5) | Open SCR-125 and SCR-128. | Amber "rotate within 14 days" chip with icon and text; SCR-128 shows the rotation-due date; one alert raised; trading unaffected (per spec; confirm against E27-D02). | SS, A11Y | — · — | Y | Q02·clk |
| E27-TC-208 | neg | US-ACCT-005 | As TC-207 with the key 75 days old | Open SCR-125. | No chip and no alert. | SS | — · — | — | Q02·clk |
| E27-TC-209 | neg | US-ACCT-005 | Policy 90 d; key 91 days old | 1. Open SCR-125. 2. Advance the clock 24 h, twice. 3. `POST /orders` on the account. | Red "overdue" chip; exactly one alert per day; the order is accepted: trading is never disabled for age alone. | SS, HAR | — · — | Y | Q02·clk |
| E27-TC-210 | pos | US-ACCT-005 | TC-209 state | Set the policy to 180 days on SCR-128. | Every warning recomputes at once, with no reload and no 60 s wait: the 91-day key loses its red chip and its due date moves; the change is audited (SCR-128). No route for the policy is documented, so this runs through the UI (§10 DC-09). | SS, T, AUD | `admin.secrets_policy_changed` (before 90, after 180) · — | Y | manual |
| E27-TC-211 | neg | US-ACCT-005 | Key registered 80 days ago; scenario `compliant` (exchange expiry 365 days after load) | Open SCR-125. | Amber chip: age counts from the registration date, never from the exchange expiry field (US-ACCT-005 NFR). | SS | — · — | — | Q02·clk |
| E27-TC-212 | neg | US-ACCT-005 | One key with scenario `expired_key` (exchange expiry passed); one `compliant` key 91 days old (§9.5) | 1. Restart (the start-up self-check). 2. `POST /orders` on each account. | The expired key's account is disabled for order placement (SR-034); the age-overdue account still trades (TC-209): expiry and age are not conflated. | HAR, SS, AUD, MET | `account.disabled_by_policy` (system, expired key only) + one self-check result per key (system) · +2 (one fail) | — | Q02·clk |

---

## 4. Group D — Revoke, disable and delete (US-ACCT-006; E27-S04)

Screens `SCR-129` (disable and delete), `SCR-127` (revoke step), `SCR-128` (mark as compromised),
`SCR-079`, `SCR-125` row actions; the rules list (`SCR-080`, `GET /rules`) is an observation point
only. The standalone key revoke of US-ACCT-006 has no screen spec: SCR-125's row actions are edit,
rotate key, disable and delete, SCR-129 covers disable and delete only, and only CMP-176
(`onRevoke`) offers a revoke, so revoke cases follow US-ACCT-006 and confirm against E27-D02
(§10 DC-26). Endpoints `DELETE .../keys/{keyId}`, `PATCH`/`DELETE /exchange-accounts/{accountId}`,
`GET /positions`, `POST /positions/close-all`; WS `revoked`. Audit `account.disabled`,
`account.deleted`, `admin.key_marked_compromised` and the key events in §8.1.

**Shared setup:** `acct-demo-sub1` and `acct-demo-sub2` verified (scenario `compliant` unless
stated; the §9.3 overlays add positions, orders and history); `manager-with-grants` holds the
`trade` grant on `acct-demo-sub1` only and has a WS session subscribed to `wallet`, `positions` and
`orders` for it; two rules armed on `acct-demo-sub1` and one on `acct-demo-sub2`. Cases act on
`acct-demo-sub1` unless stated.

<!-- prettier-ignore -->
| Case | Type | US | Preconditions · scenario | Steps | Expected result | Evidence | Audit · metric | KB | Auto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E27-TC-301 | pos | US-ACCT-006 | Shared setup; the account is flat with no orders | 1. Revoke the key (the CMP-176 row action; per US-ACCT-006, no SCR spec, confirm against E27-D02); confirm; step-up. 2. Time confirm → inactive. 3. `GET .../keys`, `GET /exchange-accounts/{accountId}`, `LOG`, the manager's frames, `GET /rules`. | `204`; key `revoked`, `key_status: missing`, account inactive, private streams stopped. No request is signed with the key after the `204` (04 §5.14 KV14), and no Bybit key-delete call is made (the contract revokes locally only). The manager's subscriptions end with `revoked`, `reason: key_revoked` (23 §9.5), never silently emptied. Both bound rules are disarmed and the other rule is untouched. Elapsed time recorded ("in seconds", US-ACCT-006). | HAR, LOG, WS, SS, T, AUD | `key.revoked` · — | Y | Q02+manual |
| E27-TC-302 | pos | US-ACCT-006 | Shared setup plus the overlay `open_position_btcusdt_5x_sl` | 1. Revoke. 2. Choose "revoke and leave positions". 3. `GET /positions`; read `LOG`. | Before revoking, the position list and both choices are shown (US-ACCT-006). After "leave": key revoked; the position stays open with its native SL on the exchange, and the UI states that it was left open under that SL (per US-ACCT-006; no SCR spec, confirm against E27-D02). | SS, HAR, LOG, AUD | `key.revoked` · — | Y | Q02+manual |
| E27-TC-303 | pos | US-ACCT-006 | As TC-302 | Choose "flatten first, then revoke". | Close-all for the account runs first and `GET /positions` is flat before the revoke (`LOG` order: close orders, then no further use of the key); then the key is revoked; both outcomes are shown. | HAR, LOG, SS, AUD | `position.flattened`, `key.revoked` · — | Y | Q02 |
| E27-TC-304 | neg | US-ACCT-006 | As TC-302 | `DELETE .../keys/{keyId}` with no position choice. | `409` with the consequence summary; the key is unchanged (#2417 SR-E27-06; the current contract is silent, §10 DC-07). | HAR | — · — | — | Q02 |
| E27-TC-305 | neg | US-ACCT-006 | As TC-302; scenario `close_rejected` | Choose "flatten first, then revoke". | The flatten failure is shown with the exchange's reason; the key is not reported revoked unless it was; the owner is offered the remaining choices (per US-ACCT-006; no SCR spec, confirm against E27-D02). | SS, HAR, LOG | — · — | Y | Q02+manual |
| E27-TC-306 | neg | US-ACCT-006 | Account flat; scenario `key_delete_5xx` (a negative guard: under the contract no build reaches its 503) | Revoke (step-up). | Local revocation always happens and is the only revocation: `204`, key `revoked`, and `LOG` shows no request signed with it afterwards (US-ACCT-006 NFR). `LOG` shows no Bybit key-delete call (contract `revokeApiKey`: "Local revocation only"; #2417), and the UI tells the owner to revoke the key in the Bybit dashboard (US-ACCT-006; confirm against E27-D02). Any outbound key-delete call is a contract deviation, raised as a defect even when its 503 is handled (§10 DC-07). Usable key material after the `204` is P0. | HAR, LOG, SS, AUD | `key.revoked` · — | Y | Q02 |
| E27-TC-307 | neg | US-ACCT-006 | A session with no live `keys` grant; then `manager-with-grants` | 1. Revoke. 2. The manager revokes the granted account's key. | 1: `403 step_up_required`; nothing revoked. 2: `403 forbidden`, no challenge. | HAR, AUD | `authz.denied` (step 2) · — | — | Q02 |
| E27-TC-308 | pos | US-ACCT-006 | Shared setup; account flat | 1. SCR-125 → Disable. 2. Read the dialog before typing. 3. Type the exact label; step-up; confirm. 4. Check the manager session, the rules and order entry. | `role="alertdialog"` with focus on Cancel, listing the consequences: open positions are not closed automatically (with a "flatten first" shortcut), working orders can be cancelled, the users who lose access, both rules by name, and that records are kept. The summary loads in ≤1 s and no confirm button shows before it (§0.2). After confirm: `enabled: false`, `connection_state: disabled`; both rules disarmed; `POST /orders` refused (403); the manager receives `revoked`, `reason: account_disabled`. | SS, A11Y, T, HAR, WS, AUD | `account.disabled` · — | Y | Q02+manual |
| E27-TC-309 | neg | US-ACCT-006 | As TC-308 | Type the label in another case, with a trailing space, and another account's label. | Confirm stays unavailable each time; nothing is sent and nothing changes. | SS, HAR | — · — | Y | Q02 |
| E27-TC-310 | neg | US-ACCT-006 | Shared setup plus the overlays `open_position_btcusdt_5x_sl` and `working_orders_2` | 1. SCR-125 → Delete. 2. `DELETE /exchange-accounts/{accountId}` directly (step-up). | The dialog lists the blockers with counts and offers no delete confirm (SCR-129); the API answers `409 conflict`; nothing changes. | SS, HAR | — · — | Y | Q02 |
| E27-TC-311 | pos | US-ACCT-006 | Shared setup plus the overlay `history_round_trip` (flat, with order, execution and audit history) | 1. Delete: typed label plus step-up. 2. `GET /exchange-accounts`; `GET /orders` and `GET /executions` for the account; `GET /admin/audit` for it. | `204`; the dialog stated that delete is irreversible and history is kept. The account is no longer active (the contract marks it `disabled`, the schema soft-deletes, §10 DC-10); its keys are revoked locally; its orders, executions and audit entries are still listed. | HAR, SS, AUD | `account.deleted`, `key.revoked` (its key) · — | Y | Q02 |
| E27-TC-312 | neg | US-ACCT-006 | TC-308 done | As the manager: `GET /exchange-accounts/{accountId}`; `sub` `wallet` for it. | REST `403 account_scope_denied` (or `404`, hidden by scope); WS `sub` → `account_scope_denied`; the earlier subscriptions had already ended with `revoked`. | HAR, WS | `authz.denied` · — | — | Q02 |
| E27-TC-313 | neg | US-ACCT-006 | Key revoked in TC-301 | Restart; let the start-up self-check run. | The key stays revoked and the account inactive; `LOG` shows no request with that key after the restart, and the start-up check queries `acct-demo-sub2`'s key only: local revocation is durable. | LOG, HAR, AUD, MET | the start-up self-check result for `acct-demo-sub2`'s key (system), none for the revoked key · +1 pass | — | Q02+manual |
| E27-TC-314 | pos | US-ACCT-006 | Shared setup plus the overlay `working_orders_2` | 1. SCR-128 → mark the key as compromised; confirm; step-up (a key action, `keys:manage`, 04 §7.2.1). 2. `GET .../keys`, `LOG`, `POST /orders` for the account and for `acct-demo-sub2`. | The immediate effect SCR-128 names: the key is disabled and order placement for the account halted. `POST /orders` for it is refused; `LOG` shows no request signed with the key after the confirmation, and its private WS session to the stub is closed (04 §5.14 KV14). `acct-demo-sub2` still trades. The working orders' state is recorded, not asserted (SCR-128 says only "orders halted"). The entry is audited at high severity (`severity` `error` or `critical`: the enum has no `high`). Per SCR-128 spec; confirm against E27-D02; no route is documented (§10 DC-28). | SS, HAR, LOG, AUD | `admin.key_marked_compromised` · — | Y | Q02+manual |
| E27-TC-315 | neg | US-ACCT-006 | Shared setup; a session with no live `keys` grant; then `manager-with-grants` | 1. Mark the key as compromised and cancel a) the confirmation, b) the step-up dialog. 2. As the manager, open `/admin/accounts`. | 1: nothing changes: the key stays active, `POST /orders` for the account is accepted and no `admin.key_marked_compromised` entry exists. 2: SCR-154 permission denied and no mark-as-compromised control (Owner only, `keys:manage`). Per SCR-128 spec; confirm against E27-D02 (§10 DC-28). | SS, HAR, AUD | — · — | Y | Q02 |

---

## 5. Group E — Health, balance and leverage (US-ACCT-008, US-ACCT-009, US-ACCT-010; E27-S05, E27-T04)

Screens `SCR-079`, `SCR-125`. Endpoints `GET /exchange-accounts`, `GET`/`PATCH
/exchange-accounts/{accountId}`, `GET /exchange-accounts/{accountId}/fee-rate`,
`PUT /positions/{positionId}/leverage`, `POST /orders`; WS `wallet`, `positions`, `system`. Metric
`cv_account_health_state` (per account: healthy, degraded, down). A health colour is always paired
with text (11 global AC 3). The account is verified, with scenario `compliant` unless stated.

<!-- prettier-ignore -->
| Case | Type | US | Preconditions · scenario | Steps | Expected result | Evidence | Audit · metric | KB | Auto |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E27-TC-401 | pos | US-ACCT-008 | Verified account; scenario `compliant` | 1. Open SCR-079 from the account picker. 2. Compare with the scenario's wallet payload. 3. `GET /exchange-accounts/{accountId}`. | Equity, available balance, used margin, unrealised PnL, margin mode, position mode and leverage shown with units and a freshness timestamp; values equal the fixture payload. REST `balance.updated_at` is set and `balance_stale: false`. The heading names the account and environment; balances form a description list. | SS, A11Y, HAR, WS | — · — | Y | Q02 |
| E27-TC-402 | pos | US-ACCT-008 | Drawer opened once (warm cache) | Close and reopen SCR-079 five times. | Each open takes ≤100 ms from cache, then refreshes in place (§0.2). | T | — · — | Y | manual |
| E27-TC-403 | neg | US-ACCT-008 | Scenario `ws_auth_then_drop` | 1. Note the freshness time at T0 (last frame). 2. Wait 60 s. 3. Read `LOG`, SCR-079 and `GET /exchange-accounts/{accountId}`. | A REST wallet-balance reconciliation runs no later than T0 + 60 s (±2 s), and the freshness timestamp moves to it; reconciling as soon as the drop is detected is also valid (03 §9.1; the exact 60 s bound for a silent stream is TC-406). The figures are not greyed (ticket AC 3). | LOG, SS, HAR | — · `cv_account_health_state` → degraded | — | Q02·clk+manual |
| E27-TC-404 | neg | US-ACCT-008 | Scenario `ws_drop_rest_fail` | Steps as in TC-403; this time the reconciliation fails. | Figures greyed with "stale since `<time of the last good snapshot>`" as text; `balance_stale: true` and `wallet` `stale: true` (ticket AC 3). The account also turns red (TC-410). | SS, HAR, WS | — · → down | Y | Q02·clk+manual |
| E27-TC-405 | neg | US-ACCT-008 | Scenario `ws_quiet_rest_fail` | 1. Wait 60 s plus the failed reconciliation. 2. Open the order ticket for the account. 3. `POST /orders` with risk-based sizing, then with a fixed quantity. 4. Switch to `compliant`. | "stale since" badge. Risk-based sizing is disabled for this account with the reason shown and refused server-side (C-2.12); fixed-quantity entry stays available, because the account is not red (its WS is healthy). After step 4 the badge clears and sizing returns. | SS, HAR | — · stays healthy | Y | Q02·clk+manual |
| E27-TC-406 | pos | US-ACCT-008 | Scenario `ws_quiet` | Wait 60 s; read `LOG` and SCR-079. | The REST truth-check runs at 60 s and the timestamp updates; the account stays green with no stale badge. | LOG, SS | — · stays healthy | — | Q02·clk |
| E27-TC-407 | neg | US-ACCT-008 | Scenario `ws_quiet` | `GET /exchange-accounts/{accountId}` 11 s and 61 s after the last wallet frame. | Contract: `balance_stale: true` once the snapshot is older than 10 s, `false` after the 60 s reconciliation. The UI does not grey the figures at 11 s (story). Recorded against §10 DC-12. | HAR, SS | — · — | — | Q02·clk |
| E27-TC-408 | pos | US-ACCT-010 | Scenario `compliant` | Keep SCR-125 and SCR-079 open 2 min. | Green "healthy" with text and the last heartbeat age, which never exceeds 10 s (§0.2); `connection_state: connected`. | SS, HAR | — · `cv_account_health_state` = healthy | Y | Q02 |
| E27-TC-409 | neg | US-ACCT-010 | Scenario `ws_auth_then_drop` | Watch SCR-125 and the rules list. | Amber "degraded — REST only"; rule actions that need sub-second reaction are flagged for this account; one polite live-region announcement for the change; `connection_state: degraded`. | SS, A11Y, HAR | — · → degraded | Y | Q02+manual |
| E27-TC-410 | neg | US-ACCT-010 | Scenario `ws_drop_rest_fail` from T0, with the overlay `open_position_btcusdt_5x_sl`; a second, healthy account | 1. Watch `GET /exchange-accounts/{accountId}` and SCR-125 until T0 + 90 s. 2. Open the order ticket for each account. 3. `POST /orders` for the red account. 4. Read `LOG` for the position's SL. | By T0 + 30 s (`HAR` and `LOG` timestamps): `connection_state: disconnected`, and `POST /orders` for this account is refused (403; nearest registry code `trading_disabled`, §10 DC-11) with no order request in `LOG`. The SCR-125 row is red with text at its next refresh, by T0 + 90 s (60 s refresh, §10 DC-13), and the ticket shows order entry disabled for this account with the reason. The other account still trades. The position keeps its native SL: `LOG` shows no request that cancels or clears it (SR-059's compensating control; the dead-man's switch is E45-Q01, §10 DC-24). | SS, HAR, LOG, T | — · → down | Y | Q02·clk+manual |
| E27-TC-411 | neg | US-ACCT-010 | Scenario `ws_blip_20s` | Watch for 60 s. | Never red and order entry never disabled for a 20 s outage; amber is allowed. | SS, HAR | — · never down | — | Q02·clk |
| E27-TC-412 | pos | US-ACCT-010 | TC-410 state | Switch to `compliant`. | Back to green and order entry re-enabled; open orders and positions are reconciled before they are shown as live (03 §9.1); one announcement. | SS, HAR, LOG | — · → healthy | Y | Q02 |
| E27-TC-413 | pos | US-ACCT-010 | Three accounts; scenario `compliant` | Keep SCR-125 open 5 min with the network log recording. | Health fields are fetched on open and every 60 s, never per second; the browser never calls the exchange (SCR-125, SCR-128). | HAR | — · — | — | manual |
| E27-TC-414 | neg | US-ACCT-008 | `manager-with-grants` (grant on `acct-demo-sub1` only) | 1. `GET /exchange-accounts`. 2. `GET /exchange-accounts/{acct-demo-sub2}`. 3. WS `sub` `wallet` for sub2 alone, then for sub1 and sub2. | 1: sub1 only (reads narrow silently). 2: `403 account_scope_denied`. 3: error `account_scope_denied`, then `sub_ok.effective` = sub1. | HAR, WS, AUD | `authz.denied` · — | — | Q02 |
| E27-TC-415 | pos | US-ACCT-009 | Owner; scenario `leverage_ok` with the overlay `open_position_btcusdt_5x_sl`; profile cap 10x | Set 10x on the SCR-079 leverage slider and apply. | `PUT /positions/{positionId}/leverage` with `{"leverage": "10"}` → `200`; the drawer and the `positions` frame show 10. Risk-limit tiers are shown beside the choice (US-ACCT-009 NFR); the liquidation preview is text, announced politely (CMP-104); the change is audited (no catalogued event name, §10 DC-08). | HAR, SS, WS, A11Y, AUD | leverage change · — | Y | Q02 |
| E27-TC-416 | neg | US-ACCT-009 | As TC-415; scenario `leverage_refused_open_position` | Request 8x. | `502 exchange_error` carrying the exchange code and message. The UI shows the exact exchange reason (code in details) and the slider returns to 5x; the snapshot is unchanged. | HAR, SS | — · — | Y | Q02 |
| E27-TC-417 | neg | US-ACCT-009 | As TC-415 (cap 10x) | 1. Drag the slider past 10x. 2. `PUT /positions/{positionId}/leverage` with `{"leverage": "20"}` directly. | 1: refused client-side, with the cap stated. 2: refused server-side (`risk_limit_breached`, 403 in the registry, 422 in the contract example, §10 DC-11). `LOG` shows zero set-leverage requests; leverage unchanged. | HAR, SS, LOG | — · — | Y | Q02 |
| E27-TC-418 | neg | US-ACCT-009 | `manager-with-grants` (trade grant); scenario `leverage_ok` with `open_position_btcusdt_5x_sl` on the granted account | `PUT /positions/{positionId}/leverage`. | `403` per 04 §7.2.2 row 18 (Owner only); nothing reaches the exchange. §7.2.1 and the story's "trader" persona disagree (§10 DC-15), so a `200` is raised as needs-clarification, not passed. | HAR, LOG, AUD | `authz.denied` · — | — | Q02 |
| E27-TC-419 | pos | US-ACCT-009 | Scenario `compliant`: no positions or orders, and the mode-switch calls succeed | `PATCH` with `margin_mode: isolated` (`If-Match`). | `200`; the drawer and CMP-128 show isolated. | HAR, SS | `account.updated` · — | Y | Q02 |
| E27-TC-420 | neg | US-ACCT-009 | The overlay `open_position_btcusdt_5x_sl` (mode-switch calls answer with the recorded open-position refusal) | `PATCH` with `margin_mode: cross`. | `409 conflict`, the same whether the server checks first or maps the exchange's refusal (contract: "fails with `conflict`"); CMP-128 disabled with "cannot change margin mode with an open position."; mode unchanged. | HAR, SS | — · — | Y | Q02 |
| E27-TC-421 | neg | US-ACCT-009 | The overlay `working_orders_2` (mode-switch calls answer with the recorded active-order refusal) | `PATCH` with `position_mode: hedge`. | `409 conflict`, as in TC-420; CMP-129 disabled with its reason; mode unchanged. | HAR, SS | — · — | Y | Q02 |
| E27-TC-422 | pos | US-ACCT-008 | Verified account; scenario `compliant` | `GET .../fee-rate?symbol=BTCUSDT` twice within 15 min. | Maker and taker rates equal the fixture; the second answer carries the same `cached_at`; `LOG` shows one upstream call (15-minute cache). | HAR, LOG | — · — | — | Q02 |

---

## 6. Coverage matrix (US-ACCT-001..010 × cases × automation)

Computed from the case tables above; case numbers drop the `E27-TC-` prefix, and a case that
covers two stories appears under both. Every story has at least one positive and one negative or
failure case, and no case is marked "cannot be executed".

<!-- prettier-ignore -->
| Story | Title | Positive | Negative or failure | Automated (`Q02`, `Q02·clk`) | Automated plus a manual part | Manual only |
| --- | --- | --- | --- | --- | --- | --- |
| US-ACCT-001 | Register a Bybit account in the app | 001, 002, 004, 007, 011, 012, 013, 014 | 003, 005, 006, 008, 009, 010, 015 | 001, 002, 003, 004, 006, 007, 008, 009, 010, 011, 013, 014, 015 | 005, 012 | — |
| US-ACCT-002 | Store an API key with envelope encryption | 101 | 118, 119, 120, 121, 131 | 119, 121, 131 | 101, 118 | 120 |
| US-ACCT-003 | API key self-check | 012, 101, 116, 124 | 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 117, 122, 123, 125, 126, 127, 128, 129, 130, 132 | 102, 103, 104, 106, 107, 108, 109, 110, 111, 112, 116, 117, 122, 123, 124, 125, 132 | 012, 101, 105, 126, 127, 128, 129, 130 | — |
| US-ACCT-004 | Key rotation with overlap | 201, 202, 203 | 204, 205, 206 | 202, 203, 204, 205, 206 | 201 | — |
| US-ACCT-005 | Key rotation policy reminder | 207, 210 | 208, 209, 211, 212 | 207, 208, 209, 211, 212 | — | 210 |
| US-ACCT-006 | Revoke a key immediately | 301, 302, 303, 308, 311, 314 | 304, 305, 306, 307, 309, 310, 312, 313, 315 | 303, 304, 306, 307, 309, 310, 311, 312, 315 | 301, 302, 305, 308, 313, 314 | — |
| US-ACCT-007 | Environment binding per account | 114 | 113, 115, 133 | 113, 114, 115, 133 | — | — |
| US-ACCT-008 | Account balance & margin snapshot | 401, 402, 406, 422 | 403, 404, 405, 407, 414 | 401, 406, 407, 414, 422 | 403, 404, 405 | 402 |
| US-ACCT-009 | Leverage and margin mode control | 415, 419 | 416, 417, 418, 420, 421 | 415, 416, 417, 418, 419, 420, 421 | — | — |
| US-ACCT-010 | Account health & connection state | 408, 412, 413 | 409, 410, 411 | 408, 411, 412 | 409, 410 | 413 |

Totals: 97 cases, 32 positive and 65 negative or failure; 71 automated, 22 automated with a manual part, 4 manual only.

## 7. Negative and abuse-adjacent cases owned by QA, and the R3 gate

Deeper adversarial work (timing side channels, races between rotate and revoke, concurrent sessions,
malformed exchange payloads) belongs to E27-X02; the full route × role matrix to E27-X03.

| Behaviour                                                 | Cases                             | Note                                                                                                                  |
| --------------------------------------------------------- | --------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Withdrawal, transfer or other fund-moving right at intake | 102, 103, 112                     | C-2.8 names withdrawal and transfer; the contract example does not (§10 DC-01); the Fiat and BitCard groups per #2417 |
| Allowlist missing, mismatched, foreign or wildcard        | 104, 105, 106                     | Mandatory in every environment                                                                                        |
| Wrong UID, wrong environment, non-UTA, unknown key        | 107, 108, 113, 133                | `LOG` proves no live-host contact                                                                                     |
| Clock skew, failed probe, 5xx, `10018`                    | 109, 110, 122, 123                | Never persisted, never a `500`                                                                                        |
| Permission drift after storage; inconclusive check        | 126, 127, 128, 129, 132           | System read-only per C-12.2, at start-up and hourly                                                                   |
| Secret never revealed or echoed, support bundle included  | 118, 119                          | P0 rule (§0.1)                                                                                                        |
| KEK unavailable                                           | 120                               | Read-only start                                                                                                       |
| Double submit                                             | 121                               | One key only                                                                                                          |
| Rotation to a hostile key                                 | 204                               | Old key stays primary                                                                                                 |
| Step-up and RBAC on writes and scoped reads               | 008, 131, 206, 307, 312, 414, 418 | Samples only; matrix in E27-X03                                                                                       |
| Revoked or compromised key still signing, or resurrected  | 301, 306, 313, 314                | Local revocation authoritative and durable                                                                            |
| Cross-environment contact                                 | 113, 115                          | C-2.11                                                                                                                |
| Leverage cap bypass                                       | 417                               | Refused before any exchange call                                                                                      |
| Emergency mark-as-compromised                             | 314, 315                          | Key disabled and orders halted at once; no route documented (§10 DC-28)                                               |

| R3 exit criterion (30 §7.3)                                               | Black-box evidence in this plan             | Owned elsewhere                                      |
| ------------------------------------------------------------------------- | ------------------------------------------- | ---------------------------------------------------- |
| #9 no API path returns a secret                                           | 118, 119                                    | Leak-assertion suite: E27-X02                        |
| #9 KEK separation demonstrated                                            | 120 (no KEK → read-only, nothing signs)     | Restore drill on a database without the KEK: E27-X04 |
| #9 every key verified withdrawal-OFF and IP-whitelisted by the self-check | 102–106, 124, 126–129, 132                  | —                                                    |
| #10 every route × role denied with 403, no state change and an audit row  | 008, 131, 206, 307, 312, 414, 418 (samples) | Full matrix: E27-X03                                 |

## 8. Audit completeness, metrics and accessibility

### 8.1 Audit events

The ticket, the screens and `04-security-program.md` §8.2 name these events differently (§10 DC-08).
Until one registered vocabulary is published (SR-E27-09), the audit step passes when each event the
case lists appears exactly once for its subject, with the actor the case gives (§0) and under either
name below; record which name appeared. A missing or malformed entry is filed against the acting
case (§0.1).

| Ticket or screen name                                                             | 04 §8.2 name                                            | Cases                                  |
| --------------------------------------------------------------------------------- | ------------------------------------------------------- | -------------------------------------- |
| `account.created`                                                                 | `account.registered`                                    | 001, 002, 004, 007, 012, 013, 014      |
| `account.updated` (key attached)                                                  | `key.created` and `key.verified`                        | 012, 101, 116, 117, 119, 121, 122, 130 |
| `account.updated` (label, margin or position mode)                                | none catalogued                                         | 011, 419                               |
| `account.tested` (Test connection by the acting user)                             | `key.verified` / `key.verification_failed`              | 101, 114, 118, 124, 125                |
| `account.tested` (system: a start-up or hourly self-check result per key, SR-031) | `key.verified` / `key.verification_failed`              | 101, 115, 126–129, 132, 212, 313       |
| `account.key_rotated`                                                             | `key.rotated`                                           | 201, 205                               |
| `account.disabled`                                                                | none catalogued                                         | 308                                    |
| `account.deleted`                                                                 | `account.removed`                                       | 311                                    |
| `account.disabled_by_policy` (system)                                             | `key.disabled_for_trading`                              | 126, 127, 128, 129, 132, 212           |
| none in the ticket                                                                | `key.verification_failed`                               | 102–113, 119, 122, 123, 133, 204       |
| none in the ticket                                                                | `key.revoked`                                           | 203, 301, 302, 303, 306, 311           |
| none in the ticket                                                                | `key.retired` (system, at drain end)                    | 202                                    |
| none in the ticket                                                                | `key.expiry_warning`                                    | 116                                    |
| `admin.secrets_policy_changed` (SCR-128)                                          | `setting.changed`                                       | 210                                    |
| `admin.key_marked_compromised` (SCR-128)                                          | none catalogued                                         | 314                                    |
| `health.diagnostics_exported` (`createSupportBundle`)                             | none catalogued                                         | 118                                    |
| none in the ticket                                                                | `authz.denied`                                          | 008, 131, 206, 307, 312, 414, 418      |
| none in the ticket                                                                | `position.flattened`                                    | 303                                    |
| none in the ticket                                                                | none catalogued for a leverage change (US-ACCT-009 NFR) | 415                                    |

### 8.2 Metrics

Read `GET /metrics` before and after the case. Label values follow the E27-T03 and E27-T04 metric
definitions. Where the UI's Test connection and Save may each run the pipeline (SCR-016, SCR-126),
the case counts the runs and asserts only their pass or fail labels (§10 DC-30).

| Metric                      | Must move in                                             | Expected movement                                                              |
| --------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `cv_key_verification_total` | 012, 101–119, 121–130, 132, 133, 201, 204, 205, 212, 313 | +1 per verification run, as pass or fail, in the steps the case names          |
| `cv_account_health_state`   | 115, 403–406, 408–412                                    | Per account: healthy → degraded → down and back, matching the row's text state |

### 8.3 Accessibility

`KB = Y` cases are also executed keyboard-only. The KB-critical paths are revoke, disable and mark
as compromised (301, 302, 303, 306, 308, 309, 314), the step-up dialog reached from every write, and
the copy control for the egress IP (105). Every state in this plan is asserted as text and never as colour alone (chips,
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

| Alias                                 | Environment | Kind | UID                    | Label                             | Created by                                                                                                                                                      |
| ------------------------------------- | ----------- | ---- | ---------------------- | --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `acct-demo-main`                      | demo        | main | `90000001`             | `QA Main`                         | TC-001 or setup                                                                                                                                                 |
| `acct-demo-sub1`                      | demo        | sub  | `90000011`             | `QA Sub 1`                        | TC-002 or setup                                                                                                                                                 |
| `acct-demo-sub2`                      | demo        | sub  | `90000012`             | `QA Sub 2`                        | Setup (Group D shared setup, TC-314, TC-414)                                                                                                                    |
| `acct-live-main`                      | live        | main | `90000001`             | `QA Main (live)`                  | TC-004 or setup; account shell only, never given a key                                                                                                          |
| `acct-live-sub1` .. `acct-live-sub21` | live        | sub  | `90000021`..`90000041` | `QA Live Sub 1`..`QA Live Sub 21` | Setup under `acct-live-main`: five for TC-005 and TC-015 (the sixth is the case's add), twenty for TC-014 (the 21st is its add); shells only, never given a key |

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
- A scenario can be switched for a stored key at runtime (needed by 126–129, 132, 204 and 212).
- "As `compliant`" means the `compliant` answers for everything the row does not change. Times
  ("after load") are relative to the test clock when the scenario is loaded.
- Overlays (origin `overlay`) seed exchange-side state and combine with any scenario; a case names
  them after its scenario.

<!-- prettier-ignore -->
| Scenario | Origin | The stub must return | Cases |
| --- | --- | --- | --- |
| `compliant` | ticket (verdict) | `query-api`: only `ContractTrade` (`Order`, `Position`) and `Derivatives` (`DerivativesTrade`), every other group empty (`Wallet` included), `ips` = egress, `uta` set, UID = the account's, `expiredAt` 365 days after load, `createdAt` more than 48 h before load. `wallet-balance`: `retCode` 0 within `recv_window`. Private WS: auth ok, a wallet snapshot, then a frame every 5 s; pongs. `fee-rate`, `set-leverage`, order create and cancel, and the mode-switch calls (`switch-mode`, `switch-isolated`, `set-margin-mode`) answer `retCode` 0. Position and open-order lists are empty unless an overlay seeds them. | Default of Groups B to E; named in 012, 101, 114, 115, 124, 211, 401, 408, 413, 419, 422; setup |
| `compliant_alt` | plan | As `compliant`, with a second key id | Via `rotation_ok` |
| `withdraw_enabled` | ticket | `query-api` lists `Withdraw` under `Wallet` | 102, 119, 126, 132a |
| `transfer_enabled`, `subtransfer_enabled`, `subtransfer_list_enabled` | plan | `query-api` lists `AccountTransfer`, `SubMemberTransfer` or `SubMemberTransferList` under `Wallet`, one per scenario | 103a–c |
| `fiat_p2p_enabled`, `fiat_bitpay_enabled`, `fiat_convert_broker_enabled`, `bitcard_enabled` | plan (#2417, E27 threat model AC-15) | One of the `FiatP2P`, `FiatBitPay`, `FiatConvertBroker` or `BitCard` groups non-empty, one per scenario (for example `FiatP2P: [FiatP2POrder]`) | 103d–g |
| `ip_missing` | ticket | `ips` empty | 104, 128, 132b |
| `ip_mismatch` | ticket | `ips` = `198.51.100.20` | 105, 127 |
| `ip_extra_foreign` | plan | `ips` = egress and `192.0.2.30` | 106a |
| `ip_wildcard` | plan (E27 threat model AC-15) | `ips` = `["*"]` | 106b |
| `uid_mismatch` | ticket | `query-api` reports UID `90000099` | 107 |
| `non_uta` | ticket | `query-api` reports `uta` unset (and the deprecated `unified` false) | 108 |
| `clock_skew` | ticket | `wallet-balance` fails on `recv_window` (recorded `10002` capture) with a server time 6 s off | 109 |
| `wallet_probe_error` | ticket | `wallet-balance` returns a recorded non-zero `retCode` on every call | 110 |
| `missing_trade_scope` | plan | No contract `Order`/`Position` scopes | 111 |
| `extra_scope_spot`, `extra_scope_options`, `extra_scope_exchange`, `extra_scope_nft`, `extra_scope_affiliate` | plan | The `Spot`, `Options`, `Exchange`, `NFT` or `Affiliate` group non-empty (SR-030a), one per scenario | 112 |
| `live_key_on_demo` | ticket (verdict) | Demo hosts reject the key id as unknown (recorded invalid-key capture); live hosts must never be called | 113 |
| `unknown_key` | plan | Identical answers to `live_key_on_demo`, for a key id no environment issued (a typo) | 133 |
| `demo_ws_unreachable` | plan | REST as `compliant`; the demo private WS refuses connections | 115 |
| `expiring_13d` / `expiring_15d` | ticket (verdict) | `expiredAt` 13 / 15 days after load | 116 / 117 |
| `expired_key` | plan | `expiredAt` 1 day before load | 212 |
| `new_key_48h` | ticket | As `compliant`, except that `query-api` reports `createdAt` 2 h before load. No other endpoint differs and no restriction answer is invented (C-13.5): the system must derive the restriction from `createdAt` (§10 DC-23) | 130 |
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
| `key_delete_5xx` | plan | As `compliant`; any Bybit key-delete endpoint answers HTTP 503. A negative guard: under the contract no build calls it (TC-306) | 306 |
| `close_rejected` | plan | As `compliant`; the position close is rejected (recorded capture) | 305 |
| `leverage_ok` | plan | As `compliant` (`set-leverage` `retCode` 0), named for the leverage cases | 415, 417, 418 |
| `leverage_refused_open_position` | plan | `set-leverage` refused with the recorded open-position reason | 416 |
| `open_position_btcusdt_5x_sl` | overlay | The position list holds one BTCUSDT position at 5x with a native stop-loss attached (recorded captures); closing orders fill; the mode-switch calls answer with the recorded open-position refusal | 126, 132, 205, 302–305, 310, 410, 412, 415–418, 420 |
| `working_orders_2` | overlay | The open-order list holds two resting BTCUSDT limit orders (recorded captures); cancels succeed; the mode-switch calls answer with the recorded active-order refusal | 126, 132, 205, 310, 314, 421 |
| `history_round_trip` | overlay | One BTCUSDT market order and its closing order fill (recorded execution captures), leaving the account flat with order, execution and audit history | 311 |

### 9.4 Step-up procedure

On `403 step_up_required`, call `POST /auth/step-up` with the password, a code from `totp_gen`
(E09 plan §6.2) and the `challenge_id`, then re-send the held request unchanged (same body and
`Idempotency-Key`). Key and account actions use a grace class: a second action within 5 minutes may
not be challenged again. Cases that assert the challenge (001, 206, 307, 315) therefore start from a
session without a live grant: sign in fresh or let the grace expire.

### 9.5 Clock control

The E09 frozen clock (E09 plan §6.3) is refused while an exchange key is present (#2086), so it cannot
drive E27. Day-scale cases (`Q02·clk`: key age, daily alerts, the hourly self-check of TC-132, the
48 h restriction, the 15-minute drain) need a test clock that works with stub keys and survives a
restart. PR 2's loader must provide it for automation, and the stub-transport follow-up for manual
runs; until then these cases run in E27-Q02 only.
Second-scale cases (30 s, 60 s) may be stopwatched in manual runs (§0).

### 9.6 Stub request log

Every stub answer is logged with timestamp, host and environment, method, path, the fabricated key id
that signed the request, whether the signature verified against the scenario secret, and the scenario
name. Cases assert on it (`LOG`): host isolation (113–115, 133), signing key (201–203, 301, 306, 313,
314), absence of exchange calls (124, 205, 301, 306, 410, 417), upstream call counts (123, 132, 422)
and the native SL kept (410). It holds no real secret, but it is still never pasted into a public
issue (§0.1).

## 10. Documentation conflicts found while authoring

The plan follows the source named in the "Plan follows" column. Rows marked #2417 are already tracked
by the contract-first alignment issue; the rest are new and need an owner decision or a docs fix
before E27-Q02 automates the affected cases.

<!-- prettier-ignore -->
| Id | Conflict | Plan follows | Cases | Tracked |
| --- | --- | --- | --- | --- |
| DC-01 | C-2.8 and SR-030a refuse transfer rights (SR-030a names `AccountTransfer` and `SubMemberTransfer`) and 21 §3.2.2 refuses them too, but `createApiKey` checks only `Withdraw` and its `201` example stores `Wallet: [AccountTransfer]`; `SubMemberTransferList` and the `FiatP2P`, `FiatBitPay`, `FiatConvertBroker` and `BitCard` groups are refused only by #2417's allow-list; the extra-scope rule is in SR-030a only | C-2.8, SR-030a, #2417 allow-list | 103, 112 | #2417 |
| DC-02 | SR-005 allows at most 4 clear characters of a key id; the contract's `key_id_masked` shows the first 4 and the last 4; #2417 (SR-E27-03) moves both to the last 4 only | SR-005 | 101, 118, §0.1 | #2417 |
| DC-03 | C-2.8 and C-12.2 require an allowlist on every key; the contract makes `require_ip_whitelist` default on for live only and says the egress IP must be "inside" the list, where SR-030a says the list must equal it (worded for live keys; #2417 applies it to every key and deletes the setting); SCR-125 shows "n/a" for a demo row | C-2.8, SR-030a as #2417 applies it | 104, 106 | #2417 |
| DC-04 | A failed stored-key check puts the whole system read-only in C-2.8 and C-12.2, force-disables one account in US-ACCT-003, and disables one credential in SR-032 | C-12.2 | 126–129, 132 | new |
| DC-05 | Self-check cadence: hourly (C-12.2), every 6 h (US-ACCT-003 NFR, SR-031), nightly (`createApiKey`); the E27 threat model picks hourly (SR-E27-05) | C-12.2 | 126–129, 132 | new |
| DC-06 | Rotation overlap: 15 min (US-ACCT-004), 900 s grace (21 §3.2.3), `overlap_seconds` default 300 (contract), 24 h (SR-035, ADR-0009 design item 5) | US-ACCT-004 | 201, 202 | #2417 |
| DC-07 | US-ACCT-004 and US-ACCT-006 attempt a Bybit revoke or delete; the contract revokes locally only, and #2417 keeps that because a compliant key cannot delete itself at Bybit; the open-position choice is missing from the contract. `key_delete_5xx` is therefore exercised only as a negative guard: an outbound delete call is a deviation, not a pass branch | Contract (local only) | 202, 301, 304, 306 | #2417 |
| DC-08 | Audit vocabulary differs between the ticket and screens (`account.*`), 04 §8.2 (`account.registered`, `key.*`) and the audit route's examples (`key.rotate`); no event exists for a leverage change, and the ticket's list has none for a revoke | §8.1 mapping | All with audit | new (SR-E27-09) |
| DC-09 | The key-age policy (US-ACCT-005, SCR-128) has no documented route or setting; SR-037 sets 180 days for demo keys while the story assumes 90 | UI only; policy set explicitly | 207–212 | new |
| DC-10 | SCR-129 makes delete irreversible and separate from disable; the contract's `DELETE` "marks it `disabled`"; 21 §3.2.1 soft-deletes | Observable outcome only | 308, 311 | new |
| DC-11 | `validation_failed` is 400 in the registry but 422 in `UnprocessableEntity` and the `createApiKey` example; `createExchangeAccount`, `createApiKey` and `rotateApiKey` document 422, `updateExchangeAccount` documents neither. `createApiKey` documents no 429 although `exchange_rate_limited` is 429; `risk_limit_breached` is 403 in the registry but 422 in the `UnprocessableEntity` example; `trading_disabled` covers only the kill switch and live enablement, so no code exists for a red, disabled or key-policy refusal | Each operation's documented status; the registry where none is documented | 009, 011, 102–113, 123, 410, 417 | new |
| DC-12 | The contract flags `balance_stale` after 10 s; US-ACCT-008 reconciles after 60 s of silence and greys the figures only when that fails. Bybit's wallet stream is change-driven, so a quiet, healthy account is flagged stale by the contract rule | Both, asserted separately | 403–407 | new |
| DC-13 | No per-account health push is documented: `system` carries one global `private_ws` state, `connection_state` is REST-only, and SCR-125 refreshes every 60 s, so the ≤30 s red deadline (US-ACCT-010) cannot be met on SCR-125 as specified | Deadline asserted on `connection_state` and order refusal; the row at its next refresh (≤ T0 + 90 s) | 408–413 | new |
| DC-14 | US-ACCT-009 sets per-symbol leverage, but the contract only offers `PUT /positions/{positionId}/leverage`, which needs an open position; 18 §2.2 lists it as `PATCH` | Contract | 415–418 | new |
| DC-15 | Leverage RBAC: 04 §7.2.2 row 18 allows only the Owner, while §7.2.1 grants `positions:write` to a Manager with a trade grant and US-ACCT-009's persona is "a trader" | 04 §7.2.2 | 418 | new |
| DC-16 | Duplicate-UID copy: "This UID is already registered as `<label>`" (US-ACCT-001) against "This Bybit UID is already connected as `'<label>'`." (SCR-126) | Message names the label | 003 | new |
| DC-17 | Sub-account cap: US-ACCT-001 lets the owner acknowledge the cap and add a sixth; US-ADMIN-014 blocks the add at capacity; the contract rejects "the 6th" with `conflict`, with no acknowledgement field and no tier condition. The tier is a recorded setting (`accounts.subaccount_tier`, read by `GET /admin/capacity`) with no documented write route, and `SubaccountCapacity.used` counts live sub-accounts only, so a demo sixth is undocumented | Contract, read against the recorded tier: `regular` 409 at the 6th, `business_kyc` 409 at the 21st, unrecorded 409 at the 6th | 005, 014, 015 | new |
| DC-18 | SR-030 stores a failing credential "disabled with a blocking banner"; the contract, 30 §7.2 and the ticket never persist a rejected key | Contract | 102–113 | new |
| DC-19 | 04 §7.2.1 requires step-up for `accounts:write` (SR-E27-02), but the `action_class` enum (`keys`, `users`, `live_enablement`, `killswitch`, `risk_caps`) has no class for account routes and the routes do not say which applies | 04 §7.2.1 | 001, 011, 308, 311 | new |
| DC-20 | `setUserAccountAccess` closes subscriptions with an `unsubscribed` frame that `23-ws-protocol.md` does not define; §9.5 uses `revoked` | 23 §9.5 | 301, 308, 312 | new |
| DC-21 | Story references: SCR-129 cites US-ACCT-008 in its validation line (disable and delete are US-ACCT-006); SCR-126 cites `US-SEC-004`, and no SEC domain exists in 11; SCR-127 cites US-ACCT-003; the ticket cites 21 "§3.13", which is §3.1.3 | Story text | — | new |
| DC-22 | CMP-034 is a "secret reveal" component with a reveal toggle, CMP-033 lists "API key display", and SCR-126 and SCR-127 use CMP-034, against US-ACCT-002's "no reveal control anywhere" | US-ACCT-002 | 118 | #2417 (reveal scope) |
| DC-23 | The 48 h restriction: ADR-0009, US-ONB-007 and US-ADMIN-013 block key creation on a new account; SCR-125, SCR-126, SCR-127 and SCR-079 describe a restriction on a new key, and SCR-017 and SCR-122 make it gate live use only. The contract has no representation: `KeyStatus` and `key_status` have no `restricted`, `createApiKey`'s pipeline has no 48 h step or warning, and no exchange answer for it is documented. ADR-0009 also has rotation create the new key through the Bybit API, where SCR-127 has the owner create it by hand | Screens; API pinned as `201` + one warning + `active`; demo order entry stays enabled; the live half is out of scope (no live keys) | 130, 201 | new |
| DC-24 | US-ACCT-010 invokes the dead-man's switch on red; SR-059 says Bybit's switch is inverse-only and E45-T05 owns an opt-in integration, with the native SL plus reconnect reconciliation as the compensating control | Deferred to E45-Q01; TC-410 asserts the native SL is kept | 410 | new |
| DC-25 | SCR-019 lists owner setup tasks ("add a live account", "record a symbol" and more) and reads `GET /onboarding/checklist`, whose `items[].key` enum (`tailscale`, `totp`, `sub_account`, `api_key`, `profile_limits`, `demo_session`) matches US-ONB-007's manager checklist and has no owner-task key | SCR-019 for the UI; the API body checked only against `OnboardingChecklist` | 013 | new |
| DC-26 | No screen spec defines the standalone key revoke of US-ACCT-006: SCR-125's row actions are edit, rotate key, disable and delete; SCR-129 covers disable and delete only; SCR-127 revokes only the old key inside a rotation; only CMP-176 has `onRevoke` | US-ACCT-006; confirm against E27-D02 | 301–307 | new |
| DC-27 | Key expiry: SR-030a requires `expiredAt` to be present and in the future; the contract checks it only "if set"; SR-034 assumes 90 days when it is absent. The `compliant` scenario sets an expiry 365 days ahead so it is compliant under every source; no case asserts the absent-expiry outcome until the owner decides | `compliant` satisfies all three | 101, 211 | new |
| DC-28 | SCR-128's "mark as compromised" emergency action (key disabled, orders halted, audited `admin.key_marked_compromised` at high severity) has no story, no route in the contract and no 04 §8.2 event, and the `Severity` enum has no `high` | SCR-128; UI-driven until a route exists | 314, 315 | new |
| DC-29 | US-ACCT-007's copy "key does not belong to this environment" names a verdict the system cannot reach without contacting live hosts (C-2.11 forbids it), so any key the demo hosts reject as unknown must get the same answer; the E27 threat model proposes the rule `key_wrong_environment` (AC-14) | Same status, rule and copy for a live key and an unknown key | 113, 133 | new |
| DC-30 | SCR-126 and SCR-016 run a Test connection before Save through `POST .../keys/{keyId}/test`, which needs a stored key; `createApiKey` verifies and stores in one call | Contract; verification runs are counted, not assumed to be one | 012, 101 | new |

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
| A: 001–015                                   | —         | demo              | `compliant` | pending (E27-S01)                            | —        | —      |
| B: 101–133                                   | —         | demo + stub       | per case    | pending (E27-S02, E27-T03, PR 2)             | —        | —      |
| C: 201–212                                   | —         | stub              | per case    | pending (E27-S03, E27-T04, PR 2, §9.5 clock) | —        | —      |
| D: 301–315                                   | —         | demo + stub       | per case    | pending (E27-S04, PR 2)                      | —        | —      |
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
