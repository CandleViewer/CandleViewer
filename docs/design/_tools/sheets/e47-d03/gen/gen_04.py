"""Board 04 `E47-D03 / 04 scr116-light` (light): the light twin of board 01's default frame (V-4)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_01 as base  # noqa: E402
import scr116 as h  # noqa: E402
from scr116 import k  # noqa: E402

NN, THEME = 4, "light"


def main() -> None:
    b = k.BOARDS[NN]
    if b.twin != 1:
        raise SystemExit("board 04 is no longer board 01's twin")
    fid = b.frames[0]
    fr = h.default_frame(fid, THEME)
    lines = [*k.variant_lines("V-4"), f"W-23 \"{k.w('W-23')}\" announced once on the change", *h.common_lines(THEME)]
    p, md, pk = k.build(NN, [fr], [(fid, lines)])
    print(p.name, md.name, pk.name, base.NN)


if __name__ == "__main__":
    main()
