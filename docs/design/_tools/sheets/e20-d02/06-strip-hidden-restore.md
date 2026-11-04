# E20-D02 / 06 strip-hidden-restore

File `E20-D02 boards`, page `E20-D02`; export `docs/design/E20/img/E20-D02-06-strip-hidden-restore.png`; sheet `06-strip-hidden-restore.json` (validated); theme dark.

Board 06 of 10 (§0 L69). Grid (0, 3200); 3280 x 1026 px; "page E20-D02 · board 06 · r1".

## Frames

- `SCR-030∕strip-AllRowsOff` (`SCR-030/strip-AllRowsOff`)
- `SCR-030∕strip-restore-menu` (`SCR-030/strip-restore-menu`)

## Validator and size

- `06-strip-hidden-restore.json: 0 errors, 0 warnings, 14 sections, 36375 bytes` (exit 0)
- 14 sections, 201 shapes, 36375 bytes

## Live checks (6)

- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y — never apply a generic re-centre
- root 'E20-D02 / 06 strip-hidden-restore' at (0, 3200): read back the name exactly after the first section call; size 3280 x 1026
- after touchTexts + relayout: the root's h 1026 is the measured max(column end, footer end) + 80
- frame 'SCR-030∕strip-AllRowsOff': read back 1280 x 800 at (80, 108); clip on, no child spills
- frame 'SCR-030∕strip-restore-menu': read back 1280 x 800 at (1440, 108); clip on, no child spills
- export docs/design/E20/img/E20-D02-06-strip-hidden-restore.png: record the board id and the PNG size

## Derivations (0)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (6)

- spec L60: "BTCUSDT"
- spec L53: "ETHUSDT"
- W-24 (§12 L403, PROPOSED (E20-D04)): "Deep Stats hidden."
- W-11 (§12 L390, PROPOSED): "Hide Deep Stats"
- W-23 (§12 L402, PROPOSED (E20-D04)): "Deep Stats shown."
- W-10 (§12 L389, PROPOSED): "Show Deep Stats"

## Copy gaps (5)

- "announced: polite, once": kit label, not E20-D02 copy — board-marker label
- "BTCUSDT · 1m": kit label, not E20-D02 copy — SCR-030's top bar (symbol and interval; the world's series)
- "Volume": kit label, not E20-D02 copy — SCR-030's volume sub-pane label
- "on press: the last row set and order return; focus returns to the chart pane's menu button": kit label, not E20-D02 copy — board-marker note
- "Deep Stats": kit label, not E20-D02 copy — the pane menu's group label

## Fallbacks (4)

- kit choice: board markers (announcements, accessible names, x(t) edges, notes) are drawn in a 1 px color.border.strong outline on color.surface.canvas, named 'board marker · …' — not product UI
- kit choice: candles are wireframe greys — body color.text.secondary (up bars outlined, down bars filled) and a 1 px wick; below a 4 px pitch the bar is its high-low rect only
- wireframe: the focus ring (E47-D04's, §6.3) is drawn as a 2 px color.text.primary outline (border.focus) outside the row or control, not color.focus.ring (a hue); E20-D03 binds the ring token in hi-fi
- kit choice: menus, the readout and the dialog are color.surface.overlay cards with a 1 px color.border.default outline

## Sources (3)

- spec docs/design/E20/E20-D02.md md5 40669dbd39cb28403fa89307f09dd676 at the boards PR (§0 L69); the ruling of record folded (BQ-0 … BQ-9); no hand-off file
- docs/design/E18/E18-D02.md md5 fd75a21fdc0b045c206182da712d94a8 (L124: the delta width floor 40 px, the collapse floor's seed, §4.1)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (tick and qty step: BTCUSDT 0.10 / 0.001, ETHUSDT 0.01 / 0.001)

## Tokens (26)

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
- border.focus
- color.surface.app
- type.ui.body
- color.surface.hover
- color.surface.overlay
- radius.card
- type.ui.heading-sm
- type.ui.label
- space.stack.sm
- space.inset.lg
