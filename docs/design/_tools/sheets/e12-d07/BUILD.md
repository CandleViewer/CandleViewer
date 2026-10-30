# E12-D07 board kit: how the ten boards are built

The SCR-045 data-table boards of E12-D07 (#242, PR 2) are generated offline from the spec as cvsheet JSON sheets,
then rendered on Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in
this folder runs from a checkout of the repository with Python 3.12 and `git`; nothing here touches the network or
Penpot.

## What is here

| Path                     | What                                                                                                                                                                           |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `e12d07kit.py`           | The kit: §0 / §H parsed from the spec, the seeded data (seed 242), the table, row, caption and annotation builders, `write_sheet`, `write_md`, `pack_sheet` and the self-test. |
| `gen/gen_NN.py`          | One generator per board (09 and 10, the light twins, reuse 04's and 05's builders); `gen/pairN_helpers.py` hold what a pair of boards shares.                                  |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page and theme), its frames, the validator line and the sheet's notes.                          |
| `v4/NN-<slug>.json`      | The packed sheets the boards were rendered from. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).       |
| `build-notes.md`         | The authors' notes: pipeline, file / page / frame naming, layout, data, the rules, the live-check fold.                                                                        |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                          |

The spec is read with `git show c3119e61e:<path>` (the kit's `PIN`, origin/main when the kit was cut):
`docs/design/E12/E12-D07.md`, `E12-D07-handoff.md`, `E12-D06.md` and `docs/design/E11/E11-D04.md`. The self-test
checks the md5 pins of the first two and E11-D04. The validator, packer, components list and tokens are the shared
copies in `../tools/`.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e12-d07
python3 -I e12d07kit.py selftest                      # 19 PASS, "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -I -B gen/gen_$n.py; done
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`,
and `v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic
(seeded data, no clock), and the `.md` the kit writes is already Prettier-stable. To check the packed sheets against
the raw ones:

```sh
for f in v4/*.json; do
  python3 -I -c 'import hashlib, json, sys; p = json.load(open(sys.argv[1]))["compactOf"]
print(sys.argv[1], hashlib.sha256(open("build/" + p["file"], "rb").read()).hexdigest() == p["sha256"])' "$f"
done
```

## Render and export

Follow `../README.md` §2 to §4 with the raw sheets in `build/` as the set. The packed sheets the drivers take must
record the raw sheet's absolute path, so pack again into a folder outside the repository
(`../tools/compact.py build/NN-<slug>.json <outside>/NN-<slug>.json`) and never commit that copy; the committed
`v4/` keeps the bare name. File `E12-D07 boards`, page `E12-D07 SCR-045 data table`; every board renders under the
dark theme, boards 09 and 10 are exported under the light set. Board 08 (`reflow-200`) draws the 1280 × 800 window
at 640 × 400 CSS px and is exported at 2× (2560 × 2506 px; ruling P-4).

## The ten boards

| Board                   | Frames | Root w × h  | Theme | Sections (packed) |
| ----------------------- | ------ | ----------- | ----- | ----------------- |
| 01 time-bars            | 3      | 4640 × 2574 | dark  | 64                |
| 02 tick-volume-delta    | 4      | 3280 × 2644 | dark  | 94                |
| 03 range-renko          | 3      | 4640 × 2587 | dark  | 70                |
| 04 row-states           | 2      | 3280 × 2414 | dark  | 43                |
| 05 separator-rows       | 3      | 4640 × 2676 | dark  | 47                |
| 06 chart-type-cells     | 3      | 4640 × 2520 | dark  | 69                |
| 07 sync-and-edge        | 2      | 3280 × 2148 | dark  | 46                |
| 08 reflow-200           | 1      | 1280 × 1253 | dark  | 5                 |
| 09 row-states-light     | 1      | 1920 × 1609 | light | 21                |
| 10 separator-rows-light | 2      | 3280 × 1981 | light | 35                |

Root heights are the live-measured annotation end + 80 (`k.MEASURED_H`, build-notes "Live-check fold"). Board ids,
PNG paths and the theme-gate results are in E12-D07 §0's as-built record.
