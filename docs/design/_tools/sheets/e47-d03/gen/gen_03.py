"""Board 03 `E47-D03 / 03 scr116-high-contrast` (hc): V-3, border.control at border.thick and the retuned link
(hc+: Blue clears 7, so no W-1)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scr116 as h  # noqa: E402
from scr116 import k  # noqa: E402

NN, THEME = 3, "hc"


def main() -> None:
    b = k.BOARDS[NN]
    fid = b.frames[0]
    fr = h.default_frame(fid, THEME, warning=False)
    hcp = k.val("ACC", "hc+/palette.blue.200")
    lines = [*k.variant_lines("V-3"),
             f"W-2 \"{k.w('W-2')}\" announced once on the change (§13 L{k.COPY['W-2'].line})",
             f"Blue in hc today {k.acc(THEME, 'Blue')}:1 (warns); hc+ {hcp}:1 after D03-D1 / D03-D2 (§8.2 "
             f"L{k.PRESET_ROWS['Blue'][1]}): the board draws hc+, so no W-1",
             k.cr_line("link in a drawer (H-8, D03-D1, D03-D2)", h.S34, ("hc+",)),
             k.cr_line("control boundary on the app (D03-D3, D03-D4)", h.S34, ("hc+",)),
             f"border.control = border.thick in high contrast (D03-D6, hand-off §C.2 L{k.HL('| D03-D6')}): every "
             "control boundary on this frame is 2 px",
             k.cr_line("body text on the app", h.S31, (THEME,)),
             k.cr_line("focus colour on the app", h.S31, (THEME,))]
    k.live("board 03: color.text.link and color.border.strong resolve to the base hc values until E47-D10 applies "
           "D03-D1 … D03-D3; if the hc set is unchanged at render, export with the PROPOSED values bound "
           "(palette.blue.200 for the link, palette.neutral.600 for color.border.strong) and say so in §0")
    k.ambiguity("Board 03 draws hc+ (§0: 'Blue clears 7, no W-1') but binds tokens that resolve to the base hc values "
                "today (palette.blue.200 does not exist yet): the export shows hc+ only after E47-D10 or a live "
                "rebind; border.control is drawn as border.thick")
    p, md, pk = k.build(NN, [fr], [(fid, lines)])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
