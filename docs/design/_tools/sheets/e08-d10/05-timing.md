# E08-D10 / 05 timing

File `E08-D10 boards`, page `E08-D10 SCR-151 empty and backfill states`; export `docs/design/E08/img/E08-D10-05-timing.png`; sheet `05-timing.json` (validated); theme dark.

Board 05 of nine (§0 L85: the cache-hit timeline (data, no skeleton); the slow path from 0 to the treatment; the empty verdict on a definitive answer; the cuts). Grid (24000, 0); 4640 x 998 px; "page E08-D10 SCR-151 empty and backfill states · board 05 · r1".

## Frames

- `SCR-151∕timing∕cache-hit · dark` (§H `SCR-151/timing/cache-hit · dark`)
- `SCR-151∕timing∕slow-path · dark` (§H `SCR-151/timing/slow-path · dark`)
- `SCR-151∕timing∕definitive-empty · dark` (§H `SCR-151/timing/definitive-empty · dark`)

## Validator and size

- `05-timing.json: 0 errors, 6 warnings, 42 sections, 103113 bytes` (exit 0)
- 42 sections, 103113 bytes

## Live checks (6)

- root 'E08-D10 / 05 timing' at (24000, 0): read back the name exactly after the first section call; size 4640 x 998
- after touchTexts + relayout: the annotation column (estimated 564 px) ends inside the root (h 998); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-151∕timing∕cache-hit · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-151∕timing∕slow-path · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-151∕timing∕definitive-empty · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E08/img/E08-D10-05-timing.png: every frame is 1280 x 800; record the board id and the PNG size

## Derivations (2)

- timeline: the treatment at T-2 = 600 ms; samples at ≤ 1 Hz → 1600 ms and 2600 ms
- W-3: 3 200 loaded of 4 896 = 17 days × 288 bars a day (5 min bars; 'about': the target is days over the interval, §3)

## Spec gaps (0)

## Deviations (0)

## Copy keys (4)

- W-1 history.backfill.heading (§13 L354; verbatim; key PROPOSED, the chip keeps c)
- W-3 history.backfill.value_known (§13 L356; PROPOSED; the ticket's words, capitalise)
- W-10 empty.heading.history_starts (§13 L363; verbatim)
- W-11 empty.cause.recorded_only (§13 L364; verbatim)

## Copy gaps (5)

- "{n} bars loaded": E11-D04 L322's caption form "0 bars loaded" with the frame's count
- panel title "Bars BTCUSDT 5 minutes": §10.1 L287's naming example (kind · symbol · interval spelled out)
- column headers time · open · high · low · close · volume: D04E11 L784
- "PROPOSED fields (D10-G1), not shipped": R-7 L127 ("say so on their face and are never shown as shipped"); no deck string
- board footer "Data: a seeded synthetic history (seed 178), not recorded": hand-off §H L93 ("declared synthetic on every board's face")

## G rows (0)

## Fallbacks (3)

- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders, the E08-D09 kit's geometry; only the host panel is this spec's (§0: one host panel per window)
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: the backfilling chip's glyph is the local icon 'pending', §3's block glyph

## Sources (7)

- spec E08-D10.md md5 1b86f428 and hand-off md5 c6177822 (§0 L85, §H L101, §3-§7, §10-§13)
- docs/design/E11/E11-D04.md md5 02f3ff69
- docs/design/E22/E22-D02.md md5 9acb071a
- docs/design/E22/E22-D03.md md5 858221c5
- docs/design/E08/E08-D02.md md5 35c1af94
- docs/design/E08/E08-D04.md md5 ceff9775
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (33)

- type.ui.label
- color.text.primary
- space.inset.sm
- space.inset.md
- color.border.default
- color.surface.raised
- radius.card
- border.hairline
- type.ui.caption
- space.inset.xs
- type.num.sm
- color.text.tertiary
- color.text.secondary
- color.border.strong
- space.stack.xs
- color.surface.app
- radius.control
- color.surface.hover
- color.border.subtle
- space.inset.lg
- color.status.info.strong
- size.icon.sm
- color.status.info.subtle
- radius.badge
- color.data-confidence.backfilling.indicator
- color.data-confidence.backfilling.text
- type.ui.heading-sm
- size.icon.lg
- type.ui.body
- space.stack.sm
- space.stack.md
- space.inset.xl
- color.surface.canvas
