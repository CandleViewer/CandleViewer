# E21-D01 / 05 tiers-and-shed

File `E21-D01 boards`, page `E21-D01`; export `docs/design/research/img/E21-D01-05-tiers-and-shed.png`; sheet `05-tiers-and-shed.json` (validated); theme dark.

Board 05 of eight (memo §0 L76: 500 → 200 → 50: what each step loses; the notice (AD-7)). Grid (28000, 0); 2080 x 1847 px; "page E21-D01 · board 05 · r1".

## Frames

- `tiers∕500-200-50` (`tiers/500-200-50`)
- `shed∕order` (`shed/order`)
- `shed∕notice` (`shed/notice`)

## Validator and size

- `05-tiers-and-shed.json: 0 errors, 0 warnings, 11 sections, 45120 bytes` (exit 0)
- 11 sections, 227 shapes, 45120 bytes

## Live checks (6)

- root 'E21-D01 / 05 tiers-and-shed' at (28000, 0): read back the name exactly after the first section call; size 2080 x 1847
- after touchTexts + relayout: the annotation column (estimated 1242 px with 15 % slack) ends inside the root (h 1847); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'tiers∕500-200-50': read back 1440 x 608 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'shed∕order': read back 1440 x 384 at (80, 824); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'shed∕notice': read back 1440 x 400 at (80, 1316); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E21-D01-05-tiers-and-shed.png: record the board id and the PNG size

## Derivations (2)

- tiers: the first N levels a side of the seeded book; ticks a side = |far − best| + 1; losses = tier hi minus tier lo, a side
- depth scale: 1742 ticks from 69,911.90 to 70,086.00 drawn over 1392 px; wall ticks (≥ 10 BTC) at 69,999.80 (17.615), 69,999.50 (40.606), 69,980.60 (37.820), 69,946.30 (56.441), 70,000.30 (32.925), 70,000.70 (21.627), 70,013.10 (57.563), 70,042.10 (36.421)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (7)

- memo L111: "the far walls beyond the tier, the cumulative depth beyond it and the heatmap rows outside it"
- memo L59: "cadence"
- memo L1: "trail"
- memo L5: "depth"
- memo L171: "200 is the default tier"
- memo L110: "500 only with heatmap_depth_500 on"
- memo L203: "heatmap_depth_500 defaults to off"

## Copy gaps (11)

- "depth": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — header tier chip label
- "Depth 500 → 200": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — notice title: both tiers (AD-7)
- "Far walls lost: 69,946.30 (56.441), 70,042.10 (36.421)": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — lost item 1 (F-11)
- "Depth lost: 267.588 BTC bids, 267.715 BTC asks": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — lost item 2 (F-11)
- "Heatmap rows lost: 544 below, 542 above": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — lost item 3 (F-11)
- "Pin 500": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — the pin control (AD-7)
- "Depth 200 → 50": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — notice title: both tiers (AD-7)
- "Far walls lost: 69,980.60 (37.820), 70,013.10 (57.563)": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — lost item 1 (F-11)
- "Depth lost: 144.440 BTC bids, 176.479 BTC asks": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — lost item 2 (F-11)
- "Heatmap rows lost: 275 below, 256 above": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — lost item 3 (F-11)
- "Pin 200": kit label, not memo copy (PROPOSED; E21-D02 #440 / E21-D03 #503 / E21-D04 #504 write the copy) — the pin control (AD-7)

## Fallbacks (2)

- kit choice: the PROPOSED stamp is the word in a 2 px color.border.strong badge (memo §0: a board that shows a recommendation carries a PROPOSED stamp)
- kit choice: board markers (step numbers, reading arrows, region names, violation flags) are caption text in a 'dashed · ' outline (board markers, not product UI)

## Sources (2)

- spec (memo) docs/design/research/e21-dom-heatmap.md md5 a95e35c3ab74dfb8b99e5633389d3dad at the boards PR (§0 drawn, §14 As built) (§0 L76)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (31)

- color.border.strong
- border.hairline
- color.surface.raised
- type.num.sm
- color.text.primary
- color.surface.hover
- color.surface.selected
- type.ui.caption
- color.text.secondary
- color.text.tertiary
- space.inset.sm
- space.inset.xs
- color.border.default
- color.surface.canvas
- space.stack.xs
- type.ui.label
- space.inset.md
- radius.card
- radius.badge
- border.thick
- space.stack.lg
- space.inset.xl
- type.ui.heading-md
- radius.control
- type.ui.body-strong
- space.button.paddingX
- type.ui.body
- size.icon
- type.ui.heading-sm
- space.stack.sm
- space.inset.lg
