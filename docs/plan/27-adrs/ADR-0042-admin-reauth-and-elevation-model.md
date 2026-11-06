# ADR-0042 — Admin re-authentication and elevation: per-action step-up stays the model, there is no admin window (D8, #1085)

- Status: **accepted**. D8 was ruled 2026-10-29 by main-orchestrator under the Owner's delegation (#2701 ledger 2,
  comment 6493096777, row 12; the Owner may revoke there): keep per-action step-up, and accept AD-E01 with a review on
  2027-02-25. Decisions 1, 2 and 6 record rows 12 and 48 of that ledger. Decisions 3 to 5 were recommended on the
  ticket's BQ list (BQ-2) and agreed in the #1085 BQ ruling (comment 6602836897, 2026-11-03), which also named the
  owners of the gap rows (the contract against the code, below). Where this record only recommends, it says so
  (decision 6's reopening path). E42-S01 (#5287, #5330) built the model before the record existed, so every statement
  below describes `main`.
- Date: 2026-11-03
- Deciders: Owner (`@basiltt`) through main-orchestrator (the delegation on #2701: ledger 2 rows 12 and 48, and the
  #1085 BQ ruling); the Security engineer through the `security-review` label (C-10.2); the architect as CODEOWNER of
  `docs/plan/`. Author: virtarix-worker-4.
- Consulted: `docs/security/threat-models/e42-admin.md` (§1.3, §3.3, §4.1 AD-S05, §4.6 AD-E01 and AD-E12, §5.2 D2 and
  D8, §11 SR-E42-12, §13.2); the E42-D01 research (`docs/design/research/e42-admin.md`: F-D5, CR-6, AD-6); E42-D02 (D2,
  A-1, A-14); E42-D03 (Q1, D5, §4, §5, CG-1, CG-2); ADR-0010 (implementation notes, D-2); ADR-0020 decision 6; ADR-0016
  (B16); `22` `authStepUp`; #2701 ledger 2 rows 12, 47 and 48; the #1085 BQ list and ruling (comments 6599561303 and
  6602836897).
- Numbering note: the ticket and the threat model plan ADR-0022 for this record, which is the hot-tier record;
  ADR-0023 is the exchange adapter; 0031 is reserved by E45-K01; 0040 went to E28-K01 (coordinator, 2026-10-25 00:41Z);
  and 0041 is the backup engine's (#3319, PR #5474, open when this was written). So this record takes 0042, and the
  flags record takes 0043, as the BQ ruling assigned them (BQ-1): if another record takes either number first, the PR
  that loses the race renumbers at its push. E42-D03 CG-1 expected 0040.
- Related: #1085 (E42-T06), #890 (E42-X01), #1022 (E42-S01), #886 (E42-D03), #964, #2701, #4673, #2304, #2725, #2101;
  RSK-074; AD-E01, AD-E12, AD-F06, AD-S05, AD-T10; SR-E42-12. ADR-0043 records the other decision the ticket names.
- Evidence: every `file:line` holds on `main` at `d023df0f6`. Module paths are under `services/api/candleviewer/`.
  `22` is `docs/plan/22-api-openapi.yaml`: an operation is cited by its operationId and a quoted heading, and `22:n` is
  a line of its `info` description.

## Context and problem statement

The ticket and `14` SCR-149 promised an admin area behind a re-authentication no older than 15 minutes: the owner-only
router answering 404 to others and the API 403, a server-issued admin token, and a pending-save queue for an edit that
outlives the token. The server does less, and deliberately. Every dangerous action asks for a step-up of its own class
(SR-025). `admin.area_entered` records every write and refusal, and the first allowed read of each session, route,
address and step-up window, with a count of the rest (#5331); it carries `reauth_age_s` and never refuses on it
(`admin/http.py:19-34`).

Three texts disagreed about the window. `14` and `15` said at most 15 minutes, with password and TOTP; `12` §4 said a
30-minute entry TTL, a 15-minute threshold for destructive actions and "TOTP code (not password)"; `11` US-ONB-005 and
the server said a 5-minute grace per action class. The 30 minutes were not only prose. Until 2026-10-26 the web client
held a window of its own: `bootstrap.ts` mapped `me.session.elevated_until` into `elevatedAt`, and `rbac.ts` called
the session fresh for `STEP_UP_TTL_MS`, 30 minutes, wider than any server grace. #4673 (`1bd181105`) removed both, and
the client now asks for no step-up at the door. `Me.session.elevated_until` is the latest live grace of any class
(`22` `getMe`: "the latest live step-up grace expiry on the session"), so after a reload the shell cannot tell which
class it belongs to (E42-D03 CG-2).

The question D8 put: does the admin area get an elevation of its own, on top of per-class step-up? AD-E01 rides on the
answer: if not, a live Owner session reads user records, the raw audit log with addresses, health and capacity with no
fresh factor (Medium if accepted, the threat model's own rating).

Out of scope: `X-Reauth-Password` on `authMfaDeleteMethod`, a separate self-service mechanism; the session-rotation
claim of `22` `authStepUp` ("Session rotation (SR-013)"; decision 1 claims none).

## Decision drivers

1. **Blast radius of a stolen or unattended Owner session** (AD-S05), weighed against friction paid by one person, the
   only Owner (`10` P1 and P4).
2. **One session model.** One B16 elevation region and one grace per class. A second clock beside it is a second thing
   to keep equal, and to attack (C-2.21: the chart records, synchronous code enforces).
3. **Enforcement on the server only** (C-12.4, SR-182, AD-T10); a screen shows what the server said.
4. **One audit record per dangerous action** (C-2.9), each tied to its challenge.
5. **Few time limits for the user to track.** The research found two gates, three durations and one word (F-D5, CR-6:
   the Owner cannot predict when a code will be asked); a countdown is a time limit (E42-D03 D5, WCAG 2.2.1).
6. **Nothing the client can get wrong:** no window constant, no mapped expiry, no held elevation.

## Considered options

Lettered as the threat model's D8 letters them (§5.2), with two more.

- **(a)** A 15-minute server-enforced admin window (the ticket's original).
- **(b)** Per-action step-up only: what `main` does.
- **(c)** Session-long elevation.
- **(d)** (b) plus step-up read classes for the PII and raw-audit reads.

## Decision outcome

Option (b), with six decisions.

1. **Per-action step-up is the admin elevation model.** A dangerous admin action answers `403 step_up_required` until
   the session holds a live step-up of its class. There is no admin window, no admin token, no `admin` action class,
   no `reauth_expires_at` in the contract and no `admin.session_elevated` record, and SCR-149 is retired. The guard's
   `admin.area_entered` keeps `reauth_age_s` as observability and never gates: `test_admin_http.py:288` pins it. The
   no-grace classes in the code are `live_enablement`, `killswitch`, `backups`, `recorder_purge` and `accounts`
   (`auth/step_up.py:119`); `22` `authStepUp` also names `sl_loosen`, ahead of the code, and ledger row 48 moves
   `risk_caps` there before the first live key (the contract against the code, below). The re-auth factor is the password plus the current TOTP code, checked
   together (`_verify_both`), and `ArmToken` is unchanged. An idle lock voids every grace window, one-shot grant and
   pending challenge of the session from the lock itself; a password-only unlock restores none of them
   (`SessionService.unlock`), so the next dangerous action answers `403 step_up_required` until a fresh password and
   TOTP code. The windows of the session
   model, as a map (`22` `authStepUp` and `auth/step_up.py` win where this table differs):

   | Window                    | Value                                               | Where                                          |
   | ------------------------- | --------------------------------------------------- | ---------------------------------------------- |
   | Grace, per grace class    | 5 minutes                                           | `auth/step_up.py:88`                           |
   | Grant, per no-grace class | 60 seconds, bound to the challenged request, once   | `auth/step_up.py:119`, `:133`                  |
   | Challenge                 | 5 minutes, one live per session                     | `CHALLENGE_WINDOW`; `22` `authStepUp`          |
   | Wrong codes               | 3, then read-only for 5 minutes                     | `auth/step_up.py:90`, `:92`                    |
   | Idle lock                 | 15 minutes by default (5 to 60); clears every grant | ADR-0010 notes; `22` `authStepUp`, "Idle lock" |
   | Session; access token     | 12 hours; 12 minutes                                | ADR-0010 notes; ADR-0020                       |
   | View-as                   | 30 minutes, never extended                          | `22` view-as, "Expiry and the hold"            |
   | Admin window              | none                                                | this record                                    |

2. **One text wins.** The step-up rule is `22` `authStepUp` (it already says "the ticket value of 5 minutes
   supersedes the earlier 15") together with `auth/step_up.py` and `24` §15.2. US-ONB-005's NFR (a 5-minute grace per
   action class, none for live enablement and kill-switch release) is the same rule in story form and stands. The
   texts that said otherwise were amended with this record, except `10` §0 and the E42 test plan
   (`docs/qa/e42-admin-test-plan.md`), which E42-T06's catalogue sweep amends, and the design specs that still
   describe an admin token or a 15- or 30-minute window (E28-D02, E16-D04, E08-D09, E10-D03, E09-D09 and the E42-D03
   hand-off), which are the design lane's. Amended here: `14` SCR-149 and SCR-154; `15` CMP-035, CMP-087 and CMP-098;
   `12` §4 and M-020; `11` US-ONB-005; `13` flows F2 and F18; `18`; `24` §15.2, §16.1 (`AuthConfig`) and §16.3;
   ADR-0020 decision 6 (Amendment 2); the E42 threat model, `04` §5.15, §7.2.0 and RR-17, `32` RSK-074 and RSK-021,
   and the abuse case AC-ADM-30.
3. **The client computes no window.** Every time the shell shows is a server-issued expiry (`elevated_until`,
   `step_up_expires_at`, `challenge_expires_at`, a view-as `expires_at`) counted against the server's clock, never a
   client TTL, and nothing is shown where the server states nothing (CG-2). The challenge's offset comes from the
   response's `Date` header (`apps/web/src/features/stepUp/challenge.ts:33-53`). The code says it in three places:
   `rbac.ts:38` (entering `/admin/**` asks for no step-up), `StepUpChallengeGate.tsx:199` ("the client keeps no copy of
   it") and `packages/ui/src/components/AdminLayout.tsx:64` (the grace's expiry is "counted, never recomputed").
   `noUnchallengedStepUp.test.tsx` drives every admin route and fails a step-up sent without a server-issued challenge.
4. **Non-disclosure.** The router's 404 (SCR-155 for any non-owner: no admin chunk is loaded and no admin request is
   sent, `lazyBoundary.test.tsx`, `admin-shell.spec.ts`) is cosmetic. The API's 403 is the control, and it writes the
   write-ahead `admin.area_entered` with outcome `denied` and no second `rbac.denied` (`admin/http.py:9-13`). Route
   existence is public through the contract (AD-I01, accepted Low).
5. **The held request replaces the pending-save queue.** SCR-006 holds the refused request, re-sends it once and
   unchanged after a matching `200`, and drops it, without logging the user out, on cancel, challenge expiry, read-only,
   idle lock or session end (`22` `authStepUp`, "Holding the refused request"; `stepUpInShell.test.tsx`). No queue
   exists in the client or is needed.
6. **Residuals and review dates.** AD-E01 is accepted: admin reads need no fresh re-auth (Medium; owner: the Owner;
   review 2027-02-25). AD-E12 stays accepted with `users` and `flags` on the 5-minute grace (ledger row 48; review
   2027-02-04) and is decided again only if E42-X02 adopts D2's band-raise (threat model §5.2). `risk_caps` moves to
   no-grace before the first live key (row 48), which is not done yet (the gap rows below). Reopen on: the 2027-02-25
   review; a stolen-session read in the `admin.area_entered` or `admin.audit_read` trail; an E43 pen-test finding on
   admin reads; or the Owner. This record recommends option (d) first, contract-first; the reopening is the Owner's.

## The contract against the code

Two step-up classes are not yet where the rulings put them in `NO_GRACE_ACTION_CLASSES` (`auth/step_up.py:119`). Each
is a gap row: ruled on #2701 ledger 2, and given its owner by the #1085 BQ ruling, which opens no new issue for either.

| Class       | `22` `authStepUp` | The code        | Ruling                                                 | Owner                                                          |
| ----------- | ----------------- | --------------- | ------------------------------------------------------ | -------------------------------------------------------------- |
| `sl_loosen` | no-grace          | not a class yet | no-grace (ledger row 47)                               | E29-T07, which adds it to both class sets and to B16's mirror  |
| `risk_caps` | grace             | grace           | no-grace before the first live key, R4 (ledger row 48) | E39 (risk): an E39 story's BQ list picks it up, contract first |

## The SR-E42-12 link

| SR-E42-12 asks for                             | Answered by                                       |
| ---------------------------------------------- | ------------------------------------------------- |
| An ADR decides the admin elevation model       | Decision 1 and the options above                  |
| Per-action step-up, with the catalogue amended | Decision 2 and the texts it lists                 |
| And the residual accepted                      | Decision 6 (AD-E01; AD-E12 as the ledger left it) |

This record also answers AD-F06 (the window was never a server gate: decision 1), AD-T10 (the client computes no
window and the server reads no client elevation value: decision 3) and RSK-074 (accepted, decision 6). It re-rates
nothing: re-rating is the Security engineer's (threat model §1.4).

## Consequences

Good:

- One elevation model, enforced on the server and recorded per action; the shell holds no admin state and counts no
  clock of its own.
- A stolen session's reach is the set of actions whose grace it happens to hold, each written as
  `auth.step_up_grace_used`, and every no-grace action needs a fresh code bound to its request.

Bad:

- Admin reads need no fresh re-auth (AD-E01, accepted).
- A long admin session meets several prompts: a grace class lapses 5 minutes after its step-up, and a no-grace class
  asks every time. The grace bounds this.
- The shell's grace line waits for the contract: `Me` carries the latest grace of any class, not the class (CG-2).

Operational:

- No Owner-editable window exists. `24`'s `AuthConfig.elevated_minutes` and its "Step-up (elevated) window" knob are
  retired (`24` §19.139): no such configuration is in the code. A window change is a code change that moves `GRACE_WINDOW` and the B16
  binding together (`test_b16.py:226` pins them) and amends this record.

## Follow-ups owned elsewhere

None is E42-T06's work; each is contract-first (C-6.1) where it touches a shared surface.

- **`risk_caps` to no-grace** (row 48, before the first live key, R4): owner E39 (risk), as the #1085 BQ ruling
  names it, with no new issue; an E39 story's BQ list picks it up. It touches `auth/step_up.py:119`, the B16 binding,
  the `authStepUp` class text and `24` §15.2, contract first. E39's threat model (G-3) asks for a neighbouring class
  move for `overrideRiskLockout`; the two belong together.
- **`sl_loosen`** (row 47): E29-T07 adds it to both class sets and to B16's mirror when it mounts the routes.
- **CG-2:** the class of the latest grace on the session contract (E09).
- **An optional web test** that `apps/web/src` holds no elevation-window constant. Today `noUnchallengedStepUp.test.tsx`
  pins only that nothing is sent without a challenge, and the comment at `rbac.ts:41-42` still promises that SCR-149's
  "re-auth on first entry" returns once its contract lands. D8 retires it: a comment-only follow-up for the web lane.
- **#2101 (tracked, not new):** the contract says a step-up rotates the session and returns `tokens` (`22`
  `authStepUp`, "Session rotation (SR-013)"); the code's `200` carries neither (`api/step_up.py:954-965`). Decision 1
  claims no rotation.
- **No alert reads `cv_maintenance_mode`** (E04 or E42; PR 2's maintenance runbook names it too).

## Why not the alternatives

**(a) A 15-minute admin window.** It reads well and costs a second session model. It needs `reauth_expires_at` on a
contract surface (`Me` or a new route), an `admin` class or a special case in the guard, `admin.session_elevated`
registered (AD-F17), SCR-149 with a countdown and the rule for an expiry in the middle of an edit (CG-1), and it flips
the pin test. The grace already bounds what a stolen session writes; the window would bound only reads, at the price of
a second clock beside B16's elevation region and one more place for a client to keep time (AD-T10).

**(c) Session-long elevation.** The fewest prompts and the widest blast radius: one step-up would cover every later
write and read of a stolen or unattended session (AD-S05). It contradicts SR-025's per-class grace and the no-grace
classes, and nothing in the product asks for it.

**(d) Read classes.** A step-up class for user records and the raw audit log would close AD-E01 without a window. It
adds a class to the contract and to B16, and a prompt to every list screen, to defend reads the Owner makes all day.
It is not adopted. This record recommends it as the first move if the decision is reopened (decision 6): contract
first, then the service, then the shell. The reopening is the Owner's.

## Validation

- `services/api/tests/unit/admin/test_admin_http.py`: `test_a_missing_or_stale_step_up_never_refuses_the_route` (the
  window is observability only), `test_reauth_age_s_is_measured_against_the_injected_clock_only`.
- `tests/unit/api/test_dangerous_route_registry.py` (every mounted dangerous route is gated or allow-listed) and
  `test_step_up_flags_class.py` (the grace placement follows the contract text).
- `tests/xstate_contract/test_b16.py:219`: `test_b16_policy_constants_match_service` pins the grace, the strike cap and
  the read-only window to the service.
- `tests/contract/test_step_up_contract.py` and `test_step_up_challenge_contract.py`: the `authStepUp` contract.
- `apps/web/test/features/stepUp/noUnchallengedStepUp.test.tsx`, `test/features/admin/shell/stepUpInShell.test.tsx`
  and `lazyBoundary.test.tsx`; `apps/web/e2e/admin/admin-shell.spec.ts`.

## References

- `docs/security/threat-models/e42-admin.md` (D8, AD-E01, AD-E12, AD-F06, SR-E42-12); `04-security-program.md` §5.15
  and RR-17; `32-risk-register.md` RSK-074.
- `22-api-openapi.yaml` `authStepUp` and `getMe`; `24-internal-schemas.md` §15.2; `21-database-schema.md` §3.1.4.
- #2701 ledger 2 (comment 6493096777) rows 12, 47 and 48; the #1085 BQ ruling (comment 6602836897).
- ADR-0010 (implementation notes), ADR-0016 (B16), ADR-0020 (Amendment 2), ADR-0043.
- `docs/design/E42/E42-D02.md` (D2, A-1, A-14), `docs/design/E42/E42-D03.md` (Q1, §4, §5, CG-1, CG-2).
