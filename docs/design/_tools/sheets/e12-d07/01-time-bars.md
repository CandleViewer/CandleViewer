# E12-D07 / 01 time-bars

File `E12-D07 boards`, page `E12-D07 SCR-045 data table`; export `docs/design/E12/img/E12-D07-01-time-bars.png`; sheet `01-time-bars.json` (validated); theme dark.

Board 01 of ten (§0 L75): the time-mode set (§3), the caption with its units (§7.4), `forming` and `—` in `state`, the sort chip with the forming row last. Three 1280 × 800 windows, one chart panel each (RightRail strip, dock 1,168 CSS px), compact density, dark.

## Frames

- `SCR-045∕time∕default · dark`
- `SCR-045∕time∕forming-last · dark`
- `SCR-045∕time∕sorted-delta · dark`
- `SCR-045∕time∕default · dark`: 20 rows, focus 10:20 (row 89 of 291); §3.1, §6, §7.4
- `SCR-045∕time∕forming-last · dark`: 20 rows to 13:42, the forming row last and focused; §6, D04E11
- `SCR-045∕time∕sorted-delta · dark`: delta ↓, 18 rows (end of the order), forming row last and focused; W-17

## Validator and size

- `01-time-bars.json: 0 errors, 133 warnings, 70 sections, 216181 bytes` (exit 0)
- 70 sections, 216181 bytes

## Live checks (10)

- root 'E12-D07 / 01 time-bars' at (0, 0): read back the name exactly after the first section call (a mismatch makes a duplicate root); size 4640 x 2574
- after touchTexts + relayout: the annotation column (estimated 2735 px) ends inside the root (h 2574); raise the root's h if not
- frame 'SCR-045∕time∕default · dark': read back 1280 x 800 at (80, 80) after relayout; no child overflows it (clip on)
- frame 'SCR-045∕time∕forming-last · dark': read back 1280 x 800 at (1440, 80) after relayout; no child overflows it (clip on)
- frame 'SCR-045∕time∕sorted-delta · dark': read back 1280 x 800 at (2800, 80) after relayout; no child overflows it (clip on)
- export docs/design/E12/img/E12-D07-01-time-bars.png: the PNG's frames are each 1280 x 800 device px; record the board id and the PNG size
- frame 1: read back the ring on the 'row .. · focused' node: 2 px color.focus.ring, stroke inner
- frame 2: the last child of 'rows' is the focused forming row; its 'state' text binds color.text.primary and its price cells color.text.secondary
- frame 3: 'th · delta' holds the arrow-down icon; 'filter and sort line' sits between the caption and the header row; the last child of 'rows' is the forming row
- every frame: no body row is cut at the table's bottom edge after relayout (whole 24 px rows)

## Spec gaps (3)

- CVD: E11-D04 D3 (D04E11:116) has CVD rejoin automatically at ≥ 708 CSS px; §3.1 (L165) tiers it E. The 1,168 px panel is wider than 708, but the board draws §3.1's set (the kit's reading for every board); flag for the set's consistency review
- sort order of rows whose delta is — : not ruled; avoided here (the loaded series holds trade-built bars only, so every closed row has a delta)
- the separator row's text for this load (kline hole meeting the 09:15 restart) is §7.1's “No bars for 17:02–09:14 UTC · Series restarted 09:15 UTC”; it is off-screen in all three frames

## Deviations (0)

## Copy keys (1)

- W-17 (§13 L361, PROPOSED)

## Copy gaps (0)

## Fallbacks (2)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the expander, check and sort glyphs
- fallback: color.text.buy / color.text.sell (E11-D04 CR-D04-2 = E11-D02 CR-5, unregistered) drawn as color.buy.default / color.sell.default; the sign (+ / −) is the carrier (D04E11 §5.4)

## Sources (1)

- spec E12-D07.md md5 d8bbf958 (§0 L75); hand-off §H; E11-D04 §2, §5, §6, §10 (md5 02f3ff69); E12-D04 board kit (chrome geometry)

## Tokens (32)

- color.text.secondary
- size.icon.sm
- type.num.sm
- color.text.primary
- space.inset.sm
- color.buy.default
- color.surface.canvas
- color.surface.raised
- color.sell.default
- color.focus.ring
- border.focus
- type.ui.caption
- color.text.tertiary
- type.ui.label
- color.border.default
- border.hairline
- radius.control
- space.inset.xs
- space.stack.xs
- color.surface.selected
- size.icon
- color.env.demo
- radius.badge
- radius.card
- type.ui.heading-sm
- space.inset.lg
- space.inset.md
- color.surface.hover
- color.surface.app
- color.surface.sunken
- type.ui.body
- space.stack.sm
