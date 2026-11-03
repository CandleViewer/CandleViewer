# E19-D04 / 01 preset-menu

File `E19-D04 boards`, page `E19-D04`; export `docs/design/E19/img/E19-D04-01-preset-menu.png`; sheet `01-preset-menu.json` (validated); theme dark.

Board 01 of ten (§0 L71: SCR-038/preset-menu-dark, SCR-038/preset-menu-empty-dark, SCR-038/preset-modified-dark, SCR-038/preset-modified-light). Grid (0, 0); 3280 x 1878 px; "page E19-D04 · board 01 · r1".

## Frames

- `SCR-038∕preset-menu-dark` (dark, 1280 x 800)
- `SCR-038∕preset-menu-empty-dark` (dark, 1280 x 800)
- `SCR-038∕preset-modified-dark` (dark, 1280 x 800)
- `SCR-038∕preset-modified-light` (light, 1280 x 800)

## Validator and size

- `01-preset-menu.json: 0 errors, 37 warnings, 36 sections, 145869 bytes` (exit 0)
- 36 sections, 145869 bytes

## Live checks (8)

- root 'E19-D04 / 01 preset-menu' at (0, 0): read back the name exactly after the first section call; size 3280 x 1878
- after touchTexts + relayout: the annotation column (estimated 1390 px) ends inside the root (h 1878, the drawn max(annotation end, footer end) + 80); raise the root's h to that rule if not
- frame 'SCR-038∕preset-menu-dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-038∕preset-menu-empty-dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-038∕preset-modified-dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'SCR-038∕preset-modified-light': read back 1280 x 800 at (1440, 960); clip on, no child spills
- export docs/design/E19/img/E19-D04-01-preset-menu.png under the dark set; record the board id and the PNG size
- kit reading R-K1: export board 01 a second time under the light set as docs/design/E19/img/E19-D04-01-preset-menu-light.png; read back one bound fill (color.surface.raised) as the light value; its '-light' frame is read from that export, its '-dark' frames from docs/design/E19/img/E19-D04-01-preset-menu.png

## Readings (1)

- a developing profile's open bracket edge (no cap) is the value-area edge on the last price's side (the E19-D03 kit's R-K3)

## Derivations (3)

- "VA 68 %": the example "VA 70 %" (D02 L144) with this frame's values
- "Value area 68 %": the example "Value area 70 %" (D02 L145) with this frame's values
- world: BTCUSDT 5m bars from 2026-11-02 00:00 UTC to the clock 2026-11-02 14:30 UTC, one walk seeded 439 (the issue number; drift redrawn every 24 bars), prices at the fixture's tick 0.10, sizes at its qty step 0.001; row size 100 ticks unless a preset says otherwise; the rectangle's price edges are the low / high of the bars it spans

## Spec gaps (0)

## Deviations (0)

## Copy keys (31)

- W-8: "Modified" (spec L328)
- D02 W-2: "Aligned to {symbol} · {interval}" (D02 L351) filled from the world
- D03 W-10: "Developing · as of {HH:MM} UTC" (D03 L391) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
- W-1: "Presets" (spec L321)
- "Period" (spec L31)
- "Session" (spec L51)
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
- W-2: "Session value" (spec L322)
- W-3: "Save as new…" (spec L323)
- W-5: "Rename…" (spec L325)
- W-6: "Delete…" (spec L326)
- W-10: "No saved presets yet" (spec L330)
- W-9: "{name} · Modified" (spec L329) filled from the world
- W-4: "Save changes to {name}" (spec L324) filled from the world
- W-7: "Reset to {name}" (spec L327) filled from the world

## Copy gaps (4)

- "Scalp tight": a synthetic user preset name (kit choice; 1–80 characters, `22`:10802)
- "5m": the bound chart's interval word (kit world: 5-minute bars)
- "Wide value": a synthetic user preset name (kit choice; 1–80 characters, `22`:10802)
- "polite announcement (once, on entering Modified)": the kit's marker label for a string a screen reader hears (board marker)

## Fallbacks (4)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- kit stand-in (the E19-D03 kit's): the engine bakes the HVN / LVN triangles into the bar instance; the board draws them as the characters ▶ / ◀ in type.num.xs
- kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the bound chart is a plain SCR-030 price pane (candles, grid, price axis); its status row draws only the chips these flows touch (the tool chip, the feed chip on the stale frame) — no environment badge or control anywhere (R-1, C-2.11)
- kit choice: a string a screen reader hears (an accessible name, a polite announcement) is drawn for the board as caption text in a bordered 'visually hidden' box (not on screen in the product)

## Sources (8)

- spec E19-D04.md md5 bad23883 in this checkout (§0 L71; BQ ruling RULED, comment 6585044844)
- D03 E19-D03.md md5 928db4e4 at 35032f521 (read via git show 35032f521; PR #5517 head; re-pinned when it merges)
- D02 E19-D02.md md5 1299df3b at 3619e95c5 (read via checkout; merge commit of PR #5487)
- D02E14 E14-D02.md md5 8560e306 at the base 95a625b09
- D07E14 E14-D07.md md5 697232d6 at the base 95a625b09
- D02E17 E17-D02.md md5 cb9a4d78 at the base 95a625b09
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json only (§11: shipped names, nothing new)

## Tokens (39)

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
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.down
- color.candle.up
- color.profile.bar
- color.profile.poc
- type.ui.body
- color.surface.hover
- color.focus.ring
- border.focus
- color.surface.overlay
- radius.card
- elevation.popover
- color.surface.app
- color.text.tertiary
- color.border.strong
- type.ui.heading-sm
- space.stack.sm
- space.inset.lg
