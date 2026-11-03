"""E47-D13 / 10 keyboard-reading-order (light): the Tab order and the reading order numbered over the page; the skip
link (§7.4)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Bands, k, mark, skip_link, stop, tag_right  # noqa: E402

NN = 10
F_TAB, F_READ = k.frames_of(NN)
THEME = k.BOARDS[NN].theme
L74 = k.L("### 7.4 Keyboard and focus")


def frame_tab() -> tuple[k.Node, tuple[str, list[str]]]:
    page = k.statement_page(k.State())
    s = page.spots
    bands = Bands(page, [(s["h1"][1] - 8, s["status"][1] + 24), (s["alternatives.h2"][1] - 8, s["scr117"][1] + 40),
                         (s["feedback.h2"][1] - 8, page.height)])
    sk = skip_link()
    nav_y = k.nav_entry_y(k.SETTINGS_NAV[0])
    ov = [dict(sk, x=8, y=8, abs=True), mark(1, (int(k.est_width(sk)) + 16, 12), name="stop 1 · skip link"),
          mark(2, (k.NAV_W + k.SET_NAV_W - 26, nav_y + 4), name="stop 2 · settings nav"),
          stop(3, bands.spot_y("scr013") + 2, "SCR-013 link"), stop(4, bands.spot_y("scr117") + 2, "SCR-117 link"),
          stop(5, bands.spot_y("copy") + 4, "copy button"), stop(6, bands.fy(page.y["footer"]), "footer"),
          k.tag("2: the SettingsLayout nav items, in order", k.NAV_W + 8, nav_y + 9 * 32 + 8, name="tag · nav"),
          tag_right("h1: focused once on arrival (tabindex -1), not a Tab stop", bands.spot_y("h1") + 6),
          tag_right("3 · W-3 link", bands.spot_y("scr013") + 4), tag_right("4 · W-19 link", bands.spot_y("scr117") + 4),
          tag_right("5 · W-13 copy button", bands.spot_y("copy") + 4),
          tag_right("6 · CMP-207 footer", bands.fy(page.y["footer"]))]
    fr = k.window(F_TAB, bands.node, overlays=ov, note="Tab order 1-6 over the page (condensed)")
    lines = [f"§7.4 L{L74}: DOM and Tab order, every focusable on the page: (1) the skip link, (2) the SettingsLayout "
             "nav items, (3) the SCR-013 link (W-3), (4) the SCR-117 link (W-19), (5) the copy button (W-13), (6) the "
             "CMP-207 footer; board 10 numbers exactly this sequence",
             "The CMP-085 skip link targets main; the h1 takes focus once on arrival; from the h1 Tab reaches (3) and "
             "Shift+Tab the nav; the notices, the version line and both tables hold nothing focusable",
             "The shell's own TopBar and rail stops are E47-D04's ring, not this page's: not numbered (kit reading)",
             "Condensed: three bands of the page (the top, the alternatives, the end); cuts name the px not shown",
             *[k.pair_line(p, THEME) for p in ("P7", "P8")]]
    return fr, k.frame_block(F_TAB, lines, keyboard="Enter on a link follows it; Enter or Space on the copy button "
                                                    "copies; Esc closes nothing; Back restores focus to the opener")


READ = [("h1", "h1"), ("status", "status (W-5)"), ("W-4", "target (W-4)"), ("scope", "scope"),
        ("version", "version line (W-6)"), ("supported.h2", "h2 What is supported"),
        ("supported.text", "W-11"),
        ("limitations.h2", "h2 Known limitations"), ("limitations.table", "limitations table"),
        ("alternatives.h2", "h2 Alternatives"), ("alt1", "alternatives list"), ("criteria.h2", "h2 All criteria"),
        ("criteria.table", "criteria table"), ("feedback.h2", "h2 Report an accessibility problem"),
        ("template", "template (W-14)"), ("copy", "copy button (W-13)"), ("footer", "CMP-207 footer")]


def frame_read() -> tuple[k.Node, tuple[str, list[str]]]:
    page = k.statement_page(k.State())
    s = page.spots
    bands = Bands(page, [(s["h1"][1] - 8, s["limitations.table"][1] + 26),
                         (s["alternatives.h2"][1] - 8, s["alt2"][1] - 4),
                         (s["criteria.h2"][1] - 8, s["criteria.table"][1] + 26),
                         (s["feedback.h2"][1] - 8, page.height)])
    ov = []
    for i, (key, lab) in enumerate(READ, 1):
        y = bands.spot_y(key) if key in s else bands.fy(page.y[key])
        ov.append(stop(i, y + 2, lab))
    fr = k.window(F_READ, bands.node, overlays=ov, note=f"reading order 1-{len(READ)} over the page (condensed)")
    lines = [f"§7.2 L{k.L('### 7.2 Anatomy')}: reading order = DOM order = the visual order: "
             + "; ".join(f"{i} {lab}" for i, (_k, lab) in enumerate(READ, 1)),
             "The stale and version-unknown notices, when shown, are read between the scope and the version line "
             "(§7.3; board 03)",
             "The Tab order (left frame) is a subset of this order; it never jumps back",
             "Condensed: four bands of the page; cuts name the px not shown"]
    return fr, k.frame_block(F_READ, lines)


def build() -> None:
    fr = [frame_tab(), frame_read()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
