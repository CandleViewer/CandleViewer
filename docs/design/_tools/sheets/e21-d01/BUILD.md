# E21-D01 board kit: how the eight boards are built

The eight greyscale research boards of E21-D01 (#417), the ladder and liquidity-trail UX memo, are generated offline
from the memo as cvsheet JSON sheets, then rendered on Penpot with the shared drivers in `docs/design/_tools/sheets/`
(`README.md` there). Everything in this folder runs from a checkout of the repository with Python 3.12; nothing here
touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                                                                                                              |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e21d01kit.py`           | The kit: memo §0's board table, §2 questions, §3 findings, §4 walkthrough, §6 defaults, §7 decisions, §8 kill-list, §10 protocol and §12 rows parsed from the memo; the seeded synthetic book (seed 417); greyscale tokens, node builders, writer, md and packer. |
| `gen/rb.py`              | The research-board parts shared by the generators (ladder, heatmap trail, pulled carrier, legend, cards, markers).                                                                                                                                                |
| `gen/gen_NN.py`          | One generator per board.                                                                                                                                                                                                                                          |
| `check_all.py`           | Builds the eight twice (byte-identical) and scans them (validator, mkcall4 count, node rules, captions, cell padding, greyscale only, no third-party product name, PROPOSED stamps, md5 pins, `compactOf`).                                                       |
| `local-icons.js`         | The local icon seed for the per-set file: `../run/local-icons.js` plus the one glyph these sheets need (`info`), named by its `packages/ui` Lucide SVG.                                                                                                           |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: file, page, export, sheet and theme), its frames, the validator line and the notes.                                                                                                |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                                                                                        |
| `build-notes.md`         | The authors' notes: sources, the world, the readings taken and the live-check fold.                                                                                                                                                                               |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                                                                                             |

The memo (`docs/design/research/e21-dom-heatmap.md`) and the recorded instrument fixture
(`packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`, the BTCUSDT tick and qty step) are read from this
checkout by repo-relative path. The kit pins the md5 of each (`DOCS`) and refuses to run when one drifts, because
every `L<n>` cite on the boards is looked up in that text: after a memo edit, re-check the cites, re-pin and rebuild.
The validator, packer, `mkcall4.py`, components list and tokens are the shared copies in `../tools/`. `CV_CHECKOUT`
names another checkout root if the kit is run from outside this folder.

## Rebuild the eight sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e21-d01
python3 -X utf8 -I -B e21d01kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                    # "OK: 0 failures"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (seed
417). To check the packed sheets against the raw ones:

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
place of `../run/local-icons.js` at §2 step 3: the sheets bind `info`, which the shared seed does not create. The
packed sheets the drivers take must record the raw sheet's absolute path, so pack again into a folder outside the
repository (`../tools/compact.py build/NN-<slug>.json <outside>/NN-<slug>.json`) and never commit that copy; the
committed `v4/` keeps the bare name. File `E21-D01 boards`, page `E21-D01`; every board renders and exports under the
dark theme only, greyscale (memo §0: no light twins). The post-step names frames with U+2215 for `/`, dashes the
`dashed · …` strokes (board markers, read-across rows, the caveat card) and turns the `hatch line · …` rules of the
pulled carrier 45° (boards 03 and 04).

## The eight boards

| Board                    | Frames | Root w × h  | Theme | Sections (packed) |
| ------------------------ | ------ | ----------- | ----- | ----------------- |
| 01 questions-hypotheses  | 3      | 2080 × 2338 | dark  | 24                |
| 02 centring-modes        | 3      | 2320 × 2591 | dark  | 129               |
| 03 placement-and-axes    | 3      | 1760 × 2364 | dark  | 42                |
| 04 pulled-vs-consumed    | 3      | 1840 × 2151 | dark  | 16                |
| 05 tiers-and-shed        | 3      | 2080 × 1847 | dark  | 11                |
| 06 own-order-and-legend  | 2      | 1920 × 1299 | dark  | 34                |
| 07 ranked-decisions      | 3      | 2400 × 1690 | dark  | 15                |
| 08 protocol-and-keyboard | 3      | 2240 × 2250 | dark  | 17                |

Root heights are the live check's read-back (`LIVE_ROOT_H`) and board 03's zooms carry the 4 px `ZOOM_GUTTER`
(build-notes "Live-check fold"). The PNG paths are in the memo's §0 rows; the board ids and the theme-gate results in
its As built record (§14).
