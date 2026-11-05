# E19-D05 board kit: how the ten boards are built

The motion boards of E19-D05 (#500) are generated offline from the spec as cvsheet JSON sheets, then rendered on
Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in this folder runs from
a checkout of the repository with Python 3.12 and `git`; nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                                                                                                                            |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e19d05kit.py`           | The kit: §0's board table and not-drawn line, §2's motion table, §3's matrix, §4.1 / §4.2's tables, §8.1's flash table and §8.3's copy deck parsed from the spec (D03's and D02's decks too); the motion maths from the PRIM easings; the seeded synthetic world; the builders. |
| `gen/frames.py`          | One builder per §0 frame: the docked CMP-183 crop at one key frame, the overlay crop, the strips, timelines and tables.                                                                                                                                                         |
| `gen/registry.py`        | Frame id to builder; `build_board(nn)`, which also adds the boards' declaration of D05 W-1 / W-1b's down forms as not drawn.                                                                                                                                                    |
| `gen/gen_NN.py`          | One generator per board; 02, 03 and 09 build their `-dark` and `-light` frames with the same builder.                                                                                                                                                                           |
| `check_all.py`           | The scan over the ten sheets (validator, pack, mkcall4 count, shapes, icons, captions, cell padding, overflow and overlap estimates, md line 3, the `.md` beside the kit, backticks in drawn text, the spec md5 pin).                                                           |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line and the notes.                                                                                                                    |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                                                                                                      |
| `build-notes.md`         | The authors' notes: sources, the synthetic world, kit readings and the live-check fold.                                                                                                                                                                                         |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                                                                                                           |

The spec `docs/design/E19/E19-D05.md` is read from this checkout by repo-relative path, md5-pinned (`DOCS` in the kit):
the kit refuses to run when it drifts, because every `L<n>` cite and every quoted string on the boards is looked up in
that text. After a spec edit, re-check the cites, re-pin and rebuild. E19-D03's spec is read at PR #5517's head and
E19-D02's at its merge commit, from the checkout when its bytes match the pin, else with `git show` at the pinned
commit; the motion primitives (`packages/ui/tokens/primitives.tokens.json`) and the recorded instrument fixture
(tick size and qty step only) the same way. The validator, packer, `mkcall4.py`, components list and tokens are the
shared copies in `../tools/`. `CV_REPO` names another checkout root if the kit is run from outside this folder.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e19-d05
python3 -X utf8 -I -B e19d05kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                    # "OK: 0 findings"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (seed
500). To check the packed sheets against the raw ones:

```sh
for f in v4/*.json; do
  python3 -X utf8 -I -c 'import hashlib, json, sys; p = json.load(open(sys.argv[1]))["compactOf"]
print(sys.argv[1], hashlib.sha256(open("build/" + p["file"], "rb").read()).hexdigest() == p["sha256"])' "$f"
done
```

The kit runs under `python3 -X utf8`, which makes it read and write UTF-8 on every platform, and it passes `-X utf8` to
every Python child it spawns (the validator, the packer and `mkcall4.py`): without it, Python on a cp1252 Windows host
decodes the sources with the locale code page and the generators fail.

## Render and export

Follow `../README.md` §2 to §4 with the raw sheets in `build/` as the set; the boards bind no local icon or token
beyond the shared seed. The packed sheets the drivers take must record the raw sheet's absolute path, so pack again
into a folder outside the repository (`../tools/compact.py build/NN-<slug>.json <outside>/NN-<slug>.json`) and never
commit that copy; the committed `v4/` keeps the bare name. File `E19-D05 boards`, page `E19-D05`; every board renders
under the dark theme. Boards 02, 03 and 09 are exported under the dark set as `…-dark.png` and again under the light
set under §0's name (each frame is token-bound; the kit's reading R-K2), then the dark set is restored.

## The ten boards

| Board                  | Frames | Root w × h  | Theme        |
| ---------------------- | ------ | ----------- | ------------ |
| 01 case-table          | 1      | 2768 × 934  | dark         |
| 02 poc-jump            | 2      | 3536 × 1958 | dark + light |
| 03 developing-final    | 2      | 3536 × 1502 | dark + light |
| 04 live-growth         | 2      | 3232 × 1534 | dark         |
| 05 developing-va       | 2      | 2848 × 1038 | dark         |
| 06 rebucket            | 3      | 2928 × 1886 | dark         |
| 07 visible-range       | 2      | 3232 × 1054 | dark         |
| 08 npoc-overlay-dock   | 3      | 2928 × 2998 | dark         |
| 09 suppression-matrix  | 2      | 2142 × 1302 | dark + light |
| 10 flash-announcements | 2      | 3280 × 918  | dark         |

Root heights are the live-measured ones (build-notes "Live-check fold"). Board ids, PNG paths and the theme-gate
results are in E19-D05 §0's Status cells and its As built record (§16).
