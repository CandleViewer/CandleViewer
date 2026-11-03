# E47-D07 / 02 shell-pair-writers

File `E47-D07 boards`, page `E47-D07 announcements`; export `docs/design/E47/img/E47-D07-02-shell-pair-writers.png`; sheet `02-shell-pair-writers.json` (validated); theme dark.

Board 02 of 10 (§0 L67: §2: the shell pair in the DOM, its writers, the local own-action regions). Grid (7000, 0); 3280 x 998 px; "page E47-D07 announcements · board 02 · r1".

## Frames

- `regions∕shell-pair · dark` (§H: `regions/shell-pair · dark`)
- `regions∕local-reply · dark` (§H: `regions/local-reply · dark`)

## Validator and size

- `02-shell-pair-writers.json: 0 errors, 0 warnings, 8 sections, 28165 bytes` (exit 0)
- 8 sections, 28165 bytes

## Live checks (5)

- root 'E47-D07 / 02 shell-pair-writers' at (7000, 0): read back the name exactly after the first section call; size 3280 x 998
- after touchTexts + relayout: the root's h 998 is the measured max(column end, footer end) + 80 (annotation column estimated 629 px); read it back
- frame 'regions∕shell-pair · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'regions∕local-reply · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- export docs/design/E47/img/E47-D07-02-shell-pair-writers.png; record the board id and the PNG size in §0

## Ambiguities (1)

- Board 02: §0 says the board draws "the local own-action regions"; the frame draws §2's four local kinds plus T-17's dialog, the other exception R-1 names, pointing to board 05 for it

## Spec gaps (0)

## Deviations (0)

## Copy keys (1)

- W-27 (§7.2 L305, no source; PROPOSED): Not sent. {reason}.

## Copy gaps (1)

- "Order ticket": the ticket's heading on this diagram (the ticket is E11's; its controls are placeholders here)

## Fallbacks (4)

- kit choice: numbered stop markers, tags, arrows and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI
- kit choice: a diagram board (map, regions, timeline, matrix, anatomy) is a 1280 x 800 specimen frame on color.surface.canvas; its boxes, lanes and bars are annotation drawing, not product UI
- kit choice: the shell chrome (TopBar, NavRail, StatusBar), the other CMP-086 entries and the other SCR-117 sections drawn as neutral placeholders; only this spec's parts are drawn
- kit choice: class tones (assertive danger, status info, ambient neutral, echo selected, silent sunken) are a stripe plus a subtle fill; the class word is always written, so colour is never the only signal (1.4.1)

## Sources (1)

- spec docs/design/E47/E47-D07.md md5 ab7bad64, hand-off docs/design/E47/E47-D07-handoff.md md5 5b74ef6e (§0 L67; hand-off §H L107); scripts docs/design/E47/E47-D07-transcripts.json md5 6bf5c553 replayed through docs/design/_tools/e47_d07_announcement_audit.py md5 8ab6f248; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 48c711e64 (§7.1 there)

## Tokens (32)

- type.ui.body-strong
- color.text.primary
- type.ui.caption
- color.text.secondary
- space.stack.xs
- space.inset.sm
- color.surface.raised
- radius.card
- type.ui.body
- radius.control
- type.num.sm
- space.stack.sm
- color.border.strong
- border.hairline
- color.border.default
- space.inset.md
- color.status.info.default
- size.icon
- type.ui.label
- space.inset.xs
- type.ui.heading-sm
- color.text.inverse
- color.surface.canvas
- color.surface.hover
- color.status.danger.strong
- space.inset.lg
- color.status.danger.subtle
- color.status.info.strong
- color.status.info.subtle
- color.border.selected
- color.surface.selected
- color.text.tertiary
