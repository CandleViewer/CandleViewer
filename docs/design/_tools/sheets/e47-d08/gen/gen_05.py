"""Board 05 `E47-D08 / 05 liquidation` (dark): §6 — a ten-event liquidation burst inside one 1 000 ms window on one
panel. burst: one overlay start (FR-5), the size text and the count updating per event; reduce: no overlay, the
glyph and the size as text (MR-3's carrier). Event times are the first ten TICKS burst ticks; sizes are TICKS'
mulberry32 on another seed (synthetic)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FOCUS_SYMBOL, Timeline, chart_body, k, liq_mark, nb, seeded  # noqa: E402

NN = 5
N_EV = int(next(m for m in __import__("re").findall(r"(\d+)-event burst", k.BOARDS[5].draws)))
EVENTS = [(t.t_ms, sz) for t, sz in zip(k.BURST[:N_EV], seeded(51, N_EV, 5, 180))]  # (t ms, size in 0.01 BTC)
TL = Timeline(0, k.WINDOW_MS, 120, 440)
I24 = next(r for r in k.INV if r.i == "I-24")


def starts() -> list[int]:
    out: list[int] = []
    for t, _s in EVENTS:
        if not out or t - out[-1] >= k.fr_ms("FR-5"):
            out.append(t)
    return out


def mark_text(n: int) -> str:
    tot = sum(s for _t, s in EVENTS[:n])
    return f"{tot // 100}.{tot % 100:02d} BTC ×{n}"


def event_table(reduce: bool) -> k.Node:
    cols = (k.Col("n", "Event", 56, True), k.Col("t", "t (ms)", 64, True), k.Col("sz", "Size", 88, True),
            k.Col("text", "Mark text after it", 136), k.Col("ov", "Overlay", 240))
    st = starts()
    rows = []
    for i, (t, s) in enumerate(EVENTS, 1):
        ov = "none (reduce)" if reduce else ("start (FR-5)" if t in st else "no new start: in the window")
        rows.append(k.table_row(cols, {"n": str(i), "t": nb(t), "sz": f"{s // 100}.{s % 100:02d} BTC",
                                       "text": mark_text(i), "ov": ov}, f"row {i}", i))
    return k.table("CMP-049 grid · events", f"The {N_EV} events (synthetic) and what the mark shows", k.header_row(cols),
                   rows, note="annotation table, not product UI")


def build_frame(reduce: bool) -> tuple[k.Node, list[str]]:
    fid = k.BOARDS[NN].frames[1 if reduce else 0]
    body, _sc = chart_body(568, 420 - k.HEADER_H, 100, t1=2000)
    ch = k.panel(f"CMP-080 panel · chart {FOCUS_SYMBOL}", f"Chart · {FOCUS_SYMBOL} · 100 ms", body, 568, 420)
    mark = dict(liq_mark(mark_text(N_EV), overlay=not reduce), x=16 + 200, y=16 + 180, abs=True)
    st = starts()
    lane = k.box("lane · events", [
        k.text("label events", "events", k.CAPTION, k.TEXT_2, x=0, y=8),
        *[k.rect(f"event {t}", 2, 14, k.TEXT_3, x=TL.x(t), y=8) for t, _s in EVENTS],
        k.text("label starts", "overlay starts" if not reduce else "overlay starts (none)", k.CAPTION, k.TEXT_2,
               x=0, y=36),
        *([] if reduce else [k.rect(f"start {t}", 4, 28, k.WARN_STRONG, x=TL.x(t), y=30) for t in st]),
        *TL.axis(64, 250)], None, w=568, h=96)
    tbl = event_table(reduce)
    content = k.box("workspace", [dict(ch, x=16, y=16), mark,
                                  dict(k.vbox("evidence", [k.text("lane title", f"One panel, 0–{nb(k.WINDOW_MS)} ms: "
                                                                  f"{N_EV} events, {0 if reduce else len(st)} overlay "
                                                                  "start", k.LABEL, k.TEXT_1), lane],
                                              {"gap": k.STACK_XS}), x=16, y=448),
                                  dict(tbl, x=600, y=16)], None, w=k.MAIN_W, h=k.BODY_H)
    fr = k.window(fid, content, note=f"§6; {'reduce' if reduce else 'safe'}")
    lines = ([f"§6 L{k.L('## 6. The liquidation flash') + 2}: at most one start per panel per 1 000 ms (FR-5); a "
              "burst inside the window updates the size text and the count, never re-starts the overlay",
              f"{N_EV} events at {nb(EVENTS[0][0])}–{nb(EVENTS[-1][0])} ms: {len(st)} start, at {nb(st[0])} ms; the "
              f"mark ends at \"{mark_text(N_EV)}\"",
              "Overlay: FALLBACKS liq-overlay (PROPOSED color.liquidation.flash, D08-A9, not a token)"]
             if not reduce else
             [f"I-24 reduced (L{I24.line}): {I24.reduced}",
              "No overlay paints; the warning glyph and the size text carry every event; the count still updates",
              f"§3: I-24's canvas-calm cell is the same (L{I24.line})"])
    k.copy_gap(f"the mark's count format \"<size> BTC ×<n>\" is a kit label: §6 says the burst updates \"the size "
               f"text and the count\" without words (L{k.L('## 6. The liquidation flash') + 2})")
    return fr, lines


def main() -> None:
    frames, blocks = [], []
    for reduce in (False, True):
        fr, lines = build_frame(reduce)
        frames.append(fr)
        blocks.append((k.BOARDS[NN].frames[len(frames) - 1], lines))
    p, md, pk = k.build(NN, frames, blocks, per_row=2, board_lines=[
        "The panel design and the mark's placement are E24-D04's (D08-G2): drawn here only as the motion layer's "
        "carrier"])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
