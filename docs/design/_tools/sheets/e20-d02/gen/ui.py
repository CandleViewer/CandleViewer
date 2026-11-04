"""E20-D02 widgets and frames (greyscale wireframes): the SCR-030 chart window (top bar, price pane, the CMP-225 strip,
the volume sub-pane, the time axis) in every strip state, the readout, the pane menu, the SCR-033 dialog and its row
list, the SCR-045 table and its export bar. Every string comes from the spec through k.W / k.S (or is a listed copy gap
via k.ui); every number from the kit's seeded world."""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import e20d02kit as k  # noqa: E402

Node = k.Node
text, icon, rect, ellipse, box, hbox, vbox = k.text, k.icon, k.rect, k.ellipse, k.box, k.hbox, k.vbox
D = Decimal
# the chart window's plan in a 1280 × 800 frame (kit geometry; §3.1 gives the order: price pane, strip, volume)
TOP_H, VOL_H, TIME_H, HEAD_H, ROW_H, CALLOUT_H = 40, 64, 24, 28, 28, 32
LABEL_W, AXIS_W = 192, 64
PLOT_X, PLOT_W = LABEL_W, k.WIN_W - LABEL_W - AXIS_W  # 1024: the label column is reserved on every pane (one x(t))
RUNS_BELOW = 10  # px pitch under which collapsed glyphs are drawn as pixel runs (FALLBACKS["runs"])
CTRL = 32


# --- board markers (never product UI)
# The drawing lane's live check (boards 07, 08): a marker's 'how' caption that runs past the marker wraps at the
# marker's w - 16 (auto-height, two live lines) and the marker grows to its content end, never shrinking. The
# estimate's widths run wide of the live line boxes, so the live line count and marker h are pinned here per caption
# (a rebuild then reproduces the drawn sheets); any other caption the estimate puts more than HOW_SLACK past the
# marker is refused until the lane measures it.
LIVE_HOW: dict[str, tuple[int, int]] = {  # the 'how' caption -> (live lines, live marker h)
    "announced: polite, one live region in the dialog, replaced never queued, ≤ 1 a second": (2, 68),
    "Move up's description (visually hidden) (not on screen)": (2, 61),
    'announced: polite, once, on the last uncheck (role="status")': (2, 74),
    "announced: polite, once, when Space re-shows it": (2, 68),
}
HOW_SLACK = 1.10  # the estimate's width over a live line box that still fits on one line (08's 234 px in 232)


def how_text(label: str, w: int | None) -> Node:
    """A marker's 'how' caption: one line, or wrapped at the marker's w - 16 where the live check pinned it."""
    if label in LIVE_HOW:
        if not w:
            raise ValueError(f"the pinned caption {label!r} needs its marker's width")
        return text("how", label, k.CAPTION, k.TEXT_3, w=w - 16)
    if w and k.text_w(label, k.CAPTION) > (w - 16) * HOW_SLACK:
        raise ValueError(f"the caption {label!r} runs past its {w} px marker: measure it live and pin it in LIVE_HOW")
    return text("how", label, k.CAPTION, k.TEXT_3)


