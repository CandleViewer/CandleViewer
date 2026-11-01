# E41-D01 — Session protocol v0 (not piloted): reviewing yesterday's session in the journal

- **Companion to:** `e41-journal-review.md` in this folder, "the memo", whose ids (RQ, F, WD, OQ) and sections ("memo §n") are cited; AC1–AC3 are the ticket's three acceptance scenarios (issue #1017).
- **Status:** not yet run. **No participant, session, timing or quote exists**; the durations below are allocations within a 45-minute session (ticket Scope), booked as 50 minutes. The owner may run it, or confirm the defaults by the memo §10 walkthrough instead.
- **Pilot:** before the first session the owner does one dry run of the memo §10 walkthrough with these prompts; any prompt that leads the answer is reworded first.

## 1. Purpose and probes

Test, before E41-D02 / D03 draw hi-fi, how the owner (P1) and the account managers (P2) review closed trades today and which of the memo's PROPOSED decisions survive contact with their habits. The five research questions (memo §2) are the probes:

- **Probe 1 (RQ1):** what started the last review, and when.
- **Probe 2 (RQ2):** on the baseline artefact, which fields the eye goes to first on a closed trade.
- **Probe 3 (RQ3):** how tags are written today — a fixed list, free words, or both.
- **Probe 4 (RQ4):** whether DEMO results count, and for what.
- **Probe 5 (RQ5):** what leaves the tool, in which format, for whom.

**Locked, not under test:** DEMO and LIVE never summed (`14` SCR-093 checklist), so WD-1 and WD-2 get a comprehension check only ("can DEMO be inside this total?"); every chart has a table alternative (`14` SCR-095); RBAC scope is server-side (C-12.4).

## 2. Participants, consent and data handling

- **Participants:** three sessions, one person each — the owner and two P2 account managers, at least one of them a swing manager (P2b). P3 Viewer is covered by the memo §4 walkthrough only.
- **Voluntary:** P2 managers report to the owner, so taking part is voluntary, declining has no consequence, and results are never attributed to a named manager.
- **Consent:** written, per session, read aloud before step 1: "This session is recorded for notes; a paraphrase without your name may appear in a design document; you may stop or turn the recording off at any time." A no-recording option keeps hand notes only. The signed form is held owner-local.
- **Data:** stimuli carry synthetic rows only (§3). The participant's own spreadsheet stays on their screen and is not shared into the recording unless redacted. Recordings stay owner-local (never a third-party service, C-1.2), are deleted after 90 days, and only redacted stills (no account id, balance or key identifier) may enter a research artefact. No live Bybit or app backend is touched.

## 3. Stimuli

**Readiness:** steps 3–5 need the memo §0 boards. Until they are drawn, run them on the text-only fallback: the memo §7.1 copy deck and the memo §6 Check column, printed as cards.

1. **The baseline artefact** — the participant's own spreadsheet or notes, opened by them; never copied into the repository.
2. **Boards 02–09** of the memo §0 once drawn, as Penpot frames or printed cards, each also read aloud; before that, the fallback cards.
3. **Three statements to react to:** a LIVE-only total, a 12-trade analytics view with the caveat, an auto tag marked `auto`.
4. **Synthetic sample:** a 12-trade and a 42-trade set, one trade group with its aggregate row, one auto tag, one trade with no recording; invented symbols, accounts and P&L.

## 4. Session order (45 minutes)

| Step | Minutes | Activity                                                                      | Probe / decision                          |
| ---- | ------- | ----------------------------------------------------------------------------- | ----------------------------------------- |
| 1    | 5       | consent, context, the participant's role and accounts in words only           | —                                         |
| 2    | 10      | think-aloud over the baseline artefact: "show me how you looked at yesterday" | Probes 1, 2                               |
| 3    | 8       | tags in the baseline; then the SCR-096 board                                  | Probe 3; WD-7, WD-8                       |
| 4    | 7       | the three statements of §3 item 3                                             | Probe 4; WD-3, WD-4; WD-1/2 comprehension |
| 5    | 7       | SCR-093 → SCR-094 boards, including the context-not-recorded frame            | WD-5, WD-6                                |
| 6    | 5       | export: what, how often, to whom; then the export confirm                     | Probe 5; WD-10                            |
| 7    | 3       | debrief; anything the boards got wrong                                        | —                                         |

**If time runs short:** step 5 gives way first and keeps SCR-094 only (WD-6); WD-5 then rests on step 2.

## 4a. Tasks per decision under test

The moderator reads each prompt as written and adds only "say more" or "what would you expect?".

| WD       | Prompt                                                     | Observation recorded                                    | Pass line                                  |
| -------- | ---------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------ |
| WD-1/2   | "What does this total include?"                            | whether DEMO is named as excluded                       | DEMO is named as not inside the LIVE total |
| WD-3, -4 | "What does this view tell you about the last 12 trades?"   | whether the caveat and n are read before a rate is used | the caveat or n is mentioned unprompted    |
| WD-5     | "Find yesterday's losing trade; read me what you look at." | the first two fields named                              | R or net P&L is among the first two        |
| WD-6     | "What can you learn about this trade's market context?"    | whether "not recorded" is read as final, not loading    | no wait for a spinner is described         |
| WD-7     | "Rename this tag and merge it with that one."              | whether the affected-trade count is checked             | the count is read before confirming        |
| WD-8     | "This tag says auto. Remove it. What is kept?"             | whether removal is expected to leave a record           | a record of the removal is expected        |
| WD-10    | "Export this list. What is in the file?"                   | whether account data, environment and range are named   | all three are named from the confirm       |

**Walkthrough-only, not testable with P1 / P2:** WD-9 (group siblings), WD-11 (table view, P3), WD-12 (IA, not drawable by a participant), WD-13 (Viewer write controls T2, P3) and WD-14 (formula link) — checked in the memo §4 P3 walkthrough and §10.

## 5. Recording the outcome

Per session: one notes sheet coded by probe and by WD (`confirms` / `contradicts` / `silent`, against the §4a pass line), stored with the recording. After three sessions, a WD contradicted twice becomes a text revision of the memo plus a redraw of its board; each finding then drops its `(heuristic)` tag only where a session observed it.
