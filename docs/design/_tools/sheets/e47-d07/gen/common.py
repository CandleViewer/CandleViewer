"""Shared imports for the generators: the kit on sys.path, and the column packer the diagram boards use."""
from __future__ import annotations

import sys
from pathlib import Path

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e47d07kit as k  # noqa: E402


def columns(cards: list[dict], x0: int, y0: int, ncols: int, colw: int, gap: int, bottom: int) -> list[dict]:
    """Cards in reading order, each into the shortest column (ties: leftmost); raises if one passes `bottom`."""
    ys = [y0] * ncols
    out = []
    for c in cards:
        i = min(range(ncols), key=lambda j: (ys[j], j))
        h = round(k.est_height(c))
        out.append(dict(c, x=x0 + i * (colw + gap), y=ys[i]))
        ys[i] += h + gap
    if max(ys) - gap > bottom:
        raise SystemExit(f"columns: {max(ys) - gap} px passes the frame's usable bottom {bottom}")
    return out


def bottom_of(nodes: list[dict]) -> int:
    return max(int(n.get("y", 0)) + round(k.est_height(n)) for n in nodes)
