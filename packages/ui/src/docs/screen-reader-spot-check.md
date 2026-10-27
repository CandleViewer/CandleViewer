# E05-S02 screen-reader spot-check: Tooltip, Popover, MaskedValue

**Status: not run.** This is the manual checklist the E05-S02 Definition of Done asks for. A human tester fills
in the blank columns; nothing in this file has been checked yet.

- **Protocol and pinned combos:** `docs/plan/05-accessibility-standard.md` §8 (§8.1 table, §8.2 setup). The
  sprint spot-check runs on the Chromium + NVDA combo; add an Electron + NVDA column if you run that too.
- **Setup:** Storybook (`pnpm --filter @candleviewer/ui storybook`), dark theme, compact density, default
  verbosity, keyboard only.
- **Result values:** Pass, Fail (open a defect and link it), or N/A (with a reason).

| Tester | Date (UTC) | Screen reader + version | Browser / shell + version | OS  |
| ------ | ---------- | ----------------------- | ------------------------- | --- |
|        |            |                         |                           |     |

## CMP-016 Tooltip (`Atoms/Tooltip`)

| #   | Story             | Steps                                           | Expected                                                             | Result | Notes / defect |
| --- | ----------------- | ----------------------------------------------- | -------------------------------------------------------------------- | ------ | -------------- |
| T1  | KeyboardTriggered | Tab to the trigger                              | Name, role, then the tooltip text as its description, read once      |        |                |
| T2  | EscDismiss        | Press Esc while the tooltip shows               | Tooltip hides; focus stays on the trigger; nothing else is announced |        |                |
| T3  | EscDismiss        | Press Esc a second time                         | The host gets the key (the tooltip no longer takes it)               |        |                |
| T4  | EchoName          | Tab to the icon trigger                         | "Settings, button" only; the echoed text is not read a second time   |        |                |
| T5  | EchoReason        | Tab to the gated trigger                        | Name, then the reason once (from the reason node), never twice       |        |                |
| T6  | Default           | Browse with the virtual cursor past the trigger | The hidden tooltip node is not read as page content                  |        |                |

## CMP-017 Popover (`Atoms/Popover`)

| #   | Story      | Steps                                        | Expected                                                                                  | Result | Notes / defect |
| --- | ---------- | -------------------------------------------- | ----------------------------------------------------------------------------------------- | ------ | -------------- |
| P1  | Default    | Tab to the trigger                           | Name, button, collapsed, and that it opens a dialog                                       |        |                |
| P2  | Default    | Press Enter                                  | Dialog is announced with its heading as its name; focus lands inside                      |        |                |
| P3  | NonModal   | Tab past the last control                    | Popover closes; focus moves on from the trigger; trigger reads collapsed when revisited   |        |                |
| P4  | NonModal   | Shift+Tab from the first control             | Focus returns to the trigger                                                              |        |                |
| P5  | Modal      | Open, then Tab and Shift+Tab around the ends | Focus stays inside; the reader reports a modal dialog and does not browse the page behind |        |                |
| P6  | EscDismiss | Press Esc inside                             | Popover closes; focus returns to the trigger; trigger reads collapsed                     |        |                |

## CMP-034 MaskedValue (`Atoms/MaskedValue`)

| #   | Story              | Steps                                                        | Expected                                                                                           | Result | Notes / defect |
| --- | ------------------ | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- | ------ | -------------- |
| M1  | Masked             | Browse the group with the virtual cursor                     | The group's label, then "{label}, hidden"; the mask dots and the value are never read              |        |                |
| M2  | Masked             | Tab to the toggle, press it, then press it again             | The name changes between "Show {label}" and "Hide {label}"; no pressed state is announced          |        |                |
| M3  | Revealed           | Activate the toggle, then browse to the value                | The value is read only when navigated to; it is not announced on reveal                            |        |                |
| M4  | Expiring           | Wait for the last 2 s of the reveal                          | One polite "{label} will hide in 2 seconds"; no per-second countdown                               |        |                |
| M5  | Expiring           | Wait for the timeout with focus on the toggle                | The value is masked again silently; focus stays on the toggle; browsing no longer reads it         |        |                |
| M6  | CopiedState        | Reveal, Tab to Copy, wait for the timed re-mask              | Focus moves from Copy to the toggle ("Show {label}"), never to the page body                       |        |                |
| M7  | CopiedState        | Activate copy while revealed                                 | "Copied" once, politely; the value is never spoken                                                 |        |                |
| M8  | Copyable           | Tab through the group while masked                           | Copy is disabled and skipped by Tab; the value is never spoken                                     |        |                |
| M9  | OneRevealedPerPage | Reveal the first value, then press the second value's toggle | The second value reveals and the first is masked in the same step; only one value is ever readable |        |                |

## Sign-off

| Role                   | Name | Date (UTC) | Outcome |
| ---------------------- | ---- | ---------- | ------- |
| Tester                 |      |            |         |
| Accessibility sign-off |      |            |         |
