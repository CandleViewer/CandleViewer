"""Board 06 strip-hidden-restore: SCR-030/strip-AllRowsOff and SCR-030/strip-restore-menu (§5)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 6


def off() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-030/strip-AllRowsOff"
    p = ui.P(strip=False, focus_menu_btn=True, markers=[ui.announce(k.W("W-24"))])
    return ui.chart(fid, p), k.frame_block(fid, [
        "The strip's band is gone and the volume sub-pane moves up; nothing else changes (§5)",
        f"Hiding is the explicit action \"{k.W('W-11')}\" (the pane menu, SCR-033's footer), distinct from "
        f"deselecting the last row (E20-S02; MEMO C10); its gear goes with it",
        "Focus goes to the chart pane's menu button (R-7's fallback, E47-D04:122), never the page body; W-24 once"])


def restore() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-030/strip-restore-menu"
    p = ui.P(strip=False, pane_menu=True, markers=[ui.note_marker(k.ui(
        "on press: the last row set and order return; focus returns to the chart pane's menu button",
        "board-marker note")), ui.announce(k.W("W-23"))])
    return ui.chart(fid, p), k.frame_block(fid, [
        f"The pane menu open: \"{k.W('W-10')}\" first in the Deep Stats group; one press restores the last row set "
        f"and order (§5; 11:1901)",
        f"While the strip shows, the item reads \"{k.W('W-11')}\""])


if __name__ == "__main__":
    ui.run(NN, [off(), restore()], 2)
