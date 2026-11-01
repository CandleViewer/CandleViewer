# E08-D10 / 01 backfill-in-progress

File `E08-D10 boards`, page `E08-D10 SCR-151 empty and backfill states`; export `docs/design/E08/img/E08-D10-01-backfill-in-progress.png`; sheet `01-backfill-in-progress.json` (validated); theme dark.

Board 01 of nine (§0 L81: the full-panel block with a known target (CMP-023) and an unknown one (CMP-038 words); the in-context chip and words over loaded rows; the cut on completion). Grid (0, 0); 3280 x 1878 px; "page E08-D10 SCR-151 empty and backfill states · board 01 · r1".

## Frames

- `SCR-151∕backfill∕known-target · dark` (§H `SCR-151/backfill/known-target · dark`)
- `SCR-151∕backfill∕open-target · dark` (§H `SCR-151/backfill/open-target · dark`)
- `SCR-151∕backfill∕in-context · dark` (§H `SCR-151/backfill/in-context · dark`)
- `SCR-151∕backfill∕cut · dark` (§H `SCR-151/backfill/cut · dark`)

## Validator and size

- `01-backfill-in-progress.json: 0 errors, 7 warnings, 60 sections, 141412 bytes` (exit 0)
- 60 sections, 141412 bytes

## Live checks (7)

- root 'E08-D10 / 01 backfill-in-progress' at (0, 0): read back the name exactly after the first section call; size 3280 x 1878
- after touchTexts + relayout: the annotation column (estimated 1086 px) ends inside the root (h 1878); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-151∕backfill∕known-target · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-151∕backfill∕open-target · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-151∕backfill∕in-context · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'SCR-151∕backfill∕cut · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- export docs/design/E08/img/E08-D10-01-backfill-in-progress.png: every frame is 1280 x 800; record the board id and the PNG size

## Derivations (4)

- bar fill 141 of 432 px = 1 600 / 4 896 bars
- W-3: 1 600 loaded of 4 896 = 17 days × 288 bars a day (5 min bars; 'about': the target is days over the interval, §3)
- W-4 / W-7: 1 600 bars back from the 10:35 UTC bar of 2026-08-23 reach 2026-08-17 21:20 UTC (1 600 × 5 min)
- W-3: 3 200 loaded of 4 896 = 17 days × 288 bars a day (5 min bars; 'about': the target is days over the interval, §3)

## Spec gaps (0)

## Deviations (0)

## Copy keys (5)

- W-1 history.backfill.heading (§13 L354; verbatim; key PROPOSED, the chip keeps c)
- W-2 history.backfill.cause (§13 L355; PROPOSED)
- W-3 history.backfill.value_known (§13 L356; PROPOSED; the ticket's words, capitalise)
- W-4 history.backfill.value_open (§13 L357; PROPOSED)
- W-5 history.backfill.loaded (§13 L358; verbatim words; key PROPOSED, E16-D05's )

## Copy gaps (7)

- "Show coverage": the link's words, spec L125 (CMP-021 → SCR-103; no W-id)
- panel title "Bars BTCUSDT 5 minutes": §10.1 L287's naming example (kind · symbol · interval spelled out)
- column headers time · open · high · low · close · volume: D04E11 L784
- "PROPOSED fields (D10-G1), not shipped": R-7 L127 ("say so on their face and are never shown as shipped"); no deck string
- "{n} bars loaded": E11-D04 L322's caption form "0 bars loaded" with the frame's count
- "visually hidden": the hidden-string marker label (E16-D05 kit form; no deck string)
- board footer "Data: a seeded synthetic history (seed 178), not recorded": hand-off §H L93 ("declared synthetic on every board's face")

## G rows (0)

## Fallbacks (5)

- kit choice: the E10 chrome (TopBar, NavRail, RightRail, StatusBar) drawn as neutral placeholders, the E08-D09 kit's geometry; only the host panel is this spec's (§0: one host panel per window)
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- fallback: CMP-038's spinner (no spinner icon in the local set) drawn as a 12 px ellipse outline in color.text.secondary, border.thick; static (reduced motion, §10.1)
- kit choice: the backfilling chip's glyph is the local icon 'pending', §3's block glyph
- kit choice: a visually hidden string drawn for the board as caption text in a dashed outline (the words a screen reader hears; not on screen in the product)

## Sources (7)

- spec E08-D10.md md5 6edf1ad0 and hand-off md5 d1e97ea3 (§0 L81, §H L97, §3-§7, §10-§13)
- docs/design/E11/E11-D04.md md5 02f3ff69
- docs/design/E22/E22-D02.md md5 9acb071a
- docs/design/E22/E22-D03.md md5 858221c5
- docs/design/E08/E08-D02.md md5 35c1af94
- docs/design/E08/E08-D04.md md5 ceff9775
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (37)

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
- border.thick
- color.data-confidence.backfilling.indicator
- color.data-confidence.backfilling.text
- color.border.strong
- color.surface.sunken
- color.surface.canvas
