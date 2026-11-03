"""Research-board parts shared by the generators (greyscale): cards, chips, markers, the menu and radio group, and the
lo-fi profile pane. Every value comes from the kit's world; every string from the memo, `05`, or a kit label listed as
a copy gap (k.ui)."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import e19d01kit as k  # noqa: E402

Node = k.Node
FW = 1440  # a text frame (kit choice)
IW = FW - 2 * k.FRAME_PAD
CTRL_H = 24  # compact row / field height (`16` §1.3: 24 px)


def card(name: str, kids: list[Node | None], w: int, *, strong: bool = False) -> Node:
    return k.vbox(name, kids, {"pad": k.INSET_MD, "gap": k.STACK_SM, "fill": k.RAISED, "radius": k.R_CARD,
                               "stroke": k.BORDER_STRONG if strong else k.BORDER, "strokeWidth": k.HAIR,
                               "strokeAlign": "inner"}, w=w)


def para(name: str, chars: str, w: int, typo: str = k.BODY, color: str = k.TEXT_1) -> Node:
    return k.text(name, chars, typo, color, w=w)


def title(chars: str, w: int) -> Node:
    return k.text("title", chars, k.HEADING_MD, k.TEXT_1, w=w)


def badge(words: str, *, name: str | None = None, strong: bool = False) -> Node:
    return k.hbox(name or f"badge · {words[:24]}", [k.text("words", words, k.LABEL, k.TEXT_1)],
                  {"padX": k.INSET_SM, "radius": k.R_BADGE, "stroke": k.BORDER_STRONG,
                   "strokeWidth": k.THICK if strong else k.HAIR, "strokeAlign": "inner"}, h=20)


def marker(words: str, w: int | None = None, *, name: str | None = None) -> Node:
    k.fallback("marker")
    t = k.text("words", words, k.CAPTION, k.TEXT_1, w=(w - 16) if w else None)
    return k.hbox(name or f"dashed · marker · {words[:24]}", [t],
                  {"padX": k.INSET_XS, "stroke": k.TEXT_1, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                   "radius": k.R_CONTROL}, w=w, h=None if w else 20, note="board marker, not product UI")


def hidden(label: str, chars: str, w: int) -> Node:
    """A string a screen reader hears, drawn for the board in a dashed outline (not on screen)."""
    k.fallback("hidden")
    return k.vbox(f"dashed · {label}", [k.text("label", label, k.CAPTION, k.TEXT_3, w=w - 16),
                                        k.text("words", chars, k.CAPTION, k.TEXT_1, w=w - 16)],
                  {"pad": k.INSET_SM, "gap": k.STACK_XS, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                   "strokeAlign": "inner", "radius": k.R_CONTROL}, w=w, note="board marker: accessible text")


def chip_partial(n: int, m: int) -> Node:
    """CMP-011 Tag / Chip variant info with E16-D05's ruled words (memo §6.5)."""
    k.fallback("chip")
    words = k.memo_tpl("Partial: {n} of {m} requested days recorded", **{"{n}": str(n), "{m}": str(m)})
    return k.hbox("CMP-011 chip · info · partial", [k.icon("glyph", "info", k.TEXT_1, k.ICON),
                                                     k.text("words", words, k.CAPTION, k.TEXT_1)],
                  {"padX": k.INSET_SM, "gap": k.INSET_XS, "radius": k.R_BADGE, "stroke": k.BORDER,
                   "strokeWidth": k.HAIR, "strokeAlign": "inner", "fill": k.RAISED}, h=20,
                  note="CMP-011 variant info (E16-D05 :246 words, via memo §6.5)")


def est_badge() -> Node:
    """CMP-227 EstimatedBadge at section grade: the visible word and the methodology words (memo §6.4, PD-4)."""
    k.fallback("chip")
    return k.hbox("CMP-227 estimated badge · section", [
        k.text("word", k.memo("(estimated)"), k.LABEL, k.TEXT_1),
        k.text("methodology", k.memo("approximated from bars"), k.CAPTION, k.TEXT_2)],
        {"padX": k.INSET_SM, "gap": k.INSET_SM, "radius": k.R_BADGE, "stroke": k.BORDER_STRONG,
         "strokeWidth": k.THICK, "strokeAlign": "inner", "fill": k.RAISED}, h=24,
        note="CMP-227 variant section; detector bar_approximation (PROPOSED, memo §6.4)")


