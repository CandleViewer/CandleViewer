# E47-D07 / 03 polite-timeline

File `E47-D07 boards`, page `E47-D07 announcements`; export `docs/design/E47/img/E47-D07-03-polite-timeline.png`; sheet `03-polite-timeline.json` (validated); theme dark.

Board 03 of 10 (§0 L68: §6.1: a 10 Hz field, the 2 s cadence, the speech share, latest wins, the composite in fixed order). Grid (14000, 0); 1920 x 1000 px; "page E47-D07 announcements · board 03 · r1".

## Frames

- `timeline∕polite-10hz · dark` (§H: `timeline/polite-10hz · dark`)

## Validator and size

- `03-polite-timeline.json: 0 errors, 0 warnings, 44 sections, 49705 bytes` (exit 0)
- 44 sections, 49705 bytes

## Live checks (4)

- root 'E47-D07 / 03 polite-timeline' at (14000, 0): read back the name exactly after the first section call; size 1920 x 1000
- after touchTexts + relayout: the annotation column (estimated 532 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'timeline∕polite-10hz · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- export docs/design/E47/img/E47-D07-03-polite-timeline.png; record the board id and the PNG size in §0

## Ambiguities (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (1)

- board 03's table headings (#, t (s), rows, composite, estimate, next after) are the kit's words over §10.2's columns and §5.1's estimate

## Fallbacks (4)

- kit choice: a timeline's x scale is linear in milliseconds, its px per second stated on the axis label; bars span [write, write + the §5.1 speech estimate]
- kit choice: class tones (assertive danger, status info, ambient neutral, echo selected, silent sunken) are a stripe plus a subtle fill; the class word is always written, so colour is never the only signal (1.4.1)
- kit choice: numbered stop markers, tags, arrows and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI
- kit choice: a diagram board (map, regions, timeline, matrix, anatomy) is a 1280 x 800 specimen frame on color.surface.canvas; its boxes, lanes and bars are annotation drawing, not product UI

## Sources (1)

- spec docs/design/E47/E47-D07.md md5 78bc33e5, hand-off docs/design/E47/E47-D07-handoff.md md5 574b8489 (§0 L68; hand-off §H L107); scripts docs/design/E47/E47-D07-transcripts.json md5 6bf5c553 replayed through docs/design/_tools/e47_d07_announcement_audit.py md5 d6f86dbc; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 1ff5d8cb9 (§7.1 there)

## Tokens (26)

- type.ui.caption
- color.text.secondary
- color.text.primary
- color.neutral.subtle
- color.neutral.default
- border.hairline
- radius.control
- space.inset.xs
- color.axis.text
- color.surface.sunken
- color.border.subtle
- color.status.danger.subtle
- color.status.danger.strong
- color.text.inverse
- color.status.info.default
- type.num.sm
- color.text.tertiary
- type.ui.label
- space.inset.sm
- color.surface.raised
- space.stack.xs
- radius.card
- type.ui.heading-sm
- color.surface.canvas
- space.stack.sm
- space.inset.lg
