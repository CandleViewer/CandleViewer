# E40-C5 Charter: Break the alert editor with the keyboard only

- Ticket: E40-Q01 (#1202) writes it; E40-Q02 (#1203) Part C runs it · Format: session-based (`docs/plan/03-testing-strategy.md`
  §11.2) · Timebox: 60 min · Also called: the keyboard-only hunt
- Status: written, not run. Its screens (SCR-090, SCR-091, SCR-092, SCR-014, SCR-115) are not on `main`: they wait on
  E40-S01 (#1129) and E40-S02 (#1130), whose UI slices wait on E40-D02's design approval (C-10.3). Until they ship, a
  session can probe only the API and WS surface (`/alerts*`, `/alerts/deliveries*`, `/notifications`, topic `alerts`), and
  its sheet says so; nothing here counts as a run against the shipped UI.
- Format note: this is the pre-run variant of the E09 charter format; the post-run debrief fields (areas covered, not probed,
  anomalies) are filled in the session sheet below.
- Setup: staging on demo with the replay feed and the fake clock (plan section 0; until FI-6's stack switch lands, the 60 s edge, quiet hours / DST and snooze / expiry run in-process only); recorded, redacted fixtures only, no live
  exchange (C-13.5); test accounts with no account id, key or balance in any note or capture. Seed a realistic state, not an
  empty install: a populated alert set across the three families and a busy history (E40-Q02 Part C, Technical notes).
- Mission: author, edit, duplicate, snooze and delete alerts without a pointer, and find where the keyboard dead-ends or the editor lies.
- Areas:
  - SCR-091 end to end: condition builder, symbol and interval scope, evaluate-on, trigger mode, channels, message, save
  - validation: the ValidationPanel's focus movement (E40-S01); server `422` issues mapped to fields; the `412` strip and `Reload` (X06)
  - the estimated warning and the vocabulary-unavailable state (E06, E10)
  - SCR-090 row menu on `Shift+F10` and the menu key, bulk selection with `Space`, the bulk bar (G03)
  - SCR-092 toasts and the drawer: focus on open, `Esc` returns focus to the opener
- Oracles (each also: an uncaught page error or a console error):
  - O5.1 a control or action that the keyboard cannot reach or operate (03 §12; C-14.1)
  - O5.2 focus lost to the page body, trapped, or not returned on close
  - O5.3 a saved alert that differs from what the restatement said
  - O5.4 a draft lost on a `412`, a `503` or a refused save
  - O5.5 a live region that announces every tick instead of once per result
- Plan cases it leans on (`docs/qa/test-plans/e40-alerts.md`): E40-TC-A17, E06, E10, G02, G03, X06; the formal a11y audit is E40-Q02
- Risks:
  - the editor exists only as a design (E40-D02 §3, §7.2) until E40-S01 ships; the whole charter waits on it
  - a keyboard trap in a modal blocks a trader mid-session

## Session sheet (one per session, attached to E40-Q02)

| Field                 | Content                                                                                        |
| --------------------- | ---------------------------------------------------------------------------------------------- |
| Charter, tester, date | this charter's id; who ran it; the date (UTC)                                                  |
| Build                 | the `main` commit and the flags on; which surfaces were live and which were stubs              |
| Duration              | planned and actual minutes, split into setup, testing and bug investigation                    |
| Areas covered         | the areas above that were reached, and those that were not                                     |
| Oracles applied       | the oracle ids used, and the plan cases each session touched                                   |
| Bugs                  | one line each with steps, the expected and the actual, severity per `03` §11.3, the issue link |
| Questions             | open questions, each raised on its owning ticket, never answered by guessing                   |
| Follow-up charters    | the seams worth another session, recorded even when they cannot run this sprint                |
