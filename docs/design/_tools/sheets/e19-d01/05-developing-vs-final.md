# E19-D01 / 05 developing-vs-final

File `E19-D01 boards`, page `E19-D01`; export `docs/design/research/img/E19-D01-05-developing-vs-final.png`; sheet `05-developing-vs-final.json` (validated); theme dark.

Board 05 of nine (memo §0 L39: §6.3, PD-1: the header words and the open-ended bracket beside the final state). Grid (28000, 0); 1708 x 932 px; "page E19-D01 · board 05 · r1".

## Frames

- `developing∕as-of` (`developing/as-of`)
- `developing∕final` (`developing/final`)

## Validator and size

- `05-developing-vs-final.json: 0 errors, 0 warnings, 11 sections, 30008 bytes` (exit 0)
- 11 sections, 174 shapes, 30008 bytes

## Live checks (5)

- root 'E19-D01 / 05 developing-vs-final' at (28000, 0): read back the name exactly after the first section call; size 1708 x 932
- after touchTexts + relayout: the annotation column (estimated 890 px with 15 % slack) ends inside the root (h 932); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'developing∕as-of': read back 494 x 632 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'developing∕final': read back 494 x 680 at (654, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E19-D01-05-developing-vs-final.png: record the board id and the PNG size

## Derivations (2)

- session 30 Oct: developing, as of 14:30 UTC; 29 periods; POC 63,085.0, VA 63,060.0–63,185.0
- session 29 Oct: complete; 48 periods; POC 63,035.0, VA 62,975.0–63,075.0

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (6)

- memo L158: "an open-ended value-area bracket (no end cap) while developing"
- memo L150: "POC 62,974.0" (placeholders filled from the world)
- memo L56: "Developing · as of HH:MM UTC" (placeholders filled from the world)
- memo L153: "Value area 70 %"
- memo L185: "at close the words become "Final" and the bracket closes"
- memo L56: "Final"

## Copy gaps (2)

- "Profile · BTCUSDT": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy)
- "Row size 50 ticks": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy)

## Fallbacks (2)

- lo-fi: a profile is drawn from the derived rows as rects (one per row, width = volume / the POC row's volume); every row has the same fill (color.text.tertiary), so no level is carried by fill (PD-3); the cues are solid rails, ticks, brackets and glyphs in color.text.primary
- kit choice: board markers (measurements, reading notes, crossed-out examples) are caption text in a 'dashed · ' outline (board markers, not product UI)

## Sources (3)

- spec (memo) docs/design/research/e19-profiles.md md5 d4e666a3f87a41724547a89a1615d062 at the boards PR (§0 drawn, §13 As built) (§0 L39)
- docs/plan/05-accessibility-standard.md at ca49e693a md5 16c60e646337d48dac83c9fb46f8a239 (`05` §6 profile table: the columns A-6 extends)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (22)

- color.text.tertiary
- color.text.primary
- type.ui.label
- type.ui.body-strong
- color.surface.sunken
- color.border.default
- border.hairline
- color.text.secondary
- size.icon
- space.inset.sm
- space.inset.xs
- radius.control
- type.ui.caption
- space.inset.md
- space.inset.lg
- color.surface.raised
- space.stack.sm
- color.surface.canvas
- space.stack.xs
- space.stack.lg
- space.inset.xl
- type.ui.heading-sm
