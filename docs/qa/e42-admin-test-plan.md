# E42 Admin area: black-box test plan, fixtures and exploratory charters

Ticket: E42-Q01 (#962). Status: a draft for review by the story owners and the Security engineer. It
holds the conventions, the cases for E42-S01 to S08 and E42-T07, the cross-session scenarios, the
exploratory charters, the traceability, the entry and exit criteria, the regression pack, the
screen-reader script and the per-screen budgets. The fixture set lands with its own PRs and is described
in section 1.

## 0. Conventions

- **Expectations come from the specification, not the implementation.** Each case cites its source:
  - `E42-Snn` is the story's Gherkin in `docs/plan/backlog/E42.json`;
  - `US-ADMIN-nnn` is `docs/plan/11-user-stories.md` §26;
  - `SCR-nnn` is `docs/plan/14-screens-catalogue.md` §10;
  - `22` is `docs/plan/22-api-openapi.yaml`, and `23` is `docs/plan/23-ws-protocol.md`;
  - `D02` is the signed-off wireframe spec, `docs/design/E42/E42-D02.md` (its decisions `D1` to `D18`, the
    destructive-action ladder's rungs, and its amendments `A-n`).
- **Where sources differ**, the case follows D02 and the server, and the difference is a question in
  section 9; where only the contract and the server differ, it asserts what both hold.
- **Environment and credentials:** demo or staging, on the seeded fixtures only, or testnet where a case
  moves the server's clock (Time). Never live (`02-definition-of-ready-done.md` §8). No fixture or step holds
  a real credential, Bybit key or user data: every password, TOTP seed, invite link and bearer a run uses is
  synthetic, generated per run and never committed, and defects, notes, screenshots, Playwright traces and
  videos, and HARs are scrubbed of them before they are filed.
- **Each case starts from a fresh seed** of section 1's handles, so no case depends on another's end state.
- **"Elevated"** means the actor holds a live step-up grace for the case's action class.
- **Time:** a case that moves the server's clock (`CV_TEST_CLOCK`: testnet only, no exchange key) runs on
  testnet and seeds users only, since the seeded sub-accounts need demo, which refuses that clock; on demo or
  staging it waits in real time. The router's 30-minute freshness window reads the browser's clock instead.
- **Case ids:**
  - `AD-Snn-nn` is a story scenario;
  - `AD-Snn-Nnn` is a negative or boundary case the story implies;
  - `AD-X-nn` is a cross-session scenario;
  - `CH-AD-n` is a charter;
  - **[R]** marks a member of the regression pack (section 7 defines the pack).
- **Layer:** each case names the layer that should own it, by `03-testing-strategy.md`'s pyramid: `unit`,
  `contract`, `integration`, `e2e`, `perf`, `security` or `a11y`. E42-Q02 automates from this label.
- **Audit:** each case names the audit actions it expects, as registered in
  `services/api/candleviewer/audit/actions.py`, or says it expects none. After the step, the tester confirms
  one record per audited action, with its actor, target, outcome, request id and, where `22` names one,
  severity. An audited action with no record is a defect. A disable also writes its cascade's records, one
  `auth.session_revoked` per session and one `rules.disarm` per armed rule. The exceptions: `admin.area_entered`
  is written once per admin API call, so a page that makes several calls writes several; a call let
  through by a live grace also writes `auth.step_up_grace_used`; a write-ahead record whose change did not
  commit is closed by a second, `failure` record; and past a budget (view-as refusals, audit reads) records
  are counted into `suppressed`, not written one by one. Where a story names an action the registry does
  not hold, the case names the registered one and the difference is a question in section 9.
- **Timing:** each timing assertion cites its source and is measured between the server's audit timestamps
  where possible, not by the test runner's clock. A record written ahead of its commit (such as
  `users.disable`) starts an interval before it, which the server's 5 s revocation deadline does not count;
  the report names the record it started from.
- **Security abuse cases** are E42-X03's (`services/api/tests/security/admin/`,
  `docs/security/abuse-cases/e42-admin.md`). This plan points at them by id (`AC-ADM-nn`, and `UL-ACnn` from
  the user-lifecycle annex, `docs/security/threat-models/e42-user-lifecycle.md` §4) rather than
  repeating them: a case whose oracle X03 holds cites the id and adds only the black-box steps.

## 1. Seeded actors and data

The handles below are fixed here. The fixture slices define each one as an idempotent seed script under
`services/api/tests/fixtures/admin/`, with a README line saying how to load it.

| Handle                                | What it is                                                                                   |
| ------------------------------------- | -------------------------------------------------------------------------------------------- |
| OWNER                                 | The Owner, TOTP enrolled                                                                     |
| OWNER-2                               | A second Owner, for concurrent edits                                                         |
| MGR-M                                 | A Manager with an active session, one armed rule and a grant on SUB-S                        |
| MGR-N                                 | A Manager with no grants                                                                     |
| MGR-MANY                              | A Manager with grants on SUB-S, SUB-T and SUB-U                                              |
| MGR-U                                 | A Manager with an active session and no grants: MGR-M for the stack that moves the clock     |
| VIEWER-V                              | A Viewer                                                                                     |
| INVITED-I, DISABLED-D, LOCKED-L       | A user in each non-active status                                                             |
| SUB-S, SUB-T, SUB-U                   | Demo sub-accounts                                                                            |
| SUB-K                                 | An account under the 48-hour key restriction                                                 |
| TIER-FULL                             | The account tier `regular`, recorded, with 5 of 5 sub-accounts in use                        |
| HEALTH-RECORDER-DOWN                  | The overview's `recorder` slice unreachable, every other slice healthy                       |
| HEALTH-RECORDER-HANG                  | The overview's `recorder` slice never answering, every other slice healthy                   |
| POS-M-S                               | An open position of MGR-M's on SUB-S, its exposure above the tightened cap AD-S03-04 saves   |
| PROFILE-S                             | The profile bound to SUB-S                                                                   |
| OVERVIEW-503                          | `GET /api/v1/admin/overview` answering `503`                                                 |
| AUDIT-10M                             | 10 million generated audit entries, from the generator E42-K01 shares                        |
| AUDIT-CORRUPT                         | A chain with one altered entry at a known `first_bad_id`; it loads only into a test database |
| AUDIT-KEY-ENTRY                       | An entry whose before and after states referenced key material, by fingerprint               |
| FLAG-UI                               | A catalogued UI flag, `rules.graph_editor`, on (see Q-9)                                     |
| FLAG-LIVE-BLOCKED                     | `trading.live_enabled` off, with the pen-test sign-off outstanding                           |
| RULES-ON-FLAG                         | Two armed rules that depend on a flag being disabled                                         |
| HEALTH-SUB002-WS-DOWN, HEALTH-TIMEOUT | Health payloads: `sub_002`'s private WebSocket down; the health read timing out              |
| BACKUP-VERIFY-FAILED, BACKUPS-NONE    | The latest backup failing verification; no backup at all                                     |
| GROUP-G                               | An enabled trade group with an open group trade                                              |
| SC-CHAIN-TRIPS                        | A machine restored with `chain_trips` above 0                                                |

## 2. Cases by story group

### S01: the admin shell, the re-auth gate and SCR-120 (US-ADMIN-001, 002, 004, 010, 011)

**AD-S01-01 Entry without a fresh step-up meets the gate [R]** (`e2e`, `contract`; E42-S01 "Owner enters the
admin area with a stale token"; SCR-149; D02 D2 and A-14)

- Pre: OWNER, whose last step-up is older than the router's freshness window (the browser's clock moves it).
- Steps: open `/admin`; enter the correct password and TOTP.
- Expected: the gate, as `role="alertdialog"` with a focus trap, says why it is shown and how long the
  result lasts. After the correct answer the admin area renders. `Esc` cancels to the previous non-admin
  route.
- Server: the entry itself is a read, which the server records but never refuses (AC-ADM-30). Every
  dangerous action is still challenged server-side (AD-S01-N01).
- Audit: `auth.step_up_granted` for OWNER, then `admin.area_entered` (allowed, with its `reauth_age_s`). See
  Q-1.

