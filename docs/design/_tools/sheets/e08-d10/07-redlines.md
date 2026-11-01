# E08-D10 / 07 redlines

File `E08-D10 boards`, page `E08-D10 SCR-151 empty and backfill states`; export `docs/design/E08/img/E08-D10-07-redlines.png`; sheet `07-redlines.json` (validated); theme dark.

Board 07 of nine (§0 L87: the tokens of §11 on boards 01–03). Grid (6000, 3200); 1920 x 998 px; "page E08-D10 SCR-151 empty and backfill states · board 07 · r1".

## Frames

- `SCR-151∕redlines · dark` (§H `SCR-151/redlines · dark`)

## Validator and size

- `07-redlines.json: 0 errors, 2 warnings, 9 sections, 25131 bytes` (exit 0)
- 9 sections, 25131 bytes

## Live checks (4)

- root 'E08-D10 / 07 redlines' at (6000, 3200): read back the name exactly after the first section call; size 1920 x 998
- after touchTexts + relayout: the annotation column (estimated 345 px) ends inside the root (h 998); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-151∕redlines · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- export docs/design/E08/img/E08-D10-07-redlines.png: every frame is 1280 x 800; record the board id and the PNG size

## Derivations (5)

- hole 09:30–10:00 UTC: 6 bars of 5 min missing = 30 min; the rows around it open 09:25 and 10:00
- W-3: 3 200 loaded of 4 896 = 17 days × 288 bars a day (5 min bars; 'about': the target is days over the interval, §3)
- bar fill 141 of 432 px = 1 600 / 4 896 bars
- W-3: 1 600 loaded of 4 896 = 17 days × 288 bars a day (5 min bars; 'about': the target is days over the interval, §3)
- W-4 / W-7: 3 200 bars back from the 10:35 UTC bar of 2026-08-23 reach 2026-08-12 08:00 UTC (3 200 × 5 min)

## Spec gaps (0)

## Deviations (0)

## Copy keys (8)

- W-1 history.backfill.heading (§13 L354; verbatim; key PROPOSED, the chip keeps c)
- W-2 history.backfill.cause (§13 L355; PROPOSED)
- W-3 history.backfill.value_known (§13 L356; PROPOSED; the ticket's words, capitalise)
- W-4 history.backfill.value_open (§13 L357; PROPOSED)
- W-7 history.partial (§13 L360; PROPOSED; E16-D05's chip grammar)
- W-8 history.backfill.gave_up (§13 L361; verbatim; key PROPOSED)
- W-12 confidence.gapped (§13 L365; verbatim)
- W-13 gap.band.kline_hole (§13 L366; verbatim)

## Copy gaps (2)

- "Show coverage": the link's words, spec L125 (CMP-021 → SCR-103; no W-id)
- board footer "Data: a seeded synthetic history (seed 178), not recorded": hand-off §H L93 ("declared synthetic on every board's face")

## G rows (0)

## Fallbacks (5)

- kit choice: the backfilling chip's glyph is the local icon 'pending', §3's block glyph
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: the gapped chip's glyph is the 8 px indicator dot (E16-D05's CMP-239 composition)
- kit choice: redline callouts drawn as caption text joined to the specimen by a 1 px color.border.strong leader (board markers, not product UI)
- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders, the E08-D09 kit's geometry; only the host panel is this spec's (§0: one host panel per window)

## Sources (7)

- spec E08-D10.md md5 1b86f428 and hand-off md5 c6177822 (§0 L87, §H L103, §3-§7, §10-§13)
- docs/design/E11/E11-D04.md md5 02f3ff69
- docs/design/E22/E22-D02.md md5 9acb071a
- docs/design/E22/E22-D03.md md5 858221c5
- docs/design/E08/E08-D02.md md5 35c1af94
- docs/design/E08/E08-D04.md md5 ceff9775
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (39)

- type.ui.heading-sm
- color.text.primary
- type.ui.body
- color.text.secondary
- space.stack.sm
- color.data-confidence.backfilling.indicator
- size.icon.sm
- type.ui.caption
- color.data-confidence.backfilling.text
- color.surface.raised
- color.border.default
- border.hairline
- radius.badge
- space.inset.sm
- space.inset.xs
- color.surface.hover
- color.action.primary.default
- color.status.info.strong
- color.status.info.subtle
- type.ui.body-strong
- color.action.secondary.default
- space.button.paddingX
- radius.control
- color.focus.ring
- border.focus
- color.data-confidence.gapped.indicator
- color.data-confidence.gapped.text
- color.text.link
- color.border.strong
- space.stack.xs
- space.inset.lg
- space.stack.lg
- radius.card
- color.surface.app
- color.border.subtle
- space.inset.md
- type.ui.label
- color.text.tertiary
- color.surface.canvas
