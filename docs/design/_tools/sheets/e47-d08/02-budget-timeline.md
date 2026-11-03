# E47-D08 / 02 budget-timeline

File `E47-D08 boards`, page `E47-D08 — Motion`; export `docs/design/E47/img/E47-D08-02-budget-timeline.png`; sheet `02-budget-timeline.json` (validated); theme dark.

Board 02 of 10 (§0 L72: §4.4: the 40 Hz burst on a 0–2 000 ms axis; the requests, the admitted starts per source and the 1 000 ms windows). Grid (7000, 0); 3280 x 998 px; "page E47-D08 — Motion · board 02 · r1".

## Frames

- `budget∕requests · dark` (§H: `budget/requests · dark`)
- `budget∕admitted · dark` (§H: `budget/admitted · dark`)

## Validator and size

- `02-budget-timeline.json: 0 errors, 1 warnings, 60 sections, 74899 bytes` (exit 0)
- 60 sections, 74899 bytes

## Live checks (5)

- root 'E47-D08 / 02 budget-timeline' at (7000, 0): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the root's h 998 is max(footer end, annotation column end) + 80 (annotation column estimated 600 px); read it back and raise it to the measured end + 80 if not
- frame 'budget∕requests · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'budget∕admitted · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D08-02-budget-timeline.png under the dark set; record the board id and the PNG size in §0

## Ambiguities (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (3)

- fallback: the direction glyphs ▲ / ▼ drawn as text characters (E05-D03 MR-3's glyph and sign); the liquidation glyph as the local warning icon
- kit choice: numbered markers, tags, window shading, outlines and callouts are annotation overlays in color.status.info.default (or its subtle tint) with color.text.inverse words, never product UI
- kit choice: time axes and ms ticks are annotation (color.axis.text on a hairline), not product UI

## Sources (1)

- spec docs/design/E47/E47-D08.md md5 a935d098, hand-off docs/design/E47/E47-D08-handoff.md md5 e4e1def0 (§0 L72; hand-off §H L99); TICKS packages/fixtures/src/synthetic-ticks.mjs md5 64c3ede9; ring geometry E47-D04 at 48c711e64 (§7.1); SCR-117 strings E47-D05 at 5e4065a44

## Tokens (27)

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
- color.status.info.subtle
- type.ui.label
- color.text.tertiary
- color.status.warning.strong
- color.heatmap.bid.5
- color.axis.text
- type.ui.heading-sm
- space.inset.xl
- space.stack.md
- color.status.danger.default
- color.text.inverse
- radius.control
- color.status.info.default
- space.stack.sm
- space.inset.lg
