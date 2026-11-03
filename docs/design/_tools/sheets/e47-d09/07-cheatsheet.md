# E47-D09 / 07 cheatsheet

File `E47-D09 boards`, page `E47-D09`; export `docs/design/E47/img/E47-D09-07-cheatsheet.png`; sheet `07-cheatsheet.json` (validated); theme dark.

Board 07 of ten (§0 L74: SCR-013: search by name and by key, the remap mark, the nine contexts, no match (§9)). Grid (6000, 3200); 3280 x 1878 px; "page E47-D09 · board 07 · r1".

## Frames

- `cheatsheet∕search-name · dark`
- `cheatsheet∕search-key · dark`
- `cheatsheet∕remapped · dark`
- `cheatsheet∕no-match · dark`

## Validator and size

- `07-cheatsheet.json: 0 errors, 5 warnings, 62 sections, 191620 bytes` (exit 0)
- 62 sections, 191620 bytes

## Live checks (8)

- modal: keep 'CMP-094 hotkey overlay' at (48, 56) after relayout: placed by the sheet, never re-centred
- root 'E47-D09 / 07 cheatsheet' at (6000, 3200): read back the name exactly after the first section call; size 3280 x 1878
- after touchTexts + relayout: the root's h 1878 is the measured max(column end, footer end) + 80 (annotation column estimated 1375 px); read it back
- frame 'cheatsheet∕search-name · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'cheatsheet∕search-key · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'cheatsheet∕remapped · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'cheatsheet∕no-match · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- export docs/design/E47/img/E47-D09-07-cheatsheet.png: every frame is 1280 x 800; record the board id and the PNG size

## Readings (1)

- SCR-013's dialog is drawn 880 px wide at the frame's left (no source gives its width); the placeholder of the search is "Filter" (E10-D03 §6.2 names Filter, CMP-054)

## G rows (1)

- D09-G1 (§19.2 L417): no flatten-all command is registered, though 05:64 and the TopBar name one (owner E47-S08, the registry rows)

## C rows (4)

- D09-C1 (§19.1 L394): the shipped key wins (D07E11:349, K10); ? a PROPOSED alias (D09-A1)
- D09-C11 (§19.1 L404): modal, as shipped and as 15 says
- D09-C10 (§19.1 L403): the nine; D09-A8
- D09-C2 (§19.1 L395): AC4 traced on positions.close_all; D09-G1

## Spec gaps (1)

- W-23 "{n} shortcuts match" has no singular form: a one-row result is drawn as the deck gives it ("1 shortcuts match"); the words are E47-D07's (#1306)

## Deviations (0)

## Copy keys (4)

- W-11 (§16 L316, verbatim)
- W-23 (§16 L328, PROPOSED)
- W-7 (§16 L312, verbatim)
- W-10 (§16 L315, PROPOSED)

## Copy gaps (0)

## Fallbacks (5)

- kit choice: CMP-022 Kbd drawn as a pill (color.surface.raised, color.border.default hairline, radius.control, type.num.xs in color.text.primary); a pointer chord reads as its words
- kit choice: numbered stop markers, tags, outlines, arrows and callouts are annotation overlays in color.status.info.default (callouts on color.surface.overlay), never product UI; a callout quotes what is spoken (polite) or what a key does
- fallback: no scrim colour token: the flat scrim is color.surface.sunken at opacity.scrim
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact); SCR-012's rows 32 px (E10-D03 §6.1, D03E10:281: 32 compact, 40 comfortable); the shell bars keep E10's 48 px TopBar
- kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab labels, RightRail rows, StatusBar items, list rows of SCR-093) drawn as neutral placeholders; only what this spec names is drawn with words

## Sources (1)

- spec docs/design/E47/E47-D09.md md5 0d47e6c0 (§0 L74); hand-off docs/design/E47/E47-D09-handoff.md md5 3b577b2c (§H L105); registry at 4c662fd5b apps/web/src/keymap/keymap.json md5 eb409e85 and apps/web/src/keymap/reserved-keys.json md5 5683c37f; tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (42)

- color.text.secondary
- size.icon
- type.ui.body
- color.text.primary
- space.inset.xs
- space.inset.sm
- color.surface.canvas
- radius.control
- color.border.default
- border.hairline
- type.ui.heading-md
- type.ui.body-strong
- space.button.paddingX
- type.num.xs
- color.surface.raised
- type.ui.caption
- space.stack.xs
- space.stack.lg
- space.inset.lg
- color.action.secondary.default
- color.focus.ring
- border.focus
- space.stack.md
- space.dialog.padding
- color.surface.overlay
- radius.dialog
- type.ui.label
- color.status.info.default
- border.thick
- opacity.scrim
- color.surface.sunken
- color.surface.hover
- space.inset.md
- color.surface.selected
- color.surface.app
- color.border.subtle
- color.env.live
- color.status.danger.subtle
- color.status.danger.strong
- type.ui.heading-sm
- color.text.tertiary
- space.stack.sm
