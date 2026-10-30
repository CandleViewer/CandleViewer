# E15-D12 — Per-component hand-off (`16` §11.4; the narrow collapse, SCR-153's two E15 rows, SCR-150 restore)

Two catalogue entries change — **CMP-092 DegradedModeBanner** (the two E15 rows, the session-long dismissal, the actions and the Details) and **CMP-251 DockTabGroup** (the collapsed form, the overflow and the pending conditions, after E15-D13's PR 2 creates it) — and four entries are used as they are: CMP-011 `neutral` (the "Reduced" chip), CMP-028 `info` `inline` (the DOM's depth control), CMP-069 `inline` (the Details) and CMP-038 (a waiting body). The pack is [E15-D12.md](E15-D12.md) and the rules are [the spec](../specs/e15-responsive-and-degraded.md); every "§", "A-n" and "CP-n" below is theirs, and the catalogue text itself is the pack's §C (this file never restates a props table, C-16.5). Every measured figure is the tool's (`docs/design/_tools/e15_d12_responsive_audit.py`).

## Hand-off checklist (E15-D12, #366)

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason (`16` §11.4, §13.3).

| Item                     | CMP-092 (the two E15 rows)                                                                     | CMP-251 (collapsed, overflow, conditions)                                  |
| ------------------------ | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Final Penpot link        | [ ] PR 3, page `E15-D12 responsive and degraded`                                               | [ ] PR 3                                                                   |
| Variants × states        | [x] the spec §8; A-8 … A-10                                                                    | [x] the spec §3, §5; A-12 … A-14 (after E15-D13's PR 2)                    |
| Keyboard table           | [x] Table K                                                                                    | [x] Table K                                                                |
| Accessible name and role | [x] Table N                                                                                    | [x] Table N                                                                |
| Live data                | [x] polite once per row; the exit once (CP-6)                                                  | [x] the collapse once per crossing (CP-12); a disarm once (CP-15)          |
| Motion pair              | [x] none new; the content appears at once (E15-D14 owns any timing)                            | [x] none; a tab switch is a cut (E15-D13's CMP-251)                        |
| Density notes            | [x] Table R                                                                                    | [x] Table R                                                                |
| Essential exceptions     | [x] none                                                                                       | [x] the four not-offered controls, each with its reason (the spec §4)      |
| Tokens used              | [x] Table R; no new token (BQ-17)                                                              | [x] Table R; E15-D13's                                                     |
| Data contract            | [x] none new; the probe's `{p95FrameMs, recommendedMaxPanes, recommendedProfile}` is E15-K01's | [x] none new; the stored layout is never written by the collapse           |
| Contrast and CVD         | [x] the spec §11; the word carries the chip                                                    | [x] E15-D13's (CMP-042's tabs); the error glyph and word carry a condition |
| Storybook                | [x] Table S                                                                                    | [x] Table S                                                                |
| Sign-off                 | [ ] the orchestrator's design approval (BQ-20)                                                 | [ ] as CMP-092                                                             |

## Table K — keyboard

| Where                      | Keys                                                         | Result                                                                                                    |
| -------------------------- | ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| the suggestion row         | `Tab` through Use reduced profile, Details, Not now          | each a button; `Enter` / `Space` acts; Details toggles its region (`aria-expanded`)                       |
| its Details                | `Tab` into Don't ask again on this device                    | a button; acting closes the row and announces nothing more                                                |
| accepting                  | `Enter` on Use reduced profile                               | the reduced row replaces the suggestion in place; focus lands on its Restore full quality                 |
| the toolbar's ⋯ menu       | `Enter` on Display quality on this device ▸, arrows, `Enter` | a submenu of two radio items (Full, Reduced) with the caption; `Esc` returns to the parent                |
| the command palette        | type "display quality"                                       | Reduce display quality · Restore full display quality                                                     |
| the collapsed tab row      | arrows, `Home`, `End`; `Shift+F10` on a tab                  | move and select (automatic activation); the panel's menu, with the not-offered items as availability rows |
| the overflow button        | `Enter`, arrows, `Enter`                                     | a menu of the remaining panels with their conditions; choosing one activates its tab                      |
| chrome regions             | `Ctrl+\`, `F6`                                               | unchanged; the tab row is one stop                                                                        |
| trading hotkeys            | as the keymap                                                | act only on the visible, focused panel; never on a hidden tab (A42)                                       |
| a waiting panel after 10 s | `Tab` to Retry                                               | retries that panel only (PROPOSED)                                                                        |

## Table N — names and roles

| Element                | Role                             | Accessible name (or text)                                                                                                           |
| ---------------------- | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| a banner row           | `status` (CMP-092 `info`)        | its message and still-works sentence (CP-1, CP-4, CP-5)                                                                             |
| the Details control    | `button`, `aria-expanded`        | "Details"; the region it controls is labelled by its first sentence                                                                 |
| the "Reduced" chip     | none (text in the header)        | "Reduced: heatmap {depthReduced} levels, updates every 200 ms" (CP-7); the region's description repeats CP-4's still-works sentence |
| the collapsed tab row  | `tablist`                        | "Panels"                                                                                                                            |
| a tab                  | `tab`                            | the panel's region name, then its conditions (CP-17); an order-capable tab adds the environment and the arm word                    |
| the overflow button    | `button`, `aria-haspopup="menu"` | CP-16                                                                                                                               |
| the slow-restore line  | `status`                         | CP-18                                                                                                                               |
| a waiting body         | `status` (CMP-038)               | CP-19, then CP-20                                                                                                                   |
| the ready announcement | the shell's polite region        | CP-22                                                                                                                               |

## Table S — stories (names only; builders)

| Entry   | Stories added                                                                                                                                                                        | Builder                              |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------ |
| CMP-092 | GpuSuggestion, GpuSuggestionDetailsOpen, SuggestionNotNowStaysForSession, ReducedProfileActive, FullByChoice, ProfileExit, GpuWithBackendRow, Narrow1024, Comfortable, ReducedMotion | E15-S08 (#561), in `apps/web` (C-19) |
| CMP-251 | Collapsed1100, CollapsedOverflow1024, PendingConditions, HiddenArmedDisarmed (each in dark / light × compact / comfortable)                                                          | E15-S08 (#561)                       |

## Table R — redlines (compact / comfortable)

| Element                                | Height                                                    | Tokens                                                                                                       |
| -------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| a banner row (one line at 1280 × 800)  | 32<!--=BUDGET:banner.c--> / 40<!--=BUDGET:banner.f-->     | `size.control.*` + `space.1` × 2; `color.status.info.subtle`, `.strong`; `color.text.primary`, `.secondary`  |
| the collapsed tab row                  | 24<!--=BUDGET:tabgroup.c--> / 32<!--=BUDGET:tabgroup.f--> | E15-D13's CMP-251 row, `space.panelheader.height.*` once PR 2T ships it (`size.control.*` until then)        |
| the restore notice row (the slow line) | 32<!--=BUDGET:restore.c--> / 40<!--=BUDGET:restore.f-->   | `size.control.*` + `space.1` × 2; `type.ui.body`, `color.text.secondary`                                     |
| the "Reduced" chip                     | inside the header row                                     | CMP-011 `neutral`: `color.neutral.subtle`, `color.border.default`, `color.text.secondary`, `type.ui.caption` |
| the DOM's depth callout                | its content                                               | CMP-028 `info` `inline`: `color.status.info.subtle`, `border.thick` edge in `color.status.info.strong`       |
