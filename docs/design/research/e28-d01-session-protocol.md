# E28-D01 — Session protocol: risk policy per account and fan-out (ready to run; optional, post-GA)

- **Companion to:** [`e28-risk-policy-fanout.md`](e28-risk-policy-fanout.md) (E28-D01, issue #820), "the report";
  RQ-, H-, W-, F-, CD-, AD-, C- and OQ- ids refer to it (tasks here are TK1–TK7, so they never clash with the persona themes T3–T11), as do the `path:line` pin and shorthand (report front matter),
  and a bare "§n" is a section of this file.
- **Status:** not yet run, and not a gate. The sessions are an optional post-GA line on the E28 epic, per the orchestrator's ruling of 2026-10-29, on the #2701 precedent for research tickets of this shape (ledger 1 rows 18, 61, 106; report Deviation 1). Every duration below is an allocation
  inside a 45-minute session, not an observation; no participant, timing, count, score or quote exists.
- **Ready to run: partly.** The interview (part A), the concept test (part C) and the card sort (part D) run on paper
  today (ticket Technical notes: paper and whiteboard, so no participant is anchored by a UI). The think-aloud tasks
  (part B) need the report's boards 04–06, which land in the boards PR (report §1); until then the moderator draws
  them on paper from the report's text.
- **Roles:** the moderator is never the participant. The owner is tagged **P1** on every sheet, because the owner also
  approves the report; someone else moderates the owner's session. No answer reaches an agent, a chat or this
  repository (§2).

## 1. Who takes part (recruiting rule)

- **The owner** (P1, and P1 wearing the P4 hat, `10:175`) is the one participant every run needs: only the owner edits
  profiles and writes group definitions (`10:294`, `10:300`; ruled D8, ledger 2 row 18).
- **Account managers** the owner names (P2a and P2b, `10:111-112`), for TK6 and TK7 only: a Manager reads their own
  limits and selects granted accounts, and edits nothing (`10:300`).
- **Accessibility:** at least one session runs keyboard-only on the boards' click-through, if the boards PR builds one;
  a screen-reader user joins if the owner knows one. Otherwise the gap stays research debt and E28-D05's review
  stands in (ticket Accessibility notes; report §15, §17).
- **Never fabricate a participant.** The ticket's "at least four" is not a gate here; a single owner session is a valid
  first run, and the report's AC1 row states how many ran.

## 2. Consent and data handling

**Opening script (read verbatim).** "Some rules in CandleViewer are fixed and are not what we test today. We want to
learn how you decide risk per account and how you think about trading several accounts at once — not whether those
rules should change." The script names no rule: the moderator states the fixed ones only in the debrief (§8).

**Consent script (read verbatim; no recording without a yes).** "We record the audio and the paper. Everything you see
is made up: no real balance, account number, key or position appears. Please never say a real balance, account number
or position aloud. The recording and the notes stay on the owner's encrypted host — never in the repository, Penpot,
GitHub, RelayRoom, any chat or any AI tool — and are deleted once the findings are signed off. Is that all right?"

**Data rules** (ticket Security notes; the E27-D01 rule, `E27R:84-89`):

- **Placeholders only:** accounts `Main`, `sub_001`, `sub_002`, `sub_003`; the group "Core3"; the numbers of the
  stories' own scenarios (equity 10 000 USDT, risk 0.5 %, a 120 USDT stop, `11:547-550`). No real balance, UID, key or
  position appears in any card, board or note.
- **Nothing connected:** the stimulus is paper and the boards, never the live app.
- **Confidential:** recordings and notes stay on the owner's encrypted host (report Deviation 4); both are deleted at
  sign-off, and the deletion is recorded on #820 and in the addendum (§9).
- **AI tools:** none receives a recording, a note or an answer.

## 3. Session plan (45 minutes, remote or in person, paper and whiteboard)

| Part                          | Minutes | Content                                           |
| ----------------------------- | ------- | ------------------------------------------------- |
| Consent and primer            | 3       | §2 scripts                                        |
| A Interview (RQ1–RQ4)         | 10      | A1–A5 (§4)                                        |
| B Think-aloud tasks (RQ4–RQ6) | 14      | TK1–TK5 for the owner; TK6–TK7 for a manager (§4) |
| C Concept test (RQ7)          | 6       | the two cards, counterbalanced (§5)               |
| D Card sort (RQ8)             | 8       | SCR-131's fields into sections (§6)               |
| Debrief                       | 4       | §8                                                |

## 4. Interview and tasks (parts A and B)

**Interview guide (probes, not a script; never correct a belief during the interview).**

- A1 "How do you decide how much to risk on an account today? Walk me through the last time it changed." (RQ1)
- A2 "Is that decision per account, per trade, or both?" (RQ1; note whether the default is read as a ceiling, D7)
- A3 "When you size a trade, what number do you start from?" (RQ2; record the first unit named: USDT, %, R, quantity)
- A4 "What does 'max daily loss' mean to you — what counts toward it?" (RQ3; record the reading before any card)
- A5 "When you trade several accounts at once, is that a set you keep, or one you pick each time?" (RQ4)

**Think-aloud tasks** (stimulus: boards 04–06 or the moderator's paper drawings; prompts read verbatim; the moderator
waits 15 s after a pause before helping, and only on request).

| Task                                           | Prompt                                                                                         | Observe and record                                                     |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| TK1 Profile list (SCR-130)                     | "Which profile will size the next trade on `sub_001`, and could another one size it bigger?"   | whether the default reads as the ceiling (B1, F-1)                     |
| TK2 New profile (SCR-131)                      | "Set up `sub_002` so it can trade BTCUSDT."                                                    | whether they find the five caps and the symbol list (F-2, F-3)         |
| TK3 Symbols (SCR-133)                          | "Let `sub_003` trade everything except DOGEUSDT."                                              | which control they reach for: "all symbols" plus a block (B3, F-13)    |
| TK4 Group (SCR-062)                            | "Make a group 'Core3' of `Main`, `sub_001` and `sub_002`. Who can use it?"                     | whether the group is read as a permission (C4, F-14)                   |
| TK5 Preview (SCR-061)                          | the "2 of 3 ready" frame, then the "Not sent" frame (CD-9, CD-10). "What will happen on Send?" | whether they tell skip from refused-whole, and what they change (F-17) |
| TK6 Manager: limits (SCR-061, granted account) | "Before you trade, what are your limits on this account?"                                      | where they look; what they cannot find (F-22)                          |
| TK7 Manager: override                          | the "capped by profile: 5x" frame. "Why can't you go higher?"                                  | whether the cap reads as policy, not fault (H6)                        |

## 5. Concept test (part C; the worked example)

The report's cards U and R (report §7), same numbers, one at a time. Half the sessions see U first, half R first,
alternating by session number; the order is written on the sheet before the session. For each card: show it for 10 s,
remove it, ask "If the stop is hit, how much do you lose, in USDT?", record the answer verbatim, then ask "Would you
want the other one too?". Score **correct** (about 50 USDT), **partial** (the right number in another unit) or
**misread** (a price or a distance read as the loss). **Until a session runs, every row is unmeasured**; H7 is scored
only from these answers.

## 6. Card sort (part D; SCR-131 grouping)

One card per field of the report's §8 table (plain-language name, no column name), shuffled; six header cards
(Leverage & margin, Sizing, Brackets, Risk caps, Symbols, Safety) and one blank "other" card. The participant sorts,
may rename a header or start a new pile, and thinks aloud. Record each card's pile and any new pile's name. No card
exists for the native stop: the moderator places the statement "Every order carries a stop-loss at the exchange"
(CD-6) under Safety before the sort and says it is fixed. **Decision rule:** a card two or more participants place
outside the report's section is a finding against AD-5; a new pile two or more participants make is the documented
alternative (OQ-1).

## 7. Keyboard-only pass (if a click-through exists)

The mouse is disconnected for TK5. Tab to the preview table, read each row's state, reach the refused-whole summary
and Send. Record the Tab count to each control, any state shown by colour only, whether a disabled Send says why
(report AX-4) and where focus lands after a refusal (AX-5).

## 8. Measures, analysis and debrief

- **Per session:** A1–A5 notes; per task the action sequence, the error and recovery points; per card the score and the
  verbatim restatement; the card-sort piles.
- **Hypotheses:** H1–H8 scored confirmed, refuted or not tested.
- **Two reviewers** (ticket Test plan): two independent affinity passes, then reconciled; the owner never codes their
  own session. A pattern in one session is a **signal**; in two or more, a **finding**.
- **Debrief (4 minutes):** the moderator states the fixed rules the session held back — every order and every leg
  carries a native stop that cannot be turned off; the default profile is the ceiling; a request that would go past it
  is refused whole, never trimmed; the lockout counts realised loss, and a new trade's headroom also counts open risk.
  Then: "Which of these cost you the most time today, and what would have made it read as protection?" Recorded
  verbatim; it feeds E28-D03's copy and is never a reason to change a locked rule (report §14).

## 9. The addendum rule and recording sheet

Results are appended to the report as "Addendum YYYY-MM-DD — sessions", never as a new document, with synthesised
findings only: the number of sessions run, the H scores, the card U / R scores, the card-sort placements against AD-5,
new findings with their F-ids and the AC rows they close; the deletion of the recordings is noted there and on #820.
No participant's real balances, accounts or positions enter the addendum, the report or #820.

**Recording sheet (template; empty until a session runs):** session id · date · persona (P1 / P2a / P2b) ·
keyboard-only (y/n) · screen reader (y/n) · stimulus (paper / boards) · card order (U→R / R→U) · A1–A5 notes · TK1–TK7
sequences and reasons · card U and R answers and scores · card-sort piles · keyboard pass counts and blockers ·
debrief verbatim.
