# E21-D01 / 08 protocol-and-keyboard

File `E21-D01 boards`, page `E21-D01`; export `docs/design/research/img/E21-D01-08-protocol-and-keyboard.png`; sheet `08-protocol-and-keyboard.json` (validated); theme dark.

Board 08 of eight (memo §0 L79: T1–T7 and the keyboard walkthrough path (§10)). Grid (14000, 6400); 2240 x 2250 px; "page E21-D01 · board 08 · r1".

## Frames

- `protocol∕probes` (`protocol/probes`)
- `protocol∕agenda-and-order` (`protocol/agenda-and-order`)
- `keyboard∕walkthrough-path` (`keyboard/walkthrough-path`)

## Validator and size

- `08-protocol-and-keyboard.json: 0 errors, 0 warnings, 17 sections, 49258 bytes` (exit 0)
- 17 sections, 269 shapes, 49258 bytes

## Live checks (6)

- root 'E21-D01 / 08 protocol-and-keyboard' at (14000, 6400): read back the name exactly after the first section call; size 2240 x 2250
- after touchTexts + relayout: the annotation column (estimated 598 px with 15 % slack) ends inside the root (h 2250); raise the root's h to max(annotation end, footer end) + 80 if not
- frame 'protocol∕probes': read back 1600 x 512 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'protocol∕agenda-and-order': read back 1600 x 680 at (80, 728); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'keyboard∕walkthrough-path': read back 1600 x 616 at (80, 1516); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/research/img/E21-D01-08-protocol-and-keyboard.png: record the board id and the PNG size

## Derivations (1)

- agenda: 10 steps over 45 min drawn 1552 px wide (34.5 px a minute)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (15)

- memo L229: "Decision rule, per probe over the sessions that ran it: T1–T5 and T7 run in all three sessions, and P1 (S1) and P2a (S2) are the deciding personas, because the ladder is their working surface (10:76, 10:111); S3 (P2b) is recorded as a third position. A PROPOSED default changes only when both deciding sessions contradict it. A one-one split records both positions, keeps the PROPOSED default and goes to the owner as an OQ. T6 runs in S3 only, so it records the keyboard path and the Enter expectation for C2 and changes no default."
- memo L205: "## 10. Owner session protocol (ready to run; nothing below has been run)"
- memo L246: "Order: S1 runs T1 beside then behind and T4 auto-follow then centre lock (order A); S2 runs both the other way round (order B); S3 runs order A. The sheet records the order used."
- memo L209: "Three sessions of 45 min: S1 the Owner (P1); S2 an intraday manager (P2a); S3 a swing manager (P2b), who also runs T6 keyboard-only."
- memo L211: "A recorder-captured BTCUSDT volatile window at depths 50, 200 and 500, declared on the sheet by capture date and window; until it exists the sessions do not run."
- memo L231: "### 10.4 Agenda (45 min) and counterbalancing"
- memo L222: "reach the ladder"
- memo L222: "move rows"
- memo L222: "reveal one level's history"
- memo L222: "cycle regions"
- memo L222: "say what Enter would do"
- memo L113: "trail [60s v]"
- memo L101: "Space = re-centre + resume auto-follow"
- memo L103: "C centres on the mark"
- memo L106: "+/- = price zoom"

## Copy gaps (0)

## Fallbacks (1)

- kit choice: board markers (step numbers, reading arrows, region names, violation flags) are caption text in a 'dashed · ' outline (board markers, not product UI)

## Sources (2)

- spec (memo) docs/design/research/e21-dom-heatmap.md md5 a95e35c3ab74dfb8b99e5633389d3dad at the boards PR (§0 drawn, §14 As built) (§0 L79)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (25)

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
- space.inset.md
- radius.card
- border.hairline
- space.stack.lg
- space.inset.xl
- color.border.strong
- type.num.sm
- color.surface.hover
- radius.badge
- radius.control
- type.ui.body
- space.stack.sm
- type.ui.heading-sm
- space.inset.lg
