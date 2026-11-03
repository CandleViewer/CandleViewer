# E19-D02 board kit: how the ten boards are built

The ten greyscale wireframe boards of E19-D02 (#416), SCR-038 (the profile panel) and SCR-039 (its settings dialog),
are generated offline from the spec as cvsheet JSON sheets, then rendered on Penpot with the shared drivers in
`docs/design/_tools/sheets/` (`README.md` there). Everything in this folder runs from a checkout of the repository
with Python 3.12 and `git`; nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                                         |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e19d02kit.py`           | The kit: spec §0's board table and not-drawn line, §12's copy deck and the window size parsed from the spec; the seeded world (seed 416); wire tokens, node builders, writer, md and packer. |
| `gen/frames.py`          | The frame builders: chart, docked and overlay hosts, the plot, the states, edge cases, the table, SCR-039, menus and flows.                                                                  |
| `gen/registry.py`        | Frame id to builder; `build_board(nn)`.                                                                                                                                                      |
| `gen/gen_NN.py`          | One generator per board.                                                                                                                                                                     |
| `check_all.py`           | Scans the ten (validator, mkcall4 count, packed sha256, node rules, wire tokens only, icons, captions, cell padding, overflow, the drawn and not-drawn W-strings, md5 pins).                 |
| `local-icons.js`         | The local icon seed for the per-set file: `../run/local-icons.js` plus the seven glyphs these sheets need, each named by its `packages/ui` Lucide SVG.                                       |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: file, page, export, sheet and theme), its frames, the validator line and the notes.                           |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                   |
| `build-notes.md`         | The authors' notes: sources, the world, the readings taken and the live-check fold.                                                                                                          |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                        |

The spec (`docs/design/E19/E19-D02.md`) and the recorded instrument fixture
(`packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`, the BTCUSDT tick and qty step) are read from this
checkout by repo-relative path. The kit pins the md5 of each (`DOCS`) and refuses to run when one drifts, because
every `L<n>` cite on the boards is looked up in that text: after a spec edit, re-check the cites, re-pin and rebuild.
The validator, packer, `mkcall4.py`, components list and tokens are the shared copies in `../tools/`. `CV_REPO` names
another checkout root if the kit is run from outside this folder.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e19-d02
python3 -X utf8 -I -B e19d02kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                    # "OK: 0 findings"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`,
and `v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic
(seed 416). To check the packed sheets against the raw ones:

```sh
for f in v4/*.json; do
  python3 -X utf8 -I -c 'import hashlib, json, sys; p = json.load(open(sys.argv[1]))["compactOf"]
print(sys.argv[1], hashlib.sha256(open("build/" + p["file"], "rb").read()).hexdigest() == p["sha256"])' "$f"
done
```

`-X utf8` makes the kit read and write UTF-8 on every platform: without it, Python on Windows decodes the sources with
the locale code page and the generators fail.

## Render and export

Follow `../README.md` §2 to §4 with the raw sheets in `build/` as the set, and run `local-icons.js` (this folder) in
place of `../run/local-icons.js` at §2 step 3: the sheets bind `check`, `chevron-down`, `info`, `more-horizontal`,
`warning`, `danger` and `pending`, which the shared seed does not create. The packed sheets the drivers take must
record the raw sheet's absolute path, so pack again into a folder outside the repository
(`../tools/compact.py build/NN-<slug>.json <outside>/NN-<slug>.json`) and never commit that copy; the committed `v4/`
keeps the bare name. File `E19-D02 boards`, page `E19-D02`; every board renders and exports under the dark theme
only, greyscale (spec §0, BQ-15: 0 light twins). Frame names carry U+2215 for `/`.

## The ten boards

| Board                   | Frames | Root w × h  | Theme | Sections (packed) |
| ----------------------- | ------ | ----------- | ----- | ----------------- |
| 01 docked-anatomy       | 4      | 3280 × 1878 | dark  | 29                |
| 02 overlay-anatomy      | 3      | 3280 × 1878 | dark  | 22                |
| 03 axis-alignment       | 4      | 3280 × 1878 | dark  | 49                |
| 04 data-states          | 5      | 3280 × 2758 | dark  | 49                |
| 05 no-history           | 3      | 3280 × 1878 | dark  | 18                |
| 06 edge-density         | 4      | 3280 × 1878 | dark  | 40                |
| 07 table-and-focus      | 1      | 1920 × 1011 | dark  | 26                |
| 08 settings-compact     | 4      | 3280 × 1878 | dark  | 72                |
| 09 presets-clamp-viewas | 4      | 3280 × 1878 | dark  | 56                |
| 10 period-flow          | 3      | 3280 × 1878 | dark  | 26                |

Root heights are the live check's read-back (`LIVE_ROOT_H`, build-notes "Live-check fold"). The PNG paths and the
board ids are in the spec's §0 rows; the live check and the drawn deviations in its As built record (§18).
