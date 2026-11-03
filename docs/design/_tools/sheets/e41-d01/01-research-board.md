# E41-D01 / 01 research-board

File `E41-D01 boards`, page `E41-D01`; export `docs/design/E41/img/E41-D01-01-research-board.png`; sheet `01-research-board.json` (validated); theme dark.

Board 01 of ten (memo §0 L66: research board — the §1.6 journey and the F → WD map). Grid (0, 0); 2080 x 2615 px; "page E41-D01 · board 01 · r1".

## Frames

- `research∕journey` (`research/journey`)
- `research∕findings-to-decisions` (`research/findings-to-decisions`)
- `research∕walkthroughs` (`research/walkthroughs`)

## Validator and size

- `01-research-board.json: 0 errors, 1 warnings, 29 sections, 86644 bytes` (exit 0)
- 29 sections, 540 shapes, 86644 bytes

## Live checks (6)

- root 'E41-D01 / 01 research-board' at (0, 0): read back the name exactly after the first section call; size 2080 x 2615
- after touchTexts + relayout: the annotation column (estimated 559 px with 15 % slack) ends inside the root (h 2615); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'research∕journey': read back 1440 x 680 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'research∕findings-to-decisions': read back 1440 x 976 at (80, 896); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'research∕walkthroughs': read back 1440 x 504 at (80, 1980); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E41/img/E41-D01-01-research-board.png: record the board id and the PNG size

## Derivations (2)

- journey: `17` L147 — 10 steps in 6 sections, scores verbatim; abandonment rows verbatim
- drawn on: each WD's §6 frame looked up in the board plan (WD-1 board 02, WD-2 board 06, WD-3 board 07, WD-4 board 07, WD-5 board 02, WD-6 board 05, WD-7 board 09, WD-8 board 04, WD-9 board 04, WD-10 board 02, WD-11 board 06, WD-12 board 02, WD-13 board 03, WD-14 board 06)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (0)

## Sources (6)

- spec (memo) docs/design/research/e41-journal-review.md md5 b2629298bc1879afa24b935e0d017f5b at the boards PR (§0 drawn, §12 As built) (§0 L66)
- docs/design/research/e41-d01-session-protocol.md md5 01433dd72a698bca4453a45f12250544 (the session protocol: stimuli, §4a prompts)
- docs/plan/17-ux-diagrams.md md5 0494186310c960cef92f3c614625db44 (`17` §1.6 journey)
- docs/plan/14-screens-catalogue.md at 46e6acd2d md5 1ca288905451c9e5c495a0468c062641 (`14` SCR-093..096 state words the memo cites)
- docs/plan/21-database-schema.md at 46e6acd2d md5 60a9ee1cef41b27a1f0524190b68f199 (`21` §3.7.2 tag categories)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, ETHUSDT tick 0.01, qty step)

## Tokens (22)

- type.ui.body
- color.text.primary
- color.border.strong
- border.hairline
- color.text.secondary
- type.ui.caption
- space.inset.xs
- space.inset.sm
- space.stack.xs
- color.surface.raised
- radius.card
- color.border.default
- type.ui.heading-sm
- space.stack.sm
- color.text.tertiary
- color.surface.canvas
- type.ui.heading-md
- space.inset.md
- type.ui.label
- space.stack.lg
- space.inset.xl
- space.inset.lg
