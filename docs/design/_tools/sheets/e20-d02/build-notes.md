# E20-D02 board kit — build notes

Ticket #574 (E20-D02): the ten greyscale wireframe boards of spec §0 (`docs/design/E20/E20-D02.md`) for the Penpot
file `E20-D02 boards`, page `E20-D02`, exported to `docs/design/E20/img/E20-D02-NN-<slug>.png`. They land in PR 2, the
boards PR, which carries the closing keyword after #573 closes (BQ-1). Offline: no Penpot, no network. Every string
comes from the spec through `k.W` (the §12 copy deck, slots filled and checked) or `k.S` (a spec string, matched
verbatim with code ticks and bold removed); labels the spec does not write are `k.ui(...)` and listed under each
sheet's `notes.copy_gaps`. Every number comes from the seeded world.

## Sources and pins (md5 in `DOCS`; the kit refuses drifted bytes)

- Spec `docs/design/E20/E20-D02.md`, md5 `e252dfbc3ddbb75528df27d70abee7dd` as built in the boards PR (§0 drawn in
  place, §19 appended; lines 1–561 in place, so every cite drawn on a board still resolves). The boards were drawn
  from the text head (md5 `152db93fec24c5698a56091d0736a0d8`, the ruling of record folded, BQ-0 … BQ-9). No hand-off
  file.
- `docs/design/E18/E18-D02.md` md5 `c18b4d41a6d91836a193cf5991a3adbf`: line 124's `delta` width floor (40 px), the
  seed of E20-K01's collapse floor (§4.1).
- `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json` md5 `edd9dd2a060c51bd4bd1450307728ddf`: tick and
  qty step for BTCUSDT (0.10 / 0.001) and ETHUSDT (0.01 / 0.001) only.
- Tools from the checkout, read-only: `docs/design/_tools/sheets/tools/` (`validate_sheet.py`,
  `components.offline.json`, `token-sync.json`, `compact.py` = the packer, `mkcall4.py`).

The kit reads by repo-relative path from a checkout: in the repo at `docs/design/_tools/sheets/e20-d02/` (REPO four
levels up; raw sheets to `build/`, packed to `v4/`), or from anywhere with `CV_CHECKOUT=<checkout>` (raw sheets to
`../E20-D02-cap/`, packed to `../E20-D02-v4/`).

## Rebuild

```sh
export CV_CHECKOUT=<a checkout at the pinned text>
python3 -X utf8 -I -B e20d02kit.py selftest       # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                # builds twice (byte-identical), scans, "OK: 0 failures"
python3 -X utf8 -I -B preview.py <raw sheet> <out.png> [--scale 0.5]   # QA only, headless Chromium
```

Every Python child the kit spawns (validator, packer, mkcall4, generators, self-test) runs as
`sys.executable -X utf8 -I -B`; every output is written UTF-8 with LF line ends.

**Small text changes.** Put the new md5 and head in `DOCS` / `HEAD`, run the self-test (a `LookupError` names the
string that moved or was reworded), then `check_all.py`. The parsers read §0's paragraph and board table (frames
included), §2's register, §3.2 / §3.3 / §3.4 / §3.6, §6.1, §9 and §12 by heading; annotation cites (`§2 L…`, `§9 L…`,
`§0 L…`) are looked up, never typed.

**Measured heights.** `MEASURED_H` (board → root h) holds the drawing lane's measured max(annotation column end,
footer end) + 80 after `touchTexts` + `relayout`; the root takes it (refused if it would not clear the footer, less one
caption line: the estimate wraps the footer one line more than the live text). A board not yet measured is estimated
with `ANN_SLACK` (15 %) on the annotation column.

## Pipeline

`gen/gen_NN.py` builds its frames with `gen/ui.py` (the SCR-030 window: top bar, price pane, CMP-225 strip, volume
sub-pane, time axis; the readout, the crosshair and data cursor, the pane menu, the x(t) markers; SCR-033's dialog,
toolbar, row list, row menu and threshold entry; the SCR-045 table and export bar) and calls `ui.run` → `k.build`: the
raw sheet (kit lint, banned scan, validator exit 0), the `.md` (line 3 is the render line), the packed sheet
(`compact.py`; the pack-source record = the raw path and sha256; mkcall4 count = sections; every packed section ≤
9216 B). Long sibling lists (candles, cells, list rows) are regrouped into overlaid bands of ≤ 8.2 KB so they pack
into few sections. Board 10 has over 2,000 shapes (noted in its live checks).

## The world (seed 574; every number derived)

