"""Board 03 colour-cvd-greyscale: SCR-051/colour, /cvd-preview, /preview-unavailable (§4, §2.3, §12.1); the board is
also exported through cvd_sim.py's greyscale (and the simulations) for the reading of §12."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 3


def ramp_line(theme: str) -> str:
    c, ln = k.RAMP_ROWS[theme]
    return (f"§12.1 L{ln} {theme}: lowest stop {k.plain(c[1])} {c[2]}:1; ΔE deuteranopia {c[3]}, protanopia {c[4]}, "
            f"tritanopia {c[5]}; CVD set lowest {k.plain(c[6])} {c[7]}:1, smallest ΔE {c[8]}")


def colour() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/colour"
    d = ui.Dlg(tab="Colour", focus="tablist", extra=[ui.under_tile(ui.hidden_name(ui.tile_name()), legend_h=48)])
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        "Colour scale log / linear and gamma; Scale (scaleMode) Adaptive / Locked; the stops (anchors) as a gradient "
        "bar with one handle and one CMP-008 input per stop (C-10); Set (palette) Standard / CVD-safe; Convention — "
        "#504's names, \"if #504 merges as is\" (R32 R6); no free bid / ask swatches (C-15)",
        f"Stops at the default tier, from the seeded tile (adaptive, log): "
        f"{', '.join(k.size_fmt(a) for a in k.stops())} BTC",
        "Colour keys are visual (R-2): one frame, no rebuild wording; the tablist holds focus (automatic activation)",
        "CMP-113 under the tile states the convention in words and the scale with numeric anchors (M AD-10); E21-D04's"])


def cvd() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/cvd-preview"
    nm = ui.tile_name(cvd=True, sim="deuteranopia")
    d = ui.Dlg(tab="Colour", cvd=True, sim=k.S("Deuteranopia"), focus="sim",
               extra=[ui.under_tile(ui.hidden_name(nm), legend_h=48)])
    k.fallback("cvd-sim")
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        "Set CVD-safe (color.cvd.heatmap.*) and the simulation Deuteranopia (W-34): the simulation filters the tile "
        "only, never the running panel; the tile's name gains \"simulated deuteranopia\"",
        ramp_line("dark"),
        "Reading (heuristic, §12.1): the standard pair bid.3 / ask.3 sits below a just-noticeable difference under "
        "deuteranopia, so the CVD-safe set is the choice when colour must carry the side; the words Ask / Bid carry "
        "it in every set"])


def unavailable() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/preview-unavailable"
    d = ui.Dlg(tab="Colour", tile_off=True)
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        "The tile cannot render: W-31 in the tile (`15`:2949), the fields unaffected; it keeps no spinner and is not "
        "a Tab stop"])


if __name__ == "__main__":
    b = k.BOARDS[NN]
    ui.run(NN, [colour(), cvd(), unavailable()], 2, board_lines=[
        f"Exports: {b.export}, then docs/design/_tools/cvd_sim.py's greyscale render of it (§0: the greyscale "
        f"export) and its deuteranopia / protanopia / tritanopia renders for the §12.1 reading",
        ramp_line("light"), ramp_line("high-contrast"),
        "Owner walkthrough item 4 (§18): compare the standard and CVD-safe sets in the simulated tile"])
