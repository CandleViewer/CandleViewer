"""E47-D13 / 09 reflow-200 (dark): the page at 200 %, at 320 CSS px and at the largest text scale: nothing clipped
(§7.5)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, tag_right  # noqa: E402

NN = 9
F_200, F_320, F_TS = k.frames_of(NN)
L75 = k.L("### 7.5 Reflow at 200 %")
VW_200, VW_320 = k.FRAME_W // 2, k.FRAME_W // 4  # 640 and 320 CSS px


def frame_200() -> tuple[k.Node, tuple[str, list[str]]]:
    st = k.State(width=VW_200 - 2 * k.PAGE_PAD, nav_above=True)
    page = k.statement_page(st)
    tops = (0, k.FRAME_H)
    ov = [k.tag("viewport 640 x 400 CSS px (the 1280 x 800 window at 200 %)", 8, 374, name="tag · viewport"),
          k.rect("viewport edge", VW_200, 2, k.MARK_FILL, x=0, y=400),
          k.tag("CMP-086 nav collapsed above the content", 330, page.y["nav"] + 6, name="tag · nav")]
    fr = k.strips_frame(F_200, page.node, tops, VW_200, overlays=ov,
                        note="200 %: a 640 CSS px viewport; the page in two strips at 1:1 CSS px")
    lines = [f"§7.5 L{L75}: at 200 % the single column reflows and nothing is clipped; the page scrolls only "
             "vertically; the tables keep their columns and wrap (stacking starts at 320 CSS px)",
             f"Page {page.height} CSS px tall at 640 wide (estimated); strip 1 CSS y 0-800 (the first 400 px is the "
             "viewport), strip 2 CSS y 800-1600",
             "The SettingsLayout nav collapses above the content per CMP-086, its items kept in the Tab order; the "
             "shell chrome at 640 CSS px is the shell's (not drawn)",
             "The sticky header is off at 200 % (§7.5)"]
    return fr, k.frame_block(F_200, lines)


def frame_320() -> tuple[k.Node, tuple[str, list[str]]]:
    st = k.State(width=VW_320 - 2 * k.PX[k.INSET_LG], pad=k.PX[k.INSET_LG], stacked=True, nav_above=True)
    page = k.statement_page(st)
    tops = (0, k.FRAME_H, page.spots["alternatives.h2"][1] - 16,
            page.height - k.FRAME_H)
    if list(tops) != sorted(tops) or any(b - a < k.FRAME_H for a, b in zip(tops, tops[1:])):
        raise ValueError(f"320 strips overlap: {tops}")
    ov = [k.tag(f"CSS y {a}-{a + k.FRAME_H}", VW_320 * i + 8, k.FRAME_H - 24, name=f"tag · strip {i + 1}")
          for i, a in enumerate(tops)]
    fr = k.strips_frame(F_320, page.node, tops, VW_320, overlays=ov,
                        note="320 CSS px (400 %): four strips of the page at 1:1 CSS px")
    lines = [f"§7.5 L{L75}: at 320 CSS px both tables stack each row into label-value pairs (CMP-049's Reflow "
             "story) that keep their table semantics (table, row, columnheader and cell roles restored); the page "
             "scrolls only vertically",
             f"Page {page.height} CSS px tall at 320 wide (estimated); the strips show CSS y "
             + ", ".join(f"{a}-{a + k.FRAME_H}" for a in tops) + ": the top, the stacked limitations, the "
             "alternatives and the stacked criteria, the end of the page",
             "Text spacing overrides (line height 1.5, paragraph 2x, letter 0.12 em, word 0.16 em) clip nothing "
             "(1.4.12): every cell and the template hug their text",
             "The two links, the copy button and the skip link stay at least 24 x 24 CSS px (2.5.8)"]
    return fr, k.frame_block(F_320, lines)


def frame_ts() -> tuple[k.Node, tuple[str, list[str]]]:
    top = max(k.TEXT_SCALES)
    page = k.statement_page(k.State(sc=k.Scale(top / 100)))
    fy = lambda key: page.frame_xy(key)[1]  # noqa: E731
    ov = [tag_right(f"text scale {top} % (the largest step, `14` SCR-116 L{k.SCR116_LINE})", fy("h1") + 6),
          tag_right("the column reflows; the tables wrap; nothing clipped", fy("limitations.h2") + 6)]
    fr = k.window(F_TS, page.node, overlays=ov, note=f"text scale {top} % at 1280 x 800")
    lines = [f"§7.5 L{L75}: at every in-app text scale the single column reflows and nothing is clipped; board 09 "
             f"shows the largest step ({top} % of {', '.join(map(str, k.TEXT_SCALES))} %, `14` SCR-116)",
             f"Page {page.height} px tall at {top} % (estimated); the sticky header is off above the default scale",
             "Text mapped to the token nearest 1.5 x (FALLBACKS type-150); the 05 text-scale keys are Ctrl+= ∕ Ctrl+-"]
    return fr, k.frame_block(F_TS, lines, keyboard="Ctrl+= and Ctrl+- step the scale (`05`:77)")


def build() -> None:
    fr = [frame_200(), frame_320(), frame_ts()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
