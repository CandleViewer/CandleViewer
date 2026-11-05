# E20-D02 / 10 alignment-3-zooms

File `E20-D02 boards`, page `E20-D02`; export `docs/design/E20/img/E20-D02-10-alignment-3-zooms.png`; sheet `10-alignment-3-zooms.json` (validated); theme dark.

Board 10 of 10 (§0 L73). Grid (25600, 3200); 3280 x 1934 px; "page E20-D02 · board 10 · r1".

## Frames

- `SCR-030∕strip-align-typical` (`SCR-030/strip-align-typical`)
- `SCR-030∕strip-align-dense` (`SCR-030/strip-align-dense`)
- `SCR-030∕strip-align-extreme` (`SCR-030/strip-align-extreme`)

## Validator and size

- `10-alignment-3-zooms.json: 0 errors, 1 warnings, 120 sections, 546758 bytes` (exit 0)
- 120 sections, 3181 shapes, 546758 bytes

## Live checks (8)

- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y — never apply a generic re-centre
- root 'E20-D02 / 10 alignment-3-zooms' at (25600, 3200): read back the name exactly after the first section call; size 3280 x 1934
- after touchTexts + relayout: the root's h 1934 is the measured max(column end, footer end) + 80
- frame 'SCR-030∕strip-align-typical': read back 1280 x 800 at (80, 108); clip on, no child spills
- frame 'SCR-030∕strip-align-dense': read back 1280 x 800 at (1440, 108); clip on, no child spills
- frame 'SCR-030∕strip-align-extreme': read back 1280 x 800 at (80, 1016); clip on, no child spills
- export docs/design/E20/img/E20-D02-10-alignment-3-zooms.png: record the board id and the PNG size
- 3181 shapes on this board (over 2,000): draw it in its section order and allow for the longer render

## Derivations (3)

- SCR-030/strip-align-typical: 128 visible bars over 1024 px = 8.00 px a bar (x(t) = 192 + i × 8.00)
- SCR-030/strip-align-dense: 400 visible bars over 1024 px = 2.56 px a bar (x(t) = 192 + i × 2.56)
- SCR-030/strip-align-extreme: 800 visible bars over 1024 px = 1.28 px a bar (x(t) = 192 + i × 1.28)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (7)

- spec L60: "BTCUSDT"
- spec L53: "ETHUSDT"
- W-1 (§12 L380, PROPOSED (BQ-6)): "Thresholds: Global"
- W-7 (§12 L386, 14:759): "forming"
- spec L314: "alignment is pixel-exact with the bar grid at all zoom levels"
- spec L427: "<=1.5 ms per frame"
- spec L427: "strip adds ≤2 ms per frame"

## Copy gaps (7)

- "BTCUSDT · 1m": kit label, not E20-D02 copy — SCR-030's top bar (symbol and interval; the world's series)
- "Volume": kit label, not E20-D02 copy — SCR-030's volume sub-pane label
- "x(13:02)": kit label, not E20-D02 copy — board-marker label
- "x(13:58)": kit label, not E20-D02 copy — board-marker label
- "volume sub-pane unchanged — columns not drawn at this density": kit label, not E20-D02 copy — kit drawing economy (board 10)
- "x(10:46)": kit label, not E20-D02 copy — board-marker label
- "x(07:26)": kit label, not E20-D02 copy — board-marker label

## Fallbacks (3)

- kit choice: candles are wireframe greys — body color.text.secondary (up bars outlined, down bars filled) and a 1 px wick; below a 4 px pitch the bar is its high-low rect only
- kit choice: below an 8 px pitch adjacent same-glyph collapsed cells are pixel-contiguous, so each run is drawn as one rect (pixel-equivalent); at 8 px and over every cell is its own glyph
- wireframe: the breach-glyph slot is an 8 × 8 outlined square (color.text.primary hairline) — a shape distinct from both sign glyphs ▲ / ▼; its form is E20-D03's

## Sources (3)

- spec docs/design/E20/E20-D02.md md5 558c4ba6afdb5eafb65d4ac6b2e922df at the boards PR (§0 L73); the ruling of record folded (BQ-0 … BQ-9); no hand-off file
- docs/design/E18/E18-D02.md md5 c18b4d41a6d91836a193cf5991a3adbf (L124: the delta width floor 40 px, the collapse floor's seed, §4.1)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (tick and qty step: BTCUSDT 0.10 / 0.001, ETHUSDT 0.01 / 0.001)

## Tokens (21)

- type.ui.body-strong
- color.text.primary
- color.border.default
- color.surface.raised
- color.surface.canvas
- color.text.secondary
- border.hairline
- color.neutral.subtle
- color.border.strong
- type.ui.caption
- color.grid.line
- size.icon
- radius.control
- border.thick
- color.text.tertiary
- color.surface.app
- type.ui.heading-sm
- type.ui.label
- space.stack.xs
- space.stack.sm
- space.inset.lg
