# E47-D07 / 09 transcript-preview

File `E47-D07 boards`, page `E47-D07 announcements`; export `docs/design/E47/img/E47-D07-09-transcript-preview.png`; sheet `09-transcript-preview.json` (validated); theme dark.

Board 09 of 10 (§0 L74: §10: the three transcripts as content for E47-D05's board-07 preview tile (its DoD), not a second tile). Grid (21000, 4200); 4640 x 1000 px; "page E47-D07 announcements · board 09 · r1".

## Frames

- `preview∕quiet · dark` (§H: `preview/quiet · dark`)
- `preview∕fast · dark` (§H: `preview/fast · dark`)
- `preview∕incident · dark` (§H: `preview/incident · dark`)

## Validator and size

- `09-transcript-preview.json: 0 errors, 0 warnings, 17 sections, 47008 bytes` (exit 0)
- 17 sections, 47008 bytes

## Live checks (6)

- root 'E47-D07 / 09 transcript-preview' at (21000, 4200): read back the name exactly after the first section call; size 4640 x 1000
- after touchTexts + relayout: the annotation column (estimated 608 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'preview∕quiet · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'preview∕fast · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'preview∕incident · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D07-09-transcript-preview.png; record the board id and the PNG size in §0

## Ambiguities (1)

- Board 09: the tile's line layout (time · channel · rows over the words) is the kit's; E47-D05's tile (its §6.3) owns the frame, the button and the list semantics

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (3)

- kit choice: the shell chrome (TopBar, NavRail, StatusBar), the other CMP-086 entries and the other SCR-117 sections drawn as neutral placeholders; only this spec's parts are drawn
- fallback: border.control (E47-D03's D03-D5 / D03-D6, PROPOSED) is not a token yet: control boundaries bind border.hairline in dark and light
- kit choice: numbered stop markers, tags, arrows and callouts are annotation overlays in color.status.info.default with color.text.inverse words, never product UI

## Sources (1)

- spec docs/design/E47/E47-D07.md md5 78bc33e5, hand-off docs/design/E47/E47-D07-handoff.md md5 574b8489 (§0 L74; hand-off §H L107); scripts docs/design/E47/E47-D07-transcripts.json md5 6bf5c553 replayed through docs/design/_tools/e47_d07_announcement_audit.py md5 d6f86dbc; tick size packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a; ring geometry E47-D04 at 1ff5d8cb9 (§7.1 there)

## Tokens (32)

- type.ui.heading-sm
- color.text.primary
- radius.control
- color.surface.hover
- space.stack.lg
- type.ui.body-strong
- space.inset.xs
- space.button.paddingX
- color.action.secondary.default
- color.border.strong
- border.hairline
- type.num.sm
- color.text.secondary
- type.ui.caption
- space.stack.xs
- space.stack.sm
- type.ui.label
- space.inset.lg
- color.surface.raised
- radius.card
- color.border.default
- space.inset.xl
- color.surface.app
- color.text.inverse
- color.status.info.default
- color.border.subtle
- space.inset.sm
- color.text.link
- color.border.selected
- space.inset.md
- color.text.tertiary
- color.surface.canvas
