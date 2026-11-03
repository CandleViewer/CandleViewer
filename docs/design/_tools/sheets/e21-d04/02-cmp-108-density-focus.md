# E21-D04 / 02 cmp-108-density-focus

File `E21-D04 boards`, page `E21-D04`; export `docs/design/E21/img/E21-D04-02-cmp-108-density-focus.png`; sheet `02-cmp-108-density-focus.json` (validated); theme dark.

Board 02 of ten (§0 L68: CMP-108 at compact and comfortable; focus-visible (CMP-039); the row menu with its T2 trade items). Grid (6000, 0); 3424 x 999 px; "page E21-D04 · board 02 · r2".

## Frames

- `CMP-108 · DomLadderRow ∕ Variant=BidSide, State=Default, Density=Compact · dark` (kit-named)
- `CMP-108 · DomLadderRow ∕ Variant=BidSide, State=Default, Density=Comfortable · dark` (kit-named)
- `CMP-108 · DomLadderRow ∕ Variant=BidSide, State=Focus · dark` (hand-off L36)
- `CMP-108 · DomLadderRow ∕ Variant=BidSide, State=MenuT2 · dark` (hand-off L37)

## Validator and size

- `02-cmp-108-density-focus.json: 0 errors, 5 warnings, 22 sections, 67203 bytes` (exit 0)
- 22 sections, 67203 bytes

## Live checks (7)

- root 'E21-D04 / 02 cmp-108-density-focus' at (6000, 0): read back the name exactly after the first section call; size 3424 x 999
- after touchTexts + relayout: the root h 999 is the live check's max(annotation end, footer end) + 80 (estimated 1012: the annotation column 852 px); re-measure it if the annotations change
- frame 'CMP-108 · DomLadderRow ∕ Variant=BidSide, State=Default, Density=Compact · dark': read back 872 x 256 at (80, 80); clip on, no child spills
- frame 'CMP-108 · DomLadderRow ∕ Variant=BidSide, State=Default, Density=Comfortable · dark': read back 872 x 312 at (1032, 80); clip on, no child spills
- frame 'CMP-108 · DomLadderRow ∕ Variant=BidSide, State=Focus · dark': read back 880 x 224 at (1984, 80); clip on, no child spills
- frame 'CMP-108 · DomLadderRow ∕ Variant=BidSide, State=MenuT2 · dark': read back 872 x 304 at (80, 472); clip on, no child spills
- export docs/design/E21/img/E21-D04-02-cmp-108-density-focus.png; record the board id and the PNG size in §0

## Not drawn (2)

- §0 L78: the light frames outside boards 01, 04 and 06; every Storybook story of §7 beyond the specimen rows above; the reveal's Enter-from-the-pane path (the same region as board 03); CMP-229's other states (E30-D04's); CMP-228's other kinds; CMP-193 (out of scope).
- the kit: W-21 … W-23, the cancel results (§4.8 L228–L230), spoken once through the panel's status node (R-5 L100); §0 draws no cancel result.

## Readings (3)

- column widths 208 / 96 / 96 / 72 / 96 / 272 px are the kit's (D02 §2.3 says 'fixed' and names no width); the Your-orders width fits W-4's longest words
- board 02's density frames extend Table 1's BidSide id with ', Density=…' (§0 draws the density axis; Table 1 names no density variant)
- the menu is drawn open under its row, over the rows below (a popover); its first line is the notice's sentence as the menu's label, so the reason stays visible while the menu covers the header (D02 §5.2)

## Derivations (2)

- bars: length = size / the window's largest size (1.823) × the 80 px cell inner width
- book: BTCUSDT, mark 65,432.0 (W-1's example price, L208), best bid 65,431.9, best ask 65,432.2, 24 levels a side at the fixture's tick 0.10, sizes at its qty step 0.001, seeded 504; trail 12 columns × 1 s to 14:32:10 UTC

## Spec gaps (0)

## Deviations (0)

## Copy keys (2)

- W-2 (own order, verbatim): "Buy 0.5 limit" (L209)
- W-20 (ladder.not_built, verbatim (PROPOSED there)): "Orders from here come later; cancel and close work as usual." (L227)

## Copy gaps (2)

- "Bid (B)", "Ask (A)": the column headers of D02 §2.3 (E21-D02 at 7e1040260; the words are D02's)
- "alert here", "copy price": the row menu's enabled items (D02 §5.2; `14`:1214)

## Fallbacks (4)

- kit choice: board markers (slot names, key captions, the focus-return path, redline callouts) drawn as caption text in a 1 px color.border.strong outline, never product UI
- kit choice: CMP-230's glyph (text first, glyph second) drawn as an 8 × 8 side-coloured square after the words; the glyph itself is the build's
- kit choice: an accessible name or a visually hidden string drawn for the board as caption text in a 'board marker · name' outline (the words a screen reader hears; not on screen in the product)
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN); CMP-019's lock and CMP-227's glyph use it

## Sources (3)

- spec E21-D04.md md5 056eae85 and hand-off md5 67fa3748 (§0 L68; §1-§8; RULED comment 6580397401)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: tools/token-sync.json (names bound; values only for the computed figures)

## Tokens (29)

- type.ui.caption
- color.text.tertiary
- space.inset.sm
- space.inset.xs
- type.num.sm
- color.surface.raised
- color.text.primary
- color.text.secondary
- color.sell.subtle
- color.surface.canvas
- color.buy.subtle
- color.border.strong
- border.hairline
- radius.control
- space.stack.md
- space.inset.lg
- color.buy.default
- color.focus.ring
- border.focus
- space.stack.xs
- color.surface.sunken
- size.icon.sm
- type.ui.body
- color.border.default
- color.surface.overlay
- radius.card
- type.ui.heading-sm
- type.ui.label
- space.stack.sm
