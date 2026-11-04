"""Board 02 `E47-D05 / 02 scr117-light` (light): the light twin of board 01 — board 01's frame builder with
theme="light"; the token set is switched at export (md line 3)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_01  # noqa: E402
from common import k  # noqa: E402

NN = 2


def main() -> None:
    k.section_reading_note()
    fr, need = gen_01.build_frame("light")
    fid = k.BOARDS[NN].frames[0]
    p, md, pk = k.build(NN, [fr], gen_01.blocks(fid, need, "light"), per_row=1, full_length=k.BOARDS[NN].frames,
                        board_lines=[f"Light twin of board 01 (§0 L{k.BOARDS[NN].line}): the same nodes and words; "
                                     "every colour is a token bind, so the light set is applied at export"])
    print(p.name, md.name, pk.name, need)


if __name__ == "__main__":
    main()
