# E08-D10 / 06 keyboard-a11y

File `E08-D10 boards`, page `E08-D10 SCR-151 empty and backfill states`; export `docs/design/E08/img/E08-D10-06-keyboard-a11y.png`; sheet `06-keyboard-a11y.json` (validated); theme dark.

Board 06 of nine (§0 L86: focus order with the Partial chip's stop, the focus move on Retry, aria-valuetext, the status-region rows and their max_rate (§10)). Grid (0, 3200); 4640 x 998 px; "page E08-D10 SCR-151 empty and backfill states · board 06 · r1".

## Frames

- `SCR-151∕a11y∕focus-order · dark` (§H `SCR-151/a11y/focus-order · dark`)
- `SCR-151∕a11y∕retry-focus · dark` (§H `SCR-151/a11y/retry-focus · dark`)
- `SCR-151∕a11y∕status-rows · dark` (§H `SCR-151/a11y/status-rows · dark`)

## Validator and size

- `06-keyboard-a11y.json: 0 errors, 3 warnings, 56 sections, 134691 bytes` (exit 0)
- 56 sections, 134691 bytes

## Live checks (6)

- root 'E08-D10 / 06 keyboard-a11y' at (0, 3200): read back the name exactly after the first section call; size 4640 x 998
- after touchTexts + relayout: the annotation column (estimated 700 px) ends inside the root (h 998); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-151∕a11y∕focus-order · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-151∕a11y∕retry-focus · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-151∕a11y∕status-rows · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E08/img/E08-D10-06-keyboard-a11y.png: every frame is 1280 x 800; record the board id and the PNG size

## Derivations (2)

- W-4 / W-7: 3 200 bars back from the 10:35 UTC bar of 2026-08-23 reach 2026-08-12 08:00 UTC (3 200 × 5 min)
- W-3: 3 200 loaded of 4 896 = 17 days × 288 bars a day (5 min bars; 'about': the target is days over the interval, §3)

## Spec gaps (0)

## Deviations (0)

## Copy keys (16)

- W-4 history.backfill.value_open (§13 L357; PROPOSED)
- W-7 history.partial (§13 L360; PROPOSED; E16-D05's chip grammar)
- W-8 history.backfill.gave_up (§13 L361; verbatim; key PROPOSED)
- W-9 history.diagnostic.link (§13 L362; PROPOSED; Owner only)
- W-1 history.backfill.heading (§13 L354; verbatim; key PROPOSED, the chip keeps c)
- W-3 history.backfill.value_known (§13 L356; PROPOSED; the ticket's words, capitalise)
- W-18 history.backfill.failed (§13 L371; PROPOSED; the full-panel give-up heading)
- W-1 history.backfill.heading (§13 L354)
- W-5 history.backfill.loaded (§13 L358)
- W-6 history.backfill.throttled (§13 L359)
- W-8 history.backfill.gave_up (§13 L361)
- W-3 history.backfill.value_known (§13 L356)
- W-4 history.backfill.value_open (§13 L357)
- W-12 confidence.gapped (§13 L365)
- W-13 gap.band.kline_hole (§13 L366)
- W-14 gap.table.row (§13 L367)

## Copy gaps (7)

- "Show coverage": the link's words, spec L125 (CMP-021 → SCR-103; no W-id)
- "{n} bars loaded": E11-D04 L322's caption form "0 bars loaded" with the frame's count
- panel title "Bars BTCUSDT 5 minutes": §10.1 L287's naming example (kind · symbol · interval spelled out)
- column headers time · open · high · low · close · volume: D04E11 L784
- focus-stop labels "panel title", "Partial chip": §10.1 Focus order row (the stops by name)
- "visually hidden": the hidden-string marker label (E16-D05 kit form; no deck string)
- board footer "Data: a seeded synthetic history (seed 178), not recorded": hand-off §H L93 ("declared synthetic on every board's face")

## G rows (0)

## Fallbacks (5)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- kit choice: focus-order numbers drawn as 20 px numbered markers in color.focus.ring (board markers, not product UI)
- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders, the E08-D09 kit's geometry; only the host panel is this spec's (§0: one host panel per window)
- kit choice: the backfilling chip's glyph is the local icon 'pending', §3's block glyph
- kit choice: a visually hidden string drawn for the board as caption text in a dashed outline (the words a screen reader hears; not on screen in the product)

## Sources (7)

- spec E08-D10.md md5 6edf1ad0 and hand-off md5 d1e97ea3 (§0 L86, §H L102, §3-§7, §10-§13)
- docs/design/E11/E11-D04.md md5 02f3ff69
- docs/design/E22/E22-D02.md md5 9acb071a
- docs/design/E22/E22-D03.md md5 858221c5
- docs/design/E08/E08-D02.md md5 35c1af94
- docs/design/E08/E08-D04.md md5 ceff9775
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (38)

- color.status.info.strong
- size.icon.sm
- type.ui.caption
- color.text.primary
- color.status.info.subtle
- radius.badge
- space.inset.sm
- space.inset.xs
- color.focus.ring
- border.focus
- color.text.secondary
- type.ui.body-strong
- color.action.secondary.default
- space.button.paddingX
- radius.control
- type.ui.body
- color.text.link
- type.ui.label
- space.inset.md
- color.border.default
- color.surface.raised
- radius.card
- border.hairline
- type.num.sm
- color.text.tertiary
- color.text.on-action
- space.inset.lg
- color.surface.sunken
- color.surface.app
- color.surface.hover
- color.border.subtle
- color.data-confidence.backfilling.indicator
- color.data-confidence.backfilling.text
- space.stack.xs
- color.border.strong
- color.surface.canvas
- type.ui.heading-sm
- space.stack.sm
