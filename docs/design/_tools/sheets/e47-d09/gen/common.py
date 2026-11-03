"""Shared pieces of the E47-D09 board generators: the kit import, CMP-022 Kbds, the seeded chart (candles, grid,
price axis, the position and order lines, the dashed pending line), the trading workspace (the chart over SCR-063),
the settings page chrome (CMP-086's list beside the content, E47-D03's SCR-116 / SCR-117 chrome), and small text
helpers. Every price comes from the kit's world (k.SERIES, k.MARK, k.SL ...), never typed here."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Iterable

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import e47d09kit as k  # noqa: E402

Node = k.Node


# --- CMP-022 Kbd (FALLBACKS kbd) and the binding cell (current binding, "remapped", "unbound")
def kbd(b: str, *, name: str | None = None, color: str = k.TEXT_1) -> Node:
    k.fallback("kbd")
    t = k.text("keys", k.kbd_words(b), k.NUM_XS, color)
    return k.hbox(name or f"CMP-022 Kbd · {b}".replace("/", k.SLASH), [t],
                  {"padX": k.INSET_XS, "radius": k.R_CONTROL, "fill": k.RAISED, "stroke": k.BORDER,
                   "strokeWidth": k.HAIR, "strokeAlign": "inner", "justify": "center"},
                  w=round(k.text_w(b, k.NUM_XS) + 2 * k.PX[k.INSET_XS] + 2), h=18)


def binding_cell(cid: str, *, color: str = k.TEXT_1) -> list[Node]:
    """§8 / §9: the current binding as a Kbd (a remap included, with W-11 "remapped" beside it), or W-7 "unbound" in
    color.text.secondary."""
    b = k.binding(cid)
    if not b:
        return [k.text("unbound", k.w("W-7"), k.BODY, k.TEXT_2)]
    out = [kbd(b, color=color)]
    if k.remapped(cid):
        out.append(k.text("remapped", k.w("W-11"), k.CAPTION, k.TEXT_2))
    return out


# --- the chart (FALLBACKS chart): 4 px per tick, 12 px per bar; the body is the panel's 984 x 412 canvas
CHART_W, CHART_H = k.MAIN_W, 412
AXIS_LABEL_H = 12  # type.num.xs, one line, measured live
AXIS_W = 72
PLOT_W = CHART_W - AXIS_W
TOP = k.tick_ladder(k.MARK, 53)  # the price at y = 0 (the visible range MARK - 50 ... MARK + 53 ticks)
X0 = 16  # the first bar's left edge


def y_of(p: Decimal) -> int:
    return int((TOP - p) / k.TICK) * k.PX_PER_TICK


def x_of(i: int) -> int:
    return X0 + i * k.BAR_W


def candles(series: Iterable[k.Bar] | None = None, group: int = 30) -> list[Node]:
    """The bars in groups of `group` (one board per group, so the section packer keeps them together)."""
    bars = list(series or k.SERIES)
    out = []
    for g0 in range(0, len(bars), group):
        chunk = bars[g0:g0 + group]
        out.append(k.box(f"candles {chunk[0].hhmm}-{chunk[-1].hhmm}".replace(":", "h"), _candles(chunk), None,
                         w=PLOT_W, h=CHART_H, x=0, y=0))
    return out


def _candles(series: Iterable[k.Bar]) -> list[Node]:
    out = []
    for b in series:
        up = b.c >= b.o
        top, bot = max(b.o, b.c), min(b.o, b.c)
        out.append(k.rect(f"wick {b.hhmm}".replace(":", "-"), 1, max(1, y_of(b.l) - y_of(b.h)), k.WICK,
                          x=x_of(b.i) + 4, y=y_of(b.h)))
        out.append(k.rect(f"body {b.hhmm}".replace(":", "-"), 8, max(2, y_of(bot) - y_of(top)),
                          k.CANDLE_UP if up else k.CANDLE_DOWN, x=x_of(b.i), y=y_of(top)))
    return out


def grid_and_axis() -> list[Node]:
    """Horizontal grid every 10 ticks with its price label on the axis (every label a price on the tick grid)."""
    grid: list[Node] = []
    axis: list[Node] = [k.rect("axis divider", 1, CHART_H, k.BORDER_SUBTLE, x=0, y=0)]
    p = k.tick_ladder(k.MARK, 50)
    while p >= k.tick_ladder(k.MARK, -50):
        y = y_of(p)
        grid.append(k.rect(f"grid {k.px_fmt(p)}", PLOT_W, 1, k.GRID, x=0, y=y))
        # an edge label is clamped inside the axis, as an engine clamps it (live check: the bottom label ran 5 px
        # past the 412 px axis at y - 7 and was cut; AXIS_LABEL_H is its measured line height)
        ly = min(max(y - 7, 0), CHART_H - AXIS_LABEL_H)
        axis.append(k.text(f"axis {k.px_fmt(p)}", k.px_fmt(p), k.NUM_XS, k.AXIS_TEXT, x=8, y=ly))
        p = k.tick_ladder(p, -10)
    return [k.box("grid", grid, None, w=PLOT_W, h=CHART_H, x=0, y=0),
            k.box("price axis", axis, None, w=AXIS_W, h=CHART_H, x=PLOT_W, y=0)]


def mark_tag() -> list[Node]:
    y = y_of(k.MARK)
    return [k.rect("mark line", PLOT_W, 1, k.CROSSHAIR, x=0, y=y),
            k.hbox("mark tag", [k.text("price", k.px_fmt(k.MARK), k.NUM_XS, k.TEXT_1)],
                   {"padX": k.INSET_XS, "fill": k.RAISED, "stroke": k.CROSSHAIR, "strokeWidth": k.HAIR,
                    "strokeAlign": "inner"}, w=AXIS_W - 4, h=16, x=PLOT_W + 2, y=y - 8,
                   note="the mark price (synthetic); the wrong side is judged against it (`11`:3056-3057)")]


def dashed(name: str, x: int, y: int, wd: int, token: str) -> Node:
    """A dashed horizontal line (FALLBACKS dashed): 8 px segments, 4 px gaps."""
    k.fallback("dashed")
    segs = [k.rect(f"dash {i:02d}", 8, 2, token, x=i * 12, y=0) for i in range(wd // 12)]
    return k.box(f"dashed · {name}", segs, None, w=wd, h=2, x=x, y=y)


LABEL_X = 744  # the line labels' left edge in the plot (right of the last bar, left of the axis)


def line_tag(chars: str, token: str, *, name: str, focused: bool = False, pending: bool = False) -> Node:
    """The order line's label (its surrogate, the trading-object stop of §4): the token's hairline and the words; a
    pending line adds the word "pending" (§4, §13: never a line style alone)."""
    kids = [k.text("label", chars, k.NUM_XS, k.TEXT_1)]
    if pending:
        kids.append(k.text("pending", "pending", k.CAPTION, k.TEXT_1))
    t = k.hbox(name, kids, {"gap": k.INSET_XS, "padX": k.INSET_XS, "fill": k.RAISED, "stroke": token,
                            "strokeWidth": k.THICK if focused else k.HAIR, "strokeAlign": "inner",
                            "radius": k.R_CONTROL},
               w=round(sum(k.est_width(x) for x in kids) + 4 * (len(kids) - 1) + 2 * 4 + 4), h=18)
    return k.focus_ring(t) if focused else t


def price_line(name: str, p: Decimal, token: str, chars: str, *, focused: bool = False, pending: bool = False,
               x_tag: int = LABEL_X) -> list[Node]:
    """A horizontal line at price p (solid, or dashed when pending) with its tag at x_tag, centred on the line."""
    y = y_of(p)
    line = dashed(name, 0, y, PLOT_W, token) if pending else k.rect(f"line · {name}", PLOT_W, 2, token, x=0, y=y)
    tag = line_tag(chars, token, name=f"tag · {name}", focused=focused, pending=pending)
    th = int(tag["h"])
    return [line, dict(tag, x=x_tag, y=y - th // 2)]


def chart_body(lines: Iterable[Node] = (), extra: Iterable[Node] = ()) -> Node:
    k.fallback("chart")
    layer = k.box("trading layer", [*mark_tag(), *lines, *extra], None, w=CHART_W, h=CHART_H, x=0, y=0)
    kids = [*grid_and_axis(), *candles(), layer]
    return k.box("plot stop · chart", kids, {"fill": k.CANVAS, "clip": True}, w=CHART_W, h=CHART_H,
                 note="the chart root: one stop; the surrogates for drawings and trading objects follow it "
                      "(D04:219); synthetic series")


def tag_text(kind: str, p: Decimal) -> str:
    return f"{kind} {k.px_fmt(p)}"


def position_lines(*, sl_focus: bool = False, sl: Decimal | None = None) -> list[Node]:
    """The long's entry, SL and TP lines at their working prices (SCR-030's trading layer)."""
    s = sl if sl is not None else k.SL
    return [*price_line("entry", k.ENTRY, k.POS_ENTRY, tag_text("Long " + k.QTY, k.ENTRY)),
            *price_line("take-profit", k.TP, k.POS_TP, tag_text("TP", k.TP)),
            *price_line("stop-loss", s, k.POS_SL, tag_text("SL", s), focused=sl_focus)]


# --- the trading workspace (SCR-020): the chart panel over SCR-063, full width (kit layout for boards 01 and 03)
CHART_PANEL_H = k.HEADER_H + CHART_H  # 440
ORDERS_PANEL_H = k.BODY_H - k.TAB_H - k.TRAY_H - CHART_PANEL_H - k.SPLIT  # 224
CB_X, CB_Y = k.NAV_W, k.TOP_H + k.TAB_H + k.HEADER_H  # the chart body's origin in frame coordinates
OP_Y = k.TOP_H + k.TAB_H + CHART_PANEL_H + k.SPLIT  # the orders panel's top in frame coordinates
ORDER_COLS = (k.Col("order", "Order", 160), k.Col("symbol", "Symbol", 120), k.Col("side", "Side", 96),
              k.Col("qty", "Qty", 120, True), k.Col("price", "Price", 160, True), k.Col("status", "Status", 160))


def orders_rows(sl: Decimal | None = None) -> list[dict[str, str]]:
    s = sl if sl is not None else k.SL
    return [{"order": "Position", "symbol": k.SYMBOL, "side": "Long", "qty": k.QTY, "price": k.px_fmt(k.ENTRY),
             "status": "Open"},
            {"order": "Stop-loss", "symbol": k.SYMBOL, "side": "Sell", "qty": k.QTY, "price": k.px_fmt(s),
             "status": "Working"},
            {"order": "Take-profit", "symbol": k.SYMBOL, "side": "Sell", "qty": k.QTY, "price": k.px_fmt(k.TP),
             "status": "Working"}]


def orders_table(*, sl: Decimal | None = None, focus: str | None = None, status: str | None = None) -> Node:
    """SCR-063 (positions and orders): the position and its two working orders; the Stop-loss row is DE-01's list
    twin ("Enter on its SCR-063 row"); its Price is the order's price at the exchange, never the pending value."""
    k.copy_gap('SCR-063 column words "Order", "Symbol", "Side", "Qty", "Price", "Status" and the row words '
               '"Position", "Stop-loss", "Take-profit", "Open", "Working": the grid\'s own (`14`:1523), not this spec\'s')
    rows = []
    for i, r in enumerate(orders_rows(sl), 1):
        cells = dict(r)
        if status and r["order"] == "Stop-loss":
            cells["status"] = status
        rows.append(k.table_row(ORDER_COLS, cells, f"row {r['order']}", i, h=k.ROW_H, focused=r["order"] == focus))
    hd = k.header_row(ORDER_COLS)
    hd = dict(hd, h=k.ROW_H, kids=[dict(x, h=k.ROW_H) for x in hd["kids"]])
    return k.table("CMP-049 grid · positions and orders", None, hd, rows,
                   note='role="grid"; one Tab stop, roving tabindex (E47-D04 R-2)')


