# E47-D07 / 08 verbosity-matrix

File `E47-D07 boards`, page `E47-D07 announcements`; export `docs/design/E47/img/E47-D07-08-verbosity-matrix.png`; sheet `08-verbosity-matrix.json` (validated); theme dark.

Board 08 of 10 (§0 L73: §6.4: announce × verbosity × reduce, what each cell reads, with the replay counts). Grid (14000, 4200); 1920 x 1000 px; "page E47-D07 announcements · board 08 · r1".

## Frames

- `matrix∕verbosity · dark` (§H: `matrix/verbosity · dark`)

## Validator and size

- `08-verbosity-matrix.json: 0 errors, 0 warnings, 11 sections, 23372 bytes` (exit 0)
- 11 sections, 23372 bytes

## Live checks (4)

- root 'E47-D07 / 08 verbosity-matrix' at (14000, 4200): read back the name exactly after the first section call; size 1920 x 1000
- after touchTexts + relayout: the annotation column (estimated 476 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'matrix∕verbosity · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- export docs/design/E47/img/E47-D07-08-verbosity-matrix.png; record the board id and the PNG size in §0

## Ambiguities (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (2)

- kit choice: numbered stop markers, tags, arrows and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI
- kit choice: a diagram board (map, regions, timeline, matrix, anatomy) is a 1280 x 800 specimen frame on color.surface.canvas; its boxes, lanes and bars are annotation drawing, not product UI

## Sources (1)

- spec docs/design/E47/E47-D07.md md5 78bc33e5, hand-off docs/design/E47/E47-D07-handoff.md md5 574b8489 (§0 L73; hand-off §H L107); scripts docs/design/E47/E47-D07-transcripts.json md5 6bf5c553 replayed through docs/design/_tools/e47_d07_announcement_audit.py md5 d6f86dbc; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 1ff5d8cb9 (§7.1 there)

## Tokens (20)

- type.ui.label
- color.text.secondary
- space.inset.sm
- space.inset.xs
- color.surface.raised
- type.ui.body
- color.text.primary
- type.ui.caption
- color.text.tertiary
- type.num.base
- color.surface.selected
- color.status.info.default
- space.stack.xs
- radius.card
- type.ui.heading-sm
- color.text.inverse
- radius.control
- color.surface.canvas
- space.stack.sm
- space.inset.lg
