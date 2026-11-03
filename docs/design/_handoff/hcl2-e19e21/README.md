# Three E19 / E21 board kits for the drawing lane (transport only)

This branch carries board sheets from one lane to another. It is never merged and has no PR. The drawing lane draws
the boards in its own Penpot, exports the PNGs, and returns them on its own branch (see each kit's `RENDER.md`, step 7).

Every sheet was built offline by its kit's generators, against the spec text at the head named below. The kits
md5-pin their sources and refuse drifted bytes; each kit's self-test and full scan passed and a rebuild was
byte-identical before packaging, so nothing was regenerated here. Every raw sheet passes `validate_sheet.py` (0 errors;
E19-D03's with `--tokens tokens.with-local.json`, see below), every packed sheet's `compactOf` names its raw sheet by
bare file name with a matching sha256, and `mkcall4.py <packed> count` exits 0 for all 30. E21-D03's kit stamps the
absolute build path in `compactOf.file`; its ten packed sheets here went through the bare-name step the other two kits
apply after `compact.py` (that one field rewritten, sha256 and every section unchanged).

The folder is self-contained, and every path in it is relative. It holds no Penpot host, team id, file id or URL. Pages
are named by page name only. The drivers, libraries, post-step (`run/post.tmpl.js`), validator and token tooling are the
repository's own, under `docs/design/_tools/sheets/` and `docs/design/_tools/penpot_token_sets.py` at origin/main.

## The kits

| Ticket | Kit        | Spec (text head)                           | Penpot file / page           | Boards | Twins                                 | Sections | Packed bytes |
| ------ | ---------- | ------------------------------------------ | ---------------------------- | ------ | ------------------------------------- | -------- | ------------ |
| #504   | `E21-D04/` | `docs/design/E21/E21-D04.md` (`1a320cde7`) | `E21-D04 boards` / `E21-D04` | 10     | 01, 04, 06 +light (same board); 09 hc | 280      | 518,488      |
| #503   | `E21-D03/` | `docs/design/E21/E21-D03.md` (`c7b0d2087`) | `E21-D03 boards` / `E21-D03` | 10     | 01, 05, 09 +light (same board)        | 290      | 673,113      |
| #438   | `E19-D03/` | `docs/design/E19/E19-D03.md` (`811292427`) | `E19-D03 boards` / `E19-D03` | 10     | 02, 05, 09 light                      | 429      | 1,233,327    |

Draw the kits in this order (top to bottom; smallest first), one Penpot file per kit, one board at a time. Light and
high-contrast boards still render under dark; only their export runs under the other theme. A "+light (same board)"
twin is exported twice (dark, then light); a plain "light" or "hc" board is exported once, under that theme only.

E19-D03 is the only kit with local token sets (spec §2.1's PROPOSED `color.tpo.letter` and
`color.tpo.initialbalance`): seed them with `E19-D03/local-tokens.js` and validate with
`--tokens tokens.with-local.json` (its `RENDER.md` says how). Its board 06 is about 3,650 nodes: draw it per section.

## What's in the folder

| Path                                                | What it is                                                                                                                                    |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `<KIT>/NN-slug.json`                                | the raw sheet (the validator's input, and the file each packed sheet's `compactOf` names)                                                     |
| `<KIT>/NN-slug.md`                                  | the sidecar: line 3 names file, page, export path and theme; then frames, live checks, ambiguities                                            |
| `<KIT>/v4/NN-slug.json`                             | the packed sheet the renderer takes (cvsheet v4.3 via `mkcall4.py`)                                                                           |
| `<KIT>/RENDER.md`                                   | the kit's render brief: seed, render, post-step and live checks, export, twins, gate, return                                                  |
| `E19-D03/local-tokens.json`                         | the six PROPOSED `color.tpo.*` rows, one per local theme set (`E19-D03 local · dark`, `· light`, `· hc`)                                      |
| `E19-D03/local-tokens.js`                           | creates those three sets in the open file and adds each to its own theme only; idempotent                                                     |
| `E19-D03/tokens.with-local.json`                    | the repo's `token-sync.json` plus those six rows: the validator's `--tokens` file for E19-D03                                                 |
| `common/local-icons-e19e21.js`                      | the repo's `run/local-icons.js` glyphs plus the ones the kits use (check, chevrons, info, more-horizontal, warning, danger, pending, refresh) |
| `common/board.sh`                                   | per board, after render: the repo's `post.tmpl.js` (hatch and dash on), then `lc`, `lc3`, `lintd`; with `probe`, the theme probe alone        |
| `common/lc.tmpl.js`, `lc3.tmpl.js`, `lintd.tmpl.js` | the live-check scripts (nodes, frames, root end + 80; text vs clipping ancestors; lint)                                                       |
| `common/probe.tmpl.js`                              | read-only theme probe: the board's `color.surface.canvas` fill against the active token value                                                 |
| `common/pagefile.js`                                | read-only: the open file and page as `{name, id}` pairs, the `out/page.txt` form                                                              |
| `common/themegate.py`                               | `themegate.py <png> dark\|light\|hc`: PASS when the PNG's text pixels are the claimed theme's (needs Pillow)                                  |
| `.gitignore`                                        | keeps each kit's `out/` (logs, filled JS, TSVs) and `STOP` out of git                                                                         |
| `MANIFEST.sha256`                                   | sha256 and relative path of every other file, generated last                                                                                  |

## Checks you can run before drawing (offline)

From this folder, with `T=<your checkout>/docs/design/_tools/sheets/tools`:

```sh
sha256sum -c MANIFEST.sha256
for k in E21-D04 E21-D03 E19-D03; do
  tk=""; [ "$k" = E19-D03 ] && tk="--tokens $k/tokens.with-local.json"
  for f in $k/[0-9][0-9]-*.json; do
    python3 -I -B $T/validate_sheet.py $f --components $T/components.offline.json $tk > /dev/null || echo "FAIL $f"
    (cd $k && python3 -I -B $T/mkcall4.py v4/$(basename $f) count > /dev/null) || echo "STALE $f"
  done
done
```

No line should print. A sheet is never edited by hand: a problem found live is fixed on the board and reported as a
`SHEET-FIX` line, and the kit is regenerated on the sending side.
