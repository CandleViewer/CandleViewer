"""Shared pieces of the E47-D08 generators: the kit import, the seeded synthetic world (TICKS) and the panels several
boards draw (watchlist rows, the DOM ladder, the chart body, the heatmap, the timeline axis)."""
from __future__ import annotations

import sys
from pathlib import Path

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e47d08kit as k  # noqa: E402

Node = k.Node
FOCUS_SYMBOL = "BTCUSDT"  # kit choice: TICKS names no instrument; the label is synthetic like its prices
OTHERS = (("ETHUSDT", 348_000, 2), ("SOLUSDT", 18_200, 3))  # (symbol, synthetic anchor in ticks, TICKS seed)
DEC = int(k.TICK_DEFAULTS["tickDecimals"])
START = int(k.TICK_DEFAULTS["startPriceTicks"])


def fmt(ticks: int) -> str:
    return f"{ticks // 10 ** DEC:,}.{ticks % 10 ** DEC:0{DEC}d}"


def fmt_delta(d: int) -> str:
    return ("+" if d > 0 else "−" if d < 0 else "±") + f"{abs(d) // 10 ** DEC}.{abs(d) % 10 ** DEC:0{DEC}d}"


def series(symbol: str) -> list[tuple[int, int]]:
    """(t_ms, price ticks) of a symbol over the burst: the focused one is TICKS' burst itself; the others are the same
    generator with another seed, moved onto a synthetic anchor."""
    if symbol == FOCUS_SYMBOL:
        return [(t.t_ms, t.price_ticks) for t in k.BURST]
    anchor, seed = next((a, s) for sym, a, s in OTHERS if sym == symbol)
    return [(t.t_ms, anchor + t.price_ticks - START) for t in k.generate_ticks(seed=seed)]


def at(symbol: str, t_ms: int) -> tuple[int, int]:
    """(price, previous different-from price): the last tick at or before t_ms and the change from the tick before."""
    s = [p for t, p in series(symbol) if t <= t_ms]
    prev = s[-2] if len(s) > 1 else s[-1]
    return s[-1], s[-1] - prev


def seeded(seed: int, n: int, lo: int, hi: int) -> list[int]:
    """n integers in [lo, hi] from TICKS' mulberry32 (the generator's PRNG, another seed)."""
    r = k.mulberry32(seed)
    return [lo + int(r() * (hi - lo + 1)) for _ in range(n)]


# --- CMP-161 watchlist rows (Symbol | Last | Change), the I-5 carrier
WL_COLS = (k.Col("sym", "Symbol", 80), k.Col("last", "Last", 112, True), k.Col("chg", "Change", 112, True))


def change_cell(delta: int, *, mode: str = "safe", show_glyph: bool | None = None) -> list[Node]:
    """The glyph and the sign (MR-3); under forced colours both in CanvasText (FALLBACKS forced)."""
    up = delta >= 0
    col = k.TEXT_1 if mode == "forced" else (k.BUY if up else k.SELL)
    if mode == "forced":
        k.fallback("forced")
    kids: list[Node] = []
    if show_glyph is None or show_glyph:
        kids.append(k.glyph(up, col))
    kids.append(k.text("sign", fmt_delta(delta), k.NUM, col))
    return kids


def overlay(w_: int, h: int, up: bool, phase: str = "peak") -> Node:
    """The I-5 overlay (FALLBACKS flash-peak): the subtle tint at the peak, the same tint at opacity.muted mid-decay;
    drawn first, behind the value, so the digits stay at full contrast."""
    k.fallback("flash-peak")
    o = {"fill": k.BUY_SUBTLE if up else k.SELL_SUBTLE}
    if phase == "mid":
        o["opacity"] = k.OPACITY_MUTED
    return k.rect(f"I-5 overlay · {phase}", w_, h, None, o, x=0, y=0, abs=True,
                  note=f"overlay opacity 0.25 → 0 in color.{'buy' if up else 'sell'}.default (§3 I-5): {phase}")


