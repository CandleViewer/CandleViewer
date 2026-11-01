# E47-S08 settings band: NVDA step list (human-owed)

Standard: WCAG 2.2 AA, `docs/plan/05-accessibility-standard.md`; story US-SET-001 (settings fully keyboard
operable, every control labelled with persistent text, scope clear), US-SET-002 (hotkey editor).
Status: **not run.** A screen-reader pass cannot be executed by an agent; a human tester runs these steps and
records the result in the table at the end. Automated cover already in CI: `apps/web/e2e/settings-keyboard.spec.ts`
(keyboard only), the axe and tree collectors over R-201 to R-205 (`apps/web/e2e/a11y/screens.ts`), and the
unit tests under `apps/web/test/features/settings/` and `apps/web/test/routes/settings-routes.test.tsx`.

Set-up: NVDA with Firefox and with Chrome, speech viewer on, browse mode default, the app signed in as an Owner
in Demo at `/settings`. Browser zoom 100 % first, then 200 % (step 12).

## Steps

| #   | Do                                                                             | Expect NVDA to say                                                                                                          |
| --- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| 1   | Open `/settings`.                                                              | The page title "Profile and security" (the profile section opens); focus on the main heading.                               |
| 2   | Press `D` through landmarks.                                                   | One "main" landmark, one "navigation Settings" landmark and the "Primary" rail; no second main.                             |
| 3   | Tab to the nav.                                                                | "Settings navigation", then the open section as a link, "current page", with its one-line description.                      |
| 4   | Press Tab again.                                                               | Focus leaves the nav (one Tab stop), it does not step through the other eight sections.                                     |
| 5   | Shift+Tab back, press Down, Up, End, Home.                                     | Each section's name and description; a section not built reads "Trading defaults, button, unavailable" and why.             |
| 6   | On a disabled section press Enter.                                             | Nothing happens; the reason is still read on re-focus.                                                                      |
| 7   | Tab to "Search settings", type `motion`, stop.                                 | Silence while typing; about 0.6 s after the last key one phrase "2 results: Accessibility; Accessibility > Reduced motion". |
| 8   | Arrow through the results in browse mode.                                      | Each result's path ("Settings > Accessibility > Reduced motion"), its description and "Scope: Per user".                    |
| 9   | Press Esc in the search.                                                       | The query clears, the section returns; no stale count is read.                                                              |
| 10  | Open Appearance. Tab to the chart palette group.                               | "Chart palette, group", its description, then "Scope: ..." (today `[scope: pending ruling]`, a placeholder).                |
| 11  | Arrow between the two palette radios; Tab to the invert checkbox, press Space. | Radio name and "checked"; checkbox "Invert buy/sell colours, checked", then the description.                                |
| 12  | Zoom to 200 %; repeat steps 3 and 7.                                           | Nav and search still reachable and read; no horizontal scroll, nothing clipped.                                             |
| 13  | Open Accessibility from the nav (Enter on the link).                           | Focus moves to the "Accessibility" heading, read as heading level 2; "current page" on the nav link.                        |
| 14  | Open Hotkeys. Tab to a key field.                                              | "Key for <command>", the visible label read once; the row's Save names its command.                                         |
| 15  | Rebind a command to a key another command holds.                               | One message through the announcer naming both commands and "Swap is available after Save."                                  |

## Record (tester fills in)

| Step | NVDA + Firefox | NVDA + Chrome | Notes / defect id |
| ---- | -------------- | ------------- | ----------------- |
| 1-15 | pending        | pending       |                   |

A failure is filed as an `a11y` bug against E47-S08 with the step number and what was said; do not edit the
expected column to match.
