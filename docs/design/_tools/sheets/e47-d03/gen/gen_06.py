"""Board 06 `E47-D03 / 06 encodings-greyscale` (dark): §5's surfaces in colour and in the greyscale of §7.4."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inkboards as ib  # noqa: E402
from inkboards import k  # noqa: E402

NN, THEME = 6, "dark"
PLAN = {"ink/footprint · colour": (["footprint", "dom"], "none"), "ink/footprint · grey": (["footprint", "dom"], "grey"),
        "ink/heatmap · grey": (["heatmap"], "grey"), "ink/profile · grey": (["profile"], "grey"),
        "ink/cvd-pane · grey": (["cvd-pane"], "grey"), "ink/bubbles · grey": (["bubbles"], "grey")}


def main() -> None:
    b = k.BOARDS[NN]
    if list(PLAN) != list(b.frames):
        raise SystemExit(f"board 06: §G frames {b.frames} != the plan")
    frames, blocks = [], []
    for fid, (surfs, sim) in PLAN.items():
        pl = ib.pair_lines("default", surfs, sim)
        hexes = k.hex_key(sim, k.SIM74_DEFAULT) if sim != "none" else []
        ev = [k.evidence(f"§7.2 in {k.SIM_WORD[sim]} (dark)", pl or ["no §7.2 pair for this surface"])]
        if hexes:
            ev.append(k.evidence("§7.4: expected hexes after the projection", hexes))
        items = [ib.PANELS[s]("default") for s in surfs] + [k.vbox("evidence", ev, {"gap": k.STACK_MD},
                                                                   w=k.PANEL_W)]
        title = " and ".join({"footprint": "Footprint cells", "dom": "DOM ladder", "heatmap": "Heatmap with its legend",
                              "profile": "Profile", "cvd-pane": "CVD pane",
                              "bubbles": "Bubbles and chart trade markers"}[s] for s in surfs)
        hdr = k.ink_header(f"{title} · default palette · {k.SIM_WORD[sim]}", sim, "default")
        frames.append(k.ink_frame(fid, THEME, hdr, items))
        blocks.append((fid, [*ib.enc_lines(surfs), *pl, *(f"expected: {x}" for x in hexes)]))
        if sim != "none":
            k.live(f"{k.frame_name(fid)}: export, then apply the grey projection (§7.1: relative luminance) to this "
                   f"frame's region; read back {hexes[0] if hexes else 'the ink'}")
    k.ambiguity("Board 06: §0 lists footprint, DOM, heatmap, profile, CVD pane, bubbles and markers each in colour "
                "and greyscale, §G six frames with one colour frame: DOM rides with the footprint frames and the "
                "markers with the bubbles; only the footprint pair has a colour frame (§G)")
    k.ambiguity("Boards 06 / 07: cvsheet binds tokens only, so §7.4's simulated hexes cannot be painted: the frames "
                "bind the true ink and the projection is applied at export (E15-D04 precedent); each frame lists the "
                "hexes to read back")
    p, md, pk = k.build(NN, frames, blocks)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
