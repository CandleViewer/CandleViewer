"""SCR-095 Journal analytics parts shared by boards 06, 07 and 08."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s093  # noqa: E402
import wf  # noqa: E402
from wf import k  # noqa: E402

H = "### SCR-095"
INNER = wf.PAGE_W - 32
HALF = (INNER - 16) // 2


def toggle(on: bool, *, focused: bool = False) -> Any:
    sw = k.hbox("switch", [k.rect("knob", 12, 12, k.TEXT_1, {"radius": k.R_BADGE})],
                {"padX": k.INSET_XS, "justify": "end" if on else "start", "radius": k.R_BADGE,
                 "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                 "fill": k.SELECTED if on else k.SUNKEN}, w=32, h=18)
    t = k.hbox("DEMO toggle", [sw, k.text("label", k.ui("DEMO instead of LIVE", "WD-2: the toggle switches the scope"),
                                          k.BODY, k.TEXT_1),
                               k.text("state", "on" if on else "off", k.CAPTION, k.TEXT_2)], {"gap": k.INSET_SM}, h=28,
               note="WD-2 / `14` SCR-095: DEMO excluded by default, an explicit toggle")
    return wf.ring(t) if focused else t


def header(env: str = "LIVE") -> Any:
    return wf.page_header("Journal analytics", "/journal/analytics", wf.PAGE_W, env=env,
                          actions=[toggle(env == "DEMO"), wf.btn(k.memo('"Export"')[1:-1])])


def filters(**over: str) -> Any:
    vals = {"range": s093.RANGE_WORDS, "account": s093.ALL, "symbol": s093.ALL, "tag": s093.ALL}
    vals.update(over)
    return wf.filter_bar(list(vals.items()), INNER)


def stat_cards(rows: list[k.Trade], env: str) -> Any:
    s = k.stats(rows)
    n = s.n
    cards = [("trades", str(n), ""), ("win rate", k.pct(s.win_rate), f"n = {n}"),
             ("expectancy", k.rfmt(s.expectancy), f"n = {n}"),
             ("profit factor", str(s.profit_factor) if s.profit_factor is not None else "—", f"n = {n}"),
             ("max drawdown", k.usdt(-s.max_dd), f"n = {n}"), ("avg hold", k.hold_fmt(s.avg_hold), f"n = {n}"),
             ("streaks", f"{s.win_streak} W / {s.loss_streak} L", f"n = {n}")]
    for lab, _v, _n in cards:
        k.cat(lab if lab not in ("trades", "streaks", "avg hold") else {"trades": "win rate", "streaks": "streaks",
                                                                           "avg hold": "average hold time"}[lab], H)
    k.derive(f"{env} stats over {n}: wins {s.wins} (net > 0) → {k.pct(s.win_rate)}; expectancy = mean R "
             f"{k.rfmt(s.expectancy)}; profit factor = net wins ÷ |net losses| = {s.profit_factor}; max drawdown "
             f"{k.usdt(-s.max_dd)} from the running peak; streaks {s.win_streak} W / {s.loss_streak} L")
    cw = (INNER - 6 * 8) // 7
    kids = [k.vbox(f"CMP-168 card · {lab}", [k.text("label", lab + (f" · {env}" if env != "LIVE" else ""),
                                                    k.CAPTION, k.TEXT_2),
                                             k.text("value", v, k.NUM_MD, k.TEXT_1),
                                             k.hbox("foot", [k.text("n", nn, k.CAPTION, k.TEXT_2) if nn else None,
                                                             wf.link(k.ui("Formula"))],
                                                    {"gap": k.INSET_SM}, h=20)],
                   {"pad": k.INSET_SM, "gap": k.STACK_XS, "fill": k.RAISED, "radius": k.R_CARD}, w=cw)
            for lab, v, nn in cards]
    return k.hbox("CMP-168 stats summary", kids, {"gap": k.INSET_SM, "align": "start"}, w=INNER)


def summaries(rows: list[k.Trade]) -> dict[str, str]:
    s = k.stats(rows)
    stopped = sum(1 for t in rows if t.r_of(t.mae) <= -1)
    return {"equity": f"Net P&L {k.usdt(s.net)} over {s.n} trades; max drawdown {k.usdt(-s.max_dd)}",
            "hist": f"Expectancy {k.rfmt(s.expectancy)} over {s.n} trades",
            "scatter": f"{s.wins} wins (circles), {s.n - s.wins} losses (squares); {stopped} of {s.n} reached "
                       f"−1.00R MAE"}


BCOLS = [k.Col("key", "tag", 152), k.Col("n", "n", 48, k.NUM_SM), k.Col("win", "win rate", 80, k.NUM_SM),
         k.Col("exp", "expectancy", 96, k.NUM_SM), k.Col("net", "net P&L", 128, k.NUM_SM)]


def breakdown_table(rows: list[k.Trade], key: str = "tag", *, label: str = "tag") -> Any:
    out = []
    for name, rs in k.breakdown(rows, key):
        s = k.stats(rs)
        low = k.deck("caveat.bucket", n=s.n) if s.n < 5 else ""
        out.append({"key": name + (f" · {low}" if low else ""), "n": str(s.n), "win": k.pct(s.win_rate),
                    "exp": k.rfmt(s.expectancy), "net": k.usdt(s.net)})
    cols = [k.Col("key", label, 152)] + BCOLS[1:]
    return k.grid_table(f"breakdown by {label} (CMP-049)", cols, out, row_h=24)


# SHEET-FIX 06 (live check): the breakdown select is sized from its value; Penpot set "session hour (UTC)" in 124 px
# (the kit's estimate over-reads it), so the measured widths stand here and other values use the estimate
LIVE_VALUE_W = {"session hour (UTC)": 124}


def select_w(value: str) -> int:
    vw = LIVE_VALUE_W.get(value, int(k.text_w(value, k.BODY)))
    return max(136, vw + 44)


def breakdown_card(rows: list[k.Trade], key: str = "tag", label: str = "tag") -> Any:
    head = k.hbox("card header", [k.text("title", k.ui("Performance by"), k.HEADING_SM, k.TEXT_1),
                                  wf.select(None, label, select_w(label))], {"gap": k.INSET_SM}, h=wf.CTRL_H)
    return k.vbox(f"breakdown card · {label}", [head, breakdown_table(rows, key, label=label),
                                                k.text("note", k.ui("A trade with two tags counts in both rows"),
                                                       k.CAPTION, k.TEXT_2) if key == "tag" else None],
                  {"pad": k.INSET_MD, "gap": k.STACK_SM, "fill": k.RAISED, "radius": k.R_CARD}, w=HALF)


def charts(rows: list[k.Trade]) -> Any:
    sm = summaries(rows)
    cw = HALF - 24
    r1 = k.hbox("charts row 1", [wf.chart_card(k.ui("Equity and drawdown"), wf.equity_chart(rows, cw), sm["equity"],
                                               HALF),
                                 wf.chart_card(k.ui("R distribution"), wf.histogram(rows, cw), sm["hist"], HALF)],
                {"gap": k.INSET_LG, "align": "start"}, w=INNER)
    r2 = k.hbox("charts row 2", [wf.chart_card(k.ui("MAE and MFE"), wf.scatter(rows, cw), sm["scatter"], HALF),
                                 breakdown_card(rows)], {"gap": k.INSET_LG, "align": "start"}, w=INNER)
    return [r1, r2]


def screen(env: str = "LIVE", rows: list[k.Trade] | None = None, *, pre: list[Any] | None = None,
           body: list[Any] | None = None, filt: dict[str, str] | None = None) -> Any:
    rs = rows if rows is not None else k.trades(env)
    main = body if body is not None else [stat_cards(rs, env), *charts(rs)]
    return wf.page("/journal/analytics", [header(env), filters(**(filt or {})), *(pre or []), *main])
