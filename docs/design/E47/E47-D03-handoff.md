# E47-D03 — Hand-off (`16` §11.4; the palettes, the encodings and SCR-116)

Components: **CMP-031 ColorSwatch / ThemeChip** (the accent presets), **CMP-037 SwatchLegendItem** (the legend rows), **CMP-062 ThemeSwitcher**, **CMP-063 DensityToggle**, **CMP-074 / CMP-075** (the env badge per theme), **CMP-228 PreviewTile** (`kind: "theme"`), plus the token sets, `tools/contrast/` and the `14` SCR-116 entry. The spec is [E47-D03.md](E47-D03.md); every "§" below without a prefix is the spec's.

## §A Hand-off checklist (`16` §11.4)

Rule: every line is `[x]` with its evidence, or `[ ]` with the reason.

| Item                     | Tokens and gates                                 | SCR-116 (CMP-031, 062, 063, 228)                    | CMP-074 / CMP-075          |
| ------------------------ | ------------------------------------------------ | --------------------------------------------------- | -------------------------- |
| Final Penpot link        | [ ] boards 09–10, drawn later in this PR         | [ ] boards 01–05, drawn later in this PR            | [ ] board 08               |
| Variants × states        | [x] §2 (twelve renderings)                       | [x] §8.3 V-1 … V-10                                 | [x] §9                     |
| Keyboard table           | [x] n/a                                          | [x] §8.1                                            | [x] unchanged (E10-D03)    |
| Accessible name and role | [x] n/a                                          | [x] §8.1, W-19, R-9                                 | [x] W-3                    |
| Live data                | [x] n/a                                          | [x] R-8: one polite announcement per change, ≤ 1 Hz | [x] unchanged              |
| Motion pair              | [x] none (E47-D08 owns motion)                   | [x] none: one-frame swap (§12)                      | [x] none                   |
| Density notes            | [x] density-independent colour                   | [x] §8.1 (J14), §8.5                                | [x] unchanged              |
| Essential exceptions     | [x] the standing exemptions of §4.2 with reasons | [x] none                                            | [x] none                   |
| Tokens used              | [x] §3, §C.2                                     | [x] §3.1, §8.2                                      | [x] §9                     |
| Data contract            | [ ] NO: D03-G4, D03-G5                           | [ ] NO: D03-G1                                      | [x] unchanged              |
| Contrast                 | [x] §3, §4 (computed)                            | [x] §3.1, §8.2                                      | [x] §9                     |
| Storybook                | [x] §D                                           | [x] §D                                              | [x] §D                     |
| Sign-off                 | [ ] owner approval pending                       | [ ] owner approval pending                          | [ ] owner approval pending |

## §B Who applies what

