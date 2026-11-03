"""Board 07 `E47-D07 / 07 scr117-panel-light` (light): the light twin of board 06's default frame — board 06's frame
builder; every colour is a token bind, so the light set is switched at export (md line 3)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_06  # noqa: E402
from common import k  # noqa: E402

NN = 7


def main() -> None:
    b = k.BOARDS[NN]
    if b.twin != 6 or k.frame_state(b.frames[0]) != k.frame_state(k.BOARDS[6].frames[0]):
        raise SystemExit("board 07: no longer the light twin of board 06's default frame")
    gen_06.notes()
    fr = gen_06.build_frame(b.frames[0], "light")
    p, md, pk = k.build(NN, [fr], [(b.frames[0], gen_06.blocks(b.frames[0], view_as=False))], per_row=1,
                        board_lines=[f"Light twin of board 06's default frame (§0 L{b.line}): the same nodes and "
                                     "words; the light token set is applied at export"])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
