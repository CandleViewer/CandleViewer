# E40 alerts: accessibility audit (E40-Q02, Part B)

Standard: WCAG 2.2 AA, `docs/plan/05-accessibility-standard.md`. Contract under audit:
`docs/design/a11y/e40-alerts-a11y-review.md` (E40-D01; its LR, T, KM, AR, NC and CR rows). Status:
**skeleton; nothing executed.** The five surfaces (SCR-090 `/alerts`, SCR-091 modal, SCR-014 drawer,
SCR-092 detail drawer, SCR-115 settings section) are not on main; every row below is
`pending: <blocker>` and is filled in by the PR that un-skips its surface. Screen-reader passes are
owner-run: `docs/qa/a11y/e40-at-pass-sheets.md`. Part B is not signed off until the owner (accessibility
lead per the E40-D01 adaptation) signs; an agent cannot sign it.

## 1. Clause-by-clause verification

Method: `auto` = axe or Playwright collector; `manual` = scripted human or agent check; the E40-D01
review itself ran no AT session, so every `PROPOSED` clause is verified here for the first time.

| Clause      | Requirement (short)                                                                                 | WCAG                 | Method             | Status                                                                                                     |
| ----------- | --------------------------------------------------------------------------------------------------- | -------------------- | ------------------ | ---------------------------------------------------------------------------------------------------------- |
| LR-1        | SCR-092 info/warning toast is polite `role=status`                                                  | 4.1.3                | auto+manual        | pending: E40-S02 #1130                                                                                     |
| LR-2        | error/critical toast persistent; politeness per OQ-15 (PROPOSED)                                    | 4.1.3, 2.2.1         | manual             | pending: E40-S02 #1130 + owner OQ-15                                                                       |
| LR-3        | batched toast / storm summary: one digest write                                                     | 4.1.3                | auto+manual        | pending: E40-S02 #1130                                                                                     |
| LR-4        | SCR-092 detail drawer: non-modal dialog, labelled, real `<table>`                                   | 1.3.1, 4.1.2         | auto               | pending: E40-S02 #1130                                                                                     |
| LR-5        | reject / lockout / kill switch / protection failure: `role=alert` once, never digested              | 4.1.3                | manual             | pending: E40-S02 #1130                                                                                     |
| LR-6        | SCR-014 list `role=log`, `aria-live=off` always                                                     | 4.1.3                | auto               | pending: E40-S02 #1130                                                                                     |
| LR-7        | bell button name carries unread count, `aria-expanded`                                              | 4.1.2                | auto               | pending: E40-S02 #1130                                                                                     |
| LR-8        | SCR-090 table in labelled region; polite result status                                              | 1.3.1, 4.1.3         | auto+manual        | pending: E40-S01 #1129                                                                                     |
| LR-9        | SCR-091 modal dialog; error summary `role=alert`; preview <=1 write/500 ms                          | 3.3.1, 4.1.3         | auto+manual        | pending: E40-S01 #1129                                                                                     |
| LR-10       | SCR-115 matrix headers; one polite save status; locked-row description                              | 1.3.1, 4.1.3         | auto+manual        | pending: E40-S02 #1130                                                                                     |
| LR-11       | SCR-117 announcements panel radiogroups                                                             | 4.1.2                | auto               | pending: E40-S02 #1130                                                                                     |
| LR-12       | rule-fire toast per OQ-13 (owner decision)                                                          | 4.1.3                | manual             | pending: E40-S02 #1130 + owner OQ-13                                                                       |
| T-1         | info/warning toast 20 s, hover/focus pause, duration control, record kept                           | 2.2.1, 2.2.2         | auto+manual        | pending: E40-S02 #1130                                                                                     |
| T-2         | error/critical toast until dismissed                                                                | 2.2.1                | auto               | pending: E40-S02 #1130                                                                                     |
| T-3         | batched / storm summary until dismissed                                                             | 2.2.1                | auto               | pending: E40-S02 #1130                                                                                     |
| T-4         | order-reject toast timing                                                                           | 2.2.1                | auto               | pending: E40-S02 #1130                                                                                     |
| T-5         | lockout / kill-switch / protection banner persistent                                                | 2.2.1                | auto               | pending: E40-S02 #1130                                                                                     |
| T-6         | snooze remaining time readable                                                                      | 2.2.1                | manual             | pending: E40-S01 #1129                                                                                     |
| T-7         | quiet-hours window                                                                                  | 2.2.1                | manual             | pending: E40-S02 #1130                                                                                     |
| T-8         | sound: no auto-play beyond user setting; preview user-triggered                                     | 1.4.2                | manual             | pending: E40-S01 #1129                                                                                     |
| T-9         | desktop (OS) notification: OS-controlled, outcome announced                                         | 4.1.3                | manual (owner-run) | pending: E40-S02 #1130                                                                                     |
| T-10        | undo on a toast (5 s) reachable by keyboard                                                         | 2.2.1                | manual             | pending: E40-S02 #1130                                                                                     |
| KM-1        | open notification centre by command palette / bell; never opened by an incoming event               | 2.1.1, 3.2.1         | auto+manual        | pending: E40-S02 #1130                                                                                     |
| KM-2        | move through items                                                                                  | 2.1.1                | auto               | pending: E40-S02 #1130                                                                                     |
| KM-3        | action an item                                                                                      | 2.1.1                | auto               | pending: E40-S02 #1130                                                                                     |
| KM-4        | mark all read / mark above as read                                                                  | 2.1.1                | auto               | pending: E40-S02 #1130                                                                                     |
| KM-5        | snooze from the toast                                                                               | 2.1.1                | auto               | pending: E40-S02 #1130                                                                                     |
| KM-6        | dismiss / Esc, focus return                                                                         | 2.1.2, 2.4.3         | auto               | pending: E40-S02 #1130                                                                                     |
| KM-7        | SCR-090 table                                                                                       | 2.1.1                | auto               | pending: E40-S01 #1129                                                                                     |
| KM-8        | SCR-091 editor Tab order, sound preview reachable, Ctrl+Enter / Esc                                 | 2.1.1, 2.4.3         | auto               | pending: E40-S01 #1129                                                                                     |
| KM-9        | SCR-115 grid: one Tab stop, arrows by row/column, locked cell focusable                             | 2.1.1, 1.3.1         | auto               | pending: E40-S02 #1130                                                                                     |
| KM-10       | SCR-115 sound preview and test notification                                                         | 2.1.1                | auto               | pending: E40-S02 #1130                                                                                     |
| KM-11       | everywhere: no keyboard trap, visible focus                                                         | 2.1.2, 2.4.7         | auto               | pending: E40-S01 #1129 + E40-S02 #1130                                                                     |
| KM-12       | SCR-117 announcements panel                                                                         | 2.1.1                | auto               | pending: E40-S02 #1130                                                                                     |
| AR-1        | single alert: announced at once, one sentence                                                       | 4.1.3                | auto+manual        | pending: E40-S02 #1130                                                                                     |
| AR-2        | burst: further firings in 60 s counted, not announced                                               | 4.1.3                | auto+manual        | pending: E40-S02 #1130                                                                                     |
| AR-3        | one digest per window                                                                               | 4.1.3                | auto+manual        | pending: E40-S02 #1130 (pre-G13 count not deterministic)                                                   |
| AR-4        | reject/lockout/kill switch never digested                                                           | 4.1.3                | auto+manual        | pending: E40-S02 #1130                                                                                     |
| AR-5        | announcer cadence independent of the 250 ms WS stream                                               | 4.1.3                | auto+manual        | pending: E40-S02 #1130                                                                                     |
| AR-6        | every announced item readable in SCR-014 / SCR-090                                                  | 4.1.3                | auto+manual        | pending: E40-S02 #1130                                                                                     |
| AR-7        | snapshot / resync does not re-announce                                                              | 4.1.3                | auto+manual        | pending: E40-S02 #1130                                                                                     |
| NC-1        | severity icon + text + colour                                                                       | 1.4.1, 1.1.1         | auto+manual        | pending: E40-S02 #1130                                                                                     |
| NC-2        | kind                                                                                                | 1.4.1, 1.1.1         | auto+manual        | pending: E40-S01 #1129                                                                                     |
| NC-3        | alert status (SCR-090)                                                                              | 1.4.1, 1.1.1         | auto+manual        | pending: E40-S01 #1129                                                                                     |
| NC-4        | snoozed                                                                                             | 1.4.1, 1.1.1         | auto+manual        | pending: E40-S01 #1129                                                                                     |
| NC-5        | disabled alert                                                                                      | 1.4.1, 1.1.1         | auto+manual        | pending: E40-S01 #1129                                                                                     |
| NC-6        | delivery failed / blocked                                                                           | 1.4.1, 1.1.1         | auto+manual        | pending: E40-S01 #1129                                                                                     |
| NC-7        | muted symbol/category                                                                               | 1.4.1, 1.1.1         | auto+manual        | pending: E40-S02 #1130                                                                                     |
| NC-8        | suppressed (storm)                                                                                  | 1.4.1, 1.1.1         | auto+manual        | pending: E40-S01 #1129                                                                                     |
| NC-9        | locked row (critical override)                                                                      | 1.4.1, 1.1.1         | auto+manual        | pending: E40-S02 #1130                                                                                     |
| NC-10       | estimated detector alert                                                                            | 1.4.1, 1.1.1         | auto+manual        | pending: E40-S01 #1129                                                                                     |
| NC-11       | unread                                                                                              | 1.4.1, 1.1.1         | auto+manual        | pending: E40-S02 #1130                                                                                     |
| CR-1..CR-36 | contrast per state x theme (4.5:1 text, 3:1 non-text, 7:1 text in high-contrast); focus rings >=3:1 | 1.4.3, 1.4.6, 1.4.11 | automated (tool)   | pending: tool runs now on tokens; rendered check blocked by E40-S01 #1129 / E40-S02 #1130; DS-CR-1..4 open |

