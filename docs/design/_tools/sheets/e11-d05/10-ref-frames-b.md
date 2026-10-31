# E11-D05 / 10 ref-frames-b

File `E11-D05 ref frames`, page `E11-D05 ref frames`; export `docs/design/E11/img/E11-D05-10-ref-frames-b.png`; sheet `10-ref-frames-b.json` (validated); theme dark.

Board 10 of the E11-D05 ref-frame set (ruling Q2): the 22 per-state ref frames of CMP-197 ChartTooltip, CMP-198 ChartWatermark, CMP-199 ChartLegend and CMP-226 BarCountdown, dark, compact, one labelled row group per component and one 400 px annotation column.

Root 3000 x 2566 px at (4000, 0); footer "page E11-D05 ref frames · board 10 · r1".

## Frames (22)

- `CMP-197 · ChartTooltip — ref frame (follow)`
- `CMP-197 · ChartTooltip — ref frame (flipped left)`
- `CMP-197 · ChartTooltip — ref frame (flipped above)`
- `CMP-197 · ChartTooltip — ref frame (clear of last price)`
- `CMP-197 · ChartTooltip — ref frame (docked)`
- `CMP-197 · ChartTooltip — ref frame (overflow)`
- `CMP-198 · ChartWatermark — ref frame (default)`
- `CMP-198 · ChartWatermark — ref frame (replay suffix)`
- `CMP-198 · ChartWatermark — ref frame (hidden below 120 px)`
- `CMP-198 · ChartWatermark — ref frame (dense 40 px)`
- `CMP-199 · ChartLegend — ref frame (default)`
- `CMP-199 · ChartLegend — ref frame (one hidden)`
- `CMP-199 · ChartLegend — ref frame (all hidden)`
- `CMP-199 · ChartLegend — ref frame (overflow "+N more")`
- `CMP-199 · ChartLegend — ref frame (popover open)`
- `CMP-199 · ChartLegend — ref frame (collapsed)`
- `CMP-199 · ChartLegend — ref frame (pane-label row focused)`
- `CMP-199 · ChartLegend — ref frame (estimated series)`
- `CMP-226 · BarCountdown — ref frame (normal)`
- `CMP-226 · BarCountdown — ref frame (warn "closing")`
- `CMP-226 · BarCountdown — ref frame (closed)`
- `CMP-226 · BarCountdown — ref frame (non-time —)`

## Validator and size

- `10-ref-frames-b.json: 0 errors, 20 warnings, 80 sections, 277123 bytes` (exit 0)
- 80 sections, 2185 shapes, 277123 bytes

## Live checks (13)

- each of the 22 frames reads back with the exact Table 1 name 'CMP-nnn · Name — ref frame (<state>)' and a non-empty plugin-data note naming its state
- CMP-197 frames: the tooltip box never overlaps the last-price pill's band (read back its y / h against the last-price line y ± 12.5)
- CMP-198 watermark texts: set the font size to 48 px (40 px in 'dense 40 px'), weight 600 after the render; read back the sizes; the 'hidden below 120 px' frame has no watermark text
- CMP-199 'popover open': the popover and its ring sit above the legend (z-order) and inside the frame
- root 'E11-D05 / 10 ref-frames-b' at (4000, 0) on page 'E11-D05 ref frames': read back the name exactly after the first section call (a mismatch makes a duplicate root); size 3000 x 2566
- after touchTexts + relayout: the annotation column (estimated 2794 px) ends at least 80 px above the root's bottom (h 2566); if not, raise the root's h to the column's end + 80 and record it
- each frame has its state caption 'state: <Table 1 state>' (type.ui.caption, color.text.secondary) 18 px above it, inside the row gap, clear of the frame (round 2, m4)
- group 'CMP-197 ChartTooltip · 6 ref frames': read back 2360 x 360 at (80, 80); its frames keep their sheet sizes after relayout (clip on, no child outside its frame)
- group 'CMP-198 ChartWatermark · 4 ref frames': read back 1400 x 240 at (80, 520); its frames keep their sheet sizes after relayout (clip on, no child outside its frame)
- group 'CMP-199 ChartLegend · 8 ref frames': read back 1480 x 680 at (80, 840); its frames keep their sheet sizes after relayout (clip on, no child outside its frame)
- group 'CMP-226 BarCountdown · 4 ref frames': read back 1080 x 88 at (80, 1600); its frames keep their sheet sizes after relayout (clip on, no child outside its frame)
- export docs/design/E11/img/E11-D05-10-ref-frames-b.png: export the root at scale 1 (dark set active) and record the board id, the PNG size (3000 x 2566) and the frame count read back
- after the render, run 10-ref-frames-b.post-live.js (the kit writes it beside this sheet) twice: frame notes to shared plugin data cvd02/note, watermarks 48 / 40 px weight 600 centred under the candles (the live fold, 2026-10-30)

