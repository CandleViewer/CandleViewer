"""E21-D04 frame builders: the specimen frames of the ten boards, keyed by board and frame id (k.FRAME_PLAN). Every
drawn string is the spec's (k.S / k.W check it verbatim) or is noted as a copy gap with its source; every number is
derived from the kit's synthetic book (seed 504)."""
from __future__ import annotations

import math
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e21d04kit as k  # noqa: E402
from e21d04kit import (S, W, Wt, L, Node, box, hbox, icon, rect, text, vbox)  # noqa: E402

FPAD = 16  # frame padding (kit choice)
D = k.TICK


# --- small pieces
def gap_text(name: str, chars: str, src: str, typo: str = k.CAPTION, color: str = k.TEXT_1, **kw: Any) -> Node:
    """A string the spec does not word: drawn and noted with its source."""
    k.copy_gap(f'"{chars}": {src}')
    return text(name, chars, typo, color, **kw)


def marker(words: str, *, w: int | None = None, name: str | None = None) -> Node:
    """A board marker: caption words in a 1 px color.border.strong outline, never product UI."""
    k.fallback("marker")
    t = text("words", words, k.CAPTION, k.TEXT_2, **({"w": w - 16} if w else {}))
    return hbox(name or f"board marker · {words[:28]}".replace("/", k.SLASH), [t],
                {"padX": k.INSET_SM, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                 "radius": k.R_CONTROL}, w=w or round(k.text_w(words, k.CAPTION)) + 18,
                h=round(k.est_height(t)) + 8 if w else 20, note="board marker, not product UI")


def name_marker(role: str, chars: str, *, w: int = 560) -> Node:
    """The accessible name (or a visually hidden string) drawn for the board: role, then the words."""
    k.fallback("hidden")
    words = text("words", chars, k.CAPTION, k.TEXT_1, w=w - 16)
    head = text("role", role, k.CAPTION, k.TEXT_3)
    return vbox(f"board marker · name · {role[:24]}", [head, words],
                {"gap": k.STACK_XS, "pad": k.INSET_SM, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                 "strokeAlign": "inner", "radius": k.R_CONTROL, "fill": k.SUNKEN}, w=w,
                h=round(k.est_height(head) + k.est_height(words) + 4 + 16), note="board marker: not on screen")


def lock(name: str = "CMP-019 lock", color: str = k.TEXT_3) -> Node:
    """The T2 lock (CMP-019, decorative=false, name "Not available"), color.text.tertiary (R-3, G-T2.2)."""
    k.fallback("icon-sm")
    return icon(name, "locked", color, k.ICON_SM, note='CMP-019 Icon "lock", accessible name "Not available"')


def ring(n: Node, *, color: str = k.RING, gap_fill: str | None = None, name: str = "CMP-039 focus ring") -> Node:
    """CMP-039: a 2 px ring outside the box with a 2 px offset (a wrapper 4 px larger a side, the ring inner)."""
    w, h = round(k.est_width(n)), round(k.est_height(n))
    kids = [dict(n, x=4, y=4)]
    if gap_fill:  # forced colours: a 1 px Canvas gap inside the Highlight ring (§5.5)
        kids.insert(0, rect("ring gap", w + 4, h + 4, None, {"stroke": gap_fill, "strokeWidth": k.HAIR,
                                                            "strokeAlign": "inner"}, x=2, y=2))
    return box(name, kids, {"stroke": color, "strokeWidth": k.FOCUS_W, "strokeAlign": "inner",
                            "radius": k.R_CONTROL}, w=w + 8, h=h + 8, note="focus-visible (CMP-039), outside the box")


def dashes(name: str, length: int, color: str, *, vertical: bool = False, x: int = 0, y: int = 0,
           thick: int = 1) -> Node:
    k.fallback("dash")
    kids, i, p = [], 0, 0
    while p < length:
        d = min(4, length - p)
        kids.append(rect(f"dash {i:02d}", thick if vertical else d, d if vertical else thick, color,
                         x=0 if vertical else p, y=p if vertical else 0))
        i, p = i + 1, p + 8
    return box(name, kids, w=thick if vertical else length, h=length if vertical else thick, x=x, y=y)


def dashed_box(name: str, w: int, h: int, color: str, *, x: int = 0, y: int = 0) -> Node:
    return box(name, [dashes("top", w, color), dashes("bottom", w, color, y=h - 1),
                      dashes("left", h, color, vertical=True), dashes("right", h, color, vertical=True, x=w - 1)],
               w=w, h=h, x=x, y=y)


def hatch(name: str, w: int, h: int, *, x: int = 0, y: int = 0) -> Node:
    """pattern.hatch.estimated's look (cited from D05E11 §7, not re-made): 2 × 2 steps on a 6 px 45° track."""
    k.fallback("hatch")
    kids: list[Node] = []
    for row in range(0, h - 1, 2):
        for s0 in range(-h, w + h, 6):
            x0 = s0 + (h - 2 - row)
            if 0 <= x0 <= w - 2:
                kids.append(rect(f"step {len(kids):03d}", 2, 2, k.NEUTRAL, x=x0, y=row))
    return box(name, kids, {"clip": True}, w=w, h=h, x=x, y=y)


def swatch(tok: str, *, outline: str | None = None, w: int = 24, h: int = 16) -> Node:
    k.fallback("swatch")
    o = {"stroke": outline, "strokeWidth": k.HAIR, "strokeAlign": "inner"} if outline else None
    return rect(f"swatch · {tok}", w, h, tok, o)


