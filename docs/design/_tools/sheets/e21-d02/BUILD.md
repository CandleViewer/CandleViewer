# E21-D02 board kit: how the ten boards are built

The SCR-050 Heatmap + DOM ladder boards of E21-D02 (#440) are generated offline from the spec as cvsheet JSON sheets,
then rendered on Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in this
folder runs from a checkout of the repository with Python 3.12; nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                                                                                                                       |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e21d02kit.py`           | The kit: §0's board table, §2's anatomy and redlines, §3.1's tier and density matrix, §4's states, §5's legs, §7.3's tables, §7.4, §9.2's keys and §12's copy deck parsed from the spec; the seeded synthetic book (seed 440); the board, section, pack and lint builders. |
| `gen/ui.py`              | The SCR-050 panel and its widgets: header, the one notice, the tier and shed notices, the pane and the ladder, the footer, the detector strip, the menus, the reveal and the Table view.                                                                                   |
| `gen/gen_NN.py`          | One generator per board.                                                                                                                                                                                                                                                   |
| `check_all.py`           | The scan over the ten sheets (two builds byte-identical, validator, pack, mkcall4 count, packed sections expanded and compared, banned strings, copy and figure checks).                                                                                                   |
| `local-icons.js`         | The local icon seed for the per-set file: `../run/local-icons.js` plus the seven glyphs these boards bind beyond it, each named to its `packages/ui` Lucide SVG.                                                                                                           |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line, the live checks and the notes.                                                                                              |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                                                                                                 |
| `build-notes.md`         | The authors' notes: sources and pins, the seeded world, readings, kit choices and the live-check fold.                                                                                                                                                                     |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                                                                                                      |

The spec is read from this checkout by repo-relative path: `docs/design/E21/E21-D02.md` (there is no hand-off file)
and the recorded instrument fixture `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json` (the BTCUSDT
tick and qty step only). The kit pins the md5 of each source in `DOCS` and refuses to run when one drifts, because
every `L<n>` cite on the boards is looked up in that text: after a spec edit, re-check the cites, re-pin and rebuild.
The validator, packer, `mkcall4.py`, components list and tokens are the shared copies in `../tools/`. `CV_CHECKOUT`
names another checkout root if the kit is run from outside this folder.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e21-d02
python3 -X utf8 -I -B e21d02kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                    # "OK: 0 failures"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (the
seeded world, seed 440). To check the packed sheets against the raw ones:

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

Follow `../README.md` §2 to §4 with the raw sheets in `build/` as the set, running `local-icons.js` (here) in place of
`../run/local-icons.js`. The packed sheets the drivers take must record the raw sheet's absolute path, so pack again
into a folder outside the repository (`../tools/compact.py build/NN-<slug>.json <outside>/NN-<slug>.json`) and never
commit that copy; the committed `v4/` keeps the bare name. File `E21-D02 boards`, page `E21-D02`; every board renders
under the dark theme and is exported under it; boards 01, 05 and 07 are exported again under the light set
(`-light.png`; each twin is token-bound), then the dark set is restored. Board 01's dark export is run through
`docs/design/_tools/cvd_sim.py` for the three colour-vision exports board 09 names (`-greyscale.png`,
`-deuteranopia.png`, `-protanopia.png`). Boards of 1,000 shapes or more are drawn one section per call; reload the tab
before a big board and watch the file's save state, since an unsaved draw cannot be exported.

## The ten boards

| Board                    | Frames | Root w × h  | Theme        |
| ------------------------ | ------ | ----------- | ------------ |
| 01 anatomy-redlines      | 3      | 3280 × 2139 | dark + light |
| 02 tiers-500-unavailable | 4      | 3280 × 1947 | dark         |
| 03 densities             | 3      | 4640 × 1026 | dark         |
| 04 loading-empty         | 3      | 4640 × 1026 | dark         |
| 05 stale-disconnected    | 3      | 4640 × 1026 | dark + light |
| 06 resyncing-depth-shed  | 3      | 4640 × 1026 | dark         |
| 07 trading-t2-arm-env    | 5      | 4640 × 2126 | dark + light |
| 08 own-orders-detectors  | 3      | 4640 × 1026 | dark         |
| 09 legend-greyscale-cvd  | 3      | 3184 × 1787 | dark         |
| 10 keyboard-table-reflow | 4      | 3280 × 1667 | dark         |

Root heights are the live-measured ones (build-notes "Live-check fold"). Board ids, PNG paths and the theme-gate
results are in E21-D02 §0's Status cells and its As built record (§17).
