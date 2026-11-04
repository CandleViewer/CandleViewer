# E47-D05 / 04 system-states

File `E47-D05 boards`, page `E47-D05 SCR-117`; export `docs/design/E47/img/E47-D05-04-system-states.png`; sheet `04-system-states.json` (validated); theme dark.

Board 04 of 10 (§0 L68: §5: following-system, os-changed-while-open with its status line, forced-colours with the T2 row (§5.4)). Grid (21000, 0); 4640 x 1296 px; "page E47-D05 SCR-117 · board 04 · r1".

## Frames

- `SCR-117∕following-system · dark` (§H: `SCR-117/following-system · dark`)
- `SCR-117∕os-changed-while-open · dark` (§H: `SCR-117/os-changed-while-open · dark`)
- `SCR-117∕forced-colours · dark` (§H: `SCR-117/forced-colours · dark`)

## Validator and size

- `04-system-states.json: 0 errors, 1 warnings, 22 sections, 106835 bytes` (exit 0)
- 22 sections, 106835 bytes

## Live checks (6)

- root 'E47-D05 / 04 system-states' at (21000, 0): read back the name exactly after the first section call; size 4640 x 1296
- after touchTexts + relayout: the annotation column (estimated 1132 px) ends inside the root (h 1296); raise the root's h to its end + 80 if not
- frame 'SCR-117∕following-system · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-117∕os-changed-while-open · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-117∕forced-colours · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D05-04-system-states.png; record the board id and the PNG size in §0

## Ambiguities (4)

- §2 L119 gives the five FormSections and their order but not which rows each holds: the kit groups §3's keys by their words — Motion: reduced_motion, disable_canvas_animation; Contrast and focus: increased_contrast, thick_focus_ring, always_show_focus_ring; Data views: always_show_tables; Announcements: announce_prices, announce_throttle_s, verbosity; Interaction: keyboard_only, larger_hit_targets (the tiles: motion, focus, table-alt and announcements after their group's last row, §6)
- Board 04 frame 2: §5.3 shows the in-place update (a following row) and W-16 (an explicit row) but W-16's words are fixed ("…asks for off; your choice of On stays"): drawn as one OS change that turns both signals off — the contrast row follows (W-15, its line updated), the motion row keeps its explicit On (W-16); an explicit contrast On would switch the theme to high contrast, so the explicit row is motion
- Effective lines with no OS preference read "the product default" (W-14): the kit reads "no-preference" as no OS signal (§5.1's override ?? OS signal ?? default)
- T2 label colour (design-read minor): §5.4 and E09-D09 §2.2 put the T2 label and its lock in color.text.tertiary; §11's "labels color.text.primary" is read as the enabled rows' rule — drawn tertiary on the forced-colours contrast row only

## Spec gaps (0)

## Deviations (0)

## Copy keys (10)

- W-15 (§15 L298, PROPOSED, label for D07): Your system setting changed: increased contrast is now off.
- W-1 (§15 L284, verbatim): Changes apply immediately, including chart canvases. They are saved to your account.
- W-2 (§15 L285, PROPOSED, the scope line): Scope: per user, for every setting on this page.
- W-18 (§15 L301, PROPOSED, the still frames): Before
- W-18 (§15 L301, PROPOSED, the still frames): After
- W-16 (§15 L299, PROPOSED, visible only, not spoken): Your system now asks for off; your choice of On stays.
- W-24 (§15 L307, PROPOSED): Reset
- W-24 (§15 L307, PROPOSED): Changed
- W-26 (§15 L309, PROPOSED, the T2 contrast row (§5.4)): Effective: On, your system's high-contrast mode
- W-17 (§15 L300, PROPOSED state key (D05-A7)): Your system's high-contrast mode is on.

## Copy gaps (6)

- "Search settings": the settings search's visible label (§10 L249 names the search; no placeholder stands in for a label, `11`:5077)
- the motion tile's accessible name "Motion preview, reduced: still before and after frames": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- "Sample": the focus tile's CMP-001 Button label (§6.2 L185 names the button, not its words)
- the focus tile's accessible name "Focus preview: normal ring": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- "Reset this section": §10 L248 and §12 name the button; §15 has no W-row for it
- the motion tile's accessible name "Motion preview, full motion: the heatmap trail fades, the price flashes": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)

## Fallbacks (2)

- fallback: border.control (E47-D03's D03-D5 / D03-D6, PROPOSED) is not a token yet: control boundaries bind border.hairline in dark and light and border.thick in high contrast
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and the other CMP-086 entries drawn as neutral placeholders; only SCR-117's content, its SettingsNav entry and the reveal hosts' named parts are drawn

## Sources (1)

- spec docs/design/E47/E47-D05.md md5 e63e13fc, hand-off docs/design/E47/E47-D05-handoff.md md5 ccc824d0 (§0 L68; hand-off §H L97); shipped labels apps/web/src/features/a11y-preferences/AccessibilitySettingsScreen.tsx at 4c662fd5b md5 797df795; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 48c711e64 (§7.1)

## Tokens (45)

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
- color.border.default
- space.stack.md
- radius.card
- type.ui.heading-sm
- space.stack.lg
- space.inset.xl
- space.inset.xs
- space.button.paddingX
- color.action.secondary.default
- color.focus.ring
- border.focus
- color.surface.raised
- color.surface.app
- color.border.subtle
- color.text.link
- color.border.selected
- color.text.tertiary
