# E40-C1 Charter: Author the strangest alert you can and try to make it act

- Ticket: E40-Q01 (#1202) writes it; E40-Q02 (#1203) Part C runs it · Format: session-based (`docs/plan/03-testing-strategy.md`
  §11.2) · Timebox: 75 min · Also called: the invariant hunt
- Status: written, not run. Its screens (SCR-090, SCR-091, SCR-092, SCR-014, SCR-115) are not on `main`: they wait on
  E40-S01 (#1129) and E40-S02 (#1130), whose UI slices wait on E40-D02's design approval (C-10.3). Until they ship, a
  session can probe only the API and WS surface (`/alerts*`, `/alerts/deliveries*`, `/notifications`, topic `alerts`), and
  its sheet says so; nothing here counts as a run against the shipped UI.
- Format note: this is the pre-run variant of the E09 charter format; the post-run debrief fields (areas covered, not probed,
  anomalies) are filled in the session sheet below.
- Setup: staging on demo with the replay feed and the fake clock (plan section 0; until FI-6's stack switch lands, the 60 s edge, quiet hours / DST and snooze / expiry run in-process only); recorded, redacted fixtures only, no live
  exchange (C-13.5); test accounts with no account id, key or balance in any note or capture. Seed a realistic state, not an
  empty install: a populated alert set across the three families and a busy history (E40-Q02 Part C, Technical notes).
- Mission: make an alert do anything but notify: place, modify or cancel an order, reach an account, or carry data it must not.
- Areas:
  - the condition IR at its edges: every comparison, logical and temporal op, nested arithmetic, variables, 512 nodes and 32 levels (`alerts/compiler.py:48-49`)
  - action-shaped input: an `actions` key, an action in `variables`, in `params`, in a logical child; look-alike keys and ops (plan E07)
  - the message template: placeholders outside the allow-list, `position.*` values, control and bidirectional characters (CC-1)
  - account reach: `exchange_account_id` and condition operands on an ungranted account as a Manager (G06)
  - the three families with unusual triggers: `on_schedule` cron, `on_metric_change`, bar close on `1w`
- Oracles (each also: an uncaught page error or a console error):
  - O1.1 any order, order intent or OMS call that follows an alert (P0)
  - O1.2 a create or update that stores an action-bearing condition, or is answered anything but `422` (E07)
  - O1.3 account data, a key or a balance in any channel's text (`position.*` renders `—`, CC-1)
  - O1.4 a refused write with no audit record, or a success audit for a refused write (C-2.9)
  - O1.5 a `500` for any input: every refusal is a typed `4xx`
- Plan cases it leans on (`docs/qa/test-plans/e40-alerts.md`): E40-TC-E07 to E10, G06, X05; E40-X01 owns the abuse cases and is cross-referenced, not repeated
- Risks:
  - a new E35 node kind that the allow-list classifies wrongly (the walk fails closed by design; a gap here is a P0)
  - template text that reaches the OS notification on a lock screen (D02 §4.7)

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
