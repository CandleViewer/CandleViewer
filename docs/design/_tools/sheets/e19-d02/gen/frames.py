"""E19-D02 frame builders (greyscale wireframes): SCR-038 docked (§3.1) and overlay (§3.2), the axis-alignment frames
(§4), the states (§6), the edge-density cases (§7), the table and focus (§11), SCR-039 (§8, §9) and the flows (§10).
Every drawn word is the spec's (k.S checks it verbatim, k.W fills a copy-deck string) or is noted as a copy gap with
its source; every number is derived from the kit's synthetic world (seed 416). Only §2's wire tokens are bound."""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e19d02kit as k  # noqa: E402
from e19d02kit import S, Node, box, ellipse, hbox, icon, rect, text, vbox  # noqa: E402

C1, C2, C3 = k.TEXT_1, k.TEXT_2, k.TEXT_3  # the three wire greys (§2)
TOP_H, STATUS_H = 40, 24  # TopBar and StatusBar placeholders (FALLBACKS chrome)
CHART_HEAD, TIME_AXIS, PRICE_AXIS = 28, 20, 64
PANEL_W = int(S("default width 280 px")[14:17])  # §2 Docked (PROPOSED)
LABEL_W, BRACKET_W = 84, 24  # kit choice: the level-label gutter (one "VAH 63,470.0" in type.num.sm) and the VA lane
DENSITY = {"compact": {"inset": k.INSET_SM, "row": 24}, "dense": {"inset": k.INSET_XS, "row": 24},
           "comfortable": {"inset": k.INSET_MD, "row": 32}}  # rows / fields per §2 (24 / 24 / 32); insets kit choice
VIEW_AS_USER = "Sam"  # synthetic display name for W-15's {user} (kit choice; no account identifier, R-1)
INTERVAL = "30m"  # the bound chart's interval word (the world's 30-minute bars), W-2's {interval}


# --- words
def say(chars: str) -> str:
    """A drawn word that stands verbatim in the spec."""
    S(chars)
    k.copy_key(f'"{chars}" ({k.SL(chars)})')
    return chars


def cap(chars: str) -> str:
    """A spec phrase drawn in sentence case (the source writes it lower case inside a sentence or a table cell)."""
    say(chars)
    return chars[0].upper() + chars[1:]


def gap_word(chars: str, src: str) -> str:
    k.copy_gap(f'"{chars}": {src}')
    return chars


def price(ticks: int | Decimal) -> str:
    """A price in USDT from integer ticks, grouped, at the tick's decimals (`63,470.0`)."""
    v = (Decimal(ticks) * k.TICK).quantize(k.TICK)
    return f"{v:,.{k.PRICE_DP}f}"


def qty(steps: int) -> str:
    return f"{(Decimal(steps) * k.QTY_STEP):,.{k.QTY_DP}f}"


def signed_qty(steps: int) -> str:
    return ("+" if steps > 0 else "−" if steps < 0 else "") + qty(abs(steps))


def hm(t: datetime) -> str:
    return f"{t:%H:%M}"


def dmon(t: datetime) -> str:
    """The kit's date form for W-21's {from} / {to}: "10 Oct" (copy gap: §12 gives no format)."""
    k.copy_gap('date form "10 Oct" (day, month) for W-21\'s {from} / {to} and W-6\'s days: §12 gives no format')
    return f"{t.day} {t:%b}"


def interval(word: str = INTERVAL) -> str:
    k.copy_gap(f'"{word}": the bound chart\'s interval word (the world\'s 30-minute bars, or n of them as one candle), '
               'drawn in the chart header and filling W-2\'s {interval}')
    return word


# --- small pieces
def marker(name: str, lines: list[str], *, w: int = 300, title: str | None = None) -> Node:
    """A board marker box: a measurement, an order or a reading beside a specimen (never product UI)."""
    k.fallback("marker")
    kids = ([text("title", title, k.LABEL, C1, w=w - 16)] if title else []) + [
        text(f"line {i:02d}", ln, k.CAPTION, C2, w=w - 16) for i, ln in enumerate(lines, 1)]
    return vbox(f"board marker · {name}".replace("/", k.SLASH), kids, {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.CANVAS,
                                                "stroke": C1, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                                                "radius": k.R_CARD}, w=w, note="board marker, not product UI")


def hidden(chars: str, *, w: int = 300, label: str = "visually hidden") -> Node:
    """A string a screen reader hears, drawn for the board (FALLBACKS hidden)."""
    k.fallback("hidden")
    return marker(label, [chars], w=w, title=gap_word(label, "the kit's marker title for a string a screen reader "
                                                              "hears (board marker)"))


def sized(n: Node) -> Node:
    """A flex box given its estimated w and h (so it can sit absolutely inside a non-flex parent)."""
    return dict(n, w=n.get("w") or math.ceil(k.est_width(n)), h=n.get("h") or math.ceil(k.est_height(n)))


def chevron(color: str = C2) -> Node:
    return icon("chevron-down", "chevron-down", color)


def lock() -> Node:
    """CMP-019 lock (decorative=false, name "Not available"), color.text.tertiary (§1.4 G-T2.1d, G-T2.2)."""
    return icon("CMP-019 lock", "locked", C3, note='CMP-019 Icon "lock", decorative=false, accessible name "Not '
                                                   'available"')


def control(name: str, label: str, *, menu: bool = False, h: int = 24, pressed: bool = False, t2: bool = False,
            focused: bool = False, lead: Node | None = None, tag: str | None = None, note: str | None = None) -> Node:
    """A button / menu button at the density's height (wire: raised fill, default hairline). Pressed: the label in
    color.text.primary on canvas with a 2 px outline-free underline (aria-pressed). T2 (§1.4): CMP-019 lock leading,
    the full label in color.text.tertiary, raised fill + default hairline, never the disabled tokens. Focused: the
    2 px color.text.primary outline (FALLBACKS focus)."""
    kids: list[Node | None] = [lock() if t2 else lead, text("label", label, k.CAPTION, C3 if t2 else C1),
                               text("tag", tag, k.CAPTION, C2) if tag else None,
                               chevron(C3 if t2 else C2) if menu else None]
    if focused:
        k.fallback("focus")
    o: dict[str, Any] = {"padX": k.INSET_SM, "gap": k.INSET_XS, "radius": k.R_CONTROL,
                         "fill": k.CANVAS if pressed else k.RAISED,
                         "stroke": C1 if (focused or pressed) else k.BORDER,
                         "strokeWidth": k.THICK if focused else k.HAIR, "strokeAlign": "outer" if focused else "inner"}
    note = note or ('T2: aria-disabled="true", never disabled; in the Tab order; the reason by aria-describedby (§1.4)'
                    if t2 else ('aria-pressed="true"' if pressed else None))
    return hbox(name, kids, o, h=h, note=note)


def stepper(name: str, value: str | None, *, h: int = 24, w: int = 64, invalid: bool = False) -> Node:
    """CMP-008 stepper: the value with its down / up steps (sunken look as a canvas field with a hairline)."""
    steps = hbox("steps", [icon("arrow-down", "arrow-down", C2), icon("arrow-up", "arrow-up", C2)], None, w=24, h=12)
    val = [text("value", value, k.NUM_SM, C1)] if value else []
    spring = w - 8 - 24 - (round(k.text_w(value, k.NUM_SM)) if value else 0)
    return hbox(name, [*val, box("spring", [], w=max(2, spring), h=2), steps],
                {"padX": k.INSET_XS, "radius": k.R_CONTROL, "fill": k.CANVAS, "stroke": C1 if invalid else k.BORDER,
                 "strokeWidth": k.THICK if invalid else k.HAIR, "strokeAlign": "inner"}, w=w, h=h,
                note='aria-invalid="true"; aria-describedby its CMP-040 error' if invalid else None)


def labelled(name: str, label: str, ctl: Node) -> Node:
    return hbox(name, [text("label", label, k.CAPTION, C2), ctl], {"gap": k.INSET_XS}, h=ctl["h"])


