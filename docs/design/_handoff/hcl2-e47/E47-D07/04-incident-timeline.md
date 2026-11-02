# E47-D07 / 04 incident-timeline

File `E47-D07 boards`, page `E47-D07 announcements`; export `docs/design/E47/img/E47-D07-04-incident-timeline.png`; sheet `04-incident-timeline.json` (validated); theme dark.

Board 04 of 10 (§0 L69: §5.1, §10.3: the queue by rank, the speech estimates, the log row per event, the auto-flatten's persistent toast). Grid (21000, 0); 1920 x 1000 px; "page E47-D07 announcements · board 04 · r1".

## Frames

- `timeline∕incident · dark` (§H: `timeline/incident · dark`)

## Validator and size

- `04-incident-timeline.json: 0 errors, 0 warnings, 9 sections, 21245 bytes` (exit 0)
- 9 sections, 21245 bytes

## Live checks (4)

- root 'E47-D07 / 04 incident-timeline' at (21000, 0): read back the name exactly after the first section call; size 1920 x 1000
- after touchTexts + relayout: the annotation column (estimated 515 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'timeline∕incident · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- export docs/design/E47/img/E47-D07-04-incident-timeline.png; record the board id and the PNG size in §0

## Ambiguities (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (4)

- kit choice: a timeline's x scale is linear in milliseconds, its px per second stated on the axis label; bars span [write, write + the §5.1 speech estimate]
- kit choice: numbered stop markers, tags, arrows and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI
- kit choice: class tones (assertive danger, status info, ambient neutral, echo selected, silent sunken) are a stripe plus a subtle fill; the class word is always written, so colour is never the only signal (1.4.1)
- kit choice: a diagram board (map, regions, timeline, matrix, anatomy) is a 1280 x 800 specimen frame on color.surface.canvas; its boxes, lanes and bars are annotation drawing, not product UI

## Sources (1)

- spec docs/design/E47/E47-D07.md md5 78bc33e5, hand-off docs/design/E47/E47-D07-handoff.md md5 574b8489 (§0 L69; hand-off §H L107); scripts docs/design/E47/E47-D07-transcripts.json md5 6bf5c553 replayed through docs/design/_tools/e47_d07_announcement_audit.py md5 d6f86dbc; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 1ff5d8cb9 (§7.1 there)

## Tokens (28)

- type.ui.caption
- color.text.secondary
- color.text.inverse
- space.inset.xs
- radius.control
- color.status.info.default
- color.text.primary
- color.neutral.subtle
- color.neutral.default
- border.hairline
- color.status.danger.subtle
- color.status.danger.strong
- color.axis.text
- type.num.sm
- color.text.tertiary
- type.ui.label
- space.stack.xs
- space.inset.sm
- space.stack.sm
- color.surface.raised
- radius.card
- size.icon
- type.ui.body
- color.surface.overlay
- color.border.default
- type.ui.heading-sm
- color.surface.canvas
- space.inset.lg
