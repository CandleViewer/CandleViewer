# E19-D01 board kit: how the nine boards are built

The nine greyscale research boards of E19-D01 (#382), the profiles UX memo, are generated offline from the memo as
cvsheet JSON sheets, then rendered on Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md`
there). Everything in this folder runs from a checkout of the repository with Python 3.12 and `git`; nothing here
touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                                                                                                     |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e19d01kit.py`           | The kit: memo §0's board table, §2 questions, §3 findings, §5 levels, §6.1 modes, §7 decisions, §8 competitive rows, §9 rows and §10 protocol parsed from the memo; the seeded world (seed 382); greyscale tokens, node builders, writer, md and packer. |
| `gen/rb.py`              | The research-board parts shared by the generators (cards, chips, menu, radio group, the lo-fi profile pane, legend).                                                                                                                                     |
| `gen/gen_NN.py`          | One generator per board.                                                                                                                                                                                                                                 |
| `check_all.py`           | Builds the nine twice (byte-identical) and scans them (validator, mkcall4 count, node rules, captions, cell padding, greyscale only, md5 pins, `compactOf`).                                                                                             |
| `local-icons.js`         | The local icon seed for the per-set file: `../run/local-icons.js` plus the four glyphs these sheets need, each named by its `packages/ui` Lucide SVG.                                                                                                    |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: file, page, export, sheet and theme), its frames, the validator line and the notes.                                                                                       |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                                                                               |
| `build-notes.md`         | The authors' notes: sources, the world, the readings taken and the live-check fold.                                                                                                                                                                      |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                                                                                    |

The memo (`docs/design/research/e19-profiles.md`) and the recorded instrument fixture
(`packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`, the BTCUSDT tick and qty step) are read from this
checkout by repo-relative path; `05` is read with `git show` at the memo's base `ca49e693ae45`, the text the memo
cites. The kit pins the md5 of each (`DOCS`) and refuses to run when one drifts, because every `L<n>` cite on the
boards is looked up in that text: after a memo edit, re-check the cites, re-pin and rebuild. The validator, packer,
`mkcall4.py`, components list and tokens are the shared copies in `../tools/`. `CV_CHECKOUT` names another checkout
root if the kit is run from outside this folder.

## Rebuild the nine sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e19-d01
python3 -X utf8 -I -B e19d01kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                    # "OK: 0 failures"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (seed
382). To check the packed sheets against the raw ones:

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
place of `../run/local-icons.js` at §2 step 3: the sheets bind `check`, `chevron-down`, `chevron-right` and `info`,
which the shared seed does not create. The packed sheets the drivers take must record the raw sheet's absolute path,
so pack again into a folder outside the repository (`../tools/compact.py build/NN-<slug>.json <outside>/NN-<slug>.json`)
and never commit that copy; the committed `v4/` keeps the bare name. File `E19-D01 boards`, page `E19-D01`; every
board renders and exports under the dark theme only, greyscale (memo §0, BQ-15: no light twins). The post-step names
frames with U+2215 for `/` and dashes the `dashed · …` strokes (board markers, accessible-name notes and board 06's
approximated-row outlines).

## The nine boards

| Board                         | Frames | Root w × h  | Theme | Sections (packed) |
| ----------------------------- | ------ | ----------- | ----- | ----------------- |
| 01 questions-hypotheses       | 2      | 2080 × 1664 | dark  | 18                |
| 02 competitive-teardown       | 2      | 2080 × 1368 | dark  | 11                |
| 03 period-mode-map            | 2      | 2080 × 1376 | dark  | 12                |
| 04 derived-level-ladder       | 2      | 2080 × 1768 | dark  | 17                |
| 05 developing-vs-final        | 2      | 1708 × 932  | dark  | 11                |
| 06 approximated-partial-strip | 3      | 3054 × 1095 | dark  | 14                |
| 07 density-row-legibility     | 3      | 3228 × 847  | dark  | 19                |
| 08 decisions                  | 2      | 2080 × 1912 | dark  | 14                |
| 09 protocol-table-alternative | 3      | 2080 × 2956 | dark  | 54                |

Root heights are the live check's read-back (`LIVE_ROOT_H`, build-notes "Live-check fold"). The PNG paths are in the
memo's §0 rows; the board ids and the theme-gate results in its As built record (§13).
