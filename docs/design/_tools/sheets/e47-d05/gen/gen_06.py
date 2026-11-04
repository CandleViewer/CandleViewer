"""Board 06 `E47-D05 / 06 focus-tile` (dark): §6.2 — the focus tile with the normal ring, the thick ring and
always-show (the ring after a simulated click)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, view_window  # noqa: E402

NN = 6
SECS = ("Contrast and focus", "Data views", "Announcements")


def main() -> None:
    k.section_reading_note()
    b = k.BOARDS[NN]
    pss = [k.PS(header=False, sections=SECS),
           k.PS(values=(("thick_focus_ring", "true"),), focus="thick_focus_ring", focus_variant="thick", header=False,
                sections=SECS),
           k.PS(values=(("always_show_focus_ring", "true"),), focus="always_show_focus_ring", header=False,
                sections=SECS)]
    frames = [view_window(fid, ps, note=fid) for fid, ps in zip(b.frames, pss)]
    s62 = k.L("### 6.2 Focus")
    g = k.RING_GEOM
    blocks = [
        (b.frames[0], [
            f"§6.2 L{s62}: a CMP-001 Button and a ladder row with the ring per the pending values: normal — ring "
            f"{g['normal'][0]} px color.focus.ring, halo {g['normal'][1]} px color.surface.canvas each side, offset "
            f"{g['normal'][2]} px (D04 §7.1 L{g['normal'][3]}); the row's ring inset (CMP-039 inset)",
            "The samples sit inside the role=\"img\" node, inert and out of the Tab order: the page never shows a second "
            "real focus; static, no loop",
            f"The ladder row is the seeded heatmap column's level {k.px_fmt(k.WORLD.heat[5][0])} (bid size "
            f"{k.WORLD.heat[5][1]}, ask size {k.WORLD.heat[3][1]})"]),
        (b.frames[1], [
            f"thick_focus_ring on: thick — ring {g['thick'][0]} px, halo {g['thick'][1]} px each side, offset "
            f"{g['thick'][2]} px (D04 §7.1 L{g['thick'][3]}; PROPOSED border.focus.thick, FALLBACKS thick)",
            "The switch that set it holds the real focus, drawn with the thick ring: the tile and the page agree "
            "(the drawn ring is painted by the same data-focus-ring token path, PCX:148)",
            "In the high-contrast theme the ring is thick regardless (D04:247; board 03's W-25)"]),
        (b.frames[2], [
            "always_show_focus_ring on (PROPOSED, D05-G1 / D04-G2): the ring also stays after a mouse click or a tap "
            "(:focus, not only :focus-visible); the tile shows it after a simulated click (the tag is annotation)",
            "Floors are unconditional (R-7): the ring and the 24 px target floor hold with every option off"]),
    ]
    p, md, pk = k.build(NN, frames, blocks, per_row=3)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
