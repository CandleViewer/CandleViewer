# E20-D02 / 03 narrow-bar-readout

File `E20-D02 boards`, page `E20-D02`; export `docs/design/E20/img/E20-D02-03-narrow-bar-readout.png`; sheet `03-narrow-bar-readout.json` (validated); theme dark.

Board 03 of 10 (§0 L66). Grid (12800, 0); 3280 x 1026 px; "page E20-D02 · board 03 · r1".

## Frames

- `SCR-030∕strip-NarrowBars-readout` (`SCR-030/strip-NarrowBars-readout`)
- `SCR-030∕strip-readout-overflow` (`SCR-030/strip-readout-overflow`)

## Validator and size

- `03-narrow-bar-readout.json: 0 errors, 12 warnings, 44 sections, 169626 bytes` (exit 0)
- 44 sections, 1011 shapes, 169626 bytes

## Live checks (6)

- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y — never apply a generic re-centre
- root 'E20-D02 / 03 narrow-bar-readout' at (12800, 0): read back the name exactly after the first section call; size 3280 x 1026
- after touchTexts + relayout: the root's h 1026 is the measured max(column end, footer end) + 80
- frame 'SCR-030∕strip-NarrowBars-readout': read back 1280 x 800 at (80, 108); clip on, no child spills
- frame 'SCR-030∕strip-readout-overflow': read back 1280 x 800 at (1440, 108); clip on, no child spills
- export docs/design/E20/img/E20-D02-03-narrow-bar-readout.png: record the board id and the PNG size

## Derivations (0)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (6)

- spec L60: "BTCUSDT"
- spec L53: "ETHUSDT"
- W-5 (§12 L383, PROPOSED (MEMO AD-3)): "Delta +36 BTC, buy side"
- W-1 (§12 L379, PROPOSED (BQ-6)): "Thresholds: Global"
- W-7 (§12 L385, 14:759): "forming"
- W-6 (§12 L384, 15:2598 pattern): "+n more · Alt+T"

## Copy gaps (4)

- "focused cell Delta · 14:01 (not on screen)": kit label, not E20-D02 copy — board-marker label
- "BTCUSDT · 1m": kit label, not E20-D02 copy — SCR-030's top bar (symbol and interval; the world's series)
- "Volume": kit label, not E20-D02 copy — SCR-030's volume sub-pane label
- "—": kit label, not E20-D02 copy — readout: no unit for count / ratio / flag rows

## Fallbacks (8)

- kit choice: board markers (announcements, accessible names, x(t) edges, notes) are drawn in a 1 px color.border.strong outline on color.surface.canvas, named 'board marker · …' — not product UI
- kit choice: candles are wireframe greys — body color.text.secondary (up bars outlined, down bars filled) and a 1 px wick; below a 4 px pitch the bar is its high-low rect only
- wireframe: the breach shade (hi-fi E20-D03) is drawn as a color.surface.selected cell fill named 'shade slot (hi-fi E20-D03)'; the greyscale frame removes it
- wireframe: the breach-glyph slot is an 8 × 8 outlined square (color.text.primary hairline) — a shape distinct from both sign glyphs ▲ / ▼; its form is E20-D03's
- wireframe: the focus ring (E47-D04's, §6.3) is drawn as a 2 px color.text.primary outline (border.focus) outside the row or control, not color.focus.ring (a hue); E20-D03 binds the ring token in hi-fi
- kit choice: menus, the readout and the dialog are color.surface.overlay cards with a 1 px color.border.default outline
- kit choice: Delta Divergence's flag is drawn with the local 'warning' glyph at size.icon.sm (the flag's form is E20-D03's); a false value leaves the glyph slot empty, its accessible text 'no divergence'
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the CMP-019 lock, the chevrons, the flag

## Sources (3)

- spec docs/design/E20/E20-D02.md md5 e252dfbc3ddbb75528df27d70abee7dd at the boards PR (§0 L66); the ruling of record folded (BQ-0 … BQ-9); no hand-off file
- docs/design/E18/E18-D02.md md5 fd75a21fdc0b045c206182da712d94a8 (L124: the delta width floor 40 px, the collapse floor's seed, §4.1)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (tick and qty step: BTCUSDT 0.10 / 0.001, ETHUSDT 0.01 / 0.001)

## Tokens (29)

- type.ui.caption
- color.text.tertiary
- color.text.primary
- space.stack.xs
- space.inset.sm
- color.surface.canvas
- color.border.strong
- border.hairline
- radius.control
- type.ui.body-strong
- color.border.default
- color.surface.raised
- color.text.secondary
- color.neutral.subtle
- color.grid.line
- size.icon
- border.thick
- type.num.xs
- color.surface.selected
- border.focus
- type.ui.label
- space.inset.xs
- color.surface.overlay
- radius.card
- color.surface.app
- size.icon.sm
- type.ui.heading-sm
- space.stack.sm
- space.inset.lg
