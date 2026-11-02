# E47-D07 / 01 taxonomy-map

File `E47-D07 boards`, page `E47-D07 announcements`; export `docs/design/E47/img/E47-D07-01-taxonomy-map.png`; sheet `01-taxonomy-map.json` (validated); theme dark.

Board 01 of 10 (§0 L66: §3, §4: the five classes, the ranks and every T-row grouped by panel class). Grid (0, 0); 1920 x 1000 px; "page E47-D07 announcements · board 01 · r1".

## Frames

- `taxonomy∕map · dark` (§H: `taxonomy/map · dark`)

## Validator and size

- `01-taxonomy-map.json: 0 errors, 0 warnings, 22 sections, 40843 bytes` (exit 0)
- 22 sections, 40843 bytes

## Live checks (4)

- root 'E47-D07 / 01 taxonomy-map' at (0, 0): read back the name exactly after the first section call; size 1920 x 1000
- after touchTexts + relayout: the annotation column (estimated 476 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'taxonomy∕map · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- export docs/design/E47/img/E47-D07-01-taxonomy-map.png; record the board id and the PNG size in §0

## Ambiguities (1)

- Board 01: §4's event cells carry a trailing source cite in parentheses; the map drops it (the cite is in each line's note) so a line fits a column

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (3)

- kit choice: class tones (assertive danger, status info, ambient neutral, echo selected, silent sunken) are a stripe plus a subtle fill; the class word is always written, so colour is never the only signal (1.4.1)
- kit choice: numbered stop markers, tags, arrows and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI
- kit choice: a diagram board (map, regions, timeline, matrix, anatomy) is a 1280 x 800 specimen frame on color.surface.canvas; its boxes, lanes and bars are annotation drawing, not product UI

## Sources (1)

- spec docs/design/E47/E47-D07.md md5 78bc33e5, hand-off docs/design/E47/E47-D07-handoff.md md5 574b8489 (§0 L66; hand-off §H L107); scripts docs/design/E47/E47-D07-transcripts.json md5 6bf5c553 replayed through docs/design/_tools/e47_d07_announcement_audit.py md5 d6f86dbc; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 1ff5d8cb9 (§7.1 there)

## Tokens (26)

- type.ui.body-strong
- color.text.primary
- type.ui.caption
- color.text.secondary
- space.stack.xs
- space.inset.sm
- space.inset.xs
- color.status.danger.strong
- color.status.danger.subtle
- radius.control
- color.status.info.strong
- color.status.info.subtle
- color.neutral.default
- color.neutral.subtle
- color.border.selected
- color.surface.selected
- color.border.subtle
- color.surface.sunken
- type.ui.label
- color.text.inverse
- color.status.info.default
- color.surface.canvas
- type.ui.heading-sm
- color.text.tertiary
- space.stack.sm
- space.inset.lg
