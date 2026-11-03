"""Wireframe parts shared by the generators (lo-fi, greyscale): page chrome, controls, the journal table, dialogs,
notices, skeletons and the lo-fi charts. Every value comes from the kit's world; every string from the memo, `14` or
a kit label listed as a copy gap (k.ui)."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import e41d01kit as k  # noqa: E402

Node = k.Node
SCREEN_W = 1200  # a SCR-093 / SCR-095 / SCR-094 frame (kit choice: the 1120 px table plus the page inset)
PAGE_W = SCREEN_W - 2 * k.FRAME_PAD
DIALOG_W = 560
CTRL_H = 28


def ring(n: Node) -> Node:
    """The focused state: a 2 px color.text.primary outline (greyscale wireframe ring)."""
    k.fallback("focus")
    o = dict(n.get("o") or {})
    o.update({"stroke": k.TEXT_1, "strokeWidth": k.FOCUS_W, "strokeAlign": "outer"})
    return dict(n, o=o, name=f"{n['name']} · focused")


def btn(label: str, *, primary: bool = False, t2: bool = False, w: int | None = None, glyph: str | None = None) -> Node:
    if primary:
        k.fallback("primary")
    kids: list[Node | None] = [k.icon("glyph", glyph, k.TEXT_2) if glyph else None,
                               k.text("label", label, k.BODY_STRONG, k.TEXT_2 if t2 else k.TEXT_1),
                               k.icon("lock", "locked", k.TEXT_2, k.ICON_SM) if t2 else None]
    o = {"padX": k.BUTTON_PADX, "gap": k.INSET_XS, "radius": k.R_CONTROL, "stroke": k.BORDER if t2 else k.BORDER_STRONG,
         "strokeWidth": k.THICK if primary else k.HAIR, "strokeAlign": "inner", "justify": "center"}
    if t2:
        k.fallback("t2stroke")
    if primary:
        o["fill"] = k.SELECTED
    return k.hbox(("dashed · " if t2 else "") + f"button · {label}" + (" · T2" if t2 else ""), kids, o, w=w, h=CTRL_H,
                  note="CMP-003 Button (lo-fi)" + ("; T2: aria-disabled, stays in the Tab order" if t2 else ""))


def link(label: str) -> Node:
    tw = round(k.text_w(label, k.BODY))
    return k.vbox(f"link · {label}", [k.text("label", label, k.BODY, k.TEXT_1), k.rect("underline", tw, 1, k.TEXT_1)],
                  {}, w=tw, h=20, note="CMP-021 Link (lo-fi: underlined, no link hue)")


def select(label: str | None, value: str, w: int, *, open_: bool = False) -> Node:
    box_ = k.hbox("control", [k.text("value", value, k.BODY, k.TEXT_1, w=w - 44),
                              k.icon("chevron", "chevron-down", k.TEXT_2)],
                  {"padX": k.INSET_SM, "gap": k.INSET_XS, "stroke": k.BORDER_STRONG if open_ else k.BORDER,
                   "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL, "fill": k.SUNKEN},
                  w=w, h=CTRL_H)
    if not label:
        return dict(box_, name=f"select · {value}")
    return k.vbox(f"select · {label}", [k.text("label", label, k.CAPTION, k.TEXT_2), box_], {"gap": k.STACK_XS}, w=w)


def textfield(label: str, value: str, w: int, *, counter: str | None = None, error: str | None = None,
              focused: bool = False, t2: bool = False) -> Node:
    if t2:
        k.fallback("t2stroke")
    kids0: list[Node | None] = [k.text("value", value, k.BODY, k.TEXT_2 if t2 else k.TEXT_1, w=w - 44 if t2 else w - 24),
                                k.icon("lock", "locked", k.TEXT_2, k.ICON_SM) if t2 else None]
    f = k.hbox("dashed · control" if t2 else "control", kids0,
               {"padX": k.INSET_SM, "gap": k.INSET_XS, "stroke": k.BORDER if t2 else k.BORDER_STRONG, "strokeWidth": k.THICK if error else k.HAIR,
                "strokeAlign": "inner", "radius": k.R_CONTROL, "fill": k.SUNKEN}, w=w, h=CTRL_H)
    kids: list[Node | None] = [k.text("label", label, k.CAPTION, k.TEXT_2), ring(f) if focused else f,
                               k.text("counter", counter, k.CAPTION, k.TEXT_3) if counter else None,
                               k.hbox("error", [k.icon("glyph", "danger", k.TEXT_1, k.ICON_SM),
                                                k.text("words", error, k.CAPTION, k.TEXT_1, w=w - 20)],
                                      {"gap": k.INSET_XS, "align": "start"}, w=w) if error else None]
    return k.vbox(f"field · {label}", kids, {"gap": k.STACK_XS}, w=w, note="CMP-058 InlineEdit / text field (lo-fi)")


def badge(words: str, *, name: str | None = None, strong: bool = False) -> Node:
    return k.hbox(name or f"badge · {words}", [k.text("words", words, k.LABEL, k.TEXT_1)],
                  {"padX": k.INSET_SM, "radius": k.R_BADGE, "stroke": k.BORDER_STRONG,
                   "strokeWidth": k.THICK if strong else k.HAIR, "strokeAlign": "inner"}, h=20)


def scope(env: str) -> Node:
    """WD-1: one scope label (LIVE or DEMO) over every total; words, not the env hue."""
    k.fallback("scope")
    words = k.deck("scope.live" if env == "LIVE" else "scope.demo")
    return k.hbox(f"scope label · {env}", [badge(env, strong=True), k.text("words", words, k.BODY, k.TEXT_1)],
                  {"gap": k.INSET_SM}, h=24, note="WD-1 scope label (persistent on SCR-093..095)")


def chip(name: str, *, auto: bool = False, removable: bool = False, t2: bool = False) -> Node:
    kids: list[Node | None] = [k.text("name", name, k.LABEL, k.TEXT_1),
                               k.text("auto", "auto", k.CAPTION, k.TEXT_2) if auto else None,
                               k.icon("remove", "close", k.TEXT_2, k.ICON_SM) if removable and not t2 else None,
                               k.icon("lock", "locked", k.TEXT_2, k.ICON_SM) if t2 else None]
    if t2:
        k.fallback("t2stroke")
    return k.hbox(("dashed · " if t2 else "") + f"tag · {name}", kids, {"padX": k.INSET_XS, "gap": k.INSET_XS, "radius": k.R_CONTROL,
                                         "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                                         "fill": k.HOVER}, h=20, note="CMP-169 TagEditor chip (lo-fi)")


def chips(tags: Iterable[tuple[str, bool]], w: int, **kw: Any) -> list[Node]:
    return [chip(n, auto=a, **kw) for n, a in tags]


def hidden(label: str, chars: str, w: int) -> Node:
    """A string a screen reader hears, drawn for the board in a dashed outline (not on screen)."""
    k.fallback("hidden")
    return k.vbox(f"dashed · {label}", [k.text("label", label, k.CAPTION, k.TEXT_3, w=w - 16),
                                        k.text("words", chars, k.CAPTION, k.TEXT_1, w=w - 16)],
                  {"pad": k.INSET_SM, "gap": k.STACK_XS, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                   "strokeAlign": "inner", "radius": k.R_CONTROL}, w=w, note="board marker: visually hidden text")


def marker(words: str, w: int | None = None, *, name: str | None = None) -> Node:
    k.fallback("marker")
    t = k.text("words", words, k.CAPTION, k.TEXT_1, w=(w - 16) if w else None)
    return k.hbox(name or f"dashed · marker · {words[:24]}", [t],
                  {"padX": k.INSET_XS, "stroke": k.TEXT_1, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                   "radius": k.R_CONTROL}, w=w, h=None if w else 20, note="board marker, not product UI")


def page(route: str, kids: list[Node | None], w: int = PAGE_W, *, name: str | None = None) -> Node:
    return k.vbox(name or f"page · {k.frame_name(route)}", kids, {"pad": k.INSET_LG, "gap": k.STACK_MD, "fill": k.APP,
                                                    "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                                    "strokeAlign": "inner"}, w=w)


def page_header(title: str, route: str, w: int, *, env: str | None, actions: Iterable[Node] = ()) -> Node:
    left = k.vbox("heading", [k.text("route", route, k.CAPTION, k.TEXT_3), k.text("title", title, k.HEADING_MD,
                                                                                   k.TEXT_1)], {"gap": k.STACK_XS})
    acts = list(actions)
    row = k.hbox("title row", [left, k.hbox("actions", acts, {"gap": k.INSET_SM}, h=CTRL_H) if acts else None],
                 {"justify": "space-between"}, w=w - 2 * k.PX[k.INSET_LG])
    return k.vbox("page header", [row, scope(env) if env else None], {"gap": k.STACK_SM},
                  w=w - 2 * k.PX[k.INSET_LG])


def filter_bar(items: list[tuple[str, str]], w: int, *, open_: str | None = None) -> Node:
    def fw(val: str) -> int:
        return max(136, int(k.text_w(val, k.BODY)) + 56)
    return k.hbox("filter bar", [select(lab, val, fw(val), open_=lab == open_) for lab, val in items],
                  {"gap": k.INSET_SM, "align": "end"}, w=w, note="CMP-055 FilterBar (lo-fi)")


COLS_093 = [k.Col("sel", "", 40), k.Col("time", "time (UTC)", 112), k.Col("symbol", "symbol", 88),
            k.Col("side", "side", 64), k.Col("r", "R", 80, k.NUM_SM), k.Col("net", "net P&L", 128, k.NUM_SM),
            k.Col("entry", "entry", 104, k.NUM_SM), k.Col("exit", "exit", 104, k.NUM_SM),
            k.Col("qty", "qty", 72, k.NUM_SM), k.Col("account", "account", 120), k.Col("tags", "tags", 208)]
TABLE_W = sum(c.w for c in COLS_093)


def checkbox(on: bool, *, t2: bool = False) -> list[Node]:
    if t2:
        k.fallback("t2stroke")
    b = k.hbox("dashed · checkbox" if t2 else "checkbox", [k.icon("tick", "check", k.TEXT_1, k.ICON_SM)] if on else [],
               {"stroke": k.BORDER if t2 else k.BORDER_STRONG, "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL,
                "justify": "center", "fill": k.SELECTED if on else None}, w=16, h=16)
    return [b, k.icon("lock", "locked", k.TEXT_2, k.ICON_SM)] if t2 else [b]


def trade_row(t: k.Trade, *, sel: bool = False, t2: bool = False, extra_tag: str | None = None) -> dict[str, Any]:
    tag_text = ", ".join(n + (" (auto)" if a else "") for n, a in t.tags)
    return {"sel": checkbox(sel, t2=t2), "time": k.dt_short(t.closed), "symbol": t.symbol, "side": k.side_word(t),
            "r": k.rfmt(t.r), "net": k.usdt(t.net), "entry": k.price(t.entry, t.symbol),
            "exit": k.price(t.exit, t.symbol), "qty": k.qtyfmt(t.qty),
            "account": t.account + (f" ({t.group})" if t.group else ""),
            "tags": tag_text + (f" · {extra_tag}" if extra_tag else "")}


def journal_table(rows: list[k.Trade], *, selected: Iterable[int] = (), t2: bool = False,
                  extra: dict[int, str] | None = None) -> Node:
    ex = extra or {}
    return k.grid_table("CMP-049 journal table", COLS_093,
                        [trade_row(t, sel=i in set(selected), t2=t2, extra_tag=ex.get(t.no)) for i, t in
                         enumerate(rows)], selected=selected)


def totals_bar(rows: list[k.Trade], env: str, filt: str, w: int) -> Node:
    s = k.stats(rows)
    words = (f"Totals for the filter ({env} · {filt}): {s.n} trades · win rate {k.pct(s.win_rate)} (n = {s.n}) · "
             f"expectancy {k.rfmt(s.expectancy)} (n = {s.n}) · net P&L {k.usdt(s.net)}")
    k.derive(f"totals ({env}, {filt}): {s.wins} of {s.n} net-positive → {k.pct(s.win_rate)}; mean R "
             f"{k.rfmt(s.expectancy)}; net {k.usdt(s.net)} (sum of the rows' gross − fees + funding; no aggregate "
             f"row, WD-9)")
    return k.hbox("totals bar", [k.text("words", words, k.BODY_STRONG, k.TEXT_1, w=w - 24)],
                  {"padX": k.INSET_SM, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                   "strokeAlign": "inner"}, w=w, h=32, note="server-side totals for the filter (WD-5)")


def pager(shown: int, total: int, w: int) -> Node:
    return k.hbox("pager", [k.text("words", f"Rows 1–{shown} of {total} · cursor-paged", k.CAPTION, k.TEXT_2),
                            btn(k.ui("Next page"))], {"justify": "space-between"}, w=w, h=CTRL_H)


def notice(glyph: str, title: str, body: str | None, w: int, *, actions: Iterable[Node] = (),
           name: str = "notice") -> Node:
    acts = list(actions)
    txt = k.vbox("words", [k.text("title", title, k.BODY_STRONG, k.TEXT_1, w=w - 56),
                           k.text("body", body, k.BODY, k.TEXT_2, w=w - 56) if body else None,
                           k.hbox("actions", acts, {"gap": k.INSET_SM}, h=CTRL_H) if acts else None],
                 {"gap": k.STACK_XS}, w=w - 56)
    return k.hbox(name, [k.icon("glyph", glyph, k.TEXT_1), txt],
                  {"pad": k.INSET_MD, "gap": k.INSET_SM, "align": "start", "fill": k.RAISED, "stroke": k.BORDER_STRONG,
                   "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CARD}, w=w)


def empty_state(title: str, body: str | None, w: int, *, actions: Iterable[Node] = ()) -> Node:
    acts = list(actions)
    return k.vbox("CMP-026 empty state", [k.icon("glyph", "info", k.TEXT_2), k.text("title", title, k.HEADING_SM,
                                                                                     k.TEXT_1),
                                          k.text("body", body, k.BODY, k.TEXT_2, w=w - 64) if body else None,
                                          k.hbox("actions", acts, {"gap": k.INSET_SM}, h=CTRL_H) if acts else None],
                  {"pad": k.INSET_XL, "gap": k.STACK_SM, "align": "center", "fill": k.RAISED}, w=w)


def skeleton_rows(n: int, w: int, *, row_h: int = 28) -> Node:
    k.fallback("skeleton")
    rows = [k.hbox(f"skeleton row · {i + 1:02d}", [k.rect(f"bar {j}", c.w - 16, 10, k.NEUTRAL_SUBTLE,
                                                          {"radius": k.R_CONTROL})
                                                   for j, c in enumerate(COLS_093[1:])],
                   {"gap": k.INSET_LG, "padX": k.INSET_SM, "fill": k.RAISED if i % 2 == 0 else k.CANVAS}, w=w, h=row_h)
            for i in range(n)]
    return k.vbox("skeleton table", rows, {}, w=w, h=n * row_h)


def skel_block(name: str, w: int, h: int) -> Node:
    k.fallback("skeleton")
    return k.rect(f"skeleton · {name}", w, h, k.NEUTRAL_SUBTLE, {"radius": k.R_CARD})


def dialog(title: str, kids: list[Node | None], actions: list[Node], w: int = DIALOG_W, *,
           name: str = "CMP-043 dialog", focus_heading: bool = False, stacked: bool = False) -> Node:
    inner = w - 2 * k.PX[k.DIALOG_PAD]
    ttl = k.text("title", title, k.HEADING_MD, k.TEXT_1, w=inner - 28)
    if focus_heading:
        ttl = ring(k.hbox("heading (tabindex -1)", [ttl], {}, w=inner - 28, h=24))
    head = k.hbox("dialog header", [ttl, k.icon("close", "close", k.TEXT_2)], {"justify": "space-between"}, w=inner,
                  h=24)
    if stacked:  # 200 %: actions stack full width, the primary first
        foot = k.vbox("dialog actions", [dict(a, w=inner) for a in reversed(actions)], {"gap": k.STACK_SM},
                      w=inner)
    else:
        foot = k.hbox("dialog actions", actions, {"gap": k.INSET_SM, "justify": "end"}, w=inner, h=CTRL_H)
    return k.vbox(name, [head, *kids, foot], {"pad": k.DIALOG_PAD, "gap": k.STACK_MD, "fill": k.OVERLAY,
                                              "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                                              "strokeAlign": "inner", "radius": k.R_DIALOG}, w=w)


def backdrop(dlg: Node, w: int, *, words: str) -> Node:
    """The dialog over the page behind it (drawn as a sunken field named for what it stands for)."""
    return k.vbox("page behind (dimmed)", [k.text("behind", words, k.CAPTION, k.TEXT_3), dlg],
                  {"pad": k.INSET_XL, "gap": k.STACK_SM, "align": "center", "fill": k.SUNKEN}, w=w)


def kv(label: str, value: str, w: int, *, typo: str = k.NUM_SM) -> Node:
    return k.hbox(f"kv · {label}", [k.text("label", label, k.CAPTION, k.TEXT_2, w=120),
                                    k.text("value", value, typo, k.TEXT_1, w=w - 128)], {"gap": k.INSET_SM,
                                                                                         "align": "start"}, w=w,
                  note="CMP-036 KeyValueRow (lo-fi)")


# --- lo-fi charts (non-flex boards; children placed by x / y from the derived series)
def _yscale(lo: Decimal, hi: Decimal, top: int, h: int):  # type: ignore[no-untyped-def]
    span = (hi - lo) or Decimal(1)
    return lambda v: top + round(float((hi - v) / span) * h)


def chart_box(name: str, w: int, h: int, kids: list[Node], note: str) -> Node:
    k.fallback("chart")
    return k.box(name, kids, {"fill": k.SUNKEN, "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"},
                 w=w, h=h, note=note)


def equity_chart(rows: list[k.Trade], w: int, h: int = 200) -> Node:
    """CMP-167: cumulative net per trade (columns from the zero rule) over the drawdown band (columns down)."""
    eq = k.equity(rows)
    vals = [e for _t, e, _d in eq]
    lo, hi = min(Decimal(0), *vals), max(Decimal(0), *vals)
    left, top, ch = 72, 12, h - 96
    y = _yscale(lo, hi, top, ch)
    step = (w - left - 12) / len(eq)
    kids = [k.rect("zero rule", w - left - 12, 1, k.BORDER_STRONG, x=left, y=y(Decimal(0)))]
    for lab, v in (("max", hi), ("min", lo)):
        kids.append(k.text(f"y label {lab}", k.usdt(v), k.NUM_SM, k.TEXT_2, x=4, y=y(v) - 6))
    for i, (t, e, _d) in enumerate(eq):
        y0, y1 = sorted((y(Decimal(0)), y(e)))
        kids.append(k.rect(f"equity col {i + 1:02d}", max(round(step) - 2, 2), max(y1 - y0, 1), k.TEXT_2,
                           x=round(left + i * step), y=y0))
    dd_max = max(d for _t, _e, d in eq)
    dtop, dh = top + ch + 24, 40
    kids.append(k.text("dd label", f"drawdown (max {k.usdt(-dd_max)})", k.CAPTION, k.TEXT_2, x=4, y=dtop - 16))
    for i, (_t, _e, d) in enumerate(eq):
        if d > 0:
            kids.append(k.rect(f"dd col {i + 1:02d}", max(round(step) - 2, 2), max(round(float(d / dd_max) * dh), 1),
                               k.NEUTRAL, x=round(left + i * step), y=dtop))
    kids.append(k.text("x first", k.dt_short(eq[0][0].closed), k.CAPTION, k.TEXT_3, x=left, y=h - 18))
    kids.append(k.text("x last", k.dt_short(eq[-1][0].closed), k.CAPTION, k.TEXT_3, x=w - 90, y=h - 18))
    k.derive(f"equity: {len(eq)} closes, cumulative net {k.usdt(vals[-1])}, peak {k.usdt(max(vals))}, max drawdown "
             f"{k.usdt(-dd_max)} (from the running peak)")
    return chart_box("CMP-167 equity and drawdown", w, h, kids, "lo-fi: columns per closed trade")


def histogram(rows: list[k.Trade], w: int, h: int = 200) -> Node:
    """N-1: the R distribution in the five R_BUCKETS."""
    counts = [sum(1 for t in rows if k.r_bucket(t.r) == i) for i in range(len(k.R_BUCKETS))]
    top, ch, n = 24, h - 64, len(counts)
    bw = (w - 32) // n
    mx = max(counts) or 1
    kids: list[Node] = [k.rect("base rule", w - 32, 1, k.BORDER_STRONG, x=16, y=top + ch)]
    for i, (c, (lab, _a, _b)) in enumerate(zip(counts, k.R_BUCKETS)):
        bh = round(ch * c / mx)
        x = 16 + i * bw
        kids += [k.rect(f"bar {i + 1}", bw - 16, max(bh, 1), k.TEXT_2, x=x + 8, y=top + ch - bh),
                 k.text(f"count {i + 1}", f"n = {c}", k.NUM_SM, k.TEXT_1, x=x + 8, y=top + ch - bh - 16),
                 k.text(f"bucket {i + 1}", lab, k.CAPTION, k.TEXT_2, x=x + 8, y=top + ch + 8)]
    k.derive(f"R histogram: {', '.join(f'{lab} {c}' for c, (lab, _a, _b) in zip(counts, k.R_BUCKETS))} "
             f"(sum {sum(counts)} = n)")
    return chart_box("N-1 R histogram", w, h, kids, "N-1: no catalogued component (memo §8)")


def scatter(rows: list[k.Trade], w: int, h: int = 200) -> Node:
    """N-2: MAE (x, R) against MFE (y, R); win = circle, loss = square (shape by outcome, `14`)."""
    mae = [t.r_of(t.mae) for t in rows]
    mfe = [t.r_of(t.mfe) for t in rows]
    left, top, cw, ch = 48, 12, w - 64, h - 52
    xmin = min(Decimal(-1), *mae)
    ymax = max(mfe) or Decimal(1)
    kids: list[Node] = [k.rect("x axis", cw, 1, k.BORDER_STRONG, x=left, y=top + ch),
                        k.rect("y axis", 1, ch, k.BORDER_STRONG, x=left, y=top),
                        k.text("x label", f"MAE (R), {k.rfmt(xmin)} to 0R", k.CAPTION, k.TEXT_2, x=left, y=h - 20),
                        k.text("y label", f"MFE to {k.rfmt(ymax)}", k.CAPTION, k.TEXT_2, x=4, y=top)]
    for i, (t, a, b) in enumerate(zip(rows, mae, mfe)):
        x = left + round(float((a - xmin) / (0 - xmin)) * (cw - 8))
        y = top + round(float((ymax - b) / ymax) * (ch - 8))
        if t.net > 0:
            kids.append(k.ellipse(f"win {i + 1:02d}", 8, 8, {"stroke": k.TEXT_1, "strokeWidth": k.HAIR}, x=x, y=y))
        else:
            kids.append(k.rect(f"loss {i + 1:02d}", 8, 8, k.TEXT_2, x=x, y=y))
    return chart_box("N-2 MAE MFE scatter", w, h, kids, "N-2: shape by outcome, no colour encoding")


def chart_card(title: str, chart: Node, summary: str, w: int, *, formula: bool = False) -> Node:
    """A chart with its text summary (with n) and "View as table" (WD-11)."""
    vt = k.WDS["WD-11"].decision
    label = "View as table"
    assert label in vt, vt
    head = k.hbox("card header", [k.text("title", title, k.HEADING_SM, k.TEXT_1),
                                  k.hbox("card actions", [link(k.ui("Formula")) if formula else None, btn(label)],
                                         {"gap": k.INSET_SM}, h=CTRL_H)], {"justify": "space-between"}, w=w - 24)
    return k.vbox(f"chart card · {title}", [head, chart, k.text("summary", summary, k.BODY, k.TEXT_1, w=w - 24)],
                  {"pad": k.INSET_MD, "gap": k.STACK_SM, "fill": k.RAISED, "radius": k.R_CARD}, w=w)


def bar_path(t: k.Trade, minutes: int = 5, pad_min: int = 30) -> list[tuple[Any, Decimal, Decimal, Decimal, Decimal]]:
    """Seeded 5-minute bars around the trade (synthetic): the path passes entry at the open, the MAE and MFE prices
    at their times and the exit at the close; the bars holding those instants reach them exactly."""
    import random
    from datetime import timedelta
    rng = random.Random(k.SEED * 100000 + t.no)
    tick = k.TICK[t.symbol]
    t0 = t.opened.replace(minute=t.opened.minute // minutes * minutes, second=0) - timedelta(minutes=pad_min)
    t1 = t.closed + timedelta(minutes=pad_min)
    anchors = sorted([(t.opened, t.entry), (t.mae_at, t.mae), (t.mfe_at, t.mfe), (t.closed, t.exit)])
    drift = t.risk / 3
    anchors = [(t0, k.q(t.entry - t.side * drift, tick))] + anchors + [(t1, k.q(t.exit + t.side * drift / 2, tick))]

    def at(x: Any) -> Decimal:
        for (a, pa), (b, pb) in zip(anchors, anchors[1:]):
            if a <= x <= b:
                f = Decimal(str((x - a).total_seconds() / max((b - a).total_seconds(), 1)))
                return pa + (pb - pa) * f
        return anchors[-1][1]

    out, cur = [], t0
    while cur < t1:
        nxt = cur + timedelta(minutes=minutes)
        o, c = k.q(at(cur), tick), k.q(at(nxt), tick)
        inside = [p for a, p in anchors if cur <= a < nxt]
        noise = k.q(t.risk * Decimal(str(round(rng.uniform(0.02, 0.12), 3))), tick)
        hi = max([o, c, *inside]) + (Decimal(0) if any(p == max([o, c, *inside]) for p in inside) else noise)
        lo = min([o, c, *inside]) - (Decimal(0) if any(p == min([o, c, *inside]) for p in inside) else noise)
        if cur <= t.mae_at < nxt:
            hi, lo = (hi, t.mae) if t.side > 0 else (t.mae, lo)
        if cur <= t.mfe_at < nxt:
            hi, lo = (t.mfe, lo) if t.side > 0 else (hi, t.mfe)
        if cur < t.closed and nxt > t.opened:  # inside the trade nothing passes its MAE or MFE
            worst, best = (t.mae, t.mfe) if t.side > 0 else (t.mfe, t.mae)
            hi, lo = min(hi, best), max(lo, worst)
        out.append((cur, o, max(hi, o, c), min(lo, o, c), c))
        cur = nxt
    return out


def context_chart(t: k.Trade, w: int, h: int = 240, *, band: tuple[Any, Any, str] | None = None) -> Node:
    """CMP-181 in an engine minimal pane (lo-fi): 5-minute bars, entry / exit / SL rules with labels."""
    k.fallback("context")
    bars = bar_path(t)
    # SHEET-FIX 05 (live check): the price scale spans the SL, entry and exit as well as the bars, so a short's SL
    # above the bars (SCR-094/pruned) stays inside the pane with its label
    lo = min(min(b[3] for b in bars), t.stop, t.entry, t.exit)
    hi = max(max(b[2] for b in bars), t.stop, t.entry, t.exit)
    left, top, ch = 96, 12, h - 44
    y = _yscale(lo, hi, top, ch)
    step = (w - left - 16) / len(bars)
    kids: list[Node] = []
    if band:
        def tx(x_: Any) -> int:
            return round(left + (x_ - bars[0][0]).total_seconds() / 300 * step)
        bx0, bx1 = tx(max(band[0], bars[0][0])), tx(min(band[1], bars[-1][0]))
        kids += [k.rect("band · ticks missing", bx1 - bx0, ch, k.NEUTRAL_SUBTLE, x=bx0, y=top),
                 k.text("band label", band[2], k.CAPTION, k.TEXT_1, x=bx0 + 4, y=top + 4)]
    for i, (ts, o, hh, ll, c) in enumerate(bars):
        x = round(left + i * step)
        kids.append(k.rect(f"wick {i + 1:02d}", 1, max(y(ll) - y(hh), 1), k.TEXT_2, x=x + round(step / 2) - 1,
                           y=y(hh)))
        y0, y1 = sorted((y(o), y(c)))
        body = {"stroke": k.TEXT_1, "strokeWidth": k.HAIR, "fill": k.SUNKEN} if c >= o else {"fill": k.TEXT_2}
        kids.append(k.rect(f"bar {i + 1:02d}", max(round(step) - 4, 2), max(y1 - y0, 1), None, body, x=x + 1, y=y0))
    for lab, v in ((f"entry {k.price(t.entry, t.symbol)}", t.entry), (f"SL {k.price(t.stop, t.symbol)}", t.stop),
                   (f"exit {k.price(t.exit, t.symbol)}", t.exit)):
        if lab.startswith("exit") and t.exit == t.stop:
            continue
        kids += [k.rect(f"rule · {lab.split()[0]}", w - left - 16, 1, k.TEXT_1, x=left, y=y(v)),
                 k.text(f"label · {lab.split()[0]}", lab, k.NUM_SM, k.TEXT_1, x=4, y=y(v) - 6)]
    kids += [k.text("x first", bars[0][0].strftime("%H:%M"), k.CAPTION, k.TEXT_3, x=left, y=h - 18),
             k.text("x last", bars[-1][0].strftime("%H:%M") + " UTC", k.CAPTION, k.TEXT_3, x=w - 80, y=h - 18)]
    k.derive(f"context bars: {len(bars)} × 5 min from {bars[0][0].strftime('%H:%M')} (seeded path through entry "
             f"{k.price(t.entry, t.symbol)}, MAE {k.price(t.mae, t.symbol)}, MFE {k.price(t.mfe, t.symbol)}, exit "
             f"{k.price(t.exit, t.symbol)}); high {k.price(hi, t.symbol)}, low {k.price(lo, t.symbol)}")
    return chart_box("CMP-181 context pane", w, h, kids, "engine minimal pane (lo-fi), no third-party library")


def run(nn: int, built: tuple[list[Node], list[tuple[str, list[str]]]], cols: int, *,
        board_lines: Iterable[str] = (), notes: dict[str, Iterable[str]] | None = None) -> None:
    p, md, packed = k.build(nn, built[0], built[1], cols, board_lines=board_lines, notes=notes)
    rc, msg = k.validate(p)
    print(f"{p.name}: {msg.splitlines()[-1]} (exit {rc}); md {md.name}; packed {packed.name}")
