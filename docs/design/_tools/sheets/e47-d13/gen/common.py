"""Shared pieces of the E47-D13 board generators: the kit import, markers in the page gutter, tags beside an item,
the condensed page (bands of the whole page in one window), the skip link."""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import e47d13kit as k  # noqa: E402

Node = k.Node
GUTTER_X = k.MAIN_X + 2  # numbered stops sit in the page's 24 px left padding


def mark(n: int | str, xy: tuple[int, int], name: str | None = None) -> Node:
    return k.marker(n, int(xy[0]), int(xy[1]), name=name)


def tag_w(label_: str) -> int:
    return int(math.ceil(k.text_w(label_, k.CAPTION))) + 2 * k.PX[k.INSET_XS] + 2


def tag_right(label_: str, y: int, *, right: int = k.FRAME_W - 12, name: str | None = None) -> Node:
    """A tag end-aligned at `right` (frame x), top at frame y."""
    return k.tag(label_, right - tag_w(label_), int(y), name=name)


def tags_row(labels: list[str], y: int, *, right: int = k.FRAME_W - 12, gap: int = 8) -> list[Node]:
    """Several tags on one line, end-aligned at `right`, the first label rightmost."""
    out = []
    for lab in labels:
        out.append(tag_right(lab, y, right=right))
        right -= tag_w(lab) + gap
    return out


def stop(n: int | str, y: int, label_: str) -> Node:
    return mark(n, (GUTTER_X, int(y)), name=f"stop {n} · {label_}")


def scroll_to(page: k.Page, key: str, above: int = 16) -> int:
    """A scroll that puts section `key` `above` px under the main pane's top (clamped to the page)."""
    return max(0, min(page.y[key] - above, page.height - k.BODY_H))


def frame_y(page: k.Page, key: str, scroll: int) -> int:
    return page.frame_xy(key, scroll)[1]


class Bands:
    """The whole page condensed into one main pane: several page ranges stacked top to bottom, each cut by a 12 px
    "N px of the page not shown" rule (the E47-D13 kit's condensed view; build-notes reading 4)."""

    CUT_H = 12

    def __init__(self, page: k.Page, ranges: list[tuple[int, int]]) -> None:
        self.page, self.ranges = page, ranges
        total = sum(b - a for a, b in ranges) + self.CUT_H * (len(ranges) - 1)
        if total > k.BODY_H:
            raise ValueError(f"bands {ranges}: {total} px > the {k.BODY_H} px main pane")
        kids, y = [], 0
        self.offsets: list[tuple[int, int, int]] = []  # (page a, page b, main y)
        for i, (a, b) in enumerate(ranges):
            if i:
                gone = a - ranges[i - 1][1]
                kids.append(k.hbox(f"cut {i} · {gone} px not shown",
                                   [k.text("label", f"{gone} px of the page not shown", k.CAPTION, k.TEXT_INVERSE)],
                                   {"padX": k.INSET_SM, "fill": k.MARK_FILL, "justify": "center"},
                                   w=k.CONTENT_W, h=self.CUT_H, x=0, y=y, note="annotation: a cut in the page"))
                y += self.CUT_H
            crop = k.crop(page.node, a, b) or page.node
            kids.append(k.box(f"band {i + 1} · page y {a}-{b}", [dict(crop, x=0, y=-a)], {"fill": k.APP, "clip": True},
                              w=k.CONTENT_W, h=b - a, x=0, y=y))
            self.offsets.append((a, b, y))
            y += b - a
        self.node = k.box("page · condensed", kids, {"fill": k.APP}, w=k.CONTENT_W, h=k.BODY_H,
                          note="the whole page in bands (annotation cuts between them)")

    def fy(self, page_y: int) -> int:
        """Frame y of a page y inside one of the bands."""
        for a, b, my in self.offsets:
            if a <= page_y < b:
                return k.MAIN_Y + my + page_y - a
        raise ValueError(f"page y {page_y} is in no band {self.ranges}")

    def spot_y(self, key: str) -> int:
        return self.fy(self.page.spots[key][1])


def skip_link(*, focused: bool = True) -> Node:
    """CMP-085 SkipLink: "Skip to main content" (`15` CMP-085, verbatim), visible at top-left when focused."""
    k.copy_gap('"Skip to main content": `15` CMP-085 (verbatim, the component\'s own label)')
    lab = "Skip to main content"
    b = k.hbox("CMP-085 SkipLink", [k.text("label", lab, k.LABEL, k.TEXT_ON_ACTION)],
               {"padX": k.BUTTON_PADX, "radius": k.R_CONTROL, "fill": k.ACTION_PRIMARY, "justify": "center"},
               w=int(k.text_w(lab, k.LABEL)) + 2 * k.PX[k.BUTTON_PADX] + 4, h=k.CONTROL_H,
               note="first focusable; visible only on focus; targets main")
    return k.focus_ring(b, name="CMP-085 SkipLink · focused") if focused else b
