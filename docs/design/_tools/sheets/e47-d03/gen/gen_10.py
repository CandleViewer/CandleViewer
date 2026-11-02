"""Board 10 `E47-D03 / 10 data-ink-ramps-light` (light): the light twin of board 09, after D03-D7 … D03-D14."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_09 as base  # noqa: E402
from gen_09 import k  # noqa: E402

NN = 10


def main() -> None:
    b = k.BOARDS[NN]
    if b.twin != 9:
        raise SystemExit("board 10 is no longer board 09's twin")
    for side in ("bid", "ask"):
        a, z = k.cr("light+", f"color.cvd.heatmap.{side}.1", k.CANVAS), k.cr("light", f"color.cvd.heatmap.{side}.5",
                                                                           k.CANVAS)
        if a != z:
            raise SystemExit(f"board 10: §3.4 light+ {side} stop 1 {a} != §3.3 light stop 5 {z}")
    fr, lines = base.build_frame("light")
    k.ambiguity("Board 10 draws the light CVD ramp after D03-D7 … D03-D14 (PROPOSED): each stop binds the base light "
                "token that holds the diff's primitive today, so the export is right before E47-D10 lands; once the "
                "diff applies, rebind each stop to its own token")
    p, md, pk = k.build(NN, [fr], [(b.frames[0], lines)])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
