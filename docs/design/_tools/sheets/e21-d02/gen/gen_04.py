"""Board 04 loading-empty: SCR-050/loading and SCR-050/empty-no-recording, the Owner CTA and the sentence form
(§4)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 4


def loading() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/loading"
    p = ui.P(state="loading")
    return ui.panel(fid, p, markers=[ui.announce(k.W("W-30"), how="polite, once (the panel's role=\"status\")")]), \
        k.frame_block(fid, ["Skeleton bars color.surface.raised, static (motion is E21-D05's); the grid "
                            "aria-busy=\"true\" and no rows; the header controls present and focusable",
                            "The footer and the row items stay T2 on the notice (R-3, §5)"])


def empty(owner: bool) -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/empty-no-recording" + ("" if owner else " · sentence form")
    p = ui.P(state="empty-owner" if owner else "empty-other")
    lines = ["CMP-026 `recording-not-started` (D05E16:236–239, D10E08:363): W-16 heading, W-17 cause"]
    lines.append("Owner: the W-19 CTA, initial focus on it" if owner else
                 "Not the Owner: the sentence form W-18 (rbac.owner_only) alone, with no glyph and no control; "
                 "initial focus on the heading (tabindex=\"-1\")")
    return ui.panel(fid, p), k.frame_block(fid, lines)


if __name__ == "__main__":
    ui.run(NN, [loading(), empty(True), empty(False)], 3)
