"""Board 08 `E47-D06 / 08 profile-table-light` (light): the light twin of board 03 — board 03's frame builders with
this board's frame ids; every colour is a token bind, so the light set is applied at export (md line 3)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_03  # noqa: E402
from common import k  # noqa: E402

NN = 8


def main() -> None:
    b = k.BOARDS[NN]
    if b.twin != gen_03.NN:
        raise SystemExit(f"gen_08: §0 makes board 08 a twin of {b.twin}, not {gen_03.NN}")
    gen_03.notes()
    p, md, pk = k.build(NN, gen_03.frames(NN), gen_03.blocks(NN), per_row=2,
                        board_lines=[f"Light twin of board {b.twin:02d} (§0 L{b.line}): the same nodes and words; "
                                     "the light token set is switched at export"])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
