"""Board 08 own-orders-detectors: §8 Your orders (single, aggregate, expanded), the position marker, the pulled
mark and its reveal, SCR-050/detector-chips."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 8


def chips() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/detector-chips"
    p = ui.P(chips=True)
    return ui.panel(fid, p), k.frame_block(fid, [
        "The strip: CMP-134 chips with \"(estimated)\" in full (W-14, W-15; the ASCII's \"(est.)\" is C-5); no label "
        "names an intent",
        f"Your orders, one fixed column (M AD-5), text first, glyph second: single {k.price0(k.SINGLE_BUY_AT)} and "
        f"{k.price0(k.SINGLE_SELL_AT)}, the aggregate at {k.price0(k.AGG_AT)} (W-23); the position marker W-25 in "
        f"the Price cell at {k.price0(k.POSITION_AT)}",
        f"The pulled mark: a hatch on the heatmap only (R-1, M AD-6) at {k.price0(k.PULL_PRICE)}, column "
        f"{k.PULL_COL + 1} of {k.COLS}"])


def expanded() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/detector-chips · aggregate expanded"
    p = ui.P(chips=True, expanded=True)
    k.derive(f"W-24: the queue ahead of {k.ACCOUNTS[0]}'s order at {k.price0(k.AGG_AT)} = {k.qty1(k.AHEAD)} (the "
             f"level's {k.qty1(k.AHEAD + k.BEHIND + k.Decimal('1.2'))} less the own 1.2 and the {k.qty1(k.BEHIND)} "
             "behind)")
    return ui.panel(fid, p, markers=[ui.acc_name("cell name", k.Wf("W-23", {}).replace(" · ", ", "))]), \
        k.frame_block(fid, [
            "Enter on the aggregate's Your-orders cell expands it per account; focus moves to the first account row; "
            "Esc collapses it and focus returns to the cell; the focused row never moves (the rows below reflow)",
            "The queue estimate W-24 with CMP-227 (the word in full); its field reaches no client frame (G-3, "
            "E21-S06 #706)", "The pane keeps the locked axis: a blank band beside the account rows (kit reading)"])


def reveal() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/detector-chips · reveal"
    p = ui.P(chips=True)
    r = k.row_of(k.PULL_PRICE, "bid")
    return ui.panel(fid, p, reveal_row=r), k.frame_block(fid, [
        f"The reveal for {k.price0(r)} (Shift+Enter, PROPOSED until E21-D06 rules the key: C-4, OQ-2): the row's "
        "history as a windowed table; the pulled level named in words, \"pulled 18.0 (estimated)\"",
        "Focus on the reveal's heading; Esc returns focus to the row (the opener)"])


if __name__ == "__main__":
    ui.run(NN, [chips(), expanded(), reveal()], 3)
