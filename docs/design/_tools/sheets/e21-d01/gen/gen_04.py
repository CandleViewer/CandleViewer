"""Board 04 pulled-vs-consumed: the two marks and the estimated carrier (memo §6 pulled-liquidity row, AD-6; F-7, F-8,
F-9; C8; OQ-5). The consumed level is the +3-tick ask wall traded through in four prints; the pulled level is the
-5-tick bid wall that vanishes with no print at its price (seeded trail)."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 4
FW = 1200
IW = FW - 2 * k.FRAME_PAD
CW2 = 32  # the enlarged row strip: one column (100 ms) = 32 px


def history(off: int) -> list[dict[str, str]]:
    """The level's columns where it changes (and one before): time, size, prints at its price."""
    rows, prev = [], None
    for c in range(k.TRAIL_COLS):
        s = k.TRAIL[c][off]
        pq = [q for c_, o, q in k.PRINTS if c_ == c and o == off]
        if prev is None or s != prev or pq:
            rows.append({"t": k.ms_label(c), "size": k.size_fmt(s),
                         "print": " + ".join(k.size_fmt(q) for q in pq) if pq else "none"})
        prev = s
    return rows


def level_table(off: int, cap: str) -> k.Node:
    cols = [k.Col("t", "column", 88), k.Col("size", "size (BTC)", 104), k.Col("print", "prints at this price", 184)]
    return k.grid_table(f"history · {k.price(k.px(off))}", cols, history(off), row_h=24, cap=cap)


def strip(off: int, *, label: list[k.Node]) -> k.Node:
    """One level across the trail, CW2 px a column: the ramp runs, the print marks, the pulled carrier."""
    k.fallback("ramp")
    kids: list[k.Node] = []
    c = 0
    while c < k.TRAIL_COLS:
        b = k.bucket(k.TRAIL[c][off])
        e = c
        while e + 1 < k.TRAIL_COLS and k.bucket(k.TRAIL[e + 1][off]) == b:
            e += 1
        if b:
            kids.append(k.rect(f"liquidity · c{c:02d}-{e:02d}", (e - c + 1) * CW2, 24, rb.RAMP_TOK[b], x=c * CW2, y=4))
        c = e + 1
    for c_, o, _q in k.PRINTS:
        if o == off:
            kids.append(k.ellipse(f"print · c{c_:02d}", 12, 12, {"fill": k.TEXT_1, "stroke": k.APP,
                                                                "strokeWidth": k.HAIR}, x=c_ * CW2 + 10, y=10))
    if off == k.PULLED_OFF:
        gone = next(c_ for c_ in range(k.TRAIL_COLS) if k.TRAIL[c_][off] == 0)
        kids.append(rb.pulled_carrier("strip", (k.TRAIL_COLS - gone) * CW2, 24, x=gone * CW2, y=4))
    w = k.TRAIL_COLS * CW2
    body = k.box("trail row", kids, {"fill": k.SUNKEN, "clip": True}, w=w, h=32)
    return k.hbox(f"level · {k.price(k.px(off))}", [k.text("price", k.price(k.px(off)), k.NUM_SM, k.TEXT_1, w=72),
                                                     body, *label], {"gap": k.INSET_SM}, h=32)


def estimated() -> k.Node:
    return rb.badge(k.memo("(estimated)"), name="CMP-227 EstimatedBadge · (estimated)")


