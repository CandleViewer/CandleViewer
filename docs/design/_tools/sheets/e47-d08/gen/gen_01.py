"""Board 01 `E47-D08 / 01 inventory-map` (dark): §3 as a surface × tier map — one frame per effective tier (§2), every
§3 row a cell holding that tier's variant verbatim, so no surface is blank in any tier."""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k  # noqa: E402

NN = 1
COLS = 4
COL_GAP = 8
INNER_W = k.FRAME_W - 2 * k.PX[k.INSET_XL]
COL_W = (INNER_W - (COLS - 1) * COL_GAP) // COLS  # 302
TXT_W = COL_W - 2 * k.PX[k.INSET_XS]
TIER_KEY = {"full": "full", "canvas-calm": "canvas calm", "reduced": "reduced"}  # §H word -> §2's tier name


def inv_cell(r: k.Inv, tier: str) -> k.Node:
    v = r.tier(tier)
    kids = [k.text("surface", f"{r.i} · {r.surface}", k.CAPTION, k.TEXT_2, w=TXT_W),
            k.text("variant", f"{r.layer} · {r.klass} — {v}", k.CAPTION, k.TEXT_1, w=TXT_W)]
    probe = k.vbox("p", kids, {"padX": k.INSET_XS, "padY": k.INSET_XS}, w=COL_W)
    h = int(math.ceil(k.est_height(probe)))
    return k.vbox(f"cell · {r.i}", kids, {"padX": k.INSET_XS, "padY": k.INSET_XS, "fill": k.RAISED if r.layer == "DOM" else k.SUNKEN,
                                          "radius": k.R_CONTROL}, w=COL_W, h=h,
                  note=f"§3 L{r.line} ({r.owner}): {tier}")


def columns(cells: list[k.Node]) -> list[list[k.Node]]:
    """Cells in I order cut into COLS contiguous columns, minimising the tallest column (exact, by search)."""
    gap = k.PX[k.STACK_XS]
    hs = [c["h"] + gap for c in cells]
    n = len(hs)
    best: dict[tuple[int, int], tuple[float, list[int]]] = {}

    def solve(i: int, cols: int) -> tuple[float, list[int]]:
        if cols == 1:
            return sum(hs[i:]), [n]
        if (i, cols) not in best:
            opts = []
            for j in range(i + 1, n - cols + 2):
                rest, cuts = solve(j, cols - 1)
                opts.append((max(sum(hs[i:j]), rest), [j, *cuts]))
            best[(i, cols)] = min(opts, key=lambda o: o[0])
        return best[(i, cols)]

    _h, cuts = solve(0, COLS)
    out, start = [], 0
    for c in cuts:
        out.append(cells[start:c])
        start = c
    return out


def build_frame(tier: str) -> tuple[k.Node, float]:
    t = k.TIER_TABLE[TIER_KEY[tier]]
    fid = next(f for f in k.BOARDS[NN].frames if f.startswith(f"inventory/{tier} "))
    head = k.text("title", f"§3 motion inventory · effective tier: {TIER_KEY[tier]}", k.HEADING_SM, k.TEXT_1)
    sub = k.text("tier line", f"Set by: {t['set_by']} · data-motion {t['motion']} · engine flags: {t['flags']} · DOM "
                              f"recipes: {t['dom']} · DOM value flash: {t['flash']} (§2 L{t['line']})",
                 k.CAPTION, k.TEXT_2, w=INNER_W)
    cells = [inv_cell(r, tier) for r in k.INV]
    cols = columns(cells)
    col_nodes = [k.vbox(f"column {i}", c, {"gap": k.STACK_XS}, w=COL_W,
                        h=int(sum(x["h"] for x in c) + (len(c) - 1) * k.PX[k.STACK_XS])) for i, c in enumerate(cols, 1)]
    grid_h = max(n["h"] for n in col_nodes)
    grid = k.hbox("map", col_nodes, {"gap": k.INSET_SM, "align": "start"}, w=INNER_W, h=grid_h)
    used = k.est_height(k.vbox("probe", [head, sub, grid], {"gap": k.STACK_SM, "pad": k.INSET_XL}, w=k.FRAME_W))
    if used > k.FRAME_H:
        raise ValueError(f"{fid}: the map needs about {used:.0f} px > {k.FRAME_H}")
    k.live(f"{fid}: after relayout the tallest map column ends inside the frame (estimated fill {used:.0f} of "
           f"{k.FRAME_H} px); if a cell clips, move the last cell of the tallest column to the next column")
    return k.specimen(fid, [head, sub, grid], gap=k.STACK_SM, note=f"§3 L{k.INV_LINE}: {len(cells)} cells, tier {tier}"), used


def main() -> None:
    frames, blocks = [], []
    for tier in k.TIERS:
        fr, used = build_frame(tier)
        frames.append(fr)
        fid = k.BOARDS[NN].frames[len(frames) - 1]
        t = k.TIER_TABLE[TIER_KEY[tier]]
        lines = [f"Every §3 row (L{k.INV[0].line}–L{k.INV[-1].line}, {len(k.INV)} rows) with its {TIER_KEY[tier]} "
                 f"cell verbatim; the tier as §2 L{t['line']} resolves it",
                 "Each cell: I-n · the surface, then layer · class — its variant in this tier; raised cells are DOM "
                 "rows, sunken cells canvas rows (the layer word says it too)",
                 f"Estimated fill {used:.0f} of {k.FRAME_H} px; cells in I order, top to bottom, left to right"]
        if tier == "canvas-calm":
            lines.append("A canvas row's canvas-calm cell equals its reduced cell; a DOM row's is \"as full\" "
                         f"(§3 L{k.INV_LINE + 2}; the self-test checks both)")
        blocks.append((fid, lines))
    p, md, pk = k.build(NN, frames, blocks, per_row=3, board_lines=[
        f"Not drawn: light and high-contrast cells of this board (§0 L{k.NOT_DRAWN_LINE})"])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
