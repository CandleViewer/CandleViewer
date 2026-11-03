# E47-D07 / 07 scr117-panel-light

File `E47-D07 boards`, page `E47-D07 announcements`; export `docs/design/E47/img/E47-D07-07-scr117-panel-light.png`; sheet `07-scr117-panel-light.json` (validated); theme light.

Board 07 of 10 (§0 L72: light twin of 06). Grid (7000, 4200); 1920 x 998 px; "page E47-D07 announcements · board 07 · r1".

## Frames

- `SCR-117∕announcements-default · light` (§H: `SCR-117/announcements-default · light`)

## Validator and size

- `07-scr117-panel-light.json: 0 errors, 0 warnings, 22 sections, 56147 bytes` (exit 0)
- 22 sections, 56147 bytes

## Live checks (5)

- root 'E47-D07 / 07 scr117-panel-light' at (7000, 4200): read back the name exactly after the first section call; size 1920 x 998
- after touchTexts + relayout: the root's h 998 is the measured max(column end, footer end) + 80 (annotation column estimated 555 px); read it back
- frame 'SCR-117∕announcements-default · light': read back 1280 x 800 at (80, 80); clip on, no child spills
- theme: activate the light token set before exporting board 07; read back one bound fill (color.surface.canvas) as the light value
- export docs/design/E47/img/E47-D07-07-scr117-panel-light.png; record the board id and the PNG size in §0

## Ambiguities (3)

- Boards 06 / 07: §8.1's fixed row lists no options; the kit draws Assertive / Polite (the six's classes offer no Off, §8.1), Assertive checked
- Boards 06 / 07: the fieldsets are drawn legend-beside-radios (220 px legend) so the seventeen fit the viewport; §8.3's stacking applies at 400 % zoom and 200 % text (not drawn, §0)
- Board 06 view-as: §8.2 gives one notice for every gated control; the safety row keeps its own W-39 reason as well

## Spec gaps (0)

## Deviations (0)

## Copy keys (1)

- W-39 (§7.2 L316, no source; PROPOSED state key a11y.safety_fixed): Safety announcements are always read at once.

## Copy gaps (0)

## Fallbacks (3)

- kit choice: numbered stop markers, tags, arrows and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI
- fallback: border.control (E47-D03's D03-D5 / D03-D6, PROPOSED) is not a token yet: control boundaries bind border.hairline in dark and light
- kit choice: the shell chrome (TopBar, NavRail, StatusBar), the other CMP-086 entries and the other SCR-117 sections drawn as neutral placeholders; only this spec's parts are drawn

## Sources (1)

- spec docs/design/E47/E47-D07.md md5 ab7bad64, hand-off docs/design/E47/E47-D07-handoff.md md5 5b74ef6e (§0 L72; hand-off §H L107); scripts docs/design/E47/E47-D07-transcripts.json md5 6bf5c553 replayed through docs/design/_tools/e47_d07_announcement_audit.py md5 8ab6f248; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 48c711e64 (§7.1 there)

## Tokens (34)

- type.ui.caption
- color.text.inverse
- space.inset.xs
- radius.control
- color.status.info.default
- type.ui.heading-sm
- color.text.primary
- color.text.secondary
- color.surface.hover
- radius.badge
- color.border.strong
- border.hairline
- type.ui.body-strong
- space.stack.xs
- space.inset.md
- color.text.tertiary
- size.icon
- color.surface.canvas
- color.border.default
- type.ui.body
- space.inset.sm
- color.focus.ring
- border.focus
- space.inset.lg
- color.surface.raised
- color.action.primary.default
- space.stack.md
- space.inset.xl
- color.surface.app
- color.border.subtle
- color.text.link
- color.border.selected
- type.ui.label
- space.stack.sm
