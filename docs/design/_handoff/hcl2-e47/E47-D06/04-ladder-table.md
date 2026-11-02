# E47-D06 / 04 ladder-table

File `E47-D06 boards`, page `E47-D06 — Canvas accessibility`; export `docs/design/E47/img/E47-D06-04-ladder-table.png`; sheet `04-ladder-table.json` (validated); theme dark.

Board 04 of 8 (§0 L70: AC3: the ladder table sorted by cumulative depth, My levels only on, focus on a row, a patch tick). Grid (21000, 0); 3280 x 1000 px; "page E47-D06 — Canvas accessibility · board 04 · r1".

## Frames

- `ladder∕depth-sort-my-levels · dark` (§I: `ladder/depth-sort-my-levels · dark`)
- `ladder∕patch-tick · dark` (§I: `ladder/patch-tick · dark`)

## Validator and size

- `04-ladder-table.json: 0 errors, 23 warnings, 56 sections, 110770 bytes` (exit 0)
- 56 sections, 110770 bytes

## Live checks (5)

- root 'E47-D06 / 04 ladder-table' at (21000, 0): read back the name exactly after the first section call; size 3280 x 1000
- after touchTexts + relayout: the annotation column (estimated 502 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'ladder∕depth-sort-my-levels · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'ladder∕patch-tick · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D06-04-ladder-table.png; record the board id and the PNG size in §0

## Ambiguities (2)

- "sorted by cumulative depth" (AC3) names no direction: drawn ascending, the first activation of §6.3's tri-state (nearest depth first)
- Bid size on an ask level and Ask size on a bid level read "—" (`05` gives one row per price level; a level rests on one side)

## Spec gaps (0)

## Deviations (1)

- own orders at 64,102.2, 64,100.0, 64,103.3, 64,098.5 (synthetic); BASE is derived so that AC3's 64,100.0 is one of them

## Copy keys (1)

- table.export_deferred (PROPOSED, owner E11-D04): "Export arrives with E15", the Export CSV T2 reason

## Copy gaps (1)

- the native grid's column words "Price", "Bid", "Ask", "Mine" are kit labels (CMP-108's own header words are E21's)

## Fallbacks (4)

- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN)
- the CMP-019 Icon `lock` glyph is the local set's `locked` icon (the same glyph, the set's name)
- kit choice: numbered markers, tags, brackets and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) drawn as neutral placeholders (the E47-D03 kit's SCR-116 chrome); only the panels this spec designs carry words

## Sources (1)

- spec docs/design/E47/E47-D06.md md5 d9cdedd6, hand-off docs/design/E47/E47-D06-handoff.md md5 d9a47687 (§0 L70; hand-off §I L111); T2 reason templates docs/design/E09/E09-D09.md md5 20c5d5f4; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 1ff5d8cb9 (§7.1)

## Tokens (37)

- type.num.base
- color.text.primary
- space.inset.sm
- color.text.tertiary
- color.sell.default
- type.ui.body
- color.text.secondary
- size.icon.sm
- color.buy.default
- color.surface.selected
- color.surface.canvas
- border.hairline
- color.focus.ring
- border.focus
- type.ui.label
- color.surface.raised
- color.sell.subtle
- color.buy.subtle
- space.inset.xs
- space.inset.md
- color.border.default
- radius.control
- radius.badge
- type.ui.caption
- type.ui.body-strong
- radius.card
- space.stack.xs
- color.surface.overlay
- color.status.info.default
- border.thick
- color.surface.app
- color.surface.hover
- color.border.subtle
- space.inset.lg
- color.text.inverse
- type.ui.heading-sm
- space.stack.sm
