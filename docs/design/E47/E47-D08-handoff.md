# E47-D08 — Hand-off (`16` §11.4; the motion layer)

Components: **CMP-161 WatchlistRow** and **CMP-036 KeyValueRow** (the value flash and its reduce holds), **CMP-112 BigTradeBubble** (no flash), **CMP-075 EnvBadgeLocal** and **CMP-074 EnvBanner**, **CMP-117 RiskLockoutBanner**, **CMP-229 ArmToggle** and **CMP-208 StatusBar** (static safety), plus the engine's SCR-030 / SCR-050 / SCR-054 rows; for T2 (spec §12) **CMP-079 RbacGate** with the **CMP-019** Icon `lock`. No component gains a motion of its own.

## §A Hand-off checklist (`16` §11.4)

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason.

| Item              | Value flash (CMP-161, CMP-036)      | Canvas data-rate (SCR-030, SCR-050, SCR-054) | Safety signals (CMP-074, -075, -117, -229, -208) | Pause controls (SCR-097, SCR-053, SCR-030) |
| ----------------- | ----------------------------------- | -------------------------------------------- | ------------------------------------------------ | ------------------------------------------ |
| Final Penpot link | [ ] boards 01, 04 pending (spec §0) | [ ] boards 02, 03, 05, 06 pending            | [ ] board 09 pending                             | [ ] board 07 pending                       |
| Variants × states | [x] spec §3 I-5, §5, §10            | [x] spec §3, §6, §7                          | [x] spec §11                                     | [x] spec §8                                |
| Keyboard table    | [x] n/a                             | [x] n/a                                      | [x] spec §12 (T2)                                | [x] spec §8                                |
| Live data         | [x] spec §4.2                       | [x] spec §4.2, §4.4                          | [x] none                                         | [x] W-4, W-6                               |
| Motion pair       | [x] E05-D03 row 3; spec §5          | [x] spec §3 (three tiers)                    | [x] none: static                                 | [x] none                                   |
| Flash budget      | [x] FR-1, FR-3                      | [x] FR-3, FR-5, FR-6                         | [x] never flashes                                | [x] n/a                                    |
| Forced colours    | [x] spec §10                        | [x] spec §10                                 | [x] spec §10                                     | [x] system colours                         |
| Tokens used       | [x] E05-D03's                       | [ ] NO: D08-A9 (liquidation)                 | [x] the owners'                                  | [x] the owners'                            |
| Data contract     | [x] none                            | [ ] NO: D08-G3, D08-G4                       | [x] none                                         | [ ] NO: D08-G7                             |
| Storybook         | [x] §D                              | [x] §D                                       | [x] §D                                           | [x] §D                                     |
| Sign-off          | [ ] owner approval pending          | [ ] owner approval pending                   | [ ] owner approval pending                       | [ ] owner approval pending                 |

## §B Who applies what

