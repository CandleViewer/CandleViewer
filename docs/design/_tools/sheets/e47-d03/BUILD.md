# E47-D03 board kit: how the ten boards are built

The themes, CVD-safe palette and SCR-116 boards of E47-D03 (#1302) are generated offline from the spec as cvsheet JSON
sheets, then rendered on Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything
in this folder runs from a checkout of the repository with Python 3.12 and `git`; nothing here touches the network or
Penpot.

## What is here

| Path                     | What                                                                                                                                                         |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `e47d03kit.py`           | The kit: §0's board table, the hand-off's §G frame plan, §13's copy deck and the §3, §5, §7, §8 rows parsed from the spec; the seeded world; the builders.   |
| `gen/scr116.py`          | The SCR-116 frame and annotation builders shared by boards 01–05.                                                                                            |
| `gen/inkboards.py`       | The ink surfaces, §5 rows and §7.2 lines shared by boards 06–08.                                                                                             |
| `gen/gen_NN.py`          | One generator per board; 04 reuses 01's builders in light, 10 reuses 09's.                                                                                   |
| `check_all.py`           | The scan over the ten sheets (validator, mkcall4 count, node rules, captions, cell padding, the committed `.md`, md5 pin, `compactOf`).                      |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line and the notes. |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                   |
| `build-notes.md`         | The authors' notes: sources, the live-check fold, naming, the rules applied and the kit's choices and fallbacks.                                             |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                        |

The spec is read from this checkout by repo-relative path: `docs/design/E47/E47-D03.md` and `E47-D03-handoff.md`. The
kit pins the md5 of each (`SPEC_MD5`) and refuses to run when one drifts, because every `L<n>` cite on the boards is
looked up in that text (`k.L`, `k.HL`) and every figure is read from the spec's anchored tool values: after a spec
edit, re-check the cites, re-pin and rebuild. The validator, packer, `mkcall4.py`, components list and tokens are the
shared copies in `../tools/`.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e47-d03
python3 -I -B e47d03kit.py selftest                   # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -I -B gen/gen_$n.py; done
python3 -I -B check_all.py                            # "OK: 0 findings"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (seed
1302). To check the packed sheets against the raw ones:

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
keeps the bare name. File `E47-D03 boards`, page `E47-D03 themes and SCR-116`; every board renders under the dark
theme and is exported with its own set active: 02, 04 and 10 light; 03 high contrast, with the PROPOSED `hc+` binding
applied for the export only; 08 under each set, composited per frame; the grey and dichromacy frames of 06 and 07 are
projected after export (spec §0, As built).

## The ten boards

| Board                   | Frames | Root w × h  | Theme | Sections (packed) |
| ----------------------- | ------ | ----------- | ----- | ----------------- |
| 01 scr116-default       | 2      | 3280 × 1039 | dark  | 16                |
| 02 accent-warning       | 1      | 1920 × 1000 | light | 12                |
| 03 scr116-high-contrast | 1      | 1920 × 1000 | hc    | 11                |
| 04 scr116-light         | 1      | 1920 × 1000 | light | 11                |
| 05 text-150-zoom-200    | 2      | 3280 × 1000 | dark  | 26                |
| 06 encodings-greyscale  | 6      | 4640 × 1901 | dark  | 73                |
| 07 cvd-safe-simulated   | 3      | 4640 × 1448 | dark  | 106               |
| 08 env-badge-themes     | 4      | 3280 × 1880 | mixed | 19                |
| 09 data-ink-ramps       | 1      | 1920 × 1000 | dark  | 8                 |
| 10 data-ink-ramps-light | 1      | 1920 × 1000 | light | 8                 |

Root heights of 01, 06 and 07 are the live-measured annotation end + 80 (`k.MEASURED_H`, build-notes "Live-check fold").
Board ids, PNG paths and the theme-gate results are in E47-D03 §0's as-built record.
