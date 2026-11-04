# E15 — Nav card-sort / first-click study and health-chip vocabulary research (heuristic evaluation)

- **Ticket:** #1479 (E15, parent #41; raised by #1468 on E10-D02 #137) · **Status:** owner approval pending;
  every proposal below is PROPOSED and changes no merged spec · **Read at:** `origin/main` `b81479ab0`
  (2026-11-03); the palette's Navigate source at PR #5280's head `8cbe2df4c`.
- **Method:** heuristic evaluation plus two ready-to-run protocols. Per the E10 ticket's binding
  Agent-delivery adaptations (owner decision 2026-09-25), the card sort, the first-click test and the
  vocabulary comprehension task are **not run**. **No participants, timings or quotes below are real or
  fabricated**; every finding is labelled `(heuristic)` and comes from applying Nielsen's ten heuristics
  (H1–H10) and `docs/plan/05-accessibility-standard.md` (§2, §3.1, §3.2, §4, §6.2) to the plan, the
  catalogue and the shipped code.
- **Scope:** the nav card sort over the 53 routes R-100..R-360 in `docs/plan/12-sitemap.md` §2 (12 groups),
  the first-click tasks per persona, and the CMP-210 HealthChips vocabulary with its as-built words
  (`docs/plan/15-component-catalogue.md` CMP-210, "As built (E10-S01, #304)"). Closes E15-D01's OQ-13
  (`docs/design/research/e15-layouts/findings.md`, "the owner routes them").
