# E21-D04 board kit — build notes

Ticket #504 (E21-D04): the design-system pack's ten specimen boards (§0; BQ-13 RULED, comment 6580397401) for the
per-set Penpot file `E21-D04 boards`, page `E21-D04`. They land in PR 2, the boards PR, which carries the closing
keyword (BQ-1 OVERRIDE: two PRs). Offline: no Penpot, no network. The boards are drawn: E21-D04 §0 holds each
board's id, PNGs and gates, §14 the as-built record.

## Build

From a checkout (the kit at `docs/design/_tools/sheets/e21-d04/`; outputs in `build/` and `v4/`, the `.md` also beside
the kit) or from anywhere with `CV_CHECKOUT=<checkout>` (outputs in the sibling `E21-D04-cap/` and `E21-D04-v4/`):

    python3 -X utf8 -I -B e21d04kit.py selftest           # "OK: 0 failures"
    for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
    python3 -X utf8 -I -B check_all.py --rebuild          # every generator twice (byte-identical), then the scans

Sources, md5-pinned in `DOCS` at the as-built text (the boards PR; the board text is r2's) and read by repo-relative path (the kit refuses drifted
bytes): `docs/design/E21/E21-D04.md` (§0 board table, §1.3 R-3, §4.1 template and tokens, §4.8 W-1 … W-25, §5.1 sets,
§5.2 / §5.3 tables, §5.5), `E21-D04-handoff.md` (the seven Table 1s: 41 Penpot variant ids; CMP-230's drag row names none) and the recorded
fixture `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json` (tick 0.10, qty step 0.001). Tools are the
checkout's `docs/design/_tools/sheets/tools/` (validator with `components.offline.json` and `token-sync.json`,
`compact.py`, `mkcall4.py count`). **After PR 1's design read changes the text:** re-pin `DOCS` (md5 of both files),
re-run the self-test (it re-checks §5.2's lowest stops against the computed ratios and W-1 against the template),
rebuild, re-run `check_all.py --rebuild`. Every `L<n>` cite and every string is looked up, never typed.

Layout: `e21d04kit.py` (registries, tokens + per-theme values and WCAG ratio, node primitives, the world, frame plan,
annotation column, board root, write / md / pack, self-test); `gen/frames.py` (ladder rows, heatmap pane, CMP-024
sparkline, CMP-111 reveal, CMP-113 legend, CMP-228 tile, notice, the per-board builders); `gen/gen_NN.py`;
`check_all.py`.

## The world (seed 504; every number derived)

Synthetic BTCUSDT book: mark 65,432.0 (W-1's example price), best bid one tick below, best ask two ticks above (the
mark row and the next sit inside the spread, so they read "none" on both sides); 24 levels a side, lognormal sizes on
the qty step; the last trades at the mark, best bid and best ask (Prints). A bid wall (14.5) at best bid − 5 ticks is
pulled at trail column 8 of 12 with no print at its price (W-16, M AD-6). Own orders are props of a DEMO session
(Acct A, Acct B; resting limits are part of their level's size, stops are not): single buy 0.5 limit; aggregate
3 orders buy 1.2 (W-3); mixed 3 orders buy 1.0 · sell 0.2 (W-4); pending sell 0.3; amending buy 0.4; a long 0.30
position (W-9's size). The queue estimate (W-8) = the level's size less the own orders there. Trail 12 × 1 s to
14:32:10 UTC (W-17). Heatmap stop = ceil(5 × log-scaled size / the window's largest); legend anchors 0, the middle
stop's edge, the largest size. Bars: size / the window's largest × the 80 px inner width.

## Readings taken (ambiguities settled)

1. Frames: §0 names no frames; the hand-off's Table 1 Penpot variant ids are the frame ids (FRAME_PLAN, 51 frames),
   kit-named where §0 draws an axis Table 1 lacks (board 02 `, Density=…`; 05; 09 `/ High contrast`, `/ Forced
colours`; 10). Frames not on a board (CMP-111 closed / inverted / CVD rows, CMP-108 VirtualisedWindow, CMP-113
   forced row as such) stay text (§0 "not drawn").
2. "dark + light" (01, 04, 06): themes are file-wide and the validator refuses primitive colour binds, so a light frame
   cannot sit on a dark board. The light twin is the same board exported a second time under the light set as
   `E21-D04-NN-<slug>-light.png`; line 3 stays `theme dark.`; the md's live checks carry the second export.
3. Board 09: §0 says dark, but its high-contrast rows are only true under the high-contrast set, so its line 3 reads
   `theme high-contrast.` (the drivers' word; the brief's "hc" does not parse in `_sets.py`). It is not a twin of a
   drawn board, so the twin count stays 3 of 10. Forced-colour frames bind stand-ins (Canvas = surface.app,
   CanvasText = text.primary, Highlight = action.primary.default, GrayText = text.tertiary).
4. Board 05's "greyscale and the three simulations of board 04" cannot be painted (no raw colours): `cvd_sim.py`
   renders board 04's export (greyscale, deuteranopia, protanopia); tritanopia has no image tool, so §5.3's computed
   table stands (spec gap). The frame draws the four sets' stops and every stop's computed ratio in three themes.
5. Size bar "inner edge": the edge toward the other side's column (bids grow from the right, asks from the left).
6. CMP-108 `estimated` row = the pulled level, with CMP-227 `inline` in the Price cell; `stale` = the stale surface
   and the word in the Price cell.
7. CMP-229 drawn in a DEMO session only (LIVE = the same pill reading the session), so no synthetic account appears
   under both environments (C-2.11). W-19's size is the single own order's 0.5.
8. Copy gaps (drawn, PROPOSED, sourced in each md): "Bid (B)" / "Ask (A)" (D02 §2.3), "alert here" / "copy price"
   (D02 §5.2), the CMP-134 chip placeholder (E25's words), board labels on 05 and 10. CMP-227's `estimated` glyph and
   CMP-230's glyph are stand-ins (local `info`, an 8 px side square). The inverted legend swaps W-12's colours.
9. Root heights: the drawn ones, `MEASURED_H` (see the live-check fold below); `est_height` is the guard.
10. CMP-230 drag (r2, after the design-read fold): absent while E21 holds, no control and no T2 state (§0 "no drag",
    §4.4, hand-off Table 1's drag row, D02:265). Board 06's eighth frame is kit-named `CMP-230 · OwnOrderMarker /
No drag`: the panel's notice with W-20 above a single own-order row with no handle; DragT2 is gone.
11. W-1 is drawn verbatim in board 01's annotation column; the rows' names are §4.1's template filled from the book.
12. W-21 … W-23 (the cancel results) are spoken once through the status node (R-5), never shown; §0 draws no cancel
    result, so they are listed under "not drawn — the text is binding" (annotation column and each md's notes).

## Live-check fold (the drawing lane's fix lines, 2026-11-03)

Every fix line of the live check is folded in, so a rebuild reproduces the drawn sheets node for node; the only
differences from the sheets as handed over are these (and the sheets' `notes`, which carry the spec pin):

- Root heights: `MEASURED_H`, the checked max(annotation end, footer end) + 80 (01 1512, 02 999, 03 1670, 04 1400,
  05 958, 06 1195, 07 789, 08 1030, 09 1033, 10 597; board 09 measured 1129 after its redraw with the T2 reason and the panel notice). Every root came out 2 to 143 px shorter than the kit's estimate:
  the annotation columns wrap fewer lines live. The root estimate now takes Inter's advance as 0.51 em
  (`INTER_EM["root"]`; the nodes' own widths keep 0.56, so no drawn geometry moves), which puts the ten estimates
  within -13 … +37 px of the drawn heights, and `board()` refuses a checked height more than `MEASURED_SLACK` (48 px)
  from its estimate: past that the text has changed since the measure, so measure again.
- Backticks: four drawn texts carried cite backticks (one on board 02, three on board 10); the drawing lane removed
  them live with the words kept. `text()` now strips every backtick from drawn text, and `check_all.py` fails on one.
- Board 09: a forced-colours system colour cannot be drawn in Penpot, so the forced-colours frames bind stand-in
  tokens (reading 3) and the ring is `color.action.primary.default`; the frames' note now says the drawn ring is a
  stand-in token (E21-D04 §14 records it as a drawn deviation).
- Board 05's colour-vision exports of board 04 are `cvd_sim.py` renders of board 04's dark export (reading 4).
- Every Python child the kit spawns (the validator, the packer, `mkcall4.py`, the generators under `check_all.py`)
  runs with `-X utf8`, so the build also runs on a cp1252 Windows host; the packed sheets keep the bare raw-sheet name.
