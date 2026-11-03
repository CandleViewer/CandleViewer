# E21-D04 / 04 cmp-113-sets-scale

File `E21-D04 boards`, page `E21-D04`; export `docs/design/E21/img/E21-D04-04-cmp-113-sets-scale.png`; sheet `04-cmp-113-sets-scale.json` (validated); theme dark.

Board 04 of ten (§0 L70: CMP-113: standard / CVD × both conventions; linear / log; adaptive / locked; stale; no data). Grid (18000, 0); 3872 x 1400 px; "page E21-D04 · board 04 · r2". Light twin: the same board exported under the light set as `docs/design/E21/img/E21-D04-04-cmp-113-sets-scale-light.png`.

## Frames

- `CMP-113 · HeatmapLegend ∕ Palette=Standard, Convention=Default · dark + light` (hand-off L164)
- `CMP-113 · HeatmapLegend ∕ Palette=Standard, Convention=Inverted · dark + light` (hand-off L165)
- `CMP-113 · HeatmapLegend ∕ Palette=Cvd, Convention=Default · dark + light` (hand-off L166)
- `CMP-113 · HeatmapLegend ∕ Palette=Cvd, Convention=Inverted · dark + light` (hand-off L167)
- `CMP-113 · HeatmapLegend ∕ Scale=Log · dark + light` (hand-off L168)
- `CMP-113 · HeatmapLegend ∕ Mode=Adaptive · dark + light` (hand-off L169)
- `CMP-113 · HeatmapLegend ∕ State=Stale · dark + light` (hand-off L170)
- `CMP-113 · HeatmapLegend ∕ State=NoData · dark + light` (hand-off L171)

## Validator and size

- `04-cmp-113-sets-scale.json: 0 errors, 1 warnings, 21 sections, 63257 bytes` (exit 0)
- 21 sections, 63257 bytes

## Live checks (12)

- root 'E21-D04 / 04 cmp-113-sets-scale' at (18000, 0): read back the name exactly after the first section call; size 3872 x 1400
- after touchTexts + relayout: the root h 1400 is the live check's max(annotation end, footer end) + 80 (estimated 1387: the annotation column 1227 px); re-measure it if the annotations change
- frame 'CMP-113 · HeatmapLegend ∕ Palette=Standard, Convention=Default · dark + light': read back 472 x 264 at (80, 80); clip on, no child spills
- frame 'CMP-113 · HeatmapLegend ∕ Palette=Standard, Convention=Inverted · dark + light': read back 472 x 264 at (632, 80); clip on, no child spills
- frame 'CMP-113 · HeatmapLegend ∕ Palette=Cvd, Convention=Default · dark + light': read back 472 x 264 at (1184, 80); clip on, no child spills
- frame 'CMP-113 · HeatmapLegend ∕ Palette=Cvd, Convention=Inverted · dark + light': read back 472 x 264 at (1736, 80); clip on, no child spills
- frame 'CMP-113 · HeatmapLegend ∕ Scale=Log · dark + light': read back 472 x 464 at (2288, 80); clip on, no child spills
- frame 'CMP-113 · HeatmapLegend ∕ Mode=Adaptive · dark + light': read back 472 x 464 at (2840, 80); clip on, no child spills
- frame 'CMP-113 · HeatmapLegend ∕ State=Stale · dark + light': read back 472 x 264 at (80, 624); clip on, no child spills
- frame 'CMP-113 · HeatmapLegend ∕ State=NoData · dark + light': read back 472 x 264 at (632, 624); clip on, no child spills
- light twin: after the dark export, activate the light theme, wait as the drivers do, and export the same board again as docs/design/E21/img/E21-D04-04-cmp-113-sets-scale-light.png; read back one bound fill (color.surface.raised) as the light value; switch back to dark
- export docs/design/E21/img/E21-D04-04-cmp-113-sets-scale.png; record the board id and the PNG size in §0

## Not drawn (2)

