# E47-D06 / 02 surrogate-grammar

File `E47-D06 boards`, page `E47-D06 — Canvas accessibility`; export `docs/design/E47/img/E47-D06-02-surrogate-grammar.png`; sheet `02-surrogate-grammar.json` (validated); theme dark.

Board 02 of 8 (§0 L68: §3: the cursor window over a chart, the sparse set over bubbles, the 24 px target overlay and the overlap rule). Grid (7000, 0); 4640 x 998 px; "page E47-D06 — Canvas accessibility · board 02 · r1".

## Frames

- `grammar∕cursor-window · dark` (§I: `grammar/cursor-window · dark`)
- `grammar∕sparse-set · dark` (§I: `grammar/sparse-set · dark`)
- `grammar∕targets · dark` (§I: `grammar/targets · dark`)

## Validator and size

- `02-surrogate-grammar.json: 0 errors, 46 warnings, 123 sections, 105246 bytes` (exit 0)
- 123 sections, 105246 bytes

## Live checks (7)

- surrogate squares: the post-step dashes every 'dashed · surrogate …' bound (36: 18 in each of the sparse-set and targets frames); read the count back
- root 'E47-D06 / 02 surrogate-grammar' at (7000, 0): read back the name exactly after the first section call; size 4640 x 998
- after touchTexts + relayout: the root's h 998 is the measured max(column end, footer end) + 80 (annotation column estimated 503 px); read it back
- frame 'grammar∕cursor-window · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'grammar∕sparse-set · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'grammar∕targets · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D06-02-surrogate-grammar.png; record the board id and the PNG size in §0

## Ambiguities (2)

- a single big print carries no estimated slot; a cluster carries "Estimated, Trade cluster" (CMP-112 names a cluster "…, estimated", `15`:1326; CMP-227's display name for trade_cluster)
- the big-trade threshold is the loaded series' 99th size percentile (0.893 BTC, kit choice); the bubble radius 4 + sqrt(notional / 10,000) px is a kit encoding

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (1)

- the hidden table's and the set's group names are not in §13 (E47-D07 words them)

## Fallbacks (5)

- kit choice: the canvas surfaces are drawn as simplified synthetic plots (bodies, wicks, bars, bubbles) from the seeded stream; their own visual design is their tickets', not this spec's
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: numbered markers, tags, brackets and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) drawn as neutral placeholders (the E47-D03 kit's SCR-116 chrome); only the panels this spec designs carry words
- kit choice: a hidden layer (the mirror table, a surrogate's bounds, an aria-describedby link) is drawn as an annotation callout or a dashed-outline overlay in color.status.info.default; it has no pixels in the product (clip-path, R-4)

## Sources (1)

- spec docs/design/E47/E47-D06.md md5 fdde6ab4, hand-off docs/design/E47/E47-D06-handoff.md md5 c6ebe77c (§0 L68; hand-off §I L111); T2 reason templates docs/design/E09/E09-D09.md md5 20c5d5f4; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 48c711e64 (§7.1)

## Tokens (38)

- color.surface.canvas
- border.hairline
- color.focus.ring
- border.focus
- color.candle.wick
- color.candle.up
- color.candle.down
- opacity.muted
- color.crosshair
- type.num.sm
- color.axis.text
- color.text.secondary
- size.icon.sm
- type.ui.caption
- color.text.primary
- color.border.default
- radius.badge
- space.inset.sm
- space.inset.xs
- type.ui.body-strong
- type.ui.label
- color.surface.selected
- radius.control
- color.surface.raised
- radius.card
- space.stack.xs
- color.surface.overlay
- color.status.info.default
- border.thick
- color.surface.app
- color.surface.hover
- color.border.subtle
- space.inset.md
- space.inset.lg
- color.text.inverse
- type.ui.heading-sm
- color.text.tertiary
- space.stack.sm
