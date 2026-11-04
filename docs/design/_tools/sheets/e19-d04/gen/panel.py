"""E19-D04 host pieces, copied from the E19-D03 kit's gen/frames.py (the SCR-038 docked panel beside its bound SCR-030
chart, the CMP-183 plot, CMP-199 legend, controls, chips, the T2 lock) and cut to what these flows draw: one session,
no TPO, no naked POCs (the world holds one session, so the nPOC button is absent, k = 0). D03's words come from D03's
deck through k.W3; every number is the kit's synthetic world (seed 439). Two changes from the copy: a node glyph is
drawn when its line clears the previous one (the copy's branches were swapped), and the docked host draws into any
region of a window (board 07's two panes)."""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e19d04kit as k  # noqa: E402
from e19d04kit import S, Node, box, ellipse, hbox, icon, rect, text, vbox  # noqa: E402

TOP_H, STATUS_H = 40, 24  # TopBar and StatusBar placeholders (FALLBACKS chrome)
CHART_HEAD, TIME_AXIS, PRICE_AXIS = 28, 20, 64
DENSITY = {"compact": {"inset": k.INSET_SM, "row": 24}}  # D03 §10.1 compact (the only density these flows draw)


# --- words
def say(chars: str, doc: str | None = None) -> str:
    """A drawn word that stands verbatim in a source."""
    S(chars, doc)
    k.copy_key(f'"{chars}" ({k.SL(chars, doc)})')
    return chars


def gap_word(chars: str, src: str) -> str:
    k.copy_gap(f'"{chars}": {src}')
    return chars


def price(ticks: int | Decimal) -> str:
    """A price in USDT from integer ticks, grouped, at the tick's decimals (`67,680.0`)."""
    v = (Decimal(ticks) * k.TICK).quantize(k.TICK)
    return f"{v:,.{k.PRICE_DP}f}"


# --- small pieces
def hidden(chars: str, *, w: int = 360, label: str = "visually hidden") -> Node:
    """A string a screen reader hears, drawn for the board (FALLBACKS hidden)."""
    k.fallback("hidden")
    k.copy_gap(f'"{label}": the kit\'s marker label for a string a screen reader hears (board marker)')
    return vbox(f"board marker · {label}", [text("marker", label, k.CAPTION, k.TEXT_3, w=w - 16),
                                            text("words", chars, k.CAPTION, k.TEXT_2, w=w - 16)],
                {"gap": k.STACK_XS, "pad": k.INSET_SM, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                 "strokeAlign": "inner", "radius": k.R_CONTROL, "fill": k.SUNKEN}, w=w,
                note="board marker: not on screen in the product")


