# E08-D10 board kit: build notes (#178, the boards leg; offline, no Penpot)

Kit `e08d10kit.py`, frame builders `gen/frames.py`, one generator per board `gen/gen_NN.py`, scan `check_all.py`.
Sheets: `build/NN-<slug>.json` with their `.md` (the render drivers' set; untracked), the `.md` also beside the kit,
packed `v4/NN-<slug>.json` (`compactOf.file` the bare raw-sheet name, its sha256 the raw sheet's). `BUILD.md` says how
to rebuild them.

## Sources (md5-pinned; the kit refuses drifted bytes)

- Spec and hand-off read from this checkout by repo-relative path, `docs/design/E08/E08-D10.md` and
  `E08-D10-handoff.md`, md5-pinned in `DOCS`. The boards draw the ruled text (BQ-11: no minimum display, T-3 is the
  cut; BQ-10: `no_matches`; BQ-2: the light variants beyond board 08 are text only). §0's as-built record was written
  in place, line for line, so every `L<n>` cite on the boards holds; the pins were then moved to the final bytes.
- Cited siblings read from this checkout, md5-pinned: E11-D04 (header labels, "0 bars loaded"), E22-D02 (tape
  columns, side words), E22-D03 ("Tape BTCUSDT"), E08-D02 (the two superseded strings), E08-D04 ("Stale 4s"), the
  instrument fixture (BTCUSDT tickSize 0.10 only).

## Pipeline

1. `python3 -I -B e08d10kit.py selftest` -> "OK: 0 failures" (one sample frame, validated, md, packed).
2. `for n in 01 02 03 04 05 06 07 08 09; do python3 -I -B gen/gen_$n.py; done`: each builds its §H frames with
   `frames.BUILDERS[<id without theme>]`, writes the raw sheet (validator `--components` + `--tokens` exit 0, kit
   lint, banned scan), the md (line 3 = the render line) and the packed sheet (mkcall4 `count` agrees).
3. `python3 -I -B check_all.py` -> "OK: 0 findings" (validator, mkcall4, 0 inst, local icons, no boolean wrap, no
   "/" in names, captions, 8 px cells, overflow and overlap by estimate, one n per frame, md5 pin, compactOf).
   The build is deterministic (seed 178, one clock): a rebuild gives byte-identical sheets.

## Live-check fold

The live check's two SHEET-FIX lines are folded in, so a rebuild reproduces the boards as drawn:

- every root's h is the measured max(annotation end, footer end) + 80 (`k.MEASURED_H`): 01-03 1878 (the estimate
  was 1880), 04-07 and 09 998 (1000), 08 1129 (1208);
- board 07's redline 01 specimen slot is 44 px (`frames.SLOT_MEASURED_H`; the estimate 43 cut W-2 by 1 px).

Against the sheets that were rendered, the rebuilt raw sheets differ only in those values and in their notes (the
sources line's md5 pins and the live-check lines that quote the root size).

## File, page, grid, names

- File `E08-D10 boards`; page `E08-D10 SCR-151 empty and backfill states` (§0, parsed). Roots are §0's names
  exactly ("E08-D10 / 01 backfill-in-progress"; no "/" after the prefix), at x = ((NN-1) mod 5) x 6000,
  y = floor((NN-1)/5) x 3200, fill `color.surface.app`, clip, hugging the frames + ONE 400 px annotation column + 80.
- Frames 1280 x 800, 80 px gutters, 2 x 2 for four frames, a row otherwise. Frame names are §H's ids with U+2215 for
  every "/": `SCR-151∕throttled∕in-context · dark`; the caption 28 px above reads `state: SCR-151/throttled/in-context
· dark`. Under the frames: "Data: a seeded synthetic history (seed 178), not recorded" (§H).
- Exports `docs/design/E08/img/E08-D10-NN-<slug>.png`; md line 3 `theme dark.` (01-07), `theme light.` (08),
  `theme hc.` (09). Twins are token-bound: the theme is set at export.

## The window and the host panels

E08-D09's chrome geometry (TopBar 48, NavRail 64, main 976 x 704, RightRail 240, StatusBar 48) as neutral
placeholders; main holds one host panel 944 x 672 at (16, 16), compact density (rows and controls 24 px). The
generic E08 history panel (§H): title "Bars BTCUSDT 5 minutes" (§10.1's naming example), the header's status slot
(wraps to a second line, never truncates), the column header row (E11-D04's `time · open · high · low · close ·
volume`), the newest rows oldest-first, the caption "{n} bars loaded". SCR-053 (board 02 / 08 `throttled/in-context`
only): "Tape BTCUSDT", Time · Price · Size · Notional · Side (taker). R-7's mark "PROPOSED fields (D10-G1), not
shipped" sits in the StatusBar of every frame built on D10-G1's fields (boards 01, 02, 05, 08 per §H).

## The world (derived, never typed twice)

5-minute bars; the latest opens 2026-08-23 10:35 UTC; target m = 17 days x 288 = 4 896 (W-3 "about 4 896"; the
deck's 5 000 is illustrative); in-context n = 3 200, which reaches 2026-08-12 (the deck's own date, so W-4 / W-7
read as written); full-panel n = 1 600 (to 2026-08-17). Prices at the fixture's tick (1 decimal), grouped with a
space like the deck. Holes: kline hole 09:30-10:00 (6 bars) on gap/hole-row and the twins; recording gap
08:50-09:05 (3 bars, 15 min, "connection lost") on gap/both. Bar fill = round(432 x n / m). Every derivation is in
the sheet's `notes.derivations` and the md.

## Boards (frames per §H)

| #   | Frames | Content                                                                                         |
| --- | ------ | ----------------------------------------------------------------------------------------------- |
| 01  | 4      | known target (CMP-023 + W-3), open target (CMP-038 + W-4), in context (chip + W-3), the cut     |
| 02  | 4      | SCR-053 throttled (W-6, W-7, W-9), long wait, give-up (W-8 + Retry), Owner and Manager sessions |
| 03  | 4      | gapped chip (W-12), hole row (W-13 + Show coverage), both (W-12 + W-14), gapped vs stale        |
| 04  | 2      | W-10 / W-11 block (D02's strings superseded, in the annotations), §5.2's exemplar table         |
| 05  | 3      | timeline diagrams of T-1 / T-2 / T-3 / T-4 / T-7 over the panel at that moment                  |
| 06  | 3      | focus order (Partial chip focused, numbered stops), Retry focus to the title, §10.2's rows      |
| 07  | 1      | §11's eleven pairs as callouts on specimens of boards 01-03                                     |
| 08  | 3      | light twin: throttled/in-context, gap/hole-row, backfill/known-target (same builders)           |
| 09  | 2      | hc twin: backfill/known-target, gap/hole-row                                                    |

## Readings and ambiguities (recorded for review)

1. Full panel with progress: §3 shows the block "with no row loaded yet" yet with a bar and W-3; drawn with n = 1 600
   of this episode while the panel's own window holds no row (a bar at 0 would show no fill to measure, §11).
2. W-7 on SCR-053 says "bars" though the tape lists prints: drawn verbatim (the ruled key).
3. `throttled/owner-vs-manager` ("beside", §0): two sessions stacked in one window, each a 944 x 308 panel with a
   role label (the one frame that holds two panels).
4. `throttled/gave-up` in context: the failed hole is older than the loaded rows, so no separator row is on screen;
   the full-panel give-up (W-18, Retry first, focus to the heading) is annotated on `a11y/retry-focus`, not drawn.
5. Glyphs: the backfilling chip and the CMP-026 blocks use the local `pending`; the gapped chip its 8 px indicator
   dot; CMP-038's spinner an ellipse outline (no spinner icon); recording-not-started's calendar is not local.
6. Strings the deck lacks (all in `notes.copy_gaps` with their source line): the R-7 mark, the data footer, the
   column headers, "{n} bars loaded", "Owner" / "Manager", the focus-stop labels, "visually hidden", the hidden
   panel name "Bars BTCUSDT 5 minutes · Stale 4s".
7. Board 05's timelines and board 06's focus strip and hidden strings are board markers on the frame's face (named
   "board marker" / "board diagram" in their notes), not product UI.
