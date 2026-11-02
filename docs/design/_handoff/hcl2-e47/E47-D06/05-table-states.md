# E47-D06 / 05 table-states

File `E47-D06 boards`, page `E47-D06 — Canvas accessibility`; export `docs/design/E47/img/E47-D06-05-table-states.png`; sheet `05-table-states.json` (validated); theme dark.

Board 05 of 8 (§0 L71: §6.5, §6.6: the stale banner per surface, empty, no data, filtered to zero, feed Stale, load more). Grid (28000, 0); 4640 x 1880 px; "page E47-D06 — Canvas accessibility · board 05 · r1".

## Frames

- `states∕stale · dark` (§I: `states/stale · dark`)
- `states∕feed-stale · dark` (§I: `states/feed-stale · dark`)
- `states∕empty · dark` (§I: `states/empty · dark`)
- `states∕no-data · dark` (§I: `states/no-data · dark`)
- `states∕filtered · dark` (§I: `states/filtered · dark`)
- `states∕load-more · dark` (§I: `states/load-more · dark`)

## Validator and size

- `05-table-states.json: 0 errors, 96 warnings, 123 sections, 284613 bytes` (exit 0)
- 123 sections, 284613 bytes

## Live checks (9)

- root 'E47-D06 / 05 table-states' at (28000, 0): read back the name exactly after the first section call; size 4640 x 1880
- after touchTexts + relayout: the annotation column (estimated 662 px) ends inside the root (h 1880); raise the root's h to its end + 80 if not
- frame 'states∕stale · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'states∕feed-stale · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'states∕empty · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- frame 'states∕no-data · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'states∕filtered · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- frame 'states∕load-more · dark': read back 1280 x 800 at (2800, 960); clip on, no child spills
- export docs/design/E47/img/E47-D06-05-table-states.png; record the board id and the PNG size in §0

## Ambiguities (2)

- states/stale draws one surface (the ladder, whose W-5 is fully specified); the other surfaces' conditions are listed from §6.5; the profile table's banner words are not in §13 (a level table takes W-1's form for its focused bar or period; E47-D07 words it)
- filtered to zero needs a filter that can empty the table: My levels only on an account without working orders (synthetic); the In VA filter can never reach zero rows

## Spec gaps (0)

## Deviations (0)

## Copy keys (1)

- table.export_deferred (PROPOSED, owner E11-D04): "Export arrives with E15", the Export CSV T2 reason

## Copy gaps (2)

- empty: "No order book yet" / "The table fills from the first book snapshot." are kit labels (§6.6 names the state only)
- "Profile", "DOM ladder" in the captions are kit labels for {panel}

## Fallbacks (5)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- the CMP-019 Icon `lock` glyph is the local set's `locked` icon (the same glyph, the set's name)
- kit choice: numbered markers, tags, brackets and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) drawn as neutral placeholders (the E47-D03 kit's SCR-116 chrome); only the panels this spec designs carry words
- fallback: a link underline drawn as a 1 px color.text.link rect under the words (no text-decoration field in cvsheet)

## Sources (1)

- spec docs/design/E47/E47-D06.md md5 d9cdedd6, hand-off docs/design/E47/E47-D06-handoff.md md5 d9a47687 (§0 L71; hand-off §I L111); T2 reason templates docs/design/E09/E09-D09.md md5 20c5d5f4; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 1ff5d8cb9 (§7.1)

## Tokens (41)

- type.num.base
- color.text.primary
- space.inset.sm
- color.buy.default
- type.ui.body
- color.text.secondary
- size.icon.sm
- color.sell.default
- type.ui.label
- space.inset.xs
- color.surface.raised
- type.ui.caption
- color.text.tertiary
- color.border.default
- border.hairline
- radius.control
- color.status.warning.strong
- size.icon
- color.status.warning.subtle
- radius.badge
- type.ui.body-strong
- color.surface.selected
- color.surface.canvas
- radius.card
- space.stack.xs
- color.surface.overlay
- color.status.info.default
- border.thick
- color.surface.app
- color.surface.hover
- color.border.subtle
- space.inset.md
- space.inset.lg
- color.focus.ring
- border.focus
- type.ui.heading-sm
- space.stack.sm
- space.inset.xl
- color.text.link
- color.sell.subtle
- color.buy.subtle
