# E11-D05 / 09 ref-frames-a

File `E11-D05 ref frames`, page `E11-D05 ref frames`; export `docs/design/E11/img/E11-D05-09-ref-frames-a.png`; sheet `09-ref-frames-a.json` (validated); theme dark.

Board 09 of the E11-D05 ref-frame set (ruling Q2): the 33 per-state ref frames of CMP-180 ChartRoot, CMP-188 PriceAxis, CMP-189 TimeAxis and CMP-190 Crosshair, dark, compact, one labelled row group per component and one 400 px annotation column.

Root 3200 x 2913 px at (0, 0); footer "page E11-D05 ref frames · board 09 · r1".

## Frames (33)

- `CMP-180 · ChartRoot — ref frame (loading)`
- `CMP-180 · ChartRoot — ref frame (streaming)`
- `CMP-180 · ChartRoot — ref frame (stale)`
- `CMP-180 · ChartRoot — ref frame (disconnected)`
- `CMP-180 · ChartRoot — ref frame (replay)`
- `CMP-180 · ChartRoot — ref frame (reduced detail)`
- `CMP-180 · ChartRoot — ref frame (aggregated)`
- `CMP-180 · ChartRoot — ref frame (context lost)`
- `CMP-180 · ChartRoot — ref frame (recovering)`
- `CMP-180 · ChartRoot — ref frame (empty)`
- `CMP-188 · PriceAxis — ref frame (auto)`
- `CMP-188 · PriceAxis — ref frame (locked)`
- `CMP-188 · PriceAxis — ref frame (mode tag)`
- `CMP-188 · PriceAxis — ref frame (last-price pill up)`
- `CMP-188 · PriceAxis — ref frame (last-price pill down)`
- `CMP-188 · PriceAxis — ref frame (mark pill)`
- `CMP-188 · PriceAxis — ref frame (focused)`
- `CMP-188 · PriceAxis — ref frame (dragging)`
- `CMP-189 · TimeAxis — ref frame (following)`
- `CMP-189 · TimeAxis — ref frame (paused)`
- `CMP-189 · TimeAxis — ref frame (boundary)`
- `CMP-189 · TimeAxis — ref frame (maintenance band)`
- `CMP-189 · TimeAxis — ref frame (loading band)`
- `CMP-189 · TimeAxis — ref frame (go-to-date marker)`
- `CMP-189 · TimeAxis — ref frame (remote crosshair)`
- `CMP-189 · TimeAxis — ref frame (virtual-now)`
- `CMP-189 · TimeAxis — ref frame (focused)`
- `CMP-190 · Crosshair — ref frame (pointer)`
- `CMP-190 · Crosshair — ref frame (keyboard column)`
- `CMP-190 · Crosshair — ref frame (magnet snap)`
- `CMP-190 · Crosshair — ref frame (remote)`
- `CMP-190 · Crosshair — ref frame (coincident gridline)`
- `CMP-190 · Crosshair — ref frame (hidden during drag)`

## Validator and size

- `09-ref-frames-a.json: 0 errors, 57 warnings, 112 sections, 366494 bytes` (exit 0)
- 112 sections, 2777 shapes, 366494 bytes

## Live checks (14)

