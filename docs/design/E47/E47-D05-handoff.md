# E47-D05 — Hand-off (`16` §11.4; SCR-117 accessibility settings)

Components: **CMP-086 SettingsNav / SettingsLayout** (the own entry, one `h1`), **CMP-065 FormSection** (five sections, the view-as notice), **CMP-006 RadioGroup** (tri-states with the Effective line), **CMP-004 Toggle**, **CMP-069 InfoPanel** `inline`, **CMP-228 PreviewTile** (four PROPOSED kinds), **CMP-043 Dialog** (the reset preview), **CMP-079 RbacGate** with the **CMP-019 Icon** `lock` glyph (a T2 control, rendering 2a: spec §5.4's T2 paragraph; board 04). The spec is [E47-D05.md](E47-D05.md); every "§" below without a prefix is the spec's.

## §A Hand-off checklist (the five boxes of `14`:2482, then `16` §11.4)

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason.

| Item                                                                | Evidence                                                                       |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Box 1 — every option drawn with a plain-language effect description | [ ] text done (§4); boards 01, 02 pending                                      |
| Box 2 — OS detection shown as the default with an explicit override | [ ] text done (§5); board 04 pending                                           |
| Box 3 — streaming-announcement throttle control drawn               | [ ] text done (§7.1; D05-Q1); board 07 pending                                 |
| Box 4 — a link to the statement and to the keyboard cheatsheet      | [ ] text done (§9); board 01 pending; the statement route is D05-G5            |
| Box 5 — the page passes its own standard at 200 % zoom              | [ ] text done (§11, §12); board 03 pending; a browser run is E47-S08's (#1322) |
| Variants × states                                                   | [x] §10                                                                        |
| Keyboard table                                                      | [x] §12                                                                        |
| Live data                                                           | [x] §5.3 (one status), §7 (the tile is never a live region)                    |
| Motion pair                                                         | [x] §6.1 (loop / still frames, Pause)                                          |
| Data contract                                                       | [ ] NO: D05-G1, D05-G2, D05-G4, D05-G7                                         |
| Sign-off                                                            | [ ] owner approval pending (#2701)                                             |

## §B Who applies what

| A                      | Target                  | Applied by                                 |
| ---------------------- | ----------------------- | ------------------------------------------ |
| D05-A1 … D05-A4        | `15` CMP-228            | E47-D10 (#1309), the CMP-228 contribution  |
| D05-A5, D05-A8, D05-A9 | `14` SCR-117            | the `14` owner, at the owner's sign-off PR |
| D05-A6                 | `12` R-203              | the `12` owner, at the owner's sign-off PR |
| D05-A7                 | E09-D09 §3.1 (the keys) | E09-D09's owner, as a registered state key |

## §C Copy-ready rows (PROPOSED)

Old is a verbatim fragment of the cited line at `4c662fd5b` (the tool checks it); New replaces it, or follows it where the row says "insert after".

| A      | Target       | Field (`file`:line)    | Old                                                       | New                                                                                                                                                                                                                                                                                  |
| ------ | ------------ | ---------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| D05-A1 | `15` CMP-228 | Props (`15`:2938)      | `kind: "footprint"\|"heatmap"\|"candles"\|"theme"`        | insert after: · PROPOSED kinds `"motion"`, `"focus"`, `"announcements"`, `"table-alt"`, each a live instance on a seeded loop under the pending value (E47-D05 §6)                                                                                                                   |
| D05-A2 | `15` CMP-228 | A11y (`15`:2939)       | with a name describing the current configuration in words | insert after: ; for the PROPOSED kinds the tile is a `role="group"` with that name holding the `role="img"` preview node, its controls (Pause, Play sample) outside the img; the `announcements` kind is a real `ul` behind a "Play sample" button, never a live region (E47-D05 §6) |
| D05-A3 | `15` CMP-228 | Motion (`15`:2944)     | **Motion (E32-D06)**: none                                | insert after: (the `motion` kind loops only under full effective motion, with a visible Pause, and shows still Before / After frames under reduce; E47-D05 §6.1)                                                                                                                     |
| D05-A4 | `15` CMP-228 | Storybook (`15`:2941)  | LadderRefused (E32-D04 D04-A2)                            | insert after: , Motion, MotionReduced, Focus, Announcements, TableAlt (E47-D05 §6)                                                                                                                                                                                                   |
| D05-A5 | `14` SCR-117 | Stories (`14`:2478)    | **Stories:** US-SET-007, US-CHART-014.                    | insert after: a **States:** line naming the eleven states of E47-D05 §10, scope per user                                                                                                                                                                                             |
| D05-A6 | `12` R-203   | Purpose (`12`:95)      | Theme, density, colour convention override, a11y prefs    | Theme, density, colour convention override; a11y prefs on their own SettingsNav entry and sub-route (E47-D05 §2)                                                                                                                                                                     |
| D05-A7 | E09-D09 §3.1 | Keys (D09E09:95)       | `rbac.view_as`                                            | insert a row after: `a11y.forced_colors` · "Your system's high-contrast mode is on." · the OS reports `forced-colors: active` (E47-D05 §5.4)                                                                                                                                         |
| D05-A8 | `14` SCR-117 | Analytics (`14`:2481)  | `a11y.preference_changed` `{key, value}`                  | `a11y.preference_changed` `{key, value, source}` (enum-only; no free text, no identity; E47-D05 §13.1)                                                                                                                                                                               |
| D05-A9 | `14` SCR-117 | Components (`14`:2477) | CMP-228 PreviewTile.                                      | insert after: CMP-043 Dialog (reset preview), CMP-079 RbacGate with CMP-019 Icon `lock` (T2, E47-D05 §5.4).                                                                                                                                                                          |

## §D Storybook story lists (each story per theme, `15`:41)

| Component            | Stories                                                                                                                                  |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| SCR-117 screen story | Default · FollowingSystem · OsChangedWhileOpen · Modified · SectionResetPreview · SearchResults · ForcedColours · LoadError · SaveFailed |
| CMP-006 RadioGroup   | the merged list + TriStateWithEffectiveLine · DisabledWithReasonForcedColours                                                            |
| CMP-228 PreviewTile  | the merged list + Motion · MotionReduced · Focus · Announcements · TableAlt (D05-A4)                                                     |
| CMP-065 FormSection  | the merged list + ViewAsNotice                                                                                                           |

## §E Owner walkthrough checklist (each frame a 1280 × 800 window unless named)

- [ ] Board 01: every row has a visible label, a description that says what changes, and (tri-states) an Effective line with its source in words.
- [ ] Board 01: read each description aloud to someone outside design; note any word they cannot act on (T Test).
- [ ] Board 03: at 200 % in high contrast nothing is clipped and nothing scrolls sideways.
- [ ] Board 04: following-system says so; after the OS flip one status line is shown and an explicit choice stays.
- [ ] Board 04: the forced-colours contrast row keeps its label, shows the lock glyph and the reason, and stays in the Tab order.
- [ ] Board 05: the motion tile stands still under reduce and shows Before / After; Pause is visible while it loops.
- [ ] Board 07: at low verbosity the sample shows only the three significant events and no tick.
- [ ] Board 08: each reveal example shows fields in place of the drag; a stop move still asks to confirm.
- [ ] Board 10: walk the numbered Tab order with the keyboard on paper; log any skipped or unlabelled stop.
- [ ] Record `approved` on #1304, or the findings `(heuristic)` with board and frame names.

## §F The key list (published) and consumer pointers

The key list is spec §3, the single source; this section publishes it for acceptance by the engineering chunk lead (E47-S08 #1322) and E47-D07 (#1306). Acceptance pending.

| Consumer        | Builds from             | Waits on                |
| --------------- | ----------------------- | ----------------------- |
| E47-S08 (#1322) | spec §2–§13, §C         | D05-G1 … D05-G3, D05-G6 |
| E47-D07 (#1306) | spec §3, §7, W-15, W-19 | D05-Q1, D05-Q2          |
| E47-D08 (#1307) | spec §6.1               | —                       |
| E47-D09 (#1308) | spec §8                 | —                       |
| E47-D10 (#1309) | §C D05-A1 … D05-A4      | D05-G8                  |
| E47-D11 (#1310) | the whole pack          | the boards              |
| E47-Q01 (#1314) | §G                      | —                       |

## §G QA draft assertions (deterministic)

| QA   | Given / when                                                                                               | Then (assert)                                                                                                                                                 |
| ---- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| QA-1 | emulate `prefers-reduced-motion: reduce`; open SCR-117                                                     | the motion radio "Follow my system" is checked; the Effective line reads W-12; the motion tile has no running loop                                            |
| QA-2 | with the row following, flip the emulated media to `no-preference`; then set On and flip again             | the line updates without reload; the polite region received exactly one W-15; after On, the value stays On and W-16 is visible but never in the polite region |
| QA-3 | set verbosity low; press "Play sample" on the announcement tile                                            | the list shows exactly the fill, reject and reconnect lines; no element in the tile has `aria-live`                                                           |
| QA-4 | emulate `forced-colors: active`; Tab to the contrast group; press `Space`, then `↓`                        | every radio has `aria-disabled="true"`, its description holds W-26 then W-17, the value is unchanged after both keys, one polite announcement                 |
| QA-5 | run E47-D03's token linter over SCR-117 in dark, light and high contrast                                   | every text and non-text pair is a registered D03 pair and passes its matrix floor (spec §11)                                                                  |
| QA-6 | modify one option, press its Reset; modify a section, press Reset this section, then confirm               | focus lands on the option's control; after the dialog, on Reset this section or, if gone, the section's `h2`; W-28 spoken once                                |
| QA-7 | set full motion; focus the motion group; press Pause; move to another group and back                       | the tile is a `role="group"` whose Pause button now reads "Play"; the tile stays paused; no control sits inside its `role="img"`                              |
| QA-8 | at 320 CSS px and with the WCAG text-spacing overrides, flip the emulated OS reduce three times within 1 s | no horizontal scroll and nothing clipped; the status region holds one W-15 text, the latest                                                                   |

## §H The board plan (pending; drawn in a later push of this PR)

The boards of spec §0, on page `E47-D05 SCR-117` of the Penpot file `E47-D05 boards`; frames named `SCR-117/<state> · <theme>`. Data: a seeded synthetic stream (seed 1304), declared synthetic on every board's face.

| Board | Frames                                                                                                                            |
| ----- | --------------------------------------------------------------------------------------------------------------------------------- |
| 01    | `SCR-117/default · dark`                                                                                                          |
| 02    | `SCR-117/default · light`                                                                                                         |
| 03    | `SCR-117/default · hc` at 640 CSS px                                                                                              |
| 04    | `SCR-117/following-system · dark`, `SCR-117/os-changed-while-open · dark`, `SCR-117/forced-colours · dark`                        |
| 05    | `tile/motion-full · dark`, `tile/motion-reduced · dark`, `tile/table-alt · dark`                                                  |
| 06    | `tile/focus-normal · dark`, `tile/focus-thick · dark`, `tile/focus-always · dark`                                                 |
| 07    | `tile/announce-off · dark`, `tile/announce-significant · dark`, `tile/announce-always · dark`, `tile/low-verbosity-sample · dark` |
| 08    | `reveal/order-line · dark`, `reveal/drawing-point · dark`, `reveal/rule-edge · dark`                                              |
| 09    | `SCR-117/modified · dark`, `SCR-117/section-reset-preview · dark`, `SCR-117/search-results · dark`                                |
| 10    | `SCR-117/keyboard-order · dark` at 150 % text scale                                                                               |

## §I Summary for #1304

1. Text-first hi-fi of the shipped SCR-117 plus PROPOSED deltas, each a G-row to its code owner; 10<!--=COUNT:boards--> boards pending; default-deny audit tool.
2. A key list of 11<!--=COUNT:keys--> keys: the eight shipped verbatim, three PROPOSED; each runtime-switchable with its consumer.
3. Every option has its label and a plain-language effect description; tri-states show the effective value and its source in words.
4. An OS change updates in place with one polite status and never discards an explicit choice; forced colours make the contrast row T2.
5. Four PROPOSED preview kinds that obey the effective motion; the announcement sample is a list, never a live region.
6. The six significant classes are quoted from `05`; the cadence default is 2 s until E47-D01 reports.
7. BQ-0 … BQ-13 defaults built, ruling pending (comment 6566520929); D03 / D04 pinned at their PR heads and re-pinned at merge.
