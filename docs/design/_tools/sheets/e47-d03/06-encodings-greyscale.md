# E47-D03 / 06 encodings-greyscale

File `E47-D03 boards`, page `E47-D03 themes and SCR-116`; export `docs/design/E47/img/E47-D03-06-encodings-greyscale.png`; sheet `06-encodings-greyscale.json` (validated); theme dark.

Board 06 of 10 (§0 L71: §5: footprint, DOM, heatmap with its legend, profile, CVD pane, bubbles, markers, each in colour and in the greyscale hexes of §7.4). Grid (0, 3200); 4640 x 1901 px; "page E47-D03 themes and SCR-116 · board 06 · r1".

## Frames

- `ink∕footprint · colour` (§G: `ink/footprint · colour`)
- `ink∕footprint · grey` (§G: `ink/footprint · grey`)
- `ink∕heatmap · grey` (§G: `ink/heatmap · grey`)
- `ink∕profile · grey` (§G: `ink/profile · grey`)
- `ink∕cvd-pane · grey` (§G: `ink/cvd-pane · grey`)
- `ink∕bubbles · grey` (§G: `ink/bubbles · grey`)

## Validator and size

- `06-encodings-greyscale.json: 0 errors, 1 warnings, 73 sections, 185250 bytes` (exit 0)
- 73 sections, 185250 bytes

## Live checks (14)

- ink∕footprint · grey: export, then apply the grey projection (§7.1: relative luminance) to this frame's region; read back color.buy.default → #A5A5A5 (none #2EBD59)
- ink∕heatmap · grey: export, then apply the grey projection (§7.1: relative luminance) to this frame's region; read back color.buy.default → #A5A5A5 (none #2EBD59)
- ink∕profile · grey: export, then apply the grey projection (§7.1: relative luminance) to this frame's region; read back color.buy.default → #A5A5A5 (none #2EBD59)
- ink∕cvd-pane · grey: export, then apply the grey projection (§7.1: relative luminance) to this frame's region; read back color.buy.default → #A5A5A5 (none #2EBD59)
- ink∕bubbles · grey: export, then apply the grey projection (§7.1: relative luminance) to this frame's region; read back color.buy.default → #A5A5A5 (none #2EBD59)
- root 'E47-D03 / 06 encodings-greyscale' at (0, 3200): read back the name exactly after the first section call; size 4640 x 1901
- after touchTexts + relayout: the annotation column (estimated 1945 px) ends inside the root (h 1901); raise the root's h to its end + 80 if not
- frame 'ink∕footprint · colour': read back 1280 x 800 at (80, 80); clip on, no child spills
- frame 'ink∕footprint · grey': read back 1280 x 800 at (1440, 80); clip on, no child spills
- frame 'ink∕heatmap · grey': read back 1280 x 800 at (2800, 80); clip on, no child spills
- frame 'ink∕profile · grey': read back 1280 x 800 at (80, 960); clip on, no child spills
- frame 'ink∕cvd-pane · grey': read back 1280 x 800 at (1440, 960); clip on, no child spills
- frame 'ink∕bubbles · grey': read back 1280 x 800 at (2800, 960); clip on, no child spills
- export docs/design/E47/img/E47-D03-06-encodings-greyscale.png: every frame is 1280 x 800; record the board id and the PNG size in §0

## Ambiguities (2)

- Board 06: §0 lists footprint, DOM, heatmap, profile, CVD pane, bubbles and markers each in colour and greyscale, §G six frames with one colour frame: DOM rides with the footprint frames and the markers with the bubbles; only the footprint pair has a colour frame (§G)
- Boards 06 / 07: cvsheet binds tokens only, so §7.4's simulated hexes cannot be painted: the frames bind the true ink and the projection is applied at export (E15-D04 precedent); each frame lists the hexes to read back

## Spec gaps (0)

## Deviations (0)

## Copy keys (7)

- W-4 (§13 L534, verbatim): Default (green / red)
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
- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and CMP-086's settings list drawn as neutral placeholders; only SCR-116's content, the PreviewTile and the env badges of board 08 are drawn
- kit choice (E15-D04 precedent): the grey and dichromacy frames bind the true ink tokens; the simulation is the export's projection (§7.1), never a painted hex; each frame lists §7.4's expected hexes to read back
- fallback: the CVD pane's line drawn as 4 x 4 px marks, one per sample (no path primitive in cvsheet)

## Sources (1)

- spec E47-D03.md md5 ea4ad258 and hand-off E47-D03-handoff.md md5 da47f763 (§0 L71; hand-off §G L130)

## Tokens (47)

- type.ui.label
- color.text.secondary
- type.ui.caption
- color.text.primary
- space.stack.xs
- space.inset.md
- color.surface.raised
- radius.card
- space.inset.sm
- type.num.sm
- color.axis.text
- space.inset.xs
- color.footprint.imbalance
- radius.control
- color.footprint.bid
- border.thick
- color.footprint.ask
- color.border.strong
- border.hairline
- color.buy.default
- color.sell.default
- color.surface.canvas
- space.stack.sm
- space.stack.md
- type.ui.heading-sm
- space.inset.lg
- color.surface.app
- color.surface.hover
- color.border.subtle
- color.heatmap.ask.2
- color.heatmap.ask.3
- color.heatmap.ask.1
- color.heatmap.ask.4
- color.heatmap.ask.5
- color.heatmap.bid.5
- color.heatmap.bid.4
- color.heatmap.bid.3
- color.heatmap.bid.2
- color.heatmap.bid.1
- color.profile.bar
- color.profile.valuearea
- color.profile.poc
- color.candle.wick
- color.candle.down
- color.candle.up
- color.text.inverse
- color.text.tertiary
