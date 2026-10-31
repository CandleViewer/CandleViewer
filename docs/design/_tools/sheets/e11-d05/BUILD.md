# E11-D05 ref-frame kit: how boards 09 / 10 are built

The 55 per-state ref frames of E11-D05 (#310; handoff Table 1) are generated offline as cvsheet JSON sheets, then
rendered on Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in this folder
runs from a full checkout of the repository with Python 3.12 and `git`; nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                                             |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `e11d05kit.py`           | The kit: Table 1 parsed from the hand-off, the seeded bars (seed 310), the chart crop, the pills, the groups, the annotation column, `write_sheet`, `write_md`, `pack_sheet`, `write_post_live`. |
| `gen/gen_09.py`          | Board 09 `ref-frames-a`: CMP-180 / 188 / 189 / 190, 33 frames.                                                                                                                                   |
| `gen/gen_10.py`          | Board 10 `ref-frames-b`: CMP-197 / 198 / 199 / 226, 22 frames.                                                                                                                                   |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page and theme), its frames, the validator line and the sheet's notes.                                            |
| `v4/NN-<slug>.json`      | The packed sheets that reproduce the drawn boards. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself.                               |
| `build-notes.md`         | The authors' notes: layout, tokens, rules, the critic fold, the live-check fold r2 and its round 2, the review folds r2, r3, r3b and r3c.                                                        |
| `build/` (not committed) | The raw sheets `NN-<slug>.json`, a copy of each `.md` (the set the render drivers read) and `NN-<slug>.post-live.js`. Listed in `.gitignore`.                                                    |

The kit reads `docs/design/E11/E11-D05.md`, `E11-D05-handoff.md`, `E11-D02.md`, `E11-D04.md` and
`docs/plan/15-component-catalogue.md` **as at e87194bb0** (`git show e87194bb0:<path>` in this checkout), the text every
`L<n>` cite on the boards was read in, and pins the md5 of each (`SPEC_MD5`): it refuses to run on drifted bytes. The
validator, packer and components list are the shared copies in `../tools/`.

## Rebuild the two sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e11-d05
python3 -I -B gen/gen_09.py
python3 -I -B gen/gen_10.py
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`,
`build/NN-<slug>.post-live.js` and `v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean (seeded
data, no clock; the `.md` is Prettier-stable). To check the packed sheets against the raw ones:

```sh
for f in v4/*.json; do
  python3 -I -c 'import hashlib, json, sys; p = json.load(open(sys.argv[1]))["compactOf"]
print(sys.argv[1], hashlib.sha256(open("build/" + p["file"], "rb").read()).hexdigest() == p["sha256"])' "$f"
done
```

## Render, post-render step and export

1. Follow `../README.md` §2 to §4 with `build/` as the set. The drivers take packed sheets that record the raw sheet's
   absolute path, so pack again into a folder outside the repository
   (`../tools/compact.py build/NN-<slug>.json <outside>/NN-<slug>.json`) and never commit that copy; the committed `v4/`
   keeps the bare name. File `E11-D05 ref frames`, page `E11-D05 ref frames`; both boards render and export under the
   dark theme.
2. After each board renders, run `build/NN-<slug>.post-live.js` twice with `../run/run_js.py` (the second run re-centres
   the watermarks on their settled heights). It writes what a sheet cannot carry: the frames' notes as shared plugin data
   `cvd02/note`, the watermarks at 48 / 40 px weight 600, the stale frame's x0.85 ink fills, the mark pill's 3 px
   padding (`build-notes.md`, "Live-check fold r2") and the maintenance band's `hatch line · NN` rects rotated 45°
   ("Review fold r3b"; the post-export step's hatch rotation does the same and both skip a rotated line).
3. Then the post-export step and the PNG export (`../README.md` §4), and `docs/design/_tools/cvd_sim.py` on each export.

## The two boards

| Board           | Frames | Root w × h  | At        | Theme | Board id (page `E11-D05 ref frames`)   |
| --------------- | ------ | ----------- | --------- | ----- | -------------------------------------- |
| 09 ref-frames-a | 33     | 3200 × 2913 | (0, 0)    | dark  | `0c4baecb-5183-80d0-8008-df897051bf16` |
| 10 ref-frames-b | 22     | 3000 × 2566 | (4000, 0) | dark  | `c3fc69a9-a43c-8099-8008-df8e5122b161` |

Root heights are the live-measured annotation end + 80 (`MEASURED_H`). The PNG paths, the theme gate, the live check and
the deviations are in E11-D05 §18.