## 2. Automated pass (axe)

Matrix: 5 surfaces x themes (dark, light, high-contrast) x zoom (100%, 200%) = 30 entries, declared in
`apps/web/e2e/a11y/alert-surfaces.ts` and reported as `skipped` (with the named blocker) in
`reports/a11y/axe.json` and `keyboard.json` until un-skipped. Gate tags: `AXE_GATE_TAGS`.

| Entry                           | 100%                         | 200%    |
| ------------------------------- | ---------------------------- | ------- |
| SCR-090 /alerts / dark          | pending: blocker per surface | pending |
| SCR-090 /alerts / light         | pending: blocker per surface | pending |
| SCR-090 /alerts / high-contrast | pending: blocker per surface | pending |
| SCR-091 modal / dark            | pending: blocker per surface | pending |
| SCR-091 modal / light           | pending: blocker per surface | pending |
| SCR-091 modal / high-contrast   | pending: blocker per surface | pending |
| SCR-014 drawer / dark           | pending: blocker per surface | pending |
| SCR-014 drawer / light          | pending: blocker per surface | pending |
| SCR-014 drawer / high-contrast  | pending: blocker per surface | pending |
| SCR-092 drawer / dark           | pending: blocker per surface | pending |
| SCR-092 drawer / light          | pending: blocker per surface | pending |
| SCR-092 drawer / high-contrast  | pending: blocker per surface | pending |
| SCR-115 section / dark          | pending: blocker per surface | pending |
| SCR-115 section / light         | pending: blocker per surface | pending |
| SCR-115 section / high-contrast | pending: blocker per surface | pending |

