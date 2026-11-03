"""Board 10 `E47-D08 / 10 forced-reduce` (dark): §10's 2 × 2 matrix (safe / reduce × no forced / forced colours) for
three classes — the DOM value flash, the canvas data-rate flash and a DOM chrome transition — each cell a specimen
plus §10's words verbatim. System colours are drawn per FALLBACKS forced and named in words."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FOCUS_SYMBOL, at, change_cell, fmt, k, liq_mark, overlay, seeded  # noqa: E402

NN = 10
CLASSES = ("DOM value flash (I-5)", "canvas data-rate (I-20 … I-24)", "DOM chrome transition (I-1 …)")
LAB_W, CELL_W, CELL_H = 200, 256, 176
NOW = 1000
INNER_W = k.FRAME_W - 2 * k.PX[k.INSET_XL]
I1 = next(r for r in k.INV if r.i == "I-1")


def spec_value(col: int) -> k.Node:
    reduce, forced = col in (1, 3), col in (2, 3)
    p, d = at(FOCUS_SYMBOL, NOW)
    kids: list[k.Node] = [k.text("value", fmt(p), k.NUM, k.TEXT_1)]
    if not reduce and not forced:
        kids.insert(0, overlay(104, 24, d >= 0))
    cell = k.hbox("cell · last", kids, {"padX": k.INSET_SM, "justify": "end"}, w=104, h=24)
    return k.hbox(f"specimen · {FOCUS_SYMBOL} last", [cell,
                               *change_cell(d, mode="forced" if forced else "safe")],
                  {"gap": k.INSET_SM, "fill": k.CANVAS}, h=28)


def spec_canvas(col: int) -> k.Node:
    reduce = col in (1, 3)
    size = f"{seeded(31, 1, 5, 240)[0] / 100:.2f} BTC"
    return k.hbox("specimen", [liq_mark(size, overlay=not reduce)], {"padX": k.INSET_SM, "fill": k.CANVAS}, h=32)


def spec_chrome(col: int) -> k.Node:
    reduce, forced = col in (1, 3), col in (2, 3)
    words = "the end state at frame 0" if reduce else "opacity 0 → 1, translateY(8px) → 0"
    pnl = k.vbox("panel", [k.text("h2", "Panel", k.BODY_STRONG, k.TEXT_1),
                           k.text("motion", words, k.CAPTION, k.TEXT_2)],
                 {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.RAISED, "stroke": k.BORDER_STRONG if forced
                  else k.BORDER_SUBTLE, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=200,
                 note=f"I-1 (§3 L{I1.line})")
    return pnl


SPEC = {CLASSES[0]: spec_value, CLASSES[1]: spec_canvas, CLASSES[2]: spec_chrome}


def build_frame(fid: str) -> tuple[k.Node, list[str]]:
    k.fallback("forced")
    head = k.hbox("header row", [k.box("corner", [], None, w=LAB_W, h=24)] + [
        k.hbox(f"th {i}", [k.text("value", h, k.LABEL, k.TEXT_2)], {"padX": k.INSET_SM}, w=CELL_W, h=24)
        for i, h in enumerate(k.MATRIX_HEAD[1:])], None, w=INNER_W, h=24)
    rows = []
    for ri, cls in enumerate(CLASSES, 1):
        words, ln = k.MATRIX[cls]
        cells = [k.vbox(f"row {ri} label", [k.text("class", cls, k.LABEL, k.TEXT_1, w=LAB_W - 16),
                                           k.text("cite", f"§10 L{ln}", k.CAPTION, k.TEXT_3)],
                        {"gap": k.STACK_XS, "padX": k.INSET_SM}, w=LAB_W, h=CELL_H)]
        for ci in range(4):
            forced = ci in (2, 3)
            kids = [SPEC[cls](ci), k.text("words", words[ci], k.CAPTION, k.TEXT_1, w=CELL_W - 16)]
            if forced:
                kids.append(k.text("system", "system colours: CanvasText on Canvas; focus Highlight", k.CAPTION,
                                   k.TEXT_3, w=CELL_W - 16))
            cells.append(k.vbox(f"cell {ri}-{ci + 1}", kids, {"gap": k.STACK_SM, "padX": k.INSET_SM,
                                                              "padY": k.INSET_SM, "fill": k.RAISED if ri % 2
                                                              else k.CANVAS}, w=CELL_W, h=CELL_H))
        rows.append(k.hbox(f"row {ri}", cells, {"align": "start"}, w=INNER_W, h=CELL_H))
    title = k.text("title", "§10 · forced colours × reduced motion: independent axes", k.HEADING_SM, k.TEXT_1)
    sub = k.text("sub", k.plain(k.SPEC_LINES[k.L("## 10. Forced colours") + 1]), k.CAPTION, k.TEXT_2, w=INNER_W)
    fr = k.specimen(fid, [title, sub, head, *rows], note="§10's matrix, three classes")
    lines = [f"§10 L{k.L('## 10. Forced colours')}: forced colours never sets data-motion; the motion mode never "
             "changes the colour mapping (D03:478–480)",
             f"Rows: {', '.join(CLASSES)}; columns: {', '.join(k.MATRIX_HEAD[1:])}; words verbatim from §10's table",
             "Specimens: the focused cell (I-5) at 1 000 ms of the burst, the liquidation mark (I-24), a panel mount "
             "(I-1); the canvas keeps the high-contrast ink under forced colours (D03:480)"]
    return fr, lines


def main() -> None:
    fid = k.BOARDS[NN].frames[0]
    fr, lines = build_frame(fid)
    p, md, pk = k.build(NN, [fr], [(fid, lines)], per_row=1, board_lines=[
        f"§10's other rows (canvas interaction, safety signal) are text-only here; safety is board 09's"])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
