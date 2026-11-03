"""Board 03 scr093-states: SCR-093 loading, empty, partial, reconciling, no-match, error and the Viewer's T2 frame
(WD-13: E09-D09's T2 anatomy, drawn here although memo §0 lists it as not drawn — the orchestrator's board plan)."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import s093  # noqa: E402
import wf  # noqa: E402
from wf import k  # noqa: E402

NN = 3
N = 5  # rows drawn on a state frame
SEP = (datetime(2026, 9, 1, tzinfo=k.UTC), datetime(2026, 9, 30, 23, 59, 59, tzinfo=k.UTC))
EARLY = (k.RANGE[0], datetime(2026, 10, 10, 23, 59, 59, tzinfo=k.UTC))
VIEWER_ACCOUNTS = k.LIVE_ACCOUNTS[:2]


def page(kids: list[k.Node | None], **kw: object) -> k.Node:
    return wf.page("/journal", [s093.header(t2=bool(kw.get("t2"))),  # kw["filt"] is always a dict of filter kwargs
                                s093.filters(**kw.get("filt", {})),  # type: ignore[arg-type]
                                *kids])


def loading(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    body = [wf.skeleton_rows(N, wf.TABLE_W), wf.skel_block("totals bar", wf.TABLE_W, 32),
            wf.hidden("status (polite live region)", k.ui("Loading trades"), 360)]
    return (k.frame(fid, [page(body)], wf.SCREEN_W, "SCR-093 loading — static skeleton rows (reduced motion), no "
                                                    "spinner, no totals until the read returns"),
            k.frame_block(fid, ["`14` SCR-093 States: loading; the totals bar is a skeleton, never a partial sum"]))


def empty(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rs = k.trades(frm=SEP[0], to=SEP[1])
    assert not rs
    first = min(t.closed for t in k.JOURNAL)
    rng = k.day_range(*SEP)
    body = [wf.empty_state(k.deck("empty.range"), k.ui(f"The journal starts with the first closed trade, "
                                                       f"{first.day} {first.strftime('%b %Y')}",
                                                       "`14`: empty state tied to recording / trading start"),
                           wf.TABLE_W)]
    k.derive(f"empty: {len(rs)} LIVE trades close in {rng}; the first close in the journal is {k.dt_long(first)}")
    return (k.frame(fid, [page(body, filt={"range": rng})], wf.SCREEN_W,
                    "SCR-093 empty — a range before the first trade; the empty state names where the journal starts"),
            k.frame_block(fid, [f"Range {rng}: 0 trades (derived)"], wds=["WD-1"]))


def partial(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rs = k.trades(frm=EARLY[0], to=EARLY[1])
    words = k.cat("chart context unavailable", "### SCR-093")
    extra = {t.no: words for t in rs if t.context == "not recorded"}
    rng = k.day_range(*EARLY)
    k.derive(f"partial: {len(extra)} of the {len(rs)} trades closing {rng} opened before recording began "
             f"({k.dt_long(k.RECORDING_FROM)}) and carry '{words}'")
    body = [wf.journal_table(rs[:N + 2], extra=extra),
            wf.totals_bar(rs, "LIVE", f"{rng} · all accounts", wf.TABLE_W)]
    return (k.frame(fid, [page(body, filt={"range": rng})], wf.SCREEN_W,
                    "SCR-093 partial — trades whose market context predates recording say so in the row; every "
                    "figure stays"),
            k.frame_block(fid, ["`14` SCR-093 States: partial (context predates recording)"], wds=["WD-6"]))


def reconciling(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rs = s093.rows()
    words = k.cat("fills still arriving", "### SCR-093")
    extra = {t.no: f"reconciling — {words}" for t in k.GROUP}
    note = wf.notice("pending", k.ui("Reconciling"), words.capitalize(), wf.TABLE_W, name="CMP-028 notice")
    k.derive(f"reconciling: the group {k.LOSER.group}'s {len(k.GROUP)} legs closed at {k.dt_long(k.LOSER.closed)} "
             "and are drawn as the moment their fills are still arriving")
    body = [note, wf.journal_table(rs[:N], extra=extra), wf.totals_bar(rs, "LIVE", f"{s093.RANGE_WORDS} · all "
                                                                                    "accounts", wf.TABLE_W)]
    return (k.frame(fid, [page(body)], wf.SCREEN_W, "SCR-093 reconciling — fills still arriving: the rows "
                                                    "affected say so; the notice names the state"),
            k.frame_block(fid, ["`14` SCR-093 States: reconciling (fills still arriving)"], wds=["WD-9"]))


def no_match(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    sym, tag = k.no_match_filter()
    k.derive(f"no-match: symbol {sym} with tag {tag} has 0 LIVE trades in {s093.RANGE_WORDS} (the first empty pair "
             "in a fixed order)")
    body = [wf.empty_state(k.deck("empty.filter"), None, wf.TABLE_W, actions=[wf.btn(k.ui("Clear filters"))])]
    return (k.frame(fid, [page(body, filt={"symbol": sym, "tag": tag})], wf.SCREEN_W,
                    "SCR-093 no-match — filters that match no trade; distinct from an empty range"),
            k.frame_block(fid, ["`13` / `17` add 'No trades match filter' (memo BQ-7)"]))


def error(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    body = [wf.notice("danger", k.ui("Trades could not be loaded", "no error string in §7.1"), None, wf.TABLE_W,
                      actions=[wf.btn(k.ui("Retry"), glyph="refresh")], name="CMP-028 notice")]
    k.spec_gap("SCR-093 / SCR-094 / SCR-095 / SCR-096 error: §7.1 has no error string; the frames draw a kit label "
               "(E41-D02 #1018 / E41-D03 #1081 write it)")
    return (k.frame(fid, [page(body)], wf.SCREEN_W, "SCR-093 error — the read failed; no stale totals are shown"),
            k.frame_block(fid, ["memo §7 frame list: error (BQ-7)"]))


def viewer(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rs = k.trades(accounts=VIEWER_ACCOUNTS)
    reason = k.memo("Your role can't write in the journal.")
    rsn = k.hbox("CMP-079 reason", [k.icon("lock", "locked", k.TEXT_2, k.ICON_SM),
                                    k.text("words", reason, k.BODY, k.TEXT_1)],
                 {"gap": k.INSET_XS, "padX": k.INSET_SM, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                  "strokeAlign": "inner", "radius": k.R_CONTROL, "fill": k.OVERLAY}, h=28,
                 note="CMP-079 visible reason, key rbac.permission (E09-D09 §3.1)")
    acct = ", ".join(VIEWER_ACCOUNTS)
    bulk = k.hbox("dashed · bulk-tag bar · T2", [
        k.text("count", "0 selected", k.BODY_STRONG, k.TEXT_2), wf.select(None, "late-entry", 200, t2=True),
        wf.btn(k.ui("Apply tag"), t2=True), wf.btn(k.ui("Clear selection"), t2=True)],
        {"gap": k.INSET_SM, "padX": k.INSET_SM, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
         "strokeAlign": "inner"}, w=wf.TABLE_W, h=44,
        note="CMP-169 TagEditor bulk mode, T2: visible, lock, aria-disabled (E09-D09 §2.1)")
    k.fallback("t2stroke")
    body = [rsn, bulk, wf.journal_table(rs[:N], t2=True),
            wf.totals_bar(rs, "LIVE", f"{s093.RANGE_WORDS} · {acct}", wf.TABLE_W)]
    k.derive(f"Viewer: granted {acct}; {len(rs)} LIVE trades; ungranted Account C is absent from the data and the "
             "account filter (scope, not a control)")
    pg = wf.page("/journal", [s093.header(t2=True), s093.filters(account=acct), *body])
    return (k.frame(fid, [pg], wf.SCREEN_W, "SCR-093 viewer-write-disabled — T2: 'Manage tags', the bulk-tag bar and the row "
                                            "checkboxes keep their labels with the CMP-019 lock and a visible reason; "
                                            "they stay in the Tab order with aria-disabled"),
            k.frame_block(fid, ["Drawn on this board by the board plan although memo §0 lists it as 'not drawn — the "
                                "text is binding': the boards PR updates that §0 line", "Reason key rbac.permission "
                                "with the §3.2 verb 'write in the journal' (memo §7.1 note); never color.text."
                                "disabled or opacity.disabled"], wds=["WD-13"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((loading, empty, partial, reconciling, no_match, error, viewer),
                                    k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    wf.run(NN, frames(), 2)
