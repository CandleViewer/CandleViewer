# E20-D02 / 07 scr033-catalogue-reorder

File `E20-D02 boards`, page `E20-D02`; export `docs/design/E20/img/E20-D02-07-scr033-catalogue-reorder.png`; sheet `07-scr033-catalogue-reorder.json` (validated); theme dark.

Board 07 of 10 (§0 L70). Grid (6400, 3200); 3280 x 1934 px; "page E20-D02 · board 07 · r1".

## Frames

- `SCR-033∕catalogue` (`SCR-033/catalogue`)
- `SCR-033∕reorder-keyboard` (`SCR-033/reorder-keyboard`)
- `SCR-033∕row-menu` (`SCR-033/row-menu`)
- `SCR-033∕thresholds` (`SCR-033/thresholds`)

## Validator and size

- `07-scr033-catalogue-reorder.json: 0 errors, 144 warnings, 58 sections, 225973 bytes` (exit 0)
- 58 sections, 1230 shapes, 225973 bytes

## Live checks (8)

- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y — never apply a generic re-centre
- root 'E20-D02 / 07 scr033-catalogue-reorder' at (6400, 3200): read back the name exactly after the first section call; size 3280 x 1934
- after touchTexts + relayout: the root's h 1934 is the measured max(column end, footer end) + 80
- frame 'SCR-033∕catalogue': read back 1280 x 800 at (80, 108); clip on, no child spills
- frame 'SCR-033∕reorder-keyboard': read back 1280 x 800 at (1440, 108); clip on, no child spills
- frame 'SCR-033∕row-menu': read back 1280 x 800 at (80, 1016); clip on, no child spills
- frame 'SCR-033∕thresholds': read back 1280 x 800 at (1440, 1016); clip on, no child spills
- export docs/design/E20/img/E20-D02-07-scr033-catalogue-reorder.png: record the board id and the PNG size

## Derivations (0)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (22)

- spec L60: "BTCUSDT"
- spec L53: "ETHUSDT"
- W-22 (§12 L401, PROPOSED (E20-D04)): "Deep Stats rows updated: 5 rows."
- spec L1: "Deep Stats rows"
- spec L286: "Set: Global"
- spec L186: "Compact mode"
- spec L245: "Sparkline N"
- spec L245: "Thresholds on"
- spec L274: "Format"
- spec L19: "Sparkline"
- spec L19: "Threshold"
- spec L286: "No threshold"
- spec L34: "Apply"
- spec L55: "Cancel"
- W-11 (§12 L390, PROPOSED): "Hide Deep Stats"
- W-15 (§12 L394, E20.json:394): "Cumulative Delta moved to position 4 of 5"
- spec L278: "Alt+↑ / Alt+↓ to move"
- W-16 (§12 L395, CMP-056 (15:656)): "Already first."
- W-16 (§12 L395, CMP-056 (15:656)): "Already last."
- spec L20: "Move up"
- spec L20: "Move down"
- spec L202: "abs >"

## Copy gaps (8)

- "announced: polite, once, on Apply": kit label, not E20-D02 copy — board-marker label
- "BTCUSDT · 1m": kit label, not E20-D02 copy — SCR-030's top bar (symbol and interval; the world's series)
- "SCR-030 with the strip, inert behind the modal (drawn on boards 01–06)": kit label, not E20-D02 copy — board-marker label for the inert page
- "announced: polite, one live region in the dialog, replaced never queued, ≤ 1 a second": kit label, not E20-D02 copy — board-marker label
- "Move up, as heard (not on screen)": kit label, not E20-D02 copy — board-marker label
- "300 BTC: example, never a recommendation (MEMO OQ-3)": kit label, not E20-D02 copy — board-marker note
- "Comparison": kit label, not E20-D02 copy — the select's visible label
- "Bound": kit label, not E20-D02 copy — the field's visible label

## Fallbacks (5)

- kit choice: board markers (announcements, accessible names, x(t) edges, notes) are drawn in a 1 px color.border.strong outline on color.surface.canvas, named 'board marker · …' — not product UI
- the dialog's scrim is color.surface.overlay at opacity.scrim (validator WARN: a Tier-1 primitive) over the inert SCR-030 behind it
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the CMP-019 lock, the chevrons, the flag
- wireframe: the focus ring (E47-D04's, §6.3) is drawn as a 2 px color.text.primary outline (border.focus) outside the row or control, not color.focus.ring (a hue); E20-D03 binds the ring token in hi-fi
- kit choice: menus, the readout and the dialog are color.surface.overlay cards with a 1 px color.border.default outline

## Sources (3)

- spec docs/design/E20/E20-D02.md md5 416c1519e1e6169a55b74455131fe031 at the boards PR (§0 L70); the ruling of record folded (BQ-0 … BQ-9); no hand-off file
- docs/design/E18/E18-D02.md md5 fd75a21fdc0b045c206182da712d94a8 (L124: the delta width floor 40 px, the collapse floor's seed, §4.1)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (tick and qty step: BTCUSDT 0.10 / 0.001, ETHUSDT 0.01 / 0.001)

## Tokens (35)

- type.ui.caption
- color.text.tertiary
- color.text.primary
- space.stack.xs
- space.inset.sm
- color.surface.canvas
- color.border.strong
- border.hairline
- radius.control
- type.ui.heading-md
- color.text.secondary
- size.icon
- color.border.default
- type.ui.body
- radius.badge
- type.num.sm
- color.surface.sunken
- color.surface.selected
- size.icon.sm
- space.inset.xs
- space.inset.lg
- color.grid.line
- border.focus
- type.ui.body-strong
- space.button.paddingX
- color.surface.raised
- color.border.subtle
- color.surface.overlay
- radius.dialog
- opacity.scrim
- color.surface.app
- radius.card
- type.ui.heading-sm
- type.ui.label
- space.stack.sm