**AD-S01-02 A non-owner cannot reach the admin area [R]** (`e2e`, `contract`; E42-S01 "Non-owner cannot
reach the admin area"; SCR §10 preamble; AC-ADM-01)

- Pre: MGR-M; then the same steps for VIEWER-V (a new user is a Viewer, SR-027).
- Steps: look at the left rail; open `/admin/users` directly; send each admin **read** with the user's
  bearer, `GET /admin/audit` included, and recorder compact and import.
- Expected: no "Admin" rail item. The router renders the 404 surface (SCR-155), with the same copy as any
  unknown route and no network call (D02 D6). Each Owner-only read answers `403 forbidden` (a gated write
  meets `403 step_up_required` first). Three operations are not Owner-only (`rbac/matrix.yaml`,
  AC-ADM-01): MGR-M's `GET /admin/audit` answers `200` with MGR-M's own records only, redacted, and recorder
  compact and import are not refused by role (the handler may still answer `4xx` for the body). VIEWER-V is
  refused all three, `403 forbidden`, though the recorder routes' refusals carry no `code` yet (SR-E42-09).
  A fourth, the backup download link (`GET /admin/backups/{backupId}/download/{token}`), is public: its
  token is the credential, so it is not refused by role for anyone.
- Audit: `admin.area_entered` (denied) per Owner-only read on the admin-area guard; `rbac.denied` per
  refusal on the `/users*` routes (AC-ADM-01); on `/admin/audit*`, `admin.audit_denied` for a refusal and
  `admin.audit_read` for MGR-M's read (AC-ADM-17: a read naming another actor first writes an
  `admin.audit_denied`); on the recorder routes, `recorder.compact` or `recorder.import`, outcome `denied`
  for VIEWER-V and, for MGR-M, a record once the handler accepts the request (a `4xx` for the key or body
  writes none). One refusal writes no record and carries no `code`: `GET /admin/support-bundle/{job_id}`
  for a Manager or Viewer, a known gap (X03-F1, #2836) and not a new defect. E42-X03's RBAC cells hold the
  full matrix.

**AD-S01-03 Overview tiles resolve independently [R]** (`e2e`, `perf`; E42-S01 "Overview tiles resolve
independently"; SCR-120)

- Pre: OWNER, elevated; HEALTH-RECORDER-DOWN, then HEALTH-RECORDER-HANG.
- Steps: open `/admin`, once per handle.
- Expected: the recorder tile shows its own error state with a retry action. Every other tile renders its
  value within 800 ms (SCR-120), measured by the overview's render metric (`cv_admin_overview_render_ms`,
  E42-Q03). With HEALTH-RECORDER-HANG the same holds, and the recorder tile reaches its error state at 3 s,
  its own timeout (E42-S01 performance notes), with no other tile waiting for it.
- Audit: `admin.area_entered` (allowed), once per call.

**AD-S01-04 Re-auth expires mid-edit** (`e2e`; E42-S01 "Re-auth expires mid-edit"; D02 D2)

- Pre: OWNER on SCR-122, with 10 seconds left on the `users` class's grace.
- Steps: change two fields; move the server's clock past the grace (§0); press Save; re-authenticate.
- Expected: the server answers the save `403 step_up_required`. The gate overlays the page, with the form
  content still under the scrim. After re-authentication the held save is sent once, unchanged (method,
  path, body and `Idempotency-Key`), and the page says "Saved".
- Audit: `auth.step_up_required`, then `auth.step_up_granted`, then `auth.step_up_grace_used` and the save's
  own record once (for a role change, `roles.grant` or `roles.revoke`).

**AD-S01-05 The backend is degraded** (`e2e`; E42-S01 "Backend degraded")

- Pre: OWNER, elevated; OVERVIEW-503.
- Steps: open `/admin`; then move through the shell's navigation.
- Expected: the error state, with the last-known values marked stale and a retry control. The shell and its
  navigation stay usable.
- Audit: `admin.area_entered` per call; nothing else.

**Negative and boundary cases**

- **AD-S01-N01 The grace's boundary, and what voids it** (`contract`; D02 A-14; SR-025; AC-ADM-03, -04):
  - with no token refresh in between, a second `users`-class action 4 min 59 s after a step-up passes with
    no challenge (`auth.step_up_grace_used`); at 5 min it is challenged (`403 step_up_required`,
    `auth.step_up_required`);
  - a refresh (`POST /auth/refresh`) or an idle lock voids the grace: the next action of the class is
    challenged (22 `authRefresh`). The read-only downgrade voids it too, and while it lasts a write answers
    `403 session_read_only`, not a challenge;
  - an action of another class is challenged whatever the `users` grace;
  - a `backups`, `killswitch` or `live_enablement` action always needs a fresh code; its one-shot grant is
    bound to the request it was challenged for, single use and valid for 60 s, so another request with it is
    refused `403 step_up_required`, `auth.step_up_mismatch` first, and leaves it bound. `22` also names
    `sl_loosen` no-grace, for an owner loosening a stop through `setPositionTpSl`; the server holds it
    only once E29-T07 extends it, and no admin case reaches it;
  - the grace is the server's, so a client clock set back changes nothing.
- **AD-S01-N02 Cancel leaves the draft** (`e2e`; D02 D2): cancelling the entry gate returns to the previous
  non-admin route, not a dead end. Cancelling a held save's gate says "Not saved", keeps the page and its
  draft, and sends nothing. Audit: none.
- **AD-S01-N03 A held save is never re-sent on its own** (`e2e`; D02 D2): if the re-sent save meets a
  network error, the page says the outcome is pending and re-reads; it does not send the save again. Audit:
  at most one record of the save.
- **AD-S01-N04 A failed re-auth** (`e2e`, `a11y`; D02 §6.1; AC-ADM-05): a wrong code answers
  `401 mfa_invalid` with `failures_remaining`, is announced assertively and audited `auth.step_up_failed`.
  The third failure makes the session read-only for 5 minutes (`auth.session_readonly_downgrade`, then
  `403 session_read_only` on every write), with Cancel the only action.
- **AD-S01-N05 Step-up time** (`perf`; SCR-149): the step-up answers in ≤400 ms, measured by E42-Q03.
  Audit: `auth.step_up_granted`.
- **AD-S01-N06 The audit marker names only registered actions** (`e2e`, `a11y`; D02 D5): every rung dialog
  ends with "Recorded in the audit log · <label> (`<code>`)", every state-changing control outside a dialog
  carries it in its `aria-describedby` line, an audited read says so in its page header ("Viewing this log
  is recorded"), and the audit export's marker adds "· needs your confirmation". Each code is a name in
  `audit/actions.py`, or absent: a marker never names an unregistered one. Audit: none.

### S02: the users list, invites and the lifecycle (US-ADMIN-001, 014; SCR-121, SCR-123)

**AD-S02-01 Invite, then grant the role [R]** (`e2e`, `contract`; E42-S02 "Create and assign role"; D02 D9)

- Pre: OWNER, elevated, on `/admin/users`.
- Steps: invite a user; copy the link; reload the page; redeem the invite in a second browser context
  (open the link, set a password, enrol TOTP); then make the user a manager on SCR-122.
- Expected:
  - the invite dialog has no role picker and says that the manager grant is a second step;
  - the row shows "Invited" until the invite is redeemed;
  - the one-time link is shown once, as a secret, with a copy control and a statement that it will not be
    shown again; after the reload no link is shown;
  - the link is held in memory only: it never reaches browser storage, analytics payloads or logs (E42-S02
    security notes), which the tester checks after the copy and after the reload;
  - the pending list offers revoke and re-issue.
- Audit: `users.invited`, naming the actor and the target; on the second step, `roles.grant`. See Q-2.
- End: the link is redeemed or revoked (`users.invite_revoked`), so none outlives the case.

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
  - MGR-M's data is kept, and the row shows "Disabled" with an Enable action (D02 D8).
- Audit: `users.disable`, then `auth.session_revoked` per session, then `rules.disarm`. AD-X-01 is the
  two-context version.

**AD-S02-03 Delete keeps the history [R]** (`e2e`, `integration`; E42-S02 "Delete with history"; 22
`deleteUser`)

- Pre: OWNER, elevated; MGR-M, active. The anonymisation half needs the server's clock moved (§0), so it
  runs on the testnet stack, which seeds users only, with MGR-U in place of MGR-M.
- Steps: delete MGR-M through its rung-3 dialog, typing MGR-M's username to confirm.
- Expected:
  - the confirm control stays disabled until the counts load and the typed name matches, and Enter in the
    name field never confirms (D02 D3, D18);
  - the delete (`DELETE /users/{userId}?purge=true`; `503 purge_unavailable` while no reaper runs) first
    disables MGR-M, then schedules the purge 90 days out; MGR-M's audit and journal history stay;
  - the anonymised reference appears only once the purge has run, which the reaper does after that date:
    with the clock moved past it, the reaper writes `users.anonymise`, MGR-U's username and email read as
    a surrogate, and every audit row about MGR-U is unchanged (UL-AC12).
- Audit: `users.disable`, `auth.session_revoked` per session, `rules.disarm` for each armed rule, then
  `users.delete`. The reaper writes `users.anonymise` later. See Q-10 on the "Disabled/Deleted" filter.

**AD-S02-04 The last owner is protected [R]** (`e2e`, `contract`; E42-S02 "Last owner protection"; AC-ADM-28)

- Pre: OWNER is the only Owner, elevated with a live `users` grace.
- Steps: look at OWNER's own row; then send `DELETE /users/{OWNER}` and a `PATCH` to `disabled` directly.
- Expected: Disable and Delete are disabled on the row with the reason "You can't remove your own owner
  role." (D02 §6.3). Each direct request is refused and nothing changes.
- Audit: `rbac.denied` per request. See Q-3 for the status the server answers.

**AD-S02-05 Capacity reached** (`e2e`; E42-S02 "Capacity reached")

- Pre: TIER-FULL.
- Expected: the capacity line reads "5 of 5 used" and names the recorded tier. The Business KYC path and the
  isolation trade-off of sharing a sub-account are explained. With the tier unrecorded, no cap is shown: D02
  D8's three capacity states.
- Audit: none (a read).

**AD-S02-06 Step-up expires during a delete [R]** (`e2e`, `contract`; E42-S02 "Step-up expired during a
destructive action")

- Pre: the delete confirmation for MGR-M is open; the `users` grace then lapses.
- Steps: confirm; re-authenticate.
- Expected: the gate appears. After success the delete goes ahead exactly once, with the same idempotency
  key; replaying the request with that key writes nothing.
- Audit: `auth.step_up_required`, `auth.step_up_granted`, `auth.step_up_grace_used`, then `users.disable`,
  `auth.session_revoked` per session, `rules.disarm` and one `users.delete`.

**Negative and boundary cases**

- **AD-S02-N01 The invite link is never served again** (`contract`; AC-ADM-27 holds a spent link's replay):
  no read of the invite answers its link. Audit: none.
- **AD-S02-N02 An invite may name only the viewer role** (`contract`; 22 `CreateUserRequest`; SR-027):
  OWNER, elevated, sends an invite naming `manager` or `owner`. It answers `422`, and no invite is
  written. Audit: `users.invite_refused`.
- **AD-S02-N03 Two owners disable one manager at once** (`integration`; 22 `deleteUser`, `updateUser`):
  OWNER and OWNER-2 are each elevated, and MGR-M is active. Two `DELETE`s answer `204` twice and write one
  `users.disable`, the second being a no-op with no record. Two `PATCH`es to `disabled` with the same
  `ETag` answer one `200` and one `412 version_conflict`, and the loser changes nothing; the second must
  send `If-Match`, since without it the server reads last write wins.
- **AD-S02-N04 A disabled user cannot sign in, and enabling restores nothing else** (`e2e`; 22 `updateUser`,
  `login`): the sign-in is refused with no session and recorded `auth.login_failed` (Q-15). On Enable,
  `users.enable`; the grants, sessions and disarmed rules stay gone, and a scheduled purge is cancelled.
- **AD-S02-N05 The status chips** (`e2e`; D02 D8): LOCKED-L shows "Locked out (sign-in)", and a manager under
  a risk lockout "Trading locked (risk)", each with its until-time.
- **AD-S02-N06 An invite without a live `users` grace is challenged** (`contract`, `integration`; SR-025;
  D02 §13.2; Q-17): OWNER, holding no `users` grace, sends `POST /users` with a valid viewer body. It
  answers `403 step_up_required` (`action_class: users`) and creates no user and no invite. The gate runs
  before the handler, so none of its records appears. Audit: `auth.step_up_required`, and neither
  `users.invited` nor `users.invite_refused`.
- **AD-S02-N07 An invite carries no account grant** (`contract`; SR-027; D02 D9; Q-17): OWNER, elevated,
  sends an invite with a non-empty `account_access`, as `22`'s `createUser` example does. It answers `422`
  and creates no user; the same body with `account_access` empty or absent is accepted. Audit:
  `users.invite_refused` (outcome `denied`) for the refusal.
- **AD-S02-N08 An unwritable audit record leaves a status change unchanged** (`integration`; 22
  `updateUser`; UL-AC05): OWNER, elevated; MGR-M, active; the `users.disable` record made unwritable.
  `PATCH /users/{userId}` to `disabled` answers `503 audit_unavailable` and changes nothing: MGR-M stays
  `active`, its sessions stay valid, its grants stay live and its rule stays armed. Audit: no
  `users.disable`, `auth.session_revoked` or `rules.disarm`.
- **AD-S02-N09 An unwritable audit record leaves a delete unchanged** (`integration`; 22 `deleteUser`;
  UL-AC05): the same Pre. `DELETE /users/{userId}` answers `503 audit_unavailable` and changes nothing, as
  AD-S02-N08 does. With `?purge=true` and only the `users.delete` record unwritable, the disable commits:
  the answer is `503 audit_unavailable`, MGR-M stays disabled with no purge scheduled, and once the writer
  is back a retry converges (the disable is a no-op, the purge is scheduled and `users.delete` is written).

### S03: user detail, bindings, limits and view-as (US-ADMIN-001, 002, 003, 008; SCR-122, SCR-124)

**AD-S03-01 Bind a manager to a sub-account [R]** (`e2e`, `contract`; E42-S03 "Bind a manager to a
sub-account")

- Pre: MGR-N, with no grants; PROFILE-S bound to SUB-S.
- Steps: grant MGR-N trade access to SUB-S; save with step-up.
- Expected: MGR-N sees and trades only SUB-S, under PROFILE-S.
- Audit: `users.access_change`, with the full grant sets before and after.

**AD-S03-02 Two bindings** (`e2e`; E42-S03 "Multiple bindings")

- Pre: MGR-N with a trade grant on SUB-S.
- Steps: add a grant on SUB-T for MGR-N.
- Expected: both accounts appear in MGR-N's scope selector on the next request, and MGR-N's own `GET /me`
  lists both.
- Audit: `users.access_change`.

**AD-S03-03 Unbind with open positions** (`e2e`, `integration`; E42-S03 "Unbind with open positions")

- Pre: POS-M-S.
- Steps: remove MGR-M's grant on SUB-S.
- Expected: the save is blocked until the owner chooses, with neither option pre-selected: leave the
  positions open (the owner takes them over) or flatten first (D02 §6.4).
- Audit: `users.access_change`, with its `positions_decision`. See Q-11.
- **AD-S03-03b An unknown position count fails closed** (`contract`; 22 `setUserAccountAccess`): OWNER is
  elevated, and while the open-position count cannot be read the save answers `409 positions_unknown`
  unless it carries `acknowledge_unknown_positions`. Audit: none for the refusal.

**AD-S03-04 Tighten a limit during an open position** (`e2e`, `integration`; E42-S03 "Tighten a limit
during an open position")

- Pre: POS-M-S.
- Steps: save the tightened limit.
- Expected: no position is closed. New entries for MGR-M are blocked, and reduce-only actions stay
  available. Both the owner and MGR-M are told.
- Audit: the limit change, with the old and new values, under the `risk_caps` class's step-up.
- **Blocked** until the per-user caps override has an admin endpoint (D02 O-G). See Q-4.

**AD-S03-05 View-as is unmistakably read-only [R]** (`e2e`, `security`; E42-S03 "View-as is unmistakably
read-only"; 22 "View-as session")

- Pre: OWNER, elevated; MGR-M, active.
- Steps: start "view as" for MGR-M, giving the entry dialog's mandatory reason; try each state-changing
  control; exit.
- Expected:
  - the banner is the document's first element and names MGR-M and the read-only state; its Exit is the
    first tab stop, in every window, and `Esc` never exits (D02 D10, D18);
  - the countdown runs to the server's `expires_at`;
  - MGR-M is told someone is viewing as them; the reason is never shown to MGR-M (D02 D10);
  - every state-changing control is disabled, with a reason, **except the protective writes** (C-2.6; 22
    "View-as session", "Protective writes"): engaging the kill switch on the target's accounts, amending an
    order or a trade group, and setting a position's TP/SL stay enabled and are served as the viewer (the
    audit actor), when the viewer's and the target's RBAC both allow them. D02 draws only one of them as an
    enabled control, the freeze engage on the target's accounts (rung 0; D02 §4.1 and §5). The handlers of
    the four are not mounted yet, so this half is blocked (§6);
  - the carve-out is bounded: releasing the kill switch, `scope: global` and an amend with any non-protective
    component are refused `403 view_as_read_only` by their handlers, before any effect; any other write sent
    anyway is refused the same way before authorisation, validation and any step-up (AC-ADM-22).
- Audit: `admin.view_as_started` (severity `warning`, see Q-12); `admin.view_as_refused` per refused write;
  `risk.freeze_manager` for a freeze engaged while viewing (D02 §5), the viewer being its actor;
  `admin.view_as_ended` on exit.

**AD-S03-06 A concurrent edit is surfaced** (`e2e`, `contract`; E42-S03 "Concurrent edit"; 22 `updateUser`;
UL3-T1)

- Pre: OWNER and OWNER-2 are each elevated. OWNER loads MGR-M's detail; OWNER-2 then changes MGR-M's roles.
- Steps: OWNER saves a profile field (`PATCH /users/{userId}` with the `If-Match` it loaded).
- Expected: `412 version_conflict`, shown as "This user changed while you were editing" with a reload
  action. OWNER's change is not applied.
- Audit: OWNER-2's `roles.grant` or `roles.revoke` only. A roles save is last-write-wins; see Q-13.

**Negative and boundary cases**

- **AD-S03-N01 View-as refusals, in the contract's order** (`contract`; 22 `startViewAs`; AC-ADM-22), all
  before the step-up gate, so never a `step_up_required` challenge:
  - an invalid body: `422 validation_failed`, with no record;
  - a second start while viewing, live or held: `409 view_as_active`;
  - viewing oneself: `403 view_as_self_target`;
  - an unknown user: `404 not_found`;
  - INVITED-I or DISABLED-D: `409 conflict`;
  - an Owner (OWNER-2): `403 view_as_owner_target`.

  Every refusal but the `422` is recorded `admin.view_as_refused`. LOCKED-L can be viewed. Combined, to prove
  the order: an invalid body while viewing is `422`; a second start naming oneself, an unknown id or OWNER-2
  is `409 view_as_active`; a start naming oneself or OWNER-2 with no live `users` grace is its own `403`.

- **AD-S03-N02 An expired view is held, not ended for the owner** (`e2e`, `contract`; 22 "Expiry and the
  hold"; 23 §9.6; D02 §6.6 and A-4; AC-ADM-22): at `expires_at` the server ends the context, request or not,
  and holds it. The banner says the view ended and offers Exit; every operation except the viewer's own and
  the protective writes, reads included, answers `403 view_as_expired`; the owner's socket gets
  `bye view_as_expired` (no reconnect) and closes with 4403. Exit (`DELETE /auth/session/view-as`, `204`)
  clears the hold. Audit: one `admin.view_as_ended`, reason `expired` (`recorded_late` only if the writer was
  down), none when the hold is cleared, and `admin.view_as_refused` per refusal in the hold.
- **AD-S03-N03 A view reads only what the user reads** (`security`; 22 "View-as session"; AC-ADM-22): an owner
  viewing as MGR-M gets MGR-M's answers, statuses and refusals (an Owner-only route answers `403 forbidden`),
  and every record names the owner.
- **AD-S03-N04 The key restriction on SCR-122** (`e2e`; D02 D8): SUB-K's row shows the 48-hour restriction
  with its absolute unlock time.
- **AD-S03-N05 A stale grant set re-grants a revoked account** (`integration`, `e2e`; 22
  `setUserAccountAccess`; E42-S03 technical notes; Q-16): OWNER loads MGR-MANY's grants (SUB-S, SUB-T,
  SUB-U); OWNER-2 then removes SUB-S and saves; OWNER, whose page still lists SUB-S, changes SUB-U's level
  and saves, the payload being the complete set (replace semantics). The route takes no `If-Match`, so the
  save answers `200` with the stored set, SUB-S included, and SUB-S is a live grant again (its soft-revoked
  row is revived, its freeze state and caps as they were). Nothing refuses it. Audit: `users.access_change`
  for each save: OWNER-2's has SUB-S in its `before_state` only, OWNER's in its `after_state` only. Until
  Q-16 is answered the case records this end state, and a tester files it against Q-16, not as a defect.
- **AD-S03-N06 The view-as start's gates** (`contract`, `security`; 22 `startViewAs`; AC-ADM-22; SR-025):
  - a valid start (an eligible target and a good reason) with no live `users` grace answers
    `403 step_up_required` (`action_class: users`, `action_summary` "View as user '<username>', read-only").
    No context starts (`GET /auth/session/view-as` answers `204`), MGR-M is not notified, and the only
    view-as-related record is `auth.step_up_required`, once: no `admin.view_as_started`, no
    `admin.view_as_refused`;
  - a reason that is empty, over 500 characters, or only whitespace or invisible characters answers
    `422 validation_failed` (AD-S03-N01's `422`) and writes no `admin.view_as_refused`; a reason of exactly
    500 characters passes;
  - a start by MGR-M, valid in every other way and with a live `users` grace, answers `403 forbidden` from
    the admin-area guard: `admin.area_entered` (outcome `denied`), no `admin.view_as_refused`, no challenge.
- **AD-S03-N07 The reason stays confidential** (`security`, `integration`; 22 `StartViewAsRequest`,
  `startViewAs`; D02 D10; AC-ADM-22): OWNER sends a start whose reason is a unique marker, first with no
  grace (the challenge), then after the step-up. The marker appears in the `admin.view_as_started` record's
  `after_state` and nowhere else: not in the challenge's `action_summary`, not in `GET /auth/session/view-as`,
  not in MGR-M's `GET /notifications` (its one `system` notification names OWNER and the window), not in
  a later `admin.view_as_refused` or `admin.view_as_ended` record, and not in any line of the run's
  captured server logs.
- **AD-S03-N08 The viewer's sockets follow the context** (`integration`, `security`; 23 §9.6, §4.3 and
  §16.4; AC-ADM-22): OWNER has two sessions, S1 and S2, each with a socket subscribed to a private topic.
  - S1 starts view-as for MGR-M: S1's sockets close with `bye view_as_changed` (`reconnect: true`) and
    `4401`, and S2's are unaffected. S1 reconnects, and its `auth_ok` carries MGR-M's `roles`,
    `permissions` and `account_scope`;
  - on S1 a `sub` to an account outside MGR-M's grants is refused as for MGR-M itself, with one
    `ws.subscribe.denied` naming OWNER's S1 session, and no owner-only `system` kind or other user's
    entity is delivered;
  - ending the live context (`DELETE /auth/session/view-as`) closes S1's sockets with `view_as_changed` and
    `4401` again, and S2's stay unaffected;
  - once the server has ended the context (AD-S03-N02), an `auth` or re-`auth` on S1 is refused with
    `bye view_as_expired` and `4403`, and does not count as a failed `auth`.
- **AD-S03-N09 An unwritable audit record leaves a role change unchanged** (`integration`; 22
  `setUserRoles`; UL-AC05): OWNER, elevated; VIEWER-V; the role records unwritable. The request
  `PUT /users/{userId}/roles` with `[manager]` answers `503 audit_unavailable`, and VIEWER-V's roles are
  as before. Audit: no `roles.grant` or `roles.revoke`.
- **AD-S03-N10 An unwritable audit record leaves a grant change unchanged** (`integration`; 22
  `setUserAccountAccess`; UL-AC05): OWNER, elevated; MGR-MANY subscribed to SUB-S; the
  `users.access_change` record unwritable. Removing the SUB-S grant answers `503 audit_unavailable`: the
  grant set is as before and MGR-MANY's subscription carries on, with no `revoked` frame. Audit: no
  `users.access_change` and no `ws.subscription.revoked`.
- **AD-S03-N11 An unwritable audit record stops a view-as start** (`integration`; 22 `startViewAs`;
  AC-ADM-22): OWNER with a live `users` grace; MGR-M; the `admin.view_as_started` record unwritable (the
  guard's `admin.area_entered` stays writable, so the refusal is the start's). The start answers
  `503 audit_unavailable`: no context starts (`GET /auth/session/view-as` answers `204`), OWNER's sockets
  see no `view_as_changed`, and MGR-M is not notified. Audit: no `admin.view_as_started`.

### S04: the audit log browser and event detail (US-ADMIN-001, 008, 009; SCR-135, SCR-136; D02 D11)

**AD-S04-01 Search the log [R]** (`e2e`, `perf`; E42-S04 "Search the log"; SCR-135; US-ADMIN-009)

- Pre: OWNER, elevated; AUDIT-10M loaded.
- Steps: filter by actor, action, subject, severity and a time range; page forward twice and back once.
- Expected: matching entries in a stable order, with cursor pagination of 200 rows. The first page answers
  within 2 s, and a filter round trip within 400 ms (SCR-135). The labels come from the registered
  vocabulary (D11).
- Audit: `admin.audit_read`.

**AD-S04-02 No mutation affordance exists [R]** (`e2e`, `security`; E42-S04 "No mutation affordance
exists"; D11)

- Steps: inspect every row, the detail drawer and the page chrome; then send every non-read HTTP verb to
  each `/admin/audit*` path.
- Expected: no edit, delete or correct control anywhere. The page says the log is append-only and kept
  indefinitely. No verb changes a record (AC-ADM-15 holds the API half).

**AD-S04-03 Integrity verification [R]** (`e2e`, `integration`; E42-S04 "Integrity verification"; D11;
22 `verifyAuditChain`)

- Pre: AUDIT-CORRUPT, the corrupted-chain fixture, on a test database.
- Steps: run the tamper check over the full range; then over a range that ends before the break.
- Expected: the first run reports the break at the fixture's `first_bad_id`, as a critical banner naming
  a security incident, not a UI error. The second reports the range verified. The page footer's tamper
  line shows its three states across the runs.
- Audit: `admin.audit_verify` per run.

**AD-S04-04 A manager sees only their own actions [R]** (`e2e`, `contract`; E42-S04 "Manager scope"; D11)

- Pre: MGR-M, with actions of its own and of others in the log.
- Steps: open the audit log; then ask the API for another actor's events.
- Expected: only MGR-M's own actions, enforced server-side, under the header "Showing your actions only".
  The request for another actor's events answers `403 forbidden`.
- Audit: `admin.audit_read`; the refusal, `admin.audit_denied`.

**AD-S04-05 Export is signed and audited [R]** (`e2e`, `contract`; E42-S04 "Export is signed and
audited"; D11; 22 `exportAuditLog`)

- Pre: OWNER, with the `audit` class's step-up.
- Steps: export the filtered set; follow the job; download the file; verify its signature.
- Expected: an async job with visible progress produces a signed NDJSON file, and redaction is kept in it.
  The export control names the real format.
- Audit: `admin.audit_export` for the request and again, with reason `downloaded`, for the download. See
  Q-5.

**AD-S04-06 A failed export offers no partial file** (`e2e`; E42-S04 "Export job fails")

- Pre: an export job that ends `failed`.
- Expected: the failure shows its reason and a retry action, and no partial file is offered.

**AD-S04-07 A secret-bearing entry shows fingerprints only [R]** (`e2e`, `security`; E42-S04 "Secret-bearing
entry")

- Pre: AUDIT-KEY-ENTRY, an entry whose before and after states referenced key material.
- Expected: the diff renders fingerprints only, never a secret value, in the drawer and in the export.

**Negative and boundary cases**

- **AD-S04-N01 An export over the range limit** (`contract`; 22 `exportAuditLog`): a window longer than
  `audit_export_max_range_days` (31 by default) answers `422 validation_failed`, with `errors[].rule`
  `max_export_range`, and no job is created.
- **AD-S04-N02 The export rate limit** (`contract`): the sixth export in an hour answers `429 rate_limited`
  with `Retry-After`.
- **AD-S04-N03 One export at a time** (`contract`): a second export while one is queued or running answers
  `409 conflict`.
- **AD-S04-N04 An expired download** (`contract`): a download after `expires_at` answers `410 gone`.
- **AD-S04-N05 Export without the step-up** (`contract`): `403 step_up_required` with `action_class`
  `audit`, and no job.
- **AD-S04-N06 The detail's fetch** (`perf`; SCR-136): one record in ≤300 ms; the raw payload loads only
  when expanded.

### S05: feature flags and maintenance mode (US-ADMIN-001, 007, 011, 012; SCR-145, SCR-148; D02 D13, D15)

**AD-S05-01 A flag change reaches every user within 10 s [R]** (`e2e`; E42-S05 "Toggle a flag";
US-ADMIN-007)

- Pre: OWNER, elevated; FLAG-UI, on; MGR-M and VIEWER-V connected. See Q-9.
- Steps: disable the flag through its dialog.
- Expected: the feature disappears for every connected user within **≤10 s** of the `flags.change`
  record, through the `system` topic.
- Audit: `flags.change`, with the before and after values and OWNER as the actor.

**AD-S05-02 A safety flag needs a fresh step-up** (`e2e`, `contract`; E42-S05 "Safety flags require
step-up"; D13)

- Pre: OWNER, with no live grace for the flag's class.
- Steps: change a trading-capability flag.
- Expected: the gate appears, and the write does not happen until the step-up succeeds.
- Audit: `auth.step_up_required`, `auth.step_up_granted`, then one `flags.change`.

**AD-S05-03 Each flag's state is visible** (`e2e`; E42-S05 "Flag state visibility"; D13)

- Expected: flags are grouped as Safety flags, Gated, Rollouts and Other. Each shows its state as a word, its
  description, its scope, who changed it last and when, and its own history. The `fail_closed`,
  `unreadable` and `409 conflict` states are drawn. No flag is labelled "kill switch".

**AD-S05-04 Live enablement stays blocked [R]** (`e2e`, `contract`, `security`; E42-S05 "Live enablement
stays blocked here"; 22 `setFeatureFlag`)

- Pre: FLAG-LIVE-BLOCKED: `trading.live_enabled` off, the pen-test sign-off outstanding.
- Steps: look at the flag's row; then write it directly through the API.
- Expected: the toggle is disabled, with the blocking reason and a link to the security centre. The direct
  write answers `422 validation_failed` with rule `gate_evidence_required`, and nothing is written.

**AD-S05-05 Maintenance mode's consequences are explicit [R]** (`e2e`; E42-S05 "Maintenance mode
consequences are explicit"; SCR-148; D15)

- Steps: open the maintenance entry dialog; turn maintenance on; then turn it off.
- Expected:
  - the dialog is `role="alertdialog"` and lists exactly: new orders blocked, running algos cancelled,
    recording continues, managers see a maintenance notice; it says native exchange stops stay active;
  - turning it on is a rung-2 action of the `flags` class; turning it off is rung 4, `killswitch`, and
    always needs a fresh code (D15). See Q-6 on the typed confirmation.
- Audit: `flags.change` and `maintenance.enabled`; then `flags.change` and `maintenance.disabled`.

**AD-S05-06 A rejected write leaves no optimistic state** (`e2e`; E42-S05 "Flag write rejected
mid-flight")

- Pre: the server answers the flag write `422`.
- Expected: the toggle returns to the server's value, with an inline error naming the reason.

**AD-S05-07 Armed rules that depend on a flag are listed** (`e2e`; E42-S05 "Armed rule depends on the
flag")

- Pre: RULES-ON-FLAG, two armed rules that depend on the flag being disabled.
- Expected: the dialog lists both rules, and the write waits for the owner's acknowledgement.

**Negative and boundary cases**

- **AD-S05-N01 A flag changed twice in one second** (`e2e`, `integration`; US-ADMIN-007; 23 §8.1 and §15.9): two `flags.change` records, in order. The `system` topic does not throttle flag
  frames, so every connected client receives both, in order, and ends on the second value within ≤10 s.
- **AD-S05-N02 Two owners change one flag** (`contract`; D13): the second write, made on a stale version,
  answers `409 conflict`, and nothing of it is applied.
- **AD-S05-N03 A safety flag ignores overrides** (`security`; AC-ADM-09): an override row never changes a
  safety flag's resolved value, and an unreadable row fails closed.

### S06: system health, incidents and backups (US-ADMIN-001, 011; SCR-143, SCR-144, SCR-146; D02 D12, D14)

**AD-S06-01 The health overview** (`e2e`, `a11y`; E42-S06 "Health overview"; D12)

- Steps: open `/admin/health`.
- Expected: WebSocket connection states, ingest rates and lag, the rate-limit budget per account, queue
  depths, database sizes and latency, error rates and process uptime. Each tile shows a number with its
  unit, a state word and "as of"; never colour alone.

**AD-S06-02 Drill down** (`e2e`; E42-S06 "Drill down"; D12)

- Steps: select the recorder.
- Expected: its recent errors, recent reconnects and metrics over the last hour. The sparkline has a table
  alternative.

**AD-S06-03 A degraded state names its impact [R]** (`e2e`; E42-S06 "Degraded state names the impact")

- Pre: HEALTH-SUB002-WS-DOWN, the private WebSocket for `sub_002` down.
- Expected: that tile escalates with a text label, names the features affected and gives a remediation
  hint. The page says native exchange stops are unaffected.

**AD-S06-04 The page survives the outage it reports [R]** (`e2e`; E42-S06 "The page survives the outage it
reports"; D4)

- Pre: HEALTH-TIMEOUT: `GET /api/v1/admin/health` times out, and the `system` topic is the only live
  source.
- Expected: the shell and navigation stay usable. Each tile keeps its last-known value, marked "stale
  since", rather than an empty page.

**AD-S06-05 Restore is gated [R]** (`e2e`, `contract`; E42-S06 "Restore is gated"; D14)

- Pre: OWNER with 2 open positions.
- Steps: start the restore wizard and go through to the confirmation.
- Expected:
  - the wizard leads with "Bybit is not affected", and the owner must acknowledge that a restore changes
    nothing on Bybit before continuing;
  - the impact preview says trading halts during the restore and market history is not restored;
  - completion is rung 4: the backup's timestamp as the typed token, and a fresh `backups` code.
- Audit: `backup.restore`, at high severity.

**AD-S06-06 A failed verification is shown with its reason [R]** (`e2e`; E42-S06 "Backup verification
fails")

- Pre: BACKUP-VERIFY-FAILED, the most recent backup having failed verification.
- Expected: its row shows the failed-verification state and its reason, and a warning states how old the
  last verified backup is.

**AD-S06-07 No backups yet** (`e2e`; E42-S06 "No backups yet")

- Pre: BACKUPS-NONE.
- Expected: the empty state says no backup has run, names the schedule and offers "Back up now".

**Negative and boundary cases**

- **AD-S06-N01 An acknowledged incident stays open** (`e2e`, `contract`; D12; 22 `listIncidents`):
  acknowledging never resolves; the system resolves it, and a new occurrence reopens it. Audit:
  `incident.acknowledged`.
- **AD-S06-N02 A backup's download and delete always need a fresh code** (`contract`; D14): rung 4, no
  grace. Audit: `backup.downloaded`, `backup.deleted`.

### S07: manager onboarding and governance (US-ADMIN-001, 005, 006, 013; SCR-140, SCR-141)

**AD-S07-01 The guided steps** (`e2e`; E42-S07 "Guided steps")

- Steps: start the manager onboarding flow and complete it.
- Expected: it walks through sub-account creation, the 48-hour key restriction, key creation with 2FA,
  permission scoping, IP whitelisting, profile creation and limits, marking each completed step.

**AD-S07-02 A blocked step does not halt the flow [R]** (`e2e`; E42-S07 "Blocked step does not halt the
flow"; D02 D8)

- Pre: SUB-K, under the 48-hour key restriction.
- Expected: the key step is blocked and shows the exact unlock time, as an absolute time. The other steps
  stay available.

**AD-S07-03 Resume on another device** (`e2e`; E42-S07 "Resume")

- Pre: the flow left after the profile step.
- Steps: return on a different device.
- Expected: the flow resumes at the first incomplete step, with the earlier steps marked complete.

**AD-S07-04 Disable a trade group** (`e2e`, `integration`; E42-S07 "Disable a trade group")

- Pre: GROUP-G, enabled, with an open group trade.
- Steps: disable G.
- Expected: G leaves the ticket's targets, and the positions opened through G stay fully manageable.

**AD-S07-05 A membership change keeps the open trade's snapshot** (`integration`; E42-S07 "Membership change
during an open trade")

- Pre: GROUP-G with an open group trade.
- Steps: change G's membership.
- Expected: the open trade keeps its original membership, and its detail shows which group version it used.

**AD-S07-06 A secret is never shown again [R]** (`e2e`, `security`; E42-S07 "Secret never re-displayed";
C-2.7)

- Steps: enter an API secret at the key step; go back to that step.
- Expected: only the key's fingerprint and status are shown. No secret value was written outside the
  encrypted store: not in a log, a record, the page state or local storage.

**AD-S07-07 A recorder purge meets the gate first** (`e2e`; E42-S07 "Recorder purge from the admin area")

- Pre: OWNER with no live grace.
- Steps: open `/admin/recorder`; purge.
- Expected: the gate appears before any destructive control is reachable. The purge shows its impact
  preview and is rung 3: the object's own name as the typed token. See Q-8.

### E42-T07 and E42-S08: the statechart inspector

**AD-T07-01 List the live machines** (`contract`; E42-T07 "List live machines"; 22 `listStatecharts`)

- Pre: several machines running.
- Expected: one row per machine, with its kind, state, `machine_hash`, `chain_trips` and
  `dropped_receipts`.

**AD-T07-02 No live interpreter is queried** (`unit`, `integration`; E42-T07 "No hot-path interpreter
query"; C-2.20)

- Expected: the answer comes from the persisted snapshots and `machine_events`; a spy on the interpreter
  records no call.

**AD-T07-03 The export matches the registered chart** (`contract`; E42-T07 "Stately export matches the
registered chart")

- Expected: the export for a registered `machine_hash` round-trips through the Stately schema the chart
  was authored in.

**AD-T07-N01 A snapshot whose seal fails is left out** (`security`; 22 `listStatecharts`): it is left out of
the list, `snapshots` says `error` with a fixed reason, and a critical event is raised once per machine,
environment and snapshot.

**AD-S08-01 See a degraded machine [R]** (`e2e`; E42-S08 "See a degraded machine")

- Pre: SC-CHAIN-TRIPS, a machine restored with `chain_trips` above 0.
- Expected: it is listed as degraded, with its `chain_trips` and `dropped_receipts` counts shown.

**AD-S08-02 Acknowledge a latch [R]** (`e2e`, `integration`; E42-S08 "Acknowledge a latch")

- Pre: SC-CHAIN-TRIPS.
- Steps: acknowledge the latch with step-up.
- Expected: the latch clears, and the machine serves order-path commands again. The acknowledgement is
  audited with the owner's identity. See Q-7.

**AD-S08-03 Acknowledging without elevation is refused** (`contract`; E42-S08 "Acknowledge without
elevation is refused")

- Expected: the server refuses, the gate appears, and the latch stays set.

**AD-S08-04 The diagram matches the running chart** (`e2e`; E42-S08 "State diagram matches the running
chart")

- Expected: the diagram matches the Stately export for that `machine_hash` and highlights the current
  state.

## 3. Cross-session scenarios

Each needs two browser contexts: A is the owner, and B is the other user. The timing is the story's or the
catalogue's, and it is measured between server timestamps.

**AD-X-01 The owner disables a manager who is trading [R]** (`e2e`; US-ADMIN-001; E42-S02)

- B: MGR-M, with the order ticket open, a live WebSocket and one armed rule.
- A: OWNER disables MGR-M and confirms.
- Expected:
  - every session of MGR-M is revoked within **≤5 s** of the `users.disable` record, measured to the last
    `auth.session_revoked` record;
  - B's socket gets `bye user_disabled` and closes with 4403 (23 §9.5), and B's next request answers
    `401 unauthenticated`;
  - B's armed rule is disarmed;
  - no order is placed after the disable (UL-AC02, UL-AC15): no `orders.submit` for MGR-M is accepted later
    than the first `auth.session_revoked` record, which the server writes after the commit; the rule's
    first evaluation after the commit emits no order intent, even if it was `evaluating` at the commit; and
    MGR-M's open orders and positions are neither cancelled nor amended (`positions_decision: leave`). The
    ticket half needs `POST /orders` (E29-T07, as AC-ADM-12); the rule half does not.
- Audit: `users.disable`, `auth.session_revoked` per session, `rules.disarm`.

**AD-X-02 The owner revokes a grant while the manager is subscribed [R]** (`e2e`; 22
`setUserAccountAccess`; 23 §16.4 "Grant revocation mid-stream")

- B: MGR-MANY, subscribed to SUB-S's and SUB-T's private topics.
- A: OWNER removes MGR-MANY's grant on SUB-S.
- Expected: B receives `revoked` for SUB-S's subscriptions within **≤2 s** of the `users.access_change`
  record (22 `setUserAccountAccess`; `23` §16.4's matrix asks ≤1 s, see Q-14), and the SUB-T topics carry
  on. B's next read of SUB-S answers as for an account it was never granted, and resubscribing to SUB-S
  alone is refused `account_scope_denied` (a refused `sub_ok` result, 23 §6.2; `403` on REST).
- Audit: `users.access_change` (before and after grant sets), `ws.subscription.revoked`, then, for the
  resubscribe, one `ws.subscribe.denied` naming B's session (23 §5.2).

**AD-X-03 The owner enables maintenance while a manager has the order ticket open [R]** (`e2e`; SCR-148;
22 `setFeatureFlag`)

- B: MGR-M, with the order ticket open.
- A: OWNER, with a live `flags` grace, turns `maintenance.mode` on.
- Expected:
  - order acceptance is blocked server-side within **≤200 ms** (SCR-148): B keeps submitting
    exposure-opening orders across the switch, and no `orders.submit` is accepted later than the
    `maintenance.enabled` record plus 200 ms; each one refused after it answers `403 trading_disabled` with
    `reason: maintenance` and is recorded `orders.submit` (denied);
  - the maintenance notice reaches every session, B's included, within **≤2 s** (SCR-148), measured to the
    `notice` frame's `ts` (23 §15.9); B's carries only what `23` §15.9's table gives a Manager for a
    `notice` (`kind`, `severity`, `message`, `reason`), which AC-ADM-11 and AC-ADM-35 hold;
  - B's cancels, closes (`closePosition`, `closeAllPositions`), attaching a missing native SL, and
    quantity-reducing and stop-tightening amends still pass (22 `setFeatureFlag`; AC-ADM-12).
- **Blocked** on `POST /orders` for the order bullets (E29-T07; AC-ADM-12).
- End: A turns maintenance off, a rung-4 `killswitch` action with no grace (D02 D15; AC-ADM-07): a fresh
  code is asked, and B's next order is no longer refused for `reason: maintenance`.
- Audit: `auth.step_up_grace_used`, `flags.change`, `maintenance.enabled`; B's refused order, `orders.submit`
  (denied); on the off step, `auth.step_up_required`, `auth.step_up_granted`, `flags.change`,
  `maintenance.disabled`.

## 4. Exploratory charters

Each charter is timeboxed, within `03-testing-strategy.md` §11.2's 60 to 120 minutes. A charter ends with
notes, the defects filed and the coverage it reached.

| Charter                                                                                                                                                                                                  | Timebox | What would make this a finding                                                                                                                                                  |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **CH-AD-1** Try to see data outside your scope as a manager: deep links with foreign ids, the scope selector, `/me`, WebSocket subscriptions, the own-redacted audit view, exports                       | 90 min  | Any byte of another user's or an ungranted account's data; or a foreign id answered differently from a missing one                                                              |
| **CH-AD-2** Try to make the audit log look editable: SCR-135 and SCR-136 controls, every HTTP verb on `/admin/audit*`, the export, a detail view edited in the browser, the chain check on AUDIT-CORRUPT | 60 min  | Any control or verb that changes a record; any affordance that suggests editing; a verify of AUDIT-CORRUPT that reports an intact chain or another `first_bad_id`               |
| **CH-AD-3** Try to reach an admin screen without elevation: deep links, the back button after a cancelled gate, a second tab, a grace lapsing mid-load, a view-as session                                | 60 min  | A step-up-gated action that succeeds with no live grace or bound grant; a state change or admin call with no record; an Owner-only route not refused `403` in a view-as session |
| **CH-AD-4** Try to lose form content by letting the step-up lapse, on every admin form                                                                                                                   | 60 min  | A form whose content is lost, that saves twice, or that saves without passing the gate                                                                                          |
| **CH-AD-5** Try to make two tiles block each other: SCR-120 with subsystems slowed, failing and flapping                                                                                                 | 60 min  | One tile's failure or slowness delays another past 800 ms; a retry that blocks the page                                                                                         |

CH-AD-2's chain check runs on AUDIT-CORRUPT, in a test database only, never on staging: a stored record
changed there would permanently break an append-only, hash-chained log.

## 5. Traceability

| Story   | Gherkin scenario                                      | Cases                                                              |
| ------- | ----------------------------------------------------- | ------------------------------------------------------------------ |
| E42-S01 | Owner enters the admin area with a stale token        | AD-S01-01, AD-S01-N01, AD-S01-N02, AD-S01-N04, AD-S01-N05, CH-AD-3 |
| E42-S01 | Non-owner cannot reach the admin area                 | AD-S01-02, CH-AD-1                                                 |
| E42-S01 | Overview tiles resolve independently                  | AD-S01-03, CH-AD-5                                                 |
| E42-S01 | (failure) Re-auth expires mid-edit                    | AD-S01-04, AD-S01-N02, AD-S01-N03, CH-AD-4                         |
| E42-S01 | (edge) Backend degraded                               | AD-S01-05                                                          |
| E42-S02 | Create and assign role                                | AD-S02-01, AD-S02-N01, AD-S02-N02, AD-S02-N06, AD-S02-N07          |
| E42-S02 | Disable revokes access quickly                        | AD-S02-02, AD-X-01, AD-S02-N04                                     |
| E42-S02 | Delete with history                                   | AD-S02-03                                                          |
| E42-S02 | (failure) Last owner protection                       | AD-S02-04                                                          |
| E42-S02 | (edge) Capacity reached                               | AD-S02-05                                                          |
| E42-S02 | (failure) Step-up expired during a destructive action | AD-S02-06                                                          |
| E42-S02 | (ticket rule) No audit record, no action              | AD-S02-N08, AD-S02-N09                                             |
| E42-S03 | Bind a manager to a sub-account                       | AD-S03-01                                                          |
| E42-S03 | Multiple bindings                                     | AD-S03-02                                                          |
| E42-S03 | Unbind with open positions                            | AD-S03-03, AD-S03-03b                                              |
| E42-S03 | Tighten a limit during an open position               | AD-S03-04                                                          |
| E42-S03 | View-as is unmistakably read-only                     | AD-S03-05, AD-S03-N01 to AD-S03-N03, AD-S03-N06 to AD-S03-N08      |
| E42-S03 | (failure) Concurrent edit                             | AD-S03-06, AD-S02-N03, AD-S03-N05                                  |
| E42-S03 | (ticket rule) No audit record, no action              | AD-S03-N09 to AD-S03-N11                                           |
| E42-S04 | Search the log                                        | AD-S04-01, AD-S04-N06                                              |
| E42-S04 | No mutation affordance exists                         | AD-S04-02, CH-AD-2                                                 |
| E42-S04 | Integrity verification                                | AD-S04-03                                                          |
| E42-S04 | Manager scope                                         | AD-S04-04, CH-AD-1                                                 |
| E42-S04 | Export is signed and audited                          | AD-S04-05, AD-S04-N01 to AD-S04-N05                                |
| E42-S04 | (failure) Export job fails                            | AD-S04-06                                                          |
| E42-S04 | (edge) Secret-bearing entry                           | AD-S04-07                                                          |
| E42-S05 | Toggle a flag                                         | AD-S05-01, AD-S05-N01                                              |
| E42-S05 | Safety flags require step-up                          | AD-S05-02, AD-S05-N03                                              |
| E42-S05 | Flag state visibility                                 | AD-S05-03, AD-S05-N02                                              |
| E42-S05 | Live enablement stays blocked here                    | AD-S05-04                                                          |
| E42-S05 | Maintenance mode consequences are explicit            | AD-S05-05, AD-X-03                                                 |
| E42-S05 | (failure) Flag write rejected mid-flight              | AD-S05-06                                                          |
| E42-S05 | (edge) Armed rule depends on the flag                 | AD-S05-07                                                          |
| E42-S06 | Health overview                                       | AD-S06-01                                                          |
| E42-S06 | Drill down                                            | AD-S06-02                                                          |
| E42-S06 | Degraded state names the impact                       | AD-S06-03                                                          |
| E42-S06 | The page survives the outage it reports               | AD-S06-04, CH-AD-5                                                 |
| E42-S06 | Restore is gated                                      | AD-S06-05, AD-S06-N02                                              |
| E42-S06 | (failure) Backup verification fails                   | AD-S06-06                                                          |
| E42-S06 | (edge) No backups yet                                 | AD-S06-07                                                          |
| E42-S06 | (no scenario) An acknowledged incident stays open     | AD-S06-N01                                                         |
| E42-S07 | Guided steps                                          | AD-S07-01                                                          |
| E42-S07 | Blocked step does not halt the flow                   | AD-S07-02                                                          |
| E42-S07 | Resume                                                | AD-S07-03                                                          |
| E42-S07 | Disable a trade group                                 | AD-S07-04                                                          |
| E42-S07 | Membership change during an open trade                | AD-S07-05                                                          |
| E42-S07 | (failure) Secret never re-displayed                   | AD-S07-06                                                          |
| E42-S07 | (edge) Recorder purge from the admin area             | AD-S07-07                                                          |
| E42-T07 | List live machines                                    | AD-T07-01, AD-T07-N01                                              |
| E42-T07 | No hot-path interpreter query                         | AD-T07-02                                                          |
| E42-T07 | Stately export matches the registered chart           | AD-T07-03                                                          |
| E42-S08 | See a degraded machine                                | AD-S08-01                                                          |
| E42-S08 | Acknowledge a latch                                   | AD-S08-02                                                          |
| E42-S08 | Acknowledge without elevation is refused              | AD-S08-03                                                          |
| E42-S08 | State diagram matches the running chart               | AD-S08-04                                                          |
| D02     | (no scenario) D5, the audit marker                    | AD-S01-N06                                                         |
| D02     | (no scenario) D8 patterns: chips, key restriction     | AD-S02-N05, AD-S03-N04                                             |

The scope's implied cases map as follows. "Expired token mid-action" is AD-S01-04 and AD-S02-06.
"Concurrent owner edits" is AD-S03-06 and AD-S02-N03 for a user's fields and roles, and AD-S03-N05 for
the grant set. "A manager session open while their grant is revoked" is AD-X-02. "An export over the
range limit" is AD-S04-N01, and "a flag changed twice in one second" is AD-S05-N01.

The omissions that the review of the S01 to S03 cases found landed as follows: the grant-edit race in
AD-S03-N05 (Q-16); the invite's step-up and `account_access` cases in AD-S02-N06 and AD-S02-N07 (Q-17);
the view-as start's gates, the reason's confidentiality and the sockets in AD-S03-N06 to AD-S03-N08; an
unwritable audit record in AD-S02-N08, AD-S02-N09 and AD-S03-N09 to AD-S03-N11; the invariant that no
order is placed after a disable in AD-X-01; and the view-as entry criterion in section 6.

## 6. Entry and exit criteria, per story group

**Entry.** A story group's cases start when all of these hold:

- the story is merged to `main` and deployed to staging, behind its flag if it has one;
- the group's fixtures are loaded, and each seed's own post-conditions passed (section 1);
- the group's `contract` cases are green in CI;
- the D02 frames the group's cases cite are signed off, and any §9 question a case depends on is answered or
  the case is marked blocked on it;
- for S03's view-as cases (AD-S03-05, AD-S03-N01 to AD-S03-N03, AD-S03-N06 to AD-S03-N08 and
  AD-S03-N11), `POST /admin/view-as` is mounted: on `main` today it is not (its `rbac/matrix.yaml` row is
  `not_mounted`, and AC-ADM-22 waits on #3085's server slice), so no context can start and those cases
  are blocked; AD-S03-05's protective-write half also needs the four handlers, E39-S03 (`setKillSwitch`),
  E29-T07 (`amendOrder`, `setPositionTpSl`) and E34-S03 (`amendTradeGroup`), since until each is mounted
  the guard refuses it like any other write.

**Exit.** A story group is done when all of these hold:

- every case of the group has a recorded result: pass or fail, the environment and the build SHA;
- every timing case records the two server timestamps it was measured between;
- no P0 or P1 defect is open, or each is explicitly accepted by the story owner;
- every **[R]** case of the group is automated (E42-Q02) or listed as manual in the regression pack;
- the group's screens passed the screen-reader script (section 8), executed by E42-Q05;
- every audit action the group's cases name was seen in the log, with its actor, target and outcome.

## 7. The regression pack

- **Members:** every case marked **[R]**. They cover each story group's headline behaviour, every
  cross-session scenario, every case whose failure is a security or money incident (view-as, live
  enablement, maintenance, the tamper check, the secret display), and each "survives the outage" case.
- **When:** every sprint after the group's exit, and on any change to the admin routes, the auth and RBAC
  modules, the audit writer or reader, the flag service, the health feed or the backup engine.
- **How:** the automated members run in CI's E2E and contract jobs (E42-Q02); the manual members run in the
  sprint's QA pass, with results recorded as in section 6.
- **Flaky members** are quarantined within 24 h with an owner and a follow-up, never silently retried
  (C-9.3).

## 8. The screen-reader script and the budgets

### 8.1 The screen-reader script

E42-Q05 runs this with a screen reader (NVDA on Windows, VoiceOver on macOS) and the keyboard only. It
follows D02's keyboard model (D18) and each frame's keyboard notes; E42-D06's hand-off pack replaces it when
it lands. A step passes when it completes by keyboard alone, each announcement is made once, and focus is
never lost.

1. **The shell (D1):** the landmarks read in order: top bar, navigation, content, right rail, status bar.
   The admin band is the first region in the content, "Admin area". A route change is announced, for
   example "Admin · Users".
2. **The gate (D2):** focus starts on the password field and Tab stays inside the dialog. A failure is
   announced assertively once, and `Esc` cancels.
3. **The users grid (D8):** one tab stop into the grid; the arrow keys move between rows and cells; Enter
   opens the user; Shift+F10 opens the row menu; sortable headers announce their sort.
4. **A destructive dialog (D3):** Cancel is the first tab stop; the consequences read as a list; Enter in a
   typed-token field never confirms.
5. **View-as (D10):** the banner is read first and Exit is the first tab stop; the countdown is not read on
   each tick.
6. **The audit log (D11):** the filter bar, then the grid; Enter opens the drawer, and `Esc` returns focus to
   the row it came from.
7. **Health (D12):** each tile is a labelled region. A component going `degraded` or `down` is announced
   assertively once, and its recovery politely once.
8. **Flags (D13):** each toggle is labelled with the flag's description, and its value is a word.
9. **Countdowns (D16):** a polite announcement at 5 minutes left, and an assertive one at 1 minute and at
   expiry; never on every tick.

### 8.2 The per-screen budgets

| Screen  | Budget                                                               | Source                | Measured by                       |
| ------- | -------------------------------------------------------------------- | --------------------- | --------------------------------- |
| SCR-120 | Each tile in ≤800 ms, with or without a slow subsystem               | SCR-120               | E42-Q03                           |
| SCR-135 | A filter round trip ≤400 ms, and the first page ≤2 s, over 10 M rows | SCR-135, US-ADMIN-009 | E42-K01 (the query plan), E42-Q03 |
| SCR-136 | One record in ≤300 ms                                                | SCR-136               | E42-Q03                           |
| SCR-143 | ≤1 % added server load, and ≤2 ms scripting per frame                | US-ADMIN-011, SCR-143 | E42-Q03                           |
| SCR-149 | The step-up in ≤400 ms                                               | SCR-149               | E42-Q03                           |

## 9. Questions

Each is a question for the owner of the source it names (a story, the contract or the server), not a
guess.

- **Q-1:** E42-S01 and SCR-149 describe a 15-minute admin token. The server has per-action step-up instead,
  with a 5-minute grace per action class, and records an entry without refusing it. The web router gates
  `/admin/**` on its own client-side freshness window of 30 minutes (D02 §1 and A-14). Whether an admin
  window gets a server half is the open decision D8 of E42-X01 (E42-T06, #1085; D02's OQ-14). Until it is
  settled admin reads are un-gated server-side (AC-ADM-30), and a read that works on a stale step-up is a
  finding only under D8's option (a). AD-S01-01 asserts the gate on a stale step-up without fixing the
  threshold, and AD-S01-N01 tests the server's grace. E42-S01 also expects `admin.session_elevated` and
  `admin.access_denied`, which `audit/actions.py` does not register: the step-up writes
  `auth.step_up_granted`, and the admin-area guard writes `admin.area_entered`. D02 names SCR-149's record
  `auth.session_unlocked`; the server writes `auth.step_up_granted`, which the cases expect.
- **Q-2:** E42-S02 invites "with role manager" and expects `users.create` (and `user.invited`,
  `user.invite_revoked`) with the assigned roles. D02 D9 invites with no role picker, the manager grant
  being a second step, and D02 §5 marks an invite `users.create` plus `users.invited`. The server writes
  only `users.invited` for an invite (`api/invites.py`). AD-S02-01 follows D9 and the server: `users.invited`,
  then `roles.grant`.
- **Q-3:** E42-S02 expects `409 conflict`, audited as a denied action, for the only owner's own Disable or
  Delete. The server refuses a self-target first, `403 forbidden` with reason `self_target` (SR-055, audited
  `rbac.denied`), once the step-up gate has passed; the `409` is the last _active_ owner's refusal from
  another owner (`04` §5.7 D6), and on the disable path it is deliberately unaudited (the user-lifecycle
  model's UL1-D1). AD-S02-04 asserts a refusal with nothing changed, and both statuses need a case once
  this is settled.
- **Q-4:** E42-S03 names the limit change's action `risk.limits_changed`, which the registry does not hold
  (it has `risk.freeze_manager` and `risk.unfreeze_manager`), and the per-user caps override has no admin
  endpoint on `main` (D02 §6.4, §13.1 and O-G). AD-S03-04 is blocked until both exist.
- **Q-5:** E42-S04 expects `audit.exported` for an export. The registry has `admin.audit_export`, which the
  contract writes for the request and, with reason `downloaded`, for the download. AD-S04-05 expects those.
- **Q-6:** E42-S05 requires a typed confirmation to enter maintenance mode. D02 D15 drops it, since it has no
  server counterpart, and leaves the choice open (O-E). AD-S05-05 asserts the rungs and not a typed word.
- **Q-7:** E42-S08's latch acknowledgement has no operation in `22` and no registered audit action. AD-S08-02
  expects a record with the owner's identity, under the action the story's contract slice registers.
- **Q-8:** E42-S07 does not name the recorder purge's action. The registry has `retention.purge` and
  `data.deleted`. AD-S07-07 expects the one the purge's operation documents.
- **Q-9:** E42-S05's examples use a liquidation-heat estimate flag, and its scope asks for flags of every kind
  (boolean, percentage and variant). The flag catalogue (`admin/flags/catalogue.py`, `21` §10.7) holds no
  such flag and only boolean ones, and a flag outside it cannot be written. AD-S05-01 uses a catalogued UI
  flag, and the fixtures seed the catalogued flags; a percentage or variant case waits for a catalogued
  flag of that kind.
- **Q-10:** E42-S02 expects a deleted user under a "Disabled/Deleted" filter. A user has no deleted status
  (22 `UserStatus`), and D02 lists disabled users in the default view. AD-S02-03 asserts neither until the
  story settles it. E42-S02 also implies an immediate anonymised reference; the contract anonymises it 90
  days later, which AD-S02-03 follows.
- **Q-11:** E42-S03 expects the audit entry to record the owner's choice when unbinding with open positions.
  The server records a constant `positions_decision: "leave"`. AD-S03-03 expects the field and leaves its
  value to the story.
- **Q-12:** E42-S03 expects `admin.view_as_started` "at high severity". The contract and the server write it
  at `warning`, the audit severity scale having no "high" (22 `startViewAs`; D02 §6.6). AD-S03-05 expects
  `warning`.
- **Q-13:** `setUserRoles` takes no `If-Match`, so of two owners' role saves the later one wins silently.
  E42-S03's concurrent-edit scenario is met only for `PATCH /users/{userId}` (AD-S03-06).
- **Q-14:** a grant revoked mid-stream ends the manager's subscriptions within 2 s by `22`
  `setUserAccountAccess`, but within 1 s by `23` §16.4's test matrix. AD-X-02 asserts 2 s until they agree.
- **Q-15:** `22` `login` makes every sign-in failure, a disabled user's included, the uniform
  `401 unauthenticated`. The server answers a disabled user's correct password `403` "Account disabled"
  (`login_service.py`, a documented trade-off). AD-S02-N04 asserts the refusal, no session and
  `auth.login_failed`, not the status.
- **Q-16:** `setUserAccountAccess` takes no `If-Match` and replaces the whole grant set (`22`; E42-S03's
  technical notes), so a page loaded before another owner's revoke sends the account back and re-grants
  it, with its freeze state and caps, and nothing refuses or flags it. `getUser`'s `ETag` covers the
  `User` representation, which holds no grants, and the user-lifecycle model's account-access threats
  (UL2) name no such race. AD-S03-N05 records the end state and asks the story whether the save takes a
  precondition, as the `PATCH` does.
- **Q-17:** E42-S02's scope has the invite carry initial `account_access` grants, and `22`'s `createUser`
  example carries a `trade` grant. SR-027 (a new user has no grants), D02 D9 (AM-4) and the server
  (`InviteCreateRequest`: `account_access` must be empty, else `422` and `users.invite_refused`) refuse it.
  AD-S02-N07 follows SR-027 and the server. Separately, SR-025 lists creating a user among the step-up
  actions and the server gates `POST /users` on class `users`, but `22`'s `createUser` names no class (D02
  §13.2: a contract gap, routed to #889 and #2701). AD-S02-N06 asserts that gate. The server also gates
  re-issue and revoke (`POST` and `DELETE /users/{userId}/invite`) on `users`, which D02 §5 draws with no
  step-up, so no case asserts either until this is settled.
