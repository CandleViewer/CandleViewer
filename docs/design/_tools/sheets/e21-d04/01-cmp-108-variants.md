# E21-D04 / 01 cmp-108-variants

File `E21-D04 boards`, page `E21-D04`; export `docs/design/E21/img/E21-D04-01-cmp-108-variants.png`; sheet `01-cmp-108-variants.json` (validated); theme dark.

Board 01 of ten (§0 L67: CMP-108: bid-side, ask-side, at-mark, own-order present, stale, estimated; the size bars and the slots). Grid (0, 0); 3416 x 1512 px; "page E21-D04 · board 01 · r2". Light twin: the same board exported under the light set as `docs/design/E21/img/E21-D04-01-cmp-108-variants-light.png`.

## Frames

- `CMP-108 · DomLadderRow ∕ Variant=BidSide, State=Default · dark + light` (hand-off L27)
- `CMP-108 · DomLadderRow ∕ Variant=AskSide, State=Default · dark + light` (hand-off L28)
- `CMP-108 · DomLadderRow ∕ Variant=Best, State=Default · dark + light` (hand-off L29)
- `CMP-108 · DomLadderRow ∕ Variant=AtMark, State=Default · dark + light` (hand-off L30)
- `CMP-108 · DomLadderRow ∕ Variant=OwnOrder, State=Default · dark + light` (hand-off L31)
- `CMP-108 · DomLadderRow ∕ Variant=OwnOrder, State=Aggregate · dark + light` (hand-off L32)
- `CMP-108 · DomLadderRow ∕ Variant=Position, State=Default · dark + light` (hand-off L33)
- `CMP-108 · DomLadderRow ∕ Variant=Stale, State=Default · dark + light` (hand-off L34)
- `CMP-108 · DomLadderRow ∕ Variant=Estimated, State=Default · dark + light` (hand-off L35)

## Validator and size

- `01-cmp-108-variants.json: 0 errors, 4 warnings, 34 sections, 106748 bytes` (exit 0)
- 34 sections, 106748 bytes

## Live checks (13)

- root 'E21-D04 / 01 cmp-108-variants' at (0, 0): read back the name exactly after the first section call; size 3416 x 1512
- after touchTexts + relayout: the root h 1512 is the live check's max(annotation end, footer end) + 80 (estimated 1531: the annotation column 1371 px); re-measure it if the annotations change
- frame 'CMP-108 · DomLadderRow ∕ Variant=BidSide, State=Default · dark + light': read back 872 x 224 at (80, 80); clip on, no child spills
- frame 'CMP-108 · DomLadderRow ∕ Variant=AskSide, State=Default · dark + light': read back 872 x 224 at (1032, 80); clip on, no child spills
- frame 'CMP-108 · DomLadderRow ∕ Variant=Best, State=Default · dark + light': read back 872 x 232 at (1984, 80); clip on, no child spills
- frame 'CMP-108 · DomLadderRow ∕ Variant=AtMark, State=Default · dark + light': read back 872 x 224 at (80, 392); clip on, no child spills
- frame 'CMP-108 · DomLadderRow ∕ Variant=OwnOrder, State=Default · dark + light': read back 872 x 232 at (1032, 392); clip on, no child spills
- frame 'CMP-108 · DomLadderRow ∕ Variant=OwnOrder, State=Aggregate · dark + light': read back 872 x 232 at (1984, 392); clip on, no child spills
- frame 'CMP-108 · DomLadderRow ∕ Variant=Position, State=Default · dark + light': read back 872 x 224 at (80, 704); clip on, no child spills
- frame 'CMP-108 · DomLadderRow ∕ Variant=Stale, State=Default · dark + light': read back 872 x 224 at (1032, 704); clip on, no child spills
- frame 'CMP-108 · DomLadderRow ∕ Variant=Estimated, State=Default · dark + light': read back 872 x 224 at (1984, 704); clip on, no child spills
- light twin: after the dark export, activate the light theme, wait as the drivers do, and export the same board again as docs/design/E21/img/E21-D04-01-cmp-108-variants-light.png; read back one bound fill (color.surface.raised) as the light value; switch back to dark
- export docs/design/E21/img/E21-D04-01-cmp-108-variants.png; record the board id and the PNG size in §0

