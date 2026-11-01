# E08-D10 / 03 coverage-gap

File `E08-D10 boards`, page `E08-D10 SCR-151 empty and backfill states`; export `docs/design/E08/img/E08-D10-03-coverage-gap.png`; sheet `03-coverage-gap.json` (validated); theme dark.

Board 03 of nine (§0 L83: a populated panel with the gapped chip; a hole separator row with its cause; both together; precedence against stale). Grid (12000, 0); 3280 x 1878 px; "page E08-D10 SCR-151 empty and backfill states · board 03 · r1".

## Frames

- `SCR-151∕gap∕gapped · dark` (§H `SCR-151/gap/gapped · dark`)
- `SCR-151∕gap∕hole-row · dark` (§H `SCR-151/gap/hole-row · dark`)
- `SCR-151∕gap∕both · dark` (§H `SCR-151/gap/both · dark`)
- `SCR-151∕gap∕vs-stale · dark` (§H `SCR-151/gap/vs-stale · dark`)

## Validator and size

- `03-coverage-gap.json: 0 errors, 1 warnings, 103 sections, 225766 bytes` (exit 0)
- 103 sections, 225766 bytes

## Live checks (7)

- root 'E08-D10 / 03 coverage-gap' at (12000, 0): read back the name exactly after the first section call; size 3280 x 1878
- after touchTexts + relayout: the annotation column (estimated 886 px) ends inside the root (h 1878); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-151∕gap∕gapped · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-151∕gap∕hole-row · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-151∕gap∕both · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'SCR-151∕gap∕vs-stale · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- export docs/design/E08/img/E08-D10-03-coverage-gap.png: every frame is 1280 x 800; record the board id and the PNG size

## Derivations (2)

- hole 09:30–10:00 UTC: 6 bars of 5 min missing = 30 min; the rows around it open 09:25 and 10:00
- hole 08:50–09:05 UTC: 3 bars of 5 min missing = 15 min; the rows around it open 08:45 and 09:05

## Spec gaps (0)

## Deviations (0)

## Copy keys (3)

- W-12 confidence.gapped (§13 L365; verbatim)
- W-13 gap.band.kline_hole (§13 L366; verbatim)
- W-14 gap.table.row (§13 L367; verbatim)

## Copy gaps (7)

- "{n} bars loaded": E11-D04 L322's caption form "0 bars loaded" with the frame's count
- panel title "Bars BTCUSDT 5 minutes": §10.1 L287's naming example (kind · symbol · interval spelled out)
- column headers time · open · high · low · close · volume: D04E11 L784
- "Show coverage": the link's words, spec L125 (CMP-021 → SCR-103; no W-id)
- stale words "Stale 4s": E08-D04 L42 (the chip text, here in the panel's name only)
- "visually hidden": the hidden-string marker label (E16-D05 kit form; no deck string)
- board footer "Data: a seeded synthetic history (seed 178), not recorded": hand-off §H L93 ("declared synthetic on every board's face")

## G rows (0)

## Fallbacks (3)

- kit choice: the gapped chip's glyph is the 8 px indicator dot (E16-D05's CMP-239 composition)
- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders, the E08-D09 kit's geometry; only the host panel is this spec's (§0: one host panel per window)
- kit choice: a visually hidden string drawn for the board as caption text in a dashed outline (the words a screen reader hears; not on screen in the product)

## Sources (7)

- spec E08-D10.md md5 6edf1ad0 and hand-off md5 d1e97ea3 (§0 L83, §H L99, §3-§7, §10-§13)
- docs/design/E11/E11-D04.md md5 02f3ff69
- docs/design/E22/E22-D02.md md5 9acb071a
- docs/design/E22/E22-D03.md md5 858221c5
- docs/design/E08/E08-D02.md md5 35c1af94
- docs/design/E08/E08-D04.md md5 ceff9775
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (29)

- color.data-confidence.gapped.indicator
- type.ui.caption
- color.data-confidence.gapped.text
- color.surface.raised
- color.border.default
- border.hairline
- radius.badge
- space.inset.sm
- space.inset.xs
- type.ui.label
- color.text.primary
- space.inset.md
- radius.card
- type.num.sm
- color.text.tertiary
- color.text.secondary
- color.surface.app
- radius.control
- color.surface.hover
- color.border.subtle
- space.inset.lg
- type.ui.body
- color.text.link
- space.stack.xs
- color.border.strong
- color.surface.sunken
- type.ui.heading-sm
- space.stack.sm
- color.surface.canvas
