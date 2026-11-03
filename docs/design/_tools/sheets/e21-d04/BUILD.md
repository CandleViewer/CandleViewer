# E21-D04 board kit: how the ten boards are built

The specimen boards of E21-D04 (#504), the design-system pack for SCR-050's seven components, are generated offline
from the pack and its hand-off as cvsheet JSON sheets, then rendered on Penpot with the shared drivers in
`docs/design/_tools/sheets/` (`README.md` there). Everything in this folder runs from a checkout of the repository with
Python 3.12 (stdlib only); nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                                                                                                                                       |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `e21d04kit.py`           | The kit: §0's board table, §1.3's R-3, §4.1's template and tokens, §4.8's copy, §5's sets and tables parsed from the pack, the hand-off's Table 1 variants; the seeded synthetic book (seed 504); tokens with per-theme values; the node primitives, the board, write, pack and self-test. |
| `gen/frames.py`          | The frames: ladder rows and windows, the heatmap pane, the CMP-024 sparkline, the CMP-111 reveal, the CMP-113 legend, the CMP-228 tile, the notice, and one builder per board.                                                                                                             |
| `gen/gen_NN.py`          | One generator per board.                                                                                                                                                                                                                                                                   |
| `check_all.py`           | The scan over the ten sheets (with `--rebuild`, every generator twice and byte-identical; validator, pack, `mkcall4.py` count, frame plan and captions, md line 3, banned strings, backticks in drawn text, tokens, icons, row and column fits, cell padding, overlaps).                   |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line, the live checks and the notes.                                                                                                              |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                                                                                                                 |
| `build-notes.md`         | The authors' notes: sources and pins, the seeded world, the readings taken, and the live-check fold.                                                                                                                                                                                       |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                                                                                                                      |

The pack is read from this checkout by repo-relative path: `docs/design/E21/E21-D04.md`, its hand-off
`docs/design/E21/E21-D04-handoff.md` and the recorded instrument fixture
`packages/fixtures/bybit/2026-10-05/rest/instruments_before.json` (the BTCUSDT tick and qty step only). The kit pins
the md5 of each source in `DOCS` and refuses to run when one drifts, because every `L<n>` cite on the boards is looked
up in that text: after an edit, re-check the cites, re-pin and rebuild. The validator, packer, `mkcall4.py`,
components list and tokens are the shared copies in `../tools/`. `CV_CHECKOUT` names another checkout root if the kit
is run from outside this folder.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e21-d04
python3 -X utf8 -I -B e21d04kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py --rebuild          # "rebuild: 30 files, byte-identical", then "OK: 0 findings"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (the
seeded world, seed 504). To check the packed sheets against the raw ones:

```sh
for f in v4/*.json; do
  python3 -X utf8 -I -c 'import hashlib, json, sys; p = json.load(open(sys.argv[1]))["compactOf"]
print(sys.argv[1], hashlib.sha256(open("build/" + p["file"], "rb").read()).hexdigest() == p["sha256"])' "$f"
done
```

The kit runs under `python3 -X utf8`, which makes it read and write UTF-8 on every platform, and it passes `-X utf8` to
every Python child it spawns (the validator, the packer, `mkcall4.py` and, under `check_all.py`, the generators):
without it, Python on a cp1252 Windows host decodes the sources with the locale code page and the generators fail.

## Render and export

Follow `../README.md` §2 to §4 with the raw sheets in `build/` as the set. The packed sheets the drivers take must
record the raw sheet's absolute path, so pack again into a folder outside the repository
(`../tools/compact.py build/NN-<slug>.json <outside>/NN-<slug>.json`) and never commit that copy; the committed `v4/`
keeps the bare name. File `E21-D04 boards`, page `E21-D04`. Every board renders under the dark theme and is exported
under it, except board 09, which is exported under the high-contrast set only (its rows are only true there); boards
01, 04 and 06 are exported again under the light set (`-light.png`; each twin is token-bound), then the dark set is
restored. Board 04's dark export is run through `docs/design/_tools/cvd_sim.py` for the three colour-vision exports
board 05 names (`-greyscale.png`, `-deuteranopia.png`, `-protanopia.png`). Board 03 has about 1,300 shapes: draw it one
section per call, reload the tab before it, and watch the file's save state, since an unsaved draw cannot be exported.

## The ten boards

| Board                    | Frames | Root w × h  | Theme                         |
| ------------------------ | ------ | ----------- | ----------------------------- |
| 01 cmp-108-variants      | 9      | 3416 × 1512 | dark + light                  |
| 02 cmp-108-density-focus | 4      | 3424 × 999  | dark                          |
| 03 cmp-111-reveal        | 4      | 4040 × 1670 | dark                          |
| 04 cmp-113-sets-scale    | 8      | 3872 × 1400 | dark + light; CVD exports     |
| 05 ramps-cvd             | 2      | 2304 × 958  | dark                          |
| 06 cmp-230-states        | 8      | 3424 × 1195 | dark + light                  |
| 07 cmp-227-cmp-229-usage | 3      | 2956 × 789  | dark                          |
| 08 cmp-228-heatmap-kind  | 5      | 2920 × 1030 | dark                          |
| 09 high-contrast-forced  | 6      | 3584 × 1033 | high contrast (exported only) |
| 10 token-map-redlines    | 2      | 2480 × 597  | dark                          |

Root heights are the live-checked ones (build-notes "Live-check fold"). Board ids, PNG paths and the theme-gate
results are in E21-D04 §0's Status cells and its as-built record (§14).
