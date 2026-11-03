# E21-D04 / 06 cmp-230-states

File `E21-D04 boards`, page `E21-D04`; export `docs/design/E21/img/E21-D04-06-cmp-230-states.png`; sheet `06-cmp-230-states.json` (validated); theme dark.

Board 06 of ten (§0 L72: CMP-230: single, aggregate, expanded, mixed sides, pending, amending, position marker, no drag). Grid (0, 3600); 3424 x 1195 px; "page E21-D04 · board 06 · r2". Light twin: the same board exported under the light set as `docs/design/E21/img/E21-D04-06-cmp-230-states-light.png`.

## Frames

- `CMP-230 · OwnOrderMarker ∕ Variant=Single, State=Working · dark + light` (hand-off L304)
- `CMP-230 · OwnOrderMarker ∕ Variant=Single, State=Pending · dark + light` (hand-off L305)
- `CMP-230 · OwnOrderMarker ∕ Variant=Single, State=Amending · dark + light` (hand-off L306)
- `CMP-230 · OwnOrderMarker ∕ Variant=Aggregate · dark + light` (hand-off L307)
- `CMP-230 · OwnOrderMarker ∕ Variant=Aggregate, Sides=Mixed · dark + light` (hand-off L308)
- `CMP-230 · OwnOrderMarker ∕ Variant=Aggregate, State=Open · dark + light` (hand-off L309)
- `CMP-230 · OwnOrderMarker ∕ Variant=Position · dark + light` (hand-off L310)
- `CMP-230 · OwnOrderMarker ∕ No drag · dark + light` (kit-named)

## Validator and size

- `06-cmp-230-states.json: 0 errors, 9 warnings, 29 sections, 97045 bytes` (exit 0)
- 29 sections, 97045 bytes

## Live checks (12)

- root 'E21-D04 / 06 cmp-230-states' at (0, 3600): read back the name exactly after the first section call; size 3424 x 1195
- after touchTexts + relayout: the root h 1195 is the live check's max(annotation end, footer end) + 80 (estimated 1229: the annotation column 1069 px); re-measure it if the annotations change
- frame 'CMP-230 · OwnOrderMarker ∕ Variant=Single, State=Working · dark + light': read back 872 x 200 at (80, 80); clip on, no child spills
- frame 'CMP-230 · OwnOrderMarker ∕ Variant=Single, State=Pending · dark + light': read back 872 x 200 at (1032, 80); clip on, no child spills
- frame 'CMP-230 · OwnOrderMarker ∕ Variant=Single, State=Amending · dark + light': read back 872 x 200 at (1984, 80); clip on, no child spills
- frame 'CMP-230 · OwnOrderMarker ∕ Variant=Aggregate · dark + light': read back 872 x 200 at (80, 360); clip on, no child spills
- frame 'CMP-230 · OwnOrderMarker ∕ Variant=Aggregate, Sides=Mixed · dark + light': read back 872 x 200 at (1032, 360); clip on, no child spills
- frame 'CMP-230 · OwnOrderMarker ∕ Variant=Aggregate, State=Open · dark + light': read back 880 x 336 at (1984, 360); clip on, no child spills
- frame 'CMP-230 · OwnOrderMarker ∕ Variant=Position · dark + light': read back 872 x 192 at (80, 776); clip on, no child spills
- frame 'CMP-230 · OwnOrderMarker ∕ No drag · dark + light': read back 872 x 200 at (1032, 776); clip on, no child spills
- light twin: after the dark export, activate the light theme, wait as the drivers do, and export the same board again as docs/design/E21/img/E21-D04-06-cmp-230-states-light.png; read back one bound fill (color.surface.raised) as the light value; switch back to dark
- export docs/design/E21/img/E21-D04-06-cmp-230-states.png; record the board id and the PNG size in §0

## Not drawn (2)

