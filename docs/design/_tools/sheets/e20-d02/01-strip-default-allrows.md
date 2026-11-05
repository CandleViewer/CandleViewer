# E20-D02 / 01 strip-default-allrows

File `E20-D02 boards`, page `E20-D02`; export `docs/design/E20/img/E20-D02-01-strip-default-allrows.png`; sheet `01-strip-default-allrows.json` (validated); theme dark.

Board 01 of 10 (§0 L64). Grid (0, 0); 3280 x 1934 px; "page E20-D02 · board 01 · r1".

## Frames

- `SCR-030∕strip-Default` (`SCR-030/strip-Default`)
- `SCR-030∕strip-AllRows` (`SCR-030/strip-AllRows`)
- `SCR-030∕strip-WithSparklines` (`SCR-030/strip-WithSparklines`)
- `SCR-030∕strip-sparkline-guard` (`SCR-030/strip-sparkline-guard`)

## Validator and size

- `01-strip-default-allrows.json: 0 errors, 13 warnings, 61 sections, 240827 bytes` (exit 0)
- 61 sections, 1499 shapes, 240827 bytes

## Live checks (8)

- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y — never apply a generic re-centre
- root 'E20-D02 / 01 strip-default-allrows' at (0, 0): read back the name exactly after the first section call; size 3280 x 1934
- after touchTexts + relayout: the root's h 1934 is the measured max(column end, footer end) + 80
- frame 'SCR-030∕strip-Default': read back 1280 x 800 at (80, 108); clip on, no child spills
- frame 'SCR-030∕strip-AllRows': read back 1280 x 800 at (1440, 108); clip on, no child spills
- frame 'SCR-030∕strip-WithSparklines': read back 1280 x 800 at (80, 1016); clip on, no child spills
- frame 'SCR-030∕strip-sparkline-guard': read back 1280 x 800 at (1440, 1016); clip on, no child spills
- export docs/design/E20/img/E20-D02-01-strip-default-allrows.png: record the board id and the PNG size

## Derivations (0)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (6)

- spec L60: "BTCUSDT"
- spec L53: "ETHUSDT"
- W-1 (§12 L380, PROPOSED (BQ-6)): "Thresholds: Global"
- W-7 (§12 L386, 14:759): "forming"
- W-3 (§12 L382, PROPOSED (BQ-6)): "Strong"
- W-18 (§12 L397, PROPOSED): "Sparklines show for 3 rows (Cumulative Delta, Max Delta, Min Delta): more than 6 slow the chart."

## Copy gaps (3)

- "BTCUSDT · 1m": kit label, not E20-D02 copy — SCR-030's top bar (symbol and interval; the world's series)
- "Volume": kit label, not E20-D02 copy — SCR-030's volume sub-pane label
- "announced: polite, once": kit label, not E20-D02 copy — board-marker label

## Fallbacks (7)

- kit choice: candles are wireframe greys — body color.text.secondary (up bars outlined, down bars filled) and a 1 px wick; below a 4 px pitch the bar is its high-low rect only
- wireframe: the breach shade (hi-fi E20-D03) is drawn as a color.surface.selected cell fill named 'shade slot (hi-fi E20-D03)'; the greyscale frame removes it
- wireframe: the breach-glyph slot is an 8 × 8 outlined square (color.text.primary hairline) — a shape distinct from both sign glyphs ▲ / ▼; its form is E20-D03's
- kit choice: Delta Divergence's flag is drawn with the local 'warning' glyph at size.icon.sm (the flag's form is E20-D03's); a false value leaves the glyph slot empty, its accessible text 'no divergence'
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the CMP-019 lock, the chevrons, the flag
- kit choice: CMP-024 sparklines are drawn as N dots (2 × 2 rects) on a 48 × 16 slot (no polyline node in the sheet schema); the dots are the row's last N values, scaled to their own min and max
- kit choice: board markers (announcements, accessible names, x(t) edges, notes) are drawn in a 1 px color.border.strong outline on color.surface.canvas, named 'board marker · …' — not product UI

## Sources (3)

- spec docs/design/E20/E20-D02.md md5 558c4ba6afdb5eafb65d4ac6b2e922df at the boards PR (§0 L64); the ruling of record folded (BQ-0 … BQ-9); no hand-off file
- docs/design/E18/E18-D02.md md5 c18b4d41a6d91836a193cf5991a3adbf (L124: the delta width floor 40 px, the collapse floor's seed, §4.1)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (tick and qty step: BTCUSDT 0.10 / 0.001, ETHUSDT 0.01 / 0.001)

## Tokens (26)

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
- type.num.xs
- color.surface.selected
- color.surface.app
- size.icon.sm
- space.stack.xs
- space.inset.sm
- space.inset.md
- type.ui.heading-sm
- type.ui.label
- space.stack.sm
- space.inset.lg
