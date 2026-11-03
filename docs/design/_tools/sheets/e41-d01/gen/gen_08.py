"""Board 08 scope-and-cohort: one environment scope at a time (WD-1) — SCR-093 in DEMO scope; SCR-095's DEMO toggle
switches the scope, never adds DEMO to LIVE (WD-2); the cohort controls for a Manager scoped to granted accounts."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import s093  # noqa: E402
import s095  # noqa: E402
import wf  # noqa: E402
from wf import k  # noqa: E402

NN = 8
MANAGER = k.LIVE_ACCOUNTS[1:]  # a P2b Manager granted Account B and Account C (synthetic)


def demo_list(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rs = k.trades("DEMO")
    k.derive(f"DEMO scope: {len(rs)} DEMO trades on {k.DEMO_ACCOUNT}; no LIVE row and no LIVE figure on the frame")
    return (k.frame(fid, [s093.screen("DEMO")], wf.SCREEN_W, "SCR-093 in DEMO scope — the scope label and the totals "
                                                             "say DEMO; LIVE is not inside any figure"),
            k.frame_block(fid, ["The environment filter is a single choice (LIVE or DEMO), never 'both'"],
                          wds=["WD-1"]))


def demo_toggle(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rs = k.trades("DEMO")
    cav = wf.notice("info", k.deck("caveat.sample"), f"n = {len(rs)}", s095.INNER, name="caveat (CMP-028 inline)")
    sm = s095.summaries(rs)
    cw = s095.HALF - 24
    row = k.hbox("charts row 1", [wf.chart_card(k.ui("Equity and drawdown") + " · DEMO", wf.equity_chart(rs, cw),
                                                sm["equity"], s095.HALF),
                                  wf.chart_card(k.ui("R distribution") + " · DEMO", wf.histogram(rs, cw), sm["hist"],
                                                s095.HALF)],
                 {"gap": k.INSET_LG, "align": "start"}, w=s095.INNER)
    return (k.frame(fid, [s095.screen("DEMO", rs, body=[cav, s095.stat_cards(rs, "DEMO"), row])], wf.SCREEN_W,
                    "SCR-095 with the DEMO toggle on — every figure and chart is labelled DEMO; no LIVE figure "
                    "remains; 12 trades, so the caveat shows"),
            k.frame_block(fid, ["OQ-3 (owner): DEMO beside LIVE for a method comparison, never summed"],
                          wds=["WD-2", "WD-3"]))


def cohort(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rs = k.trades(accounts=MANAGER)
    opts = [k.hbox(f"option · {a}", wf.checkbox(True) + [k.text("name", a, k.BODY, k.TEXT_1),
                                                         k.text("n", f"{len(k.trades(accounts=[a]))} trades",
                                                                k.CAPTION, k.TEXT_2)],
                   {"gap": k.INSET_SM, "padX": k.INSET_SM}, w=240, h=28) for a in MANAGER]
    lb = k.vbox("listbox · account", opts, {"pad": k.INSET_XS, "fill": k.OVERLAY, "stroke": k.BORDER_STRONG,
                                            "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL},
                w=248)
    acct = ", ".join(MANAGER)
    k.derive(f"cohort: a Manager granted {acct} sees {len(rs)} LIVE trades; Account A is absent from the data and "
             "the list (scope, not a control)")
    body = [lb, s095.stat_cards(rs, "LIVE"), k.hbox("charts row 2", [
        wf.chart_card(k.ui("R distribution"), wf.histogram(rs, s095.HALF - 24), s095.summaries(rs)["hist"], s095.HALF),
        s095.breakdown_card(rs, "account", "account")], {"gap": k.INSET_LG, "align": "start"}, w=s095.INNER)]
    return (k.frame(fid, [wf.page("/journal/analytics", [s095.header(), wf.filter_bar(
        [("range", s093.RANGE_WORDS), ("account", acct), ("symbol", s093.ALL), ("tag", s093.ALL)], s095.INNER,
        open_="account"), *body])], wf.SCREEN_W,
                    "SCR-095 cohort controls — range, account, symbol and tag; the account list holds granted "
                    "accounts only"),
            k.frame_block(fid, ["`14` SCR-095 checklist: date-range and cohort controls; journal.cohort_changed "
                                "(analytics only)", "RBAC scope is server-side (C-12.4); BQ-13"], wds=["WD-1"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((demo_list, demo_toggle, cohort), k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    wf.run(NN, frames(), 2)
