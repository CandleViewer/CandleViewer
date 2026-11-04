# E20-D02 / 08 scr033-validation-source-unavailable

File `E20-D02 boards`, page `E20-D02`; export `docs/design/E20/img/E20-D02-08-scr033-validation-source-unavailable.png`; sheet `08-scr033-validation-source-unavailable.json` (validated); theme dark.

Board 08 of 10 (§0 L71). Grid (12800, 3200); 3280 x 1934 px; "page E20-D02 · board 08 · r1".

## Frames

- `SCR-033∕no-row-selected` (`SCR-033/no-row-selected`)
- `SCR-033∕threshold-invalid` (`SCR-033/threshold-invalid`)
- `SCR-033∕source-unavailable` (`SCR-033/source-unavailable`)
- `SCR-033∕view-as` (`SCR-033/view-as`)

## Validator and size

- `08-scr033-validation-source-unavailable.json: 0 errors, 131 warnings, 58 sections, 214759 bytes` (exit 0)
- 58 sections, 1167 shapes, 214759 bytes

## Live checks (8)

- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y — never apply a generic re-centre
- root 'E20-D02 / 08 scr033-validation-source-unavailable' at (12800, 3200): read back the name exactly after the first section call; size 3280 x 1934
- after touchTexts + relayout: the root's h 1934 is the measured max(column end, footer end) + 80
- frame 'SCR-033∕no-row-selected': read back 1280 x 800 at (80, 108); clip on, no child spills
- frame 'SCR-033∕threshold-invalid': read back 1280 x 800 at (1440, 108); clip on, no child spills
- frame 'SCR-033∕source-unavailable': read back 1280 x 800 at (80, 1016); clip on, no child spills
- frame 'SCR-033∕view-as': read back 1280 x 800 at (1440, 1016); clip on, no child spills
- export docs/design/E20/img/E20-D02-08-scr033-validation-source-unavailable.png: record the board id and the PNG size

## Derivations (0)

## Decisions (1)

- OI Δ's source is absent for the synthetic BTCUSDT session on this frame (the state is the source's absence; no real symbol is claimed to lack open interest)

## Spec gaps (0)

## Deviations (0)

## Copy keys (21)

- spec L60: "BTCUSDT"
- spec L53: "ETHUSDT"
- W-12 (§12 L390, PROPOSED (MEMO C10)): "Select at least one row. To remove the strip, use Hide Deep Stats."
- spec L1: "Deep Stats rows"
- spec L285: "Set: Global"
- spec L185: "Compact mode"
- spec L244: "Sparkline N"
- spec L244: "Thresholds on"
- spec L273: "Format"
- spec L19: "Sparkline"
- spec L19: "Threshold"
- spec L285: "No threshold"
- spec L34: "Apply"
- spec L55: "Cancel"
- W-11 (§12 L389, PROPOSED): "Hide Deep Stats"
- spec L201: "abs >"
- W-29 (§12 L407, PROPOSED (E20-S03 bounds)): "Delta: enter a number in BTC."
- W-13 (§12 L391, PROPOSED): "Delta %: enter a value from 0 to 100 %."
- W-14 (§12 L392, PROPOSED (MEMO G8)): "No open-interest data for this symbol."
- spec L105: "deepstats.source_unavailable"
- W-17 (§12 L395, E09-D09:95): "Read-only while viewing as Manager 01."

## Copy gaps (9)

- "announced: polite, once, on the last uncheck (role="status")": kit label, not E20-D02 copy — board-marker label
- "BTCUSDT · 1m": kit label, not E20-D02 copy — SCR-030's top bar (symbol and interval; the world's series)
- "SCR-030 with the strip, inert behind the modal (drawn on boards 01–06)": kit label, not E20-D02 copy — board-marker label for the inert page
- "4o0": kit label, not E20-D02 copy — a synthetic mistyped entry (not a number)
- "Comparison": kit label, not E20-D02 copy — the select's visible label
- "Bound": kit label, not E20-D02 copy — the field's visible label
- "the checkbox, as heard (not on screen)": kit label, not E20-D02 copy — board-marker label
- "announced: polite, once, when Space re-shows it": kit label, not E20-D02 copy — board-marker label
- "Apply, as heard (not on screen)": kit label, not E20-D02 copy — board-marker label

## Fallbacks (4)

- kit choice: board markers (announcements, accessible names, x(t) edges, notes) are drawn in a 1 px color.border.strong outline on color.surface.canvas, named 'board marker · …' — not product UI
- the dialog's scrim is color.surface.overlay at opacity.scrim (validator WARN: a Tier-1 primitive) over the inert SCR-030 behind it
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the CMP-019 lock, the chevrons, the flag
- wireframe: the focus ring (E47-D04's, §6.3) is drawn as a 2 px color.text.primary outline (border.focus) outside the row or control, not color.focus.ring (a hue); E20-D03 binds the ring token in hi-fi

## Sources (3)

- spec docs/design/E20/E20-D02.md md5 e252dfbc3ddbb75528df27d70abee7dd at the boards PR (§0 L71); the ruling of record folded (BQ-0 … BQ-9); no hand-off file
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
- type.ui.body-strong
- space.button.paddingX
- color.surface.raised
- color.border.subtle
- color.surface.overlay
- radius.dialog
- opacity.scrim
- color.surface.app
- border.thick
- border.focus
- type.ui.heading-sm
- type.ui.label
- space.stack.sm
