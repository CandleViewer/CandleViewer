"""E47-D13 / 04 known-limitations (hc): the limitations table (what you notice · who it affects · what to do
instead) and the generic sentences (§7.2 item 5, §6.3, §6.5)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, scroll_to, stop, tag_right, tags_row  # noqa: E402

TAG_X_MEASURED = (966, 728, 446)  # right to left; the estimates (919, 679, 359) put the last over 'Known limitations'

NN = 4
F_TABLE, F_GENERIC = k.frames_of(NN)
THEME = k.BOARDS[NN].theme
L72_5 = k.L("5. Known limitations (W-9)")


def frame_table() -> tuple[k.Node, tuple[str, list[str]]]:
    page = k.statement_page(k.State())
    sc = scroll_to(page, "limitations")
    fy = lambda key: page.frame_xy(key, sc)[1]  # noqa: E731
    ov = [stop(1, fy("limitations.h2"), "h2"), stop(2, fy("limitations.table") + 2, "table"),
          # the live check moved the three tags right at the same y (measured widths), clear of the h2's words
          *[dict(t_, x=x_) for t_, x_ in zip(tags_row([f"h2 · {k.wcite('W-9')} · names the table (aria-labelledby)",
                                                      f"three th scope=col · {k.wcite('W-10')}",
                                                      "the words first, the criterion number after (R-7)"],
                                                     fy("limitations.h2") + 2), TAG_X_MEASURED, strict=True)]]
    fr = k.window(F_TABLE, page.node, scroll=sc, overlays=ov, note="the limitations table, high contrast")
    lines = [f"§7.2 item 5 L{L72_5}: a CMP-049 static table named by its h2, three th column headers (W-10), one row "
             f"per statement row, the criterion number in parentheses after the words",
             f"Rows: the {len(k.STATEMENT_LIMITS)} statement rows of 47-limitations.json in register order "
             f"({', '.join(x['id'] for x in k.STATEMENT_LIMITS)}); plain, impact and workaround as written (dry "
             "run drafts, D13-Q3)",
             f"§6.3 L{k.L('### 6.3 Plain language')}: one sentence each, at most 30 words, no criterion number in "
             f"the words; {k.rule('R-7')}",
             f"Sign-off: {len(k.BLOCKED)} rows have no disposition ({', '.join(k.BLOCKED)}); the disposition is the "
             "register's, not shown on the page (§6.4)",
             *[k.pair_line(p, THEME) for p in ("P1", "P5", "P6")]]
    return fr, k.frame_block(F_TABLE, lines, keyboard="nothing in the table is focusable; table keys move the "
                                                      "screen reader cell by cell")


def frame_generic() -> tuple[k.Node, tuple[str, list[str]]]:
    page = k.statement_page(k.State(internal_demo=True))
    sc = max(0, page.y["limitations"] + page.h["limitations"] - k.BODY_H + 40)
    fy = lambda key: page.frame_xy(key, sc)[1]  # noqa: E731
    gy = fy("limitations") + page.h["limitations"]
    ov = [stop(1, gy - 58, "W-16"), stop(2, gy - 32, "generic sentence"),
          tag_right(f"{k.wcite('W-16')} · before the generic sentences", gy - 76),
          tag_right("category security: its one generic sentence (R-8)", gy - 14)]
    fr = k.window(F_GENERIC, page.node, scroll=sc, overlays=ov,
                  note="illustrative: one synthetic internal row shown by its category sentence")
    lines = [f"§6.5 L{k.L('### 6.5 The disclosure split')}: an internal row appears only as its category's generic "
             f"sentence; the register holds the full text; E47-X04 (#1389) reviews the split; {k.rule('R-8')}",
             f"Illustrative (synthetic): at {k.BASE_SHA} every one of the {len(k.LIMITS)} rows is statement "
             f"disclosure ({len(k.INTERNAL_LIMITS)} internal), so this frame marks one invented internal row of "
             "category security; the sentence is the register's own categories.security",
             "The tool fails statement text that carries a host, an id of six or more digits, a key-like string or "
             "an image (§6.5)"]
    return fr, k.frame_block(F_GENERIC, lines)


def build() -> None:
    fr = [frame_table(), frame_generic()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
