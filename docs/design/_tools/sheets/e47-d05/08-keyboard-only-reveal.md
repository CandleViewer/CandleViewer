# E47-D05 / 08 keyboard-only-reveal

File `E47-D05 boards`, page `E47-D05 SCR-117`; export `docs/design/E47/img/E47-D05-08-keyboard-only-reveal.png`; sheet `08-keyboard-only-reveal.json` (validated); theme dark.

Board 08 of 10 (§0 L72: §8: one example per kind (order line, drawing point, rule-graph edge), drags inert with their hint). Grid (14000, 4200); 4640 x 1000 px; "page E47-D05 SCR-117 · board 08 · r1".

## Frames

- `reveal∕order-line · dark` (§H: `reveal/order-line · dark`)
- `reveal∕drawing-point · dark` (§H: `reveal/drawing-point · dark`)
- `reveal∕rule-edge · dark` (§H: `reveal/rule-edge · dark`)

## Validator and size

- `08-keyboard-only-reveal.json: 0 errors, 0 warnings, 16 sections, 46445 bytes` (exit 0)
- 16 sections, 46445 bytes

## Live checks (6)

- root 'E47-D05 / 08 keyboard-only-reveal' at (14000, 4200): read back the name exactly after the first section call; size 4640 x 1000
- after touchTexts + relayout: the annotation column (estimated 664 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'reveal∕order-line · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'reveal∕drawing-point · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'reveal∕rule-edge · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D05-08-keyboard-only-reveal.png; record the board id and the PNG size in §0

## Ambiguities (1)

- Board 08: the hosts are not built (S07:8–11) and their forms are E47-D09's: each frame draws the reveal pattern on a synthetic panel (placeholder header, seeded candles), the field labels as copy gaps

## Spec gaps (0)

## Deviations (0)

## Copy keys (2)

- W-20 (§15 L303, PROPOSED): Use the fields to move this.
- W-19 (§15 L302, PROPOSED, label for D07): Drag handles now show fields.

## Copy gaps (3)

- "Stop", "Price": the order line's kind word and its field label (§8.1 names "a price field + step buttons by tick"; the words are E47-D09's)
- "Time", "Price": the drawing point's field labels (§8.1: "x / y fields in time and price")
- "Source", "Target", "Node 1", "Node 2": the edge pickers' labels and two illustrative node names (§8.1: "source and target pickers")

## Fallbacks (3)

- fallback: border.control (E47-D03's D03-D5 / D03-D6, PROPOSED) is not a token yet: control boundaries bind border.hairline in dark and light and border.thick in high contrast
- kit choice: numbered stop markers, tags and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and the other CMP-086 entries drawn as neutral placeholders; only SCR-117's content, its SettingsNav entry and the reveal hosts' named parts are drawn

## Sources (1)

- spec docs/design/E47/E47-D05.md md5 8ea33dd1, hand-off docs/design/E47/E47-D05-handoff.md md5 67b6a7d8 (§0 L72; hand-off §H L97); shipped labels apps/web/src/features/a11y-preferences/AccessibilitySettingsScreen.tsx at 4c662fd5b md5 797df795; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 48c711e64 (§7.1)

## Tokens (41)

- color.status.danger.strong
- type.ui.label
- color.text.primary
- type.num.sm
- space.inset.xs
- color.surface.raised
- radius.control
- type.ui.caption
- color.text.secondary
- color.text.tertiary
- size.icon
- space.inset.sm
- color.candle.wick
- color.candle.down
- color.candle.up
- color.axis.text
- color.surface.canvas
- type.num.base
- color.border.strong
- border.hairline
- color.focus.ring
- border.focus
- color.action.secondary.default
- space.stack.xs
- space.stack.md
- color.surface.overlay
- color.status.info.default
- border.thick
- type.ui.body-strong
- color.surface.hover
- space.inset.md
- space.inset.lg
- radius.card
- color.border.default
- space.inset.xl
- color.surface.app
- color.border.subtle
- color.text.link
- type.ui.body
- type.ui.heading-sm
- space.stack.sm
