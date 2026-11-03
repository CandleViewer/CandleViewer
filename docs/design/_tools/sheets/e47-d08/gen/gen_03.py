"""Board 03 `E47-D08 / 03 region-arbiter` (dark + light): §4.3's FR-2 rectangle (341 × 256 px) over a watchlist cell,
a DOM-ladder cell and a liquidation mark; the frame is the state at 1 000 ms of the burst, and a table under the
panels says who wins each half-open 1 000 ms window (k.simulate with FR-9's rank: liquidation, the focused symbol,
the rest). The light twin is the same builder; the theme is the token set at export."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (FOCUS_SYMBOL, OTHERS, WL_PANEL_H, at, chart_body, fmt, k, ladder, liq_mark, nb,  # noqa: E402
                    seeded, watchlist)

NN = 3
NOW = 1000  # the frame's instant: window 2 opens (k.SIM admits the liquidation and the focused cell here)
REST = OTHERS[0][0]  # the watchlist cell inside the region: another symbol, "the rest" of FR-9
WL = (96, 16, 304, WL_PANEL_H)  # x, y, w, h in main (h 133: the grid's 105 px under the header)
LAD = (96, 152, 272, 296)
CH = (408, 16, 632, 432)
TABLE_Y = 464
ROW1_TOP = k.HEADER_H + k.ROW_H + 1 + 2 * k.PX[k.STACK_XS]  # 61: a panel's first body row (header, rule, gaps)
LIQ_SIZE = f"{seeded(31, 1, 5, 240)[0] / 100:.2f} BTC"  # synthetic (TICKS mulberry32, seed 31)
SRC = {"liq": "1 · liquidation mark (I-24)", "price": f"2 · ladder cell, {FOCUS_SYMBOL} focused (I-5)",
       "heat": f"3 · watchlist cell, {REST} (I-5)"}


def region_sim() -> k.Sim:
    ticks = [t.t_ms for t in k.BURST]
    return k.simulate({"liq": ticks, "price": ticks, "heat": ticks},
                      {"liq": k.fr_ms("FR-5"), "price": k.fr_ms("FR-1"), "heat": k.fr_ms("FR-1")})


def geometry() -> dict[str, tuple[int, int, int, int]]:
    """Main-area rectangles of the three elements (derived from the panel geometry and the table's row pitch)."""
    rest_row = 2  # REST is the watchlist's second row
    cur_row = 5  # the ladder's current-price row (9 rows, the price in the middle)
    lw = round(k.est_width(liq_mark(LIQ_SIZE, overlay=True)))
    return {"heat": (WL[0] + 80, WL[1] + ROW1_TOP + (rest_row - 1) * k.ROW_H, 112, k.ROW_H),
            "price": (LAD[0] + 80, LAD[1] + ROW1_TOP + (cur_row - 1) * k.ROW_H, 112, k.ROW_H),
            "liq": (CH[0] + 8, CH[1] + 160, lw, 24)}


def region_xy(g: dict[str, tuple[int, int, int, int]]) -> tuple[int, int]:
    x0 = min(v[0] for v in g.values())
    y0 = min(v[1] for v in g.values())
    x1 = max(v[0] + v[2] for v in g.values())
    y1 = max(v[1] + v[3] for v in g.values())
    if x1 - x0 > k.REGION_W or y1 - y0 > k.REGION_H:
        raise ValueError(f"the three elements span {x1 - x0} x {y1 - y0} > the FR-2 region")
    return x0 - (k.REGION_W - (x1 - x0)) // 2, y0 - (k.REGION_H - (y1 - y0)) // 2


def who_wins(sim: k.Sim) -> k.Node:
    cols = (k.Col("win", "Window", 160), *(k.Col(s, SRC[s], 300) for s in k.SOURCES), k.Col("n", "Starts", 96, True))
    rows = []
    for i, w0 in enumerate(range(0, 3 * k.WINDOW_MS, k.WINDOW_MS), 1):
        cells: dict = {"win": f"[{nb(w0)}, {nb(w0 + k.WINDOW_MS)}) ms"}
        n = 0
        for s in k.SOURCES:
            a = [t for t in sim.admitted[s] if w0 <= t < w0 + k.WINDOW_MS]
            r = [t for t in sim.refused[s] if w0 <= t < w0 + k.WINDOW_MS]
            n += len(a)
            cells[s] = ("starts at " + ", ".join(f"{nb(t)} ms" for t in a) if a else "no start") + \
                (f"; {len(r)} refused, the value still updates" if r else "")
        cells["n"] = str(n)
        rows.append(k.table_row(cols, cells, f"row {i}", i))
    return k.table("CMP-049 grid · who wins", f"Who wins each window (FR-9 rank 1 → 3; at most FR-3 = "
                   f"{k.fr_int('FR-3')} starts): the burst through §4.3's arbiter", k.header_row(cols), rows,
                   note="annotation table (k.simulate), not product UI")


def build_frame(fid: str) -> tuple[k.Node, list[str]]:
    sim = region_sim()
    g = geometry()
    rx, ry = region_xy(g)
    wl = k.panel("CMP-080 panel · watchlist", "Watchlist", watchlist(NOW), WL[2], WL[3])
    lad = k.panel(f"CMP-080 panel · DOM ladder {FOCUS_SYMBOL}", f"DOM · {FOCUS_SYMBOL}",
                  ladder(NOW, flash_price=at(FOCUS_SYMBOL, NOW)[0]), LAD[2], LAD[3])
    body, _sc = chart_body(CH[2], CH[3] - k.HEADER_H, 100)
    ch = k.panel(f"CMP-080 panel · chart {FOCUS_SYMBOL}", f"Chart · {FOCUS_SYMBOL} · 100 ms", body, CH[2], CH[3])
    lx, ly, _lw, _lh = g["liq"]
    mark = dict(liq_mark(LIQ_SIZE, overlay=True), x=lx, y=ly, abs=True)
    k.fallback("markers")
    over = [k.rect("FR-2 region · outline", k.REGION_W, k.REGION_H, None,
                   {"stroke": k.MARK_FILL, "strokeWidth": k.THICK, "strokeAlign": "inner"}, x=rx, y=ry,
                   note=f"annotation: one FR-2 rectangle, {k.REGION_W} × {k.REGION_H} CSS px (§4.1 FR-2)"),
            # the tag right of the outline's top-right corner, on the chart's empty upper plot: under the outline's
            # bottom-left corner (the first render) it covered two ladder prices
            k.tag(f"FR-2 region · {k.REGION_W} × {k.REGION_H} px", rx + k.REGION_W + 6, ry)]
    for n_, s in enumerate(k.SOURCES, 1):
        x, y, wd, _h = g[s]
        over.append(k.marker(n_, x + wd - 12, y - 12))
    wins = dict(who_wins(sim), x=0, y=TABLE_Y)
    content = k.box("workspace", [dict(wl, x=WL[0], y=WL[1]), dict(lad, x=LAD[0], y=LAD[1]),
                                  dict(ch, x=CH[0], y=CH[1]), mark, *over, wins], None, w=k.MAIN_W, h=k.BODY_H)
    fr = k.window(fid, content, note=f"§4.3; the state at {NOW} ms of the burst")
    p_now = fmt(at(FOCUS_SYMBOL, NOW)[0])
    r_now = fmt(at(REST, NOW)[0])
    lines = [f"State at {NOW} ms (window 2 opens): 1 the liquidation overlay and 2 the focused {FOCUS_SYMBOL} ladder "
             f"cell ({p_now}) start; 3 {REST}'s cell ({r_now}) is refused and its value still updates (R-4)",
             f"The outline is one FR-2 rectangle (§4.1 L{k.FR['FR-2']['line']}) holding all three elements, "
             f"the rule §4.3 L{k.L('### 4.3 The region arbiter') + 2} states; refused requests are dropped, never "
             "queued",
             f"Rank FR-9 (§4.1 L{k.FR['FR-9']['line']}): liquidation, then the focused symbol, then the rest; so the "
             f"rest never starts while the burst lasts ({len(sim.refused['heat'])} requests refused over "
             f"{nb(k.BURST_MS)} ms)",
             "The overlays use the FALLBACKS tints (flash-peak, liq-overlay); markers 1-3 and the outline are "
             "annotation"]
    return fr, lines


def main() -> None:
    frames, blocks = [], []
    for fid in k.BOARDS[NN].frames:
        fr, lines = build_frame(fid)
        frames.append(fr)
        if k.frame_theme(fid) != "dark":
            lines = [f"{k.THEME_WORD[k.frame_theme(fid)].capitalize()} twin: the same nodes and words; evidence in "
                     f"the second export {k.BOARDS[NN].twin_export}", *lines[:1]]
        blocks.append((fid, lines))
    p, md, pk = k.build(NN, frames, blocks, per_row=2, board_lines=[
        f"HS-1b's area bound stays light-only as ruled; FR-2's start count is D08's own budget in every theme "
        f"(§4.3 L{k.L('### 4.3 The region arbiter') + 2})"])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
