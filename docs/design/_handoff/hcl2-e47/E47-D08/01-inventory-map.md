# E47-D08 / 01 inventory-map

File `E47-D08 boards`, page `E47-D08 — Motion`; export `docs/design/E47/img/E47-D08-01-inventory-map.png`; sheet `01-inventory-map.json` (validated); theme dark.

Board 01 of 10 (§0 L71: §3 as a surface × tier map: each surface's full, canvas-calm and reduced variant in one cell). Grid (0, 0); 4640 x 1000 px; "page E47-D08 — Motion · board 01 · r1".

## Frames

- `inventory∕full · dark` (§H: `inventory/full · dark`)
- `inventory∕canvas-calm · dark` (§H: `inventory/canvas-calm · dark`)
- `inventory∕reduced · dark` (§H: `inventory/reduced · dark`)

## Validator and size

- `01-inventory-map.json: 0 errors, 1 warnings, 17 sections, 91226 bytes` (exit 0)
- 17 sections, 91226 bytes

## Live checks (9)

- inventory/full · dark: after relayout the tallest map column ends inside the frame (estimated fill 766 of 800 px); if a cell clips, move the last cell of the tallest column to the next column
- inventory/canvas-calm · dark: after relayout the tallest map column ends inside the frame (estimated fill 584 of 800 px); if a cell clips, move the last cell of the tallest column to the next column
- inventory/reduced · dark: after relayout the tallest map column ends inside the frame (estimated fill 649 of 800 px); if a cell clips, move the last cell of the tallest column to the next column
- root 'E47-D08 / 01 inventory-map' at (0, 0): read back the name exactly after the first section call; size 4640 x 1000
- after touchTexts + relayout: the annotation column (estimated 720 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'inventory∕full · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'inventory∕canvas-calm · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'inventory∕reduced · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D08-01-inventory-map.png under the dark set; record the board id and the PNG size in §0

## Ambiguities (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (0)

## Sources (1)

- spec docs/design/E47/E47-D08.md md5 6c50afbb, hand-off docs/design/E47/E47-D08-handoff.md md5 dc1307c8 (§0 L71; hand-off §H L99); TICKS packages/fixtures/src/synthetic-ticks.mjs md5 64c3ede9; ring geometry E47-D04 at 1ff5d8cb9 (§7.1); SCR-117 strings E47-D05 at 3987edc89

## Tokens (16)

- type.ui.heading-sm
- color.text.primary
- type.ui.caption
- color.text.secondary
- space.inset.xs
- color.surface.raised
- radius.control
- color.surface.sunken
- space.stack.xs
- space.inset.sm
- space.stack.sm
- space.inset.xl
- color.surface.canvas
- type.ui.label
- color.text.tertiary
- space.inset.lg
