# E47-D09 board kit: build notes

Ticket #1308 (E47-D09, keyboard operability): ten cvsheet v4.3 sheets for the per-set Penpot file `E47-D09 boards`,
page `E47-D09` (spec §0), built offline. No Penpot, no network. Synthetic data only (seed 1308, BTCUSDT, tick 0.10
from the recorded fixture), declared on every board's face. The rulings of record (BQ-0 … BQ-15) and the design read
apply.

## Build

In a checkout the kit sits at `docs/design/_tools/sheets/e47-d09/` (raw sheets to `build/`, packed to `v4/`);
anywhere else set `CV_CHECKOUT` to a checkout (raw sheets + `.md` to `../E47-D09-cap/`, packed to `../E47-D09-v4/`).

```sh
python3 -X utf8 -I -B e47d09kit.py selftest         # OK: 0 failures
for n in 01 02 03 04 05 06 07 08 09 10; do python3 -X utf8 -I -B gen/gen_$n.py; done
python3 -X utf8 -I -B check_all.py                  # all ten twice (byte-identical), then the scans
```

A rebuild is byte-identical (raw sheets, packed sheets and `.md`). Each packed sheet's `compactOf` is the bare raw
name and the raw sheet's sha256.

## Sources (md5-pinned in `DOCS`; the kit refuses drifted bytes)

- Spec `docs/design/E47/E47-D09.md` and hand-off `E47-D09-handoff.md` as committed with the boards (the text head
  was `260bb0caf`; the boards PR edits §0 in place and appends §21, every cited line where it was): §0 boards, §1.4
  K-rules, §3 DE rows, §4, §7–§13, §16 copy deck, §19 C / G rows, the COUNT slots; the hand-off's §H frames, §E, §G.
- The registry `apps/web/src/keymap/keymap.json` and `reserved-keys.json`, read with `git show` at the base the
  spec's "Inputs pinned" line names (`4c662fd5b`), as the spec cites them (main's `keymap.json` has moved on since).
- `packages/fixtures/bybit/2026-10-05/rest/instruments_before.json`: BTCUSDT's tick size only (0.10).

