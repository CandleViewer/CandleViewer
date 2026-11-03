"""Board 04 `E47-D06 / 04 ladder-table` (dark): AC3 — the ladder table sorted by cumulative depth, My levels only on,
focus on a row; then one patch tick: values rewritten in place, focus, position, sort and filter kept (§6.4)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (PX0, grid_y, k, ladder_body, ladder_panel, ladder_table_rows,  # noqa: E402
                    native_left)

NN = 4
N_ASK, N_BID = 6, 16  # kit choice: the native grid's visible depth (6 asks over 16 bids), AC3's level inside it
LEFT_W = 328  # the native grid's width (96 + 80 + 80 + 72)
TX = PX0 + k.PX[k.INSET_SM] + LEFT_W + 12  # the ladder table's left edge in frame coordinates
CX = TX + sum(c.w for c in k.LADDER_COLS) + 40 + 2 * k.PX[k.INSET_SM] + 8  # the patch tags, right of the rows
BY = grid_y(len(k.MY_ROWS) + 2)  # callouts under the table's rows


def _patched() -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for a, b in zip(k.MY_ROWS, k.MY_ROWS_NEXT_HELD):
        s = set()
        if a.size != b.size:
            s.add("Bid size" if a.side == "buy" else "Ask size")
        if a.depth != b.depth:
            s.add("Cumulative depth")
        if s:
            out[a.k] = s
    return out


def frames() -> list[dict]:
    b = k.BOARDS[NN]
    fk = k.FOCUS_ROW.k
    f1 = k.window(b.frames[0], [ladder_panel(ladder_body(
        ladder_table_rows(k.MY_ROWS, fk), chips=(k.MY_LEVELS_LABEL,), shown=len(k.MY_ROWS), total=len(k.BOOK),
        left=native_left(N_ASK, N_BID)))],
        overlays=[k.callout("AC3", [f"Sorted by cumulative depth, ascending; {k.MY_LEVELS_LABEL} on; focus on "
                                    f"{k.px_fmt(k.AC3_PRICE)} (aria-current)",
                                    "Rows keyed by price level (D04:118), never by row index (R-6)"],
                            TX, BY, wd=320),
                  k.callout("the native grid", ["CMP-108, native DOM (IV-6): no canvas node; the table is kept "
                                                "beside it because `05` mandates it (§6.2)"], TX + 344, BY, wd=320)])
    patched = _patched()
    rows2 = ladder_table_rows(k.MY_ROWS_NEXT_HELD, fk, patched=patched)
    held = [r.k for r in k.MY_ROWS_NEXT_HELD] != [r.k for r in k.MY_ROWS_NEXT_SORTED]
    f2 = k.window(b.frames[1], [ladder_panel(ladder_body(
        rows2, chips=(k.MY_LEVELS_LABEL,), shown=len(k.MY_ROWS), total=len(k.BOOK),
        left=native_left(N_ASK, N_BID, book=k.BOOK_NEXT)))],
        overlays=[k.callout("the tick", [f"One tick of the SCR-117 cadence: {sum(len(v) for v in patched.values())} "
                                         "cells rewritten in place (marked); no row node recreated (QA-2)",
                                         "The focused row keeps focus, its position and aria-current; the filter "
                                         "keeps its rows; a tick patch announces nothing (§13)"],
                            TX, BY, wd=320),
                  k.callout("order held", ["While focus is inside the grid the rows are not re-ordered; the sort is "
                                           "re-applied when focus leaves, on Shift+R or on resume (§6.4)",
                                           ("Re-applied order: " + ", ".join(k.px_fmt(k.price(r.k))
                                                                              for r in k.MY_ROWS_NEXT_SORTED))
                                           if held else "The patched depths keep the same order"],
                            TX + 344, BY, wd=320),
                  *[k.tag("patched", CX, grid_y(i) + 4) for i, r in enumerate(k.MY_ROWS, 1) if r.k in patched]])
    return [f1, f2]


def blocks() -> list[tuple[str, list[str]]]:
    b = k.BOARDS[NN]
    return [(b.frames[0], [f"AC3 (§6.4 L{k.AC3_LINE}): sorted by cumulative depth, {k.MY_LEVELS_LABEL} on, focus "
                           f"on {k.px_fmt(k.AC3_PRICE)}",
                           f"Columns (§6.2 L{k.L('**DOM ladder**', k._S62)}): " + " · ".join(c.name for c in
                                                                                             k.LADDER_COLS),
                           f"My orders reads the panel's own account only (§10 L{k.L('- **My orders.**')}); flag "
                           f"word N-6 \"{k.N6_FLAG}\"",
                           f"{len(k.MY_ROWS)} own-order levels of {len(k.BOOK)} drawn ({k.BOOK_LEVELS} a side); "
                           "the depth runs from the best price outward on each side (`05`)"]),
            (b.frames[1], ["The same rows one tick later (seeded size changes on a fifth of the levels); depths "
                           "re-derived from the new sizes",
                           "Pause updates (PROPOSED, D06-Q6) would stop the patch; it is off here"])]


def notes() -> None:
    k.copy_key(f"{k.EXPORT_KEY} (PROPOSED, owner E11-D04): \"{k.EXPORT_REASON}\", the Export CSV T2 reason")
    k.ambiguity("\"sorted by cumulative depth\" (AC3) names no direction: drawn ascending, the first activation of "
                "§6.3's tri-state (nearest depth first)")
    k.ambiguity("Bid size on an ask level and Ask size on a bid level read \"—\" (`05` gives one row per price "
                "level; a level rests on one side)")
    k.copy_gap("the native grid's column words \"Price\", \"Bid\", \"Ask\", \"Mine\" are kit labels (CMP-108's own "
               "header words are E21's)")
    k.deviate(f"own orders at {', '.join(k.px_fmt(k.price(r.k)) for r in k.MY_ROWS)} (synthetic); BASE is derived "
              f"so that AC3's {k.px_fmt(k.AC3_PRICE)} is one of them")


def main() -> None:
    notes()
    p, md, pk = k.build(NN, frames(), blocks(), per_row=2)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