| Rows                                       | Target                                                                              | Applied by                                                                                                        |
| ------------------------------------------ | ----------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| D03-D1 … D03-D18                           | `packages/ui/tokens/*.tokens.json` (§11.2 runbook A, steps 4–6)                     | E47-D10 (#1309)                                                                                                   |
| D03-A10, D03-A11, D03-A15, D03-A7 … D03-A9 | `tools/contrast/pairs.mjs`, `exemptions.json`, `encodings.json`, `data-ink-lib.mjs` | E47-D10 (#1309) with the `tools/contrast` code owners                                                             |
| D03-A12, D03-A13                           | `packages/ui/scripts/chart-color-modes.mjs`, `apps/web` engine tokens               | E47-D10 (#1309) with the frontend owners                                                                          |
| D03-A1 … D03-A4                            | `14` SCR-116                                                                        | `14`'s owner, at the owner's sign-off PR; D03-A4's payload is stated to E05-D02 (#161), the analytics owner (J16) |
| D03-A5, D03-A14                            | `15` CMP-074, CMP-031                                                               | `15`'s owner                                                                                                      |
| D03-A6                                     | `16` §2.1                                                                           | `16`'s owner                                                                                                      |

## §C Copy-ready rows (PROPOSED)

### §C.1 A-rows

Old is a verbatim fragment of the cited line at `95a4f2765` (the tool checks it); New replaces it, or follows it where the row says "insert after".

| A       | Target                  | Field (`file`:line)    | Old                                                                                    | New                                                                                                                                                                                                                                                                                                                                                                                       |
| ------- | ----------------------- | ---------------------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D03-A1  | `14` SCR-116            | Type (`14`:2458)       | Theme (dark / light / high-contrast / CVD-safe deuteranopia & protanopia / tritanopia) | Theme (Dark · Light · High contrast, with a match-system toggle, J13; the colour-blind-safe option is the chart palette, E47-D03 §2)                                                                                                                                                                                                                                                      |
| D03-A2  | `14` SCR-116            | Type (`14`:2458)       | density (compact / cosy / comfortable)                                                 | density (Compact · Comfortable; J14)                                                                                                                                                                                                                                                                                                                                                      |
| D03-A3  | `14` SCR-116            | checklist (`14`:2464)  | compact / comfortable / spacious density drawn on a real grid                          | Compact · Comfortable density drawn on a real grid (J14)                                                                                                                                                                                                                                                                                                                                  |
| D03-A4  | `14` SCR-116            | Analytics (`14`:2463)  | `appearance.chart_palette_changed` (analytics)                                         | `appearance.chart_palette_changed` with `palette` and `convention` in its payload, and `appearance.accent_changed` with the preset name (analytics; E47-D03 §12)                                                                                                                                                                                                                          |
| D03-A5  | `15` CMP-074            | Tokens (`15`:836)      | `color.env.demo` (blue), `color.env.live` (red), `font.weight.bold`.                   | `color.env.demo` / `color.env.live` for the glyph and the 2 px border on `color.surface.raised`, the word in `color.text.primary`, DEMO `font.weight.medium` / LIVE `font.weight.bold`, `icon/env-demo` / `icon/env-live` (E10-D03 A4). In every theme and chart palette the word and the glyph identify the environment; no palette, accent or theme changes `color.env.*` (E47-D03 §9). |
| D03-A6  | `16` §2.1               | CVD pairs (`16`:51)    | Two colour-blind-safe green/red pairs are pre-validated                                | insert after: ; the colour-blind-safe option is the `color.cvd.*` chart palette (blue / orange), a chart palette, not a theme (E47-D03 §2, §7)                                                                                                                                                                                                                                            |
| D03-A7  | `encodings.json`        | demo-live (ENC:42)     | `"every screen badge": ["text"],`                                                      | `"every screen badge": ["text", "glyph"],`                                                                                                                                                                                                                                                                                                                                                |
| D03-A8  | `encodings.json`        | demo-live (ENC:43)     | `"order ticket": ["text"]`                                                             | `"order ticket": ["text", "glyph"]`                                                                                                                                                                                                                                                                                                                                                       |
| D03-A9  | `encodings.json`        | bid-ask (ENC:17)       | `"heatmap": ["position"],`                                                             | `"heatmap": ["position", "text"],` plus the four new surfaces of spec §5                                                                                                                                                                                                                                                                                                                  |
| D03-A10 | `pairs.mjs`             | H-8 (PAIRS:193)        | Held out (E47-D03 retune)                                                              | after D03-D2: replace the comment with `{ fg: "color.text.link", bg: "color.surface.overlay", threshold: THRESHOLD.TEXT },`                                                                                                                                                                                                                                                               |
| D03-A11 | `exemptions.json`       | pair entries (EXEM:65) | `"pair": "dark:color.profile.bar on color.surface.canvas",`                            | delete this entry and every entry spec §4.2 classes stale; the three retune entries after D03-D3 / D03-D4                                                                                                                                                                                                                                                                                 |
| D03-A12 | `chart-color-modes.mjs` | the remap (MODES:13)   | `["color.footprint.bid", "color.footprint.ask"],`                                      | insert after: the CVD-safe palette also maps `color.heatmap.{bid,ask}.1–5` to `color.cvd.heatmap.{bid,ask}.1–5` and `color.footprint.imbalance` to `color.cvd.imbalance` (E47-D03 §2.3)                                                                                                                                                                                                   |
| D03-A13 | `chartColorMode.ts`     | engine tokens (ENG:15) | `"color.footprint.ask",`                                                               | insert after: the heatmap ramp and imbalance tokens of D03-A12, so the engine re-uploads them in one block                                                                                                                                                                                                                                                                                |
| D03-A14 | `15` CMP-031            | Purpose (`15`:371)     | (drawing tool colour, account colour, heatmap ramp preview)                            | (drawing tool colour, account colour, heatmap ramp preview, the SCR-116 accent presets, E47-D03 §8.2)                                                                                                                                                                                                                                                                                     |
| D03-A15 | `data-ink-lib.mjs`      | GRADIENTS (INK:48)     | `{ id: "heatmap.ask", anchors: side("ask") },`                                         | insert after: `cvd.heatmap.bid` / `cvd.heatmap.ask` gradients over `color.cvd.heatmap.{bid,ask}.1–5`, and a direction check under A11Y-C004: each stop's L* distance from `CANVAS` grows with the stop, so an inverted ramp fails (E47-D03 §7.3)                                                                                                                                          |

### §C.2 The token diff (one schema; applied by E47-D10)

| D       | Set            | Token                                        | Old                            | New                            | Why                                                                                                        |
| ------- | -------------- | -------------------------------------------- | ------------------------------ | ------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| D03-D1  | primitives     | `palette.blue.200`                           | —                              | `#A8C7FA`                      | the high-contrast link (H-8; F-12)                                                                         |
| D03-D2  | semantic-hc    | `color.text.link`                            | —                              | `{palette.blue.200}`           | 7:1 in high contrast on every surface (§3.4)                                                               |
| D03-D3  | semantic-dark  | `color.border.strong`                        | `{palette.neutral.400}`        | `{palette.neutral.600}`        | control boundaries at 3:1 (R-6; F-9); high contrast inherits it, fixing the strong < default order         |
| D03-D4  | semantic-light | `color.border.strong`                        | `{palette.light.neutral.300}`  | `{palette.light.neutral.500}`  | as D03-D3 in light                                                                                         |
| D03-D5  | semantic-dark  | `border.control`                             | —                              | `{border.hairline}`            | a new alias every control boundary binds                                                                   |
| D03-D6  | semantic-hc    | `border.control`                             | —                              | `{border.thick}`               | high contrast adds weight, not only contrast (T Tech)                                                      |
| D03-D7  | semantic-light | `color.cvd.heatmap.bid.1`                    | `{palette.cvd.light.blue.5}`   | `{palette.cvd.light.blue.1}`   | the light CVD ramp reads in the right direction (§7.3)                                                     |
| D03-D8  | semantic-light | `color.cvd.heatmap.bid.2`                    | `{palette.cvd.light.blue.4}`   | `{palette.cvd.light.blue.2}`   | as D03-D7                                                                                                  |
| D03-D9  | semantic-light | `color.cvd.heatmap.bid.4`                    | `{palette.cvd.light.blue.2}`   | `{palette.cvd.light.blue.4}`   | as D03-D7                                                                                                  |
| D03-D10 | semantic-light | `color.cvd.heatmap.bid.5`                    | `{palette.cvd.light.blue.1}`   | `{palette.cvd.light.blue.5}`   | as D03-D7                                                                                                  |
| D03-D11 | semantic-light | `color.cvd.heatmap.ask.1`                    | `{palette.cvd.light.orange.5}` | `{palette.cvd.light.orange.1}` | as D03-D7                                                                                                  |
| D03-D12 | semantic-light | `color.cvd.heatmap.ask.2`                    | `{palette.cvd.light.orange.4}` | `{palette.cvd.light.orange.2}` | as D03-D7                                                                                                  |
| D03-D13 | semantic-light | `color.cvd.heatmap.ask.4`                    | `{palette.cvd.light.orange.2}` | `{palette.cvd.light.orange.4}` | as D03-D7                                                                                                  |
| D03-D14 | semantic-light | `color.cvd.heatmap.ask.5`                    | `{palette.cvd.light.orange.1}` | `{palette.cvd.light.orange.5}` | as D03-D7                                                                                                  |
| D03-D15 | semantic-dark  | `color.data-confidence.disconnected.text`    | `{color.text.primary}`         | `{color.text.secondary}`       | DS-CR-1 (A11Y-R-E08-D12-F-01): a disconnected row no longer reads as live; light and high contrast inherit |
| D03-D16 | semantic-dark  | `color.data-confidence.disconnected.surface` | —                              | `{color.surface.sunken}`       | as D03-D15                                                                                                 |
| D03-D17 | semantic-dark  | `color.data-confidence.reconnecting.text`    | `{color.text.primary}`         | `{color.text.secondary}`       | as D03-D15                                                                                                 |
| D03-D18 | semantic-dark  | `color.data-confidence.reconnecting.surface` | —                              | `{color.surface.sunken}`       | as D03-D15                                                                                                 |

18<!--=COUNT:diff--> values; `.3` stays (it maps to itself). After applying: `build:tokens`, `contrast:gate` (expect the A11Y-C007 stale-matrix step, then `contrast:data-ink` and commit the matrix, `16`:519), `verify_tokens.py`, and this tool's §3.4 and §7.3 rows read on the `+` themes become the base rows.

## §D Storybook story lists (each story per theme and density, `15`:41)

| Component                | Stories                                                                    |
| ------------------------ | -------------------------------------------------------------------------- |
| CMP-031 ColorSwatch      | the merged list + AccentPresets · AccentBelowBar                           |
| CMP-037 SwatchLegendItem | the merged list + HeatmapSide · ImbalanceHatch · DeltaSign · ProfileLevels |
| CMP-062 ThemeSwitcher    | the merged list (J13)                                                      |
| CMP-074 EnvBanner        | the merged list + HighContrast · CvdSafe · Greyscale                       |
| CMP-228 PreviewTile      | the merged list + ThemeCvdSafeInverted · ThemeHighContrast                 |

## §E Owner walkthrough checklist (each frame a 1280 × 800 window)

- [ ] Board 01: every control has a visible label; the chosen accent shows a check glyph, not only a ring.
- [ ] Board 02: Amber in light on a selected row: the warning reads W-1 with a glyph; the swatch keeps its colour; text stays on the link token.
- [ ] Board 03: borders read heavier in high contrast; links read clearly in a drawer.
- [ ] Board 04: the light twin keeps every word of board 01.
- [ ] Board 05: at 150 % and at 200 % nothing is clipped and Reset is reachable.
- [ ] Board 06: in greyscale, side, sign and imbalance are readable from glyph, sign, position and hatch alone.
- [ ] Board 07: under each simulation the CVD-safe buy and sell stay apart.
- [ ] Board 08: LIVE is identifiable in every theme by its word and glyph.
- [ ] Boards 09–10: the heatmap reads "more" the same way in dark and light; the palettes are tradeable, not only compliant.
- [ ] Record `approved` on #1302, or the findings `(heuristic)` with board and frame names.

## §F Consumer pointers

| Consumer                       | Builds from                                     | Waits on               |
| ------------------------------ | ----------------------------------------------- | ---------------------- |
| E47-D10 (#1309)                | §C.2, §C.1 D03-A7 … D03-A13, D03-A15            | —                      |
| E47-D05 (#1304)                | spec §10 (increase contrast and forced colours) | —                      |
| E47-D08 (#1307)                | spec §3.2 (no flash colour), D03-G2             | —                      |
| E47-Q01 (#1314) cases 410, 413 | spec §7.2, §8.2, W-1                            | D03-G3 for screenshots |
| E47-S08 (#1322)                | spec §8                                         | D03-G1                 |
| E08-D04                        | D03-D15 … D03-D18 (DS-CR-1)                     | E47-D10 (#1309)        |

## §G Board plan (drawn later in this PR)

Frames are named `SCR-116/<state> · <theme>` or `ink/<surface> · <theme or simulation>`. Data: a seeded synthetic stream, declared on every board; ink hexes come from spec §7.4. Each board's frames:

| Board | Frames                                                                                                                                    |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 01    | `SCR-116/default · dark`, `SCR-116/preview-tile · dark`                                                                                   |
| 02    | `SCR-116/accent-below-bar · light`                                                                                                        |
| 03    | `SCR-116/default · hc`                                                                                                                    |
| 04    | `SCR-116/default · light`                                                                                                                 |
| 05    | `SCR-116/text-150 · dark`, `SCR-116/zoom-200 · dark`                                                                                      |
| 06    | `ink/footprint · colour`, `ink/footprint · grey`, `ink/heatmap · grey`, `ink/profile · grey`, `ink/cvd-pane · grey`, `ink/bubbles · grey` |
| 07    | `ink/cvd-safe · deut`, `ink/cvd-safe · prot`, `ink/cvd-safe · trit`                                                                       |
| 08    | `env/badge · dark`, `env/badge · light`, `env/badge · hc`, `env/badge · cvd-safe`                                                         |
| 09    | `ink/ramps · dark`                                                                                                                        |
| 10    | `ink/ramps · light`                                                                                                                       |

## §H Summary for #1302

1. Text-first spec + hand-off + default-deny audit tool; 10<!--=COUNT:boards--> boards planned (3<!--=COUNT:boards.light--> in light, 2 of them twins), drawn later in this PR.
2. Three themes × one CVD-safe chart palette × two conventions, one overlay schema; the six ticket ids map onto it.
3. Every pair recomputed per theme; 18<!--=COUNT:exempt.stale--> stale exemptions to remove; H-8, the control borders and the high-contrast border order and DS-CR-1 closed by 18<!--=COUNT:diff--> token values.
4. The light CVD heatmap ramp runs backwards; the diff reverses it on the same primitives.
5. Every surface keeps a non-colour channel; greyscale proves no hue pair suffices alone.
6. SCR-116: closed accent presets measured per theme on a selected row too, the verbatim warning, no T2.
