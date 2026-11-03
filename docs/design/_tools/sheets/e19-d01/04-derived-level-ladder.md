# E19-D01 / 04 derived-level-ladder

File `E19-D01 boards`, page `E19-D01`; export `docs/design/research/img/E19-D01-04-derived-level-ladder.png`; sheet `04-derived-level-ladder.json` (validated); theme dark.

Board 04 of nine (memo §0 L38: §5: labelled vs implied, each level's non-colour cue, in greyscale). Grid (21000, 0); 2080 x 1768 px; "page E19-D01 · board 04 · r1".

## Frames

- `levels∕ladder` (`levels/ladder`)
- `levels∕in-situ-greyscale` (`levels/in-situ-greyscale`)

## Validator and size

- `04-derived-level-ladder.json: 0 errors, 0 warnings, 17 sections, 55652 bytes` (exit 0)
- 17 sections, 340 shapes, 55652 bytes

## Live checks (5)

- root 'E19-D01 / 04 derived-level-ladder' at (21000, 0): read back the name exactly after the first section call; size 2080 x 1768
- after touchTexts + relayout: the annotation column (estimated 951 px with 15 % slack) ends inside the root (h 1768); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'levels∕ladder': read back 1440 x 736 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'levels∕in-situ-greyscale': read back 966 x 672 at (80, 952); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E19-D01-04-derived-level-ladder.png: record the board id and the PNG size

## Derivations (2)

- session 30 Oct as of 14:30 UTC: 35 rows of 50 ticks, POC 63,085.0, VA 63,060.0–63,185.0, HVN 63,205.0, LVN 63,150.0, single prints 63,150.0, 63,225.0, 63,230.0, IB 63,072.6–63,108.6 (periods 00:00–01:00 UTC), TPO max 16 periods
- naked POCs: 29 Oct 63,035.0 (untested through 14:30 UTC), 28 Oct 62,840.0 (untested through 14:30 UTC); the nearest 1 drawn, 1 hidden

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (12)

- memo L150: "POC 62,974.0" (placeholders filled from the world)
- memo L56: "Developing · as of HH:MM UTC" (placeholders filled from the world)
- memo L153: "Value area 70 %"
- memo L91: "Single prints"
- memo L156: "N hidden" (placeholders filled from the world)
- memo L159: ""IB" + its range"
- memo L156: ""nPOC" + the session date at the ray's end"
- memo L146: "point of control"
- memo L146: "value area high"
- memo L146: "value area low"
- memo L154: "high-volume node"
- memo L155: "low-volume node"

## Copy gaps (2)

- "Profile · BTCUSDT": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy)
- "Row size 50 ticks": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy)

## Fallbacks (4)

- kit stand-in (E19-D03 chooses the glyphs, memo §5): HVN = the local chevron-right icon (right-pointing), LVN = a solid 6 px circle, single prints = a solid 2 px bar in the TPO margin, IB = a solid vertical bar left of the TPO strip, nPOC = a solid 1 px ray
- lo-fi: a profile is drawn from the derived rows as rects (one per row, width = volume / the POC row's volume); every row has the same fill (color.text.tertiary), so no level is carried by fill (PD-3); the cues are solid rails, ticks, brackets and glyphs in color.text.primary
- lo-fi: the TPO strip draws each row's TPO count as a solid bar 4 px per period (a stand-in for the letters; CMP-184 draws letters)
- kit choice: a string a screen reader hears (an accessible name, the DOM mirror) is drawn as caption text in a 'dashed · ' outline

## Sources (3)

- spec (memo) docs/design/research/e19-profiles.md md5 d4e666a3f87a41724547a89a1615d062 at the boards PR (§0 drawn, §13 As built) (§0 L38)
- docs/plan/05-accessibility-standard.md at ca49e693a md5 16c60e646337d48dac83c9fb46f8a239 (`05` §6 profile table: the columns A-6 extends)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (25)

- color.text.primary
- size.icon
- type.ui.caption
- color.text.secondary
- color.text.tertiary
- space.inset.sm
- space.inset.xs
- color.surface.raised
- color.border.default
- color.surface.canvas
- space.stack.xs
- type.ui.body
- space.inset.md
- space.stack.sm
- radius.card
- border.hairline
- type.ui.label
- type.ui.body-strong
- color.border.strong
- space.stack.lg
- space.inset.xl
- color.surface.sunken
- radius.control
- space.inset.lg
- type.ui.heading-sm