def chip(name: str, words: str, glyph: str | None = "info", *, note: str | None = None) -> Node:
    """A status chip (CMP-011 / the corner tag): glyph + words on raised with a hairline (wire)."""
    kids = [icon("glyph", glyph, C2) if glyph else None, text("words", words, k.CAPTION, C1)]
    return hbox(name, kids, {"padX": k.INSET_SM, "gap": k.INSET_XS, "radius": k.R_BADGE, "fill": k.RAISED,
                             "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, h=20, note=note)


def estimated_badge() -> Node:
    """CMP-227 `section` grade: W-8 after the title (§6 approximated), with the hatch-slot key."""
    k.fallback("hatch")
    return hbox("CMP-227 estimated", [box("key · estimated slot", [], {"fill": k.CANVAS, "stroke": C1,
                                                                      "strokeWidth": k.HAIR, "strokeAlign": "inner"},
                                          w=12, h=8),
                                      text("words", k.W(8), k.CAPTION, C1)],
                {"padX": k.INSET_SM, "gap": k.INSET_XS, "radius": k.R_BADGE, "fill": k.RAISED, "stroke": C1,
                 "strokeWidth": k.HAIR, "strokeAlign": "inner"}, h=20,
                note='CMP-227 section: opens the methodology drawer (SCR-058); methodology "approximated from bars"')


# --- the price scale and the chart (SCR-030 price pane: the docked panel's bound chart, or the overlay's host)
@dataclass(frozen=True)
class Scale:
    lo: Decimal  # ticks at y_bot
    hi: Decimal  # ticks at y_top
    y_top: float
    y_bot: float
    log: bool = False  # `26`:221's log mapping
    pct_base: int | None = None  # percent mode (alignment cannot hold): the base price in ticks

    def y(self, ticks: float | Decimal) -> float:
        t = Decimal(str(ticks))
        if self.log:
            f = (t.ln() - self.lo.ln()) / (self.hi.ln() - self.lo.ln())
        else:
            f = (t - self.lo) / (self.hi - self.lo)
        return float(Decimal(str(self.y_bot)) - f * Decimal(str(self.y_bot - self.y_top)))

    def shift(self, dy: float) -> "Scale":
        return replace(self, y_top=self.y_top - dy, y_bot=self.y_bot - dy)


def fit_scale(lo_t: int, hi_t: int, y_top: float, y_bot: float, want_top: float, want_bot: float, *,
              log: bool = False) -> Scale:
    """The price range a chart shows so that [lo_t, hi_t] lands on [want_bot, want_top] of a plot spanning
    [y_top, y_bot] (solved, never typed)."""
    if log:
        a, b = Decimal(lo_t).ln(), Decimal(hi_t).ln()
        span = (b - a) / Decimal(str(want_bot - want_top))
        return Scale((a - span * Decimal(str(y_bot - want_bot))).exp(), (b + span * Decimal(str(want_top - y_top)))
                     .exp(), y_top, y_bot, log=True)
    span = Decimal(hi_t - lo_t) / Decimal(str(want_bot - want_top))
    return Scale(Decimal(lo_t) - span * Decimal(str(y_bot - want_bot)), Decimal(hi_t) + span * Decimal(str(
        want_top - y_top)), y_top, y_bot)


def nice_step(span_ticks: Decimal, px: float, min_px: int = 56) -> int:
    """The price-axis label step in ticks: the smallest of 1-2-5 × 10^n ticks giving >= min_px between labels."""
    for e in range(0, 9):
        for m in (1, 2, 5):
            step = m * 10 ** e
            if float(step) / float(span_ticks) * px >= min_px:
                return step
    return 10 ** 9


def candles(bars: list[k.Bar], sc: Scale, x0: float, slot: float) -> list[Node]:
    """Grey candles (FALLBACKS chart): wick and body in color.text.tertiary; direction not encoded."""
    out = []
    for i, b in enumerate(bars):
        cx = x0 + i * slot + slot / 2
        bw = max(1, round(slot * 0.6))
        top, bot = sc.y(max(b.o, b.c)), sc.y(min(b.o, b.c))
        out.append(rect(f"wick {i:03d}", 1, max(1, round(sc.y(b.bottom) - sc.y(b.top))), C3, x=round(cx),
                        y=round(sc.y(b.top))))
        out.append(rect(f"body {i:03d}", bw, max(1, round(bot - top)), C3, x=round(cx - bw / 2), y=round(top)))
    return out


def axis_label(sc: Scale, p: int | Decimal) -> str:
    if sc.pct_base is not None:
        return f"{(Decimal(p) - sc.pct_base) / Decimal(sc.pct_base) * 100:+.2f} %"
    return price(int(p))


def price_axis(sc: Scale, x: float, w: int, *, last: int | None = None, grid_w: float = 0) -> list[Node]:
    """Labels every nice step (percent mode: the % from the base), grid lines across the plot, the last price."""
    span = sc.hi - sc.lo
    step = nice_step(span, sc.y_bot - sc.y_top)
    out: list[Node] = []
    p = int(math.ceil(float(sc.lo) / step)) * step
    while p <= sc.hi:
        y = sc.y(p)
        if sc.y_top + 8 <= y <= sc.y_bot - 8:
            if grid_w:
                out.append(rect(f"grid {p}", round(grid_w), 1, k.BORDER, x=0, y=round(y)))
            out.append(text(f"tick label {p}", axis_label(sc, p), k.NUM_SM, C2, x=round(x + 6), y=round(y - 7)))
        p += step
    if last is not None:
        out.append(hbox("last price label", [text("price", axis_label(sc, last), k.NUM_SM, C1)],
                        {"padX": k.INSET_XS, "fill": k.RAISED, "stroke": C1, "strokeWidth": k.HAIR,
                         "strokeAlign": "inner", "radius": k.R_CONTROL}, w=w - 2, h=16, x=round(x + 1),
                        y=round(sc.y(last) - 8)))
    return out


def time_axis(bars: list[k.Bar], slot: float, y: float, every: int, fmt: str = "%H:%M") -> list[Node]:
    return [text(f"time label {i:03d}", f"{b.start:{fmt}}", k.NUM_SM, C2, x=round(i * slot), y=round(y + 3))
            for i, b in enumerate(bars) if i % every == 0]


def chrome(w: int, h: int) -> list[Node]:
    """TopBar and StatusBar placeholders (no words; FALLBACKS chrome). No environment control or badge (R-1)."""
    k.fallback("chrome")
    return [box("TopBar (placeholder)", [rect("rule", w, 1, k.BORDER, x=0, y=TOP_H - 1)], {"fill": k.RAISED}, w=w,
                h=TOP_H, x=0, y=0, note="E10 chrome placeholder; the global band carries the environment (R-1)"),
            box("StatusBar (placeholder)", [rect("rule", w, 1, k.BORDER, x=0, y=0)], {"fill": k.RAISED}, w=w,
                h=STATUS_H, x=0, y=h - STATUS_H)]


@dataclass
class ChartSpec:
    bars: list[k.Bar]
    slots: int  # bar slots across the plot (room to the right of the last bar)
    w: int  # the pane's width, the price axis included
    every: int  # a time label every n bars
    fmt: str = "%H:%M"
    words: str = ""  # the chart header's mode words ("log", "%"), drawn after the interval
    interval: str = INTERVAL


def chart_pane(cs: ChartSpec, sc: Scale, top: int, bot: int, *, x: int = 0, extra: list[Node] | None = None,
               name: str = "SCR-030 price pane") -> Node:
    """The SCR-030 price pane: header strip (symbol, interval), plot (grid, candles), price axis, time axis. sc is in
    window coordinates; extra nodes are in pane coordinates."""
    k.fallback("chart")
    plot_w = cs.w - PRICE_AXIS
    slot = plot_w / cs.slots
    loc = sc.shift(top)
    kids: list[Node] = [rect("plot", plot_w, bot - top, k.CANVAS, x=0, y=0),
                        rect("price axis rule", 1, bot - top, k.BORDER, x=plot_w, y=0)]
    kids += price_axis(loc, plot_w, PRICE_AXIS, last=cs.bars[-1].c, grid_w=plot_w)
    kids += candles(cs.bars, loc, 0, slot)
    kids += time_axis(cs.bars, slot, bot - top - TIME_AXIS, cs.every, cs.fmt)
    head = [text("symbol", say(k.SYMBOL), k.LABEL, C1), text("interval", interval(cs.interval), k.CAPTION, C2)]
    if cs.words:
        head.append(text("scale mode", cs.words, k.CAPTION, C2))
    kids.append(hbox("chart header", head, {"gap": k.INSET_SM, "padX": k.INSET_SM, "fill": k.CANVAS}, h=CHART_HEAD,
                     x=0, y=0))
    kids += extra or []
    return box(name, kids, {"clip": True, "fill": k.CANVAS}, w=cs.w, h=bot - top, x=x, y=top)


def agg(bars: list[k.Bar], n: int) -> list[k.Bar]:
    """n consecutive 30-minute bars as one (the chart's coarser interval for long views)."""
    out = []
    for i in range(0, len(bars), n):
        g = bars[i:i + n]
        out.append(k.Bar(g[0].start, g[0].o, max(b.top for b in g), min(b.bottom for b in g), g[-1].c,
                         sum(b.vol for b in g), None))
    return out


# --- the plot (CMP-183 rows of CMP-110): bars, named levels, the bracket, glyphs (§3.1, §3.3, §5.3)
MARGIN_W, OWN_AXIS_W, LINE = 24, 56, 14  # TPO letter margin, own-axis lane (kit choices); one type.num.sm line + gap


@dataclass
class PlotOpts:
    inp: str = "volume"  # volume | delta | tpo
    host: str = "docked"  # docked: bars from the left; overlay: from the right, toward the price axis
    inset: int = 8
    run: int | None = None  # overlay: the bars' maximum length
    label_w: int = LABEL_W
    merge: int = 1  # levels per drawn row (`26`:238; W-20)
    developing_edge: str | None = None  # "top" | "bottom": the bracket's open end (PD-1); None: closed (final)
    pins: bool = False  # the value area spans the view: VAH / VAL as edge pins (W-26)
    own_axis: bool = False  # alignment cannot hold: the panel's own CMP-188 on its left edge (§4.1 rule 6)
    approx: bool = True  # the approximated part of each bar as the estimated-hatch slot (PD-4; D02-C10)


@dataclass
class Geo:
    rx0: float  # the bars region's left
    run: float  # its width
    gut_x: float  # the label gutter's left
    lane_x: float  # the bracket lane's left
    margin_x: float | None  # the TPO letter margin's left (TPO only)
    anchor: str  # "left" (docked) | "right" (overlay): where a volume bar starts


def geo(w: float, o: PlotOpts) -> Geo:
    m = MARGIN_W if o.inp == "tpo" else 0
    if o.host == "docked":
        x = o.inset + (OWN_AXIS_W if o.own_axis else 0)
        run = w - x - o.inset - o.label_w - BRACKET_W - m
        return Geo(x + m, run, x + m + run + 4, w - o.inset - BRACKET_W, x if m else None, "left")
    lane = w - o.inset - BRACKET_W
    run = float(o.run or 0)
    rx0 = lane - 2 - run
    return Geo(rx0, run, rx0 - m - o.label_w, lane, rx0 - m if m else None, "right")


def tpo_profile(pr: k.Profile) -> k.Profile:
    """The TPO input's profile: each row's count is its TPO periods (letters), POC / VA by the same `24` §4.5 rule."""
    levels = {r: k.Level(vol=len(x.tpo), tpo=set(x.tpo)) for r, x in pr.levels.items() if x.tpo}
    num = sum(Decimal(r * pr.row_ticks) * v.vol for r, v in levels.items())
    p2 = k.Profile(pr.label, pr.kind, pr.start, pr.end, pr.row_ticks, pr.tpo_min, levels, pr.complete,
                   num / sum(v.vol for v in levels.values()), pr.last_ticks)
    return k.finish(p2)


def row_y(pr: k.Profile, sc: Scale, r: int, n: int = 1) -> tuple[float, float]:
    """A drawn row's top and height (rows r .. r+n-1 merged): its boundary prices through the chart's price -> y of
    the same frame (§4.1 rule 2)."""
    top, bot = sc.y((r + n) * pr.row_ticks), sc.y(r * pr.row_ticks)
    return top, bot - top


@dataclass
class Label:
    key: str
    lines: list[str]
    want: float
    y: float = 0


def stack(labels: list[Label], y_min: float, y_max: float) -> list[Label]:
    """Labels that would collide stack apart in steps of one line; a label pushed past the plot is dropped."""
    placed: list[Label] = []
    for a in sorted(labels, key=lambda a: a.want):
        y = a.want - len(a.lines) * LINE / 2
        if placed:
            y = max(y, placed[-1].y + len(placed[-1].lines) * LINE)
        a.y = y
        placed.append(a)
    for i in range(len(placed) - 1, -1, -1):
        a = placed[i]
        lim = y_max - len(a.lines) * LINE if i == len(placed) - 1 else placed[i + 1].y - len(a.lines) * LINE
        a.y = min(a.y, lim)
    return [a for a in placed if a.y >= y_min - 0.5]


def draw_labels(labels: list[Label], x: float, *, backing: bool = False) -> list[Node]:
    """Labels at their stacked y; on the overlay each line sits on a color.surface.canvas backing so a word stays
    legible over the candles (kit choice)."""
    out = []
    for a in labels:
        for j, ln in enumerate(a.lines):
            if backing:
                out.append(rect(f"{a.key} · backing {j + 1}", round(k.text_w(ln, k.NUM_SM)) + 6, LINE, k.CANVAS,
                                x=round(x) - 3, y=round(a.y + j * LINE)))
            out.append(text(f"{a.key} · line {j + 1}", ln, k.NUM_SM, C1, x=round(x), y=round(a.y + j * LINE)))
        mid = a.y + len(a.lines) * LINE / 2
        if abs(mid - a.want) > 2:
            y0, y1 = sorted((a.want, mid))
            out.append(rect(f"{a.key} · leader", 1, max(1, round(y1 - y0)), C2, x=round(x - 3), y=round(y0)))
    return out


def plot(pr: k.Profile, sc: Scale, w: int, h: float, o: PlotOpts, *, name: str = "CMP-183 plot",
         fill: str | None = k.CANVAS) -> Node:
    """The histogram body: sc maps prices to this box's own y (0 at its top). Volume bars from the anchor (in the VA:
    color.text.secondary, outside: .tertiary); delta bars either side of a centre line with the zero-delta tick; TPO
    counts with the letter-margin slot, the IB bar and single prints; the POC rail, VAH / VAL ticks, the bracket,
    words + prices on named levels only (PD-8), the HVN / LVN glyphs."""
    if o.inp == "tpo":
        pr = tpo_profile(pr)
    g = geo(w, o)
    kids: list[Node] = []
    groups = [pr.rows[i:i + o.merge] for i in range(0, len(pr.rows), o.merge)]
    if o.inp == "delta":
        top = max((abs(sum(pr.lv(r).delta for r in gr)) for gr in groups), default=1) or 1
    else:
        top = max(sum(pr.lv(r).vol for r in gr) for gr in groups)
    cx = g.rx0 + g.run / 2
    if o.inp == "delta":
        kids.append(rect("delta centre line", 1, round(h), k.BORDER, x=round(cx), y=0))
    last_glyph = {">": -1e9, "<": -1e9}
    for gr in groups:
        y, rh = row_y(pr, sc, gr[0], len(gr))
        if y + rh < 0 or y > h:
            continue
        hh = max(1, round(rh - 1 if rh >= 3 else rh))
        tag = f"{gr[0] * pr.row_ticks}"
        v = sum(pr.lv(r).vol for r in gr)
        if v == 0:
            continue  # untraded: no bar, no mark (§3.3)
        in_va = any(pr.va[0] <= r <= pr.va[1] for r in gr)
        ink = C2 if in_va else C3
        end = g.rx0
        if o.inp in ("volume", "tpo"):
            ap = sum(pr.lv(r).approx for r in gr) if (o.approx and o.inp == "volume") else 0
            ln_all = max(1, round(v / top * g.run))
            ln_ap = round(ap / top * g.run) if ap else 0
            ln_rec = ln_all - ln_ap
            if g.anchor == "left":
                if ln_rec:
                    kids.append(rect(f"bar {tag}", ln_rec, hh, ink, x=round(g.rx0), y=round(y)))
                if ln_ap:
                    kids.append(rect(f"estimated slot {tag}", ln_ap, hh, k.CANVAS, {"stroke": C1, "strokeWidth":
                                     k.HAIR, "strokeAlign": "inner"}, x=round(g.rx0 + ln_rec), y=round(y)))
                end = g.rx0 + ln_all
            else:
                x1 = g.rx0 + g.run
                if ln_rec:
                    kids.append(rect(f"bar {tag}", ln_rec, hh, ink, x=round(x1 - ln_rec), y=round(y)))
                if ln_ap:
                    kids.append(rect(f"estimated slot {tag}", ln_ap, hh, k.CANVAS, {"stroke": C1, "strokeWidth":
                                     k.HAIR, "strokeAlign": "inner"}, x=round(x1 - ln_all), y=round(y)))
                end = x1 - ln_all
        else:
            d = sum(pr.lv(r).delta for r in gr)
            rec = sum(pr.lv(r).recorded for r in gr)
            if rec and d == 0:
                th = max(2, min(8, round(rh)))
                kids.append(rect(f"zero-delta tick {tag}", 2, th, C1, x=round(cx - 1), y=round(y + rh / 2 - th / 2)))
            elif d:
                ln = max(1, round(abs(d) / top * g.run / 2))
                kids.append(rect(f"delta {tag}", ln, hh, ink, x=round(cx if d > 0 else cx - ln), y=round(y)))
                end = cx + ln if d > 0 else cx - ln
        if o.merge == 1 and o.inp == "volume":
            for ch, rows_ in ((">", pr.hvn), ("<", pr.lvn)):
                if any(r in rows_ for r in gr) and abs(y - last_glyph[ch]) >= LINE:
                    k.fallback("glyph")
                    last_glyph[ch] = y
                    gx = end + 3 if g.anchor == "left" else end - 10
                    kids.append(text(f"{'HVN' if ch == '>' else 'LVN'} glyph {tag}", ch, k.NUM_SM, C1, x=round(gx),
                                     y=round(y + rh / 2 - 7)))
                elif any(r in rows_ for r in gr):
                    k.reading("glyph spacing: a node glyph whose line would touch the previous one of its kind is not "
                              "drawn; the row keeps its bar, and the mirror and the table carry the word (§11)")
    if o.inp == "tpo":
        kids += tpo_marks(pr, sc, g, h)
    kids += level_marks(pr, sc, g, h, o)
    if o.own_axis:
        kids += own_axis(sc, h, o.inset)
    return box(name, kids, {"clip": True, **({"fill": fill} if fill else {})}, w=w, h=round(h))


def level_marks(pr: k.Profile, sc: Scale, g: Geo, h: float, o: PlotOpts) -> list[Node]:
    """POC rail (2 px, color.text.primary, across the bars), VAH / VAL ticks at the VA boundaries, the value-area
    bracket in its lane (closed ends ticked, the developing end open, PD-1), words + prices in the gutter (PD-2);
    with o.pins, VAH / VAL out of view become edge pins (W-26) and the bracket runs the full height, open both ends."""
    out: list[Node] = []
    poc_y = sum(row_y(pr, sc, pr.poc)) - row_y(pr, sc, pr.poc)[1] / 2
    vah_y = row_y(pr, sc, pr.va[1])[0]
    val_y = sum(row_y(pr, sc, pr.va[0]))
    out.append(rect("POC rail", round(g.run), 2, C1, x=round(g.rx0), y=round(poc_y - 1)))
    delta = o.inp == "delta"

    def words(word: str, r: int) -> list[str]:
        lines = [f"{word} {price(r * pr.row_ticks)}"]
        if delta:
            lines.append(signed_qty(pr.lv(r).delta))
        return lines

    labels: list[Label] = []
    coincide = pr.poc == pr.va[0] == pr.va[1]
    if coincide:  # §7 edge-two-level: POC, VAH and VAL coincide and are all labelled (stacked words, one price)
        labels.append(Label("POC VAH VAL label", [say("POC"), say("VAH"), say("VAL"), price(pr.poc * pr.row_ticks)],
                            poc_y))
    else:
        labels.append(Label("POC label", words(say("POC"), pr.poc), poc_y))
    y_top, y_bot = vah_y, val_y
    if o.pins:
        y_top, y_bot = 0.0, h
        out.append(sized(hbox("VAH pin", [text("words", k.W(26, 0, price=price(pr.va[1] * pr.row_ticks)), k.NUM_SM,
                                               C1)], {"padX": k.INSET_XS, "fill": k.RAISED, "stroke": C1,
                                                      "strokeWidth": k.HAIR, "strokeAlign": "inner"}, h=18))
                   | {"x": round(g.rx0 if g.anchor == "left" else g.gut_x), "y": 2})
        val_pin = sized(hbox("VAL pin", [text("words", k.W(26, 1, price=price(pr.va[0] * pr.row_ticks)), k.NUM_SM,
                                              C1)], {"padX": k.INSET_XS, "fill": k.RAISED, "stroke": C1,
                                                     "strokeWidth": k.HAIR, "strokeAlign": "inner"}, h=18))
        out.append(val_pin | {"x": round(g.rx0 if g.anchor == "left" else g.gut_x), "y": round(h - 20)})
    elif not coincide:
        for word, r, yb in (("VAH", pr.va[1], vah_y), ("VAL", pr.va[0], val_y)):
            out.append(rect(f"{word} tick", 8, 1, C1, x=round(g.gut_x - 4 if g.anchor == "left" else g.rx0 - 4),
                            y=round(yb)))
            labels.append(Label(f"{word} label", words(say(word), r), yb))
    lx = g.gut_x + 6 if g.anchor == "left" else g.gut_x
    out += draw_labels(stack(labels, 0, h - (22 if o.pins else 0)), lx, backing=o.host == "overlay")
    # the bracket (MEMO :163 via §3.1): a 2 px line, ticked at each closed end, open at the developing end
    bx = g.lane_x + 4
    out.append(rect("VA bracket", 2, max(1, round(y_bot - y_top)), C2, x=round(bx), y=round(y_top)))
    if not o.pins:
        if o.developing_edge != "top":
            out.append(rect("VA bracket · top end", 6, 2, C2, x=round(bx - 4), y=round(y_top)))
        if o.developing_edge != "bottom":
            out.append(rect("VA bracket · bottom end", 6, 2, C2, x=round(bx - 4), y=round(y_bot - 2)))
    out.append(text("VA bracket · word", say("VA"), k.NUM_SM, C1, x=round(bx + 5), y=round((y_top + y_bot) / 2 - 7)))
    return out


def tpo_marks(pr: k.Profile, sc: Scale, g: Geo, h: float) -> list[Node]:
    """The TPO letter margin left of the bars as a slot (the letters are SCR-038/tpo-detail, not drawn: the text
    binds), the initial balance as a solid bar labelled "IB" and single prints as a solid glyph in the margin (§3.3)."""
    mx = g.margin_x or 0
    y_a = max(0.0, row_y(pr, sc, max(pr.rows))[0])
    y_b = min(h, sum(row_y(pr, sc, min(pr.rows))))
    out: list[Node] = [rect("TPO letter margin (slot)", MARGIN_W - 4, round(y_b - y_a), k.CANVAS,
                            {"stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, x=round(mx),
                            y=round(y_a),
                            note="the letters per `24`:1019, sized by SCR-039's TPO letter size: SCR-038/tpo-detail "
                                 "(not drawn; the text is binding)")]
    if pr.ib:
        y0 = row_y(pr, sc, pr.ib[1])[0]
        y1 = sum(row_y(pr, sc, pr.ib[0]))
        out.append(rect("IB bar", 3, max(1, round(y1 - y0)), C1, x=round(mx + 2), y=round(y0)))
        if y0 - 14 >= 0:
            out.append(text("IB label", say("IB"), k.NUM_SM, C1, x=round(mx + 7), y=round(y0 - 14)))
        else:  # SHEET-FIX 02 (live check 2026-11-03): above the plot top it is cut, so it sits beside the bar
            lw = 14  # the label's laid-out width, read back live ("IB" in num.sm)
            out.append(text("IB label", say("IB"), k.NUM_SM, C1, x=round(mx + 2) - lw - 4, y=round(y0)))
    for r in pr.single_prints:
        y, rh = row_y(pr, sc, r)
        out.append(rect(f"single print {r * pr.row_ticks}", 4, max(1, round(rh - 1 if rh >= 3 else rh)), C1,
                        x=round(mx + MARGIN_W - 10), y=round(y)))
    return out


def own_axis(sc: Scale, h: float, inset: int) -> list[Node]:
    """The own-scale fallback (§4.1 rule 6): the panel's own CMP-188 price axis on its left edge."""
    step = nice_step(sc.hi - sc.lo, sc.y_bot - sc.y_top, 40)
    x = inset + OWN_AXIS_W - 4
    out: list[Node] = [rect("CMP-188 own axis", 1, round(h), C1, x=x, y=0)]
    p = int(math.ceil(float(sc.lo) / step)) * step
    while p <= sc.hi:
        y = sc.y(p)
        if 8 <= y <= h - 8:
            out.append(rect(f"own tick {p}", 4, 1, C1, x=x - 4, y=round(y)))
            out.append(text(f"own label {p}", price(p), k.NUM_SM, C2, x=inset - 2, y=round(y - 7)))
        p += step
    return out


# --- SCR-038 docked panel (§3.1): header band (CMP-199) on raised, the body on the canvas, the legend (CMP-199)
INPUT_WORD = {"volume": "Volume", "delta": "Delta", "tpo": "TPO"}


@dataclass
class Panel:
    pr: k.Profile | None
    density: str = "compact"
    interval: str = INTERVAL
    inp: str = "volume"
    period: str = "Session"
    aligned: bool = True
    status: list[Node] = field(default_factory=list)  # the status slot, left to right (PD-5)
    status_notes: list[str] = field(default_factory=list)  # W-7 / W-9 under the slot
    busy: bool = False  # §6 loading: the thin busy bar in the header
    hint: str | None = None  # W-30 / W-31 (§10.2)
    table: bool = False  # the Histogram │ Table switch pressed on Table
    focus: str | None = None  # a header control drawn focused
    presets_tag: str | None = None  # W-32 "Modified" slot on the Presets menu button (§9)
    row_value: str | None = None  # the Row stepper's value (default: the profile's row size)
    merged_k: int = 1
    covered: str | None = None  # W-21 in the legend (a composite)
    opts: PlotOpts = field(default_factory=PlotOpts)
    body: Callable[[int, int], list[Node]] | None = None  # replaces the plot (empty state, table): (w, h) -> nodes

    @property
    def state_word(self) -> str | None:
        if self.pr is None:
            return None
        return k.W(5) if self.pr.complete else k.W(4, **{"HH:MM": hm(k.NOW)})


def header(p: Panel, w: int) -> Node:
    d = DENSITY[p.density]
    rh = d["row"]
    inner = w - 2 * k.PX[d["inset"]]
    align = k.W(2, symbol=k.SYMBOL, interval=interval(p.interval)) if p.aligned else k.W(3)
    title = [text("title", k.W(1), k.LABEL, C1)]
    if p.state_word:
        title.append(text("state", p.state_word, k.CAPTION, C2))
    rows: list[Node] = [hbox("title row", title, {"gap": k.INSET_SM, "wrap": "wrap"}, w=inner),
                        control("alignment status", align, menu=True, h=rh - 4, focused=p.focus == "alignment")]
    if p.busy:
        rows.append(rect("busy bar", round(inner * 0.4), 2, C1, note="a thin busy bar in the header; aria-busy on the "
                                                                     "body; no spinner on the plot (§6 loading)"))
    if p.status:
        rows.append(hbox("status slot", p.status, {"gap": k.INSET_XS, "wrap": "wrap"}, w=inner,
                         note="left to right: the partial chip, CMP-227, the degraded tag; >= 4 px apart, each its "
                              "own accessible name (PD-5)"))
    rows += [text(f"status note {i}", s, k.CAPTION, C2, w=inner) for i, s in enumerate(p.status_notes, 1)]
    if p.hint:
        rows.append(hbox("hint", [icon("glyph", "info", C2), text("words", p.hint, k.CAPTION, C1, w=inner - 16)],
                         {"gap": k.INSET_XS, "align": "start"}, w=inner, note="announced politely once on the choice"))
    row_v = p.row_value or (str(p.pr.row_ticks) if p.pr else str(k.ROW_TICKS))
    ctl = [labelled("period", say("Period"), control("period menu", say(p.period), menu=True, h=rh,
                                                      focused=p.focus == "period")),
           labelled("input", say("Input"), control("input menu", say(INPUT_WORD[p.inp]), menu=True, h=rh)),
           labelled("va", say("VA%"), stepper("VA % stepper", str(k.VA_PCT), h=rh, w=52)),
           labelled("row", say("Row"), stepper("row size stepper", row_v, h=rh, w=60)),
           control("show-VWAP toggle", say("VWAP"), h=rh),
           hbox("switch", [control("Histogram", k.W(29, 0), h=rh, pressed=not p.table, focused=p.focus == "switch"
                                   and not p.table),
                           control("Table", k.W(29, 1), h=rh, pressed=p.table, focused=p.focus == "switch" and p.table)],
                None, h=rh, note="the Histogram │ Table switch (W-29), equal status; Alt+T"),
           control("presets", say("Presets"), menu=True, h=rh, tag=p.presets_tag, focused=p.focus == "presets"),
           control("settings", say("Settings"), h=rh)]
    rows.append(hbox("controls row", ctl, {"gap": k.INSET_XS, "wrap": "wrap"}, w=inner,
                     note="wraps to a second line rather than truncating a word (PD-7)"))
    return vbox("CMP-199 header band", rows, {"gap": k.STACK_XS, "padX": d["inset"], "padY": k.INSET_XS,
                                              "fill": k.RAISED}, w=w)


def key(name: str, word: str, mark: list[Node], mark_h: int = 12, row_h: int = 14) -> Node:
    """One legend key: its word and a 12 px mark. SHEET-FIX ALL (live check 2026-11-03): the row is 14 px, the
    caption's line height (12 cut 1 px top and bottom); a glyph mark is 14 px too, its glyph at the mark's top. The
    legend keeps the height it had with 12 px rows (the live fix left it unchanged), so nothing below it moves."""
    return hbox(f"key {name}", [text("word", word, k.CAPTION, C2),
                                box("mark", mark, {"clip": True, "fill": k.CANVAS}, w=12, h=mark_h)],
                {"gap": k.INSET_XS}, h=row_h)


def legend(p: Panel, w: int) -> Node:
    d = DENSITY[p.density]
    inner = w - 2 * k.PX[d["inset"]]
    rt = p.pr.row_ticks if p.pr else k.ROW_TICKS
    parts = [say(p.period)] + ([p.state_word] if p.state_word else []) + [
        say(INPUT_WORD[p.inp]), k.W(19, n=str(rt), price=price(rt)), k.tpl("VA 70 %", {"70": str(k.VA_PCT)})]
    if p.merged_k > 1:
        parts.append(k.W(20, k=str(p.merged_k)))
    if p.covered:
        parts.append(p.covered)
    def keys_(fix: bool) -> list[Node]:
        rh, gh, gy = (14, 14, 0) if fix else (12, 12, -1)
        return [key("value area", k.tpl("Value area 70 %", {"70": str(k.VA_PCT)}),
                    [rect("bracket", 2, 10, C2, x=5, y=1), rect("end", 5, 2, C2, x=2, y=1)], row_h=rh),
                key("HVN", say("HVN"), [text("glyph", ">", k.NUM_SM, C1, x=2, y=gy)], mark_h=gh, row_h=rh),
                key("LVN", say("LVN"), [text("glyph", "<", k.NUM_SM, C1, x=2, y=gy)], mark_h=gh, row_h=rh),
                key("single prints", say("Single prints"), [rect("glyph", 4, 10, C1, x=4, y=1)], row_h=rh)]

    def legend_(keys: list[Node], **kw: Any) -> Node:
        return vbox("CMP-199 legend", [text("words", " · ".join(parts), k.CAPTION, C2, w=inner),
                                       hbox("keys", keys, {"gap": k.INSET_SM, "wrap": "wrap"}, w=inner)
                                       if p.pr else None],
                    {"gap": k.STACK_XS, "padX": d["inset"], "padY": k.INSET_XS, "fill": k.RAISED}, w=w,
                    note="glyph keys: the word on hover, focus, the mirror and the table (§5.3)", **kw)

    keys = keys_(True)
    k.fallback("glyph")
    return legend_(keys, h=math.ceil(k.est_height(legend_(keys_(False)))))


def frame(fid: str, kids: list[Node], *, note: str | None = None) -> Node:
    w, h = k.frame_size(fid)
    kids = [anchor_checks(k.frame_name(fid), "the frame", w, h, n) for n in kids]
    return box(k.frame_name(fid), kids, {"fill": k.CANVAS, "clip": True}, w=w, h=h, note=note)


def centred(n: Node, pw: int, ph: int) -> Node:
    """Place n centred horizontally and vertically in a pw x ph parent (a live check says so by name)."""
    return dict(n, x=(pw - n["w"]) // 2, y=(ph - n["h"]) // 2, _centre=True)


def anchor_checks(fname: str, parent: str, pw: int, ph: int, n: Node) -> Node:
    """Live checks for absolutely placed blocks: a centred block names its centring (both axes, with the sums); a
    board marker names its top-left anchor and must not be re-centred. Recurses into plain boxes (no flex layout)."""
    n = dict(n)
    if n.pop("_centre", False):
        k.live(f"frame {fname!r}: {n['name']!r} ({n['w']} x {n['h']}) centred horizontally and vertically in "
               f"{parent} at ({n['x']}, {n['y']}) = (({pw} - {n['w']}) / 2, ({ph} - {n['h']}) / 2); after relayout "
               "re-centre it on both axes if its size changed")
    elif str(n.get("name", "")).startswith("board marker") and "x" in n and "y" in n:
        k.live(f"frame {fname!r}: {n['name']!r} anchored top-left at ({n['x']}, {n['y']}) in {parent}; keep that "
               "anchor after relayout: do not centre it")
    if n.get("kids") and not (n.get("o") or {}).get("dir") and n.get("t", "board") == "board" and "w" in n:
        n["kids"] = [anchor_checks(fname, repr(n["name"]), n["w"], n.get("h", 0), c) for c in n["kids"]]
    return n


@dataclass
class Docked:
    panel: Panel
    bars: list[k.Bar]  # the bound chart's bars
    slots: int = 52
    every: int = 8
    fmt: str = "%H:%M"
    pct: bool = False  # the chart in percent mode (alignment cannot hold, §4.1 rule 6)
    log: bool = False  # the chart in log mode (§4.1 rule 3)
    view: tuple[int, int] | None = None  # the user's vertical zoom: [lo, hi] ticks fitted to the panel plot
    chart_extra: list[Node] = field(default_factory=list)  # board markers over the chart pane (pane coords)
    extra: list[Node] = field(default_factory=list)  # board markers over the window (window coords)
    h: int = k.WIN_H
    chrome: bool = True


@dataclass
class DockedOut:
    kids: list[Node]
    sc: Scale  # window coordinates
    panel_y0: float  # the panel plot's top / bottom in window coordinates
    panel_y1: float
    panel: Node


def panel_parts(p: Panel, w: int) -> tuple[Node, Node, int, int]:
    hd, lg = header(p, w), legend(p, w)
    hh, lh = math.ceil(k.est_height(hd)), math.ceil(k.est_height(lg))
    hd["h"], lg["h"] = hh, lh
    return hd, lg, hh, lh


def docked_window(dk: Docked, *, w: int = k.WIN_W) -> DockedOut:
    """SCR-038 docked beside its bound chart; the panel's rows use the chart's price -> y of the same frame (aligned,
    §4.1 rule 2), or the panel's own scale when alignment cannot hold (rule 6)."""
    p, h = dk.panel, dk.h
    pw = PANEL_W
    top, bot = (TOP_H, h - STATUS_H) if dk.chrome else (0, h)
    hd, lg, hh, lh = panel_parts(p, pw)
    py0, py1 = (top + hh + 1 + lh, bot) if p.table else (top + hh + 1, bot - lh)
    pr = p.pr
    lo_t, hi_t = min(b.bottom for b in dk.bars), max(b.top for b in dk.bars)
    if pr is not None and p.body is None:  # the chart's auto-fit holds its bars and the profile's rows
        lo_t, hi_t = min(lo_t, min(pr.rows) * pr.row_ticks), max(hi_t, (max(pr.rows) + 1) * pr.row_ticks)
    if dk.view:
        lo_t, hi_t = dk.view
    ch_top, ch_bot = top + CHART_HEAD + 4, bot - TIME_AXIS - 4
    want = (py0 + 16, py1 - 16) if p.body is None else (ch_top + 24, ch_bot - 24)
    sc = fit_scale(lo_t, hi_t, ch_top, ch_bot, *want, log=dk.log)
    if pr is not None and p.body is None:  # rows under 2 px merge (`26`:238); the legend states W-20
        px = min(row_y(pr, sc, r)[1] for r in pr.rows)
        mk = max(1, math.ceil(2 / px)) if px < 2 else 1
        if mk > p.merged_k:
            p.merged_k = mk
            p.opts = replace(p.opts, merge=mk)
            hd, lg, hh, lh = panel_parts(p, pw)
            py0, py1 = top + hh + 1, bot - lh
            sc = fit_scale(lo_t, hi_t, ch_top, ch_bot, py0 + 16, py1 - 16, log=dk.log)
    chart_sc = sc
    if dk.pct:  # percent mode: the chart re-scales to its own range; the panel keeps its own axis
        clo, chi = min(b.bottom for b in dk.bars), max(b.top for b in dk.bars)
        chart_sc = replace(fit_scale(clo, chi, ch_top, ch_bot, ch_top + 24, ch_bot - 24), pct_base=dk.bars[0].o)
    words = say("log") if dk.log else (say("percent") if dk.pct else "")
    cs = ChartSpec(dk.bars, dk.slots, w - pw, dk.every, dk.fmt, words, p.interval)
    chart = chart_pane(cs, chart_sc, top, bot, extra=dk.chart_extra)
    kids: list[Node] = [hd | {"x": 0, "y": 0}, rect("header rule", pw, 1, k.BORDER, x=0, y=hh)]
    if p.body:
        kids.append(box("body", p.body(pw, py1 - py0), {"clip": True}, w=pw, h=py1 - py0, x=0, y=py0 - top))
    elif pr is not None:
        o = replace(p.opts, inp=p.inp, inset=k.PX[DENSITY[p.density]["inset"]], own_axis=not p.aligned)
        kids.append(plot(pr, sc.shift(py0), pw, py1 - py0, o) | {"x": 0, "y": py0 - top})
    kids += [lg | {"x": 0, "y": (hh + 1) if p.table else py1 - top},
             rect("panel edge", 1, bot - top, k.BORDER, x=0, y=0)]
    panel = box("SCR-038 docked panel", kids, {"clip": True, "fill": k.CANVAS}, w=pw, h=bot - top, x=w - pw, y=top,
                note="bound to one named chart (§4.1 rule 1)")
    out = ([*chrome(w, h)] if dk.chrome else []) + [chart, panel, *dk.extra]
    return DockedOut(out, sc, py0, py1, panel)


# --- SCR-038 overlay (§3.2): CMP-183 inside SCR-030's price pane on its CMP-188, the controls on the CMP-199 row
@dataclass
class Overlay:
    pr: k.Profile
    bars: list[k.Bar]
    density: str = "compact"
    inp: str = "volume"
    period: str = "Visible range"
    slots: int = 60
    every: int = 8
    fmt: str = "%H:%M"
    run: int = 240  # kit choice: the overlay bars' maximum length
    status: list[Node] = field(default_factory=list)
    popover: bool = False  # the ⋯ disclosure popover open


def overlay_row(ov: Overlay, inner: int) -> Node:
    """§3.2: "Profile · Visible range ▾ · Volume ▾ · Histogram │ Table · ⚙", the status slot, then ⋯ (aria-expanded,
    a non-modal disclosure popover holding VA %, Row size, Show VWAP and Presets)."""
    rh = DENSITY[ov.density]["row"]
    sep = {"gap": k.INSET_XS}
    kids = [text("name", say("Profile"), k.LABEL, C1),
            control("period menu", say(ov.period), menu=True, h=rh),
            control("input menu", say(INPUT_WORD[ov.inp]), menu=True, h=rh),
            hbox("switch", [control("Histogram", k.W(29, 0), h=rh, pressed=True),
                            control("Table", k.W(29, 1), h=rh)], None, h=rh,
                 note="the table switch at equal status, directly on the legend row, never in the overflow"),
            control("settings", say("Settings"), h=rh),
            *ov.status,
            hbox("overflow ⋯", [icon("glyph", "more-horizontal", C1)],
                 {"padX": k.INSET_XS, "radius": k.R_CONTROL, "fill": k.CANVAS if ov.popover else k.RAISED,
                  "stroke": C1 if ov.popover else k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, h=rh,
                 note=f'aria-expanded="{str(ov.popover).lower()}"; opens the non-modal disclosure popover (not a '
                      'menu)')]
    k.reading("overlay settings button: §3.2's '⚙' is drawn as the docked panel's 'Settings' button word (the glyph "
              "is E19-D03's; no gear in the local icon set); its accessible name is the same")
    return hbox("CMP-199 legend row", kids, {**sep, "padX": k.INSET_SM, "fill": k.RAISED, "stroke": k.BORDER,
                                             "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CARD,
                                             "wrap": "wrap"}, w=inner)


def overlay_window(ov: Overlay, *, w: int = k.WIN_W, h: int = k.WIN_H) -> tuple[list[Node], Scale, Node]:
    top, bot = TOP_H, h - STATUS_H
    d = DENSITY[ov.density]
    plot_w = w - PRICE_AXIS
    row = overlay_row(ov, plot_w - 2 * 8 - 120)
    row["h"] = math.ceil(k.est_height(row))
    pr = ov.pr
    words_line = [say(ov.period), (k.W(5) if pr.complete else k.W(4, **{"HH:MM": hm(k.NOW)})),
                  say(INPUT_WORD[ov.inp]), k.W(19, n=str(pr.row_ticks), price=price(pr.row_ticks)),
                  k.tpl("VA 70 %", {"70": str(k.VA_PCT)})]
    legend_words = text("CMP-199 legend words", " · ".join(words_line), k.CAPTION, C2, x=8,
                        y=CHART_HEAD + row["h"] + 8)
    p_top = CHART_HEAD + row["h"] + 30
    lo_t = min(min(pr.rows) * pr.row_ticks, min(b.bottom for b in ov.bars))
    hi_t = max((max(pr.rows) + 1) * pr.row_ticks, max(b.top for b in ov.bars))
    sc = fit_scale(lo_t, hi_t, top + CHART_HEAD + 4, bot - TIME_AXIS - 4, top + p_top + 8, bot - TIME_AXIS - 12)
    o = PlotOpts(inp=ov.inp, host="overlay", inset=k.PX[d["inset"]], run=ov.run, label_w=120)
    ph = (bot - top) - TIME_AXIS - p_top
    layer = plot(pr, sc.shift(top + p_top), plot_w, ph, o, name="CMP-183 overlay plot", fill=None)
    extra = [row | {"x": 8, "y": CHART_HEAD + 2}, legend_words, layer | {"x": 0, "y": p_top}]
    cs = ChartSpec(ov.bars, ov.slots, w, ov.every, ov.fmt)
    chart = chart_pane(cs, sc, top, bot, extra=extra)
    return [*chrome(w, h), chart], sc, row


# --- the world's views
def day_bars(day: datetime) -> list[k.Bar]:
    return k.session_bars(day)


def dev_edge(pr: k.Profile) -> str:
    """Kit reading: the developing (open) end of the bracket is the value-area edge on the last price's side."""
    k.reading("developing bracket: the open end is the value-area edge on the last price's side (PD-1 leaves the side "
              "unworded)")
    mid = (pr.va[0] + pr.va[1] + 1) * pr.row_ticks / 2
    return "top" if pr.last_ticks >= mid else "bottom"


def opts_for(pr: k.Profile) -> PlotOpts:
    return PlotOpts(developing_edge=None if pr.complete else dev_edge(pr))


def levels_line(pr: k.Profile) -> str:
    k.not_drawn_w(33, "announcement-only (the panel's polite region, latest value only, at most once per 2 s: "
                      f"§11 L{k.L('- **Announcements:** POC / VAH / VAL announced')}, R-4); the annotation's "
                      "'Levels (derived)' line carries the values it would announce")
    return (f"Levels (derived): POC {price(pr.poc * pr.row_ticks)}, VAH {price(pr.va[1] * pr.row_ticks)}, VAL "
            f"{price(pr.va[0] * pr.row_ticks)}; {len(pr.rows)} rows of {pr.row_ticks} ticks; HVN "
            f"{len(pr.hvn)}, LVN {len(pr.lvn)}; {'complete' if pr.complete else 'developing'}")


def docked_frame(fid: str, dk: Docked) -> tuple[Node, DockedOut]:
    out = docked_window(dk)
    return frame(fid, out.kids), out


# --- board 01: docked anatomy at three densities + the degraded inset (§3.1)
def f_docked(fid: str, density: str) -> tuple[Node, list[str]]:
    pr = k.FINAL
    p = Panel(pr, density=density, opts=opts_for(pr))
    node_, _o = docked_frame(fid, Docked(p, day_bars(pr.start)))
    d = DENSITY[density]
    return node_, [f"{pr.label} ({pr.kind}), Volume; bound chart {k.SYMBOL} {INTERVAL}; panel {PANEL_W} px (§2, "
                   f"PROPOSED); rows / fields {d['row']} px, inset {k.PX[d['inset']]} px (§2; R-3: spacing only)",
                   levels_line(pr),
                   "The status slot is empty: the session is recorded in full (partial, CMP-227 and the degraded "
                   "tag appear only in their states: board 04 and this board's inset)",
                   "Body: POC rail, VAH / VAL ticks, the value-area bracket with 'VA' (closed: final), words + prices "
                   "on named levels only (PD-8); HVN '>' / LVN '<' glyphs keyed in the legend (§5.3)",
                   "E40 slot: the level context menu reserves one unlabelled slot; nothing is drawn (§10.5)"]


def f_degraded(fid: str) -> tuple[Node, list[str]]:
    pr = k.DEVELOPING
    tag = chip("degraded tag", k.W(16), "pending", note="E17's corner tag (D02E17:221), nothing invented; announced "
                                                       "by E17's system notice, not here")
    p = Panel(pr, status=[tag], opts=opts_for(pr))
    out = docked_window(Docked(p, day_bars(pr.start)))
    panel = dict(out.panel, x=0, y=0)
    return frame(fid, [panel]), [
        f"Inset: the docked panel alone ({PANEL_W} × {k.INSET_SIZE[1]}, the window body); {pr.label}, developing",
        f"W-16 '{k.W(16)}' in the status slot, last (§3.1 order), while profile.{{symbol}}.{{kind}} is in "
        "degraded_topics (`23`:1368); nothing else changes (D02-C8); D02-OQ4: shown, as E17 specifies",
        "Glyph: 'pending' from the extra icon set (a clock-like mark; E17's own glyph is E17-D02's)"]


# --- board 02: overlay at three densities (§3.2); the three inputs (§15 L1: volume, delta and TPO on boards 01, 02)
VISIBLE_BARS = [b for b in k.BARS if b.start >= k.NOW - timedelta(hours=24)]
VISIBLE = k.build_profile("Visible range", "Visible range", VISIBLE_BARS, complete=False)


def f_overlay(fid: str, density: str, inp: str) -> tuple[Node, list[str]]:
    if inp == "tpo":
        pr, period, bars = k.DEVELOPING, "Session", day_bars(k.TODAY)
    else:
        pr, period, bars = VISIBLE, "Visible range", VISIBLE_BARS
    ov = Overlay(pr, bars, density=density, inp=inp, period=period, slots=round(len(bars) * 1.45))
    k.reading("overlay: the chart keeps empty room right of its last bar (1.45 × the bars' slots, kit choice), so the "
              "right-docked profile reads mostly over empty plot; labels sit on a canvas backing")
    kids, _sc, _row = overlay_window(ov)
    d = DENSITY[density]
    lines = [f"{period}, {INPUT_WORD[inp]}; CMP-183 on the pane's own CMP-188 (shares its price -> y; never W-2 / "
             f"W-3); controls {d['row']} px, inset {k.PX[d['inset']]} px (R-3)",
             levels_line(pr if inp != "tpo" else tpo_profile(pr)),
             "Legend row: Profile · period ▾ · input ▾ · Histogram │ Table · Settings, the status slot, then ⋯ "
             "(aria-expanded; a non-modal disclosure popover: VA %, Row size, Show VWAP, Presets); Esc returns focus "
             "to ⋯",
             "Focus order: the chart's own stops (toolbar, plot, drawings group), then this row, then ⋯, then the "
             "histogram mirror or the table (§3.2)"]
    if inp == "delta":
        lines.append("Delta: net delta per row either side of a centre line (sign by side, not by grey); a centred "
                     "tick on a zero-delta row, nothing on an untraded row (§3.3); net delta as text on named levels")
    if inp == "tpo":
        lines.append("TPO: the letter margin left of the bars is a slot (letters: SCR-038/tpo-detail, not drawn); "
                     f"the initial balance a solid bar labelled IB ({k.IB_PERIODS} periods, kit choice); single "
                     "prints a solid glyph in the margin (§3.3); Period Session (overlay default is Visible range; "
                     "the IB needs a session start)")
    reading_ = ("board 02 draws the three inputs §15 places on boards 01 and 02 (compact Volume, dense Delta, "
                "comfortable TPO); board 01 keeps Volume at all three densities for the R-3 comparison; every "
                "board 02 frame carries the same controls and words, only the input word and its marks differ")
    k.reading(reading_)
    return frame(fid, kids), lines


# --- board 03: axis alignment (§4)
def boundary_markers(pr: k.Profile, sc: Scale, rows: list[int], x0: float, x1: float, top: int) -> list[Node]:
    """Board markers: each row boundary b(k) = price_origin + k × aggregation_ticks × tick_size drawn as a 1 px
    color.text.tertiary line from the chart's price axis to the panel, at the y of THIS frame's transform."""
    out = []
    for r in rows:
        y = sc.y(r * pr.row_ticks)
        out.append(rect(f"board marker · boundary {r * pr.row_ticks}", round(x1 - x0), 1, C3, x=round(x0),
                        y=round(y) - top, note="board marker: a row boundary through the chart's price -> y"))
    return out


def row_table(pr: k.Profile, sc: Scale, rows: list[int]) -> list[str]:
    out = []
    for r in rows:
        y, h = row_y(pr, sc, r)
        out.append(f"row {price(r * pr.row_ticks)}–{price((r + 1) * pr.row_ticks)}: y {y:.1f}–{y + h:.1f} px, "
                   f"h {h:.2f} px")
    return out


def f_aligned_linear(fid: str) -> tuple[Node, list[str]]:
    pr = k.FINAL
    p = Panel(pr, opts=opts_for(pr))
    out = docked_window(Docked(p, day_bars(pr.start)))
    rows = [pr.poc - 1, pr.poc, pr.poc + 1]
    lines = row_table(pr, out.sc, rows)
    mk = marker("row boundaries", [*lines, "linear: equal row heights (§4.1 rule 3)"], w=300,
                title=gap_word("Row boundaries (this frame)", "board marker title (kit)"))
    chart_w = k.WIN_W - PANEL_W
    extra = boundary_markers(pr, out.sc, [rows[0], rows[1], rows[2], rows[2] + 1], chart_w - PRICE_AXIS - 40,
                             chart_w + 8, 0)
    kids = out.kids + extra + [sized(mk) | {"x": 24, "y": TOP_H + CHART_HEAD + 24}]
    return frame(fid, kids), [
        f"{pr.label}, linear; W-2 '{k.W(2, symbol=k.SYMBOL, interval=INTERVAL)}' (the alignment status, a menu "
        "button named by its text + ', change chart')", *lines,
        "Each boundary price goes through the bound chart's own price -> y of the same frame (`26`:216–221); never "
        "a separate scale, never an interpolated copy (§4.1 rule 2)"]


ALL_DONE = [d for d in k.SESSION_DAYS if d in k.SESSIONS and k.SESSIONS[d].complete]
LOG_ROW = 2000  # kit choice: 200.0 USDT rows over the world's whole range, so the log heights are measurable


def f_aligned_log(fid: str) -> tuple[Node, list[str]]:
    bars = [b for b in k.BARS if b.start < ALL_DONE[-1] + timedelta(days=1)]
    pr = k.build_profile("Composite", "Composite", bars, row_ticks=LOG_ROW, complete=True)
    cbars = agg(bars, 8)
    p = Panel(pr, period="Composite", interval="4h", opts=PlotOpts())
    out = docked_window(Docked(p, cbars, slots=len(cbars) + 4, every=12, fmt="%d %b", log=True))
    hi_r, lo_r = max(pr.rows), min(pr.rows)
    lines = row_table(pr, out.sc, [hi_r, lo_r])
    mk = marker("log heights", [*lines, "log: rows at higher prices are drawn thinner, at their true log heights; "
                                "never re-gridded (§4.1 rule 3)"], w=320,
                title=gap_word("Log row heights (this frame)", "board marker title (kit)"))
    chart_w = k.WIN_W - PANEL_W
    extra = boundary_markers(pr, out.sc, [hi_r + 1, hi_r, lo_r + 1, lo_r], chart_w - PRICE_AXIS - 40, chart_w + 8,
                             0)
    kids = out.kids + extra + [sized(mk) | {"x": 24, "y": TOP_H + CHART_HEAD + 24}]
    return frame(fid, kids), [
        f"Composite of the {len(ALL_DONE)} complete sessions ({dmon(ALL_DONE[0])} – {dmon(ALL_DONE[-1])}), row size "
        f"{LOG_ROW} ticks (kit choice); the chart in log mode, 4-hour candles", *lines,
        f"Top / bottom row height ratio {row_y(pr, out.sc, hi_r)[1] / row_y(pr, out.sc, lo_r)[1]:.3f} = the "
        "log mapping's (`26`:221)"]


MIDFIT = (Decimal("0.40"), Decimal("0.20"))  # kit choice: two consecutive auto-fit frames, the range still 40 % / 20 %
# wider than its end state on each side


def f_aligned_mid_fit(fid: str) -> tuple[Node, list[str]]:
    pr = k.DEVELOPING
    lo_t, hi_t = min(pr.rows) * pr.row_ticks, (max(pr.rows) + 1) * pr.row_ticks
    span = hi_t - lo_t
    halves, lines = [], []
    half_w = k.WIN_W // 2
    for i, f in enumerate(MIDFIT, 1):
        p = Panel(pr, opts=opts_for(pr))
        view = (int(lo_t - span * f), int(hi_t + span * f))
        out = docked_window(Docked(p, day_bars(pr.start), view=view, every=12), w=half_w)
        lo_p, hi_p = price(int(out.sc.lo)), price(int(out.sc.hi))
        poc_y = row_y(pr, out.sc, pr.poc)
        mk = marker(f"auto-fit frame {i}", [f"priceLow {lo_p} · priceHigh {hi_p} (this frame)",
                                            f"POC row y {poc_y[0]:.1f} px in the chart and the panel, h "
                                            f"{poc_y[1]:.2f} px"], w=280,
                    title=gap_word(f"Auto-fit frame {i} of 2", "board marker title (kit)"))
        halves.append(box(f"auto-fit frame {i}", [*out.kids, sized(mk) | {"x": 12, "y": TOP_H + CHART_HEAD + 8}],
                          {"clip": True, "fill": k.CANVAS}, w=half_w, h=k.WIN_H, x=(i - 1) * half_w, y=0,
                          note="one frame of an auto-fit; both aligned"))
        lines.append(f"frame {i}: priceLow {lo_p}, priceHigh {hi_p} (the range {int(f * 100)} % wider than its end "
                     f"state each side, kit choice); POC row at y {poc_y[0]:.1f} px, h {poc_y[1]:.2f} px")
    sep = rect("board marker · frame divider", 2, k.WIN_H, C1, x=half_w - 1, y=0)
    return frame(fid, [*halves, sep]), [
        "Two frames of one auto-fit side by side (§4.3 'two stacked frames', laid out left to right so each keeps "
        "the full window height, kit choice), both aligned: the panel reads the priceLow / priceHigh of the frame "
        "being drawn (auto-scale at most once per frame, `26`:228; sync once per frame, `26`:229); never the "
        "animation's end state, never a frame late (§4.1 rule 4)", *lines,
        f"Each half is a {half_w} × {k.WIN_H} window (the chart narrower; the panel {PANEL_W} px); motion "
        "choreography is E19-D05's"]


def f_not_aligned(fid: str) -> tuple[Node, list[str]]:
    pr = k.DEVELOPING
    p = Panel(pr, aligned=False, opts=opts_for(pr))
    out = docked_window(Docked(p, day_bars(pr.start), pct=True))
    ann = hidden(k.W(3), label=gap_word("announced once, polite", "board marker title (kit): the R-4 announcement"))
    kids = out.kids + [sized(ann) | {"x": 24, "y": TOP_H + CHART_HEAD + 24}]
    return frame(fid, kids), [
        f"The bound chart in percent mode (`15`:2426): the panel draws its own CMP-188 on its left edge and the header "
        f"says W-3 '{k.W(3)}' (§4.1 rule 6); it never shows a misaligned histogram beside a chart",
        "Also W-3 when the chart shows another symbol, is inverted, closed or hidden, or is log with a price <= 0 in "
        "range (`26`:772) — not drawn separately, the text is binding",
        "W-3 announced once, polite, when alignment is lost; W-2 once when regained; a flapping condition coalesced "
        "to the latest state (R-4)"]


# --- board 04: data states (§6)
def gap_ranges(a: datetime, b: datetime) -> list[tuple[datetime, datetime]]:
    """The ranges in [a, b) with no bar (no data at all), from the world."""
    have = sorted(x.start for x in k.BARS if a <= x.start < b)
    out, t = [], a
    for s in have:
        if s > t:
            out.append((t, s))
        t = s + k.P30
    if t < b:
        out.append((t, b))
    return out


def hours(ranges: list[tuple[datetime, datetime]]) -> str:
    n = sum((y - x for x, y in ranges), timedelta()) / timedelta(hours=1)
    k.copy_gap('"{n} h": the kit\'s duration form for W-7\'s {duration} (§12 gives none)')
    return f"{n:g} h"


def partial_parts(days: list[datetime]) -> tuple[k.Profile, list[Node], list[str], str, list[k.Bar]]:
    """A composite request over `days`: its profile, the status slot (partial chip; CMP-227 when bars-only data is in
    it), the notes (W-7; W-9) and W-21."""
    a, b = days[0], days[-1] + timedelta(days=1)
    bars = k.bars_between(a, b)
    rec_days = [d for d in days if k.bars_between(d, d + timedelta(days=1))]
    gaps = gap_ranges(a, b)
    pr = k.build_profile("Composite", "Composite", bars, complete=True)
    status = [chip("partial chip", k.W(6, n=str(len(rec_days)), m=str(len(days))), "info",
                   note="CMP-011 info; not a stop; W-6 announced once when it appears")]
    notes = [k.W(7, k=str(len(gaps)), duration=hours(gaps))]
    if any(x.approximated for x in bars):
        status.append(estimated_badge())
        notes.append(k.W(9, **{"HH:MM": hm(k.TICKS_FROM)}))
    cov = k.W(21, **{"from": dmon(rec_days[0]), "to": dmon(rec_days[-1]), "n": str(len(rec_days)),
                     "m": str(len(days))})
    return pr, status, notes, cov, bars


def f_loading(fid: str) -> tuple[Node, list[str]]:
    for num, state in ((17, "SCR-038/load-failed"), (18, "SCR-038/stale")):  # the data states this board does not draw
        k.not_drawn_w(num, f"outside the 10-board cap; §0 L{k.NOT_DRAWN_LINE} declares {state} not drawn")
    pr = k.DEVELOPING
    p = Panel(pr, busy=True, opts=opts_for(pr))
    node_, _o = docked_frame(fid, Docked(p, day_bars(pr.start)))
    return node_, ["Bootstrap GET /market/profile in flight: the last frame kept, aria-busy on the body, a thin busy "
                   "bar in the header; no spinner on the plot; header controls operable; no announcement (§6)",
                   "First load (not drawn): the header and a legend skeleton"]


PARTIAL_DAYS = [k.DAY0 - timedelta(days=2) + timedelta(days=i) for i in range(7)]  # kit choice: 8–14 Oct requested


def f_partial(fid: str) -> tuple[Node, list[str]]:
    pr, status, notes, cov, bars = partial_parts(PARTIAL_DAYS)
    cb = agg(bars, 4)
    p = Panel(pr, period="Composite", interval="2h", status=status, status_notes=notes, covered=cov,
              opts=PlotOpts())
    node_, _o = docked_frame(fid, Docked(p, cb, slots=len(cb) + 4, every=12, fmt="%d %b"))
    return node_, [f"A composite request {dmon(PARTIAL_DAYS[0])} – {dmon(PARTIAL_DAYS[-1])} (kit choice): days with "
                   f"data from the world's start ({dmon(k.DAY0)}); gap ranges derived from the bars", levels_line(pr),
                   "Status slot left to right: the partial chip (W-6), then CMP-227 (the window also holds bars-only "
                   "data before the recorder's trades), >= 4 px apart (PD-5); W-7 under the chip; W-21 in the legend",
                   "No hatch for partial-ness (D05E16:285): only the bars-only part carries the estimated slot"]


def f_approximated(fid: str) -> tuple[Node, list[str]]:
    pr = k.SESSIONS[k.TICKS_FROM.replace(hour=0)]
    p = Panel(pr, status=[estimated_badge()], status_notes=[k.W(9, **{"HH:MM": hm(k.TICKS_FROM)})],
              opts=opts_for(pr))
    out = docked_window(Docked(p, day_bars(pr.start)))
    meth = marker("methodology drawer (SCR-058)", [k.W(8, 1)], w=300,
                  title=gap_word("Methodology (SCR-058, opened by the badge)", "board marker title (kit)"))
    node_ = frame(fid, out.kids + [sized(meth) | {"x": 24, "y": TOP_H + CHART_HEAD + 24}])
    k.reading("estimated slot: each bar's bars-only part is drawn as an outlined segment after its recorded part "
              "(the hatch is E19-D03's, D02-C10)")
    return node_, [f"{pr.label}: trades recorded from {hm(k.TICKS_FROM)} UTC, bars only before (approximated, "
                   "`14`:1009)", levels_line(pr),
                   "CMP-227 section grade W-8 after the title (in the status slot, never scrolling out while the "
                   "histogram shows); the approximated part of each row as the estimated-hatch slot; delta and TPO "
                   "over that portion absent with W-9 (PD-4); the badge opens SCR-058; W-8 announced once",
                   f"W-8's methodology line '{k.W(8, 1)}' drawn in a board marker: SCR-058's drawer is not this "
                   "spec's (the text is binding for its layout)"]


def f_developing(fid: str) -> tuple[Node, list[str]]:
    pr = k.DEVELOPING
    node_, _o = docked_frame(fid, Docked(Panel(pr, opts=opts_for(pr)), day_bars(pr.start)))
    return node_, [f"complete false: W-4 '{k.W(4, **{'HH:MM': hm(k.NOW)})}' in the header and the legend; the "
                   f"bracket open at its developing edge ({dev_edge(pr)}) (PD-1); no announcement per update",
                   levels_line(pr)]


def f_final(fid: str) -> tuple[Node, list[str]]:
    pr = k.FINAL
    node_, _o = docked_frame(fid, Docked(Panel(pr, opts=opts_for(pr)), day_bars(pr.start)))
    return node_, [f"complete true: W-5 '{k.W(5)}'; the bracket closed; W-5 announced once", levels_line(pr)]


# --- board 05: no history (§6; T2 §1.4)
def empty_body(heading: str, body: str, tail: Node | None, *, note: str) -> Callable[[int, int], list[Node]]:
    def make(w: int, h: int) -> list[Node]:
        inner = w - 32
        kids = [text("heading", heading, k.LABEL, C1, w=inner), text("body", body, k.CAPTION, C2, w=inner), tail]
        v = vbox("CMP-026 recording-not-started", kids, {"gap": k.STACK_SM, "pad": k.INSET_LG}, w=w, note=note)
        hh = math.ceil(k.est_height(v))
        return [dict(v, h=hh, x=0, y=16)]
    return make


def f_no_history(fid: str, who: str) -> tuple[Node, list[str]]:
    heading = k.W(11, symbol=k.SYMBOL)
    body = k.W(12)
    if who == "owner":
        tail: Node | None = hbox("CTA", [text("label", k.W(13), k.CAPTION, C1)],
                                 {"padX": k.INSET_MD, "radius": k.R_CONTROL, "fill": k.RAISED, "stroke": C1,
                                  "strokeWidth": k.HAIR, "strokeAlign": "inner"}, h=24,
                                 note="CTA -> SCR-140 (`14`:83); in the Tab order; initial focus stays on the header")
        lines = ["The Owner, not viewing as: CMP-026 recording-not-started in the body: heading W-11 (never recorded), "
                 "body W-12, CTA W-13 -> SCR-140; no announcement (static)",
                 f"W-10 is the heading when a start exists ('{k.W(10, ts=TS_FORM)}' with this world's first recorded "
                 "minute): same layout, the text is binding"]
    elif who == "sentence":
        tail = text("reason", k.W(14), k.CAPTION, C2, w=PANEL_W - 32,
                    note="T2 sentence form: the reason as a sentence; no button, no glyph (§1.4)")
        lines = ["A Manager or a Viewer: T2 (§1.4), the sentence form (CMP-026 with cta omitted): heading, W-12, then "
                 "W-14 (rbac.owner_only, verb 'change recording'); no button, no glyph, no CTA stop; no CMP-079 "
                 "control and no CMP-019 lock (nothing to gate)"]
    else:
        tail = text("reason", k.W(15, user=VIEW_AS_USER), k.CAPTION, C2, w=PANEL_W - 32,
                    note="T2 sentence form, the view-as leg first (step 3a): rbac.view_as")
        k.copy_gap(f'"{VIEW_AS_USER}": W-15\'s {{user}}, a synthetic display name (no account identifier, R-1)')
        lines = ["The Owner viewing as a user: T2 (§1.4), the sentence form, the view-as leg first: heading, W-12, "
                 "then W-15 (rbac.view_as); no button, no glyph, no CTA stop"]
    p = Panel(None, opts=PlotOpts())
    p.body = empty_body(heading, body, tail, note="recording-not-started; heading W-11, body W-12")
    node_, _o = docked_frame(fid, Docked(p, day_bars(k.TODAY)))
    k.reading("board 05 condition: the window has no recorded history and BTCUSDT was never recorded (a synthetic "
              "condition for this board's three frames, so W-11 holds; the bound chart still shows public bars); "
              "the three variants share it so they compare")
    return node_, lines + ["The header and legend stay; initial focus stays on the header; the body is static text"]


TS_FORM = f"{k.DAY0:%d %b %Y %H:%M} UTC"  # kit choice: W-10's {ts} as the world's first recorded minute


# --- board 06: edge density (§7)
def edge_suffix() -> list[k.Bar]:
    """The longest suffix of the world's bars whose range fits 5 000 rows at row size 1 (`14`:1013)."""
    best: list[k.Bar] = []
    for i in range(len(k.BARS) - 1, -1, -1):
        s = k.BARS[i:]
        if max(b.top for b in s) - min(b.bottom for b in s) + 1 > 5000:
            break
        best = s
    return best


def f_edge5000(fid: str) -> tuple[Node, list[str]]:
    bars = edge_suffix()
    pr = k.build_profile("Fixed range", "Fixed range", bars, row_ticks=1, complete=False)
    p = Panel(pr, period="Fixed range", opts=PlotOpts(developing_edge=dev_edge(pr)))
    out = docked_window(Docked(p, bars, slots=len(bars) + 4, every=max(1, len(bars) // 6)))
    ph = out.panel_y1 - out.panel_y0
    mins = len(bars) * 30
    return frame(fid, out.kids), [
        f"{len(pr.rows):,} rows at row size 1 (the longest bar suffix within 5 000 rows: {len(bars)} bars, "
        f"{mins} min fixed range ending {hm(k.NOW)} UTC) in a {ph:.0f} px plot (§7 names 620 px, PROPOSED; this "
        f"frame's plot is what the window leaves)",
        f"Rows merge by summing adjacent levels until >= 2 px (`26`:238): {p.merged_k} levels per drawn row, W-20 in "
        "the legend; price text on named levels only, never below the 10 px floor (PD-8)", levels_line(pr)]


def two_level() -> tuple[k.Profile, list[k.Bar]]:
    """§7 edge-two-level, a dead symbol: two traded levels on synthetic BTCUSDT prices (kit: rows 100 ticks, the
    second level 6 rows under the first; the first carries 80 % of the volume, so POC = VAH = VAL at VA 70 %; the
    second trades both sides evenly: zero net delta). Its bars: 12 flat 30-minute bars ending at the clock."""
    top_r = k.last_price() // k.ROW_TICKS
    lv = {top_r: k.Level(vol=800, buy=520, sell=280), top_r - 6: k.Level(vol=200, buy=100, sell=100)}
    start = k.NOW - 12 * k.P30
    pr = k.Profile("Session", "Session", start, k.NOW, k.ROW_TICKS, 30, lv, True,
                   Decimal(sum(r * k.ROW_TICKS * x.vol for r, x in lv.items())) / 1000, top_r * k.ROW_TICKS + 50)
    pr = k.finish(pr)
    bars = []
    for i in range(12):
        r = top_r - 6 if i % 4 == 3 else top_r
        t = r * k.ROW_TICKS + 50
        bars.append(k.Bar(start + i * k.P30, t, t + 20, t - 20, t, 80, None))
    return pr, bars


def f_edge_two_level(fid: str) -> tuple[Node, list[str]]:
    pr, bars = two_level()
    view = (min(pr.rows) * pr.row_ticks - 4 * pr.row_ticks, (max(pr.rows) + 5) * pr.row_ticks)
    p = Panel(pr, inp="delta", opts=PlotOpts(developing_edge=None))
    out = docked_window(Docked(p, bars, slots=16, every=4, view=view))
    zr, ur = min(pr.rows), pr.poc - 2
    m1 = hidden(k.W(27, 1), label=gap_word("mirror reading · zero-delta row", "board marker title (kit)"))
    m2 = hidden(k.W(27, 0), label=gap_word("mirror reading · untraded row", "board marker title (kit)"))
    zy = out.panel_y0 + row_y(pr, out.sc.shift(out.panel_y0), zr)[0]
    uy = out.panel_y0 + row_y(pr, out.sc.shift(out.panel_y0), ur)[0]
    x = k.WIN_W - PANEL_W - PRICE_AXIS - 316
    kids = out.kids + [sized(m1) | {"x": x, "y": round(zy) - 10}, sized(m2) | {"x": x, "y": round(uy) - 70}]
    return frame(fid, kids), [
        "A dead symbol (kit: two traded levels on synthetic BTCUSDT prices, declared): POC, VAH and VAL coincide and "
        f"are all labelled (stacked words, one price {price(pr.poc * pr.row_ticks)})",
        f"Input Delta: the POC row's net delta {signed_qty(pr.lv(pr.poc).delta)} as a bar; the second traded row "
        f"({price(zr * pr.row_ticks)}) nets zero: the centred tick; every other row in range is untraded: no mark "
        "(§3.3); mirror words W-27 shown as board markers",
        "Untraded rows are never nodes (levels are sparse); the bracket spans the one VA row"]


COMPOSITE_30 = [ALL_DONE[-1] - timedelta(days=29 - i) for i in range(30)]  # the 30 sessions to the last complete


def f_edge_composite(fid: str) -> tuple[Node, list[str]]:
    pr, status, notes, cov, bars = partial_parts(COMPOSITE_30)
    pr = k.build_profile("Composite", "Composite", bars, row_ticks=500, complete=True)
    cb = agg(bars, 8)
    p = Panel(pr, period="Composite", interval="4h", status=status, status_notes=notes, covered=cov,
              opts=PlotOpts())
    node_, _o = docked_frame(fid, Docked(p, cb, slots=len(cb) + 4, every=12, fmt="%d %b"))
    return node_, [f"A composite of 30 sessions ({dmon(COMPOSITE_30[0])} – {dmon(COMPOSITE_30[-1])}); recorded "
                   f"history covers what exists: W-21 '{cov}' in the legend (MEMO G-4), the partial chip and W-7 for "
                   "the gaps, CMP-227 for the bars-only part (PD-5 order)",
                   "Row size 500 ticks (kit choice, so rows stay >= 2 px); the request does not cross the 90-day "
                   "coverage horizon (D05E16:202), so W-21 carries no horizon note: the text is binding for that case",
                   levels_line(pr)]


def f_va_spans(fid: str) -> tuple[Node, list[str]]:
    pr = k.FINAL
    va_lo, va_hi = pr.va[0] * pr.row_ticks, (pr.va[1] + 1) * pr.row_ticks
    inset = (va_hi - va_lo) // 6
    view = (va_lo + inset, va_hi - inset)  # kit choice: zoomed in so the value area spans the whole view
    p = Panel(pr, opts=PlotOpts(pins=True))
    node_, _o = docked_frame(fid, Docked(p, day_bars(pr.start), view=view))
    return node_, [f"The view zoomed into the value area ({price(view[0])} – {price(view[1])}, kit choice): VAH and "
                   "VAL drawn as edge pins at the top and bottom of the plot with word, price and an arrow (W-26); "
                   "the bracket runs the full height, open at both ends", levels_line(pr)]


# --- board 07: the table alternative and focus (§11)
def table_cols(pr: k.Profile) -> list[k.Col]:
    def width(strings: list[str], typo: str) -> int:
        return int(math.ceil((max(k.text_w(x, typo) for x in strings) + 16) / 8) * 8)
    words = [price(r * pr.row_ticks) + " POC" for r in pr.rows]
    vols = [qty(pr.lv(r).vol) for r in pr.rows]
    return [k.Col("price", say("Price"), width(words, k.NUM_SM)),
            k.Col("volume", say("Volume"), width(vols + ["Volume"], k.NUM_SM), True),
            k.Col("delta", say("Delta"), width([signed_qty(pr.lv(r).delta) for r in pr.rows] + ["Delta"], k.NUM_SM),
                  True),
            k.Col("pct", say("% of POC"), width(["100 %", "% of POC"], k.CAPTION), True),
            k.Col("va", say("Value area"), width([say("Outside VA"), "Value area"], k.CAPTION))]


def level_word(pr: k.Profile, r: int) -> str:
    return "POC" if r == pr.poc else "VAH" if r == pr.va[1] else "VAL" if r == pr.va[0] else ""


def table_body(pr: k.Profile) -> Callable[[int, int], list[Node]]:
    cols = table_cols(pr)
    order = [pr.poc] + [r for r in sorted(pr.rows, reverse=True) if r != pr.poc and pr.lv(r).vol]

    def make(w: int, h: int) -> list[Node]:
        n = int((h - 24 - 40 - 12) // k.ROW_H)
        rows = []
        for r in order[:n]:
            lw = level_word(pr, r)
            pw_ = (price(r * pr.row_ticks) + f" {lw}").strip()
            cells = {"price": pw_, "volume": qty(pr.lv(r).vol), "delta": signed_qty(pr.lv(r).delta),
                     "pct": f"{pr.lv(r).vol * 100 // pr.max_vol} %",
                     "va": say("In VA") if pr.va[0] <= r <= pr.va[1] else say("Outside VA")}
            rows.append(k.table_row(cols, cells, f"row · {r * pr.row_ticks}", h=k.ROW_H,
                                    colors={"price": C1, "volume": C1, "delta": C1, "pct": C2, "va": C2}))
        full = sum(c.w for c in cols)
        tbl = vbox("table", [k.header_row(cols), *rows], None, w=full, h=24 + len(rows) * k.ROW_H,
                   note='a semantic table: <th scope="col"> headers, Price a <th scope="row">; aria-sort tri-state, '
                        "the third press returns to this order; Value area filter-only (In VA / Outside VA)")
        vis = w - 16
        track = box("horizontal scroll", [rect("thumb", round(vis * vis / full), 6, C3, x=0, y=0)],
                    {"fill": k.RAISED}, w=vis, h=6, x=8, y=24 + len(rows) * k.ROW_H + 4,
                    note="Price stays as a sticky row header; the other columns scroll (§11 R1)")
        more = control("load more rows", say("load more rows"), h=24, note="keyboard-operable (`05`:195)")
        clip = box("table viewport", [tbl | {"x": 0, "y": 0}], {"clip": True}, w=vis, h=24 + len(rows) * k.ROW_H,
                   x=8, y=0)
        return [clip, track, sized(more) | {"x": 8, "y": 24 + len(rows) * k.ROW_H + 16}]
    return make


A6_COLS = ("TPO count", "Node", "Naked POC", "Single print", "Developing / Final", "Estimated")


def f_table(fid: str) -> tuple[Node, list[str]]:
    pr = k.DEVELOPING
    p = Panel(pr, table=True, focus="switch", opts=opts_for(pr))
    p.body = table_body(pr)
    out = docked_window(Docked(p, day_bars(pr.start)))
    cols = table_cols(pr)
    order = marker("focus order", [say("header controls → histogram mirror → legend → table"),
                                   "Table view: the mirror is absent, the legend moves above the table: 1 header "
                                   "controls (the switch keeps focus) · 2 legend · 3 table"], w=320,
                   title=gap_word("Focus order", "board marker title (kit)"))
    a6 = marker("MEMO A-6 columns", [", ".join(say(c) for c in A6_COLS) + " (proposed, not built; E19-D06)"], w=320,
                title=gap_word("Further columns", "board marker title (kit)"))
    k.fallback("hidden")
    ann = marker("announced on the swap", [k.W(35, 0), k.W(35, 1)], w=300,
                 title=gap_word("announced on the swap", "the kit's marker title for a string a screen reader hears "
                                                         "(board marker)"))
    k.not_drawn_w(34, "announcement-only (Enter on a histogram-mirror row reads it, §11 "
                      f"L{k.L('- **Focus order:** header controls')}; the mirror is absent in Table view)")
    x = k.WIN_W - PANEL_W - PRICE_AXIS - 336
    kids = out.kids + [sized(order) | {"x": x, "y": TOP_H + CHART_HEAD + 16},
                       sized(a6) | {"x": x, "y": TOP_H + CHART_HEAD + 150},
                       sized(ann) | {"x": x, "y": TOP_H + CHART_HEAD + 250}]
    return frame(fid, kids), [
        "The Histogram │ Table switch (W-29) pressed on Table and focused (it keeps focus when toggled); Alt+T toggles "
        "from anywhere in the panel; each swap announces W-35 (both forms drawn in the marker: to Table, then back "
        "to Histogram)",
        f"Columns: {', '.join(c.label for c in cols)} ({sum(c.w for c in cols)} px; the panel shows {PANEL_W - 16} px: "
        "Price sticky, the rest scroll horizontally, no column dropped); cells padded 8 px a side",
        f"Rows: the POC row first in reading order ('{price(pr.poc * pr.row_ticks)} POC'), then descending price; "
        f"named levels carry their word in the Price cell; windowed with a keyboard-operable 'load more rows' "
        f"({len([r for r in pr.rows if pr.lv(r).vol])} traded rows)",
        "The overlay's table (a non-modal panel over the pane's right side, §3.2) is not drawn: the text is binding",
        levels_line(pr)]


# --- SCR-039 (§8): CMP-043 dialog on color.surface.overlay; CMP-065 sections; the CMP-228 preview pinned
DLG_W, DLG_H = (int(x) for x in S("760 × 640").split(" × "))  # §8.1 (PROPOSED)
FORM_W, PREVIEW_W = int(S("440 px")[:3]), int(S("280 px")[:3])  # §8.1 (PROPOSED)
HEAD_H = FOOT_H = 56  # kit choice
FIELD_LABEL_W = 150


def radio(label: str, on: bool) -> Node:
    dot = box("dot", [ellipse("inner", 6, 6, {"fill": C1}, x=4, y=4)] if on else [],
              {"radius": k.R_BADGE, "stroke": C1 if on else C2, "strokeWidth": k.HAIR, "strokeAlign": "inner",
               "fill": k.CANVAS}, w=14, h=14)
    return hbox(f"radio {label}".replace("/", k.SLASH), [dot, text("label", label, k.CAPTION, C1)],
                {"gap": k.INSET_XS}, h=20, note='role="radio"; aria-checked="true"' if on else None)


def checkbox(label: str, on: bool) -> Node:
    bx = box("box", [icon("check", "check", C1, x=1, y=1)] if on else [],
             {"radius": k.R_CONTROL, "fill": k.CANVAS, "stroke": C1 if on else C2, "strokeWidth": k.HAIR,
              "strokeAlign": "inner"}, w=14, h=14)
    return hbox(f"checkbox {label}".replace("/", k.SLASH), [bx, text("label", label, k.CAPTION, C1)],
                {"gap": k.INSET_XS}, h=20)


def tfield(name: str, value: str, *, w: int = 120, invalid: bool = False) -> Node:
    return hbox(name, [text("value", value, k.NUM_SM, C1)],
                {"padX": k.INSET_SM, "radius": k.R_CONTROL, "fill": k.CANVAS, "stroke": C1 if invalid else k.BORDER,
                 "strokeWidth": k.THICK if invalid else k.HAIR, "strokeAlign": "inner"}, w=w, h=24,
                note='aria-invalid="true"; aria-describedby its CMP-040 error' if invalid else None)


def field_row(label: str, ctl: Node, unit: str | None = None) -> Node:
    return hbox(f"field {label}".replace("/", k.SLASH), [text("label", label, k.CAPTION, C2, w=FIELD_LABEL_W), ctl,
                                                         text("unit", unit, k.CAPTION, C2) if unit else None],
                {"gap": k.INSET_SM}, h=24)


def message(name: str, words: str, glyph: str, *, note: str) -> Node:
    """CMP-040 inline error (danger) or the role="status" warning (warning): glyph + words under the field."""
    return hbox(name, [icon("glyph", glyph, C1), text("words", words, k.CAPTION, C1, w=FORM_W - 32 - 24)],
                {"gap": k.INSET_XS, "align": "start", "padL": k.INSET_XS}, w=FORM_W - 32, note=note)


def placeholder_line(w: int = 180) -> Node:
    k.copy_gap("the Period radios' one-line descriptions are `14`:1025's, unworded in this spec: each is a grey "
               "placeholder line (wire convention), linked by aria-describedby")
    return rect("description (placeholder line)", w, 6, C3, {"radius": k.R_CONTROL})


def section(title: str, kids: list[Node]) -> Node:
    return vbox(f"CMP-065 {title}".replace("/", k.SLASH), [text("title", title, k.LABEL, C1), *kids],
                {"gap": k.STACK_XS, "padY": k.INSET_XS}, w=FORM_W - 32)


@dataclass
class Dlg:
    mode: str = "Session"
    va: str = str(k.VA_PCT)
    row: str = str(k.ROW_TICKS)
    va_error: bool = False
    end_error: bool = False
    lookback: bool = False  # the composite look-back warning
    clamp: str | None = None  # the entered row size the clamp replaced (W-25)
    view_as: bool = False
    menu: bool = False  # the footer Presets menu open (view-as)
    scroll_to: str = "Period"  # the section at the top of the scrolled form column


MODES = ("Session", "Fixed range", "Visible range", "Anchored", "Composite")  # §5.1 (S-checked at use)
FIXED_START, FIXED_END = k.NOW - timedelta(hours=4), k.NOW - timedelta(hours=5)  # kit: an end before its start


def period_section(d: Dlg) -> Node:
    items: list[Node] = []
    for m in MODES:
        items.append(vbox(f"mode {m}", [radio(say(m), m == d.mode), placeholder_line()],
                          {"gap": k.STACK_XS, "padL": k.INSET_XS}, w=FORM_W - 32))
    opts: list[Node] = []
    if d.mode == "Session":
        opts = [hbox("anchor", [text("label", cap("anchor"), k.CAPTION, C2), radio(say("UTC day"), True),
                                radio(say("funding 8 h"), False), radio(say("custom HH:MM"), False)],
                     {"gap": k.INSET_SM}, h=20),
                checkbox(say("One per session, side by side"), False)]
    elif d.mode == "Fixed range":
        opts = [field_row(cap("duration"), stepper("duration", str(int((k.NOW - FIXED_START).total_seconds() // 60)),
                                                   w=72), say("min")),
                field_row(say("Start"), tfield("start", f"{FIXED_START:%d %b %H:%M}")),
                field_row(say("End"), tfield("end", f"{FIXED_END:%d %b %H:%M}", invalid=d.end_error))]
        k.copy_gap("start / end values: the kit's 'DD Mon HH:MM' UTC form (no format in §8)")
        if d.end_error:
            opts.append(message("CMP-040 error", k.W(23), "danger", note="inline error under End; W-23 once"))
    elif d.mode == "Composite":
        opts = [field_row(cap("look-back sessions"), stepper("look-back", str(len(COMPOSITE_30)), w=60)),
                hbox("composite anchor", [text("label", cap("anchor"), k.CAPTION, C2),
                                          *[radio(say(x), x == "session") for x in ("session", "day", "week",
                                                                                     "custom range")]],
                     {"gap": k.INSET_SM}, h=20)]
        if d.lookback:
            opts.append(message("look-back warning", k.W(24, n=str(len(ALL_DONE)), m=str(len(COMPOSITE_30))),
                                "warning", note='role="status", a warning, not an error; Save stays enabled'))
    return section(say("Period"), [*items, *opts])


def rows_section(d: Dlg) -> Node:
    kids: list[Node] = [
        hbox("input", [text("label", say("Input"), k.CAPTION, C2, w=FIELD_LABEL_W),
                       *[radio(say(w), w == "Volume") for w in ("Volume", "Delta", "TPO")]], {"gap": k.INSET_SM}, h=20),
        field_row(say("Row size (ticks)"), stepper("row size", d.row, w=72, invalid=False))]
    if d.clamp:
        kids.append(message("clamp message", k.W(25, tick=str(k.TICK), entered=d.clamp), "info",
                            note="shown inline under the field and announced politely once; never a silent "
                                 "correction (§9)"))
    kids.append(field_row(say("Value area %"), stepper("value area", d.va, w=60, invalid=d.va_error)))
    if d.va_error:
        kids.append(message("CMP-040 error", k.W(22), "danger", note="CMP-040 under the field; Save moves focus to "
                                                                   "the first invalid field; W-22 once"))
    kids += [hbox("VA presets", [text("label", gap_word("Presets", "the VA % preset chips' label (§8.1 'presets "
                                                                  "68 / 70 / 80')"), k.CAPTION, C2, w=FIELD_LABEL_W),
                                 *[control(f"preset {v}", v, h=20, pressed=v == str(k.VA_PCT))
                                   for v in say("68 / 70 / 80").split(" / ")]], {"gap": k.INSET_XS}, h=20),
             hbox("algorithm", [radio(say("Single step"), True), radio(say("Two-row TPO"), False)],
                  {"gap": k.INSET_SM}, h=20, note="D02-G2: no request parameter; drawn, not wired (R-5)"),
             text("help 1", k.W(28, 0), k.CAPTION, C2, w=FORM_W - 32),
             text("help 2", k.W(28, 1), k.CAPTION, C2, w=FORM_W - 32)]
    return section(say("Rows and value area"), kids)


def levels_section() -> Node:
    return section(say("Levels and overlays"), [
        checkbox(cap("show developing value area"), True), checkbox(cap("extend POC / VA lines to the right"), False),
        checkbox(say("HVN / LVN marking"), True),
        field_row(cap("naked POC, nearest N"), stepper("nearest N", "5", w=52)),
        checkbox(say("VWAP ±1σ / ±2σ"), False)])


def tpo_section() -> Node:
    return section(say("TPO"), [
        field_row(say("TPO period"), stepper("TPO period", "30", w=52), say("min")),
        field_row(say("TPO letter size"), stepper("letter size", None, w=52)),
        field_row(cap("initial balance periods"), stepper("IB periods", str(k.IB_PERIODS), w=52)),
        checkbox(cap("single prints"), True)])


def appearance_section() -> Node:
    slot = box("per-period colour slot", [text("words", say("per-period colour (a slot; hi-fi E19-D03)"), k.CAPTION,
                                               C3, x=8, y=4)],
               {"fill": k.CANVAS, "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                "radius": k.R_CONTROL}, w=FORM_W - 32, h=24)
    return section(say("Appearance"), [
        hbox("bars", [radio(cap("split"), False), radio(cap("merged bars"), True)], {"gap": k.INSET_SM}, h=20),
        checkbox(cap("combined volume + delta view"), False), slot])


def t2_menu_item(label: str, *, reason: str | None, focused: bool = False) -> Node:
    """A T2 2a menu item (§1.4, E09-D09 §2.1): CMP-019 lock + the full label in color.text.tertiary on the raised
    fill with the default hairline (never the disabled tokens); aria-disabled, arrow-reachable; the reason as its
    second line (SCR-038 header) or described by the dialog-header notice (SCR-039)."""
    if focused:
        k.fallback("focus")
    kids: list[Node] = [hbox("label row", [lock(), text("label", label, k.CAPTION, C3)], {"gap": k.INSET_XS}, h=16)]
    if reason:
        kids.append(text("reason", reason, k.CAPTION, C2, w=184))
    return vbox("item Save preset…", kids, {"gap": k.STACK_XS, "padX": k.INSET_SM, "padY": k.INSET_XS,
                                            "fill": k.RAISED, "stroke": C1 if focused else k.BORDER,
                                            "strokeWidth": k.THICK if focused else k.HAIR, "strokeAlign": "inner",
                                            "radius": k.R_CONTROL}, w=200,
                note='T2 2a: role="menuitem", aria-disabled="true", arrow-reachable; ' + (
                    "the reason is the item's own aria-describedby target, mounted with the menu" if reason else
                    "aria-describedby the dialog-header notice (G-T2.5)"))


def menu(name: str, items: list[Node], *, w: int = 216) -> Node:
    m = vbox(name, items, {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.OVERLAY, "stroke": k.BORDER,
                           "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CARD}, w=w)
    m["h"] = math.ceil(k.est_height(m))
    return m


def menu_item(label: str, *, checked: bool = False, focused: bool = False, note: str | None = None) -> Node:
    if focused:
        k.fallback("focus")
    return hbox(f"item {label}".replace("/", k.SLASH),
                [box("check slot", [icon("check", "check", C1)] if checked else [], None, w=12, h=12),
                 text("label", label, k.CAPTION, C1)],
                {"gap": k.INSET_XS, "padX": k.INSET_XS, "radius": k.R_CONTROL,
                 **({"stroke": C1, "strokeWidth": k.THICK, "strokeAlign": "inner"} if focused else {})},
                w=200, h=20, note=note)


USER_PRESETS = ("Preset A", "Preset B")  # kit choice: the user's presets (synthetic names)


def presets_items(*, view_as: bool, reason: str | None, focus_save: bool = False) -> list[Node]:
    k.copy_gap(f"the user's presets {', '.join(USER_PRESETS)}: synthetic names (kit choice; E19-D04 owns presets)")
    items = [menu_item(say("Session value"), note="the built-in preset (`11`:1852)"),
             *[menu_item(x) for x in USER_PRESETS], rect("separator", 200, 1, k.BORDER)]
    if view_as:
        items.append(t2_menu_item(say("Save preset…"), reason=reason, focused=focus_save))
    else:
        items.append(menu_item(say("Save preset…"), focused=focus_save))
    return items


def preview(d: Dlg, h: int) -> Node:
    """CMP-228 pinned (never scrolls), not a Tab stop, its text summary first; never announces per update (R-4)."""
    if d.mode == "Composite":
        pr = k.build_profile("Composite", "Composite", k.bars_between(COMPOSITE_30[0], COMPOSITE_30[-1] +
                                                                      timedelta(days=1)), row_ticks=500, complete=True)
        cov = k.W(21, **{"from": dmon(ALL_DONE[0]), "to": dmon(ALL_DONE[-1]), "n": str(len(ALL_DONE)),
                         "m": str(len(COMPOSITE_30))})
    else:
        pr, cov = k.DEVELOPING, None
    summary = [say("Session" if d.end_error else d.mode), say("Volume"), k.tpl("VA 70 %", {"70": str(k.VA_PCT)}),
               k.W(19, n=str(pr.row_ticks), price=price(pr.row_ticks))] + ([cov] if cov else [])
    head = text("summary", " · ".join(summary), k.CAPTION, C2, w=PREVIEW_W - 16)
    th = math.ceil(k.est_height(head)) + 16
    lo_t, hi_t = min(pr.rows) * pr.row_ticks, (max(pr.rows) + 1) * pr.row_ticks
    ph = h - th
    sc = fit_scale(lo_t, hi_t, 0, ph, 12, ph - 12)
    o = PlotOpts(developing_edge=None if pr.complete else dev_edge(pr))
    return box("CMP-228 preview", [head | {"x": 8, "y": 8}, plot(pr, sc, PREVIEW_W, ph, o) | {"x": 0, "y": th}],
               {"clip": True, "fill": k.CANVAS, "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"},
               w=PREVIEW_W, h=h, note="CMP-228 (kind 'profile' proposed, D02-A6); not a Tab stop; exposes its text "
                                      "summary; the last valid value while a field is invalid (D02-C2)")


def dialog(d: Dlg) -> Node:
    secs = [period_section(d), rows_section(d), levels_section(), tpo_section(), appearance_section()]
    form = vbox("form", secs, {"gap": k.STACK_SM}, w=FORM_W - 32)
    off = 0.0
    for s_ in secs:
        if s_["name"] == f"CMP-065 {d.scroll_to}":
            break
        off += k.est_height(s_) + 8
    body_h = DLG_H - HEAD_H - FOOT_H
    form_col = box("form column", [dict(form, h=math.ceil(k.est_height(form)), x=16, y=8 - round(off))],
                   {"clip": True}, w=FORM_W, h=body_h,
                   note="scrolls vertically (this frame: scrolled to its " + d.scroll_to + " section); no horizontal "
                        "scroll at 1280 × 800 compact")
    head_kids: list[Node] = [text("title", say("Profile settings"), k.LABEL, C1)]
    if d.view_as:
        k.copy_gap(f'"{VIEW_AS_USER}": W-15\'s {{user}}, a synthetic display name (no account identifier, R-1)')
        head_kids.append(chip("view-as notice", k.W(15, user=VIEW_AS_USER), "info",
                              note="the dialog's aria-describedby; every gated control points at it (G-T2.5)"))
    head = hbox("dialog header", head_kids, {"gap": k.INSET_MD, "padX": k.INSET_XL}, w=DLG_W, h=HEAD_H)
    if d.view_as:
        save = control("Save", say("Save"), h=28, t2=True, note='T2 2a (CMP-079 RbacGate): aria-disabled="true", '
                                                                "in the Tab order; aria-describedby the dialog-header "
                                                                "notice (W-15); with an invalid field, both described, "
                                                                "the error first")
    else:
        save = hbox("Save", [text("label", say("Save"), k.CAPTION, k.CANVAS)],
                    {"padX": k.INSET_MD, "radius": k.R_CONTROL, "fill": C1}, h=28,
                    note="the primary action (wire: inverted); never aria-disabled for an invalid field (§8.3)")
    left = [control("Reset", say("Reset"), h=28), control("Presets", say("Presets"), menu=True, h=28,
                                                           pressed=d.menu)]
    used = sum(math.ceil(k.est_width(x)) for x in left + [save]) + math.ceil(k.est_width(control("c", "Cancel", h=28)))
    foot = hbox("dialog footer", [*left, box("spring", [], w=DLG_W - 48 - 4 * 8 - used, h=2),
                                  control("Cancel", say("Cancel"), h=28), save],
                {"gap": k.INSET_SM, "padX": k.INSET_XL}, w=DLG_W, h=FOOT_H)
    tile = preview(d, body_h - 16)
    kids: list[Node] = [head | {"x": 0, "y": 0}, rect("header rule", DLG_W, 1, k.BORDER, x=0, y=HEAD_H),
                        form_col | {"x": 0, "y": HEAD_H + 1}, tile | {"x": DLG_W - PREVIEW_W - 24, "y": HEAD_H + 8},
                        rect("footer rule", DLG_W, 1, k.BORDER, x=0, y=DLG_H - FOOT_H - 1),
                        foot | {"x": 0, "y": DLG_H - FOOT_H}]
    if d.menu:
        m = menu("CMP-041 Presets menu", presets_items(view_as=d.view_as, reason=None))
        kids.append(m | {"x": 24 + 8 + math.ceil(k.est_width(left[0])), "y": DLG_H - FOOT_H - m["h"] - 4})
    return box("CMP-043 dialog", kids, {"fill": k.OVERLAY, "radius": k.R_DIALOG, "stroke": k.BORDER,
                                        "strokeWidth": k.HAIR, "strokeAlign": "inner", "clip": True},
               w=DLG_W, h=DLG_H, note="aria-labelledby the title; modal: focus trapped, Tab wraps, background inert; "
                                      "Esc closes and returns focus to the opener (R3)")


def f_settings(fid: str, d: Dlg, lines: list[str]) -> tuple[Node, list[str]]:
    k.fallback("scrim")
    k.not_drawn_w(38, "announcement-only (Save applies and closes the dialog); named in this board's annotation "
                      "notes only, on no frame")
    pr = k.DEVELOPING
    out = docked_window(Docked(Panel(pr, opts=opts_for(pr)), day_bars(pr.start)))
    dlg = centred(dialog(d), k.WIN_W, k.WIN_H)
    base = [f"CMP-043 {DLG_W} × {DLG_H} at compact (§8.1, PROPOSED): the form column {FORM_W} px scrolls, the "
            f"CMP-228 preview {PREVIEW_W} px pinned right; footer Reset · Presets ▾ · Cancel · Save; no horizontal "
            "scroll at 1280 × 800 compact (AC 4)",
            "Initial focus: the first Period radio; Enter in a field never submits; Save applies, closes and "
            "announces W-38 once"]
    return frame(fid, out.kids + [dlg]), base + lines


def f_settings_compact(fid: str) -> tuple[Node, list[str]]:
    ln = k.L("- **Announcements:** POC / VAH / VAL announced")
    k.not_drawn_w(36, f"announcement-only (an Input change, announced once, §11 L{ln})")
    k.not_drawn_w(37, f"announcement-only (a VA % change, announced once, §11 L{ln})")
    return f_settings(fid, Dlg(), ["Valid, the preview live; scrolled to the top (Period, then Rows and value area)",
                                   "Sections (CMP-065): Period · Rows and value area · Levels and overlays · TPO · "
                                   "Appearance (below the fold)", "TPO letter size: a unit-labelled stepper, values "
                                   "E19-D03's (D02-OQ3): drawn without a value",
                                   "Value-area algorithm: Single step (default) / Two-row TPO with W-28's help; D02-G2 "
                                   "(no request parameter): drawn, not wired (R-5)"])


def f_va_invalid(fid: str) -> tuple[Node, list[str]]:
    v = "40"  # kit choice: an entered value outside 50–95
    k.not_drawn_w(39, "announcement-only (one polite count on Save with several errors, §8.3 "
                      f"L{k.L('Every invalid field carries `aria-invalid=')}); SCR-039/va-invalid draws one error")
    return f_settings(fid, Dlg(va=v, va_error=True, scroll_to="Rows and value area"), [
        f"VA % '{v}' (outside 50–95, `22`:4876; D02-C2) on blur or Save: CMP-040 inline error W-22 under the field, "
        "aria-invalid + aria-describedby; Save moves focus to the first invalid field; the preview keeps the last "
        "valid value (70); W-22 announced once; with several errors one polite W-39 counts them",
        "Form-validity errors are outside the T2 grammar: Save is never aria-disabled for an invalid field"])


def f_end_before_start(fid: str) -> tuple[Node, list[str]]:
    return f_settings(fid, Dlg(mode="Fixed range", end_error=True), [
        f"Fixed range with start {FIXED_START:%d %b %H:%M} and end {FIXED_END:%d %b %H:%M} UTC (end <= start, kit "
        "values): inline error W-23 under End; W-23 announced once"])


def f_lookback(fid: str) -> tuple[Node, list[str]]:
    return f_settings(fid, Dlg(mode="Composite", lookback=True), [
        f"Composite, look-back {len(COMPOSITE_30)} sessions; recorded history covers {len(ALL_DONE)}: the non-blocking "
        "warning W-24 under the look-back field (role=\"status\"); Save stays enabled; the preview builds from what "
        "exists and shows W-21's covered range (AC 5); W-24 announced once"])


# --- board 09: presets entry, the clamp, view-as (§9; T2 §1.4)
def header_menu(fid: str, p: Panel, items: list[Node], anchor: str, extra: list[Node] | None = None
                ) -> tuple[Node, DockedOut]:
    """The docked window with a header menu open under its button (window coords: under the controls row)."""
    out = docked_window(Docked(p, day_bars(p.pr.start if p.pr else k.TODAY)))
    m = menu(f"CMP-041 {anchor} menu", items)
    hd = header(p, PANEL_W)
    y = TOP_H + math.ceil(k.est_height(hd)) + 2
    kids = out.kids + [m | {"x": k.WIN_W - PANEL_W + 32, "y": y}] + (extra or [])
    return frame(fid, kids), out


def f_presets_entry(fid: str) -> tuple[Node, list[str]]:
    pr = k.DEVELOPING
    p = Panel(pr, presets_tag=k.W(32), focus="presets", opts=opts_for(pr))
    node_, _o = header_menu(fid, p, presets_items(view_as=False, reason=None), "Presets")
    return node_, ["Entry points only (E19-D04 owns apply / save / overwrite / undo): the Presets menu button in the "
                   "SCR-038 header, open; items: the built-in 'Session value', the user's presets, 'Save preset…'",
                   "After a manual change the menu button carries the 'Modified' slot (W-32, E19-D04's word); a preset "
                   "is available to every profile instance (`11`:1856); storage contract D02-G4"]


def f_presets_view_as(fid: str) -> tuple[Node, list[str]]:
    pr = k.DEVELOPING
    p = Panel(pr, focus="presets", opts=opts_for(pr))
    reason = k.W(15, user=VIEW_AS_USER)
    k.copy_gap(f'"{VIEW_AS_USER}": W-15\'s {{user}}, a synthetic display name (no account identifier, R-1)')
    ann = hidden(reason, label=gap_word("announced on Enter / Space", "board marker title (kit)"))
    node_, _o = header_menu(fid, p, presets_items(view_as=True, reason=reason, focus_save=True), "Presets",
                            [sized(ann) | {"x": k.WIN_W - PANEL_W - PRICE_AXIS - 316, "y": TOP_H + CHART_HEAD + 24}])
    return node_, ["T2 (§1.4) 2a inline inside the menu: 'Save preset…' led by the CMP-019 lock (decorative=false, "
                   "'Not available'), its full label in color.text.tertiary on the raised fill with the default "
                   "hairline (E09-D09 §2.1; never color.text.disabled or opacity.disabled); W-15 as the item's second "
                   "line, mounted with the menu, its own aria-describedby target",
                   "aria-disabled=\"true\", arrow-reachable (drawn focused); Enter or Space on it changes nothing and "
                   "re-shows W-15 with one polite announcement (G-T2.3)",
                   "Under view-as the header switches stay operable and change the view only (not T2)"]


def f_row_clamped(fid: str) -> tuple[Node, list[str]]:
    entered = "0.5"  # kit choice: a fractional row size below one tick
    return f_settings(fid, Dlg(row="1", clamp=entered, scroll_to="Rows and value area"), [
        f"A row size below one tick ('{entered}' entered) is replaced by 1 in the field on blur; W-25, naming the "
        "entered value, shows inline under it and is announced politely once; never a silent correction (AC 6; "
        "`11`:1858–1859)",
        "In SCR-038's header stepper the same rule: W-25 becomes the stepper's description, announced politely once "
        "on the change"])


def f_settings_view_as(fid: str) -> tuple[Node, list[str]]:
    return f_settings(fid, Dlg(view_as=True, menu=True), [
        "T2 (§1.4) 2a, CMP-079 RbacGate: Save and the footer Presets menu's 'Save preset…' each led by the CMP-019 "
        "lock glyph, the full label in color.text.tertiary, raised fill + default hairline, aria-disabled (never "
        "disabled), in the Tab order / arrow-reachable, both described by the one dialog-header notice W-15 "
        "(G-T2.5)",
        "Reset, Cancel and every field stay operable; the preview updates; nothing is saved"])


# --- board 10: the period switch, fixed range and anchored flows; analytics annotations (§10)
KINDS = {"Session": "session", "Fixed range": "fixed_range", "Visible range": "visible_range",
         "Anchored": "none — contract pending A-1", "Composite": "composite"}  # §5.1's `24` kind column


def event_marker(ev: str, at: str, payload: str) -> Node:
    return marker(f"event {ev}", [f"{k.plain(say(at))}: {say(payload)}"], w=300, title=say(ev))


def f_period_menu(fid: str) -> tuple[Node, list[str]]:
    pr = k.DEVELOPING
    p = Panel(pr, opts=opts_for(pr))
    items = [menu_item(say(m), checked=m == "Session", focused=m == "Fixed range") for m in MODES]
    kinds = marker("kinds", [f"{m}: {say(KINDS[m])}" for m in MODES], w=300,
                   title=gap_word("Each word's kind (board only)", "board marker title (kit); §5.1"))
    x, y = k.WIN_W - PANEL_W - PRICE_AXIS - 316, TOP_H + CHART_HEAD + 16
    evs = [event_marker("profile.period_changed", "a committed choice in the Period menu or SCR-039's radio",
                        "{from, to, host}"),
           event_marker("profile.mode_changed", "a committed choice in the Input menu (volume / delta / TPO)",
                        "{from, to, host}"),
           event_marker("profile.va_percent_changed", "the VA % stepper's commit (blur or `Enter`), never per key",
                        "{from, to, host}")]
    extra, yy = [], y
    for mk in [kinds, *evs]:
        s_ = sized(mk)
        extra.append(s_ | {"x": x, "y": yy})
        yy += s_["h"] + 12
    node_, _o = header_menu(fid, p, items, "Period", extra)
    return node_, ["The Period menu button opened: a menu of the five words (§5.1), the current one checked; "
                   "ArrowUp / ArrowDown move (focus drawn on 'Fixed range'), Enter / Space choose, Esc closes and "
                   "returns focus to the button",
                   "Choosing recomputes: the header's busy bar (§6 loading), the legend's mode word changes; 'Period: "
                   "{mode}' announced once (R-4)",
                   "Analytics (§10.4, payloads PROPOSED): host ∈ {docked, overlay}; no symbol, account, user or order "
                   "id; profile.settings_changed ({key}, one per changed key) is emitted at SCR-039 Save (board 08); "
                   "the profile.* namespace clash is D02-C7",
                   "≥ 55 fps (§10.3): in Visible range a pan or zoom re-renders only the plot and the legend; recompute "
                   "<= 10 Hz with a debounce on pan end; the table patches at most once per second"]


FIXED_MIN = 240  # kit choice: a 240-minute fixed range ending at the clock (`22`:4870 allows 1–10 080)
ANCHOR = k.TODAY + timedelta(hours=6)  # kit choice: the anchor bar, 06:00 UTC on the clock's day


def chart_slot_x(bars: list[k.Bar], t: datetime, slots: int) -> float:
    plot_w = k.WIN_W - PANEL_W - PRICE_AXIS
    i = next(i for i, b in enumerate(bars) if b.start >= t)
    return i * plot_w / slots


def f_fixed_range(fid: str) -> tuple[Node, list[str]]:
    bars = day_bars(k.TODAY)
    a = k.NOW - timedelta(minutes=FIXED_MIN)
    sel = [b for b in bars if b.start >= a]
    pr = k.build_profile("Fixed range", "Fixed range", sel, complete=False)
    p = Panel(pr, period="Fixed range", hint=k.W(30), opts=opts_for(pr))
    x0 = chart_slot_x(bars, a, 52)
    x1 = chart_slot_x(bars, bars[-1].start, 52) + (k.WIN_W - PANEL_W - PRICE_AXIS) / 52
    band = box("board marker · Shift-drag range", [text("words", gap_word("Shift-drag (PROPOSED)", "board marker "
                                                                          "label (kit), §10.2"), k.CAPTION, C1, x=4,
                                                         y=4)],
               {"stroke": C1, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=round(x1 - x0),
               h=k.WIN_H - TOP_H - STATUS_H - CHART_HEAD - TIME_AXIS - 8, x=round(x0), y=CHART_HEAD + 4,
               note="board marker: the range a Shift-drag selects on the bound chart's plot")
    node_, _o = docked_frame(fid, Docked(p, bars, chart_extra=[band]))
    return node_, [f"Choosing Fixed range shows W-30 as a hint in the header, announced politely once; Shift-drag on "
                   f"the bound chart's plot selects the range (PROPOSED; gesture conflicts E19-D04's, D02-OQ2): here "
                   f"{hm(a)}–{hm(k.NOW)} UTC ({FIXED_MIN} min, kit choice); the keyboard path is SCR-039's start / end "
                   "fields", levels_line(pr)]


def f_anchored(fid: str) -> tuple[Node, list[str]]:
    bars = day_bars(k.TODAY)
    sel = [b for b in bars if b.start >= ANCHOR]
    pr = k.build_profile("Anchored", "Anchored", sel, complete=False)
    p = Panel(pr, period="Anchored", hint=k.W(31), opts=opts_for(pr))
    x0 = chart_slot_x(bars, ANCHOR, 52) + (k.WIN_W - PANEL_W - PRICE_AXIS) / 52 / 2
    anchor = box("board marker · anchor", [rect("line", 2, k.WIN_H - TOP_H - STATUS_H - CHART_HEAD - TIME_AXIS - 8,
                                                C1, x=0, y=0),
                                           text("words", gap_word("anchor", "board marker label (kit), §10.2"),
                                                k.CAPTION, C1, x=6, y=4)],
                 None, w=60, h=k.WIN_H - TOP_H - STATUS_H - CHART_HEAD - TIME_AXIS - 8, x=round(x0), y=CHART_HEAD + 4,
                 note="board marker: the bar a click anchored")
    pend = marker("contract pending", [say("contract pending A-1")], w=200,
                  title=gap_word("Anchored", "board marker title (kit), the §5.1 word"))
    node_, _o = docked_frame(fid, Docked(p, bars, chart_extra=[anchor, sized(pend) | {
        "x": k.WIN_W - PANEL_W - PRICE_AXIS - 216, "y": CHART_HEAD + 8}]))
    return node_, [f"Choosing Anchored shows W-31, announced politely once; a click on a bar places the anchor (here "
                   f"{hm(ANCHOR)} UTC, kit choice); the profile accumulates forward and extends with new bars "
                   "(`11`:1726–1727); the keyboard path is SCR-039's anchor time; anchor gestures and handles are "
                   "E19-D04's",
                   "Anchored has no `24` kind and no request: contract pending A-1 (R-5: drawn and annotated, never "
                   "wired to an invented parameter)", levels_line(pr)]