| A                      | Target                   | Applied by                                         |
| ---------------------- | ------------------------ | -------------------------------------------------- |
| D08-A1                 | `16` §7                  | the `16` owner, at the owner's sign-off PR         |
| D08-A2, D08-A3, D08-A5 | `05` §7, §11             | the `05` owner, at the owner's sign-off PR         |
| D08-A4                 | `05` §3.2                | the `05` owner, with E10-S02 (#305)                |
| D08-A6, D08-A7         | REG                      | E47-S04 (#1318), the register's owner              |
| D08-A8, D08-A9         | `16` §7.1; the token set | E47-D10 (#1309), the motion and token contribution |

## §C Copy-ready rows (PROPOSED)

Old is a verbatim fragment of the cited line at `85b6b6c1c` (D03 at `73fefc62b`; the tool checks it); New replaces it, or follows it where the row says "insert after".

| A      | Target        | Field (`file`:line)      | Old                                                                          | New                                                                                                                                                                                                         |
| ------ | ------------- | ------------------------ | ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D08-A1 | `16` §7       | budget (`16`:209)        | Unmet or excepted surfaces: `docs/qa/a11y/e47-motion-exception-register.md`. | insert after: The flash-rate budget holds in both motion modes: at most 2 starts per cell and 2 combined starts per sliding 341 × 256 px region in any half-open 1 000 ms window, every theme (E47-D08 §4). |
| D08-A2 | `05` §7       | item 3 (`05`:218)        | price-flash-on-tick.                                                         | insert after: The budget, its coalescing window and the region rule: E47-D08 §4; the budget applies in both motion modes.                                                                                   |
| D08-A3 | `05` §7       | item 4 (`05`:219)        | a shared `motion-safe`/`motion-reduce` variant pair                          | a shared safe / reduce pair, realised as the recipe custom-property pair resolved by `data-motion` (`16` §7; E47-D08 §13)                                                                                   |
| D08-A4 | `05` §3.2     | `Ctrl+Shift+M` (`05`:78) | Session override on top of OS-level `prefers-reduced-motion` (§6)            | Persisted override of OS-level `prefers-reduced-motion`, announced once (§7; E05-D03 §6.5; E47-D08 §9)                                                                                                      |
| D08-A5 | `05` §11      | item 4 (`05`:328)        | (§7.4)                                                                       | (§7 item 4)                                                                                                                                                                                                 |
| D08-A6 | REG           | MX-15 (REG:24)           | E47-D08 (#1307) as the design input                                          | insert row after MX-15: MX-16 · the region arbiter, combined starts per 341 × 256 px region (E47-D08 §4.3) · MR-1, HS-1b · pending · not built (E47-D08 D08-G3)                                             |
| D08-A7 | REG           | MX-15 (REG:24)           | E47-D08 (#1307) as the design input                                          | insert row after MX-16: MX-17 · reduce-mode holds: the direction glyph and the heatmap live column (E47-D08 §5, §7) · MR-1, HS-1 · pending · not built (E47-D08 D08-G4)                                     |
| D08-A8 | `16` §7.1     | hold group (`16`:225)    | `motion.hold.*` group for §2.6 and bound to no token here.                   | insert after: E47-D08 §4.1's FR-1 … FR-10 are named spec constants of the same kind, PROPOSED for that group.                                                                                               |
| D08-A9 | the token set | D03-G2 (D03:627)         | no token for the liquidation flash                                           | a PROPOSED name `color.liquidation.flash` for E47-D08 §6's opacity-only overlay; its value set by E47-D10 under E47-D03's rules                                                                             |

## §D Storybook story lists (each story per theme and density, `15`:41)

| Component             | Stories                                                                                |
| --------------------- | -------------------------------------------------------------------------------------- |
| CMP-161 WatchlistRow  | the merged list + FlashBurst40Hz · ReduceGlyphHeld · ForcedColorsGlyph · CanvasCalmDom |
| CMP-036 KeyValueRow   | the merged list + FlashBurst40Hz · ReduceGlyphHeld                                     |
| CMP-075 EnvBadgeLocal | the merged list + ReducedMotion · HighContrastReduced                                  |
| CMP-229 ArmToggle     | the merged list + ReducedMotion · ReadOnlyT2Hotkey                                     |

## §E Owner walkthrough checklist (each frame a 1280 × 800 window; compact density)

**§E.0 The owner session protocol** (BQ-13; T Test). Who: the owner, alone or with a reviewer they name; no participant is recruited or invented. Setup: the seeded TICKS stream, a 1280 × 800 window, compact density, dark then high contrast. Passes, each run with the OS reduced-motion setting on and then off: every §3 surface (spec §3), recorded as a video per surface; a screen-reader pass of W-1 … W-13 (each heard once); a keyboard-only pass of the four pause controls of spec §8; a 200 % zoom and 320 px pass (spec §15); a Windows forced-colours pass (spec §10). Record: the board and frame names, each finding marked `(heuristic)`, vestibular discomfort in the owner's own words; the videos go to E47-Q05 (#1357) and E47-Q01 (#1314).

- [ ] Board 01: every surface has a full, a canvas-calm and a reduced cell; none is blank.
- [ ] Board 02: the 40 Hz burst never puts a third start inside any 1 000 ms window on the region.
- [ ] Board 03: in light and dark, a liquidation, a ladder cell and a watchlist cell in one rectangle never exceed two starts a second.
- [ ] Board 04: under reduce no overlay paints; the glyph changes at most twice a second; under forced colours the glyph is in system text colour.
- [ ] Boards 05–06: a ten-event liquidation burst starts one overlay; the heatmap trail stops fading under reduce and canvas calm.
- [ ] Board 07: replay pauses with `Space`, the tape with `P`, follow-live with its toggle; no copy says the feed paused.
- [ ] Board 08: OS reduce plus the override off: full motion, one announcement naming the override, SCR-117's Effective line.
- [ ] Board 09–10: every safety signal reads by icon and word under reduce, in high contrast and in forced colours.
- [ ] Run §E.0: the OS setting on and off over every §3 surface with video per surface, the screen-reader, keyboard-only, 200 % zoom and forced-colours passes; note any vestibular discomfort `(heuristic)` (T Test).
- [ ] Record `approved` on #1307, or the findings `(heuristic)` with board and frame names.

## §F Consumer pointers

| Consumer                 | Builds from                                         | Waits on               |
| ------------------------ | --------------------------------------------------- | ---------------------- |
| E47-S04 (#1318), E08-S08 | spec §4, §5                                         | D08-G3, D08-G4         |
| E47-Q05 (#1357)          | spec §4.4, §14; §G                                  | D08-G5, D08-G6, D08-Q2 |
| E47-Q01 (#1314)          | §G                                                  | —                      |
| E47-D10 (#1309)          | spec §4.1, §13; D08-A8, D08-A9                      | —                      |
| E24-D04 (#662)           | spec §6                                             | D08-G2                 |
| E21-D05 (#505)           | spec §7, §8                                         | D08-G1, D08-G7         |
| E22-D04 (#577)           | spec §8, W-8, W-9                                   | D08-C11, D08-Q4        |
| E47-D07 (#1306)          | W-2 … W-4, W-8 … W-10; spec §15's announcement rule | —                      |
| E47-D11 (#1310)          | this pack                                           | the ruling             |

## §G QA draft assertions (deterministic; the specification for the §9 gate, `05`:261)

| QA   | Given / when                                                                                                                       | Then (assert)                                                                                                                                                                                                                                                                                                                                    |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| QA-1 | the TICKS `burst` preset drives a value cell, a liquidation mark and a heatmap cell inside one 341 × 256 px region; 60 Hz sampling | per element and over the region, the maximum flashes in any 1 s window is at most 2 (FR-3), under `safe` and `reduce`, every theme                                                                                                                                                                                                               |
| QA-2 | `data-motion="reduce"`; the same burst                                                                                             | no overlay frame paints; the glyph's direction changes at most once per 500 ms per cell; the digits update every tick                                                                                                                                                                                                                            |
| QA-3 | replay at 100× over a recorded window                                                                                              | the same wall-clock maxima as QA-1                                                                                                                                                                                                                                                                                                               |
| QA-4 | keyboard only: replay playing; tape scrolling; chart following live                                                                | `Space` pauses replay (W-6) and plays it (W-7), each announced once; `P` with focus in the tape pauses and resumes it (W-8, W-9), and `P` typed in a text input does nothing to the tape; the follow toggle turns follow off (W-4) and `End` resumes it (W-10); repeated presses inside 1 000 ms announce the last state once; focus never moves |
| QA-5 | `data-motion="reduce"`, then canvas calm; a burst                                                                                  | `document.getAnimations()` is empty under reduce; the engine's decay and flash passes do not run under either (R-5)                                                                                                                                                                                                                              |
| QA-6 | 200 % zoom, then a 320 CSS px wide window; then `forced-colors: active`                                                            | every W string, chip and T2 reason wraps, never clipped or ellipsised; every pause control's target is at least 24 × 24 CSS px; under forced colours the focus ring, the replay frame's `border` and the lock glyph render in system colours                                                                                                     |

## §H The board plan (drawn later in this PR; a Penpot pass)

The boards of spec §0 on page `E47-D08 — Motion`; frames named `<surface>/<tier> · <theme>`. Data: the seeded TICKS stream, declared synthetic on every board's face.

| Board | Frames                                                                              |
| ----- | ----------------------------------------------------------------------------------- |
| 01    | `inventory/full · dark`, `inventory/canvas-calm · dark`, `inventory/reduced · dark` |
| 02    | `budget/requests · dark`, `budget/admitted · dark`                                  |
| 03    | `region/arbiter · dark`, `region/arbiter · light`                                   |
| 04    | `value-flash/safe · dark`, `value-flash/reduce · dark`, `value-flash/forced · dark` |
| 05    | `liquidation/burst · dark`, `liquidation/reduce · dark`                             |
| 06    | `heatmap/full · dark`, `heatmap/canvas-calm · dark`, `heatmap/reduced · dark`       |
| 07    | `pause/replay · dark`, `pause/tape · dark`, `pause/follow-live · dark`              |
| 08    | `override/os-reduce-off · dark`                                                     |
| 09    | `safety/reduced · dark`, `safety/reduced · hc`                                      |
| 10    | `forced-reduce/matrix · dark`                                                       |

## §I Summary for #1307

1. Text-first motion layer + hand-off + default-deny audit tool; 10<!--=COUNT:boards--> boards pending, drawn later in this PR.
2. The flash-rate budget applies in both motion modes.
3. 41<!--=COUNT:inv.rows--> surfaces, each with its full, canvas-calm and reduced variant, checked against its owning spec row.
4. Per cell 500 ms; per region at most 2 combined starts a second in every theme; the 40 Hz simulation proves it with the arbiter.
5. Every auto-mover over 5 s has a keyboard pause; pausing follow-live never reads as a paused feed.
6. Safety signals are static by icon and word; the BQ defaults are built, the ruling pending.
