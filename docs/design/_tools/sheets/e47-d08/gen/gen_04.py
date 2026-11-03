"""Board 04 `E47-D08 / 04 price-cell-modes` (dark): the I-5 value flash on the focused symbol's watchlist cell in three
modes. safe: the overlay's peak and decay (FALLBACKS flash-peak), starts held to FR-1; reduce: no overlay, the glyph
and the sign carry it, the glyph's direction held to FR-1 (§5) while the digits update every tick (R-4); forced: the
same in CanvasText (§10; FALLBACKS forced). Every figure comes from the TICKS burst."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (FOCUS_SYMBOL, WL_COLS, WL_PANEL_H, Timeline, at, fmt, fmt_delta, k, nb,  # noqa: E402
                    watch_row, watchlist)

NN = 4
NOW = next(t.t_ms for t in k.BURST if t.t_ms >= 1000 and t.move != "flat")  # a changing tick in window 2
T1 = 2000
TL = Timeline(0, T1, 200, 960)
INV5 = next(r for r in k.INV if r.i == "I-5")


def glyph_hold() -> tuple[list[tuple[int, bool]], list[tuple[int, bool]]]:
    """(data direction changes, drawn glyph changes): a change of direction at most once per FR-1 per cell; when a
    change is due the glyph takes the latest direction (§5; the coalescer's net direction, CAL:86)."""
    iv = k.fr_ms("FR-1")
    data, drawn = [], []
    cur: bool | None = None
    last_dir: bool | None = None
    last_change = -iv
    for t in k.BURST:
        if t.move == "flat":
            continue
        up = t.move == "up"
        if up != last_dir:
            data.append((t.t_ms, up))
            last_dir = up
        if up != cur and t.t_ms - last_change >= iv:
            drawn.append((t.t_ms, up))
            cur, last_change = up, t.t_ms
    return data, drawn


def drawn_at(t_ms: int) -> bool:
    return [u for t, u in glyph_hold()[1] if t <= t_ms][-1]


def lane_marks(prefix: str, pts: list[tuple[int, bool]], y: int, h: int, mode: str) -> list[k.Node]:
    out = []
    for t, up in pts:
        if t >= T1:
            continue
        col = k.TEXT_1 if mode == "forced" else (k.BUY if up else k.SELL)
        out.append(k.text(f"{prefix} {t}", "▲" if up else "▼", k.NUM_SM, col, x=TL.x(t) - 4, y=y))
    return out


def strip(mode: str) -> tuple[k.Node, list[str]]:
    """The right-hand evidence: safe = three snapshots of the cell; reduce / forced = the glyph-hold lanes."""
    kids: list[k.Node] = []
    lines: list[str] = []
    if mode == "safe":
        k.fallback("flash-peak")
        starts = [t for t in k.SIM.solo["price"] if t < T1]
        for i, (ph, lab) in enumerate((("peak", f"t = {nb(NOW)} ms · peak: overlay opacity 0.25"),
                                       ("mid", "mid-decay: motion.duration.fast · motion.easing.accelerate"),
                                       (None, "end: the overlay at 0; the value stays")), 1):
            row = watch_row(FOCUS_SYMBOL, NOW, 1, flash=ph)
            kids.append(k.vbox(f"snapshot {i}", [k.text("label", lab, k.CAPTION, k.TEXT_2),
                                                  k.table("CMP-049 grid · one row", None, k.header_row(WL_COLS),
                                                          [row])], {"gap": k.STACK_XS}))
        lane = k.box("lane · starts", [*TL.windows(0, 64), *[k.rect(f"start {t}", 4, 32, k.BUY, x=TL.x(t), y=24)
                                                              for t in starts], *TL.axis(64, 250)], None,
                     w=1180, h=96)
        kids.append(k.text("lane label", f"Overlay starts on this cell, held to FR-1 ({k.fr_ms('FR-1')} ms): "
                                         f"{len(starts)} in 0–{nb(T1)} ms, max {k.max_window(starts)} per window",
                           k.LABEL, k.TEXT_1))
        kids.append(lane)
        lines = [f"§3 I-5 (L{INV5.line}): {INV5.full}",
                 f"Snapshots of the {FOCUS_SYMBOL} row at {nb(NOW)} ms: peak, mid-decay, end (FALLBACKS flash-peak)",
                 f"Starts admitted at FR-1: {', '.join(nb(t) for t in starts)} ms (k.SIM; §4.4 'one cell' max "
                 f"{k.val('SIM', 'price')})"]
    else:
        data, drawn = glyph_hold()
        dd = [p for p in data if p[0] < T1]
        dr = [p for p in drawn if p[0] < T1]
        lane = k.box("lanes · glyph", [*TL.windows(0, 120),
                                       k.text("lane 1 label", "data direction", k.CAPTION, k.TEXT_2, x=0, y=28),
                                       *lane_marks("data", dd, 26, 14, mode),
                                       k.text("lane 2 label", "glyph drawn (held)", k.CAPTION, k.TEXT_2, x=0, y=76),
                                       *lane_marks("drawn", dr, 74, 14, mode), *TL.axis(120, 250)], None, w=1180,
                     h=152)
        kids.append(k.text("lane label", f"Under reduce the glyph's direction changes at most once per FR-1 "
                                         f"({k.fr_ms('FR-1')} ms): {len(dd)} direction changes in the data, {len(dr)} "
                                         f"drawn, max {k.max_window([t for t, _u in dr])} per window",
                           k.LABEL, k.TEXT_1))
        kids.append(lane)
        lines = [f"§5 L{k.L('| the direction glyph and its tint (I-5)')}: a change of direction at most once per "
                 "FR-1 per cell; the sign and digits update at once",
                 f"I-5 reduced (L{INV5.line}): {INV5.reduced}",
                 f"At {nb(NOW)} ms the {FOCUS_SYMBOL} glyph shows {'▲' if drawn_at(NOW) else '▼'} (held) while the "
                 f"sign reads {fmt_delta(at(FOCUS_SYMBOL, NOW)[1])} and the last {fmt(at(FOCUS_SYMBOL, NOW)[0])}"]
        if mode == "forced":
            k.fallback("forced")
            m = k.MATRIX["DOM value flash (I-5)"]
            lines.insert(0, f"§10 L{m[1]}: {k.MATRIX_HEAD[3]}: {m[0][2]}; the glyph changes shape, not luminance, so "
                            f"it is not a flash (§5 L{k.L('Under forced colours the glyph is drawn in')})")
    return k.vbox("evidence", kids, {"gap": k.STACK_SM}, w=1180), lines


def build_frame(mode: str) -> tuple[k.Node, list[str]]:
    fid = k.BOARDS[NN].frames[("safe", "reduce", "forced").index(mode)]
    held = None if mode == "safe" else {FOCUS_SYMBOL: drawn_at(NOW)}
    wl = k.panel("CMP-080 panel · watchlist", "Watchlist", watchlist(NOW, flash={FOCUS_SYMBOL: "peak"} if mode == "safe"
                                                                     else None, mode=mode, held=held), 304, WL_PANEL_H)
    ev, lines = strip(mode)
    head = k.text("mode", {"safe": "data-motion safe: the overlay, starts held to FR-1",
                           "reduce": "data-motion reduce: no overlay; the glyph and the sign carry the change",
                           "forced": "reduce + forced-colors: active — glyph and sign in CanvasText"}[mode],
                  k.HEADING_SM, k.TEXT_1)
    sysnote = (k.chip("system colours: text CanvasText on Canvas (D03:478–480)", stroke=k.BORDER_STRONG)
               if mode == "forced" else None)
    content = k.vbox("workspace", [head, sysnote, wl, ev], {"gap": k.STACK_MD, "pad": k.INSET_LG}, w=k.MAIN_W,
                     h=k.BODY_H)
    return k.window(fid, content, note=f"I-5 in mode {mode}"), lines


def main() -> None:
    frames, blocks = [], []
    for mode in ("safe", "reduce", "forced"):
        fr, lines = build_frame(mode)
        frames.append(fr)
        blocks.append((k.BOARDS[NN].frames[len(frames) - 1], lines))
    p, md, pk = k.build(NN, frames, blocks, per_row=3, board_lines=[
        f"The focused symbol {FOCUS_SYMBOL} is a kit label: TICKS names no instrument; the other rows are the same "
        "generator on other seeds and synthetic anchors",
        "Only the focused row's flash is drawn; the other rows' cells are between their own starts at this instant"])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
