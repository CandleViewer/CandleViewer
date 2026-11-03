# E47-D08 / 09 safety-static

File `E47-D08 boards`, page `E47-D08 — Motion`; export `docs/design/E47/img/E47-D08-09-safety-static.png`; sheet `09-safety-static.json` (validated); theme dark.

Board 09 of 10 (§0 L79: §11: env banner and badge, freeze banner, arm toggle (T2 inset, §12) and status-bar counts under reduce; hc twin). Grid (21000, 4200); 3280 x 998 px; "page E47-D08 — Motion · board 09 · r1". Twin export: theme hc; export `docs/design/E47/img/E47-D08-09-safety-static-high-contrast.png` (the same sheet; frame `safety∕reduced · hc` is the evidence).

## Frames

- `safety∕reduced · dark` (§H: `safety/reduced · dark`)
- `safety∕reduced · hc` (§H: `safety/reduced · hc`)

## Validator and size

- `09-safety-static.json: 0 errors, 1 warnings, 66 sections, 86148 bytes` (exit 0)
- 66 sections, 86148 bytes

## Live checks (6)

- root 'E47-D08 / 09 safety-static' at (21000, 4200): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the root's h 998 is max(footer end, annotation column end) + 80 (annotation column estimated 647 px); read it back and raise it to the measured end + 80 if not
- frame 'safety∕reduced · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'safety∕reduced · hc': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D08-09-safety-static.png under the dark set; record the board id and the PNG size in §0
- twin: activate the high contrast token set, read back one bound fill (color.surface.canvas) as its high contrast value, export the board again to docs/design/E47/img/E47-D08-09-safety-static-high-contrast.png (frame 'safety∕reduced · hc' is the evidence there, the dark frame in the first export), then restore the dark set

## Ambiguities (1)

- A-1: §0 L79 plans a dark and a high contrast frame on one board while the token set is file-wide: read as one token-bound board exported twice (dark, then high contrast to docs/design/E47/img/E47-D08-09-safety-static-high-contrast.png); the export name adds the theme word to §0 L67's NN-<slug> pattern

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (2)

- CMP-208's words "Kill switch: engaged" and "Armed rules: 2" are kit labels: §11 names "the kill-switch glyph and its word; the count as text" without the words
- CMP-117's banner reads FROZEN + `15` L1420's open-ended line as its reason (§11 gives no reason text)

## Fallbacks (3)

- fallback: the direction glyphs ▲ / ▼ drawn as text characters (E05-D03 MR-3's glyph and sign); the liquidation glyph as the local warning icon
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and panels outside the board's subject are neutral placeholders; only the surfaces a board draws are drawn
- fallback: the environment glyph (CMP-074 / CMP-075) drawn as a filled ellipse in color.env.live inside a ring (no env icon in the local set)

## Sources (1)

- spec docs/design/E47/E47-D08.md md5 a935d098, hand-off docs/design/E47/E47-D08-handoff.md md5 e4e1def0 (§0 L79; hand-off §H L99); TICKS packages/fixtures/src/synthetic-ticks.mjs md5 64c3ede9; ring geometry E47-D04 at 48c711e64 (§7.1); SCR-117 strings E47-D05 at 5e4065a44

## Tokens (37)

- type.num.base
- color.text.primary
- color.buy.default
- type.ui.body
- space.inset.sm
- space.inset.xs
- color.surface.canvas
- color.surface.raised
- type.ui.caption
- color.text.secondary
- color.border.default
- space.stack.xs
- color.text.tertiary
- size.icon
- type.ui.label
- radius.control
- border.hairline
- color.grid.line
- color.candle.wick
- color.candle.up
- color.candle.down
- type.num.sm
- color.axis.text
- type.ui.body-strong
- color.surface.hover
- color.border.subtle
- color.env.live
- border.thick
- space.inset.lg
- color.status.danger.subtle
- color.status.danger.strong
- space.stack.md
- radius.badge
- space.inset.md
- color.surface.app
- type.ui.heading-sm
- space.stack.sm
