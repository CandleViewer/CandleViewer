"""E27-D03 / 02 cmp-175-key-states-light: board 01 in semantic-light (§0 L219; BQ-2, BQ-6). Same cells, same names,
same tokens (bound by name through the file's light theme); no frame of its own."""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_01 as g

k = g.k

if __name__ == "__main__":
    g.NOTES[-1] = (
        "the light twin of board 01: in light color.status.danger.strong equals color.status.warning.strong, "
        "so the octagon and the triangle / clock share one colour and the shape and the words carry them "
        "(BQ-6, §0 L219)"
    )
    g.build(2, g.cells())