## Not drawn (2)

- §0 L78: the light frames outside boards 01, 04 and 06; every Storybook story of §7 beyond the specimen rows above; the reveal's Enter-from-the-pane path (the same region as board 03); CMP-229's other states (E30-D04's); CMP-228's other kinds; CMP-193 (out of scope).
- the kit: W-21 … W-23, the cancel results (§4.8 L228–L230), spoken once through the panel's status node (R-5 L100); §0 draws no cancel result.

## Readings (4)

- column widths 208 / 96 / 96 / 72 / 96 / 272 px are the kit's (D02 §2.3 says 'fixed' and names no width); the Your-orders width fits W-4's longest words
- CMP-230's count badge drawn as the count words in a 1 px pill outline, the rest after a ' · '; the chevron (right collapsed, down expanded) is the kit's expand cue, aria-expanded carries the state
- CMP-227's glyph (IconName `estimated`, PROPOSED in `15`) is not in the local set: drawn with the local 'info' glyph as a stand-in
- 'estimated' row: the pulled level (its last change is a pull, an estimate, M AD-6), shown with CMP-227 `inline` in the Price cell

## Derivations (10)

- bars: length = size / the window's largest size (1.823) × the 80 px cell inner width
- "Sell 0.3 limit": W-2 "Buy 0.5 limit" (L209) filled from the synthetic book
- bars: length = size / the window's largest size (5.946) × the 80 px cell inner width
- bars: length = size / the window's largest size (1.507) × the 80 px cell inner width
- bars: length = size / the window's largest size (0.504) × the 80 px cell inner width
- bars: length = size / the window's largest size (1.481) × the 80 px cell inner width
- bars: length = size / the window's largest size (1.032) × the 80 px cell inner width
- "Buy 0.4 limit": W-2 "Buy 0.5 limit" (L209) filled from the synthetic book
- bars: length = size / the window's largest size (1.778) × the 80 px cell inner width
- book: BTCUSDT, mark 65,432.0 (W-1's example price, L208), best bid 65,431.9, best ask 65,432.2, 24 levels a side at the fixture's tick 0.10, sizes at its qty step 0.001, seeded 504; trail 12 columns × 1 s to 14:32:10 UTC

## Spec gaps (0)

## Deviations (0)

## Copy keys (5)

- W-2 (own order, verbatim): "Buy 0.5 limit" (L209)
- W-6 (pending, verbatim): "pending" (L213)
- W-3 (own-order aggregate, verbatim (PROPOSED there)): "3 orders · buy 1.2 BTC" (L210)
- W-9 (position marker, verbatim (PROPOSED there)): "Long 0.30 · entry" (L216)
- W-7 (amending, PROPOSED): "amending" (L214)

## Copy gaps (1)

- "Bid (B)", "Ask (A)": the column headers of D02 §2.3 (E21-D02 at 7e1040260; the words are D02's)

## Fallbacks (5)

- kit choice: CMP-230's glyph (text first, glyph second) drawn as an 8 × 8 side-coloured square after the words; the glyph itself is the build's
- kit choice: board markers (slot names, key captions, the focus-return path, redline callouts) drawn as caption text in a 1 px color.border.strong outline, never product UI
- kit choice: an accessible name or a visually hidden string drawn for the board as caption text in a 'board marker · name' outline (the words a screen reader hears; not on screen in the product)
- radius.pill is a Tier-1 primitive (validator WARN); CMP-229's Tokens field names it (`15`:2965)
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN); CMP-019's lock and CMP-227's glyph use it

## Sources (3)

- spec E21-D04.md md5 f4e8a509 and hand-off md5 67fa3748 (§0 L67; §1-§8; RULED comment 6580397401)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: tools/token-sync.json (names bound; values only for the computed figures)

## Tokens (30)

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
- color.border.strong
- border.hairline
- radius.control
- space.stack.xs
- color.surface.sunken
- space.stack.md
- space.inset.lg
- color.sell.subtle
- color.sell.default
- radius.pill
- size.icon.sm
- color.data-confidence.stale.text
- color.data-confidence.stale.surface
- color.status.info.default
- color.status.info.subtle
- radius.badge
- type.ui.heading-sm
- type.ui.label
- space.stack.sm
