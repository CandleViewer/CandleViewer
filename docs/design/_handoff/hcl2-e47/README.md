# Six E47 board kits for the drawing lane (transport only)

This branch carries board sheets from one lane to another. It is never merged and has no PR. The drawing lane draws
the boards in its own Penpot, exports the PNGs, and returns them on its own branch (see each kit's `RENDER.md`, step 7).

Every sheet was built offline by its kit's generators, against the spec text at the head named below. The kits
md5-pin their sources, and before packaging every pin was re-checked against that head: all six kits are current, so
nothing was regenerated. Every raw sheet passes `validate_sheet.py` (0 errors), every packed sheet's `compactOf`
names its raw sheet by bare file name with a matching sha256, and `mkcall4.py <packed> count` exits 0 for all 58.
E47-D09's kit stamps the absolute build path in `compactOf.file`; its ten packed sheets here went through the bare-name
step the other five kits apply after `compact.py` (that one field rewritten, sha256 and every section unchanged).

The folder is self-contained, and every path in it is relative. It holds no Penpot host, team id, file id or URL. Pages
are named by page name only. The drivers, libraries, post-step (`run/post.tmpl.js`), validator and token tooling are the
repository's own, under `docs/design/_tools/sheets/` and `docs/design/_tools/penpot_token_sets.py` at origin/main.

## The kits

| Ticket | Kit        | Spec (text head)                           | Penpot file / page                                   | Boards | Twins                          | Sections | Packed bytes |
| ------ | ---------- | ------------------------------------------ | ---------------------------------------------------- | ------ | ------------------------------ | -------- | ------------ |
| #1304  | `E47-D05/` | `docs/design/E47/E47-D05.md` (`3987edc89`) | `E47-D05 boards` / `E47-D05 SCR-117`                 | 10     | 02 light, 03 hc                | 216      | 636,031      |
| #1308  | `E47-D09/` | `docs/design/E47/E47-D09.md` (`260bb0caf`) | `E47-D09 boards` / `E47-D09`                         | 10     | 02, 06 light, 10 hc            | 529      | 1,065,838    |
| #1311  | `E47-D13/` | `docs/design/E47/E47-D13.md` (`91e9bde44`) | `E47-D13 boards` / `E47-D13 — Conformance statement` | 10     | 02, 10 light, 04 hc            | 305      | 427,990      |
| #1305  | `E47-D06/` | `docs/design/E47/E47-D06.md` (`7a9002dbd`) | `E47-D06 boards` / `E47-D06 — Canvas accessibility`  | 8      | 08 light                       | 587      | 911,121      |
| #1306  | `E47-D07/` | `docs/design/E47/E47-D07.md` (`260510d44`) | `E47-D07 boards` / `E47-D07 announcements`           | 10     | 07 light                       | 203      | 332,325      |
| #1307  | `E47-D08/` | `docs/design/E47/E47-D08.md` (`e60fe7baa`) | `E47-D08 boards` / `E47-D08 — Motion`                | 10     | 03 +light, 09 +hc (same board) | 517      | 547,740      |

Draw the kits in this order (top to bottom), one Penpot file per kit, one board at a time. Light and high-contrast
boards still render under dark; only their export runs under the other theme. E47-D08's boards 03 and 09 are exported
twice (dark, then light or high contrast).

## What's in the folder

| Path                                                | What it is                                                                                                                                                        |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `<KIT>/NN-slug.json`                                | the raw sheet (the validator's input, and the file each packed sheet's `compactOf` names)                                                                         |
| `<KIT>/NN-slug.md`                                  | the sidecar: line 3 names file, page, export path and theme; then frames, live checks, ambiguities                                                                |
| `<KIT>/v4/NN-slug.json`                             | the packed sheet the renderer takes (cvsheet v4.3 via `mkcall4.py`)                                                                                               |
| `<KIT>/RENDER.md`                                   | the kit's render brief: seed, render, post-step and live checks, export, twins, gate, return                                                                      |
| `common/local-icons-e47.js`                         | the repo's `run/local-icons.js` glyphs plus the 11 more the kits use (search, copy, refresh from `packages/ui` Lucide sources); run it after `run/local-icons.js` |
| `common/board.sh`                                   | per board, after render: the repo's `post.tmpl.js` (hatch and dash on), then `lc`, `lc3`, `lintd`; with `probe`, the theme probe alone                            |
| `common/lc.tmpl.js`, `lc3.tmpl.js`, `lintd.tmpl.js` | the live-check scripts (nodes, frames, root end + 80; text vs clipping ancestors; lint)                                                                           |
| `common/probe.tmpl.js`                              | read-only theme probe: the board's `color.surface.canvas` fill against the active token value                                                                     |
| `common/pagefile.js`                                | read-only: the open file and page as `{name, id}` pairs, the `out/page.txt` form                                                                                  |
| `common/themegate.py`                               | `themegate.py <png> dark\|light\|hc`: PASS when the PNG's text pixels are the claimed theme's (needs Pillow)                                                      |
| `.gitignore`                                        | keeps each kit's `out/` (logs, filled JS, TSVs) and `STOP` out of git                                                                                             |
| `MANIFEST.sha256`                                   | sha256 and relative path of every other file, generated last                                                                                                      |

## Checks you can run before drawing (offline)

From this folder, with `T=<your checkout>/docs/design/_tools/sheets/tools`:

```sh
sha256sum -c MANIFEST.sha256
for k in E47-D05 E47-D09 E47-D13 E47-D06 E47-D07 E47-D08; do
  for f in $k/[0-9][0-9]-*.json; do
    python3 -I -B $T/validate_sheet.py $f --components $T/components.offline.json > /dev/null || echo "FAIL $f"
    (cd $k && python3 -I -B $T/mkcall4.py v4/$(basename $f) count > /dev/null) || echo "STALE $f"
  done
done
```

No line should print. A sheet is never edited by hand: a problem found live is fixed on the board and reported as a
`SHEET-FIX` line, and the kit is regenerated on the sending side.
