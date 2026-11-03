# E47-D09 / 04 node-move

File `E47-D09 boards`, page `E47-D09`; export `docs/design/E47/img/E47-D09-04-node-move.png`; sheet `04-node-move.json` (validated); theme dark.

Board 04 of ten (§0 L71: SCR-082 Move mode: entry, a step, the view following, Enter, Esc and the 200 % inset (§7)). Grid (18000, 0); 4640 x 1878 px; "page E47-D09 · board 04 · r1".

## Frames

- `node∕move-mode · dark`
- `node∕view-follows · dark`
- `node∕placed · dark`
- `node∕escaped · dark`
- `node∕move-mode-200 · dark`

## Validator and size

- `04-node-move.json: 0 errors, 1 warnings, 56 sections, 173089 bytes` (exit 0)
- 56 sections, 173089 bytes

## Live checks (8)

- root 'E47-D09 / 04 node-move' at (18000, 0): read back the name exactly after the first section call; size 4640 x 1878
- after touchTexts + relayout: the root's h 1878 is the measured max(column end, footer end) + 80 (annotation column estimated 1148 px); read it back
- frame 'node∕move-mode · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'node∕view-follows · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'node∕placed · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- frame 'node∕escaped · dark': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'node∕move-mode-200 · dark': read back 1280 x 800 at (1440, 960); clip on, no child spills
- export docs/design/E47/img/E47-D09-04-node-move.png: every frame is 1280 x 800; record the board id and the PNG size

## Readings (2)

- one layout step (D09-G6, undefined) is drawn as one 24 px grid cell; W-15's column / row count cells from the canvas origin, so a scrolled view does not renumber them
- the 200 % inset draws two 640 CSS px strips (E47-D03 board 05's method): text 100 % and the 150 % text scale; the inset is a full 1280 x 800 frame like the others

## G rows (1)

- D09-G6 (§19.2 L422): the rule canvas defines no layout step for a keyboard node move (owner E37-D04, the node editor's review)

## C rows (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (3)

- W-16 (§16 L321, PROPOSED)
- W-15 (§16 L320, PROPOSED)
- W-4 (§16 L309, PROPOSED (a local object, K-5))

## Copy gaps (1)

- "ATR trail 2x", the node words, "Form", "Graph", the palette groups (Triggers, Metrics, Logic, Actions) and "Validate", "Simulate", "Save": `14` SCR-082's wireframe (`14`:1931-1946), synthetic

## Fallbacks (6)

- kit choice: numbered stop markers, tags, outlines, arrows and callouts are annotation overlays in color.status.info.default (callouts on color.surface.overlay), never product UI; a callout quotes what is spoken (polite) or what a key does
- kit choice for D09-G6 (no layout step is defined for the rule canvas): the canvas grid is 24 px and one layout step = one grid cell; column / row in W-15 count cells from the canvas origin
- kit choice: the shell chrome not under study (wordmark, pickers, health chips, rail glyphs, tab labels, RightRail rows, StatusBar items, list rows of SCR-093) drawn as neutral placeholders; only what this spec names is drawn with words
- kit choice: compact density (§0) at 24 px controls and rows (size.control.compact, size.row.compact); SCR-012's rows 32 px (E10-D03 §6.1, D03E10:281: 32 compact, 40 comfortable); the shell bars keep E10's 48 px TopBar
- kit choice (E47-D03 board 05's): at 200 % the 1280 x 800 window is a 640 x 400 CSS px viewport; the inset draws the 640 CSS px layout at 1:1 in a 640 px strip with the 400 px viewport outlined; the device shows it at 2 x
- fallback (E47-D03's FALLBACKS type-150): no type token at a 150 % text scale: each role is drawn with the token nearest 1.5 x its size (caption 11 -> heading-md 16, label 12 / body 13 -> heading-lg 20, heading-sm 14 / heading-md 16 -> display 24, num.xs 11 -> heading-md 16)

## Sources (1)

- spec docs/design/E47/E47-D09.md md5 8e2c7257 (§0 L71); hand-off docs/design/E47/E47-D09-handoff.md md5 bbb18e25 (§H L105); registry at 4c662fd5b apps/web/src/keymap/keymap.json md5 eb409e85 and apps/web/src/keymap/reserved-keys.json md5 5683c37f; tick size: packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a

## Tokens (46)

- type.ui.label
- color.text.inverse
- color.status.info.default
- radius.badge
- color.text.primary
- type.ui.caption
- space.stack.xs
- space.inset.sm
- color.surface.overlay
- radius.control
- border.thick
- color.grid.line
- color.border.strong
- color.node.trigger
- type.ui.body-strong
- color.text.secondary
- color.surface.raised
- color.border.default
- border.hairline
- radius.card
- color.node.condition
- color.node.logic
- color.surface.canvas
- color.focus.ring
- border.focus
- color.node.action
- color.status.info.strong
- size.icon
- type.ui.body
- space.inset.md
- type.ui.heading-sm
- space.inset.xs
- space.button.paddingX
- color.action.secondary.default
- space.inset.lg
- color.surface.app
- color.surface.hover
- space.stack.sm
- color.surface.selected
- color.border.subtle
- color.env.live
- color.status.danger.subtle
- color.status.danger.strong
- type.ui.heading-lg
- type.ui.display
- color.text.tertiary
