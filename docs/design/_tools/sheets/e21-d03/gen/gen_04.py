"""Board 04 ladder-centring: SCR-051/ladder (§5) — row height, the three centring behaviours (M AD-8), the show
toggles."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 4


def ladder() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/ladder"
    d = ui.Dlg(tab="Ladder", focus="centre lock")
    c, ln = k.RANGES["Row height"]
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        f"Row height (px) 24, range {k.plain(c[1])} (§9.1 L{ln}; C-2, A-2: the catalogue's 18 px and 10–23 px dropped)",
        "Centring (M AD-8): one three-option CMP-006 — Auto-follow (default), Free scroll, Centre lock with W-16 as its "
        "description line (M K3); it replaces \"centre lock [x] auto-follow\" (C-1, A-1)",
        "Show: Your orders, Position, Prints (the tape-print overlay, checklist item 7), Cumulative depth, Queue "
        "estimate (estimated) — off by default; \"(estimated)\" in full (C-9, A-5)",
        "Visual keys (R-2): applied in one frame on Save, the frame buffer kept"])


if __name__ == "__main__":
    ui.run(NN, [ladder()], 1, board_lines=[
        "AD-8 (§14.2): satisfied — §5 Centring, three options, this board",
        "Owner walkthrough item 5 (§18): does \"Centre lock\" warn enough about its motion"])
