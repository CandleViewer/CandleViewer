# E47-D13 board kit: how the ten boards are built

The conformance-statement boards of E47-D13 (#1311) are generated offline from the spec as cvsheet JSON sheets, then
rendered on Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in this
folder runs from a checkout of the repository with Python 3.12 and `git`; nothing here touches the network or Penpot.

## What is here

| Path                     | What                                                                                                                                                                                                                                                                                                 |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `e47d13kit.py`           | The kit: §0's board table, the hand-off's §H frame plan, §11's copy deck, §14.2's G-ledger, §1.4's rules, §7.6's ratios and every COUNT slot parsed from the spec; the dry-run report and the limitations register; the window and the statement page; the node builders, the writer and the packer. |
| `gen/common.py`          | The shared builders: gutter stops, end-aligned tags, the condensed bands, the skip link.                                                                                                                                                                                                             |
| `gen/gen_NN.py`          | One generator per board.                                                                                                                                                                                                                                                                             |
| `check_all.py`           | The self-test, all ten built (twice with `--twice`, byte-identical), then the scan over the ten sheets (validator, pack, mkcall4 count, shapes, icons, captions, cell padding, md line 3, root width, the md5 pin).                                                                                  |
| `local-icons.js`         | The local icon seed for the per-set file: `../run/local-icons.js` plus the four glyphs these boards bind, each named to its `packages/ui` Lucide SVG.                                                                                                                                                |
| `NN-<slug>.md`           | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page, export, sheet and theme), its frames, the validator line and the notes.                                                                                                                                         |
| `v4/NN-<slug>.json`      | The packed sheets. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below).                                                                                                                                                           |
| `build-notes.md`         | The authors' notes: sources, the window and the page, the readings taken and the live-check fold.                                                                                                                                                                                                    |
| `build/` (not committed) | The raw sheets `NN-<slug>.json` with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                                                                                                                                |

The spec is read from this checkout by repo-relative path: `docs/design/E47/E47-D13.md` and `E47-D13-handoff.md`,
with the generated dry run `docs/plan/a11y/47-conformance-report.md` and the register
`docs/plan/a11y/47-limitations.json`. The screens catalogue `docs/plan/14-screens-catalogue.md` is read with
`git show` at the base the spec's "Inputs pinned" line names, so it reads as the spec cites it. The kit pins the md5
of each (`DOCS`) and refuses to run when one drifts, because every `L<n>` cite on the boards is looked up in that
text: after a spec edit, re-check the cites, re-pin and rebuild. The validator, packer, `mkcall4.py`, components list
and tokens are the shared copies in `../tools/`. `CV_CHECKOUT` names another checkout root if the kit is run from
outside this folder.

## Rebuild the ten sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e47-d13
python3 -X utf8 -I -B e47d13kit.py selftest           # "OK: 0 failures"
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                    # "OK"
```

Each generator writes `build/NN-<slug>.json` (validator exit 0 or it raises), `NN-<slug>.md` here and in `build/`, and
`v4/NN-<slug>.json`. A rebuild on an unchanged kit leaves `git status` clean: the generation is deterministic (no
clock, no random). To check the packed sheets against the raw ones:

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
commit that copy; the committed `v4/` keeps the bare name. File `E47-D13 boards`, page `E47-D13 — Conformance
statement`; every board renders under the dark theme and is exported with its own set active: 02 and 10 light, 04 high
contrast, the rest dark (the twins are token-bound). After relayout set each root's height to the checked one (the
column's or the footer's end + 80; the sheets carry it as a live check).

## The ten boards

| Board                     | Frames | Root w × h  | Theme | Sections (packed) |
| ------------------------- | ------ | ----------- | ----- | ----------------- |
| 01 statement-anatomy      | 2      | 3280 × 1304 | dark  | 43                |
| 02 statement-top          | 1      | 1920 × 998  | light | 17                |
| 03 stale-notice           | 3      | 4640 × 998  | dark  | 29                |
| 04 known-limitations      | 2      | 3280 × 1001 | hc    | 28                |
| 05 alternatives           | 1      | 1920 × 998  | dark  | 17                |
| 06 criteria-table         | 1      | 1920 × 998  | dark  | 24                |
| 07 feedback-copy          | 3      | 4640 × 998  | dark  | 55                |
| 08 entry-insets           | 2      | 3280 × 998  | dark  | 18                |
| 09 reflow-200             | 3      | 4640 × 1029 | dark  | 31                |
| 10 keyboard-reading-order | 2      | 3280 × 998  | light | 42                |

Root heights are the live-measured ones (build-notes "Live-check fold"), except board 01's, an estimate until its
redraw. Board ids, PNG paths and the theme-gate results are in E47-D13 §0's Status cells and its As built record
(§16).