def badge_estimated(*, host: str = "inline") -> Node:
    """CMP-227 `inline` (sm): the info-subtle pill, its glyph and the word "(estimated)" (`15`:2938)."""
    word = S("(estimated)")
    g = icon("glyph (stand-in: info)", "info", k.INFO, k.ICON_SM)
    k.fallback("icon-sm")
    k.reading("CMP-227's glyph (IconName `estimated`, PROPOSED in `15`) is not in the local set: drawn with the local "
              "'info' glyph as a stand-in")
    t = text("word", word, k.CAPTION, k.TEXT_1)
    return hbox(f"CMP-227 EstimatedBadge · {host}", [g, t],
                {"gap": k.INSET_XS, "padX": k.INSET_XS, "fill": k.INFO_SUBTLE, "stroke": k.INFO,
                 "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_BADGE},
                w=round(12 + 4 + k.text_w(word, k.CAPTION) + 8 + 2), h=16, note='button, name "Estimated, …"')


def t2_item(label: str, *, w: int, focused: bool = False, forced: bool = False) -> Node:
    """R-3 rendering 2a: the CMP-019 lock leading the full label in color.text.tertiary, on color.surface.raised with
    a 1 px color.border.default hairline; aria-disabled, never opacity.disabled."""
    b = hbox(f"T2 item · {label}", [lock(), text("label", label, k.BODY, k.TEXT_3)],
             {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": None if forced else k.RAISED,
              "stroke": k.TEXT_1 if forced else k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner",
              "radius": k.R_CONTROL}, w=w, h=k.ROW_H, note='menuitem, aria-disabled="true", described by the notice')
    return ring(b) if focused else b


# --- CMP-108 rows: the six cell slots (BQ-15; the column set, order and header words are D02's §2.3)
OWN_CLAUSE = re.search(r'the own clause is "([^"]+)"', k.SPEC_TEXT).group(1)  # type: ignore[union-attr]
WORD_ESTIMATED = S("estimated")
WORD_STALE = S("stale")


def cols() -> list[k.Col]:
    k.copy_gap('"Bid (B)", "Ask (A)": the column headers of D02 §2.3 (E21-D02 at 7e1040260; the words are D02\'s)')
    k.reading("column widths 208 / 96 / 96 / 72 / 96 / 272 px are the kit's (D02 §2.3 says 'fixed' and names no "
              "width); the Your-orders width fits W-4's longest words")
    return [k.Col("price", S("Price"), 208), k.Col("bid", "Bid (B)", 96, True), k.Col("ask", "Ask (A)", 96, True),
            k.Col("prints", S("Prints"), 72, True), k.Col("depth", S("Cum. depth"), 96, True),
            k.Col("own", S("Your orders"), 272)]


LADDER_W = 840


def side_word(o: k.Own) -> str:
    return o.side.capitalize()


def single_words(o: k.Own) -> str:
    return Wt("W-2", {"Buy": side_word(o), "0.5": k.qty(o.qty), "limit": o.kind})


def agg_words(p: Decimal) -> str:
    os_ = k.own_at(p)
    buys = sum((o.qty for o in os_ if o.side == "buy"), Decimal(0))
    sells = sum((o.qty for o in os_ if o.side == "sell"), Decimal(0))
    if buys and sells:
        return Wt("W-4", {"3 orders": f"{len(os_)} orders", "buy 1.0": f"buy {k.qty1(buys)}",
                          "sell 0.2": f"sell {k.qty1(sells)}"})
    sd, q = ("buy", buys) if buys else ("sell", sells)
    return Wt("W-3", {"3 orders": f"{len(os_)} orders", "buy 1.2": f"{sd} {k.qty1(q)}"})


def position_words() -> str:
    return Wt("W-9", {"0.30": f"{k.POSITION_QTY:.2f}"})


def own_glyph(o: k.Own, forced: bool) -> Node:
    k.fallback("own-glyph")
    tok = k.BUY if o.side == "buy" else k.SELL
    return rect("CMP-230 glyph", 8, 8, None if forced else tok,
                {"stroke": k.TEXT_1, "strokeWidth": k.HAIR, "strokeAlign": "inner"} if forced else None)


def own_cell(p: Decimal, *, forced: bool = False, expanded: bool = False) -> list[Node]:
    os_ = k.own_at(p)
    fg = k.TEXT_1
    if not os_:
        return []
    if len(os_) == 1:
        o = os_[0]
        words = single_words(o)
        sw, rest = words.split(" ", 1)
        kids = [text("side word", sw, k.NUM_SM, fg if forced else (k.BUY if o.side == "buy" else k.SELL)),
                text("words", rest, k.NUM_SM, fg)]
        if o.status != "working":
            kids.append(text("status", W("W-6") if o.status == "pending" else W("W-7"), k.NUM_SM,
                             fg if forced else k.TEXT_2))
        return [*kids, own_glyph(o, forced)]
    words = agg_words(p)
    count, rest = words.split(" · ", 1)
    k.reading("CMP-230's count badge drawn as the count words in a 1 px pill outline, the rest after a ' · '; the "
              "chevron (right collapsed, down expanded) is the kit's expand cue, aria-expanded carries the state")
    k.fallback("pill")
    pill = hbox("count badge", [text("words", count, k.NUM_SM, fg)],
                {"padX": k.INSET_XS, "stroke": k.TEXT_1 if forced else k.BORDER_STRONG, "strokeWidth": k.HAIR,
                 "strokeAlign": "inner", "radius": k.R_PILL}, w=round(k.text_w(count, k.NUM_SM)) + 10, h=16)
    return [pill, text("words", "· " + rest, k.NUM_SM, fg),
            icon("expand cue", "chevron-down" if expanded else "chevron-right", fg if forced else k.TEXT_2,
                 k.ICON_SM)]


def row_label(p: Decimal, *, stale: bool = False, estimated: bool = False, position: bool = False) -> str:
    sd, sz = k.side_at(p), k.size_at(p)
    none = S("none")
    vals = {"price": k.price(p), "bid": k.qty(sz) if sd == "bid" else none,
            "ask": k.qty(sz) if sd == "ask" else none}
    flags: list[str] = []
    if p == k.BEST_BID:
        flags.append("best bid")
    if p == k.BEST_ASK:
        flags.append("best ask")
    if p == k.MARK:
        flags.append("at the mark")
    if p in k.PRINTS:
        flags.append("prints")
        vals["prints"] = k.qty(k.PRINTS[p])
    if sd:
        flags.append("depth")
        vals["depth"] = k.qty(k.cum_depth(p))  # type: ignore[arg-type]
    os_ = k.own_at(p)
    if os_:
        flags.append("own")
        vals["own"] = (OWN_CLAUSE.replace("{side}", os_[0].side).replace("{qty}", k.qty(os_[0].qty))
                       if len(os_) == 1 else k.name_form(agg_words(p)))
    if position and p == k.POSITION_AT:
        flags.append("position")
        vals["position"] = k.name_form(position_words())
    if stale:
        flags.append("stale")
    if estimated:
        flags.append("estimated")
    return k.label(vals, flags)


def ladder_row(p: Decimal, vmax: Decimal, *, h: int = 0, stale: bool = False, forced: bool = False,
               estimated: bool = False, position: bool = False, expanded: bool = False) -> Node:
    h = h or k.ROW_H
    cs = cols()
    fg = k.TEXT_1
    sd, sz = k.side_at(p), k.size_at(p)
    price_kids: list[Node] = [text("price", k.price(p), k.NUM_SM, fg)]
    if position and p == k.POSITION_AT:
        price_kids.append(text("position marker", position_words(), k.NUM_SM, fg if forced else k.TEXT_2))
    if stale:
        price_kids.append(text("stale word", WORD_STALE, k.CAPTION, fg if forced else k.STALE_TEXT))
    if estimated:
        price_kids.append(badge_estimated(host="row"))

    def size_cell(side: str) -> list[Node]:
        if sd != side or sz is None:
            return []
        letter = "B" if side == "bid" else "A"
        kids = [text("side letter", letter, k.NUM_SM, fg if forced else k.TEXT_2, note="aria-hidden"),
                text("size", k.qty(sz), k.NUM_SM, fg)]
        if not forced:  # §5.5: the bar is hidden under forced colours; the number carries the size
            inner = 96 - 16
            bw = max(1, round(inner * float(sz / vmax)))
            kids.insert(0, rect("size bar", bw, h - 8, k.BUY_SUBTLE if side == "bid" else k.SELL_SUBTLE,
                                x=8 + inner - bw if side == "bid" else 8, y=4, abs=True,
                                note="aria-hidden; length = size / the visible window's largest size"))
        return kids

    cells = {"price": price_kids, "bid": size_cell("bid"), "ask": size_cell("ask"),
             "prints": k.qty(k.PRINTS[p]) if p in k.PRINTS else None,
             "depth": k.qty(k.cum_depth(p)) if sd else None,  # type: ignore[arg-type]
             "own": own_cell(p, forced=forced, expanded=expanded)}
    fill = k.APP if forced else k.STALE_SURFACE if stale else k.CANVAS
    kids = [k.cell(c.key, cells.get(c.key), c.w, numeric=c.numeric, h=h, color=fg) for c in cs]
    return hbox(f"row · {k.price(p)}", kids, {"fill": fill}, w=LADDER_W, h=h,
                note=f'role="row", name: {row_label(p, stale=stale, estimated=estimated, position=position)}')


def header(*, forced: bool = False, h: int = 0) -> Node:
    hr = k.header_row(cols())
    if forced:
        hr["o"] = dict(hr["o"], fill=k.APP)
    return hr


def window(prices: list[Decimal], *, h: int = 0, stale: bool = False, forced: bool = False,
           estimated_at: Decimal | None = None, position: bool = False, expanded_at: Decimal | None = None,
           ring_at: Decimal | None = None, ring_color: str = k.RING) -> Node:
    """A header and the given rows (top = highest price); bars scale to the window's largest size."""
    vmax = max((k.size_at(p) or Decimal(0) for p in prices), default=Decimal(1)) or Decimal(1)
    hh = h or k.ROW_H
    rows: list[Node] = [header(forced=forced)]
    for p in prices:
        rows.append(ladder_row(p, vmax, h=h, stale=stale, forced=forced, estimated=p == estimated_at,
                               position=position, expanded=p == expanded_at))
    if ring_at is not None:  # CMP-039 drawn over the rows, 2 px outside the row box, so the rows keep their pitch
        y = k.ROW_H + prices.index(ring_at) * hh
        rows.append(rect("CMP-039 focus ring", LADDER_W + 8, hh + 8, None,
                         {"stroke": ring_color, "strokeWidth": k.FOCUS_W, "strokeAlign": "inner",
                          "radius": k.R_CONTROL}, x=0, y=y - 4, abs=True, note="focus-visible, outside the row box"))
        if forced:
            rows.append(rect("ring gap", LADDER_W + 4, hh + 4, None, {"stroke": k.APP, "strokeWidth": k.HAIR,
                                                                      "strokeAlign": "inner"}, x=2, y=y - 2,
                             abs=True))
    k.derive(f"bars: length = size / the window's largest size ({k.qty(vmax)}) × the 80 px cell inner width")
    ringed = ring_at is not None
    return vbox("CMP-108 rows", rows, {"padX": k.INSET_XS} if ringed else None, w=LADDER_W + (8 if ringed else 0),
                h=k.ROW_H + len(prices) * hh)


def around(p: Decimal, n: int = 1) -> list[Decimal]:
    return [p + i * D for i in range(n, -n - 1, -1)]


# --- the frame wrapper
def frame(vid: str, nn: int, kids: list[Node], *, w: int | None = None, fill: str = k.CANVAS) -> Node:
    """A specimen frame: the kids stacked with 12 px gaps inside 16 px padding, hugging them (h rounded up to 8)."""
    inner_w = max(round(k.est_width(x)) for x in kids)
    fw = w or inner_w + 2 * FPAD
    inner_h = sum(k.est_height(x) for x in kids) + 12 * (len(kids) - 1)
    fh = int(math.ceil((inner_h + 2 * FPAD) / 8) * 8)
    return box(k.frame_name(vid, nn), kids, {"dir": "column", "align": "start", "gap": k.STACK_MD, "pad": k.INSET_LG,
                                             "fill": fill, "clip": True}, w=fw, h=fh,
               note=f"specimen frame: {vid} (no library component)")


def stage(name: str, kids: list[Node], w: int, h: int) -> Node:
    """A free-placed group (no flex): kids carry x / y."""
    return box(name, kids, w=w, h=h)


# --- the heatmap pane (CMP-111 cells over CMP-193's mount; drawn as specimen cells, one row per ladder row)
CW = 16  # one trail column (1 s) drawn 16 px wide


def set_tokens(si: int) -> tuple[list[str], list[str]]:
    """§5.1's set si: (bid stops, ask stops)."""
    _n, b, a, _f = k.PALETTE_SETS[si]
    return k.stops(b), k.stops(a)


def heat_pane(prices: list[Decimal], *, si: int = 0, scale: str = "log", rh: int = 0, cw: int = CW,
              head: int = 0, pulled: bool = True, name: str = "heatmap pane") -> tuple[Node, Decimal]:
    """Cells for the given rows over the drawn trail; returns (pane, the window's largest size)."""
    rh = rh or k.ROW_H
    bids, asks = set_tokens(si)
    vmax = max(k.trail_window(prices), default=Decimal(1)) or Decimal(1)
    kids: list[Node] = []
    for r, p in enumerate(prices):
        sd = k.side_at(p) or ("bid" if p < k.MARK else "ask")
        cells = []
        for c, s in enumerate(k.trail(p)):
            bk = k.bucket(s, vmax, scale)
            tok = k.HEAT_ZERO if bk == 0 else (bids if sd == "bid" else asks)[bk - 1]
            cells.append(rect(f"cell {c:02d}", cw, rh, tok, x=c * cw, y=0))
        kids.append(box(f"cells · {k.price(p)}", cells, w=k.TRAIL_COLS * cw, h=rh, x=0, y=head + r * rh))
        if pulled and p == k.PULL_PRICE:
            x0 = k.PULL_COL * cw
            kids.append(hatch("pulled mark · hatch", cw, rh, x=x0, y=head + r * rh))
            kids.append(dashed_box("pulled mark · outline", cw, rh, k.TEXT_1, x=x0, y=head + r * rh))
    if k.MARK in prices:
        kids.append(rect("mark rule", len(k.trail(prices[0])) * cw, 1, k.TEXT_2, x=0,
                         y=head + prices.index(k.MARK) * rh + rh // 2))
    k.derive(f"heatmap cells: stop = ceil(5 × {scale}-scaled size / the window's largest size {k.qty(vmax)}); 0 = "
             f"color.heatmap.zero (the floor, never a stop)")
    return stage(name, kids, k.TRAIL_COLS * cw, head + len(prices) * rh), vmax


# --- CMP-024 sparkline and the CMP-111 reveal region
SPARK_W, SPARK_H = 240, 48


def sparkline(series: dict[str, list[Decimal]]) -> Node:
    k.fallback("sparkline")
    vmax = max((v for s in series.values() for v in s), default=Decimal(1)) or Decimal(1)
    kids: list[Node] = []
    ends: dict[str, int] = {}
    step = SPARK_W // (k.TRAIL_COLS - 1)
    for side, vals in series.items():
        ys = [SPARK_H - 2 - round((SPARK_H - 4) * float(v / vmax)) for v in vals]
        tok = k.TEXT_1
        for i, y in enumerate(ys):
            x0 = i * step
            seg = step if i < len(ys) - 1 else 2
            if side == "ask":
                kids.append(dashes(f"ask run {i:02d}", seg, tok, x=x0, y=y, thick=2))
            else:
                kids.append(rect(f"bid run {i:02d}", seg, 2, tok, x=x0, y=y))
            if i and ys[i - 1] != y and side == "bid":
                kids.append(rect(f"bid riser {i:02d}", 2, abs(ys[i - 1] - y) + 2, tok, x=x0, y=min(ys[i - 1], y)))
        ends[side] = max(0, min(SPARK_H - 14, ys[-1] - 6))
    if abs(ends.get("bid", 0) - ends.get("ask", 99)) < 14:  # the two end labels never overlap
        ends["bid"] = max(0, ends["ask"] - 14) if ends["ask"] >= 14 else ends["ask"] + 14
    for side, y in ends.items():
        kids.append(text(f"label {side}", S("Bid") if side == "bid" else S("Ask"), k.CAPTION, k.TEXT_2,
                         x=SPARK_W + 6, y=y))
    return stage("CMP-024 Sparkline", kids, SPARK_W + 32, SPARK_H)


def reveal(p: Decimal, *, state: str = "open") -> Node:
    """CMP-111's reveal region (A-10): heading W-14 (programmatic focus), CMP-024 named W-24, CMP-049 named W-25 with
    the W-17 line; empty → W-15; stale → the word; pulled → W-16 in the pulled column."""
    pr = k.price(p)
    heading = text("heading", Wt("W-14", {"{price}": pr}), k.HEADING_SM, k.TEXT_1)
    kids: list[Node] = [ring(heading, name="CMP-039 focus ring · heading (tabindex -1)")]
    hist = k.trail(p)
    sd = k.side_at(p)
    if state == "empty" or not any(hist):
        kids.append(text("empty", W("W-15"), k.BODY, k.TEXT_2))
        return _region(kids, pr)
    bid = hist if sd == "bid" else [Decimal(0)] * len(hist)
    ask = hist if sd == "ask" else [Decimal(0)] * len(hist)
    span = f"{k.TRAIL_COLS * k.TRAIL_STEP_S} s"
    kids.append(sparkline({"bid": bid, "ask": ask}))
    kids.append(name_marker('img name (CMP-024)', Wt("W-24", {"{price}": pr, "{span}": span, "{bidFrom}": k.qty(bid[0]),
                                                             "{bidTo}": k.qty(bid[-1]), "{askFrom}": k.qty(ask[0]),
                                                             "{askTo}": k.qty(ask[-1])})))
    upd = [text("updated", Wt("W-17", {"{time}": k.hms()}), k.CAPTION, k.TEXT_2)]
    if state == "stale":
        upd.append(text("stale word", WORD_STALE, k.CAPTION, k.STALE_TEXT))
    kids.append(hbox("snapshot line", upd, {"gap": k.INSET_SM}, h=16))
    tc = [k.Col("time", S("time"), 96, True), k.Col("bid", S("bid resting"), 120, True),
          k.Col("ask", S("ask resting"), 120, True), k.Col("pulled", S("pulled"), 216)]
    rows = []
    for j, c in enumerate(range(1, k.TRAIL_COLS, 2)):
        pulled = None
        if p == k.PULL_PRICE and c - 2 < k.PULL_COL <= c:
            pulled = Wt("W-16", {"18.0": k.qty1(k.PULL_SIZE)})
        rows.append(k.table_row(tc, {"time": k.hms((k.TRAIL_COLS - 1 - c) * k.TRAIL_STEP_S), "bid": k.qty(bid[c]),
                                     "ask": k.qty(ask[c]), "pulled": pulled}, f"row · {j + 1:02d}",
                                fill=k.RAISED if j % 2 else k.CANVAS))
    kids.append(vbox("CMP-049 Table", [k.header_row(tc), k.rows_block(rows)], None, w=sum(c.w for c in tc)))
    kids.append(name_marker("table name (CMP-049)", Wt("W-25", {"{price}": pr})))
    return _region(kids, pr)


def _region(kids: list[Node], pr: str) -> Node:
    return vbox("CMP-111 reveal region", kids,
                {"gap": k.STACK_SM, "pad": k.INSET_MD, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                 "strokeAlign": "inner", "radius": k.R_CARD}, w=600,
                note=f'role="region", name W-14 for {pr}; non-modal (PROPOSED)')


# --- CMP-113 legend
LEG_W = 440
# the legend's window: the reveal board's nine rows around the best bid (the same window feeds board 03)
LEG_PRICES = [k.BEST_BID + i * D for i in range(4, -5, -1)]


def colour_words(si: int) -> str:
    base = W("W-12", 0 if si < 2 else 1)
    if si in (1, 3):  # an inverted convention swaps the colour words (hand-off Table 1: "colour words swapped")
        a, b = re.match(r"bids (\w+), asks (\w+)", base).groups()  # type: ignore[union-attr]
        out = f"bids {b}, asks {a}"
        k.derive(f'"{out}": W-12 "{base}" with its colours swapped (hand-off L{k.HL("colour words swapped")})')
        return out
    return base


def legend(si: int = 0, *, scale: str = "log", mode: str = "adaptive", state: str = "default",
           forced: bool = False) -> Node:
    fg = k.TEXT_1
    bids, asks = set_tokens(si)
    outline = k.TEXT_1 if forced else None
    win = LEG_PRICES if mode == "adaptive" else LEG_PRICES[:5]

    def side_row(toks: list[str], words: str, nm: str) -> Node:
        sw = hbox("swatches", [swatch(t, outline=outline) for t in toks], {"gap": k.INSET_XS}, w=5 * 24 + 4 * 4,
                  h=16, note="aria-hidden; the words and anchors carry it")
        return hbox(nm, [sw, text("words", words, k.CAPTION, fg if forced else k.TEXT_1, w=LEG_W - 16 - 140 - 8)],
                    {"gap": k.INSET_SM, "align": "start"}, w=LEG_W - 16)

    kids = [side_row(bids, W("W-10"), "bid row"), side_row(asks, W("W-11"), "ask row"),
            text("colour words", colour_words(si), k.CAPTION, fg if forced else k.TEXT_2)]
    sc = W("W-13", 0 if scale == "log" else 1)
    md = W("W-13", 2 if mode == "adaptive" else 3)
    kids.append(text("scale and mode words", f"{sc} · {md}", k.CAPTION, fg if forced else k.TEXT_2, w=LEG_W - 16))
    if state == "nodata":
        nd = S("no data", "handoff")
        an = hbox("anchors", [text(f"anchor {i}", "—", k.NUM_SM, fg) for i in range(3)] +
                  [text("no data", nd, k.CAPTION, fg if forced else k.TEXT_2)], {"gap": k.INSET_LG}, h=16)
    else:
        _pane, vmax = heat_pane(win, si=si, scale=scale)
        a0, a1, a2 = k.anchors(vmax, scale)
        if mode == "locked":
            k.derive(f"locked anchors: the window's anchors when the lock was taken (its first five rows, largest "
                     f"{k.qty(vmax)})")
        ak: list[Node] = [text(f"anchor {i}", a, k.NUM_SM, fg) for i, a in enumerate((a0, a1, a2))]
        if state == "stale":
            ak.append(text("stale word", WORD_STALE, k.CAPTION, fg if forced else k.STALE_TEXT))
        an = hbox("anchors", ak, {"gap": k.INSET_LG}, h=16)
    kids.append(an)
    return vbox(f"CMP-113 HeatmapLegend · {k.PALETTE_SETS[si][0]}".replace("/", k.SLASH), kids,
                {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.APP if forced else k.RAISED,
                 "stroke": k.TEXT_1 if forced else None, "strokeWidth": k.HAIR if forced else None,
                 "strokeAlign": "inner" if forced else None, "radius": k.R_CARD}, w=LEG_W,
                note='role="group", name "Heatmap legend" plus the sentence; static, never announced (R-5)')


def legend_name(si: int, scale: str = "log", mode: str = "adaptive") -> str:
    return (f"{S('Heatmap legend', 'handoff')}: {W('W-10')}; {W('W-11')}; {colour_words(si)}; "
            f"{W('W-13', 0 if scale == 'log' else 1)}; {W('W-13', 2 if mode == 'adaptive' else 3)}")


# --- CMP-228 preview tile (`heatmap` kind)
TILE_PRICES = [k.MARK + i * D for i in range(5, -5, -1)]


def tile(si: int, *, state: str = "sample") -> tuple[Node, str]:
    if state in ("empty", "error"):
        words = S("Preview unavailable")
        body = box("tile body", [text("words", words, k.CAPTION, k.TEXT_2, x=12, y=52)], w=216, h=120)
        nm = words
    else:
        pane, _v = heat_pane(TILE_PRICES, si=si, rh=12, cw=18, pulled=False, name="sample cells")
        body = pane
        nm = Wt("W-18", {"{colour words}": colour_words(si), "{scale words}": W("W-13", 0),
                         "{mode words}": W("W-13", 2)})
    t = vbox(f"CMP-228 PreviewTile · heatmap · {state}", [body],
             {"pad": k.INSET_MD, "fill": k.SUNKEN, "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner",
              "radius": k.R_CARD}, w=216 + 24, h=round(k.est_height(body)) + 24, note=f'role="img", name: {nm}')
    return t, nm


# --- small compositions
def notice(*, forced: bool = False) -> Node:
    """The panel's one header notice (D02 §5.1, rendering 2a): the CMP-019 lock and the first missing leg's reason
    (W-20 while E21 holds); every gated control's aria-describedby points here (G-T2.5)."""
    return hbox("header notice (G-T2.5)", [lock(), text("reason", W("W-20"), k.CAPTION, k.TEXT_1 if forced else
                                                         k.TEXT_2)],
                {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.APP if forced else k.RAISED}, w=LADDER_W, h=k.ROW_H,
                note=f"the notice node; reason key {k.W20_REASON} (PROPOSED; vocabulary owner E09-D09 #192)")


def account_row(o: k.Own, *, first: bool, forced: bool = False) -> Node:
    words = Wt("W-5", {"Buy": side_word(o), "0.5": k.qty(o.qty), "limit": o.kind, "Acct B": o.acct})
    kids: list[Node] = [text("words", words, k.NUM_SM, k.TEXT_1)]
    if first:
        ahead = k.queue_ahead(o.price)
        w8 = Wt("W-8", {"12.4": k.qty1(ahead)})
        k.reading("W-8's '(estimated)' is drawn as CMP-227 `inline` beside 'ahead …' (the badge carries the word)")
        kids += [text("queue estimate", w8.replace(" (estimated)", ""), k.NUM_SM, k.TEXT_2), badge_estimated()]
    inner = hbox("account row content", kids, {"gap": k.INSET_SM, "padX": k.INSET_SM, "justify": "start"}, w=LADDER_W - 208, h=k.ROW_H)
    return hbox(f"account row · {o.acct} · {k.qty(o.qty)}", [rect("indent", 208, k.ROW_H), inner],
                {"fill": k.APP if forced else k.RAISED}, w=LADDER_W, h=k.ROW_H, note=f'role="row", name: {words}')


def expanded(p: Decimal, *, forced: bool = False, focus_first: bool = True) -> Node:
    """An aggregate's row expanded (Enter on its Your-orders cell): one row per order of the caller's accounts; focus
    on the first account row; the rows below reflow (D02:340)."""
    vmax = max((k.size_at(q) or Decimal(0) for q in around(p)), default=Decimal(1))
    rows: list[Node] = [header(forced=forced), ladder_row(p + D, vmax, forced=forced),
                        ladder_row(p, vmax, forced=forced, expanded=True)]
    for i, o in enumerate(k.own_at(p)):
        r = account_row(o, first=i == 0, forced=forced)
        rows.append(ring(r, color=k.ACTION_PRIMARY if forced else k.RING, gap_fill=k.APP if forced else None)
                    if i == 0 and focus_first else r)
    rows.append(ladder_row(p - D, vmax, forced=forced))
    return vbox("CMP-108 rows with CMP-230 expanded", rows, {"gap": k.STACK_XS}, w=LADDER_W + 8)


# --- board 01: CMP-108's variants (and the light twin at export)
B01 = {"Variant=BidSide, State=Default": (k.BEST_BID - 2 * D, {}),
       "Variant=AskSide, State=Default": (k.BEST_ASK + 2 * D, {}),
       "Variant=Best, State=Default": (k.BEST_BID, {}),
       "Variant=AtMark, State=Default": (k.MARK, {}),
       "Variant=OwnOrder, State=Default": (k.OWN_SINGLE, {}),
       "Variant=OwnOrder, State=Aggregate": (k.OWN_AGG, {}),
       "Variant=Position, State=Default": (k.POSITION_AT, {"position": True}),
       "Variant=Stale, State=Default": (k.BEST_BID - D, {"stale": True}),
       "Variant=Estimated, State=Default": (k.PULL_PRICE, {"estimated": True})}


def f_row(vid: str, nn: int) -> tuple[Node, list[str]]:
    p, fl = B01[vid.split(" / ", 1)[1]]
    win = window(around(p), stale=fl.get("stale", False), estimated_at=p if fl.get("estimated") else None,
                 position=fl.get("position", False))
    nm = row_label(p, **fl)
    kids = [marker(f"specimen: the middle row, {k.price(p)}"), win, name_marker('role="row" name (template, §4.1)', nm)]
    lines = [f"Name: {nm}"]
    if fl.get("estimated"):
        k.reading("'estimated' row: the pulled level (its last change is a pull, an estimate, M AD-6), shown with "
                  "CMP-227 `inline` in the Price cell")
        lines.append("Estimated: CMP-227 inline in the Price cell (the word, never colour alone)")
    if fl.get("stale"):
        lines.append("Stale: color.data-confidence.stale.surface with the word 'stale' (§4.1 tokens; §5.4 pairs)")
    return frame(vid, nn, kids), lines


# --- board 02: densities, focus-visible, the row menu with its T2 trade items
def f_density(vid: str, nn: int) -> tuple[Node, list[str]]:
    comf = vid.endswith("Density=Comfortable")
    h = k.ROW_H_COMFORTABLE if comf else k.ROW_H
    tok = k.ROW_COMFORTABLE if comf else k.ROW_COMPACT
    win = window(around(k.MARK, 3), h=h)
    k.reading("board 02's density frames extend Table 1's BidSide id with ', Density=…' (§0 draws the density axis; "
              "Table 1 names no density variant)")
    kids = [marker(f"row height {h} px: {tok} (a minimum that grows with the text scale, R-7)"), win]
    return frame(vid, nn, kids), [f"Row height {h} px = {tok} (hand-off L{k.HL('### Density')} density table)",
                                  "Seven rows around the mark: the spread's two empty rows read 'none' on both sides"]


def f_focus(vid: str, nn: int) -> tuple[Node, list[str]]:
    p = k.BEST_BID - 2 * D
    win = window(around(p), ring_at=p)
    kids = [marker("focus-visible: CMP-039 outside the row box, one tab stop, roving rows keyed by price"), win,
            name_marker('role="row" name', row_label(p))]
    return frame(vid, nn, kids), ["Ring: CMP-039 FocusRing (`15`:454), color.focus.ring + border.focus, outside the "
                                  "row box (C-1); kept whole on the first and last rows (scroll-padding)",
                                  "Keys: ↑/↓ rows, ←/→ cells, Enter the row menu, Delete cancel (never gated on the "
                                  "arm, R-4), Shift+Enter the reveal (PROPOSED, OQ-1), Esc back to the row"]


def f_menu(vid: str, nn: int) -> tuple[Node, list[str]]:
    p = k.BEST_BID - 2 * D
    win = window(around(p))
    mw = 312
    first = hbox("menu label (aria-labelledby): the notice's sentence", [lock(), text("reason", W("W-20"), k.CAPTION,
                                                                                         k.TEXT_2, w=mw - 44)],
                 {"gap": k.INSET_XS, "padX": k.INSET_SM, "align": "start"}, w=mw - 8)
    items = [t2_item(S(w_), w=mw - 16, focused=i == 0) for i, w_ in enumerate(("limit", "stop", "TP"))]
    k.copy_gap('"alert here", "copy price": the row menu\'s enabled items (D02 §5.2; `14`:1214)')
    en = [hbox(f"item · {w_}", [text("label", w_, k.BODY, k.TEXT_1)], {"padX": k.INSET_SM}, w=mw - 8, h=k.ROW_H)
          for w_ in ("alert here", "copy price")]
    menu = vbox("CMP-041 Menu (row menu)", [first, *items, *en],
                {"gap": k.STACK_XS, "pad": k.INSET_XS, "fill": k.OVERLAY, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                 "strokeAlign": "inner", "radius": k.R_CARD}, w=mw,
                note='role="menu"; trade items aria-disabled, arrow-reachable; focus on the first item')
    mh = round(k.est_height(menu))
    st = stage("row and its open menu", [dict(win, x=0, y=0), dict(menu, x=208, y=2 * k.ROW_H + 4)],
               LADDER_W, max(round(k.est_height(win)), 2 * k.ROW_H + 4 + mh))
    k.reading("the menu is drawn open under its row, over the rows below (a popover); its first line is the notice's "
              "sentence as the menu's label, so the reason stays visible while the menu covers the header (D02 §5.2)")
    return frame(vid, nn, [marker("Enter on the row: the row action menu (CMP-041)"), st]), [
        "T2 (R-3): limit, stop, TP in rendering 2a: CMP-019 lock + full label in color.text.tertiary on "
        "color.surface.raised with a color.border.default hairline; aria-disabled, in the arrow order; never "
        "opacity.disabled",
        f"Reason: {k.W20_REASON} W-20 (PROPOSED), linked to the panel's one header notice (G-T2.5); a press re-announces "
        "it once, polite (R-5)", "Cancel is not in this menu and is never gated on the arm (R-4)"]


# --- board 03: CMP-111's reveal
B03 = {"Palette=Standard, State=Open": (k.BEST_BID, "open"), "State=Empty": (k.MARK, "empty"),
       "State=Pulled": (k.PULL_PRICE, "pulled"), "State=Stale": (k.BEST_BID - D, "stale")}


def f_reveal(vid: str, nn: int) -> tuple[Node, list[str]]:
    p, st_ = B03[vid.split(" / ", 1)[1]]
    prices = [p + i * D for i in range(3, -4, -1)]
    pane, vmax = heat_pane(prices, head=k.ROW_H)
    win = window(prices, stale=st_ == "stale", ring_at=p)
    top = hbox("pane and ladder", [pane, win], {"gap": k.INSET_SM, "align": "start"},
               h=max(round(k.est_height(pane)), round(k.est_height(win))))
    back = marker(f"Esc anywhere in the region: focus returns to the opener row {k.price(p)} (else the rendered row at "
                  f"its price, else the nearest; never body)", w=LADDER_W)
    kids = [top, back, reveal(p, state=st_)]
    lines = [f"Opener: the focused ladder row {k.price(p)}, Shift+Enter (PROPOSED, OQ-1) or Enter on the pane's stop",
             "Region: non-modal (PROPOSED); Tab: heading → table → the ladder grid; nothing announced per update (R-5)"]
    if st_ == "pulled":
        lines.append(f"Pulled: the hatched mark at column {k.PULL_COL + 1} of {k.TRAIL_COLS} (no print at its price), "
                     f"named in the table by W-16 (M AD-6)")
    return frame(vid, nn, kids), lines


# --- board 04: CMP-113
B04 = {"Palette=Standard, Convention=Default": dict(si=0), "Palette=Standard, Convention=Inverted": dict(si=1),
       "Palette=Cvd, Convention=Default": dict(si=2), "Palette=Cvd, Convention=Inverted": dict(si=3),
       "Scale=Log": dict(si=0, pair="scale"), "Mode=Adaptive": dict(si=0, pair="mode"),
       "State=Stale": dict(si=0, state="stale"), "State=NoData": dict(si=0, state="nodata")}


def f_legend(vid: str, nn: int) -> tuple[Node, list[str]]:
    spec = B04[vid.split(" / ", 1)[1]]
    si, pair, state = spec["si"], spec.get("pair"), spec.get("state", "default")
    kids: list[Node] = []
    if pair == "scale":
        for sc, story in (("log", "LogScale"), ("linear", "LinearScale")):
            kids += [marker(f"story {story}"), legend(si, scale=sc)]
    elif pair == "mode":
        for md, story in (("adaptive", "Adaptive"), ("locked", "Locked")):
            kids += [marker(f"story {story}"), legend(si, mode=md)]
    else:
        kids.append(legend(si, state=state))
    kids.append(name_marker('role="group" name', legend_name(si), w=LEG_W))
    lines = [f"Set: {k.PALETTE_SETS[si][0]} (§5.1 L{k.L('| Set                                   | Bid stops') + 2 + si})",
             "Anchors: 0, the middle stop's edge and the window's largest size, as text with the unit (M AD-10)"]
    if pair:
        lines.append("Two stories in one Table 1 row: both specimens drawn, labelled by story name")
    return frame(vid, nn, kids), lines


# --- board 05: the ramps on the canvas, and the colour-vision distances
def f_ramps(vid: str, nn: int) -> tuple[Node, list[str]]:
    rows: list[Node] = []
    for si, (nm, b, a, fl) in enumerate(k.PALETTE_SETS):
        rows.append(hbox(f"set {si + 1}", [
            text("set name", nm, k.CAPTION, k.TEXT_1, w=232),
            hbox("bid stops", [swatch(t) for t in k.stops(b)], {"gap": k.INSET_XS}, w=136, h=16),
            hbox("ask stops", [swatch(t) for t in k.stops(a)], {"gap": k.INSET_XS}, w=136, h=16),
            swatch(fl), text("floor", "floor", k.CAPTION, k.TEXT_2)], {"gap": k.INSET_MD}, h=24))
    k.copy_gap('"floor", "bid stops", "ask stops": board labels for §5.1\'s columns (Bid stops, Ask stops, Floor)')
    head = hbox("set heads", [text("h0", "set", k.CAPTION, k.TEXT_3, w=232), text("h1", "bid stops", k.CAPTION,
                                                                                    k.TEXT_3, w=136),
                              text("h2", "ask stops", k.CAPTION, k.TEXT_3, w=136)], {"gap": k.INSET_MD}, h=16)
    k.copy_gap('"set": the board label of §5.1\'s first column')
    cols_ = [k.Col("token", "stop", 248), k.Col("dark", "dark", 96, True), k.Col("light", "light", 96, True),
             k.Col("hc", "high-contrast", 120, True), k.Col("floor", "floor", 72, True)]
    k.copy_gap('"stop", "dark", "light", "high-contrast": the ratio table\'s column labels (§5.2\'s theme names)')
    names = [t for p in (*k.STD, *k.CVD) for t in k.stops(p)]
    body = []
    for j, t in enumerate(names):
        r = {th: k.ratio(t, k.CANVAS, th) for th in ("dark", "light", "high-contrast")}
        body.append(k.table_row(cols_, {"token": t, "dark": f"{r['dark']:.2f}", "light": f"{r['light']:.2f}",
                                        "hc": f"{r['high-contrast']:.2f}", "floor": "3:1"}, f"row · {j + 1:02d}",
                                fill=k.RAISED if j % 2 else k.CANVAS))
    tbl = vbox("stop contrast on color.surface.canvas", [
        text("caption", f"Every stop on color.surface.canvas, computed from the shipped token values (§5.2 "
                        f"L{k.L('### 5.2 Contrast')}); 20 of 20 ≥ 3:1 in each theme", k.CAPTION, k.TEXT_2, w=616),
        k.header_row(cols_), k.rows_block(body)], {"gap": k.STACK_XS}, w=sum(c.w for c in cols_))
    lows = {th: (k.lowest(k.STD, th), k.lowest(k.CVD, th)) for th in ("dark", "light", "high-contrast")}
    k.derive("ratios: WCAG 2.x relative luminance of the token-sync.json values per theme (dark; light = dark + "
             "semantic-light; high-contrast = dark + semantic-hc), rounded half-up to 0.01; the lowest per palette "
             "equal §5.2's table: " + "; ".join(f"{th} {a[0]} {a[1]:.2f}, {b[0]} {b[1]:.2f}"
                                                 for th, (a, b) in lows.items()))
    kids = [marker("the four palette sets of §5.1: stops 1 → 5 left to right; the floor is never a stop (C-9)"),
            vbox("palette sets", [head, *rows], {"gap": k.STACK_SM}, w=720), tbl]
    return frame(vid, nn, kids), [
        "Swatches bind the stop tokens; under this board's dark export they show the dark values; the light and "
        "high-contrast columns are computed, not drawn (themes are file-wide)",
        "semantic-hc overrides no heatmap token, so the high-contrast column equals dark (§5.2)"]


def f_cvd(vid: str, nn: int) -> tuple[Node, list[str]]:
    a = k.L("| Theme         | Palette  | Deuteranopia")
    hdr = k._cells(k.SPEC_LINES[a - 1])
    widths = [120, 96, 112, 104, 104, 112, 152]
    cols_ = [k.Col(f"c{i}", k.plain(h), w, i >= 2) for i, (h, w) in enumerate(zip(hdr, widths))]
    rows = [{f"c{i}": k.plain(c) for i, c in enumerate(k._cells(k.SPEC_LINES[i - 1]))} for i in range(a + 2, a + 8)]
    tbl = k.spec_table("ΔE76 table", cols_, rows, cap=f"ΔE76 after simulation, floor 5.0 (§5.3 L{a}; "
                                                       f"docs/research/_tools/cvd_simulate.py)", w_=sum(widths))
    sim = marker("greyscale, deuteranopia and protanopia renders of board 04: docs/design/_tools/cvd_sim.py on its "
                 "export; tritanopia: the distances above only (the image tool has no tritanopia)", w=sum(widths))
    k.reading("board 05's 'greyscale and the three simulations of board 04' cannot be painted (cvsheet binds tokens, "
              "never simulated hexes): they are cvd_sim.py renders of board 04's export, and the drawn frame carries "
              "§5.3's computed table; a tritanopia render has no tool (spec gap)")
    k.NOTES.add("spec_gaps", "§0 board 05 asks for three simulations of board 04; cvd_sim.py renders greyscale, "
                             "deuteranopia and protanopia only: tritanopia is the §5.3 table's figures")
    return frame(vid, nn, [tbl, sim]), [
        "Reading (§5.3, heuristic): deuteranopia brings the standard bid / ask stops to 1.9 in dark and high "
        "contrast, so side is carried by the column, the letter and the words (R-2), and in the pane by position",
        "Exports: E21-D04-04-cmp-113-sets-scale-greyscale.png, -deuteranopia.png, -protanopia.png beside board 04"]


# --- board 06: CMP-230
B06 = {"Variant=Single, State=Working": k.OWN_SINGLE, "Variant=Single, State=Pending": k.OWN_PENDING,
       "Variant=Single, State=Amending": k.OWN_AMENDING, "Variant=Aggregate": k.OWN_AGG,
       "Variant=Aggregate, Sides=Mixed": k.OWN_MIXED, "Variant=Aggregate, State=Open": k.OWN_AGG,
       "Variant=Position": k.POSITION_AT, "No drag": k.OWN_SINGLE}


def f_own(vid: str, nn: int) -> tuple[Node, list[str]]:
    key = vid.split(" / ", 1)[1]
    p = B06[key]
    lines: list[str] = []
    if key == "Variant=Aggregate, State=Open":
        body = expanded(p)
        nm = "; ".join(Wt("W-5", {"Buy": side_word(o), "0.5": k.qty(o.qty), "limit": o.kind, "Acct B": o.acct})
                       for o in k.own_at(p))
        kids = [marker("Enter on the aggregate's Your-orders cell: one row per order; focus on the first account row"),
                body, name_marker("account row names (role=\"row\")", nm)]
        lines += ["Esc collapses and returns focus to the cell; the rows below reflow; only accounts in the caller's "
                  "accessible set, never another environment (§8)",
                  "Queue estimate: W-8 with CMP-227 inline on the first order's row (its field is G-3's)"]
    elif key == "No drag":
        win = window(around(p))
        kids = [notice(), win, marker("no drag: the marker is text, not draggable, with no control and no T2 state "
                                      "while E21 holds; the notice above carries why (W-20)")]
        lines += [f"Drag absent while E21 holds (§0 L{k.BOARDS[nn].line} 'no drag'; §4.4 "
                  f"L{k.L('- **States**: working, pending (W-6)')}; hand-off Table 1 L{k.DRAG_ABSENT_LINE}; D02:265): "
                  f"no handle, no control, no T2 state (R-3 table L{k.L('| CMP-230 drag ')})",
                  f"The panel's notice carries why: {k.W20_REASON} W-20, PROPOSED, vocabulary owner E09-D09 #192 §3.1",
                  "Delete still cancels the row's one own order: never gated on the arm (R-4; C-2.6)"]
    else:
        win = window(around(p), position=key == "Variant=Position")
        kids = [win, name_marker('role="row" name', row_label(p, position=key == "Variant=Position"))]
        if len(k.own_at(p)) > 1:
            lines.append(f"Aggregate cell name: {k.name_form(agg_words(p))} (' · ' read ', ', §4.8)")
    return frame(vid, nn, kids), lines


# --- board 07: CMP-227 and CMP-229 on the panel
def f_badge(vid: str, nn: int) -> tuple[Node, list[str]]:
    if "Host=Strip" in vid:
        k.copy_gap('"CMP-134 chip": a detector chip\'s words are E25\'s (CMP-134 content, out of scope): a neutral '
                   'placeholder beside CMP-227 inline')
        chip = hbox("CMP-134 chip (placeholder)", [text("words", "CMP-134 chip", k.CAPTION, k.TEXT_2),
                                                   badge_estimated(host="strip")],
                    {"gap": k.INSET_XS, "padX": k.INSET_SM, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                     "strokeAlign": "inner", "radius": k.R_PILL}, h=k.ROW_H)
        strip = hbox("detector strip", [chip], {"padX": k.INSET_SM, "fill": k.RAISED}, w=LADDER_W, h=32)
        o = k.own_at(k.OWN_AGG)[0]
        kids = [marker("inline: the detector strip's chips"), strip,
                marker("inline: the queue estimate in an expanded own-order row (W-8)"),
                account_row(o, first=True)]
        return frame(vid, nn, kids), ["Variants used: inline (here) and marker; section unused (A-23)",
                                      "The word '(estimated)' is in the name; never colour, icon or opacity alone"]
    prices = [k.PULL_PRICE + i * D for i in range(2, -3, -1)]
    pane, _v = heat_pane(prices)
    pw = k.TRAIL_COLS * CW
    x0, y0 = pw + 12, 2 * k.ROW_H + 4
    lead = rect("leader", pw + 12 - (k.PULL_COL + 1) * CW, 1, k.TEXT_2, x=(k.PULL_COL + 1) * CW, y=y0 + 8)
    mk = box("CMP-227 marker (hollow, dashed)", [dashed_box("outline", 20, 16, k.INFO),
                                                 icon("glyph (stand-in: info)", "info", k.INFO, k.ICON_SM, x=4, y=2)],
             w=20, h=16, x=x0, y=y0)
    k.fallback("icon-sm")
    lab = text("visible word", Wt("W-16", {"18.0": k.qty1(k.PULL_SIZE)}), k.CAPTION, k.TEXT_1, x=x0 + 26, y=y0)
    st = stage("pane with the pulled mark", [pane, lead, mk, lab], pw + 12 + 26 + round(k.text_w(lab["chars"], k.CAPTION))
               + 8, 5 * k.ROW_H)
    k.reading("CMP-227 `marker` beside the pulled mark carries its visible word in the same pane as a text label "
              "beside the mark (`15`:2935): W-16's words; drawn at the pane's right edge on the mark's row with a 1 px "
              "leader, so neither covers data ink")
    return frame(vid, nn, [marker("marker: the heatmap's pulled mark (M AD-6)"), st]), [
        "The hatch is pattern.hatch.estimated (D05E11 §7), cited, not re-made; the reveal names the level W-16"]


def f_arm(vid: str, nn: int) -> tuple[Node, list[str]]:
    acct, size = k.ACCOUNTS[0], k.qty(k.own_at(k.OWN_SINGLE)[0].qty)
    lbl = Wt("W-19", {"{account}": acct, "{size}": size, "{coin}": k.COIN})
    k.fallback("pill")
    pill = hbox("CMP-229 ArmToggle · LOCKED · T2 2a", [lock(), text("label", lbl, k.LABEL, k.TEXT_3)],
                {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                 "strokeAlign": "inner", "radius": k.R_PILL}, w=round(12 + 4 + k.text_w(lbl, k.LABEL) + 16 + 2),
                h=k.ROW_H, note='aria-pressed switch, aria-disabled="true", described by the header notice')
    reason_ = text("reason (aria-hidden here)", W("W-20"), k.CAPTION, k.TEXT_2)
    env = hbox("env badge (from the session)", [rect("dot", 8, 8, k.ENV_DEMO), text("words", S("DEMO"), k.LABEL,
                                                                                    k.TEXT_1)],
               {"gap": k.INSET_XS, "padX": k.INSET_SM, "stroke": k.ENV_DEMO, "strokeWidth": k.HAIR,
                "strokeAlign": "inner", "radius": k.R_PILL}, h=20)
    right = vbox("arm with its reason", [ring(pill), reason_], {"gap": k.STACK_XS})
    head = hbox("panel header (DEMO session)", [env, right], {"gap": k.INSET_LG, "padX": k.INSET_SM, "align": "start",
                                                              "fill": k.RAISED}, w=LADDER_W, h=56)
    kids = [head, notice(), marker("Enter / Space on the pill, or Ctrl+Shift+T: re-shows W-20, changes nothing")]
    k.reading("CMP-229 is drawn in a DEMO session only: LIVE is the same pill reading the session (R-6), not drawn, "
              "so no synthetic account appears under both environments (C-2.11)")
    return frame(vid, nn, kids), [
        "Read-only T2 LOCKED (R-3): full label W-19 in color.text.tertiary, W-20 under it, CMP-079 + CMP-019 lock, "
        "color.surface.raised + color.border.default; never opacity.disabled", "ARMED is E31's; cancel and close are "
        "never gated on the arm (R-4)", "DEMO comes from the session, never the data (R-6, C-2.11)"]


# --- board 08: CMP-228's heatmap kind
B08 = {"Kind=Heatmap, State=Sample": (0, "sample"), "Kind=Heatmap, Palette=Cvd": (2, "sample"),
       "Kind=Heatmap, Convention=Inv": (1, "sample"), "Kind=Heatmap, State=Empty": (0, "empty"),
       "Kind=Heatmap, State=Error": (0, "error")}


def f_tile(vid: str, nn: int) -> tuple[Node, list[str]]:
    si, st_ = B08[vid.split(" / ", 1)[1]]
    t, nm = tile(si, state=st_)
    kids = [t, name_marker('role="img" name', nm, w=360)]
    lines = ["Sample data only: the kit's seeded synthetic book (ten rows around the mark), never live or recorded "
             "data (A-24)", "Never a spinner: a recomputing tile keeps its last frame; placement is E21-D03's (BQ-12)"]
    if st_ != "sample":
        lines.insert(0, "Empty and error are both named 'Preview unavailable' (J21)")
    return frame(vid, nn, kids), lines


# --- board 09: high contrast and forced colours
def f_hc(vid: str, nn: int) -> tuple[Node, list[str]]:
    forced = vid.endswith("Forced colours")
    if forced:
        k.fallback("forced")
    cmp = vid[:7]
    if cmp == "CMP-108":
        p = k.OWN_SINGLE
        body: list[Node] = [window(around(p, 2), forced=forced, ring_at=p,
                                   ring_color=k.ACTION_PRIMARY if forced else k.RING),
                            window(around(k.BEST_BID - D), stale=True, forced=forced)]
        if forced:
            body.append(t2_item(S("limit"), w=200, forced=True))
        lines = ["Rows: a bid window with the focused row, then a stale window (the word carries it)"]
    elif cmp == "CMP-113":
        body = [legend(0, forced=forced)]
        lines = ["The legend on its solid backing; anchors and words as text"]
    else:
        body = [expanded(k.OWN_AGG, forced=forced), window(around(k.OWN_PENDING), forced=forced)]
        lines = ["The aggregate expanded and a pending order: words, never colour alone"]
    if forced:
        a = k.L("### 5.5 Forced colours (R32 R2)")
        lines.append(f"forced-colors: active per §5.5 (L{a}): bars hidden; side letters and words in CanvasText; stale "
                     "surface to Canvas; ring Highlight 2 px, 1 px Canvas gap (drawn as a stand-in token: Penpot has "
                     "no system colour); T2 label GrayText, ButtonText border")
    else:
        lines.append("High contrast: the same rows under the high-contrast set (semantic-hc), exported with it")
    return frame(vid, nn, body, fill=k.APP if forced else k.CANVAS), lines


# --- board 10: the token map and the redlines
def _tokens_of(heading: str) -> list[str]:
    a = k.L(heading)
    ln = next(k.SPEC_LINES[i - 1] for i in range(a, a + 8) if k.SPEC_LINES[i - 1].startswith("- **Tokens**"))
    return list(dict.fromkeys(t for t in re.findall(r"`([a-z][a-z0-9.-]+)`", ln) if "." in t and not
                              t.startswith(("font.mono", "color.surface.ownorder"))))


def f_tokens(vid: str, nn: int) -> tuple[Node, list[str]]:
    a = k.L("| Set                                   | Bid stops")
    hdr = k._cells(k.SPEC_LINES[a - 1])
    widths = [264, 216, 216, 152]
    cols_ = [k.Col(f"c{i}", k.plain(h), w) for i, (h, w) in enumerate(zip(hdr, widths))]
    rows = [{f"c{i}": k.plain(c) for i, c in enumerate(k._cells(k.SPEC_LINES[i - 1]))} for i in range(a + 2, a + 6)]
    sets = k.spec_table("palette sets (§5.1)", cols_, rows, cap=f"The palette sets (§5.1 L{a}): no new token",
                        w_=sum(widths))
    ec = [k.Col("entry", "entry", 160), k.Col("tokens", "tokens (the entry's Tokens field)", 688)]
    k.copy_gap('"entry", "tokens (the entry\'s Tokens field)": board labels for §4\'s Tokens bullets')
    ents = [("CMP-108", "### 4.1 CMP-108 DomLadderRow"), ("CMP-111", "### 4.2 CMP-111 HeatmapCell"),
            ("CMP-113", "### 4.3 CMP-113 HeatmapLegend"), ("CMP-230", "### 4.4 CMP-230 OwnOrderMarker")]
    body = [k.table_row(ec, {"entry": e, "tokens": ", ".join(_tokens_of(h))}, f"row · {j + 1:02d}",
                        fill=k.RAISED if j % 2 else k.CANVAS) for j, (e, h) in enumerate(ents)]
    tm = vbox("entries' tokens", [text("caption", "The entries' token fields (§4.1 … §4.4), as named at the base; "
                                                  "`font.mono` and `color.surface.ownorder` are not tokens (C-5)",
                                       k.CAPTION, k.TEXT_2, w=832), k.header_row(ec), k.rows_block(body)],
              {"gap": k.STACK_XS}, w=sum(c.w for c in ec))
    return frame(vid, nn, [sets, tm]), ["No new token (§5.1); ramp[] is the lookup's array view, not a token (A-11)",
                                        "pattern.hatch.estimated is D05E11's registry id, not a token (`26`:393)"]


def f_redlines(vid: str, nn: int) -> tuple[Node, list[str]]:
    vmax = max(k.size_at(q) or Decimal(0) for q in around(k.BEST_BID - 2 * D))
    p = k.BEST_BID - 2 * D
    r24 = ladder_row(p, vmax)
    r32 = ladder_row(p, vmax, h=k.ROW_H_COMFORTABLE)
    focus = ring(ladder_row(p - D, vmax))
    badge_pair = hbox("CMP-227 with a CMP-239 neighbour (4 px gap)", [badge_estimated(host="pair"),
                                                                      text("neighbour", WORD_STALE, k.CAPTION,
                                                                           k.STALE_TEXT)], {"gap": k.INSET_XS}, h=16)
    kids = [marker(f"compact row {k.ROW_H} px: {k.ROW_COMPACT}"), r24,
            marker(f"comfortable row {k.ROW_H_COMFORTABLE} px: {k.ROW_COMFORTABLE}"), r32,
            marker("size bar: from the cell's inner edge (bid: right, ask: left), length = size / the window's largest "
                   "size × the 80 px inner width; behind its number", w=LADDER_W),
            marker(f"ring: CMP-039, {k.FOCUS_W} = 2 px, 2 px outside the row box"), focus,
            marker(f"badge gap: {k.INSET_XS} = 4 px between CMP-227 and its neighbour (`15`:2939)"), badge_pair]
    k.reading("the bar's 'inner edge' read as the edge toward the other side's column: bids grow from the right "
              "edge, asks from the left (§4.1 names the inner edge without a side)")
    return frame(vid, nn, kids), ["Heights are minimums that grow with the text scale; never clipped (R-7)",
                                  "Cells: 8 px padding a side; numbers right-aligned, mono (type.num.sm)"]


BUILDERS: dict[int, list[Callable[[str, int], tuple[Node, list[str]]]]] = {
    1: [f_row] * 9, 2: [f_density, f_density, f_focus, f_menu], 3: [f_reveal] * 4, 4: [f_legend] * 8,
    5: [f_ramps, f_cvd], 6: [f_own] * 8, 7: [f_badge, f_badge, f_arm], 8: [f_tile] * 5, 9: [f_hc] * 6,
    10: [f_tokens, f_redlines]}


def build_board(nn: int) -> tuple[Path, Path, Path]:
    k.NOTES.reset()
    frames_, blocks = [], []
    for vid, fn in zip(k.FRAME_PLAN[nn], BUILDERS[nn], strict=True):
        node_, lines = fn(vid, nn)
        frames_.append(node_)
        blocks.append(k.frame_block(vid, nn, lines))
    tpl = (f"Row names: the template of §4.1 (L{k.TEMPLATE_LINE}), optional clauses only when true and in order; an "
           f"empty side reads \"none\"; the label never names an account (§8)")
    own = ("CMP-230 text first (R-2): the side word in color.buy.default / color.sell.default, status words in "
           "color.text.secondary, the glyph second; synthetic accounts of the DEMO session only (§8)")
    w1 = (f"W-1, the CMP-108 label example (§4.8 L{k.COPY['W-1'].line}, verbatim): \"{k.COPY['W-1'].strings[0]}\"; "
          f"the drawn rows' names are this template filled from the synthetic book")
    extra = {1: [tpl, w1], 2: [tpl], 6: [tpl, own], 9: [tpl]}.get(nn, [])
    return k.build(nn, frames_, blocks, board_lines=extra)
