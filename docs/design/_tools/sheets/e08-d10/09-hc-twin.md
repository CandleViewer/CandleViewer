# E08-D10 / 09 hc-twin

File `E08-D10 boards`, page `E08-D10 SCR-151 empty and backfill states`; export `docs/design/E08/img/E08-D10-09-hc-twin.png`; sheet `09-hc-twin.json` (validated); theme hc.

Board 09 of nine (§0 L89: high-contrast twin of 01's bar and 03's hole row). Grid (18000, 3200); 3280 x 998 px; "page E08-D10 SCR-151 empty and backfill states · board 09 · r1".

## Frames

- `SCR-151∕backfill∕known-target · hc` (§H `SCR-151/backfill/known-target · hc`)
- `SCR-151∕gap∕hole-row · hc` (§H `SCR-151/gap/hole-row · hc`)

## Validator and size

- `09-hc-twin.json: 0 errors, 3 warnings, 32 sections, 74378 bytes` (exit 0)
- 32 sections, 74378 bytes

## Live checks (6)

- root 'E08-D10 / 09 hc-twin' at (18000, 3200): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the annotation column (estimated 750 px) ends inside the root (h 998); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-151∕backfill∕known-target · hc': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-151∕gap∕hole-row · hc': read back 1280 x 800 at (1440, 80); clip on, no child spills
- theme: activate the hc token set before exporting board 09; read back one bound fill (color.surface.raised) as the hc value
- export docs/design/E08/img/E08-D10-09-hc-twin.png: every frame is 1280 x 800; record the board id and the PNG size

## Derivations (3)

- bar fill 141 of 432 px = 1 600 / 4 896 bars
- W-3: 1 600 loaded of 4 896 = 17 days × 288 bars a day (5 min bars; 'about': the target is days over the interval, §3)
- hole 09:30–10:00 UTC: 6 bars of 5 min missing = 30 min; the rows around it open 09:25 and 10:00

## Spec gaps (0)

## Deviations (0)

## Copy keys (4)

- W-1 history.backfill.heading (§13 L354; verbatim; key PROPOSED, the chip keeps c)
- W-2 history.backfill.cause (§13 L355; PROPOSED)
- W-3 history.backfill.value_known (§13 L356; PROPOSED; the ticket's words, capitalise)
- W-13 gap.band.kline_hole (§13 L366; verbatim)

## Copy gaps (6)

- "Show coverage": the link's words, spec L125 (CMP-021 → SCR-103; no W-id)
- panel title "Bars BTCUSDT 5 minutes": §10.1 L287's naming example (kind · symbol · interval spelled out)
- column headers time · open · high · low · close · volume: D04E11 L784
- "PROPOSED fields (D10-G1), not shipped": R-7 L127 ("say so on their face and are never shown as shipped"); no deck string
- "{n} bars loaded": E11-D04 L322's caption form "0 bars loaded" with the frame's count
- board footer "Data: a seeded synthetic history (seed 178), not recorded": hand-off §H L93 ("declared synthetic on every board's face")

## G rows (0)

## Fallbacks (2)

- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders, the E08-D09 kit's geometry; only the host panel is this spec's (§0: one host panel per window)
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)

## Sources (7)

- spec E08-D10.md md5 6edf1ad0 and hand-off md5 d1e97ea3 (§0 L89, §H L105, §3-§7, §10-§13)
- docs/design/E11/E11-D04.md md5 02f3ff69
- docs/design/E22/E22-D02.md md5 9acb071a
- docs/design/E22/E22-D03.md md5 858221c5
- docs/design/E08/E08-D02.md md5 35c1af94
- docs/design/E08/E08-D04.md md5 ceff9775
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (32)

- radius.badge
- color.surface.hover
- color.action.primary.default
- type.ui.body
- color.text.link
- type.ui.heading-sm
- color.text.primary
- color.text.tertiary
- size.icon.lg
- color.text.secondary
- type.ui.caption
- space.stack.xs
- space.stack.sm
- space.inset.sm
- space.stack.md
- space.inset.xl
- type.ui.label
- space.inset.xs
- type.num.sm
- color.surface.raised
- space.inset.md
- color.border.default
- radius.card
- border.hairline
- color.surface.app
- radius.control
- color.border.subtle
- space.inset.lg
- color.status.info.strong
- size.icon.sm
- color.status.info.subtle
- color.surface.canvas
