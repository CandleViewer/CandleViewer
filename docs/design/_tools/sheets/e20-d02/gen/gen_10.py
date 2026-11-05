"""Board 10 alignment-3-zooms: SCR-030/strip-align-typical, -dense, -extreme (§8)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 10
DENSITIES = (("SCR-030/strip-align-typical", 128), ("SCR-030/strip-align-dense", 400),
             ("SCR-030/strip-align-extreme", 800))  # ~120, ~400, ~800 (E20.json:207)
SAME = "13:58"  # kit: the bar whose x(t) left edge is marked at every density, with the window's middle bar


def frame(fid: str, n: int) -> tuple[k.Node, tuple[str, list[str]]]:
    pw = ui.PLOT_W / n
    p = ui.P(n=n, edges=(k.window(n)[n // 2].t, SAME), volume=n <= 128)
    k.derive(f"{fid}: {n} visible bars over {ui.PLOT_W} px = {pw:.2f} px a bar (x(t) = {ui.PLOT_X} + i × {pw:.2f})")
    lines = [f"{n} visible bars, {pw:.2f} px a column: every column's left edge and width come from the chart "
             f"engine's x(t) for that bar; the strip lays out nothing itself (MEMO C7; E20-T04 decides how)",
             f"Below the {k.FLOOR_PX} px seed floor the cells are collapsed (§4.1)"]
    if pw < ui.RUNS_BELOW:
        lines.append(f"At {pw:.2f} px adjacent equal glyphs are pixel-contiguous: drawn as runs (kit fallback)")
    if n > 128:
        lines.append("The volume sub-pane is unchanged; its columns are not drawn at this density (kit economy)")
    return ui.chart(fid, p), k.frame_block(fid, lines)


if __name__ == "__main__":
    ui.run(NN, [frame(f, n) for f, n in DENSITIES], 2, board_lines=[
        f"NFR: \"{k.S('alignment is pixel-exact with the bar grid at all zoom levels')}\" (11:1885); the engineering "
        f"proof is E20-K01's", "x(t) edges are board markers, not product UI",
        f"Performance (§4.3, D02-C2): the {k.CEILING}-row ceiling; \"{k.S('<=1.5 ms per frame')}\" (14:874) and "
        f"\"{k.S('strip adds ≤2 ms per frame')}\" (11:1885) both recorded"])
