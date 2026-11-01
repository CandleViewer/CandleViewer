# Conformance lines for screens not yet built (E47-S05, BQ-2)

E47-S05 closes on the built screens plus the guards that every later screen plugs into: the dialog conformance
matrix (`apps/web/test/dialog-conformance.test.tsx`), the focus-ring guard (`packages/ui/test/focus-ring-guard.test.ts`),
the focus-not-obscured and target-size specs (`apps/web/e2e/a11y/`), the regions and Help specs, and
`assertKeyboardAlternative` (`docs/qa/a11y/e47-drag-alternative-register.md`). Each screen below is unbuilt, so its owning
ticket carries one line to make those guards reach it. A line is part of that ticket's Done; it is not an edit to the
ticket's text made here.

| Screen  | Name                               | Owning ticket | Conformance line                                                                                                                                                                                 |
| ------- | ---------------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| SCR-021 | Dock / panel system                | E15-S02       | Add its row to `screens.ts` and the dialog matrix; panels are named regions on `Ctrl+\`; every drag has its move-mode and split-resize keys (register DR-01, DR-02); targets at compact density. |
| SCR-027 | Floating panel window              | E15-S02       | Its own document has its own skip link, a named `main`, and the Help entry in the same TopBar slot; the window controls meet 24 px.                                                              |
| SCR-029 | Unsaved-changes / conflict dialog  | E15-S03       | A row in the dialog matrix: focus in, trap, Esc cancels, focus back to the opener; no choice depends on a pointer.                                                                               |
| SCR-064 | Position SL/TP editor              | E32-S07       | A matrix row; price fields take typed values and arrow nudges by tick, so a drag on the chart is never the only path (DR-07); Confirm path keyboard-reachable.                                   |
| SCR-072 | Kill-switch / freeze confirmation  | E39-S05       | A matrix row as an `alertdialog` with focus on Cancel; the hold gate has its two-press alternative; none of the three actions below 24 px.                                                       |
| SCR-074 | Environment switcher (Demo / Live) | E44-S02       | A matrix row; switching to Live needs a typed confirm that is paste-friendly (3.3.8) and keeps focus in the dialog through step-up and back.                                                     |
| SCR-076 | Order confirmation modal           | E44-S03       | A matrix row as a `dialog` with focus on Cancel; Confirm ignores the first `confirmDelayMs`; the environment sentence is text, never colour alone.                                               |
| SCR-085 | Rule arming dialog                 | E35-S08       | A matrix row; the arm switch is a deliberate control, not a silent toggle; focus returns to the rule's arm control.                                                                              |
| SCR-129 | Admin: account disable / delete    | E27-S04       | A matrix row with the typed confirm, consequences stated before the field; Esc is Cancel and never confirms.                                                                                     |
| SCR-149 | Admin re-authentication gate       | E42-S01       | A matrix row; credential fields allow paste and password managers (3.3.8); focus lands on the first field and returns to the admin entry point on cancel.                                        |

Every one of these screens also lands inside the shell, so it inherits the five named regions and the Help entry
(`apps/web/e2e/a11y/regions.spec.ts`, `help-entry.spec.ts`) without a further line.
