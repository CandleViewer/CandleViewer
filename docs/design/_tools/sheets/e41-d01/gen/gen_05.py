"""Board 05 scr094-context-states: SCR-094's context pane loading, bar-only, context-not-recorded, pruned (bar
replay) and error — each in words, never a spinner (WD-6)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import s094  # noqa: E402
import wf  # noqa: E402
from wf import k  # noqa: E402

NN = 5


def newest(ctx: str) -> k.Trade:
    return next(t for t in k.trades() if t.context == ctx)


def page(t: k.Trade, right: list[k.Node | None]) -> k.Node:
    w = s094.COL_W
    left = k.vbox("left column", [s094.facts(t), s094.fills_table(t)], {"gap": k.STACK_LG}, w=w)
    return wf.page("/journal/:tradeId", [s094.header(t), k.hbox("columns", [
        left, k.vbox("right column", right, {"gap": k.STACK_SM}, w=w)], {"gap": k.INSET_XL, "align": "start"},
        w=wf.PAGE_W - 32)])


def card(title: str, kids: list[k.Node | None]) -> k.Node:
    w = s094.COL_W
    return k.vbox(f"context card · {title}", [k.text("title", k.ui("Market context"), k.HEADING_SM, k.TEXT_1), *kids],
                  {"pad": k.INSET_MD, "gap": k.STACK_SM, "fill": k.RAISED, "radius": k.R_CARD}, w=w)


def loading(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    t = k.LOSER
    w = s094.COL_W - 24
    body = card("loading", [wf.skel_block("context pane", w, 240),
                            wf.hidden("status (polite live region)", k.ui("Loading market context"), w)])
    return (k.frame(fid, [page(t, [body])], wf.SCREEN_W, "SCR-094 loading — the pane is a static skeleton; the "
                                                         "trade's own facts and fills are already shown"),
            k.frame_block(fid, ["`14` SCR-094 Performance: the context window renders in ≤ 1.5 s, else a clear "
                                "state, never a spinner"], wds=["WD-6"]))


def bar_only(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    t = newest("bar-only")
    w = s094.COL_W - 24
    a, b = k.TICK_GAP
    gap = f"ticks missing {a.strftime('%H:%M')}–{b.strftime('%H:%M')} UTC"
    k.derive(f"bar-only: #{t.no} ({k.dt_long(t.opened)} → {t.closed.strftime('%H:%M:%S')}) spans the recorder's "
             f"tick gap {a.strftime('%H:%M')}–{b.strftime('%H:%M')} on {a.day} Oct; bars exist throughout")
    body = card("bar-only", [wf.notice("info", k.deck("context.bars"), None, w), wf.context_chart(t, w, band=(a, b, gap))])
    return (k.frame(fid, [page(t, [body])], wf.SCREEN_W, "SCR-094 bar-only — part of the trade has bars but no "
                                                         "ticks: excursions are bar-derived and the pane says so"),
            k.frame_block(fid, ["The MAE / MFE rows inherit the bar-derived flag (memo A-2: a bar-derived flag on "
                                "CMP-166)"], wds=["WD-6"]))


def not_recorded(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    t = newest("not recorded")
    w = s094.COL_W - 24
    k.derive(f"not recorded: #{t.no} opened {k.dt_long(t.opened)}, before recording began "
             f"{k.dt_long(k.RECORDING_FROM)}")
    body = card("not recorded", [wf.notice("info", k.deck("context.none"), None, w)])
    return (k.frame(fid, [page(t, [body])], wf.SCREEN_W, "SCR-094 context-not-recorded — a final state in words; "
                                                         "the fills and prices are listed beside it"),
            k.frame_block(fid, ["`14` SCR-094 checklist: 'context not recorded' state"], wds=["WD-6"]))


def pruned(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    t = newest("pruned")
    w = s094.COL_W - 24
    k.derive(f"pruned: #{t.no} opened {k.dt_long(t.opened)}; ticks before {k.dt_long(k.TICKS_FROM)} are pruned "
             "(synthetic retention), bars kept")
    body = card("pruned", [wf.notice("info", k.deck("context.pruned"), None, w,
                                     actions=[wf.btn(k.ui("Open bar replay"))]), wf.context_chart(t, w)])
    return (k.frame(fid, [page(t, [body])], wf.SCREEN_W, "SCR-094 pruned — recorded ticks are gone, bars remain: "
                                                         "the pane draws bars and offers bar replay"),
            k.frame_block(fid, ["Replay from bars: E26's replay surfaces own the bar replay itself"], wds=["WD-6"]))


def error(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    t = k.LOSER
    w = s094.COL_W - 24
    body = card("error", [wf.notice("danger", k.ui("Market context could not be loaded", "no error string in §7.1"),
                                    None, w, actions=[wf.btn(k.ui("Retry"), glyph="refresh")])])
    return (k.frame(fid, [page(t, [body])], wf.SCREEN_W, "SCR-094 error — the context read failed; the trade's "
                                                         "own record stays"),
            k.frame_block(fid, ["memo §7 frame list: error"], wds=["WD-6"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((loading, bar_only, not_recorded, pruned, error), k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    wf.run(NN, frames(), 2)
