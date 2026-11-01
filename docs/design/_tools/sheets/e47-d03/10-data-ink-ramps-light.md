# E47-D03 / 10 data-ink-ramps-light

File `E47-D03 boards`, page `E47-D03 themes and SCR-116`; export `docs/design/E47/img/E47-D03-10-data-ink-ramps-light.png`; sheet `10-data-ink-ramps-light.json` (validated); theme light.

Board 10 of 10 (§0 L75: light twin of 09, after D03-D7 … D03-D14). Grid (24000, 3200); 1920 x 1000 px; "page E47-D03 themes and SCR-116 · board 10 · r1".

## Frames

- `ink∕ramps · light` (§G: `ink/ramps · light`)

## Validator and size

- `10-data-ink-ramps-light.json: 0 errors, 0 warnings, 8 sections, 36934 bytes` (exit 0)
- 8 sections, 36934 bytes

## Live checks (5)

- root 'E47-D03 / 10 data-ink-ramps-light' at (24000, 3200): read back the name exactly after the first section call; size 1920 x 1000
- after touchTexts + relayout: the annotation column (estimated 807 px) ends inside the root (h 1000); raise the root's h to its end + 80 if not
- frame 'ink∕ramps · light': read back 1280 x 800 at (80, 80); clip on, no child spills
- theme: activate the light token set before exporting board 10; read back one bound fill (color.surface.canvas) as the light value
- export docs/design/E47/img/E47-D03-10-data-ink-ramps-light.png: every frame is 1280 x 800; record the board id and the PNG size in §0

## Ambiguities (1)

- Board 10 draws the light CVD ramp after D03-D7 … D03-D14 (PROPOSED): each stop binds the base light token that holds the diff's primitive today, so the export is right before E47-D10 lands; once the diff applies, rebind each stop to its own token

## Spec gaps (0)

## Deviations (0)

## Copy keys (0)

## Copy gaps (0)

## Fallbacks (1)

- kit choice: the shell chrome (TopBar, NavRail, StatusBar) and CMP-086's settings list drawn as neutral placeholders; only SCR-116's content, the PreviewTile and the env badges of board 08 are drawn

## Sources (1)

- spec E47-D03.md md5 dcf7a14b and hand-off E47-D03-handoff.md md5 9115b708 (§0 L75; hand-off §G L134)

## Tokens (53)

- color.border.strong
- border.hairline
- color.heatmap.bid.1
- type.ui.caption
- color.text.primary
- type.num.sm
- space.stack.xs
- color.heatmap.bid.2
- color.heatmap.bid.3
- color.heatmap.bid.4
- color.heatmap.bid.5
- type.ui.label
- color.text.secondary
- space.inset.sm
- space.stack.sm
- space.inset.md
- color.surface.raised
- radius.card
- color.heatmap.ask.1
- color.heatmap.ask.2
- color.heatmap.ask.3
- color.heatmap.ask.4
- color.heatmap.ask.5
- color.cvd.heatmap.bid.5
- color.cvd.heatmap.bid.4
- color.cvd.heatmap.bid.3
- color.cvd.heatmap.bid.2
- color.cvd.heatmap.bid.1
- color.cvd.heatmap.ask.5
- color.cvd.heatmap.ask.4
- color.cvd.heatmap.ask.3
- color.cvd.heatmap.ask.2
- color.cvd.heatmap.ask.1
- color.profile.bar
- color.profile.valuearea
- color.profile.poc
- color.candle.up
- color.candle.down
- color.buy.default
- color.sell.default
- color.footprint.imbalance
- color.cvd.buy
- color.cvd.sell
- color.cvd.imbalance
- type.ui.heading-sm
- space.inset.lg
- color.surface.app
- radius.control
- color.surface.hover
- color.border.subtle
- space.inset.xs
- color.text.tertiary
- color.surface.canvas
