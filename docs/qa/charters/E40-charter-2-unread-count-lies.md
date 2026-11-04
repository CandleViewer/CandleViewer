# E40-C2 Charter: Make the notification centre lie about the unread count

- Ticket: E40-Q01 (#1202) writes it; E40-Q02 (#1203) Part C runs it · Format: session-based (`docs/plan/03-testing-strategy.md`
  §11.2) · Timebox: 60 min · Also called: the unread-count hunt
- Status: written, not run. Its screens (SCR-090, SCR-091, SCR-092, SCR-014, SCR-115) are not on `main`: they wait on
  E40-S01 (#1129) and E40-S02 (#1130), whose UI slices wait on E40-D02's design approval (C-10.3). Until they ship, a
  session can probe only the API and WS surface (`/alerts*`, `/alerts/deliveries*`, `/notifications`, topic `alerts`), and
  its sheet says so; nothing here counts as a run against the shipped UI.
- Format note: this is the pre-run variant of the E09 charter format; the post-run debrief fields (areas covered, not probed,
  anomalies) are filled in the session sheet below.
- Setup: staging on demo with the replay feed and the fake clock (plan section 0; until FI-6's stack switch lands, the 60 s edge, quiet hours / DST and snooze / expiry run in-process only); recorded, redacted fixtures only, no live
  exchange (C-13.5); test accounts with no account id, key or balance in any note or capture. Seed a realistic state, not an
  empty install: a populated alert set across the three families and a busy history (E40-Q02 Part C, Technical notes).
- Mission: find any state in which the badge, SCR-014 and the server disagree on what is unread.
- Areas:
  - acks from two sessions and two tabs at once; `ack-all` past 5 000 rows (the continuation, CC-18)
  - a firing on in_app and desktop: the count must hold the in_app row only (CC-18; plan D13)
  - WS reconnect, resnapshot and `upstream_desync` during a burst (23 §15.7)
  - a delivery acked while the topic is backpressured; a deleted alert's unread firings
  - `GET /notifications?unread_only=true` against the WS `unacked_count`
- Oracles (each also: an uncaught page error or a console error):
  - O2.1 the badge differs from `unacked_count` after the UI settles (at most 1 Hz list updates)
  - O2.2 `unacked_count` differs from the count of the caller's `sent` in_app rows with no `acked_at` in the store
  - O2.3 an ack that changes nothing on the server but clears the badge, or the reverse
  - O2.4 a repeated ack that moves `acked_at` (D12)
  - O2.5 another user's row in the count (G07)
- Plan cases it leans on (`docs/qa/test-plans/e40-alerts.md`): E40-TC-D12, D13, F08, G04, G07
- Risks:
  - the count is per channel today and per in_app row only after S02 slice 2 (D13 fails until then; say which build ran)
  - a lost delta repaired only by a later snapshot looks right after a refresh and wrong before it

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
