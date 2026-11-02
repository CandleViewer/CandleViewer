# E47-D05 / 07 announcement-tile

File `E47-D05 boards`, page `E47-D05 SCR-117`; export `docs/design/E47/img/E47-D05-07-announcement-tile.png`; sheet `07-announcement-tile.json` (validated); theme dark.

Board 07 of 10 (§0 L71: §6.3, §7: off / significant / always, and the low-verbosity sample (T AC5)). Grid (7000, 4200); 3280 x 1880 px; "page E47-D05 SCR-117 · board 07 · r1".

## Frames

- `tile∕announce-off · dark` (§H: `tile/announce-off · dark`)
- `tile∕announce-significant · dark` (§H: `tile/announce-significant · dark`)
- `tile∕announce-always · dark` (§H: `tile/announce-always · dark`)
- `tile∕low-verbosity-sample · dark` (§H: `tile/low-verbosity-sample · dark`)

## Validator and size

- `07-announcement-tile.json: 0 errors, 1 warnings, 28 sections, 99159 bytes` (exit 0)
- 28 sections, 99159 bytes

## Live checks (7)

- root 'E47-D05 / 07 announcement-tile' at (7000, 4200): read back the name exactly after the first section call; size 3280 x 1880
- after touchTexts + relayout: the annotation column (estimated 884 px) ends inside the root (h 1880); raise the root's h to its end + 80 if not
- frame 'tile∕announce-off · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'tile∕announce-significant · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'tile∕announce-always · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'tile∕low-verbosity-sample · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- export docs/design/E47/img/E47-D05-07-announcement-tile.png; record the board id and the PNG size in §0

## Ambiguities (2)

- §2 L119 gives the five FormSections and their order but not which rows each holds: the kit groups §3's keys by their words — Motion: reduced_motion, disable_canvas_animation; Contrast and focus: increased_contrast, thick_focus_ring, always_show_focus_ring; Data views: always_show_tables; Announcements: announce_prices, announce_throttle_s, verbosity; Interaction: keyboard_only, larger_hit_targets (the tiles: motion, focus, table-alt and announcements after their group's last row, §6)
- Board 07: §0's "off / significant / always" frames show the same three event lines under Off and On significant change — §7.1 reads Off and the cadence as governing the polite price reads only, and the seeded burst has no price line under either; they differ in the radio and the tile's name

## Spec gaps (0)

## Deviations (0)

## Copy keys (3)

- W-24 (§15 L307, PROPOSED): Reset
- W-24 (§15 L307, PROPOSED): Changed
- W-27 (§15 L310, PROPOSED, the announcement tile (§6.3)): Show all

## Copy gaps (8)

- "Reset this section": §10 L248 and §12 name the button; §15 has no W-row for it
- "Play sample": the announcement tile's button (§6.3 L189; W-27 "Show all" is its label while playing)
- the tile's burst line "20 s BTCUSDT burst, 40 prints a second": §7.3 L218's figures, worded by the kit
- the announcements tile's accessible name "Announcement preview: Off, verbosity Normal": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- the announcements tile's accessible name "Announcement preview: On significant change, verbosity Normal": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- the announcements tile's accessible name "Announcement preview: Always, verbosity Normal": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- the announcements tile's accessible name "Announcement preview: On significant change, verbosity Low": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- "[latest price]": the price lines' bracketed label (§7.3 L218: "one latest-price line per field per cadence"; the words are E47-D07's)

## Fallbacks (2)

- fallback: border.control (E47-D03's D03-D5 / D03-D6, PROPOSED) is not a token yet: control boundaries bind border.hairline in dark and light and border.thick in high contrast
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and the other CMP-086 entries drawn as neutral placeholders; only SCR-117's content, its SettingsNav entry and the reveal hosts' named parts are drawn

## Sources (1)

- spec docs/design/E47/E47-D05.md md5 2352bde9, hand-off docs/design/E47/E47-D05-handoff.md md5 0b4d3568 (§0 L71; hand-off §H L97); shipped labels apps/web/src/features/a11y-preferences/AccessibilitySettingsScreen.tsx md5 797df795; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 1ff5d8cb9 (§7.1)

## Tokens (37)

- type.ui.caption
- color.text.primary
- color.text.secondary
- size.icon
- type.ui.label
- space.inset.xs
- space.stack.xs
- space.inset.md
- color.surface.raised
- radius.card
- color.action.primary.default
- color.surface.canvas
- color.border.strong
- border.hairline
- type.ui.body
- space.inset.sm
- space.inset.lg
- type.ui.body-strong
- space.button.paddingX
- radius.control
- color.action.secondary.default
- type.num.sm
- space.stack.md
- color.border.default
- type.ui.heading-sm
- space.stack.lg
- space.inset.xl
- color.surface.hover
- radius.badge
- color.surface.app
- color.border.subtle
- color.text.link
- color.border.selected
- color.focus.ring
- border.focus
- color.text.tertiary
- space.stack.sm
