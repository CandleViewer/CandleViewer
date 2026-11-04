# E19-D05 (#500) board kit: build notes

Offline cvsheet v4 sheets for the ten §0 boards of `docs/design/E19/E19-D05.md` (file `E19-D05 boards`, page
`E19-D05`; BQ-13 RULED: ACCEPT). No Penpot, no network. In a checkout the kit sits at
`docs/design/_tools/sheets/e19-d05/` (raw sheets and their `.md` to `build/`, packed sheets to `v4/`); outside one it
needs `CV_REPO` naming a checkout and writes to the sibling `E19-D05-cap/` and `E19-D05-v4/` folders.

## Sources (md5-pinned in `DOCS`; the kit refuses drifted bytes)

- The spec, by repo-relative path in this checkout only (md5 `5f60e801`, the text with §0 and §16 recording the
  boards as drawn). §0's board table and not-drawn line,
  §2's motion table, §3's matrix, §4.1 / §4.2's tables, §8.1's flash table and §8.3's copy deck are parsed, never
  typed; every drawn word passes `k.S` (verbatim in the spec, D03 or D02, markdown marks dropped) or is a `copy_gap`
  note naming its source. No hand-off file exists (BQ-1), so there is no hand-off pin.
- D03 (`docs/design/E19/E19-D03.md`, md5 `928db4e4`) at `35032f521` (PR #5517 head, not merged yet) and D02 (`E19-D02.md`, md5 `1299df3b`) at
  `3619e95c5` (the #5487 merge commit, bytes equal to the earlier pin), read with `git show` when the checkout lacks them.
  Re-pin D03 to its merge commit when #5517 merges.
- PRIM (`packages/ui/tokens/primitives.tokens.json`, md5 `b5e47569`): `motion.duration.*` and `motion.easing.*` only.
- The recorded instrument fixture: BTCUSDT's tick size 0.10 and qty step 0.001, nothing else.
- Tools: the checkout's `docs/design/_tools/sheets/tools/` (validator with `components.offline.json` and the default
  `token-sync.json`, `compact.py`, `mkcall4.py`) and `docs/design/_tools/contrast_check.py` (`relative_luminance()`
  for §8.1's re-derivation). No local token rows: every sheet validates with the default tokens.

## Build

```sh
cd docs/design/_tools/sheets/e19-d05                  # in a checkout; outside one, export CV_REPO=<checkout>
python3 -X utf8 -I -B e19d05kit.py selftest            # OK: 0 failures
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py             # OK: 0 findings
```

A rebuild is byte-identical (seed 500; checked: every raw sheet, `.md` and packed sheet hashes equal across two runs).
After the ruling or any text fold: re-pin the spec md5 (and commit) in `DOCS`, rebuild, re-run the self-test and
`check_all.py`. Cites (`§0 L…`, `L…`) and every table are looked up, so a moved line or a reworded cell flows through;
a reworded string a board quotes with `k.S` stops the build at that string (re-read it, then change the call).

## Layout

| File              | What                                                                                                                                  |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `e19d05kit.py`    | sources, §0 parse, spec tables, copy decks, motion maths (PRIM easings), the world and scenarios, node builders, sheet I/O, self-test |
| `gen/frames.py`   | the crop (docked CMP-183 at one key frame), the overlay crop, strips, timelines, tables, one builder per frame                        |
| `gen/registry.py` | frame id -> builder; `build_board(nn)`                                                                                                |
| `gen/gen_NN.py`   | one generator per board                                                                                                               |
| `check_all.py`    | the scan (validator, mkcall4 count, sha256, node rules, captions, cells, overflow, overlap, pins)                                     |

## The synthetic world (declared on every board; seed 500)

BTCUSDT 30-minute bars 11 Oct 00:00 – 31 Oct 14:30 UTC (the bar in progress), one upward walk (140 USDT a day) so
most earlier POCs stay naked; volume on a 10-tick grain (1-tick rows split it, seeded per bucket). Live updates from
U0 = 31 Oct 14:41:00 UTC at the 1 000 ms default throttle. Profiles follow `24`: POC tie-break chain, the single-step
value area at 70 %. Scenarios (each derived, the self-test checks the claim): a 3-row POC jump (a seeded print run
just big enough) then a 1-row move; the 30 Oct session's last developing recompute (as of 23:59) and its close; the
U0 -> U1 prints at the 120-row (10-tick) and 5 000-row (1-tick, 28 merged) arms with the scale maximum unchanged; a
minute of prints one row under VAL that moves the developing area; HS-1 on two tied levels at 250 ms; re-bucket
100 -> 50 ticks and Session -> Fixed range (240 min) with the result at 600 ms; a time pan of the 24 visible bars at
10 Hz with a 100 ms debounce; 8 naked POCs of 20 sessions, the nearest 5 drawn, 26 Oct's retested at the 15:00 close
(3 -> 2 hidden); the region rule simulated for three runs.

## Kit readings (each is a `readings` note on the boards that use it)

- **R-K1 (export path).** §0 names no export path; the kit takes the merged motion specs' form
  `docs/design/E19/img/E19-D05-NN-<slug>.png` (E08-D11 §0).
- **R-K2 (mixed twins).** Boards 02, 03, 09 are "dark + light twin" boards holding a `-dark` and a `-light` frame; a
  board renders under one theme set, so each is exported under the light set as §0's name and again under the dark
  set as `…-dark.png` (E19-D03's R-K1). The `.md` line 3 says `theme light.` for them.
- **R-K3 (the trace lane).** §5.1's 4 px band "in the rail's lane" that "never covers a bar": D03's rail is
  full-width, so the lane is the first 4 px of the price gutter, from the previous POC row to the new one.
- **R-K4 (developing edge).** The developing bracket's open edge is the VA edge on the last price's side (D03 kit).
- **R-K5 (W-19 singular).** D02 W-19 has no singular: the 1-tick arm reads "Row size: 1 ticks (0.1)".
- **R-K6 (overlay DOM).** The overlay's legend row mounts in frame 0 as a cut; only the canvas uniform eases.
- **R-K7 ("(pressed)").** Marks D03 W-6's aria-pressed state on the board.
- **Announcements (BQ-7 ruling).** A re-bucket or period change says only the action's D02 word once ("Profile settings applied.", "Period: {mode}") and its end is silent; D05 W-2 ("Recalculating") is the composite progress bar's name, never announced, and its frame is not drawn (§0). The busy bar shows after 300 ms (§6.1). The old W-2a is gone.
- **Opacity stand-in (FALLBACKS alpha).** The renderer binds opacity only to a token and no token carries a key frame's
  value (R-3 adds none): 1 is solid, 0 absent, between is the shape's 1 px outline with the computed value in the
  caption (accelerate at the middle: 0.372 progress; decelerate: 0.890).
- **Strip form.** §0: frame 0, the middle and the end, the reduce strip beneath. A row that is a cut in every mode
  draws its normal strip once and states the reduce strip in words (the nodes are the same, R-6).
- **Crop.** A key frame is a 280 px crop of the docked panel (header strip, plot, legend words); D03's controls rows
  are unchanged by this spec and not repeated. The 120 / 5 000-row arms use a 360 px plot.

## Not drawn: the down forms

No board has a POC-down case in a legend or an announcement. D05 W-1's down form and D05 W-1b's down form are declared under "Not drawn — the text is binding" in the annotation and the readings of boards 02, 05 (W-1 down is quoted in its intro only) and 10 (W-1b only); see `gen/registry.py`.

## Live-check fold (the drawing lane's record, 2026-11-03)

The ten boards were drawn and exported in one round; the record carried two geometry fix lines, both folded here.

- **Root heights.** Each root is max(annotation end, footer end) + 80 px as read back: 934, 1 958, 1 502, 1 534,
  1 038, 1 886, 1 054, 2 998, 1 302, 918 for 01–10 (`LIVE_ROOT_H`; the estimate ran 18 px over on each). The kit
  refuses a height that leaves less than 80 px under the footer.
- **Board 09's header row.** The §3 table's column (c) header wraps to two lines (27 px) in a 24 px row:
  `header_row` now sizes the row from its tallest wrapped header cell (+ 4 px a side, rounded up to 8 px), so 40 px,
  the table 280 px and the load marker at y 419. The frames keep their drawn 512 px (`LIVE_FRAME_H` in
  `gen/frames.py`; sized from the content they would grow to 528), so the marker ends 8 px above the frame's edge.
- **The down-form cite.** The declaration on boards 02, 05 and 10 drew "§8.3 Lspec L418"; `gen/registry.py` now
  writes "§8.3 L418" (text only, a drawn deviation in the spec's §16).

A rebuild reproduces the drawn sheets node for node but for those values (checked by a geometry diff against the
drawn set); the sheet notes also name the spec's new md5.
