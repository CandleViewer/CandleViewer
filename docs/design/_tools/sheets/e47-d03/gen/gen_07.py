"""Board 07 `E47-D03 / 07 cvd-safe-simulated` (dark): the CVD-safe palette on board 06's surfaces under
deuteranopia, protanopia and tritanopia (§7.4)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inkboards as ib  # noqa: E402
from inkboards import k  # noqa: E402

NN, THEME = 7, "dark"
SURFS = ["footprint", "dom", "heatmap", "profile", "cvd-pane", "bubbles"]


def main() -> None:
    b = k.BOARDS[NN]
    frames, blocks = [], []
    for fid in b.frames:
        sim = fid.rsplit("· ", 1)[1]
        if sim not in ("deut", "prot", "trit"):
            raise SystemExit(f"board 07: unknown simulation in {fid}")
        items = [ib.PANELS[s]("cvd-safe") for s in SURFS]
        hdr = k.ink_header(f"CVD-safe palette on every ink surface · {k.SIM_WORD[sim]}", sim, "cvd-safe")
        frames.append(k.ink_frame(fid, THEME, hdr, items))
        hexes = k.hex_key(sim, k.SIM74_CVD)
        blocks.append((fid, [*ib.pair_lines("cvd-safe", SURFS, sim), *(f"expected: {x}" for x in hexes)]))
        k.live(f"{k.frame_name(fid)}: export, then apply the {k.SIM_WORD[sim]} projection (§7.1) to this frame's "
               f"region; read back {hexes[0]}")
    lines = [f"Result (§7.2 L{k.L('Result: the CVD-safe palette keeps')}): the CVD-safe palette keeps buy / sell, "
             "bid / ask and the imbalance flag apart under all three dichromacies; no per-deficiency variant (D03-C1)",
             "Profile ink is not remapped by the CVD-safe palette (§2.3); the profile panel keeps it",
             *ib.enc_lines(SURFS)[:6]]
    p, md, pk = k.build(NN, frames, blocks, board_lines=lines)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