- CMP-180 stale frame, group 'data ink · x0.85': set every body fill on color.candle.up to #27A14C, on color.candle.down to #C33D41 and every wick to #767E86 (the dim85 dark column, E11-D02 D16 L123 'stale = data-ink uniform × 0.85 (no extra pass)'; E11-D05 L279 and the dim85 rows L557-L559); read back the three hex values; these are the frame's only unbound fills
- CMP-189 maintenance band: every rect named 'hatch line · NN' (pane and strip) is rotated 45° about its centre by the post-render step (post-live.js; the post-export step's hatch line rotation); read back rotation 45 on each and 1 px lines 6 px apart across the stroke, clipped to the band
- each of the 33 frames reads back with the exact Table 1 name 'CMP-nnn · Name — ref frame (<state>)' and a non-empty plugin-data note naming its state
- pick one bound shape per slot family (pane fill, grid major, axis label, pill text) and read back its fill token name = the alias target listed under Fallbacks
- watermark texts (CMP-180 streaming / replay frames): set the font size to 48 px, weight 600 after the render (no type token carries 48 px); read back 48
- root 'E11-D05 / 09 ref-frames-a' at (0, 0) on page 'E11-D05 ref frames': read back the name exactly after the first section call (a mismatch makes a duplicate root); size 3200 x 2913
- after touchTexts + relayout: the annotation column (estimated 3212 px) ends at least 80 px above the root's bottom (h 2913); if not, raise the root's h to the column's end + 80 and record it
- each frame has its state caption 'state: <Table 1 state>' (type.ui.caption, color.text.secondary) 18 px above it, inside the row gap, clear of the frame (round 2, m4)
- group 'CMP-180 ChartRoot · 10 ref frames': read back 2560 x 680 at (80, 80); its frames keep their sheet sizes after relayout (clip on, no child outside its frame)
- group 'CMP-188 PriceAxis · 8 ref frames': read back 2040 x 300 at (80, 840); its frames keep their sheet sizes after relayout (clip on, no child outside its frame)
- group 'CMP-189 TimeAxis · 9 ref frames': read back 2560 x 336 at (80, 1220); its frames keep their sheet sizes after relayout (clip on, no child outside its frame)
- group 'CMP-190 Crosshair · 6 ref frames': read back 2120 x 260 at (80, 1636); its frames keep their sheet sizes after relayout (clip on, no child outside its frame)
- export docs/design/E11/img/E11-D05-09-ref-frames-a.png: export the root at scale 1 (dark set active) and record the board id, the PNG size (3200 x 2913) and the frame count read back
- after the render, run 09-ref-frames-a.post-live.js (the kit writes it beside this sheet) twice: frame notes to shared plugin data cvd02/note, watermarks 48 / 40 px weight 600 centred under the candles, the stale x0.85 ink fills, the mark pill's 3 px padding, the hatch lines rotated 45° (the live fold, 2026-10-30)

## Spec gaps (6)

- CMP-180 stale: the x 0.85 dim is a colour multiply on the data-ink uniforms with no token and no opacity token (E11-D02 D16 L123 'stale = data-ink uniform × 0.85 (no extra pass)'; E11-D05 L279 and the dim85 rows L557-L559); the sheet groups the ink as 'data ink · x0.85' and the live step sets the spec's resolved dark values - a layer opacity 0.85 would blend with the pane, not multiply
- CMP-180 context lost / recovering: E11-D02 D16 has no row for them; Table 1 and `15` name the states and E11-D04 §12.2 gives the timeline: 'context lost' = t 0 (attempt 1 of 3), 'recovering' is read as a later restore attempt (attempt 2 of 3) - the restored frame itself has no visual of its own
- CMP-180 empty: E11-D02 D16 defers to E11-D04 (SCR-047); the frame draws reason 2's heading only, in the kept chassis; the cause sentence, action and link are E11-D04 §11's
- CMP-188 lock badge: D7 gives the pill's tokens, the lock glyph and the accessible name 'Price scale locked' but not its visible text in a 72 px gutter (badge states are E11-D03's); drawn glyph-only
- CMP-189 virtual-now: D8 names the 1 px dashed replay line and 'a clock pill' but not the pill's fill / text tokens; drawn neutral (surface.raised, text.primary) with a replay hairline
- CMP-190 remote time pill text: E11-D02 D8 says color.text.secondary; `15` CMP-190 and E11-D05 §4.1b bind color.chart.pill.text.default (= color.text.primary); drawn per `15` / §4.1b

## Deviations (4)

