# E47-D04 / 09 ring-spec-light

File `E47-D04 boards`, page `E47-D04 — Focus model`; export `docs/design/E47/img/E47-D04-09-ring-spec-light.png`; sheet `09-ring-spec-light.json` (validated); theme light.

Board 09 of ten (§0 L79: light twin of 08). Grid (18000, 3200); 3280 x 998 px; "page E47-D04 — Focus model · board 09 · r1".

## Frames

- `ring∕geometry · light`
- `ring∕backgrounds · light`

## Validator and size

- `09-ring-spec-light.json: 0 errors, 0 warnings, 15 sections, 51994 bytes` (exit 0)
- 15 sections, 51994 bytes

## Live checks (6)

- root 'E47-D04 / 09 ring-spec-light' at (18000, 3200): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the annotation column (estimated 799 px) ends inside the root (h 998); set the root's h to max(column end, footer end) + 80
- frame 'ring∕geometry · light': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'ring∕backgrounds · light': read back 1280 x 800 at (1440, 80); clip on, no child spills
- theme: activate the light token set before exporting board 09 (twin of 08); read back one bound fill (color.surface.canvas) as the light value
- export docs/design/E47/img/E47-D04-09-ring-spec-light.png: every frame is 1280 x 800; record the board id and the PNG size

## G rows (3)

- D04-G5 (§18.2 L459): border.focus.thick is not a token
- D04-G6 (§18.2 L460): no forced-colors technique for the ring: a shadow halo is dropped under forced-colors: active
- D04-G1 (§18.2 L455): the ring–halo pair is under 9:1 in dark and light, so the ring's 3:1 holds per measured background, not against any colour

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (2)

- fallback: the 3 px thick ring (PROPOSED border.focus.thick, D04-G5: not a token) drawn as two adjacent strokes in color.focus.ring, border.focus (2) + border.hairline (1)
- fallback: border.panel.focus (= {border.focus}, `16`:88) is not in the token file: the inset panel frame is drawn as a border.focus inner stroke in color.focus.ring; the header bar as a 3 px color.focus.ring rect (border.thick + border.hairline, the `16`:88 composite)

## Sources (1)

- spec E47-D04.md md5 82406120 (§0 L79); hand-off E47-D04-handoff.md md5 d6454712 (§H L94); tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (40)

- type.ui.body-strong
- color.text.primary
- space.inset.xs
- space.button.paddingX
- radius.control
- color.action.secondary.default
- color.surface.canvas
- border.hairline
- color.focus.ring
- border.focus
- color.surface.raised
- radius.card
- type.ui.heading-sm
- type.ui.caption
- color.text.secondary
- space.stack.xs
- space.stack.sm
- space.inset.md
- color.border.default
- type.num.base
- space.inset.sm
- border.thick
- space.inset.lg
- type.ui.heading-md
- type.ui.body
- space.stack.lg
- color.surface.app
- color.heatmap.bid.5
- type.ui.label
- size.icon
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
