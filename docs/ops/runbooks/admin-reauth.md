# Runbook: admin re-authentication troubleshooting (E42-T06)

Status: written 2026-11-03 against `main` at `d023df0f6`; not yet drilled (E48-Q02 rehearses it).
Owner: accounts-admin (E42-T06, #1085). Contributed to E48-T03's runbook set, which has no id for it yet. It supports
the model that ADR-0042 records.

Conventions: REST paths are relative to `$API`, your API base URL; `$TOKEN` is an access token of the stated role,
sent as `Authorization: Bearer $TOKEN`. Every state-changing call (`POST`, `PUT`, `PATCH`, `DELETE`) also sends the
session's CSRF token twice, as `X-CSRF-Token: $CSRF` and as `Cookie: __Host-cv_csrf=$CSRF`: there is no bearer
exemption, and a write without both answers `403 csrf_token_invalid` (SR-041). `$CSRF` is your own session's
`__Host-cv_csrf` cookie value, set at sign-in and re-issued by `GET $API/auth/session` when it is missing or no longer
valid. All three come from your own session and environment, never from this page. No secret, key material, host
address or exploit detail belongs in this file (C-12.2). Paths under `candleviewer/` mean
`services/api/candleviewer/`. Where a procedure needs something that does not exist, it says **BLOCKED — not
implemented** with its tracking reference and offers no substitute command.

The model, in one paragraph (ADR-0042, D8): there is **no admin window, no admin token and no admin unlock**. Entering
`/admin/*` asks for nothing. Each protected action is challenged by the server, per action class
(`403 step_up_required`), and answered with the password and a TOTP code in the step-up dialog (SCR-006), which holds
the refused request and sends it again once. An admin unlock badge with its own countdown was a design variant
(E42-D03's variant (a)) that D8 did not take.

Quick facts the procedures rely on (the map is ADR-0042 decision 1; `22` `authStepUp` and `candleviewer/auth/step_up.py`
win where this table differs):

| Fact             | Value                                                                                       | Source                       |
| ---------------- | ------------------------------------------------------------------------------------------- | ---------------------------- |
| Grace classes    | `keys`, `users`, `risk_caps`, `recorder`, `flags`, `audit`: 5 minutes after the step-up     | `auth/step_up.py:88`, `:101` |
| No-grace classes | `live_enablement`, `killswitch`, `backups`, `recorder_purge`, `accounts`: a fresh code each | `auth/step_up.py:119`        |
| A no-grace grant | one use, bound to the challenged request, valid 60 seconds                                  | `auth/step_up.py:133`        |
| A challenge      | 5 minutes; one live per session; a newer `403` replaces it                                  | `auth/step_up.py:132`        |
| Wrong codes      | three in a row make the session read-only for 5 minutes                                     | `auth/step_up.py:90`, `:92`  |
| Idle lock        | 15 minutes by default (5 to 60); it clears every grant                                      | `22:260-268`; ADR-0010       |

## Trigger

An Owner asks why a code is asked again; an admin action answers `403 step_up_required`; the step-up dialog refuses a
code; a session turns read-only; or a step-up answers `503`. Start from the symptom in Steps.

## Detection

Every write and refusal is recorded, and so is the first allowed admin read of each session, route, address and step-up
window, with a count of the rest (#5331). Read the records as the Owner with `GET $API/admin/audit?action=<code>`
(repeat `action` for several).

- Audit actions: `auth.step_up_required` (a challenge issued; it carries the `challenge_id`), `auth.step_up_granted`,
  `auth.step_up_failed` (a wrong password or code, or a challenge that cannot be answered), `auth.step_up_mismatch`
  (another request than the one challenged, no-grace classes), `auth.step_up_grace_used` (a write inside a live grace)
  and `auth.session_readonly_downgrade` (the third wrong code, severity high).
- `admin.area_entered` records every admin write and refusal, and the first allowed read of each session, route,
  address and step-up window with a count of the rest (#5331), each with `reauth_age_s`: the whole seconds since the
  session's last step-up, or `null` when the row holds none (never stepped up, a spent single-use grant, a lapsed
  grace, an idle lock, a read-only downgrade or a refreshed token's new row). It is observability: it never refuses
  and is not a freshness test.
- Metrics: `auth_stepup_failures_total`, `auth_step_up_total`, `auth_readonly_downgrades_total` (names as
  `candleviewer/auth/metrics.py` registers them).
- There is no alert on step-up failures (Known gaps). A burst of `auth.step_up_failed` or `auth.step_up_mismatch` from a
  session the Owner does not recognise is a possible stolen session: go to Escalation.

## Prerequisites

The Owner's password and authenticator in hand. An Owner session for the audit reads. For a script, `POST $API/auth/step-up`
takes `challenge_id`, `password` and `code` and sends the CSRF headers (Conventions); a script that handles the password
is out of scope here.

## Steps

Each step names what to do and what to expect, by symptom.

1. **`403 step_up_required` on an admin action.**
   **Do:** read the problem body: `action_class`, `action_summary` (what would run, verbatim), `challenge_id` and
   `challenge_expires_at`. In the app, SCR-006 opens over the page; enter the password and a current code.
   **Expect:** `200` from `POST /auth/step-up`, the held request sent again once and unchanged, and `auth.step_up_granted`
   in the log. A grace class answers `step_up_expires_at` five minutes ahead; a no-grace class answers `single_use: true`
   and its grant lasts 60 seconds, for that request only.
2. **A code is asked again within minutes.**
   **Do:** compare the action's class with Quick facts. **Expect** one of: a no-grace class (it asks every time); a
   different grace class (a `users` grace does not cover `flags`); a lapsed grace (5 minutes); an idle lock, which
   cleared every grant (step 7); or a token refresh, which starts a new session row without grants
   (`auth/session_service.py:411-413`), so a refresh inside the five minutes ends the grace early. None is a fault.
3. **`400 validation_failed` with rule `challenge_required` or `challenge_expired`.**
   **Do:** nothing was sent: no factor was checked, no failure counted and nothing elevated. Repeat the action.
   **Expect:** a new `403 step_up_required` and a new `challenge_id`. The dialog drops the held request unsent and says
   it was not sent. A challenge ends when it is used, at its expiry, when a newer `403` replaces it, on read-only and on
   idle lock.
4. **`401 mfa_invalid`.**
   **Do:** retry with a fresh code. The answer never says whether the password or the code was wrong. A wrong password
   also counts toward the account's sign-in lock (`auth-rbac.md` §1). If a correct code keeps failing, suspect clock skew
   (`auth-rbac.md` §9); a code already accepted in its 30-second step is refused until the next one (SR-021).
   **Expect:** `failures_remaining` of 2, then 1. The third wrong code is step 5.
5. **`403 session_read_only`.**
   **Do:** wait. The session is read-only for 5 minutes (`readonly_until` in the body; Known gaps). Reads work; sign-out,
   `POST /auth/session/extend`, `POST /auth/lock` and ending a view-as work; every other write is refused, and
   `POST /auth/step-up` answers it too. The downgrade survives a lock, an unlock and a token refresh.
   **Expect:** `auth.session_readonly_downgrade` (high severity) and, after the window, writes and step-ups again.
6. **`503 audit_unavailable` on a step-up or an admin action.**
   **Do:** retry later. The audit writer could not take the write-ahead record within 2 seconds, so no challenge was
   issued, no failure counted and nothing elevated or revoked; a grant bound to a held request was neither used nor
   ended (C-2.9). Follow [`AuditSinkRefusing`](../../plan/07-release-and-prr.md#alert-auditsinkrefusing) for the cause.
   **Expect:** the same request succeeds once the writer recovers.
7. **`401 session_idle_locked`.**
   **Do:** unlock with the password (`POST /auth/unlock`; SCR-005). Signing out instead also works (`auth-rbac.md` §1).
   **Expect:** reads work again, and every dangerous action asks for a code again: a one-factor unlock never inherits a
   grace.
8. **`403 view_as_read_only` during a view-as (SCR-124).**
   **Do:** end the view (`DELETE $API/auth/session/view-as`), then repeat the action. Starting a view needs the `users`
   step-up and ending it needs none; a view elevates nothing, and `Me` shows `elevated_until: null` while it lasts.
   **Expect:** `204` and one `admin.view_as_ended`; the action then answers as it would outside the view, its step-up
   included.
9. **The re-send had no answer after a successful step-up** (a network error or a timeout). The action may have run.
   **Do:** read the state back (the affected screen, or `GET $API/admin/audit?action=<code>`) before repeating it.
   **Expect:** a record naming the action if it ran. The dialog never calls it "not sent" and never re-sends by itself.

## Verification

A later action of the same grace class inside five minutes runs without a prompt and writes `auth.step_up_grace_used`;
a no-grace action asks again and writes `auth.step_up_required`; after step 5's window a write is accepted again. For a
refused or unexplained prompt, the `auth.step_up_*` records name the class and the `challenge_id` of each attempt.

## Rollback, and what cannot be undone

A step-up changes nothing to roll back: it opens a grace or a one-time grant, and an unused one lapses by itself. A held
request that was re-sent is an action like any other: undo it by the action's own procedure, never by repeating the step-up.
A read-only downgrade ends at `readonly_until`.

## Escalation

Repeated `auth.step_up_failed` or `auth.step_up_mismatch` from a session the Owner does not recognise, or an
`admin.area_entered` trail from one, is a possible stolen session: follow IR-01 in
[`04-security-program.md`](../../plan/04-security-program.md) §10.3 and RSK-074's contingency in
[`32-risk-register.md`](../../plan/32-risk-register.md), and read the authorisation alerts in
[`07-release-and-prr.md`](../../plan/07-release-and-prr.md) §9 (`AuthzDeniedSpike`, `AuthLockouts`). An Owner who is
locked out follows `auth-rbac.md` §1 to §3.

## Known gaps

| Gap                                                                                                           | Reference                                             |
| ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| After a reload the shell cannot say which class a grace belongs to: `Me.session.elevated_until` is the latest | E42-D03 CG-2 (E09 session contract)                   |
| `risk_caps` is a grace class today; the ruling moves it to no-grace before the first live key                 | ADR-0042's gap row (owner E39); #2701 ledger 2 row 48 |
| `readonly_until` is returned on `session_read_only` but is not declared in `Problem`                          | E42-D03 CG-3                                          |
| The contract says a step-up rotates the session and returns `tokens`; the code's `200` does neither           | #2101                                                 |
| No alert reads the step-up, session or sign-in failure series                                                 | #2746                                                 |

## Execution record

Not executed: no staging host exists (#1778 item A, as `auth-rbac.md` records), and the rehearsal is E48-Q02's. Every
statement above was read against the code at `d023df0f6`.

Links: [`auth-rbac.md`](auth-rbac.md) §1, §2, §7, §9; [ADR-0042](../../plan/27-adrs/ADR-0042-admin-reauth-and-elevation-model.md).