def marker_box(name: str, lines: list[str], *, w: int = 320, title: str | None = None,
               extra: list[Node] | None = None) -> Node:
    """A board marker box: a click path, a measurement or a reading note beside a specimen (never product UI)."""
    k.fallback("busy-free")
    kids = ([text("title", title, k.LABEL, k.TEXT_1, w=w - 16)] if title else []) + [
        text(f"line {i:02d}", ln, k.CAPTION, k.TEXT_2, w=w - 16) for i, ln in enumerate(lines, 1)] + (extra or [])
    return vbox(f"board marker · {name}", kids, {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.CANVAS,
                                                "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                                                "strokeAlign": "inner", "radius": k.R_CARD}, w=w,
                note="board marker, not product UI")


def chevron(color: str = k.TEXT_2) -> Node:
    return icon("chevron-down", "chevron-down", color, k.ICON_SM)


def control(name: str, label: str, *, menu: bool = False, h: int = 24, pressed: bool = False, t2: bool = False,
            lead: Node | None = None, focused: bool = False, typo: str = k.CAPTION, expanded: bool = False) -> Node:
    """A CMP-001 / CMP-041 trigger. T2 (§1.4): label tertiary, CMP-019 lock leading, the raised fill with a 1 px
    default border, never the disabled tokens. Focused: the 2 px focus ring. Expanded: a menu trigger whose menu is
    open (aria-expanded="true"), drawn pressed."""
    kids: list[Node | None] = [lock() if t2 else lead,
                               text("label", label, typo, k.TEXT_3 if t2 else k.TEXT_1),
                               chevron(k.TEXT_3 if t2 else k.TEXT_2) if menu else None]
    o: dict[str, Any] = {"padX": k.INSET_SM, "gap": k.INSET_XS, "radius": k.R_CONTROL,
                         "fill": k.SELECTED if (pressed or expanded) else (k.RAISED if t2 else k.ACTION_SECONDARY),
                         "stroke": k.RING if focused else k.BORDER, "strokeWidth": k.FOCUS_W if focused else k.HAIR,
                         "strokeAlign": "outer" if focused else "inner"}
    note = ("T2: aria-disabled=\"true\", never disabled; the reason by aria-describedby (§1.4)" if t2 else
            'aria-expanded="true": its menu is open' if expanded else None)
    return hbox(name, kids, o, h=h, note=note)


def lock() -> Node:
    """CMP-019 lock (decorative=false, name "Not available"), color.text.tertiary (§1.4 G-T2.2)."""
    return icon("CMP-019 lock", "locked", k.TEXT_3, k.ICON_SM, note='CMP-019 Icon "lock", accessible name '
                                                                   '"Not available"')


def stepper(name: str, value: str, *, h: int = 24, w: int = 64) -> Node:
    """CMP-008 stepper: the value with its up / down steps."""
    steps = hbox("steps", [icon("arrow-down", "arrow-down", k.TEXT_2, k.ICON_SM),
                           icon("arrow-up", "arrow-up", k.TEXT_2, k.ICON_SM)], None, w=24, h=12)
    return hbox(name, [text("value", value, k.NUM_SM, k.TEXT_1), box("spring", [], w=max(2, w - 8 - 24 - round(
        k.text_w(value, k.NUM_SM))), h=2), steps], {"padX": k.INSET_XS, "radius": k.R_CONTROL, "fill": k.SUNKEN,
                                                    "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                                    "strokeAlign": "inner"}, w=w, h=h)


def labelled(name: str, label: str, ctl: Node) -> Node:
    return hbox(name, [text("label", label, k.CAPTION, k.TEXT_2), ctl], {"gap": k.INSET_XS}, h=ctl["h"])


def chip(name: str, words: str, *, kind: str = "info", glyph: str | None = "info", strong_border: bool = False,
         note: str | None = None) -> Node:
    """CMP-011 chip (info: color.status.info.subtle fill, the glyph in .strong, words in color.text.primary); kind
    "armed" is E14's armed-tool chip (§11: color.surface.raised, color.border.strong, type.ui.caption)."""
    fill, ink = {"info": (k.INFO_SUBTLE, k.INFO_STRONG), "warning": (k.WARN_SUBTLE, k.WARN_STRONG),
                 "danger": (k.DANGER_SUBTLE, k.DANGER_STRONG), "neutral": (k.RAISED, k.TEXT_2),
                 "armed": (k.RAISED, k.TEXT_2)}[kind]
    kids = [icon("glyph", glyph, ink, k.ICON_SM) if glyph else None, text("words", words, k.CAPTION, k.TEXT_1)]
    return hbox(name, kids, {"padX": k.INSET_SM, "gap": k.INSET_XS, "radius": k.R_BADGE, "fill": fill,
                             "stroke": k.BORDER_STRONG if (strong_border or kind == "armed") else k.BORDER,
                             "strokeWidth": k.HAIR, "strokeAlign": "inner"}, h=20, note=note)


# --- the price scale and the chart (SCR-030 price pane: the docked panel's bound chart)
@dataclass(frozen=True)
class Scale:
    lo: Decimal  # ticks at y_bot
    hi: Decimal  # ticks at y_top
    y_top: float
    y_bot: float

    def y(self, ticks: float | Decimal) -> float:
        return float(self.y_bot - (Decimal(str(ticks)) - self.lo) / (self.hi - self.lo) * Decimal(
            str(self.y_bot - self.y_top)))


def fit_scale(lo_t: int, hi_t: int, y_top: float, y_bot: float, want_top: float, want_bot: float) -> Scale:
    """The price range a chart shows so that [lo_t, hi_t] lands on [want_bot, want_top] of a plot spanning
    [y_top, y_bot] (solved, never typed)."""
    span = Decimal(hi_t - lo_t) / Decimal(str(want_bot - want_top))
    hi = Decimal(hi_t) + span * Decimal(str(want_top - y_top))
    lo = Decimal(lo_t) - span * Decimal(str(y_bot - want_bot))
    return Scale(lo, hi, y_top, y_bot)


def nice_step(span_ticks: Decimal, px: float, min_px: int = 56) -> int:
    """The price-axis label step in ticks: the smallest of 1-2-5 × 10^n giving >= min_px between labels."""
    for e in range(0, 8):
        for m in (1, 2, 5):
            step = m * 10 ** e
            if float(step) / float(span_ticks) * px >= min_px:
                return step
    return 10 ** 8


def candles(bars: list[k.Bar], sc: Scale, x0: float, slot: float) -> list[Node]:
    out = []
    for i, b in enumerate(bars):
        cx = x0 + i * slot + slot / 2
        bw = max(1, round(slot * 0.6))
        up = b.c >= b.o
        ink = k.CANDLE_UP if up else k.CANDLE_DOWN
        top, bot = sc.y(max(b.o, b.c)), sc.y(min(b.o, b.c))
        out.append(rect(f"wick {i:03d}", 1, max(1, round(sc.y(b.l) - sc.y(b.h))), k.WICK, x=round(cx), y=round(
            sc.y(b.h))))
        out.append(rect(f"body {i:03d}", bw, max(1, round(bot - top)), ink, x=round(cx - bw / 2), y=round(top)))
    return out


def price_axis(sc: Scale, x: float, w: int, *, last: int | None = None, grid_w: float = 0) -> list[Node]:
    """Labels every nice step, grid lines across the plot, the last-price label."""
    step = nice_step(sc.hi - sc.lo, sc.y_bot - sc.y_top)
    p = int(math.ceil(float(sc.lo) / step)) * step
    out: list[Node] = []
    while p <= sc.hi:
        y = sc.y(p)
        if sc.y_top + 6 <= y <= sc.y_bot - 6:
            if grid_w:
                out.append(rect(f"grid {p}", round(grid_w), 1, k.GRID, x=0, y=round(y)))
            out.append(text(f"tick label {p}", price(p), k.NUM_SM, k.AXIS_TEXT, x=round(x + 6), y=round(y - 7)))
        p += step
    if last is not None:
        y = sc.y(last)
        out.append(hbox("last price label", [text("price", price(last), k.NUM_SM, k.TEXT_1)],
                        {"padX": k.INSET_XS, "fill": k.SELECTED, "radius": k.R_CONTROL}, w=w - 2, h=16,
                        x=round(x + 1), y=round(y - 8)))
    return out


def time_axis(bars: list[k.Bar], slot: float, y: float, every: int) -> list[Node]:
    return [text(f"tick label t{i:03d}", f"{b.start:%H:%M}", k.NUM_SM, k.AXIS_TEXT, x=round(i * slot), y=round(y + 3))
            for i, b in enumerate(bars) if b.start.minute % (every * 5) == 0]


def chrome(w: int, h: int) -> list[Node]:
    """TopBar and StatusBar placeholders (no words; FALLBACKS chrome). No environment control or badge (R-1)."""
    k.fallback("chrome")
    return [box("TopBar (placeholder)", [rect("rule", w, 1, k.BORDER, x=0, y=TOP_H - 1)], {"fill": k.RAISED}, w=w,
                h=TOP_H, x=0, y=0),
            box("StatusBar (placeholder)", [rect("rule", w, 1, k.BORDER, x=0, y=0)], {"fill": k.RAISED}, w=w,
                h=STATUS_H, x=0, y=h - STATUS_H)]


@dataclass
class ChartGeo:
    """The bound chart's plot in PANE coordinates (x from the plot's left, y from the pane's top): bar time -> x,
    price -> y; (ox, oy) is the pane's origin in the window."""
    bars: list[k.Bar]
    plot_w: float
    slot: float
    h: float  # the pane's height
    sc: Scale  # pane-local
    ox: float
    oy: float

    def x_at(self, t: datetime) -> float:
        """The left edge of the bar opening at t (a bar boundary); t may lie one bar past the last bar."""
        return int((t - self.bars[0].start) / k.BAR) * self.slot

    def x_mid(self, t: datetime) -> float:
        return self.x_at(t) + self.slot / 2

    def y(self, ticks: float | Decimal) -> float:
        return self.sc.y(ticks)

    @property
    def plot_top(self) -> float:
        return CHART_HEAD

    @property
    def plot_bot(self) -> float:
        return self.h - TIME_AXIS


UNDER = frozenset({"profile range band"})


def chart_pane(bars: list[k.Bar], slots: int, x: int, w: int, top: int, bot: int, sc: Scale, *,
               status: list[Node] | None = None, extra: Callable[[ChartGeo], list[Node]] | None = None,
               shade: bool = False, name: str = "SCR-030 price pane") -> tuple[Node, ChartGeo]:
    """The SCR-030 price pane: header strip (symbol, interval, the status row's chips these flows touch), plot (grid,
    candles), price axis, time axis; extra(geo) = marks in the pane's coordinates, drawn over the candles."""
    plot_w = w - PRICE_AXIS
    slot = plot_w / slots
    loc = replace(sc, y_top=sc.y_top - top, y_bot=sc.y_bot - top)
    g = ChartGeo(bars, plot_w, slot, bot - top, loc, x, top)
    marks = extra(g) if extra else []
    under = [n for n in marks if n.get("name") in UNDER]  # fills drawn behind the candles (the range band)
    kids: list[Node] = [rect("plot", plot_w, bot - top, k.CANVAS, x=0, y=0), *under]
    kids += price_axis(loc, plot_w, PRICE_AXIS, last=bars[-1].c, grid_w=plot_w)
    kids += candles(bars, loc, 0, slot)
    kids += time_axis(bars, slot, bot - top - TIME_AXIS, 6)
    if shade:
        k.fallback("scrim")
        kids.append(rect("E17 stale shade", plot_w, bot - top - TIME_AXIS, k.STALE_SURFACE, {"opacity": k.SCRIM},
                         x=0, y=0, note="E17's shade over the stale pane (D02E17 L64–65)"))
    kids += [n for n in marks if n.get("name") not in UNDER]
    head = [text("symbol", say(k.SYMBOL), k.LABEL, k.TEXT_1),
            text("interval", gap_word(k.INTERVAL, "the bound chart's interval word (kit world: 5-minute bars)"),
                 k.CAPTION, k.TEXT_2), *(status or [])]
    kids.append(hbox("chart header · status row", head, {"gap": k.INSET_SM, "padX": k.INSET_SM}, h=CHART_HEAD, x=0,
                     y=0, note="the status row's chip slot: only the chips these flows touch are drawn"))
    return box(name, kids, {"clip": True, "fill": k.CANVAS}, w=w, h=bot - top, x=x, y=top), g


# --- the plot (CMP-183 rows of CMP-110)
@dataclass
class PlotOpts:
    inset: int = 8
    words: bool = True
    nodes: bool = True  # HVN / LVN marking (a preset's held key)
    developing_edge: str | None = None


@dataclass
class Geo:
    x_axis: float  # the bars' zero (the plot's left, after the bracket lane)
    run: float
    sign: int
    lane_x: float
    gut_x: float
    right: float
    w: float


def geo(w: float, o: PlotOpts) -> Geo:
    run = w - 2 * o.inset - k.BRACKET_LANE - k.GUTTER_W
    return Geo(o.inset + k.BRACKET_LANE, run, 1, o.inset, o.inset + k.BRACKET_LANE + run, w - o.inset, w)


def row_y(pr: k.Profile, sc: Scale, r: int, n: int = 1) -> tuple[float, float]:
    """A drawn row's top and height, from the chart's price -> y of the same frame."""
    top, bot = sc.y((r + n) * pr.row_ticks), sc.y(r * pr.row_ticks)
    return top, bot - top


def level_y(pr: k.Profile, sc: Scale, r: int) -> float:
    t, h = row_y(pr, sc, r)
    return t + h / 2


def bar_len(v: int, top: int, run: float) -> int:
    return max(1, round(v / top * run)) if v else 0


LINE_H = 12  # one type.num.xs line (10 px × 1.2)


def glyph(name: str, ch: str, x: float, y: float, color: str = k.TEXT_2) -> Node:
    k.fallback("glyph")
    return text(name, ch, k.NUM_XS, color, x=round(x), y=round(y - 6))


def bars(pr: k.Profile, sc: Scale, g: Geo, o: PlotOpts, y_min: float, y_max: float) -> list[Node]:
    """One volume bar per row (value-area rows in color.profile.valuearea), the HVN / LVN glyphs when marking is on
    (a glyph is skipped when its line would touch the previous one of its kind)."""
    out: list[Node] = []
    top = pr.max_vol
    last_glyph = {"HVN": -1e9, "LVN": -1e9}
    for r in pr.rows:
        v = pr.lv(r).vol
        y, h = row_y(pr, sc, r)
        if y + h < y_min or y > y_max or v == 0:
            continue
        hh = h - 1 if h >= 3 else h
        tag = f"{pr.price(r) / k.TICK:.0f}"
        ln = bar_len(v, top, g.run)
        out.append(rect(f"bar {tag}", ln, max(1, round(hh)), k.P_VA if pr.va[0] <= r <= pr.va[1] else k.P_BAR,
                        x=round(g.x_axis), y=round(y)))
        if not o.nodes:
            continue
        for word, rows_, ch, gx in (("HVN", pr.hvn, "▶", g.x_axis + ln + 2), ("LVN", pr.lvn, "◀", g.x_axis - 7)):
            if r in rows_:
                if abs(y - last_glyph[word]) >= LINE_H:
                    last_glyph[word] = y
                    out.append(glyph(f"{word} glyph {tag}", ch, gx, y + h / 2))
                else:
                    k.reading("a node glyph (▶ / ◀) whose line would touch the previous one of its kind is not drawn "
                              "(the E19-D03 kit's R-K6)")
    return out


@dataclass
class Label:
    key: str
    lines: list[str]
    want: float
    ink: str
    y: float = 0


def stack(labels: list[Label], y_min: float, y_max: float, line: float = LINE_H) -> list[Label]:
    """Labels that would collide stack from their levels in steps of one line; one pushed past the plot is dropped."""
    placed: list[Label] = []
    for a in sorted(labels, key=lambda a: a.want):
        y = a.want - len(a.lines) * line / 2
        if placed:
            y = max(y, placed[-1].y + len(placed[-1].lines) * line + 2)
        a.y = y
        placed.append(a)
    for i in range(len(placed) - 1, -1, -1):
        a = placed[i]
        lim = y_max - len(a.lines) * line if i == len(placed) - 1 else placed[i + 1].y - len(a.lines) * line - 2
        a.y = min(a.y, lim)
    return [a for a in placed if a.y >= y_min - 0.5 and a.y + len(a.lines) * line <= y_max + 0.5]


def draw_labels(labels: list[Label], x: float) -> list[Node]:
    out = []
    for a in labels:
        for j, ln in enumerate(a.lines):
            out.append(text(f"{a.key} · line {j + 1}", ln, k.NUM_XS, k.TEXT_1, x=round(x), y=round(a.y + j * LINE_H)))
        mid = a.y + len(a.lines) * LINE_H / 2
        if abs(mid - a.want) > 1.5:
            y0, y1 = sorted((a.want, mid))
            out.append(rect(f"{a.key} · leader", 1, max(1, round(y1 - y0)), a.ink, x=round(x - 3), y=round(y0)))
    return out


def level_marks(pr: k.Profile, sc: Scale, g: Geo, o: PlotOpts, y_min: float, y_max: float) -> tuple[list[Node],
                                                                                                   list[Label]]:
    """The POC rail, the value-area bracket, its caps (none on a developing edge) and gutter ticks; the labels."""
    out: list[Node] = []
    labels: list[Label] = []
    y, h = row_y(pr, sc, pr.poc)
    if y_min <= y <= y_max:
        for edge, yy in (("top", y), ("bottom", y + h - 1)):
            out.append(rect(f"POC rail {edge}", round(g.right - g.x_axis), 1, k.P_POC, x=round(g.x_axis),
                            y=round(yy)))
    vah_t, _ = row_y(pr, sc, pr.va[1])
    val_t, val_h = row_y(pr, sc, pr.va[0])
    top_y, bot_y = max(vah_t, y_min), min(val_t + val_h, y_max)
    bx = g.lane_x + 1
    out.append(rect("VA bracket", 2, max(1, round(bot_y - top_y)), k.P_VA, x=round(bx), y=round(top_y)))
    for edge, yy in (("VAH", vah_t), ("VAL", val_t + val_h - 2)):
        if edge != o.developing_edge and y_min <= yy <= y_max:
            out.append(rect(f"VA bracket cap {edge}", 6, 2, k.P_VA, x=round(bx), y=round(yy)))
    for word, r in (("VAH", pr.va[1]), ("VAL", pr.va[0])):
        yy = level_y(pr, sc, r)
        if y_min <= yy <= y_max:
            out.append(rect(f"{word} tick", 6, 2, k.P_VA, x=round(g.gut_x), y=round(yy - 1)))
    if o.words:
        for word, r, ink in (("POC", pr.poc, k.P_POC), ("VAH", pr.va[1], k.P_VA), ("VAL", pr.va[0], k.P_VA)):
            labels.append(Label(f"level {word}", [say(word), price(r * pr.row_ticks)], level_y(pr, sc, r), ink))
    return out, labels


def plot(pr: k.Profile, sc: Scale, w: int, y0: float, y1: float, o: PlotOpts) -> Node:
    """The CMP-183 plot on color.surface.canvas, clipped; rows at the bound chart's price -> y (sc in the panel's
    coordinates: y0 is subtracted here)."""
    loc = replace(sc, y_top=sc.y_top - y0, y_bot=sc.y_bot - y0)
    g = geo(w, o)
    hgt = y1 - y0
    kids: list[Node] = bars(pr, loc, g, o, 0, hgt)
    lm, ll = level_marks(pr, loc, g, o, 0, hgt)
    kids += lm
    kids += draw_labels(stack(ll, 2, hgt - 2), g.gut_x + 8)
    return box("CMP-183 plot", kids, {"clip": True, "fill": k.CANVAS}, w=w, h=round(hgt), x=0, y=round(y0))


# --- SCR-038 docked panel (D03 §10.1): header band + controls row on color.surface.raised, plot on the canvas, legend
@dataclass
class Panel:
    pr: k.Profile
    period: str = "Session"
    preset: k.Preset = k.BUILTIN  # the held keys on screen (row size, VA %, VWAP, nodes) come from it
    row_ticks: int | None = None  # a held key changed by hand (Modified): overrides the preset's
    presets_label: str | None = None  # None: W-1 "Presets"
    presets_expanded: bool = False
    presets_focused: bool = False
    period_expanded: bool = False
    status: list[Node] = field(default_factory=list)  # the panel's status slot (D02 W-18 when stale)
    legend_extra: list[str] = field(default_factory=list)  # a range's two times in words (R-2)
    link: str | None = None  # the link words W-33 / W-34, drawn after the link glyph (§4.2)
    shade: bool = False  # CMP-078 stale shade over the plot
    body_note: str | None = None
    hint: str | None = None  # a mode hint in the header (W-23 replaces D02 W-30 there, §3.1)

    @property
    def rows_shown(self) -> int:
        return self.row_ticks or self.preset.row_ticks


def header(p: Panel, w: int) -> Node:
    d = DENSITY["compact"]
    rh = d["row"]
    inner = w - 2 * k.PX[d["inset"]]
    align = k.W(2, doc="d02", symbol=k.SYMBOL, interval=k.INTERVAL)
    state = k.W3(11) if p.pr.complete else k.W3(10, **{"HH:MM": k.hm(k.NOW)})
    title = hbox("title row", [text("title", k.W(1, doc="d02"), k.LABEL, k.TEXT_1),
                               text("state", state, k.CAPTION, k.TEXT_2),
                               control("alignment status", align, menu=True, h=rh - 4, typo=k.CAPTION)],
                 {"gap": k.INSET_SM, "wrap": "wrap", "align": "center"}, w=inner)
    rows: list[Node] = [title]
    if p.hint:
        rows.append(text("hint", p.hint, k.CAPTION, k.TEXT_2, w=inner, note="the mode hint (D02 L314's slot)"))
    if p.status:
        rows.append(hbox("status slot", p.status, {"gap": k.INSET_XS, "wrap": "wrap"}, w=inner))
    plabel = p.presets_label or k.W(1)
    ctl = [labelled("period", say("Period"), control("period menu", say(p.period), menu=True, h=rh,
                                                      expanded=p.period_expanded)),
           labelled("input", say("Input"), control("input menu", say("Volume"), menu=True, h=rh)),
           labelled("va", say("VA%"), stepper("VA % stepper", str(p.pr.va_pct), h=rh, w=52)),
           labelled("row", say("Row"), stepper("row size stepper", str(p.pr.row_ticks), h=rh, w=60)),
           control("VWAP toggle", say("VWAP"), h=rh, pressed=p.preset.vwap),
           hbox("switch", [control("Histogram", k.W(29, 0, doc="d02"), h=rh, pressed=True),
                           control("Table", k.W(29, 1, doc="d02"), h=rh)], None, h=rh,
                note="the Histogram │ Table switch (D02 W-29)"),
           control("Presets menu button", plabel, menu=True, h=rh, expanded=p.presets_expanded,
                   focused=p.presets_focused),
           control("settings", say("Settings"), h=rh)]
    rows.append(hbox("controls row", ctl, {"gap": k.INSET_XS, "wrap": "wrap"}, w=inner,
                     note="wraps, never truncates (D03 §10.1)"))
    return vbox("header band", rows, {"gap": k.STACK_XS, "padX": d["inset"], "padY": k.INSET_XS, "fill": k.RAISED},
                w=w)


def swatch(name: str, kids: list[Node], h: int = 8) -> Node:
    """A 12 × h px color.surface.canvas key swatch with its mark (plot inks only on the canvas, D03 §10.1): 8 px for
    the value-area bar, 12 px for the HVN / LVN glyph marks (live-check fold: the glyph's line is 12 px)."""
    return box(f"key · {name}", kids, {"clip": True, "fill": k.CANVAS}, w=12, h=h)


def link_glyph() -> Node:
    """The link glyph stand-in (FALLBACKS link): two interlocked rings, never alone (R-2)."""
    k.fallback("link")
    o = {"stroke": k.TEXT_2, "strokeWidth": k.HAIR, "strokeAlign": "inner"}
    return box("link glyph", [ellipse("ring a", 7, 5, o, x=0, y=3), ellipse("ring b", 7, 5, o, x=5, y=3)], w=12, h=12,
               note="decorative: the words beside it carry the state (R-2); CanvasText under forced colours (§4.2)")


def link_row(words: str, w: int) -> Node:
    t = text("words", words, k.CAPTION, k.TEXT_2, w=w - 16)
    return hbox("link · W-33", [link_glyph(), t], {"gap": k.INSET_XS, "align": "start"}, w=w,
                h=max(16, math.ceil(k.est_height(t))),
                note="the legend's link words, type.ui.caption color.text.secondary (§11); in the drawing's "
                     "accessible name and tree row too (§4.2)")


# live-check fold: a legend key row is 14 px, the caption's line (12 px rows cut the word 1 px top and bottom)
KEY_ROW_H = 14


def legend(p: Panel, w: int) -> Node:
    d = DENSITY["compact"]
    inner = w - 2 * k.PX[d["inset"]]
    state = k.W3(11) if p.pr.complete else k.W3(10, **{"HH:MM": k.hm(k.NOW)})
    parts = [say(p.period), *p.legend_extra, state, say("Volume"),
             k.W(19, doc="d02", n=str(p.pr.row_ticks), price=price(p.pr.row_ticks)),
             k.tpl("VA 70 %", {"70": str(p.pr.va_pct)}, "d02")]
    rows: list[Node] = [text("words", " · ".join(parts), k.CAPTION, k.TEXT_2, w=inner)]
    if p.link:
        rows.append(link_row(p.link, inner))
    keys = [hbox("key value area", [swatch("value area", [rect("bar", 8, 6, k.P_VA, x=0, y=1),
                                                          rect("bracket", 2, 8, k.P_VA, x=10, y=0)]),
                                    text("word", k.tpl("Value area 70 %", {"70": str(p.pr.va_pct)}, "d02"),
                                         k.CAPTION, k.TEXT_2)], {"gap": k.INSET_XS}, h=KEY_ROW_H)]
    if p.preset.nodes:
        keys += [hbox("key HVN", [swatch("HVN", [text("glyph", "▶", k.NUM_XS, k.TEXT_2, x=3, y=0)], h=12),
                                  text("word", say("HVN"), k.CAPTION, k.TEXT_2)], {"gap": k.INSET_XS}, h=KEY_ROW_H),
                 hbox("key LVN", [swatch("LVN", [text("glyph", "◀", k.NUM_XS, k.TEXT_2, x=3, y=0)], h=12),
                                  text("word", say("LVN"), k.CAPTION, k.TEXT_2)], {"gap": k.INSET_XS}, h=KEY_ROW_H)]
    rows.append(hbox("keys", keys, {"gap": k.INSET_SM, "wrap": "wrap"}, w=inner))
    rows.append(hbox("legend controls", [control("history toggle", k.W3(6), h=d["row"])], {"gap": k.INSET_XS}, w=inner,
                     h=d["row"], note="D03's history toggle (W-6); the nPOC button is absent: one session, k = 0"))
    return vbox("CMP-199 legend", rows, {"gap": k.STACK_XS, "padX": d["inset"], "padY": k.INSET_XS,
                                         "fill": k.RAISED}, w=w)


def frame(fid: str, kids: list[Node], *, note: str | None = None) -> Node:
    w, h = k.frame_size(fid)
    return box(k.frame_name(fid), kids, {"fill": k.APP, "clip": True}, w=w, h=h, note=note)


def drawn_legend(lg: Node) -> Node:
    """The legend as its height was drawn: the live check grew its key rows 12 -> 14 px and the drawn legend kept its
    height (the caption line's estimate carries the 2 px), so the height is estimated with 12 px key rows."""
    keys = [dict(r, h=12) if str(r.get("name", "")).startswith("key ") else r
            for r in next(c for c in lg["kids"] if c["name"] == "keys")["kids"]]
    return dict(lg, kids=[dict(c, kids=keys) if c["name"] == "keys" else c for c in lg["kids"]])


def panel_parts(p: Panel, w: int, h: int) -> tuple[Node, Node, float, float]:
    hd, lg = header(p, w), legend(p, w)
    hh, lh = math.ceil(k.est_height(hd)), math.ceil(k.est_height(drawn_legend(lg)))
    hd["h"], lg["h"] = hh, lh
    return hd, lg, hh + 1, h - lh


@dataclass
class Host:
    """What a docked host drew: the chart's geometry, the panel's box in window coordinates, the header height."""
    chart: ChartGeo
    panel_x: int
    panel_y: int
    header_h: float
    plot_y0: float
    plot_y1: float


def docked(p: Panel, chart_bars: list[k.Bar], *, x: int = 0, y: int = TOP_H, w: int = k.WIN_W,
           h: int = k.WIN_H - TOP_H - STATUS_H, slots: int = k.CHART_SLOTS, chart_status: list[Node] | None = None,
           chart_extra: Callable[[ChartGeo], list[Node]] | None = None, chart_shade: bool = False,
           view: tuple[int, int] | None = None, pane: str = "") -> tuple[list[Node], Host]:
    """SCR-038 docked beside its bound chart in the region (x, y, w, h) of a window; the chart's vertical range is its
    bars' (or view), fitted so the panel's rows sit on the chart's price -> y of the same frame (D02 §4.1)."""
    pw = k.PANEL_W
    hd, lg, py0, py1 = panel_parts(p, pw, h)
    lo_t, hi_t = view or (min(b.l for b in chart_bars), max(b.h for b in chart_bars))
    ch_top, ch_bot = y + CHART_HEAD + 4, y + h - TIME_AXIS - 4
    sc = fit_scale(lo_t, hi_t, ch_top, ch_bot, y + py0 + 16, y + py1 - 16)
    chart, g = chart_pane(chart_bars, slots, x, w - pw, y, y + h, sc, status=chart_status, extra=chart_extra,
                          shade=chart_shade, name=f"SCR-030 price pane{pane}")
    psc = replace(sc, y_top=sc.y_top - y, y_bot=sc.y_bot - y)
    kids: list[Node] = [hd | {"x": 0, "y": 0}, rect("header rule", pw, 1, k.BORDER, x=0, y=round(py0 - 1))]
    o = PlotOpts(inset=k.PX[DENSITY["compact"]["inset"]], nodes=p.preset.nodes,
                 developing_edge=None if p.pr.complete else dev_edge(p.pr))
    kids.append(plot(p.pr, psc, pw, py0, py1, o))
    if p.shade:
        k.fallback("scrim")
        kids.append(rect("CMP-078 stale shade", pw, round(py1 - py0), k.STALE_SURFACE, {"opacity": k.SCRIM},
                         x=0, y=round(py0), note="CMP-078: the shade over the plot; the marks keep their shapes"))
    kids += [lg | {"x": 0, "y": round(py1)}, rect("panel edge", 1, h, k.BORDER, x=0, y=0)]
    panel = box(f"SCR-038 docked panel{pane}", kids, {"clip": True, "fill": k.CANVAS}, w=pw, h=h, x=x + w - pw, y=y,
                note=p.body_note)
    return [chart, panel], Host(g, x + w - pw, y, py0, py0, py1)


def dev_edge(pr: k.Profile) -> str:
    """The E19-D03 kit's R-K3: the developing edge is the value-area edge on the last price's side."""
    mid = (pr.va[0] + pr.va[1] + 1) * pr.row_ticks / 2
    k.reading("a developing profile's open bracket edge (no cap) is the value-area edge on the last price's side "
              "(the E19-D03 kit's R-K3)")
    return "VAH" if pr.last_ticks >= mid else "VAL"


def window(p: Panel, **kw: Any) -> tuple[list[Node], Host]:
    """A 1280 × 800 window: chrome + the docked host in the body."""
    nodes, host = docked(p, kw.pop("bars", None) or k.bars_between(k.CHART_FROM, k.NOW), **kw)
    return [*chrome(k.WIN_W, k.WIN_H), *nodes], host
