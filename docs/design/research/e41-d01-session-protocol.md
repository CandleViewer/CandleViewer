# E41-D01 — Session protocol: reviewing yesterday's session in the journal

- **Companion to:** `e41-journal-review.md` in this folder, "the memo", whose ids (RQ, F, WD, OQ) and sections ("memo §n") are cited; AC1–AC3 are the ticket's three acceptance scenarios (issue #1017).
- **Status:** not yet run. **No participant, session, timing or quote exists**; the durations below are allocations within a 45-minute session (ticket Scope). The owner may run it, or confirm the defaults by the memo §10 walkthrough instead.

## 1. Purpose and probes

Test, before E41-D02 / D03 draw hi-fi, how the owner (P1) and the account managers (P2) review closed trades today and which of the memo's PROPOSED decisions survive contact with their habits. The five research questions (memo §2) are the probes:

- **Probe 1 (RQ1):** what started the last review, and when.
- **Probe 2 (RQ2):** on the baseline artefact, which fields the eye goes to first on a closed trade.
- **Probe 3 (RQ3):** how tags are written today — a fixed list, free words, or both.
- **Probe 4 (RQ4):** whether DEMO results count, and for what.
- **Probe 5 (RQ5):** what leaves the tool, in which format, for whom.

**Locked, not under test:** DEMO and LIVE never summed (`14` SCR-093 checklist); every chart has a table alternative (`14` SCR-095); RBAC scope is server-side (C-12.4).

## 2. Participants, consent and data handling

- **Participants:** three sessions, one person each — the owner and two account managers (P1 + P2). P3 Viewer is covered by the memo §4 walkthrough only.
- **Consent:** written, per session, covering recording, notes and anonymised paraphrase; the participant may stop at any point.
- **Data:** the session shows real account identifiers and P&L, so recordings stay owner-local (never a third-party service, C-1.2), are deleted after 90 days, and only redacted stills (no account id, balance or key identifier) may enter a research artefact.

## 3. Stimuli

1. **The baseline artefact** — the participant's own spreadsheet or notes, opened by them; never copied into the repository.
2. **Boards 02–09** of the memo §0 once drawn, as Penpot frames or printed cards, each also read aloud.
3. **Three statements to react to:** a LIVE-only total, a 12-trade analytics view with the caveat, an auto tag marked `auto`.

## 4. Session order (45 minutes)

| Step | Minutes | Activity                                                                      | Probe / decision    |
| ---- | ------- | ----------------------------------------------------------------------------- | ------------------- |
| 1    | 5       | consent, context, the participant's role and accounts in words only           | —                   |
| 2    | 10      | think-aloud over the baseline artefact: "show me how you looked at yesterday" | Probes 1, 2         |
| 3    | 8       | tags in the baseline; then the SCR-096 board                                  | Probe 3; WD-7, WD-8 |
| 4    | 7       | the three statements of §3 item 3                                             | Probe 4; WD-1–WD-4  |
| 5    | 7       | SCR-093 → SCR-094 boards, including the context-not-recorded frame            | WD-5, WD-6, WD-12   |
| 6    | 5       | export: what, how often, to whom                                              | Probe 5; WD-10      |
| 7    | 3       | debrief; anything the boards got wrong                                        | —                   |

## 5. Recording the outcome

Per session: one notes sheet coded by probe and by WD (`confirms` / `contradicts` / `silent`), stored with the recording. After three sessions, a WD contradicted twice becomes a text revision of the memo plus a redraw of its board; each finding then drops its `(heuristic)` tag only where a session observed it.
