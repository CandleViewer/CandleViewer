"""Board 06 detectors: SCR-051/detectors (§7)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 6


def detectors() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/detectors"
    d = ui.Dlg(tab="Detectors", focus="big")
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        "Iceberg, Stop-run and Absorption, each (estimated), on by default; Sensitivity Medium — the labels, the word "
        "and the semantics are E25's (T OOS): this tab draws the controls only",
        "W-28 with its unit, empty = off: a PROPOSED field, no story or contract defines it (G-2, E21-T04 #710)",
        "CMP-136 is not drawn (C-8, E21-S07 #707)"])


if __name__ == "__main__":
    ui.run(NN, [detectors()], 1)
