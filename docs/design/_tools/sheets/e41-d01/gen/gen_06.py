"""Board 06 scr095-default: SCR-095 in LIVE scope (stats with n and a formula link, equity + drawdown, R histogram,
MAE / MFE scatter, the by-tag breakdown) and its table view (WD-11)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import s095  # noqa: E402
import wf  # noqa: E402
from wf import k  # noqa: E402

NN = 6


def default(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    return (k.frame(fid, [s095.screen()], wf.SCREEN_W, "SCR-095 default — LIVE scope; every statistic with its n and "
                                                       "a formula link; every chart with 'View as table' and a text "
                                                       "summary"),
            k.frame_block(fid, ["`14` metric set: win rate, expectancy, avg R (= expectancy in R), profit factor, max "
                                "drawdown, streaks, by-tag drawn; by-symbol / by-hour / by-account through the 'by' "
                                "select (by-hour in the table view); by-rule waits on G-4 (no rule-source key)",
                                "N-1 histogram and N-2 scatter: new-component notes to E41-D04 #1082"],
                              wds=["WD-1", "WD-4", "WD-11", "WD-14"]))


def table_view(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rs = k.trades()
    sm = s095.summaries(rs)
    days: dict[str, list[k.Trade]] = {}
    for t in sorted(rs, key=lambda t: (t.closed, t.no)):
        days.setdefault(t.closed.strftime("%d %b"), []).append(t)
    eq, peak, drows = k.Decimal(0), k.Decimal(0), []
    for d, ts in days.items():
        net = sum((t.net for t in ts), k.Decimal(0))
        eq += net
        peak = max(peak, eq)
        drows.append({"day": d, "n": str(len(ts)), "net": k.usdt(net), "cum": k.usdt(eq), "dd": k.usdt(eq - peak)})
    ecols = [k.Col("day", "day", 80), k.Col("n", "n", 48, k.NUM_SM), k.Col("net", "net P&L", 128, k.NUM_SM),
             k.Col("cum", "cumulative", 128, k.NUM_SM), k.Col("dd", "drawdown", 128, k.NUM_SM)]
    k.derive(f"table view: equity by close day ({len(days)} days); the last cumulative value {k.usdt(eq)} equals the "
             "net P&L stat")
    hist = [{"b": lab, "n": str(sum(1 for t in rs if k.r_bucket(t.r) == i))} for i, (lab, _a, _b) in
            enumerate(k.R_BUCKETS)]
    sc = [{"no": f"#{t.no}", "mae": k.rfmt(t.r_of(t.mae)), "mfe": k.rfmt(t.r_of(t.mfe)),
           "out": "win" if t.net > 0 else "loss"} for t in rs[:8]]

    def card(title: str, tbl: k.Node, summary: str, extra: k.Node | None = None) -> k.Node:
        return k.vbox(f"table card · {title}", [k.hbox("card header", [
            k.text("title", title, k.HEADING_SM, k.TEXT_1), wf.btn(k.ui("View as chart"))], {"justify":
                                                                                             "space-between"},
            w=s095.HALF - 24), tbl, extra, k.text("summary", summary, k.BODY, k.TEXT_1, w=s095.HALF - 24)],
            {"pad": k.INSET_MD, "gap": k.STACK_SM, "fill": k.RAISED, "radius": k.R_CARD}, w=s095.HALF)

    left = k.vbox("left", [card(k.ui("Equity and drawdown"), k.grid_table("equity by day (CMP-049)", ecols, drows,
                                                                          row_h=24), sm["equity"])],
                  {"gap": k.INSET_LG}, w=s095.HALF)
    right = k.vbox("right", [
        card(k.ui("R distribution"), k.grid_table("R buckets (CMP-049)", [k.Col("b", "R bucket", 160),
                                                                           k.Col("n", "n", 64, k.NUM_SM)], hist,
                                                  row_h=24), sm["hist"]),
        card(k.ui("MAE and MFE"), k.grid_table("MAE MFE rows (CMP-049)", [
            k.Col("no", "trade", 88), k.Col("mae", "MAE", 96, k.NUM_SM), k.Col("mfe", "MFE", 96, k.NUM_SM),
            k.Col("out", "outcome", 88)], sc, row_h=24), sm["scatter"],
             wf.pager(len(sc), len(rs), s095.HALF - 24)),
        s095.breakdown_card(rs, "hour", "session hour (UTC)")], {"gap": k.INSET_LG}, w=s095.HALF)
    body = [s095.stat_cards(rs, "LIVE"), k.hbox("tables", [left, right], {"gap": k.INSET_LG, "align": "start"},
                                                w=s095.INNER)]
    return (k.frame(fid, [s095.screen(body=body)], wf.SCREEN_W, "SCR-095 table-view — each chart as a table with the "
                                                                "same text summary; the by-hour breakdown"),
            k.frame_block(fid, ["`05`:156 data-table alternative; `14` SCR-095 A11y"], wds=["WD-11"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((default, table_view), k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    wf.run(NN, frames(), 2)
