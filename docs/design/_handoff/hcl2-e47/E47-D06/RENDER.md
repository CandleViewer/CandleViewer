# E47-D06 (#1305): render brief

Penpot file `E47-D06 boards`, page `E47-D06 — Canvas accessibility` (line 3 of every `.md`). 8 boards; every
board renders under the DARK theme and is themed only at export. Eight boards. Boards 05 and 06 are the largest of the six kits (about 1,700 and 2,300 shapes): reload the tab before each of them.

| NN  | Packed sheet                      | Board (root) name                   | Sections | Root w×h  | Export theme | PNG (`docs/design/E47/img/`)          |
| --- | --------------------------------- | ----------------------------------- | -------- | --------- | ------------ | ------------------------------------- |
| 01  | `v4/01-four-layer-inventory.json` | `E47-D06 / 01 four-layer-inventory` | 18       | 1920×1000 | dark         | `E47-D06-01-four-layer-inventory.png` |
| 02  | `v4/02-surrogate-grammar.json`    | `E47-D06 / 02 surrogate-grammar`    | 123      | 4640×1000 | dark         | `E47-D06-02-surrogate-grammar.png`    |
| 03  | `v4/03-profile-table.json`        | `E47-D06 / 03 profile-table`        | 51       | 3280×1000 | dark         | `E47-D06-03-profile-table.png`        |
| 04  | `v4/04-ladder-table.json`         | `E47-D06 / 04 ladder-table`         | 56       | 3280×1000 | dark         | `E47-D06-04-ladder-table.png`         |
| 05  | `v4/05-table-states.json`         | `E47-D06 / 05 table-states`         | 123      | 4640×1880 | dark         | `E47-D06-05-table-states.png`         |
| 06  | `v4/06-equal-status-headers.json` | `E47-D06 / 06 equal-status-headers` | 153      | 4640×1880 | dark         | `E47-D06-06-equal-status-headers.png` |
| 07  | `v4/07-parity-oracle.json`        | `E47-D06 / 07 parity-oracle`        | 12       | 1920×1000 | dark         | `E47-D06-07-parity-oracle.png`        |
| 08  | `v4/08-profile-table-light.json`  | `E47-D06 / 08 profile-table-light`  | 51       | 3280×1000 | light        | `E47-D06-08-profile-table-light.png`  |

The raw sheets (`NN-slug.json`) and their sidecars (`NN-slug.md`) sit in this folder; the packed sheets in `v4/`.
Each packed sheet's `compactOf.file` is the bare raw name, so run every driver FROM THIS FOLDER. Read each `.md` before
its board: its "Live checks" list is part of the job.

Set once: `CV_REPO` = the root of your own checkout (origin/main or later); `CV_MCP` = your bridge arguments
(`--server <entry>` and, for a local-scope entry, `--project <dir>`); `R=$CV_REPO/docs/design/_tools/sheets/run`.
Do not use `set_render.py` / `set_post_export.py` here: their md parser does not read `theme hc.`, and they do not run
from the raw folder.

**Page.** Pages go by exact NAME only: pass `--page "E47-D06 — Canvas accessibility"` to `render_exec.py` (the sheet-key default is not
this page). Its `root` step finds that page by name (`penpotUtils.getPageByName`), creates it if missing, and logs
`page=<page id>` on the `root ok` line of `out/render-NN.log`; nothing takes a page id as input except the export TSV.
Record the pair once, as the E26 renders did, in `out/page.txt`:
`{"page":{"name":"E47-D06 — Canvas accessibility","id":"<page id>"},"file":{"name":"E47-D06 boards","id":"<file id>"}}` (run `../common/pagefile.js`
through `run_js.py` with the page open: it returns exactly this object) — the return note quotes it. **Stamps.** The sheets carry no writer or provenance field to
fill in: the board footer draws `page E47-D06 — Canvas accessibility · board NN · r1` from the sheet itself, and cvlib tags its own shapes
(shared plugin data `cvd02` / `kind`) automatically. Do not add or edit either. **Local token sets: none.** Every
sheet binds only tokens of the repo's four sets (`primitives`, `semantic-dark`, `semantic-light`, `semantic-hc`,
checked against `docs/design/_tools/sheets/tools/token-sync.json`) and their `themes`.

1. **File and seed** (once, in this order; each through `python3 -I -B $R/run_js.py <file.js> $CV_MCP`):
   `python3 -I -B $CV_REPO/docs/design/_tools/penpot_token_sets.py --check`, then save and run `--emit-js` for
   `primitives`, `semantic-dark`, `semantic-light`, `semantic-hc`, and `themes` last; `$R/local-icons.js`;
   `../common/local-icons-e47.js` (the extra glyphs: search, copy, refresh, check, chevrons, info, more-horizontal,
   warning, danger, pending); `$R/theme-dark.js`; no local token set. Then `$R/probe-ro.js`.
2. **Render** each board, one at a time, 60 s apart, board 01 first (look at it before going on):
   `python3 -I -B $R/render_exec.py v4/NN-slug.json --page "E47-D06 — Canvas accessibility" --progress out/render-NN.log $CV_MCP`
   (always pass `--page`: the sheet key default is not this page). Resume with `--from <step>`. Reload your tab
   between boards once about 1,500 shapes have been drawn since the last reload (never mid-board).
3. **Post-step and live checks** right after each board: `sh ../common/board.sh NN "E47-D06 — Canvas accessibility" "<board name>"`
   (post.tmpl.js with hatch and dash on: U+2215 back to "/", `dashed · …` strokes, `hatch line · …` rotated 45°;
   then lc, lc3, lintd). Pass when: `lc.count` (nodes) = `lintd.shapes` + 1; lint `unmeasured` and `unbound` are 0
   and every other finding is acted on; `lc3.cutN` = 0 (no text cut by a clipping ancestor); `lc.h` = `lc.want`
   (footer / annotation end + 80; otherwise set the root height to `want` and re-run lc); every frame matches its md
   size, `clip` true, `spill` 0; and every item of the md's Live checks holds. Small fixes on that board only; never
   pad a padding problem. Record each live fix as a SHEET-FIX line (below).
4. **Export 1:1** (dark first): page id from `$R/pageid.js`, board id from `out/lc-NN.out`; one line per board in
   `out/dark.tsv`: `page_id<TAB>board_id<TAB>board name<TAB><png checkout>/docs/design/E47/img/<file>.png`; run
   `python3 -I -B $R/export_exec.py out/dark.tsv --progress out/export-dark.log $CV_MCP`.
5. **Theme twins**, after every dark export:
   - light: boards 08. Run `run/theme-light.js`, wait 90 s, then for each board `sh ../common/board.sh NN "E47-D06 — Canvas accessibility" "<board name>" probe` until `canvas.fill` equals the `tokenValue` of the light set; write `out/light.tsv` and run `export_exec.py out/light.tsv`.
     Then run `$R/theme-dark.js` and probe one board back to dark.
6. **Theme gate** on every PNG: `python3 -I -B ../common/themegate.py <png> dark|light|hc` (needs Pillow); every
   line PASS. Open each PNG at 1x and zoomed in: no clipped or overlapping text, no empty regions.
7. **Return**: on branch `design/hpe2-png-e47` (from origin/main; no PR) the PNGs at their export paths, one commit
   per kit, plus `docs/design/_handoff/hpe2-e47/E47-D06-render.md`: file and page {name, id}; per board: board id,
   nodes, lint counts, PNG path, pixel size and bytes, gate line; then one `SHEET-FIX E47-D06 NN <what was changed
live, and why>` line per live fix (or `SHEET-FIX none`). `out/` stays local (never commit it).