def watch_row(symbol: str, t_ms: int, i: int, *, flash: str | None = None, mode: str = "safe",
              glyph_up: bool | None = None, note: str | None = None) -> Node:
    """One row; flash 'peak' / 'mid' paints the I-5 overlay on the Last cell (safe mode only); glyph_up holds the
    glyph's direction (§5) while the sign shows the true change (R-4)."""
    p, d = at(symbol, t_ms)
    last: list[Node] = [k.text("value", fmt(p), k.NUM, k.TEXT_1)]
    if flash:
        last.insert(0, overlay(WL_COLS[1].w, k.ROW_H, d >= 0, flash))
    if glyph_up is None:
        chg = change_cell(d, mode=mode)
    else:
        gc = k.TEXT_1 if mode == "forced" else (k.BUY if glyph_up else k.SELL)
        chg = [k.glyph(glyph_up, gc),
               k.text("sign", fmt_delta(d), k.NUM, k.TEXT_1 if mode == "forced" else (k.BUY if d >= 0 else k.SELL))]
    return k.table_row(WL_COLS, {"sym": symbol, "last": last, "chg": chg}, f"row {i}", i, h=k.ROW_H, note=note)


def watchlist(t_ms: int, *, flash: dict[str, str] | None = None, mode: str = "safe",
              held: dict[str, bool] | None = None) -> Node:
    syms = (FOCUS_SYMBOL, *(s for s, _a, _sd in OTHERS))
    rows = [watch_row(s, t_ms, i, flash=(flash or {}).get(s), mode=mode, glyph_up=(held or {}).get(s))
            for i, s in enumerate(syms, 1)]
    return k.table("CMP-049 grid · watchlist", None, k.header_row(WL_COLS), rows,
                   note="CMP-161 WatchlistRow ×3: the I-5 carrier (overlay, or the glyph and the sign)")


# the watchlist panel's height: its 28 px header over the grid's content (header row 24, two 4 px gaps, the rule and
# three 24 px rows: 105 px); the first sheets gave the panel 128, so the grid had 100 px and row 3 was cut live
WL_PANEL_H = k.HEADER_H + round(k.est_height(watchlist(0)))


# --- the DOM ladder (CMP-049): price rows around the focused symbol's price at t_ms
LAD_COLS = (k.Col("bid", "Bid size", 80, True), k.Col("price", "Price", 112, True), k.Col("ask", "Ask size", 80, True))


