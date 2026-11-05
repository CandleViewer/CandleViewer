# E47-D09 board kit: how the ten boards are built

The keyboard-operability boards of E47-D09 (#1308) are generated offline from the spec as cvsheet JSON sheets, then
rendered on Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in this
folder runs from a checkout of the repository with Python 3.12 and `git`; nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                                                                                                                    |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e47d09kit.py`           | The kit: §0's board table, the hand-off's §H frame plan, §1.4's K-rules, §3's census, §10's redlines, §16's copy deck and the §19 C / G rows parsed from the spec; the keymap registry; the seeded world (seed 1308); the node builders, the window, writer and packer. |
| `gen/common.py`          | The shared builders: Kbd, the seeded chart and price axis, the trading workspace, the settings chrome.                                                                                                                                                                  |
| `gen/gen_NN.py`          | One generator per board; 02 calls 01's builder with the light theme, 06 and 10 call 05's with light and high contrast.                                                                                                                                                  |
| `check_all.py`           | All ten built twice (byte-identical), then the scan over the ten sheets (validator, pack, mkcall4 count, shapes, icons, captions, cell padding, md line 3, root width).                                                                                                 |
| `local-icons.js`         | The local icon seed for the per-set file: `../run/local-icons.js` plus the five glyphs these boards bind, each named to its `packages/ui` Lucide SVG.                                                                                                                   |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line and the notes.                                                                                                            |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                                                                                              |
| `build-notes.md`         | The authors' notes: sources, the boards, the world, the readings taken and the live-check fold.                                                                                                                                                                         |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                                                                                                   |

The spec is read from this checkout by repo-relative path: `docs/design/E47/E47-D09.md` and `E47-D09-handoff.md`,
with the recorded instrument fixture (`packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`, BTCUSDT's tick
size only). The keymap registry (`apps/web/src/keymap/keymap.json` and `reserved-keys.json`) is read with `git show`
at the base the spec's "Inputs pinned" line names, so it reads as the spec cites it. The kit pins the md5 of each
(`DOCS`) and refuses to run when one drifts, because every `L<n>` cite on the boards is looked up in that text: after a
spec edit, re-check the cites, re-pin and rebuild. The validator, packer, `mkcall4.py`, components list and tokens are
the shared copies in `../tools/`. `CV_CHECKOUT` names another checkout root if the kit is run from outside this folder.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e47-d09
python3 -X utf8 -I -B e47d09kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                    # "OK: 0 failures"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (seed
1308). To check the packed sheets against the raw ones:

```sh
for f in v4/*.json; do
  python3 -X utf8 -I -c 'import hashlib, json, sys; p = json.load(open(sys.argv[1]))["compactOf"]
print(sys.argv[1], hashlib.sha256(open("build/" + p["file"], "rb").read()).hexdigest() == p["sha256"])' "$f"
done
```

`-X utf8` makes the kit read and write UTF-8 on every platform: without it, Python on Windows decodes the sources with
the locale code page and the generators fail.

## Render and export

Follow `../README.md` §2 to §4 with the raw sheets in `build/` as the set, running `local-icons.js` (here) in place of
`../run/local-icons.js`. The packed sheets the drivers take must record the raw sheet's absolute path, so pack again
into a folder outside the repository (`../tools/compact.py build/NN-<slug>.json <outside>/NN-<slug>.json`) and never
commit that copy; the committed `v4/` keeps the bare name. File `E47-D09 boards`, page `E47-D09`; every board renders
under the dark theme and is exported with its own set active: 02 and 06 light, 10 high contrast, the rest dark (the
twins are token-bound). A dialog with no placement is re-centred after relayout on both axes; the CMP-059 palette is
re-centred horizontally only (it is top-anchored), and the CMP-094 cheatsheet keeps the sheet's placement.

## The ten boards

| Board               | Frames | Root w × h  | Theme | Sections (packed) |
| ------------------- | ------ | ----------- | ----- | ----------------- |
| 01 order-line       | 5      | 4640 × 1878 | dark  | 91                |
| 02 order-line-light | 5      | 4640 × 1878 | light | 91                |
| 03 anchors          | 3      | 4640 × 1008 | dark  | 48                |
| 04 node-move        | 5      | 4640 × 1878 | dark  | 56                |
| 05 palette          | 4      | 3280 × 1878 | dark  | 33                |
| 06 palette-light    | 4      | 3280 × 1878 | light | 33                |
| 07 cheatsheet       | 4      | 3280 × 1878 | dark  | 62                |
| 08 hotkey-editor    | 5      | 4640 × 1878 | dark  | 65                |
| 09 inert            | 2      | 3280 × 998  | dark  | 17                |
| 10 palette-hc       | 4      | 3280 × 1878 | hc    | 33                |

Root heights are the live-measured ones (build-notes "Live-check fold"). Board ids, PNG paths and the theme-gate
results are in E47-D09 §0's Status cells and its As built record (§21).
