"""E47-D13 / 06 criteria-table (dark): the plain table of the 55 rows, the levels as words, the wide-only sticky
header (§7.2 item 7, §7.5)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, stop, tag_right, tags_row  # noqa: E402

NN = 6
(F_CRIT,) = k.frames_of(NN)
STUCK_AFTER = 8  # rows scrolled under the header (a kit choice of scroll position)


def frame_crit() -> tuple[k.Node, tuple[str, list[str]]]:
    st = k.State()
    page = k.statement_page(st)
    cols = k._cols(st, k.CRIT_COLS)
    row_h = int(k.est_height(k.table_row(cols, {"criterion": k.ROWS[0].criterion, "level": k.ROWS[0].level_words,
                                                 "word": k.ROWS[0].word}, "probe", 1)))
    rows_top = page.spots["criteria.rows"][1]
    sc = rows_top + STUCK_AFTER * row_h
    hdr = k.header_row(cols)
    sticky = k.vbox("sticky header (wide only)", [hdr, k.rect("header rule", k.PAGE_W, 1, k.BORDER)], None,
                    w=k.PAGE_W, h=k.ROW_H + 1, x=k.PAGE_PAD, y=0,
                    note="position sticky above the reflow breakpoint only (§7.5)")
    first = STUCK_AFTER + 2  # row STUCK_AFTER + 1 sits under the header
    last = min(len(k.ROWS), STUCK_AFTER + (k.BODY_H // row_h))
    hy = k.MAIN_Y
    ov = [stop(1, hy + 2, "sticky header"),
          *tags_row(["sticky header: wide only (§7.5)", "th Criterion scope=row; Level and Conformance level as words"],
                    hy + 30),
          tag_right("Level A ∕ Level AA: words, never a symbol (R-9)", hy + 30 + 3 * row_h),
          tag_right("Supports ∕ Partially Supports ∕ Does Not Support ∕ Not Applicable", hy + 30 + 6 * row_h)]
    fr = k.window(F_CRIT, page.node, scroll=sc, overlays=ov, main_extra=[sticky],
                  note=f"scrolled into the table: rows {first}-{last} of {len(k.ROWS)} under the sticky header")
    words = [r.word for r in k.ROWS]
    lines = [f"§7.2 item 7 L{k.L('7. All criteria:')}: a CMP-049 static table of the {len(k.ROWS)} rows named by its "
             "h2, columns Criterion (th scope=row), Level (\"Level A\" or \"Level AA\"), Conformance level, in "
             "words only",
             f"Rows {first}-{last} visible (row height {row_h} px, estimated); the dry run: "
             + ", ".join(f"{words.count(x_)} {x_}" for x_ in k.WORDS) + f" ({k.rule('R-9')})",
             f"§7.5 L{k.L('### 7.5 Reflow')}: the sticky header applies only above the reflow breakpoint; it is off "
             "at 200 %, at any text scale above the default and when stacked, so it never covers the focused link "
             "(2.4.11)",
             "The table holds nothing focusable: no row takes focus, the reader uses table keys"]
    return fr, k.frame_block(F_CRIT, lines)


def build() -> None:
    fr = [frame_crit()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
