"""Board 06 `E47-D08 / 06 heatmap-tiers` (dark): §7 — a heatmap of 100 ms columns in the three tiers. full: the trail's
age-based fade (I-20; FALLBACKS trail: one ramp step dimmer per AGE_STEP older columns); canvas calm and reduced:
instant, intensity at true size, no age fade. The live column's held cell (I-21) is the same in every tier: its drawn
step crosses at most FR-6 times per 1 000 ms while the readout carries the true size (R-4). Sizes: TICKS' mulberry32
on per-column seeds (synthetic)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FOCUS_SYMBOL, START, fmt, k, nb, seeded  # noqa: E402

NN = 6
COLS, ROWS, CW, CH = 32, 14, 28, 28
AGE_STEP = 6  # columns per fade step (kit choice: the trail has no hi-fi spec, D08-G1)
LIVE_ROW = 9
I20 = next(r for r in k.INV if r.i == "I-20")
I21 = next(r for r in k.INV if r.i == "I-21")


def size(col: int, row: int) -> int:
    return seeded(600 + col, ROWS, 0, 100)[row]


def step(sz: int) -> int:
    return 0 if sz < 10 else min(5, 1 + (sz - 10) // 18)


def live_series() -> tuple[list[int], list[int]]:
    """The live cell's true step per 100 ms refresh over the last 1 000 ms, and the drawn step held to FR-6."""
    true = [step(seeded(700 + i, 1, 0, 100)[0]) for i in range(k.WINDOW_MS // k.HEAT_MS)]
    drawn, last_t, cur = [], -k.fr_ms("FR-6"), None
    for i, s in enumerate(true):
        t = i * k.HEAT_MS
        if cur is None or (s != cur and t - last_t >= k.fr_ms("FR-6")):
            cur, last_t = s, t
        drawn.append(cur)
    return true, drawn


def crossings(xs: list[int]) -> int:
    return sum(1 for a, b in zip(xs, xs[1:]) if a != b)


def heatmap(tier: str) -> k.Node:
    k.fallback("trail")
    kids = []
    true, drawn = live_series()
    for c in range(COLS):
        age = COLS - 1 - c
        col: list[k.Node] = []
        for r in range(ROWS):
            st = step(size(c, r))
            if c == COLS - 1 and r == LIVE_ROW:
                st = drawn[-1]
            elif tier == "full":
                st = max(st - age // AGE_STEP, 0)
            fill_ = k.HM_ZERO if st == 0 else k.HM[st]
            col.append(k.rect(f"cell {r}", CW - 1, CH - 1, fill_, x=0, y=r * CH))
        kids.append(k.box(f"column {c}", col, None, w=CW, h=ROWS * CH, x=c * CW, y=0))
    k.fallback("markers")
    kids.append(k.rect("live cell · outline", CW + 3, CH + 3, None, {"stroke": k.MARK_FILL, "strokeWidth": k.THICK,
                                                                       "strokeAlign": "inner"},
                       x=(COLS - 1) * CW - 2, y=LIVE_ROW * CH - 2))
    return k.box("plot · heatmap", kids, {"fill": k.CANVAS}, w=COLS * CW, h=ROWS * CH,
                 note=f"{COLS} columns of {k.HEAT_MS} ms ({nb(COLS * k.HEAT_MS)} ms), {ROWS} price levels; tier {tier}")


def build_frame(tier: str) -> tuple[k.Node, list[str]]:
    fid = k.BOARDS[NN].frames[k.TIERS.index(tier)]
    hm = heatmap(tier)
    levels = [k.text(f"level {r}", fmt(START + ROWS // 2 - r), k.NUM_SM, k.AXIS, x=COLS * CW + 8, y=r * CH + 4)
              for r in range(0, ROWS, 3)]
    ages = [k.text(f"age {c}", ("now" if c == COLS - 1 else f"−{(COLS - 1 - c) * k.HEAT_MS / 1000:.1f} s"), k.CAPTION,
                   k.AXIS, x=c * CW, y=ROWS * CH + 4) for c in range(0, COLS - 4, 6)] + [
        k.text("age now", "now", k.CAPTION, k.AXIS, x=(COLS - 1) * CW - 4, y=ROWS * CH + 4)]
    plot = k.box("heatmap + axes", [hm, *levels, *ages], None, w=COLS * CW + 80, h=ROWS * CH + 20)
    body = k.box("body", [dict(plot, x=8, y=8)], {"fill": k.CANVAS}, w=COLS * CW + 96, h=ROWS * CH + 36)
    pnl = k.panel(f"CMP-080 panel · heatmap {FOCUS_SYMBOL}", f"Heatmap · {FOCUS_SYMBOL} · {k.HEAT_MS} ms columns",
                  body, COLS * CW + 96, ROWS * CH + 36 + k.HEADER_H)
    true, drawn = live_series()
    cols = (k.Col("lab", "t (ms)", 96), *(k.Col(f"r{i}", f"{i * k.HEAT_MS}", 40, True) for i in range(len(true))))
    t_row = k.table_row(cols, {"lab": "true step", **{f"r{i}": str(s) for i, s in enumerate(true)}}, "row 1", 1)
    d_row = k.table_row(cols, {"lab": "drawn step", **{f"r{i}": str(s) for i, s in enumerate(drawn)}}, "row 2", 2)
    held = k.vbox("live cell", [
        k.text("title", f"The live column's held cell (I-21), last {nb(k.WINDOW_MS)} ms: true step "
                        f"{crossings(true)} crossings, drawn {crossings(drawn)} (FR-6: ≤ "
                        f"{k.FR['FR-6']['value']})", k.LABEL, k.TEXT_1, w=520),
        k.table("CMP-049 grid · live cell", None, k.header_row(cols), [t_row, d_row]),
        k.text("readout", f"Readout: true size {seeded(700 + len(true) - 1, 1, 0, 100)[0]} (steps from the ramp; the table and the "
                          "readout get the true size at once, R-4)", k.CAPTION, k.TEXT_2, w=520)],
        {"gap": k.STACK_SM}, w=520)
    head = k.text("tier", {"full": "Effective tier full: the trail fades with age (I-20)",
                           "canvas-calm": "Canvas calm: decay instant — intensity at true size, no age fade",
                           "reduced": "Reduced: decay instant — intensity at true size, no age fade"}[tier],
                  k.HEADING_SM, k.TEXT_1)
    content = k.vbox("workspace", [head, pnl, held], {"gap": k.STACK_MD, "pad": k.INSET_LG}, w=k.MAIN_W, h=k.BODY_H)
    lines = [f"I-20 {tier} (§3 L{I20.line}): {I20.tier(tier)}",
             f"I-21 (§3 L{I21.line}), every tier: {I21.full}; FR-6 = {k.FR['FR-6']['value']} (§4.1 "
             f"L{k.FR['FR-6']['line']})",
             f"Columns every {k.HEAT_MS} ms (§3 I-20's trigger); cell sizes TICKS mulberry32 seeds 600–{600 + COLS - 1}, "
             f"live cell seeds 700–{700 + len(true) - 1} (synthetic)"]
    if tier == "full":
        lines.append(f"Fade drawn one ramp step dimmer per {AGE_STEP} columns of age (FALLBACKS trail; the trail's "
                     "own motion spec is E21-D05's, D08-G1)")
    return k.window(fid, content, note=f"§7; tier {tier}"), lines


def main() -> None:
    frames, blocks = [], []
    for tier in k.TIERS:
        fr, lines = build_frame(tier)
        frames.append(fr)
        blocks.append((k.BOARDS[NN].frames[len(frames) - 1], lines))
    p, md, pk = k.build(NN, frames, blocks, per_row=3, board_lines=[
        f"Bubbles (I-22) never flash and are not drawn here (§7 L{k.L('## 7. Heatmap, bubbles and replay') + 4})"])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
