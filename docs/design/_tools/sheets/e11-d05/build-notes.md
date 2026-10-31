# E11-D05 ref frames — build notes (boards 09 / 10, r1)

Ruling of record Q2 / Q3 (#310, 2026-10-30): the 55 per-state ref frames of handoff Table 1 on two boards, dark only,
in the per-set file `E11-D05 ref frames`, page `E11-D05 ref frames`. Spec read as at origin/main e87194bb0 with `git show`
(md5s in `e11d05kit.py` SPEC_MD5; the kit refuses to run on drift).

## Rebuild

See `BUILD.md` (commands, outputs, the post-render step). Each generator validates the raw sheet
(`../tools/validate_sheet.py --components ../tools/components.offline.json`, exit 0 or it raises), writes the .md (line 3
= the render drivers' line), the post-render script and the packed sheet (`compactOf.file` the bare raw-sheet name with its
sha256, packed sections <= 9216 B). Deterministic: seed 310, no clock.

## Layout

- Root non-flex, fill color.surface.app, clip; one labelled group per component (non-flex, frames at 40 px gaps,
  rows of 5 / 8 / 5 / 6 on board 09 and 6 / 4 / 4 / 4 on board 10), groups 80 px apart, one 400 px annotation column
  at the right; root = content + 80. Board 09 at (0, 0), board 10 at (4000, 0).
- Frame sizes per component: CMP-180 480 x 300 (status row + pane + gutter + strip), CMP-188 220 x 260, CMP-189
  480 x 128, CMP-190 320 x 220, CMP-197 360 x 320, CMP-198 320 x 200, CMP-199 340 x 300, CMP-226 240 x 48.
- Compact density throughout (axis type.num.sm, pills 17, chips 20, strip 24, gutter 72, inset 8).
- Each frame's `note` (plugin data) = its state, its source line and the slots it binds.

## Tokens

- The 18 §4.1 / §4.1b slot names are not in packages/ui/tokens (they land with #390): `k.slot(name)` binds the alias
  target and the sheet notes list "slot pending #390: <slot> -> <target>".
- `color.chart.replay.border`: the spec's alias is palette.purple.400, a primitive (the validator refuses primitives
  for colour); `color.node.logic` (palette.purple.500) stands in.
- `color.indicator.palette.1` (E13-D04) -> color.status.info.strong; watermark 48 / 40 px -> type.ui.display
  (live check sets the size); boundary date medium weight -> type.num.sm.

## Rules kept

No inst nodes; icons only from the local 18; o.wrap never boolean; flex children without text carry h; no "/" in node
names; no local path / host / agent string anywhere (checked on the sheet and the md).

## Fold r1a (#310 critic MINOR-2 / 3 / 4; MINOR-1 kept)

- CMP-180 (stale): the candles sit in one group `data ink · x0.85`; the live step sets the spec's dim85 dark values
  (E11-D05 L626-628: up #27A14C, down #C33D41, wick #767E86 = the data-ink uniforms x 0.85 of E11-D02 D16 L123 /
  E11-D05 L279). No opacity token is 0.85 and a layer opacity would blend with the pane rather than multiply; those
  three fills are the frame's only unbound ones (spec_gaps + live_checks).
- CMP-190 (magnet snap): the 12 px magnet glyph (E11-D02 L302) is drawn from primitives (`magnet glyph`, a 12 x 12
  horseshoe of three rects in the pill text colour) at the pill's left edge, beside the OHLC letter; icon/magnet is
  CR-7 and not in the local set. The frame's gutter is 96 px so the wider pill fits.
- CMP-198 (dense 40 px): the watermark is type.ui.heading-lg (20 px semibold) vs type.ui.display (24 px) in the
  default frame - the 40 : 48 ratio of E11-D05 L291 (watermark 48 / 48 / 40 px); the live check sets 48 / 40 px.
- MINOR-1 kept: `(non-time —)` follows Table 1's backticked state cell.

## Live-check fold r2 (2026-10-30, after the render)

The live check of the drawn boards (page `E11-D05 ref frames`) fixed these on the boards; the kit now writes them, so a
regeneration reproduces the drawn boards:

- In the sheet: the `CMP-198 watermark` is the pane's first child (under the grid and the candles); a watermark whose
  48 / 40 px text is wider than the pane - 16 (board 09 replay; board 10 default, replay suffix, dense 40 px) is a fixed
  `pane - 16` wide, centred text at x 8 (`WATERMARK_WRAP`); the top price tick is never above its gutter (y -2 -> 0: 6
  CMP-190 frames, 3 CMP-198 frames); the last-price pill (14 + 6) and the mark pill sit at the gutter's x 0 (was 4); the
  CMP-180 (empty) SCR-047 heading at x 24 (centred in the pane, was 60); the CMP-188 (locked) / (dragging) lock badge at
  y 3 (was 232); the root heights are the measured annotation end + 80 (`MEASURED_H`: 2913, 2566; were 3376, 2960);
  CMP-189 (boundary) and (maintenance band) drop `time 0` (`Crop.drop_times`: the date, resp. the band label, replaces
  it; the other labels keep their positions).
- After the render (`build/NN-<slug>.post-live.js`, run twice): what a sheet cannot carry - the frames' notes as shared
  plugin data `cvd02/note` (cvsheet drops `note`), the watermarks' 48 / 40 px weight 600 (no type token) and their
  centring on the settled heights, the stale frame's x0.85 ink fills #27A14C / #C33D41 / #767E86 (no token), the mark
  pill's 3 px padding (no 3 px spacing token).
- Proof: the regenerated sheets match the live read-backs of both roots (size and position), their eight groups and
  annotation columns (position and size) and all 55 frames (name, size, clip): 73 values, 0 differences. The read-backs
  carry no deeper node list; inside the frames the fold is the live-check log's own fix list, and the two dropped time
  labels show in the re-exported board 09 PNG and its shape count (2912 -> 2910 with the root).
- Recorded deviations: overlaps by design 16 (board 09) + 8 (board 10); 11 watermark texts unbound at 48 / 40 px; 4
  wrapping watermarks (a spec gap: 48 px exceeds 60 % of a cropped pane).

## Review fold r2 (2026-10-31, the orchestrator's ruled Minors on PR #5105)

The kit now draws these; boards 09 / 10 are re-rendered from it (spec lines are E11-D02's, unchanged since e87194bb0):

- m1, D5 (L205): the last-price pill suppresses every price tick label whose box comes within one label height of it
  (`Crop.lp_box`; board 09 aggregated `64,025.0`, board 10 docked / overflow `64,000.0`, and the near ticks of the
  other last-price frames). L206 lets pills cover tick labels only, so a strip pill never covers the zone tag's clock:
  `Crop.strip_pill` centres a pill on its anchor, flips it left at the cluster's zone (L171 / L206) and, at the tag's
  mirror zone (L172), flips it right and holds it at the zone's edge (CMP-197 follow / flipped above / clear of last
  price / overflow; a spec gap in the sidecar). The crosshair-over-tick overlaps stay (by design).
- m2, D12 (L119, L343): hidden legend rows draw eye-off, built from primitives (the `show` eye plus a 2 px diagonal
  stroke; no eye-off in the local icon set). CMP-199 (all hidden) hides the price series too, so no candles sit behind
  the `—` values; (one hidden) widens the crop's price range so no candle crosses the hidden row's `—`.
- m3: every strip pill reads its value off its own axis (`Crop.minutes_at` / `clock_at`, linear through the frame's
  time labels), so it falls between the ticks it sits between: the crosshair, remote and go-to-date pills, CMP-197's
  box title, the virtual-now pill and CMP-189's zone tag, the maintenance band's label (the frame keeps 13:30 / 13:35 /
  13:40 and drops the two the band label covers; boundary still drops its `time 0`), and the CMP-180 replay frame's
  zone tag and REPLAY chip, which show the virtual now (L276). The overflow tooltip's BB and Keltner rows read upper >=
  middle (64,003.2, the EMA 20 row) >= lower.
- m4: each frame carries a caption `state: <Table 1 state>` (type.ui.caption, color.text.secondary) in the row gap 18
  px above it; root and group sizes are unchanged. CMP-188 (last-price pill down) closes its last bar at the bar's low,
  so its down pill sits below (auto)'s (the seeded bar is already down) and (up)'s.

## Review fold r3 (2026-10-31, axis agreement)

A sweep of all 55 frames checks each value against its own axis. Every price value (tooltip rows, legend values,
price pills; not the watermark) must lie within the visible price ticks plus one tick step. Every time value in the
strip must lie between its neighbouring ticks, and every other time value within the visible time ticks plus one step.
Four frames failed and now pass (m3):

- CMP-197 (overflow) and (docked): the widened range showed ticks 64,100-64,300 (64,000 is suppressed by the
  last-price pill) while the box read about 64,003. Their bars and series now sit 40.0 higher (`SHIFT_197`), and the
  range is set to 0.65 px per price unit with the last close 248 px down. The ticks read 64,000-64,400 and every value
  falls on them. BB and Keltner still read upper >= middle (the EMA 20 row) >= lower.
- CMP-189 (paused): "Paused at hh:mm" shows the newest bar on screen read off the axis (L267), not 13:47.
- CMP-189 (maintenance band): the band runs 13:31-13:38, and its label `13:31–13:38 maintenance` sits between the
  13:30 and 13:40 ticks. The label now covers only 13:35, which is the one dropped label.
- CMP-199 (popover open): EMA 200 now reads 63,946.0 (was 63,912.0) and BB 20 upper 64,052.0 (was 64,080.0), inside
  the 63,960-64,040 ticks plus one step.

The CMP-180 disconnected strip's "last data 00:12" is an age (L413), not a clock value, so the sweep skips it.

## Live-check fold, round 2 (2026-10-31)

The round-2 live check left two overlaps open on board 09: in CMP-189 (virtual-now) the clock pill covered `time 1`
(13:35) and `time 2` (13:40) by 8 and 7 px. Both labels were removed live and the board re-exported. The kit now drops
them too (`Crop.drop_times = {1, 2}`, E11-D02 D4: a label that overlaps a placed label is dropped as a collision), so
a rebuild reproduces the drawn board: 2838 -> 2836 shapes in the sheet, root size unchanged. Board 09's overlaps are
now 13, all by design (crosshair over tick 9, replay frame 3, watermark under the stale ink 1).

## Review fold r3b (2026-10-31, the orchestrator's round-3 items on PR #5105)

- Board 09, CMP-189 (boundary) and (maintenance band): the boundary line and both band edges are 1 px dashed 4 / 4
  (`dash.4-4`; E11-D02 D1 L108 and D8, E11-D05 L336), drawn as dash rects like the crosshair. The hatch is 45° 1 px
  lines at a 6 px pitch (E11-D05 L327, E11-D02 L140) in `color.chart.hatch.texture`, clipped to the band: each line is a
  1 px rect `hatch line · NN` centred on its diagonal, 6 * sqrt(2) px apart along x, that the post-render step rotates
  45° (30 lines in the pane, 21 in the strip; the 2 x 2 dot grid is gone, 2836 -> 2809 shapes). The band label is
  `color.text.tertiary` (L140).
- Board 10, CMP-199 (the six frames with a price value): the "BTCUSDT 1m" row reads the drawn last bar's close
  (64,014.0, the board's ▲64,014.0 pill), not a constant.
- Board 09, CMP-188 (dragging): the last-price pill is drawn (D5 L205); the ns-resize stand-in moves 6 px below it.
- Board 10, CMP-197: each frame draws the crosshair price pill in the gutter at the horizontal line, its value read off
  the price axis there (`Crop.price_at`, 0.5 tick); the kit asserts it never covers the last-price pill.
- Board 09, the status row against the 13:47:05 clock (`CLOCK`): the stale chip reads `Stale 7s · last 13:46:58`
  (clock - age) and its axis is 13:35 / 13:40 / 13:45, so the newest drawn bar is the 13:46 bar; `bar close 0:55` is
  the time to the 1m bar's close at the zone tag's clock (board 10's CMP-226 frames have no clock and keep the spec's
  `0:41`); the aggregated frame's axis is 12:30 / 13:00 / 13:30 and its chip reads `1 column = 4 bars`, read off that
  axis (minutes per px x the column width, `Crop.bars_per_column`).

Checks: the offline overlap check and the axis sweep stay at 0; the rebuild is idempotent.

## Review fold r3c (2026-10-31, values agree with the axis and the clock)

- The time axis is derived from the series (`Crop.anchor`): in every frame with a zone-tag clock and bars, the newest
  bar opens at a set minute, each bar is `mpb` minutes wide, so the axis runs `slot_w / mpb` px per minute and each time
  label sits at its own time's x (bar pitch == px per minute x minutes per bar). Labels stop at the latest bar (E11-D02
  L267) and draw only inside the strip's label area (L171 / L172); `Crop.drop_under` drops the labels a placed strip
  item covers (D8 collisions), replacing the index-based drops of the boundary, maintenance-band and virtual-now frames.
- Board 09, CMP-180 against the 13:47:05 clock: streaming, reduced detail, context lost and recovering put the newest
  bar at 13:47; stale at 13:46 (`last 13:46:58`); disconnected at 13:46 (clock - the 00:12 age); aggregated is 4 bars a
  column, the newest column opening at 13:44 (it holds the clock's minute), 30-minute labels, the chip's `1 column = 4
bars` read off the axis; replay keeps the virtual now read off the axis (13:42:59) in the zone tag and the chip.
- Board 09, CMP-189: following-type frames put the newest bar at 13:47; paused holds the view two minutes back
  (`Paused at 13:45`, the newest bar on screen). The maintenance band moves right of the 13:40 label (x 194, 90 px wide),
  its label reads `13:40 – 13:44 maintenance` (the spaced dash of E11-D02 L272) and covers only 13:45; 37 hatch lines.
- Board 10, CMP-197: the newest bar is 13:46 (no follow cluster; the view is one bar back), so the time pill held at the
  zone tag's edge sits left of the next label's centre and its value lies between the labels around it.
- Board 10, CMP-226: the readout is `last <the shared series' last close>` (the seeded 14 bars, 64,014.0, CMP-199's
  legend value), not a constant; the four frames draw no clock, so the countdown keeps the spec's values (D11).
- CMP-188 / 198 / 199 draw no time strip and no clock; CMP-190's frames show one time label (13:45) on the anchored
  axis.

Checks: the offline overlap check and the axis sweep stay at 0; a global value sweep (every clock, `last` / age,
countdown, paused time, column count, last-price, crosshair price, legend value and readout against the frame's drawn
axis and series) finds 0 of 94 checked values off; the rebuild is idempotent.
