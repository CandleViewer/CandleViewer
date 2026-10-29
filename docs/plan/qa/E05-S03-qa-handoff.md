# E05-S03 (#266) QA handoff: the molecules

For the QA pass of E05-Q01 on the fifteen E05-S03 molecules: CMP-040 FormField, CMP-041 Menu, CMP-042 Tabs, CMP-043 Dialog, CMP-044 ConfirmDialog, CMP-045 Toast, CMP-046 Drawer, CMP-047 DatePicker / DateRangePicker, CMP-048 Combobox, CMP-049 Table, CMP-050 Card, CMP-054 SearchBox, CMP-059 CommandPalette, CMP-065 FormSection and CMP-069 InfoPanel. The tests carry no Gherkin scenario text, so this note is the scenario-name to test index (DoD: "scenarios covered by automated tests"). Paths are under `packages/ui/`; `T` is `test/`, `S` is `src/components/`. Divergences from `15` are its "As built (E05-S03)" lines; keyboard and name/role tables are in `src/docs/Molecules.mdx` (Storybook: Molecules/Overview).

## Scenario to test

| Scenario (ticket)                          | Covered by                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Form field wires label, help and error     | `T/FormField.test.tsx` "wires the label, the help and the error to the control" and "keeps the label when a value is typed: the placeholder is never the name"; the error node in "pre-renders one polite, atomic error node and renders each message once".                                                                                                                                                                                                |
| Dialog focus contract                      | `T/Dialog.test.tsx` "Gherkin 'Dialog focus contract': focus in, Tab trapped, Escape closes, focus returns, page inert" and "native inert where the engine has it; data-cv-inert-exempt regions are spared"; `aria-modal` in "closed: renders nothing; open: a modal dialog named by its title and described"; the return fallback in "returns focus to the host's fallback when the opener is gone, never to body"; story `S/Dialog.stories.tsx` `Default`. |
| Hold-to-confirm gate                       | `T/ConfirmDialogHold.test.tsx` "Gherkin 'Hold-to-confirm gate': a release at 400 ms fires nothing and resets the progress"; the keyboard-only path in "keyboard: holding Enter (repeats included) for the duration fires key-hold" and "keyboard: a second non-repeat Enter 250 ms – 5 s later fires double-press"; fake timers in "a pointer hold fires at the duration, never before, once".                                                              |
| Typed confirm                              | `T/ConfirmDialog.test.tsx` "Gherkin 'Typed confirm': with FLATTEN required, other text keeps Confirm disabled with the instruction" (case, spaces and a short match stay disabled; Enter in the field never confirms).                                                                                                                                                                                                                                      |
| Table reflow at 200% zoom                  | `T/Table.test.tsx` (describe "Table (CMP-049) stacked reflow") "tracks a font-size change at the same width (200 % zoom) through the em probe", "keeps explicit table roles while stacked: …" and "stacked cells: the first is the heading line; …"; the browser check is story `S/Table.stories.tsx` `Reflow` (compact, root font size 200 % on the 1280 × 800 frame, then at 640 px: stacked, no sideways overflow, every column's value present).        |
| Toast does not steal focus                 | `T/Toast.test.tsx` (describe "ToastRegion") "Toast does not steal focus: focus stays in the typing field, the toast is announced politely" and "speaks assertively only for danger or an error; politeness overrides; each toast once".                                                                                                                                                                                                                     |
| Combobox keyboard                          | `T/Combobox.test.tsx` "Gherkin 'Combobox keyboard': the arrows move the active option, named by aria-activedescendant", "↓ opens a closed list on the first option; Alt+↓ opens without moving; Alt+↑ closes", "Enter chooses the active option, shows its label and closes; …" and "Esc closes the list and keeps the text, a second Esc bubbles; leaving never chooses".                                                                                  |
| Test plan: tabs roving tabindex            | `T/Tabs.test.tsx` "renders a named tablist, tabs wired to their panels, one tab stop on the selected tab", "automatic: arrows, Home and End move and select, wrapping; …" and "manual: arrows move focus only; Enter or Space selects the focused tab".                                                                                                                                                                                                     |
| Test plan: table keyboard navigation       | `T/Table.test.tsx` "keyboard header-sort: Enter sorts ascending, then descending; Space too", "puts no Tab stop in the body: …", "is one Tab stop: in on the first body cell, …" and "keyboard matrix: arrows by cell (the header row included), Home / End, Ctrl+Home / Ctrl+End, clamped at the edges".                                                                                                                                                   |
| Test plan: hold timing with fake timers    | `T/ConfirmDialogHold.test.tsx` "a pointer hold fires at the duration, never before, once" and "clamps holdDurationMs to 300–2,000 ms, 800 by default (H2)".                                                                                                                                                                                                                                                                                                 |
| Test plan: axe per story                   | `pnpm storybook:test` plays every story with axe (zero serious or critical). The explicit assertions: `aria-modal` (Dialog, above), toast politeness (Toast, above), form-field description wiring (FormField, above); `T/CommandPalette.test.tsx` "has no serious or critical axe violation with every row kind showing".                                                                                                                                  |
| Security: the hold gate resists automation | `T/ConfirmDialogHold.test.tsx` "a synthetic click(), a pointerdown/pointerup pair and two clicks never confirm nor arm" and "a pointer press never counts as the second press"; `T/ConfirmDialog.test.tsx` "the 400 ms guard: a stray click or a single Enter inside it does nothing" and "held-Enter repeats are ignored: one press, one confirm; …". The full gate × state matrix is below.                                                               |
| Observability: the gate in `onConfirm`     | `T/ConfirmDialogGateMatrix.test.tsx` "enabled: the full gesture confirms once, with the gate in the metadata" (per gate); the elapsed time in the "Typed confirm" test above.                                                                                                                                                                                                                                                                               |
| Performance: bounded rows in one frame     | Story `S/Table.stories.tsx` `Perf200Rows` (tagged `perf`, skipped on shared runners unless `CV_STORYBOOK_PERF=1`); the bound in `T/Table.test.tsx` "warns in development above 200 rows and still renders every row". Scroll lock without shift: `T/Dialog.test.tsx` "locks page scroll with the scrollbar's width given back as padding, and restores it" and story `S/Dialog.stories.tsx` `NoLayoutShift`.                                                |
| Full matrix, visual regression (E05-T04)   | `S/AllMolecules.stories.tsx` (Storybook: Molecules/All molecules matrix): the at-rest page per theme × density, with the stacked Table at a 200 % text scale (its play asserts the stacked layout and no sideways overflow), and Dialog, ConfirmDialog, Drawer and CommandPalette each open in their own story per theme × density. Interactive states stay in each molecule's own stories.                                                                 |

## Per molecule

| Molecule                   | Tests                                                                                                                           | Stories                        | Keyboard table (Molecules.mdx) |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ | ------------------------------ |
| CMP-040 FormField          | `T/FormField.test.tsx`, `T/formfield-css.test.ts`                                                                               | `S/FormField.stories.tsx`      | FormField                      |
| CMP-041 Menu               | `T/Menu.test.tsx`, `T/menu-css.test.ts`                                                                                         | `S/Menu.stories.tsx`           | Menu                           |
| CMP-042 Tabs               | `T/Tabs.test.tsx`, `T/tabs-css.test.ts`                                                                                         | `S/Tabs.stories.tsx`           | Tabs                           |
| CMP-043 Dialog             | `T/Dialog.test.tsx`, `T/overlay-layer.test.tsx`, `T/dialog-css.test.ts`                                                         | `S/Dialog.stories.tsx`         | Dialog                         |
| CMP-044 ConfirmDialog      | `T/ConfirmDialog.test.tsx`, `T/ConfirmDialogHold.test.tsx`, `T/ConfirmDialogGateMatrix.test.tsx`, `T/confirmdialog-css.test.ts` | `S/ConfirmDialog.stories.tsx`  | ConfirmDialog                  |
| CMP-045 Toast              | `T/Toast.test.tsx`, `T/toast-css.test.ts`                                                                                       | `S/Toast.stories.tsx`          | Toast and the toast region     |
| CMP-046 Drawer             | `T/Drawer.test.tsx`, `T/drawer-css.test.ts`                                                                                     | `S/Drawer.stories.tsx`         | Drawer                         |
| CMP-047 DatePicker / range | `T/DatePicker.test.tsx`, `T/DateRangePicker.test.tsx`, `T/isoDate.test.ts`, `T/datepicker-css.test.ts`                          | `S/DatePicker.stories.tsx`     | DatePicker, DateRangePicker    |
| CMP-048 Combobox           | `T/Combobox.test.tsx`                                                                                                           | `S/Combobox.stories.tsx`       | Combobox                       |
| CMP-049 Table              | `T/Table.test.tsx`, `T/table-css.test.ts`                                                                                       | `S/Table.stories.tsx`          | Table; Table, grid mode        |
| CMP-050 Card               | `T/Card.test.tsx`, `T/card-css.test.ts`                                                                                         | `S/Card.stories.tsx`           | Card                           |
| CMP-054 SearchBox          | `T/SearchBox.test.tsx`, `T/searchbox-css.test.ts`                                                                               | `S/SearchBox.stories.tsx`      | SearchBox                      |
| CMP-059 CommandPalette     | `T/CommandPalette.test.tsx`, `T/fuzzy.test.ts`                                                                                  | `S/CommandPalette.stories.tsx` | CommandPalette                 |
| CMP-065 FormSection        | `T/FormSection.test.tsx`, `T/formsection-css.test.ts`                                                                           | `S/FormSection.stories.tsx`    | FormSection                    |
| CMP-069 InfoPanel          | `T/InfoPanel.test.tsx`, `T/infopanel-css.test.ts`                                                                               | `S/InfoPanel.stories.tsx`      | InfoPanel                      |

The package entry and the catalogue ids: `T/index.test.ts` (describe "@candleviewer/ui molecules (E05-S03)") and `T/data-cmp.test.tsx` (describe "molecules carry their catalogue id").

## T2 and gated cases

Every gated control stays focusable with `aria-disabled="true"` and its reason as the description, and never acts (`docs/design/E09/E09-D09.md` §2.2 T2).

| Molecule               | Covered by                                                                                                                                                                                                                                                                                      |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CMP-040 FormField      | `T/FormField.test.tsx` "T2: the reason alone describes the control, once, and the field never validates" and "T2 suppresses an atom's own invalid verdict and message"                                                                                                                          |
| CMP-065 FormSection    | `T/FormSection.test.tsx` "T2: one notice under the heading that every gated field points at; no reason line per field" and "T2: a gated field never validates, so it never shows an error"                                                                                                      |
| CMP-042 Tabs           | `T/Tabs.test.tsx` "a gated tab: aria-disabled, the reason as its description, one shared reason line" and "a press selects a tab in both modes; a press on a gated tab refuses with the reason"                                                                                                 |
| CMP-041 Menu           | `T/Menu.test.tsx` "disabled, busy and gated items are reached by the arrows and never activated", "a gated item: full name, the reason as its description in the DOM at mount, re-shown once per press" and "a gated submenu item never opens; a press re-shows its reason, a plain → does not" |
| CMP-045 Toast          | `T/Toast.test.tsx` "gated actions keep their names, stay focusable and point at one reason line" and "a press on a gated action speaks its reason politely, once per press"                                                                                                                     |
| CMP-047 DatePicker     | `T/DatePicker.test.tsx` "T2: read-only field, aria-disabled button with the reason, and the dialog never opens"; `T/DateRangePicker.test.tsx` "T2: every field read-only behind the lock, one reason, the button aria-disabled, nothing opens"                                                  |
| CMP-048 Combobox       | `T/Combobox.test.tsx` "a T2 option is reached, never chosen: Enter or a press says its reason, once per press" and "T2 through CMP-079 and CMP-040: the lock leads the value; focusable, read-only; keys refused, said once"                                                                    |
| CMP-049 Table          | `T/Table.test.tsx` "T2 items are arrow-reachable, never activated, and keep their reason"                                                                                                                                                                                                       |
| CMP-059 CommandPalette | `T/CommandPalette.test.tsx` "a gated row is reachable and aria-disabled; Enter re-shows its reason once per press, never runs" and "a click on a gated row never runs it and re-shows its reason per click"                                                                                     |
| CMP-044 ConfirmDialog  | The gate matrix below (the "gated" column), with `T/ConfirmDialog.test.tsx` "H30: a Confirm gated mid-dialog keeps focus, speaks once assertively, then re-shows its reason politely"                                                                                                           |

Card, SearchBox, Dialog, Drawer and InfoPanel have no gated state of their own: a gated control inside them carries T2 itself.

## Keyboard matrices

The key tables are in `src/docs/Molecules.mdx`, one per molecule (listed above). The tests that walk each matrix:

- **Tabs:** `T/Tabs.test.tsx` "automatic: arrows, Home and End move and select, wrapping; …", "manual: arrows move focus only; …", "horizontal answers Left and Right only; …" and "vertical answers Up and Down only; …".
- **Menu:** `T/Menu.test.tsx` describes "Menu (CMP-041) keyboard", "Menu (CMP-041) submenus" and "Menu (CMP-041) context menu" (Shift+F10, the Menu key, a right-click).
- **Dialog, Drawer, layers:** `T/Dialog.test.tsx` (describe "the overlay layer stack") "Esc closes the topmost layer only: Tooltip, then Popover, then Dialog"; `T/Drawer.test.tsx` (describe "Drawer (CMP-046) non-modal") for the non-modal Tab path; `T/overlay-layer.test.tsx` "cycles at the edges both ways, and holds Tab when there is nothing to reach".
- **ConfirmDialog:** `T/ConfirmDialogHold.test.tsx` (describe "ConfirmDialog hold (CMP-044, H25)") for the held-Enter, double-press, Space and disarm keys; `T/ConfirmDialog.test.tsx` "order confirm: a dialog with its close button; Tab runs Cancel, Confirm, close, the body".
- **DatePicker:** `T/DatePicker.test.tsx` (describe "CalendarGrid keyboard matrix (APG Date Picker Dialog)") and "walks the grid across a year edge by keyboard, the heading following".
- **Combobox:** the Combobox rows in the scenario table above.
- **Table:** `T/Table.test.tsx` "keyboard matrix: arrows by cell (the header row included), Home / End, Ctrl+Home / Ctrl+End, clamped at the edges", "Page Up / Page Down move by the rows that fit the region, less the header" and "an interactive cell: its controls leave the Tab order; Enter or F2 moves in, Esc moves back".
- **CommandPalette:** `T/CommandPalette.test.tsx` "keyboard: ↓ / ↑ wrap, Home / End, PageUp / PageDown by ten; focus never leaves the input" and "Ctrl+Enter runs the group action and closes; …".
- **SearchBox, FormSection, InfoPanel, Toast:** `T/SearchBox.test.tsx` "Esc clears a non-empty query and keeps focus; it bubbles only once the query is empty"; `T/FormSection.test.tsx` "collapsible: a disclosure button inside the heading toggles the body, and focus stays"; `T/InfoPanel.test.tsx` "J18: activating the trigger opens a non-modal drawer, focus on its heading"; `T/Toast.test.tsx` "Esc on a focused toast dismisses it and moves focus to the next, then back to the field".

## CMP-044 ConfirmDialog gate matrix (for E05-X02)

This section stands on its own so the E05-X02 security review can lift it. CMP-044 gates flatten, cancel-all, reverse and freeze (US-SET-003); the ticket's threat is a gate satisfied programmatically or by a stray Enter.

- **Gates:** standard (`variant="standard"`, a press past the 400 ms guard); typed (`variant="typed"`, the exact token, then a press); hold (`variant="hold"`, a pointer hold for `holdDurationMs`, default 800, or the keyboard paths); auto-cancel (`autoCancelMs`, the inactivity time-out on an order confirm, which cancels and never confirms).
- **States:** enabled (Confirm available); gated (`confirmDisabledReason`, T2); pending (`summaryLoading` before a send, `busy` after it); error (`failure`, a partial failure with Retry).
- **Each cell** of `T/ConfirmDialogGateMatrix.test.tsx` (describe "ConfirmDialog gate matrix (CMP-044, E05-X02)", one describe per gate) mounts the dialog in that state, waits out the 400 ms guard, runs the gate's whole gesture and checks what fired. Enabled and error must confirm exactly once, with the gate in `onConfirm`'s metadata; gated and pending must fire nothing.

| Gate        | Enabled                  | Gated                                          | Pending                                                                                               | Error              |
| ----------- | ------------------------ | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------ |
| standard    | M "enabled" · A1, A2     | M "gated" · A5, A6                             | M "pending (summary loading)", M "pending (busy send)" · A7                                           | M "error" · A8, A9 |
| typed       | M "enabled" · A3         | M "gated"                                      | M "pending (summary loading)", M "pending (busy send)" · A10, A11                                     | M "error"          |
| hold        | M "enabled" · H1, H2, H3 | M "gated" · H5                                 | M "pending (summary loading)", M "pending (busy send)"                                                | M "error"          |
| auto-cancel | M "enabled" · C1         | M "gated" (its expiry cancels, never confirms) | M "pending (summary loading)", M "pending (busy send)" (the count never cancels a busy send) · C2, C3 | M "error" · C4     |

`M "<state>"` is the matrix test of that name under the row's gate, for example "ConfirmDialog gate matrix (CMP-044, E05-X02) > hold > gated: Confirm stays focusable with its reason, and the full gesture fires nothing". Its full names:

- "enabled: the full gesture confirms once, with the gate in the metadata"
- "gated: Confirm stays focusable with its reason, and the full gesture fires nothing"
- "pending (summary loading): Confirm is natively disabled and the full gesture fires nothing"
- "pending (busy send): the card and Confirm are busy and the full gesture fires nothing"
- "error: the partial failure shows with Retry, and one more confirm is allowed"

The deeper tests, in `T/ConfirmDialog.test.tsx` (A), `T/ConfirmDialogHold.test.tsx` (H) and the auto-cancel describes of `T/ConfirmDialogHold.test.tsx` (C):

| Ref | Test                                                                                                      |
| --- | --------------------------------------------------------------------------------------------------------- |
| A1  | "the 400 ms guard: a stray click or a single Enter inside it does nothing"                                |
| A2  | "single fire: two clicks or two Enters past the guard, with no busy from the host, confirm once"          |
| A3  | "Gherkin 'Typed confirm': with FLATTEN required, other text keeps Confirm disabled with the instruction"  |
| A4  | "held-Enter repeats are ignored: one press, one confirm; Cancel ignores repeats too"                      |
| A5  | "H30: a Confirm gated mid-dialog keeps focus, speaks once assertively, then re-shows its reason politely" |
| A6  | "gated while focus is elsewhere: no assertive announcement; a reason that clears restores Confirm"        |
| A7  | "the guard rearms when Confirm becomes available or the intent changes while open"                        |
| A8  | "partial failure: CMP-027's inline error with Retry above the footer"                                     |
| A9  | "single fire: a new failure, or busy ending, allows one more confirm"                                     |
| A10 | "the summary still loading keeps Confirm natively disabled (availability, not T2)"                        |
| A11 | "busy: aria-busy on the card, Confirm loading and inert to presses, the field read-only"                  |
| H1  | "a pointer hold fires at the duration, never before, once"                                                |
| H2  | "keyboard: holding Enter (repeats included) for the duration fires key-hold"                              |
| H3  | "keyboard: a second non-repeat Enter 250 ms – 5 s later fires double-press"                               |
| H4  | "a synthetic click(), a pointerdown/pointerup pair and two clicks never confirm nor arm"                  |
| H5  | "a hold Confirm gated mid-hold drops the hold and fires nothing"                                          |
| C1  | "speaks politely at 0:10 and 0:00 only, and cancels at 0:00, never confirming"                            |
| C2  | "stops once Confirm has fired: a busy send is never cancelled by the count"                               |
| C3  | "a busy that ends without a send restarts the count from the full time"                                   |
| C4  | "a send that fails after the count would have run out is never cancelled by it"                           |

Across every gate: A4 (key repeats) and H4 (no synthetic or two-click path to a hold) are the automation cases; "a hold in progress at 0:00 is dropped: the expiry cancels, never confirms" covers hold with auto-cancel. The stories that show each state are in `S/ConfirmDialog.stories.tsx` (Standard, Guard, Typed, TypedMatch, Hold, HoldKeyboard, ConfirmGated, Busy, PartialFailure, CountingDown, TimedOut).

## Manual screen-reader log

`src/docs/screen-reader-spot-check-e05-s03.md`: Dialog, Combobox and Table, marked "not run". A human tester fills it in.

## Manual passes still owed (DoD)

- The manual screen-reader pass above.
- The Security engineer's review of the ConfirmDialog gates (E05-X02), from the matrix above.
- Keyboard-only walk of each molecule (the Molecules/Overview tables are the script).
- Design QA against the boards (E05-D05), the QA sign-off of E05-Q01 and the Sprint Review demo; none is claimed here.