- **Out of scope:** wireframes and hi-fi (E15-D05 #321 and E10-D03 #197 are closed), any edit to a merged
  spec (the feed in §7 is advisory), palette command categories beyond Navigate (BQ 4 (a)).

## Acceptance-criteria trace (#1479)

| AC                                                        | Evidence                                                              |
| --------------------------------------------------------- | --------------------------------------------------------------------- |
| 1. Nav card-sort / first-click: heuristic eval + protocol | §2 deck and tasks, §3 findings N-1..N-7 `(heuristic)`, §4 protocol    |
| 2. Health-chip vocabulary: heuristic eval + protocol      | §5 findings HC-1..HC-8 `(heuristic)`, §6 protocol and gate            |
| 3. Owner-walkthrough checklist posted on #1479            | §8, written here; posted on the issue before merge (BQ 5 (a))         |
| 4. Findings feed E15's switcher and command-surface work  | §7 feed table: #476 E15-S03, #5280 E10-S05, CMP-210 (#325), the owner |

## Deviations

1. **No Agent execution brief, no estimate, no sprint, no E15.json row.** The DoR gaps were folded on
   #1479's BQ list (2026-11-03). The coordinator ruled that list (21:51Z comment on #1479): every default
   stands, build now, one design PR that closes #1479, as the coordinator's design approval under the
   2026-10-29 delegation. The owner ratifies BQ 1 (checklist item 1).
2. **Mandatory design evidence is absent; the owner decides.** `docs/design/README.md` (the
   "Mandatory evidence on EVERY design ticket" rule) reads: "Mandatory evidence on EVERY design ticket — no
   exceptions for "research" or "wireframe" tickets"; it requires the Penpot page name and id and a committed
   PNG per frame, adds that a UX-research ticket's artefact is a research board "not a markdown file alone",
   and says the `code-reviewer` fails a design PR missing either item. **Both are absent here:** no Penpot
   page (no name, no id) and no committed PNG; the text reads #1479's AC as heuristic evaluation plus protocol
   (E10-D02 precedent, `docs/design/E10/research-findings.md`). The 21:51Z ruling (issue #1479, comment 6616342783)
   says "The folded items and assumptions stand (text + markdown card deck, ...)"; it does not lift the README rule, which
   still asks the `code-reviewer` to fail this PR for the missing Penpot reference and PNGs. Owner checklist
   item 2 asks the owner to accept the text-only form or to ask for boards of the §2 deck and the §5 word
   table.
3. **No pointer edit.** `research-findings.md` already names #1479 as the carrier; it is left untouched.

## 1. Method note and limits

One evaluator read specs, the route manifest (`apps/web/src/routes/manifest.ts`, `titles.ts`), the rail
(`apps/web/src/features/app-shell/navItems.ts`), the keymap (`apps/web/src/keymap/keymap.json`) and #5280's
`sources.ts`; no running interface, no screen reader. NN/g recommends three to five evaluators. The v1
population (`10-personas.md` §0: the owner, a few managers, viewers) is too small for statistics even after a
full run, so the gates in §4 and §6 are agreement bars, not significance tests. **Confidence:** High = stated
in code, the contract or a locked plan; Med = sound reading of cited sources; Low = persona inference.
**Pri** follows E15-D01: Pri 0 = can hide a risk state or block the keyboard path; Pri 1 = slows a main
path; Pri 2 = clarity. Persona codes follow the §2 RBAC legend: O Owner, M Manager (◑ assigned accounts),
V Viewer (⓪ read-only), A the owner's Admin hat, RA rule-author mode.

## 2. Card-sort deck and first-click tasks

### 2.1 The deck (53 screen-level cards)

Participants see only the **card text** (the §2 screen name, with no group prefix such as "Terminal:" so the
text does not bias the sort); the route id, today's group and the RBAC column
are the moderator's key. A participant sorts only the cards their role can open (§4 step 2); the A cards go to
the owner alone.

| #   | Card text                                         | Route | Today's group (§2)   | RBAC              |
| --- | ------------------------------------------------- | ----- | -------------------- | ----------------- |
| 1   | Your default or last layout                       | R-100 | Trading Terminal     | O, M◑, V⓪         |
| 2   | A specific saved layout                           | R-101 | Trading Terminal     | O, M◑, V⓪         |
| 3   | A workspace popped out into its own window        | R-102 | Trading Terminal     | O, M◑, V⓪         |
| 4   | Watchlist manager (all saved groups)              | R-110 | Watchlist            | O, M, V           |
| 5   | One saved watchlist group                         | R-111 | Watchlist            | O, M, V           |
| 6   | Layout manager (create, duplicate, share)         | R-120 | Layouts & workspaces | O, M, V (list)    |
| 7   | Positions and orders, all accounts                | R-130 | Positions & Orders   | O, M◑, V◑         |
| 8   | Positions and orders for one account              | R-131 | Positions & Orders   | O, M◑, V◑         |
| 9   | One order's detail                                | R-132 | Positions & Orders   | O, M◑, V◑         |
| 10  | Trade group list                                  | R-140 | Trade groups         | O (M granted)     |
| 11  | One trade group's detail                          | R-141 | Trade groups         | O; M◑ view/select |
| 12  | New trade group wizard                            | R-142 | Trade groups         | O                 |
| 13  | Risk dashboard, all accounts                      | R-150 | Risk Dashboard       | O                 |
| 14  | Risk detail for one account                       | R-151 | Risk Dashboard       | O; M◑ own         |
| 15  | Rule list                                         | R-160 | Rule Builder         | O, M◑ RA          |
| 16  | A rule in the form editor                         | R-161 | Rule Builder         | O, M◑             |
| 17  | A rule in the node-graph editor                   | R-162 | Rule Builder         | O, M◑             |
| 18  | New rule wizard                                   | R-163 | Rule Builder         | O, M◑ granted     |
| 19  | A rule's fire history and simulation log          | R-164 | Rule Builder         | O, M◑, V◑ granted |
| 20  | Replay session picker                             | R-170 | Replay               | O, M, V           |
| 21  | A running replay session                          | R-171 | Replay               | O, M, V           |
| 22  | Trade list and filters                            | R-180 | Journal & analytics  | O, M, V⓪ granted  |
| 23  | One trade's record (MAE/MFE, tags, replay link)   | R-181 | Journal & analytics  | O, M◑, V◑ granted |
| 24  | Analytics dashboards (win rate, equity curve)     | R-182 | Journal & analytics  | O, M◑, V◑ granted |
| 25  | Alerts centre (list, create, mute, snooze)        | R-190 | Alerts               | O, M, V◑ own      |
| 26  | One alert's detail and editor                     | R-191 | Alerts               | O, M, V◑          |
| 27  | Settings home                                     | R-200 | Settings             | O, M, V           |
| 28  | Profile, password and two-factor                  | R-201 | Settings             | O, M, V           |
| 29  | Hotkey map editor                                 | R-202 | Settings             | O, M, V           |
| 30  | Theme, density and accessibility preferences      | R-203 | Settings             | O, M, V           |
| 31  | Notification channel preferences                  | R-204 | Settings             | O, M, V           |
| 32  | Window and monitor preferences                    | R-205 | Settings             | O, M, V           |
| 33  | Admin home (users, accounts, health, audit tiles) | R-300 | Admin                | A                 |
| 34  | Users and roles                                   | R-301 | Admin                | A                 |
| 35  | One user's role and granted accounts              | R-302 | Admin                | A                 |
| 36  | Create a manager or viewer                        | R-303 | Admin                | A                 |
| 37  | Exchange accounts and sub-accounts                | R-310 | Admin                | A                 |
| 38  | One exchange account's detail                     | R-311 | Admin                | A                 |
| 39  | Add an exchange account                           | R-312 | Admin                | A                 |
| 40  | API keys across all accounts                      | R-320 | Admin                | A                 |
| 41  | One API key's permissions and expiry              | R-321 | Admin                | A                 |
| 42  | Rotate an API key                                 | R-322 | Admin                | A                 |
| 43  | Per-account profiles                              | R-330 | Admin                | A                 |
| 44  | One account profile (leverage, sizing, SL/TP)     | R-331 | Admin                | A                 |
| 45  | Recorder and retention                            | R-340 | Admin                | A                 |
| 46  | System health (ingestion lag, WS, queues)         | R-350 | Admin                | A                 |
| 47  | Feature flags                                     | R-351 | Admin                | A                 |
| 48  | Trade-group administration (all groups)           | R-352 | Admin                | A                 |
| 49  | Global risk policy                                | R-353 | Admin                | A                 |
| 50  | Security centre                                   | R-354 | Admin                | A                 |
| 51  | Backups and restore                               | R-355 | Admin                | A                 |
| 52  | Maintenance mode control                          | R-356 | Admin                | A                 |
| 53  | Audit log                                         | R-360 | Admin                | A; O⓪, M◑ own     |

### 2.2 Open-sort instructions (read aloud)

1. "Here are cards for the screens you can open. Put together the ones you would expect to find together."
2. "Make as many or as few piles as you like. A card that fits nowhere can stay on its own."
3. "Name each pile with the word you would look for in a menu."
4. "Think aloud as you go; there are no wrong answers. We are testing the menus, not you."
5. The moderator never names a group, a route or the rail; questions about a card get "what do you think it
   is?". Note the pile names in the participant's words and the cards they hesitate over.

### 2.3 First-click tasks per persona

Starting point for every task: the Terminal (R-101) with the rail expanded and the palette closed. The first
click (or first key) counts: a rail item, a top-bar control, `Ctrl+K` then a typed word, or the user menu.
"Expected first click" is today's path; **none** means no visible entry exists today (§3).
The targets of O4, M1, M2 and M3 are `:param` routes, which Navigate never lists (N-7): those tasks
score against the list route a participant reaches first (R-140 for O4 and M3, R-130 for M2); M1 has no
list route, so it scores the path to R-150 or R-151.

| Task | Persona | Prompt (read aloud)                                    | Target | Expected first click (today)              |
| ---- | ------- | ------------------------------------------------------ | ------ | ----------------------------------------- |
| O1   | O       | "Open your Swing 4H workspace."                        | R-101  | rail Terminal tree, or TopBar switcher    |
| O2   | O       | "See open positions across all accounts."              | R-130  | none in the rail; `Ctrl+K`                |
| O3   | O       | "Freeze one manager's account."                        | R-150  | none in the rail; `Ctrl+K`                |
| O4   | O       | "Change which accounts a trade group sends orders to." | R-141  | none in the rail; `Ctrl+K`                |
| O5   | O       | "Review last week's losing trades."                    | R-180  | rail Journal                              |
| A1   | A       | "Rotate the key on the main account."                  | R-322  | user menu or rail Admin                   |
| A2   | A       | "Let a manager author rules."                          | R-302  | user menu or rail Admin                   |
| A3   | A       | "Find out why market data is lagging."                 | R-350  | user menu or rail Admin                   |
| A4   | A       | "Find who cancelled an order this morning."            | R-360  | user menu or rail Admin                   |
| M1   | M       | "Check whether your account is locked out."            | R-151  | none (rail and palette both lack it, N-1) |
| M2   | M       | "Close a position on your account."                    | R-131  | none in the rail; `Ctrl+K`                |
| M3   | M       | "Pick the trade group you were given."                 | R-141  | none in the rail; `Ctrl+K`                |
| M4   | M       | "Snooze a price alert until tomorrow."                 | R-190  | rail Alerts                               |
| M5   | M       | "Find your own actions from yesterday."                | R-360  | none (rail and palette both lack it, N-4) |
| RA1  | RA      | "Start a new rule as a graph."                         | R-163  | rail Rules                                |
| RA2  | RA      | "See why a rule fired twice."                          | R-164  | rail Rules                                |
| V1   | V       | "Watch the shared footprint layout."                   | R-101  | rail Terminal tree, or TopBar switcher    |
| V2   | V       | "Replay last Tuesday's session."                       | R-170  | rail Replay                               |
| V3   | V       | "Switch to the light theme."                           | R-203  | rail Settings, or `Ctrl+K`                |
| V4   | V       | "Find the alerts you set."                             | R-190  | rail Alerts                               |

A first click scores **direct** (a rail item or a visible control on the expected path), **indirect** (a
working path that is not visible, such as `Ctrl+K` and a typed word) or **miss**; direct and indirect are
tallied separately, and time to first click is noted but not gated.

## 3. Heuristic evaluation of the current IA `(heuristic)`

Surfaces evaluated: the rail as built (`navItems.ts`: Terminal, Rules, Journal, Replay, Alerts, Settings,
Admin on `Alt+1..7`), SCR-011's rail tree and switcher, the palette groups (E10-D03: the empty-query Recent and Suggested, then
Navigate, Panel, Symbol, Action, Setting; #5280's `GROUP_ORDER` carries only the last five) and #5280's Navigate source (every manifest route without a
`:param`, labelled from `titles.ts`).

| ID  | Finding `(heuristic)`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | Heuristic                | Conf. | Pri |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ | ----- | --- |
| N-1 | Six of the eleven non-admin groups reach the rail; Positions & Orders, Risk Dashboard, Trade groups, Watchlist and Layouts do not, although `10` §8 rates Positions & Orders ●●● for both P1 Owner and P2 Manager and Risk Dashboard ●●● for the Owner and ●● (own) for the Manager. For a Manager, R-150 is owner-only and R-151 takes `:accountId`, so M1 has no rail and no palette path (like M5); O2–O4, M2 and M3 depend on recall of a palette word. `navItems.ts` already records this as plan gap 3. | H6, H7; `05` §3.1 item 2 | High  | 1   |
| N-2 | Admin sits in the rail (owner only), while `12` §1.1 puts it in the user menu "to reinforce that Admin is a hat" (`navItems.ts` plan gap 1). Two homes for one destination; A1–A4 test which one the owner reaches for.                                                                                                                                                                                                                                                                                       | H4                       | High  | 2   |
| N-3 | One destination, two names: the rail says "Terminal" (R-100), the palette row for R-100 says "Terminal default layout" and R-101's title is "Terminal". The palette also lists "Settings" (R-200, a redirect) and "Profile and security" (R-201), which open the same page.                                                                                                                                                                                                                                   | H4, H8                   | High  | 2   |
| N-4 | R-360 admits the non-admin Owner (read-only) and a Manager (own actions) by role, yet Navigate drops every `/admin/*` row without `admin:read` and the rail has no audit item, so M5 has no visible entry. Whether a non-admin path should exist is an RBAC question for the owner, not a wording fix.                                                                                                                                                                                                        | H6, H10                  | High  | 1   |
| N-5 | "Layout" and "workspace" share the Terminal group: R-101 is a "saved layout", R-102 a "workspace", SCR-011 lists "recent workspaces" under Terminal and R-120 is the "Layout manager". E15-D01 §1 fixed workspace = the tab set and layout = one arrangement inside it; the route titles predate that rule.                                                                                                                                                                                                   | H2, H4                   | Med   | 2   |
| N-6 | `Alt+1..9` (rail) and `05` §3.2's Drawing row `Alt+1..4` collide while a chart has focus; already logged as E14-D02 C8 and E14-D03 A9. `12` §1.1 still says the rail jumps on `Ctrl+1..9`, which `05` §3.2 gives to layouts. Adding rail items (N-1) must keep each item's digit stable.                                                                                                                                                                                                                      | H4; `05` §3.1 item 2     | High  | 1   |
| N-7 | Strengths kept: the rail asks the route guard (`evaluateAccess`) and leaves a gap rather than renumbering, so a role's digits never shift; Navigate skips `:param` detail routes, which are not destinations; the switcher sits both in the rail tree and the TopBar (H7, two paths to one list).                                                                                                                                                                                                             | H4, H7                   | High  | —   |

The card sort tests N-1, N-2 and N-5 (do participants pile Positions, Risk and Trade groups next to Terminal,
and Admin apart?); the first-click tasks test N-1, N-2 and N-4 (M1 and M5 have no path, so they fail by construction).

## 4. Ready-to-run protocol: card sort and first click (for the owner)

1. **Setup.** The 53 cards of §2.1 printed or on a local, offline board (no third-party sorting service: no
   analytics sink exists under `04` §15.3, E15-D01 OQ-11). Use placeholder accounts and symbols only; never a
   real account id, balance or key. Recordings follow E15-D01's interim rule (OQ-2): never in the repository,
   deleted when the owner approves the addendum. Consent reuses `e15-layouts/consent-form.md`'s wording.
2. **Participants.** The owner (O, then A, then RA), each available manager (M, RA if granted) and each
   viewer (V). Each sorts only the cards their role opens (§2.1 RBAC column); the owner sorts all 53.
3. **Pilot, then open sort.** Run the whole protocol once with one participant first (the owner, or a
   colleague with placeholder data), fix unclear card text or instructions, and discard that run. Then the
   **open sort** (about 15 minutes): §2.2's script, the cards dealt in a fresh shuffled order for every
   participant; photograph or export the piles and their names.
4. **First click** (about 10 minutes): the role's tasks from §2.3 in a shuffled order, on the running app or the
   E10-D03 boards with click-through; record the first click and score it direct, indirect or miss.
5. **Debrief** (about 5 minutes): "Which screen was hardest to find? What would you call the menu for it?"
6. **Gate, card sort.** A §2 group is confirmed when at least two thirds of participants (rounded up) put at
   least two thirds of its cards (rounded up) in one pile; an unconfirmed group goes to the owner with the
   pile names participants used.
7. **Gate, first click.** Each task passes when at least two thirds of its persona's participants (rounded up)
   click direct or indirect; any task with a miss by the owner goes to the owner. Indirect is a pass for this
   bar only. **F-5's gate uses the direct rate alone**, for the tasks N-1 predicts have no rail entry (O2, O3,
   M2; M1 joins as its path is missing): F-5 counts as confirmed when fewer than two thirds of a persona's
   participants click direct on any of them, or when the open sort piles Positions or Risk cards with the
   Terminal cards.

