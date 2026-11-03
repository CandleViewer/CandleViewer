# E21-D03 board kit: how the ten boards are built

The hi-fi boards of E21-D03 (#503), the SCR-051 Heatmap & ladder settings dialog and the SCR-153 depth-shed row, are
generated offline from the spec as cvsheet JSON sheets, then rendered on Penpot with the shared drivers in
`docs/design/_tools/sheets/` (`README.md` there). Everything in this folder runs from a checkout of the repository with
Python 3.12 (stdlib only); nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                                                                                                                       |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e21d03kit.py`           | The kit: §0's board table, §10's states, §15's copy deck and the other sections the boards draw, parsed from the spec; the seeded synthetic book (seed 503); tokens; the node primitives, the text estimates, the board, write, pack and self-test.                        |
| `gen/ui.py`              | The widgets and frames: the CMP-043 dialog and its five tabpanels, the controls and their T2 rendering, the CMP-228 tile, SCR-050 behind the dialog, the SCR-153 window and its shed row, and the board markers.                                                           |
| `gen/gen_NN.py`          | One generator per board.                                                                                                                                                                                                                                                   |
| `check_all.py`           | The scan over the ten sheets (every generator twice and byte-identical; validator, pack, `mkcall4.py` count, frame plan and captions, md line 3, banned strings, backticks in drawn text, tokens, icons, cell padding, the §10 states on their boards, T2, DEMO and LIVE). |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line, the live checks and the notes.                                                                                              |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                                                                                                 |
| `build-notes.md`         | The authors' notes: sources and pins, the seeded world, the readings taken, and the live-check fold.                                                                                                                                                                       |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                                                                                                      |

The spec is read from this checkout by repo-relative path: `docs/design/E21/E21-D03.md` (there is no hand-off file)
and the recorded instrument fixture `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json` (the BTCUSDT
tick and qty step only). The kit pins the md5 of each source in `DOCS` and refuses to run when one drifts, because every
string on the boards is looked up in that text: after an edit, re-check the strings, re-pin and rebuild. The validator,
packer, `mkcall4.py`, components list and tokens are the shared copies in `../tools/`. `CV_CHECKOUT` names another
checkout root if the kit is run from outside this folder.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e21-d03
python3 -X utf8 -I -B e21d03kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                    # "rebuild byte-identical (40 files ...)", then "OK: 0 failures"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (the
seeded world, seed 503). To check the packed sheets against the raw ones:

```sh
for f in v4/*.json; do
  python3 -X utf8 -I -c 'import hashlib, json, sys; p = json.load(open(sys.argv[1]))["compactOf"]
print(sys.argv[1], hashlib.sha256(open("build/" + p["file"], "rb").read()).hexdigest() == p["sha256"])' "$f"
done
```

The kit runs under `python3 -X utf8`, which makes it read and write UTF-8 on every platform, and it passes `-X utf8` to
every Python child it spawns (the validator, the packer, `mkcall4.py` and, under `check_all.py`, the generators and the
self-test): without it, Python on a cp1252 Windows host decodes the sources with the locale code page and the
generators fail.

## Render and export

Follow `../README.md` §2 to §4 with the raw sheets in `build/` as the set. The packed sheets the drivers take must
record the raw sheet's absolute path, so pack again into a folder outside the repository
(`../tools/compact.py build/NN-<slug>.json <outside>/NN-<slug>.json`) and never commit that copy; the committed `v4/`
keeps the bare name. File `E21-D03 boards`, page `E21-D03`. Every board renders and is exported under the dark theme;
boards 01, 05 and 09 are exported again under the light set (`-light.png`; each twin is token-bound), then the dark
set is restored. The dark exports of boards 03 and 09 are run through `docs/design/_tools/cvd_sim.py` for the greyscale
exports §0 names (`-greyscale.png`); board 03 also keeps the deuteranopia and protanopia renders its annotation names.
Seeding the token sets, Penpot refuses the four `motion.duration.*` primitives; no sheet binds a motion token.

## The ten boards

| Board                   | Frames | Root w × h  | Theme                           |
| ----------------------- | ------ | ----------- | ------------------------------- |
| 01 anatomy-redlines     | 2      | 3280 × 1026 | dark + light                    |
| 02 tier-rebuild-500     | 5      | 3280 × 2322 | dark                            |
| 03 colour-cvd-greyscale | 3      | 3280 × 1934 | dark; greyscale and CVD renders |
| 04 ladder-centring      | 1      | 1920 × 1039 | dark                            |
| 05 trading-demo-live    | 3      | 3280 × 1947 | dark + light                    |
| 06 detectors            | 1      | 1920 × 1039 | dark                            |
| 07 validation-clamp     | 3      | 3280 × 1422 | dark                            |
| 08 cost-save-t2         | 3      | 3280 × 1334 | dark                            |
| 09 shed-row-restore     | 3      | 3280 × 1934 | dark + light; greyscale         |
| 10 keyboard-reflow      | 2      | 2640 × 1166 | dark                            |

Root heights are the live-checked ones (build-notes "Live-check fold"). Board ids, PNG paths and the theme-gate
results are in E21-D03 §0's Status cells and its as-built record (§20).