Layout: `e47d09kit.py` (registries, tokens, node primitives, E47-D04's ring / shell / tables / annotation column /
packer, the world, write / md / pack, self-test); `gen/common.py` (Kbd, the seeded chart, the trading workspace,
the settings chrome after E47-D03's SCR-116 / SCR-117); `gen/gen_01..10.py`. Twins: 02 = 01's `build("light")`,
06 / 10 = 05's `build("light" / "hc")`.

## Boards

| Board               | Frames | Root w × h  | Theme | Sections |
| ------------------- | ------ | ----------- | ----- | -------- |
| 01 order-line       | 5      | 4640 × 1878 | dark  | 91       |
| 02 order-line-light | 5      | 4640 × 1878 | light | 91       |
| 03 anchors          | 3      | 4640 × 1008 | dark  | 48       |
| 04 node-move        | 5      | 4640 × 1878 | dark  | 56       |
| 05 palette          | 4      | 3280 × 1878 | dark  | 33       |
| 06 palette-light    | 4      | 3280 × 1878 | light | 33       |
| 07 cheatsheet       | 4      | 3280 × 1878 | dark  | 62       |
| 08 hotkey-editor    | 5      | 4640 × 1878 | dark  | 65       |
| 09 inert            | 2      | 3280 × 998  | dark  | 17       |
| 10 palette-hc       | 4      | 3280 × 1878 | hc    | 33       |

Root heights are the live-measured ones (`MEASURED_H`, the live-check fold below).

## The world (seed 1308; every number derived)

60 seeded 1-minute BTCUSDT bars (13:00–13:59 UTC on the fixture's date) ending at the mark 67,420.00; a long 0.250 at
entry mark − 15 ticks, SL mark − 40, TP mark + 45. Board 01: `↑` ×5 → SL + 5 ticks (pending); `Shift+↑` ×5 → SL + 50
ticks, at or above the mark = the wrong side (`11`:3056-3057). Board 03: a Rectangle over bars 18–40 (the range's
high and low), anchor 2 nudged 3 ticks; a volume profile over bars 30–44 in 5-tick rows (seeded volumes; POC and the
70 % value area computed), the end moved 3 bars pending. Board 04: `14` SCR-082's "ATR trail 2x" graph on a 24 px
grid. Keymap profile: positions.close_all → Ctrl+Shift+F, ticket.reduce_only → Alt+R, replay.bookmark → Ctrl+B,
dom.centre_mark unbound (the self-test checks none is reserved or clashes); Reset all's count (W-17) = 4.

## Readings taken (ambiguities settled)

1. §H frame names use U+2215 for "/"; twin rows "the frames of NN · theme" expand from board NN.
2. W-1 / W-2's {object} = "Stop-loss" (the SCR-063 row word); the select announcement is built from §4's cell.
3. The "readout that follows" (§2) = the line's price tag on the axis; the line label carries the word "pending";
   dashed = 8 px segments (no dashed stroke in the renderer).
4. W-19 and W-20 share board 01's one refused frame (§H names both): W-20's case is drawn, W-19 a second callout.
5. The confirm dialog's words ("Amend stop-loss", Cancel, Confirm) are copy gaps (E31-D01's drop confirm); its
   initial focus is E47-D04's contract and not redrawn.
6. Board 03's drawing is a Rectangle (two anchors); the profile is a personalised-range overlay; the pending range
   end is a dashed vertical with "pending", the rows redraw only on Enter.
7. D09-G6: one layout step = one 24 px cell; W-15's column / row count from the canvas origin.
8. The 200 % insets follow E47-D03 board 05: two 640 CSS px strips at 1:1 (text 100 % and the 150 % text scale, its
   type-150 mapping), the 400 px fold marked.
9. Valid here = context active in SCR-020's trading workspace + validWhen holds; Replay rows are the invalid-here
   example; every registry row sits in E10-D03's "Action" group.
10. Palette T2 = a Viewer (E10-D03's "lee") with rbac.permission "Your role can't change positions." (D09E09:89 with
    D03E10:281's verb; copy gap); per-row reasons as E10-D03 draws them.
11. W-9 drawn in PCOPY:39's form with the query; the suggestion is PCOPY:40's shipped line (copy gap).
12. W-23 has no singular: "1 shortcuts match" drawn as the deck gives it (spec gap, E47-D07's words).
13. The cheatsheet is 880 px wide; the remapped frame is scrolled so Positions and Replay (two remaps) are in view.
14. SCR-113: every frame works on positions.close_all; conflict key Ctrl+Shift+A (Global's account picker), reserved
    key Ctrl+Shift+I; RL-1's held Save is an ordinary button (form validity, never T2) and the key field's
    aria-invalid is a 2 px danger edge plus words; RL-5's caution note words are a copy gap (placeholder lines).
15. Board 09: AC5's case is ticket.submit (Ctrl+Enter) in the journal; W-6's {contexts} = "Ticket"; the tone word
    "Info" is E10-D03 §7's (copy gap).

## Live-check fold

The drawing lane's sixteen SHEET-FIX lines are handled, so a rebuild reproduces the boards as drawn (spec §21); the
geometry is folded in, the repaints are a drawing step:

- root heights are the checked `want` (`k.MEASURED_H`): 1878 on 01, 02, 04–08 and 10 (the footer's one-line data
  statement measured 14 px against the 16 px estimate), 1008 on 03 (the annotation column end 928 + 80), 998 on 09;
- the price axis's edge labels are clamped inside the 412 px axis (`common.AXIS_LABEL_H`, 12 px): the bottom label
  `axis 67,415.00` sits at y 400, not 405, in every chart frame of 01, 02 and 03, as an engine clamps it;
- board 01 / 02's `CMP-044 confirm · amend` is centred on its measured 480 × 183 (`k.MEASURED_MODAL`; y 309, was
  310);
- board 04's `tag · fold` in the 200 % frame sits at x 440 (was 16), clear of the `position_side == long` node;
- boards 05, 06 and 10's `tag · the session` sits at x 620 in the TopBar gap (was 980, over FLATTEN ALL and FREEZE);
- board 09's strip tags and annotation state the measured toasts (`MEASURED_TOAST`): 71 px, one line at text
  100 %; 100 px, two lines at 150 % (the toast 29 px taller); the strips keep the drawn placement;
- the modal live check is narrowed: a dialog with no placement is re-centred on both axes; the CMP-059 palette
  (top-anchored at y 64) is re-centred horizontally only, never vertically; the CMP-094 cheatsheet is kept at
  (48, 56), where the sheet places it at the frame's left.

Board 04 keeps five texts clipped by the scrolled rule canvas on purpose (`lc3.cutN` 5): `position_side == long` in
`node∕view-follows` ("view scrolled 5 cells right") and `modify_stop`'s name and kind at the 640 CSS px edge of both
200 % strips. The texts of the first frame drawn after a tab reload (01, 02, 03, 05, 07, 08 and 10) were set again
live; that is a drawing step, not a kit change.
