# E49 bug-bash kit

- Ticket: E49-Q02 (#1336), `Partial:` slice S-B. Index and rules: `docs/qa/charters/E49-README.md`.
  Harness: `docs/qa/e49-exploratory-harness.md`. Severity and SLAs: `docs/plan/03-testing-strategy.md` §11.3.
- What this is: everything a lane can prepare so a two-hour cross-team bug bash starts on time and ends
  with every card decided the same day. It schedules nothing and runs nothing; the bashes are human work.
- Related slices, cited only: #5840 refreshes the charters, #5841 adds the disposition check
  (the `check_e49_records.py` checker, whose path that slice settles) and the findings-schema text in the
  README. The bash card ids in §9 (`E49-B<bash>-<nn>`) need #5841's id pattern widened to
  `^E49-[RB]\d+-\d+$`; that change is made in #5841, and until it merges the checker does not
  accept a B id.
- Agenda of the two hours: 5 minutes scripted warm-up (§6), 90 minutes free exploration, 25 minutes
  same-day triage (§8).

## §1 Who decides what

| Item                                           | Decided by                                 | Prepared by a lane                                        |
| ---------------------------------------------- | ------------------------------------------ | --------------------------------------------------------- |
| Bash 1 date: S23 (2027-02-26 to 2027-03-04)    | Owner. PROPOSED, owner decision pending.   | This kit; the pre-bash checklist (§7)                     |
| Bash 2 date: S25 (2027-03-12 to 2027-03-18)    | Owner. PROPOSED, owner decision pending.   | This kit; the pre-bash checklist (§7)                     |
| Attendees and the role each one plays          | Owner (agent lanes stand in, see below)    | The lane table (§2)                                       |
| The shared board and the bash label            | Owner (a Project view cannot be committed) | The card template (§4); no lane creates a view or a label |
| Stack host and the build under test            | Owner names the host; QA lead pins the sha | The pre-bash checklist (§7)                               |
| Severity disputes at triage                    | Owner                                      | The grading sheet (§5), a recommended grade per card      |
| Whether the security route is staffed that day | Owner                                      | The security-card rule (§6)                               |
| Highlights at Sprint Review                    | Owner                                      | A one-page summary from the bash record (§9)              |
| Filing each graded card as an issue            | Orchestrator (filing freeze)               | Draft issue bodies from the cards (§9)                    |
| Routing of perf and screen-reader cards        | Owners of E46 (#72) and the a11y epic      | A routing value on each card (§9)                         |

The triage ritual (`docs/plan/backlog/artifacts/e49-triage-ritual.md`) says that in this
agent-delivery setup the owner stands in for the human roles, so the record says who attended in which role.
The ticket names E47 for routings while the README routes screen-reader rows to E49-Q03 (#1395); the
DoD routing row's epic stays PROPOSED until the owner says which.

## §2 Lanes

Two lanes at least (README, bug-bash template). A lane is a role, a first screen and one happy path. Only
screens the app builds at the build under test are worth a lane's time; a parked screen shows a stub card
and is not explored (see §3 for the table and what unparks a row).

| Lane | Name                           | Role signed in | First screen                | One happy path                                                |
| ---- | ------------------------------ | -------------- | --------------------------- | ------------------------------------------------------------- |
| L1   | Trading flows                  | Owner          | `/terminal/last` (R-101)    | Land from sign-in, read the setup checklist, open `/alerts`   |
| L2   | Admin, shell and accessibility | Owner          | `/admin` (R-300)            | Open the overview, then the invite screen `/admin/users/new`  |
| L2b  | Admin, shell and accessibility | Manager        | `/settings/hotkeys` (R-202) | Open a hotkey, change nothing, return; try `/admin` (refused) |
| L2c  | Admin, shell and accessibility | Viewer         | `/settings/appearance`      | Switch the theme and back; try `/admin/users/new` (refused)   |

- L1 is thin at today's build: the terminal is a stub card plus a checklist, and the chart, order ticket,
  algos, rules and replay have no screen. L1 grows as each owner epic unparks its row; until then L1 spends
  its time on the alerts centre and the shell states, and the robot lane (§3) covers breadth.
- L2b and L2c exist because the same screen is a different screen per role; one human can hold one lane
  per half hour and swap.
- Each lane gets one lane page: a copy of its table row plus the screens it may touch (§3), filled by the
  QA lead before the bash. The lane page never holds a credential.

## §3 Buildable surfaces and the robot lane

The scout's BQ-1 table decides what a lane may script. Re-check it against the build under test: a row
flips to buildable when its screen's route renders a body instead of the stub card (`apps/web/src/routes/tree.tsx`).

| Surface                                          | State at the pin (2026-11-04) | Used by          | Unparks when                                  |
| ------------------------------------------------ | ----------------------------- | ---------------- | --------------------------------------------- |
| Sign-in, step-up, change password, invite accept | buildable                     | L1, L2, L2b, L2c | already built                                 |
| Settings: profile, hotkeys, appearance           | buildable                     | L2b, L2c         | already built                                 |
| Admin overview R-300, invites R-303              | buildable                     | L2               | already built                                 |
| Admin security centre R-354                      | placeholder only              | L2 (look)        | E43 ships its body                            |
| Alerts centre R-190                              | buildable                     | L1               | already built                                 |
| Terminal R-101                                   | stub card plus checklist      | L1               | E15 ships the terminal body                   |
| 403 and 404 screens, shell states                | buildable                     | every lane       | already built                                 |
| Order ticket, positions, trade groups, algos     | parked (stub routes)          | none             | their owner epics ship a body                 |
| Rule editors, replay, journal                    | parked (stub routes)          | none             | their owner epics ship a body                 |
| Chart on a route                                 | parked (no route hosts it)    | none             | a route mounts `apps/web/src/chart/Chart.tsx` |

Scripted warm-ups (§6) touch only the buildable rows. A card against a parked row is
`not-a-defect: unbuilt, owner epic` and is graded in seconds.

**Robot lane (optional, owner's call).** Agent lanes run the tier A sessions of the harness
(`apps/web/e2e/exploratory/`; `run-1.explore.ts` is the current entry and a run-2 entry is expected from
the harness slice) during free exploration and post each `suspect` or `info` note as one card, so card
volume does not depend on human hours and human time goes to judgment calls. Robot cards use the same template, role `robot`, and are graded in the same triage.

## §4 Card template

One card per candidate. The title starts with the screen and then a verb, so a duplicate shows on the
board in real time: `Admin overview: shows wrong user count`. Before posting, search the board for the
screen name; if a card exists, add a comment there instead.

```text
Title:        <screen> <verb> <what happened>
Bash / lane:  B<1|2> / <L1|L2|L2b|L2c|robot>
Role:         Owner | Manager | Viewer
Build sha:    <full sha under test>
Tier:         A (stubs) | B (seeded backend)
Screen:       <route, e.g. /admin/users/new>
Steps:        1. ...  2. ...  3. ...
Expected:     <one line>
Actual:       <one line>
Keyboard-only: yes | no   (did the path work without a mouse?)
Evidence:     <recording timestamp or screenshot path; no credential in frame>
Security?:    no   (if yes, stop: leave the board, see §6)
Recommended:  P0 | P1 | P2 | P3 | not-a-defect   (the poster's guess; triage decides)
```

- Evidence carries paths, statuses and timestamps only. Never paste a password, a one-time code, a
  session value or a real account identifier (the issue form forbids them; the DoR job scans for secret
  shapes).
- A card is a candidate, not a bug. It becomes a bug only through §9.

## §5 Grading sheet (cheat sheet from 03 §11.3)

The authoritative text is 03 §11.3; this sheet is a reading aid and loses to it.

| Grade | Think                                                                                | Examples for these screens                                                        | Triage within       |
| ----- | ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- | ------------------- |
| P0    | Wrong order, missing native stop-loss, data loss, security breach, core flow crashes | A state change while viewing as another user; an order without a native stop-loss | 2 h, business hours |
| P1    | Major feature broken, a workaround exists                                            | A role sees an admin screen it must be refused                                    | 1 business day      |
| P2    | Partly broken, confusing, or an accessibility AA failure                             | A screen with no keyboard path; a focus trap                                      | 3 business days     |
| P3    | Cosmetic or wording                                                                  | A typo; a heading that names the wrong epic                                       | 1 sprint            |

Two standing P0 rules from the README: any state change while impersonating and any order without a
native stop-loss. A security-class card is `security-private` (README), not a board grade; it leaves the
board (§6), and a security breach is P0 under 03 §11.3.

Not a defect, with a one-line reason: by design; harness artefact; unbuilt (name the owner epic);
duplicate (name the original card). Perf cards route to E46 (#72) and screen-reader cards to E49-Q03
(#1395); the routing is recorded, and a routed card is not double-counted.

## §6 Scripted warm-up (5 minutes, per lane)

Runs at the start of the bash, on the seeded stack, one person per lane, together.

1. Sign in as the lane's role (§2) on the stack the owner named. Credentials come from the stack's
   private files, never from a card, a chat or a recording; sign in off camera.
2. Open the lane's first screen.
3. Do the lane's one happy path.
4. Open the shared board.
5. Post one test card using §4 with the title `Warm-up: <lane> ok` and a recommended grade of
   not-a-defect. Delete it from the count at triage (it is not a candidate and is never filed).

A warm-up that cannot finish is the first card of the bash, graded P1 if the screen is a built one.

**Security cards.** If a card might be a security issue, stop and do not post it. Do not paste detail into
the board, the chat or an issue. Tell the owner (standing in for the Security engineer) at once and use the
private route in `SECURITY.md`. The public board gets no card; the bash record states the count only
(`security-private`). The owner confirms before the bash that this route is staffed.

## §7 Checklists

**Before the bash (QA lead, with the owner)**

- [ ] Dates confirmed by the owner (PROPOSED: S23 2027-02-26..03-04, S25 2027-03-12..03-18).
- [ ] Attendees, their roles and the lane each one holds are written down; at least two lanes covered.
- [ ] The stack host is named and up; the build sha is pinned and printed on the board header.
- [ ] Three accounts seeded (Owner, Manager, Viewer), synthetic only, `test-` or `fixture-` names.
- [ ] No exchange, Demo, testnet or live credential anywhere on the stack.
- [ ] Recording on without credentials: screen recording at display level; on a seeded backend the kit's own
      rule is that the harness trace, video and screenshot stay off, and sign-in happens off camera.
- [ ] The shared board and the bash label exist (owner); the board header holds the card template.
- [ ] The security route is staffed for the day (owner confirms).
- [ ] The lane pages are filled (role, first screen, happy path, buildable screens from §3).
- [ ] The parked-surface table (§3) is re-checked against the build under test.
- [ ] A second look at open bug issues: known ones are listed on the board so they are not re-raised.

**After the bash (same day, then next morning)**

- [ ] Every card is graded or marked not-a-defect with its one-line reason (triage, §8).
- [ ] Security cards have left the board; the count is noted; the owner acknowledges the private route.
- [ ] Every graded card is an issue with `type/bug` by end of day (orchestrator files, filing freeze), or
      is recorded as `pending filing` with the reason.
- [ ] The bash record (§9) is filled and its card ids match the board.
- [ ] Next working morning: read the arrival-versus-closure panel of the defect dashboard
      (`infra/grafana/dashboards/ga-defects.json`); arrivals appear once the issues are
      filed. Record the arrival count in the bash record. An absent spike is itself a signal that the
      sessions were not effective (ticket Observability).
- [ ] Highlights page drafted for Sprint Review (owner presents).
- [ ] Text logs from the bash are scanned with `scripts/check_secrets_hygiene.py logs` before they are
      attached to the epic; a recording is checked by a person at display level; none holds a credential.

## §8 Same-day triage (25 minutes)

This is the 25-minute tail of the two hours (agenda in the header). Chair: the owner, with QA lead as
facilitator. Attendees: lane representatives and the security stand-in.
The board is read oldest first.

| Min   | Step                                                                                      |
| ----- | ----------------------------------------------------------------------------------------- |
| 0-3   | Confirm the build sha, lanes present, number of cards, number of warm-up cards to drop    |
| 3-6   | Merge duplicates: keep the oldest card, mark each other `not-a-defect: duplicate of <id>` |
| 6-9   | Security check: any card that should leave the board goes to the private route now        |
| 9-20  | Grade each remaining card with §5; the owner decides disputes; name the routing if any    |
| 20-23 | Mark every `not-a-defect` with its one-line reason; no card is left undecided             |
| 23-25 | Read back counts per disposition; assign who drafts filings; confirm the arrival check    |

Rule of the room: a card that cannot be graded in two minutes is graded P2 with the question written on it,
and a named person answers it before the bash record closes. It is never left blank.

## §9 From cards to the disposition check

Cards flow into the same ledger as the charter findings, so one check covers both (#5841, once its id pattern accepts the B ids, see the header).

1. **Candidate ids.** Each card gets `E49-B<bash>-<nn>` (for example `E49-B1-07`) at triage, in board order.
   Warm-up cards and duplicates keep ids but are not counted as arrivals.
2. **Disposition.** Exactly one of the four values in the README: `bug P0..P3`, `not-a-defect` (with a
   one-line reason), `security-private`, or `pending filing`.
3. **Findings table.** Each card becomes one row of the closing run record (the ten-column findings schema in the
   README). The Charter cell holds `B1` or `B2`; the `Oracle` column names the charter check the card touched or
   says why none did; Area is the area of the epic that built the screen; Severity is the graded value
   from §5, or `n/a` for a `not-a-defect` row; Status holds the disposition, and the issue number once
   filed. No cell is empty. The record, not the board, is the ledger.
4. **Filing.** A `bug` row is filed through the issue form, which the DoR job gates. Field mapping:
   Reproduction steps from Steps plus build sha and tier; Environment `staging - Demo` for a shared stack, or `dev - Demo` for a local seeded stack; Symbol and account
   context from the fixture handles only; Expected and Actual from the row; Severity from §5; Root cause
   hypothesis `needs investigation` unless an engineer offers one; Test layer that should have caught it is picked by the engineer who takes the issue, because neither the card nor the row carries it; Originating
   Story or Epic is the epic that built the screen. One body line, `Found in: E49-B<n>, card <id>`.
5. **Check.** The disposition check reads the run record and fails on an empty cell or an unknown
   disposition; at closing time it also fails on a `bug` row with no issue number and on any
   `pending filing`. Zero undecided
   is the ticket's second Gherkin scenario.

### Bash record template

Copy this section into the closing run record, once per bash.

```text
## Bash <1|2>: <date, PROPOSED until the owner confirms>

- Build sha: <full sha>        Stack tier: <A|B>        Stack host: <named by the owner>
- Attendees and roles: <person or lane: role; design, security, owner each named, or stand-in noted>
- Lanes run: <L1, L2, L2b, L2c, robot>
- Warm-up done: <yes/no per lane>
- Cards raised: <n>   Dropped (warm-up): <n>   Duplicates: <n>   Counted arrivals: <n>
- Dispositions: bug P0 <n> | P1 <n> | P2 <n> | P3 <n> | not-a-defect <n> | security-private <n> | pending filing <n>
- Routings: E46 <n> | screen-reader <n> | fix epics E49-S02 <n> / E49-S03 <n>
- Triage finished at: <time>, same day <yes/no>
- Arrivals on the defect dashboard next working morning: <n>, read at <time>
- Cards by id: E49-B<n>-01 .. E49-B<n>-<last>, each a row in the findings table
- Not covered: <screens or roles nobody reached>
- Highlights for Sprint Review: <three lines>
```

## §10 What stays open

- The two dates, the attendee list, the board and its label, the stack host: owner.
- Whether the robot lane runs: owner.
- The routing epic for screen-reader cards (E47 or E49-Q03): owner, PROPOSED.
- Closing the DoD rows "Two bug bashes run with same-day triage" and "Every candidate dispositioned":
  the owner and the QA lead, on the closing PR (`Closes #1336`), never on this slice.
