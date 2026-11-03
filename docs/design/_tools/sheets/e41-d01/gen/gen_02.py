"""Board 02 scr093-default: SCR-093 in LIVE scope (WD-5 columns, server-side totals, cursor paging), the bulk-tag
state and the export confirm (WD-10)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import s093  # noqa: E402
import wf  # noqa: E402
from wf import k  # noqa: E402

NN = 2


def default(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rs = s093.rows()
    k.derive(f"rows: the {s093.ROWS_SHOWN} newest of {len(rs)} LIVE closes, newest first; the trade group "
             f"{k.LOSER.group} shows one row per account ({', '.join(t.account for t in k.GROUP)}), no aggregate row")
    fr = k.frame(fid, [s093.screen()], wf.SCREEN_W, "SCR-093 default — LIVE scope; R and net P&L lead entry and exit; "
                                                    "totals for the filter, computed server-side; cursor paging")
    return fr, k.frame_block(fid, [f"Columns: {', '.join(c.label for c in wf.COLS_093[1:])} (WD-5 order); `14` "
                                   "checklist columns open time, fees, environment and rating are not drawn on the "
                                   "lo-fi row (fees on SCR-094; environment is the scope) — E41-D02 #1018 places "
                                   "them"], wds=["WD-1", "WD-5", "WD-9", "WD-12"])


def bulk(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rs = s093.rows()
    sel = tuple(i for i, t in enumerate(rs[:s093.ROWS_SHOWN]) if t.group)
    bar = k.hbox("bulk-tag bar", [k.text("count", f"{len(sel)} selected", k.BODY_STRONG, k.TEXT_1),
                                  wf.select(None, "late-entry", 200), wf.btn(k.ui("Apply tag"), primary=True),
                                  wf.btn(k.ui("Clear selection"))],
                 {"gap": k.INSET_SM, "padX": k.INSET_SM, "fill": k.RAISED, "stroke": k.BORDER_STRONG,
                  "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=wf.TABLE_W, h=44,
                 note="CMP-169 TagEditor in bulk mode (lo-fi)")
    k.derive(f"bulk-tag: the {len(sel)} rows of group {k.LOSER.group} selected; the tag 'late-entry' is already on "
             "them, so applying it changes no row (the server answers per row)")
    fr = k.frame(fid, [s093.screen(selected=sel, pre_table=[bar])], wf.SCREEN_W,
                 "SCR-093 bulk-tag — rows selected by their checkboxes; one tag applied to every selected row")
    return fr, k.frame_block(fid, ["Bulk tagging is a `14` SCR-093 checklist item; audited as journal.tag_added "
                                   "per row (`14` SCR-093 Analytics/audit)"], wds=["WD-9"])


def export(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rs = s093.rows()
    accts = sorted({t.account for t in rs})
    words = k.deck("export.confirm", accounts=", ".join(accts), env="LIVE", range=s093.RANGE_WORDS, rows=len(rs))
    dlg = wf.dialog(k.memo('"Export"')[1:-1], [
        k.text("confirm", words, k.BODY, k.TEXT_1, w=wf.DIALOG_W - 48),
        wf.select(k.ui("format"), "CSV", 200)], [wf.btn(k.ui("Cancel")), wf.btn(k.memo('"Export"')[1:-1],
                                                                                primary=True)])
    fr = k.frame(fid, [wf.backdrop(dlg, wf.PAGE_W, words="SCR-093 Journal (LIVE) behind the dialog")], wf.SCREEN_W,
                 "SCR-093 export — the confirm states environment, accounts, range, row count and the account-data "
                 "line before any file is made")
    k.derive(f"export confirm: {len(rs)} rows = the LIVE filter's count; accounts = the accounts present in the rows")
    return fr, k.frame_block(fid, ["Formats CSV / JSON (`14` SCR-093 Interactions); a manager's export holds own "
                                   "trades only (memo BQ-13, E41-S04 #1212)"], wds=["WD-10"])


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((default, bulk, export), k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    wf.run(NN, frames(), 2)