def consumed(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    off = k.CONSUMED_OFF
    start = k.TRAIL[0][off]
    tot = sum((q for _c, o, q in k.PRINTS if o == off), Decimal(0))
    k.derive(f"consumed: {k.price(k.px(off))} holds {k.size_fmt(start)} BTC; prints at that price total "
             f"{k.size_fmt(tot)} BTC over {sum(1 for _c, o, _q in k.PRINTS if o == off)} columns; "
             f"{k.size_fmt(start)} − {k.size_fmt(tot)} = {k.size_fmt(start - tot)}")
    return (k.frame(fid, [k.hbox("pair", [rb.heat_region("heatmap region", 0),
                                          level_table(off, f"The {k.price(k.px(off))} ask wall, column by column "
                                                           "(seeded)")], {"gap": k.INSET_XL, "align": "start"}, w=IW),
                          strip(off, label=[rb.marker("consumed: prints at this price", None)]),
                          rb.card("F-8 (heuristic) · Major", [k.FINDINGS["F-8"][0][1]], IW)],
                    FW, "Consumed: a level that shrank because it traded — the prints at its price account for the size "
                        "(filled dots on the trail)", proposed=True),
            k.frame_block(fid, ["The level ends where the prints end; no estimate word: a consumed level is "
                                "observed, not inferred"], ads=["AD-6"], fs=["F-8"]))


def pulled(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    off = k.PULLED_OFF
    gone = next(c for c in range(k.TRAIL_COLS) if k.TRAIL[c][off] == 0)
    k.derive(f"pulled: {k.price(k.px(off))} holds {k.size_fmt(k.TRAIL[0][off])} BTC until {k.ms_label(gone - 1)}, "
             f"0 from {k.ms_label(gone)}; no print at that price in the {k.TRAIL_COLS} columns; the mark never trades "
             f"below {k.price(k.px(min(k.MARKS)))}")
    return (k.frame(fid, [k.hbox("pair", [rb.heat_region("heatmap region", 0),
                                          level_table(off, f"The {k.price(k.px(off))} bid wall, column by column "
                                                           "(seeded)")], {"gap": k.INSET_XL, "align": "start"}, w=IW),
                          strip(off, label=[estimated()]),
                          k.hbox("cards", [rb.card("F-7 (heuristic) · Major", [k.FINDINGS["F-7"][0][1]],
                                                   (IW - 12) // 2),
                                           rb.card("F-9 (heuristic) · Minor", [k.FINDINGS["F-9"][0][1]],
                                                   (IW - 12) // 2)], {"gap": k.INSET_MD, "align": "start"}, w=IW)],
                    FW, "Pulled: a level removed without matching prints — the hollow, hatched carrier plus the "
                        "CMP-227 EstimatedBadge text (an inference, never a fact)", proposed=True),
            k.frame_block(fid, ["The carrier starts at the column where the level vanished and runs to now",
                                "OQ-5 open: the carrier is drawn on the heatmap only here; whether the ladder row "
                                "carries it too is E21-S07 #707 / E21-D02 #440's"], ads=["AD-6"], fs=["F-7", "F-9"]))


def side_by_side(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    if k.bucket(k.TRAIL[0][k.CONSUMED_OFF]) != k.bucket(k.TRAIL[0][k.PULLED_OFF]):
        raise ValueError("the two walls must start on the same ramp step")
    d, _ln = k.DEFAULTS["Pulled liquidity"]
    c8, _l = k.CONTRAS["C8"]
    caveat = rb.card("caveat on demand (CMP-227)", [k.memo("without L3 data replenishment is inferred from L2 changes "
                                                           "only"),
                                                    k.memo("(estimated) a level dropped without matching prints")],
                     520, name="dashed · caveat on demand")
    return (k.frame(fid, [k.vbox("pair", [strip(k.CONSUMED_OFF, label=[rb.marker("consumed", None)]),
                                          strip(k.PULLED_OFF, label=[estimated(), rb.marker("pulled", None)])],
                                 {"gap": k.STACK_SM}, w=IW),
                          k.hbox("cards", [caveat, k.vbox("rules", [
                              rb.card("Default (PROPOSED)", [d[1]], IW - 520 - 12),
                              rb.card("C8 · no intent word in UI copy", [c8[1], c8[2]], IW - 520 - 12)],
                              {"gap": k.STACK_SM}, w=IW - 520 - 12)], {"gap": k.INSET_MD, "align": "start"}, w=IW)],
                    FW, "Side by side: the two marks differ by pattern (dots vs a hatched hollow outline), which "
                        "survives greyscale; the pulled one carries the estimated word", proposed=True),
            k.frame_block(fid, [f"Greyscale check: both walls start on ramp step "
                                f"{k.bucket(k.TRAIL[0][k.CONSUMED_OFF])} of 4 (≥ {k.anchor(k.WALL)} BTC); the consumed "
                                "one steps down as it trades, the pulled one ends at once; the endings differ by "
                                "pattern, not by lightness (AD-6 violates if lightness alone differs)",
                                "The caveat card is the on-demand text (dashed: shown on request, not by default)"],
                          ads=["AD-6"], fs=["F-8"]))


if __name__ == "__main__":
    built = [f(fid) for f, fid in zip((consumed, pulled, side_by_side), k.BOARDS[NN].frames)]
    rb.run(NN, ([b[0] for b in built], [b[1] for b in built]), 1,
           board_lines=["T2 (board 08) tests whether participants tell pulled from consumed and mention the estimate"])
