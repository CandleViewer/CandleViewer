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
