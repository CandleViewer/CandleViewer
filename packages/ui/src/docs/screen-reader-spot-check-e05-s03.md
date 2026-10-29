# E05-S03 screen-reader spot-check: Dialog, Combobox, Table

**Status: not run.** This is the manual screen-reader pass the E05-S03 Definition of Done asks for ("manual
screen-reader pass on Dialog, Combobox and Table"). A human tester fills in the blank columns; nothing in this
file has been checked yet.

- **Protocol and pinned combos:** `docs/plan/05-accessibility-standard.md` §8 (§8.1 table, §8.2 setup). The
  sprint spot-check runs on the Chromium + NVDA combo; add an Electron + NVDA column if you run that too.
- **Setup:** Storybook (`pnpm --filter @candleviewer/ui storybook`), dark theme, compact density, default
  verbosity, keyboard only.
- **Result values:** Pass, Fail (open a defect and link it), or N/A (with a reason).

| Tester | Date (UTC) | Screen reader + version | Browser / shell + version | OS  |
| ------ | ---------- | ----------------------- | ------------------------- | --- |
|        |            |                         |                           |     |

## CMP-043 Dialog (`Molecules/Dialog`)

| #   | Story          | Steps                                                                          | Expected                                                                                         | Result | Notes / defect |
| --- | -------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ | ------ | -------------- |
| D1  | Default        | Tab to the opener and press Enter                                              | A dialog named by its title, then its description; focus on the first field, read with its label |        |                |
| D2  | Default        | Tab and Shift+Tab past both ends of the dialog                                 | Focus stays inside; the reader never reaches the page behind                                     |        |                |
| D3  | Default        | Try to browse out of the dialog with the virtual cursor                        | The page behind is not read (inert); only the dialog's content is                                |        |                |
| D4  | Default        | Press Esc                                                                      | The dialog closes; focus returns to the opener, which is read again                              |        |                |
| D5  | AlertDialog    | Open it                                                                        | Announced as an alert dialog with its title and message; focus on the least destructive choice   |        |                |
| D6  | Scrolling      | Tab and browse through the scrolling body                                      | The body reads in order between the header and footer; nothing is skipped                        |        |                |
| D7  | Busy           | Open it and Tab through it                                                     | The primary button reads busy and the fields read-only; Esc still closes the dialog              |        |                |
| D8  | EscTopmost     | Show the tooltip and the popover inside the dialog, then press Esc three times | Each Esc closes only the topmost layer: the tooltip, then the popover, then the dialog           |        |                |
| D9  | StackedDiscard | Edit the form, press Esc, then press Esc on the prompt                         | The discard prompt is announced as an alert dialog; Esc returns to the form, focus where it was  |        |                |
| D10 | ExemptRegion   | Open the dialog, then browse with the virtual cursor                           | The exempt region (shell status) is still read; the rest of the page is not                      |        |                |

## CMP-048 Combobox (`Molecules/Combobox`)

| #   | Story              | Steps                                    | Expected                                                                                                    | Result | Notes / defect |
| --- | ------------------ | ---------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------ | -------------- |
| C1  | Sync               | Tab to the field                         | "Symbol", combobox (or edit with autocomplete), collapsed                                                   |        |                |
| C2  | Sync               | Type "eth", then wait                    | One polite count once typing settles (about half a second), never one per keystroke; the list expands       |        |                |
| C3  | Sync               | Press ↓, then ↑ on the first option      | Each active option is read with its position; ↑ on the first returns to the text, read as the field's value |        |                |
| C4  | Sync               | Press ↓ to an option, then Enter         | The value is read as the chosen label; the list collapses                                                   |        |                |
| C5  | Sync               | Open the list, press Esc, then Esc again | The first Esc collapses the list and keeps the text; the second leaves the field to the host                |        |                |
| C6  | Sync               | Type, then Tab away without choosing     | Nothing is chosen; focus moves on                                                                           |        |                |
| C7  | AsyncLoading       | Type "BTC"                               | "Searching…" is shown but not announced; no option is read while the list is busy                           |        |                |
| C8  | NoResults          | Type a query with no match               | The host's sentence is read once; it is not an option                                                       |        |                |
| C9  | SearchFailed       | Type a query                             | The host's failure sentence is read once; it is not an option                                               |        |                |
| C10 | DisabledWithReason | Tab to the field and press a key         | Name, the lock ("Not available"), read-only, then the reason once; keys change nothing                      |        |                |

## CMP-049 Table (`Molecules/Table`)

| #   | Story      | Steps                                                       | Expected                                                                                                   | Result | Notes / defect |
| --- | ---------- | ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ------ | -------------- |
| B1  | Default    | Move into the table with the table navigation keys          | "Open positions", table, with its row and column counts; each cell read with its column header             |        |                |
| B2  | Default    | Read a numeric cell                                         | The full number with its sign where it has one (PnL), not a clipped or abbreviated form                    |        |                |
| B3  | Sortable   | Tab to a sort button and press Enter, then Enter again      | The header's sort state is read (ascending, then descending); the result is said once, politely            |        |                |
| B4  | Default    | Tab through the table                                       | Only the sort buttons take focus; the body adds no Tab stop                                                |        |                |
| B5  | Loading    | Browse the table                                            | The loading words are read once; the skeleton rows are not read                                            |        |                |
| B6  | Empty      | Browse the table                                            | The empty state's heading and text are read inside the table                                               |        |                |
| B7  | Error      | Open the story                                              | The error message is said once, politely; Retry is reachable and named                                     |        |                |
| B8  | Reflow     | Set the browser zoom to 200 %, then browse the stacked rows | Still a table: each block reads as a row, each value with its column header, nothing missing or read twice |        |                |
| B9  | Grid       | Tab into the grid, then use the arrows, Home and End        | One Tab stop; each move reads the cell and its header; the focused cell is never hidden under the header   |        |                |
| B10 | Selectable | Press Space on a row, then on select-all                    | The row reads selected; "2 selected" (or the count) is said once; select-all reads mixed, then checked     |        |                |
| B11 | RowActions | Press Shift+F10 on a row, then Esc                          | The row's menu opens, named "Actions for {first cell}"; Esc returns focus to the cell, read again          |        |                |

## Sign-off

| Role                   | Name | Date (UTC) | Outcome |
| ---------------------- | ---- | ---------- | ------- |
| Tester                 |      |            |         |
| Accessibility sign-off |      |            |         |
