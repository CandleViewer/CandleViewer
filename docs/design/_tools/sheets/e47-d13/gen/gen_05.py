"""E47-D13 / 05 alternatives (dark): the alternatives with their keys and links (§7.2 item 6)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, scroll_to, stop, tag_right  # noqa: E402

NN = 5
(F_ALT,) = k.frames_of(NN)


def frame_alt() -> tuple[k.Node, tuple[str, list[str]]]:
    page = k.statement_page(k.State(focus="scr013"))
    sc = scroll_to(page, "alternatives", 48)
    fy = lambda key: page.frame_xy(key, sc)[1]  # noqa: E731
    keys = ("Alt+T", "W-3", "W-19", "Ctrl+=", "Ctrl+Shift+M", "Ctrl+Shift+H")
    ov = [stop(3, fy("scr013") + 2, "Tab stop 3"), stop(4, fy("scr117") + 2, "Tab stop 4"),
          tag_right("h2 · Alternatives (copy gap)", fy("alternatives.h2") + 2),
          tag_right("kbd: one element, its text joins the keys with + (§7.2 item 6)", fy("alt1") + 2),
          tag_right(f"CMP-021 link · {k.wcite('W-3')} · SCR-013 · focused (CMP-039)", fy("scr013") + 4),
          tag_right(f"CMP-021 link · {k.wcite('W-19')} · SCR-117", fy("scr117") + 4),
          tag_right("SCR-116's control named as text, not a link", fy("alt4") + 24)]
    fr = k.window(F_ALT, page.node, scroll=sc, overlays=ov, note="the alternatives; the SCR-013 link focused")
    lines = [f"§7.2 item 6 L{k.ALT_LINE}: " + ", ".join(keys) + " in that order; the two links are the section's "
             "only Tab stops; each key group one kbd element (\"Alt+T\" reads as words)",
             "The platform modifier follows the keymap and E47-D04, never restated here (§7.2 item 6)",
             f"Keys from `05`:57, :77, :78, :79 (§1.3 L{k.L('The keys the statement names')}); the row words are copy "
             "gaps from `05`'s keyboard table (listed in the notes)",
             k.pair_line("P3", "dark"), k.pair_line("P8", "dark"),
             "Links underlined (the colour is never the only cue, `15` CMP-021)"]
    return fr, k.frame_block(F_ALT, lines, keyboard="Tab: SCR-013 link (3) -> SCR-117 link (4) -> copy button (5); "
                                                    "Enter follows a link")


def build() -> None:
    fr = [frame_alt()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
