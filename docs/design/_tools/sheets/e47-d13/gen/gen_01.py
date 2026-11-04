"""E47-D13 / 01 statement-anatomy (dark): the whole page inside SettingsLayout, its heading order and the eight
sections of §7.2 (condensed into bands), then the page top with redlines and token callouts (§7.2, §7.6, §7.7)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Bands, k, stop, tag_right, tags_row  # noqa: E402

NN = 1
F_ANAT, F_RED = k.frames_of(NN)
L72 = k.L("### 7.2 Anatomy")
L77 = k.L("### 7.7 Components and tokens")
SECTIONS = [  # (page key, the §7.2 item, its heading level and words)
    ("h1", "1", "h1 · status"), ("W-4", "2", "target + scope"), ("version", "3", "version line"),
    ("supported.h2", "4", "h2 · What is supported"), ("limitations.h2", "5", "h2 · Known limitations"),
    ("alternatives.h2", "6", "h2 · Alternatives"), ("criteria.h2", "7", "h2 · All criteria"),
    ("feedback.h2", "8", "h2 · Report an accessibility problem"),
]


def condensed(page: k.Page) -> Bands:
    s = page.spots
    return Bands(page, [(s["h1"][1] - 8, s["limitations.table"][1] + 30),
                        (s["alternatives.h2"][1] - 8, s["scr013"][1] + 26),
                        (s["criteria.h2"][1] - 8, s["criteria.table"][1] + 33 + k.ROW_H),
                        (s["feedback.h2"][1] - 8, s["copy"][1] + 29)])


def frame_anatomy() -> tuple[k.Node, tuple[str, list[str]]]:
    page = k.statement_page(k.State())
    bands = condensed(page)
    ov = []
    for key, item, lab in SECTIONS:
        y = bands.spot_y(key)
        ov += [stop(item, y, lab), tag_right(f"§7.2 item {item} · {lab}", y + 2)]
    fr = k.window(F_ANAT, bands.node, overlays=ov, note="the whole page condensed into four bands (annotation cuts)")
    outline = "; ".join(f"{item} {lab} (page y {page.spots[key][1]})" for key, item, lab in SECTIONS)
    lines = [f"§7.2 L{L72}: top to bottom, one h1 and an h2 per section from item 4; the eight sections at page y "
             f"(estimated, page {page.height} px tall): {outline}; then the CMP-207 footer at y {page.y['footer']}",
             f"§7.1 L{k.L('### 7.1 Route')}: one full page at /accessibility, SCR-119∕statement inside CMP-086 "
             f"SettingsLayout, {k.SCR119} selected in its nav; one main (W-20 is the document title)",
             "Condensed: four bands of the real page (items 1-5 to the table header, 6 to the first link, 7 to the "
             "first row, 8 to the copy button), each cut marked with the page px not shown; nothing is reordered",
             f"Status in words: \"{k.status_words()}\" derived from the {len(k.ROWS)} rows (R-9; {k.rule('R-9')})",
             f"Item 4 shows {k.wcite('W-11')}: the dry run has 0 Supports rows"]
    return fr, k.frame_block(F_ANAT, lines, keyboard="headings: h1 then five h2 in reading order; the tables are "
                                                     "static (no row takes focus)")


def redline_v(name: str, x: int, y0: int, y1: int, label_: str) -> list[k.Node]:
    return [k.vline(name, x, y0, max(y1 - y0, 2)), k.tag(label_, x + 6, (y0 + y1) // 2 - 8, name=f"redline · {name}")]


def frame_redlines() -> tuple[k.Node, tuple[str, list[str]]]:
    page = k.statement_page(k.State())
    fy = lambda key: page.frame_xy(key)[1]  # noqa: E731
    x_col = k.MAIN_X + k.PAGE_PAD
    gap_x = x_col + 520
    ov = [k.hline("page column 960", x_col, k.MAIN_Y + 8, k.PAGE_W),
          k.tag(f"column {k.PAGE_W} px · pad {k.PAGE_PAD} px (space.inset.xl) each side", x_col + 300, k.MAIN_Y + 10,
                name="redline · column"),
          *redline_v("section gap", gap_x, fy("version") + page.h["version"], fy("supported"),
                     f"{k.SECTION_GAP} px · space.inset.xl"),
          *redline_v("item gap", gap_x, fy("head") + page.h["head"], fy("target"),
                     f"{k.PX[k.STACK_MD]} px · space.stack.md"),
          tag_right("h1 · type.ui.heading-lg · color.text.primary", fy("head") + 4),
          tag_right("status · type.ui.body-strong", fy("status") + 2),
          tag_right("version line · type.ui.caption · color.text.secondary", fy("version")),
          tag_right("h2 · type.ui.heading-md", fy("supported.h2") + 2),
          *tags_row(["th · type.ui.label · color.text.secondary on color.surface.raised",
                     "rows zebra: color.surface.app ∕ color.surface.raised"], fy("limitations.h2") + 2),
          k.tag_stack("token · nav", ["CMP-086 nav: color.surface.raised", "current: color.surface.selected"],
                      k.NAV_W + 8, k.nav_entry_y(k.SCR119) + 40, k.SET_NAV_W - 16)]
    fr = k.window(F_RED, page.node, overlays=ov, note="the page top at scroll 0 with redlines and token callouts")
    lines = [f"§7.7 L{L77}: " + k._plain(k.SPEC_LINES[L77 + 1]),  # the whole line: a cut here drew "…; co"
             *[k.pair_line(p, "dark") for p in ("P1", "P2", "P5", "P6", "P3")],
             f"Prose measure {k.TEXT_W} px inside the {k.PAGE_W} px column (kit choice); tables take the full column",
             f"Spacing: sections {k.SECTION_GAP} px apart (space.inset.xl), items 1-3 {k.PX[k.STACK_MD]} px "
             f"(space.stack.md), h2 to body {k.PX[k.STACK_MD]} px; table cells 8 px a side (space.inset.sm)",
             "No colour carries meaning: the conformance level is a word, links are underlined (§7.6)"]
    return fr, k.frame_block(F_RED, lines)


def build() -> None:
    fr = [frame_anatomy(), frame_redlines()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
