# E40-C3 Charter: Configure yourself into silence and see what still reaches you

- Ticket: E40-Q01 (#1202) writes it; E40-Q02 (#1203) Part C runs it · Format: session-based (`docs/plan/03-testing-strategy.md`
  §11.2) · Timebox: 90 min · Also called: the critical-override hunt
- Status: written, not run. Its screens (SCR-090, SCR-091, SCR-092, SCR-014, SCR-115) are not on `main`: they wait on
  E40-S01 (#1129) and E40-S02 (#1130), whose UI slices wait on E40-D02's design approval (C-10.3). Until they ship, a
  session can probe only the API and WS surface (`/alerts*`, `/alerts/deliveries*`, `/notifications`, topic `alerts`), and
  its sheet says so; nothing here counts as a run against the shipped UI.
- Format note: this is the pre-run variant of the E09 charter format; the post-run debrief fields (areas covered, not probed,
  anomalies) are filled in the session sheet below.
- Setup: staging on demo with the replay feed and the fake clock (plan section 0); recorded, redacted fixtures only, no live
  exchange (C-13.5); test accounts with no account id, key or balance in any note or capture. Seed a realistic state, not an
  empty install: a populated alert set across the three families and a busy history (E40-Q02 Part C, Technical notes).
- Mission: turn every mute, quiet-hours and channel setting to its quietest and find what still reaches you, and what should and does not.
- Areas:
  - symbol mute, category mute, the SCR-115 matrix, quiet hours across midnight and a DST changeover day
  - every CO entry of the critical-override list (plan section 4, PROPOSED until ratified) against every combination
  - desktop permission denied or unsupported, the window focused, desktop off (FI-2)
  - a user alert with severity `critical`: it never overrides (`user_alerts_override: false`, S02)
  - snooze on top of a mute; an expired alert; a disabled owner
- Oracles (each also: an uncaught page error or a console error):
  - O3.1 a CO event that is not delivered in some combination (P0, US-ALRT-006/3)
  - O3.2 a muted firing with no record: every firing is recorded, only sound and notification are held (US-ALRT-006/2)
  - O3.3 a user alert that breaks through a mute or quiet hours
  - O3.4 a setting that reads as on in SCR-115 while the server holds it off, or the reverse
  - O3.5 a locked cell that a user can turn off
- Plan cases it leans on (`docs/qa/test-plans/e40-alerts.md`): E40-TC-B10 to B12, C01 to C09 and the section 4 cells, D03 to D05, D15
- Risks:
  - mute and quiet hours are `_never` on `main` (plan G-3) and the CO emitters are partial (G-4): until E40-S02 slices 2 and 3 and E39 land, this session can only confirm that nothing is silenced
  - a DST day misread by one hour silences a real alert or lets a quiet-hours one through

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
