# E21-D01 / 02 centring-modes

File `E21-D01 boards`, page `E21-D01`; export `docs/design/research/img/E21-D01-02-centring-modes.png`; sheet `02-centring-modes.json` (validated); theme dark.

Board 02 of eight (memo §0 L73: auto-follow, free-scroll and centre lock as state strips (§6)). Grid (7000, 0); 2320 x 2591 px; "page E21-D01 · board 02 · r1".

## Frames

- `centring∕auto-follow` (`centring/auto-follow`)
- `centring∕free-scroll` (`centring/free-scroll`)
- `centring∕centre-lock` (`centring/centre-lock`)

## Validator and size

- `02-centring-modes.json: 0 errors, 1 warnings, 129 sections, 310732 bytes` (exit 0)
- 129 sections, 2107 shapes, 310732 bytes

## Live checks (6)

- root 'E21-D01 / 02 centring-modes' at (7000, 0): read back the name exactly after the first section call; size 2320 x 2591
- after touchTexts + relayout: the annotation column (estimated 1157 px with 15 % slack) ends inside the root (h 2591); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'centring∕auto-follow': read back 1680 x 624 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'centring∕free-scroll': read back 1680 x 664 at (80, 840); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'centring∕centre-lock': read back 1680 x 848 at (80, 1612); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E21-D01-02-centring-modes.png: record the board id and the PNG size

## Derivations (3)

- auto-follow snapshots: update 0 and each update that takes the mark to a new distance from the centre (0, 1, 4, 5, 6, 13); the mark enters the band (|offset| ≥ 7 rows) at update 13 (+650 ms) and the ladder re-centres once, on 70,000.70
- free-scroll: a 6-row scroll down puts the view centre on 69,999.40 (rows 69,998.60–70,000.20); the mark walks 70,000.00 → 70,000.20 (update 3, the last in view) and leaves the view at update 4; no re-centre; Space centres on 70,000.70
- centre lock: updates 0, 1, 4, 5, 6 (each moves the mark); the pointer stays on screen row 6 and the price under it is 70,000.30 → 70,000.50 → 70,000.60 → 70,000.70 → 70,000.90

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (5)

- memo L25: "auto-follow"
- memo L152: "auto-follow with an edge-band trigger; a manual scroll suspends it visibly (free-scroll); Space resumes"
- memo L73: "free-scroll"
- memo L101: "Space = re-centre + resume auto-follow"
- memo L55: "centre lock"

## Copy gaps (4)

- "price": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — ladder column heading
- "size": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — ladder column heading; asks above the mark, bids below
- "moves every row on every update": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — AD-8's every-update-motion caveat
- "Centring": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — SCR-051 setting label (E21-D03 #503)

## Fallbacks (3)

- lo-fi: the mark (last price) row is a color.surface.selected fill with a 2 px color.text.primary edge and the word 'mark' (board marker)
- lo-fi: bid and ask are told apart by position (asks above the mark, bids below) and by the column heading, never by a hue (the bid/ask hue is user-configurable, F-16)
- kit choice: the PROPOSED stamp is the word in a 2 px color.border.strong badge (memo §0: a board that shows a recommendation carries a PROPOSED stamp)

## Sources (2)

- spec (memo) docs/design/research/e21-dom-heatmap.md md5 a95e35c3ab74dfb8b99e5633389d3dad at the boards PR (§0 drawn, §14 As built) (§0 L73)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (29)

- type.num.sm
- color.text.primary
- space.inset.sm
- space.inset.xs
- color.surface.raised
- color.surface.canvas
- color.surface.selected
- border.focus
- type.ui.caption
- color.text.tertiary
- type.ui.label
- radius.badge
- color.border.strong
- border.thick
- color.text.secondary
- space.stack.xs
- color.border.subtle
- border.hairline
- space.inset.md
- type.ui.body
- space.stack.lg
- space.inset.xl
- radius.control
- color.surface.sunken
- radius.card
- color.border.default
- space.stack.sm
- type.ui.heading-sm
- space.inset.lg
