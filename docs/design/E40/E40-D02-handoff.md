# E40-D02 — Hand-off pack: the five alert surfaces (part C; `16` §11.4 for CMP-163/164/165)

The engineering hand-off of E40-D02 (#1013) for SCR-090, SCR-091, SCR-092, SCR-014 and SCR-115, assembled from the
merged spec [E40-D02.md](E40-D02.md) (PR-1, #4126); every "§" below is the spec's. It decides nothing new: each row cites
the section that decided it. Ruled by the orchestrator on 2026-10-29 (issuecomment-6486717743, BQ-1..BQ-9; the questions
are issuecomment-6486480087). **Status:** text; the ten boards are PENDING (the boards PR fills C2's Penpot board ids and
posts the owner walkthrough, spec §13.2). The re-plan to ten boards is PROPOSED, owner approval pending (#2701) (BQ-2).
Every number here is the audit tool's: `python3 -I -B docs/design/_tools/e40_d02_alert_audit.py --json`, whose `--check`
gates C1, C2, the copy deck, the allow-list, the token map, the cites and the Deferred rows. **Normative for E40-S01..S04
and E40-Q01 / Q02:** the state matrix, the copy deck, the a11y contract and the budgets. Frame data is synthetic only
(BTCUSDT, ETHUSDT, SOLUSDT; the account label "Main"); no account identifier, balance or credential appears here.

## Hand-off checklist (E40-D02, #1013)

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason (`16` §11.4, §13.3). One table with a column per
component replaces three literal copies (the E15-D03 form).

| Item                     | CMP-163 AlertRow                                                                                                             | CMP-164 AlertBuilderForm                                                                                                         | CMP-165 AlertFiredToastGroup                                                                                   |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Final Penpot link        | `[ ]` the boards PR: page `E40-D02`, board 01 (A6) and 08; C2 below holds every frame                                        | `[ ]` the boards PR: board 02 (A8) with A16's strip; C2                                                                          | `[ ]` the boards PR: boards 03 (B1), 04 (B15), 09; C2                                                          |
| Variants × States matrix | `[x]` `15` CMP-163 States and Storybook (24 stories); spec §7.1; C1                                                          | `[x]` `15` CMP-164 States and Storybook (26 stories); spec §7.2; C1                                                              | `[x]` `15` CMP-165 States and Storybook (22 stories); spec §7.3; C1                                            |
| Keyboard table           | `[x]` spec §11.2 SCR-090; D01 KM-7 (the a11y contract below); the row menu on `Shift+F10`, `Space` selects (spec §2.6, §2.7) | `[x]` spec §11.2 SCR-091, §3.2's order; D01 KM-8; `Ctrl+Enter` checks the draft and never saves (X-33)                           | `[x]` spec §11.2 Toast; D01 KM-5, KM-6; never focused on arrival; `Esc` dismisses and acknowledges             |
| Accessible name / role   | `[x]` a `<tr>` with `th scope="row"`; "Select BTC above 65k", "More actions for BTC above 65k" (spec §2.2, §7.1)             | `[x]` the modal `dialog` "New alert"; the Delivery fieldset described by the boundary line; CMP-234 takes focus on a failed save | `[x]` `role="status"` through CMP-212's polite region at every severity (LR-1, LR-2, AM-11); "Alert: …" (X-30) |
| Live data                | `[x]` a row repaints in place at ≤ 1 Hz, never announced (LR-8); one bulk result line                                        | `[x]` the preview `role="status"`, at most one write per 500 ms (LR-9)                                                           | `[x]` the announcer decides (AR-1..AR-7); nothing per WS frame (AR-5); the toast itself never writes           |
| Motion pair              | `[x]` the created-row mark only, no motion (spec §8)                                                                         | `[x]` CMP-043's pair (the editor is its modal)                                                                                   | `[x]` the motion table below: enter, exit, stack reflow; fade only under motion-reduce                         |
| Density notes            | `[x]` `size.row.compact` / `.comfortable`; the 1 056 px fold (spec §2.2, §11.3)                                              | `[x]` 720 px; labels stack above controls at 200 % (spec §11.3)                                                                  | `[x]` 360 px; two body lines compact, three comfortable (spec §10.2)                                           |
| Essential exceptions     | `[x]` none: every target ≥ 24 px in both densities (spec §11.3)                                                              | `[x]` none                                                                                                                       | `[x]` none                                                                                                     |
| Tokens used              | `[x]` the token map's `SCR-090` group; `packages/ui/tokens` at `728b4254d`                                                   | `[x]` the token map's `SCR-091` group                                                                                            | `[x]` the token map's `SCR-092 toast` group                                                                    |
| Data contract confirmed  | `[x]` `22` `Alert` as served; CC-3, CC-4, CC-5 for status, snooze and cooldown (spec §17.1)                                  | `[x]` `22` `AlertInput`, unchanged; the 409, 412, 422, 403, 404, 503 answers (spec §3.7); CC-10, CC-12, CC-19                    | `[x]` `23` §15.7 `alerts` items; CC-1, CC-2, CC-7, CC-18 (spec §4.1, §17.1)                                    |
| Contrast and CVD         | `[x]` spec §14.2 CP-1..CP-4, CP-8..CP-11; CVD renders with board 01 (boards PR)                                              | `[x]` CP-6, CP-12, CP-16, CP-17                                                                                                  | `[x]` D01 CR-1..CR-12; CVD renders with board 03 (boards PR)                                                   |
| Design QA, `05` §10      | `[ ]` the `16` §12 pass runs on the boards PR; the `05` §10 template is D01 §7.3                                             | `[ ]` as CMP-163                                                                                                                 | `[ ]` as CMP-163                                                                                               |
| Sign-off                 | `[ ]` owner approval pending (#1013, #2701)                                                                                  | `[ ]` owner approval pending                                                                                                     | `[ ]` owner approval pending                                                                                   |

## C2 — Frame index (the "Dev Mode links")

Every frame of spec §12.1 and every light twin, in its order, with its board, size, status and its place in the owner
walkthrough (the boards in their numbered order; a frame not on a board reads "on request"). The Penpot board id column is
filled by the boards PR. Generated by the audit tool's `--write` and gated by `--check`.

<!-- c2:begin -->

| Walk       | Frame                                                               | Theme | Board | Size        | Status                       | Penpot board id |
| ---------- | ------------------------------------------------------------------- | ----- | ----- | ----------- | ---------------------------- | --------------- |
| on request | `A1 SCR-090/all-populated`                                          | dark  | —     | 1280 × 800  | specified (drawn on request) | —               |
| on request | `A1 SCR-090/all-populated (light twin)`                             | light | —     | 1280 × 800  | specified (drawn on request) | —               |
| on request | `A2 SCR-090/fired-tab`                                              | dark  | —     | 1280 × 800  | specified (drawn on request) | —               |
| on request | `A2 SCR-090/fired-tab (light twin)`                                 | light | —     | 1280 × 800  | specified (drawn on request) | —               |
| on request | `A3 SCR-090/snoozed-and-row-menu`                                   | dark  | —     | 1280 × 800  | specified (drawn on request) | —               |
| on request | `A3 SCR-090/snoozed-and-row-menu (light twin)`                      | light | —     | 1280 × 800  | specified (drawn on request) | —               |
| on request | `A4 SCR-090/empty-filtered-loading-error`                           | dark  | —     | 1600 × 1000 | specified (drawn on request) | —               |
| on request | `A4 SCR-090/empty-filtered-loading-error (light twin)`              | light | —     | 1600 × 1000 | specified (drawn on request) | —               |
| on request | `A5 SCR-090/bulk-selection-confirm`                                 | dark  | —     | 1280 × 800  | specified (drawn on request) | —               |
| on request | `A5 SCR-090/bulk-selection-confirm (light twin)`                    | light | —     | 1280 × 800  | specified (drawn on request) | —               |
| 1          | `A6 SCR-090/failure-states`                                         | dark  | 01    | 1280 × 900  | board 01, PENDING            | —               |
| 8          | `A6 SCR-090/failure-states (light twin)`                            | light | 08    | 1280 × 900  | board 08, PENDING            | —               |
| on request | `A7 SCR-090/viewer-and-manager`                                     | dark  | —     | 1280 × 800  | specified (drawn on request) | —               |
| on request | `A7 SCR-090/viewer-and-manager (light twin)`                        | light | —     | 1280 × 800  | specified (drawn on request) | —               |
| 2          | `A8 SCR-091/new-default`                                            | dark  | 02    | 720 × 960   | board 02, PENDING            | —               |
| on request | `A8 SCR-091/new-default (light twin)`                               | light | —     | 720 × 960   | specified (drawn on request) | —               |
| on request | `A9 SCR-091/edit-estimated-restatement-preview`                     | dark  | —     | 720 × 1100  | specified (drawn on request) | —               |
| on request | `A9 SCR-091/edit-estimated-restatement-preview (light twin)`        | light | —     | 720 × 1100  | specified (drawn on request) | —               |
| on request | `A10 SCR-091/validation-errors-and-pending`                         | dark  | —     | 720 × 1100  | specified (drawn on request) | —               |
| on request | `A10 SCR-091/validation-errors-and-pending (light twin)`            | light | —     | 720 × 1100  | specified (drawn on request) | —               |
| on request | `A11 SCR-091/vocabulary-unavailable-and-server-errors`              | dark  | —     | 1100 × 900  | specified (drawn on request) | —               |
| on request | `A11 SCR-091/vocabulary-unavailable-and-server-errors (light twin)` | light | —     | 1100 × 900  | specified (drawn on request) | —               |
| on request | `A12 SCR-091/channels-sound-test-fire`                              | dark  | —     | 720 × 1000  | specified (drawn on request) | —               |
| on request | `A12 SCR-091/channels-sound-test-fire (light twin)`                 | light | —     | 720 × 1000  | specified (drawn on request) | —               |
| on request | `A13 SCR-091/rule-editor-vs-alert-editor`                           | dark  | —     | 1500 × 1000 | specified (drawn on request) | —               |
| on request | `A14 SCR-090-091/entry-points-and-flows`                            | dark  | —     | 1600 × 900  | specified (drawn on request) | —               |
| on request | `A15 SCR-090/redline-focus-200`                                     | dark  | —     | 1600 × 1000 | specified (drawn on request) | —               |
| on request | `A16 SCR-091/redline-focus-200`                                     | dark  | —     | 1600 × 1100 | specified (drawn on request) | —               |
| 3          | `B1 SCR-092/toast-severities-actions`                               | dark  | 03    | 1100 × 900  | board 03, PENDING            | —               |
| 9          | `B1 SCR-092/toast-severities-actions (light twin)`                  | light | 09    | 1100 × 900  | board 09, PENDING            | —               |
| on request | `B2 SCR-092/stack-group-storm`                                      | dark  | —     | 1100 × 1000 | specified (drawn on request) | —               |
| on request | `B2 SCR-092/stack-group-storm (light twin)`                         | light | —     | 1100 × 1000 | specified (drawn on request) | —               |
| on request | `B3 SCR-092/detail-drawer`                                          | dark  | —     | 480 × 1100  | specified (drawn on request) | —               |
| on request | `B3 SCR-092/detail-drawer (light twin)`                             | light | —     | 480 × 1100  | specified (drawn on request) | —               |
| on request | `B4 SCR-092/detail-drawer-states`                                   | dark  | —     | 1480 × 700  | specified (drawn on request) | —               |
| on request | `B4 SCR-092/detail-drawer-states (light twin)`                      | light | —     | 1480 × 700  | specified (drawn on request) | —               |
| 5          | `B5 SCR-014/populated-mixed`                                        | dark  | 05    | 480 × 1000  | board 05, PENDING            | —               |
| on request | `B5 SCR-014/populated-mixed (light twin)`                           | light | —     | 480 × 1000  | specified (drawn on request) | —               |
| on request | `B6 SCR-014/grouped-storm-overflow`                                 | dark  | —     | 480 × 1000  | specified (drawn on request) | —               |
| on request | `B6 SCR-014/grouped-storm-overflow (light twin)`                    | light | —     | 480 × 1000  | specified (drawn on request) | —               |
| on request | `B7 SCR-014/empty-loading-error`                                    | dark  | —     | 1960 × 600  | specified (drawn on request) | —               |
| on request | `B7 SCR-014/empty-loading-error (light twin)`                       | light | —     | 1960 × 600  | specified (drawn on request) | —               |
| on request | `B8 SCR-014/mute-and-mark-read`                                     | dark  | —     | 960 × 900   | specified (drawn on request) | —               |
| on request | `B8 SCR-014/mute-and-mark-read (light twin)`                        | light | —     | 960 × 900   | specified (drawn on request) | —               |
| 6          | `B9 SCR-115/matrix-locked-rows`                                     | dark  | 06    | 960 × 1100  | board 06, PENDING            | —               |
| 10         | `B9 SCR-115/matrix-locked-rows (light twin)`                        | light | 10    | 960 × 1100  | board 10, PENDING            | —               |
| on request | `B10 SCR-115/sound-quiet-hours-test`                                | dark  | —     | 960 × 1100  | specified (drawn on request) | —               |
| on request | `B10 SCR-115/sound-quiet-hours-test (light twin)`                   | light | —     | 960 × 1100  | specified (drawn on request) | —               |
| on request | `B11 SCR-115/desktop-permission-states`                             | dark  | —     | 1480 × 900  | specified (drawn on request) | —               |
| on request | `B11 SCR-115/desktop-permission-states (light twin)`                | light | —     | 1480 × 900  | specified (drawn on request) | —               |
| on request | `B12 CMP-163/alert-row-variants-states`                             | dark  | —     | 1480 × 1100 | specified (drawn on request) | —               |
| on request | `B12 CMP-163/alert-row-variants-states (light twin)`                | light | —     | 1480 × 1100 | specified (drawn on request) | —               |
| on request | `B13 CMP-164/alert-builder-form-anatomy`                            | dark  | —     | 1100 × 1100 | specified (drawn on request) | —               |
| on request | `B13 CMP-164/alert-builder-form-anatomy (light twin)`               | light | —     | 1100 × 1100 | specified (drawn on request) | —               |
| on request | `B14 CMP-165/fired-toast-group-variants`                            | dark  | —     | 1100 × 1000 | specified (drawn on request) | —               |
| on request | `B14 CMP-165/fired-toast-group-variants (light twin)`               | light | —     | 1100 × 1000 | specified (drawn on request) | —               |
| 4          | `B15 SCR-092/placement-over-workspace`                              | dark  | 04    | 1600 × 1000 | board 04, PENDING            | —               |
| on request | `B16 SCR-014/deep-links-and-role-variants`                          | dark  | —     | 1600 × 900  | specified (drawn on request) | —               |
| on request | `B17 SCR-115/symbol-mute-and-viewer`                                | dark  | —     | 1600 × 900  | specified (drawn on request) | —               |
| on request | `B18 CMP-045-060-212/documented-variants`                           | dark  | —     | 1400 × 900  | specified (drawn on request) | —               |
| 7          | `B19 MOTION/storyboards`                                            | dark  | 07    | 1600 × 900  | board 07, PENDING            | —               |
| on request | `B20 SOUND/assets-labels-fallback`                                  | dark  | —     | 1200 × 700  | specified (drawn on request) | —               |
| on request | `B21 SCR-092/redline-focus-200`                                     | dark  | —     | 1600 × 1000 | specified (drawn on request) | —               |
| on request | `B22 SCR-014/redline-focus-200`                                     | dark  | —     | 1600 × 1000 | specified (drawn on request) | —               |
| on request | `B23 SCR-115/redline-focus-200`                                     | dark  | —     | 1600 × 1100 | specified (drawn on request) | —               |

<!-- c2:end -->

## C1 — State matrix (12 states × 5 screens)

The ticket's twelve states for each screen: the frame that draws it and its copy string, quoted from the spec, or
`N/A — reason`. An empty cell fails `--check`, and so does a frame absent from C2 or a string the spec does not hold.
SCR-092 is the toast and its detail drawer; "active" is an armed alert as each surface shows it, "triggered" a firing.
Generated by the audit tool's `--write`.

<!-- c1:begin -->

| Screen  | State                  | Frame                                                  | Copy string, or N/A — reason                                                                                                 | Ref |
| ------- | ---------------------- | ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- | --- |
| SCR-090 | loading                | `A4 SCR-090/empty-filtered-loading-error`              | "Loading alerts…"                                                                                                            | A4  |
| SCR-090 | empty                  | `A4 SCR-090/empty-filtered-loading-error`              | "No alerts yet"                                                                                                              | A4  |
| SCR-090 | populated              | `A1 SCR-090/all-populated`                             | "Showing 4 of 12 alerts"                                                                                                     | A1  |
| SCR-090 | active                 | `A1 SCR-090/all-populated`                             | "Armed"                                                                                                                      | A1  |
| SCR-090 | triggered              | `A2 SCR-090/fired-tab`                                 | "Fired at 14:02:11 UTC"                                                                                                      | A2  |
| SCR-090 | snoozed                | `A3 SCR-090/snoozed-and-row-menu`                      | "Snoozed until 14:32 UTC (28 min)"                                                                                           | A3  |
| SCR-090 | expired                | `A1 SCR-090/all-populated`                             | "Expired"                                                                                                                    | A1  |
| SCR-090 | disabled               | `A1 SCR-090/all-populated`                             | "Disabled"                                                                                                                   | A1  |
| SCR-090 | delivery-failed        | `A6 SCR-090/failure-states`                            | "The desktop app couldn't show the notification. The alert fired and is recorded here."                                      | A6  |
| SCR-090 | vocabulary-unavailable | `A6 SCR-090/failure-states`                            | "Alert conditions can't be described right now: the rule engine isn't available. Your alerts are unchanged."                 | A6  |
| SCR-090 | permission-denied      | `A6 SCR-090/failure-states`                            | "Desktop notification blocked by the OS — enable it in Settings"                                                             | A6  |
| SCR-090 | error                  | `A4 SCR-090/empty-filtered-loading-error`              | "Alerts couldn't load."                                                                                                      | A4  |
| SCR-091 | loading                | `A10 SCR-091/validation-errors-and-pending`            | "Saving…"                                                                                                                    | A10 |
| SCR-091 | empty                  | `A8 SCR-091/new-default`                               | "New alert"                                                                                                                  | A8  |
| SCR-091 | populated              | `A9 SCR-091/edit-estimated-restatement-preview`        | "Preview with current values; the alert uses the values when it fires."                                                      | A9  |
| SCR-091 | active                 | `A8 SCR-091/new-default`                               | "Alert BTC above 65k created"                                                                                                | A8  |
| SCR-091 | triggered              | `A12 SCR-091/channels-sound-test-fire`                 | "Test shown on this device"                                                                                                  | A12 |
| SCR-091 | snoozed                | —                                                      | N/A — snoozing is done from SCR-090, the toast and SCR-014, never in the editor (D-5)                                        | —   |
| SCR-091 | expired                | `A10 SCR-091/validation-errors-and-pending`            | "Pick a time in the future."                                                                                                 | A10 |
| SCR-091 | disabled               | `A11 SCR-091/vocabulary-unavailable-and-server-errors` | "Your role can't change alerts."                                                                                             | A11 |
| SCR-091 | delivery-failed        | `A12 SCR-091/channels-sound-test-fire`                 | "Desktop didn't respond"                                                                                                     | A12 |
| SCR-091 | vocabulary-unavailable | `A11 SCR-091/vocabulary-unavailable-and-server-errors` | "The rule engine isn't available, so conditions can't be checked or changed right now. Your alerts keep running."            | A11 |
| SCR-091 | permission-denied      | `A12 SCR-091/channels-sound-test-fire`                 | "Blocked by the OS — fix in Notification settings"                                                                           | A12 |
| SCR-091 | error                  | `A11 SCR-091/vocabulary-unavailable-and-server-errors` | "The alerts service is unavailable. Your changes are kept — try again."                                                      | A11 |
| SCR-092 | loading                | —                                                      | N/A — the toast renders at once from the alerts item; the drawer's loading (B4) is CMP-015 rows with aria-busy and no string | —   |
| SCR-092 | empty                  | `B4 SCR-092/detail-drawer-states`                      | "Values at fire time aren't available yet."                                                                                  | B4  |
| SCR-092 | populated              | `B1 SCR-092/toast-severities-actions`                  | "Last price 65,012.5 crossed above 65,000"                                                                                   | B1  |
| SCR-092 | active                 | `B1 SCR-092/toast-severities-actions`                  | "Alert: {name}, {symbol}, {metric} {value}, {time}"                                                                          | B1  |
| SCR-092 | triggered              | `B2 SCR-092/stack-group-storm`                         | "3 alerts fired for BTCUSDT"                                                                                                 | B2  |
| SCR-092 | snoozed                | `B1 SCR-092/toast-severities-actions`                  | "Snoozed until 14:32 UTC (28 min)"                                                                                           | B1  |
| SCR-092 | expired                | —                                                      | N/A — an expired alert never fires, so no toast or drawer exists for it (§2.3)                                               | —   |
| SCR-092 | disabled               | `B1 SCR-092/toast-severities-actions`                  | "Alert disabled. It won't fire until you enable it."                                                                         | B1  |
| SCR-092 | delivery-failed        | `B3 SCR-092/detail-drawer`                             | "The desktop notification for this firing couldn't be shown."                                                                | B3  |
| SCR-092 | vocabulary-unavailable | `B1 SCR-092/toast-severities-actions`                  | "Alert disarmed: CVD divergence data source unavailable"                                                                     | B1  |
| SCR-092 | permission-denied      | `B3 SCR-092/detail-drawer`                             | "Desktop notification blocked by the OS — enable it in Settings"                                                             | B3  |
| SCR-092 | error                  | `B4 SCR-092/detail-drawer-states`                      | "The details of this firing couldn't load."                                                                                  | B4  |
| SCR-014 | loading                | —                                                      | N/A — five CMP-015 rows with aria-busy and no string (B7)                                                                    | —   |
| SCR-014 | empty                  | `B7 SCR-014/empty-loading-error`                       | "Nothing yet today"                                                                                                          | B7  |
| SCR-014 | populated              | `B5 SCR-014/populated-mixed`                           | "Notifications, {N} unread"                                                                                                  | B5  |
| SCR-014 | active                 | `B5 SCR-014/populated-mixed`                           | "3 new — Back to top"                                                                                                        | B5  |
| SCR-014 | triggered              | `B6 SCR-014/grouped-storm-overflow`                    | "12 similar alerts"                                                                                                          | B6  |
| SCR-014 | snoozed                | —                                                      | N/A — snoozing is a row-menu action; the alert's snoozed state reads in SCR-090 (§5.6)                                       | —   |
| SCR-014 | expired                | —                                                      | N/A — the centre lists deliveries, never alert definitions; an expiry writes no row                                          | —   |
| SCR-014 | disabled               | `B16 SCR-014/deep-links-and-role-variants`             | "Your role can't change alerts."                                                                                             | B16 |
| SCR-014 | delivery-failed        | `B5 SCR-014/populated-mixed`                           | "Desktop notification not shown: {name}"                                                                                     | B5  |
| SCR-014 | vocabulary-unavailable | `B5 SCR-014/populated-mixed`                           | "Alert disarmed: {metric} data source unavailable"                                                                           | B5  |
| SCR-014 | permission-denied      | —                                                      | N/A — the centre needs no OS permission; a blocked desktop notification is its delivery-failed row                           | —   |
| SCR-014 | error                  | `B7 SCR-014/empty-loading-error`                       | "Notifications couldn't load."                                                                                               | B7  |
| SCR-115 | loading                | —                                                      | N/A — the sections as CMP-015 rows with aria-busy and no string; this device's values show at once (B17)                     | —   |
| SCR-115 | empty                  | —                                                      | N/A — the matrix always holds its six categories (§6.2)                                                                      | —   |
| SCR-115 | populated              | `B9 SCR-115/matrix-locked-rows`                        | "Critical events ignore mutes and quiet hours: they always notify on every channel they use."                                | B9  |
| SCR-115 | active                 | `B10 SCR-115/sound-quiet-hours-test`                   | "Critical events still notify during quiet hours."                                                                           | B10 |
| SCR-115 | triggered              | `B10 SCR-115/sound-quiet-hours-test`                   | "Test notification shown"                                                                                                    | B10 |
| SCR-115 | snoozed                | `B17 SCR-115/symbol-mute-and-viewer`                   | "muted since 14:02 UTC"                                                                                                      | B17 |
| SCR-115 | expired                | —                                                      | N/A — a notification setting never expires                                                                                   | —   |
| SCR-115 | disabled               | `B17 SCR-115/symbol-mute-and-viewer`                   | "Your role can't change settings."                                                                                           | B17 |
| SCR-115 | delivery-failed        | `B10 SCR-115/sound-quiet-hours-test`                   | "The last sound couldn't play on this device (14:02 UTC). Alerts still show as toasts."                                      | B10 |
| SCR-115 | vocabulary-unavailable | —                                                      | N/A — SCR-115 reads no rule vocabulary                                                                                       | —   |
| SCR-115 | permission-denied      | `B11 SCR-115/desktop-permission-states`                | "This test can't show a desktop notification until the OS allows it."                                                        | B11 |
| SCR-115 | error                  | `B17 SCR-115/symbol-mute-and-viewer`                   | "Notification settings couldn't load."                                                                                       | B17 |

<!-- c1:end -->

## C3 — Lifecycle

| #   | From               | Event                                                   | To                                                      | Surface and frame                                       | Spec        |
| --- | ------------------ | ------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------- | ----------- |
| 1   | —                  | `Create alert` (any of the seven entries)               | Armed (`enabled` defaults true)                         | SCR-091 A8, A14; SCR-090 A1 with the 2 s mark           | §3.7, §3.10 |
| 2   | Armed (every time) | the condition holds (gate, cooldown, storm window pass) | Armed; a firing with one row per channel                | SCR-092 toast B1; SCR-014 row B5; SCR-090 Last fired A1 | §4.1        |
| 3   | Armed (once)       | the condition holds                                     | Fired (the one-shot disarms in the same transaction)    | SCR-092 B1 with `Enable again`; SCR-090 A2              | §2.3, §4.2  |
| 4   | Fired toast        | `Details`                                               | the detail drawer, focus on its heading                 | SCR-092 B3, B4                                          | §4.6        |
| 5   | Fired toast        | `Dismiss`, `Esc`                                        | acknowledged; the SCR-014 row read                      | SCR-014 B8                                              | §4.3, §5.3  |
| 6   | Armed              | the storm gate holds the firing                         | Armed; "Suppressed (storm)" in the history; one summary | SCR-092 B2; SCR-014 B6; SCR-090 A2                      | §4.5, §5.4  |
| 7   | Armed              | `Snooze ▸` a preset (behind E40-S01's flag until CC-4)  | Snoozed until the absolute end                          | SCR-090 A3; the toast B1                                | §2.6        |
| 8   | Snoozed            | `Wake now`, or the end passes                           | Armed                                                   | SCR-090 A3                                              | §2.6        |
| 9   | Armed              | `Disable` (row, toast, bulk with its confirm)           | Disabled                                                | SCR-090 A1, A5; SCR-092 B1                              | §2.6, §2.7  |
| 10  | Disabled           | `Enable`                                                | Armed                                                   | SCR-090 A1, A5                                          | §2.6        |
| 11  | Armed              | the metric source is lost                               | Disarmed, with its notice                               | SCR-090 A6; SCR-092 B1 (the disarm notice); SCR-014 B5  | §2.5, §4.2  |
| 12  | Disarmed           | `Why`, then `Enable…` with its confirm                  | Armed (it may disarm again and say so)                  | SCR-090 A6, A14                                         | §2.5        |
| 13  | Fired (once)       | `Enable again`                                          | Armed for one more firing                               | SCR-092 B1; SCR-090 A2                                  | §4.4        |
| 14  | Armed              | `expires_at` passes                                     | Expired (derived, never stored)                         | SCR-090 A1                                              | §2.3        |
| 15  | any                | `Delete…` with its confirm                              | deleted; past firings stay in Notifications             | SCR-090 A5; the drawer's "This alert was deleted." B4   | §2.7, §4.6  |
| 16  | any toast stream   | the client reconnects after a gap                       | one digest toast; rows resynced                         | SCR-092 B2; SCR-090 A4; SCR-014 B7                      | §4.5, §2.5  |

## Token map (machine-readable; token names only)

The tokens each surface binds (spec §14.1, §4.2, §8), as one JSON block for E40-D03 to diff against the shipped CSS custom
properties; `--check` fails on a name that is not in `packages/ui/tokens`. Four `15` names are not tokens and are drawn
with existing ones until E05 decides (spec §14.4, DF-17); the toast, rail and drawer widths are raw px until then.

```json
{
  "source": "docs/design/E40/E40-D02.md §14.1, §4.2, §8; packages/ui/tokens at 728b4254d",
  "surfaces": {
    "SCR-090": [
      "color.surface.canvas",
      "color.surface.raised",
      "color.surface.hover",
      "color.surface.selected",
      "color.text.primary",
      "color.text.secondary",
      "color.text.tertiary",
      "color.status.warning.strong",
      "color.status.danger.strong",
      "color.status.info.strong",
      "color.status.success.strong",
      "color.status.danger.default",
      "color.border.selected",
      "size.row.compact",
      "size.row.comfortable",
      "type.ui.body",
      "type.num.base"
    ],
    "SCR-091": [
      "color.surface.overlay",
      "elevation.dialog",
      "radius.dialog",
      "space.dialog.padding",
      "space.field.gap",
      "color.surface.sunken",
      "color.status.warning.subtle",
      "color.status.warning.strong",
      "color.status.info.subtle",
      "color.status.info.strong",
      "color.action.primary.default",
      "color.text.primary",
      "color.text.secondary"
    ],
    "SCR-092 toast": [
      "color.surface.overlay",
      "elevation.popover",
      "radius.card",
      "space.inset.md",
      "space.stack.sm",
      "border.thick",
      "color.status.info.default",
      "color.status.warning.default",
      "color.status.danger.default",
      "color.status.warning.strong",
      "type.ui.caption",
      "type.ui.body-strong",
      "type.ui.body",
      "type.num.sm",
      "color.text.primary",
      "color.text.secondary",
      "color.text.tertiary"
    ],
    "SCR-092 drawer": [
      "color.surface.raised",
      "elevation.popover",
      "type.num.sm",
      "color.text.tertiary"
    ],
    "SCR-014": [
      "color.surface.raised",
      "color.status.info.default",
      "color.status.info.strong",
      "color.text.inverse",
      "color.neutral.subtle",
      "color.text.secondary"
    ],
    "SCR-115": [
      "color.surface.canvas",
      "color.text.secondary",
      "color.action.primary.default",
      "color.text.tertiary",
      "color.status.info.subtle",
      "color.status.success.strong"
    ],
    "Disconnected": [
      "color.data-confidence.stale.surface",
      "color.data-confidence.stale.text",
      "color.data-confidence.disconnected.text",
      "color.data-confidence.disconnected.indicator",
      "color.data-confidence.resyncing.indicator",
      "color.data-confidence.resyncing.text"
    ],
    "Focus": ["color.focus.ring", "border.focus", "color.surface.canvas"],
    "Motion": [
      "motion.duration.fast",
      "motion.duration.normal",
      "motion.easing.standard",
      "motion.easing.decelerate",
      "motion.easing.accelerate"
    ]
  }
}
```

## Redlines (token names, never hex or px; BQ-3)

| Surface and element                  | Fill / stroke                                                                                                                                                   | Text                                                                                                            | Spacing, size, elevation                                                       |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| SCR-090 row                          | `color.surface.canvas`; hover `color.surface.hover`; selected `color.surface.selected`                                                                          | name `color.text.primary` `type.ui.body`; times `type.num.base`                                                 | `size.row.compact` / `size.row.comfortable`                                    |
| SCR-090 header row, tab underline    | `color.surface.raised`; the selected tab `color.border.selected` (CP-13)                                                                                        | `color.text.secondary`                                                                                          | —                                                                              |
| SCR-090 status glyphs, delivery chip | glyphs `color.status.*.strong` (CP-1, CP-2, CP-4); chip outline `color.status.danger.default` (CP-3)                                                            | the word beside each glyph `color.text.secondary`, never `color.text.disabled` (CR-17)                          | —                                                                              |
| SCR-091 modal, preview, callouts     | `color.surface.overlay`; preview `color.surface.sunken`; callouts `color.status.warning.subtle` / `color.status.info.subtle`                                    | preview `color.text.primary` (CP-16); the boundary line `color.text.secondary`                                  | `elevation.dialog`, `radius.dialog`, `space.dialog.padding`, `space.field.gap` |
| SCR-092 toast                        | `color.surface.overlay`; the `border.thick` edge in `color.status.*.default` (light warning `.strong`, DS-CR-2)                                                 | kicker `type.ui.caption`; title `type.ui.body-strong`; body `type.ui.body`; meta `type.num.sm`                  | `elevation.popover`, `radius.card`, `space.inset.md`, `space.stack.sm`         |
| SCR-092 detail drawer                | `color.surface.raised` over the rail's `elevation.1`                                                                                                            | keys `type.num.sm` in `color.text.tertiary`                                                                     | `elevation.popover`                                                            |
| SCR-014 row, bell badge              | `color.surface.raised`; unread dot `color.status.info.default` (CP-7); badge `color.status.info.strong` (CP-5)                                                  | numeral `color.text.inverse` (CP-14); muted chip label `color.text.secondary` on `color.neutral.subtle` (CP-20) | —                                                                              |
| SCR-115 matrix                       | `color.surface.canvas`; checked `color.action.primary.default` (CP-11); locked boxes `color.text.secondary` (CR-28); boundaries `color.text.tertiary` (DS-CR-3) | the statement on `color.status.info.subtle` (CP-18)                                                             | `size.row.comfortable`                                                         |
| Disconnected (SCR-090, SCR-014)      | `color.data-confidence.stale.surface`                                                                                                                           | rows `color.data-confidence.stale.text` (CP-22); the line `color.data-confidence.disconnected.text` (CP-23)     | —                                                                              |
| Focus, every filled control          | `color.focus.ring` with a 1 px `color.surface.canvas` halo (CR-33)                                                                                              | —                                                                                                               | `border.focus`                                                                 |

## Template allow-list (E40-T02's, drawn in the picker; spec §3.5)

`Insert value` offers exactly the shipped allow-list (`TEMPLATE_FIELDS`, `services/api/candleviewer/alerts/compiler.py`)
plus the metrics the condition references, inserted as `market.<metric>` or `footprint.<metric>` (`_placeholder_ok`);
nothing else. It is the rule E40-T02 enforces; `--check` fails when either drifts. The 36 fixed leaves are the first
four groups below. No leaf is a secret; the `position.*` leaves render in the app only, never in a desktop notification
(D-23, CC-1, DF-8).

| Group (namespace)       | Leaves (count)                                                                                                                                |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Market (`market`)       | symbol, last, last_price, price, bid, ask, mark, mark_price, index, index_price, funding_rate, open_interest, volume_24h, change_24h_pct (14) |
| Footprint (`footprint`) | delta, volume, poc, imbalance, cvd, buy_volume, sell_volume, sell_stack_size, buy_stack_size, timeframe (10)                                  |
| Position (`position`)   | side, size, entry, entry_price, unrealised_pnl, leverage, liquidation_price (7)                                                               |
| Alert (`alert`)         | name, id, triggered_at, condition_summary, severity (5)                                                                                       |
| This condition          | each metric the condition uses, under its namespace                                                                                           |

## Copy deck

Every string a builder needs that a state, a refusal or a notice shows, quoted from the spec (`--check` fails on a string
the spec does not hold); the state matrix C1 holds the per-state strings. **Untrusted text** (spec §10.2): alert names,
templates and their rendered messages, rule names and the Owner's system messages render as plain text: no markup, no
automatic links, no `dangerouslySetInnerHTML`, each in an isolated bidirectional span. **Truncation limits:** an alert
name (API limit 120) is one line with an ellipsis on the toast, the SCR-014 row and the SCR-090 cell, and at most 64
characters with the qualifier in the OS notification; a rendered message (template limit 500) is two lines on the toast
(three comfortable) and the SCR-014 row and never in the OS notification; an Owner system title (500) is two lines with
`Show all`; a `context` string is cut at 200 characters with `Show all`; the drawer wraps everything in full. The full
text is always reachable through the accessible name and the drawer.

| Key                     | String                                                                                                                                                                              | Where       |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| estimated qualifier     | "(estimated)"                                                                                                                                                                       | §2.5, §4.2  |
| estimated warning       | "CVD divergence is estimated: a heuristic detector, not a raw value. The alert can fire on a reading the detector later revises."                                                   | §3.6        |
| sound in the browser    | "Sound requires the desktop shell."                                                                                                                                                 | §3.4, §9.4  |
| boundary line           | "Alerts notify; to act automatically, create a rule."                                                                                                                               | §1 (D-1)    |
| in-app locked           | "Every alert is recorded in the app."                                                                                                                                               | §3.4        |
| rule link-out, gated    | "Your role can't change rules."                                                                                                                                                     | §1          |
| disarm title            | "Alert disarmed: CVD divergence data source unavailable"                                                                                                                            | §2.5, §4.2  |
| disarm why              | "The CVD divergence values stopped arriving at 14:02:07 UTC, so the alert was disarmed instead of firing on missing data. It stays off until you enable it."                        | §2.5        |
| enable confirm          | "If the source is still unavailable, it will disarm again and tell you."                                                                                                            | §2.5        |
| OS disarm title         | "Alert disarmed: {name}"                                                                                                                                                            | §4.1, §4.7  |
| storm summary title     | "{n} more alerts in the last minute — held as one summary"                                                                                                                          | §4.5 (SR-5) |
| storm summary body      | "{first}{others}. 20 alerts had already fired within 60 seconds, so these were recorded here without a toast, sound or desktop notification. Open the alert centre to review them." | §4.5 (SR-5) |
| after a gap             | "{n} alerts fired while disconnected — Open Notifications"                                                                                                                          | §4.5        |
| counted toast           | "4 more alerts — Open Notifications"                                                                                                                                                | §4.5        |
| counted pill            | "3 alerts — Open Notifications"                                                                                                                                                     | §4.8        |
| enable again            | "Alert enabled. It fires once more, then disarms."                                                                                                                                  | §4.4        |
| locked cell             | "Cannot be muted — critical"                                                                                                                                                        | §6.2        |
| locked row caption      | "Critical · always delivered"                                                                                                                                                       | §6.2        |
| centre column, kept     | "Kept in Notifications"                                                                                                                                                             | §6.2        |
| centre column, not yet  | "Not kept yet"                                                                                                                                                                      | §6.2        |
| not kept yet, described | "Shown as it happens; Notifications keeps it once its history is available."                                                                                                        | §6.2        |
| sound only, disabled    | "Sound can't be the only channel — turn on the toast or desktop notification first."                                                                                                | §6.3        |
| sound only, refused     | "Sound can't be the only channel: keep the toast or desktop notification on, or turn sound off first."                                                                              | §6.3        |
| quiet hours statement   | "Critical events still notify during quiet hours."                                                                                                                                  | §6.4        |
| validation: condition   | "Add a condition."                                                                                                                                                                  | §3.6        |
| validation: cooldown    | "Use at least 5 seconds."                                                                                                                                                           | §3.6        |
| validation: expiry      | "Pick a time in the future."                                                                                                                                                        | §3.6        |
| validation: name        | "Name the alert."                                                                                                                                                                   | §3.6        |
| validation: name length | "Use at most 120 characters."                                                                                                                                                       | §3.6        |
| validation: name taken  | "You already have an alert with this name."                                                                                                                                         | §3.6, §3.7  |
| validation: template    | "Use at most 500 characters."                                                                                                                                                       | §3.6        |
| validation: braces      | "The message has an unclosed '{{' or a stray '}}'."                                                                                                                                 | §3.6        |
| validation: timeframe   | "A bar-close alert needs a timeframe such as 1m, 5m, 1h or 1d."                                                                                                                     | §3.6        |
| save pending            | "Still checking the condition…"                                                                                                                                                     | §3.6        |
| may already exist       | "This alert may already exist — Open it"                                                                                                                                            | §3.7        |
| changed elsewhere       | "The alert was changed by another session; reload and retry."                                                                                                                       | §3.7        |
| deleted                 | "This alert was deleted."                                                                                                                                                           | §3.7, §4.6  |
| vocabulary, saving off  | "Changes can't be saved while the rule engine is unavailable."                                                                                                                      | §3.8        |
| export disabled         | "Export waits for the values at fire time."                                                                                                                                         | §2.6        |
| snooze until tomorrow   | "Until tomorrow — 00:00 Europe/Berlin (22:00 UTC)"                                                                                                                                  | §2.6 (D-5)  |
| bulk enable             | "Enable 3 alerts?"                                                                                                                                                                  | §2.7        |
| bulk disable            | "Disable 3 alerts?"                                                                                                                                                                 | §2.7        |
| bulk delete             | "Delete 3 alerts?"                                                                                                                                                                  | §2.7        |
| bulk delete body        | "This can't be undone. Their past firings stay in Notifications."                                                                                                                   | §2.7        |
| filtered empty          | "No alerts match these filters."                                                                                                                                                    | §2.5        |
| fired tab empty         | "Nothing has fired yet."                                                                                                                                                            | §2.5        |
| snoozed tab empty       | "Nothing snoozed."                                                                                                                                                                  | §2.5        |
| disconnected            | "Disconnected — last data 00:12"                                                                                                                                                    | §2.5, §5.5  |
| resyncing (SCR-090)     | "Resyncing alerts…"                                                                                                                                                                 | §2.5        |
| resyncing (SCR-014)     | "Resyncing notifications…"                                                                                                                                                          | §5.5        |
| muted category line     | "Muted: Rule actions — still recorded here"                                                                                                                                         | §5.5        |
| muted row               | "Muted · recorded"                                                                                                                                                                  | §5.5, §6.7  |
| overflow                | "Showing the newest 500"                                                                                                                                                            | §5.5        |
| saved on this device    | "Saved on this device"                                                                                                                                                              | §6.8        |
| save failed             | "Not saved: the server didn't respond. Try again."                                                                                                                                  | §6.8        |
| save refused            | "Not saved: that value isn't allowed."                                                                                                                                              | §6.8        |
| account not granted     | "This account isn't assigned to you."                                                                                                                                               | §2.9, §3.7  |
| view-as                 | "Read-only while viewing as {user}."                                                                                                                                                | §2.9        |

## Component contracts

The contracts are `15`'s entries, entered by this PR (BQ-6), so E40-S01 and E40-S02 build from the catalogue: **CMP-163
AlertRow**, **CMP-164 AlertBuilderForm** and **CMP-165 AlertFiredToastGroup** (props, states, a11y, tokens, the Storybook
lists and tests; spec §7.1–§7.3), and the documented variants of **CMP-045, CMP-046, CMP-060, CMP-209, CMP-212** and
**CMP-012**'s count badge as the "E40-D02" line of each entry (spec §7.4), never forks. Where E05-S03's shipped Toast
differs from the spec, the shipped code wins and CMP-045's line says so. The Storybook lists are PROPOSED until
engineering agrees them on E40-S02 (the ticket's test plan); the orchestrator's text lens and the `15` look stand in for
the design-system review (agent-delivery adaptation).

## A11y contract (normative; E40-Q02 audits against it)

Lifted from D01 by cited id: the text is D01's at the cited line (`D01` = `docs/design/a11y/e40-alerts-a11y-review.md`,
merged as #3979), applied where the last column says; `--check` fails when a pin no longer lands on its id. The focus
orders are spec §11.2, the zoom, density and forced-colours rules §11.3.

| Id    | D01 subject                                                            | D01       | Applied in E40-D02                                         |
| ----- | ---------------------------------------------------------------------- | --------- | ---------------------------------------------------------- |
| LR-0  | Architecture: one announcer owns every alert-system announcement       | `D01:27`  | §4.3; E40-S02 builds the two CMP-212 regions               |
| LR-1  | SCR-092 fired-alert toast (CMP-045 / CMP-165) — severity info, warning | `D01:31`  | §4.3                                                       |
| LR-2  | SCR-092 fired-alert toast — severity error, critical (K2)              | `D01:32`  | §4.3 (X-30)                                                |
| LR-3  | CMP-165 batched toast / SR-5 storm summary                             | `D01:33`  | §4.3, §4.5                                                 |
| LR-4  | SCR-092 detail drawer (CMP-046)                                        | `D01:34`  | §4.6 (X-32)                                                |
| LR-5  | Order-reject toast; risk lockout; kill switch; position-protection …   | `D01:35`  | §4.3: never a user alert's region                          |
| LR-6  | SCR-014 notification-centre list (CMP-060)                             | `D01:36`  | §5.1, §5.5                                                 |
| LR-7  | SCR-014 bell (top bar)                                                 | `D01:37`  | §5.3                                                       |
| LR-8  | SCR-090 alerts centre                                                  | `D01:38`  | §2.7, §2.8                                                 |
| LR-9  | SCR-091 editor                                                         | `D01:39`  | §3.1, §3.5                                                 |
| LR-10 | SCR-115 settings matrix                                                | `D01:40`  | §6.6, §6.8                                                 |
| LR-11 | Announcements panel (05 §6.2 bullet 3 names the panel and no screen; … | `D01:41`  | not drawn (DF-14)                                          |
| LR-12 | Rule-fire toast (K4)                                                   | `D01:42`  | §4.3                                                       |
| T-1   | Fired-alert toast, info / warning (LR-1)                               | `D01:50`  | §4.3, §6.5                                                 |
| T-2   | Fired-alert toast, error / critical (LR-2)                             | `D01:51`  | §4.3                                                       |
| T-3   | Batched toast / storm summary (LR-3)                                   | `D01:52`  | §4.3, §4.5                                                 |
| T-4   | Order-reject toast (LR-5)                                              | `D01:53`  | §4.3 (the order owner's toast)                             |
| T-5   | Lockout / kill-switch / disconnect / protection-failure banner (LR-5)  | `D01:54`  | the banner owners (E17-D01, E39-D01)                       |
| T-6   | Snooze remaining time (SCR-090, toast action)                          | `D01:55`  | §2.5, D-5                                                  |
| T-7   | Quiet-hours window                                                     | `D01:56`  | §6.4                                                       |
| T-8   | Sound                                                                  | `D01:57`  | §4.5, §9.1                                                 |
| T-9   | Desktop (OS) notification                                              | `D01:58`  | §4.7                                                       |
| T-10  | "Undo" on a toast (SCR-015, 5 s)                                       | `D01:59`  | not used: Disable offers `Enable`, Delete confirms (§11.1) |
| KM-1  | Open the notification centre                                           | `D01:67`  | §5.1, §11.2                                                |
| KM-2  | Move through items                                                     | `D01:68`  | §5.6, §11.2                                                |
| KM-3  | Action an item                                                         | `D01:69`  | §5.6                                                       |
| KM-4  | Mark all read / mark above as read                                     | `D01:70`  | §5.3                                                       |
| KM-5  | Snooze from the toast                                                  | `D01:71`  | §4.3                                                       |
| KM-6  | Dismiss / escape                                                       | `D01:72`  | §4.3, §4.6                                                 |
| KM-7  | SCR-090 table                                                          | `D01:73`  | §2.7, §11.2                                                |
| KM-8  | SCR-091 editor                                                         | `D01:74`  | §3.2, §11.2 (X-13, X-33)                                   |
| KM-9  | SCR-115 matrix                                                         | `D01:75`  | §6.2, §11.2                                                |
| KM-10 | SCR-115 sound preview and test notification                            | `D01:76`  | §6.5, §11.2 (X-31)                                         |
| KM-11 | Everywhere                                                             | `D01:77`  | everywhere                                                 |
| KM-12 | SCR-117 Announcements panel (LR-11)                                    | `D01:78`  | not drawn (DF-14)                                          |
| AR-1  | Single-alert path                                                      | `D01:86`  | §4.3                                                       |
| AR-2  | Digest path                                                            | `D01:87`  | §4.3                                                       |
| AR-3  | One digest                                                             | `D01:88`  | §4.3, §4.5 (CC-7)                                          |
| AR-4  | Never digested:                                                        | `D01:89`  | §4.3, §6.2                                                 |
| AR-5  | Cadence independence                                                   | `D01:90`  | §4.3                                                       |
| AR-6  | Readable on demand                                                     | `D01:91`  | §5.4, §2.6                                                 |
| AR-7  | Snapshot and reconnect                                                 | `D01:92`  | §4.5 step 5, §2.5, §5.5                                    |
| NC-1  | Severity info / warning / error / critical                             | `D01:100` | §4.2, §5.1                                                 |
| NC-2  | Kind                                                                   | `D01:101` | §5.1, §5.2                                                 |
| NC-3  | Alert status (SCR-090)                                                 | `D01:102` | §2.3 (X-29)                                                |
| NC-4  | Snoozed                                                                | `D01:103` | §2.3, §2.5                                                 |
| NC-5  | Disabled alert                                                         | `D01:104` | §2.3, §2.5                                                 |
| NC-6  | Delivery failed / blocked                                              | `D01:105` | §2.5 (D-7)                                                 |
| NC-7  | Muted (symbol / category)                                              | `D01:106` | §5.5, §6.7                                                 |
| NC-8  | Suppressed (storm)                                                     | `D01:107` | §2.5, §2.6                                                 |
| NC-9  | Locked row (critical override)                                         | `D01:108` | §6.2                                                       |
| NC-10 | Estimated detector alert                                               | `D01:109` | §2.5, §3.6, §4.2                                           |
| NC-11 | Unread                                                                 | `D01:110` | §2.5, §5.3                                                 |

## Motion table (spec §8; `data-motion` is the single source, E11-D06 D21)

| Element                                | Token: duration, easing (motion-safe)                                                              | motion-reduce counterpart                                                  |
| -------------------------------------- | -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Toast enter                            | `translateY` 8 px → 0, opacity 0 → 1; `motion.duration.fast`, `motion.easing.decelerate`           | fade only: opacity 0 → 1; `motion.duration.fast`, `motion.easing.standard` |
| Toast exit (dismiss, timeout, snooze)  | opacity 1 → 0, `translateX` 0 → 8 px; `motion.duration.fast`, `motion.easing.accelerate`           | fade only: opacity 1 → 0; `motion.duration.fast`, `motion.easing.standard` |
| Stack reflow                           | siblings by `transform`; `motion.duration.normal`, `motion.easing.standard`                        | instant                                                                    |
| Toast content swap, badges, tab counts | instant                                                                                            | instant                                                                    |
| Drawer open / close (SCR-014, detail)  | `translateX` 100 % → 0; `motion.duration.normal`, `motion.easing.decelerate` (close `.accelerate`) | instant                                                                    |
| Group expand, row status change        | instant                                                                                            | instant                                                                    |
| Created-row mark (SCR-090)             | `color.surface.selected` for 2 s, removed without a fade                                           | the same (no motion)                                                       |

Only transform and opacity animate; nothing pulses, blinks, loops or shakes; nothing moves on its own for more than 5 s;
no countdown bar (X-17).

## Interaction spec

- **Snooze** (D-5; flagged until CC-4): presets 15 min · 30 min · 1 h · Until tomorrow, each showing its absolute end;
  "Until tomorrow" ends at 00:00 in the quiet-hours IANA zone, printed with the zone and UTC; `Wake now` ends it; snoozing
  from the toast acknowledges (spec §2.6, §4.4).
- **Bulk actions** (D-6): select by `Space`, the first-column box or `Shift+click` for a range; Enable, Disable and
  Delete each confirm with CMP-044 naming the count and the consequence; requests go one per alert with bounded
  concurrency; the bar reports per item and failed rows stay selected (spec §2.7). No bulk snooze or mute.
- **Mark above as read** (D-25): `Shift+click` on a row, or `Ctrl+Shift+Enter` inside the drawer, acknowledges every
  unread alert row above it; `Mark all read` acknowledges all; only alert rows have read state; without `alerts:write`
  both are disabled with E09-D09's reason (spec §5.3).
- **Deep links** (D-38): only the three route shapes the server builds, with UUID ids, through E10's deep-link contract;
  anything else is not followed and is logged. An alert row opens its firing's detail drawer; a rule row
  `/rules/{id}/history`; an order row `/positions/order/{id}`; `Open chart` opens a new chart panel at the symbol and
  interval and jumps to the fire time, never retargeting an existing pane (spec §4.4, §5.6, §10.3).
- **Placement** (D-20): the toast never covers order entry, an armed ticket, SCR-063, the Safety cluster, an open
  dialog's footer or the focused element; bottom-right left of the rail, else top-right, else the counted pill (spec §4.8).

## Budgets the design assumes

| Budget                                                                                                | Spec        |
| ----------------------------------------------------------------------------------------------------- | ----------- |
| ≤ 2 s condition-to-toast (1 s target; the first toast never waits on a batch)                         | §4.5, DF-15 |
| ≤ 1 Hz list updates on SCR-090, repainted in place                                                    | §2.8        |
| SCR-014 virtualised: 500 rows at ≤ 8 ms scripting per scroll frame; unread count every 250 ms at most | §5.3, §5.5  |
| ≤ 200 KB sounds, each ≤ 100 KB, preloaded once (80,428 bytes as generated)                            | §9.1, §9.4  |
| ≤ 300 ms validation round-trip, with `Saving…` and the pending line past 300 ms                       | §3.6        |

## Events per surface (analytics client-side; audit server-side, never duplicated by the client)

| Surface | Analytics                                                                                                                              | Audited (server)                                                                                                                              |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| SCR-090 | `alerts.list_viewed`, `alerts.filtered`, `alert.snoozed`, `alerts.bulk_action {action, count, failed}`                                 | `alert.created`, `alert.updated`, `alert.deleted`, `alert.enabled` / `alert.disabled` (X-10), `alert.denied`, `alert.fired`, `alert.disarmed` |
| SCR-091 | none: the save itself is the record                                                                                                    | `alert.created`, `alert.updated`                                                                                                              |
| SCR-092 | `alert.toast_shown {severity, grouped}`, `alert.toast_actioned {action}`, `alert.detail_opened {from}`, `alert.snoozed {preset, from}` | `alert.fired`, `alert.delivery_acked`, `alert.deliveries_acked`, `alert.desktop_outcome`                                                      |
| SCR-014 | `notifications.opened`, `notifications.filtered`, `notifications.item_actioned {kind, action}`, `notifications.mark_all_read`          | `alert.delivery_acked`, `alert.deliveries_acked`                                                                                              |
| SCR-115 | `notifications.preference_changed {event, channel, enabled}`, `notifications.test_sent {channel}`                                      | `notifications.risk_channel_muted` (high severity; the UI offers no control that sends one)                                                   |

## Deferred (each with its ticket and the interim behaviour; spec §17.3)

| DF    | Item                                                                                                    | Ticket                                     | Interim                                                          |
| ----- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------ | ---------------------------------------------------------------- |
| DF-1  | instances from the E36 library (Part A DoD item 4 `[~]`)                                                | E36-D02                                    | stand-ins named identically (D-2)                                |
| DF-2  | the owner's explicit acceptance of CO-1..CO-12 and the DN, RF and UA choices (OQ-2, OQ-5, OQ-13, OQ-15) | #2701 owner queue                          | D01's interim defaults, drawn                                    |
| DF-3  | CO-13, the OCO reconciliation race                                                                      | #2701 owner queue                          | a candidate, not locked                                          |
| DF-4  | the liquidation-proximity distance (OQ-3; no emitter, D01 G3)                                           | E39                                        | its row drawn locked                                             |
| DF-5  | whether user alerts of severity Critical pass the storm gate (OQ-4)                                     | #2701 owner queue; E40-S02 builds a ruling | the gate applies to every alert, as built                        |
| DF-6  | the email channel                                                                                       | E40-S03 with E04                           | not drawn                                                        |
| DF-7  | default keys for "Open notifications" and "New alert" (OQ-6)                                            | E49                                        | command-palette entries                                          |
| DF-8  | the `position.*` leaves in messages                                                                     | E40-X01                                    | in-app only (D-23)                                               |
| DF-9  | `push` in `AlertChannel` (OQ-8)                                                                         | E40-T05                                    | kept in the enum, not drawn                                      |
| DF-10 | the alert's level drawn on the chart                                                                    | E11                                        | `Show on chart` opens the symbol at the interval                 |
| DF-11 | the mute chip in the chart header and the watchlist row                                                 | E11, the watchlist owner                   | the chip on these surfaces only                                  |
| DF-12 | a per-rule toast toggle (OQ-10)                                                                         | E36                                        | per category only                                                |
| DF-13 | the strict one-announcement storm variant (OQ-B1)                                                       | #2701 owner queue                          | the first item, then one digest (AR-3)                           |
| DF-14 | the announcements panel (LR-11, OQ-B5)                                                                  | SCR-117 (E47)                              | the locked kinds of §6.2 stay fixed                              |
| DF-15 | the 2 s budget and the storm constants against a recorded window (OQ-11, SR-7)                          | E40-Q02                                    | 2 s budget, 1 s target; 20 per 60 s                              |
| DF-16 | the "(estimated)" label form (E25-D01 C15, Q4)                                                          | E25-D01                                    | "(estimated)" with CMP-227                                       |
| DF-17 | DS-CR-1..DS-CR-4                                                                                        | E05                                        | `.strong` for the light warning edge; `text.tertiary` boundaries |
| DF-18 | the order-entry regions behind the placement rule                                                       | E30-D02 (#3923), merged                    | closed: §4.8 takes the regions from its geometry                 |
| DF-19 | the `05`, `14` and `17` halves of AM-5, AM-6, AM-7, AM-8 and AM-10                                      | their owners                               | hand-offs                                                        |

## Open questions

Open questions: none. Every decision is made in the spec (the D rows, spec §16) or deferred above with its ticket and its
interim behaviour; the contract change requests are spec §17.1's CC rows, posted once on E40-S01 (RULED Q3).