Record real results in a new dated section of this file once run — do not overwrite the `(heuristic)`
sections above; append.

## 5. Health-chip vocabulary `(heuristic)`

### 5.1 The words today

| Source                                        | Words                                                                        | Status                      |
| --------------------------------------------- | ---------------------------------------------------------------------------- | --------------------------- |
| CMP-210 `state` (spec)                        | ok · warn · error · stale ("stale since hh:mm:ss") · unknown                 | merged spec                 |
| CMP-210 as built, "Connection: <word>"        | live · connecting · reconnecting · offline (the retry stopped)               | PROPOSED for #325           |
| CMP-210 as built, "WS latency: <word>"        | ok · slow · over budget · unavailable                                        | PROPOSED for #325           |
| CMP-076 ConnectionStatus `status`             | live · delayed · stale · reconnecting · offline; "Connecting…" first connect | merged; Connecting PROPOSED |
| `05` §4 item 1, the connection/health example | Connected · Degraded · Disconnected, each with ✓ / ⚠ / ✕                     | standard (an example)       |

### 5.2 Findings

| ID   | Finding `(heuristic)`                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | Heuristic                    | Conf. | Pri |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- | ----- | --- |
| HC-1 | The connection signal has three vocabularies: the as-built Connection chip's words (live · connecting · reconnecting · offline) lack CMP-076's `delayed` and `stale` (the CMP-210 spec state set does include `stale`), so two chips showing the same feed could disagree: "Connection: live" where CMP-076 says "Stale 7 seconds". A user who glances at the wrong chip reads stale data as live. No cited surface renders both for one feed, so this is a reading of the two specs. | H1, H4; `05` §4              | Med   | 0   |
| HC-2 | "offline" is defined twice: CMP-210 as built, "the retry stopped"; CMP-076, "a fatal close or `bye.reconnect: false` only". They likely coincide, but nothing states it; one definition must own the word.                                                                                                                                                                                                                                                                            | H4                           | Med   | 1   |
| HC-3 | Two words for "no reading": latency `unavailable` and the CMP-210 state `unknown` (feed behind the chips down). One concept, one word.                                                                                                                                                                                                                                                                                                                                                | H4, H8                       | High  | 2   |
| HC-4 | `warn` is read aloud in the accessible name "Recorder: warn"; it is a code token, not a word a trader says (the others are adjectives).                                                                                                                                                                                                                                                                                                                                               | H2; `05` §2 (Understandable) | Med   | 2   |
| HC-5 | "WS latency" and "over budget" are engineering words (a WebSocket, an SLO budget); a Manager or Viewer (`10` §3, §4) may not map "over budget" to "orders and data are arriving late". The owner likely does.                                                                                                                                                                                                                                                                         | H2                           | Low   | 2   |
| HC-6 | Placement drifts: CMP-210's purpose says "in the top bar", E10-D03 draws a TopBar HealthChips row, the build puts two chips in the CMP-208 StatusBar. `12` §1.1 splits it again (connection in the top bar, latency in the status bar). A first-click probe answers where users look.                                                                                                                                                                                                 | H4                           | High  | 1   |
| HC-7 | The as built avoids "degraded" on purpose (the API's and the shell mode's word); `05` §4's example uses it. The example is illustrative, so no `05` change is needed, but the comprehension task should include it as a distractor.                                                                                                                                                                                                                                                   | H4                           | Med   | 2   |
| HC-8 | Strengths kept: glyph + word + colour on every chip (`05` §4 item 1); the value sits outside the live region and CMP-076 owns no region, so nothing is announced per tick (`05` §6.2); "stale since hh:mm:ss" states the age (H1).                                                                                                                                                                                                                                                    | H1; `05` §4, §6.2            | High  | —   |

