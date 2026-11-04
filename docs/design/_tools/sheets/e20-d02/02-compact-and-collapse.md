# E20-D02 / 02 compact-and-collapse

File `E20-D02 boards`, page `E20-D02`; export `docs/design/E20/img/E20-D02-02-compact-and-collapse.png`; sheet `02-compact-and-collapse.json` (validated); theme dark.

Board 02 of 10 (§0 L65). Grid (6400, 0); 3280 x 1026 px; "page E20-D02 · board 02 · r1".

## Frames

- `SCR-030∕strip-CompactMode` (`SCR-030/strip-CompactMode`)
- `SCR-030∕strip-NarrowBars` (`SCR-030/strip-NarrowBars`)

## Validator and size

- `02-compact-and-collapse.json: 0 errors, 1 warnings, 28 sections, 96780 bytes` (exit 0)
- 28 sections, 564 shapes, 96780 bytes

## Live checks (6)

- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y — never apply a generic re-centre
- root 'E20-D02 / 02 compact-and-collapse' at (6400, 0): read back the name exactly after the first section call; size 3280 x 1026
- after touchTexts + relayout: the root's h 1026 is the measured max(column end, footer end) + 80
- frame 'SCR-030∕strip-CompactMode': read back 1280 x 800 at (80, 108); clip on, no child spills
- frame 'SCR-030∕strip-NarrowBars': read back 1280 x 800 at (1440, 108); clip on, no child spills
- export docs/design/E20/img/E20-D02-02-compact-and-collapse.png: record the board id and the PNG size

## Derivations (1)

- pitch 1024 / 32 = 32 px < the 40 px seed floor: every cell collapses (§4.1)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (10)

- spec L60: "BTCUSDT"
- spec L53: "ETHUSDT"
- W-1 (§12 L380, PROPOSED (BQ-6)): "Thresholds: Global"
- W-7 (§12 L386, 14:759): "forming"
- W-3 (§12 L382, PROPOSED (BQ-6)): "Strong"
- W-5 (§12 L384, PROPOSED (MEMO AD-3)): "Delta +36 BTC, buy side"
- W-5 (§12 L384, PROPOSED (MEMO AD-3)): "Delta +68 BTC, buy side"
- W-5 (§12 L384, PROPOSED (MEMO AD-3)): ", forming"
- spec L427: "<=1.5 ms per frame"
- spec L427: "strip adds ≤2 ms per frame"

## Copy gaps (5)

- "row headers' accessible names (not on screen)": kit label, not E20-D02 copy — board-marker label
- "BTCUSDT · 1m": kit label, not E20-D02 copy — SCR-030's top bar (symbol and interval; the world's series)
- "Volume": kit label, not E20-D02 copy — SCR-030's volume sub-pane label
- "cell Delta · 14:01 (not on screen)": kit label, not E20-D02 copy — board-marker label
- "cell Delta · 14:05 (not on screen)": kit label, not E20-D02 copy — board-marker label

## Fallbacks (4)

- kit choice: board markers (announcements, accessible names, x(t) edges, notes) are drawn in a 1 px color.border.strong outline on color.surface.canvas, named 'board marker · …' — not product UI
- kit choice: candles are wireframe greys — body color.text.secondary (up bars outlined, down bars filled) and a 1 px wick; below a 4 px pitch the bar is its high-low rect only
- wireframe: the breach shade (hi-fi E20-D03) is drawn as a color.surface.selected cell fill named 'shade slot (hi-fi E20-D03)'; the greyscale frame removes it
- wireframe: the breach-glyph slot is an 8 × 8 outlined square (color.text.primary hairline) — a shape distinct from both sign glyphs ▲ / ▼; its form is E20-D03's

## Sources (3)

- spec docs/design/E20/E20-D02.md md5 416c1519e1e6169a55b74455131fe031 at the boards PR (§0 L65); the ruling of record folded (BQ-0 … BQ-9); no hand-off file
- docs/design/E18/E18-D02.md md5 fd75a21fdc0b045c206182da712d94a8 (L124: the delta width floor 40 px, the collapse floor's seed, §4.1)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (tick and qty step: BTCUSDT 0.10 / 0.001, ETHUSDT 0.01 / 0.001)

## Tokens (24)

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
- color.surface.app
- type.ui.heading-sm
- type.ui.label
- space.stack.sm
- space.inset.lg