An 800-bar BTCUSDT 1m series to the forming bar 14:05 (seed 574) and an ETHUSDT one (seed 575) for the per-symbol
frame. Volume lognormal (BTC around 300), Delta % uniform in ±45 % (so no unplanted bar breaches), price drifting with
the delta plus noise (divergences occur), trades from a seeded average size, intrabar max / min delta around the
delta, CVD cumulative from the first bar. Planted from §3.6's table, so the drawn values are its values: 13:58
Delta +420 and Delta % +72 % (volume = 420 / 0.72), 14:03 Delta % −68 %, 14:01 Delta % +12 %; the forming bar at
+57 % (near the 60 % bound, §3.7). The self-test proves the drawn strings equal the table and that exactly the
table's breached cells breach in the 16-bar window.

## Readings (ambiguities settled)

1. Fidelity: §0's "Greyscale, desktop, 1280 × 800 windows": `node()` refuses every colour token outside `GREY`; the
   focus ring is a 2 px color.text.primary outline (E47-D04's ring, hue-free); 10 boards, 0 twins, theme dark.
2. Frame plan: §0's frame column verbatim (30 frames); §2's register maps every frame to its board.
3. Thresholds are on, the Global set named (W-1), on every strip frame, so the world's breaches show wherever 13:58
   and 14:03 are in view (boards 01–05); board 04 is the specimen board.
4. Collapse floor: E20-K01's number is not set; the kit seeds it from E18-D02:124's `delta` floor (40 px). 16 bars
   (64 px) draw digits; 32 bars (32 px) and all three alignment densities (8 / 2.56 / 1.28 px) collapse. Below 10 px
   equal glyphs are pixel-contiguous and drawn as runs.
5. The per-symbol frame charts ETHUSDT (W-2 names it); its set's Delta % bound (50 %) is labelled example (MEMO OQ-3).
6. OI Δ source-unavailable: the synthetic BTCUSDT session on that frame has no open-interest source (no real symbol
   is claimed to lack it).
7. The row menu's range-end item is T2 2b (§1.4's table): lock + tertiary label on raised + hairline, the reason
   visually hidden and echoed by CMP-016, drawn as its own line. View-as Apply and the OI Δ checkbox are 2a with the
   reason its own line. No forced-colours / high-contrast frame is drawn (0 twins); the T2 grammar is token-bound and
   holds under any theme switch (R2's row).
8. SCR-045: Delta and Cumulative Delta are not repeated (§7.1); Delta %, Total Volume and # Trades are added after
   cvd. Total Volume duplicates the existing vol column, as §7.1's wording keeps it (only Delta and CVD are named as
   not repeated) — a spec gap for E20-S04 / D02-OQ3. The export job is a kit 86,400-bar range at 40 %.
9. The strip's gear has no local glyph: a 24 × 24 icon button with a ring-and-hub stand-in (E20-D03 owns the glyph).
10. SCR-033 behind-the-modal: an inert placeholder (the strip states are drawn on boards 01–06).
11. Data-source lines (§9: "each frame's annotation carries its row's line") are carried on each strip frame for the
    rows it introduces (Default: the five; AllRows: the other seven; the 13th row; OI Δ on board 08).

## Live-check fold

The drawing lane's live check of the ten boards (one pass; dark only) gave five fix lines, all folded here; a rebuild
reproduces the drawn sheets node for node (only those values differ from the sheets as first drawn).

1. Root heights, `MEASURED_H`: 1934 / 1026 / 1026 / 1947 / 1934 / 1026 / 1934 / 1934 / 1934 / 1934 for 01–10 (the
   footer governs on all ten; the estimate had 1952 or 1040).
2. Board-marker captions (`gen/ui.py` `LIVE_HOW`): four 'how' captions ran past their 248 px markers on one line
   (board 07: `SCR-033/reorder-keyboard`'s announcement, `SCR-033/row-menu`'s accessible text; board 08:
   `SCR-033/no-row-selected`'s and `SCR-033/source-unavailable`'s announcements). Each wraps at the marker's w − 16
   (232 px, auto-height, two live lines) and the marker grows to its content end, never shrinking: h 68, 61, 74 and 68.
   The estimate's widths run wide of the live line boxes (08's accessible-text caption estimates 234 px and fits 232
   live), so the live line count and marker h are pinned per caption; any other caption estimated more than 10 % past
   its marker is refused until it is measured. `check_all.py` asserts each pinned caption is drawn once, wrapped, with
   its pinned h.

Folded with the redraw of board 07 (2026-11-04): its `Move up` menu item is 176 px wide, so the focus ring (4 px a
side) is the 184 px item that holds it with its reason line and is no longer clipped; `check_all.py` fails any focus
ring whose left edge plus width runs past the parent that clips it.

Not folded (the PNGs are not redrawn; As built §19 records them): board 05's gear focus ring is clipped by the 28 px
strip header row (only its sides show); board 10's `x(10:46)` edge label sits on same-grey candles on the dense frame.
