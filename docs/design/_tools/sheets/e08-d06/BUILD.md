# E08-D06 board kit: how the eleven boards are built

The SCR-103 symbol info boards of E08-D06 (#174) are generated offline from the spec as cvsheet JSON sheets, then
rendered on Penpot with the shared drivers in `docs/design/_tools/sheets/` (`README.md` there). Everything in this
folder runs from a full clone of the repository with Python 3.12 and `git`; nothing here touches the network or
Penpot.

## What is here

| Path                        | What                                                                                                                                                                     |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `e08d06kit.py`              | The kit: §15's registry, r2's seed data, the §5 formatters, the drawer, band, row and annotation builders, `write_sheet`, `write_md`, `pack_sheet` and the self-test.    |
| `gen/gen_<key>.py`          | One generator per drawn board (`1L` reuses `1D`'s builder, `25H` reuses `25D`'s); `gen/{a,b,c}_helpers.py` hold what a group of boards shares.                           |
| `NN-<slug>-<theme>.md`      | Each board's sidecar as the kit writes it (line 3 is the render drivers' line: page and theme), its frames, the validator line and the notes.                            |
| `v4/NN-<slug>-<theme>.json` | The packed sheets the boards were rendered from. `compactOf.file` is the bare raw-sheet name; `compactOf.sha256` is the raw sheet's, so a rebuild proves itself (below). |
| `r2/e08-d06-board.js.txt`   | The r2 board script (2026-10-23, sha256 `298c156f…e1a7`, pinned in `R2_SHA256`): the kit reads its DATA block only, never its drawing code.                              |
| `build-notes.md`            | The authors' notes: pipeline, file / page / frame naming, the registry, the cap, the ambiguities and the live-check fold.                                                |
| `build/` (not committed)    | The raw sheets with a copy of each `.md` (the set the render drivers read), and `selftest/`. Listed in `.gitignore`.                                                     |

The spec is read from this checkout as at `BASE` (`33bb920225ec`, the merge of the E08-D06 text) with `git show`:
`docs/design/E08/E08-D06.md` and `E08-D06-handoff.md`. The kit pins the md5 of each (`SPEC_MD5`) and refuses to run
when one drifts, because every `L<n>` / `H<n>` cite on the boards is looked up in that text (`k.L`, `k.HL`). The
text as later edited keeps those line numbers. The validator, packer, `mkcall4.py`, components list and tokens are
the shared copies in `../tools/`.

## Rebuild the eleven sheets

From the repository root:

```sh
cd docs/design/_tools/sheets/e08-d06
python3 -I -B e08d06kit.py selftest                    # 26 PASS, "OK: 0 failures"
for g in 1D 1L 3D 6D 10D 15D 18D 21D 23D 25D 25H; do python3 -I -B gen/gen_$g.py; done
```

Each generator writes `build/NN-<slug>-<theme>.json` (validator exit 0 or it raises), `NN-<slug>-<theme>.md` here
and in `build/`, and `v4/NN-<slug>-<theme>.json`. A rebuild on an unchanged kit leaves `git status` clean: the
generation is deterministic (seeded data, no clock). To check the packed sheets against the raw ones:

```sh
for f in v4/*.json; do
  python3 -I -c 'import hashlib, json, sys; p = json.load(open(sys.argv[1]))["compactOf"]
print(sys.argv[1], hashlib.sha256(open("build/" + p["file"], "rb").read()).hexdigest() == p["sha256"])' "$f"
done
```

## Render and export

Follow `../README.md` §2 to §4 with the raw sheets in `build/` as the set. The packed sheets the drivers take must
record the raw sheet's absolute path, so pack again into a folder outside the repository
(`../tools/compact.py build/NN-<slug>-<theme>.json <outside>/NN-<slug>-<theme>.json`) and never commit that copy; the
committed `v4/` keeps the bare name. File `E08-D06 boards`, page `E08-D06 SCR-103 Symbol info`; every board renders
under the dark theme; board 1L is exported under the light set and board 25H under the high-contrast set. The export
names are §15's (`docs/design/E08/img/`), board 25H's with `-hc`.

## The eleven boards

| Key | Board (§15 id)                              | Frames | Root w × h  | Theme | Sections (packed) |
| --- | ------------------------------------------- | ------ | ----------- | ----- | ----------------- |
| 1D  | 01 `SCR-103/populated-recorded-owner`       | 1      | 1120 × 1756 | dark  | 23                |
| 1L  | 01 `SCR-103/populated-recorded-owner`       | 1      | 1120 × 1786 | light | 23                |
| 3D  | 03 `SCR-103/live-stale-t1-t2-owner`         | 1      | 1640 × 1520 | dark  | 36                |
| 6D  | 06 `SCR-103/not-trading-closed-owner`       | 1      | 1120 × 1260 | dark  | 13                |
| 10D | 10 `SCR-103/load-error-catalogue-owner`     | 1      | 1120 × 994  | dark  | 5                 |
| 15D | 15 `CMP-126/funding-countdown-states`       | 1      | 1600 × 1098 | dark  | 12                |
| 18D | 18 `SCR-103/precision-rules-examples`       | 1      | 1840 × 1298 | dark  | 9                 |
| 21D | 21 `SCR-103/keyboard-focus-order`           | 1      | 1640 × 1560 | dark  | 21                |
| 23D | 23 `SCR-103/states-matrix`                  | 1      | 1920 × 1259 | dark  | 23                |
| 25D | 25 `SCR-103/not-recorded-non-owner-view-as` | 2      | 1680 × 1549 | dark  | 29                |
| 25H | 25 `SCR-103/not-recorded-non-owner-view-as` | 2      | 1680 × 1694 | hc    | 29                |

Root heights and the drawers' sticky headers are the live-measured values (`k.MEASURED_H`, `k.HEADER_LIVE_H`;
build-notes "Live-check fold"). Board ids, PNG paths and the theme-gate results are in E08-D06 §15's as-built
record.
