# Runbook: maintenance mode, entry and exit (E42-T06)

Status: written 2026-11-03 against `main` at `d023df0f6`; not yet drilled (E48-Q02 rehearses it). The console path is
**in flight** (E42-S05, #1024, as built on its branch at `db0f3979f`, "if #1024 merges as is"); the REST path and the server's
behaviour, including what is not wired, are what `main` serves. Re-pin the console path at #1024's merge.
Owner: accounts-admin (E42-T06, #1085). Contributed to E48-T03's runbook set as RB-17. It uses the flag procedure of
[`admin-flag-rollback.md`](admin-flag-rollback.md) (RB-11), which says in full what a flag change is and is not.

Conventions: REST paths are relative to `$API`, your API base URL; `$TOKEN` is an Owner access token, sent as
`Authorization: Bearer $TOKEN`. Every state-changing call (`POST`, `PUT`, `PATCH`, `DELETE`) also sends the session's
CSRF token twice, as `X-CSRF-Token: $CSRF` and as `Cookie: __Host-cv_csrf=$CSRF`: there is no bearer exemption, and a
write without both answers `403 csrf_token_invalid` (SR-041). `$CSRF` is your own session's `__Host-cv_csrf` cookie
value, set at sign-in and re-issued by `GET $API/auth/session` when it is missing or no longer valid. All three come
from your own session and environment, never from this page. No secret, key material, host address or exploit detail
belongs in this file (C-12.2). Paths under `candleviewer/` mean `services/api/candleviewer/`. Where a procedure needs
something that does not exist, it says **BLOCKED — not implemented** with its tracking reference and offers no
substitute command.

What maintenance mode does today, and nothing more (`22` `setFeatureFlag`; `candleviewer/admin/flags/maintenance.py`):

- While `maintenance.mode` **or** `killswitch.order_entry` is on, or either cannot be read, the shared order-entry gate
  refuses every submission that opens or increases exposure with `403 trading_disabled` and `reason: maintenance`, before
  any OMS work. Cancels, `closePosition`, `closeAllPositions`, quantity-reducing and stop-tightening amends stay, as does
  attaching a missing native stop. Native exchange stops are never touched.
- Turning it on or off sends every session a `notice` on the `system` topic within 2 seconds (`23-ws-protocol.md` §15.9) and
  writes `maintenance.enabled` or `maintenance.disabled`.
- It is a flag: the write is `setFeatureFlag`, the stop direction needs the `flags` grace and the exit needs a fresh
  `killswitch` code. It is not E39's trading kill switch (see RB-11).

## Trigger

Planned maintenance (a release, a migration, a restore) where new exposure must stop first; or an incident in which new
exposure must stop and the Owner chooses this control.

## Detection

- `cv_maintenance_mode`: 1 while the order gate is engaged by maintenance **or** by the order kill switch, so it cannot tell
  which: read both flags (`GET $API/admin/feature-flags`). `cv_order_entry_refusals_total{reason}` shows the refusals.
- Records: `maintenance.enabled` and `maintenance.disabled` (`GET $API/admin/audit?action=maintenance.enabled&action=maintenance.disabled`);
  `flags.change` for the write; the shell shows the `notice` to every role.
- **No alert rule reads `cv_maintenance_mode`** (`infra/prometheus/alerts/`, checked at `d023df0f6`; Known gaps).
  `cv_order_entry_gate_poll_dead_total` counts the poll that keeps the gate in step ending: it latches the gate engaged until
  the API restarts and logs `order_entry_gate_poll_dead` at CRITICAL (`20-architecture.md` §12.1).
- Maintenance that is on and that nobody turned on: the flag store may be unreachable, which resolves it engaged (fail
  closed; the log has `maintenance_state_unknown`): follow `PostgresDown` in
  [`07-release-and-prr.md`](../../plan/07-release-and-prr.md) §9. Or the order kill switch is engaged, or the poll died.

## Prerequisites

An Owner session; the password and authenticator for two step-ups ([`admin-reauth.md`](admin-reauth.md)): the `flags`
class to enter, a fresh `killswitch` code to leave. A reason in plain words (never a credential).

## Steps

1. **Pre-check: no position is open and unprotected** (RB-17's rule).
   **Do:** the console cannot count open positions today (its dialog reads "unavailable" until a provider exists), so read
   them yourself: `curl -s "$API/positions?open_only=true" -H "Authorization: Bearer $TOKEN"`.
   **Expect:** every open row has `native_stop_present: true` and a `stop_loss`. A position with `native_stop_present: false`
   is an alarm condition: stop here and follow `NakedPositionDetected` in `07` §9; do not enter maintenance over it.
   `503 store_unavailable` means the read store is not served (the fake backend): you cannot make this check, so do not
   proceed.
2. **Enter.**
   **Do (REST, on `main`):** read the flag's `updated_at` (`GET $API/admin/feature-flags`), then
   `curl -s -X PUT "$API/admin/feature-flags/maintenance.mode" -H "Authorization: Bearer $TOKEN" -H "X-CSRF-Token: $CSRF" -H "Cookie: __Host-cv_csrf=$CSRF" -H 'Content-Type: application/json' -d '{"value": true, "reason": "<why, in words>", "expected_updated_at": "<updated_at>"}'`;
   it answers `403 step_up_required` with `action_class: flags` until the Owner steps up, then send it once. The answers (`409`,
   `422`, `503`) are RB-11 step 3.
   **Do (console, in flight):** `/admin/maintenance` (SCR-148), **Turn on…**: a confirmation that lists what is refused and
   what stays, with **Why?**; no typed confirmation. A `409` already in the state asked for closes the dialog and the status
   line says so.
   **Expect:** `200`; the gate closes before the write returns; `maintenance.enabled` is recorded; every session gets the
   `notice`; `cv_maintenance_mode` reads 1.
3. **What does not happen today.**
   **Do:** nothing: each item below is **BLOCKED — not implemented**, and no substitute command exists.
   **Expect:** exposure-opening submissions refused, and resting orders left alone (resting entry orders can still fill).
   Not done:
   - Cancelling running emulated algos at entry (#5629): the controller is built without an algo canceller
     (`candleviewer/flags_wiring.py:320-322`), so entering logs `maintenance_algo_cancel_unavailable` and cancels nothing;
     no emulated algo exists yet either (E33, `docs/security/threat-models/E33-emulated-algos.md` §1.1).
   - Pausing the recorder when `maintenance.keep_recorder` is `false` (#5629): no recorder control is wired, so the
     recorder keeps running whatever that flag says.
   - The scheduled window and the message to users: not built (#2764).
4. **Work the maintenance.**
   **Do:** the planned work; nothing here touches a native stop. A restore needs maintenance on first: by contract it
   answers `409` with rule `maintenance_mode_required` while maintenance is off
   ([`admin-restore-drill.md`](admin-restore-drill.md), where the console restore is BLOCKED).
   **Expect:** `cv_maintenance_mode` stays 1, and entry orders stay refused, until step 5.
5. **Exit.**
   **Do (REST):** the same `PUT` with `"value": false` and the `updated_at` read again; it answers `403 step_up_required`
   with `action_class: killswitch`, which has no grace: the fresh code is spent on that exact request, sent once.
   **Do (console, in flight):** **Turn off…** on SCR-148: always a fresh code.
   **Expect:** `200`; `maintenance.disabled` recorded; every session gets the `notice`; the gate opens **only when both
   `maintenance.mode` and `killswitch.order_entry` read off and readable**, so `cv_maintenance_mode` stays 1 while the order
   kill switch is engaged or either flag is unreadable.

## Verification

At entry: `cv_maintenance_mode` is 1, the `maintenance.enabled` record exists, an open position still shows its native stop,
and, on demo, an entry order answers `403 trading_disabled` with `reason: maintenance` while a cancel and a close are
accepted. At exit: `cv_maintenance_mode` is 0 (if the order kill switch is off), `maintenance.disabled` exists, and, on demo,
an entry order is accepted.

## Rollback, and what cannot be undone

Rollback is the exit (step 5). Entry changes nothing that has to be restored on the exchange. Leaving resumes a recorder
that maintenance paused (none is paused today, step 3). What exit cannot undo: any emulated algo cancelled at entry
stays cancelled, since nothing in `main` restarts one, and every record written is permanent. A `killswitch` grant is
single-use and bound to its request: after a refused or failed attempt, treat it as spent and step up again before
retrying.

## Known gaps

| Gap                                                                           | Reference                                                             |
| ----------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| Entry cancels no emulated algo: the canceller is not wired and no algo exists | #5629; E33 (`docs/security/threat-models/E33-emulated-algos.md` §1.1) |
| `maintenance.keep_recorder` has no effect: no recorder control is wired       | #5629                                                                 |
| The scheduled window and the message to users                                 | #2764                                                                 |
| The console counts no open positions ("unavailable")                          | E42-D04 §10 (CG-21: a position provider)                              |
| No alert rule reads `cv_maintenance_mode`                                     | E04 or E42, no ticket yet                                             |
| The console path is not on `main`                                             | E42-S05 (#1024)                                                       |

## Execution record

Not executed: no staging host exists (#1778 item A), and the rehearsal is E48-Q02's. The server's behaviour was read against
the code and the contract at `d023df0f6`, and the console path against `db0f3979f` on its branch, which is not merged.
