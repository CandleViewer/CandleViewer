# Runbook: flag rollback from the admin console (E42-T06)

Status: written 2026-11-03 against `main` at `d023df0f6`; not yet drilled (E48-Q02 rehearses it). Two parts describe work
that is **in flight** and are marked so: the console path (E42-S05, #1024, as built on its branch at `db0f3979f`, "if
#1024 merges as is") and the armed-rule acknowledgement (the contract in #5570, "if #5570 merges as is"). Re-pin both at their
merge commits; until then the REST path and the server's behaviour are what `main` serves.
Owner: accounts-admin (E42-T06, #1085). Contributed to E48-T03's runbook set as RB-11, the flag half. The trading kill
switch is RB-12.

Conventions: REST paths are relative to `$API`, your API base URL; `$TOKEN` is an Owner access token, sent as
`Authorization: Bearer $TOKEN`. Every state-changing call (`POST`, `PUT`, `PATCH`, `DELETE`) also sends the session's
CSRF token twice, as `X-CSRF-Token: $CSRF` and as `Cookie: __Host-cv_csrf=$CSRF`: there is no bearer exemption, and a
write without both answers `403 csrf_token_invalid` (SR-041). `$CSRF` is your own session's `__Host-cv_csrf` cookie
value, set at sign-in and re-issued by `GET $API/auth/session` when it is missing or no longer valid. All three come
from your own session and environment, never from this page. No secret, key material, host address or exploit detail
belongs in this file (C-12.2). Paths under `candleviewer/` mean `services/api/candleviewer/`. Where a procedure needs
something that does not exist, it says **BLOCKED — not implemented** with its tracking reference and offers no
substitute command.

## What a flag change is, and is not

- A flag change flips a stored value the server reads. Kill-switch-class flags are re-read at least every 5 seconds;
  others may be served from a 30-second cache (`22` `listFeatureFlags`). A committed write is pushed to every session
  the flag's visibility admits, on the `system` topic, within 2 seconds.
- A flag change **never closes a position and never touches a native stop**. It stops or starts a feature, or refuses
  new exposure; resting orders and open positions stay as they are.
- The kill-switch-class flags **are flags**, and this procedure writes them: `killswitch.order_entry`,
  `killswitch.ingestion` and `maintenance.mode`. Engaging one is the stop direction and needs only the `flags` grace;
  releasing one needs a fresh `killswitch` code. They take no overrides.
- **E39's trading kill switch (B18, `POST /trading/kill-switch`) is a different control.** Its route is not mounted
  today (the `POST /trading/kill-switch` row of `services/api/tests/contract/rbac/matrix.yaml`), so its code-free engage
  is **BLOCKED — not implemented** (E39-S03; the host-console fallback `candleviewer kill` is E39-T05). This console is
  not the emergency control.
- No flag may be defined to gate a security control: the registry refuses such a definition and the app will not boot
  with one (C-4.14; [ADR-0043](../../plan/27-adrs/ADR-0043-feature-flags-never-gate-a-security-control.md) states the
  limits). Behaviour a flag does not cover is rolled back by a release
  ([`07-release-and-prr.md`](../../plan/07-release-and-prr.md) §7).

## Trigger

A rollout behind a flag misbehaves (`trading.oms_enabled`, `trading.trade_groups`, `engine.webgl_v2`, `algo.*` and the
rest of the 19 keys the registry serves); a change just made must be undone; or new exposure or ingestion must be stopped
from the console.

## Detection

- Metrics: `cv_feature_flag_changes_total{flag,result}` (conflicts and refusals show in `result`),
  `cv_flag_push_latency_seconds` (budget 2 seconds) and `cv_maintenance_mode` (1 for maintenance **or** the order kill
  switch, so read the flag to tell which): `20-architecture.md` §12.1.
- Records: `flags.change` for every attempt past RBAC, refused ones included, written ahead of the write
  (`GET $API/admin/audit?action=flags.change&subject_type=feature_flag&subject_id=<flagKey>`); `maintenance.enabled` and
  `maintenance.disabled` for `maintenance.mode`; `auth.step_up_required` and `auth.step_up_mismatch` for the challenge.
- Logs: `feature_flag_store_unavailable` (the store could not be read). Two counters watch the polls that keep the
  order gate and the flag views in step, `cv_order_entry_gate_poll_dead_total` and `cv_flag_view_stopped_total{flag}`: a
  death latches order entry engaged, or that flag off, until the API restarts, and logs `order_entry_gate_poll_dead` or
  `flag_view_poll_dead` at CRITICAL.
- **No alert rule reads these series, nor a flag-store outage** (`infra/prometheus/alerts/`, checked at `d023df0f6`;
  Known gaps). The two poll-death counters page only through their `cv_page` CRITICAL log line (`20-architecture.md`
  §12.1; #4973, #5053), and nothing in `infra/` consumes `cv_page` yet.

## Prerequisites

An Owner session, and the password and authenticator for the step-up
([`admin-reauth.md`](admin-reauth.md)). A reason in plain words: a `reason` that carries a credential is refused with
`422 credential_in_reason` and is stored only as `<redacted:credential>`.

## Steps

### On `main`: the REST path

1. **Read the flag.**
   **Do:** `curl -s "$API/admin/feature-flags" -H "Authorization: Bearer $TOKEN"` and note the flag's `value` and
   `updated_at`.
   **Expect:** `200` with `resolution: stored`. `resolution: fail_closed` means the flag store could not be read: every
   flag then shows its fail-closed value and carries no `updated_at`, and a write is `503`; stop and follow step 5. A flag
   marked `unreadable: true` is repaired by a write with a valid value and its `expected_updated_at`.
2. **Write it.**
   **Do:** `curl -s -X PUT "$API/admin/feature-flags/<flagKey>" -H "Authorization: Bearer $TOKEN" -H "X-CSRF-Token: $CSRF" -H "Cookie: __Host-cv_csrf=$CSRF" -H 'Content-Type: application/json' -d '{"value": <true or false>, "reason": "<why, in words>", "expected_updated_at": "<updated_at from step 1>"}'`
   (`setFeatureFlag`, `22-api-openapi.yaml:12494`; the contract is `PUT`, not the `PATCH` E48-T03's text names).
   **Expect:** `403 step_up_required` with the class chosen under the flag's row lock: `flags` for every write but two;
   `killswitch` to release a kill-switch-class flag (a write from its engaged value); `live_enablement` to write `true` to
   `trading.live_enabled`. Step up ([`admin-reauth.md`](admin-reauth.md) step 1), then send the same request once; a
   no-grace grant is bound to that exact request.
3. **Read the answer.**
   **Do:** read the status and the body of the re-sent `PUT`.
   **Expect:** `200` with the `FeatureFlag` and its new `updated_at`. `409 conflict` carries the flag as stored in `current`:
   someone changed it since step 1, so read it again and decide; never retry blind. `422 validation_failed` names its rule
   (`required`, `kind_mismatch`, `unknown_user`, `invalid_character`, `overrides_not_allowed`, `gate_evidence_required`,
   `credential_in_reason`); nothing was written. `404` is an unknown key, `403` a non-Owner, `503 store_unavailable`
   nothing written.
4. **`trading.live_enabled`.**
   **Do:** by REST, writing `false` (live trading off) is an ordinary write in the `flags` class, as in steps 1 to 3.
   Writing `true` needs a fresh `live_enablement` code, a `reason` and an `evidence_url` (`22` `setFeatureFlag`; the
   evidence binding is E44-T04): that is the R4 release gate's business, outside this runbook. The console's
   **Change…** is disabled for this flag in both directions (step 6). In an incident the stop control is RB-12, the
   trading kill switch, whose code-free engage is **BLOCKED — not implemented** (E39-S03).
   **Expect:** `false` answers as steps 2 and 3 say; a `true` without `evidence_url` is `422 validation_failed` with
   rule `gate_evidence_required`, and nothing is written.
5. **The flag store is unreachable.**
   **Do:** write nothing: every write answers `503` until the store can be read again.
   **Expect:** the order kill switch and maintenance mode resolve engaged, `trading.live_enabled` resolves off and
   `killswitch.ingestion` resolves to its default (AD-D02, accepted); order entry that opens exposure is refused while
   cancels, closes and native stops pass. Follow `PostgresDown` in [`07-release-and-prr.md`](../../plan/07-release-and-prr.md) §9.

### In flight: the console path (E42-S05, #1024; if #1024 merges as is)

6. **Do:** open `/admin/flags` (SCR-145). The flags appear in four groups. **Change…** on the flag's row opens a
   confirmation with **Why?** (the server requires it), the step-up line and the marker `flags.change`; SCR-006 opens inside
   it if a code is needed, and the held `PUT` is sent once. A change shows on the row only with the server's answer.
   **Expect:** the row updates from the answer, offers **Revert to {previous}**, and every other session sees the change
   without a reload. Engaging a kill-switch-class flag needs the `flags` grace; releasing one asks for a fresh code, always.
   `trading.live_enabled`'s **Change…** is disabled with a visible reason and a link to the security centre (SCR-137);
   `maintenance.mode` links to SCR-148 ([`admin-maintenance-mode.md`](admin-maintenance-mode.md)).
7. **When the page says changes wait for the store** (`fail_closed`), or a change is refused.
   **Do:** for the store notice, wait or follow step 5; for a `409`, take **Use the current value** and decide again;
   for a `422`, correct what it names under **Why?**.
   **Expect:** every control points at the one store notice while it stands; a `503` or no answer is checked by a
   re-read, and nothing is shown as changed until it reads back.
8. **Read the history.**
   **Do:** open **History**, the disclosure row under the flag with its newest three merged changes. Its link to the audit
   log screen (SCR-135) filtered to the flag is **BLOCKED — not implemented** until E42-S04 (#1135) lands: read the same
   records with the REST query in Detection.
   **Expect:** the change just made, among the newest three.

### In flight: the armed-rule acknowledgement (#5570, contract only; if #5570 merges as is)

9. When it merges, `GET $API/admin/feature-flags/{flagKey}/dependents` (Owner only) lists the armed rules that read the flag,
   and a write must carry `acknowledged_dependents` holding exactly their ids, compared as sets. A write that does not
   answers `422 validation_failed` with rule `dependents_unacknowledged` and the live list, the `missing` ids and the
   `unexpected` ones. **Do:** read the list again and acknowledge exactly that set; never reuse an older list.
   **Expect today: nothing to do.** No flag has a dependent until a row of `24-internal-schemas.md` §16.4 lands with the code
   that reads the flag (E35), so every live set is empty and no write needs an acknowledgement. While
   `POST /trading/kill-switch` is not mounted, a write in the stop direction (engaging a kill-switch-class flag, or turning
   off a flag that admits order entry or rule actions) is never refused by this check. Re-read this step at the merge.

## Verification

1. `GET $API/admin/feature-flags` shows the new `value` and a later `updated_at`.
2. The `flags.change` record (Detection) shows `before`, `after` and the `reason`, written before the change committed.
3. A second session shows the change without a reload within about 2 seconds; `cv_flag_push_latency_seconds` stays within
   its budget.
4. For `killswitch.order_entry` or `maintenance.mode`, `cv_maintenance_mode` reads 1 when engaged and 0 when released
   (only when both are off), and, on demo, an entry order answers `403 trading_disabled` with `reason: maintenance` while
   engaged.

## Rollback, and what cannot be undone

- **Rollback of a rollback:** write the previous value, from **Revert to {previous}**, History or the `before` of the
  `flags.change` record. Each direction needs its own step-up.
- A flag change itself is reversible. What it did in between is not always: positions, resting orders and native stops
  were never touched, but the contract has entering maintenance mode cancel running emulated algos, and leaving it restarts
  none (none is cancelled today: [`admin-maintenance-mode.md`](admin-maintenance-mode.md)). The audit record of every
  attempt is permanent.
- **With the API down:** **BLOCKED — not implemented**: no host-side flag command exists, and no ticket tracks one yet
  (the owning epic is E42). Follow the rollback procedure in [`07-release-and-prr.md`](../../plan/07-release-and-prr.md)
  §7 (flags are its first line only while the API answers). An unreachable store is step 5.

## Known gaps

| Gap                                                                                                   | Reference                 |
| ----------------------------------------------------------------------------------------------------- | ------------------------- |
| The armed-rule dependents read and acknowledgement: the contract is in flight and no table row exists | #5570; E35 (`24` §16.4)   |
| The History link to the audit screen (SCR-135)                                                        | E42-S04 (#1135)           |
| The trading kill switch route and its host-console fallback                                           | E39-S03, E39-T05          |
| No host-side flag command                                                                             | E42, no ticket yet        |
| No alert rule reads the flag, gate or view series, or a flag-store outage                             | E04 or E42, no ticket yet |
| `trading.live_enabled`'s write path (the evidence binding)                                            | E44-T04                   |

## Execution record

Not executed: no staging host exists (#1778 item A), and the rehearsal is E48-Q02's. The REST path and the server's
behaviour were read against the code and the contract at `d023df0f6`; the console path against `db0f3979f` on its
branch, and the dependents text against the head of #5570, neither merged.
