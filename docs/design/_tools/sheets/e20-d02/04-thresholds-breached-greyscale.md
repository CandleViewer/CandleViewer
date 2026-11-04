# E20-D02 / 04 thresholds-breached-greyscale

File `E20-D02 boards`, page `E20-D02`; export `docs/design/E20/img/E20-D02-04-thresholds-breached-greyscale.png`; sheet `04-thresholds-breached-greyscale.json` (validated); theme dark.

Board 04 of 10 (§0 L67). Grid (19200, 0); 3280 x 1947 px; "page E20-D02 · board 04 · r1".

## Frames

- `SCR-030∕strip-ThresholdsBreached` (`SCR-030/strip-ThresholdsBreached`)
- `SCR-030∕strip-ThresholdsBreached-greyscale` (`SCR-030/strip-ThresholdsBreached-greyscale`)
- `SCR-030∕strip-thresholds-symbol-set` (`SCR-030/strip-thresholds-symbol-set`)

## Validator and size

- `04-thresholds-breached-greyscale.json: 0 errors, 1 warnings, 38 sections, 138094 bytes` (exit 0)
- 38 sections, 818 shapes, 138094 bytes

## Live checks (7)

- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y — never apply a generic re-centre
- root 'E20-D02 / 04 thresholds-breached-greyscale' at (19200, 0): read back the name exactly after the first section call; size 3280 x 1947
- after touchTexts + relayout: the root's h 1947 is the measured max(column end, footer end) + 80
- frame 'SCR-030∕strip-ThresholdsBreached': read back 1280 x 800 at (80, 108); clip on, no child spills
- frame 'SCR-030∕strip-ThresholdsBreached-greyscale': read back 1280 x 800 at (1440, 108); clip on, no child spills
- frame 'SCR-030∕strip-thresholds-symbol-set': read back 1280 x 800 at (80, 1016); clip on, no child spills
- export docs/design/E20/img/E20-D02-04-thresholds-breached-greyscale.png: record the board id and the PNG size

## Derivations (0)

## Decisions (1)

- W-2 names ETHUSDT, so this frame charts the second synthetic series (ETHUSDT, seed 575); its set's Delta % bound 50 % is a placeholder labelled example (MEMO OQ-3)

## Spec gaps (0)

## Deviations (0)

## Copy keys (7)

- spec L60: "BTCUSDT"
- spec L53: "ETHUSDT"
- W-1 (§12 L380, PROPOSED (BQ-6)): "Thresholds: Global"
- W-7 (§12 L386, 14:759): "forming"
- W-3 (§12 L382, PROPOSED (BQ-6)): "Strong"
- W-4 (§12 L383, PROPOSED (MEMO AD-5)): "Delta % +55 %, buy side, strong: beyond threshold 50 %"
- W-2 (§12 L381, PROPOSED (BQ-6)): "Thresholds: ETHUSDT"

## Copy gaps (6)

- "accessible text, §3.6 (PROPOSED) (not on screen)": kit label, not E20-D02 copy — board-marker label
- "example": kit label, not E20-D02 copy — the placeholder bound label (MEMO OQ-3)
- "BTCUSDT · 1m": kit label, not E20-D02 copy — SCR-030's top bar (symbol and interval; the world's series)
- "Volume": kit label, not E20-D02 copy — SCR-030's volume sub-pane label
- "accessible text · Delta % 13:51 (not on screen)": kit label, not E20-D02 copy — board-marker label
- "ETHUSDT · 1m": kit label, not E20-D02 copy — SCR-030's top bar (symbol and interval; the world's series)

## Fallbacks (4)

- kit choice: board markers (announcements, accessible names, x(t) edges, notes) are drawn in a 1 px color.border.strong outline on color.surface.canvas, named 'board marker · …' — not product UI
- kit choice: candles are wireframe greys — body color.text.secondary (up bars outlined, down bars filled) and a 1 px wick; below a 4 px pitch the bar is its high-low rect only
- wireframe: the breach shade (hi-fi E20-D03) is drawn as a color.surface.selected cell fill named 'shade slot (hi-fi E20-D03)'; the greyscale frame removes it
- wireframe: the breach-glyph slot is an 8 × 8 outlined square (color.text.primary hairline) — a shape distinct from both sign glyphs ▲ / ▼; its form is E20-D03's

## Sources (3)

- spec docs/design/E20/E20-D02.md md5 40669dbd39cb28403fa89307f09dd676 at the boards PR (§0 L67); the ruling of record folded (BQ-0 … BQ-9); no hand-off file
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
