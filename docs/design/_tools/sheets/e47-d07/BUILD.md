# E47-D07 board kit: how the ten boards are built

The live-region announcement boards of E47-D07 (#1306) are generated offline from the spec as cvsheet JSON sheets,
then rendered on Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in
this folder runs from a checkout of the repository with Python 3.12 and `git`; nothing here touches the network or
Penpot.

## What is here

| Path                     | What                                                                                                                                                                                                                                                                                  |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e47d07kit.py`           | The kit: §0's board table, the hand-off's §H frame plan, §3.1's classes, §4's taxonomy, §5.1's ranks, §6.4's matrix, §7.1's slots, §7.2's copy deck, §7.3's reason map and §8.1's panel classes parsed from the spec; the spec's audit tool as a library (the replays); the builders. |
| `gen/common.py`          | The shared imports and the column packer of the diagram boards.                                                                                                                                                                                                                       |
| `gen/gen_NN.py`          | One generator per board; 07 calls 06's default-frame builder with the light theme.                                                                                                                                                                                                    |
| `check_all.py`           | The scan over the ten sheets (validator, pack, mkcall4 count, shapes, icons, captions, cell padding, md line 3, backticks in drawn text, sized callouts or tags inside their frame, the source md5 pins).                                                                             |
| `local-icons.js`         | The local icon seed for the per-set file: `../run/local-icons.js` plus the two glyphs these boards bind beyond it, each named to its `packages/ui` Lucide SVG.                                                                                                                        |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line and the notes.                                                                                                                          |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                                                                                                            |
| `build-notes.md`         | The authors' notes: sources, the boards, the kit choices and the live-check fold.                                                                                                                                                                                                     |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                                                                                                                 |

The spec is read from this checkout by repo-relative path: `docs/design/E47/E47-D07.md`, `E47-D07-handoff.md` and
`E47-D07-transcripts.json`, the spec's audit tool `docs/design/_tools/e47_d07_announcement_audit.py` (loaded as a
library: every timeline figure is its replay of the seeded scripts), `docs/design/E09/E09-D09.md` (the view-as reason
words) and the recorded instrument fixture (`packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`,
BTCUSDT's tick size only). E47-D04's ring geometry and E47-D05's SettingsNav and tile labels are read with `git show`
at the pins the spec's Start line names. The kit pins the md5 of each source (`DOCS`, the paths and the pins kept
apart) and refuses to run when one drifts, because every `L<n>` cite on the boards is looked up in that text: after a
spec edit, re-check the cites, re-pin and rebuild. The validator, packer, `mkcall4.py`, components list and tokens are
the shared copies in `../tools/`. `CV_CHECKOUT` names another checkout root if the kit is run from outside this folder.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e47-d07
python3 -X utf8 -I -B e47d07kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                    # "OK: 0 findings"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (seed
1306). To check the packed sheets against the raw ones:

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
commit that copy; the committed `v4/` keeps the bare name. File `E47-D07 boards`, page `E47-D07 announcements`; every
board renders under the dark theme and is exported with its own set active: 07 light, the rest dark (the twin is
token-bound). Every board renders in one pass (the largest, 06, about 730 shapes). Re-centre board 05's dialog after
relayout (the sidecar's live check).

## The ten boards

| Board                 | Frames | Root w × h | Theme |
| --------------------- | ------ | ---------- | ----- |
| 01 taxonomy-map       | 1      | 1920 × 998 | dark  |
| 02 shell-pair-writers | 2      | 3280 × 998 | dark  |
| 03 polite-timeline    | 1      | 1920 × 998 | dark  |
| 04 incident-timeline  | 1      | 1920 × 998 | dark  |
| 05 focus-kept         | 2      | 3280 × 998 | dark  |
| 06 scr117-panel       | 2      | 3280 × 998 | dark  |
| 07 scr117-panel-light | 1      | 1920 × 998 | light |
| 08 verbosity-matrix   | 1      | 1920 × 998 | dark  |
| 09 transcript-preview | 3      | 4640 × 998 | dark  |
| 10 copy-anatomy       | 1      | 1920 × 998 | dark  |

Root heights are the live-measured ones (build-notes "Live-check fold"). Board ids, PNG paths and the theme-gate
results are in E47-D07 §0's Status cells and its As built record (§17).