## Spec gaps (2)

- CMP-197: where the crosshair time pill would cover the zone tag's clock, E11-D02 L206 lets pills cover tick labels only and L172 mirrors the cluster's exclusion zone at the tag; the pill flips right of its anchor and is held at the zone's edge (8 px right of the tag), its value still the crosshair's time
- CMP-197 docked: D10 rule 6 says the docked box yields to the legend by sitting right of it; the frame has no legend (CMP-199 is board 10's own row), so the box sits at the pane's top-right

## Deviations (5)

- CMP-197 docked: the frame's price range is widened so the last-price band sits low and the box clears it (rule 4 priority), and its bars and series sit 40.0 higher so every value the frame shows lies on its visible ticks (64,000-64,400); a layout choice of the crop, not a spec value
- CMP-197 overflow: the frame's price range is widened so the last-price band sits low and the box clears it (rule 4 priority), and its bars and series sit 40.0 higher so every value the frame shows lies on its visible ticks (64,000-64,400); a layout choice of the crop, not a spec value
- CMP-199 hidden rows: E11-D02 D12 (L119) and L343 draw an eye-off icon; the local icon set has none, so it is drawn from primitives - the `show` eye plus a 2 px diagonal stroke (13 2 x 2 steps) in color.text.tertiary; swap for the library icon when it lands
- CMP-199 one hidden: the frame's price range is widened so no candle crosses the hidden row's "—" value (D12 gives the legend no row fill); a layout choice of the crop, not a spec value
- CMP-199 all hidden: every series row is hidden, the price series included, so the pane draws no candles (grid and axis stay) and no "—" value sits over a wick

## Fallbacks (12)

- slot pending #390: color.chart.pill.text.inverse -> color.text.inverse (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.crosshair -> color.crosshair (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.grid.major -> color.border.default (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.grid.minor -> color.grid.line (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.pane.bg.default -> color.surface.canvas (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.rule -> color.border.default (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.axis -> color.text.tertiary (the alias target §4.1 / §4.1b names)
- fallback: the watermark's 48 px (40 px dense) semibold has no type token (E11-D05 §6.1: a fixed px, not a class); drawn with type.ui.display (24 px bold) - live check sets the size
- slot pending #390: color.chart.watermark -> color.border.default (the alias target §4.1 / §4.1b names)
- fallback: the dense 40 px watermark (E11-D05 §6 L291 'watermark 48 / 48 / 40 px') is drawn with type.ui.heading-lg (20 px semibold), the same 40 : 48 ratio as the 24 px default - live check sets 40 px
- fallback: color.indicator.palette.1 (E13-D04's slot, not in packages/ui/tokens) for the EMA 20 swatch / line is drawn as color.status.info.strong; the swatch's shape carries the kind
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): small glyphs in pills and chips

## Copy keys (0)

## Copy gaps (0)

## Sources (1)

- origin/main e87194bb0: E11-D05.md md5 6575db49, E11-D05-handoff.md md5 1f2def41 (Table 1 L176), E11-D02.md md5 c42ae385, E11-D04.md md5 02f3ff69, 15 md5 d88c34b2; ruling of record Q2 / Q3 (2026-10-30)

## Tokens (42)

- color.candle.up
- type.num.sm
- color.text.inverse
- radius.xs
- space.inset.xs
- color.crosshair
- type.ui.caption
- color.text.secondary
- color.text.primary
- space.inset.sm
- color.surface.overlay
- color.border.default
- border.hairline
- radius.card
- elevation.popover
- color.grid.line
- color.candle.wick
- color.candle.down
- color.surface.canvas
- color.text.tertiary
- type.ui.display
- type.ui.heading-lg
- type.num.xs
- type.ui.label
- size.icon
- color.status.info.strong
- radius.control
- color.focus.ring
- border.focus
- color.action.primary.default
- color.surface.raised
- color.surface.app
- color.status.warning.strong
- size.icon.sm
- type.ui.body-strong
- color.status.warning.subtle
- radius.badge
- type.ui.heading-sm
- type.ui.body
- space.stack.xs
- space.stack.sm
- space.inset.lg
