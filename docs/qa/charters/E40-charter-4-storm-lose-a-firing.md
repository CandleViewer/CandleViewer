# E40-C4 Charter: Fire a storm and try to lose a firing

- Ticket: E40-Q01 (#1202) writes it; E40-Q02 (#1203) Part C runs it · Format: session-based (`docs/plan/03-testing-strategy.md`
  §11.2) · Timebox: 75 min · Also called: the storm-conservation hunt
- Status: written, not run. Its screens (SCR-090, SCR-091, SCR-092, SCR-014, SCR-115) are not on `main`: they wait on
  E40-S01 (#1129) and E40-S02 (#1130), whose UI slices wait on E40-D02's design approval (C-10.3). Until they ship, a
  session can probe only the API and WS surface (`/alerts*`, `/alerts/deliveries*`, `/notifications`, topic `alerts`), and
  its sheet says so; nothing here counts as a run against the shipped UI.
- Format note: this is the pre-run variant of the E09 charter format; the post-run debrief fields (areas covered, not probed,
  anomalies) are filled in the session sheet below.
- Setup: staging on demo with the replay feed and the fake clock (plan section 0); recorded, redacted fixtures only, no live
  exchange (C-13.5); test accounts with no account id, key or balance in any note or capture. Seed a realistic state, not an
  empty install: a populated alert set across the three families and a busy history (E40-Q02 Part C, Technical notes).
- Mission: make the storm suppressor drop, duplicate or misplace a firing.
- Areas:
  - exactly 20, 21 and 25 firings in 60 s; the window's edge at exactly 60 s (plan B13)
  - storms across several symbols, alerts and channels; two users storming at once (B16, B17)
  - a `once` alert as the held firing (B15); a disarm during a storm
  - stop the process with held firings (B19); reconnect the WS during a storm
  - the history and SCR-014 during and after the window
- Oracles (each also: an uncaught page error or a console error):
  - O4.1 delivered plus suppressed differs from the firings the tape produced (conservation, B14)
  - O4.2 a suppressed firing missing from history, or listed twice (F01)
  - O4.3 more than one summary per user per window, or a summary whose count differs from the held rows
  - O4.4 a toast, sound or desktop notification for a held firing
  - O4.5 `cv_alert_suppressed_total{reason="storm"}` differs from the held count
- Plan cases it leans on (`docs/qa/test-plans/e40-alerts.md`): E40-TC-B13 to B19, F01, X01, X04; the storm constants are PROPOSED (G-5)
- Risks:
  - the replay tape for FX-C is not recorded yet; a hand-built tape must be named in the sheet
  - the summary wording is provisional until the copy deck lands (B18)

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
