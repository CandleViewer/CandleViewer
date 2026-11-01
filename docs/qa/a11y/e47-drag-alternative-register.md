# Drag alternative register (E47-S05)

WCAG 2.2 SC 2.5.7 (Dragging Movements, AA), `docs/plan/05-accessibility-standard.md` §3.1 rule 6 and §3.4 rule 8:
every drag has a single-pointer or keyboard alternative that reaches the same state. No drag surface is built yet (at
this commit the only pointer-draggable thing is the native `Slider`, which is keyboard-native), so this is the register
of the surfaces that will be, each with its keyboard equivalent as the catalogue specifies it and the ticket that owns
both halves. Source rows: `docs/plan/14-screens-catalogue.md`, `docs/plan/15-component-catalogue.md`.

## How a drag-owning ticket closes its row

1. Build the keyboard path in the same PR as the drag (never later).
2. Add a test that calls `assertKeyboardAlternative` (`apps/web/test/support/assertKeyboardAlternative.ts`, unit test
   `apps/web/test/keyboard-alternative.test.tsx`). It checks that the target is keyboard reachable and named, that the
   drag changes the committed value, and that the listed keys reach the same value from the same start.
3. Set `Status` to `built` and name the test in `Test`. T05 (E47-T05) accepts or rejects a row left `planned` at release.

## Register

| Id    | Surface (screen / component)                                | Drag                              | Keyboard equivalent (as specified)                                         | Owner ticket      | Status  | Test |
| ----- | ----------------------------------------------------------- | --------------------------------- | -------------------------------------------------------------------------- | ----------------- | ------- | ---- |
| DR-01 | SCR-021 dock: CMP-080 DockPanel, CMP-082 PanelHeader handle | move a panel to a drop zone       | move mode from the panel menu (E15-D04 §5)                                 | E15-S02 / E15-S03 | planned |      |
| DR-02 | SCR-021: CMP-083 SplitPane divider                          | resize a split                    | arrows 2 %, `Shift`+arrows 10 %, `Home` / `End`; one "Minimum size." stop  | E15-S02 / E15-S03 | planned |      |
| DR-03 | SCR-011 workspace switcher                                  | reorder workspaces                | "Move up" / "Move down" per row                                            | E15-S02           | planned |      |
| DR-04 | SCR-033 Deep Stats rows configuration                       | reorder rows                      | `Alt+Up` / `Alt+Down` on the focused row                                   | E20-S02           | planned |      |
| DR-05 | CMP-056 ColumnPicker                                        | reorder columns                   | `Alt+Up` / `Alt+Down`; "Move column up / down" buttons inside a dialog     | E20-S02, E08-S08  | planned |      |
| DR-06 | SCR-037 drawing tools (chart)                               | move a drawing node               | select, arrows nudge by a tick, `Enter` commits, `Esc` cancels             | E14-S10           | planned |      |
| DR-07 | SCR-040 chart trading overlay: SL / TP lines                | drag-to-amend an order line       | select the line, arrows nudge by tick size, `Enter` commits (confirm path) | E31 (SCR-030/040) | planned |      |
| DR-08 | SCR-050 DOM ladder: CMP-108 DomLadderRow own-order marker   | drag an own order to a new price  | focus the order, arrows move by a tick, `Enter` commits                    | E21-S01           | planned |      |
| DR-09 | SCR-082 rule editor: CMP-146 NodeGraphCanvas, CMP-148 nodes | move a node; drag port to port    | DOM mirror per node and edge; handle focus, `Enter`, arrow-pick target     | E37               | planned |      |
| DR-10 | SCR-100 / SCR-101 watchlist: CMP-161 WatchlistRow           | reorder; drop a symbol on a panel | "Move up" / "Move down"; "Send to panel" menu                              | E08-S08           | planned |      |
| DR-11 | CMP-067 FileDrop (layout import)                            | drop a file                       | native `<input type=file>` (drag-and-drop is additive)                     | E15 (import)      | planned |      |
| DR-12 | CMP-104 LeverageSlider (extends CMP-010 Slider)             | drag the thumb                    | the slider's arrow, `PageUp`, `PageDown`, `Home`, `End` keys               | E30 (ticket)      | planned |      |
| DR-13 | SCR-097 replay timeline scrub (if a scrub bar is drawn)     | drag the playhead                 | `Left` / `Right` step a bar, `Shift` a tick, `Ctrl` jump a minute          | E44-S02 / E44-S03 | planned |      |