- §0 L78: the light frames outside boards 01, 04 and 06; every Storybook story of §7 beyond the specimen rows above; the reveal's Enter-from-the-pane path (the same region as board 03); CMP-229's other states (E30-D04's); CMP-228's other kinds; CMP-193 (out of scope).
- the kit: W-21 … W-23, the cancel results (§4.8 L228–L230), spoken once through the panel's status node (R-5 L100); §0 draws no cancel result.

## Readings (0)

## Derivations (7)

- heatmap cells: stop = ceil(5 × log-scaled size / the window's largest size 2.358); 0 = color.heatmap.zero (the floor, never a stop)
- "bids red, asks green": W-12 "bids green, asks red" with its colours swapped (hand-off L165)
- "bids orange, asks blue": W-12 "bids blue, asks orange" with its colours swapped (hand-off L165)
- heatmap cells: stop = ceil(5 × linear-scaled size / the window's largest size 2.358); 0 = color.heatmap.zero (the floor, never a stop)
- heatmap cells: stop = ceil(5 × log-scaled size / the window's largest size 1.216); 0 = color.heatmap.zero (the floor, never a stop)
- locked anchors: the window's anchors when the lock was taken (its first five rows, largest 1.216)
- book: BTCUSDT, mark 65,432.0 (W-1's example price, L208), best bid 65,431.9, best ask 65,432.2, 24 levels a side at the fixture's tick 0.10, sizes at its qty step 0.001, seeded 504; trail 12 columns × 1 s to 14:32:10 UTC

## Spec gaps (0)

## Deviations (0)

## Copy keys (8)

- W-10 (legend, bid, verbatim (PROPOSED there)): "Bid: resting buy liquidity, left column, below the best price" (L217)
- W-11 (legend, ask, verbatim (PROPOSED there)): "Ask: resting sell liquidity, right column, above the best price" (L218)
- W-12 (legend, colour words, PROPOSED): "bids green, asks red" (L219)
- W-13 (legend, scale words, PROPOSED): "log scale" (L220)
- W-13 (legend, scale words, PROPOSED): "adaptive: anchors follow the visible window" (L220)
- W-12 (legend, colour words, PROPOSED): "bids blue, asks orange" (L219)
- W-13 (legend, scale words, PROPOSED): "linear scale" (L220)
- W-13 (legend, scale words, PROPOSED): "anchors locked" (L220)

## Copy gaps (0)

## Fallbacks (3)

- kit choice: legend and ramp swatches drawn as 24 × 16 rects bound to the stop tokens, outlined 1 px color.border.default only in the forced-colours frames (CanvasText outline, §5.5)
- kit choice: an accessible name or a visually hidden string drawn for the board as caption text in a 'board marker · name' outline (the words a screen reader hears; not on screen in the product)
- kit choice: board markers (slot names, key captions, the focus-return path, redline callouts) drawn as caption text in a 1 px color.border.strong outline, never product UI

## Sources (3)

- spec E21-D04.md md5 f4e8a509 and hand-off md5 67fa3748 (§0 L70; §1-§8; RULED comment 6580397401)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: tools/token-sync.json (names bound; values only for the computed figures)

## Tokens (42)

- color.heatmap.bid.1
- color.heatmap.bid.2
- color.heatmap.bid.3
- color.heatmap.bid.4
- color.heatmap.bid.5
- space.inset.xs
- type.ui.caption
- color.text.primary
- space.inset.sm
- color.heatmap.ask.1
- color.heatmap.ask.2
- color.heatmap.ask.3
- color.heatmap.ask.4
- color.heatmap.ask.5
- color.text.secondary
- color.heatmap.zero
- type.num.sm
- space.inset.lg
- space.stack.xs
- color.surface.raised
- radius.card
- color.text.tertiary
- color.border.strong
- border.hairline
- radius.control
- color.surface.sunken
- space.stack.md
- color.surface.canvas
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
- color.data-confidence.stale.text
- type.ui.heading-sm
- type.ui.label
- space.stack.sm
