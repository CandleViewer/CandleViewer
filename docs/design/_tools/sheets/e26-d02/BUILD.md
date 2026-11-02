# E26-D02 board kit: how the ten boards are built

The SCR-097 boards of E26-D02 (#509) are generated offline from the spec as cvsheet JSON sheets, then rendered on
Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in this folder runs from
a checkout of the repository with Python 3.12 and `git`; nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                            |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e26d02kit.py`           | The kit: §16's board and frame tables and the spec's strings parsed from the spec; the seeded world (seed 509); the node builders, the root, writer and packer. |
| `gen/frames.py`          | The frame builders, keyed by §16's frame id; a light twin calls the same builders with its own theme.                                                           |
| `gen/gen_NN.py`          | One generator per board: `frames.build_board(NN)`.                                                                                                              |
| `check_all.py`           | The scan over the ten sheets (validator, mkcall4 count, node rules, captions, cell padding, overflow and overlap by estimate, md5 pin, local-token rows).       |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line and the notes.    |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                      |
| `local-tokens.json`      | The PROPOSED local token `color.replay.border` (RULED BQ-10), one row per theme: dark and hc `{palette.purple.400}`, light `{palette.purple.600}`.              |
| `tokens.with-local.json` | `../tools/token-sync.json` plus those rows: the validator's `--tokens`.                                                                                         |
| `build-notes.md`         | The authors' notes: sources, the local token, pipeline, the live-check fold, the seeded world, layout and the kit's readings.                                   |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                           |

The spec is read from this checkout by repo-relative path: `docs/design/E26/E26-D02.md` and `E26-D02-handoff.md`,
with the recorded instrument fixture (`packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`, tick size and
qty step only). The kit pins the md5 of each (`DOCS`) and refuses to run when one drifts, because every `L<n>` cite on
the boards is looked up in that text: after a spec edit, re-check the cites, re-pin and rebuild. The validator, packer,
`mkcall4.py`, components list and tokens are the shared copies in `../tools/`. `CV_REPO` names another checkout root
if the kit is run from outside this folder.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e26-d02
python3 -I -B e26d02kit.py selftest                   # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -I -B gen/gen_$n.py; done
python3 -I -B check_all.py                            # "OK: 0 findings"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`,
and `v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic
(seed 509, one illustrative clock), and the `.md` the kit writes is already Prettier-stable. To check the packed
sheets against the raw ones:

```sh
for f in v4/*.json; do
  python3 -I -c 'import hashlib, json, sys; p = json.load(open(sys.argv[1]))["compactOf"]
print(sys.argv[1], hashlib.sha256(open("build/" + p["file"], "rb").read()).hexdigest() == p["sha256"])' "$f"
done
```

## Render and export

Follow `../README.md` §2 to §4 with the raw sheets in `build/` as the set; the drivers resolve the bare
`compactOf.file` against that folder. File `E26-D02 boards`, page `E26-D02 SCR-097 Replay page`; create the local
token sets of `local-tokens.json` (`E26-D02 local · dark`, `· light`, `· hc`, each active only in its theme) before the
first section call. Every board renders under the dark theme; B3 and B8 are exported under the light set, every other
board under dark, as `docs/design/E26/img/E26-D02-NN-<slug>-<theme>.png`; B2 and B6 also get
`docs/design/_tools/cvd_sim.py`'s greyscale, deuteranopia and protanopia renders.

## The ten boards

| Board                    | Frames | Root w × h  | Theme | Sections (packed) |
| ------------------------ | ------ | ----------- | ----- | ----------------- |
| 01 anatomy-focus-order   | 2      | 4240 × 1598 | dark  | 79                |
| 02 playing-paper         | 1      | 2560 × 1278 | dark  | 48                |
| 03 playing-paper-light   | 1      | 2560 × 1278 | light | 48                |
| 04 ac1-control-set       | 2      | 4560 × 1278 | dark  | 81                |
| 05 pre-play-and-paused   | 3      | 4560 × 2438 | dark  | 71                |
| 06 scrubber-and-seeking  | 2      | 4240 × 1398 | dark  | 68                |
| 07 stop-states           | 4      | 4560 × 2438 | dark  | 212               |
| 08 stop-states-light     | 4      | 4560 × 2438 | light | 212               |
| 09 paper-fills-and-speed | 2      | 4560 × 1398 | dark  | 89                |
| 10 panels-and-conditions | 4      | 4560 × 2558 | dark  | 206               |

Root heights are the live-measured footer end + 80 (`k.MEASURED_H`, build-notes "Live-check fold"). Board ids, PNG
paths and the theme-gate results are in E26-D02 §16's Status cells and its As built record.
