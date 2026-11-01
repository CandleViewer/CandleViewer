# E09-D07 board script (#190, PR 3): the auth component band

The script that drew the ten E09-D07 specimen boards, and its helpers. The pack is
[`docs/design/E09/E09-D07.md`](../../../E09/E09-D07.md) (§0 records the boards); the PNGs are
`docs/design/E09/img/E09-D07-NN-<slug>.png`.

## Files and sha256

| File                      | What                                                                                             | sha256                                                             |
| ------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `e09-d07-board.r3.js.txt` | The build script, r3 (the version that drew the boards)                                          | `36457d7ab693b85cf2091120db7eabd8a16e9e571ed95c7c91316fbcec87d675` |
| `e09-d07-relayout.js.txt` | The relayout pass (`PASS` `"measure"`, then `"restack"`; r3 roots end at the footer + 80)        | `3e5a9796950f5fdcbf5d5de4d2243f6c2634e025d0e6da1803a994640a771372` |
| `e09-d07-dedupe.js.txt`   | The dedupe pass (`DRY_RUN` true first), unchanged from r2                                        | `792be1ac3ab254954df2fcd63f54ef938473f6b41ac37f72ccde7709d6224d7e` |
| `probe.js.txt`            | The read-only instance probe, unchanged from r2 (byte-equal to `e08-d08/probe.js.txt`)           | `5f2b37587b6fdafc792eab517c32b3195eedab4f48cc64ff21f6a0f6662219d6` |
| `expect.txt`              | Shapes per board from the offline mock (01 … 10; 2,041 in all), the counts the live draw matched | `970dee333d88a2c5a5d1c0b3afbc7006067bf7773065e91ec294d2bc96e1c05a` |

**Provenance.** r3 is a copy of the r2 board script
(`fec0df7b69684c196ba302bd1cf60d7a0f4de82206b5f2a35abf645cfbb02746`, written for #190 by another lane and
released to this PR by the orchestrator's PR 3 ruling; attributed by its sha, never run in place), with
the r3 changes its header lists: the per-set file guard (`FILE_NAME`), inputs regenerated at
`16d70feed9` plus the pack's drift commit (the light `color.status.*.strong` inks of #5140 / #5161, the
re-measured §6 values), and roots that end 80 px below the footer.

**Committed form.** Each script is committed with a `.txt` suffix, byte-identical to what ran (the
sha256 values above are of these bytes), as `e08-d08/` does: they are plugin function bodies with a
top-level `return`, which the repo's ESLint and Prettier do not parse as modules. Strip `.txt` to run one.

## Target

Per-set file `E09-D07 boards` (the PR 3 ruling), page `E09-D07 auth band`
(`e4de416d-a820-8072-8008-e06d290d694c`); the file's local icon components sit on page
`E09-D07 local icons`. The file is referenced by name only and the page by name + id only: no file
id, host or URL is committed. Specimen boards only, no library component, no instance.

## How to run

One Penpot plugin call per step, through `docs/design/_tools/penpot_exec.py`. Make a run copy per call
(never edit these files in place) and set the runner constants by a regex on their own lines:
`WRITER` (the stamp `probe.js` returns for your instance), `FILE_ID` (the per-set file's id, set at load
time, never committed or logged), `ONLY` (`[n]`, one board), `PART` (`0` prints the plan; `k` is part
k), and `PAGE_ID` (null on the first call, then the page id that call returns).

1. Load the token sets into the per-set file first (`docs/design/_tools/penpot_token_sets.py`), so a
   bind by name resolves.
2. `probe.js` until every instance agrees.
3. Board 01 with `PART` null (it creates the page by name; pin the returned page id), then boards 02,
   04, 05, 07 and 08; boards 03 and 06 in two parts (`PART` 1, then 2); board 09 with the light theme
   active and board 10 with high contrast.
4. Per board, `e09-d07-relayout.js` with `PASS` `"measure"` until `unmeasured` is 0, then `"restack"`
   until `moved` is 0.
5. `e09-d07-dedupe.js` with `DRY_RUN` true, then false; `probe.js` again.
6. Export each board at 1x from its result's `exportCommands` line to
   `docs/design/E09/img/E09-D07-NN-<slug>.png`.

## Known script fixes (for an r4; the drawn boards are unaffected)

- `typoOf()` reads a typography token's resolved value in a shape Penpot no longer returns (it now
  returns a list holding one object with plural keys), so every typography bind fell back to its
  literal value (55 … 113 per board).
- Board 09: the per-set file's light token set predates #5140 / #5161, so the template's value guard
  left 7 light status colours unbound; they are drawn with the repo's values. Regenerate that set.
- A fresh per-set file holds its local icon components on page 1, which the page guard counts as
  foreign: rename that page (`E09-D07 local icons`) and let board 01 create the band page by name.
