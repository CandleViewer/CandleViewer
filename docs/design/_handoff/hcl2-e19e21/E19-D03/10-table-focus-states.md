# E19-D03 / 10 table-focus-states

File `E19-D03 boards`, page `E19-D03`; export `docs/design/E19/img/E19-D03-10-table-focus-states.png`; sheet `10-table-focus-states.json` (validated); theme dark.

Board 10 of ten (§0 L83: SCR-038/table-dark, SCR-038/focus-dark, SCR-038/no-history-sentence-dark, SCR-038/no-history-view-as-dark, SCR-038/load-failed-dark, SCR-038/stale-dark; the two no-history frames T2 (§1.4), sentence form (no CMP-079 control, no CMP-019 lock)). Grid (30400, 5600); 3280 x 2776 px; "page E19-D03 · board 10 · r1".

## Frames

- `SCR-038∕table-dark` (dark, 1280 x 800)
- `SCR-038∕focus-dark` (dark, 1280 x 800)
- `SCR-038∕no-history-sentence-dark` (dark, 1280 x 800)
- `SCR-038∕no-history-view-as-dark` (dark, 1280 x 800)
- `SCR-038∕load-failed-dark` (dark, 1280 x 800)
- `SCR-038∕stale-dark` (dark, 1280 x 800)

## Validator and size

- `10-table-focus-states.json: 0 errors, 45 warnings, 68 sections, 201249 bytes` (exit 0)
- 68 sections, 201249 bytes

## Live checks (10)

- root 'E19-D03 / 10 table-focus-states' at (30400, 5600): read back the name exactly after the first section call; size 3280 x 2776
- after touchTexts + relayout: the annotation column (estimated 1178 px) ends inside the root (h 2776); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'SCR-038∕table-dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-038∕focus-dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-038∕no-history-sentence-dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'SCR-038∕no-history-view-as-dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- frame 'SCR-038∕load-failed-dark': read back 1280 x 800 at (80, 1840); clip on, no child spills
- frame 'SCR-038∕stale-dark': read back 1280 x 800 at (1440, 1840); clip on, no child spills
- local tokens: create the sets of local-tokens.json ('E19-D03 local · dark', '· light', '· hc', each active only in its theme) before the first section call; color.tpo.letter and color.tpo.initialbalance bind them
- export docs/design/E19/img/E19-D03-10-table-focus-states.png; record the board id and the PNG size

## Readings (2)

- overlay bars: 30 % of the pane's plot width (365 px of 1216, §10.2 PROPOSED), from the pane's right edge toward the left; the price axis and its last-price label stay uncovered
- R-K3: the bracket's developing edge (no end cap, §7.2) is the value-area edge on the last price's side

## Derivations (1)

- world: BTCUSDT 30-minute bars from 10 Oct 00:00 UTC to 31 Oct 14:30 UTC, one walk seeded 438 (the issue number), prices at the fixture's tick 0.10, sizes at its qty step 0.001; recorded trades from 12 Oct 09:00 UTC (bars only before: approximated); no data 13 Oct 04:00–06:00 UTC; one stop-run print cluster per session; row size 100 ticks unless a frame says otherwise

## Spec gaps (0)

## Deviations (0)

## Copy keys (50)

