# E21-D02 / 04 loading-empty

File `E21-D02 boards`, page `E21-D02`; export `docs/design/E21/img/E21-D02-04-loading-empty.png`; sheet `04-loading-empty.json` (validated); theme dark.

Board 04 of 10 (§0 L103: SCR-050/loading, SCR-050/empty-no-recording (Owner CTA and the sentence form)). Grid (19200, 0); 4640 x 1026 px; "page E21-D02 · board 04 · r1".

## Frames

- `SCR-050∕loading` (`SCR-050/loading`)
- `SCR-050∕empty-no-recording` (`SCR-050/empty-no-recording`)
- `SCR-050∕empty-no-recording · sentence form` (`SCR-050/empty-no-recording · sentence form`)

## Validator and size

- `04-loading-empty.json: 0 errors, 23 warnings, 24 sections, 71801 bytes` (exit 0)
- 24 sections, 394 shapes, 71801 bytes

## Live checks (10)

- frame 'SCR-050∕loading': the board markers stack bottom-left at x 12, the last ending at y 696 (8 px above the footer); keep that anchor, never centre them
- frame 'SCR-050∕empty-no-recording': the EmptyState card (560 wide) — centre horizontally in the frame (x 360) and vertically in the panel body (y 80–704, card top y 326); re-measure its h after touchTexts and re-centre this card only
- frame 'SCR-050∕empty-no-recording · sentence form': the EmptyState card (560 wide) — centre horizontally in the frame (x 360) and vertically in the panel body (y 80–704, card top y 332); re-measure its h after touchTexts and re-centre this card only
- centring: only a node a line here names is centred, and only on the axis it names; every other node keeps the sheet's x / y or its flex parent's alignment — never apply a generic re-centre
- root 'E21-D02 / 04 loading-empty' at (19200, 0): read back the name exactly after the first section call; size 4640 x 1026
- after touchTexts + relayout: the root h 1026 is the live check's max(annotation end, footer end 945) + 80 (the annotation column estimated 866 px with 15 % slack); re-measure it if the annotations change
- frame 'SCR-050∕loading': read back 1280 x 800 at (80, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-050∕empty-no-recording': read back 1280 x 800 at (1440, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- frame 'SCR-050∕empty-no-recording · sentence form': read back 1280 x 800 at (2800, 108); clip on, no child spills (raise h in 8 px steps if the lint reports text-overflow)
- export docs/design/E21/img/E21-D02-04-loading-empty.png: record the board id and the PNG size

## Derivations (0)

## Decisions (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (24)

- spec L96: "BTCUSDT"
- spec L160: "mark 64,012.5"
- spec L147: "trail [60 s ▾]"
- spec L224: "T1 (2 s"
- spec L96: "Acct A"
- spec L96: "Acct B"
- spec L348: "pulled 18.0 (estimated)"
- W-30 (§12 L458, PROPOSED): "Loading book…"
- spec L144: "BTCUSDT · Heatmap + Ladder"
- spec L84: "LOCKED"
- spec L152: "Following"
- spec L152: "Pause"
- spec L85: "DEMO"
- spec L151: "Ladder │ Table"
- W-1 (§12 L429, PROPOSED): "DOM ladder, BTCUSDT, DEMO"
- W-20 (§12 L448, PROPOSED; E09-D09 (A-5)): "Orders from here come later; cancel and close work as usual."
- spec L258: "BUY MKT"
- spec L258: "SELL MKT"
- spec L259: "FLAT"
- spec L259: "CXL"
- W-16 (§12 L444, verbatim): "History starts when you record BTCUSDT — recording has not begun yet."
- W-17 (§12 L445, verbatim): "Nothing is missing or broken: CandleViewer keeps only what it records."
- W-19 (§12 L447, verbatim): "Record this symbol"
- W-18 (§12 L446, verbatim): "Only the owner can change recording."

## Copy gaps (6)

- "announced: polite, once (the panel's role="status")": kit label, not E21-D02 copy — board-marker label
- "depth": kit label, not E21-D02 copy — §2.1's `depth [200 ▾]` slot, its label word
- "Heatmap · time →": kit label, not E21-D02 copy — §2.2's heading words as the pane's label
- "qty": kit label, not E21-D02 copy — `14`:1211's footer label
- "0.10 · 0.25 · 0.50 · 1.0": kit label, not E21-D02 copy — `14`:1211's qty presets (CMP-122); enabled, choosing one sends nothing
- "Detectors": kit label, not E21-D02 copy — the strip's label; CMP-134's words are E25's

## Fallbacks (5)

- kit choice: board markers (focus-order numbers, announcements, accessible names, redline callouts) are drawn in a 1 px color.border.strong outline — not product UI
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): the CMP-019 lock and the chevrons
- kit choice: the env badge's icon (E10-D03's) is not in the local icon set; drawn as an 8 px dot in the env colour, outlined for DEMO and filled for LIVE, beside the word (text + icon, the colour never the only signal)
- kit choice: the `Ladder │ Table` radiogroup drawn as two 24 px segments, the checked one color.surface.selected with a color.border.selected outline
- kit choice: loading skeleton bars are color.surface.raised rects inset 4 px in each 24 px row, their widths the kit's (static, no shimmer: motion is E21-D05's)

## Sources (2)

- spec docs/design/E21/E21-D02.md md5 4d99a14edaaa38680621310731662f6d at the boards PR (§0 L103); no hand-off file (BQ-2)
- packages/fixtures/bybit/2026-10-05/rest/instruments_before.json md5 edd9dd2a060c51bd4bd1450307728ddf (BTCUSDT tick 0.10, qty step 0.001)

## Tokens (39)

- type.ui.caption
- color.text.tertiary
- color.text.primary
- space.stack.xs
- space.inset.sm
- color.surface.canvas
- color.border.strong
- border.hairline
- radius.control
- type.ui.body-strong
- color.text.secondary
- type.num.sm
- size.icon.sm
- space.inset.xs
- color.surface.sunken
- color.border.default
- space.button.paddingX
- size.icon
- color.env.demo
- border.thick
- type.ui.label
- color.surface.raised
- radius.badge
- color.surface.selected
- color.border.selected
- space.inset.md
- color.heatmap.zero
- color.grid.line
- color.surface.app
- type.ui.heading-sm
- type.ui.body
- color.text.on-action
- color.action.primary.default
- color.focus.ring
- border.focus
- space.stack.md
- space.inset.lg
- radius.card
- space.stack.sm
