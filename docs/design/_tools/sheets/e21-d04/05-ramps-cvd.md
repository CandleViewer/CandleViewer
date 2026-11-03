# E21-D04 / 05 ramps-cvd

File `E21-D04 boards`, page `E21-D04`; export `docs/design/E21/img/E21-D04-05-ramps-cvd.png`; sheet `05-ramps-cvd.json` (validated); theme dark.

Board 05 of ten (§0 L71: the ramps' stops on the canvas; greyscale and the three simulations of board 04). Grid (24000, 0); 2304 x 958 px; "page E21-D04 · board 05 · r2".

## Frames

- `Ramps ∕ The four palette sets on the canvas · dark` (kit-named)
- `Ramps ∕ Colour vision after simulation · dark` (kit-named)

## Validator and size

- `05-ramps-cvd.json: 0 errors, 1 warnings, 28 sections, 69648 bytes` (exit 0)
- 28 sections, 69648 bytes

## Live checks (5)

- root 'E21-D04 / 05 ramps-cvd' at (24000, 0): read back the name exactly after the first section call; size 2304 x 958
- after touchTexts + relayout: the root h 958 is the live check's max(annotation end, footer end) + 80 (estimated 957: the annotation column 494 px); re-measure it if the annotations change
- frame 'Ramps ∕ The four palette sets on the canvas · dark': read back 752 x 760 at (80, 80); clip on, no child spills
- frame 'Ramps ∕ Colour vision after simulation · dark': read back 832 x 280 at (912, 80); clip on, no child spills
- export docs/design/E21/img/E21-D04-05-ramps-cvd.png; record the board id and the PNG size in §0

## Not drawn (2)

- §0 L78: the light frames outside boards 01, 04 and 06; every Storybook story of §7 beyond the specimen rows above; the reveal's Enter-from-the-pane path (the same region as board 03); CMP-229's other states (E30-D04's); CMP-228's other kinds; CMP-193 (out of scope).
- the kit: W-21 … W-23, the cancel results (§4.8 L228–L230), spoken once through the panel's status node (R-5 L100); §0 draws no cancel result.

## Readings (1)

- board 05's 'greyscale and the three simulations of board 04' cannot be painted (cvsheet binds tokens, never simulated hexes): they are cvd_sim.py renders of board 04's export, and the drawn frame carries §5.3's computed table; a tritanopia render has no tool (spec gap)

## Derivations (2)

- ratios: WCAG 2.x relative luminance of the token-sync.json values per theme (dark; light = dark + semantic-light; high-contrast = dark + semantic-hc), rounded half-up to 0.01; the lowest per palette equal §5.2's table: dark color.heatmap.ask.1 3.15, color.cvd.heatmap.bid.1 3.86; light color.heatmap.bid.1 3.34, color.cvd.heatmap.bid.5 3.28; high-contrast color.heatmap.ask.1 3.15, color.cvd.heatmap.bid.1 3.86
- book: BTCUSDT, mark 65,432.0 (W-1's example price, L208), best bid 65,431.9, best ask 65,432.2, 24 levels a side at the fixture's tick 0.10, sizes at its qty step 0.001, seeded 504; trail 12 columns × 1 s to 14:32:10 UTC

## Spec gaps (1)

- §0 board 05 asks for three simulations of board 04; cvd_sim.py renders greyscale, deuteranopia and protanopia only: tritanopia is the §5.3 table's figures

## Deviations (0)

## Copy keys (0)

## Copy gaps (3)

- "floor", "bid stops", "ask stops": board labels for §5.1's columns (Bid stops, Ask stops, Floor)
- "set": the board label of §5.1's first column
- "stop", "dark", "light", "high-contrast": the ratio table's column labels (§5.2's theme names)

## Fallbacks (2)

- kit choice: legend and ramp swatches drawn as 24 × 16 rects bound to the stop tokens, outlined 1 px color.border.default only in the forced-colours frames (CanvasText outline, §5.5)
- kit choice: board markers (slot names, key captions, the focus-return path, redline callouts) drawn as caption text in a 1 px color.border.strong outline, never product UI

## Sources (3)

- spec E21-D04.md md5 f4e8a509 and hand-off md5 67fa3748 (§0 L71; §1-§8; RULED comment 6580397401)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: tools/token-sync.json (names bound; values only for the computed figures)

## Tokens (41)

- type.ui.caption
- color.text.primary
- color.heatmap.bid.1
- color.heatmap.bid.2
- color.heatmap.bid.3
- color.heatmap.bid.4
- color.heatmap.bid.5
- space.inset.xs
- color.heatmap.ask.1
- color.heatmap.ask.2
- color.heatmap.ask.3
- color.heatmap.ask.4
- color.heatmap.ask.5
- color.heatmap.zero
- color.text.secondary
- space.inset.md
- color.cvd.heatmap.bid.1
- color.cvd.heatmap.bid.2
- color.cvd.heatmap.bid.3
- color.cvd.heatmap.bid.4
- color.cvd.heatmap.bid.5
- color.cvd.heatmap.ask.1
- color.cvd.heatmap.ask.2
- color.cvd.heatmap.ask.3
- color.cvd.heatmap.ask.4
- color.cvd.heatmap.ask.5
- color.text.tertiary
- space.inset.sm
- type.num.sm
- color.surface.canvas
- color.surface.raised
- space.stack.xs
- color.border.strong
- border.hairline
- radius.control
- space.stack.sm
- space.stack.md
- space.inset.lg
- color.border.default
- type.ui.heading-sm
- type.ui.label
