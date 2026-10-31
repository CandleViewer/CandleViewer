# E08-D09 board kit: how the ten boards are built

The SCR-147 boards of E08-D09 (#177, PR 3) are generated offline from the spec as cvsheet JSON sheets, then rendered
on Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in this folder runs
from a checkout of the repository with Python 3.12 and `git`; nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                       |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e08d09kit.py`           | The kit: §0's board table, §5.2's register, §15's copy deck, §17's SR and T2 rows and §21.2's G-rows parsed from the spec; the window, section, table and dialog builders. |
| `gen/gen_NN.py`          | One generator per board (08, 09 and 10, the twins, call 01's, 05's and 02's `build(theme)`); `gen/pairN_helpers.py` hold what a pair of boards shares.                     |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line and the sheet's notes.       |
| `v4/NN-<slug>.json`      | The packed sheets the boards were rendered from. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).   |
| `build-notes.md`         | The authors' notes: pipeline, file / page / frame naming, the window, the illustrative world, the rules, the kit's readings and the live-check fold.                       |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                      |

The spec is read from this checkout by repo-relative path: `docs/design/E08/E08-D09.md` and `E08-D09-handoff.md`. The
kit pins the md5 of each (`SPEC_MD5`) and refuses to run when one drifts, because every `L<n>` cite on the boards is
looked up in that text (`k.L`, `k.HL`): after a spec edit, re-check the cites, re-pin and rebuild. The validator,
packer, `mkcall4.py`, components list and tokens are the shared copies in `../tools/`.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e08-d09
python3 -I -B e08d09kit.py selftest                   # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -I -B gen/gen_$n.py; done
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`,
and `v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic
(one illustrative clock, no randomness), and the `.md` the kit writes is already Prettier-stable. To check the packed
sheets against the raw ones:

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
keeps the bare name. File `E08-D09 boards`, page `E08-D09 SCR-147 Connectivity`; every board renders under the dark
theme; boards 08 and 09 are exported under the light set and board 10 under the high-contrast set.

## The ten boards

| Board                    | Frames | Root w × h  | Theme | Sections (packed) |
| ------------------------ | ------ | ----------- | ----- | ----------------- |
| 01 healthy               | 9      | 4640 × 2758 | dark  | 137               |
| 02 approaching-throttled | 2      | 3280 × 1926 | dark  | 21                |
| 03 held-banned           | 2      | 3280 × 1455 | dark  | 26                |
| 04 ws-states             | 5      | 4640 × 2506 | dark  | 45                |
| 05 clock                 | 6      | 4640 × 2270 | dark  | 43                |
| 06 simulator-budget      | 5      | 4640 × 1878 | dark  | 64                |
| 07 inspector-history     | 7      | 4640 × 2758 | dark  | 93                |
| 08 healthy-light         | 9      | 4640 × 2758 | light | 137               |
| 09 clock-light           | 6      | 4640 × 2244 | light | 43                |
| 10 throttled-hc          | 2      | 3280 × 1957 | hc    | 21                |

Root heights are the live-measured annotation or footer end + 80 (`k.MEASURED_H`, build-notes "Live-check fold").
Board ids, PNG paths and the theme-gate results are in E08-D09 §0's as-built record.
