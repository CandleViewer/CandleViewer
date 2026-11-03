# E19-D04 / 05 anchored

File `E19-D04 boards`, page `E19-D04`; export `docs/design/E19/img/E19-D04-05-anchored.png`; sheet `05-anchored.json` (validated); theme dark.

Board 05 of ten (§0 L75: SCR-038/anchored-dark, SCR-038/anchor-removed-dark). Grid (30400, 0); 3280 x 998 px; "page E19-D04 · board 05 · r1".

## Frames

- `SCR-038∕anchored-dark` (dark, 1280 x 800)
- `SCR-038∕anchor-removed-dark` (dark, 1280 x 800)

## Validator and size

- `05-anchored.json: 0 errors, 17 warnings, 20 sections, 71984 bytes` (exit 0)
- 20 sections, 71984 bytes

## Live checks (5)

- root 'E19-D04 / 05 anchored' at (30400, 0): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the annotation column (estimated 616 px) ends inside the root (h 998, the drawn max(annotation end, footer end) + 80); raise the root's h to that rule if not
- frame 'SCR-038∕anchored-dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-038∕anchor-removed-dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E19/img/E19-D04-05-anchored.png under the dark set; record the board id and the PNG size

## Readings (1)

- a developing profile's open bracket edge (no cap) is the value-area edge on the last price's side (the E19-D03 kit's R-K3)

## Derivations (1)

- world: BTCUSDT 5m bars from 2026-11-02 00:00 UTC to the clock 2026-11-02 14:30 UTC, one walk seeded 439 (the issue number; drift redrawn every 24 bars), prices at the fixture's tick 0.10, sizes at its qty step 0.001; row size 100 ticks unless a preset says otherwise; the rectangle's price edges are the low / high of the bars it spans

## Spec gaps (0)

## Deviations (0)

## Copy keys (29)

- "Anchored" (spec L51)
- "contract pending A-1" (spec L55)
- D02 W-2: "Aligned to {symbol} · {interval}" (D02 L351) filled from the world
- D03 W-10: "Developing · as of {HH:MM} UTC" (D03 L391) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- W-1: "Presets" (spec L321)
- "Period" (spec L31)
- "Input" (spec L9)
- "Volume" (D03 L5)
- "VA%" (D02 L135)
- "Row" (spec L235)
- "VWAP" (spec L51)
- D02 W-29: "Histogram" (D02 L378)
- D02 W-29: "Table" (D02 L378)
- "Settings" (D02 L100)
- D02 W-19: "Row size: {n} ticks ({price})" (D02 L368) filled from the world
- "HVN" (spec L125)
- "LVN" (spec L125)
- D03 W-6: "Show tested" (D03 L387)
- "BTCUSDT" (spec L67)
- "POC" (spec L551)
- "VAH" (spec L551)
- "VAL" (D03 L120)
- W-27: "Keep open-ended" (spec L347)
- W-24: "Click a bar to anchor the profile" (spec L344)
- W-28: "Anchored at {time} UTC; extends with new bars." (spec L348) filled from the world
- "Session" (spec L51)
- W-29: "Remove anchor" (spec L349)
- W-30: "Anchor removed. Period: {mode}." (spec L350) filled from the world

## Copy gaps (2)

- "5m": the bound chart's interval word (kit world: 5-minute bars)
- "polite announcement (once)": the kit's marker label for a string a screen reader hears (board marker)

## Fallbacks (5)

- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen, a click path or a measurement, never product UI
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the bound chart is a plain SCR-030 price pane (candles, grid, price axis); its status row draws only the chips these flows touch (the tool chip, the feed chip on the stale frame) — no environment badge or control anywhere (R-1, C-2.11)
- kit choice: a string a screen reader hears (an accessible name, a polite announcement) is drawn for the board as caption text in a bordered 'visually hidden' box (not on screen in the product)
- kit stand-in (the E19-D03 kit's): the engine bakes the HVN / LVN triangles into the bar instance; the board draws them as the characters ▶ / ◀ in type.num.xs

## Sources (8)

- spec E19-D04.md md5 ede2cf4a in this checkout (§0 L75; BQ ruling RULED, comment 6585044844)
- D03 E19-D03.md md5 928db4e4 at 35032f521 (read via git show 35032f521; PR #5517 head; re-pinned when it merges)
- D02 E19-D02.md md5 1299df3b at 3619e95c5 (read via checkout; merge commit of PR #5487)
- D02E14 E14-D02.md md5 8560e306 at the base 95a625b09
- D07E14 E14-D07.md md5 697232d6 at the base 95a625b09
- D02E17 E17-D02.md md5 cb9a4d78 at the base 95a625b09
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json only (§11: shipped names, nothing new)

## Tokens (40)

- type.ui.caption
- color.text.secondary
- space.stack.xs
- space.inset.sm
- color.surface.canvas
- color.border.strong
- border.hairline
- radius.card
- type.ui.label
- color.text.primary
- size.icon.sm
- space.inset.xs
- radius.control
- color.action.secondary.default
- color.border.default
- type.num.sm
- color.surface.sunken
- color.surface.selected
- color.surface.raised
- color.profile.valuearea
- type.num.xs
- color.focus.ring
- size.icon
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.down
- color.candle.up
- color.profile.bar
- color.profile.poc
- color.text.tertiary
- color.surface.app
- type.ui.body
- color.surface.hover
- border.focus
- color.surface.overlay
- elevation.popover
- type.ui.heading-sm
- space.stack.sm
- space.inset.lg
