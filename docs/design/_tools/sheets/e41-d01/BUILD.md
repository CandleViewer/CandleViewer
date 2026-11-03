# E41-D01 board kit: how the ten boards are built

The research board and the SCR-093..SCR-096 lo-fi wireframes of E41-D01 (#1017) are generated offline from the research
memo as cvsheet JSON sheets, then rendered on Penpot with the shared drivers in `docs/design/_tools/sheets/`
(`README.md` there). Everything in this folder runs from a checkout of the repository with Python 3.12 and `git`;
nothing here touches the network or Penpot.

## What is here

| Path                      | What                                                                                                                                                                                                                       |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e41d01kit.py`            | The kit: memo §0's board table, §5 findings, §6 decisions, §7 frames and §7.1 copy deck parsed from the memo; the `17` §1.6 journey; the seeded world (seed 1017); greyscale tokens, node builders, writer, md and packer. |
| `gen/wf.py`               | The wireframe parts shared by the generators (page chrome, controls, the journal table, dialogs, lo-fi charts).                                                                                                            |
| `gen/s093.py` … `s096.py` | The per-screen parts of SCR-093, SCR-094, SCR-095 and SCR-096.                                                                                                                                                             |
| `gen/gen_NN.py`           | One generator per board.                                                                                                                                                                                                   |
| `check_all.py`            | Builds the ten twice (byte-identical) and scans them (validator, mkcall4 count, node rules, captions, cell padding, greyscale only, md5 pins, `compactOf`).                                                                |
| `local-icons.js`          | The local icon seed for the per-set file: `../run/local-icons.js` plus the ten glyphs these sheets need, each named by its `packages/ui` Lucide SVG.                                                                       |
| `NN-<slug>.md`            | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: file, page, export, sheet and theme), its frames, the validator line and the notes.                                                         |
| `v4/NN-<slug>.json`       | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                                                 |
| `build-notes.md`          | The authors' notes: sources, the world, the readings taken, the review fold and the live-check fold.                                                                                                                       |
| `build/` (not committed)  | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                                                      |

The memo (`docs/design/research/e41-journal-review.md`), its session protocol, `17` and the recorded instrument
fixture (`packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`, the BTCUSDT and ETHUSDT ticks and the qty
step) are read from this checkout by repo-relative path; `14` and `21` are read with `git show` at the memo's base
`46e6acd2d`, the text the memo cites. The kit pins the md5 of each (`DOCS`) and refuses to run when one drifts, because
every `L<n>` cite on the boards is looked up in that text: after a memo edit, re-check the cites, re-pin and rebuild.
The validator, packer, `mkcall4.py`, components list and tokens are the shared copies in `../tools/`. `CV_CHECKOUT`
names another checkout root if the kit is run from outside this folder.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e41-d01
python3 -X utf8 -I -B e41d01kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                    # "OK: 0 failures"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (seed
1017). To check the packed sheets against the raw ones:

```sh
for f in v4/*.json; do
  python3 -X utf8 -I -c 'import hashlib, json, sys; p = json.load(open(sys.argv[1]))["compactOf"]
print(sys.argv[1], hashlib.sha256(open("build/" + p["file"], "rb").read()).hexdigest() == p["sha256"])' "$f"
done
```

`-X utf8` makes the kit read and write UTF-8 on every platform: without it, Python on Windows decodes the sources with
the locale code page and the generators fail.

## Render and export

Follow `../README.md` §2 to §4 with the raw sheets in `build/` as the set, and run `local-icons.js` (this folder) in
place of `../run/local-icons.js` at §2 step 3: the sheets bind `refresh`, `search` and six other glyphs the shared seed
does not create. The packed sheets the drivers take must record the raw sheet's absolute path, so pack again into a
folder outside the repository (`../tools/compact.py build/NN-<slug>.json <outside>/NN-<slug>.json`) and never commit
that copy; the committed `v4/` keeps the bare name. File `E41-D01 boards`, page `E41-D01`; every board renders and
exports under the dark theme only (memo §0, BQ-15: no light twins). The post-step names frames with U+2215 for `/` and
dashes the `dashed · …` strokes (T2 controls, the 200 % viewport outlines, the board-10 legends).

## The ten boards

| Board                    | Frames | Root w × h  | Theme | Sections (packed) |
| ------------------------ | ------ | ----------- | ----- | ----------------- |
| 01 research-board        | 3      | 2080 × 2615 | dark  | 29                |
| 02 scr093-default        | 3      | 3120 × 1595 | dark  | 37                |
| 03 scr093-states         | 7      | 3120 × 2827 | dark  | 45                |
| 04 scr094-default        | 1      | 1840 × 1356 | dark  | 10                |
| 05 scr094-context-states | 5      | 3120 × 2263 | dark  | 43                |
| 06 scr095-default        | 2      | 3120 × 1487 | dark  | 61                |
| 07 scr095-states         | 6      | 3120 × 2343 | dark  | 25                |
| 08 scope-and-cohort      | 3      | 3120 × 1851 | dark  | 28                |
| 09 scr096-tag-manager    | 7      | 3248 × 2418 | dark  | 34                |
| 10 keyboard-and-reflow   | 7      | 2608 × 2923 | dark  | 32                |

Root heights are the live check's read-back (`LIVE_ROOT_H`, build-notes "Live-check fold"). The PNG paths are in the
memo's §0 rows; the board ids and the theme-gate results in its As built record (§12).