- CMP-180 replay: CR-7's icon/replay is not in the local icon set; the `refresh` glyph stands in
- CMP-180 aggregated: the chip's merge glyph is not in the local icon set; drawn text-only
- CMP-188 last-price pill down: the seeded last bar is a down bar, so the (auto) frame already shows a down pill; in this frame the bar closes at its low (63,985.5) so the down pill sits below (auto)'s, in color.candle.down with ▼
- CMP-190 magnet snap: icon/magnet (E11-D02 CR-7) is not in the local icon set; the 12 px glyph at the pill's left edge (E11-D02 L302) is drawn from primitives (a 12 x 12 horseshoe of three rects in the pill text colour) beside the OHLC letter H (the frame's gutter is 96 px so the wider pill fits); swap for the library icon when CR-7 lands

## Fallbacks (20)

- slot pending #390: color.chart.grid.major -> color.border.default (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.grid.minor -> color.grid.line (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.pane.bg.default -> color.surface.canvas (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.rule -> color.border.default (the alias target §4.1 / §4.1b names)
- fallback: the watermark's 48 px (40 px dense) semibold has no type token (E11-D05 §6.1: a fixed px, not a class); drawn with type.ui.display (24 px bold) - live check sets the size
- slot pending #390: color.chart.watermark -> color.border.default (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.pill.text.inverse -> color.text.inverse (the alias target §4.1 / §4.1b names)
- size.icon.sm (12 px) is a Tier-1 primitive (validator WARN): small glyphs in pills and chips
- slot pending #390: color.chart.axis -> color.text.tertiary (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.replay.border -> color.node.logic. The spec aliases it to palette.purple.400 (dark), a primitive the validator refuses as a colour bind; no semantic token resolves to purple.400, so the nearest semantic purple (color.node.logic = palette.purple.500) stands in; the live drawer reads the hue as the replay purple, not its exact value
- slot pending #390: color.chart.boundary -> color.text.tertiary (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.pill.bg -> color.surface.raised (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.pill.text.default -> color.text.primary (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.pill.border -> color.border.strong (the alias target §4.1 / §4.1b names)
- fallback: the boundary date label's medium weight has no mono type token; drawn type.num.sm (the weight is reinforcement, priority 0 is its position)
- slot pending #390: color.chart.hatch.texture -> color.border.strong (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.marker.goto -> color.action.primary.default (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.pill.text.on-marker -> color.text.on-action (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.crosshair -> color.crosshair (the alias target §4.1 / §4.1b names)
- slot pending #390: color.chart.focus.ring -> color.focus.ring (the alias target §4.1 / §4.1b names)

## Copy keys (0)

## Copy gaps (0)

## Sources (1)

- origin/main e87194bb0: E11-D05.md md5 6575db49, E11-D05-handoff.md md5 1f2def41 (Table 1 L176), E11-D02.md md5 c42ae385, E11-D04.md md5 02f3ff69, 15 md5 d88c34b2; ruling of record Q2 / Q3 (2026-10-30)

## Tokens (49)

- type.ui.label
- color.text.primary
- color.surface.raised
- radius.badge
- space.inset.sm
- space.inset.xs
- color.env.demo
- border.focus
- radius.control
- color.surface.hover
- type.ui.body
- color.text.secondary
- color.grid.line
- color.border.default
- color.surface.canvas
- type.ui.display
- color.candle.down
- type.num.sm
- color.text.inverse
- radius.xs
- type.ui.caption
- size.icon.sm
- color.surface.selected
- color.border.strong
- border.hairline
- color.candle.wick
- color.candle.up
- color.text.tertiary
- color.data-confidence.stale.indicator
- color.data-confidence.stale.text
- color.data-confidence.stale.surface
- color.data-confidence.reconnecting.indicator
- color.data-confidence.reconnecting.text
- opacity.scrim
- color.surface.app
- color.data-confidence.disconnected.indicator
- color.node.logic
- color.status.warning.strong
- color.status.warning.subtle
- type.ui.heading-sm
- color.focus.ring
- color.action.primary.default
- color.text.on-action
- color.crosshair
- opacity.muted
- size.icon
- space.stack.xs
- space.stack.sm
- space.inset.lg
