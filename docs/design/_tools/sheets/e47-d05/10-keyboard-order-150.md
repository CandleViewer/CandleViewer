# E47-D05 / 10 keyboard-order-150

File `E47-D05 boards`, page `E47-D05 SCR-117`; export `docs/design/E47/img/E47-D05-10-keyboard-order-150.png`; sheet `10-keyboard-order-150.json` (validated); theme dark.

Board 10 of 10 (§0 L74: §12: the Tab and reading order numbered, at 150 % text scale). Grid (28000, 4200); 1920 x 2864 px; "page E47-D05 SCR-117 · board 10 · r1".

## Frames

- `SCR-117∕keyboard-order · dark` (§H: `SCR-117/keyboard-order · dark` at 150 % text scale)

## Validator and size

- `10-keyboard-order-150.json: 0 errors, 1 warnings, 16 sections, 65183 bytes` (exit 0)
- 16 sections, 65183 bytes

## Live checks (7)

- link 'Read the accessibility statement': after relayout set the underline's width to the words' measured width (314 px expected)
- link 'Change shortcuts': after relayout set the underline's width to the words' measured width (173 px expected)
- 'dashed · fold · 800 px viewport': set its stroke to dashed style (post-step), so it reads as an annotation, not a divider
- root 'E47-D05 / 10 keyboard-order-150' at (28000, 4200): read back the name exactly after the first section call; size 1920 x 2864
- after touchTexts + relayout: the annotation column (estimated 695 px) ends inside the root (h 2864); raise the root's h to its end + 80 if not
- frame 'SCR-117∕keyboard-order · dark': read back 1280 x 2664 at (80, 80); clip on, no child spills
- export docs/design/E47/img/E47-D05-10-keyboard-order-150.png; record the board id and the PNG size in §0

## Ambiguities (1)

- §2 L119 gives the five FormSections and their order but not which rows each holds: the kit groups §3's keys by their words — Motion: reduced_motion, disable_canvas_animation; Contrast and focus: increased_contrast, thick_focus_ring, always_show_focus_ring; Data views: always_show_tables; Announcements: announce_prices, announce_throttle_s, verbosity; Interaction: keyboard_only, larger_hit_targets (the tiles: motion, focus, table-alt and announcements after their group's last row, §6)

## Spec gaps (0)

## Deviations (0)

## Copy keys (5)

- W-1 (§15 L284, verbatim): Changes apply immediately, including chart canvases. They are saved to your account.
- W-2 (§15 L285, PROPOSED, the scope line): Scope: per user, for every setting on this page.
- W-22 (§15 L305, PROPOSED): Show the keyboard shortcut cheatsheet (Ctrl+/)
- W-21 (§15 L304, PROPOSED): Read the accessibility statement
- W-23 (§15 L306, PROPOSED): Change shortcuts

## Copy gaps (9)

- "Search settings": the settings search's visible label (§10 L249 names the search; no placeholder stands in for a label, `11`:5077)
- "Pause" / "Play": the motion tile's one button (§6 L179: "one button whose label swaps \"Pause\" / \"Play\"")
- the motion tile's accessible name "Motion preview, full motion: the heatmap trail fades, the price flashes": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- "Sample": the focus tile's CMP-001 Button label (§6.2 L185 names the button, not its words)
- the focus tile's accessible name "Focus preview: normal ring": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- the table-alt tile's accessible name "Table preview: the sample candles as a chart": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- "Play sample": the announcement tile's button (§6.3 L189; W-27 "Show all" is its label while playing)
- the tile's burst line "20 s BTCUSDT burst, 40 prints a second": §7.3 L218's figures, worded by the kit
- the announcements tile's accessible name "Announcement preview: On significant change, verbosity Normal": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)

## Fallbacks (6)

- kit choice: numbered stop markers, tags and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI
- fallback: border.control (E47-D03's D03-D5 / D03-D6, PROPOSED) is not a token yet: control boundaries bind border.hairline in dark and light and border.thick in high contrast
- fallback: no type token at 150 %: each role is drawn with the token nearest 1.5 x its size (caption 11 -> heading-md 16, label 12 / body 13 -> heading-lg 20, heading-sm 14 / heading-md 16 -> display 24), as the E47-D03 kit does
- fallback: the link underline (A11Y-F-0018) drawn as a 1 px color.text.link rect under the words (no text-decoration field in cvsheet)
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and the other CMP-086 entries drawn as neutral placeholders; only SCR-117's content, its SettingsNav entry and the reveal hosts' named parts are drawn
- kit choice: a 1280-wide window whose page is longer than the 800 px viewport is drawn at its full scroll length (the fixed TopBar and StatusBar drawn once, at the top and the bottom), with the 800 px fold marked by a dashed annotation line

## Sources (1)

- spec docs/design/E47/E47-D05.md md5 8ea33dd1, hand-off docs/design/E47/E47-D05-handoff.md md5 67b6a7d8 (§0 L74; hand-off §H L97); shipped labels apps/web/src/features/a11y-preferences/AccessibilitySettingsScreen.tsx at 4c662fd5b md5 797df795; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 48c711e64 (§7.1)

## Tokens (50)

- type.ui.label
- color.text.inverse
- color.status.info.default
- radius.badge
- color.text.secondary
- size.icon
- space.inset.sm
- color.surface.canvas
- radius.control
- color.border.strong
- border.hairline
- type.ui.heading-lg
- color.text.primary
- space.stack.xs
- type.ui.display
- type.ui.heading-md
- space.stack.sm
- color.action.primary.default
- space.inset.lg
- color.surface.hover
- space.inset.md
- color.axis.text
- color.heatmap.bid.4
- color.heatmap.bid.5
- color.heatmap.bid.2
- color.heatmap.bid.1
- color.heatmap.bid.3
- color.buy.subtle
- space.inset.xs
- space.button.paddingX
- color.action.secondary.default
- space.stack.md
- radius.card
- color.border.default
- space.stack.lg
- color.focus.ring
- border.focus
- color.surface.raised
- color.candle.wick
- color.candle.down
- color.candle.up
- color.text.link
- space.inset.xl
- color.surface.app
- color.border.subtle
- type.ui.body-strong
- color.border.selected
- type.ui.heading-sm
- type.ui.caption
- color.text.tertiary
