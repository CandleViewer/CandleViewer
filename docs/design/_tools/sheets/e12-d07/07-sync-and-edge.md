# E12-D07 / 07 sync-and-edge

File `E12-D07 boards`, page `E12-D07 SCR-045 data table`; export `docs/design/E12/img/E12-D07-07-sync-and-edge.png`; sheet `07-sync-and-edge.json` (validated); theme dark.

Board 07 of ten (§0 L80: the crosshair before the loaded window: the first loaded row under its boundary row (§9.1); the stale banner naming a non-time bar (§9.1, W-22)). Grid (6000, 3200); 3280 x 2148 px; footer "page E12-D07 SCR-045 data table · board 07 · r1".

## Frames

- `SCR-045∕sync∕before-loaded · dark`
- `SCR-045∕sync∕stale-banner-non-time · dark`
- sources: spec §0 L80; §2.2 L132; §7.1 L249; §7.2 L267; §9.1 L286; §13 W-16 L359, W-22 L365, W-10 L353, W-11 L354; E11-D04 §7 L266, loading-older L325; hand-off §H L105
- theme dark; export docs/design/E12/img/E12-D07-07-sync-and-edge.png

## Validator and size

- `07-sync-and-edge.json: 0 errors, 85 warnings, 48 sections, 177594 bytes` (exit 0)
- 48 sections, 177594 bytes

## Live checks (8)

- frame 1: read back the band row "Loading older bars…" directly above the first bar row, the first bar row carrying the only 2 px color.focus.ring, and the footer's Older control
- frame 2: read back the banner text exactly "Data is for bar 10:22:11.412 bar 3 of 5, no longer in view — press Shift+R or Refresh to current" on one line, fill color.status.warning.subtle, h 32
- frame 2: read back the focused row's header "10:22:11.412 bar 3 of 5" with the 2 px ring
- root 'E12-D07 / 07 sync-and-edge' at (6000, 3200): read back the name exactly after the first section call (a mismatch makes a duplicate root); size 3280 x 2148
- after touchTexts + relayout: the annotation column (estimated 2244 px) ends inside the root (h 2148); raise the root's h if not
- frame 'SCR-045∕sync∕before-loaded · dark': read back 1280 x 800 at (80, 80) after relayout; no child overflows it (clip on)
- frame 'SCR-045∕sync∕stale-banner-non-time · dark': read back 1280 x 800 at (1440, 80) after relayout; no child overflows it (clip on)
- export docs/design/E12/img/E12-D07-07-sync-and-edge.png: the PNG's frames are each 1280 x 800 device px; record the board id and the PNG size

## Spec gaps (4)

- A-7: the chart is hidden while the table is open in place, so sync/before-loaded draws the table state only (first loaded row focused under the loading-older band) and states the trigger in the annotation
- the boundary row is the loading-older band because W-16 says "Loading older bars"; the hand-off allows lookback or loading-older
- the stale banner's polite announcement on a non-time series is not given verbatim by the spec (§9.1 names only the banner, W-22); the annotation applies E11-D04's form with the row header in place of the time, as W-22 does for the banner; not drawn
- A-8: rows come from a seeded synthetic stream; only tick size and qty step come from the fixture

## Deviations (0)

## Copy keys (5)

- W-10 (§13 L353, verbatim)
- W-11 (§13 L354, PROPOSED, the registry's unit)
- loading-older: E11-D04's band (D04E11:325), unchanged
- W-16 (§13 L359, PROPOSED)
- W-22 (§13 L365, PROPOSED)

## Copy gaps (0)

## Fallbacks (2)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the expander, check and sort glyphs
- fallback: color.text.buy / color.text.sell (E11-D04 CR-D04-2 = E11-D02 CR-5, unregistered) drawn as color.buy.default / color.sell.default; the sign (+ / −) is the carrier (D04E11 §5.4)

## Sources (1)

- spec E12-D07.md md5 561a7fee (§0 L80); hand-off §H; E11-D04 §2, §5, §6, §10 (md5 02f3ff69); E12-D04 board kit (chrome geometry)

## Tokens (34)

- type.ui.caption
- color.text.secondary
- color.surface.hover
- size.icon.sm
- type.num.sm
- color.text.primary
- space.inset.sm
- color.buy.default
- color.surface.canvas
- color.focus.ring
- border.focus
- color.surface.raised
- color.sell.default
- type.ui.label
- color.border.default
- border.hairline
- radius.control
- space.inset.xs
- color.text.tertiary
- space.stack.xs
- color.surface.selected
- size.icon
- color.env.demo
- radius.badge
- radius.card
- type.ui.heading-sm
- space.inset.lg
- space.inset.md
- color.surface.app
- color.surface.sunken
- color.status.warning.strong
- color.status.warning.subtle
- type.ui.body
- space.stack.sm
