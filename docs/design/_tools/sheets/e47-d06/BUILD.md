# E47-D06 board kit: how the eight boards are built

The canvas-accessibility boards of E47-D06 (#1305) are generated offline from the spec as cvsheet JSON sheets, then
rendered on Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in this
folder runs from a checkout of the repository with Python 3.12 and `git`; nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                                                                                                        |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e47d06kit.py`           | The kit: §0's board table, the hand-off's §I frame plan, §2's inventory, §4's caps, §5's name grammar, §6.2's column sets, §8's labels, §9's oracle, §10's T2 reasons and §13's copy deck parsed from the spec; the seeded world (seed 1305); the builders. |
| `gen/common.py`          | The shared builders of the table boards: the profile and ladder panels, their rows, the grid placement.                                                                                                                                                     |
| `gen/gen_NN.py`          | One generator per board; 08 calls 03's builders with the light theme.                                                                                                                                                                                       |
| `check_all.py`           | The scan over the eight sheets (validator, pack, mkcall4 count, shapes, icons, captions, cell padding, md line 3, backticks in drawn text, callouts inside their frame, the source md5 pins).                                                               |
| `local-icons.js`         | The local icon seed for the per-set file: `../run/local-icons.js` plus the six glyphs these boards bind, each named to its `packages/ui` Lucide SVG.                                                                                                        |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line and the notes.                                                                                                |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                                                                                  |
| `build-notes.md`         | The authors' notes: sources, the boards, the world, the readings taken and the live-check fold.                                                                                                                                                             |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                                                                                       |

The spec is read from this checkout by repo-relative path: `docs/design/E47/E47-D06.md` and `E47-D06-handoff.md`, with
`docs/design/E09/E09-D09.md` (the T2 reason templates), `docs/design/E11/E11-D04.md` (SCR-047's copy, the stale chip)
and the recorded instrument fixture (`packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`, BTCUSDT's tick
size only). The screens catalogue (`docs/plan/14-screens-catalogue.md`, the panel titles) is read with `git show` at
the base the spec's "Inputs pinned" line names, so it reads as the spec cites it; E47-D04's ring geometry is read at
the Start line's E47-D04 pin. The kit pins the md5 of each source (`DOCS`) and refuses to run when one drifts, because
every `L<n>` cite on the boards is looked up in that text: after a spec edit, re-check the cites, re-pin and rebuild.
The validator, packer, `mkcall4.py`, components list and tokens are the shared copies in `../tools/`. `CV_CHECKOUT`
names another checkout root if the kit is run from outside this folder.

## Rebuild the eight sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e47-d06
python3 -X utf8 -I -B e47d06kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                    # "OK: 0 findings"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (seed
1305). To check the packed sheets against the raw ones:

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
commit that copy; the committed `v4/` keeps the bare name. File `E47-D06 boards`, page `E47-D06 — Canvas
accessibility`; every board renders under the dark theme and is exported with its own set active: 08 light, the rest
dark (the twin is token-bound). The post-step dashes the `dashed · surrogate …` bounds of board 02. Boards 05 and 06
are large (about 2,100 and 2,700 shapes): run touch and relayout once per top-level child of the root, never as one
call, and keep the Penpot window in the foreground while texts measure (the As built record, spec §18).

## The eight boards

| Board                   | Frames | Root w × h  | Theme | Sections (packed) |
| ----------------------- | ------ | ----------- | ----- | ----------------- |
| 01 four-layer-inventory | 1      | 1920 × 998  | dark  | 18                |
| 02 surrogate-grammar    | 3      | 4640 × 998  | dark  | 123               |
| 03 profile-table        | 2      | 3280 × 998  | dark  | 51                |
| 04 ladder-table         | 2      | 3280 × 998  | dark  | 56                |
| 05 table-states         | 6      | 4640 × 1878 | dark  | 123               |
| 06 equal-status-headers | 6      | 4640 × 1878 | dark  | 153               |
| 07 parity-oracle        | 1      | 1920 × 998  | dark  | 12                |
| 08 profile-table-light  | 2      | 3280 × 998  | light | 51                |

Root heights are the live-measured ones (build-notes "Live-check fold"). Board ids, PNG paths and the theme-gate
results are in E47-D06 §0's Status cells and its As built record (§18).
