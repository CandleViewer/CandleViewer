"""E47-D13 / 02 statement-top (light): the status, the target, the version line and the dates (§7.2 items 1-3)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, stop, tag_right  # noqa: E402

NN = 2
(F_TOP,) = k.frames_of(NN)
THEME = k.BOARDS[NN].theme


def frame_top() -> tuple[k.Node, tuple[str, list[str]]]:
    page = k.statement_page(k.State(focus="h1"))
    fy = lambda key: page.frame_xy(key)[1]  # noqa: E731
    ov = [stop(1, fy("h1") + 6, "h1"), stop(2, fy("status"), "status"), stop(3, fy("W-4"), "target"),
          stop(4, fy("scope"), "scope"), stop(5, fy("version") - 3, "version line"),
          tag_right(f"h1 focused once on arrival (tabindex -1, §7.4) · {k.wcite('W-1')}", fy("h1") + 6),
          tag_right(f"status in words · {k.wcite('W-5')} · derived from the report (R-9)", fy("status") + 2),
          tag_right(f"target · {k.wcite('W-4')}", fy("W-4") + 2),
          tag_right("scope · §7.2 item 2 (copy gap)", fy("scope") + 2),
          tag_right(f"version line · {k.wcite('W-6')} · as text", fy("version") - 2)]
    fr = k.window(F_TOP, page.node, overlays=ov, note="the page top, light theme (token-bound)")
    s = k.SYNTH
    lines = [f"§7.2 L{k.L('1. `h1` \"Accessibility statement\"')}-L{k.L('3. The version line (W-6)')}: the h1, then "
             "the status in words as the first text after it, the target and scope, the version line",
             f"Status \"{k.status_words()}\": not every one of the {len(k.ROWS)} rows is Supports or Not "
             f"Applicable ({k.rule('R-9')})",
             f"Version line (synthetic values): applies to {s['appliesTo']}, issued {k.date_words(s['issued'])}, "
             f"review by {k.date_words(s['reviewBy'])} (issued + {k.REVIEW_DAYS} days, a kit choice); §8.1 "
             f"L{k.L('### 8.1 The statement document')} names the fields",
             "Reading order 1-5 = DOM order; nothing here is focusable but the h1's one-time programmatic focus",
             *[k.pair_line(p, THEME) for p in ("P1", "P2", "P7")]]
    return fr, k.frame_block(F_TOP, lines, keyboard="arrival focuses the h1; Tab then reaches the SCR-013 link "
                                                    "(item 6), Shift+Tab the settings nav", waits=["D13-G2"])


def build() -> None:
    fr = [frame_top()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