## 6. Ready-to-run protocol: health-chip comprehension (for the owner)

1. **Setup.** Static exports of each chip in each word of §5.1 (CMP-210's five states, the four connection
   words plus `delayed` and `stale`, the four latency words) plus two distractors ("Degraded", "Disconnected"),
   in colour and in greyscale, shown alone and inside the E10-D03 TopBar and the StatusBar. Placeholder
   values only.
2. **Participants.** As §4 step 2, the same session or a separate one.
3. **Comprehension** (about 10 minutes): each chip in a shuffled order. Ask "What is happening?" then "What
   would you do now?". Score **correct** when the answer matches §5.1's definition, **partial** when the
   meaning is right but the action is not, **misread** otherwise.
4. **Danger probe:** for `stale`, `delayed`, `reconnecting` and `offline`, ask "Can you trust the price on the
   chart right now?". A "yes" is a **dangerous misread**.
5. **Placement** (about 3 minutes): on the shell at 1920×1080, "Where would you look to see if your data is
   live?"; record the first fixation region by pointing, not eye tracking.
6. **Gate.** Each word passes when at least two thirds of participants (rounded up) score correct or partial,
   in both colour and greyscale; for `stale`, `delayed`, `reconnecting` and `offline`, only **correct**
   counts (partial is a fail); **zero** dangerous misreads across all participants (Pri 0, HC-1). A failing
   word is replaced by the best-scoring candidate the participants used and re-tested.