- §0 L78: the light frames outside boards 01, 04 and 06; every Storybook story of §7 beyond the specimen rows above; the reveal's Enter-from-the-pane path (the same region as board 03); CMP-229's other states (E30-D04's); CMP-228's other kinds; CMP-193 (out of scope).
- the kit: W-21 … W-23, the cancel results (§4.8 L228–L230), spoken once through the panel's status node (R-5 L100); §0 draws no cancel result.

## Readings (4)

- column widths 208 / 96 / 96 / 72 / 96 / 272 px are the kit's (D02 §2.3 says 'fixed' and names no width); the Your-orders width fits W-4's longest words
- CMP-230's count badge drawn as the count words in a 1 px pill outline, the rest after a ' · '; the chevron (right collapsed, down expanded) is the kit's expand cue, aria-expanded carries the state
- W-8's '(estimated)' is drawn as CMP-227 `inline` beside 'ahead …' (the badge carries the word)
- CMP-227's glyph (IconName `estimated`, PROPOSED in `15`) is not in the local set: drawn with the local 'info' glyph as a stand-in

## Derivations (12)

- bars: length = size / the window's largest size (1.823) × the 80 px cell inner width
- "Sell 0.3 limit": W-2 "Buy 0.5 limit" (L209) filled from the synthetic book
- bars: length = size / the window's largest size (5.946) × the 80 px cell inner width
- "Buy 0.4 limit": W-2 "Buy 0.5 limit" (L209) filled from the synthetic book
- bars: length = size / the window's largest size (1.778) × the 80 px cell inner width
- bars: length = size / the window's largest size (1.481) × the 80 px cell inner width
- bars: length = size / the window's largest size (2.38) × the 80 px cell inner width
- "Buy 0.5 limit, account Acct A": W-5 "Buy 0.5 limit, account Acct B" (L212) filled from the synthetic book
- "ahead 0.3 (estimated)": W-8 "ahead 12.4 (estimated)" (L215) filled from the synthetic book
- "Buy 0.2 limit, account Acct A": W-5 "Buy 0.5 limit, account Acct B" (L212) filled from the synthetic book
- bars: length = size / the window's largest size (1.032) × the 80 px cell inner width
- book: BTCUSDT, mark 65,432.0 (W-1's example price, L208), best bid 65,431.9, best ask 65,432.2, 24 levels a side at the fixture's tick 0.10, sizes at its qty step 0.001, seeded 504; trail 12 columns × 1 s to 14:32:10 UTC

## Spec gaps (0)

## Deviations (0)

## Copy keys (9)

- W-2 (own order, verbatim): "Buy 0.5 limit" (L209)
- W-6 (pending, verbatim): "pending" (L213)
- W-7 (amending, PROPOSED): "amending" (L214)
- W-3 (own-order aggregate, verbatim (PROPOSED there)): "3 orders · buy 1.2 BTC" (L210)
- W-4 (aggregate, mixed sides, verbatim (PROPOSED there)): "3 orders · buy 1.0 · sell 0.2 BTC" (L211)
- W-5 (expanded account row, verbatim): "Buy 0.5 limit, account Acct B" (L212)
- W-8 (queue estimate, verbatim (PROPOSED there)): "ahead 12.4 (estimated)" (L215)
- W-9 (position marker, verbatim (PROPOSED there)): "Long 0.30 · entry" (L216)
- W-20 (ladder.not_built, verbatim (PROPOSED there)): "Orders from here come later; cancel and close work as usual." (L227)

## Copy gaps (1)

- "Bid (B)", "Ask (A)": the column headers of D02 §2.3 (E21-D02 at 7e1040260; the words are D02's)

## Fallbacks (5)

- kit choice: CMP-230's glyph (text first, glyph second) drawn as an 8 × 8 side-coloured square after the words; the glyph itself is the build's
- kit choice: an accessible name or a visually hidden string drawn for the board as caption text in a 'board marker · name' outline (the words a screen reader hears; not on screen in the product)
- radius.pill is a Tier-1 primitive (validator WARN); CMP-229's Tokens field names it (`15`:2965)
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN); CMP-019's lock and CMP-227's glyph use it
- kit choice: board markers (slot names, key captions, the focus-return path, redline callouts) drawn as caption text in a 1 px color.border.strong outline, never product UI

## Sources (3)

- spec E21-D04.md md5 f4e8a509 and hand-off md5 67fa3748 (§0 L72; §1-§8; RULED comment 6580397401)
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
- space.stack.xs
- color.border.strong
- border.hairline
- radius.control
- color.surface.sunken
- space.stack.md
- space.inset.lg
- color.sell.subtle
- color.sell.default
- radius.pill
- size.icon.sm
- color.status.info.default
- color.status.info.subtle
- radius.badge
- color.focus.ring
- border.focus
- type.ui.heading-sm
- type.ui.label
- space.stack.sm
