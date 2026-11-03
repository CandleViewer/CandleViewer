"""Board 04 scr094-default: SCR-094 for yesterday's loser (fills, excursions, attribution, group siblings, notes,
tags with an auto tag, the replay link)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import s094  # noqa: E402
import wf  # noqa: E402
from wf import k  # noqa: E402

NN = 4


def default(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    t = k.LOSER
    w = s094.COL_W
    left = k.vbox("left column", [s094.facts(t), s094.fills_table(t), s094.attribution(t)], {"gap": k.STACK_LG}, w=w)
    summary = (f"{k.ui('Market context')}: 5-minute bars; entry {k.price(t.entry, t.symbol)}, SL "
               f"{k.price(t.stop, t.symbol)}, MFE {k.price(t.mfe, t.symbol)} at {t.mfe_at.strftime('%H:%M:%S')}, "
               f"exit at the SL {t.closed.strftime('%H:%M:%S')} UTC")
    pane = wf.chart_card(k.ui("Market context"), wf.context_chart(t, w - 24), summary, w)
    right = k.vbox("right column", [pane, s094.siblings(t), s094.notes_tags(t)], {"gap": k.STACK_LG}, w=w)
    pg = wf.page("/journal/:tradeId", [s094.header(t), k.hbox("columns", [left, right], {"gap": k.INSET_XL,
                                                                                         "align": "start"},
                                                               w=wf.PAGE_W - 32)])
    inset = k.vbox("inset · viewer-write-disabled", [
        k.text("inset title", "Inset: SCR-094 as a Viewer sees it (write-disabled, T2): the note field and the tag "
                              "editor stay visible with the CMP-019 lock, a dashed color.border.default stroke and the "
                              "reason; they stay in the Tab order with aria-disabled", k.CAPTION, k.TEXT_3,
               w=w - 16),
        s094.notes_tags(t, t2=True, w=w - 16)], {"pad": k.INSET_SM, "gap": k.STACK_SM, "stroke": k.BORDER_SUBTLE,
                                       "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL},
        w=w, note="WD-13 T2 inset (E09-D09 §2.1): tag editor and note, viewer role")
    pg["kids"].append(inset)
    k.derive(f"opened from SCR-093: yesterday's loser #{t.no} (Account A's leg of {t.group}), stopped at "
             f"{k.rfmt(t.r)}")
    return (k.frame(fid, [pg], wf.SCREEN_W, "SCR-094 default — a page (R-181), not a drawer: fills, R, MAE / MFE "
                                            "with units, who acted, the group's siblings, the context pane with its "
                                            "text summary, notes and tags (the auto tag marked 'auto', removable)"),
            k.frame_block(fid, ["`14` SCR-094 checklist: context chart, full fill list, attribution, notes and tags, "
                                "R / MAE / MFE / time in trade with units, replay link — all drawn; 'context not "
                                "recorded' on board 05", "Footprint: the hi-fi pane (E41-D03 #1081) adds it; the "
                                "lo-fi draws bars only"], wds=["WD-6", "WD-8", "WD-9", "WD-12", "WD-13"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    f, b = default(k.BOARDS[NN].frames[0])
    return [f], [b]


if __name__ == "__main__":
    wf.run(NN, frames(), 1)
