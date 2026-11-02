# E47-D08 / 06 heatmap-tiers

File `E47-D08 boards`, page `E47-D08 — Motion`; export `docs/design/E47/img/E47-D08-06-heatmap-tiers.png`; sheet `06-heatmap-tiers.json` (validated); theme dark.

Board 06 of 10 (§0 L76: §7: a heatmap column with its trail in full, canvas calm and reduced; the held live-column cell). Grid (0, 4200); 4640 x 1000 px; "page E47-D08 — Motion · board 06 · r1".

## Frames

- `heatmap∕full · dark` (§H: `heatmap/full · dark`)
- `heatmap∕canvas-calm · dark` (§H: `heatmap/canvas-calm · dark`)
- `heatmap∕reduced · dark` (§H: `heatmap/reduced · dark`)

## Validator and size

- `06-heatmap-tiers.json: 0 errors, 1 warnings, 140 sections, 231916 bytes` (exit 0)
- 140 sections, 231916 bytes

## Live checks (6)

- root 'E47-D08 / 06 heatmap-tiers' at (0, 4200): read back the name exactly after the first section call; size 4640 x 1000
- after touchTexts + relayout: the annotation column (estimated 760 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'heatmap∕full · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'heatmap∕canvas-calm · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'heatmap∕reduced · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D08-06-heatmap-tiers.png under the dark set; record the board id and the PNG size in §0

## Ambiguities (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (3)

- fallback: the heatmap trail's age-based fade (no hi-fi spec, D08-G1) drawn as stepped ramp tokens color.heatmap.bid.1-5, one step dimmer per older column; the instant mode maps true size to the step
- kit choice: numbered markers, tags, window shading, outlines and callouts are annotation overlays in color.status.info.default (or its subtle tint) with color.text.inverse words, never product UI
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and panels outside the board's subject are neutral placeholders; only the surfaces a board draws are drawn

## Sources (1)

- spec docs/design/E47/E47-D08.md md5 6c50afbb, hand-off docs/design/E47/E47-D08-handoff.md md5 dc1307c8 (§0 L76; hand-off §H L99); TICKS packages/fixtures/src/synthetic-ticks.mjs md5 64c3ede9; ring geometry E47-D04 at 1ff5d8cb9 (§7.1); SCR-117 strings E47-D05 at 3987edc89

## Tokens (34)

- color.heatmap.zero
- color.heatmap.bid.1
- color.heatmap.bid.2
- color.heatmap.bid.3
- color.heatmap.bid.4
- color.heatmap.bid.5
- color.status.info.default
- border.thick
- color.surface.canvas
- type.num.sm
- color.axis.text
- type.ui.caption
- type.ui.body-strong
- color.text.primary
- radius.control
- color.surface.hover
- space.inset.sm
- color.surface.raised
- color.border.subtle
- border.hairline
- type.ui.body
- space.inset.xs
- type.num.base
- type.ui.label
- color.text.secondary
- color.border.default
- space.stack.xs
- space.stack.sm
- type.ui.heading-sm
- space.stack.md
- space.inset.lg
- color.surface.app
- space.inset.md
- color.text.tertiary
