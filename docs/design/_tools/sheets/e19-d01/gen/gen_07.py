"""Board 07 density-row-legibility: memo §4.3 and PD-8 — the row ladder (re-derived from its Rows column), the same
arithmetic on this board's synthetic session, and that session at one-tick rows merged per `26`'s rule (rows < 2 px
are summed), docked at compact and as a chart overlay at dense; price words on the named levels only."""
from __future__ import annotations

import math
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 7
PANES = (320, 480, 640)  # the memo's example pane heights (§4.3: "examples, not sourced")
PLOT_H = 320
FLOOR_PX = 10  # the borrowed 10 px canvas-text floor (memo §4.3, PROPOSED in PD-8)


def ladder_cells(rows: int) -> tuple[str, str, str]:
    px = [h / rows for h in PANES]
    merge = [max(math.ceil(2 / p - 1e-9), 1) for p in px]
    lab = [h for h, p in zip(PANES, px) if p >= FLOOR_PX]
    m = " / ".join(str(x) for x in merge) if len(set(merge)) > 1 else str(merge[0])
    word = "no" if not lab else ("yes" if len(lab) == len(PANES) else " and ".join(str(h) for h in lab) + " only")
    return " / ".join(f"{p:.2f}" for p in px), m, word


def ladder(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    hd = k.table_head("### 4.3 Row density")
    for _i, c in k.DENSITY:  # the memo's columns, re-derived from its Rows column
        got = ladder_cells(int(c[1].replace(" ", "")))
        if got != (c[2], c[3], c[4]):
            raise ValueError(f"§4.3 row {c[0]}: memo {c[2:]} != derived {got}")
    k.derive("memo §4.3: px per row, merge factor and the 10 px answer re-derived from each row's Rows (all four agree)")
    cols = list(zip(("size", "rows", "px", "merge", "lab"), hd, (176, 120, 272, 256, 336)))
    t1 = rb.table("memo ladder", cols, [dict(zip(("size", "rows", "px", "merge", "lab"), c)) for _i, c in k.DENSITY],
                  cap=f"memo §4.3 L{k.DENSITY_LINE}: the kline range, 2 251 one-tick rows (verbatim)")
    pr = k.FINAL
    span = max(p.hi for p in k.periods(pr.first)) - min(p.lo for p in k.periods(pr.first)) + 1
    mine = []
    for size in (int(c[0]) for _i, c in k.DENSITY):
        rows = math.ceil(span / size)
        px, m, word = ladder_cells(rows)
        mine.append({"size": str(size), "rows": f"{rows:,}".replace(",", " "), "px": px, "merge": m, "lab": word})
    t2 = rb.table("synthetic ladder", cols, mine,
                  cap=f"the same arithmetic on this board's synthetic session ({k.day_word(pr.first)}: {span:,} "
                      f"one-tick rows, seed {k.SEED})".replace(",", " "))
    cap = k.LINES["spec"][k.L("At the 10 px floor a pane holds") - 1].strip()
    return (k.frame(fid, [t1, t2, rb.card("capacity", [rb.para("words", cap, rb.IW - 24)], rb.IW)], rb.FW,
                    "Research — rows, pixels and merging: at one-tick rows no pane can label every row, so only "
                    "named levels carry words"),
            k.frame_block(fid, [k.f_line("F-19"), k.f_line("F-14")], ["PD-8"]))


def merged_pane(pr: k.Profile) -> k.Node:
    lo_t, hi_t = min(pr.vol), max(pr.vol)
    rows = hi_t - lo_t + 1
    px = PLOT_H / rows
    merge = max(math.ceil(2 / px - 1e-9), 1)
    bands: list[int] = []
    for b in range(math.ceil(rows / merge)):
        top_tick = hi_t - b * merge
        bands.append(sum(pr.vol.get(t, 0) for t in range(top_tick - merge + 1, top_tick + 1)))
    bh = merge * px
    top, xh, mx = 12, 12, max(bands)
    kids: list[k.Node] = [k.rect(f"band {i + 1}", max(round(v / mx * rb.BAR_W), 1), max(round(bh) - 1, 1), k.TEXT_3,
                                 x=xh, y=top + round(i * bh)) for i, v in enumerate(bands) if v]

    def y(t: int) -> int:
        return top + round((hi_t - t) * px)

    bx = xh + rb.BAR_W + 24
    poc_band_y = top + round(((hi_t - pr.poc) // merge) * bh)
    kids += [k.rect("POC rail top", rb.BAR_W, 1, k.TEXT_1, x=xh, y=poc_band_y),
             k.rect("POC rail bottom", rb.BAR_W, 1, k.TEXT_1, x=xh, y=poc_band_y + max(round(bh) - 1, 1)),
             k.rect("VA bracket", 2, y(pr.va[0]) - y(pr.va[1]) + 1, k.TEXT_1, x=bx, y=y(pr.va[1])),
             k.rect("VA bracket cap top", 8, 2, k.TEXT_1, x=bx - 6, y=y(pr.va[1])),
             k.rect("VA bracket cap bottom", 8, 2, k.TEXT_1, x=bx - 6, y=y(pr.va[0]) - 1),
             k.rect("VAH tick", 6, 2, k.TEXT_1, x=bx + 16, y=y(pr.va[1])),
             k.rect("VAL tick", 6, 2, k.TEXT_1, x=bx + 16, y=y(pr.va[0]))]
    last = -100
    for nm, words, typo, ly in sorted([
            ("VAH label", f"VAH {k.row_price(pr, pr.va[1])}", k.LABEL, y(pr.va[1]) - 6),
            ("POC label", k.memo_tpl("POC 62,974.0", **{"62,974.0": k.row_price(pr, pr.poc)}), k.BODY_STRONG,
             poc_band_y - 8),
            ("VAL label", f"VAL {k.row_price(pr, pr.va[0])}", k.LABEL, y(pr.va[0]) - 6)], key=lambda t: t[3]):
        ly = max(ly, last + 18)
        kids.append(k.text(nm, words, typo, k.TEXT_1, x=bx + 26, y=ly))
        last = ly
    w, h = bx + 26 + 132, top + PLOT_H + 12
    k.derive(f"{pr.label} at one-tick rows: {rows} rows over {PLOT_H} px = {px:.2f} px each; merge ×{merge} "
             f"(`26`: rows < 2 px are summed) → {len(bands)} drawn rows of {bh:.2f} px; POC "
             f"{k.row_price(pr, pr.poc)}, VA {k.row_price(pr, pr.va[0])}–{k.row_price(pr, pr.va[1])} (one-tick rows)")
    return k.box("profile pane · merged", rb.layers(kids, w, h), {"fill": k.SUNKEN, "stroke": k.BORDER,
                                                                  "strokeWidth": k.HAIR, "strokeAlign": "inner",
                                                                  "clip": True}, w=w, h=h,
                 note=f"one-tick rows merged ×{merge}; words on POC, VAH and VAL only")


def density_frame(fid: str, overlay: bool) -> tuple[k.Node, tuple[str, list[str]]]:
    pr = k.one_tick("session 29 Oct · one-tick rows", k.periods(k.DAYS[1]))
    pane = merged_pane(pr)
    rows = max(pr.vol) - min(pr.vol) + 1
    merge = max(math.ceil(2 / (PLOT_H / rows) - 1e-9), 1)
    pw = pane["w"] + 32
    rs = k.ui(f"Row size 1 tick ({k.TICK} USDT), merged ×{merge} on screen", "PD-8: the row size is in the legend")
    leg = rb.legend([(k.memo("Value area 70 %"), rb.glyph("bracket")), (k.developing_words(pr), None), (rs, None)],
                    pw - 16)
    if overlay:
        head = [k.text("title", k.ui("Volume profile"), k.BODY_STRONG, k.TEXT_1), rb.menu_button(k.mode_words()[2])]
        p = rb.panel(head, [k.hbox("pane row", [pane], {"padX": k.INSET_SM}, w=pw, h=pane["h"]),
                            k.hbox("legend row", [leg], {"padX": k.INSET_SM}, w=pw)], pw, name="chart overlay · dense")
        framing = ("Research — the chart overlay at the chart-only dense density (`16` :146): dense tightens canvas "
                   "padding and gutters, never the legibility floors, so the merge and the label rule are unchanged")
        lines = ["Visible range = the 29 Oct UTC day in view (synthetic); the candles under the overlay are not drawn"]
    else:
        head = [k.text("title", k.ui("Profile · BTCUSDT"), k.BODY_STRONG, k.TEXT_1), rb.menu_button(k.mode_words()[0])]
        p = rb.panel(head, [k.hbox("pane row", [pane], {"padX": k.INSET_LG}, w=pw, h=pane["h"]),
                            k.hbox("legend row", [leg], {"padX": k.INSET_SM}, w=pw)], pw)
        framing = ("Research — the docked panel at compact (the chart default, `16` :129): one-tick rows merged to "
                   "reach 2 px; price words on POC, VAH and VAL only, never on every row")
        lines = ["The 320 px plot is one of the memo's example pane heights (§4.3: examples, not sourced)"]
    return (k.frame(fid, [p], pw + 2 * k.FRAME_PAD, framing), k.frame_block(fid, lines))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    f1, f2, f3 = k.BOARDS[NN].frames
    out = [ladder(f1), density_frame(f2, False), density_frame(f3, True)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    one = k.one_tick("session 29 Oct · one-tick rows", k.periods(k.DAYS[1]))
    zero_50 = sum(1 for v in k.FINAL.delta.values() if v == 0)
    zero_1 = sum(1 for v in one.delta.values() if v == 0)
    untraded_1 = sum(1 for r in one.rows if not one.vol.get(r))
    rb.run(NN, frames(), 3, board_lines=[
        f"PD-8's second clause (untraded vs zero-delta rows) is not drawn: at {k.ROW_TICKS}-tick rows the synthetic "
        f"29 Oct session has {zero_50} zero-delta rows and no untraded row; at one-tick rows it has {zero_1} zero-delta "
        f"and {untraded_1} untraded rows, merged away on screen — E19-D02 draws the mark (memo §4.2, F-14)"])
