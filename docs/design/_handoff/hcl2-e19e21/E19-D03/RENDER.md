# E19-D03 (#438): render brief

Penpot file `E19-D03 boards`, page `E19-D03` (line 3 of every `.md`). 10 boards; every board renders under the DARK theme and is
themed only at export. Boards 02, 05 and 09 are light boards: they render under dark like every other board and are exported ONCE, under the light theme only (not under dark). Board 06 is the largest sheet of the three kits (84 sections, 3280×3416): see Big boards.

Spec: `docs/design/E19/E19-D03.md` at `811292427` (same spec bytes at `35032f521`); every sheet md5-pins it (notes `sources`).

| NN  | Packed sheet                    | Board (root) name                 | Sections | Root w×h  | Export theme | PNG (`docs/design/E19/img/`)        |
| --- | ------------------------------- | --------------------------------- | -------- | --------- | ------------ | ----------------------------------- |
| 01  | `v4/01-docked-redlines.json`    | `E19-D03 / 01 docked-redlines`    | 36       | 3280×1896 | dark         | `E19-D03-01-docked-redlines.png`    |
| 02  | `v4/02-docked-light.json`       | `E19-D03 / 02 docked-light`       | 9        | 1920×1016 | light only   | `E19-D03-02-docked-light.png`       |
| 03  | `v4/03-overlay-densities.json`  | `E19-D03 / 03 overlay-densities`  | 30       | 3280×1896 | dark         | `E19-D03-03-overlay-densities.png`  |
| 04  | `v4/04-cmp-110-variants.json`   | `E19-D03 / 04 cmp-110-variants`   | 38       | 2880×2136 | dark         | `E19-D03-04-cmp-110-variants.png`   |
| 05  | `v4/05-greyscale-cvd.json`      | `E19-D03 / 05 greyscale-cvd`      | 23       | 3280×1896 | light only   | `E19-D03-05-greyscale-cvd.png`      |
| 06  | `v4/06-cmp-183-periods.json`    | `E19-D03 / 06 cmp-183-periods`    | 84       | 3280×3416 | dark         | `E19-D03-06-cmp-183-periods.png`    |
| 07  | `v4/07-cmp-184-tpo.json`        | `E19-D03 / 07 cmp-184-tpo`        | 40       | 3280×2536 | dark         | `E19-D03-07-cmp-184-tpo.png`        |
| 08  | `v4/08-rays-npoc-tooltip.json`  | `E19-D03 / 08 rays-npoc-tooltip`  | 53       | 3280×2776 | dark         | `E19-D03-08-rays-npoc-tooltip.png`  |
| 09  | `v4/09-settings.json`           | `E19-D03 / 09 settings`           | 48       | 3280×1896 | light only   | `E19-D03-09-settings.png`           |
| 10  | `v4/10-table-focus-states.json` | `E19-D03 / 10 table-focus-states` | 68       | 3280×2776 | dark         | `E19-D03-10-table-focus-states.png` |

The raw sheets (`NN-slug.json`) and their sidecars (`NN-slug.md`) sit in this folder; the packed sheets in `v4/`.
Each packed sheet's `compactOf.file` is the bare raw name, so run every driver FROM THIS FOLDER. Read each `.md` before
its board: its "Live checks" list is part of the job.

Set once: `CV_REPO` = the root of your own checkout (origin/main or later); `CV_MCP` = your bridge arguments
(`--server <entry>` and, for a local-scope entry, `--project <dir>`); `R=$CV_REPO/docs/design/_tools/sheets/run`.
Do not use `set_render.py` / `set_post_export.py` here: their md parser does not read these sidecars' theme lines, and
they do not run from the raw folder.

