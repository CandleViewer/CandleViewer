# E26-D02 board kit: build notes (#509, the boards leg; offline, no Penpot)

Kit `e26d02kit.py`, frame builders `gen/frames.py`, one generator per board `gen/gen_NN.py`, scan `check_all.py`.
Raw sheets and their `.md` in `build/` (not committed), the `.md` also beside the kit, packed sheets in `v4/`
(`compactOf.file` the bare raw name, its sha256 the raw sheet's). `BUILD.md` is the how-to.

## Sources (md5-pinned; the kit refuses drifted bytes)

- `docs/design/E26/E26-D02.md` and `E26-D02-handoff.md` as the boards PR commits them (RULED, comment 6555545802;
  md5s in `DOCS`), read by repo-relative path from this checkout (`CV_REPO` names another root). The sheets were
  rendered from the text at `ca477fad3`; the boards PR's edits (§16's Status cells and As built record, the status
  lines) keep every line the sheets cite in place, so the re-pinned rebuild differs only in the sources line's md5s.
- `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json` (edd9dd2a): BTCUSDT tick 0.10 and qty step 0.001,
  ETHUSDT tick 0.01 (the REAL-TIME panel only).
- Every drawn string passes `k.S` (verbatim in the spec, line breaks read as spaces) or is a noted copy gap; every
  example re-filled with this frame's values passes `k.tpl` (the example verbatim, the substitution derived).

## The PROPOSED local token (RULED BQ-10; OQ-1 the owner's)

`color.replay.border` is not a theme token. `local-tokens.json` holds one row per theme, set
`E26-D02 local · <theme>`, type color, value CR-4's primitive parsed from §16 (dark and hc `{palette.purple.400}`,
light `{palette.purple.600}`); `tokens.with-local.json` is `tools/token-sync.json` plus those rows, and is the
validator's `--tokens`. The render step creates the local set before the first section call (a live check on every
board). AC 1 never rests on the hue.

## Live-check fold

The live check's SHEET-FIX lines are folded in, so a rebuild reproduces the boards as drawn:

- every root's h is the measured footer end + 80 (`k.MEASURED_H`; the one-line data statement measured 14 px where
  the estimate allows 28): 01 1598, 02-04 1278, 05, 07 and 08 2438, 06 and 09 1398, 10 2558, each 18 px under the
  estimate;
- B1: the focus-order markers never sit left of the frame (02, 04 and 06 at x 0, not -2; `frames.focus_markers`);
- B6: the bookmark ordinals at y 0, not -2; the "landed and cancelled" tray 192 px and its moment 131
  (`frames.TRAY_MEASURED_H`; the caption wraps to two lines), the tray row keeping its drawn y;
- B9: "the 25× reason" tray 65 px and its moment 19 (the reason measured 19 px);
- B10: the open DOM menu's "Centre on mark" first line 19 px (the item and the menu hug it: 50 and 93).

