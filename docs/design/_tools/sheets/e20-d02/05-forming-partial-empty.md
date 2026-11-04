# E20-D02 / 05 forming-partial-empty

File `E20-D02 boards`, page `E20-D02`; export `docs/design/E20/img/E20-D02-05-forming-partial-empty.png`; sheet `05-forming-partial-empty.json` (validated); theme dark.

Board 05 of 10 (§0 L68). Grid (25600, 0); 3280 x 1934 px; "page E20-D02 · board 05 · r1".

## Frames

- `SCR-030∕strip-forming` (`SCR-030/strip-forming`)
- `SCR-030∕strip-PartialHistory` (`SCR-030/strip-PartialHistory`)
- `SCR-030∕strip-Empty(no recording)` (`SCR-030/strip-Empty(no recording)`)

## Validator and size

- `05-forming-partial-empty.json: 0 errors, 1 warnings, 37 sections, 112002 bytes` (exit 0)
- 37 sections, 659 shapes, 112002 bytes

## Live checks (7)

- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y — never apply a generic re-centre
- root 'E20-D02 / 05 forming-partial-empty' at (25600, 0): read back the name exactly after the first section call; size 3280 x 1934
- after touchTexts + relayout: the root's h 1934 is the measured max(column end, footer end) + 80
- frame 'SCR-030∕strip-forming': read back 1280 x 800 at (80, 108); clip on, no child spills
- frame 'SCR-030∕strip-PartialHistory': read back 1280 x 800 at (1440, 108); clip on, no child spills
- frame 'SCR-030∕strip-Empty(no recording)': read back 1280 x 800 at (80, 1016); clip on, no child spills
- export docs/design/E20/img/E20-D02-05-forming-partial-empty.png: record the board id and the PNG size

## Derivations (1)

- the forming cell's accessible text: §3.6's neutral form + W-5's ", forming"

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (9)

- spec L60: "BTCUSDT"
- spec L53: "ETHUSDT"
- W-5 (§12 L384, PROPOSED (MEMO AD-3)): ", forming"
- W-1 (§12 L380, PROPOSED (BQ-6)): "Thresholds: Global"
- W-7 (§12 L386, 14:759): "forming"
- W-3 (§12 L382, PROPOSED (BQ-6)): "Strong"
- W-28 (§12 L407, PROPOSED (R-2)): "no order flow"
- W-8 (§12 L387, 14:762): "Order flow from 13:56; earlier bars from exchange klines"
- W-9 (§12 L388, PROPOSED): "No recorded order flow in this range"

## Copy gaps (7)

- "forming cell Delta % · 14:05 (not on screen)": kit label, not E20-D02 copy — board-marker label
- "BTCUSDT · 1m": kit label, not E20-D02 copy — SCR-030's top bar (symbol and interval; the world's series)
- "Volume": kit label, not E20-D02 copy — SCR-030's volume sub-pane label
- "—": kit label, not E20-D02 copy — readout: no unit for count / ratio / flag rows
- "each empty cell left of the boundary (not on screen)": kit label, not E20-D02 copy — board-marker label
- "announced: polite, once (role="status")": kit label, not E20-D02 copy — board-marker label
- "each empty cell (not on screen)": kit label, not E20-D02 copy — board-marker label

## Fallbacks (6)

- kit choice: board markers (announcements, accessible names, x(t) edges, notes) are drawn in a 1 px color.border.strong outline on color.surface.canvas, named 'board marker · …' — not product UI
- kit choice: candles are wireframe greys — body color.text.secondary (up bars outlined, down bars filled) and a 1 px wick; below a 4 px pitch the bar is its high-low rect only
- wireframe: the breach shade (hi-fi E20-D03) is drawn as a color.surface.selected cell fill named 'shade slot (hi-fi E20-D03)'; the greyscale frame removes it
- wireframe: the breach-glyph slot is an 8 × 8 outlined square (color.text.primary hairline) — a shape distinct from both sign glyphs ▲ / ▼; its form is E20-D03's
- kit choice: menus, the readout and the dialog are color.surface.overlay cards with a 1 px color.border.default outline
- wireframe: the focus ring (E47-D04's, §6.3) is drawn as a 2 px color.text.primary outline (border.focus) outside the row or control, not color.focus.ring (a hue); E20-D03 binds the ring token in hi-fi

## Sources (3)

- spec docs/design/E20/E20-D02.md md5 416c1519e1e6169a55b74455131fe031 at the boards PR (§0 L68); the ruling of record folded (BQ-0 … BQ-9); no hand-off file
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
- type.ui.label
- space.inset.xs
- color.surface.overlay
- radius.card
- color.surface.app
- border.focus
- type.ui.body
- type.ui.heading-sm
- space.stack.sm
- space.inset.lg
