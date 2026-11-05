# E20-D02 / 09 scr045-delta-export

File `E20-D02 boards`, page `E20-D02`; export `docs/design/E20/img/E20-D02-09-scr045-delta-export.png`; sheet `09-scr045-delta-export.json` (validated); theme dark.

Board 09 of 10 (§0 L72). Grid (19200, 3200); 3280 x 1934 px; "page E20-D02 · board 09 · r1".

## Frames

- `SCR-045∕deepstats-columns` (`SCR-045/deepstats-columns`)
- `SCR-045∕exporting` (`SCR-045/exporting`)
- `SCR-045∕export-cancelled` (`SCR-045/export-cancelled`)

## Validator and size

- `09-scr045-delta-export.json: 0 errors, 2 warnings, 56 sections, 190310 bytes` (exit 0)
- 56 sections, 1250 shapes, 190310 bytes

## Live checks (7)

- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y — never apply a generic re-centre
- root 'E20-D02 / 09 scr045-delta-export' at (19200, 3200): read back the name exactly after the first section call; size 3280 x 1934
- after touchTexts + relayout: the root's h 1934 is the measured max(column end, footer end) + 80
- frame 'SCR-045∕deepstats-columns': read back 1280 x 800 at (80, 108); clip on, no child spills
- frame 'SCR-045∕exporting': read back 1280 x 800 at (1440, 108); clip on, no child spills
- frame 'SCR-045∕export-cancelled': read back 1280 x 800 at (80, 1016); clip on, no child spills
- export docs/design/E20/img/E20-D02-09-scr045-delta-export.png: record the board id and the PNG size

## Derivations (1)

- the job: 86,400 bars (kit: a 60-day 1m range) > the 50,000-bar job threshold; 40 % done when drawn

## Decisions (0)

## Spec gaps (1)

- §7.1 names only Delta and Cumulative Delta as not repeated, so Total Volume is added beside the existing vol column (the same number twice): for E20-S04 / D02-OQ3

## Deviations (0)

## Copy keys (8)

- spec L60: "BTCUSDT"
- spec L53: "ETHUSDT"
- spec L109: "Export CSV"
- W-7 (§12 L386, 14:759): "forming"
- W-25 (§12 L404, PROPOSED): "Exporting 86,400 bars."
- W-19 (§12 L398, PROPOSED (14:761 pattern)): "Exporting 86,400 bars: 40 %"
- spec L55: "Cancel"
- W-20 (§12 L399, PROPOSED): "Export cancelled. No file was saved."

## Copy gaps (12)

- "added after cvd, in strip order: Delta %, Total Volume, # Trades": kit label, not E20-D02 copy — board-marker note
- "BTCUSDT 1m · table view (visible range)": kit label, not E20-D02 copy — SCR-045's title (14:1093 sketch)
- "time": kit label, not E20-D02 copy — SCR-045's existing column (14:1097 sketch)
- "open": kit label, not E20-D02 copy — SCR-045's existing column (14:1097 sketch)
- "high": kit label, not E20-D02 copy — SCR-045's existing column (14:1097 sketch)
- "low": kit label, not E20-D02 copy — SCR-045's existing column (14:1097 sketch)
- "close": kit label, not E20-D02 copy — SCR-045's existing column (14:1097 sketch)
- "vol": kit label, not E20-D02 copy — SCR-045's existing column (14:1097 sketch)
- "delta": kit label, not E20-D02 copy — SCR-045's existing column (14:1097 sketch)
- "cvd": kit label, not E20-D02 copy — SCR-045's existing column (14:1097 sketch)
- "announced: polite, once, at start": kit label, not E20-D02 copy — board-marker label
- "announced: polite, once": kit label, not E20-D02 copy — board-marker label

## Fallbacks (3)

- kit choice: board markers (announcements, accessible names, x(t) edges, notes) are drawn in a 1 px color.border.strong outline on color.surface.canvas, named 'board marker · …' — not product UI
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the CMP-019 lock, the chevrons, the flag
- wireframe: the focus ring (E47-D04's, §6.3) is drawn as a 2 px color.text.primary outline (border.focus) outside the row or control, not color.focus.ring (a hue); E20-D03 binds the ring token in hi-fi

## Sources (3)

- spec docs/design/E20/E20-D02.md md5 558c4ba6afdb5eafb65d4ac6b2e922df at the boards PR (§0 L72); the ruling of record folded (BQ-0 … BQ-9); no hand-off file
- docs/design/E18/E18-D02.md md5 c18b4d41a6d91836a193cf5991a3adbf (L124: the delta width floor 40 px, the collapse floor's seed, §4.1)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (tick and qty step: BTCUSDT 0.10 / 0.001, ETHUSDT 0.01 / 0.001)

## Tokens (25)

- type.ui.caption
- color.text.primary
- space.stack.xs
- space.inset.sm
- color.surface.canvas
- color.border.strong
- border.hairline
- radius.control
- type.ui.body-strong
- space.button.paddingX
- color.border.default
- color.surface.raised
- type.ui.heading-sm
- color.text.secondary
- space.inset.xs
- type.num.xs
- color.surface.app
- color.text.tertiary
- size.icon.sm
- color.surface.sunken
- border.focus
- type.ui.body
- type.ui.label
- space.stack.sm
- space.inset.lg
