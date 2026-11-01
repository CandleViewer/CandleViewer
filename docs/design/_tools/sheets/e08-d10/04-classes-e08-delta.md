# E08-D10 / 04 classes-e08-delta

File `E08-D10 boards`, page `E08-D10 SCR-151 empty and backfill states`; export `docs/design/E08/img/E08-D10-04-classes-e08-delta.png`; sheet `04-classes-e08-delta.json` (validated); theme dark.

Board 04 of nine (§0 L84: the E08 delta only: W-10 and W-11 superseding D02's two strings (D10-C1); the E08 exemplars as an E08 table, the classes cited). Grid (18000, 0); 3280 x 998 px; "page E08-D10 SCR-151 empty and backfill states · board 04 · r1".

## Frames

- `SCR-151∕classes∕e08-delta · dark` (§H `SCR-151/classes/e08-delta · dark`)
- `SCR-151∕classes∕e08-exemplars · dark` (§H `SCR-151/classes/e08-exemplars · dark`)

## Validator and size

- `04-classes-e08-delta.json: 0 errors, 1 warnings, 10 sections, 32473 bytes` (exit 0)
- 10 sections, 32473 bytes

## Live checks (5)

- root 'E08-D10 / 04 classes-e08-delta' at (18000, 0): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the annotation column (estimated 616 px) ends inside the root (h 998); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-151∕classes∕e08-delta · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-151∕classes∕e08-exemplars · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E08/img/E08-D10-04-classes-e08-delta.png: every frame is 1280 x 800; record the board id and the PNG size

## Derivations (0)

## Spec gaps (0)

## Deviations (1)

- classes/e08-delta: CMP-026's recording-not-started glyph drawn with the local icon 'pending' (the E16-D05 calendar glyph is not in the local set)

## Copy keys (5)

- W-10 empty.heading.history_starts (§13 L363; verbatim)
- W-11 empty.cause.recorded_only (§13 L364; verbatim)
- W-16 classes.created.heading (§13 L369)
- W-15 none: SCR-053's host string (§13 L368)
- W-10 empty.heading.history_starts (§13 L363)

## Copy gaps (3)

- panel title "Bars BTCUSDT 5 minutes": §10.1 L287's naming example (kind · symbol · interval spelled out)
- column headers time · open · high · low · close · volume: D04E11 L784
- board footer "Data: a seeded synthetic history (seed 178), not recorded": hand-off §H L93 ("declared synthetic on every board's face")

## G rows (0)

## Fallbacks (2)

- kit choice: the backfilling chip's glyph is the local icon 'pending', §3's block glyph
- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders, the E08-D09 kit's geometry; only the host panel is this spec's (§0: one host panel per window)

## Sources (7)

- spec E08-D10.md md5 1b86f428 and hand-off md5 c6177822 (§0 L84, §H L100, §3-§7, §10-§13)
- docs/design/E11/E11-D04.md md5 02f3ff69
- docs/design/E22/E22-D02.md md5 9acb071a
- docs/design/E22/E22-D03.md md5 858221c5
- docs/design/E08/E08-D02.md md5 35c1af94
- docs/design/E08/E08-D04.md md5 ceff9775
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (26)

- type.ui.heading-sm
- color.text.primary
- type.num.sm
- space.inset.xs
- color.text.tertiary
- size.icon.lg
- type.ui.body
- color.text.secondary
- space.stack.sm
- space.stack.md
- space.inset.xl
- type.ui.label
- type.ui.caption
- space.inset.sm
- color.surface.raised
- space.inset.md
- color.border.default
- radius.card
- border.hairline
- color.surface.app
- radius.control
- color.surface.hover
- color.border.subtle
- space.inset.lg
- color.surface.canvas
- space.stack.xs
