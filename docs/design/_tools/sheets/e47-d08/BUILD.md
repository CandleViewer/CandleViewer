# E47-D08 board kit: how the ten boards are built

The motion boards of E47-D08 (#1307) are generated offline from the spec as cvsheet JSON sheets, then rendered on
Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in this folder runs from
a checkout of the repository with Python 3.12 and `git`; nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                                                                                                                                                                                                   |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `e47d08kit.py`           | The kit: §0's board table, the hand-off's §H frame plan, §2's tiers, §3's inventory, §4's constants, surfaces and simulation inputs, §8's pause rows, §10's matrix, §11's safety rows, §12's T2 verb and §15's copy deck parsed from the spec; TICKS' generator ported and self-tested against its own output; §4.4's simulation re-run; the builders. |
| `gen/common.py`          | The synthetic world (the burst and two more symbols), the watchlist, the DOM ladder, the chart body, the liquidation mark and the millisecond timeline several boards draw.                                                                                                                                                                            |
| `gen/gen_NN.py`          | One generator per board; 03 and 09 build their twin frame with the same builder.                                                                                                                                                                                                                                                                       |
| `check_all.py`           | The scan over the ten sheets (validator, pack, mkcall4 count, shapes, icons, captions, cell padding, md line 3, backticks in drawn text, the source md5 pins).                                                                                                                                                                                         |
| `local-icons.js`         | The local icon seed for the per-set file: `../run/local-icons.js` plus the two glyphs these boards bind beyond it, each named to its `packages/ui` Lucide SVG.                                                                                                                                                                                         |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line and the notes.                                                                                                                                                                                           |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                                                                                                                                                                             |
| `build-notes.md`         | The authors' notes: pipeline, readings, kit labels and the live-check fold.                                                                                                                                                                                                                                                                            |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                                                                                                                                                                                  |

The spec is read from this checkout by repo-relative path: `docs/design/E47/E47-D08.md`, `E47-D08-handoff.md` and the
synthetic tick generator `packages/fixtures/src/synthetic-ticks.mjs` (read as text; its `burst` preset and PRNG are
ported, never run). E47-D04's ring geometry and E47-D05's SCR-117 strings are read with `git show` at the pins the
spec's "Inputs pinned" line names (their merge commits). The kit pins the md5 of each source (`_PATHS` and `_MD5`,
kept apart) and refuses to run when one drifts, because every `L<n>` cite on the boards is looked up in that text:
after a spec edit, re-check the cites, re-pin and rebuild. The validator, packer, `mkcall4.py`, components list and
tokens are the shared copies in `../tools/`. `CV_CHECKOUT` names another checkout root if the kit is run from outside
this folder.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e47-d08
python3 -X utf8 -I -B e47d08kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                    # "OK: 0 findings"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (TICKS
seed 1 and the kit's own mulberry32 seeds). To check the packed sheets against the raw ones:

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
commit that copy; the committed `v4/` keeps the bare name. File `E47-D08 boards`, page `E47-D08 — Motion`; every
board renders under the dark theme and is exported under it; board 03 is exported again under the light set and
board 09 under the high-contrast set (`-light.png`, `-high-contrast.png`; each twin is token-bound), then the dark set
is restored. Board 06 (about 1 850 shapes) is drawn in steps: one section per call, then touch and relayout one
top-level child per call. Reload the tab before a big board and check the first frame after a reload for a fallback
font.

## The ten boards

| Board               | Frames | Root w × h | Theme        |
| ------------------- | ------ | ---------- | ------------ |
| 01 inventory-map    | 3      | 4640 × 998 | dark         |
| 02 budget-timeline  | 2      | 3280 × 998 | dark         |
| 03 region-arbiter   | 2      | 3280 × 998 | dark + light |
| 04 price-cell-modes | 3      | 4640 × 998 | dark         |
| 05 liquidation      | 2      | 3280 × 998 | dark         |
| 06 heatmap-tiers    | 3      | 4640 × 998 | dark         |
| 07 pause-controls   | 3      | 4640 × 998 | dark         |
| 08 override-vs-os   | 1      | 1920 × 998 | dark         |
| 09 safety-static    | 2      | 3280 × 998 | dark + hc    |
| 10 forced-reduce    | 1      | 1920 × 998 | dark         |

Root heights are the live-measured ones (build-notes "Live-check fold"). Board ids, PNG paths and the theme-gate
results are in E47-D08 §0's Status cells and its As built record (§20).
