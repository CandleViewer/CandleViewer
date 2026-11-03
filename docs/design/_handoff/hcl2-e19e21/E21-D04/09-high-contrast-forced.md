# E21-D04 / 09 high-contrast-forced

File `E21-D04 boards`, page `E21-D04`; export `docs/design/E21/img/E21-D04-09-high-contrast-forced.png`; sheet `09-high-contrast-forced.json` (validated); theme high-contrast.

Board 09 of ten (§0 L75: boards 01, 04 and 06's rows in high contrast and under forced-colors: active). Grid (18000, 3600); 3584 x 1176 px; "page E21-D04 · board 09 · r2".

## Frames

- `CMP-108 · DomLadderRow ∕ High contrast · high contrast` (kit-named)
- `CMP-108 · DomLadderRow ∕ Forced colours · high contrast` (kit-named)
- `CMP-113 · HeatmapLegend ∕ High contrast · high contrast` (kit-named)
- `CMP-113 · HeatmapLegend ∕ Forced colours · high contrast` (kit-named)
- `CMP-230 · OwnOrderMarker ∕ High contrast · high contrast` (kit-named)
- `CMP-230 · OwnOrderMarker ∕ Forced colours · high contrast` (kit-named)

## Validator and size

- `09-high-contrast-forced.json: 0 errors, 8 warnings, 31 sections, 104680 bytes` (exit 0)
- 31 sections, 104680 bytes

## Live checks (10)

- root 'E21-D04 / 09 high-contrast-forced' at (18000, 3600): read back the name exactly after the first section call; size 3584 x 1176
- after touchTexts + relayout: the annotation column (estimated 1008 px) ends inside the root (h 1176); raise the root's h to max(annotation end, footer end) + 80 if not (SHEET-FIX: MEASURED_H)
- frame 'CMP-108 · DomLadderRow ∕ High contrast · high contrast': read back 880 x 288 at (80, 80); clip on, no child spills
- frame 'CMP-108 · DomLadderRow ∕ Forced colours · high contrast': read back 880 x 320 at (1040, 80); clip on, no child spills
- frame 'CMP-113 · HeatmapLegend ∕ High contrast · high contrast': read back 472 x 160 at (2000, 80); clip on, no child spills
- frame 'CMP-113 · HeatmapLegend ∕ Forced colours · high contrast': read back 472 x 160 at (2552, 80); clip on, no child spills
- frame 'CMP-230 · OwnOrderMarker ∕ High contrast · high contrast': read back 880 x 344 at (80, 480); clip on, no child spills
- frame 'CMP-230 · OwnOrderMarker ∕ Forced colours · high contrast': read back 880 x 344 at (1040, 480); clip on, no child spills
- theme: board 09 renders under dark and exports under the high-contrast set (line 3)
- export docs/design/E21/img/E21-D04-09-high-contrast-forced.png; record the board id and the PNG size in §0

## Not drawn (2)

- §0 L78: the light frames outside boards 01, 04 and 06; every Storybook story of §7 beyond the specimen rows above; the reveal's Enter-from-the-pane path (the same region as board 03); CMP-229's other states (E30-D04's); CMP-228's other kinds; CMP-193 (out of scope).
- the kit: W-21 … W-23, the cancel results (§4.8 L228–L230), spoken once through the panel's status node (R-5 L100); §0 draws no cancel result.

## Readings (4)

- column widths 208 / 96 / 96 / 72 / 96 / 272 px are the kit's (D02 §2.3 says 'fixed' and names no width); the Your-orders width fits W-4's longest words
- CMP-230's count badge drawn as the count words in a 1 px pill outline, the rest after a ' · '; the chevron (right collapsed, down expanded) is the kit's expand cue, aria-expanded carries the state
- W-8's '(estimated)' is drawn as CMP-227 `inline` beside 'ahead …' (the badge carries the word)
- CMP-227's glyph (IconName `estimated`, PROPOSED in `15`) is not in the local set: drawn with the local 'info' glyph as a stand-in

## Derivations (8)

- bars: length = size / the window's largest size (1.823) × the 80 px cell inner width
- heatmap cells: stop = ceil(5 × log-scaled size / the window's largest size 2.358); 0 = color.heatmap.zero (the floor, never a stop)
- "Buy 0.5 limit, account Acct A": W-5 "Buy 0.5 limit, account Acct B" (L212) filled from the synthetic book
- "ahead 0.3 (estimated)": W-8 "ahead 12.4 (estimated)" (L215) filled from the synthetic book
- "Buy 0.2 limit, account Acct A": W-5 "Buy 0.5 limit, account Acct B" (L212) filled from the synthetic book
- "Sell 0.3 limit": W-2 "Buy 0.5 limit" (L209) filled from the synthetic book
- bars: length = size / the window's largest size (5.946) × the 80 px cell inner width
- book: BTCUSDT, mark 65,432.0 (W-1's example price, L208), best bid 65,431.9, best ask 65,432.2, 24 levels a side at the fixture's tick 0.10, sizes at its qty step 0.001, seeded 504; trail 12 columns × 1 s to 14:32:10 UTC

## Spec gaps (0)

## Deviations (0)

## Copy keys (10)

- W-2 (own order, verbatim): "Buy 0.5 limit" (L209)
- W-10 (legend, bid, verbatim (PROPOSED there)): "Bid: resting buy liquidity, left column, below the best price" (L217)
- W-11 (legend, ask, verbatim (PROPOSED there)): "Ask: resting sell liquidity, right column, above the best price" (L218)
- W-12 (legend, colour words, PROPOSED): "bids green, asks red" (L219)
- W-13 (legend, scale words, PROPOSED): "log scale" (L220)
- W-13 (legend, scale words, PROPOSED): "adaptive: anchors follow the visible window" (L220)
- W-3 (own-order aggregate, verbatim (PROPOSED there)): "3 orders · buy 1.2 BTC" (L210)
- W-5 (expanded account row, verbatim): "Buy 0.5 limit, account Acct B" (L212)
- W-8 (queue estimate, verbatim (PROPOSED there)): "ahead 12.4 (estimated)" (L215)
- W-6 (pending, verbatim): "pending" (L213)

## Copy gaps (1)

- "Bid (B)", "Ask (A)": the column headers of D02 §2.3 (E21-D02 at 7e1040260; the words are D02's)

## Fallbacks (5)

- kit choice: CMP-230's glyph (text first, glyph second) drawn as an 8 × 8 side-coloured square after the words; the glyph itself is the build's
- kit choice: forced-colours frames bind stand-in tokens that resolve near the system colours under the high-contrast set: Canvas = color.surface.app, CanvasText = color.text.primary, Highlight = color.action.primary.default, GrayText = color.text.tertiary, ButtonText = color.text.primary
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN); CMP-019's lock and CMP-227's glyph use it
- kit choice: legend and ramp swatches drawn as 24 × 16 rects bound to the stop tokens, outlined 1 px color.border.default only in the forced-colours frames (CanvasText outline, §5.5)
- radius.pill is a Tier-1 primitive (validator WARN); CMP-229's Tokens field names it (`15`:2965)

## Sources (3)

- spec E21-D04.md md5 db638a7e and hand-off md5 d2486898 (§0 L75; §1-§8; RULED comment 6580397401)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: tools/token-sync.json (names bound; values only for the computed figures)

## Tokens (46)

- type.ui.caption
- color.text.tertiary
- space.inset.sm
- space.inset.xs
- type.num.sm
- color.surface.raised
- color.text.primary
- color.text.secondary
- color.buy.subtle
- color.surface.canvas
- color.buy.default
- color.focus.ring
- border.focus
- radius.control
- color.data-confidence.stale.text
- color.data-confidence.stale.surface
- space.stack.md
- space.inset.lg
- color.surface.app
- border.hairline
- color.action.primary.default
- size.icon.sm
- type.ui.body
- color.heatmap.bid.1
- color.heatmap.bid.2
- color.heatmap.bid.3
- color.heatmap.bid.4
- color.heatmap.bid.5
- color.heatmap.ask.1
- color.heatmap.ask.2
- color.heatmap.ask.3
- color.heatmap.ask.4
- color.heatmap.ask.5
- color.heatmap.zero
- space.stack.xs
- radius.card
- color.border.strong
- radius.pill
- color.status.info.default
- color.status.info.subtle
- radius.badge
- color.sell.subtle
- color.sell.default
- type.ui.heading-sm
- type.ui.label
- space.stack.sm
