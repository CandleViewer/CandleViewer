# Runbook: audit integrity failure from the admin console (E42-T06)

Status: written 2026-11-03 against `main` at `d023df0f6`; not yet drilled (E48-Q02 rehearses it). The Security engineer
reviews this file before merge (the E42-T06 rule: a wrong instruction here turns an incident into a cover-up).
Owner: accounts-admin (E42-T06, #1085). Contributed to E48-T03's runbook set as the audit-chain step of RB-08
(post-restore verification), beside the E45 resilience runbooks.

Conventions: REST paths are relative to `$API`, your API base URL; `$TOKEN` is an Owner access token, sent as
`Authorization: Bearer $TOKEN`. Every state-changing call (`POST`, `PUT`, `PATCH`, `DELETE`) also sends the session's
CSRF token twice, as `X-CSRF-Token: $CSRF` and as `Cookie: __Host-cv_csrf=$CSRF`: there is no bearer exemption, and a
write without both answers `403 csrf_token_invalid` (SR-041). `$CSRF` is your own session's `__Host-cv_csrf` cookie
value, set at sign-in and re-issued by `GET $API/auth/session` when it is missing or no longer valid. All three come
from your own session and environment, never from this page. No secret, key material, host address or exploit detail
belongs in this file (C-12.2). Paths under `candleviewer/` mean `services/api/candleviewer/`. Where a procedure needs
something that does not exist, it says **BLOCKED — not implemented** with its tracking reference and offers no
substitute command.

Scope. This file adds the Owner's console path and the order of the acknowledgement to what already exists. It restates
none of the three alert responses; read them where they live, in [`07-release-and-prr.md`](../../plan/07-release-and-prr.md)
§9: [`AuditChainVerificationFailed`](../../plan/07-release-and-prr.md#alert-auditchainverificationfailed),
[`AuditVerifyNotPassing`](../../plan/07-release-and-prr.md#alert-auditverifynotpassing) and
[`AuditBreakHaltEngaged`](../../plan/07-release-and-prr.md#alert-auditbreakhaltengaged). The enforced posture (what a
break halts and what always passes) is owned by [`04-security-program.md`](../../plan/04-security-program.md) §8.1. The
evidence-first steps are [`auth-rbac.md`](auth-rbac.md) §5.

## Trigger

One of the three alerts above fires; an Owner's `POST /admin/audit/verify` answers `verified: false`; or an audit page
answers `chain_verified: false`, which is not evidence of tampering by itself (it can mean a page that was not fully
checked) and calls for a verify run.

## Detection

- Alerts (all Page): `AuditChainVerificationFailed`, `AuditVerifyNotPassing`, `AuditBreakHaltEngaged`.
- Metrics (`20-architecture.md` §12.1): `cv_audit_chain_verified_state` (1 after a genesis-to-head run, 0 on a break, NaN
  before a run), `audit_chain_verification_failures_total`, `cv_audit_verify_last_ok_timestamp_seconds`,
  `cv_audit_verify_runs_total{result}`, `cv_audit_break_halt_state`. The ticket's `cv_audit_chain_verified` is not a served
  name.
- Records: `admin.audit_verify` (a `started` record before each run and a result, critical when `verified` is false),
  `audit.chain_break_halted`, `audit.chain_break_acknowledged` and `audit.chain_break_ack_denied`; the system event
  `audit_chain_break` names the break (`first_bad_id`, `kind`). Read them as the Owner with
  `GET $API/admin/audit?action=<code>`.
- The kill switch shows engaged to every client while the halt stands; only the Owner's view carries the reason,
  `audit_chain_break` (a Manager or Viewer sees that it is engaged, its scope and since when). A reason of
  `audit_halt_unread` means the halt records could not be read and the API failed closed: there is no break to
  acknowledge, so follow rows 2 and 5 of the
  [`AuditBreakHaltEngaged`](../../plan/07-release-and-prr.md#alert-auditbreakhaltengaged) response, not step 5.

## Prerequisites

An Owner session: only the Owner may verify or acknowledge (a Manager holding `audit:read` or `killswitch:write` is refused
`403`). The acknowledgement also needs a fresh `killswitch` step-up code, which has no grace: see
[`admin-reauth.md`](admin-reauth.md).

## Steps

1. **Confirm; it changes no audit row.**
   **Do:** the Owner's console path is **BLOCKED — not implemented**: the overview's "Run tamper check" and SCR-135 belong to
   E42-S04 (#1135). Use the REST path: follow [`auth-rbac.md`](auth-rbac.md) §5 step 1 as written, both runs. The first
   covers the chain:
   `curl -s -X POST "$API/admin/audit/verify" -H "Authorization: Bearer $TOKEN" -H "X-CSRF-Token: $CSRF" -H "Cookie: __Host-cv_csrf=$CSRF" -H 'Content-Type: application/json' -d '{}'`.
   The second runs over a range that ends just before `first_bad_id` (`to_id`), to confirm the chain before the break is
   intact (optional `from_id` and `to_id`; the contract is `verifyAuditChain`, `22-api-openapi.yaml:11489`).
   **Expect:** `200` with `verified`, `entries_checked`, `first_bad_id`, `checked_at`, `from_id`, `to_id`, `anchor_hash` and
   `last_hash`. `verified: false` with a `first_bad_id` is the break, and the ranged run answers `verified: true`.
   `entries_checked: 0` proves nothing. A passing range never sets `cv_audit_chain_verified_state` back to 1: only a run
   from genesis to the head that finds no break does (`candleviewer/api/audit_verify.py:13-16`). Refusals: `409` (a run
   is already going, the scheduled one included), `429` (30 runs an hour), `404` (a `from_id` beyond the head), `422` (a
   span over `audit_verify_max_span`) and `503 store_unavailable` (the run hit its deadline, a read timeout or an entry over
   the size cap; it reports nothing as verified and is recorded). A run that finds a break also engages the order-entry halt if it is not engaged
   already (`04` §8.1). Ids are not contiguous (`auth-rbac.md` §5).
2. **Preserve the evidence before anything else.**
   **Do:** follow `auth-rbac.md` §5 steps 2 to 4 as written: save both answers, take the off-host copy, notify the Owner and
   the Security engineer, and keep the system running for the evidence.
   **Expect:** a stored copy and a named person who owns the incident.
3. **Name the break.**
   **Do:** `GET $API/admin/audit?action=audit.chain_break_halted` for the record, the dependable source: its `object_id` is
   `<first_bad_id>:<kind>`. The `audit_chain_break` system event is listed by `GET $API/admin/incidents`
   (`listIncidents`), but that read model normalises its `title`, stripping ids and numbers, so read the two values from
   the record.
   **Expect:** the `first_bad_id` and the `kind`, one of `prev_hash_mismatch`, `entry_hash_mismatch`, `checkpoint_mismatch`,
   `checkpoint_missing`, `tail_truncated` or `unknown`.
4. **Settle the incident first.**
   **Do:** work IR-06 in [`04-security-program.md`](../../plan/04-security-program.md) §10.3. Whether to engage the global
   kill switch as well, while the halt already stops new risk, is the Owner's decision there (its step 1). Its code-free
   engage is **BLOCKED — not implemented** (E39-S03); the order-entry kill-switch flag is the stop control the console serves,
   and [`admin-flag-rollback.md`](admin-flag-rollback.md) says how the two differ.
   **Expect:** a written finding from the Security engineer. Do not acknowledge before it.
5. **Acknowledge the named break.**
   **Do:** once IR-06 has settled it, the Owner calls `POST $API/admin/audit/chain-breaks/{firstBadId}/acknowledge`
   (`acknowledgeAuditChainBreak`, `22-api-openapi.yaml:11648`) with `kind`, a `reason` of 3 to 280 printable characters and
   the CSRF headers (Conventions). It answers `403 step_up_required` with `action_class: killswitch` until the Owner steps
   up (`admin-reauth.md`); the fresh code is spent on that exact request, which is then sent once, unchanged. The
   break-glass command for when the app cannot is in the
   [`AuditBreakHaltEngaged`](../../plan/07-release-and-prr.md#alert-auditbreakhaltengaged) response, not copied here.
   **Expect:** `200` with `halted`; `audit.chain_break_acknowledged` is written ahead; `cv_audit_break_halt_state` reads 0
   within 5 seconds. A `409` means the break is unknown to this process, already acknowledged or of another `kind`: retry
   after about 10 seconds if it was found just now. `503 audit_unavailable` leaves the halt engaged.

## Verification

`cv_audit_break_halt_state` reads 0 and, on demo, an entry order is accepted once any kill switch engaged at step 4 has
been released by its own decision ([`admin-flag-rollback.md`](admin-flag-rollback.md), with a fresh `killswitch` code):
acknowledging a break never releases a kill switch (`04-security-program.md` §8.1). The per-alert checks are rows 7 of
the three sections in `07` §9. The acknowledgement does not repair the chain: the same break is found and paged again at
every start and every daily run while it stands, and no longer halts once acknowledged, while a different break halts
again. Recovery of the chain itself is IR-06's restore path; a verify run over the restored chain must pass, and its
record is the evidence.

## Rollback, and what cannot be undone

A verify run changes no audit row (it writes its own records); one that finds a break engages the halt. The
acknowledgement cannot be undone by an operator: it lifts the halt for that named break and is on the chain for good. Never edit, repair, rebuild or truncate an audit table, never re-run or add
migrations on one, and never restore a backup over the live database before the evidence copy exists and the Security engineer
agrees: each destroys the signal this runbook exists to keep.

## Known gaps

| Gap                                                                                                                                        | Reference                          |
| ------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------- |
| The console path: the overview's "Run tamper check", SCR-135 and the break's own screen                                                    | E42-S04 (#1135)                    |
| The chain is unkeyed: the database owner role or a superuser can rewrite the chain consistently (AD-T02); only off-box anchors detect that | #1238 (the anchors), RR-17 in `04` |
| The break-glass acknowledgement runs on the trading host and is not rehearsed                                                              | E48-Q02                            |

## Execution record

Not executed: no staging host exists (#1778 item A), and the rehearsal is E48-Q02's. Every route, record and metric above was
read against the code and the contract at `d023df0f6`. `auth-rbac.md` §5's background paragraph said the scheduled verifier
and its alert did not exist; the paragraph was corrected in the same change as this file.
