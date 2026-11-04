# E21-D01 / 07 ranked-decisions

File `E21-D01 boards`, page `E21-D01`; export `docs/design/research/img/E21-D01-07-ranked-decisions.png`; sheet `07-ranked-decisions.json` (validated); theme dark.

Board 07 of eight (memo §0 L78: AD-1..AD-10 with their satisfies / violates clauses (§7)). Grid (7000, 6400); 2400 x 1690 px; "page E21-D01 · board 07 · r1".

## Frames

- `decisions∕AD-1-to-AD-5` (`decisions/AD-1-to-AD-5`)
- `decisions∕AD-6-to-AD-10` (`decisions/AD-6-to-AD-10`)
- `decisions∕kill-list` (`decisions/kill-list`)

## Validator and size

- `07-ranked-decisions.json: 0 errors, 0 warnings, 15 sections, 50487 bytes` (exit 0)
- 15 sections, 299 shapes, 50487 bytes

## Live checks (6)

- root 'E21-D01 / 07 ranked-decisions' at (7000, 6400): read back the name exactly after the first section call; size 2400 x 1690
- after touchTexts + relayout: the annotation column (estimated 583 px with 15 % slack) ends inside the root (h 1690); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'decisions∕AD-1-to-AD-5': read back 1760 x 424 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'decisions∕AD-6-to-AD-10': read back 1760 x 456 at (80, 640); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'decisions∕kill-list': read back 1760 x 368 at (80, 1204); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E21-D01-07-ranked-decisions.png: record the board id and the PNG size

## Derivations (0)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (4)

- memo L161: "Ranked by the cost of getting it wrong on a click-to-trade surface. A wireframe reviewer marks each one satisfied or violated from the frames alone."
- memo L159: "## 7. Adopted decisions AD-1..AD-10 (ranked; heuristic, PROPOSED)"
- memo L178: "Budget #1: "≤16.6ms/frame (60fps) sustained" (06:25). Budget #14: "100ms cadence sustained, 200-depth, ≤1 dropped/coalesced frame per 10s under nominal load" (06:38)."
- memo L176: "## 8. Performance kill-list (budgets #1 and #14; heuristic, PROPOSED)"

## Copy gaps (0)

## Fallbacks (1)

- kit choice: the PROPOSED stamp is the word in a 2 px color.border.strong badge (memo §0: a board that shows a recommendation carries a PROPOSED stamp)

## Sources (2)

- spec (memo) docs/design/research/e21-dom-heatmap.md md5 a95e35c3ab74dfb8b99e5633389d3dad at the boards PR (§0 drawn, §14 As built) (§0 L78)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (20)

- type.ui.body
- color.text.secondary
- type.ui.caption
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
- border.thick
- space.stack.lg
- space.inset.xl
- type.ui.heading-sm
- space.stack.sm
- space.inset.lg