**Page.** Pages go by exact NAME only: pass `--page "E19-D03"` to `render_exec.py`. Its `root` step finds that page by
name (`penpotUtils.getPageByName`), creates it if missing, and logs `page=<page id>` on the `root ok` line of
`out/render-NN.log`; nothing takes a page id as input except the export TSV. Record the pair once in `out/page.txt`:
`{"page":{"name":"E19-D03","id":"<page id>"},"file":{"name":"E19-D03 boards","id":"<file id>"}}` (run `../common/pagefile.js`
through `run_js.py` with the page open: it returns exactly this object); the return note quotes it. **Stamps.** The
sheets carry no writer or provenance field to fill in: the board footer draws `page E19-D03 · board NN · rN` from the
sheet itself, and cvlib tags its own shapes (shared plugin data `cvd02` / `kind`) automatically. Do not add or edit
either. **Local token sets: three.** Spec §2.1's `color.tpo.letter` and `color.tpo.initialbalance` are PROPOSED aliases that the repo's sets do not define yet. `local-tokens.json` (in this folder) holds them as one row per theme set: `E19-D03 local · dark`, `E19-D03 local · light`, `E19-D03 local · hc`. `local-tokens.js` creates those sets and adds each to its own theme only (`dark`, `light`, `high-contrast`), after the theme's repo sets, so the theme switch drives them like any other set. `tokens.with-local.json` is the repo's `token-sync.json` (equal to origin/main's at packaging) with those six rows appended: the validator needs it (`--tokens`), because the default token list does not know `color.tpo.*` and exits 1 on exactly those names. Never edit the repo's token files.

1. **File and seed** (once, in this order; each through `python3 -I -B $R/run_js.py <file.js> $CV_MCP`):
   `python3 -I -B $CV_REPO/docs/design/_tools/penpot_token_sets.py --check`, then save and run `--emit-js` for
   `primitives`, `semantic-dark`, `semantic-light`, `semantic-hc`, and `themes` last; `local-tokens.js` (from this folder, after the `themes` emit); `$R/local-icons.js`;
   `../common/local-icons-e19e21.js` (the extra glyphs this kit uses); `$R/theme-dark.js`. Then `$R/probe-ro.js`.
2. **Render** each board, one at a time, 60 s apart, board 01 first (look at it before going on):
   `python3 -I -B $R/render_exec.py v4/NN-slug.json --page "E19-D03" --progress out/render-NN.log $CV_MCP`
   (always pass `--page`). Resume with `--from <step>`. Reload your tab between boards once about 1,500 shapes have
   been drawn since the last reload (never mid-board).
3. **Post-step and live checks** right after each board: `sh ../common/board.sh NN "E19-D03" "<board name>"`
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
   per dark-exported board (01, 03, 04, 06, 07, 08, 10) in `out/dark.tsv`:
   `page_id<TAB>board_id<TAB>board name<TAB><png checkout>/docs/design/E19/img/<file>.png`; run
   `python3 -I -B $R/export_exec.py out/dark.tsv --progress out/export-dark.log $CV_MCP`.
5. **Theme exports**, after every dark export:
   - light: boards 02, 05, 09 (their only export). Run `$R/theme-light.js`, wait 90 s, then for each board `sh ../common/board.sh NN "E19-D03" "<board name>" probe` until `canvas.fill` equals the `tokenValue` of the light set; write `out/light.tsv` and run `export_exec.py out/light.tsv`.
     Then run `$R/theme-dark.js` and probe one board back to dark.
6. **Theme gate** on every PNG: `python3 -I -B ../common/themegate.py <png> dark|light|hc` (needs Pillow): every dark PNG `dark`, every light PNG `light`; where a light board binds `color.tpo.*`, read one such fill back as the light local value before export; every
   line PASS. A FAIL is never re-labelled: re-probe, re-export, and gate again. Open each PNG at 1x and zoomed in: no
   clipped or overlapping text, no empty regions. Each PNG's pixel size equals the board's final root w×h (1:1).
7. **Return**: on branch `design/hpe2-png-e19e21` (from origin/main; no PR) the PNGs at their export paths, one commit
   per kit, plus `docs/design/_handoff/hpe2-e19e21/E19-D03-render.md`: file and page {name, id}; per board: board id,
   nodes, lint counts, `cutN`, PNG path, pixel size and bytes, gate line; then one SHEET-FIX line per live fix, in the
   form `SHEET-FIX E19-D03 NN <what was changed live, and why>` (or `SHEET-FIX none`). `out/` stays local (never commit it).

## Two live notes

- Link underlines take the words' measured widths. If one is off after the render, fix it in Penpot and report it
  as a `SHEET-FIX` line.
- After a tab reload, the first texts drawn may not paint in the first export. Look at each PNG, and re-set any
  blank texts (then re-export that board).

## Big boards and kit checks

- Boards of about 2,000 shapes or more push the single whole-board relayout call past the bridge's 120 s limit:
  run relayout per top-level child instead, draw one section per call, clear the selection after each call, and keep
  the window in the foreground (texts only measure there). Shape estimates run low by about a quarter.
- Over 2,000 nodes here: board 06 cmp-183-periods (84 sections, about 3,650 nodes in its sheet, 3280×3416) and board 08 rays-npoc-tooltip (53 sections, about 2,400). Draw them per section and run relayout per child. Next largest, under the line but worth the same care: board 07 cmp-184-tpo (about 1,570), board 10 table-focus-states (about 1,500), board 09 settings (about 1,430), board 03 overlay-densities (about 1,220) and board 01 docked-redlines (about 1,080). All other boards are under 800.
- Kit check, backticks in drawn cite text: boards 06 (6 strings: the period lines' "`24` kind ..."), 07 (1), 08 (1) and 10 (1). Strip the backticks from the drawn text (keep the words) and report it as one SHEET-FIX line per board.
- Kit check, hatch and dash: 935 `hatch line · …` rectangles across the kit (the post-step rotates them 45°); no `dashed · …` names. The 12 stroke-only rects (`halo outer`, `halo inner`, `ring`) are solid focus outlines and are meant to be solid.
- U+2215 in frame names (365 across the kit): the post-step turns them into "/"; never type them by hand.
