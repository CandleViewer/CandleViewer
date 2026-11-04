# E19-D04 / 02 preset-save

File `E19-D04 boards`, page `E19-D04`; export `docs/design/E19/img/E19-D04-02-preset-save.png`; sheet `02-preset-save.json` (validated); theme dark.

Board 02 of ten (§0 L72: SCR-038/preset-save-dark, SCR-038/preset-conflict-dark, SCR-038/preset-rename-dark, SCR-038/preset-delete-dark). Grid (7600, 0); 3280 x 1878 px; "page E19-D04 · board 02 · r1".

## Frames

- `SCR-038∕preset-save-dark` (dark, 1280 x 800)
- `SCR-038∕preset-conflict-dark` (dark, 1280 x 800)
- `SCR-038∕preset-rename-dark` (dark, 1280 x 800)
- `SCR-038∕preset-delete-dark` (dark, 1280 x 800)

## Validator and size

- `02-preset-save.json: 0 errors, 38 warnings, 42 sections, 147294 bytes` (exit 0)
- 42 sections, 147294 bytes

## Live checks (8)

- the field's selection box is sized from the estimated text width: after touchTexts, fit its width to the drawn name (+ 2 px)
- root 'E19-D04 / 02 preset-save' at (7600, 0): read back the name exactly after the first section call; size 3280 x 1878
- after touchTexts + relayout: the annotation column (estimated 1013 px) ends inside the root (h 1878, the drawn max(annotation end, footer end) + 80); raise the root's h to that rule if not
- frame 'SCR-038∕preset-save-dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-038∕preset-conflict-dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-038∕preset-rename-dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'SCR-038∕preset-delete-dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- export docs/design/E19/img/E19-D04-02-preset-save.png under the dark set; record the board id and the PNG size

## Readings (2)

- a developing profile's open bracket edge (no cap) is the value-area edge on the last price's side (the E19-D03 kit's R-K3)
- the CMP-043 scrim drawn as color.surface.sunken at opacity.scrim (its palette.black is a primitive)

## Derivations (3)

- "VA 68 %": the example "VA 70 %" (D02 L144) with this frame's values
- "Value area 68 %": the example "Value area 70 %" (D02 L145) with this frame's values
- world: BTCUSDT 5m bars from 2026-11-02 00:00 UTC to the clock 2026-11-02 14:30 UTC, one walk seeded 439 (the issue number; drift redrawn every 24 bars), prices at the fixture's tick 0.10, sizes at its qty step 0.001; row size 100 ticks unless a preset says otherwise; the rectangle's price edges are the low / high of the bars it spans

## Spec gaps (0)

## Deviations (0)

## Copy keys (39)

- "Save as new" (spec L52)
- W-11: "Saves period, row size, value area, VWAP and node marking — never a time, symbol or account." (spec L331)
- W-12: "Preset name" (spec L332)
- "Cancel" (spec L52)
- "Save" (spec L52)
- "export holds these keys only — no time, symbol, drawing or account" (spec L128)
- W-8: "Modified" (spec L328)
- W-9: "{name} · Modified" (spec L329) filled from the world
- D02 W-2: "Aligned to {symbol} · {interval}" (D02 L351) filled from the world
- D03 W-10: "Developing · as of {HH:MM} UTC" (D03 L391) filled from the world
- D02 W-1: "Profile: BTCUSDT" (D02 L350)
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
- W-13: "A preset named {name} already exists." (spec L333) filled from the world
- W-13: "Overwrite" (spec L333)
- W-13: "Rename" (spec L333)
- "Rename preset" (spec L157)
- W-15: "Name must be 1 to 80 characters." (spec L335)
- W-1: "Presets" (spec L321)
- W-16: "Delete preset {name}?" (spec L336) filled from the world
- W-16: "Profiles using it keep their current settings." (spec L336)
- W-16: "Cancel" (spec L336)
- W-16: "Delete" (spec L336)

## Copy gaps (5)

- "Scalp tight 80": a synthetic name typed into the field (kit choice)
- "Scalp tight": a synthetic user preset name (kit choice; 1–80 characters, `22`:10802)
- "5m": the bound chart's interval word (kit world: 5-minute bars)
- "scalp tight": the typed name: the applied preset's name in another case (kit choice; uniqueness is case-insensitive)
- "polite announcement (once)": the kit's marker label for a string a screen reader hears (board marker)

## Fallbacks (7)

- kit choice: a board marker box ('board marker · …', 1 px color.border.strong outline) frames a specimen, a click path or a measurement, never product UI
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN), used for small glyphs
- kit stand-in (the E19-D03 kit's): the engine bakes the HVN / LVN triangles into the bar instance; the board draws them as the characters ▶ / ◀ in type.num.xs
- kit choice: the terminal's TopBar and StatusBar are neutral placeholders (E10's, not this spec's); the bound chart is a plain SCR-030 price pane (candles, grid, price axis); its status row draws only the chips these flows touch (the tool chip, the feed chip on the stale frame) — no environment badge or control anywhere (R-1, C-2.11)
- opacity.scrim is a Tier-1 primitive (validator WARN); the CMP-078 stale shade and the dialog scrim use it
- kit choice: a string a screen reader hears (an accessible name, a polite announcement) is drawn for the board as caption text in a bordered 'visually hidden' box (not on screen in the product)
- kit stand-in: the field's selected text is drawn as a color.surface.selected box behind the name

## Sources (8)

- spec E19-D04.md md5 9e0d20c3 in this checkout (§0 L72; BQ ruling RULED, comment 6585044844)
- D03 E19-D03.md md5 928db4e4 at 35032f521 (read via git show 35032f521; PR #5517 head; re-pinned when it merges)
- D02 E19-D02.md md5 1299df3b at 3619e95c5 (read via git show 3619e95c5; merge commit of PR #5487)
- D02E14 E14-D02.md md5 8560e306 at the base 95a625b09
- D07E14 E14-D07.md md5 697232d6 at the base 95a625b09
- D02E17 E17-D02.md md5 cb9a4d78 at the base 95a625b09
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a (tick size and qty step only)
- tokens: token-sync.json only (§11: shipped names, nothing new)

## Tokens (47)

- type.ui.caption
- color.text.secondary
- type.ui.body
- color.text.primary
- color.surface.sunken
- radius.control
- color.focus.ring
- border.focus
- space.stack.xs
- space.inset.sm
- space.inset.xs
- color.action.secondary.default
- color.border.default
- border.hairline
- color.text.on-action
- space.inset.md
- color.action.primary.default
- type.ui.heading-sm
- space.stack.md
- space.dialog.padding
- color.surface.overlay
- radius.dialog
- elevation.dialog
- type.ui.label
- color.surface.canvas
- color.border.strong
- radius.card
- size.icon.sm
- type.num.sm
- color.surface.selected
- color.surface.raised
- color.profile.valuearea
- type.num.xs
- color.grid.line
- color.axis.text
- color.candle.wick
- color.candle.down
- color.candle.up
- color.profile.bar
- color.profile.poc
- opacity.scrim
- color.surface.app
- color.status.danger.strong
- color.text.tertiary
- color.status.danger.default
- space.stack.sm
- space.inset.lg
