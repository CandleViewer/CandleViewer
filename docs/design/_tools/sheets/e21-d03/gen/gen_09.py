"""Board 09 shed-row-restore: SCR-153/depth-shed, /depth-pinned, /depth-restored (§11; AC 2), 200 → 50; dark, exported
again under light (the twin) and through cvd_sim.py's greyscale."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 9


def pair(name: str) -> str:
    row = next(c for _i, c in k.PAIRS if k.plain(c[0]) == name)
    return f"§12.2 {k.plain(row[0])} ≥ {row[1]}: dark {row[2]}, light {row[3]}, hc {row[4]}"


def shed() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-153/depth-shed"
    return ui.shed_window(fid, "shed"), k.frame_block(fid, [
        "Frame time over budget for 5 s: the tier stepped 200 → 50 (US-DOM-005, `11`:2060–`11`:2062): one CMP-092 info "
        "row per episode in the banner slot (after E15-D12's rows; none in this session), not dismissible while the "
        "shed holds",
        "W-22 cause and loss, W-23 what still works, W-24 restore, the W-25 pin (CMP-001 secondary, the same state as "
        "the dialog's W-15 and D02's pin); never the reduced-profile wording (`14`:3116)",
        "W-35's earlier steps (cadence, trail) are not drawn: their order and values are E21-T07's (G-5)",
        "W-22 polite once through the banner's persistent role=\"status\" (C-11); D02's W-21 stays the panel's visible "
        "notice and is not re-announced (C-5); degraded.entered {cause, sheddedFeatures} fires here (§14.1)"])


def pinned() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-153/depth-pinned"
    return ui.shed_window(fid, "pinned"), k.frame_block(fid, [
        "Pin pressed while still over budget: the tier is restored and kept (200), the row stays and reads W-26 with "
        "no pin button (`11`:2063–`11`:2065); the pressed pin leaves the row, so focus moves to the row's message "
        "(tabindex=\"-1\")",
        "W-26 polite once; flap guard: two announcements at least 5 s apart, a change inside the window replaces the "
        "queued one",
        "In a view-as session, or without workspaces:write, the W-25 pin still restores the tier but holds for this "
        "session only: nothing is written to the pane's layout (C-12; E17-D03 G3)"])


def restored() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-153/depth-restored"
    return ui.shed_window(fid, "restored"), k.frame_block(fid, [
        "Load allows: the tier restored to 200 and the row removed; focus on the pin button or the pinned message "
        "moved to the panel's depth control before the row went",
        "W-27 polite once through the banner's region, so a removed row is still heard; degraded.exited {durationMs} "
        "fires (`14`:3117)"])


if __name__ == "__main__":
    b = k.BOARDS[NN]
    ui.run(NN, [shed(), pinned(), restored()], 2, board_lines=[
        f"Exports: {b.export}, its light twin {b.export_light}, and docs/design/_tools/cvd_sim.py's greyscale render "
        f"(AC 2: the meaning is in the words and the info glyph)",
        *(pair(p) for p in ("color.text.primary on color.status.info.subtle",
                            "color.text.secondary on color.status.info.subtle",
                            "color.status.info.strong on color.status.info.subtle",
                            "color.focus.ring on color.status.info.subtle")),
        "AD-7 (§14.2): satisfied — the §11 row, W-21, W-22, the 200 default (with board 02)",
        "Owner walkthrough item 8 (§18): read the greyscale export — what was lost, why, how to keep the depth"])