def trading_window(fid: str, chart: Node, *, orders: Node | None = None, focus: str | None = None,
                   overlays: Iterable[Node] = (), note: str | None = None) -> Node:
    """SCR-020 with two docked panels, full width: the chart (984 x 440) over SCR-063 (984 x 224)."""
    k.fallback("density")
    chart_p = k.panel("chart", k.PANELS[0][1], chart, focused=focus == "chart", w_=k.MAIN_W, h_=CHART_PANEL_H)
    orders_p = k.panel("positions", k.PANELS[2][1], orders or orders_table(),
                       focused=focus == "positions", w_=k.MAIN_W, h_=ORDERS_PANEL_H)
    main = k.box("main · workspace", [dict(k.tabstrip(), x=0, y=0), dict(chart_p, x=0, y=k.TAB_H),
                                      dict(orders_p, x=0, y=k.TAB_H + CHART_PANEL_H + k.SPLIT),
                                      dict(k.tray(), x=0, y=k.BODY_H - k.TRAY_H)],
                 {"fill": k.BORDER_SUBTLE, "clip": True}, w=k.MAIN_W, h=k.BODY_H,
                 note="<main>; two panels, a 4 px splitter (color.border.subtle)")
    body = k.hbox("body", [k.navrail(), main, k.rightrail()], {"align": "start"}, w=k.FRAME_W, h=k.BODY_H)
    return k._frame(fid, [k.topbar(), body, k.statusbar()], overlays, note)


