"""The frame registry: §0 frame id -> builder(theme) -> (frame node, annotation lines); build_board(nn)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e19d05kit as k  # noqa: E402
import frames as F  # noqa: E402

Builder = Callable[[str], tuple[k.Node, list[str]]]
BUILDERS: dict[str, Builder] = {
    "SCR-038/motion-cases-dark": lambda th: F.f_cases("SCR-038/motion-cases-dark"),
    "SCR-038/suppression-matrix-dark": lambda th: F.f_matrix("SCR-038/suppression-matrix-dark"),
    "SCR-038/suppression-matrix-light": lambda th: F.f_matrix("SCR-038/suppression-matrix-light"),
    "SCR-038/flash-audit-dark": lambda th: F.f_flash("SCR-038/flash-audit-dark"),
    "SCR-038/announcement-timeline-dark": lambda th: F.f_announce("SCR-038/announcement-timeline-dark"),
    "SCR-038/poc-jump-dark": lambda th: F.f_poc_jump("SCR-038/poc-jump-dark"),
    "SCR-038/poc-jump-light": lambda th: F.f_poc_jump("SCR-038/poc-jump-light"),
    "SCR-038/developing-final-dark": lambda th: F.f_developing_final("SCR-038/developing-final-dark"),
    "SCR-038/developing-final-light": lambda th: F.f_developing_final("SCR-038/developing-final-light"),
    "SCR-038/growth-120-dark": lambda th: F.f_growth_120("SCR-038/growth-120-dark"),
    "SCR-038/growth-5000-dark": lambda th: F.f_growth_5000("SCR-038/growth-5000-dark"),
    "SCR-038/developing-va-dark": lambda th: F.f_developing_va("SCR-038/developing-va-dark"),
    "SCR-038/poc-tie-cap-dark": lambda th: F.f_tie_cap("SCR-038/poc-tie-cap-dark"),
    "SCR-038/rebucket-dark": lambda th: F.f_rebucket("SCR-038/rebucket-dark"),
    "SCR-038/period-change-dark": lambda th: F.f_period_change("SCR-038/period-change-dark"),
    "SCR-038/feed-break-dark": lambda th: F.f_feed_break("SCR-038/feed-break-dark"),
    "SCR-038/visible-range-pan-dark": lambda th: F.f_vr_pan("SCR-038/visible-range-pan-dark"),
    "SCR-038/visible-range-settle-dark": lambda th: F.f_vr_settle("SCR-038/visible-range-settle-dark"),
    "SCR-038/npoc-fade-dark": lambda th: F.f_npoc_fade("SCR-038/npoc-fade-dark"),
    "SCR-038/npoc-tested-cut-dark": lambda th: F.f_npoc_tested("SCR-038/npoc-tested-cut-dark"),
    "SCR-038/overlay-show-dark": lambda th: F.f_overlay_show("SCR-038/overlay-show-dark"),
}


def _undrawn_down_forms(nn: int) -> str | None:
    """Kit-check W-1 / W-1b: no board has a POC-down case, so the down forms of D05 W-1 / W-1b are declared, not drawn."""
    w1 = k.S("POC {price} ▼ {n} rows")
    w1b = k.S("POC moved down {n} rows")
    where = f"§8.3 {k.SL('POC {price} ▼ {n} rows', 'spec').replace('spec ', '')}"  # "§8.3 L418" (drawn as "§8.3 Lspec L418")
    if nn == 2:
        why = ("the board's POC moves up (3 rows, then 1), so the legend and the appended announcement show the up "
               "forms only")
        what = f"D05 W-1's down form \"{w1}\" as a legend row and D05 W-1b's down form \"{w1b}\""
    elif nn == 5:
        why = ("the tied POC's two flips appear as text in the intro line only, never as a legend row, and no "
               "announcement is drawn here")
        what = f"D05 W-1's down form \"{w1}\" as a legend row and D05 W-1b's down form \"{w1b}\""
    elif nn == 10:
        why = "the timeline's jump run moves the POC up, so the appended words show the up form only"
        what = f"D05 W-1b's down form \"{w1b}\""
    else:
        return None
    return (f"Not drawn — the text is binding ({where}): {what}; {why}; the down forms are the same strings with the "
            f"glyph and verb swapped and \"up\" / \"down\" as hidden text")


def build_board(nn: int, *, board_lines: tuple[str, ...] = ()) -> tuple[Path, Path, Path]:
    b = k.BOARDS[nn]
    k.NOTES.reset()
    nodes, blocks = [], []
    for fid in b.frames:
        th = k.frame_theme(fid, b.theme)
        n, lines = BUILDERS[fid](th)
        nodes.append(n)
        blocks.append(k.frame_block(fid, th, (n["w"], n["h"]), lines))
    nd = _undrawn_down_forms(nn)
    if nd:
        k.reading(nd)
        board_lines = (*board_lines, nd)
    return k.build(nn, nodes, blocks, board_lines=board_lines)
