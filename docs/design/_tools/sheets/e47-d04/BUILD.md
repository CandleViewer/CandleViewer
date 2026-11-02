# E47-D04 board kit: how the ten boards are built

The focus-model boards of E47-D04 (#1303) are generated offline from the spec as cvsheet JSON sheets, then rendered on
Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in this folder runs from
a checkout of the repository with Python 3.12 and `git`; nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                            |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e47d04kit.py`           | The kit: §0's board table, the hand-off's §H frame lists, §4's archetypes, §7.1's geometry, §7.6's ratios, §15's copy deck and §18.2's G-rows parsed; builders. |
| `gen/common.py`          | The panel bodies of the four-panel workspace and the marker spots per region.                                                                                   |
| `gen/gen_NN.py`          | One generator per board; boards 09 and 10 call board 08's `build(theme)`, and 10's first frame is its own.                                                      |
| `scan.py`                | The scan over the ten sheets (frames and captions, the annotation column, node rules, cell padding, banned strings, `compactOf`, the md5 pin).                  |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line and the notes.    |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                      |
| `build-notes.md`         | The authors' notes: pipeline, the live-check fold, file / page / frame naming, the window, the seeded world, the annotation column and the kit's readings.      |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                           |

The spec is read from this checkout by repo-relative path: `docs/design/E47/E47-D04.md` and `E47-D04-handoff.md`, with
the recorded instrument fixture (`packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`, tick sizes only).
The kit pins the md5 of each (`SPEC_MD5`) and refuses to run when one drifts, because every `L<n>` cite on the boards
is looked up in that text (`k.L`, `k.HL`): after a spec edit, re-check the cites, re-pin and rebuild. The validator,
packer, `mkcall4.py`, components list and tokens are the shared copies in `../tools/`.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e47-d04
python3 -I -B e47d04kit.py selftest                   # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -I -B gen/gen_$n.py; done
python3 -I -B scan.py                                 # "OK"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`,
and `v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic
(seed 1303, no clock), and the `.md` the kit writes is already Prettier-stable. To check the packed sheets against the
raw ones:

```sh
for f in v4/*.json; do
  python3 -I -c 'import hashlib, json, sys; p = json.load(open(sys.argv[1]))["compactOf"]
print(sys.argv[1], hashlib.sha256(open("build/" + p["file"], "rb").read()).hexdigest() == p["sha256"])' "$f"
done
```

## Render and export

Follow `../README.md` §2 to §4 with the raw sheets in `build/` as the set. The packed sheets the drivers take must
record the raw sheet's absolute path, so pack again into a folder outside the repository
(`../tools/compact.py build/NN-<slug>.json <outside>/NN-<slug>.json`) and never commit that copy; the committed `v4/`
keeps the bare name. File `E47-D04 boards`, page `E47-D04 — Focus model`; every board renders under the dark theme;
board 09 is exported under the light set and board 10 under the high-contrast set (the twins are token-bound).

## The ten boards

| Board              | Frames | Root w × h  | Theme | Sections (packed) |
| ------------------ | ------ | ----------- | ----- | ----------------- |
| 01 landmarks-ring  | 2      | 3280 × 998  | dark  | 61                |
| 02 workspace-order | 2      | 3280 × 998  | dark  | 63                |
| 03 grid-escape     | 3      | 4640 × 1036 | dark  | 58                |
| 04 retention       | 4      | 3280 × 1878 | dark  | 76                |
| 05 dialog-flatten  | 2      | 3280 × 998  | dark  | 35                |
| 06 overlay-palette | 3      | 4640 × 1101 | dark  | 55                |
| 07 full-page-form  | 2      | 3280 × 1042 | dark  | 32                |
| 08 ring-spec       | 2      | 3280 × 998  | dark  | 15                |
| 09 ring-spec-light | 2      | 3280 × 998  | light | 15                |
| 10 ring-hc-thick   | 2      | 3280 × 998  | hc    | 14                |

Root heights are the live-measured annotation or footer end + 80 (`k.MEASURED_H`, build-notes "Live-check fold").
Board ids, PNG paths and the theme-gate results are in E47-D04 §0's as-built record.
