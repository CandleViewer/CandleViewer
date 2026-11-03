# E47-D08 board kit: build notes

Ten cvsheet v4.3 sheets (22 frames) for #1307 E47-D08 (the motion layer), built offline from the approved text head.
No Penpot, no network.

## Pipeline

- Spec: `docs/design/E47/E47-D08.md` and `E47-D08-handoff.md`, read by repo-relative path from a checkout and
  md5-pinned in `DOCS` with TICKS (`packages/fixtures/src/synthetic-ticks.mjs`); the kit refuses to import on drift.
  E47-D04 (ring geometry, §7.1) and E47-D05 (SCR-117's labels, rows, Effective template) are read with `git show` at
  the pins of the spec's "Inputs pinned" line; E10-D03, E22-D04, E26-D02 and `15` at its base for the words §8 and
  §11 cite.
- `e47d08kit.py`: parses §0 (BOARDS, themes per board), §H (FRAMES), §2 (TIER_TABLE), §3 (INV, 41 rows), §4.1 (FR),
  §4.2, §4.4 (SIM rows), §8 (PAUSE), §10 (MATRIX), §11 (SAFETY), §12 (the T2 verb), §15 (COPY); ports TICKS'
  mulberry32 / generateTicks (self-tested against the generator's own output) and re-runs §4.4's simulation
  (`simulate()`, the spec tool's rules); builders, the annotation column, `board()`, sections, lint, validator,
  `write_sheet`, `write_md`, `pack_sheet`, `build`, `selftest`.
- `gen/common.py`: the synthetic world (focused symbol = the burst; two more symbols = the generator on seeds 2 / 3
  at synthetic anchors), watchlist rows with the I-5 overlay / held glyph, the DOM ladder, candles bucketed from the
  burst, the liquidation mark, the ms timeline. `gen/gen_NN.py` one per board. `check_all.py` the scan.
  `preview.py` an offline HTML preview (QA only).

## Build

In a checkout the kit sits at `docs/design/_tools/sheets/e47-d08/` (raw sheets to `build/`, packed to `v4/`);
anywhere else set `CV_CHECKOUT` to a checkout (raw sheets + `.md` to `../E47-D08-cap/`, packed to `../E47-D08-v4/`).

```sh
python3 -X utf8 -I -B e47d08kit.py selftest                 # OK: 0 failures
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                          # every sheet "ok", "OK: 0 findings"
```

A rebuild is byte-identical (raw sheets, packed sheets and `.md`). Each packed sheet's `compactOf` is the bare raw
name and the raw sheet's sha256.

## Readings (settled ambiguities)

- A-1 Twins on one board: §0 plans board 03 dark + light and board 09 dark + hc as second frames, but the token set
  is file-wide: one token-bound board exported twice, the second under the twin's set to `...-03-region-arbiter-light
.png` / `...-09-safety-static-high-contrast.png` (md line 3 stays the dark render line; the twin export is in the
  md's summary and live checks).
- A-2 Board 08's Effective line with the override Off is "Effective: Off, your choice", the Off fill of E47-D05 §5.1's
  template; §15's W-3 is that template's On fill (self-tested).
- Board 03's three elements: the liquidation mark (rank 1), the focused symbol's ladder price cell (rank 2) and
  another symbol's watchlist Last cell (rank 3) inside one 341 × 256 rectangle; the frame is the state at 1 000 ms.
- Board 04's glyph hold: a change of direction drawn at most once per FR-1; when due, the latest direction.
- Board 06: the trail fade (no hi-fi spec, D08-G1) drawn one ramp step dimmer per 6 columns of age; the live cell's
  drawn step held to FR-6 over the last 1 000 ms.
- Forced colours are not tokens: drawn token-bound and named in words (FALLBACKS forced).
- Kit labels (copy gaps, recorded per board): the liquidation mark's "<size> BTC ×<n>", CMP-208's "Kill switch:
  engaged" / "Armed rules: 2", CMP-117's reason (`15`'s open-ended line), the focused symbol's name.

## Live-check fold (after the render, 2026-11-03)

The drawing lane drew the ten boards from this kit and returned 18 fix lines and six calls. Folded here, so a rebuild
reproduces the drawn geometry:

- A text box's estimate is its live line box, ceil(size x line-height x lines): 19 px for a 13 px x 1.4 line, 14 for
  11 x 1.2 (`text_h`), kit-wide. Board 01's map cells, columns and maps grow with it; the rebuild grows 121 of 123
  cells (the drawn 93: the other 28 wrapped shorter live than the estimate), maps 682 / 500 / 566 px against the drawn
  676 / 498 / 564, every column inside its frame.
- Root heights hug max(footer end, annotation end) + 80: 998 on all ten, the checked `want` (footer end 918 + 80).
- The watchlist panel is its grid's content under the header (`WL_PANEL_H` 133; the grid 105), on boards 03 and 04;
  128 cut row 3 by 1-2.5 px.
- Board 09's chart tools row is the arm toggle's measured height (42: 24 + 4 + the reason's 14 px line box) and its
  plot 162, so tools + plot keep 204; the plot keeps the scale it was drawn at.
- Board 03's FR-2 tag sits right of the outline's top-right corner, on the chart's empty upper plot (it covered two
  ladder prices under the bottom-left corner).
- Board 07's Pause ring is drawn over the tape panel (the header keeps an empty slot of the button's size): inside
  the 28 px header the 36 px ring was clipped top and bottom.
- Drawn text carries no backtick: `text()` strips them; `check_all.py` fails one. Board 07's callout writes "4 000 ms".

Recorded, not folded: board 03's outline crossing watchlist row 1 and the DOM title (FR-2's fixed rectangle round the
three elements); board 05's reduce mark "×10" over a green body, 2.04:1 (the spec's §6 reduce carrier has no
backing: a fix row to E24-D04, spec §20); the text re-sets after a tab reload on 06 and 07 and 03's light-twin
repaint (drawing steps); board 09's high-contrast twin changes text and `color.border.default` only (the token set's
`semantic-hc` overrides no surface). The PNGs are not redrawn for the folded items (spec §20, drawn deviations).
