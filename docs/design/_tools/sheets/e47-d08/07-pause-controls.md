# E47-D08 / 07 pause-controls

File `E47-D08 boards`, page `E47-D08 — Motion`; export `docs/design/E47/img/E47-D08-07-pause-controls.png`; sheet `07-pause-controls.json` (validated); theme dark.

Board 07 of 10 (§0 L77: §8: the replay transport, the tape pause and the follow-live toggle with focus, state and W-4 / W-6). Grid (7000, 4200); 4640 x 998 px; "page E47-D08 — Motion · board 07 · r1".

## Frames

- `pause∕replay · dark` (§H: `pause/replay · dark`)
- `pause∕tape · dark` (§H: `pause/tape · dark`)
- `pause∕follow-live · dark` (§H: `pause/follow-live · dark`)

## Validator and size

- `07-pause-controls.json: 0 errors, 1 warnings, 100 sections, 96522 bytes` (exit 0)
- 100 sections, 96522 bytes

## Live checks (6)

- root 'E47-D08 / 07 pause-controls' at (7000, 4200): read back the name exactly after the first section call; size 4640 x 998
- after touchTexts + relayout: the root's h 998 is max(footer end, annotation column end) + 80 (annotation column estimated 682 px); read it back and raise it to the measured end + 80 if not
- frame 'pause∕replay · dark': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'pause∕tape · dark': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'pause∕follow-live · dark': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D08-07-pause-controls.png under the dark set; record the board id and the PNG size in §0

## Ambiguities (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (6)

- W-6 (§15 L327, verbatim (replay; unchanged)): Paused at 13:38:04
- W-7 (§15 L328, verbatim (replay; the speed varies)): Playing at 4 times
- W-8 (§15 L329, PROPOSED; D08-C11; words E47-D07): Tape paused
- W-9 (§15 L330, PROPOSED; D08-C11; words E47-D07): Tape resumed
- W-4 (§15 L325, PROPOSED; D08-C3): Not following live — viewing hh:mm
- W-10 (§15 L331, PROPOSED; D08-C3; words E47-D07): Following live

## Copy gaps (0)

## Fallbacks (3)

- fallback: the direction glyphs ▲ / ▼ drawn as text characters (E05-D03 MR-3's glyph and sign); the liquidation glyph as the local warning icon
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and panels outside the board's subject are neutral placeholders; only the surfaces a board draws are drawn
- kit choice: numbered markers, tags, window shading, outlines and callouts are annotation overlays in color.status.info.default (or its subtle tint) with color.text.inverse words, never product UI

## Sources (1)

- spec docs/design/E47/E47-D08.md md5 a935d098, hand-off docs/design/E47/E47-D08-handoff.md md5 e4e1def0 (§0 L77; hand-off §H L99); TICKS packages/fixtures/src/synthetic-ticks.mjs md5 64c3ede9; ring geometry E47-D04 at 48c711e64 (§7.1); SCR-117 strings E47-D05 at 5e4065a44

## Tokens (45)

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
- color.grid.line
- color.candle.wick
- color.candle.up
- color.candle.down
- type.num.sm
- color.axis.text
- type.ui.body-strong
- radius.control
- color.surface.hover
- color.border.subtle
- border.hairline
- color.status.info.strong
- border.thick
- type.ui.label
- radius.badge
- color.status.info.subtle
- space.button.paddingX
- color.action.secondary.default
- color.border.strong
- color.focus.ring
- border.focus
- space.inset.md
- color.surface.overlay
- color.status.info.default
- color.surface.app
- space.inset.lg
- color.surface.selected
- color.status.warning.subtle
- color.status.warning.strong
- color.sell.default
- type.ui.heading-sm
- color.text.tertiary
- space.stack.sm
