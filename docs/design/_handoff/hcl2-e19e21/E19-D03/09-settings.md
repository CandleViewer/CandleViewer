# E19-D03 / 09 settings

File `E19-D03 boards`, page `E19-D03`; export `docs/design/E19/img/E19-D03-09-settings.png`; sheet `09-settings.json` (validated); theme light.

Board 09 of ten (§0 L82: SCR-039/compact-dark, SCR-039/compact-light, SCR-039/view-as-dark (T2 (§1.4): CMP-079, CMP-019 lock)). Grid (22800, 5600); 3280 x 1896 px; "page E19-D03 · board 09 · r1".

## Frames

- `SCR-039∕compact-dark` (dark, 1280 x 800)
- `SCR-039∕compact-light` (light, 1280 x 800)
- `SCR-039∕view-as-dark` (dark, 1280 x 800)

## Validator and size

- `09-settings.json: 0 errors, 79 warnings, 48 sections, 185461 bytes` (exit 0)
- 48 sections, 185461 bytes

## Live checks (9)

- root 'E19-D03 / 09 settings' at (22800, 5600): read back the name exactly after the first section call; size 3280 x 1896
- after touchTexts + relayout: the annotation column (estimated 993 px) ends inside the root (h 1896); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-039∕compact-dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-039∕compact-light': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-039∕view-as-dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- local tokens: create the sets of local-tokens.json ('E19-D03 local · dark', '· light', '· hc', each active only in its theme) before the first section call; color.tpo.letter and color.tpo.initialbalance bind them
- theme: activate the light token set (and 'E19-D03 local · light') before exporting board 09; read back one bound fill (color.surface.raised) as the light value
- export docs/design/E19/img/E19-D03-09-settings.png; record the board id and the PNG size
- kit reading R-K1: export board 09 a second time under the dark set as docs/design/E19/img/E19-D03-09-settings-dark.png; its '-dark' frames are read from that export, its '-light' frames from docs/design/E19/img/E19-D03-09-settings.png

## Readings (1)

- R-K3: the bracket's developing edge (no end cap, §7.2) is the value-area edge on the last price's side

## Derivations (1)

- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 438 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (58)

- D02 W-2: "Aligned to {symbol} · {interval}" (D02 L351) filled from the world
- W-10: "Developing · as of {HH:MM} UTC" (spec L391) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- "Period" (spec L261)
- "Session" (spec L263)
- "Input" (spec L9)
- "Volume" (spec L5)
- "VA%" (D02 L135)
- "Row" (spec L253)
- "VWAP" (spec L61)
- D02 W-29: "Histogram" (D02 L378)
- D02 W-29: "Table" (D02 L378)
- "Presets" (D02 L113)
- "Settings" (D02 L100)
- D02 W-19: "Row size: {n} ticks ({price})" (D02 L368) filled from the world
- "HVN" (spec L124)
- "LVN" (spec L124)
- "Single prints" (spec L200)
- W-2: "{k} hidden" (spec L383) filled from the world
- W-6: "Show tested" (spec L387)
- "BTCUSDT" (spec L62)
- "POC" (spec L5)
- "VAH" (spec L120)
- "VAL" (spec L120)
- "Fixed range" (spec L263)
- "Visible range" (spec L263)
- "Anchored" (spec L263)
- "Composite" (spec L263)
- "UTC day" (spec L241)
- "funding 8 h" (D02 L277)
- "custom HH:MM" (D02 L277)
- "One per session, side by side" (spec L263)
- "Rows and value area" (D02 L278)
- "Delta" (spec L217)
- "TPO" (spec L23)
- "Row size (ticks)" (D02 L278)
- "Value area %" (D02 L278)
- "Single step" (D02 L287)
- "Two-row TPO" (D02 L287)
- D02 W-28: "Single step: grows the value area one row at a time toward the heavier side." (D02 L377)
- "Levels and overlays" (D02 L279)
- "show developing value area" (D02 L279)
- "extend POC / VA lines to the right" (D02 L279)
- "HVN / LVN marking" (D02 L279)
- "naked POC, nearest N" (D02 L279)
- "VWAP ±1σ / ±2σ" (D02 L279)
- "TPO period" (D02 L280)
- "TPO letter size" (spec L249)
- "px" (spec L59)
- "initial balance periods" (D02 L280)
- "single prints" (spec L59)
- "Profile settings" (D02 L267)
- "Reset" (spec L349)
- "Cancel" (spec L349)
- "Save" (spec L108)
- D02 W-15: "Read-only while viewing as {user}." (D02 L364) filled from the world
- "Session value" (D02 L302)
- "Save preset…" (spec L108)

## Copy gaps (3)

- "30m": the bound chart's interval word (kit world: 30-minute bars), filling D02 W-2's {interval}
- "min": `22`:4879's unit
- "Sam": D02 W-15's {user}, a synthetic display name (the name other boards use)

## Fallbacks (3)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the chart beside the panel is a plain SCR-030 price pane (candles, grid, price axis) for alignment only
- opacity.scrim is a Tier-1 primitive (validator WARN); the CMP-078 stale shade and the dialog scrim use it

## Sources (4)

- spec E19-D03.md md5 928db4e4 and hand-off md5 fb2077ba (§0 L82; RULED comment 6580374205)
- D02 E19-D02.md md5 1299df3b at bed73afaa (read via git show bed73afaa; re-pinned when PR #5487 merges)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json + local-tokens.json (color.tpo.*, PROPOSED, §2.1)

## Tokens (44)

- type.ui.label
- color.text.primary
- type.ui.caption
- color.text.secondary
- size.icon.sm
- space.inset.sm
- space.inset.xs
- radius.control
- color.action.secondary.default
- color.border.default
- border.hairline
- type.num.sm
- color.surface.sunken
- color.surface.selected
- space.stack.xs
- color.surface.raised
- color.profile.valuearea
- color.surface.canvas
- type.num.xs
- color.tpo.letter
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.up
- color.candle.down
- color.profile.bar
- color.profile.poc
- opacity.scrim
- radius.badge
- color.border.strong
- color.text.on-action
- color.action.primary.default
- space.stack.sm
- type.ui.heading-sm
- space.inset.md
- space.inset.xl
- color.surface.overlay
- radius.dialog
- color.surface.app
- color.status.info.strong
- color.status.info.subtle
- color.text.tertiary
- radius.card
- space.inset.lg
