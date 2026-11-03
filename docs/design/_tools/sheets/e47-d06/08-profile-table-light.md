# E47-D06 / 08 profile-table-light

File `E47-D06 boards`, page `E47-D06 — Canvas accessibility`; export `docs/design/E47/img/E47-D06-08-profile-table-light.png`; sheet `08-profile-table-light.json` (validated); theme light.

Board 08 of 8 (§0 L74: light twin of 03). Grid (14000, 4200); 3280 x 998 px; "page E47-D06 — Canvas accessibility · board 08 · r1".

## Frames

- `profile∕sorted · light` (§I: `profile/sorted · light`)
- `profile∕in-va · light` (§I: `profile/in-va · light`)

## Validator and size

- `08-profile-table-light.json: 0 errors, 49 warnings, 51 sections, 120729 bytes` (exit 0)
- 51 sections, 120729 bytes

## Live checks (6)

- root 'E47-D06 / 08 profile-table-light' at (14000, 4200): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the root's h 998 is the measured max(column end, footer end) + 80 (annotation column estimated 576 px); read it back
- frame 'profile∕sorted · light': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'profile∕in-va · light': read back 1280 x 800 at (1440, 80); clip on, no child spills
- theme: activate the light token set before exporting board 08; read back one bound fill (color.surface.canvas) as the light value
- export docs/design/E47/img/E47-D06-08-profile-table-light.png; record the board id and the PNG size in §0

## Ambiguities (2)

- "sorted by volume" (§0 board 03) names no direction: drawn descending (the second activation of §6.3's tri-state), so the largest level leads
- Value area cell: "In VA" / "Outside VA" then the POC / VAH / VAL word, joined by ", " (§5's value joiner); Periods cell: letters, the TPO count as "n TPO", then "Initial balance" — §6.2 names the three parts, not their order or format

## Spec gaps (0)

## Deviations (1)

- 70 % value area, rows of 10 ticks, 30-minute periods lettered from A: kit choices (SCR-038's settings, `14`:1025); the profile itself is E19's

## Copy keys (1)

- table.export_deferred (PROPOSED, owner E11-D04): "Export arrives with E15", the Export CSV T2 reason

## Copy gaps (2)

- "Add filter", "Columns": SCR-045's toolbar labels (D04E11:788), reused by §6.1's shell
- the panel title "Profile": `14`'s SCR-038 heading, " panel" and the parenthesis dropped (the panel header's own words are its spec's)

## Fallbacks (4)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- the CMP-019 Icon `lock` glyph is the local set's `locked` icon (the same glyph, the set's name)
- kit choice: numbered markers, tags, brackets and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) drawn as neutral placeholders (the E47-D03 kit's SCR-116 chrome); only the panels this spec designs carry words

## Sources (1)

- spec docs/design/E47/E47-D06.md md5 fdde6ab4, hand-off docs/design/E47/E47-D06-handoff.md md5 c6ebe77c (§0 L74; hand-off §I L111); T2 reason templates docs/design/E09/E09-D09.md md5 20c5d5f4; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 48c711e64 (§7.1)

## Tokens (35)

- type.num.base
- color.text.primary
- space.inset.sm
- color.sell.default
- type.ui.body
- color.text.secondary
- size.icon.sm
- color.surface.selected
- color.surface.canvas
- border.hairline
- color.focus.ring
- border.focus
- color.buy.default
- type.ui.label
- space.inset.xs
- color.surface.raised
- type.ui.caption
- color.text.tertiary
- color.border.default
- radius.control
- radius.badge
- type.ui.body-strong
- radius.card
- color.text.inverse
- color.status.info.default
- space.stack.xs
- color.surface.overlay
- border.thick
- color.surface.app
- color.surface.hover
- color.border.subtle
- space.inset.md
- space.inset.lg
- type.ui.heading-sm
- space.stack.sm
