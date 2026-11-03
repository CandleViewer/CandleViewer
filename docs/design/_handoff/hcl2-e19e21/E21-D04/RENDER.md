# E21-D04 (#504): render brief

Penpot file `E21-D04 boards`, page `E21-D04` (line 3 of every `.md`). 10 boards; every board renders under the DARK theme and is
themed only at export. Boards 01, 04 and 06 are light twins on ONE board each: line 3 of their .md says theme dark, and the md asks for a SECOND export of the same board under the light theme, to `-light.png`. Board 09 is a high-contrast board: it renders under dark and is exported ONCE, under high contrast only. Its forced-colours frames bind stand-in tokens (the md's kit-choice line); draw them as bound.

Spec: `docs/design/E21/E21-D04.md` at `1a320cde7` (the spec bytes on origin/main are the same); every sheet md5-pins it (notes `sources`).

| NN  | Packed sheet                       | Board (root) name                    | Sections | Root w×h  | Export theme                                           | PNG (`docs/design/E21/img/`)           |
| --- | ---------------------------------- | ------------------------------------ | -------- | --------- | ------------------------------------------------------ | -------------------------------------- |
| 01  | `v4/01-cmp-108-variants.json`      | `E21-D04 / 01 cmp-108-variants`      | 34       | 3416×1552 | dark + light `E21-D04-01-cmp-108-variants-light.png`   | `E21-D04-01-cmp-108-variants.png`      |
| 02  | `v4/02-cmp-108-density-focus.json` | `E21-D04 / 02 cmp-108-density-focus` | 22       | 3424×1072 | dark                                                   | `E21-D04-02-cmp-108-density-focus.png` |
| 03  | `v4/03-cmp-111-reveal.json`        | `E21-D04 / 03 cmp-111-reveal`        | 59       | 4040×1672 | dark                                                   | `E21-D04-03-cmp-111-reveal.png`        |
| 04  | `v4/04-cmp-113-sets-scale.json`    | `E21-D04 / 04 cmp-113-sets-scale`    | 21       | 3872×1440 | dark + light `E21-D04-04-cmp-113-sets-scale-light.png` | `E21-D04-04-cmp-113-sets-scale.png`    |
| 05  | `v4/05-ramps-cvd.json`             | `E21-D04 / 05 ramps-cvd`             | 28       | 2304×976  | dark                                                   | `E21-D04-05-ramps-cvd.png`             |
| 06  | `v4/06-cmp-230-states.json`        | `E21-D04 / 06 cmp-230-states`        | 29       | 3424×1312 | dark + light `E21-D04-06-cmp-230-states-light.png`     | `E21-D04-06-cmp-230-states.png`        |
| 07  | `v4/07-cmp-227-cmp-229-usage.json` | `E21-D04 / 07 cmp-227-cmp-229-usage` | 14       | 2956×872  | dark                                                   | `E21-D04-07-cmp-227-cmp-229-usage.png` |
| 08  | `v4/08-cmp-228-heatmap-kind.json`  | `E21-D04 / 08 cmp-228-heatmap-kind`  | 33       | 2920×1152 | dark                                                   | `E21-D04-08-cmp-228-heatmap-kind.png`  |
| 09  | `v4/09-high-contrast-forced.json`  | `E21-D04 / 09 high-contrast-forced`  | 31       | 3584×1176 | high contrast only                                     | `E21-D04-09-high-contrast-forced.png`  |
| 10  | `v4/10-token-map-redlines.json`    | `E21-D04 / 10 token-map-redlines`    | 9        | 2480×656  | dark                                                   | `E21-D04-10-token-map-redlines.png`    |

The raw sheets (`NN-slug.json`) and their sidecars (`NN-slug.md`) sit in this folder; the packed sheets in `v4/`.
Each packed sheet's `compactOf.file` is the bare raw name, so run every driver FROM THIS FOLDER. Read each `.md` before
its board: its "Live checks" list is part of the job.

Set once: `CV_REPO` = the root of your own checkout (origin/main or later); `CV_MCP` = your bridge arguments
(`--server <entry>` and, for a local-scope entry, `--project <dir>`); `R=$CV_REPO/docs/design/_tools/sheets/run`.
Do not use `set_render.py` / `set_post_export.py` here: their md parser does not read these sidecars' theme lines, and
they do not run from the raw folder.

**Page.** Pages go by exact NAME only: pass `--page "E21-D04"` to `render_exec.py`. Its `root` step finds that page by
name (`penpotUtils.getPageByName`), creates it if missing, and logs `page=<page id>` on the `root ok` line of
`out/render-NN.log`; nothing takes a page id as input except the export TSV. Record the pair once in `out/page.txt`:
`{"page":{"name":"E21-D04","id":"<page id>"},"file":{"name":"E21-D04 boards","id":"<file id>"}}` (run `../common/pagefile.js`
through `run_js.py` with the page open: it returns exactly this object); the return note quotes it. **Stamps.** The
sheets carry no writer or provenance field to fill in: the board footer draws `page E21-D04 · board NN · rN` from the
sheet itself, and cvlib tags its own shapes (shared plugin data `cvd02` / `kind`) automatically. Do not add or edit
either. **Local token sets: none.** Every sheet binds only tokens of the repo's four sets (`primitives`, `semantic-dark`, `semantic-light`, `semantic-hc`, checked against `docs/design/_tools/sheets/tools/token-sync.json`) and their `themes`.

1. **File and seed** (once, in this order; each through `python3 -I -B $R/run_js.py <file.js> $CV_MCP`):
   `python3 -I -B $CV_REPO/docs/design/_tools/penpot_token_sets.py --check`, then save and run `--emit-js` for
   `primitives`, `semantic-dark`, `semantic-light`, `semantic-hc`, and `themes` last; `$R/local-icons.js`;
   `../common/local-icons-e19e21.js` (the extra glyphs this kit uses); `$R/theme-dark.js`. Then `$R/probe-ro.js`.
2. **Render** each board, one at a time, 60 s apart, board 01 first (look at it before going on):
   `python3 -I -B $R/render_exec.py v4/NN-slug.json --page "E21-D04" --progress out/render-NN.log $CV_MCP`
   (always pass `--page`). Resume with `--from <step>`. Reload your tab between boards once about 1,500 shapes have
   been drawn since the last reload (never mid-board).
3. **Post-step and live checks** right after each board: `sh ../common/board.sh NN "E21-D04" "<board name>"`
   (post.tmpl.js with hatch and dash on: U+2215 back to "/", `dashed · …` strokes, `hatch line · …` rotated 45°;
   then lc, lc3, lintd). Pass when:
   - nodes: `lc.count` = `lintd.shapes` + 1 (the root);
   - lint: `unmeasured` and `unbound` are 0, and every other finding is acted on;
   - text vs clipping ancestors: `lc3.cutN` = 0 (no text cut by any clipping ancestor, frame or root);
   - root height: `lc.h` = `lc.want` = footer / annotation end + 80; otherwise set the root height to `want` and re-run lc;
   - frames: every frame matches its md size, `clip` true, `spill` 0;
   - line height: a 13 px text at line height 1.4 renders a 19 px line (not 18.2), so a block of n lines stands
     n × 19 px tall; when a frame spills or `cutN` is not 0, that rounding is the usual cause: raise the frame in 8 px
     steps, never pad the text;
   - and every item of the md's Live checks holds.
     Small fixes on that board only; never pad a padding problem. Record each live fix as a SHEET-FIX line (below).
4. **Export 1:1** (scale 1, no crop; dark first): page id from `$R/pageid.js`, board id from `out/lc-NN.out`; one line
   per dark-exported board (01, 02, 03, 04, 05, 06, 07, 08, 10) in `out/dark.tsv`:
   `page_id<TAB>board_id<TAB>board name<TAB><png checkout>/docs/design/E21/img/<file>.png`; run
   `python3 -I -B $R/export_exec.py out/dark.tsv --progress out/export-dark.log $CV_MCP`.
5. **Theme exports**, after every dark export:
   - light: boards 01, 04, 06 (twins 01, 04, 06: their second export, to `…-light.png`). Run `$R/theme-light.js`, wait 90 s, then for each board `sh ../common/board.sh NN "E21-D04" "<board name>" probe` until `canvas.fill` equals the `tokenValue` of the light set; write `out/light.tsv` and run `export_exec.py out/light.tsv`.
   - high contrast: board 09 (its only export). Run `$R/theme-hc.js`, wait 90 s, then `sh ../common/board.sh NN "E21-D04" "<board name>" probe` until `canvas.fill` equals the `tokenValue` of the high contrast set; write `out/hc.tsv` and run `export_exec.py out/hc.tsv`.
     Then run `$R/theme-dark.js` and probe one board back to dark.
6. **Theme gate** on every PNG: `python3 -I -B ../common/themegate.py <png> dark|light|hc` (needs Pillow): every dark PNG `dark`, every light PNG `light`, the high-contrast PNG `hc`; every
   line PASS. A FAIL is never re-labelled: re-probe, re-export, and gate again. Open each PNG at 1x and zoomed in: no
   clipped or overlapping text, no empty regions. Each PNG's pixel size equals the board's final root w×h (1:1).
7. **Return**: on branch `design/hpe2-png-e19e21` (from origin/main; no PR) the PNGs at their export paths, one commit
   per kit, plus `docs/design/_handoff/hpe2-e19e21/E21-D04-render.md`: file and page {name, id}; per board: board id,
   nodes, lint counts, `cutN`, PNG path, pixel size and bytes, gate line; then one SHEET-FIX line per live fix, in the
   form `SHEET-FIX E21-D04 NN <what was changed live, and why>` (or `SHEET-FIX none`). `out/` stays local (never commit it).

## Two live notes

- Link underlines take the words' measured widths. If one is off after the render, fix it in Penpot and report it
  as a `SHEET-FIX` line.
- After a tab reload, the first texts drawn may not paint in the first export. Look at each PNG, and re-set any
  blank texts (then re-export that board).

## Big boards and kit checks

- Boards of about 2,000 shapes or more push the single whole-board relayout call past the bridge's 120 s limit:
  run relayout per top-level child instead, draw one section per call, clear the selection after each call, and keep
  the window in the foreground (texts only measure there). Shape estimates run low by about a quarter.
- No board reaches 1,500 nodes: the largest is board 03 cmp-111-reveal (59 sections, about 1,340 nodes in its sheet, 4040×1672), then board 09 high-contrast-forced (about 660) and board 01 cmp-108-variants (about 620).
- Kit check, backticks in drawn cite text: boards 02 (1 string) and 10 (3). Strip the backticks from the drawn text (keep the words) and report it as one SHEET-FIX line per board.
- Kit check, rect markers that should be dashed: none found. The 11 stroke-only rects (`CMP-039 focus ring`, `ring gap`, `CMP-230 glyph`) are solid outlines and are meant to be solid; no `hatch line · …` names. U+2215 in frame names (256): the post-step turns them into "/".
