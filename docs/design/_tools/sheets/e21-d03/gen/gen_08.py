"""Board 08 cost-save-t2: SCR-051/cost-unmeasured (§3.4) and /save-gated (§8.4, T2 2a), with the W-33 leg."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 8


def unmeasured() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/cost-unmeasured"
    d = ui.Dlg(measured=())
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        "No measurement on this device yet: W-6 and one W-8 line per tier (R-6: no figure by estimate); the panel is "
        "text, not a Tab stop",
        "The source of the measured figure is G-1 (E21-K01 #603, E21-S09 #709); K04's reference-host figures are not "
        "shown"])


def gated() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/save-gated"
    w32 = k.W("W-32", user=k.VIEW_AS_USER)
    d = ui.Dlg(save="t2", notice=w32, focus="save",
               extra=[ui.announce(w32, how="polite, on each Enter / Space on Save (G-T2.3, R-5)")])
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        "Viewing as a synthetic user: Save is T2 in rendering 2a (R-3) — the CMP-019 lock leads the label, "
        "color.text.tertiary on color.surface.raised + a color.border.default hairline, aria-disabled=\"true\", never "
        "disabled, never opacity.disabled; CMP-079 wraps it",
        "The footer carries the one notice Save's aria-describedby points at (G-T2.5, adapted); the view-as leg first "
        "(E09-D09 order), W-33 next (the specimen)",
        "W-32 is the key rbac.view_as, E09-D09 §3.1's words verbatim (D09E09:95), {user} filled with the synthetic "
        "viewing-as user",
        "The fields stay operable and the preview works; gated Save writes and applies nothing and never validates "
        "(C-12); Enter / Space re-shows the notice"])


def leg() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = k.SPEC08
    ft = ui.footer(ui.Dlg(save="t2", notice=k.W("W-33")))
    fr = k.marker_frame(fid, [
        k.text("lead", k.ui("Without workspaces:write (the second leg): the footer", "board-marker caption"), k.LABEL,
               k.TEXT_2), ft], ui.DLG_W + 48)
    return fr, k.frame_block(fid, [
        "W-33 rbac.permission with D09E09:114's verb \"save workspaces\"; if C-7's user-settings store holds, the leg "
        "is settings:write, \"change settings\" (D09E09:115)"])


if __name__ == "__main__":
    ui.run(NN, [unmeasured(), gated(), leg()], 2, board_lines=[
        "Owner walkthrough item 1 (§18), with board 01: unmeasured reads \"not yet measured\", never a guess (H-7)"])