def menu_button(word: str, *, open_: bool = False) -> Node:
    return k.hbox(f"menu button · {word}", [k.text("value", word, k.BODY_STRONG, k.TEXT_1),
                                            k.icon("chevron", "chevron-down", k.TEXT_2, k.ICON)],
                  {"padX": k.INSET_SM, "gap": k.INSET_XS, "radius": k.R_CONTROL, "fill": k.SUNKEN,
                   "stroke": k.BORDER_STRONG if open_ else k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"},
                  h=CTRL_H, note="menu button showing the current mode word (PD-7)")


def menu(items: list[tuple[str, str]], current: str, w: int) -> Node:
    rows = [k.hbox(f"item · {word}", [k.icon("check", "check", k.TEXT_1, k.ICON) if word == current else
                                      k.rect("no check", 12, 12, None),
                                      k.text("word", word, k.BODY, k.TEXT_1, w=120),
                                      k.text("kind", kind, k.CAPTION, k.TEXT_3, w=w - 172)],
                   {"padX": k.INSET_SM, "gap": k.INSET_SM, "fill": k.SELECTED if word == current else k.OVERLAY},
                   w=w, h=CTRL_H) for word, kind in items]
    return k.vbox("menu · open", rows, {"fill": k.OVERLAY, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                                        "strokeAlign": "inner", "radius": k.R_CARD, "padY": k.INSET_XS}, w=w,
                  note="the open mode menu (lo-fi)")


def radio_group(label: str, items: list[str], current: str, w: int) -> Node:
    rows = [k.hbox(f"radio · {word}", [k.ellipse("ring", 14, 14, {"stroke": k.TEXT_1, "strokeWidth": k.HAIR}),
                                       k.ellipse("dot", 6, 6, {"fill": k.TEXT_1}, abs=True, x=4, y=9)
                                       if word == current else None,
                                       k.text("word", word, k.BODY, k.TEXT_1)], {"gap": k.INSET_SM}, w=w, h=CTRL_H)
            for word in items]
    return k.vbox(f"CMP-006 radio group · {label}", [k.text("legend", label, k.LABEL, k.TEXT_2), *rows],
                  {"gap": k.STACK_XS}, w=w, note="CMP-006 RadioGroup (lo-fi), SCR-039")


def table(name: str, cols: list[tuple[str, str, int]], rows: list[dict[str, Any]], *, cap: str | None = None,
          row_h: int = 24, selected: Iterable[int] = ()) -> Node:
    return k.grid_table(name, [k.Col(a, b, c) for a, b, c in cols], rows, cap=cap, row_h=row_h, selected=selected)


# --- the lo-fi profile pane (a non-flex board; children placed by x / y from the derived rows)
BAR_W = 220
PAD = 12


def ib_range(pr: k.Profile) -> tuple[Decimal, Decimal]:
    rec = [p for p in k.PERIODS if pr.first <= p.start < pr.last and not p.approximated][:k.IB_PERIODS]
    return min(p.lo for p in rec) * k.TICK, max(p.hi for p in rec) * k.TICK


def pane_rows(pr: k.Profile, npocs: Iterable[Decimal] = ()) -> tuple[int, int]:
    rs = [*pr.rows, *(int(p / (k.TICK * pr.row_ticks)) for p in npocs)]
    return min(rs), max(rs)


def profile_pane(pr: k.Profile, *, row_px: int = 10, tpo: bool = False, nodes_on: bool = False,
                 npocs: Iterable[tuple[str, Decimal]] = (), hatch: bool = False, delta: bool = False,
                 name: str = "profile pane") -> Node:
    k.fallback("profile")
    npocs = list(npocs)
    lo_r, hi_r = pane_rows(pr, [p for _l, p in npocs])
    top = PAD

    def y(r: int) -> int:
        return top + (hi_r - r) * row_px

    kids: list[Node] = []
    x = PAD
    if tpo:
        k.fallback("tpo")
        k.fallback("glyph")
        mx = max(pr.tpo.values())
        if pr.ib:
            ia, ib = pr.ib
            kids.append(k.rect("IB bar", 3, (ib - ia + 1) * row_px, k.TEXT_1, x=x, y=y(ib)))
        for r in k.single_prints(pr):
            kids.append(k.rect(f"single print · {k.row_price(pr, r)}", 2, row_px - 2, k.TEXT_1, x=x + 8, y=y(r) + 1))
        for r, n in sorted(pr.tpo.items()):
            kids.append(k.rect(f"tpo · {k.row_price(pr, r)}", 4 * n, row_px - 2, k.TEXT_2, x=x + 16, y=y(r) + 1))
        x += 16 + 4 * mx + 16
    if delta:
        dw = 96
        mxd = max(abs(v) for v in pr.delta.values()) or 1
        z = x + dw // 2
        kids.append(k.rect("delta zero rule", 1, (hi_r - lo_r + 1) * row_px, k.BORDER_STRONG, x=z, y=top))
        for r, v in sorted(pr.delta.items()):
            bw = max(round(abs(v) / mxd * (dw // 2 - 4)), 1)
            kids.append(k.rect(f"delta · {k.row_price(pr, r)}", bw, row_px - 2, k.TEXT_2, x=z + 1 if v > 0 else z - bw,
                               y=y(r) + 1))
        x += dw + 16
    xh = x
    top_v = max(pr.vol.values())
    for r in pr.rows:
        v = pr.vol.get(r, 0)
        if not v:
            continue
        bw = max(round(v / top_v * BAR_W), 1)
        if hatch and pr.approx.get(r):
            k.fallback("hatch")
            kids.append(k.rect(f"row · {k.row_price(pr, r)} · estimated", bw, row_px - 2, None,
                               {"stroke": k.TEXT_2, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, x=xh, y=y(r) + 1))
            if bw > 6 and row_px > 6:
                kids.append(k.rect(f"dashed · hatch · {k.row_price(pr, r)}", bw - 4, row_px - 6, None,
                                   {"stroke": k.TEXT_2, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, x=xh + 2,
                                   y=y(r) + 3))
        else:
            kids.append(k.rect(f"row · {k.row_price(pr, r)}", bw, row_px - 2, k.TEXT_3, x=xh, y=y(r) + 1))
    # POC rails (E18-D02 D6): solid, full width, on the row's top and bottom edges
    kids += [k.rect("POC rail top", BAR_W, 1, k.TEXT_1, x=xh, y=y(pr.poc)),
             k.rect("POC rail bottom", BAR_W, 1, k.TEXT_1, x=xh, y=y(pr.poc) + row_px - 1)]
    if nodes_on:
        k.fallback("glyph")
        hvn, lvn = k.nodes(pr)
        kids.append(k.icon("HVN glyph", "chevron-right", k.TEXT_1, k.ICON,
                           x=xh + round(pr.vol[hvn] / top_v * BAR_W) + 2, y=y(hvn) + row_px // 2 - 8))
        kids.append(k.ellipse("LVN glyph", 6, 6, {"fill": k.TEXT_1}, x=xh + round(pr.vol[lvn] / top_v * BAR_W) + 4,
                              y=y(lvn) + row_px // 2 - 3))
    # the value-area bracket: closed (end caps) when final, open-ended (no end cap) while developing (PD-1)
    bx = xh + BAR_W + 24
    va_lo, va_hi = pr.va
    kids.append(k.rect("VA bracket", 2, (va_hi - va_lo + 1) * row_px, k.TEXT_1, x=bx, y=y(va_hi)))
    if pr.complete:
        kids += [k.rect("VA bracket cap top", 8, 2, k.TEXT_1, x=bx - 6, y=y(va_hi)),
                 k.rect("VA bracket cap bottom", 8, 2, k.TEXT_1, x=bx - 6, y=y(va_lo) + row_px - 2)]
    lx = bx + 16
    poc_word = k.memo_tpl("POC 62,974.0", **{"62,974.0": k.row_price(pr, pr.poc)})
    labels = [("VAH label", f"VAH {k.row_price(pr, va_hi)}", k.LABEL, y(va_hi) - 6),
              ("POC label", poc_word, k.BODY_STRONG, y(pr.poc) + row_px // 2 - 9),
              ("VAL label", f"VAL {k.row_price(pr, va_lo)}", k.LABEL, y(va_lo) + row_px - 8)]
    kids += [k.rect("VAH tick", 6, 2, k.TEXT_1, x=lx, y=y(va_hi)),
             k.rect("VAL tick", 6, 2, k.TEXT_1, x=lx, y=y(va_lo) + row_px - 2)]
    for lab, p in npocs:
        r = int(p / (k.TICK * pr.row_ticks))
        kids.append(k.rect(f"nPOC ray · {lab}", lx - PAD, 1, k.TEXT_1, x=PAD, y=y(r) + row_px // 2))
        labels.append((f"nPOC label · {lab}", f"nPOC {lab}", k.LABEL, y(r) + row_px // 2 - 7))
    labels.sort(key=lambda t: t[3])
    last = -100
    for nm, words, typo, ly in labels:  # keep 18 px between label tops (a label moved keeps its tick at the row)
        ly = max(ly, last + 18)
        kids.append(k.text(nm, words, typo, k.TEXT_1, x=lx + 10, y=ly))
        last = ly
    h = top + (hi_r - lo_r + 1) * row_px + PAD
    w = lx + 10 + 132
    return k.box(name, layers(kids, w, h), {"fill": k.SUNKEN, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                            "strokeAlign": "inner", "clip": True}, w=w, h=h,
                 note=f"{pr.label}: {len(pr.rows)} rows of {pr.row_ticks} ticks, {row_px} px each")


def layers(kids: list[Node], w: int, h: int, per: int = 48) -> list[Node]:
    """Absolute marks grouped into transparent full-size layers of <= per marks, so the packer sends a few sections
    instead of one per mark (a non-flex board's overflow kids are each sent alone)."""
    if len(kids) <= per:
        return kids
    return [k.box(f"layer · {i // per + 1:02d}", kids[i:i + per], {}, w=w, h=h, x=0, y=0)
            for i in range(0, len(kids), per)]


def legend(entries: list[tuple[str, Node | None]], w: int) -> Node:
    items = [k.hbox(f"entry · {words[:28]}", [g, k.text("words", words, k.CAPTION, k.TEXT_1)] if g else
                    [k.text("words", words, k.CAPTION, k.TEXT_1)], {"gap": k.INSET_XS}, h=16) for words, g in entries]
    return k.hbox("CMP-199 legend", items, {"gap": k.INSET_MD, "wrap": "wrap", "align": "center"}, w=w,
                  note="CMP-199 ChartLegend (lo-fi)")


def glyph(kind: str) -> Node:
    if kind == "bracket":
        return k.rect("glyph · bracket", 2, 12, k.TEXT_1)
    if kind == "HVN":
        return k.icon("glyph · HVN", "chevron-right", k.TEXT_1, k.ICON)
    if kind == "LVN":
        return k.ellipse("glyph · LVN", 6, 6, {"fill": k.TEXT_1})
    if kind == "single":
        return k.rect("glyph · single print", 2, 10, k.TEXT_1)
    if kind == "ray":
        return k.rect("glyph · ray", 16, 1, k.TEXT_1)
    if kind == "IB":
        return k.rect("glyph · IB", 3, 12, k.TEXT_1)
    if kind == "rail":
        return k.rect("glyph · rail", 16, 2, k.TEXT_1)
    if kind == "hatch":
        return k.box("glyph · hatch", [k.rect("dashed · inner", 20, 8, None, {"stroke": k.TEXT_2, "strokeWidth": k.HAIR,
                                                                          "strokeAlign": "inner"}, x=2, y=2)],
                     {"stroke": k.TEXT_2, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=24, h=12)
    raise KeyError(kind)


def panel(head: list[Node | None], body: list[Node | None], w: int, *, name: str = "SCR-038 profile panel") -> Node:
    hdr = k.hbox("panel header", head, {"gap": k.INSET_SM, "padX": k.INSET_SM, "fill": k.RAISED}, w=w, h=CTRL_H + 8)
    return k.vbox(name, [hdr, *body], {"gap": k.STACK_SM, "padB": k.INSET_SM, "fill": k.CANVAS, "stroke": k.BORDER,
                                       "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=w)


def run(nn: int, built: tuple[list[Node], list[tuple[str, list[str]]]], cols: int, *,
        board_lines: Iterable[str] = (), notes: dict[str, Iterable[str]] | None = None) -> None:
    p, md, packed = k.build(nn, built[0], built[1], cols, board_lines=board_lines, notes=notes)
    rc, msg = k.validate(p)
    print(f"{p.name}: {msg.splitlines()[-1]} (exit {rc}); md {md.name}; packed {packed.name}")
