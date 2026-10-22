# E42 Admin area: black-box test plan, fixtures and exploratory charters

Ticket: E42-Q01 (#962). Status: part 1 of 2, a draft for review by the story owners and the Security
engineer. This part holds the conventions, the S01 to S03 cases, the cross-session scenarios, the
exploratory charters and the S01 to S03 traceability. Part 2 adds S04 to S07, E42-T07 and E42-S08,
the entry and exit criteria, the regression pack, the screen-reader script and the per-screen budgets.
The fixture set lands with its own PRs and is described in section 1.

## 0. Conventions

- **Expectations come from the specification, not the implementation.** Each case cites its source:
  - `E42-Snn` is the story's Gherkin in `docs/plan/backlog/E42.json`;
  - `US-ADMIN-nnn` is `docs/plan/11-user-stories.md` §26;
  - `SCR-nnn` is `docs/plan/14-screens-catalogue.md` §10;
  - `22` is `docs/plan/22-api-openapi.yaml`, and `23` is `docs/plan/23-ws-protocol.md`;
  - `D02` is the signed-off wireframe spec, `docs/design/E42/E42-D02.md` (its decisions `D1` to `D18`, the
    destructive-action ladder's rungs, and its amendments `A-n`).
- **Where D02 resolved a pattern differently** from a story's Gherkin or the catalogue, the case follows D02
  and the server, and the difference is a question in section 9.
- **Environment:** staging or demo, on the seeded fixtures only. Never live (`02-definition-of-ready-done.md`
  §8). No fixture or step holds a real credential, a real Bybit key or real user data.
- **Case ids:**
  - `AD-Snn-nn` is a story scenario;
  - `AD-Snn-Nnn` is a negative or boundary case the story implies;
  - `AD-X-nn` is a cross-session scenario;
  - `CH-AD-n` is a charter;
  - **[R]** marks a member of the regression pack (part 2 defines the pack).
- **Layer:** each case names the layer that should own it, by `03-testing-strategy.md`'s pyramid: `unit`,
  `contract`, `integration`, `e2e`, `perf`, `security` or `a11y`. E42-Q02 automates from this label.
- **Audit:** each case names the audit action it expects, as registered in
  `services/api/candleviewer/audit/actions.py`. After the step, the tester confirms exactly one record per
  action with its actor, target, outcome and request id. An audited action with no record is a defect.
  Where a story names an action the registry does not hold, the case names the registered one and the
  difference is a question in section 9.
- **Timing:** each timing assertion cites its source and is measured between the server's audit
  timestamps where possible, not by the test runner's clock.
- **Security abuse cases** are E42-X03's (`tests/security/admin`, `docs/security/abuse-cases/e42-admin.md`).
  This plan points at them by id (`AC-ADM-nn`) rather than repeating them.

## 1. Seeded actors and data

The handles below are fixed here. The fixture slices define each one as an idempotent seed script under
`services/api/tests/fixtures/admin/`, with a README line saying how to load it.

| Handle                          | What it is                                                               |
| ------------------------------- | ------------------------------------------------------------------------ |
| OWNER                           | The Owner, TOTP enrolled                                                 |
| OWNER-2                         | A second Owner, for concurrent edits                                     |
| MGR-M                           | A Manager with an active session, one armed rule and a grant on SUB-S    |
| MGR-N                           | A Manager with no grants                                                 |
| MGR-MANY                        | A Manager with grants on SUB-S, SUB-T and SUB-U                          |
| VIEWER-V                        | A Viewer                                                                 |
| INVITED-I, DISABLED-D, LOCKED-L | A user in each non-active status                                         |
| SUB-S, SUB-T, SUB-U             | Demo sub-accounts                                                        |
| SUB-K                           | An account under the 48-hour key restriction                             |
| TIER-FULL                       | The account tier `regular` with 5 of 5 sub-accounts in use               |
| HEALTH-RECORDER-DOWN            | Health payloads: the recorder unreachable, every other subsystem healthy |
| OVERVIEW-503                    | `GET /api/v1/admin/overview` answering `503`                             |

## 2. Cases by story group

### S01: the admin shell, the re-auth gate and SCR-120 (US-ADMIN-001, 002, 004, 010, 011)

**AD-S01-01 Entry without a fresh step-up meets the gate [R]** (`e2e`, `contract`; E42-S01 "Owner enters the
admin area with a stale token"; SCR-149; D02 D2 and A-14)

- Pre: OWNER, whose last step-up is older than the web router's freshness window (the test clock moves it).
- Steps: open `/admin`; enter the correct password and TOTP.
- Expected: the gate, as `role="alertdialog"` with a focus trap, says why it is shown and how long the
  result lasts. After the correct answer the admin area renders. `Esc` cancels to the previous non-admin
  route.
- Server: the entry itself is a read, which the server records but never refuses. Every dangerous action
  is still challenged server-side (AD-S01-N01).
- Audit: `auth.step_up_granted` for OWNER, then `admin.area_entered` (allowed, with its `reauth_age_s`). See
  Q-1.

**AD-S01-02 A non-owner cannot reach the admin area [R]** (`e2e`, `contract`; E42-S01 "Non-owner cannot
reach the admin area"; SCR §10 preamble)

- Pre: MGR-M.
- Steps: look at the left rail; open `/admin/users` directly; send each admin API call with MGR-M's bearer.
- Expected: no "Admin" rail item. The router renders the 404 surface (SCR-155) with no network call. Each
  API call answers `403 forbidden`.
- Audit: one `admin.area_entered` (denied) per API call. E42-X03's RBAC cells hold the full matrix.

**AD-S01-03 Overview tiles resolve independently [R]** (`e2e`, `perf`; E42-S01 "Overview tiles resolve
independently"; SCR-120)

- Pre: OWNER, elevated; HEALTH-RECORDER-DOWN.
- Steps: open `/admin`.
- Expected: the recorder tile shows its own error state with a retry action. Every other tile renders its
  value within 800 ms (SCR-120).
- Audit: `admin.area_entered` (allowed).

**AD-S01-04 Re-auth expires mid-edit** (`e2e`; E42-S01 "Re-auth expires mid-edit"; D02 D2)

- Pre: OWNER on SCR-122, with 10 seconds left on the `users` class's grace.
- Steps: change two fields; move the test clock past the grace; press Save; re-authenticate.
- Expected: the server answers the save with a step-up challenge. The gate overlays the page, with the form
  content still under the scrim. After re-authentication the held save is sent once, unchanged (method,
  path, body and `Idempotency-Key`), and the page says "Saved".
- Audit: `auth.step_up_required`, then `auth.step_up_granted`, then the save's own record, once.

**AD-S01-05 The backend is degraded** (`e2e`; E42-S01 "Backend degraded")

- Pre: OWNER, elevated; OVERVIEW-503.
- Steps: open `/admin`; then move through the shell's navigation.
- Expected: the error state, with the last-known values marked stale and a retry control. The shell and its
  navigation stay usable.

**Negative and boundary cases**

- **AD-S01-N01 The grace's boundary** (`contract`; D02 A-14; SR-025):
  - a second `users`-class action 4 min 59 s after a step-up passes with no challenge
    (`auth.step_up_grace_used`); at 5 min it is challenged (`auth.step_up_required`);
  - an action of another class is challenged whatever the `users` grace;
  - a `backups`, `killswitch` or `live_enablement` action always needs a fresh code;
  - the grace is the server's, so a client clock set back changes nothing.
- **AD-S01-N02 Cancel leaves the draft** (`e2e`; D02 D2): cancelling the entry gate returns to the previous
  non-admin route, not a dead end. Cancelling a held save's gate says "Not saved", keeps the page and its
  draft, and sends nothing.
- **AD-S01-N03 A held save is never re-sent on its own** (`e2e`; D02 D2): if the re-sent save meets a
  network error, the page says the outcome is pending and re-reads; it does not send the save again.
- **AD-S01-N04 A failed re-auth** (`e2e`, `a11y`; SCR-149 "failure and lockout states"): a wrong TOTP is
  announced assertively and audited `auth.step_up_failed`. Repeated failures reach the lockout state.
- **AD-S01-N05 Step-up time** (`perf`; SCR-149): the step-up answers in ≤400 ms.

### S02: the users list, invites and the lifecycle (US-ADMIN-001, 014; SCR-121, SCR-123)

**AD-S02-01 Invite, then grant the role [R]** (`e2e`, `contract`; E42-S02 "Create and assign role"; D02 D9)

- Pre: OWNER, elevated, on `/admin/users`.
- Steps: invite a user; copy the link; reload the page; once the invite is redeemed, make the user a
  manager on SCR-122.
- Expected:
  - the invite dialog has no role picker and says that the manager grant is a second step;
  - the row shows "Invited" until the invite is redeemed;
  - the one-time link is shown once, as a secret, with a copy control and a statement that it will not be
    shown again; after the reload no link is shown;
  - the pending list offers revoke and re-issue.
- Audit: `users.invited`, naming the actor and the target; on the second step, `roles.grant`. See Q-2.

**AD-S02-02 Disabling revokes access within 5 s [R]** (`e2e`, `integration`; E42-S02 "Disable revokes
access quickly"; US-ADMIN-001)

- Pre: MGR-M with an active session and one armed rule.
- Steps: disable MGR-M through its rung-2 dialog and confirm.
- Expected:
  - the dialog lists the consequences, with the counts loaded before Confirm enables, and Cancel takes the
    first focus (D02 D3, D18);
  - every session of MGR-M is revoked within 5 s, measured from the `users.disable` record to the last
    `auth.session_revoked` record for MGR-M's sessions;
  - MGR-M's rules show as disarmed (`rules.disarm`);
  - MGR-M's data is kept, and the row shows "Disabled" with a Re-enable action.
- Audit: `users.disable`, then `auth.session_revoked` per session, then `rules.disarm`. AD-X-01 is the
  two-context version.

**AD-S02-03 Delete keeps the history [R]** (`e2e`, `integration`; E42-S02 "Delete with history")

- Steps: delete MGR-M through its rung-3 dialog, typing MGR-M's username to confirm.
- Expected: the confirm control stays disabled until the counts load and the typed name matches, and Enter
  in the name field never confirms (D02 D3, D18). MGR-M's audit and journal history remain, attributed to an anonymised reference. MGR-M leaves
  the default list and appears under the "Disabled/Deleted" filter.
- Audit: `users.delete`, then `users.anonymise`.

**AD-S02-04 The last owner is protected [R]** (`e2e`, `contract`; E42-S02 "Last owner protection")

- Pre: OWNER is the only Owner.
- Steps: look at OWNER's own row; then send `DELETE /users/{OWNER}` and a `PATCH` to `disabled` directly.
- Expected: Disable and Delete are disabled on the row, with a tooltip saying the last owner is protected.
  Each direct request is refused and nothing changes.
- Audit: `rbac.denied` per request. See Q-3 for the status the server answers.

**AD-S02-05 Capacity reached** (`e2e`; E42-S02 "Capacity reached")

- Pre: TIER-FULL.
- Expected: the capacity line reads "5 of 5 used" and names the assumed tier. The Business KYC path and the
  isolation trade-off of sharing a sub-account are explained.

**AD-S02-06 Step-up expires during a delete [R]** (`e2e`, `contract`; E42-S02 "Step-up expired during a
destructive action")

- Pre: the delete confirmation for MGR-M is open; the token then expires.
- Steps: confirm; re-authenticate.
- Expected: the gate appears. After success the delete goes ahead exactly once, with the same idempotency
  key; replaying the request with that key writes nothing.
- Audit: `auth.step_up_required`, `auth.step_up_granted`, then one `users.delete`.

**Negative and boundary cases**

- **AD-S02-N01 The invite link is never served again** (`contract`): no read of the invite answers its link.
- **AD-S02-N02 An unknown role is refused** (`contract`): `422`, and no invite is written.
- **AD-S02-N03 Two owners disable one manager at once** (`integration`): one `users.disable` record; the
  other request is refused (`409` or `412`) and changes nothing.
- **AD-S02-N04 A disabled user cannot sign in, and re-enabling restores it** (`e2e`): `auth.login_failed`
  while disabled; `users.enable` on re-enable.

### S03: user detail, bindings, limits and view-as (US-ADMIN-001, 002, 003, 008; SCR-122, SCR-124)

**AD-S03-01 Bind a manager to a sub-account [R]** (`e2e`, `contract`; E42-S03 "Bind a manager to a
sub-account")

- Pre: MGR-N, with no grants.
- Steps: grant MGR-N trade access to SUB-S; save with step-up.
- Expected: MGR-N sees and trades only SUB-S, under SUB-S's profile.
- Audit: `users.access_change`, with the full grant sets before and after.

**AD-S03-02 Two bindings** (`e2e`; E42-S03 "Multiple bindings")

- Steps: add a grant on SUB-T for MGR-N.
- Expected: both accounts appear in MGR-N's scope selector on the next request, and MGR-N's own `GET /me`
  lists both.
- Audit: `users.access_change`.

**AD-S03-03 Unbind with open positions** (`e2e`, `integration`; E42-S03 "Unbind with open positions")

- Pre: MGR-M holds an open position on SUB-S.
- Steps: remove MGR-M's grant on SUB-S.
- Expected: the save is blocked until the owner chooses: leave the positions (the owner takes them over) or
  flatten first.
- Audit: `users.access_change`, recording the chosen option.

**AD-S03-04 Tighten a limit during an open position** (`e2e`, `integration`; E42-S03 "Tighten a limit
during an open position")

- Pre: MGR-M's exposure exceeds the new maximum position size.
- Steps: save the tightened limit.
- Expected: no position is closed. New entries for MGR-M are blocked, and reduce-only actions stay
  available. Both the owner and MGR-M are told.
- Audit: the limit change, with the old and new values. See Q-4.

**AD-S03-05 View-as is unmistakably read-only [R]** (`e2e`, `security`; E42-S03 "View-as is unmistakably
read-only"; 22 "View-as session")

- Steps: start "view as" for MGR-M, giving the entry dialog's mandatory reason; try each state-changing
  control; exit.
- Expected:
  - the banner is the document's first element and names MGR-M and the read-only state; its Exit is the
    first tab stop, in every window, and `Esc` never exits (D02 D10, D18);
  - the countdown runs to the server's `expires_at`;
  - every state-changing control is disabled, with a reason;
  - a write sent anyway is refused `403 view_as_read_only` (AC-ADM-22).
- Audit: `admin.view_as_started` (severity high); `admin.view_as_refused` per refused write;
  `admin.view_as_ended` on exit.

**AD-S03-06 A concurrent edit is surfaced** (`e2e`, `contract`; E42-S03 "Concurrent edit")

- Pre: OWNER loads MGR-M's detail; OWNER-2 then changes MGR-M's roles.
- Steps: OWNER saves.
- Expected: `412`, shown as "This user changed while you were editing" with a reload action. OWNER's change
  is not applied.
- Audit: OWNER-2's `roles.grant` or `roles.revoke` only.

**Negative and boundary cases**

- **AD-S03-N01 View-as refusals, in the contract's order** (`contract`; 22 `startViewAs`):
  - a second start while viewing: `409 view_as_active`;
  - viewing oneself: `403 view_as_self_target`;
  - an unknown user: `404`;
  - INVITED-I or DISABLED-D: `409 conflict`;
  - an Owner: `403 view_as_owner_target`.

  Each is recorded `admin.view_as_refused`. LOCKED-L can be viewed.

- **AD-S03-N02 A view ends at its expiry** (`e2e`): at `expires_at` the banner clears and the next request
  answers as the owner. Audit: `admin.view_as_ended`.
- **AD-S03-N03 A view reads only what the user reads** (`security`): an owner viewing as MGR-M gets MGR-M's
  answers, statuses and refusals, and every record names the owner (E42-X03's view-as cells).

## 3. Cross-session scenarios

Each needs two browser contexts: A is the owner, and B is the other user. The timing is the story's or the
catalogue's, and it is measured between server timestamps.

**AD-X-01 The owner disables a manager who is trading [R]** (`e2e`; US-ADMIN-001; E42-S02)

- B: MGR-M, with the order ticket open, a live WebSocket and one armed rule.
- A: OWNER disables MGR-M and confirms.
- Expected:
  - every session of MGR-M is revoked within **≤5 s** of the `users.disable` record, measured to the last
    `auth.session_revoked` record;
  - B's socket closes and B lands on sign-in; B's next order is refused `401`;
  - B's armed rule is disarmed.
- Audit: `users.disable`, `auth.session_revoked` per session, `rules.disarm`.

**AD-X-02 The owner revokes a grant while the manager is subscribed [R]** (`e2e`; 23 §16.4 "Grant
revocation mid-stream")

- B: MGR-MANY, subscribed to SUB-S's and SUB-T's private topics.
- A: OWNER removes MGR-MANY's grant on SUB-S.
- Expected: B receives `revoked` for SUB-S's subscriptions within **≤1 s**, and the SUB-T topics carry on.
  B's next read of SUB-S answers as for an account it was never granted.
- Audit: `users.access_change` (before and after grant sets), then `ws.subscription.revoked`.

**AD-X-03 The owner enables maintenance while a manager has the order ticket open [R]** (`e2e`; SCR-148;
22 "Maintenance mode")

- B: MGR-M, with the order ticket open.
- A: OWNER turns `maintenance.mode` on.
- Expected:
  - order acceptance is blocked server-side within **≤200 ms** of the `maintenance.enabled` record; an order
    from B after that answers `403 trading_disabled` with `reason: maintenance`;
  - the maintenance notice reaches every session, B's included, within **≤2 s** (SCR-148).
- Audit: `flags.change`, then `maintenance.enabled`.

## 4. Exploratory charters

Each charter is timeboxed. A charter ends with notes, the defects filed and the coverage it reached.

| Charter                                                                                                                                                                            | Timebox | What would make this a finding                                                                                                                       |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **CH-AD-1** Try to see data outside your scope as a manager: deep links with foreign ids, the scope selector, `/me`, WebSocket subscriptions, the own-redacted audit view, exports | 60 min  | Any byte of another user's or an ungranted account's data; or a foreign id answered differently from a missing one                                   |
| **CH-AD-2** Try to make the audit log look editable: SCR-135 and SCR-136 controls, every HTTP verb on `/admin/audit*`, the export, a detail view edited in the browser             | 45 min  | Any control or verb that changes a record; any affordance that suggests editing; a verify that reports an intact chain after a stored record changed |
| **CH-AD-3** Try to reach an admin screen without elevation: deep links, the back button after a cancelled gate, a second tab, a token expiring mid-load, a view-as session         | 45 min  | Admin data rendered, or an admin API answering 2xx, without a token at most 15 min old; an admin call with no audit record                           |
| **CH-AD-4** Try to lose form content by letting the token expire, on every admin form                                                                                              | 45 min  | A form whose content is lost, that saves twice, or that saves without passing the gate                                                               |
| **CH-AD-5** Try to make two tiles block each other: SCR-120 with subsystems slowed, failing and flapping                                                                           | 30 min  | One tile's failure or slowness delays another past 800 ms; a retry that blocks the page                                                              |

## 5. Traceability: S01 to S03

| Story   | Gherkin scenario                                      | Cases                                         |
| ------- | ----------------------------------------------------- | --------------------------------------------- |
| E42-S01 | Owner enters the admin area with a stale token        | AD-S01-01, AD-S01-N01, AD-S01-N02             |
| E42-S01 | Non-owner cannot reach the admin area                 | AD-S01-02                                     |
| E42-S01 | Overview tiles resolve independently                  | AD-S01-03, CH-AD-5                            |
| E42-S01 | (failure) Re-auth expires mid-edit                    | AD-S01-04, AD-S01-N02, AD-S01-N03, CH-AD-4    |
| E42-S01 | (edge) Backend degraded                               | AD-S01-05                                     |
| E42-S02 | Create and assign role                                | AD-S02-01, AD-S02-N01, AD-S02-N02             |
| E42-S02 | Disable revokes access quickly                        | AD-S02-02, AD-X-01                            |
| E42-S02 | Delete with history                                   | AD-S02-03                                     |
| E42-S02 | (failure) Last owner protection                       | AD-S02-04                                     |
| E42-S02 | (edge) Capacity reached                               | AD-S02-05                                     |
| E42-S02 | (failure) Step-up expired during a destructive action | AD-S02-06                                     |
| E42-S03 | Bind a manager to a sub-account                       | AD-S03-01                                     |
| E42-S03 | Multiple bindings                                     | AD-S03-02                                     |
| E42-S03 | Unbind with open positions                            | AD-S03-03                                     |
| E42-S03 | Tighten a limit during an open position               | AD-S03-04                                     |
| E42-S03 | View-as is unmistakably read-only                     | AD-S03-05, AD-S03-N01, AD-S03-N02, AD-S03-N03 |
| E42-S03 | (failure) Concurrent edit                             | AD-S03-06, AD-S02-N03                         |

The scope's implied cases map as follows. "Expired token mid-action" is AD-S01-04 and AD-S02-06.
"Concurrent owner edits" is AD-S03-06 and AD-S02-N03. "A manager session open while their grant is
revoked" is AD-X-02. "An export over the range limit" and "a flag changed twice in one second" are S04's and
S05's, in part 2.

## 9. Questions

Each is a question for the implementing story, not a guess.

- **Q-1:** E42-S01 and SCR-149 describe a 15-minute admin token. The server has per-action step-up instead,
  with a 5-minute grace per action class, and records an entry without refusing it. The web router gates
  `/admin/**` on its own freshness window (D02 A-14 and addendum A2). Whether an admin window gets a server
  half is D8's open question (OQ-14). AD-S01-01 asserts the gate on a stale step-up without fixing the
  threshold, and AD-S01-N01 tests the server's grace. E42-S01 also expects `admin.session_elevated`, which
  `audit/actions.py` does not register: the step-up writes `auth.step_up_granted`, and the admin-area guard
  writes `admin.area_entered`.
- **Q-2:** E42-S02 invites "with role manager" and expects `users.create` with the assigned roles. D02 D9
  invites with no role picker, the manager grant being a second step. The registry has both `users.create`
  and `users.invited`. AD-S02-01 follows D9 and expects `users.invited`, then `roles.grant`.
- **Q-3:** E42-S02 expects `409 conflict` for the only owner's own Disable or Delete. The server refuses a
  self-target first, `403 self_target` (SR-055); the `409` is the last _active_ owner's refusal from another
  owner (D6). AD-S02-04 asserts a refusal with nothing changed, and both statuses need a case once this is
  settled.
- **Q-4:** E42-S03 does not name the limit change's action. The registry has `profile.updated`,
  `profiles.update` and `users.update`.