# --- the settings page (SCR-110's chrome, E47-D03's SCR-116 / SCR-117 pattern): CMP-086's list beside the content
SET_NAV_W = 208
CONTENT_W = k.MAIN_W - SET_NAV_W  # 776
SETTINGS_X = k.NAV_W + SET_NAV_W  # the content's left edge in frame coordinates


def settings_nav(current: str) -> Node:
    k.fallback("chrome")
    cur = k.vbox(f"entry · {current} (current)", [k.text("label", current, k.BODY_STRONG, k.TEXT_LINK),
                                                   k.rect("selected underline", 64, 2, "color.border.selected")],
                 {"gap": k.STACK_XS, "padX": k.INSET_MD, "padY": k.INSET_XS}, w=SET_NAV_W - 16,
                 note='aria-current="page"')
    ents = [k.hbox(f"entry-{i}", [k.placeholder("label", 96 + 8 * (i % 3))], {"padX": k.INSET_MD}, w=SET_NAV_W - 16,
                   h=28) for i in range(1, 6)]
    return k.vbox("CMP-086 settings list", [*ents[:3], cur, *ents[3:],
                                            k.rect("divider", 1, k.BODY_H, k.BORDER_SUBTLE, x=SET_NAV_W - 1, y=0,
                                                   abs=True)],
                  {"gap": k.INSET_XS, "pad": k.INSET_SM, "fill": k.RAISED}, w=SET_NAV_W, h=k.BODY_H)


def settings_window(fid: str, current: str, content: Node, *, overlays: Iterable[Node] = (),
                    note: str | None = None) -> Node:
    main = k.hbox("main · settings", [settings_nav(current),
                                      k.box("content", [dict(content, x=0, y=0)], {"fill": k.APP, "clip": True},
                                            w=CONTENT_W, h=k.BODY_H)],
                  {"align": "start"}, w=k.MAIN_W, h=k.BODY_H, note="<main>")
    body = k.hbox("body", [k.navrail(current=6), main, k.rightrail()], {"align": "start"}, w=k.FRAME_W, h=k.BODY_H)
    return k._frame(fid, [k.topbar(), body, k.statusbar()], overlays, note)


def say(name: str, key: str, *vals: object, x: int, y: int, wd: int = 320, head: str | None = None,
        extra: Iterable[str] = ()) -> Node:
    """A callout quoting a W-string as spoken (polite), with its key: head line, the quoted string, extra lines."""
    s = k.w(key, *vals)
    return k.callout(name, [head or f"{key}, polite:", f"“{s}”", *extra], x, y, wd)
