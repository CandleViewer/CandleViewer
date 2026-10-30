"""E12-D07 board 08 `reflow-200` (dark): §0 L62 — the tick set at 640 CSS px (200 %): the stacked block with close
time and duration (§5 L193). Frame (hand-off §H L103): reflow/tick-200, the 1280 x 800 window at 200 % drawn as
640 x 400 CSS px, the chart panel maximised (D04E11:214 step 3, no hint when maximised); export at 2x (A-6).
Writes build/08-reflow-200.json (validated), 08-reflow-200.md beside the kit, and packs v4/.
Usage: python3 -I -B gen/gen_08.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pair2_helpers as h  # noqa: E402

k = h.k
NN = 8
MODE = "tick"


def fit_blocks(rows_all: list, i0: int, w: int, room: int, focus_k: int) -> tuple[list, list, str]:
    """As many stacked blocks as fit the table room under the caption (whole blocks only; table() raises otherwise)."""
    best = None
    for n in range(1, 8):
        sel = rows_all[i0:i0 + n]
        cap = k.caption_text(sel, MODE, loaded=len(rows_all), durations=True)
        blocks = [k.stacked_block(b, MODE, i + 1, w=w - 16, focused=b.t == k.SWEEP_AT and b.k == focus_k)
                  for i, b in enumerate(sel)]
        try:
            t = k.table(blocks, w=w, h=room, caption_chars=cap, header=None, footer=k.footer_row(w - 16))
        except ValueError:
            break
        best = (sel, t, cap)
    if best is None:
        raise RuntimeError("no stacked block fits")
    return best


def build() -> tuple[list[dict], dict]:
    fid = k.BOARDS[NN].frames[0]
    w, hgt = k.ZOOM_W, k.ZOOM_H
    rows_all = k.series(MODE)
    i_sweep = next(j for j, b in enumerate(rows_all) if b.t == k.SWEEP_AT)
    sel, t, cap = fit_blocks(rows_all, i_sweep + 3, w, hgt - k.PANEL_ROWS, 5)  # bar 4 of 5, then bar 5 of 5 (focused)
    fr = k.window_maximised(fid, k.panel(MODE, t, w=w, h=hgt))
    focus = next(b for b in sel if b.k == 5)
    cols = k.shown_columns(MODE, auto=True)
    blk = (k.frame_name(fid), [
        f"Frame: {k.frame_name(fid)}",
        "State: reflow/tick-200: tick's primary set (833.8 CSS px, §5 L186) does not fit the 640 CSS px of a maximised "
        "panel at 200 % (§5 L193, “stacked”), so each row takes E11-D04's stacked reflow (D04E11:214 step 3); "
        "maximised, so no “Maximise the panel” hint",
        f"Mode: {MODE} ({k.SHORT[MODE]}) · chart type: candle",
        "Columns (as stacked lines, §5 L193): heading = row header + `state`; open / high / low / close 2 × 2; "
        "`close time` and `duration` on one line under OHLC; volume, delta, `trades` on one line — " +
        k.columns_line(cols, MODE),
        f"Row header: {k.row_header(focus, MODE)} (§2.2 L113) — name: {k.row_name(focus, MODE)} (§2.2 L116)",
        "Keyboard and focus: as board 02 (D04E11:129); one <tr> per bar, ↑ / ↓ move block to block; ring on block "
        f"{sel.index(focus) + 1:02d} ({k.row_header(focus, MODE)}), 2 px color.focus.ring, aria-current",
        "Announcement: Data table, row k of N (D04E11:115 D2)",
        "Copy: " + " · ".join(f"{c} “{k.COPY[c][0]}” (L{k.COPY[c][1]})" for c in ("W-10", "W-11")),
        f"Blocks: {len(sel)} ({', '.join(k.row_header(b, MODE) for b in sel)}); every value of the tick row kept "
        "(hand-off §E L64)",
        "Size: 640 × 400 CSS px = 1280 × 800 device px at 200 %; export the board at 2x (A-6)",
        "Tokens: " + ", ".join(k.frame_tokens(fr)) + "; buy / sell text falls back (A-12)",
    ])
    for c in ("W-10", "W-11"):
        k.copy(c)
    ann = k.annotations(NN, [blk], board_lines=[
        "One frame (§H L103): the 1280 × 800 window at 200 %, the chart panel maximised (F11, D04E11 §5.2), the "
        "table open in place, compact; seeded data (A-8)"])
    k.live(f"frame {k.frame_name(fid)!r}: block {sel.index(focus) + 1:02d} reads {k.row_header(focus, MODE)!r} and its `state` “—”; its "
           "stroke is 2 px color.focus.ring (inner); each block shows open, high, low, close, close time, duration, "
           "volume, delta, trades")
    k.live(f"frame {k.frame_name(fid)!r}: no block is cut at the table's bottom edge after relayout ({len(sel)} "
           "blocks, then the footer)")
    notes = {"spec_gaps": [
        "A-2: bars 1–4 of 5 close at their open millisecond (duration 0:00.0) under §2.2 L114's rule; the focused "
        "bar 5 of 5 carries a non-zero duration; L116's example string is not drawn",
        "A-6: no token scales type 2×; the frame is drawn in CSS px (640 × 400) and exported at 2x",
        "A-8: seeded synthetic stream; tick size and qty step from the recorded instrument fixture",
        "A-12: buy / sell text tokens unregistered: color.buy.default / color.sell.default, the sign carries it"]}
    return [fr], {"ann": ann, "notes": notes}


def main() -> int:
    frames, rest = build()
    p = k.write_sheet(NN, frames, rest["ann"], notes=rest["notes"])
    k.write_md(NN, p, frames_info=[
        "reflow/tick-200: tick, maximised panel 640 × 400 CSS px, stacked blocks (spec §5 L186, L193; E11-D04 :214)",
        "Walkthrough (hand-off §E L64): at 200 % the stacked block keeps every value of the tick row",
        "Copy: W-10 (spec L332), W-11 (L333); theme dark; export docs/design/E12/img/E12-D07-08-reflow-200.png at 2x"])
    v4 = k.pack_sheet(p)
    print(p, v4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
