# E47-D05 / 03 hc-zoom-200

File `E47-D05 boards`, page `E47-D05 SCR-117`; export `docs/design/E47/img/E47-D05-03-hc-zoom-200.png`; sheet `03-hc-zoom-200.json` (validated); theme hc.

Board 03 of 10 (§0 L67: §11: high contrast at 200 % (640 CSS px), the stacked column, nothing clipped (T AC4)). Grid (14000, 0); 2560 x 1000 px; "page E47-D05 SCR-117 · board 03 · r1".

## Frames

- `SCR-117∕default · hc` (§H: `SCR-117/default · hc` at 640 CSS px)

## Validator and size

- `03-hc-zoom-200.json: 0 errors, 1 warnings, 31 sections, 129330 bytes` (exit 0)
- 31 sections, 129330 bytes

## Live checks (8)

- link 'Read the accessibility statement': after relayout set the underline's width to the words' measured width (199 px expected)
- link 'Change shortcuts': after relayout set the underline's width to the words' measured width (110 px expected)
- strip 1: set 'dashed · viewport 640 x 400 CSS' to a dashed style stroke (post-step) so its bottom edge does not strike through the words under the 400 px fold
- root 'E47-D05 / 03 hc-zoom-200' at (14000, 0): read back the name exactly after the first section call; size 2560 x 1000
- after touchTexts + relayout: the annotation column (estimated 589 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'SCR-117∕default · hc': read back 1920 x 800 at (80, 80); clip on, no child spills
- theme: activate the hc token set before exporting board 03; read back one bound fill (color.surface.canvas) as the hc value
- export docs/design/E47/img/E47-D05-03-hc-zoom-200.png; record the board id and the PNG size in §0

## Ambiguities (1)

- §2 L119 gives the five FormSections and their order but not which rows each holds: the kit groups §3's keys by their words — Motion: reduced_motion, disable_canvas_animation; Contrast and focus: increased_contrast, thick_focus_ring, always_show_focus_ring; Data views: always_show_tables; Announcements: announce_prices, announce_throttle_s, verbosity; Interaction: keyboard_only, larger_hit_targets (the tiles: motion, focus, table-alt and announcements after their group's last row, §6)

## Spec gaps (0)

## Deviations (0)

## Copy keys (6)

- W-1 (§15 L284, verbatim): Changes apply immediately, including chart canvases. They are saved to your account.
- W-2 (§15 L285, PROPOSED, the scope line): Scope: per user, for every setting on this page.
- W-25 (§15 L308, PROPOSED, the focus-ring row (§5.1)): Effective: On, the high-contrast theme
- W-22 (§15 L305, PROPOSED): Show the keyboard shortcut cheatsheet (Ctrl+/)
- W-21 (§15 L304, PROPOSED): Read the accessibility statement
- W-23 (§15 L306, PROPOSED): Change shortcuts

## Copy gaps (8)

- "Search settings": the settings search's visible label (§10 L249 names the search; no placeholder stands in for a label, `11`:5077)
- the motion tile's accessible name "Motion preview, full motion: the heatmap trail fades, the price flashes": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- "Sample": the focus tile's CMP-001 Button label (§6.2 L185 names the button, not its words)
- the focus tile's accessible name "Focus preview: thick ring": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- the table-alt tile's accessible name "Table preview: the sample candles as a chart": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- "Play sample": the announcement tile's button (§6.3 L189; W-27 "Show all" is its label while playing)
- the tile's burst line "20 s BTCUSDT burst, 40 prints a second": §7.3 L218's figures, worded by the kit
- the announcements tile's accessible name "Announcement preview: On significant change, verbosity Normal": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)

## Fallbacks (4)

- kit choice (the E47-D03 kit's): the 200 % frame draws the 640 CSS px page at 1:1 in 640 x 800 strips side by side (CSS y 0-800, 800-1600, ...); the device shows it at 2 x; the first 640 x 400 CSS viewport is outlined on strip 1
- fallback: border.control (E47-D03's D03-D5 / D03-D6, PROPOSED) is not a token yet: control boundaries bind border.hairline in dark and light and border.thick in high contrast
- fallback: the 3 px thick ring (PROPOSED border.focus.thick, D04-G5: not a token) drawn as two adjacent strokes in color.focus.ring, border.focus (2) + border.hairline (1); its 2 px halos as border.thick
- fallback: the link underline (A11Y-F-0018) drawn as a 1 px color.text.link rect under the words (no text-decoration field in cvsheet)

## Sources (1)

- spec docs/design/E47/E47-D05.md md5 8ea33dd1, hand-off docs/design/E47/E47-D05-handoff.md md5 67b6a7d8 (§0 L67; hand-off §H L97); shipped labels apps/web/src/features/a11y-preferences/AccessibilitySettingsScreen.tsx at 4c662fd5b md5 797df795; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 48c711e64 (§7.1)

## Tokens (47)

- color.text.secondary
- size.icon
- space.inset.sm
- color.surface.canvas
- radius.control
- color.border.strong
- border.thick
- type.ui.label
- color.text.primary
- space.stack.xs
- type.ui.heading-md
- type.ui.body
- type.ui.caption
- space.stack.sm
- type.ui.body-strong
- color.action.primary.default
- space.inset.lg
- color.surface.hover
- radius.badge
- space.inset.md
- type.num.sm
- color.axis.text
- color.heatmap.bid.4
- color.heatmap.bid.5
- color.heatmap.bid.2
- color.heatmap.bid.1
- color.heatmap.bid.3
- type.num.base
- color.border.default
- border.hairline
- space.stack.md
- radius.card
- type.ui.heading-sm
- space.stack.lg
- space.inset.xs
- space.button.paddingX
- color.action.secondary.default
- color.focus.ring
- border.focus
- color.surface.raised
- color.candle.wick
- color.candle.down
- color.candle.up
- color.text.link
- color.surface.app
- color.status.info.default
- color.text.tertiary
