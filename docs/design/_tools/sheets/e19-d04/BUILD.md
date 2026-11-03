# E19-D04 board kit: how the ten boards are built

The flow boards of E19-D04 (#439) are generated offline from the spec as cvsheet JSON sheets, then rendered on Penpot
with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in this folder runs from a
checkout of the repository with Python 3.12 and `git`; nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                                                                                         |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e19d04kit.py`           | The kit: §0's board table and not-drawn line, §8's state rows, §9's copy deck, §5's matrix and §6's keyboard table parsed from the spec (D03's, D02's, E14's and E17's words too); the seeded synthetic world; the node builders; sheet I/O. |
| `gen/panel.py`           | The E19-D03 kit's host pieces, cut down: the chart pane, the CMP-183 plot, the SCR-038 header and CMP-199 legend, the docked host.                                                                                                           |
| `gen/flows.py`           | The menus, dialogs, toast and chart marks, one builder per §0 frame, the gesture matrix.                                                                                                                                                     |
| `gen/registry.py`        | Frame id to builder; `build_board(nn)`.                                                                                                                                                                                                      |
| `gen/gen_NN.py`          | One generator per board; 01, 04 and 08 build their `-light` frame with the same builders.                                                                                                                                                    |
| `check_all.py`           | The scan over the ten sheets (validator, pack, mkcall4 count, shapes, icons, captions, cell padding, overflow and overlap estimates, md line 3, the `.md` beside the kit, backticks or local paths in drawn text, the spec md5 pin).         |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line and the notes.                                                                                 |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                                                                   |
| `local-icons.js`         | The local icon seed: `../run/local-icons.js` plus the five glyphs these sheets bind beyond it, each the `packages/ui` Lucide source.                                                                                                         |
| `build-notes.md`         | The authors' notes: sources, layout, the synthetic world, kit readings, the live-check fold, T2 and the stand-ins.                                                                                                                           |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                                                                        |

The spec `docs/design/E19/E19-D04.md` is read from this checkout by repo-relative path, md5-pinned (`DOCS` in the kit):
the kit refuses to run when it drifts, because every `L<n>` cite and every quoted string on the boards is looked up in
that text. After a spec edit, re-check the cites, re-pin and rebuild. E19-D03's spec is read at PR #5517's head and
E19-D02's at its merge commit, from the checkout when its bytes match the pin, else with `git show` at the pinned
commit; E14-D02, E14-D07, E17-D02 and the recorded instrument fixture (tick size and qty step only) the same way, at
the text PR's base. The validator, packer, `mkcall4.py`, components list and tokens are the shared copies in
`../tools/`. `CV_REPO` names another checkout root if the kit is run from outside this folder.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e19-d04
python3 -X utf8 -I -B e19d04kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                    # "OK: 0 findings"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (seed
439). To check the packed sheets against the raw ones:

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

Follow `../README.md` §2 to §4 with the raw sheets in `build/` as the set; run this folder's `local-icons.js` in place
of `../run/local-icons.js` (the seed plus `check`, `chevron-down`, `chevron-right`, `danger` and `warning`). The packed
sheets the drivers take must record the raw sheet's absolute path, so pack again into a folder outside the repository
(`../tools/compact.py build/NN-<slug>.json <outside>/NN-<slug>.json`) and never commit that copy; the committed `v4/`
keeps the bare name. File `E19-D04 boards`, page `E19-D04`; every board renders under the dark theme. Boards 01, 04 and
08 are exported under the dark set under §0's name and again under the light set as `…-light.png` (their `-light` frame
is token-bound; the kit's reading R-K1), then the dark set is restored.

## The ten boards

| Board                | Frames | Root w × h  | Theme            |
| -------------------- | ------ | ----------- | ---------------- |
| 01 preset-menu       | 4      | 3280 × 1878 | dark, light twin |
| 02 preset-save       | 4      | 3280 × 1878 | dark             |
| 03 preset-apply-undo | 2      | 3280 × 998  | dark             |
| 04 range-mode        | 3      | 3280 × 1878 | dark, light twin |
| 05 anchored          | 2      | 3280 × 998  | dark             |
| 06 drawing-attach    | 2      | 3280 × 998  | dark             |
| 07 drawing-events    | 5      | 3280 × 2758 | dark             |
| 08 gesture-matrix    | 2      | 3280 × 1398 | dark, light twin |
| 09 keyboard          | 2      | 3280 × 998  | dark             |
| 10 pan-stale-view-as | 3      | 3280 × 1878 | dark             |

Root heights are the live-measured ones (build-notes "Live-check fold"). Board ids, PNG paths and the theme-gate
results are in E19-D04 §0's Status cells and its As built record (§16).