def marker_box(name: str, kids: list[Node], *, w: int | None = None, **kw: Any) -> Node:
    k.fallback("marker")
    n = vbox(f"board marker · {name}", kids, {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.CANVAS,
                                              "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                                              "strokeAlign": "inner", "radius": k.R_CONTROL},
             **({"w": w} if w else {}), note="board marker, not product UI", **kw)
    pinned = [LIVE_HOW[c["chars"]] for c in kids if c.get("name") == "how" and c.get("w") and c["chars"] in LIVE_HOW]
    if pinned:
        lines, h = pinned[0]
        one = dict(n, h=0, kids=[dict(c, w=None) if c.get("name") == "how" else c for c in n["kids"]])
        floor = math.ceil(k.est_height(one) / 4) * 4 + 4  # the single-line marker it grew from
        pads, gap = 2 * k.PX[k.INSET_SM], k.PX[k.STACK_XS]
        need = pads + gap + k.text_h(k.CAPTION, lines) + k.text_h(k.CAPTION)  # the caption and one words line
        if h < max(floor, need):
            raise ValueError(f"marker {name!r}: the pinned h {h} is below {max(floor, need)}")
        n["h"] = h
    else:
        n["h"] = math.ceil(k.est_height(n) / 4) * 4 + 4
    return n


def announce(chars: str, *, how: str = "polite, once", w: int = 440) -> Node:
    """The words a screen reader hears (R-4), drawn as a board marker."""
    return marker_box("announcement", [how_text(k.ui(f"announced: {how}", "board-marker label"), w),
                                       text("words", chars, k.CAPTION, k.TEXT_1, w=w - 16)], w=w)


def acc_name(role: str, chars: str, *, w: int = 440) -> Node:
    """An accessible name or a visually hidden string, drawn as a board marker: role, then the words."""
    return marker_box("accessible text", [how_text(k.ui(f"{role} (not on screen)", "board-marker label"), w),
                                          text("words", chars, k.CAPTION, k.TEXT_1, w=w - 16)], w=w)


def note_marker(chars: str, *, w: int = 440) -> Node:
    return marker_box("note", [text("words", chars, k.CAPTION, k.TEXT_1, w=w - 16)], w=w)


def stack(markers: Iterable[Node | None], x: int, y: int, gap: int = 8) -> list[Node]:
    """Markers stacked top-down from (x, y) inside a frame."""
    out = []
    for m in markers:
        if m:
            out.append(dict(m, x=x, y=y))
            y += m["h"] + gap
    return out


# --- primitives of the controls (greyscale)
def ring(n: Node, radius: str = k.R_CONTROL, name: str = "focus ring") -> Node:
    """E47-D04's ring, wireframe form: 2 px color.text.primary outside the control (a wrapper padded 4 around it)."""
    k.fallback("focus")
    w = round(k.est_width(n)) + 8
    return box(name, [dict(n, x=4, y=4)], {"radius": radius, "stroke": k.TEXT_1, "strokeWidth": k.FOCUS_W,
                                           "strokeAlign": "inner"}, w=w, h=round(k.est_height(n)) + 8,
               note="focus-visible: E47-D04's ring (hi-fi color.focus.ring), 2 px outside the control")


def ring_rect(w: float, h: float, x: float, y: float, name: str = "focus ring") -> Node:
    k.fallback("focus")
    return rect(name, round(w + 4, 2), h + 4, None, {"stroke": k.TEXT_1, "strokeWidth": k.FOCUS_W,
                                                     "strokeAlign": "inner", "radius": k.R_CONTROL},
                x=round(x - 2, 2), y=y - 2, note="focus-visible: E47-D04's ring, 2 px outside the box")


def lock(name: str = "CMP-019 lock") -> Node:
    """CMP-019 `lock` (decorative=false, accessible name "Not available"), leading the label, color.text.tertiary."""
    return icon(name, "locked", k.TEXT_3, k.ICON_SM, note='CMP-019 lock, accessible name "Not available"')


def t2_box(label: str, *, name: str, typo: str = k.BODY_STRONG, h: int = CTRL, w: int | None = None,
           focused: bool = False, note: str = "", checkbox_: bool = False, rendering: str = "2a") -> Node:
    """E09-D09 §2.1 rendering 2a: the CMP-019 lock leads the full label in color.text.tertiary, on
    color.surface.raised with a color.border.default hairline; aria-disabled, never color.text.disabled, never
    opacity.disabled."""
    lw = round(k.text_w(label, typo))
    box_ = [box("box (unchecked)", [], {"stroke": k.TEXT_3, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                                        "radius": k.R_CONTROL}, w=14, h=14)] if checkbox_ else []
    b = hbox(f"{name} · T2 {rendering}", [lock(), *box_, text("label", label, typo, k.TEXT_3)],
             {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
              "strokeAlign": "inner", "radius": k.R_CONTROL}, w=w or lw + 12 + 4 + 18, h=h,
             note=note or 'T2 2a (§1.4): aria-disabled="true", in the Tab order, aria-describedby → the reason node')
    return ring(b) if focused else b


def reason(chars: str, w: int, name: str = "T2 reason") -> Node:
    """The reason, its own line, color.text.secondary, in the DOM at mount (§1.4)."""
    return text(name, chars, k.CAPTION, k.TEXT_2, w=w, note="reason node: aria-describedby target, in the DOM at mount")


def button(label: str, *, kind: str = "secondary", focused: bool = False, name: str | None = None,
           h: int = CTRL, note: str | None = None) -> Node:
    """CMP-001 primary / secondary / ghost, greyscale: primary color.surface.selected + a color.border.strong
    outline; secondary color.surface.raised + color.border.default; ghost a color.border.subtle outline."""
    lw = round(k.text_w(label, k.BODY_STRONG))
    fill, stroke = {"primary": (k.SELECTED, k.BORDER_STRONG), "secondary": (k.RAISED, k.BORDER),
                    "ghost": (None, k.BORDER_SUBTLE)}[kind]
    o: dict[str, Any] = {"padX": k.BUTTON_PADX, "radius": k.R_CONTROL, "justify": "center", "stroke": stroke,
                         "strokeWidth": k.HAIR, "strokeAlign": "inner"}
    if fill:
        o["fill"] = fill
    b = hbox(name or f"CMP-001 {label}", [text("label", label, k.BODY_STRONG, k.TEXT_1)], o, w=lw + 26, h=h,
             note=note or kind)
    return ring(b) if focused else b


def icon_button(name: str, glyph: str, *, focused: bool = False, note: str = "") -> Node:
    """CMP-002 icon button, a 24 × 24 target (2.5.8)."""
    b = hbox(name, [icon("glyph", glyph, k.TEXT_2, k.ICON)], {"justify": "center", "radius": k.R_CONTROL,
                                                              "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                                              "strokeAlign": "inner"}, w=24, h=24, note=note or None)
    return ring(b) if focused else b


def gear(*, focused: bool = False) -> Node:
    """The strip's gear (onConfigure, §3.1): no gear glyph in the local set, so a wireframe stand-in: a 10 px ring
    and a 4 px hub in a 24 × 24 icon button (the glyph is E20-D03's)."""
    b = box("gear (CMP-002, opens SCR-033)", [
        ellipse("gear ring", 12, 12, {"stroke": k.TEXT_2, "strokeWidth": k.THICK, "strokeAlign": "inner"}, x=6, y=6),
        ellipse("gear hub", 4, 4, {"fill": k.TEXT_2}, x=10, y=10)],
        {"radius": k.R_CONTROL, "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=24, h=24,
        note='icon button, accessible name "Deep Stats rows" (SCR-033\'s title); the glyph is E20-D03\'s')
    return ring(b) if focused else b


def card(name: str, kids: list[Node], w: int, note: str, *, pad: str = k.INSET_XS) -> Node:
    k.fallback("menu")
    n = vbox(name, kids, {"gap": k.STACK_XS, "pad": pad, "fill": k.OVERLAY, "stroke": k.BORDER,
                          "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CARD}, w=w, note=note)
    n["h"] = math.ceil(k.est_height(n))
    return n


def item(label: str, w: int, *, focused: bool = False, name: str | None = None) -> Node:
    it = hbox(name or f"item · {label}", [text("label", label, k.BODY, k.TEXT_1)],
              {"padX": k.INSET_SM, **({"fill": k.HOVER} if focused else {})}, w=w, h=28)
    return ring(it) if focused else it


def checkbox(on: bool, name: str = "box") -> Node:
    kids = [icon("check", "check", k.TEXT_1, k.ICON_SM, x=2, y=2)] if on else []
    return box(name, kids, {"stroke": k.TEXT_2, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                            "radius": k.R_CONTROL, **({"fill": k.SELECTED} if on else {})}, w=16, h=16)


def switch(on: bool, name: str = "track") -> Node:
    return box(name, [ellipse("thumb", 12, 12, {"fill": k.TEXT_1 if on else k.TEXT_2}, x=18 if on else 2, y=2)],
               {"stroke": k.TEXT_2, "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_BADGE,
                **({"fill": k.SELECTED} if on else {})}, w=32, h=16, note="switch, aria-checked=" + str(on).lower())


# --- the chart window
DEFAULT = tuple(r["label"] for r in k.DEFAULT_ROWS)
ALL12 = tuple(r["label"] for r in k.ALL_ROWS)


@dataclass
class P:
    n: int = 16  # visible bars, the last one forming
    sym: str = k.SYM
    rows: tuple[str, ...] = DEFAULT
    strip: bool = True
    shade: bool = True  # the breach shade slot (hi-fi E20-D03); the greyscale frame removes it
    set_wid: str = "W-1"  # the header cell's set word (W-1 Global, W-2 the per-symbol set)
    short: bool = False  # compact mode: the short labels
    spark: tuple[str, ...] = ()  # rows whose CMP-024 sparkline draws
    callout: str | None = None  # CMP-028 inline callout above the strip
    partial_from: str | None = None  # the first bar with recorded order flow
    empty: bool = False  # Empty(no recording)
    crosshair: str | None = None  # bar time under the pointer
    readout: str | None = None  # bar time the CMP-197 readout lists
    focus_cell: tuple[str, str] | None = None  # (row label, bar time) with keyboard focus
    focus_gear: bool = False
    pane_menu: bool = False
    focus_menu_btn: bool = False
    volume: bool = True  # per-bar volume columns (the alignment study's dense frames draw a placeholder)
    edges: tuple[str, ...] = ()  # bar times whose x(t) left edges are marked (board 10)
    markers: list[Node] = field(default_factory=list)  # board markers stacked in the price pane


def pitch(p: P) -> float:
    return PLOT_W / p.n


def xb(p: P, j: int) -> float:
    """x(t) of the j-th visible bar's column (the engine's x(t), §8): one function for every pane."""
    return round(PLOT_X + j * pitch(p), 2)


def geometry(p: P) -> dict[str, int]:
    sh = (HEAD_H + len(p.rows) * ROW_H) if p.strip else 0
    ch = CALLOUT_H if p.callout else 0
    ph = k.WIN_H - TOP_H - ch - sh - VOL_H - TIME_H
    return {"price_y": TOP_H, "price_h": ph, "callout_y": TOP_H + ph, "strip_y": TOP_H + ph + ch, "strip_h": sh,
            "vol_y": TOP_H + ph + ch + sh, "time_y": TOP_H + ph + ch + sh + VOL_H}


def _nice(span: Decimal, parts: int) -> Decimal:
    raw = span / parts
    mag = D(10) ** (raw.adjusted())
    for m in (1, 2, 5, 10):
        if mag * m >= raw:
            return mag * m
    return mag * 10


def top_bar(p: P) -> Node:
    words = k.ui(f"{p.sym} · 1m", "SCR-030's top bar (symbol and interval; the world's series)")
    return box("top bar (SCR-030)", [text("symbol", words, k.BODY_STRONG, k.TEXT_1, x=16, y=11),
                                     rect("rule", k.WIN_W, 1, k.BORDER, x=0, y=TOP_H - 1)],
               {"fill": k.RAISED}, w=k.WIN_W, h=TOP_H, x=0, y=0)


def price_pane(p: P, g: dict[str, int]) -> Node:
    k.fallback("candles")
    bars = k.window(p.n, p.sym)
    tick = k.INSTR[p.sym][0]
    lo, hi = min(b.l for b in bars), max(b.h for b in bars)
    ph = g["price_h"]

    def y(v: Decimal) -> float:
        return round(12 + float((hi - v) / (hi - lo)) * (ph - 24), 2)

    kids: list[Node] = [rect("label column (reserved)", LABEL_W, ph, k.CANVAS, x=0, y=0,
                             note="the strip's label column, reserved on every pane so x(t) is one function (§8)")]
    pw = pitch(p)
    for j, b in enumerate(bars):
        x0 = xb(p, j) - PLOT_X + LABEL_W
        nm = f"candle · {b.t}" + (" · forming" if b.forming else "")
        if pw < 4:
            kids.append(rect(nm, round(max(1.0, pw * 0.8), 2), max(1.0, round(y(b.l) - y(b.h), 2)), k.TEXT_2,
                             x=round(x0, 2), y=y(b.h)))
            continue
        cx = round(x0 + pw / 2 - 0.5, 2)
        kids.append(rect(f"wick · {b.t}", 1, max(1.0, round(y(b.l) - y(b.h), 2)), k.TEXT_2, x=cx, y=y(b.h)))
        top, bot = y(max(b.o, b.c)), y(min(b.o, b.c))
        o = ({"fill": k.NEUTRAL_SUBTLE, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR, "strokeAlign": "inner"}
             if b.forming else {"stroke": k.TEXT_2, "strokeWidth": k.HAIR, "strokeAlign": "inner"} if b.c >= b.o
             else {"fill": k.TEXT_2})
        kids.append(rect(nm, round(pw * 0.6, 2), max(1.0, round(bot - top, 2)), None, o, x=round(x0 + pw * 0.2, 2),
                         y=top, note="forming-bar treatment: E12-D06's form (14:759)" if b.forming else None))
    step = _nice(hi - lo, 4)
    v = (lo / step).to_integral_value(rounding="ROUND_CEILING") * step
    while v <= hi:
        kids.append(text(f"price · {v}", f"{v.quantize(tick):,}", k.CAPTION, k.TEXT_2, x=LABEL_W + PLOT_W + 6,
                         y=round(y(v) - 7, 2)))
        kids.append(rect(f"gridline · {v}", PLOT_W, 1, k.GRID, x=LABEL_W, y=y(v)))
        v += step
    kids = [kids[0], *k.bands("candles", kids[1:], k.WIN_W, ph)]
    kids.append(rect("pane rule", k.WIN_W, 1, k.BORDER, x=0, y=ph - 1))
    btn = icon_button("chart pane menu button", "more-horizontal", focused=p.focus_menu_btn,
                      note="the chart pane's menu (Show / Hide Deep Stats, §5)")
    kids.append(dict(btn, x=LABEL_W + PLOT_W - 40, y=8))
    return box("price pane", kids, {}, w=k.WIN_W, h=ph, x=0, y=g["price_y"])


SHORT = {r["label"]: r["x"] for r in k.COMPACT_ROWS}


def breach_slot(name: str, x: float, y: float, s: int = 8) -> Node:
    k.fallback("breach-slot")
    return rect(name, s, s, None, {"stroke": k.TEXT_1, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, x=round(x, 2),
                y=y, note="breach-glyph slot (MEMO AD-5): a shape distinct from both sign glyphs; its form is E20-D03's")


def sparkline(label: str, x: int, y: int) -> Node:
    """CMP-024: the row's last N closed values as N dots on a 48 × 16 slot (its own min / max)."""
    k.fallback("sparkline")
    vals = [float(v) if not isinstance(v := k.raw_value(label, b), bool) else float(v)
            for b in k.BARS[k.SYM][-1 - k.SPARK_N:-1]]
    lo, hi = min(vals), max(vals)
    dots = [rect(f"dot {i + 1:02d}", 2, 2, k.TEXT_2, x=round(i * 46 / (len(vals) - 1), 2),
                 y=round(14 - (v - lo) / ((hi - lo) or 1) * 14, 2)) for i, v in enumerate(vals)]
    return box(k.safe(f"CMP-024 sparkline · {label}"), dots, {}, w=48, h=16, x=x, y=y,
               note=f"aria-label summarises the trend of the last {k.SPARK_N} values (15:294)")


def cell_nodes(p: P, label: str, b: k.Bar, x0: float) -> list[Node]:
    """One strip cell at full width (≥ the floor) or collapsed (§4.1); none left of a partial boundary or when empty."""
    if p.empty or (p.partial_from and k.idx(b.t) < k.idx(p.partial_from)):
        return []
    pw = pitch(p)
    br = k.breached(label, b, p.sym)
    out: list[Node] = []
    if br and p.shade:
        k.fallback("shade")
        out.append(rect(f"shade slot (hi-fi E20-D03) · {b.t}", round(pw, 2), ROW_H - 1, k.SELECTED, x=round(x0, 2),
                        y=0))
    g = k.glyph(label, b)
    if pw >= k.FLOOR_PX:
        vy = 15 if br else 8
        if br:
            out += [breach_slot(f"breach-glyph slot · {b.t}", x0 + 8, 5),
                    text(f"Strong · {b.t}", k.W("W-3"), k.CAPTION, k.TEXT_1, x=round(x0 + 19, 2), y=2,
                         w=round(pw - 27, 2), align="right")]
        if g == "flag":
            k.fallback("flag")
            out.append(icon(f"flag · {b.t}", "warning", k.TEXT_1, k.ICON_SM, x=round(x0 + 8, 2), y=vy))
        elif label in k.SIGNED:
            out.append(text(f"glyph · {b.t}", g, k.NUM_XS, k.TEXT_1, x=round(x0 + 8, 2), y=vy))
        if label not in k.FLAG:
            out.append(text(f"value · {b.t}", k.value(label, b), k.NUM_XS, k.TEXT_1, x=round(x0 + 18, 2), y=vy,
                            w=round(pw - 26, 2), align="right"))
        return out
    if br:
        out.append(breach_slot(f"breach-glyph slot · {b.t}", x0 + pw / 2 - 4, 3))
    if g == "flag":
        k.fallback("flag")
        out.append(icon(f"flag · {b.t}", "warning", k.TEXT_1, k.ICON_SM, x=round(x0 + pw / 2 - 6, 2), y=13))
    elif g:
        out.append(text(f"glyph · {b.t}", g, k.NUM_XS, k.TEXT_1, x=round(x0, 2), y=14, w=round(pw, 2), align="center"))
    return out


def run_nodes(p: P, label: str, bars: tuple[k.Bar, ...]) -> list[Node]:
    """Below RUNS_BELOW px a run of equal glyphs is one rect (pixel-equivalent): ▲ above the midline, ▼ below it,
    the presence mark a 1 px line; breach slots per breached bar."""
    k.fallback("runs")
    pw = pitch(p)
    out: list[Node] = []
    j = 0
    while j < len(bars):
        g = k.glyph(label, bars[j])
        e = j
        while e + 1 < len(bars) and k.glyph(label, bars[e + 1]) == g:
            e += 1
        x0, w = xb(p, j), round((e - j + 1) * pw, 2)
        geo = {"▲": (9, 4), "▼": (17, 4), "·": (14, 1), "flag": (6, 6)}.get(g)
        if geo:
            out.append(rect(f"run {g} · {bars[j].t}–{bars[e].t}", w, geo[1], k.TEXT_1, x=x0, y=geo[0],
                            note=f"{e - j + 1} collapsed cells, glyph {g} (pixel-contiguous at {pw:.2f} px)"))
        j = e + 1
    for jj, b in enumerate(bars):
        if k.breached(label, b, p.sym):
            out.append(breach_slot(f"breach-glyph slot · {b.t}", xb(p, jj) + pw / 2 - 3, 1, 6))
    return out


def strip(p: P, g: dict[str, int]) -> Node:
    bars = k.window(p.n, p.sym)
    pw = pitch(p)
    hd: list[Node] = [text("set", k.W(p.set_wid), k.CAPTION, k.TEXT_2, x=8, y=8, w=LABEL_W - 48,
                           note="header cell: the active threshold set (11:1918)"),
                      dict(gear(focused=p.focus_gear), x=LABEL_W - 32 - (4 if p.focus_gear else 0),
                           y=2 - (4 if p.focus_gear else 0))]
    for j, b in enumerate(bars):
        if b.forming:
            fw = round(max(pw, 48.0), 2)
            hd.append(text("column header · forming", k.W("W-7"), k.CAPTION, k.TEXT_1, x=round(xb(p, j) + pw - fw, 2),
                           y=8, w=fw - 4, align="right",
                           note="the forming column's header (W-7); its time in the accessible name"))
        elif pw >= k.FLOOR_PX:
            hd.append(text(f"column header · {b.t}", b.t, k.CAPTION, k.TEXT_3, x=xb(p, j), y=8, w=round(pw, 2),
                           align="center"))
    hd.append(rect("header rule", k.WIN_W, 1, k.BORDER, x=0, y=HEAD_H - 1))
    kids: list[Node] = [box("strip header row", hd, {}, w=k.WIN_W, h=HEAD_H, x=0, y=0)]
    for r, label in enumerate(p.rows):
        sp = label in p.spark
        lab = SHORT[label] if p.short else label
        rk: list[Node] = [text("row label", lab, k.CAPTION, k.TEXT_2, x=8, y=8, w=(120 if sp else LABEL_W - 16),
                               align="right", note=f"row header; accessible name {label!r} (24 §7)")]
        if sp:
            rk.append(sparkline(label, LABEL_W - 56, 6))
        if pw >= RUNS_BELOW or p.empty or p.partial_from:
            for j, b in enumerate(bars):
                rk += cell_nodes(p, label, b, xb(p, j))
        else:
            rk += run_nodes(p, label, bars)
        rk = [*rk[:2 if sp else 1], *k.bands("cells", rk[2 if sp else 1:], k.WIN_W, ROW_H)]
        rk.append(rect("row rule", k.WIN_W, 1, k.GRID, x=0, y=ROW_H - 1))
        kids.append(box(k.safe(f"strip row · {label}"), rk, {}, w=k.WIN_W, h=ROW_H, x=0, y=HEAD_H + r * ROW_H))
    kids.append(rect("label column rule", 1, g["strip_h"], k.BORDER, x=LABEL_W - 1, y=0))
    body_y, body_h = HEAD_H, g["strip_h"] - HEAD_H
    if p.partial_from:
        jb = k.idx(p.partial_from) - (k.N_BARS - p.n)
        bx = xb(p, jb)
        tag = k.W("W-8", ts=p.partial_from)
        tw = round(k.text_w(tag, k.CAPTION)) + 8
        kids += [rect("partial-history boundary", 1, body_h, k.BORDER_STRONG, x=bx, y=body_y),
                 text("partial-history tag (W-8)", tag, k.CAPTION, k.TEXT_2, x=round(bx - tw - 8, 2), y=body_y + 8,
                      w=tw, align="right", note="SCR-030's boundary tag (14:762), names the first available bar")]
    if p.empty:
        w9 = k.W("W-9")
        tw = round(k.text_w(w9, k.BODY)) + 8
        kids.append(text("empty line (W-9)", w9, k.BODY, k.TEXT_2, x=round(PLOT_X + (PLOT_W - tw) / 2), w=tw,
                         y=body_y + round((body_h - 18) / 2), align="center",
                         note='role="status", announced once when it appears after a range change'))
    return box("CMP-225 Deep Stats strip", kids, {"fill": k.CANVAS}, w=k.WIN_W, h=g["strip_h"], x=0, y=g["strip_y"],
               note='role="grid", named "Deep Stats"; one row per enabled row, top row nearest the bars (MEMO AD-1)')


def volume_pane(p: P, g: dict[str, int]) -> Node:
    bars = k.window(p.n, p.sym)
    kids: list[Node] = [rect("label column (reserved)", LABEL_W, VOL_H, k.CANVAS, x=0, y=0),
                        text("pane label", k.ui("Volume", "SCR-030's volume sub-pane label"), k.CAPTION, k.TEXT_3,
                             x=8, y=6)]
    if p.volume:
        vmax = max(b.vol for b in bars)
        pw = pitch(p)
        for j, b in enumerate(bars):
            h = max(1.0, round(float(b.vol / vmax) * (VOL_H - 16), 2))
            kids.append(rect(f"volume · {b.t}", round(max(1.0, pw * 0.6), 2), h, k.BORDER_STRONG,
                             x=round(xb(p, j) + pw * 0.2, 2), y=round(VOL_H - 4 - h, 2)))
        kids = [*kids[:2], *k.bands("columns", kids[2:], k.WIN_W, VOL_H)]
    else:
        kids.append(text("volume placeholder", k.ui("volume sub-pane unchanged — columns not drawn at this density",
                                                    "kit drawing economy (board 10)"), k.CAPTION, k.TEXT_3,
                         x=PLOT_X + 8, y=24))
    kids.append(rect("pane rule", k.WIN_W, 1, k.BORDER, x=0, y=VOL_H - 1))
    return box("volume sub-pane", kids, {}, w=k.WIN_W, h=VOL_H, x=0, y=g["vol_y"])


def time_axis(p: P, g: dict[str, int]) -> Node:
    bars = k.window(p.n, p.sym)
    pw = pitch(p)
    step = next(s for s in (1, 2, 4, 5, 10, 15, 20, 30, 60, 120, 240) if s * pw >= 64)
    kids: list[Node] = []
    for j, b in enumerate(bars):
        if int(b.t[3:]) % step == 0 and (int(b.t[:2]) * 60 + int(b.t[3:])) % step == 0:
            kids.append(text(f"time · {b.t}", b.t, k.CAPTION, k.TEXT_2, x=round(xb(p, j) + pw / 2 - 20, 2), y=5, w=40,
                             align="center"))
    return box("time axis", kids, {"fill": k.RAISED}, w=k.WIN_W, h=TIME_H, x=0, y=g["time_y"])


def callout(chars: str, g: dict[str, int]) -> Node:
    """CMP-028 inline callout above the strip (§3.5)."""
    return hbox("CMP-028 callout (sparkline guard)", [icon("glyph", "info", k.TEXT_1, k.ICON),
                                                      text("words", chars, k.CAPTION, k.TEXT_1)],
                {"gap": k.INSET_SM, "padX": k.INSET_MD, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                 "strokeAlign": "inner"}, w=k.WIN_W, h=CALLOUT_H, x=0, y=g["callout_y"],
                note="inline callout, announced once, politely, when it appears")


def readout(p: P, g: dict[str, int], t: str, *, max_rows: int = 12) -> Node:
    """CMP-197 for the bar under the crosshair: every enabled row's §7 label, value and unit in strip order; the
    forming bar carries W-7; past 12 rows W-6."""
    b = k.BARS[p.sym][k.idx(t)]
    title = f"{t} · {k.W('W-7')}" if b.forming else t
    rows: list[Node] = [text("title", title, k.LABEL, k.TEXT_1)]
    for label in p.rows[:max_rows]:
        rows.append(hbox(k.safe(f"readout row · {label}"), [
            text("label", label, k.CAPTION, k.TEXT_2, w=112),
            text("value", k.value(label, b), k.NUM_XS, k.TEXT_1, w=72, align="right"),
            text("unit", k.unit_word(label, p.sym) or k.ui("—", "readout: no unit for count / ratio / flag rows"),
                 k.CAPTION, k.TEXT_3, w=32)], {"gap": k.INSET_XS}, w=232, h=16))
    extra = len(p.rows) - max_rows
    if extra > 0:
        rows.append(text("overflow (W-6)", k.W("W-6").replace("+n", f"+{extra}"), k.CAPTION, k.TEXT_1,
                         note="the path to SCR-045, the catalogue's table alternative (15:2598)"))
    c = card("CMP-197 readout", rows, 248, "the bar under the crosshair; on pointer it stays while hovered (1.4.13); "
                                         "Esc dismisses it", pad=k.INSET_SM)
    j = k.idx(t) - (k.N_BARS - p.n)
    x = xb(p, j) + pitch(p) + 12
    if x + 248 > PLOT_X + PLOT_W:
        x = xb(p, j) - 248 - 12
    return dict(c, x=round(x, 2), y=max(TOP_H + 8, g["strip_y"] - c["h"] - 8))


def crosshair(p: P, g: dict[str, int], t: str) -> list[Node]:
    j = k.idx(t) - (k.N_BARS - p.n)
    cx = round(xb(p, j) + pitch(p) / 2, 2)
    b = k.BARS[p.sym][k.idx(t)]
    tag = f"{t} · {k.W('W-7')}" if b.forming else t
    tw = round(k.text_w(tag, k.CAPTION)) + 16
    return [rect("crosshair", 1, g["time_y"] - TOP_H, k.BORDER_STRONG, x=cx, y=TOP_H, note="the pointer's crosshair"),
            hbox("data cursor", [text("time", tag, k.CAPTION, k.TEXT_1)], {"padX": k.INSET_SM, "fill": k.SELECTED,
                                                                          "radius": k.R_CONTROL},
                 w=tw, h=18, x=round(cx - tw / 2, 2), y=g["time_y"] + 3,
                 note="the data cursor carries the word when the bar is forming (14:759)")]


def pane_menu(*, hidden: bool, focused: bool = True) -> Node:
    """The chart pane's menu, its Deep Stats group: W-10 when the strip is hidden, W-11 while it shows (§5)."""
    words = k.W("W-10") if hidden else k.W("W-11")
    kids = [text("group label", k.ui("Deep Stats", "the pane menu's group label"), k.CAPTION, k.TEXT_3),
            item(words, 232, focused=focused, name=f"menuitem · {words}")]
    c = card("chart pane menu (role=menu)", kids, 248, "first item of the Deep Stats group; one press restores the "
                                                     "last row set and order (§5)", pad=k.INSET_SM)
    return dict(c, x=LABEL_W + PLOT_W - 248, y=TOP_H + 40)


def edge_markers(p: P, g: dict[str, int]) -> list[Node]:
    out: list[Node] = []
    for e, t in enumerate(p.edges):
        j = k.idx(t) - (k.N_BARS - p.n)
        x = xb(p, j)
        out += [rect(f"board marker · x(t) edge · {t}", 1, g["strip_y"] + g["strip_h"] - TOP_H, k.TEXT_1, x=x,
                     y=TOP_H, note="board marker: the column's left edge = the engine's x(t) for this bar"),
                text(f"board marker · x(t) label · {t}", k.ui(f"x({t})", "board-marker label"), k.CAPTION, k.TEXT_1,
                     x=round(x + 3, 2), y=TOP_H + 44 + 18 * e)]
    return out


def chart(fid: str, p: P, extra: Iterable[Node | None] = ()) -> Node:
    g = geometry(p)
    kids: list[Node | None] = [top_bar(p), price_pane(p, g)]
    if p.callout:
        kids.append(callout(p.callout, g))
    if p.strip:
        kids.append(strip(p, g))
    kids += [volume_pane(p, g), time_axis(p, g)]
    if p.crosshair:
        kids += crosshair(p, g, p.crosshair)
    if p.focus_cell:
        label, t = p.focus_cell
        j = k.idx(t) - (k.N_BARS - p.n)
        r = p.rows.index(label)
        kids.append(ring_rect(pitch(p), ROW_H - 1, xb(p, j), g["strip_y"] + HEAD_H + r * ROW_H,
                              name=k.safe(f"focus ring · cell {label} {t}")))
    if p.readout:
        kids.append(readout(p, g, p.readout))
    if p.pane_menu:
        kids.append(pane_menu(hidden=not p.strip))
    kids += edge_markers(p, g)
    kids += stack(p.markers, PLOT_X + 16, TOP_H + 16)
    kids += list(extra)
    return k.frame(fid, kids)


def run(nn: int, built: list[tuple[Node, tuple[str, list[str]]]], cols: int, board_lines: Iterable[str] = (),
        notes: dict[str, Iterable[str]] | None = None) -> None:
    """The generators' last step: k.build (validator exit 0, .md, packed)."""
    k.live("centring: only a node a line here names is centred, and only on the axis it names; every other node "
           "keeps the sheet's x / y — never apply a generic re-centre")
    k.build(nn, [x[0] for x in built], [x[1] for x in built], cols, board_lines=board_lines, notes=notes)
    print("ok", k.BOARDS[nn].sheet)


# --- SCR-033 (CMP-043 Dialog, size md) and its CMP-056 row list
DLG_W, DLG_H, DLG_X, DLG_Y = 720, 736, 280, 32
DLG_PAD = 24
LIST_W = DLG_W - 2 * DLG_PAD
LROW_H, EXP_H, HEAD_DLG, TOOL_H, FOOT_H = 36, 36, 56, 48, 64
NO_THRESHOLD = frozenset(("Delta Divergence", "Bar POC", "Bar VA"))  # flag and price rows (§6.4, MEMO §8)


@dataclass
class R:
    label: str
    on: bool = True
    spark: bool = False
    expanded: tuple[str, str] | None = None  # (comparison, bound text)
    invalid: str | None = None  # the message under the field
    t2: str | None = None  # the W-14 reason: the checkbox is T2 2a
    hint: bool = False  # the reorder hint chip
    focus: str | None = None  # "row" | "field" | "t2"


def list_order(enabled: tuple[str, ...] = DEFAULT) -> list[str]:
    """§6.1: the user's order, enabled rows first, then the rest in `24` §7 order."""
    return [*enabled, *[r["label"] for r in k.CATALOGUE if r["label"] not in enabled]]


def small_button(label: str, w: int, *, name: str, chevron: str | None = None, note: str | None = None) -> Node:
    kids = [text("label", label, k.CAPTION, k.TEXT_1)] + ([icon("chevron", chevron, k.TEXT_2, k.ICON_SM)]
                                                          if chevron else [])
    return hbox(name, kids, {"gap": k.INSET_XS, "padX": k.INSET_SM, "radius": k.R_CONTROL, "stroke": k.BORDER,
                             "strokeWidth": k.HAIR, "strokeAlign": "inner", "justify": "center"}, w=w, h=24,
                note=note)


def field_box(value: str, w: int, *, name: str, invalid: bool = False, chevron: bool = False,
              placeholder: bool = False) -> Node:
    kids = [text("value", value, k.NUM_SM, k.PLACEHOLDER if placeholder else k.TEXT_1)] + (
        [icon("chevron", "chevron-down", k.TEXT_2, k.ICON_SM)] if chevron else [])
    return hbox(name, kids, {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.SUNKEN, "radius": k.R_CONTROL,
                             "stroke": k.TEXT_1 if invalid else k.BORDER, "strokeWidth": k.THICK if invalid else k.HAIR,
                             "strokeAlign": "inner", "justify": "space-between"}, w=w, h=24,
                note='aria-invalid="true", described by the message' if invalid else None)


def list_row(r: R, y: int) -> list[Node]:
    """One CMP-056 row at list y: handle, checkbox + §7 label (+ the hint chip), Format, Sparkline, Threshold, ⋯;
    the T2 2a checkbox with its reason line; the expanded threshold entry beneath."""
    out: list[Node] = []
    kids: list[Node] = [dict(icon("drag handle (pointer only)", "drag-handle", k.TEXT_3, k.ICON), x=4, y=10)]
    if r.t2:
        gate = box("CMP-079 RbacGate", [
            dict(t2_box(r.label, name=k.safe("checkbox " + r.label), typo=k.BODY, h=24, w=96, checkbox_=True,
                        note='checkbox, native role, full label; aria-disabled="true", never disabled; in the roving '
                             'row; aria-describedby → the W-14 node'), x=0, y=0),
            dict(reason(r.t2, 280, "T2 reason (W-14)"), x=4, y=28)], {}, w=300, h=44, x=32, y=6,
            note="CMP-079 RbacGate wraps the gated checkbox (§6.5)")
        kids.append(gate)
        if r.focus == "t2":
            kids.append(ring_rect(96, 24, 32, 6, name="focus ring · T2 checkbox"))
    else:
        kids += [dict(checkbox(r.on, "checkbox"), x=36, y=10),
                 text("label", r.label, k.BODY, k.TEXT_1, x=60, y=8, note=f"the §7 label; accessible name of the "
                                                                          f"checkbox ({r.label!r})")]
        if r.hint:
            chip = k.S("Alt+↑ / Alt+↓ to move")
            cw = round(k.text_w(chip, k.CAPTION)) + 16
            kids.append(hbox("hint chip", [text("words", chip, k.CAPTION, k.TEXT_1)],
                             {"padX": k.INSET_SM, "fill": k.SELECTED, "radius": k.R_BADGE}, w=cw, h=20,
                             x=round(68 + k.text_w(r.label, k.BODY)), y=8,
                             note="its text is in every row's DOM and each checkbox's aria-describedby"))
    rh = 56 if r.t2 else LROW_H
    kids += [dict(small_button(k.S("Format"), 80, name="Format menu button", chevron="chevron-down",
                               note="W-21's menu: decimals and abbreviation only (PROPOSED, D02-G3)"), x=360, y=6),
             box("Sparkline", [dict(checkbox(r.spark, "box"), x=0, y=4),
                               text("label", k.S("Sparkline"), k.CAPTION, k.TEXT_1, x=22, y=4)], {}, w=104, h=24,
                 x=452, y=6, note="per-row sparkline checkbox (PROPOSED, D02-A4)")]
    if r.label in NO_THRESHOLD:
        kids.append(text("no threshold", k.S("No threshold"), k.CAPTION, k.TEXT_2, x=564, y=10))
    else:
        kids.append(dict(small_button(k.S("Threshold"), 76, name="Threshold toggle",
                                      chevron="chevron-down" if r.expanded else "chevron-right",
                                      note=f"toggle button, aria-expanded=\"{str(bool(r.expanded)).lower()}\""),
                         x=564, y=6))
    kids.append(dict(icon_button("row menu button ⋯", "more-horizontal"), x=LIST_W - 24, y=6))
    kids.append(rect("row rule", LIST_W, 1, k.GRID, x=0, y=rh - 1))
    out.append(box(k.safe(f"list row · {r.label}"), kids, {}, w=LIST_W, h=rh, x=DLG_PAD, y=y))
    if r.focus == "row":
        out.append(ring_rect(LIST_W, rh - 2, DLG_PAD, y + 1, name=k.safe(f"focus ring · row {r.label}")))
    if r.expanded:
        cmp_, bound = r.expanded
        unit = {"pct": "%"}.get(k.UNIT[r.label], k.unit_word(r.label))
        ek: list[Node] = [
            text("comparison label", k.ui("Comparison", "the select's visible label"), k.CAPTION, k.TEXT_2, x=60, y=10),
            dict(field_box(cmp_, 72, name="comparison select", chevron=True), x=136, y=6),
            text("bound label", k.ui("Bound", "the field's visible label"), k.CAPTION, k.TEXT_2, x=224, y=10),
            dict(field_box(bound, 80, name="bound field", invalid=bool(r.invalid)), x=268, y=6),
            text("unit", unit or "—", k.CAPTION, k.TEXT_2, x=356, y=10)]
        eh = EXP_H
        if r.invalid:
            ek += [dict(icon("message glyph", "warning", k.TEXT_1, k.ICON_SM), x=268, y=36),
                   text("message", r.invalid, k.CAPTION, k.TEXT_1, x=284, y=35,
                        note="shown on blur and on Apply; the field's aria-describedby")]
            eh += 22
        if r.focus == "field":
            ek.append(ring_rect(80, 24, 268, 6, name="focus ring · bound field"))
        out.append(box(k.safe(f"threshold entry · {r.label}"), ek, {"fill": k.SUNKEN}, w=LIST_W, h=eh, x=DLG_PAD,
                       y=y + rh, note="opens beneath its row only on the toggle, never on focus (§6.2)"))
    return out


def row_h(r: R) -> int:
    return (56 if r.t2 else LROW_H) + ((EXP_H + (22 if r.invalid else 0)) if r.expanded else 0)


def stepper(value: str) -> Node:
    """CMP-008 NumericStepperInput: − value +, each part a 24 px target."""
    return hbox("CMP-008 Sparkline N", [
        hbox("minus", [text("g", "−", k.BODY, k.TEXT_1)], {"justify": "center"}, w=24, h=24),
        hbox("value", [text("v", value, k.NUM_SM, k.TEXT_1)], {"justify": "center", "fill": k.SUNKEN}, w=40, h=24),
        hbox("plus", [text("g", "+", k.BODY, k.TEXT_1)], {"justify": "center"}, w=24, h=24)],
        {"stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL}, w=88, h=24)


def toolbar(set_words: str, *, compact: bool = False, thresholds: bool = True) -> Node:
    def lab(s: str) -> Node:
        return text(f"label {s}", k.S(s), k.BODY, k.TEXT_1)
    kids = [hbox("Compact mode", [lab("Compact mode"), switch(compact)], {"gap": k.INSET_SM}, h=24,
                 note="switch: the row-set choice (MEMO AD-2)"),
            hbox("Sparkline N", [lab("Sparkline N"), stepper(str(k.SPARK_N))], {"gap": k.INSET_SM}, h=24),
            hbox("Thresholds on", [lab("Thresholds on"), switch(thresholds)], {"gap": k.INSET_SM}, h=24,
                 note="US-DS-003 Disabled (11:1921)"),
            field_box(set_words, 104, name="set selector", chevron=True)]
    return hbox("toolbar", kids, {"gap": k.INSET_LG}, w=LIST_W, h=TOOL_H - 16, x=DLG_PAD, y=HEAD_DLG + 4,
                note="sticky above the list; Tab order: Compact mode, Sparkline N, Thresholds on, Set (§11)")


def dialog(fid: str, rows: list[R], *, apply: str = "enabled", view_as: str | None = None, message: str | None = None,
           set_words: str | None = None, scroll_to_end: bool = False, extra: Iterable[Node | None] = (),
           markers: Iterable[Node | None] = ()) -> Node:
    """SCR-033 over an inert SCR-030: header (title, close; the view-as notice), toolbar, the list (scrolling), the
    validation message, footer (Hide Deep Stats left; Cancel, Apply)."""
    k.fallback("scrim")
    title = k.S("Deep Stats rows")
    hk: list[Node] = [text("title", title, k.HEADING_MD, k.TEXT_1, x=DLG_PAD, y=18),
                      dict(icon_button("close", "close", note="Esc / close discard every change"), x=DLG_W - 48, y=16)]
    head_h = HEAD_DLG
    if view_as:
        hk.append(hbox("header notice (view-as)", [lock(), text("words", view_as, k.CAPTION, k.TEXT_2)],
                       {"gap": k.INSET_XS}, w=LIST_W, h=20, x=DLG_PAD, y=48,
                       note="the one notice (R32:57); Apply's aria-describedby target; in the DOM at mount"))
        head_h += 24
    kids: list[Node] = [box("dialog header", hk, {}, w=DLG_W, h=head_h, x=0, y=0)]
    tb = toolbar(set_words or k.S("Set: Global"))
    kids.append(dict(tb, y=head_h + 4))
    list_y = head_h + TOOL_H
    foot_y = DLG_H - FOOT_H
    msg_h = 40 if message else 0
    room = foot_y - msg_h - list_y - 8
    hs = [row_h(r) for r in rows]
    start = 0
    if scroll_to_end:
        while sum(hs[start:]) > room:
            start += 1
    y, drawn = list_y, 0
    lr: list[Node] = []
    for r, h in zip(rows[start:], hs[start:]):
        if y + h - list_y > room:
            break
        lr += list_row(r, y)
        y += h
        drawn += 1
    kids += k.bands("list rows", lr, DLG_W, DLG_H)
    total = sum(hs)
    shown = sum(hs[start:start + drawn])
    kids += [rect("list rule", LIST_W, 1, k.BORDER, x=DLG_PAD, y=list_y - 1),
             rect("scroll track", 4, room, k.SUNKEN, x=DLG_W - 12, y=list_y),
             rect("scroll thumb", 4, round(room * shown / total), k.BORDER_STRONG, x=DLG_W - 12,
                  y=list_y + round(room * sum(hs[:start]) / total), note="the body scrolls; toolbar and footer sticky")]
    if message:
        kids.append(hbox("validation message", [icon("glyph", "info", k.TEXT_1, k.ICON_SM),
                                                text("words", message, k.CAPTION, k.TEXT_1)],
                         {"gap": k.INSET_XS}, w=LIST_W, h=24, x=DLG_PAD, y=foot_y - msg_h + 4,
                         note='role="status", announced once on the last uncheck; Apply\'s aria-describedby'))
    if apply == "t2":
        ap = t2_box(k.S("Apply"), name="CMP-001 Apply", w=96,
                    note='T2 2a (§1.4, view-as): aria-disabled="true", aria-describedby → the header notice')
    elif apply == "invalid":
        ap = hbox("CMP-001 Apply · form validity", [text("label", k.S("Apply"), k.BODY_STRONG, k.TEXT_2)],
                  {"padX": k.BUTTON_PADX, "radius": k.R_CONTROL, "justify": "center", "fill": k.RAISED,
                   "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=72, h=CTRL,
                  note='form validity, not T2 (14:870): aria-disabled="true", focusable, described by W-12; no lock')
    else:
        ap = button(k.S("Apply"), kind="primary")
    cancel = button(k.S("Cancel"))
    fk = [dict(button(k.W("W-11"), kind="ghost", name="Hide Deep Stats"), x=DLG_PAD, y=16),
          dict(cancel, x=DLG_W - DLG_PAD - ap["w"] - 8 - cancel["w"], y=16),
          dict(ap, x=DLG_W - DLG_PAD - ap["w"], y=16), rect("footer rule", DLG_W, 1, k.BORDER, x=0, y=0)]
    kids.append(box("dialog footer", fk, {}, w=DLG_W, h=FOOT_H, x=0, y=foot_y))
    kids += [x for x in extra if x]
    dlg = box("CMP-043 Dialog · SCR-033", kids, {"fill": k.OVERLAY, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                                 "strokeAlign": "inner", "radius": k.R_DIALOG, "clip": True},
              w=DLG_W, h=DLG_H, x=DLG_X, y=DLG_Y, note='role="dialog", size md; initial focus the first enabled '
                                                       'row\'s checkbox; Esc / Cancel / Apply return focus to the gear')
    p = P()
    behind = [top_bar(p), box("SCR-030 behind the modal", [
        text("words", k.ui("SCR-030 with the strip, inert behind the modal (drawn on boards 01–06)", "board-marker "
                           "label for the inert page"), k.CAPTION, k.TEXT_3, x=16, y=12)],
        {"fill": k.CANVAS}, w=k.WIN_W, h=k.WIN_H - TOP_H, x=0, y=TOP_H)]
    scrim = rect("scrim", k.WIN_W, k.WIN_H, k.OVERLAY, {"opacity": k.SCRIM}, x=0, y=0,
                 note="the inert SCR-030 behind the modal")
    mk = stack(markers, 16, 48)
    return k.frame(fid, [*behind, scrim, dlg, *mk])


def menu_at(r_y: int, items: list[Node], w: int = 200) -> Node:
    """The row menu (role=menu) anchored under a row's ⋯ (dialog coordinates)."""
    c = card("row menu (role=menu)", items, w, "Move up / Move down (E47-D09:140); Esc returns to ⋯", pad=k.INSET_XS)
    return dict(c, x=DLG_W - DLG_PAD - w, y=r_y + 32)
