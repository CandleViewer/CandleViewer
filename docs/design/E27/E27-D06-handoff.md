# E27-D06 — Engineering hand-off pack: accounts, sub-accounts and the API-key vault

**Ticket:** E27-D06 (#819) · **Epic:** E27 · **Kind:** design hand-off pack and its committed index, text-first,
pre-stage (`Refs #819`) · **Status:** Draft v0.2. The BQ list (BQ-01 … BQ-10) is ruled on #819 (3 Nov): BQ-01, 03,
05, 07 and 08 agreed; BQ-04, 06, 09 and 10 amended; BQ-02 disagreed. Every ruling is folded here (§16.1). **Split
(BQ-02, ruled; C-4.8):** PR 1a carries the copy deck and the tool, PR 1b this pack and the pins, each `Refs #819` with a
`Partial:` line; PR 2 applies §14's rows this ticket owns and carries the closing line. One `Partial:` reason stands
until then: E27-D04's seven boards are PENDING (`D05`:480). **Unblocks:** E27-S01 … E27-S05 (#895–#899): no `apps/web` work on SCR-125 … SCR-129 or SCR-079 starts until
this ticket is Done (`02`:53; `16`:721).

**What this file is.** The single pack the ticket asks for. Every screen links to its frames, its copy-deck section and
its component entries (§3), so the pointer survives a reorganised design file. It adds no design decision of its own
beyond the rows stamped PROPOSED; everything else is cited from the merged parents and never restated where a cite will
do. The copy deck as data is [E27-D06-copy-deck.jsonl](E27-D06-copy-deck.jsonl): one header line, then one row per
string. `docs/design/_tools/e27_d06_handoff_audit.py` gates this file, the deck and the pins file (§17).

**Inputs pinned.** Base `origin/main` `a7d659a5be`<!--=SHA:BASE-->. Every `file`:line below is read there with
`git show`. The blockers: E27-D03 (#816) Done; E27-D04 (#817) PR 1 merged (#5001), its seven boards PENDING in its PR 2;
E27-D05 (#818) merged (#5461), open until #817 closes. At #817's closing merge every `D04` cite is re-read by content
and re-pinned (§17).

**Key.** `NN`:line = `docs/plan/NN-*.md`; `22`:line = `docs/plan/22-api-openapi.yaml`. `D01` =
`docs/design/research/e27-key-custody.md`; `D02` … `D05` =
`docs/design/E27/E27-D02.md` … `E27-D05.md`; `D03H` = `E27-D03-handoff.md`. `TM` =
`docs/security/threat-models/E27-accounts.md`. `CAL` = `docs/plan/backlog/_tools/calendar_cv.py`. `T` = the ticket
(#819; its twin in `docs/plan/backlog/E27.json`). `deck` = the copy deck, its rows named by id. M-n are D04's motion
rows; FO-, KS-, LR-, SR- and F- rows are D05's; NR-n are §2's rules; A-n are §14's copy-ready rows.

## Acceptance-criteria and DoD trace (#819)

| Ticket item                                                                | Where                                   | Status                                                                                                                                                                                                                           |
| -------------------------------------------------------------------------- | --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AC The pack is self-sufficient (SCR-126 built from the pack alone)         | §3–§9; §13's dry run                    | text done; PENDING: the agent dry run, which replaces the session and is labelled `(heuristic)` (BQ-04, ruled), owner E27-D06, logged in §13.2 before READY; AC 1 stays open until the stories count the questions               |
| AC Every string is in the copy deck                                        | §9 and the deck (G-DECK, G-COVER)       | done: every E27-D03 §12 id once, checked by id, never by row position (G-COVER), plus the lifts                                                                                                                                  |
| AC Sign-offs complete before engineering starts                            | §15, §12                                | the `02`:53 waiver is recorded for #895's and #898's started server slices (BQ-06, ruled; §12); C-10.3 gates every UI merge on this ticket; the sign-offs PENDING, owner approval pending                                        |
| AC Components come from the library                                        | §5; the library edits ride PR 2 (BQ-02) | text done; the `15` entries are PENDING in PR 2                                                                                                                                                                                  |
| AC A gap found during implementation                                       | §13.3                                   | the protocol is written                                                                                                                                                                                                          |
| Scope: per screen frames, tokens, components, data, RBAC, audit, analytics | §3, §4, §6, §10                         | done                                                                                                                                                                                                                             |
| Scope: the final copy deck, keyed by screen and element                    | §9; the deck                            | done                                                                                                                                                                                                                             |
| Scope: CMP-175, CMP-176 and CMP-034 published with their Storybook lists   | §5                                      | lists done; publication PENDING (BQ-02)                                                                                                                                                                                          |
| Scope: focus-order maps, live-region plan and screen-reader scripts (D05)  | §8                                      | done by reference; the F rows lifted                                                                                                                                                                                             |
| Scope: motion with its reduced-motion equivalents (D04)                    | §7                                      | done by reference; D04's boards PENDING                                                                                                                                                                                          |
| Scope: the non-negotiable visual rules                                     | §2                                      | done                                                                                                                                                                                                                             |
| Scope: the 45-minute walkthrough, questions answered in the pack           | §13                                     | the agent dry run replaces the session (BQ-04, ruled); the owner-walkthrough checklist is posted on #819 in E38-D06 §14's form                                                                                                   |
| Scope: the sign-off record (CDO or delegate, accessibility, Security)      | §15                                     | pending                                                                                                                                                                                                                          |
| DoD frames in dark and light and three densities                           | §3; §16 D-3                             | partial: SCR-127 is dark and comfortable only, light by token with no twin (`D03`:1279); SCR-019 is text only, not drawn (§3); two densities, not three (D-3); E27-D04's seven boards PENDING (`D05`:480), the `Partial:` reason |
| DoD contributions merged into the library, zero one-off components         | §5; §14 A-4                             | PENDING: the `15` entries, owner E27-D06 in PR 2; no one-off exists (`D03`:2655); the `02`:56 checklists for CMP-175, CMP-176 and CMP-034 are §5.1's                                                                             |
| DoD accessibility annotations with measured contrast                       | §8                                      | partial: focus order, roles and live regions by reference; contrast measured in D05 §11; G-08's families PENDING, owner E27-D06 in PR 2 (§8.3)                                                                                   |
| DoD `14` sign-off checklists ticked item by item                           | §15                                     | PENDING: the lane ticks each screen's checklist item by item in the review comment (SCR-127 `14`:2705, SCR-129 `14`:2729 and the rest), and the orchestrator confirms at approval (DoD 4)                                        |
| DoD signed off by the CDO or delegate, plus Security for key-state frames  | §15                                     | PENDING: the owner (#2701); the Security row after the security lens                                                                                                                                                             |
| DoD Done two sprints before the consuming story starts                     | §12                                     | PENDING: Done by §12's date, owner E27-D06; for #895 and #898 the `02`:53 waiver of §12 (BQ-06)                                                                                                                                  |
| DoD pack linked from every consuming engineering ticket                    | §12                                     | PENDING: one comment on each of #895–#899 at PR 1b's merge; SCR-016 step 3 linked from #895 and #896 (BQ-10)                                                                                                                     |

## 0. Status and evidence

Text-first, pre-staged on the blocker. No board is drawn here: the frames are E27-D03's ten boards (drawn and exported,
`D03`:192) and E27-D04's seven motion boards (PENDING, `D04`:198). The deck is generated from E27-D03 §12 at the base
and every row is checked against its cited line by the tool, so a merged string cannot drift between the parent and the
pack. Nothing here was measured on built screens or with people; every walkthrough or dry-run row says so.

## 1. Locked inputs (cited, never re-decided)

| Input                               | File                                      | What the pack takes from it                                  |
| ----------------------------------- | ----------------------------------------- | ------------------------------------------------------------ |
| E27-D01 key-custody research        | `docs/design/research/e27-key-custody.md` | the CD, CP, AD and RA rows, through D02 and D03              |
| E27-D02 wireframes                  | `D02`                                     | the 78 frames, the state inventory (`D02`:1011), the events  |
| E27-D03 hi-fi and the contributions | `D03`, `D03H`                             | boards, tokens, the deck (`D03`:2046), the `16` §11.4 blocks |
| E27-D04 motion                      | `D04`                                     | M-1 … M-11 (`D04`:55) and the anti-motion rules (`D04`:110)  |
| E27-D05 accessibility review        | `D05`                                     | FO, KS, LR, SR and F rows; the lifts in §8.3                 |
| The E27 threat model                | `TM`                                      | the security notes behind §2                                 |

## 2. The non-negotiable visual rules (security; stated once)

These four rules bind every E27 surface and every story. A builder who meets a case they do not cover stops and raises
a design ticket (§13.3); nothing here may be traded for layout, a flag or a test shortcut. Each rule names the deck
rows that carry it, and the tool checks those rows (G-RULES).

| NR   | Rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Carried by (deck ids)                                                                                                                   |
| ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| NR-1 | **No control anywhere shows a secret.** No show, hide, unmask, peek, copy-out or timed display for an API key or secret, on any screen, in any role, in any state. CMP-034 renders the server's masked id only (`D03`:657); key and secret entry is CMP-201's `writeOnly` variant, with no toggle in the DOM, autocomplete off, cleared on leave (`D03`:930). A string may say a secret "can't be shown", never offer to.                                                                                                                                                   | `e27.cmp034.description`, `e27.scr126.saved`, `e27.scr126.edit.write_only`, `e27.scr128.policy.write_only`                              |
| NR-2 | **The withdrawal verdict is always explicit.** It is a word, a glyph and a time, never a colour or an absent chip: "OFF" only beside its verified time, and a failed, stale or unread check is negated in words (`D03`:2062; `14`:2658). The withdrawal-detected state is a blocking error, not a warning (`14`:2664).                                                                                                                                                                                                                                                      | `e27.scr125.verdict.dated`, `e27.scr125.verdict.overdue`, `e27.cmp175.verified`, `e27.scr079.key.statements`                            |
| NR-3 | **No number without its freshness.** Every figure carries its unit, and its block carries "as of" or "stale since" with a UTC time; a stale value keeps full contrast (`D03`:1542; `D04`:103).                                                                                                                                                                                                                                                                                                                                                                              | `e27.shell.meta`, `e27.scr079.balances.caption`, `e27.scr079.stale`, `e27.scr079.announce.stale`                                        |
| NR-4 | **Destructive actions follow the step-up ladder: typed label plus step-up at rung 3.** Disable, delete, revoking the last key and the rotation switch are rung 3: the typed account label, a fresh `keys` step-up, focus on Cancel, the confirm absent until the consequence summary loads (`14`:2724; `14`:2706). OQ-9 and OQ-10 (RULED, `D01`:611, :612) narrow `T`'s "typed confirmation plus step-up": rotation is rung 3 (OQ-10), and revoking a key that is not the last is rung 1 with the step-up and no typed label (OQ-9), as drawn in D03 frame 49 (`D03`:1510). | `e27.scr129.typed`, `e27.scr129.hint.typed`, `e27.scr127.typed`, `e27.scr127.hint.typed`, `e27.scr125.menu.ask.label`, `e27.shared.ask` |

The tool refuses key material in any field of any deck row, and any secret-bearing string that offers to show, copy out
or unmask a key or secret (G-SECRET); any "shown" not negated, any withdrawal "OFF" without "verified", and a rung-3
action on the rung-1 ask (G-RULES). The motion half of the danger rules is D04's (`D04`:110): destructive
confirmations get no decorative animation, withdrawal-detected never fades in, and nothing about a blocking error is
soft.

## 3. The committed index (screen → frames, copy, components)

Boards are on the page `E27-D03 Accounts and key vault hi-fi` (page id `2cfb7e8e-8725-806d-8008-daee3d38d63c`,
`D03`:194), exported to `docs/design/E27/img/E27-D03-NN-<slug>.png` (`D03`:247). The motion boards are on E27-D04's page
once its PR 2 lands (`D04`:198). A screen's frames are D02's names (`SCR-nnn / <state>`), so a frame is found by name on
any board.

| Screen  | Spec sections (D02 · D03) | Boards (D03) | Deck screen | Components (`14` line, plus what D03 binds)                                                          | Consumer |
| ------- | ------------------------- | ------------ | ----------- | ---------------------------------------------------------------------------------------------------- | -------- |
| SCR-125 | `D02`:398 · `D03`:989     | 04, 05, 01   | SCR-125     | CMP-001, CMP-011, CMP-049, CMP-055, CMP-087, CMP-175, CMP-176 (`14`:2662); CMP-178, CMP-028          | E27-S01  |
| SCR-126 | `D02`:505 · `D03`:1168    | 06, 03       | SCR-126     | CMP-027, CMP-034, CMP-040, CMP-065, CMP-087, CMP-093, CMP-175 (`14`:2690); CMP-201, CMP-203, CMP-033 | E27-S02  |
| SCR-127 | `D02`:607 · `D03`:1271    | 07           | SCR-127     | CMP-027, CMP-033, CMP-034, CMP-043, CMP-066, CMP-093, CMP-175 (`14`:2703); CMP-035, CMP-201          | E27-S03  |
| SCR-128 | `D02`:671 · `D03`:1348    | 04, 05       | SCR-128     | CMP-028, CMP-035, CMP-049, CMP-087, CMP-175, CMP-178 (`14`:2712)                                     | E27-S03  |
| SCR-129 | `D02`:773 · `D03`:1432    | 08, 03       | SCR-129     | CMP-027, CMP-044, CMP-093 (`14`:2727); CMP-015                                                       | E27-S04  |
| SCR-079 | `D02`:864 · `D03`:1524    | 09           | SCR-079     | CMP-036, CMP-046, CMP-104, CMP-106, CMP-116, CMP-128, CMP-129, CMP-175 (`14`:1846); CMP-178          | E27-S05  |
| SCR-016 | `D02`:943 · `D03`:1244    | 06 (inset)   | SCR-016     | the step 3 inset of SCR-126's key step (`14`:429)                                                    | E27-S02  |
| SCR-019 | `D02`:943 · `D03`:1524    | not drawn    | SCR-019     | the account tasks inside E09's card (`14`:493); text binding, drawn on request (`D03`:278)           | E27-S01  |

Board 10 holds the keyboard, zoom and forced-colours specimens for every screen (`D03`:228). The deck screens `shared`,
`CMP-034` and `CMP-175` hold the strings several screens show; their first consumer is named per row.

## 4. Per screen: data, RBAC, events and budget

Every operation below is in `22` at the base and every topic in `23` (G-DATA). The permission names are `24` §15.2's
(`24`:5205–5208, :5241–5242); the role matrix is `24`:5271–5274. A server sentence is shown verbatim, never rewritten
(`D03`:2058). A gated (T2) control emits nothing (`D03`:2567).

### 4.1 SCR-125 — Bybit accounts list (`/admin/accounts`)

| Operation              | Request                                                 | Permission      |
| ---------------------- | ------------------------------------------------------- | --------------- |
| `listExchangeAccounts` | `GET /exchange-accounts`                                | `accounts:read` |
| `listApiKeys`          | `GET /exchange-accounts/{accountId}/keys`               | `keys:read`     |
| `getSecuritySummary`   | `GET /admin/security/summary`                           | `audit:read`    |
| `getCapacity`          | `GET /admin/capacity`                                   | `admin:read`    |
| `testApiKey`           | `POST /exchange-accounts/{accountId}/keys/{keyId}/test` | `keys:read`     |

Topics: `system` (the read-only notices and the KEK notice), `wallet` (health). RBAC: the Owner; every other role is
T3 (`D02`:441). Events: `admin.accounts_list_viewed` (analytics), `account.tested` and `account.disabled_by_policy`
(audit, written by the server). Budget: refresh on open and every 60<!--=BUD:health.s--> s, never per second
(`14`:2661). Data detail and producers: `D03`:1097.

### 4.2 SCR-126 — Add or edit an account (and SCR-016 step 3)

| Operation                | Request                                    | Permission       |
| ------------------------ | ------------------------------------------ | ---------------- |
| `createExchangeAccount`  | `POST /exchange-accounts`                  | `accounts:write` |
| `createApiKey`           | `POST /exchange-accounts/{accountId}/keys` | `keys:manage`    |
| `getExchangeAccount`     | `GET /exchange-accounts/{accountId}`       | `accounts:read`  |
| `updateExchangeAccount`  | `PATCH /exchange-accounts/{accountId}`     | `accounts:write` |
| `authStepUp`             | `POST /auth/step-up`                       | self             |
| `getOnboardingChecklist` | `GET /onboarding/checklist`                | self             |

Topics: `system`. RBAC: the Owner, `keys` step-up before the import (`D03`:1205). Events: `account.created` (audit,
`accounts.create` and `api_key.import`), `account.updated` (audit; registered, `24`:5360), `admin.key_form_opened`
(analytics). Budget: the round trip within 3<!--=BUD:test.s--> s, with a validating state that names its wait
(`14`:2689; `D04`:81). Data detail: `D03`:1205.

### 4.3 SCR-127 — Key rotation

| Operation      | Request                                                   | Permission    |
| -------------- | --------------------------------------------------------- | ------------- |
| `rotateApiKey` | `POST /exchange-accounts/{accountId}/keys/{keyId}/rotate` | `keys:manage` |
| `listApiKeys`  | `GET /exchange-accounts/{accountId}/keys`                 | `keys:read`   |
| `authStepUp`   | `POST /auth/step-up`                                      | self          |

Topics: `system`. RBAC: the Owner, rung 3 with a fresh `keys` code and the typed account label (`14`:2706). Events:
`account.key_rotated` (audit; `24`:5360 registers `apikey.rotated`, C-2), `security.key_policy_violation` on a refused new key. Budget: 10<!--=BUD:rotate.s--> s
across stages 2–3 with each stage's elapsed time, never the 900 s overlap (`14`:2702). Data detail: `D03`:1301.
The rung is `14`:2706's ruling, which supersedes `D03`:1278 (rung 1; C-1): the deck carries it as PROPOSED rows on
that line, `e27.scr127.typed` and `e27.scr127.hint.typed` at stage 2, and the menu's ask line for Rotate key… moves to
`e27.scr125.menu.ask.label`. Frame 34 and frame 11 are drawn at rung 1; PR 2 redraws or annotates them.

### 4.4 SCR-128 — Key health and secrets policy (a panel of `/admin/accounts`)

| Operation            | Request                                              | Permission         |
| -------------------- | ---------------------------------------------------- | ------------------ |
| `getSecuritySummary` | `GET /admin/security/summary`                        | `audit:read`       |
| `listApiKeys`        | `GET /exchange-accounts/{accountId}/keys`            | `keys:read`        |
| `setKillSwitch`      | `POST /trading/kill-switch`                          | `killswitch:write` |
| `revokeApiKey`       | `DELETE /exchange-accounts/{accountId}/keys/{keyId}` | `keys:manage`      |

Topics: `system` (`rate_budget_free_pct`, `secrets.kek_unavailable`). RBAC: the Owner only (`D03`:1399). Events:
`admin.key_health_viewed` (analytics), `admin.key_marked_compromised` (audit, no operation and no registered code;
BLOCKS the build, R6 in §10). Budget: computed server-side and cached 60 s, never an exchange call from the browser (`14`:2715). Data detail:
`D03`:1399.

### 4.5 SCR-129 — Disable, delete and the revoke dialog

| Operation                | Request                                              | Permission       |
| ------------------------ | ---------------------------------------------------- | ---------------- |
| `getAccountConsequences` | `GET /exchange-accounts/{accountId}/consequences`    | `accounts:write` |
| `updateExchangeAccount`  | `PATCH /exchange-accounts/{accountId}`               | `accounts:write` |
| `deleteExchangeAccount`  | `DELETE /exchange-accounts/{accountId}`              | `accounts:write` |
| `revokeApiKey`           | `DELETE /exchange-accounts/{accountId}/keys/{keyId}` | `keys:manage`    |
| `authStepUp`             | `POST /auth/step-up`                                 | self             |

Topics: `system`; the `revoked` reasons `key_revoked` and `account_disabled` end a viewer's subscriptions (`23`:1567).
RBAC: the Owner. Events: `account.disabled`, `account.deleted` (audit, registered for E27-S04, `24`:5370; their markers
`e27.scr129.marker.disable` and `.delete`), `account.key_revoked` (audit, `api_key.revoke` ahead and `api_key.revoked`
on completion, `24`:5372). Budget: the summary within 1<!--=BUD:summary.s--> s, no confirm until it has loaded
(`14`:2726). The up-front read D03 asked for (G-7, `D03`:1480) is served at the base as `getAccountConsequences`
(`22`:3263), so the loading → ready cut of M-8 has its source.

### 4.6 SCR-079 — Account detail drawer (trading side)

| Operation               | Request                                   | Permission        |
| ----------------------- | ----------------------------------------- | ----------------- |
| `getExchangeAccount`    | `GET /exchange-accounts/{accountId}`      | `accounts:read`   |
| `listApiKeys`           | `GET /exchange-accounts/{accountId}/keys` | `keys:read`       |
| `getSecuritySummary`    | `GET /admin/security/summary`             | `audit:read`      |
| `setPositionLeverage`   | `PUT /positions/{positionId}/leverage`    | `positions:write` |
| `updateExchangeAccount` | `PATCH /exchange-accounts/{accountId}`    | `accounts:write`  |

Topics: `wallet`, `positions`, `system`. RBAC: every role sees the account's served facts; the Owner adds the key
facts; a Manager's or a Viewer's writes are T2 with E09-D09's reasons (`D03`:1569; `D02`:900). Events:
`account.detail_viewed` (analytics; its payload the viewer's role only). Budget: opens from cache in 100<!--=BUD:drawer.ms--> ms
and refreshes in place, never a spinner over cached values (`14`:1849).

## 5. Components and the library

Every control resolves to a catalogued CMP entry; no one-off exists (`D03`:2655). The three contributions and the
extensions are specified in D03 §2 (`D03`:336) and carried in `16` §11.4 form by `D03H` (one block each: CMP-175
`D03H`:15, CMP-176 `D03H`:57, CMP-034 `D03H`:100; the extended entries `D03H`:130).

| Component                                   | Contract  | Storybook title and stories                        | `15` entry                    |
| ------------------------------------------- | --------- | -------------------------------------------------- | ----------------------------- |
| CMP-175 KeyPermissionBadge                  | `D03`:338 | `Atoms/KeyPermissionBadge`, the list at `D03`:2665 | PENDING: D03 Appendix A, PR 2 |
| CMP-176 AccountKeyRow                       | `D03`:508 | `Molecules/AccountKeyRow`, the list at `D03`:2666  | PENDING: D03 Appendix A, PR 2 |
| CMP-034 MaskedValue                         | `D03`:657 | `Atoms/MaskedValue`, the list at `D03`:2667        | PENDING: D03 Appendix A, PR 2 |
| CMP-201 PasswordField (`writeOnly`)         | `D03`:702 | `Atoms/PasswordField`, the list at `D03`:2668      | PENDING: D03 Appendix A, PR 2 |
| CMP-028, CMP-035, CMP-044, CMP-066, CMP-178 | `D03`:730 | the lists at `D03`:2669–2673                       | PENDING: D03 Appendix A, PR 2 |
| CMP-011, CMP-203, CMP-033                   | `D03`:918 | the lists at `D03`:2674–2676                       | PENDING: D03 Appendix A, PR 2 |

Every story runs in six cells, dark, light and high contrast by compact and comfortable, with axe at zero serious or
critical findings and its keyboard path as an interaction test (`D03`:2657). **Published in the library** means two
things: D03's boards carry the components on the page above (done), and `15` carries the entries. D03's Appendix A
(`D03`:3018) never reached `15` or `14` (D05 G-02, `D05`:479); this ticket applies it in PR 2, after the pack merges,
re-reading every Old cell at that day's `main` (BQ-02).

**The per-component hand-off checklists (`02`:56; `16` §11.4).** CMP-175, CMP-176 and CMP-034 each carry their
`16` §11.4 block in D03H (CMP-175 `D03H`:15, CMP-176 `D03H`:57, CMP-034 `D03H`:100); each line is ticked or N/A
with a reason, but for the six open lines below, and each consuming story links its block through §3.
D05 closes the numbers behind two of the open lines; none is closed by this pack alone.

| D03H line  | Block and line                | What closes it                                                                                          | Owner                |
| ---------- | ----------------------------- | ------------------------------------------------------------------------------------------------------- | -------------------- |
| `D03H`:49  | CMP-175, Contrast and CVD     | the numbers: D05 §11 (`D05`:347; F-06) and §10 (`D05`:328); the PROPOSED pairs' registration stays open | E27-D06, PR 2 (G-08) |
| `D03H`:55  | CMP-175, Sign-off             | §15's records                                                                                           | the owner (#2701)    |
| `D03H`:93  | CMP-176, Contrast and CVD     | as `D03H`:49                                                                                            | E27-D06, PR 2 (G-08) |
| `D03H`:98  | CMP-176, Sign-off             | §15's records                                                                                           | the owner (#2701)    |
| `D03H`:127 | CMP-034, Sign-off             | §15's records; the supersession of E05-D02's timed display stays the owner's                            | the owner (#2701)    |
| `D03H`:264 | section A, accessibility role | §15's accessibility row                                                                                 | the owner (#2701)    |

## 6. Tokens and redlines

Token references replace pixel redlines, as the ticket's Technical notes ask: each screen's anatomy row in D03 names
its tokens (`D03`:1016 for SCR-125 and `D03`:1176 for SCR-126; the per-frame Tokens column in each screen's hi-fi rows). The
token sets are `packages/ui/tokens` as D03 bound them (`D03`:67). The contrast numbers of record are D05 §11's
re-measured rows (`D05`:347), which replace D03 §9's markers (F-06). Density: compact and comfortable, the two `16`
defines (`16`:14; D-3); type never changes with density.

## 7. Motion and its reduced-motion equivalents

D04 owns E27's motion (`D05`:96). Its eleven rows, by surface; every cell below is D04 §2's (`D04`:66–76), and the tool
checks the ids and recipes (G-MOTION). Reduce is driven by `data-motion` only (`D04`:155).

| M    | Surfaces                                          | Recipe                           | Reduced motion                     |
| ---- | ------------------------------------------------- | -------------------------------- | ---------------------------------- |
| M-1  | SCR-126, SCR-127 stage 3, the Test dialog         | a cut; the busy state: row 7     | identical (a cut); row 7's reduce  |
| M-2  | SCR-127 stages 1–5 and the wizard                 | a cut; the wizard dialog: row 2a | identical (a cut); row 2a's reduce |
| M-3  | SCR-127 stage 4 countdown (CMP-035)               | a cut                            | identical (a cut)                  |
| M-4  | SCR-125 chips and the verdict line                | a cut                            | identical (a cut)                  |
| M-5  | SCR-079 balances and the stale chip               | a cut                            | identical (a cut)                  |
| M-6  | the KEK-unavailable banner (SCR-125, SCR-126)     | a cut                            | identical (a cut)                  |
| M-7  | withdrawal-detected (SCR-125, SCR-126)            | a cut                            | identical (a cut)                  |
| M-8  | SCR-129 and every destructive dialog              | row 2a                           | row 2a's reduce                    |
| M-9  | the compromise card (SCR-128, SCR-125)            | a cut                            | identical (a cut)                  |
| M-10 | SCR-079 drawer (CMP-046)                          | row 2b                           | row 2b's reduce                    |
| M-11 | first loads of SCR-125 and SCR-079; busy controls | rows 6 and 7                     | rows 6 and 7's reduce              |

A destructive confirmation's loading state is motion-free in both modes (M-8, A25a; `D04`:95). Durations and easings
are E05-D03's rows cited by id, never copied (`D04`:57).

## 8. Accessibility (the full E27-D05 output)

### 8.1 Where each part lives

| Part                                    | Rows          | Where     |
| --------------------------------------- | ------------- | --------- |
| Focus-order maps (on open, Tab, close)  | FO-01 … FO-12 | `D05`:172 |
| Keyboard-only flows                     | KS rows       | `D05`:193 |
| Live-region plan                        | LR-01 … LR-29 | `D05`:290 |
| Screen-reader script (E27-Q04's pass)   | SR-01 … SR-20 | `D05`:517 |
| Contrast in every state                 | D05 §11       | `D05`:347 |
| Densities, zoom, forced colours, motion | D05 §12       | `D05`:389 |

Per screen: SCR-125 FO-01, FO-05, FO-09, FO-12; SCR-126 FO-02, FO-03; SCR-016 FO-04; SCR-127 FO-06; SCR-129 FO-07 and
the step-up FO-08; SCR-079 FO-10; SCR-019 FO-11. Every live region is pre-rendered empty, and only its text changes
(`D05`:290).

### 8.2 The findings and their disposition in this pack

| F    | Severity | Disposition                                                                                                  |
| ---- | -------- | ------------------------------------------------------------------------------------------------------------ |
| F-01 | Major    | lifted: the dialog is described by the whole restatement group; deck `e27.scr129.announce.loaded` (PROPOSED) |
| F-02 | Major    | lifted: SCR-019's account tasks show `rbac.view_as` while viewing as; `rbac.owner_only` otherwise            |
| F-03 | Minor    | lifted: the key and secret labels say "(write-only)"; deck rows on SCR-126 and SCR-127 (PROPOSED, BQ-07)     |
| F-04 | Minor    | lifted: LR-14's sentence first, then focus to stage 5's heading, whose name is the heading alone             |
| F-05 | Minor    | lifted: no confirm in the DOM until the summary loads, then focusable `aria-disabled` with its hint (A-5)    |
| F-06 | Minor    | lifted: D05 §11's numbers are the contrast record (§6; `D05`:451)                                            |
| F-07 | Info     | recorded for E28-D03; no E27 change                                                                          |
| F-08 | Info     | recorded (`D05`:453): the premise moved; the decision (shape and word carry the class) stands                |
| F-09 | Major    | lifted: inside a text field or an open modal, no single-character global binding fires; `Esc` still cancels  |
| F-10 | Minor    | lifted: heartbeat as an absolute time; deck `e27.scr125.row.health`, `e27.scr079.health` (PROPOSED)          |
| F-11 | Minor    | lifted: the T2 lock is `aria-hidden`; the name is the visible label, "unavailable" from `aria-disabled`      |
| F-12 | Minor    | lifted: one "{n} accounts: {state}" per episode; deck `e27.shared.announce.chips` (PROPOSED)                 |

No Blocking row stands, so D05's hold on this ticket's sign-off is clear (`D05`:442). D05's open questions Q-01 … Q-03
are built on their defaults (`D05`:487); the owner rules them at sign-off, and A-5 carries Q-02's answer to `15`.

### 8.3 The two gaps D05 hands to this pack

- **Reflow at 320 CSS px (G-07, `D05`:484). PROPOSED, one rule per family (BQ-08).** At 320 CSS px every E27
  surface is one column, and nothing scrolls in two directions except a table's own region. E27-Q04 checks the built
  screens.
  - **Lists (SCR-125):** each row keeps its two-line form, its actions stacked under it.
  - **Dialogs (SCR-126, the SCR-127 wizard, every SCR-129 dialog, the Test dialog and the step-up):** full width,
    footer actions stacked, Cancel first. SCR-129's sticky header (the title and the account) and sticky footer
    (Cancel and the confirm) stay pinned while the consequence summary scrolls between them.
  - **Drawers (SCR-079, CMP-046):** full width, the header and its close kept in view.
  - **Tables (SCR-128):** one card per key, with the same labels.
- **Contrast families outside D05 §11 (G-08, `D05`:485).** PENDING: the stepper's current and upcoming steps, inline
  error text, radio and checkbox boundaries, the primary action's hover, pressed and busy looks, and CMP-104's track
  and thumb are measured with the tokens tool in PR 2, before sign-off; any gated pair under 4.5:1 for text or 3:1 for
  a boundary blocks it (BQ-08, ruled).

## 9. The copy deck

[E27-D06-copy-deck.jsonl](E27-D06-copy-deck.jsonl) holds every string the eight screens and the contributed
components render: 353<!--=COUNT:deck.rows--> rows, of them merged 340<!--=COUNT:deck.merged--> (E27-D03 §12.1 and
§12.2, `D03`:2046, :2522) and PROPOSED 13<!--=COUNT:deck.proposed-->: 7<!--=COUNT:deck.lifts--> D05 lift rows
(§8.2; F-10's row and drawer are two), the four rung-3 rows on `14`:2706 (§4.3), and SCR-129's disable and delete
markers on `24`:5360 (§10). Per screen: SCR-125
81<!--=COUNT:screen.SCR-125-->, SCR-126 47<!--=COUNT:screen.SCR-126-->, SCR-127 34<!--=COUNT:screen.SCR-127-->,
SCR-128 35<!--=COUNT:screen.SCR-128-->, SCR-129 50<!--=COUNT:screen.SCR-129-->, SCR-079 27<!--=COUNT:screen.SCR-079-->,
SCR-016 7<!--=COUNT:screen.SCR-016-->, SCR-019 8<!--=COUNT:screen.SCR-019-->, shared 50<!--=COUNT:screen.shared-->,
CMP-175 12<!--=COUNT:screen.CMP-175-->, CMP-034 2<!--=COUNT:screen.CMP-034-->.

**Frozen.** Every string is rendered byte for byte; a builder fills only the `{…}` slots, with UTC times
(`D03`:2058). Every key, secret and key-id string is frozen with the rest, and no fill ever carries key material: the
only key fills are `{key_id_masked}`, the server's masked id, and `{last4}`, CMP-034's (G-SECRET). A string not in the deck is a gap (§13.3), never invented.
A row has `id` (its name), `text` (or `parts`, for a cell D03 wrote as several strings), `screen`, `where`, `status`,
`owner`, `source` (the parent line the text stands on), `origin` (D03's status and source cell, verbatim) and `consumer`;
a lifted row adds `quote` (the words on its D05 line or its ruled `14` line) and `d03_text` (the string it replaces), and
a row whose `where` moved adds `d03_where`. The header lists RULED as a status; no row is RULED: the BQ ruling
settles the rungs and the codes, and the strings wait on the owner's approval.

**Provenance is checked by id, never by row position.** E27-D03 §12.1 holds 327<!--=COUNT:d03.ids--> `e27.*` ids; each
is in the deck once (G-COVER), and 322<!--=COUNT:deck.byid--> of them carry D03's string byte for byte. The rest are
lifts, each naming the D03 string it replaces.

## 10. Observability (audit and analytics, per screen)

The ticket's thirteen events with their real state at the base. Implementation emits only a registered audit code;
an event with none shows "Recorded in the audit log" and is routed to the registry owner, never invented
(`D03`:2561; BQ-09). Payloads carry fingerprints or ids, never key material (`D03`:2564).

| Event                          | Kind      | Screens          | State at the base                                                                       |
| ------------------------------ | --------- | ---------------- | --------------------------------------------------------------------------------------- |
| `account.created`              | audit     | SCR-126, SCR-016 | registered as `accounts.create` and `api_key.import`                                    |
| `account.updated`              | audit     | SCR-126          | registered (`24`:5360); D03's edit flow names no code yet                               |
| `account.tested`               | audit     | SCR-125, SCR-128 | registered; written by the server                                                       |
| `account.disabled_by_policy`   | audit     | SCR-125          | registered; written by the server on a failing verdict                                  |
| `account.key_rotated`          | audit     | SCR-127          | registered: `apikey.rotated` (`24`:5360); the marker keeps D03's `api_key.rotate` (C-2) |
| `account.key_revoked`          | audit     | SCR-129, SCR-128 | registered: `api_key.revoke` ahead, `api_key.revoked` on completion (`24`:5372)         |
| `admin.secrets_policy_changed` | audit     | SCR-128          | dropped: the policy has no write (D03 C15)                                              |
| `admin.key_marked_compromised` | audit     | SCR-128          | BLOCKS the build: no code is registered (R6)                                            |
| `admin.accounts_list_viewed`   | analytics | SCR-125          | PROPOSED here: the payload is the verdict form, never a label                           |
| `admin.key_form_opened`        | analytics | SCR-126          | PROPOSED: the key step opened                                                           |
| `admin.key_test_run`           | analytics | SCR-125, SCR-128 | PROPOSED: the Test press                                                                |
| `admin.key_health_viewed`      | analytics | SCR-128          | named in `14`:2716: the disclosure opened                                               |
| `account.detail_viewed`        | analytics | SCR-079          | named in `14`:1850: the payload is the viewer's role only                               |

Disable and delete are registered for E27-S04 (`24`:5370), so SCR-129's markers name them
(`e27.scr129.marker.disable`, `e27.scr129.marker.delete`; BQ-09, ruled); both drops above hold.

**Requests to owners.** A-5 … A-8 and A-10 (§14) are the first five rows routed to an owner; R6 is the sixth.

| R   | To                                                               | Request                                                                                                                                                                                   | Blocks                                                                   |
| --- | ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| R6  | the `24` audit-registry owner; E27-S03 (#897) and E27-S04 (#898) | `admin.key_marked_compromised` is a key action (C-12.12) and C-2.9 audits every key action: register an ahead code and a completion code for it before any build of the compromise action | the compromise action on SCR-128's card: no build until both codes exist |

## 11. Budgets (restated from `14`, never re-decided)

SCR-126: the test round trip within 3<!--=BUD:test.s--> s with a validating state (`14`:2689). SCR-127: rotation
within 10<!--=BUD:rotate.s--> s with per-stage timing (`14`:2702). SCR-129: the consequence summary within
1<!--=BUD:summary.s--> s before the confirm appears (`14`:2726). SCR-079: open from cache within
100<!--=BUD:drawer.ms--> ms (`14`:1849). SCR-125: health refresh every 60<!--=BUD:health.s--> s, never per second
(`14`:2661).

## 12. The design-ahead record and the links

`02` asks for design Done two sprints before the consuming story starts (`02`:53). This ticket is planned in Sprint
13<!--=SPRINT:own--> and its consumers in Sprint 15<!--=SPRINT:first-->, so the pack must be Done by
2026-12-17<!--=DATE:ahead.end--> (the end of Sprint 12<!--=SPRINT:ahead-->); Sprint 15 starts
2027-01-01<!--=DATE:first.start-->.

**The `02`:53 waiver (BQ-06, ruled).** E27-S01 (#895) and E27-S04 (#898) went In Progress on 2026-10-25 with server
slices that render no screen, while this ticket blocked them: that crossing is recorded here. The orchestrator's ruling
on #819 (2026-11-03) is the explicit waiver `02`:53 allows, for those server slices only. C-10.3 still gates every UI
merge on this ticket being Done, and the pack's own date stands: Done by 2026-12-17, two sprints before the consumers
start on 2027-01-01.

A precondition for E27-S02's first `apps/web` change: PR 2 applies A-4 and A-9, so `15` no longer defaults CMP-201's
unmask prop to on. At PR 1b's merge, one comment on each of
#895–#899 links this file and names the consumer's screens (§3); SCR-016 step 3 is linked from both #895, whose scope
wires it, and #896 (BQ-10, ruled).

## 13. The walkthrough, the dry run and gaps

### 13.1 The walkthrough (45 minutes; the protocol)

0–5 min: the four rules (§2), read aloud. 5–35 min: per screen, five minutes each, in §3's order: the frames, the
deck section, the data and RBAC rows, the motion and live-region rows. 35–45 min: questions. Every question is
written into §13.2 with its answer and the section that now holds it; an answer given only in chat does not count.
Attendees: the frontend engineers of E27-S01 … S05, the design owner and the security reviewer. The session is run by
the owner, or replaced by the agent dry run (BQ-04, ruled): a fresh agent builds SCR-126 from the pack alone, and
every question it asks is logged in §13.2, labelled `(heuristic)`. The owner-walkthrough checklist is posted on #819
in E38-D06 §14's form; AC 1 stays open until the stories count the questions. No session is claimed here.

### 13.2 Questions and answers

| Q   | Asked by (role) | Question | Answer and where it now lives |
| --- | --------------- | -------- | ----------------------------- |

The table is empty until the walkthrough or the dry run is logged on #819. A question the pack should have answered is
also logged as a hand-off checklist improvement (§13.3).

### 13.3 A gap found during implementation (`T` AC 5)

An engineer who meets a state with no frame, a string with no deck row or a control with no CMP entry stops that part,
comments on the story with the screen and the state, and asks the design lane for a follow-up design ticket. The design
ticket updates this pack (a new deck row, a frame, an entry) and logs the gap in a "Gaps found" table appended here, so
the next pack's checklist can be improved. Nothing is invented in code meanwhile.

## 14. Copy-ready rows (A-1 … A-4 and A-9 applied by PR 2; A-5 … A-8 and A-10 routed to their owners)

| A    | File and line | Old                                                                | New                                                                                                                                           | Owner             |
| ---- | ------------- | ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| A-1  | `14`:2666     | —                                                                  | after it: "- **Hand-off pack (E27-D06):** [E27-D06-handoff.md](../design/E27/E27-D06-handoff.md) — frames, the copy deck, data, RBAC, events" | this ticket, PR 2 |
| A-2  | `14`:2694     | —                                                                  | the same line after SCR-126's wireframes line                                                                                                 | this ticket, PR 2 |
| A-3  | `14`:2707     | —                                                                  | the same line after SCR-127's; likewise after `14`:2719 (SCR-128), `14`:2731 (SCR-129) and `14`:1853 (SCR-079)                                | this ticket, PR 2 |
| A-4  | `15`:2246     | "Atom (owner/admin, security-critical)"                            | D03 Appendix A's twelve entries (`D03`:3018), each Old cell re-read at that day's `main`                                                      | this ticket, PR 2 |
| A-5  | `15`:520      | "typed (Confirm natively disabled until the summary has loaded"    | D05 A-05's new text (`D05`:503)                                                                                                               | `15`'s owner      |
| A-6  | `05`:100      | "Only explicit user action or an explicit modal alert"             | D05 A-01's addition (`D05`:499; it cites the rules block, `05`:96)                                                                            | `05`'s owner      |
| A-7  | `14`:2657     | "account is auto-disabled for trading with a red banner"           | D05 A-02's text (`D05`:500; cited there as :2636, now :2657)                                                                                  | `14`'s owner      |
| A-8  | `11`:504      | "Then the account row shows green with the last heartbeat age"     | D05 A-03's first text (`D05`:501)                                                                                                             | `11`'s owner      |
| A-9  | `15`:2652     | "**Props**: `value` · `onChange`"                                  | D05 A-04's variant (`D05`:502; cited there as :2632, now :2652), with CMP-201's other rows in A-4                                             | this ticket, PR 2 |
| A-10 | `11`:510      | "Then the row shows red, order entry is disabled for that account" | D05 A-03's second text, "reads Down, with its octagon" (`D05`:501)                                                                            | `11`'s owner      |

## 15. Sign-off record

| Role                             | Scope                                               | Record                                                                                     |
| -------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Chief Design Officer or delegate | the whole pack                                      | PENDING: owner approval pending (#2701)                                                    |
| Accessibility specialist         | §8, the deck's announcement rows, D05's F rows      | PENDING: owner approval pending (#2701)                                                    |
| Security engineer                | §2, NR-1 … NR-4, every frame that renders key state | PENDING: owner approval pending, after one Opus security pass on §2 and the key-state rows |

Under the delegation of #2701 the owner's `approved` stands in for each role, recorded per row with the comment that
gives it (BQ-03, ruled). The Security engineer's row is never implied by the other two; the security pass runs once,
with no re-run. No path here matches a C-10.2 glob by name (`*key*`, `*secret*`, `*token*`, `*crypt*`). The lane ticks
each screen's `14` sign-off checklist item by item in the review comment (SCR-127 `14`:2705, SCR-129 `14`:2729, the
others likewise; D05 §17, `D05`:561, did it first), and the orchestrator confirms them at approval (DoD 4).

## 16. Deviations

- **D-1 Path.** `T` names `docs/design/e27/handoff.md`; the pack is `docs/design/E27/E27-D06-handoff.md` with its deck,
  as every E27 spec lives in the epic folder (D05 C-08, `D05`:472; BQ-01, ruled). No file name matches a C-10.2 glob.
- **D-2 Tool.** `T` says Figma; the design file is the self-hosted Penpot, referenced by page name and id only.
- **D-3 Densities.** `T`'s DoD names three densities; `16` defines two, as D03 C1 and D05 C-07 recorded
  (`D05`:471).
- **D-4 People.** No walkthrough or comprehension session was run by this text; §13 is the protocol and its log.

### 16.1 The BQ ruling (#819, 2026-11-03)

| BQ    | Question                 | Ruling and where it is folded                                                                                                                                             |
| ----- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BQ-01 | Path and shape           | agreed: the epic folder; no C-10.2 path by name, `*crypt*` included (D-1, §15)                                                                                            |
| BQ-02 | PR shape and the library | disagreed: the deck-first split, PR 1a the deck and the tool, PR 1b this pack and the pins, PR 2 the edits and the closing line (header)                                  |
| BQ-03 | Sign-off record          | agreed: one Opus security pass on §2 and the key-state rows, no re-run; every role row "owner approval pending" (§15)                                                     |
| BQ-04 | The walkthrough          | amended: the agent dry run replaces the session, labelled `(heuristic)`; the owner-walkthrough checklist on #819; AC 1 open until the stories count the questions (§13.1) |
| BQ-05 | NR-4 and the ladder      | agreed: NR-4 cites OQ-9 and OQ-10 (RULED); `D03`:1278 is C-1 against `14`:2706 (§2, §16.2)                                                                                |
| BQ-06 | The design-ahead AC      | amended: the `02`:53 waiver for #895's and #898's server slices, both dates stated; C-10.3 gates the UI (§12)                                                             |
| BQ-07 | The D05 lifts            | agreed: the lift rows recounted at the deck by the tool (§9)                                                                                                              |
| BQ-08 | D05's G-07 and G-08      | agreed: one PROPOSED reflow rule per family; G-08 measured in PR 2 gates the sign-off (§8.3)                                                                              |
| BQ-09 | The ticket's events      | amended: the registered spellings cited; disable and delete registered for E27-S04 (§4.5, §10, C-2)                                                                       |
| BQ-10 | Consumers and links      | amended: SCR-016 step 3 linked from #895 and #896; one comment per story (§12)                                                                                            |

### 16.2 Contradictions (C-rows)

| C   | Between                                                                                                                                                                                                                         | Reading here                                                                                                                           |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| C-1 | `D03`:1278 (the rotation switch at rung 1) vs `14`:2706 (OQ-10, RULED: rung 3)                                                                                                                                                  | the pack and the deck follow `14`:2706 (§4.3); frames 11 and 34 are redrawn or annotated in PR 2 (BQ-05)                               |
| C-2 | `24`:5360 registers rotation as `apikey.rotated` (and lists `account.created`, `apikey.added`) vs the audit registry in code at the base and D03's markers, which read `api_key.rotate`, `accounts.create` and `api_key.import` | the deck keeps D03's merged markers until the registry's owner settles one spelling; routed to E27-S03 (#897) and `24`'s owner (BQ-09) |

## 17. The tool

`python3 -I docs/design/_tools/e27_d06_handoff_audit.py --stage full --check` (exit 1 on any FAIL); `--json`;
`--self-test` (with `--stage`; one mutation per gate at least, texts restored); `--repin-ruled` (the pins file's only
writer). The `deck` stage reads the deck and the tool only, so the deck lands first (PR 1a, `--stage deck`); PR 1b
adds this pack and the pins (`--stage full`). Gates: G-DECK (each row parses,
its text on its cited line), G-COVER (every E27-D03 §12 id once, by id, merged text unchanged unless lifted), G-RULES (§2), G-SECRET (no key material
in any field; no show, copy-out or unmask offer),
G-INDEX (§3 against `14` and D03's boards), G-DATA (§4 against `22`, `23` and `24`), G-EVENT (§10 against `T`; the
compromise row blocks the build), G-RULING (§16.1's BQ-01 … BQ-10 rows; §10's registered spellings),
G-MOTION (§7 against D04), G-A11Y (§8 against D05), G-BUDGET and G-AHEAD (the anchors), G-AROW, G-CITE (every cite
pinned by content), G-FILLED, G-HYGIENE and G-SCOPE.
