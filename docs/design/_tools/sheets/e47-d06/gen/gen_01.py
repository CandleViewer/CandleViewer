"""Board 01 `E47-D06 / 01 four-layer-inventory` (dark): §2 as a sheet — every surface, its four layers, its status;
no surface is exempt (R-1)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, sheet_table  # noqa: E402

NN = 1
COLS = [("IV", 56), ("Surface (component)", 168), ("Screen", 104), ("L1 unit · grammar", 216),
        ("L2 class", 176), ("L3 table", 200), ("L4 canvas role · label", 152), ("Design", 176)]  # 1248


def frame() -> dict:
    keys = ("iv", "surface", "screen", "l1", "l2", "l3", "l4", "design")
    rows = [[iv[x] for x in keys] for iv in k.INV.values()]
    t = sheet_table("§2 inventory", COLS, rows)
    title = k.text("title", f"The surface inventory: {len(k.INV)} surfaces, four layers each (§2 L{k.INV_LINE}); "
                   "native DOM meets layers 1 and 3 by the element; nothing is exempt (R-1)", k.HEADING_SM, k.TEXT_1,
                   w=1248)
    foot = k.text("foot", "SCR-049's cells are SCR-030 instances: each cell carries IV-1 … IV-14's layers (§2)",
                  k.CAPTION, k.TEXT_2, w=1248)
    f = k.sheet_frame(k.BOARDS[NN].frames[0], [title, t, foot])
    need = 32 + k.est_height(title) + k.est_height(t) + k.est_height(foot) + 2 * 12
    if need > k.FRAME_H:
        raise SystemExit(f"gen_01: the sheet needs {need:.0f} px")
    return f


def main() -> None:
    k.ambiguity("the sheet repeats §2's cells verbatim (cite marks stripped of backticks); the Design column is "
                "the status the board's \"its status\" names")
    b = k.BOARDS[NN]
    blocks = [(b.frames[0], [f"§2 L{k.INV_LINE}: {len(k.INV)} surfaces (COUNT:inv {k.val('COUNT', 'inv')}); L1 = "
                             "the mirror unit and grammar, L2 the `05` §6.2 class, L3 the table, L4 the canvas "
                             "role and label", f"The register tags {k.val('COUNT', 'cat.chrome')} of these screens chrome (D06-C1)"])]
    p, md, pk = k.build(NN, [frame()], blocks, per_row=1)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
