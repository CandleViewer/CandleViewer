# E05-D04 — Accessibility and CVD design review of the v0 component set

**Ticket:** E05-D04 (#259) · binding references `docs/plan/05-accessibility-standard.md` §3 (keyboard, target size), §4
(colour independence), §5 (contrast), §7 (reduced motion), §10 (acceptance template), §11 (design-system requirements)
and `docs/plan/16-design-system-brief.md` §12–§13. It supersedes the five E05-D02 pre-reviews
(`E05-D02-a11y-audit.md`, `-data-display-`, `-form-controls-`, `-feedback-overlays-`, `-rest-a11y-audit.md`), which
named this review as the formal one for CVD and sign-off; their keyboard, name and role tables are cited here, not
redone.
**Status:** findings and a sign-off draft. No finding is serious. The sign-off comments (§8) are drafted for the
coordinator and are not posted by this document.

## 0. Honest scope

- **Agent-run, not a human pass.** Every row below was produced by an agent from the built library and the repo's
  tools. No designer, accessibility specialist or assistive-technology user took part.
- **Audited code:** `main` at `d721407c71d7ddda11d2ec781d9ce8010746c94e`, plus the E05-S04 slice H tip
  `9a789439e14bd0503a4e4c0c430b3bc60ccfdaec` for the three components not on `main` yet (ThemeSwitcher,
  DensityToggle, PreviewTile). The slice H state was read, not changed; re-check both at READY.
- **Environment:** the slice H static Storybook build (served on loopback), headless Chromium from Playwright 1.64.1,
  theme dark for the geometry probes (sizes do not vary by theme), both densities, motion `reduce`.
- **Screen reader:** not run. The name, role and value contract is the E05-D02 tables plus the component tests; the
  manual pass is E05-Q02 (#262).
- **Not run here:** 200 % zoom and 400 % reflow live, Windows forced colours, a Penpot side-by-side (the spec side is
  the E05-D02 documents and `15-component-catalogue.md`, a text read; no canvas compare), axe (E05-T03's gate;
  Q01 recorded 726 stories passing at dark, compact only), the Lighthouse score, any visual-fidelity judgement.
- **Imported, not redone:** keyboard paths, roles and names (E05-D02), the pair registry (E05-T05).

**Method.** _V0 set:_ pinned from the ticket lists of E05-S01 (#264: CMP-001..010), E05-S02 (#265: CMP-011..039),
E05-S03 (#266: CMP-040..050, 054, 059, 065, 069) and E05-S04 (#267: CMP-062, 063, 079, 085, 089..091, 228). Together
S01..S03 deliver every id of CMP-001..050, so the ticket's "CMP-001..050 subset" is the whole range: 62 components in
all. Names come from the `### CMP-` headings of the
catalogue. _Contrast:_ `pnpm --filter @candleviewer/ui contrast:gate`, exemptions read from
`tools/contrast/exemptions.json`, and the gate's own rows re-evaluated for stale exemptions. _CVD:_ the E05-D07 method
(Brettel/Vienot protan and deutan, Machado tritan, CIE76 dE, JND floor 5.0) imported from
`docs/research/_tools/cvd_simulate.py`, run over the real layered token files by `docs/design/_tools/cvd_v0_report.py`
into `docs/research/artifacts/E05-D04/cvd_simulation_v0.md`. _Targets:_ a Playwright probe over the first four stories
of each component, 1,560 interactive elements at two densities, reading `getBoundingClientRect` and, for each
undersized element, its wrapper chain and a pointer hit test. Numbers are rounded half up as printed by the tools.

## 1. Summary

| Check                     | Requirement              | Result                                                                                                                                                                                                                  |
| ------------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Template per band (§2)    | `05` §10; ticket AC 1    | **Pass, with scope limits**: six bands, six scenarios each, no blank field; the screen-reader row reads "proxy only; E05-Q02".                                                                                          |
| CVD, 3 themes (§3)        | `05` §4.2; ticket AC 2   | **Pass**: 0 flags in 3 themes x 3 deficiencies; narrowest margin 0.8 dE above the 5.0 floor (high-contrast buy/sell, deuteranopia).                                                                                     |
| Essential exceptions (§4) | `05` §3.4.7; ticket AC 3 | **Pass**: no shipped v0 control is below 24 x 24 px without a measured 24 px well, hit area, spacing or inline basis; none needs an essential exception.                                                                |
| Contrast report (§5)      | E05-T05; ticket scope    | **Pass with findings**: gate 0 findings (378 pair, 33 heatmap, 81 CVD checks); 45 exemptions all carry a reason and an owner, but 18 of their checks now pass (F-02) and 3 reasons cite no ticket for real debt (F-03). |
| Colour never alone (§6)   | `05` §4                  | **Pass** at the cited components; `no-hue-alone` gate ok; the encodings inventory lists a non-colour channel for every buy/sell, bid/ask and status surface.                                                            |
| Reduced motion (§6)       | `05` §7                  | **Pass**: one runtime rule neutralises every transition and animation under `data-motion="reduce"` and the OS preference; the VR matrix and Q01 ran it.                                                                 |
| Findings (§7)             | ticket AC 4              | **0 serious, 3 moderate, 5 minor or observation.** One moderate (F-01) waits on the coordinator's BQ-4 ruling.                                                                                                          |
| Rules amended             | ticket DoD               | None. `05` and `16` are unchanged.                                                                                                                                                                                      |

## 2. Acceptance-criteria template per component band

The template is `05` §10: Keyboard-only operation, Screen-reader operation, Colour-independence, Contrast, Reduced
motion, Automated gates, plus the screen readers spot-tested and any owner-approved exception. Counts: stories are the
`*.stories.tsx` files; tests are `it(` and `test(` cases in the component's test files under `packages/ui/test`
(Divider and Skeleton counted once; Icon from `test/icons`); VR is the number of baseline PNGs under
`packages/ui/vr/baselines` (`<group>-<component>...--<theme>--<density>.png`; the cells are 3 themes x 2 densities).
The VR gate and axe were not re-run (E05-T04, E05-T03).

| Band                                               | Components | Stories    | Tests | VR baselines (per cell) |
| -------------------------------------------------- | ---------- | ---------- | ----- | ----------------------- |
| A Controls: CMP-001..010                           | 10         | 10         | 258   | 894 (149)               |
| B Display, feedback, utility: CMP-011..039         | 29         | 28 + Icons | 415   | 1,608 (268)             |
| C Form and overlay molecules: CMP-040..050         | 11         | 11         | 390   | 954 (159)               |
| D Search and structure: CMP-054, 059, 065, 069     | 4          | 4          | 75    | 198 (33)                |
| E Theming and preview: CMP-062, 063, 228           | 3          | 3          | 45    | 240 (40), slice H only  |
| F Gate and app states: CMP-079, 085, 089, 090, 091 | 5          | 5          | 59    | 168 (28)                |

Scenarios common to every band: **Screen-reader operation** is "proxy only" (roles and names asserted in the tests by
role and label, specified in the E05-D02 tables; NVDA, JAWS and VoiceOver not run; owner E05-Q02 #262; deferral
stated per `05` §10). **Automated gates** is E05-T03's axe run per story and E05-T04's VR matrix, cited not re-run.
**Reduced motion** is the one runtime rule in `packages/ui/src/theme/theme.css` (`:root[data-motion="reduce"] *`
sets `transition` and `animation` to none, `--cv-motion-scale: 0` also under the OS preference); the 12
component stylesheets that declare a transition or animation each also carry their own guard.

### Band A: controls (CMP-001..010)

| Scenario            | Evidence                                                                                                                                                                                                                                                                       | Result                         |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------ |
| Keyboard-only       | `E05-D02-a11y-audit.md` §2 (Button, Toggle, Checkbox, RadioGroup, Slider, SegmentedControl) and `E05-D02-form-controls-a11y-audit.md` §2 (TextInput, NumericStepper, Select); the band's tests reference keys 231 times (Tab, Enter, arrows, Escape: a proxy count, not cases) | Pass                           |
| Screen-reader       | proxy only (above); `aria-invalid` + `aria-describedby`, `spinbutton` with `aria-valuetext`, select-only `combobox` per D02                                                                                                                                                    | Pass at design stage; Q02 owed |
| Colour-independence | invalid field: 2 px boundary, glyph, words; bound of a stepper: a disabled button; buy/sell Button: label and arrow in `text.inverse`; CVD §3                                                                                                                                  | Pass                           |
| Contrast            | gate 0 findings; label-on-fill matrix `tools/contrast/label-on-fill.json`; ring 4.72:1 or more (D02 §1); live exemptions on secondary fill and border (F-03)                                                                                                                   | Pass with F-03                 |
| Reduced motion      | global rule; Toggle, Select carry their own guard                                                                                                                                                                                                                              | Pass                           |
| Automated gates     | axe per story (Q01: 726 pass, dark compact); 894 VR baselines                                                                                                                                                                                                                  | Cited                          |
| Exceptions          | none needed: wells 24 / 32 px, Slider rail 240 x 24 / 32, Checkbox label area 72 x 24 / 76 x 32 (§4)                                                                                                                                                                           | Pass                           |

### Band B: display, feedback and utility atoms (CMP-011..039)

| Scenario            | Evidence                                                                                                                                                                                             | Result                                  |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| Keyboard-only       | `E05-D02-data-display-a11y-audit.md` §2, `E05-D02-feedback-overlays-a11y-audit.md` §2 (Tooltip, Popover, CopyButton, MaskedValue, Link, Callout actions); 415 tests (Popover 38 with key references) | Pass                                    |
| Screen-reader       | proxy only; MaskedValue never puts the value in its live region (D02 form-controls §2); status regions polite                                                                                        | Pass at design stage; Q02 owed          |
| Colour-independence | D02 slice 4 §1: every tone (toast, callout, error, progress) carries a glyph and a word; Badge, Tag, ConfidenceDots, Sparkline and ColorSwatch per slice 2 §1 (Pass); CVD for the colour pairs in §3 | Pass                                    |
| Contrast            | gate 0 findings; D02 slice 2 listed 14 `colorBySign` text pairs below 4.5:1 at design stage, not individually re-mapped to registry rows here                                                        | Pass on the registry; D02 opens carried |
| Reduced motion      | Spinner, Skeleton, Tooltip, Popover carry their own guard; the global rule covers the rest                                                                                                           | Pass                                    |
| Automated gates     | axe per story; 1,608 VR baselines (Icon: 18, the glyph sheet)                                                                                                                                        | Cited                                   |
| Exceptions          | none: standalone links 17 to 18.3 px tall rest on the 24 px spacing exception, the inline Link on the inline exception (§4); every button 24 / 32 px                                                 | Pass                                    |

### Band C: form and overlay molecules (CMP-040..050)

| Scenario            | Evidence                                                                                                                                                                                                              | Result                         |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| Keyboard-only       | D02 form-controls §2 (FormField, DatePicker, Combobox, Table) and feedback-overlays §2 (Menu, Dialog, ConfirmDialog, Toast, Drawer); 390 tests, the heaviest keyboard suites (Menu 62 cases, Table 72, DatePicker 62) | Pass                           |
| Screen-reader       | proxy only; Combobox (`aria-activedescendant`), DatePicker grid, Table `aria-sort` and `aria-rowindex` specified in D02                                                                                               | Pass at design stage; Q02 owed |
| Colour-independence | invalid: 2 px boundary, glyph, words; selection: a check, a checked box or an outline; unavailable: its reason; toasts carry a glyph and a word                                                                       | Pass                           |
| Contrast            | gate 0 findings; D02 form-controls: invalid boundary on `surface.hover` / `surface.selected` and a checked box on `selected` fall below 3:1 in dark, handled by rules (G2, G3)                                        | Pass with D02 rules            |
| Reduced motion      | popups fade over `motion.duration.fast` and appear at once under reduce; Dialog, Drawer, Toast, Menu, Combobox carry their own guard                                                                                  | Pass                           |
| Automated gates     | axe per story; 954 VR baselines                                                                                                                                                                                       | Cited                          |
| Exceptions          | none: wells 24 / 32 px; Menu rows 24 / 32 px; Table header buttons 24 px (§4)                                                                                                                                         | Pass                           |

### Band D: search and structure (CMP-054, 059, 065, 069)

| Scenario            | Evidence                                                                                                                                                       | Result                         |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| Keyboard-only       | D02 form-controls §2 (SearchBox: Esc clears, then bubbles; FormSection Disclosure) and rest §2 (CommandPalette, InfoPanel); 75 tests                           | Pass                           |
| Screen-reader       | proxy only; `searchbox` named by its label, count announced once per settled query by the host                                                                 | Pass at design stage; Q02 owed |
| Colour-independence | a destructive command its glyph and "confirms" (D02 rest §1)                                                                                                   | Pass                           |
| Contrast            | gate 0 findings                                                                                                                                                | Pass                           |
| Reduced motion      | global rule; no per-component guard needed (none of the four declares its own motion)                                                                          | Pass                           |
| Automated gates     | axe per story; 198 VR baselines                                                                                                                                | Cited                          |
| Exceptions          | none: palette option rows hit-test at 32 / 40 px around an 18.2 px text span; the standalone InfoPanel link is 18.2 px with 52.8 px or more to the next target | Pass                           |

### Band E: theming and preview (CMP-062, 063, 228)

| Scenario            | Evidence                                                                                                                                                        | Result                         |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| Keyboard-only       | D02 rest §2: ThemeSwitcher and DensityToggle expose radio items (role `radio`, as probed); 45 tests; the match-system switch is a 40 x 24 button                | Pass                           |
| Screen-reader       | proxy only; the PreviewTile warning is text plus the `warning` glyph, in a note                                                                                 | Pass at design stage; Q02 owed |
| Colour-independence | PreviewTile warning: the `warning` glyph and words (BQ-18), never colour alone; the warning and danger inks are only 14.7 dE apart in dark (11.2 under CVD), §3 | Pass                           |
| Contrast            | PreviewTile measures its own pairs at runtime and arms the warning (BQ-18); the registry gate 0 findings                                                        | Pass                           |
| Reduced motion      | a theme swap is one frame (`data-theme-swap` cuts transitions); no component motion                                                                             | Pass                           |
| Automated gates     | axe per story; 240 VR baselines exist only in the slice H chain (ThemeSwitcher 66, DensityToggle 72, PreviewTile 102), none on `main` yet (F-08)                | Cited, pending merge           |
| Exceptions          | none: ThemeSwitcher radios 52 to 98 px by 24 px, DensityToggle 73 and 92 by 24, switch 40 x 24 (§4)                                                             | Pass                           |

### Band F: gate and app states (CMP-079, 085, 089, 090, 091)

| Scenario            | Evidence                                                                                                                                                                | Result                         |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| Keyboard-only       | D02 rest §2 and form-controls §2: RbacGate keeps the T2 keys (re-show the reason once, polite); SkipLink: first Tab shows it, Enter moves focus to the target; 59 tests | Pass, with F-01                |
| Screen-reader       | proxy only; RbacGate sets `aria-disabled` and `aria-describedby`, never `disabled`                                                                                      | Pass at design stage; Q02 owed |
| Colour-independence | T2 is a lock, a tertiary label and a reason; the state pages are words and an action                                                                                    | Pass                           |
| Contrast            | gate 0 findings                                                                                                                                                         | Pass                           |
| Reduced motion      | SkipLink: pill transition 1e-05 s under reduce, 0 s under motion off (Q01 C47)                                                                                          | Pass                           |
| Automated gates     | axe per story; 168 VR baselines                                                                                                                                         | Cited                          |
| Exceptions          | SkipLink is 1 x 1 px while unfocused (visually hidden, as intended) and a pill when focused; the focused pill overlays the header's first button: F-01                  | Open (F-01)                    |

## 3. CVD review

Artifact: `docs/research/artifacts/E05-D04/cvd_simulation_v0.md` (generated; command in its header; 3 themes x 3
deficiencies x 25 pairs and 16 ramp steps per theme, with normal-vision dE alongside). Floor: dE76 5.0 under every deficiency.
Cells are the smallest dE over deuteranopia, protanopia and tritanopia, with the pair that sets it.

| Group (pairs)                                           | dark                              | light                             | high-contrast                        | Verdict |
| ------------------------------------------------------- | --------------------------------- | --------------------------------- | ------------------------------------ | ------- |
| buy / sell (default, hc, candle, `cvd.*`)               | 5.8 (`buy.hc` / `sell.hc`, deut.) | 8.5 (`buy.hc` / `sell.hc`, deut.) | 5.8 (`buy.default` / `sell.default`) | Pass    |
| status ramp (6 pairs of success, warning, danger, info) | 12.1 (success / info)             | 13.5 (success / info)             | 10.3 (success / danger)              | Pass    |
| status strong vs subtle fill (4)                        | 55.7                              | 53.0                              | 55.7                                 | Pass    |
| heatmap ramps, adjacent stops (`heatmap`, 8 each side)  | 6.3 (bid 4-5)                     | 5.3 (bid 2-3)                     | 6.3 (bid 4-5)                        | Pass    |
| `cvd.heatmap` ramps, adjacent stops                     | 7.2 (ask 1-2)                     | 6.1 (ask 4-5)                     | 7.2 (ask 1-2)                        | Pass    |
| heatmap bid vs ask, stop 1 and 5                        | 12.6 (`heatmap`), 49.6 (`cvd`)    | 6.1, 61.1                         | 12.6, 49.6                           | Pass    |
| focus ring vs app, raised, selected                     | 54.2                              | 50.3                              | 77.8                                 | Pass    |
| PreviewTile warning glyph vs sunken and vs danger       | 11.2 (vs `danger.strong`)         | 23.7                              | 11.2                                 | Pass    |
| chart ink (candle up, down, wick, imbalance) vs app     | 44.6                              | 61.4                              | 44.6                                 | Pass    |

**Result: 0 flags**, so the ticket's "no buy/sell pair and no adjacent heatmap ramp stop is indistinguishable" holds
and no Bug is owed for a CVD failure. Readings that need care:

- The high-contrast theme's buy and sell are `#6BD48A` and `#F08A8A`: 5.8 under deuteranopia, 0.8 above the floor
  (31.9 protan, 91.3 tritan). The default pair is 8.3 in dark (deuteranopia) and 16.1 in light. Both rest on lightness, and the product
  never relies on the pair alone (§6). Any retune of these tokens must re-run the artifact.
- Light `heatmap.bid.2` to `.3` is 5.3 under deuteranopia: the narrowest ramp step of the review.
- The gate still carries three light-theme CVD exemptions (`heatmap.bid.3` vs `.4` deuteranopia and protanopia,
  `heatmap.ask.4` vs `.5` protanopia) that quote dE 1.67, 2.43 and 2.64. The tokens were retuned since (#5161): the
  gate's own rows now read 13.6, 14.72 and 9.36 (F-02).
- Dark `status.danger.strong` is `#F0B441`, amber, 14.7 dE from `status.warning.strong` (11.2 under CVD); in light they
  are the same value by owner decision A6 (`E05-D02.md` §6; `packages/ui/tokens/CHANGELOG.md`). The two are told apart
  by glyph and word, never colour (F-06).
- The simulation is of dichromacy (full loss of a cone class); anomalous trichromacy is milder, so the numbers are a
  conservative bound. The floor is a review threshold (5.0), not the classic JND (2.3).

## 4. Essential-exception reconciliation

The E05-D07 log (`docs/research/density-legibility-cvd-e05-d07.md` §3) walks CMP-100..139 only (DomLadderRow,
FootprintCell, the heatmap legend rows), so it holds no v0 row, and this table is the v0 measurement. It is new work, as
the brief anticipated. The probe covered the first four stories of every v0 component at both densities (1,560
elements); "rect" is the element's own box, "hit" is the extent a pointer reaches from its centre (wrapper or label
included), "well" is the field wrapper that carries the border and focus ring. Disabled elements are exempt and were
only counted.

| Control (CMP)                                                                                  | Own rect, compact / comfortable    | Target that counts                                           | Basis                                                                          | On the D07 list? | Verdict                    |
| ---------------------------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------ | ---------------- | -------------------------- |
| Text input, stepper, select trigger, search, combobox, date (007..009, 047, 048, 054)          | input 22 / 30 px tall              | well 24 / 32 px (`cv-field`)                                 | well is the control (2 px = its border)                                        | no, not needed   | Pass                       |
| Step buttons, IconButton, CopyButton, Toast close, DatePicker button (008, 002, 033, 045, 047) | 24 x 24 / 32 x 32                  | the button                                                   | target is 24                                                                   | no, not needed   | Pass                       |
| Toggle, SegmentedControl, RadioGroup, Tabs, ThemeSwitcher, DensityToggle                       | 24 / 32 px tall                    | the item, 37 to 114 px wide                                  | target is 24                                                                   | no, not needed   | Pass                       |
| Checkbox (005)                                                                                 | box 16 x 16, both                  | its label, 72 x 24 / 76 x 32 hit-tested                      | labelled hit area                                                              | no, not needed   | Pass (F-07)                |
| Slider thumb (010)                                                                             | 16 x 16, both                      | the rail, 240 x 24 / 240 x 32 (pointer-down moves the thumb) | D02 spec: "the rail: full width x 24 px"                                       | no, not needed   | Pass                       |
| Menu item (041)                                                                                | text span 18.2 px tall             | `cv-menu__row` 118 x 24 / 118 x 32                           | row is the item                                                                | no, not needed   | Pass                       |
| CommandPalette option (059)                                                                    | text span 18.2 px tall             | row, hit-tested 32 / 40 px                                   | row is the item                                                                | no, not needed   | Pass                       |
| Standalone links (021, 026, 069)                                                               | 17 to 18.3 px tall, 96 to 455 wide | the link                                                     | 2.5.8 spacing: nearest other target 17 px or more from its box (approximation) | no               | Pass, spacing approximated |
| Inline Link in a sentence (021)                                                                | 17 px tall                         | the link                                                     | 2.5.8 inline exception                                                         | no               | Pass                       |
| SkipLink (085), unfocused                                                                      | 1 x 1 px                           | none (visually hidden until focus)                           | not a target until focused                                                     | no               | Pass; focused: F-01        |
| Story-host fixtures (Buy, Zoom in, Run benchmark, Focus ring sample)                           | 21 px tall                         | not library components                                       | demo buttons of three stories                                                  | no               | Not shipped                |

No row needs an essential exception, so none is added to the log and no component is "fixed" by this review. The
probe is a sample (four stories per component), not every state: states reached only by interaction (open menus beyond
the first four stories, hold-to-confirm) were not sized.

## 5. Contrast report and exemptions

`pnpm --filter @candleviewer/ui contrast:gate` exited 0: **0 findings; 45 active exemptions; 378 pair checks, 33 heatmap
checks, 81 CVD checks; data-ink 558 checks, 0 failing in each theme (0 known, 0 new); no-hue-alone ok.** Every
exemption has a reason and an owner, so none is "unexplained" in the registry's sense. Reading them against the gate's
current rows:

| Class                                                                             | Entries (checks)                                                  | State now                                                                                           | Reading          |
| --------------------------------------------------------------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ---------------- |
| Label-on-fill states and other token-level entries                                | 12 (not evaluated as rows)                                        | for example `action.primary.hover`: gated by `tools/contrast/label-on-fill.json` (#3896)            | Explained        |
| Borders and secondary fill vs `surface.app`                                       | 8 (`border.default`, `border.strong`, `action.secondary.default`) | below 3:1: 1.4 to 2.02, "follow-up design debt", no ticket id                                       | Real debt: F-03  |
| `grid.line`, `heatmap.zero` vs canvas                                             | 6                                                                 | 1.15 to 1.17 and 1.00: by design intent (a gridline and a zero stop are not meaning-bearing)        | Explained        |
| Light `color.buy.hc` vs app                                                       | 1                                                                 | 5.75:1 against a 7:1 stretch target, not an AA failure                                              | Explained (F-04) |
| Heatmap stops (8), `profile.bar`, `profile.valuearea`, light `success.strong` (7) | 15 checks                                                         | all **pass now** (for example `heatmap.bid.1` 3.19, `success.strong` light 5.39 against 3.9 quoted) | Stale: F-02      |
| Light heatmap CVD adjacency                                                       | 3                                                                 | pass now (13.6, 14.72, 9.36 against a floor of 5.0)                                                 | Stale: F-02      |

The count of stale checks (18) comes from re-evaluating the gate's rows with a temporary copy of `generate.mjs` that
printed every exempt row that passes; the copy was not kept. `docs/design/_tools/contrast_check.py` and
`verify_tokens.py` were not re-run (the gate covers their pairs).

## 6. Colour independence, motion, zoom and forced colours

- **Colour never the only signal.** `tools/contrast/encodings.json` lists a non-colour channel for every surface that
  renders buy/sell (position, pattern, text, glyph), bid/ask, order status, P&L (sign and text) and connection
  health, and the `no-hue-alone` gate passed. At the v0 components: invalid fields (boundary, glyph, words), toast and
  callout tones (glyph and word), selection (check or outline), T2 (lock, tertiary label, reason), the PreviewTile
  warning (glyph and words), the active tab (2 px rule and `aria-selected`).
- **Reduced motion** on and off: the VR matrix captures with `motion:system` and emulated `reduce`; Q01 C47 measured
  the SkipLink pill at 1e-05 s under reduce and 0 s under motion off.
- **Zoom and text resize.** Specified in each D02 "Resize and overflow" line; Table reflows to a stacked layout (S03
  required state). Not measured live at 200 % here.
- **Forced colours.** Specified in the D02 documents (`05` §8.1); 60 of the 62 component stylesheets contain a
  `forced-colors` block, but no Windows render was run here.

## 7. Findings

Severity: serious blocks sign-off (ticket AC 4); moderate is fixed or filed with a priority; minor and observations are
recorded. Under the filing freeze these are rows, not issues; "Bug owed" means the coordinator files it.

| Id   | Finding                                                                                                                                                                                                                                                                                                             | WCAG SC          | Severity    | Owner ticket                 | Disposition                                                                                                                                                                                           |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- | ----------- | ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-01 | The focused SkipLink pill overlays the header's first button (the #262 sweep finding; reported there, not re-measured here: the Storybook SkipLink story has no header).                                                                                                                                            | 2.5.8, 2.4.11    | Moderate    | E05-S04 (CMP-085), E10-D03   | Fix built on the lane's BQ-4 default in #262's PR (the focused pill takes its own row, in-flow; the re-sweep reads 0 violations over 54 cells); pending the coordinator's ruling and that PR's merge. |
| F-02 | 18 exemption checks now pass (15 pair and heatmap rows, 3 CVD rows), so their reasons are stale; the gate has no stale-exemption check.                                                                                                                                                                             | 1.4.11 (process) | Minor       | E05-T05                      | Remove the entries; follow-up Task: fail the gate on an exemption that passes.                                                                                                                        |
| F-03 | `border.default`, `border.strong` and `action.secondary.default` sit at 1.4 to 2.02:1 on `surface.app` (dark and light; border.strong and the secondary fill also in high contrast), "tracked as follow-up design debt" with no ticket. A secondary Button is identified by its label, so this is a judgement call. | 1.4.11           | Moderate    | E05-T01 (tokens)             | Bug owed, priority p2, naming the three tokens; evidence: §5.                                                                                                                                         |
| F-04 | Light `color.buy.hc` is 5.75:1 on the app surface against a 7:1 stretch target.                                                                                                                                                                                                                                     | none (AA met)    | Minor       | E05-T01                      | Recorded; no action.                                                                                                                                                                                  |
| F-05 | The high-contrast buy/sell pair is 0.8 dE above the 5.0 floor under deuteranopia (5.8); the default pair 8.3 in dark.                                                                                                                                                                                               | 1.4.1            | Observation | E05-T01                      | Safe; re-run the artifact on any retune.                                                                                                                                                              |
| F-06 | Dark `status.danger.strong` and `status.warning.strong` are 14.7 dE apart (11.2 under CVD), identical in light by decision A6.                                                                                                                                                                                      | 1.4.1            | Observation | E05-D02 A6                   | Distinguished by glyph and word.                                                                                                                                                                      |
| F-07 | A Checkbox's 16 x 16 box is a 24 px target only through its label (72 x 24 compact); a checkbox used with no label would be 16 x 16.                                                                                                                                                                                | 2.5.8            | Minor       | E05-S01 (CMP-005); consumers | Screens must keep the label; not measured unlabelled.                                                                                                                                                 |
| F-08 | ThemeSwitcher, DensityToggle and PreviewTile are not on `main`: their VR baselines (240) and the geometry probe come from the slice H tree.                                                                                                                                                                         | n/a              | Minor       | E05-S04                      | Re-check after the slice H PRs merge, before the sign-off is posted.                                                                                                                                  |

No serious finding is open. Rules `05` and `16` are not changed. Follow-up Tasks (not filed): the stale-exemption check
(F-02); a pair-registry row for each of the three borders and fills (F-03).

## 8. Sign-off (drafted for the coordinator)

Posting is the coordinator's, under the owner's delegation. Withhold both if F-01 is ruled serious or a serious finding
appears. Both lines assume the slice H components are merged and §4 and §3 are unchanged.

> **Accessibility-role sign-off for E05-D04: yes, with open items.** Sources: `docs/design/E05/E05-D04-a11y-cvd-signoff.md`,
> `docs/research/artifacts/E05-D04/cvd_simulation_v0.md`. Agent-run, honest scope: not a human pass. Template completed
> for 6 bands (62 components); CVD: 0 flags across 3 themes and 3 deficiencies (narrowest margin 5.8 dE against the 5.0
> floor); essential exceptions: none needed (v0 measured, §4); contrast gate 0 findings, 45 exemptions all carry a reason
> and owner. Open: F-01 (SkipLink overlay, BQ-4), F-02 (18 stale exemptions), F-03 (three borders and fills, Bug owed).
> No serious finding. Limits: no screen reader, no live 200 % zoom, no forced-colours render, no Penpot compare, axe and
> VR cited from CI. Human legs still owed: the manual screen-reader pass (E05-Q02, #262), and any visual-fidelity
> judgement.

> **CDO design sign-off for E05-D04 (R0 quality gate, design-system v0): recommended; owner approval pending.** The
> accessibility gate above holds with open items; the review found nothing that needs a design rule change (`05`, `16`
> unchanged). The CDO sign-off is the owner's `approved` comment or merge.