Record real results in a new dated section of this file once run — do not overwrite the `(heuristic)`
sections above; append.

## 7. Feed table (advisory; every row PROPOSED, no merged spec edited)

| ID   | To                              | PROPOSED delta                                                                                                                                                                                         | From          |
| ---- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------- |
| F-1  | #5280 E10-S05                   | PROPOSED: the R-100 Navigate row reads "Terminal", the rail's word; the route title may stay.                                                                                                          | N-3           |
| F-2  | #5280 E10-S05                   | PROPOSED: Navigate omits R-200, a redirect to R-201, so one page has one row; the rail keeps R-200.                                                                                                    | N-3           |
| F-3  | owner (RBAC), then #5280        | PROPOSED: decide whether the non-admin Owner's and a Manager's reduced audit view (R-360) gets an entry (a user-menu item or a non-admin path); until ruled, Navigate keeps today's `admin:read` rule. | N-4           |
| F-4  | #476 E15-S03                    | PROPOSED: the switcher and the rail tree say "workspace" for the tab set and never "layout" (E15-D01 §1), and both list the same workspaces in `sort_order`; tasks O1 and V1 join #476's QA plan.      | N-5, N-7      |
| F-5  | owner (CMP-071, plan gaps 1, 3) | PROPOSED, after §4's gate: add Positions and orders (R-130) and Risk dashboard (R-150) to the rail and move Admin to the user menu (`12` §1.1); existing digits stay, the new items take free digits.  | N-1, N-2, N-6 |
| F-6  | CMP-210 (#325 E17-D02)          | PROPOSED: the connection chip reads CMP-076's words (live · delayed · stale · reconnecting · offline, "Connecting…" first), and CMP-076's definition of `offline` owns the word.                       | HC-1, HC-2    |
| F-7  | CMP-210 (#325 E17-D02)          | PROPOSED: the accessible name says "warning" for `warn` (the prop value stays `warn`).                                                                                                                 | HC-4          |
| F-8  | CMP-210 (#325 E17-D02)          | PROPOSED: one word for "no reading" across chips, `unknown` (CMP-210's own), replacing latency `unavailable`.                                                                                          | HC-3          |
| F-9  | CMP-210 (#325 E17-D02)          | PROPOSED: the label "Latency" replaces "WS latency"; "over budget" stays until §6's gate picks a word.                                                                                                 | HC-5          |
| F-10 | owner, then CMP-210             | PROPOSED: one placement for the chips (the as-built StatusBar or E10-D03's TopBar row), recorded in CMP-210's purpose; the as built stands until ruled.                                                | HC-6          |

## 8. Owner-walkthrough checklist (ready to post on #1479 before merge; owner approval pending)

1. Ratify the ruled BQ 1 (a): this study runs now in the E15 lane, R1, on #1479 (Deviations 1).
2. Accept the text-only form despite the mandatory Penpot page and PNG evidence rule (Deviations 2), or
   ask for a research board of §2.1 and §5.1.
3. Read §3 N-1 and N-4 (the Pri 1 rows) and §5.2 HC-1 (the Pri 0 row).
4. Rule F-3: does the reduced audit view (R-360) get a non-admin entry, and where?
5. Rule F-5 now, or after §4's gate: Positions and Risk in the rail, Admin in the user menu.
6. Rule F-10: the chips' one placement, StatusBar or TopBar row.
7. Accept or override F-1, F-2, F-4 and F-6..F-9 by exception; name only those you override.
8. Accept §4's and §6's two-thirds bars and the zero-dangerous-misread gate, or set others.
9. When you run §4 or §6, append the results here in a dated section; never overwrite.

## 9. References

`docs/plan/05-accessibility-standard.md` §2, §3.1, §3.2, §4, §6.2; `10-personas.md` §0, §8; `12-sitemap.md`
§1.1, §2; `14-screens-catalogue.md` SCR-011, SCR-012; `15-component-catalogue.md` CMP-059, CMP-071,
CMP-076, CMP-210; `docs/design/E10/E10-D02.md` (Deferred research), `E10-D03.md`, `research-findings.md`;
`docs/design/research/e15-layouts/findings.md` §1, OQ-1, OQ-2, OQ-11, OQ-13; `docs/design/E14/E14-D02.md` C8;
Nielsen's ten heuristics (https://www.nngroup.com/articles/ten-usability-heuristics/).
