# E20-D02 board kit: how the ten boards are built

The greyscale wireframe boards of E20-D02 (#574), SCR-033's Deep Stats rows and the CMP-225 strip under SCR-030, are
generated offline from the spec as cvsheet JSON sheets, then rendered on Penpot with the shared drivers in
`docs/design/_tools/sheets/` (`README.md` there). Everything in this folder runs from a checkout of the repository with
Python 3.12; nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                                                                   |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e20d02kit.py`           | The kit: §0's board table, §2's register, §3's row tables, §6.1's catalogue, §9's sources and §12's copy deck parsed from the spec; the seeded synthetic world (seed 574); the board, section, pack and lint builders. |
| `gen/ui.py`              | The SCR-030 window and the strip, the readout, crosshair and markers; SCR-033's dialog, rows, row menu and threshold entry; the SCR-045 table and export bar; the board markers.                                       |
| `gen/gen_NN.py`          | One generator per board.                                                                                                                                                                                               |
| `check_all.py`           | The scan over the ten sheets (two builds byte-identical, validator, pack, mkcall4 count, packed sections expanded and compared, banned strings, greyscale, T2, AC 3, the live-check fold).                             |
| `local-icons.js`         | The local icon seed for the per-set file: `../run/local-icons.js` plus the glyphs these boards bind beyond it, each named to its `packages/ui` Lucide SVG.                                                             |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line, the live checks and the notes.                                          |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                                             |
| `build-notes.md`         | The authors' notes: sources and pins, the seeded world, readings and the live-check fold.                                                                                                                              |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                                                  |

The spec is read from this checkout by repo-relative path: `docs/design/E20/E20-D02.md` (there is no hand-off file),
`docs/design/E18/E18-D02.md` (line 124's `delta` width floor) and the recorded instrument fixture
`packages/fixtures/bybit/2026-10-05/rest/instruments_before.json` (tick and qty step only). The kit pins the md5 of each
source in `DOCS` and refuses to run when one drifts, because every `L<n>` cite on the boards is looked up in that text:
after a spec edit, re-check the cites, re-pin and rebuild. The validator, packer, `mkcall4.py`, components list and
tokens are the shared copies in `../tools/`. `CV_CHECKOUT` names another checkout root if the kit is run from outside
this folder.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e20-d02
python3 -X utf8 -I -B e20d02kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                    # "OK: 0 failures"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (the
seeded world, seeds 574 and 575). To check the packed sheets against the raw ones:

```sh
for f in v4/*.json; do
  python3 -X utf8 -I -c 'import hashlib, json, sys; p = json.load(open(sys.argv[1]))["compactOf"]
print(sys.argv[1], hashlib.sha256(open("build/" + p["file"], "rb").read()).hexdigest() == p["sha256"])' "$f"
done
```

The kit runs under `python3 -X utf8`, which makes it read and write UTF-8 on every platform, and it passes `-X utf8` to
every Python child it spawns (the validator, the packer, `mkcall4.py` and the generators): without it, Python on a
cp1252 Windows host decodes the sources with the locale code page and the generators fail.

## Render and export

Follow `../README.md` §2 to §4 with the raw sheets in `build/` as the set, running `local-icons.js` (here) in place of
`../run/local-icons.js`. `mkcall4.py` resolves a packed sheet's bare `compactOf.file` from its working directory, so run
it from `build/`. File `E20-D02 boards`, page `E20-D02`; every board renders and is exported under the dark theme (0
light twins, no colour-vision export). Board 10 has over 3,000 shapes: draw it one section per call and lay out each
section as it lands. Watch the file's save state, since an unsaved draw cannot be exported.

## The ten boards

| Board                                   | Frames | Root w × h  | Theme |
| --------------------------------------- | ------ | ----------- | ----- |
| 01 strip-default-allrows                | 4      | 3280 × 1934 | dark  |
| 02 compact-and-collapse                 | 2      | 3280 × 1026 | dark  |
| 03 narrow-bar-readout                   | 2      | 3280 × 1026 | dark  |
| 04 thresholds-breached-greyscale        | 3      | 3280 × 1947 | dark  |
| 05 forming-partial-empty                | 3      | 3280 × 1934 | dark  |
| 06 strip-hidden-restore                 | 2      | 3280 × 1026 | dark  |
| 07 scr033-catalogue-reorder             | 4      | 3280 × 1934 | dark  |
| 08 scr033-validation-source-unavailable | 4      | 3280 × 1934 | dark  |
| 09 scr045-delta-export                  | 3      | 3280 × 1934 | dark  |
| 10 alignment-3-zooms                    | 3      | 3280 × 1934 | dark  |

Root heights are the live-measured ones (build-notes "Live-check fold"). Board ids, PNG paths and the theme-gate
results are in E20-D02 §0's Status cells and its As built record (§19).
