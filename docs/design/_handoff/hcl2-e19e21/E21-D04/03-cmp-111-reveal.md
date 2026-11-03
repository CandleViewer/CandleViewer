# E21-D04 / 03 cmp-111-reveal

File `E21-D04 boards`, page `E21-D04`; export `docs/design/E21/img/E21-D04-03-cmp-111-reveal.png`; sheet `03-cmp-111-reveal.json` (validated); theme dark.

Board 03 of ten (§0 L69: CMP-111's reveal: open, empty history, pulled (estimated), stale; the opener row and the focus return). Grid (12000, 0); 4040 x 1672 px; "page E21-D04 · board 03 · r2".

## Frames

- `CMP-111 · HeatmapCell ∕ Palette=Standard, State=Open · dark` (hand-off L101)
- `CMP-111 · HeatmapCell ∕ State=Empty · dark` (hand-off L102)
- `CMP-111 · HeatmapCell ∕ State=Pulled · dark` (hand-off L103)
- `CMP-111 · HeatmapCell ∕ State=Stale · dark` (hand-off L104)

## Validator and size

- `03-cmp-111-reveal.json: 0 errors, 3 warnings, 59 sections, 186018 bytes` (exit 0)
- 59 sections, 186018 bytes

## Live checks (7)

- root 'E21-D04 / 03 cmp-111-reveal' at (12000, 0): read back the name exactly after the first section call; size 4040 x 1672
- after touchTexts + relayout: the annotation column (estimated 800 px) ends inside the root (h 1672); raise the root's h to max(annotation end, footer end) + 80 if not (SHEET-FIX: MEASURED_H)
- frame 'CMP-111 · HeatmapCell ∕ Palette=Standard, State=Open · dark': read back 1080 x 696 at (80, 80); clip on, no child spills
- frame 'CMP-111 · HeatmapCell ∕ State=Empty · dark': read back 1080 x 360 at (1240, 80); clip on, no child spills
- frame 'CMP-111 · HeatmapCell ∕ State=Pulled · dark': read back 1080 x 696 at (2400, 80); clip on, no child spills
- frame 'CMP-111 · HeatmapCell ∕ State=Stale · dark': read back 1080 x 696 at (80, 856); clip on, no child spills
- export docs/design/E21/img/E21-D04-03-cmp-111-reveal.png; record the board id and the PNG size in §0

## Not drawn (2)

- §0 L78: the light frames outside boards 01, 04 and 06; every Storybook story of §7 beyond the specimen rows above; the reveal's Enter-from-the-pane path (the same region as board 03); CMP-229's other states (E30-D04's); CMP-228's other kinds; CMP-193 (out of scope).
- the kit: W-21 … W-23, the cancel results (§4.8 L228–L230), spoken once through the panel's status node (R-5 L100); §0 draws no cancel result.

## Readings (2)

- column widths 208 / 96 / 96 / 72 / 96 / 272 px are the kit's (D02 §2.3 says 'fixed' and names no width); the Your-orders width fits W-4's longest words
- CMP-230's count badge drawn as the count words in a 1 px pill outline, the rest after a ' · '; the chevron (right collapsed, down expanded) is the kit's expand cue, aria-expanded carries the state

## Derivations (17)

- heatmap cells: stop = ceil(5 × log-scaled size / the window's largest size 2.358); 0 = color.heatmap.zero (the floor, never a stop)
- bars: length = size / the window's largest size (1.823) × the 80 px cell inner width
- "Liquidity history at 65,431.9": W-14 "Liquidity history at {price}" (L221) filled from the synthetic book
- "Resting size at 65,431.9, last 12 s: bid 0.559 to 0.504, ask 0 to 0": W-24 "Resting size at {price}, last {span}: bid {bidFrom} to {bidTo}, ask {askFrom} to {askTo}" (L231) filled from the synthetic book
- "Updated 14:32:10": W-17 "Updated {time}" (L224) filled from the synthetic book
- "Resting size by time at 65,431.9": W-25 "Resting size by time at {price}" (L232) filled from the synthetic book
- "Liquidity history at 65,432.0": W-14 "Liquidity history at {price}" (L221) filled from the synthetic book
- heatmap cells: stop = ceil(5 × log-scaled size / the window's largest size 14.5); 0 = color.heatmap.zero (the floor, never a stop)
- "Buy 0.4 limit": W-2 "Buy 0.5 limit" (L209) filled from the synthetic book
- "Liquidity history at 65,431.4": W-14 "Liquidity history at {price}" (L221) filled from the synthetic book
- "Resting size at 65,431.4, last 12 s: bid 14.5 to 1.778, ask 0 to 0": W-24 "Resting size at {price}, last {span}: bid {bidFrom} to {bidTo}, ask {askFrom} to {askTo}" (L231) filled from the synthetic book
- "pulled 14.5 (estimated)": W-16 "pulled 18.0 (estimated)" (L223) filled from the synthetic book
- "Resting size by time at 65,431.4": W-25 "Resting size by time at {price}" (L232) filled from the synthetic book
- "Liquidity history at 65,431.8": W-14 "Liquidity history at {price}" (L221) filled from the synthetic book
- "Resting size at 65,431.8, last 12 s: bid 2.106 to 1.507, ask 0 to 0": W-24 "Resting size at {price}, last {span}: bid {bidFrom} to {bidTo}, ask {askFrom} to {askTo}" (L231) filled from the synthetic book
- "Resting size by time at 65,431.8": W-25 "Resting size by time at {price}" (L232) filled from the synthetic book
- book: BTCUSDT, mark 65,432.0 (W-1's example price, L208), best bid 65,431.9, best ask 65,432.2, 24 levels a side at the fixture's tick 0.10, sizes at its qty step 0.001, seeded 504; trail 12 columns × 1 s to 14:32:10 UTC

## Spec gaps (0)

## Deviations (0)

## Copy keys (9)

- W-2 (own order, verbatim): "Buy 0.5 limit" (L209)
- W-14 (reveal region name, PROPOSED (T's words)): "Liquidity history at {price}" (L221)
- W-24 (reveal sparkline name, PROPOSED): "Resting size at {price}, last {span}: bid {bidFrom} to {bidTo}, ask {askFrom} to {askTo}" (L231)
- W-17 (reveal, snapshot, PROPOSED): "Updated {time}" (L224)
- W-25 (reveal table name, PROPOSED): "Resting size by time at {price}" (L232)
- W-15 (reveal, empty, PROPOSED): "No history at this price in the visible trail." (L222)
- W-7 (amending, PROPOSED): "amending" (L214)
- W-3 (own-order aggregate, verbatim (PROPOSED there)): "3 orders · buy 1.2 BTC" (L210)
- W-16 (reveal, pulled, verbatim): "pulled 18.0 (estimated)" (L223)

## Copy gaps (1)

- "Bid (B)", "Ask (A)": the column headers of D02 §2.3 (E21-D02 at 7e1040260; the words are D02's)

## Fallbacks (8)

- kit choice: CMP-230's glyph (text first, glyph second) drawn as an 8 × 8 side-coloured square after the words; the glyph itself is the build's
- kit choice: board markers (slot names, key captions, the focus-return path, redline callouts) drawn as caption text in a 1 px color.border.strong outline, never product UI
- kit choice: CMP-024's lines drawn as 2 px step segments (horizontal runs joined by vertical risers) on the sample times; bid solid, ask dashed, each labelled at its end
- kit choice: dashed lines (the CMP-227 marker outline, the ask sparkline, the pulled outline) drawn as 4 px dashes with 4 px gaps
- kit choice: an accessible name or a visually hidden string drawn for the board as caption text in a 'board marker · name' outline (the words a screen reader hears; not on screen in the product)
- kit choice: the pulled mark's pattern.hatch.estimated (D05E11 §7, cited, not re-made) drawn as 2 × 2 px color.neutral.default steps on a 6 px 45° track inside a 1 px dashed outline; the registry's recipe is applied live
- radius.pill is a Tier-1 primitive (validator WARN); CMP-229's Tokens field names it (`15`:2965)
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN); CMP-019's lock and CMP-227's glyph use it

## Sources (3)

- spec E21-D04.md md5 db638a7e and hand-off md5 d2486898 (§0 L69; §1-§8; RULED comment 6580397401)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: tools/token-sync.json (names bound; values only for the computed figures)

## Tokens (42)

- color.heatmap.ask.4
- color.heatmap.ask.3
- color.heatmap.ask.2
- color.heatmap.zero
- color.heatmap.bid.2
- color.heatmap.bid.3
- color.heatmap.bid.5
- color.heatmap.bid.4
- color.text.secondary
- type.ui.caption
- color.text.tertiary
- space.inset.sm
- space.inset.xs
- type.num.sm
- color.surface.raised
- color.text.primary
- color.sell.subtle
- color.surface.canvas
- color.buy.subtle
- color.buy.default
- color.focus.ring
- border.focus
- radius.control
- color.border.strong
- border.hairline
- type.ui.heading-sm
- space.stack.xs
- color.surface.sunken
- space.stack.sm
- space.inset.md
- color.border.default
- radius.card
- space.stack.md
- space.inset.lg
- type.ui.body
- color.heatmap.bid.1
- color.neutral.default
- radius.pill
- size.icon.sm
- color.data-confidence.stale.text
- color.data-confidence.stale.surface
- type.ui.label
