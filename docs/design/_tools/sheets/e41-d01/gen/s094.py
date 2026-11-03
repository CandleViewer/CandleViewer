"""SCR-094 Trade detail parts shared by boards 04 and 05."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wf  # noqa: E402
from wf import k  # noqa: E402

COL_W = (wf.PAGE_W - 2 * 16 - 24) // 2
H = "### SCR-094"


def header(t: k.Trade) -> Any:
    title = f"Trade #{t.no} {t.symbol} {k.side_word(t)} {k.qtyfmt(t.qty)} ({t.account})"
    k.derive(f"title in `14`'s SCR-094 sketch form 'Trade #n SYMBOL side qty (account)': {title}")
    return k.vbox("page top", [wf.link(k.ui("Back to journal", "`12` R-181 back link")),
                               wf.page_header(title, f"/journal/{t.no}", wf.PAGE_W, env=t.env,
                                              actions=[wf.link(k.cat("Open in replay", H)),
                                                       wf.link(k.cat("Open chart at entry", H))])],
                  {"gap": k.STACK_SM}, w=wf.PAGE_W - 32)


def fills(t: k.Trade) -> list[tuple[str, str, str, str, str]]:
    """(time, side, qty, price, fee): the entry fill and the exit fill; the fees sum to the trade's fee."""
    fe = k.q(k.FEE_RATE * t.entry * t.qty, k.Decimal("0.01"))
    buy, sell = ("Buy", "Sell") if t.side > 0 else ("Sell", "Buy")
    return [(k.dt_long(t.opened), buy, k.qtyfmt(t.qty), k.price(t.entry, t.symbol), f"{fe:.2f} USDT"),
            (k.dt_long(t.closed), sell, k.qtyfmt(t.qty), k.price(t.exit, t.symbol), f"{t.fees - fe:.2f} USDT")]


def facts(t: k.Trade) -> Any:
    w = COL_W
    rows = [("entry", f"{k.price(t.entry, t.symbol)} at {k.dt_long(t.opened)}"),
            ("exit", f"{k.price(t.exit, t.symbol)} at {k.dt_long(t.closed)}"),
            ("R multiple", f"{k.rfmt(t.r)} (risk {k.price(t.risk, t.symbol)} = entry − SL {k.price(t.stop, t.symbol)})"),
            ("net P&L", f"{k.usdt(t.net)} = gross {k.usdt(t.gross)} − fees {t.fees:.2f} + funding {k.usdt(t.funding)}"),
            ("MAE", f"{k.rfmt(t.r_of(t.mae))} ({k.price(t.mae, t.symbol)} at {t.mae_at.strftime('%H:%M:%S')} UTC)"),
            ("MFE", f"{k.rfmt(t.r_of(t.mfe))} ({k.price(t.mfe, t.symbol)} at {t.mfe_at.strftime('%H:%M:%S')} UTC)"),
            ("time in trade", k.hold_fmt(t.hold)), ("managed by", t.managed)]
    k.derive(f"#{t.no}: R = (exit − entry) ÷ (entry − SL) = {k.rfmt(t.r)}; gross {k.usdt(t.gross)}, fees "
             f"{t.fees:.2f} ({(k.FEE_RATE * 100).normalize()} % a side), funding {k.usdt(t.funding)}, net "
             f"{k.usdt(t.net)}")
    return k.vbox("CMP-036 key values", [wf.kv(a, b, w) for a, b in rows], {"gap": k.STACK_XS}, w=w)


def fills_table(t: k.Trade) -> Any:
    cols = [k.Col("time", "time", 184), k.Col("side", "side", 64), k.Col("qty", "qty", 72, k.NUM_SM),
            k.Col("price", "price", 104, k.NUM_SM), k.Col("fee", "fee", 104, k.NUM_SM)]
    rows = [dict(zip(("time", "side", "qty", "price", "fee"), f)) for f in fills(t)]
    return k.grid_table("fills (CMP-049)", cols, rows, cap=k.ui("Fills"))


def attribution(t: k.Trade) -> Any:
    cols = [k.Col("time", "time", 88), k.Col("action", "action", 248), k.Col("by", "by", 192)]
    stop_by = "exchange-native SL" if t.exit == t.stop else t.managed
    rows = [{"time": t.opened.strftime("%H:%M:%S"), "action": f"entry filled at {k.price(t.entry, t.symbol)}",
             "by": t.managed if t.managed == "manual" else "manual"},
            {"time": t.opened.strftime("%H:%M:%S"), "action": f"native SL at {k.price(t.stop, t.symbol)}",
             "by": "attached with the entry"},
            {"time": t.closed.strftime("%H:%M:%S"), "action": f"exit filled at {k.price(t.exit, t.symbol)}",
             "by": stop_by}]
    return k.grid_table("attribution (CMP-049)", cols, rows, cap=k.ui("Who acted"))


def siblings(t: k.Trade) -> Any:
    legs = [x for x in k.JOURNAL if x.group and x.group == t.group]
    cols = [k.Col("account", "account", 136), k.Col("qty", "qty", 80, k.NUM_SM), k.Col("r", "R", 80, k.NUM_SM),
            k.Col("net", "net P&L", 136, k.NUM_SM)]
    rows = [{"account": x.account + (" (this trade)" if x.no == t.no else ""), "qty": k.qtyfmt(x.qty),
             "r": k.rfmt(x.r), "net": k.usdt(x.net)} for x in legs]
    k.derive(f"group {t.group}: {len(legs)} legs, one per account, same prices; no aggregate row and no group sum "
             "is drawn (WD-9)")
    return k.grid_table("group siblings (CMP-049)", cols, rows, cap=f"{k.ui('Trade group')} {t.group}: "
                                                                   f"{len(legs)} legs, one row per account")


def notes_tags(t: k.Trade, *, removed_auto: bool = False, t2: bool = False, w: int = COL_W) -> Any:
    note = wf.textfield(k.ui("Note"), "Entered on the breakout retest; stop under the range low.", w, t2=t2)
    tags = [(n, a) for n, a in t.tags if not (removed_auto and a)]
    chip_row = k.hbox("CMP-169 tag editor", [*wf.chips(tags, w, removable=True, t2=t2), wf.btn(k.ui("Add tag"), t2=t2)],
                      {"gap": k.INSET_XS, "wrap": "wrap"}, w=w, h=28)
    if t2:
        reason = k.memo("Your role can't write in the journal.")
        rsn = k.hbox("CMP-079 reason", [k.icon("lock", "locked", k.TEXT_2, k.ICON_SM),
                                        k.text("words", reason, k.BODY, k.TEXT_1)],
                     {"gap": k.INSET_XS, "padX": k.INSET_SM, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                      "strokeAlign": "inner", "radius": k.R_CONTROL, "fill": k.OVERLAY}, h=28,
                     note="CMP-079 visible reason, key rbac.permission (E09-D09 §3.1)")
        return k.vbox("notes and tags · T2", [note, chip_row, rsn], {"gap": k.STACK_SM}, w=w)
    rec = k.text("removal note", k.ui("Removing an auto tag is recorded (journal.tag_removed)"), k.CAPTION, k.TEXT_2,
                 w=w)
    return k.vbox("notes and tags", [note, chip_row, rec], {"gap": k.STACK_SM}, w=w)
