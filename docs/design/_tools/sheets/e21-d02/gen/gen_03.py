"""Board 03 densities: the density strip compact / cosy / comfortable at 200 (§3.1; BQ-3)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 3


def density(d: str) -> tuple[k.Node, tuple[str, list[str]]]:
    fid = f"SCR-050/streaming · {d}"
    p = ui.P(density=d)
    n = ui.BODY_H / p.row_h
    k.derive(f"{d}: {p.row_h} px rows in the {ui.BODY_H} px ladder body = {n:.2f} rows ({int(n)} whole rows shown)")
    col = {"compact": 1, "cosy": 2, "comfortable": 3}[d]
    cell = k.plain(next(c for _i, c in k.MATRIX if c[0] == "200")[col])
    lines = [f"§3.1 L{k.MATRIX[1][0]} (200, {d}): {cell}"]
    if d == "cosy":
        lines.append("Cosy = compact rows (24 px) + the chart-only `dense` heatmap pane (`16`:146, `16`:148): the "
                     "pane's cells lose their 1 px gutters; never a third row height (BQ-3; §15 item 3)")
    if d == "comfortable":
        lines.append("Rows 32 px (`16`:130); the extent is unchanged, fewer rows are shown; the partial last row is "
                     "clipped by the body")
    return ui.panel(fid, p), k.frame_block(fid, lines)


if __name__ == "__main__":
    ui.run(NN, [density("compact"), density("cosy"), density("comfortable")], 3)
