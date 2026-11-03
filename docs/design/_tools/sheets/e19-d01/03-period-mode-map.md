# E19-D01 / 03 period-mode-map

File `E19-D01 boards`, page `E19-D01`; export `docs/design/research/img/E19-D01-03-period-mode-map.png`; sheet `03-period-mode-map.json` (validated); theme dark.

Board 03 of nine (memo §0 L37: §6.1: the four source vocabularies onto the five user-facing modes and the 24 kinds). Grid (14000, 0); 2080 x 1376 px; "page E19-D01 · board 03 · r1".

## Frames

- `modes∕vocabulary-map` (`modes/vocabulary-map`)
- `modes∕defaults-and-switcher` (`modes/defaults-and-switcher`)

## Validator and size

- `03-period-mode-map.json: 0 errors, 0 warnings, 12 sections, 41079 bytes` (exit 0)
- 12 sections, 218 shapes, 41079 bytes

## Live checks (5)

- root 'E19-D01 / 03 period-mode-map' at (14000, 0): read back the name exactly after the first section call; size 2080 x 1376
- after touchTexts + relayout: the annotation column (estimated 890 px with 15 % slack) ends inside the root (h 1376); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'modes∕vocabulary-map': read back 1440 x 576 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'modes∕defaults-and-switcher': read back 1440 x 440 at (80, 792); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E19-D01-03-period-mode-map.png: record the board id and the PNG size

## Derivations (1)

- menu items: memo §6.1's five modes in order, each with its `24` kind cell (Anchored: none — A-1)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (1)

- memo L181: "it follows the viewport the trader is already reading"

## Copy gaps (6)

- "Profile · BTCUSDT": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy)
- "Volume profile": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy)
- "Period mode": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy)
- "Docked panel — opens on Session (the UTC day)": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy) — board label summarising memo §6.2
- "Chart overlay — opens on Visible range": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy) — board label summarising memo §6.2
- "SCR-039 settings dialog — keeps its radio group": kit label, not in the memo (PROPOSED; E19-D02 / E19-D03 write the copy) — board label summarising memo §6.2

## Fallbacks (0)

## Sources (3)

- spec (memo) docs/design/research/e19-profiles.md md5 d4e666a3f87a41724547a89a1615d062 at the boards PR (§0 drawn, §13 As built) (§0 L37)
- docs/plan/05-accessibility-standard.md at ca49e693a md5 16c60e646337d48dac83c9fb46f8a239 (`05` §6 profile table: the columns A-6 extends)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (28)

- type.ui.caption
- color.text.secondary
- color.text.tertiary
- space.inset.sm
- space.inset.xs
- color.surface.raised
- color.border.default
- color.text.primary
- color.surface.canvas
- space.stack.xs
- type.ui.label
- radius.badge
- color.border.strong
- border.hairline
- space.inset.md
- space.stack.sm
- radius.card
- space.inset.lg
- type.ui.body
- space.stack.lg
- space.inset.xl
- type.ui.body-strong
- size.icon
- radius.control
- color.surface.sunken
- color.surface.selected
- color.surface.overlay
- type.ui.heading-sm
