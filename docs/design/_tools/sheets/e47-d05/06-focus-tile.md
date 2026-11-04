# E47-D05 / 06 focus-tile

File `E47-D05 boards`, page `E47-D05 SCR-117`; export `docs/design/E47/img/E47-D05-06-focus-tile.png`; sheet `06-focus-tile.json` (validated); theme dark.

Board 06 of 10 (§0 L70: §6.2: normal / thick / always-show ring on the tile). Grid (0, 4200); 4640 x 1000 px; "page E47-D05 SCR-117 · board 06 · r1".

## Frames

- `tile∕focus-normal · dark` (§H: `tile/focus-normal · dark`)
- `tile∕focus-thick · dark` (§H: `tile/focus-thick · dark`)
- `tile∕focus-always · dark` (§H: `tile/focus-always · dark`)

## Validator and size

- `06-focus-tile.json: 0 errors, 1 warnings, 26 sections, 104856 bytes` (exit 0)
- 26 sections, 104856 bytes

## Live checks (6)

- root 'E47-D05 / 06 focus-tile' at (0, 4200): read back the name exactly after the first section call; size 4640 x 1000
- after touchTexts + relayout: the annotation column (estimated 664 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'tile∕focus-normal · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'tile∕focus-thick · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'tile∕focus-always · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D05-06-focus-tile.png; record the board id and the PNG size in §0

## Ambiguities (1)

- §2 L119 gives the five FormSections and their order but not which rows each holds: the kit groups §3's keys by their words — Motion: reduced_motion, disable_canvas_animation; Contrast and focus: increased_contrast, thick_focus_ring, always_show_focus_ring; Data views: always_show_tables; Announcements: announce_prices, announce_throttle_s, verbosity; Interaction: keyboard_only, larger_hit_targets (the tiles: motion, focus, table-alt and announcements after their group's last row, §6)

## Spec gaps (0)

## Deviations (0)

## Copy keys (2)

- W-24 (§15 L307, PROPOSED): Reset
- W-24 (§15 L307, PROPOSED): Changed

## Copy gaps (9)

- "Sample": the focus tile's CMP-001 Button label (§6.2 L185 names the button, not its words)
- the focus tile's accessible name "Focus preview: normal ring": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- the table-alt tile's accessible name "Table preview: the sample candles as a chart": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- "Play sample": the announcement tile's button (§6.3 L189; W-27 "Show all" is its label while playing)
- the tile's burst line "20 s BTCUSDT burst, 40 prints a second": §7.3 L218's figures, worded by the kit
- the announcements tile's accessible name "Announcement preview: On significant change, verbosity Normal": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- "Reset this section": §10 L248 and §12 name the button; §15 has no W-row for it
- the focus tile's accessible name "Focus preview: thick ring": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- the focus tile's accessible name "Focus preview: normal ring, shown after a click": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)

## Fallbacks (4)

- fallback: border.control (E47-D03's D03-D5 / D03-D6, PROPOSED) is not a token yet: control boundaries bind border.hairline in dark and light and border.thick in high contrast
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and the other CMP-086 entries drawn as neutral placeholders; only SCR-117's content, its SettingsNav entry and the reveal hosts' named parts are drawn
- fallback: the 3 px thick ring (PROPOSED border.focus.thick, D04-G5: not a token) drawn as two adjacent strokes in color.focus.ring, border.focus (2) + border.hairline (1); its 2 px halos as border.thick
- kit choice: numbered stop markers, tags and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI

## Sources (1)

- spec docs/design/E47/E47-D05.md md5 e63e13fc, hand-off docs/design/E47/E47-D05-handoff.md md5 ccc824d0 (§0 L70; hand-off §H L97); shipped labels apps/web/src/features/a11y-preferences/AccessibilitySettingsScreen.tsx at 4c662fd5b md5 797df795; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 48c711e64 (§7.1)

## Tokens (44)

- type.ui.body-strong
- color.text.primary
- color.action.primary.default
- color.surface.canvas
- color.border.strong
- border.hairline
- type.ui.body
- space.inset.sm
- space.inset.lg
- type.ui.caption
- color.text.secondary
- space.stack.xs
- color.surface.hover
- radius.badge
- space.inset.md
- space.inset.xs
- space.button.paddingX
- radius.control
- color.action.secondary.default
- color.focus.ring
- border.focus
- type.num.base
- color.surface.raised
- space.stack.md
- radius.card
- color.border.default
- type.ui.heading-sm
- space.stack.lg
- space.inset.xl
- color.candle.wick
- color.candle.down
- color.candle.up
- size.icon
- type.ui.label
- color.surface.app
- color.border.subtle
- color.text.link
- color.border.selected
- color.text.on-action
- border.thick
- color.text.inverse
- color.status.info.default
- color.text.tertiary
- space.stack.sm
