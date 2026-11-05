"""Board 06 resyncing-depth-shed: SCR-050/resyncing (the scrim, then the W-12 tag) and SCR-050/depth-shed (§4,
§11.1)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 6


def resync(rebuilt: bool) -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/resyncing" + (" · rebuilt" if rebuilt else "")
    p = ui.P(state="rebuilt" if rebuilt else "resyncing")
    ann = ui.announce(k.W("W-29") if rebuilt else k.W("W-28"), how="polite, once on exit" if rebuilt else
                      "polite, once on entry")
    lines = (["W-12 \"Book rebuilt\" is a visual tag only (D02E17:258); W-29 polite on exit; focus is on the same "
              "price row, or the mark row if that price left the extent"] if rebuilt else
             ["The scrim is visual only: the grid takes aria-busy=\"true\", rows stay focusable and read-only, focus "
              "never moves; the notice leads with feed.resyncing (W-11)",
              "SR-038: resyncing never drops the arm (D01E17:203), so the header text state and the feed.resyncing "
              "notice alone carry it"])
    return ui.panel(fid, p, markers=[ann]), k.frame_block(fid, lines)


def shed() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/depth-shed"
    p = ui.P(state="shed", tier=50)
    return ui.panel(fid, p, markers=[ui.announce(k.W("W-21"))]), k.frame_block(fid, [
        "Load shedding stepped the tier 200 → 50: levels 51–200 hidden; the notice stays until the tier is restored "
        "or pinned (no timeout); the pin a native button named \"Pin depth 200\"",
        "dom.depth_changed {from: 200, to: 50, cause: shed} and degraded.entered surface on this notice (§11.1); "
        "SCR-153's banner is E21-D03's; the shed order cadence → trail → depth is E21-T07 #711's (M C6)",
        "Focus stays on its price row, or the mark row if that price left the extent"])


if __name__ == "__main__":
    ui.run(NN, [resync(False), resync(True), shed()], 3)
