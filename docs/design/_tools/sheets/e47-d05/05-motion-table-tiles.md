# E47-D05 / 05 motion-table-tiles

File `E47-D05 boards`, page `E47-D05 SCR-117`; export `docs/design/E47/img/E47-D05-05-motion-table-tiles.png`; sheet `05-motion-table-tiles.json` (validated); theme dark.

Board 05 of 10 (§0 L69: §6.1, §6.4: the motion tile full / reduced (still frames, Pause) and the table-alternative tile). Grid (28000, 0); 4640 x 1008 px; "page E47-D05 SCR-117 · board 05 · r1".

## Frames

- `tile∕motion-full · dark` (§H: `tile/motion-full · dark`)
- `tile∕motion-reduced · dark` (§H: `tile/motion-reduced · dark`)
- `tile∕table-alt · dark` (§H: `tile/table-alt · dark`)

## Validator and size

- `05-motion-table-tiles.json: 0 errors, 1 warnings, 25 sections, 103909 bytes` (exit 0)
- 25 sections, 103909 bytes

## Live checks (6)

- root 'E47-D05 / 05 motion-table-tiles' at (28000, 0): read back the name exactly after the first section call; size 4640 x 1008
- after touchTexts + relayout: the annotation column (estimated 848 px) ends inside the root (h 1008); raise the root's h to its end + 80 if not
- frame 'tile∕motion-full · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'tile∕motion-reduced · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'tile∕table-alt · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D05-05-motion-table-tiles.png; record the board id and the PNG size in §0

## Ambiguities (2)

- §2 L119 gives the five FormSections and their order but not which rows each holds: the kit groups §3's keys by their words — Motion: reduced_motion, disable_canvas_animation; Contrast and focus: increased_contrast, thick_focus_ring, always_show_focus_ring; Data views: always_show_tables; Announcements: announce_prices, announce_throttle_s, verbosity; Interaction: keyboard_only, larger_hit_targets (the tiles: motion, focus, table-alt and announcements after their group's last row, §6)
- Board 05 motion-reduced: §0 asks for the motion tile "full / reduced"; reduced is drawn through disable_canvas_animation (§6.1's second trigger), since board 04 already draws the OS-reduce route

## Spec gaps (0)

## Deviations (0)

## Copy keys (6)

- W-1 (§15 L284, verbatim): Changes apply immediately, including chart canvases. They are saved to your account.
- W-2 (§15 L285, PROPOSED, the scope line): Scope: per user, for every setting on this page.
- W-24 (§15 L307, PROPOSED): Reset
- W-24 (§15 L307, PROPOSED): Changed
- W-18 (§15 L301, PROPOSED, the still frames): Before
- W-18 (§15 L301, PROPOSED, the still frames): After

## Copy gaps (16)

- "Search settings": the settings search's visible label (§10 L249 names the search; no placeholder stands in for a label, `11`:5077)
- "Pause" / "Play": the motion tile's one button (§6 L179: "one button whose label swaps \"Pause\" / \"Play\"")
- the motion tile's accessible name "Motion preview, full motion: the heatmap trail fades, the price flashes": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- "Sample": the focus tile's CMP-001 Button label (§6.2 L185 names the button, not its words)
- the focus tile's accessible name "Focus preview: normal ring": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- "Reset this section": §10 L248 and §12 name the button; §15 has no W-row for it
- the motion tile's accessible name "Motion preview, reduced: still before and after frames": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- "Time": a candle-table column header in the table tile (§6.4 L193 names the CMP-049 table, §15 no header)
- "Open": a candle-table column header in the table tile (§6.4 L193 names the CMP-049 table, §15 no header)
- "High": a candle-table column header in the table tile (§6.4 L193 names the CMP-049 table, §15 no header)
- "Low": a candle-table column header in the table tile (§6.4 L193 names the CMP-049 table, §15 no header)
- "Close": a candle-table column header in the table tile (§6.4 L193 names the CMP-049 table, §15 no header)
- the table-alt tile's accessible name "Table preview: the sample candles as a table": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- "Play sample": the announcement tile's button (§6.3 L189; W-27 "Show all" is its label while playing)
- the tile's burst line "20 s BTCUSDT burst, 40 prints a second": §7.3 L218's figures, worded by the kit
- the announcements tile's accessible name "Announcement preview: On significant change, verbosity Normal": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)

## Fallbacks (2)

- fallback: border.control (E47-D03's D03-D5 / D03-D6, PROPOSED) is not a token yet: control boundaries bind border.hairline in dark and light and border.thick in high contrast
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and the other CMP-086 entries drawn as neutral placeholders; only SCR-117's content, its SettingsNav entry and the reveal hosts' named parts are drawn

## Sources (1)

- spec docs/design/E47/E47-D05.md md5 e63e13fc, hand-off docs/design/E47/E47-D05-handoff.md md5 ccc824d0 (§0 L69; hand-off §H L97); shipped labels apps/web/src/features/a11y-preferences/AccessibilitySettingsScreen.tsx at 4c662fd5b md5 797df795; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 48c711e64 (§7.1)

## Tokens (47)

- color.text.secondary
- size.icon
- space.inset.sm
- color.surface.canvas
- radius.control
- color.border.strong
- border.hairline
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
- color.buy.subtle
- space.inset.xs
- space.button.paddingX
- color.action.secondary.default
- color.focus.ring
- border.focus
- space.stack.md
- radius.card
- color.border.default
- type.ui.heading-sm
- space.stack.lg
- space.inset.xl
- color.surface.raised
- color.surface.app
- color.border.subtle
- color.text.link
- color.border.selected
- color.text.on-action
- color.text.tertiary
