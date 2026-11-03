# E19-D01 / 06 approximated-partial-strip

File `E19-D01 boards`, page `E19-D01`; export `docs/design/research/img/E19-D01-06-approximated-partial-strip.png`; sheet `06-approximated-partial-strip.json` (validated); theme dark.

Board 06 of nine (memo §0 L40: §6.4–§6.5, PD-4, PD-5: the header status slot with CMP-011 and CMP-227, the hatched approximated rows). Grid (0, 5200); 3054 x 1095 px; "page E19-D01 · board 06 · r1".

## Frames

- `status∕approximated-session` (`status/approximated-session`)
- `status∕partial-composite` (`status/partial-composite`)
- `status∕header-slot` (`status/header-slot`)

## Validator and size

- `06-approximated-partial-strip.json: 0 errors, 0 warnings, 14 sections, 54169 bytes` (exit 0)
- 14 sections, 283 shapes, 54169 bytes

## Live checks (6)

- root 'E19-D01 / 06 approximated-partial-strip' at (0, 5200): read back the name exactly after the first section call; size 3054 x 1095
- after touchTexts + relayout: the annotation column (estimated 1151 px with 15 % slack) ends inside the root (h 1095); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'status∕approximated-session': read back 606 x 544 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'status∕partial-composite': read back 888 x 696 at (766, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'status∕header-slot': read back 760 x 296 at (1734, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E19-D01-06-approximated-partial-strip.png: record the board id and the PNG size

## Derivations (2)

- session 28 Oct: periods before 09:00 UTC are approximated from bars (the memo's uniform rule); 17 of 22 rows carry approximated volume and are hatched; delta drawn from the 30 recorded periods only; POC 62,840.0
- composite: requested 25 Oct, 26 Oct, 27 Oct, 28 Oct, 29 Oct; recorded trades on 28 Oct, 29 Oct (28 Oct from 09:00 UTC, its morning approximated from bars); nothing kept for 25–27 Oct; POC 62,840.0, VA 62,825.0–62,995.0

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (8)

- memo L150: "POC 62,974.0" (placeholders filled from the world)
- memo L56: "Final"
- memo L57: "(estimated)"
- memo L4: "approximated from bars"
- memo L189: "Delta not available before 09:00 UTC" (placeholders filled from the world)
- memo L153: "Value area 70 %"
- memo L193: "Partial: {n} of {m} requested days recorded" (placeholders filled from the world)
- memo L193: "at least 4 px apart, each with its own accessible name"

## Copy gaps (4)

- "Profile · BTCUSDT": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy)
- "Row size 50 ticks": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy)
- "Covered 28 Oct–29 Oct 2026 (2 of 5 requested sessions)": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy) — the covered-range words; G-4 has no carrier yet
- "Estimated, approximated from bars": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy) — CMP-227's name pattern "Estimated, <display name>" (`15`) with the memo's methodology words

## Fallbacks (5)

- lo-fi: a profile is drawn from the derived rows as rects (one per row, width = volume / the POC row's volume); every row has the same fill (color.text.tertiary), so no level is carried by fill (PD-3); the cues are solid rails, ticks, brackets and glyphs in color.text.primary
- lo-fi stand-in: pattern.hatch.estimated is a registered pattern id (`16` §6 rule 4), not a Penpot token; approximated rows are drawn as hollow bars with an inner dashed outline ('dashed · ' name, dashed by the post-step); E19-D03 binds the pattern
- research board: CMP-011 info and CMP-227 are drawn as bordered greyscale pills with their words; the status hues (color.status.info.*) are not bound (greyscale, memo §0)
- kit choice: board markers (measurements, reading notes, crossed-out examples) are caption text in a 'dashed · ' outline (board markers, not product UI)
- kit choice: a string a screen reader hears (an accessible name, the DOM mirror) is drawn as caption text in a 'dashed · ' outline

## Sources (3)

- spec (memo) docs/design/research/e19-profiles.md md5 d4e666a3f87a41724547a89a1615d062 at the boards PR (§0 drawn, §13 As built) (§0 L40)
- docs/plan/05-accessibility-standard.md at ca49e693a md5 16c60e646337d48dac83c9fb46f8a239 (`05` §6 profile table: the columns A-6 extends)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (25)

- color.border.strong
- color.text.secondary
- color.text.tertiary
- border.hairline
- color.text.primary
- type.ui.label
- type.ui.body-strong
- color.surface.sunken
- color.border.default
- size.icon
- space.inset.sm
- space.inset.xs
- radius.control
- type.ui.caption
- radius.badge
- border.thick
- color.surface.raised
- space.inset.lg
- space.inset.md
- space.stack.sm
- color.surface.canvas
- space.stack.xs
- space.stack.lg
- space.inset.xl
- type.ui.heading-sm
