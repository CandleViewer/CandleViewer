"""Board 05 `E47-D03 / 05 text-150-zoom-200` (dark): V-5, 150 % text and the 200 % reflow at 640 CSS px (§8.5)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scr116 as h  # noqa: E402
from scr116 import k  # noqa: E402

NN, THEME = 5, "dark"


def text150(fid: str) -> tuple[dict, float]:
    ch = k.Choice(theme=THEME, text_size="150 %", focus="Text size")
    page = k.scr116_page(ch, k.Scale(1.5))
    return k.window(k.frame_name(fid), THEME, page, note="text size 150 %; the main column scrolls vertically"), \
        k.est_height(page)


def zoom200(fid: str) -> tuple[dict, float]:
    k.fallback("zoom-200")
    ch = k.Choice(theme=THEME, focus=None)
    page = k.scr116_page(ch, stacked=True, w_=640)
    need = k.est_height(page)
    if need > 1600:
        raise ValueError(f"zoom-200: the stacked page is about {need:.0f} CSS px > two strips")
    strips = []
    for i, top in enumerate((0, 800), 1):
        kids = [dict(page, x=0, y=-top)]
        if top == 0:
            kids.append(k.rect("dashed · viewport 640 x 400 CSS", 640, 400, None,
                               {"stroke": k.RING, "strokeWidth": k.FOCUS_W, "strokeAlign": "inner"}, x=0, y=0))
            k.live("zoom-200 strip 1: set the 'dashed · viewport 640 x 400 CSS' outline to dashed style (post-step), "
                   "so its bottom edge does not strike through the heading under the 400 px fold")
        strips.append(k.box(f"strip {i} · CSS y {top}-{top + 800}", kids, {"fill": k.APP, "clip": True}, w=640, h=800,
                            x=640 * (i - 1), y=0))
    fr = k.box(k.frame_name(fid), strips, {"fill": k.APP, "clip": True}, w=k.FRAME_W, h=k.FRAME_H,
               note="200 % zoom: a 640 CSS px viewport; the page in two 640 px strips at 1:1 CSS px")
    return fr, need


def main() -> None:
    b = k.BOARDS[NN]
    f1, h1 = text150(b.frames[0])
    f2, h2 = zoom200(b.frames[1])
    s85 = k.L("### 8.5 Text scale and 200 % zoom")
    l1 = [*k.variant_lines("V-5"),
          f"§8.5 L{s85 + 2}: at 150 % the labels wrap, the segmented controls stay one row each and the PreviewTile "
          "keeps its last frame (drawn at 100 %)",
          f"Page about {h1:.0f} px for a {k.BODY_H} px view: the main column scrolls vertically, never horizontally; "
          "Reset is reached by Tab (it scrolls into view)",
          f"Announcement: \"Text size 150 %\" once (§8.3 V-5); W-11 \"{k.w('W-11')}\""]
    l2 = [f"§8.5 L{s85 + 2}: at 200 % (640 CSS px) the column stacks: controls, then the tile, then Reset; nothing "
          "clipped, no control scrolls horizontally (05:131)",
          f"Stacked page about {h2:.0f} CSS px: strip 1 shows CSS y 0-800 (the 640 x 400 viewport outlined), strip 2 "
          "800-1600; DOM order = visual order (§8.1)",
          "The shell chrome at 640 CSS px is the shell's (not drawn)"]
    k.ambiguity("Board 05: no type token exists at 150 % or at 2 x: the text-150 frame maps each role to the token "
                "nearest 1.5 x (FALLBACKS type-150) and the zoom-200 frame draws the 640 CSS px page at 1:1 in two "
                "strips instead of a 2 x raster")
    p, md, pk = k.build(NN, [f1, f2], [(b.frames[0], l1), (b.frames[1], l2)], per_row=2)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
