# E21-D04 / 10 token-map-redlines

File `E21-D04 boards`, page `E21-D04`; export `docs/design/E21/img/E21-D04-10-token-map-redlines.png`; sheet `10-token-map-redlines.json` (validated); theme dark.

Board 10 of ten (§0 L76: the token map of §5.1 and the redlines: row heights, bar origin, ring offset, badge gap). Grid (24000, 3600); 2480 x 597 px; "page E21-D04 · board 10 · r2".

## Frames

- `Token map ∕ The palette sets and the entries' tokens · dark` (kit-named)
- `Redlines ∕ Rows, bars, ring and badge gaps · dark` (kit-named)

## Validator and size

- `10-token-map-redlines.json: 0 errors, 1 warnings, 9 sections, 30782 bytes` (exit 0)
- 9 sections, 30782 bytes

## Live checks (5)

- root 'E21-D04 / 10 token-map-redlines' at (24000, 3600): read back the name exactly after the first section call; size 2480 x 597
- after touchTexts + relayout: the root h 597 is the live check's max(annotation end, footer end) + 80 (estimated 614: the annotation column 454 px); re-measure it if the annotations change
- frame "Token map ∕ The palette sets and the entries' tokens · dark": read back 880 x 384 at (80, 80); clip on, no child spills
- frame 'Redlines ∕ Rows, bars, ring and badge gaps · dark': read back 880 x 352 at (1040, 80); clip on, no child spills
- export docs/design/E21/img/E21-D04-10-token-map-redlines.png; record the board id and the PNG size in §0

## Not drawn (2)

- §0 L78: the light frames outside boards 01, 04 and 06; every Storybook story of §7 beyond the specimen rows above; the reveal's Enter-from-the-pane path (the same region as board 03); CMP-229's other states (E30-D04's); CMP-228's other kinds; CMP-193 (out of scope).
- the kit: W-21 … W-23, the cancel results (§4.8 L228–L230), spoken once through the panel's status node (R-5 L100); §0 draws no cancel result.

## Readings (3)

- column widths 208 / 96 / 96 / 72 / 96 / 272 px are the kit's (D02 §2.3 says 'fixed' and names no width); the Your-orders width fits W-4's longest words
- CMP-227's glyph (IconName `estimated`, PROPOSED in `15`) is not in the local set: drawn with the local 'info' glyph as a stand-in
- the bar's 'inner edge' read as the edge toward the other side's column: bids grow from the right edge, asks from the left (§4.1 names the inner edge without a side)

## Derivations (1)

- book: BTCUSDT, mark 65,432.0 (W-1's example price, L208), best bid 65,431.9, best ask 65,432.2, 24 levels a side at the fixture's tick 0.10, sizes at its qty step 0.001, seeded 504; trail 12 columns × 1 s to 14:32:10 UTC

## Spec gaps (0)

## Deviations (0)

## Copy keys (1)

- W-2 (own order, verbatim): "Buy 0.5 limit" (L209)

## Copy gaps (2)

- "entry", "tokens (the entry's Tokens field)": board labels for §4's Tokens bullets
- "Bid (B)", "Ask (A)": the column headers of D02 §2.3 (E21-D02 at 7e1040260; the words are D02's)

## Fallbacks (3)

- kit choice: CMP-230's glyph (text first, glyph second) drawn as an 8 × 8 side-coloured square after the words; the glyph itself is the build's
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN); CMP-019's lock and CMP-227's glyph use it
- kit choice: board markers (slot names, key captions, the focus-return path, redline callouts) drawn as caption text in a 1 px color.border.strong outline, never product UI

## Sources (3)

- spec E21-D04.md md5 f4e8a509 and hand-off md5 67fa3748 (§0 L76; §1-§8; RULED comment 6580397401)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: tools/token-sync.json (names bound; values only for the computed figures)

## Tokens (28)

- type.ui.caption
- color.text.primary
- space.inset.sm
- space.inset.xs
- color.surface.canvas
- color.surface.raised
- color.text.secondary
- color.text.tertiary
- color.border.default
- space.stack.xs
- space.stack.md
- space.inset.lg
- type.num.sm
- color.buy.subtle
- color.buy.default
- color.focus.ring
- border.focus
- radius.control
- color.status.info.default
- size.icon.sm
- color.status.info.subtle
- border.hairline
- radius.badge
- color.data-confidence.stale.text
- color.border.strong
- type.ui.heading-sm
- type.ui.label
- space.stack.sm