def ladder(t_ms: int, rows: int = 9, *, flash_price: int | None = None, seed: int = 11) -> Node:
    p, d = at(FOCUS_SYMBOL, t_ms)
    sizes = seeded(seed, rows, 1, 60)
    out = []
    for i in range(rows):
        lvl = p + (rows // 2 - i)
        ask = lvl > p
        sz = f"{sizes[i] / 10:.1f}"
        price: list[Node] = [k.text("value", fmt(lvl), k.NUM, k.SELL if ask else k.BUY)]
        if flash_price == lvl:
            price.insert(0, overlay(LAD_COLS[1].w, k.ROW_H, d >= 0))
        out.append(k.table_row(LAD_COLS, {"bid": None if ask else sz, "price": price, "ask": sz if ask else None},
                               f"row {i + 1}", i + 1, h=k.ROW_H))
    return k.table("CMP-049 grid · DOM ladder", None, k.header_row(LAD_COLS), out,
                   note=f"{FOCUS_SYMBOL} ladder at {t_ms} ms (synthetic sizes, TICKS mulberry32 seed {seed})")


def nb(n: int) -> str:
    """A number with a thin-space-free plain space as the thousands separator, as the spec writes "1 000"."""
    return f"{n:,}".replace(",", " ")


# --- a millisecond timeline (annotation axis; FALLBACKS time-axis): a non-flex box, marks placed by x = x0 + t * scale
class Timeline:
    def __init__(self, t0: int, t1: int, x0: int, width: int) -> None:
        self.t0, self.t1, self.x0, self.wd = t0, t1, x0, width
        self.scale = width / (t1 - t0)

    def x(self, t: float) -> int:
        return self.x0 + round((t - self.t0) * self.scale)

    def axis(self, y: int, step: int, *, name: str = "axis") -> list[Node]:
        k.fallback("time-axis")
        out = [k.rect(f"{name} · line", self.wd, 1, k.BORDER, x=self.x0, y=0)]
        for t in range(self.t0, self.t1 + 1, step):
            out.append(k.rect(f"{name} · tick {t}", 1, 6, k.AXIS, x=self.x(t), y=0))
            lab = nb(t) + (" ms" if t == self.t1 else "")
            dx = round(k.text_w(lab, k.CAPTION)) if t == self.t1 else 4
            out.append(k.text(f"{name} · label {t}", lab, k.CAPTION, k.AXIS, x=self.x(t) - dx, y=8))
        return [k.box(name, out, None, w=self.x0 + self.wd + 8, h=24, x=0, y=y)]

    def windows(self, y: int, h: int, *, name: str = "window") -> list[Node]:
        """The half-open 1 000 ms windows [n * W, (n + 1) * W): every other one shaded (annotation)."""
        k.fallback("markers")
        out = []
        for i, s in enumerate(range(self.t0, self.t1, k.WINDOW_MS)):
            e = min(s + k.WINDOW_MS, self.t1)
            if i % 2 == 0:
                out.append(k.rect(f"{name} {i + 1} · shade", self.x(e) - self.x(s), h, k.INFO_SUBTLE,
                                  x=self.x(s), y=0, note="annotation: a half-open 1 000 ms window"))
            out.append(k.text(f"{name} {i + 1} · label", f"window [{nb(s)}, {nb(e)}) ms", k.CAPTION,
                              k.TEXT_2, x=self.x(s) + 4, y=2))
        return [k.box(f"{name}s", out, None, w=self.x0 + self.wd, h=h, x=0, y=y)]


# --- the chart body: candles of the focused symbol bucketed from the burst (non-flex box; x, y derived)
def bars(bucket_ms: int, t0: int = 0, t1: int = k.BURST_MS) -> list[tuple[int, int, int, int, int]]:
    """(t, open, high, low, close) per bucket of the focused symbol's ticks."""
    out = []
    s = series(FOCUS_SYMBOL)
    for b0 in range(t0, t1, bucket_ms):
        ps = [p for t, p in s if b0 <= t < b0 + bucket_ms]
        if ps:
            out.append((b0, ps[0], max(ps), min(ps), ps[-1]))
    return out


class PriceScale:
    def __init__(self, lo: int, hi: int, y0: int, h: int) -> None:
        self.lo, self.hi, self.y0, self.h = lo - 1, hi + 1, y0, h

    def y(self, p: int) -> int:
        return self.y0 + round((self.hi - p) * self.h / (self.hi - self.lo))


def chart_body(w_: int, h: int, bucket_ms: int = 100, *, t1: int = k.BURST_MS, name: str = "plot") -> tuple[Node,
                                                                                                         PriceScale]:
    bs = bars(bucket_ms, 0, t1)
    sc = PriceScale(min(b[3] for b in bs), max(b[2] for b in bs), 16, h - 48)
    step = (w_ - 80) / len(bs)
    kids: list[Node] = [k.rect("grid · mid", w_ - 72, 1, k.GRID, x=8, y=sc.y((sc.lo + sc.hi) // 2))]
    for i, (t, o, hi, lo, c) in enumerate(bs):
        x = 8 + round(i * step)
        up = c >= o
        kids.append(k.rect(f"wick {t}", 1, max(sc.y(lo) - sc.y(hi), 1), k.C_WICK, x=x + round(step / 2) - 1,
                           y=sc.y(hi)))
        kids.append(k.rect(f"body {t}", max(round(step) - 2, 2), max(abs(sc.y(o) - sc.y(c)), 2),
                           k.C_UP if up else k.C_DOWN, x=x, y=min(sc.y(o), sc.y(c))))
    for p in (sc.hi - 1, (sc.lo + sc.hi) // 2, sc.lo + 1):
        kids.append(k.text(f"axis {p}", fmt(p), k.NUM_SM, k.AXIS, x=w_ - 64, y=sc.y(p) - 7))
    return k.box(name, kids, {"fill": k.CANVAS, "clip": True}, w=w_, h=h,
                 note=f"{FOCUS_SYMBOL} candles of {bucket_ms} ms from the TICKS burst (synthetic)"), sc


def liq_mark(size: str, *, overlay: bool, name: str = "I-24 liquidation mark") -> Node:
    """The liquidation mark (MR-3's carrier: the glyph and the size as text); overlay = the §6 flash (FALLBACKS)."""
    k.fallback("glyph")
    kids: list[Node] = [k.icon("glyph", "warning", k.WARN_STRONG, note="the liquidation glyph"),
                        k.text("size", size, k.NUM_SM, k.TEXT_1)]
    o: dict = {"gap": k.INSET_XS, "padX": k.INSET_XS, "radius": k.R_CONTROL}
    if overlay:
        k.fallback("liq-overlay")
        o.update(fill=k.WARN_SUBTLE, stroke=k.WARN_STRONG, strokeWidth=k.THICK, strokeAlign="inner")
    return k.hbox(name, kids, o, h=24, note="§6: an opacity-only overlay, <= one start per 1 000 ms per panel"
                  + ("; PROPOSED color.liquidation.flash (D08-A9)" if overlay else "; no overlay"))
