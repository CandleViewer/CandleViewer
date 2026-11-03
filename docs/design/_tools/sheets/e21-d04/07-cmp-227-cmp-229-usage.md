# E21-D04 / 07 cmp-227-cmp-229-usage

File `E21-D04 boards`, page `E21-D04`; export `docs/design/E21/img/E21-D04-07-cmp-227-cmp-229-usage.png`; sheet `07-cmp-227-cmp-229-usage.json` (validated); theme dark.

Board 07 of ten (§0 L73: CMP-227 inline and marker on the panel; CMP-229 read-only T2 LOCKED with its reason). Grid (6000, 3600); 2956 x 789 px; "page E21-D04 · board 07 · r2".

## Frames

- `CMP-227 · EstimatedBadge ∕ Variant=Inline, Host=Strip · dark` (hand-off L220)
- `CMP-227 · EstimatedBadge ∕ Variant=Marker, Host=Pulled · dark` (hand-off L221)
- `CMP-229 · ArmToggle ∕ Scope=Dom, State=ReadOnlyT2 · dark` (hand-off L275)

## Validator and size

- `07-cmp-227-cmp-229-usage.json: 0 errors, 8 warnings, 14 sections, 34767 bytes` (exit 0)
- 14 sections, 34767 bytes

## Live checks (6)

- root 'E21-D04 / 07 cmp-227-cmp-229-usage' at (6000, 3600): read back the name exactly after the first section call; size 2956 x 789
- after touchTexts + relayout: the root h 789 is the live check's max(annotation end, footer end) + 80 (estimated 790: the annotation column 630 px); re-measure it if the annotations change
- frame 'CMP-227 · EstimatedBadge ∕ Variant=Inline, Host=Strip · dark': read back 872 x 168 at (80, 80); clip on, no child spills
- frame 'CMP-227 · EstimatedBadge ∕ Variant=Marker, Host=Pulled · dark': read back 412 x 184 at (1032, 80); clip on, no child spills
- frame 'CMP-229 · ArmToggle ∕ Scope=Dom, State=ReadOnlyT2 · dark': read back 872 x 160 at (1524, 80); clip on, no child spills
- export docs/design/E21/img/E21-D04-07-cmp-227-cmp-229-usage.png; record the board id and the PNG size in §0

## Not drawn (2)

- §0 L78: the light frames outside boards 01, 04 and 06; every Storybook story of §7 beyond the specimen rows above; the reveal's Enter-from-the-pane path (the same region as board 03); CMP-229's other states (E30-D04's); CMP-228's other kinds; CMP-193 (out of scope).
- the kit: W-21 … W-23, the cancel results (§4.8 L228–L230), spoken once through the panel's status node (R-5 L100); §0 draws no cancel result.

## Readings (4)

- CMP-227's glyph (IconName `estimated`, PROPOSED in `15`) is not in the local set: drawn with the local 'info' glyph as a stand-in
- W-8's '(estimated)' is drawn as CMP-227 `inline` beside 'ahead …' (the badge carries the word)
- CMP-227 `marker` beside the pulled mark carries its visible word in the same pane as a text label beside the mark (`15`:2935): W-16's words; drawn at the pane's right edge on the mark's row with a 1 px leader, so neither covers data ink
- CMP-229 is drawn in a DEMO session only: LIVE is the same pill reading the session (R-6), not drawn, so no synthetic account appears under both environments (C-2.11)

## Derivations (6)

- "Buy 0.5 limit, account Acct A": W-5 "Buy 0.5 limit, account Acct B" (L212) filled from the synthetic book
- "ahead 0.3 (estimated)": W-8 "ahead 12.4 (estimated)" (L215) filled from the synthetic book
- heatmap cells: stop = ceil(5 × log-scaled size / the window's largest size 14.5); 0 = color.heatmap.zero (the floor, never a stop)
- "pulled 14.5 (estimated)": W-16 "pulled 18.0 (estimated)" (L223) filled from the synthetic book
- "LOCKED · Acct A · 0.5 BTC": W-19 "LOCKED · {account} · {size} {coin}" (L226) filled from the synthetic book
- book: BTCUSDT, mark 65,432.0 (W-1's example price, L208), best bid 65,431.9, best ask 65,432.2, 24 levels a side at the fixture's tick 0.10, sizes at its qty step 0.001, seeded 504; trail 12 columns × 1 s to 14:32:10 UTC

## Spec gaps (0)

## Deviations (0)

## Copy keys (5)

- W-5 (expanded account row, verbatim): "Buy 0.5 limit, account Acct B" (L212)
- W-8 (queue estimate, verbatim (PROPOSED there)): "ahead 12.4 (estimated)" (L215)
- W-16 (reveal, pulled, verbatim): "pulled 18.0 (estimated)" (L223)
- W-19 (arm.locked, verbatim): "LOCKED · {account} · {size} {coin}" (L226)
- W-20 (ladder.not_built, verbatim (PROPOSED there)): "Orders from here come later; cancel and close work as usual." (L227)

## Copy gaps (1)

- "CMP-134 chip": a detector chip's words are E25's (CMP-134 content, out of scope): a neutral placeholder beside CMP-227 inline

## Fallbacks (5)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN); CMP-019's lock and CMP-227's glyph use it
- kit choice: board markers (slot names, key captions, the focus-return path, redline callouts) drawn as caption text in a 1 px color.border.strong outline, never product UI
- kit choice: the pulled mark's pattern.hatch.estimated (D05E11 §7, cited, not re-made) drawn as 2 × 2 px color.neutral.default steps on a 6 px 45° track inside a 1 px dashed outline; the registry's recipe is applied live
- kit choice: dashed lines (the CMP-227 marker outline, the ask sparkline, the pulled outline) drawn as 4 px dashes with 4 px gaps
- radius.pill is a Tier-1 primitive (validator WARN); CMP-229's Tokens field names it (`15`:2965)

## Sources (3)

- spec E21-D04.md md5 f4e8a509 and hand-off md5 67fa3748 (§0 L73; §1-§8; RULED comment 6580397401)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: tools/token-sync.json (names bound; values only for the computed figures)

## Tokens (32)

- type.ui.caption
- color.text.secondary
- color.status.info.default
- size.icon.sm
- color.text.primary
- space.inset.xs
- color.status.info.subtle
- border.hairline
- radius.badge
- space.inset.sm
- color.border.default
- radius.pill
- color.surface.raised
- color.border.strong
- radius.control
- type.num.sm
- space.stack.md
- space.inset.lg
- color.surface.canvas
- color.heatmap.bid.2
- color.heatmap.bid.1
- color.heatmap.bid.5
- color.neutral.default
- color.heatmap.bid.3
- color.text.tertiary
- type.ui.label
- color.env.demo
- color.focus.ring
- border.focus
- space.stack.xs
- type.ui.heading-sm
- space.stack.sm
