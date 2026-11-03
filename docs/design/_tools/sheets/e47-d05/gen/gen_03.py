"""Board 03 `E47-D05 / 03 hc-zoom-200` (hc): §11 — high contrast at 200 % (640 CSS px), the stacked column, nothing
clipped (T AC4). The 640 CSS px page is drawn at 1:1 in 640 x 800 strips side by side (FALLBACKS zoom-200)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k  # noqa: E402

NN = 3
PS = k.PS(theme="hc", os_contrast=True, stacked=True, width=k.ZOOM_W)


def build_frame() -> tuple[dict, int, int]:
    k.fallback("zoom-200")
    fid = k.BOARDS[NN].frames[0]
    pg = k.page(PS)
    need = int(math.ceil(k.est_height(pg) / 8) * 8)
    n = math.ceil(need / k.FRAME_H)
    strips = []
    for i in range(n):
        top = i * k.FRAME_H
        kids = [dict(pg, x=0, y=-top)]
        if i == 0:
            kids.append(k.rect("dashed · viewport 640 x 400 CSS", k.ZOOM_W, 400, None,
                               {"stroke": k.MARK_FILL, "strokeWidth": k.THICK, "strokeAlign": "inner"}, x=0, y=0,
                               note="annotation: the first 640 x 400 CSS viewport (not product UI)"))
            k.live("strip 1: set 'dashed · viewport 640 x 400 CSS' to a dashed style stroke (post-step) so its bottom edge "
                   "does not strike through the words under the 400 px fold")
        strips.append(k.box(f"strip {i + 1} · CSS y {top}-{top + k.FRAME_H}", kids, {"fill": k.APP, "clip": True},
                            w=k.ZOOM_W, h=k.FRAME_H, x=k.ZOOM_W * i, y=0))
    fr = k.box(k.frame_name(fid), strips, {"fill": k.APP, "clip": True}, w=k.ZOOM_W * n, h=k.FRAME_H,
               note="200 % zoom: a 640 CSS px viewport; the page at 1:1 CSS px in strips; the shell chrome is the shell's")
    return fr, need, n


def main() -> None:
    k.section_reading_note()
    fr, need, n = build_frame()
    fid = k.BOARDS[NN].frames[0]
    on, eff = k.effective(PS, "increased_contrast")
    lines = [
        f"§11 L{k.L('## 11. Themes, text scale')}: at 200 % (640 CSS px) the column stacks label, description, control, "
        "Effective line, tile; nothing clipped, nothing scrolls horizontally (`05`:131)",
        f"The stacked page is about {need} CSS px: {n} strips of 640 x 800 (strip 1 = CSS y 0-800 with the 640 x 400 "
        "viewport outlined); vertical scroll only",
        f"High contrast here is the OS asking for more contrast with the row on \"{k.TRI_OPTIONS[0]}\": \"{eff}\" "
        f"(§5.1 L{k._S51})",
        f"The focus-ring row adds W-25 \"{k.w('W-25')}\" (D04:247): a switch reading Off never hides the thick ring; "
        "the focus tile draws the thick ring",
        "Control boundaries at border.thick (E47-D03's border.control in hc, FALLBACKS border-control); the tile "
        "frames color.border.default",
        "The shell chrome at 640 CSS px is the shell's (A11Y-F-0016 at 320 px, noted, not redesigned): not drawn",
    ]
    p, md, pk = k.build(NN, [fr], [(fid, lines)], per_row=1,
                        board_lines=[f"High-contrast twin of board 01 at the 200 % viewport (§0 L{k.BOARDS[NN].line}; "
                                     "twins sentence L61): token-bound, the hc set applied at export"])
    print(p.name, md.name, pk.name, need, n)


if __name__ == "__main__":
    main()