- D02 §3.2: "Profile · Visible range ▾ · Volume ▾ · Histogram │ Table · ⚙" (D02 L159)
- "Profile" (spec L5)
- "Visible range" (spec L263)
- "Volume" (spec L5)
- D02 W-29: "Histogram" (D02 L378)
- D02 W-29: "Table" (D02 L378)
- "⚙" (D02 L159)
- W-2: "{k} hidden" (spec L383) filled from the world
- W-6: "Show tested" (spec L387)
- "BTCUSDT" (spec L62)
- "POC" (spec L5)
- "VAH" (spec L120)
- "VAL" (spec L120)
- W-4: "nPOC {date}" (spec L385) filled from the world
- W-19: "Levels" (spec L400)
- W-20: "{n} ticks above the last price" (spec L401) filled from the world
- W-20: "{n} ticks below the last price" (spec L401) filled from the world
- "Price" (spec L184)
- "Delta" (spec L217)
- "% of POC" (D02 L339)
- "Value area" (spec L355)
- W-13: "In VA" (spec L394)
- W-9: "Net delta zero" (spec L390)
- W-13: "Outside VA" (spec L394)
- W-9: "No trades at this price" (spec L390)
- "load more rows" (D02 L339)
- W-17: "high-volume node" (spec L398)
- D02 W-34: "{level word} {price}: volume {v}, delta {d}, in value area" (D02 L383) filled from the world
- D02 W-2: "Aligned to {symbol} · {interval}" (D02 L351) filled from the world
- W-10: "Developing · as of {HH:MM} UTC" (spec L391) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- "Period" (spec L261)
- "Session" (spec L263)
- "Input" (spec L9)
- "VA%" (D02 L135)
- "Row" (spec L253)
- "VWAP" (spec L61)
- "Presets" (D02 L113)
- "Settings" (D02 L100)
- D02 W-19: "Row size: {n} ticks ({price})" (D02 L368) filled from the world
- "HVN" (spec L124)
- "LVN" (spec L124)
- "Single prints" (spec L200)
- D02 W-14: "Only the owner can change recording." (D02 L363)
- D02 W-11: "History starts when you record {symbol} — recording has not begun yet." (D02 L360) filled from the world
- D02 W-12: "Nothing is missing or broken: CandleViewer keeps only what it records." (D02 L361)
- D02 W-15: "Read-only while viewing as {user}." (D02 L364) filled from the world
- D02 W-17: "Could not load the profile." (D02 L366)
- D02 W-17: "Retry" (D02 L366)
- D02 W-18: "Stale · last update {HH:MM:SS} UTC" (D02 L367) filled from the world

## Copy gaps (5)

- "0 %", "87 %": the % of POC column's values as whole percent (kit form)
- "Enter on the focused row reads": the kit's marker label for a string a screen reader hears (board marker)
- "Enter on the focused row reads": the hidden-string marker label (board marker)
- "30m": the bound chart's interval word (kit world: 30-minute bars), filling D02 W-2's {interval}
- "Sam": D02 W-15's {user}, a synthetic display name (the name other boards use)

## Fallbacks (6)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the chart beside the panel is a plain SCR-030 price pane (candles, grid, price axis) for alignment only
- kit choice: a string a screen reader hears (an accessible name, the mirror's reading, a polite announcement) is drawn for the board as caption text in a bordered 'visually hidden' box (not on screen in the product)
- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen or a measurement, never product UI
- token-sync.json has no color.chart.focus.ring; SD:715 aliases it to color.focus.ring (§2.1), so the canvas ring binds color.focus.ring
- opacity.scrim is a Tier-1 primitive (validator WARN); the CMP-078 stale shade and the dialog scrim use it

## Sources (4)

- spec E19-D03.md md5 928db4e4 and hand-off md5 fb2077ba (§0 L83; RULED comment 6580374205)
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
- color.surface.selected
- size.icon
- color.surface.canvas
- color.grid.line
- type.num.sm
- color.axis.text
- color.candle.wick
- color.candle.down
- color.candle.up
- color.surface.raised
- color.surface.app
- color.text.tertiary
- space.stack.xs
- color.border.strong
- color.surface.sunken
- radius.card
- color.focus.ring
- border.focus
- space.stack.sm
- color.profile.valuearea
- type.num.xs
- color.tpo.letter
- color.profile.bar
- color.profile.poc
- type.ui.body-strong
- space.inset.lg
- color.status.danger.strong
- color.status.warning.strong
- radius.badge
- color.status.warning.subtle
- opacity.scrim
- color.data-confidence.stale.surface
- type.ui.heading-sm
