# E47-D05 / 09 modified-reset-search

File `E47-D05 boards`, page `E47-D05 SCR-117`; export `docs/design/E47/img/E47-D05-09-modified-reset-search.png`; sheet `09-modified-reset-search.json` (validated); theme dark.

Board 09 of 10 (§0 L73: §10: modified with per-option reset, the section-reset preview dialog, search results with section paths). Grid (21000, 4200); 4640 x 1032 px; "page E47-D05 SCR-117 · board 09 · r1".

## Frames

- `SCR-117∕modified · dark` (§H: `SCR-117/modified · dark`)
- `SCR-117∕section-reset-preview · dark` (§H: `SCR-117/section-reset-preview · dark`)
- `SCR-117∕search-results · dark` (§H: `SCR-117/search-results · dark`)

## Validator and size

- `09-modified-reset-search.json: 0 errors, 2 warnings, 24 sections, 111722 bytes` (exit 0)
- 24 sections, 111722 bytes

## Live checks (7)

- modal: re-centre 'CMP-043 Dialog' after relayout (estimated 440 x 178 px)
- root 'E47-D05 / 09 modified-reset-search' at (21000, 4200): read back the name exactly after the first section call; size 4640 x 1032
- after touchTexts + relayout: the annotation column (estimated 870 px) ends inside the root (h 1032); raise the root's h to its end + 80 if not
- frame 'SCR-117∕modified · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'SCR-117∕section-reset-preview · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'SCR-117∕search-results · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D05-09-modified-reset-search.png; record the board id and the PNG size in §0

## Ambiguities (2)

- §2 L119 gives the five FormSections and their order but not which rows each holds: the kit groups §3's keys by their words — Motion: reduced_motion, disable_canvas_animation; Contrast and focus: increased_contrast, thick_focus_ring, always_show_focus_ring; Data views: always_show_tables; Announcements: announce_prices, announce_throttle_s, verbosity; Interaction: keyboard_only, larger_hit_targets (the tiles: motion, focus, table-alt and announcements after their group's last row, §6)
- Board 09 search: §10 gives the synonyms and the status, not the match rule: the kit matches the term in a row's label or description ("motion" finds 2), each result naming its section path as "Accessibility › <section>"

## Spec gaps (0)

## Deviations (1)

- dialog width 440 px: a kit choice (no source gives CMP-043's width)

## Copy keys (8)

- W-24 (§15 L307, PROPOSED): Reset
- W-1 (§15 L284, verbatim): Changes apply immediately, including chart canvases. They are saved to your account.
- W-2 (§15 L285, PROPOSED, the scope line): Scope: per user, for every setting on this page.
- W-24 (§15 L307, PROPOSED): Changed
- W-18 (§15 L301, PROPOSED, the still frames): Before
- W-18 (§15 L301, PROPOSED, the still frames): After
- W-29 (§15 L312, PROPOSED, label for D07): 2 settings found
- W-28 (§15 L311, PROPOSED, label for D07): 2 settings reset to their defaults.

## Copy gaps (9)

- "On" / "Off" for a switch's value in the preview lines, and the dialog title "Reset this section" (§10 gives the line form "Label: current → default" and names the invoking button, not a title)
- "Cancel": the dialog's initial-focus button (§10 names it)
- "Search settings": the settings search's visible label (§10 L249 names the search; no placeholder stands in for a label, `11`:5077)
- "Reset this section": §10 L248 and §12 name the button; §15 has no W-row for it
- the motion tile's accessible name "Motion preview, reduced: still before and after frames": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- "Sample": the focus tile's CMP-001 Button label (§6.2 L185 names the button, not its words)
- the focus tile's accessible name "Focus preview: normal ring": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)
- the result's section path "Accessibility › <section>": §10 asks for "their section path", §15 gives no form
- the motion tile's accessible name "Motion preview, full motion: the heatmap trail fades, the price flashes": §6 L179 asks for "the configuration in words" and gives no string (an aria-label, not drawn)

## Fallbacks (3)

- fallback: border.control (E47-D03's D03-D5 / D03-D6, PROPOSED) is not a token yet: control boundaries bind border.hairline in dark and light and border.thick in high contrast
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and the other CMP-086 entries drawn as neutral placeholders; only SCR-117's content, its SettingsNav entry and the reveal hosts' named parts are drawn
- fallback: no scrim colour token: the flat scrim is color.surface.sunken at opacity.scrim

## Sources (1)

- spec docs/design/E47/E47-D05.md md5 e63e13fc, hand-off docs/design/E47/E47-D05-handoff.md md5 ccc824d0 (§0 L73; hand-off §H L97); shipped labels apps/web/src/features/a11y-preferences/AccessibilitySettingsScreen.tsx at 4c662fd5b md5 797df795; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 48c711e64 (§7.1)

## Tokens (51)

- type.ui.body-strong
- color.text.primary
- space.inset.xs
- space.button.paddingX
- radius.control
- color.action.secondary.default
- color.border.strong
- border.hairline
- color.surface.canvas
- color.focus.ring
- border.focus
- type.ui.body
- space.stack.xs
- type.ui.heading-md
- space.inset.sm
- color.surface.overlay
- radius.dialog
- space.dialog.padding
- space.stack.md
- color.border.default
- color.text.secondary
- size.icon
- type.ui.label
- type.ui.caption
- space.stack.sm
- color.action.primary.default
- space.inset.lg
- color.text.on-action
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
- radius.card
- type.ui.heading-sm
- space.stack.lg
- space.inset.xl
- color.surface.hover
- color.surface.raised
- color.surface.app
- color.border.subtle
- color.text.link
- color.border.selected
- opacity.scrim
- color.surface.sunken
- color.text.tertiary
