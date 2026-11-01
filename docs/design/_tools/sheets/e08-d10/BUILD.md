# E08-D10 board kit: how the nine boards are built

The SCR-151 boards of E08-D10 (#178) are generated offline from the spec as cvsheet JSON sheets, then rendered on
Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in this folder runs from
a checkout of the repository with Python 3.12 and `git`; nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                              |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e08d10kit.py`           | The kit: §0's board table, the hand-off's §H frame lists, §13's copy deck and §7, §10.2, §11 and §12's rows parsed from the spec; the seeded world; the builders. |
| `gen/frames.py`          | The frame builders, keyed by the §H frame id without its theme; a twin board calls its base frames' builders with its own id.                                     |
| `gen/gen_NN.py`          | One generator per board: `frames.build_board(NN)`.                                                                                                                |
| `check_all.py`           | The scan over the nine sheets (validator, mkcall4 count, node rules, captions, cell padding, overflow by estimate, md5 pin, `compactOf`).                         |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line and the notes.      |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                        |
| `build-notes.md`         | The authors' notes: pipeline, the live-check fold, file / page / frame naming, the window, the seeded world, the boards and the kit's readings.                   |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                             |

The spec is read from this checkout by repo-relative path: `docs/design/E08/E08-D10.md` and `E08-D10-handoff.md`,
with the cited siblings (E11-D04, E22-D02, E22-D03, E08-D02, E08-D04) and the recorded instrument fixture. The kit pins
the md5 of each (`DOCS`) and refuses to run when one drifts, because every `L<n>` cite on the boards is looked up in
that text (`k.L`, `k.HL`): after a spec edit, re-check the cites, re-pin and rebuild. The validator, packer,
`mkcall4.py`, components list and tokens are the shared copies in `../tools/`.

## Rebuild the nine sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e08-d10
python3 -I -B e08d10kit.py selftest                   # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09; do python3 -I -B gen/gen_$n.py; done
python3 -I -B check_all.py                            # "OK: 0 findings"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`,
and `v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic
(seed 178, one illustrative clock), and the `.md` the kit writes is already Prettier-stable. To check the packed
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
keeps the bare name. File `E08-D10 boards`, page `E08-D10 SCR-151 empty and backfill states`; every board renders
under the dark theme; board 08 is exported under the light set and board 09 under the high-contrast set.

## The nine boards

| Board                   | Frames | Root w × h  | Theme | Sections (packed) |
| ----------------------- | ------ | ----------- | ----- | ----------------- |
| 01 backfill-in-progress | 4      | 3280 × 1878 | dark  | 60                |
| 02 backfill-throttled   | 4      | 3280 × 1878 | dark  | 92                |
| 03 coverage-gap         | 4      | 3280 × 1878 | dark  | 103               |
| 04 classes-e08-delta    | 2      | 3280 × 998  | dark  | 10                |
| 05 timing               | 3      | 4640 × 998  | dark  | 42                |
| 06 keyboard-a11y        | 3      | 4640 × 998  | dark  | 56                |
| 07 redlines             | 1      | 1920 × 998  | dark  | 9                 |
| 08 light-twin           | 3      | 4640 × 1129 | light | 56                |
| 09 hc-twin              | 2      | 3280 × 998  | hc    | 32                |

Root heights are the live-measured annotation or footer end + 80 (`k.MEASURED_H`, build-notes "Live-check fold").
Board ids, PNG paths and the theme-gate results are in E08-D10 §0's as-built record.