Un-skip owners: SCR-090 and SCR-091 by E40-S01 #1129; SCR-014, SCR-092 and SCR-115 by E40-S02 #1130. Zoom 200% is a
320 CSS px-equivalent reflow check (SC 1.4.10) as in the E09 audit.

## 3. Keyboard sweep

`keyboard.collect.ts` traversal per surface (no trap, visible focus, zero mouse events) plus the KM-1..KM-12
maps above. Result: pending (surfaces absent).

## 4. Timing audit (SC 2.2.1)

Every auto-dismissing toast has a retrievable record (SCR-014 row, SCR-090 Triggered row); hover and focus
pause; error/critical never auto-dismiss. Rows T-1..T-10. Result: pending (E40-S02 #1130).

## 5. Non-colour encoding

Each state shown by icon + text + colour (NC-1..NC-11), checked with the colour channel removed
(greyscale emulation) in all three themes. Result: pending.

## 6. Contrast per state and theme

Tool: `python3 -I docs/design/_tools/e40_d01_alert_contrast.py --md --hex` (tokens), then a rendered
spot-check per entry in section 2. Bars: 4.5:1 text, 3:1 non-text and focus ring, 7:1 text in
high-contrast. Open design-system change requests DS-CR-1..4 and OQ-B4 are listed in E40-D01 s6 and s8.
Result: pending (re-run at the head commit when the surfaces land).

## 7. Reduced motion

`prefers-reduced-motion` (and the app motion toggle, `:root[data-motion]`) removes toast slide and drawer
motion (fade only, SCR-014); no flashing (SC 2.3.1, `flash.collect.ts`). Result: pending.

## 8. Findings log

| Id         | Surface | Clause | Severity | Description | Owner | Status |
| ---------- | ------- | ------ | -------- | ----------- | ----- | ------ |
| (none yet) |         |        |          |             |       |        |

Severity: blocker / major / minor. A major defect blocks handoff to sign-off.

## 9. Owner-run assistive-technology passes

NVDA + Firefox, VoiceOver + Safari and the Electron pass are scripted in
`docs/qa/a11y/e40-at-pass-sheets.md`; evidence is attached to #1203. Untested by design: webhook channel
(flagged off, descoped to R5).

| Pass                     | Run by | Date    | Evidence | Result  |
| ------------------------ | ------ | ------- | -------- | ------- |
| NVDA / Firefox           | owner  | pending | pending  | pending |
| VoiceOver / Safari       | owner  | pending | pending  | pending |
| Electron + screen reader | owner  | pending | pending  | pending |
