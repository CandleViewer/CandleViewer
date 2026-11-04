"""Board 08 `E47-D05 / 08 keyboard-only-reveal` (dark): §8 — keyboard-only mode on, one example per kind (an order
line, a drawing point, a rule-graph edge): the fields in place of the drag, the drag inert with its hint W-20. The
hosts are not built (S07:8–11): this is the pattern each host adopts; the forms themselves are E47-D09's."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k  # noqa: E402

NN = 8
PS = k.PS(values=(("keyboard_only", "true"),))
MAIN_W = k.FRAME_W - k.NAV_W  # 1216: no SettingsNav on a workspace window
PANEL_W, PANEL_H, CANVAS_H = 1120, 600, 480
STOP_TICKS = 18  # kit choice: the stop sits 18 ticks under the last print


def handle_with_hint(name: str, hint_left: bool = False) -> k.Node:
    hint = k.text("hint · W-20", k.w("W-20"), k.CAPTION, k.TEXT_2, note="persistent text while the mode is on (§8.2)")
    h = k.hbox("drag handle (inert)", [k.icon("glyph", "drag-handle", k.TEXT_3)],
               {"justify": "center", "radius": k.R_CONTROL, "fill": k.RAISED}, w=24, h=24,
               note="a pointer target only, no keyboard role (not a T2 control); under the mode a drag moves nothing")
    return k.hbox(name, [hint, h] if hint_left else [h, hint], {"gap": k.INSET_SM}, h=24)


def panel(title_kids: list[k.Node], body: k.Node, side: k.Node) -> k.Node:
    head = k.hbox("panel header", [k.text("symbol", k.SYMBOL, k.BODY_STRONG, k.TEXT_1), *title_kids,
                                  k.placeholder("toolbar", 160, 16)], {"gap": k.INSET_MD, "padX": k.INSET_MD,
                                                                      "fill": k.RAISED}, w=PANEL_W, h=32)
    row = k.hbox("panel body", [body, side], {"align": "start", "gap": k.INSET_LG, "pad": k.INSET_LG},
                 w=PANEL_W, h=PANEL_H - 32)
    return k.vbox("panel", [head, row], {"fill": k.CANVAS, "radius": k.R_CARD, "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"},
                  w=PANEL_W, h=PANEL_H)


def price_y(p: Decimal, hi: Decimal, lo: Decimal) -> int:
    return round(float(hi - p) / float(hi - lo) * (CANVAS_H - 24)) + 12


def chart_canvas(extra: list[k.Node], hi: Decimal, lo: Decimal, wd: int = 760) -> k.Node:
    kids: list[k.Node] = []
    n = len(k.WORLD.candles)
    for i, c in enumerate(k.WORLD.candles):
        x = 40 + i * (wd - 160) // n
        top, bot = max(c.o, c.c), min(c.o, c.c)
        kids += [k.rect(f"wick {i + 1}", 1, max(1, price_y(c.l, hi, lo) - price_y(c.h, hi, lo)), k.C_WICK,
                        x=x + 7, y=price_y(c.h, hi, lo)),
                 k.rect(f"body {i + 1}", 16, max(2, price_y(bot, hi, lo) - price_y(top, hi, lo)),
                        k.C_UP if c.c >= c.o else k.C_DOWN, x=x, y=price_y(top, hi, lo))]
    for j in range(5):
        p = lo + (hi - lo) * j / 4
        p = (p / k.TICK).to_integral_value() * k.TICK
        kids.append(k.text(f"axis {j + 1}", k.px_fmt(p), k.NUM_SM, k.AXIS, x=wd - 72, y=price_y(p, hi, lo) - 7))
    return k.box("chart canvas (synthetic)", kids + extra, {"fill": k.CANVAS, "clip": True}, w=wd, h=CANVAS_H,
                 note="seeded candles; the axis labels are prices at quarter steps of the drawn range")


def order_line_frame(fid: str) -> tuple[k.Node, list[str]]:
    lo0 = min(c.l for c in k.WORLD.candles)
    stop = lo0 - STOP_TICKS * k.TICK
    hi, lo = max(c.h for c in k.WORLD.candles) + 10 * k.TICK, stop - 10 * k.TICK
    y = price_y(stop, hi, lo)
    line = k.rect("stop line", 760, 2, k.DANGER_STRONG, x=0, y=y)
    chip = k.hbox("line label", [k.text("kind", "Stop", k.LABEL, k.TEXT_1), k.text("price", k.px_fmt(stop), k.NUM_SM,
                                                                                    k.TEXT_1)],
                  {"gap": k.INSET_XS, "padX": k.INSET_XS, "fill": k.RAISED, "radius": k.R_CONTROL}, h=20, x=320,
                  y=y - 22, abs=True)
    # under the stop line, so the line does not strike through the W-20 hint (live check: y - 11 -> y + 5)
    hnd = dict(handle_with_hint("handle"), x=8, y=y + 5, abs=True)
    canvas = chart_canvas([line, chip, hnd], hi, lo)
    k.copy_gap('"Stop", "Price": the order line\'s kind word and its field label (§8.1 names "a price field + step '
               'buttons by tick"; the words are E47-D09\'s)')
    side = k.vbox("fields (revealed)", [k.field("Price", k.px_fmt(stop), PS, steps=True, focused=True)],
                  {"gap": k.STACK_MD}, w=260,
                  note="persistent and visible under the mode; Enter commits, Esc cancels (`05`:35); step = one tick")
    callout = k.callout("confirm", ["Moving a stop still asks to confirm",
                                    "US-SET-003's confirm policy (`11`:5107); Live never weaker than Demo "
                                    "(`11`:5111–5112); the dialog returns focus to the invoker (D04:312)"],
                        k.NAV_W + 32 + 760 + 48, 360, wd=300)
    fr = window(fid, panel([], canvas, side), [callout])
    return fr, [f"Order line: the stop at {k.px_fmt(stop)} ({STOP_TICKS} ticks under the low {k.px_fmt(lo0)}); the price "
                f"field steps by the tick ({k.TICK.normalize()}) with the arrow buttons; Enter commits, Esc cancels "
                "(§8.1; `05`:35)",
                f"§8.3 L{k.L('### 8.3 Safety')}: the form equivalent of a destructive drag inherits US-SET-003's confirm "
                "policy and is never a lower-friction path; it never weakens the native stop-loss invariant (C-2.6)"]


def drawing_point_frame(fid: str) -> tuple[k.Node, list[str]]:
    c0, c1 = k.WORLD.candles[1], k.WORLD.candles[4]
    hi, lo = max(c.h for c in k.WORLD.candles) + 10 * k.TICK, min(c.l for c in k.WORLD.candles) - 10 * k.TICK
    n = len(k.WORLD.candles)
    xs = [40 + 1 * 600 // n + 8, 40 + 4 * 600 // n + 8]
    ys = [price_y(c0.l, hi, lo), price_y(c1.h, hi, lo)]
    marks = [k.rect(f"trend mark {i}", 3, 3, k.TEXT_LINK, x=round(xs[0] + (xs[1] - xs[0]) * i / 24),
                    y=round(ys[0] + (ys[1] - ys[0]) * i / 24)) for i in range(1, 24)]
    pts = [k.rect(f"point {i + 1}", 8, 8, k.TEXT_LINK, {"radius": k.R_CONTROL}, x=xs[i] - 4, y=ys[i] - 4)
           for i in range(2)]
    hnd0 = handle_with_hint("handle", hint_left=True)  # left of the point, clear of the last candle (design read)
    hnd = dict(hnd0, x=xs[1] - 12 - round(k.est_width(hnd0)), y=ys[1] - 30, abs=True)
    canvas = chart_canvas([*marks, *pts, hnd], hi, lo)
    k.copy_gap('"Time", "Price": the drawing point\'s field labels (§8.1: "x / y fields in time and price")')
    side = k.vbox("fields (revealed)", [k.field("Time", k.candle_minute(c1.minute), PS, wd=88),
                                        k.field("Price", k.px_fmt(c1.h), PS, steps=True, focused=True)],
                  {"gap": k.STACK_MD}, w=260, note="the selected point's x / y; persistent under the mode")
    fr = window(fid, panel([], canvas, side), [])
    return fr, [f"Drawing point: a trend line from the {k.candle_minute(c0.minute)} low {k.px_fmt(c0.l)} to the "
                f"{k.candle_minute(c1.minute)} high {k.px_fmt(c1.h)}; the second point's fields in time and price "
                "(§8.1; E47-D09)",
                "The line is drawn as 3 px marks (no path primitive in cvsheet)"]


def rule_edge_frame(fid: str) -> tuple[k.Node, list[str]]:
    copy_n = ("Node 1", "Node 2")
    nodes = [k.vbox(f"rule node · {n}", [k.text("name", n, k.BODY_STRONG, k.TEXT_1)],
                    {"pad": k.INSET_MD, "fill": k.RAISED, "radius": k.R_CARD, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                     "strokeAlign": "inner"}, w=160, h=56, x=80 + 360 * i, y=200) for i, n in enumerate(copy_n)]
    edge = k.rect("edge", 200, 2, k.TEXT_2, x=240, y=227)
    hnd = dict(handle_with_hint("handle"), x=300, y=260, abs=True)  # clear of Node 2's box (live check: 244 -> 260)
    canvas = k.box("rule graph (synthetic)", [*nodes, edge, hnd], {"fill": k.CANVAS, "clip": True}, w=760, h=CANVAS_H)
    k.copy_gap('"Source", "Target", "Node 1", "Node 2": the edge pickers\' labels and two illustrative node names '
               '(§8.1: "source and target pickers")')
    side = k.vbox("fields (revealed)", [k.field("Source", copy_n[0], PS, wd=160, picker=True, focused=True),
                                        k.field("Target", copy_n[1], PS, wd=160, picker=True)],
                  {"gap": k.STACK_MD}, w=260, note="the selected edge's pickers; persistent under the mode")
    fr = window(fid, panel([], canvas, side), [])
    return fr, ["Rule-graph edge: the edge's source and target pickers replace dragging its end (§8.1; E47-D09)",
                "The rule graph's node words are illustrative (synthetic)"]


def window(fid: str, content: k.Node, overlays: list[k.Node]) -> k.Node:
    main = k.vbox("workspace (synthetic)", [content], {"pad": k.INSET_XL, "fill": k.APP}, w=MAIN_W)
    return k.window(k.frame_name(fid), main, settings=False, overlays=overlays,
                    note="keyboard_only on: data-keyboard-only on the root (PCX:149)")


def main() -> None:
    b = k.BOARDS[NN]
    built = [order_line_frame(b.frames[0]), drawing_point_frame(b.frames[1]), rule_edge_frame(b.frames[2])]
    s81, s82 = k.L("### 8.1 The reveal pattern"), k.L("### 8.2 The inert drag")
    common = [f"§8.2 L{s82}: the drag handle is a pointer target only; beside it \"{k.w('W-20')}\" (W-20) is persistent "
              "text while the mode is on, and a drag moves nothing",
              f"§8.1 L{s81}: toggling the mode on, the switch speaks its own state and one polite status adds only "
              f"\"{k.w('W-19')}\" (W-19); outside the mode a click selects the handle and opens its fields (2.5.7)"]
    blocks = [(fid, lines + common if i == 0 else lines) for i, (fid, (_f, lines)) in enumerate(zip(b.frames, built))]
    k.ambiguity("Board 08: the hosts are not built (S07:8–11) and their forms are E47-D09's: each frame draws the "
                "reveal pattern on a synthetic panel (placeholder header, seeded candles), the field labels as copy gaps")
    k.fallback("chrome")
    p, md, pk = k.build(NN, [f for f, _l in built], blocks, per_row=3)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