Against the sheets that were rendered, the rebuilt raw sheets differ only in those values and in their notes (the
sources line's md5 pins and the live-check lines that quote the root size).

Drawn deviations, recorded in E26-D02 §16: B6 frame 16's second visually hidden box loses its bottom padding and
border to the row's estimated h (`lower`, 256 px; folded below, redraw pending); B7 and B8 frame 12's DOM scrim label
crosses a dimmed book row (kept).

## Boards-lens fold (redraw pending)

The boards lens on the drawn PNGs is folded into the kit; the PNGs are the earlier render until B4, B5, B6, B7, B8, B9
and B10 are redrawn. B1, B2 and B3 differ only in the sources line's spec md5.

- B9 frame 10: the other-sessions line (D-11) sits under the Positions row (y 88), clear of the trays.
- B10 frame 23: the hold tray's `Pause` is T1 (no lock); `replay.degraded` gates the steps, seeks and presets.
- B10 frame 22: the leave-confirm tray starts past the ticket (x 544, over the tape), so the T2 submit stays in view.
  Moving it 40 px down would cover the transport's `rbac.view_as` notice, so it moves right instead.
- B5, B7, B8, B10: the T2 `Go to` keeps its time value (lock, label, value at `type.num.xs`, all
  `color.text.tertiary`) at the T1 field's width, so the track and the thumb keep frame 04's geometry.
- B5, B7, B8: an end thumb (frames 03 and 11) turns the track's clip off, so the disc and its halo stay whole.
- B4 frame 05: `Paper fills` alone (no account attached).
- B6 frame 16: `lower` is 16 px taller (272), so the second hidden box keeps its padding and border.
- B7, B8 frame 12: the closed state's alert reads "… without a control." with §7's amended row (D-17, D-20).

## Pipeline

1. `python3 -I -B e26d02kit.py selftest` -> "OK: 0 failures".
2. `for n in 01 … 10; do python3 -I -B gen/gen_$n.py; done`: each builds its §16 nested frames with
   `frames.BUILDERS[<id>]`, writes the raw sheet (validator exit 0, kit lint, banned scan), the md (line 3 = the
   render line) and the packed sheet (mkcall4 `count` agrees).
3. `python3 -I -B check_all.py` -> "OK: 0 findings" (validator, mkcall4, compactOf, 0 inst, local icons, no boolean
   wrap, no "/" in names, captions, 8 px cells, row / column overflow and sibling overlap by estimate, md5 pin,
   local-token rows). Board markers, trays, the thumb, the frame and chip, strips, scrims and the open menu are drawn
   on top by design and left out of the overlap estimate.
4. Deterministic (seed 509, one world): a rebuild is byte-identical.

## The world (shared by every E26 board set)

BTCUSDT, window 2026-09-13 13:00–15:00 UTC (spec L25), a paper account "Paper 1"; history start 13:04:12; gap
13:52:10–13:55:40 (connection lost); partial after 14:41; playhead 13:38:04.210. One walk seeded 509 gives the prints
(no print before the history start or inside the gap); the walk is shifted so the bar holding the playhead closes at
§3's illustrative last 64,011.0; 1-minute bars, the book and the tape derive from the prints. Other moments are the
spec's own: stepped to 13:39:00, error at 13:52:04.120, closed and disconnected at 13:52:04, seek target 13:52:04,
bookmark 1 at 13:41:07 (bookmark 2 at 14:20:00 is a kit choice).

## Layout

Pages are 1920 wide: TopBar 48 (placeholders, except the CMP-074 band), header strip 32, the dock, the transport
(padding 8, rows 24 · 40 · 24, gap 4, plus a notice, a callout or the presets' reason row), StatusBar 24 (placeholder).
Composite roots hug the nested frames (rows of two, 80 px gutters) plus ONE 400 px annotation column plus 80, a
"state: <id>" caption 28 px above each frame and the data statement under them. Grid x = ((NN-1) mod 5) × 6000,
y = floor((NN-1)/5) × 3200.

## Readings (also in each board's notes)

- Frame 01 is §3's anatomy playing, no REAL-TIME watchlist; B1's 18 markers: Sessions, the chart, DOM, ticket and
  tape regions, the 13 transport stops (§12.1). §11's redlines are a seven-column callout band under the 1080 px
  anatomy (tokens cut at their first sentence).
- `Go to` is the track row's time field; revived draws no controls row (Prepare only); not found its callout alone.
- Frame 09's switch reads "Paper fills · off above 25×"; frame 10's "Paper fills · Paper 1" (on, T2 on
  replay.paper_working).
- Bookmarks only in B6's "needs CC-15 — not rendered until it lands" inset; frame 08 draws Skip gap and Stop here and
  is stamped "gap stop needs CC-1/CC-2; today the clock skips (X-7)"; the CC-2 controls are not drawn.
- A state's other moments are "board marker · tray" boxes at the dock's foot, never product UI.
- Under a whole-transport notice (no session, viewing as, hold, ended) the worded controls show the lock and the label
  with no second copy; elsewhere a 2a control carries its reason beside it; 2b badges only on |<<, <, >.
- R-170 with no session draws the bare groove (no window); buffering panels are empty and their chips show the word
  and the date only; the REAL-TIME panel is an ETHUSDT chart (kit choice) and frame 15 shows Allow real-time panels on.

## 2026-11-01 fix: board 04 frame 18 mark (sheets-check MINOR, #509)

Frame 18 (the live DEMO terminal) drew "mark —", D-15's replay-only text. `chart_head(t, live=True)` now draws
"mark {last − one tick}" from the shared world (last 64,011.0 at 13:38:04, tick 0.10 -> "mark 64,010.9", derive line
added); replay frames keep "mark —". Only board 04 regenerated (md and raw/packed sheets); selftest 0 failures,
check_all 0 findings (validator, mkcall4 count, packed sha256 = raw).
