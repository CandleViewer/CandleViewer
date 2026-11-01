# E47-D04 / 10 ring-hc-thick

File `E47-D04 boards`, page `E47-D04 — Focus model`; export `docs/design/E47/img/E47-D04-10-ring-hc-thick.png`; sheet `10-ring-hc-thick.json` (validated); theme hc.

Board 10 of ten (§0 L80: high-contrast twin of 08 with the thick geometry (§7.3)). Grid (24000, 3200); 3280 x 998 px; "page E47-D04 — Focus model · board 10 · r1".

## Frames

- `ring∕thick-hc · hc`
- `ring∕backgrounds · hc`

## Validator and size

- `10-ring-hc-thick.json: 0 errors, 0 warnings, 14 sections, 51263 bytes` (exit 0)
- 14 sections, 51263 bytes

## Live checks (6)

- root 'E47-D04 / 10 ring-hc-thick' at (24000, 3200): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the annotation column (estimated 816 px) ends inside the root (h 998); set the root's h to max(column end, footer end) + 80
- frame 'ring∕thick-hc · hc': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'ring∕backgrounds · hc': read back 1280 x 800 at (1440, 80); clip on, no child spills
- theme: activate the hc token set before exporting board 10 (twin of 08); read back one bound fill (color.surface.canvas) as the hc value
- export docs/design/E47/img/E47-D04-10-ring-hc-thick.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (3)

- D04-G2 (§18.2 L456): "always-show focus ring" (14:2471) has no preference in the shipped model
- D04-G5 (§18.2 L459): border.focus.thick is not a token
- D04-G1 (§18.2 L455): the ring–halo pair is under 9:1 in dark and light, so the ring's 3:1 holds per measured background, not against any colour

## Spec gaps (0)

## Deviations (0)

## Copy keys (2)

- W-7 (§15 L383, verbatim (the shipped label))
- W-8 (§15 L384, verbatim (the shipped help))

## Copy gaps (0)

## Fallbacks (1)

- fallback: the 3 px thick ring (PROPOSED border.focus.thick, D04-G5: not a token) drawn as two adjacent strokes in color.focus.ring, border.focus (2) + border.hairline (1)

## Sources (1)

- spec E47-D04.md md5 ec4172fe (§0 L80); hand-off E47-D04-handoff.md md5 7ffe0dc8 (§H L94); tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (43)

- type.ui.heading-sm
- color.text.primary
- color.text.on-action
- color.action.primary.default
- radius.badge
- color.border.default
- border.hairline
- type.ui.body-strong
- type.ui.caption
- color.text.secondary
- space.stack.xs
- space.inset.md
- space.stack.sm
- color.surface.canvas
- radius.card
- space.inset.xs
- space.button.paddingX
- radius.control
- color.action.secondary.default
- border.thick
- color.focus.ring
- border.focus
- color.surface.raised
- space.inset.lg
- type.ui.heading-md
- type.ui.body
- space.stack.lg
- color.surface.app
- color.heatmap.bid.5
- type.ui.label
- size.icon
- type.num.base
- space.inset.sm
- color.heatmap.ask.5
- color.cvd.heatmap.bid.5
- color.cvd.heatmap.ask.5
- color.heatmap.bid.1
- color.heatmap.ask.1
- color.heatmap.zero
- color.surface.selected
- color.buy.default
- color.sell.default
- color.text.tertiary
