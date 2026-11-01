# E08-D10 / 02 backfill-throttled

File `E08-D10 boards`, page `E08-D10 SCR-151 empty and backfill states`; export `docs/design/E08/img/E08-D10-02-backfill-throttled.png`; sheet `02-backfill-throttled.json` (validated); theme dark.

Board 02 of nine (§0 L82: the throttled line with the Partial chip; the long wait; the give-up line with Retry; the Owner's link beside a Manager's frame without it). Grid (6000, 0); 3280 x 1878 px; "page E08-D10 SCR-151 empty and backfill states · board 02 · r1".

## Frames

- `SCR-151∕throttled∕in-context · dark` (§H `SCR-151/throttled/in-context · dark`)
- `SCR-151∕throttled∕long-wait · dark` (§H `SCR-151/throttled/long-wait · dark`)
- `SCR-151∕throttled∕gave-up · dark` (§H `SCR-151/throttled/gave-up · dark`)
- `SCR-151∕throttled∕owner-vs-manager · dark` (§H `SCR-151/throttled/owner-vs-manager · dark`)

## Validator and size

- `02-backfill-throttled.json: 0 errors, 38 warnings, 92 sections, 221594 bytes` (exit 0)
- 92 sections, 221594 bytes

## Live checks (7)

- root 'E08-D10 / 02 backfill-throttled' at (6000, 0): read back the name exactly after the first section call; size 3280 x 1878
- after touchTexts + relayout: the annotation column (estimated 1135 px) ends inside the root (h 1878); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-151∕throttled∕in-context · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-151∕throttled∕long-wait · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-151∕throttled∕gave-up · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'SCR-151∕throttled∕owner-vs-manager · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- export docs/design/E08/img/E08-D10-02-backfill-throttled.png: every frame is 1280 x 800; record the board id and the PNG size

## Derivations (2)

- W-4 / W-7: 3 200 bars back from the 10:35 UTC bar of 2026-08-23 reach 2026-08-12 08:00 UTC (3 200 × 5 min)
- tape: 24 synthetic prints in the 10:35 UTC bar, newest first; notional = price × size, rounded down to whole USDT

## Spec gaps (0)

## Deviations (0)

## Copy keys (6)

- W-1 history.backfill.heading (§13 L354; verbatim; key PROPOSED, the chip keeps c)
- W-6 history.backfill.throttled (§13 L359; PROPOSED)
- W-4 history.backfill.value_open (§13 L357; PROPOSED)
- W-7 history.partial (§13 L360; PROPOSED; E16-D05's chip grammar)
- W-9 history.diagnostic.link (§13 L362; PROPOSED; Owner only)
- W-8 history.backfill.gave_up (§13 L361; verbatim; key PROPOSED)

## Copy gaps (10)

- "Show coverage": the link's words, spec L125 (CMP-021 → SCR-103; no W-id)
- tape title "Tape BTCUSDT": E22-D03 L104 (SCR-053 header row)
- column headers Time · Price · Size · Notional · Side (taker): D02E22 L87
- side words Buy / Sell: E22-D02 L99 ("Buy / Sell, left-aligned")
- "PROPOSED fields (D10-G1), not shipped": R-7 L127 ("say so on their face and are never shown as shipped"); no deck string
- "{n} bars loaded": E11-D04 L322's caption form "0 bars loaded" with the frame's count
- panel title "Bars BTCUSDT 5 minutes": §10.1 L287's naming example (kind · symbol · interval spelled out)
- column headers time · open · high · low · close · volume: D04E11 L784
- session labels "Owner" / "Manager": §0 L82 ("the Owner's link beside a Manager's frame without it")
- board footer "Data: a seeded synthetic history (seed 178), not recorded": hand-off §H L93 ("declared synthetic on every board's face")

## G rows (0)

## Fallbacks (3)

- kit choice: the backfilling chip's glyph is the local icon 'pending', §3's block glyph
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders, the E08-D09 kit's geometry; only the host panel is this spec's (§0: one host panel per window)

## Sources (7)

- spec E08-D10.md md5 1b86f428 and hand-off md5 c6177822 (§0 L82, §H L98, §3-§7, §10-§13)
- docs/design/E11/E11-D04.md md5 02f3ff69
- docs/design/E22/E22-D02.md md5 9acb071a
- docs/design/E22/E22-D03.md md5 858221c5
- docs/design/E08/E08-D02.md md5 35c1af94
- docs/design/E08/E08-D04.md md5 ceff9775
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (35)

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
- type.ui.body-strong
- color.action.secondary.default
- space.button.paddingX
- type.ui.heading-sm
- space.stack.xs
- space.stack.sm
- color.surface.canvas
