# E08-D10 / 08 light-twin

File `E08-D10 boards`, page `E08-D10 SCR-151 empty and backfill states`; export `docs/design/E08/img/E08-D10-08-light-twin.png`; sheet `08-light-twin.json` (validated); theme light.

Board 08 of nine (§0 L88: light twin of 02's throttled line, 03's hole row and 01's bar). Grid (12000, 3200); 4640 x 1129 px; "page E08-D10 SCR-151 empty and backfill states · board 08 · r1".

## Frames

- `SCR-151∕throttled∕in-context · light` (§H `SCR-151/throttled/in-context · light`)
- `SCR-151∕gap∕hole-row · light` (§H `SCR-151/gap/hole-row · light`)
- `SCR-151∕backfill∕known-target · light` (§H `SCR-151/backfill/known-target · light`)

## Validator and size

- `08-light-twin.json: 0 errors, 30 warnings, 56 sections, 133221 bytes` (exit 0)
- 56 sections, 133221 bytes

## Live checks (7)

- root 'E08-D10 / 08 light-twin' at (12000, 3200): read back the name exactly after the first section call; size 4640 x 1129
- after touchTexts + relayout: the annotation column (estimated 1042 px) ends inside the root (h 1129); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-151∕throttled∕in-context · light': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-151∕gap∕hole-row · light': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-151∕backfill∕known-target · light': read back 1280 x 800 at (2800, 80); clip on, no child spills
- theme: activate the light token set before exporting board 08; read back one bound fill (color.surface.raised) as the light value
- export docs/design/E08/img/E08-D10-08-light-twin.png: every frame is 1280 x 800; record the board id and the PNG size

## Derivations (5)

- W-4 / W-7: 3 200 bars back from the 10:35 UTC bar of 2026-08-23 reach 2026-08-12 08:00 UTC (3 200 × 5 min)
- tape: 24 synthetic prints in the 10:35 UTC bar, newest first; notional = price × size, rounded down to whole USDT
- hole 09:30–10:00 UTC: 6 bars of 5 min missing = 30 min; the rows around it open 09:25 and 10:00
- bar fill 141 of 432 px = 1 600 / 4 896 bars
- W-3: 1 600 loaded of 4 896 = 17 days × 288 bars a day (5 min bars; 'about': the target is days over the interval, §3)

## Spec gaps (0)

## Deviations (0)

## Copy keys (8)

- W-1 history.backfill.heading (§13 L354; verbatim; key PROPOSED, the chip keeps c)
- W-6 history.backfill.throttled (§13 L359; PROPOSED)
- W-4 history.backfill.value_open (§13 L357; PROPOSED)
- W-7 history.partial (§13 L360; PROPOSED; E16-D05's chip grammar)
- W-9 history.diagnostic.link (§13 L362; PROPOSED; Owner only)
- W-13 gap.band.kline_hole (§13 L366; verbatim)
- W-2 history.backfill.cause (§13 L355; PROPOSED)
- W-3 history.backfill.value_known (§13 L356; PROPOSED; the ticket's words, capitalise)

## Copy gaps (9)

- "Show coverage": the link's words, spec L125 (CMP-021 → SCR-103; no W-id)
- tape title "Tape BTCUSDT": E22-D03 L104 (SCR-053 header row)
- column headers Time · Price · Size · Notional · Side (taker): D02E22 L87
- side words Buy / Sell: E22-D02 L99 ("Buy / Sell, left-aligned")
- "PROPOSED fields (D10-G1), not shipped": R-7 L127 ("say so on their face and are never shown as shipped"); no deck string
- "{n} bars loaded": E11-D04 L322's caption form "0 bars loaded" with the frame's count
- panel title "Bars BTCUSDT 5 minutes": §10.1 L287's naming example (kind · symbol · interval spelled out)
- column headers time · open · high · low · close · volume: D04E11 L784
- board footer "Data: a seeded synthetic history (seed 178), not recorded": hand-off §H L93 ("declared synthetic on every board's face")

## G rows (0)

## Fallbacks (3)

- kit choice: the backfilling chip's glyph is the local icon 'pending', §3's block glyph
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders, the E08-D09 kit's geometry; only the host panel is this spec's (§0: one host panel per window)

## Sources (7)

- spec E08-D10.md md5 1b86f428 and hand-off md5 c6177822 (§0 L88, §H L104, §3-§7, §10-§13)
- docs/design/E11/E11-D04.md md5 02f3ff69
- docs/design/E22/E22-D02.md md5 9acb071a
- docs/design/E22/E22-D03.md md5 858221c5
- docs/design/E08/E08-D02.md md5 35c1af94
- docs/design/E08/E08-D04.md md5 ceff9775
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (36)

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
- color.text.secondary
- color.status.info.strong
- color.text.primary
- color.status.info.subtle
- type.ui.body
- color.text.link
- type.ui.label
- space.inset.md
- radius.card
- color.sell.default
- type.num.sm
- color.buy.default
- color.text.tertiary
- color.surface.app
- radius.control
- color.surface.hover
- color.border.subtle
- space.inset.lg
- color.action.primary.default
- type.ui.heading-sm
- size.icon.lg
- space.stack.xs
- space.stack.sm
- space.stack.md
- space.inset.xl
- color.surface.canvas
