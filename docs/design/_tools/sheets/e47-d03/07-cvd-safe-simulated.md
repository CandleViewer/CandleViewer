# E47-D03 / 07 cvd-safe-simulated

File `E47-D03 boards`, page `E47-D03 themes and SCR-116`; export `docs/design/E47/img/E47-D03-07-cvd-safe-simulated.png`; sheet `07-cvd-safe-simulated.json` (validated); theme dark.

Board 07 of 10 (§0 L72: §7.4: the CVD-safe palette on the same surfaces under deuteranopia, protanopia and tritanopia). Grid (6000, 3200); 4640 x 1448 px; "page E47-D03 themes and SCR-116 · board 07 · r1".

## Frames

- `ink∕cvd-safe · deut` (§G: `ink/cvd-safe · deut`)
- `ink∕cvd-safe · prot` (§G: `ink/cvd-safe · prot`)
- `ink∕cvd-safe · trit` (§G: `ink/cvd-safe · trit`)

## Validator and size

- `07-cvd-safe-simulated.json: 0 errors, 1 warnings, 106 sections, 283057 bytes` (exit 0)
- 106 sections, 283057 bytes

## Live checks (9)

- ink∕cvd-safe · deut: export, then apply the deuteranopia projection (§7.1) to this frame's region; read back color.cvd.buy → #9696DA (none #58A8D9)
- ink∕cvd-safe · prot: export, then apply the protanopia projection (§7.1) to this frame's region; read back color.cvd.buy → #A1A1D9 (none #58A8D9)
- ink∕cvd-safe · trit: export, then apply the tritanopia projection (§7.1) to this frame's region; read back color.cvd.buy → #00B5B8 (none #58A8D9)
- root 'E47-D03 / 07 cvd-safe-simulated' at (6000, 3200): read back the name exactly after the first section call; size 4640 x 1448
- after touchTexts + relayout: the annotation column (estimated 1401 px) ends inside the root (h 1448); raise the root's h to its end + 80 if not
- frame 'ink∕cvd-safe · deut': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'ink∕cvd-safe · prot': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'ink∕cvd-safe · trit': read back 1280 x 800 at (2800, 80); clip on, no child spills
- export docs/design/E47/img/E47-D03-07-cvd-safe-simulated.png: every frame is 1280 x 800; record the board id and the PNG size in §0

## Ambiguities (0)

## Spec gaps (0)

## Deviations (0)

## Copy keys (7)

- W-5 (§13 L535, verbatim): Colour-blind safe (blue / orange)
- W-12 (§13 L542, verbatim): = buy / bid / up
- W-13 (§13 L543, verbatim): = sell / ask / down
- W-15 (§13 L545, PROPOSED): Hatched: imbalance
- W-16 (§13 L546, PROPOSED): + buying, − selling
- W-14 (§13 L544, PROPOSED): Bids below the price, asks above
- W-17 (§13 L547, PROPOSED): POC · VA · HVN · LVN

## Copy gaps (4)

- "Price", "Bid", "Ask", "Delta": the footprint column headers at Compact (§5: "the column header at Compact"; §13 gives none)
- the DOM readout "Bid · <price> · <size>": §5 asks for the side word in the readout; §13 gives no pattern (kit wording)
- "asks" / "bids" (axis side words) and "1 → 5: more size" (the CMP-113 ramp row): §5 / §7.3 give the rule ("bids below the price, asks above"; "twice as bright reads as more size"), §13 no string
- "Volume": the profile bar's legend row (§3.2 "profile bar (HVN / LVN by length)"; §13 has W-17 only)

## Fallbacks (5)

- fallback: pattern.hatch (§5 imbalance) drawn as 1 px vertical stripes in the imbalance ink over an 8 px strip at the cell's outer edge (no pattern primitive in cvsheet)
- fallback: the direction glyphs ▲ / ▼ drawn as text characters (§5's own glyphs)
- fallback: the CVD pane's line drawn as 4 x 4 px marks, one per sample (no path primitive in cvsheet)
- kit choice (E15-D04 precedent): the grey and dichromacy frames bind the true ink tokens; the simulation is the export's projection (§7.1), never a painted hex; each frame lists §7.4's expected hexes to read back
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and CMP-086's settings list drawn as neutral placeholders; only SCR-116's content, the PreviewTile and the env badges of board 08 are drawn

## Sources (1)

- spec E47-D03.md md5 a79ee897 and hand-off E47-D03-handoff.md md5 9115b708 (§0 L72; hand-off §G L131)

## Tokens (42)

- type.ui.caption
- color.text.secondary
- space.inset.sm
- type.num.sm
- color.axis.text
- space.inset.xs
- color.cvd.imbalance
- radius.control
- color.cvd.buy
- color.text.primary
- border.thick
- color.cvd.sell
- color.border.strong
- border.hairline
- space.inset.md
- color.surface.canvas
- type.ui.label
- space.stack.sm
- color.surface.raised
- radius.card
- color.cvd.heatmap.ask.2
- color.cvd.heatmap.ask.3
- color.cvd.heatmap.ask.1
- color.cvd.heatmap.ask.4
- color.cvd.heatmap.ask.5
- color.cvd.heatmap.bid.5
- color.cvd.heatmap.bid.4
- color.cvd.heatmap.bid.3
- color.cvd.heatmap.bid.2
- color.cvd.heatmap.bid.1
- color.profile.bar
- color.profile.valuearea
- color.profile.poc
- color.candle.wick
- color.text.inverse
- type.ui.heading-sm
- space.stack.xs
- space.inset.lg
- color.surface.app
- color.surface.hover
- color.border.subtle
- color.text.tertiary
