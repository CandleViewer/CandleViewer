# E21-D04 / 08 cmp-228-heatmap-kind

File `E21-D04 boards`, page `E21-D04`; export `docs/design/E21/img/E21-D04-08-cmp-228-heatmap-kind.png`; sheet `08-cmp-228-heatmap-kind.json` (validated); theme dark.

Board 08 of ten (§0 L74: CMP-228 heatmap kind: sample, empty, error; its name sentence). Grid (12000, 3600); 2920 x 1030 px; "page E21-D04 · board 08 · r2".

## Frames

- `CMP-228 · PreviewTile ∕ Kind=Heatmap, State=Sample · dark` (hand-off L243)
- `CMP-228 · PreviewTile ∕ Kind=Heatmap, Palette=Cvd · dark` (hand-off L244)
- `CMP-228 · PreviewTile ∕ Kind=Heatmap, Convention=Inv · dark` (hand-off L245)
- `CMP-228 · PreviewTile ∕ Kind=Heatmap, State=Empty · dark` (hand-off L246)
- `CMP-228 · PreviewTile ∕ Kind=Heatmap, State=Error · dark` (hand-off L247)

## Validator and size

- `08-cmp-228-heatmap-kind.json: 0 errors, 1 warnings, 33 sections, 67057 bytes` (exit 0)
- 33 sections, 67057 bytes

## Live checks (8)

- root 'E21-D04 / 08 cmp-228-heatmap-kind' at (12000, 3600): read back the name exactly after the first section call; size 2920 x 1030
- after touchTexts + relayout: the root h 1030 is the live check's max(annotation end, footer end) + 80 (estimated 1037: the annotation column 877 px); re-measure it if the annotations change
- frame 'CMP-228 · PreviewTile ∕ Kind=Heatmap, State=Sample · dark': read back 392 x 248 at (80, 80); clip on, no child spills
- frame 'CMP-228 · PreviewTile ∕ Kind=Heatmap, Palette=Cvd · dark': read back 392 x 248 at (552, 80); clip on, no child spills
- frame 'CMP-228 · PreviewTile ∕ Kind=Heatmap, Convention=Inv · dark': read back 392 x 248 at (1024, 80); clip on, no child spills
- frame 'CMP-228 · PreviewTile ∕ Kind=Heatmap, State=Empty · dark': read back 392 x 240 at (1496, 80); clip on, no child spills
- frame 'CMP-228 · PreviewTile ∕ Kind=Heatmap, State=Error · dark': read back 392 x 240 at (1968, 80); clip on, no child spills
- export docs/design/E21/img/E21-D04-08-cmp-228-heatmap-kind.png; record the board id and the PNG size in §0

## Not drawn (2)

- §0 L78: the light frames outside boards 01, 04 and 06; every Storybook story of §7 beyond the specimen rows above; the reveal's Enter-from-the-pane path (the same region as board 03); CMP-229's other states (E30-D04's); CMP-228's other kinds; CMP-193 (out of scope).
- the kit: W-21 … W-23, the cancel results (§4.8 L228–L230), spoken once through the panel's status node (R-5 L100); §0 draws no cancel result.

## Readings (0)

## Derivations (6)

- heatmap cells: stop = ceil(5 × log-scaled size / the window's largest size 7.736); 0 = color.heatmap.zero (the floor, never a stop)
- "Heatmap preview, sample data: bids green, asks red, log scale, adaptive: anchors follow the visible window": W-18 "Heatmap preview, sample data: {colour words}, {scale words}, {mode words}" (L225) filled from the synthetic book
- "Heatmap preview, sample data: bids blue, asks orange, log scale, adaptive: anchors follow the visible window": W-18 "Heatmap preview, sample data: {colour words}, {scale words}, {mode words}" (L225) filled from the synthetic book
- "bids red, asks green": W-12 "bids green, asks red" with its colours swapped (hand-off L165)
- "Heatmap preview, sample data: bids red, asks green, log scale, adaptive: anchors follow the visible window": W-18 "Heatmap preview, sample data: {colour words}, {scale words}, {mode words}" (L225) filled from the synthetic book
- book: BTCUSDT, mark 65,432.0 (W-1's example price, L208), best bid 65,431.9, best ask 65,432.2, 24 levels a side at the fixture's tick 0.10, sizes at its qty step 0.001, seeded 504; trail 12 columns × 1 s to 14:32:10 UTC

## Spec gaps (0)

## Deviations (0)

## Copy keys (5)

- W-12 (legend, colour words, PROPOSED): "bids green, asks red" (L219)
- W-13 (legend, scale words, PROPOSED): "log scale" (L220)
- W-13 (legend, scale words, PROPOSED): "adaptive: anchors follow the visible window" (L220)
- W-18 (preview tile name, PROPOSED): "Heatmap preview, sample data: {colour words}, {scale words}, {mode words}" (L225)
- W-12 (legend, colour words, PROPOSED): "bids blue, asks orange" (L219)

## Copy gaps (0)

## Fallbacks (1)

- kit choice: an accessible name or a visually hidden string drawn for the board as caption text in a 'board marker · name' outline (the words a screen reader hears; not on screen in the product)

## Sources (3)

- spec E21-D04.md md5 056eae85 and hand-off md5 67fa3748 (§0 L74; §1-§8; RULED comment 6580397401)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: tools/token-sync.json (names bound; values only for the computed figures)

## Tokens (38)

- color.heatmap.ask.5
- color.heatmap.ask.4
- color.heatmap.ask.3
- color.heatmap.ask.2
- color.heatmap.ask.1
- color.heatmap.zero
- color.heatmap.bid.2
- color.heatmap.bid.1
- color.heatmap.bid.3
- color.text.secondary
- space.inset.md
- color.surface.sunken
- color.border.default
- border.hairline
- radius.card
- type.ui.caption
- color.text.primary
- color.text.tertiary
- space.stack.xs
- space.inset.sm
- color.border.strong
- radius.control
- space.stack.md
- space.inset.lg
- color.surface.canvas
- color.cvd.heatmap.ask.5
- color.cvd.heatmap.ask.4
- color.cvd.heatmap.ask.3
- color.cvd.heatmap.ask.2
- color.cvd.heatmap.ask.1
- color.cvd.heatmap.bid.2
- color.cvd.heatmap.bid.1
- color.cvd.heatmap.bid.3
- color.heatmap.bid.5
- color.heatmap.bid.4
- type.ui.heading-sm
- type.ui.label
- space.stack.sm
