"""Shared parts for the E21-D01 research boards (lo-fi, greyscale): the ladder, the heatmap trail, the pulled carrier,
the print marks, the legend, cards and markers. Every value comes from the kit's world; every string from the memo
(k.memo), or a kit label listed as a copy gap (k.ui), or a board marker."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import e21d01kit as k  # noqa: E402

Node = k.Node
ROW_H = 20  # one ladder row = one heatmap row (AD-2: rows align tick for tick)
CW = 16  # one heatmap column (100 ms) drawn 16 px wide
PRICE_W, SIZE_W, OWN_W = 120, 80, 136
RAMP_TOK = (None, k.HOVER, k.SELECTED, k.NEUTRAL, k.TEXT_2)  # bucket 0..4 (bucket 0 not drawn)
HEAD_H = 20


def marker(words: str, w: int | None = None, *, name: str | None = None) -> Node:
    k.fallback("marker")
    t = k.text("words", words, k.CAPTION, k.TEXT_1, w=(w - 16) if w else None)
    return k.hbox(name or f"dashed · marker · {words[:24]}", [t],
                  {"padX": k.INSET_XS, "stroke": k.TEXT_1, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                   "radius": k.R_CONTROL}, w=w, h=None if w else 20, note="board marker, not product UI")


def card(title: str, lines: Iterable[str], w: int, *, name: str | None = None, typo: str = k.CAPTION) -> Node:
    body = [k.text(f"line {i}", ln, typo, k.TEXT_1, w=w - 24) for i, ln in enumerate(lines, 1) if ln]
    return k.vbox(name or f"card · {title[:28]}", [k.text("title", title, k.LABEL, k.TEXT_2, w=w - 24), *body],
                  {"pad": k.INSET_MD, "gap": k.STACK_XS, "fill": k.RAISED, "radius": k.R_CARD, "stroke": k.BORDER,
                   "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=w)


def badge(words: str, *, strong: bool = False, name: str | None = None) -> Node:
    return k.hbox(name or f"badge · {words[:24]}", [k.text("words", words, k.LABEL, k.TEXT_1)],
                  {"padX": k.INSET_SM, "radius": k.R_BADGE, "stroke": k.BORDER_STRONG,
                   "strokeWidth": k.THICK if strong else k.HAIR, "strokeAlign": "inner"}, h=20)


def key_cap(words: str) -> Node:
    return k.hbox(f"key · {words}", [k.text("words", words, k.NUM_SM, k.TEXT_1)],
                  {"padX": k.INSET_XS, "radius": k.R_CONTROL, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                   "strokeAlign": "inner", "fill": k.SUNKEN}, h=20)


# --- the ladder (price | size | own orders): rows from the highest price down; bids below the mark, asks above
def ladder_row(j: int, off: int, size: Decimal, *, mark: bool, own: str | None, show_own: bool,
               pointer: bool = False) -> Node:
    p = k.price(k.px(off))
    cells = [k.cell("price", p + ("  mark" if mark else ""), PRICE_W, h=ROW_H, typo=k.NUM_SM),
             k.cell("size", k.size_fmt(size) if size > 0 else None, SIZE_W, h=ROW_H, typo=k.NUM_SM)]
    if show_own:
        glyph = None if not own else "arrow-up" if own.startswith("Buy") else "arrow-down"
        cells.append(k.cell("own", None, OWN_W, h=ROW_H, kids=[k.icon("glyph", glyph, k.TEXT_1),
                                                               k.text("words", own, k.CAPTION, k.TEXT_1)])
                     if own and glyph else k.cell("own", None, OWN_W, h=ROW_H))
    o: dict[str, Any] = {"fill": k.SELECTED if mark else k.RAISED if j % 2 == 0 else k.CANVAS}
    if mark:
        k.fallback("mark")
        o.update({"stroke": k.TEXT_1, "strokeWidth": k.FOCUS_W, "strokeAlign": "inner"})
    if pointer:
        o.update({"stroke": k.TEXT_1, "strokeWidth": k.HAIR, "strokeAlign": "inner"})
    return k.hbox(f"row · {j + 1:02d}", cells, o,
                  w=PRICE_W + SIZE_W + (OWN_W if show_own else 0), h=ROW_H)


def own_words(off: int) -> str | None:
    for o, side, qty, typ in k.OWN:
        if o == off:
            return k.ui(f"{side} {k.size_fmt(qty)} {typ}", "own-order cell words: side, size and type (AD-5)")
    return None


def agg(book: dict[int, Decimal], off: int, step: int) -> Decimal:
    """The size of one row: the sum of the ticks [off, off + step) (step 1 = one tick)."""
    return sum((book.get(o, Decimal(0)) for o in range(off, off + step)), Decimal(0))


def row_offs(centre: int, step: int = 1) -> list[int]:
    return [centre + (k.HALF - j) * step for j in range(2 * k.HALF + 1)]


def ladder(name: str, centre: int, book: dict[int, Decimal], mark: int, *, show_own: bool = False,
           pointer_row: int | None = None, own_head: str | None = None, step: int = 1, clear: bool = False) -> Node:
    """HALF rows above and below centre, step ticks a row; size from book (an offset -> size map; missing = empty);
    clear = rows without a fill (the 'behind' position: whatever is under them shows through)."""
    rows = []
    for j, off in enumerate(row_offs(centre, step)):
        r = ladder_row(j, off, agg(book, off, step), mark=off <= mark < off + step,
                       own=own_words(off) if show_own else None, show_own=show_own, pointer=pointer_row == j)
        if clear and not off <= mark < off + step:
            r = dict(r, o={x: y for x, y in r["o"].items() if x != "fill"})
        rows.append(r)
    w = PRICE_W + SIZE_W + (OWN_W if show_own else 0)
    head = [k.cell("th · price", k.ui("price", "ladder column heading"), PRICE_W, h=HEAD_H, color=k.TEXT_3),
            k.cell("th · size", k.ui("size", "ladder column heading; asks above the mark, bids below"), SIZE_W,
                   h=HEAD_H, color=k.TEXT_3)]
    if show_own:
        head.append(k.cell("th · own", own_head or k.ui("own orders", "C7 (Your orders / My orders) is open"),
                           OWN_W, h=HEAD_H, color=k.TEXT_3))
    k.fallback("side")
    return k.vbox(name, [k.hbox("header row", head, {} if clear else {"fill": k.RAISED}, w=w, h=HEAD_H),
                         k.vbox("rows", rows, {}, w=w, h=len(rows) * ROW_H)], {}, w=w, h=HEAD_H + len(rows) * ROW_H)


def rel_book(mark: int) -> dict[int, Decimal]:
    """The t0 book shape carried with the mark (centring strips): size at offset o = t0 size at o - mark."""
    return {o: k.SIZE0[o - mark][1] for o in range(mark - 3 * k.HALF, mark + 3 * k.HALF + 1) if (o - mark) in k.SIZE0}


# --- the heatmap trail
def heatmap(name: str, centre: int, *, carriers: bool = True, prints: bool = True, cols: int = k.TRAIL_COLS,
            behind: bool = False, step: int = 1) -> Node:
    """TRAIL_COLS columns (oldest left) x the ladder's rows (step ticks a row); run-length rects per ramp step; the
    pulled carrier (step 1 only) and the print marks when asked."""
    k.fallback("ramp")
    w, h = cols * CW, (2 * k.HALF + 1) * ROW_H
    kids: list[Node] = []
    for j, off in enumerate(row_offs(centre, step)):
        c = 0
        while c < cols:
            b = k.bucket(agg(k.TRAIL[c], off, step))
            e = c
            while e + 1 < cols and k.bucket(agg(k.TRAIL[e + 1], off, step)) == b:
                e += 1
            if b:
                kids.append(k.rect(f"liquidity · {k.price(k.px(off))} · c{c:02d}-{e:02d}", (e - c + 1) * CW, ROW_H - 4,
                                   RAMP_TOK[b], x=c * CW, y=j * ROW_H + 2))
            c = e + 1
        if carriers and step == 1 and off == k.PULLED_OFF:
            gone = next(c_ for c_ in range(cols) if k.TRAIL[c_][off] == 0)
            kids.append(pulled_carrier(f"{k.price(k.px(off))}", (cols - gone) * CW, ROW_H - 4, x=gone * CW,
                                       y=j * ROW_H + 2))
    if prints:
        offs = row_offs(centre, step)
        for c, off, _q in k.PRINTS:
            j = next((i for i, o in enumerate(offs) if o <= off < o + step), None)
            if j is not None and c < cols:
                kids.append(k.ellipse(f"print · c{c:02d} · {k.price(k.px(off))}", 8, 8,
                                      {"fill": k.TEXT_1, "stroke": k.APP, "strokeWidth": k.HAIR}, x=c * CW + 4,
                                      y=j * ROW_H + 6))
    return k.box(name, unique_kids(kids), {"fill": k.SUNKEN, "clip": True}, w=w, h=h,
                 note="heatmap trail excerpt (lo-fi)" + (" drawn under the ladder (the recorded other position)"
                                                         if behind else ""))


def unique_kids(kids: list[Node]) -> list[Node]:
    return k.unique_names(kids)


def pulled_carrier(label: str, w: int, h: int, **kw: Any) -> Node:
    """The pulled mark: a hollow dashed outline with hatch rules (the pattern word: hollow, dashed or hatched =
    estimated or absent)."""
    k.fallback("pattern")
    lines = [k.rect(f"hatch line · {i + 1}", int(h * 1.5), 1, k.TEXT_2, x=i * 8 - h // 2, y=h // 2)
             for i in range(max(1, (w + h) // 8))]
    return k.box(f"dashed · pulled carrier · {label}", lines, {"stroke": k.TEXT_1, "strokeWidth": k.HAIR,
                                                              "strokeAlign": "inner", "clip": True}, w=w, h=h, **kw)


def time_axis(cols: int = k.TRAIL_COLS) -> Node:
    ticks = [0, cols // 2 - 1, cols - 1]
    kids = [k.text(f"t · {c:02d}", k.ms_label(c), k.CAPTION, k.AXIS, x=min(c * CW, cols * CW - 40), y=2)
            for c in ticks]
    k.derive(f"time axis: {cols} columns × {k.COL_MS} ms = {cols * k.COL_MS / 1000:.1f} s drawn of the "
             f"{k.TRAIL_S} s live trail; labels at columns {', '.join(str(c) for c in ticks)}")
    return k.box("time axis", kids, {}, w=cols * CW, h=18)


def heat_region(name: str, centre: int, **kw: Any) -> Node:  # noqa: D401
    """Header spacer (aligns with the ladder header) + the heatmap + its time axis."""
    w = k.TRAIL_COLS * CW
    return k.vbox(name, [k.hbox("header row", [k.cell("th · trail", k.memo("heatmap (time ->)"), w, h=HEAD_H,
                                                      color=k.TEXT_3)], {"fill": k.RAISED}, w=w, h=HEAD_H),
                         heatmap("heatmap", centre, **kw), time_axis()], {}, w=w)


def legend_swatches() -> Node:
    k.fallback("ramp")
    items = []
    for i in range(1, 5):
        lo = k.RAMP[i - 1]
        hi = k.RAMP[i] if i < 4 else None
        words = f"{k.anchor(lo)}–{k.anchor(hi)} BTC" if hi else f"≥ {k.anchor(lo)} BTC"
        items.append(k.hbox(f"step {i}", [k.rect("swatch", 24, 12, RAMP_TOK[i], {"stroke": k.BORDER,
                                                                                  "strokeWidth": k.HAIR}),
                                          k.text("anchor", words, k.NUM_SM, k.TEXT_1)], {"gap": k.INSET_XS}, h=16))
    return k.hbox("swatches", items, {"gap": k.INSET_LG}, h=16)


def run(nn: int, built: tuple[list[Node], list[tuple[str, list[str]]]], cols: int, *,
        board_lines: Iterable[str] = (), notes: dict[str, Iterable[str]] | None = None) -> None:
    p, md, packed = k.build(nn, built[0], built[1], cols, board_lines=board_lines, notes=notes)
    rc, msg = k.validate(p)
    print(f"{p.name}: {msg.splitlines()[-1]} (exit {rc}); md {md.name}; packed {packed.name}")
