# E47-D08 / 02 budget-timeline

File `E47-D08 boards`, page `E47-D08 — Motion`; export `docs/design/E47/img/E47-D08-02-budget-timeline.png`; sheet `02-budget-timeline.json` (validated); theme dark.

Board 02 of 10 (§0 L72: §4.4: the 40 Hz burst on a 0–2 000 ms axis; the requests, the admitted starts per source and the 1 000 ms windows). Grid (7000, 0); 3280 x 1000 px; "page E47-D08 — Motion · board 02 · r1".

## Frames

- `budget∕requests · dark` (§H: `budget/requests · dark`)
- `budget∕admitted · dark` (§H: `budget/admitted · dark`)

## Validator and size

- `02-budget-timeline.json: 0 errors, 1 warnings, 60 sections, 74628 bytes` (exit 0)
- 60 sections, 74628 bytes

## Live checks (5)

- root 'E47-D08 / 02 budget-timeline' at (7000, 0): read back the name exactly after the first section call; size 3280 x 1000
- after touchTexts + relayout: the annotation column (estimated 589 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'budget∕requests · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'budget∕admitted · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D08-02-budget-timeline.png under the dark set; record the board id and the PNG size in §0

## Ambiguities (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (2)

- kit choice: numbered markers, tags, window shading, outlines and callouts are annotation overlays in color.status.info.default (or its subtle tint) with color.text.inverse words, never product UI
- kit choice: time axes and ms ticks are annotation (color.axis.text on a hairline), not product UI

## Sources (1)

- spec docs/design/E47/E47-D08.md md5 6c50afbb, hand-off docs/design/E47/E47-D08-handoff.md md5 dc1307c8 (§0 L72; hand-off §H L99); TICKS packages/fixtures/src/synthetic-ticks.mjs md5 64c3ede9; ring geometry E47-D04 at 1ff5d8cb9 (§7.1); SCR-117 strings E47-D05 at 3987edc89

## Tokens (23)

- color.status.info.subtle
- type.ui.caption
- color.text.secondary
- type.ui.label
- color.text.primary
- space.stack.xs
- color.text.tertiary
- color.buy.default
- color.status.warning.strong
- color.heatmap.bid.5
- color.border.default
- color.axis.text
- type.ui.heading-sm
- color.surface.canvas
- space.inset.xl
- space.stack.md
- color.status.danger.default
- color.text.inverse
- space.inset.xs
- radius.control
- color.status.info.default
- space.stack.sm
- space.inset.lg
