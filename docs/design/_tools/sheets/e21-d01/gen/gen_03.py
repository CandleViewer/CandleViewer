"""Board 03 placement-and-axes: beside vs behind, and one locked price axis (memo §6 placement and price-axis rows,
AD-1, AD-2; F-4, F-6; C1; K4). The heatmap trail and the ladder are the seeded book at the trail's last column."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 3
FW = 1120
IW = FW - 2 * k.FRAME_PAD
# SHEET-FIX 03 (live check 2026-11-03): two zooms with a 16 px gutter were 536 wide, 1096 with the gap in IW 1072,
# so the second overhung 24 px and cut its ladder's size texts; a 4 px gutter makes each 524 (524 + 24 + 524 = IW).
ZOOM_GUTTER = 4
SUPPORT = -2  # W1's "real support": the bid wall that stays (offset in ticks)


def last_book() -> dict[int, k.Decimal]:
    return k.TRAIL[-1]


def read_across(j: int, w: int, words: str) -> k.Node:
    k.fallback("marker")
    return k.rect(f"dashed · read across · {words}", w, rb.ROW_H, None,
                  {"stroke": k.TEXT_1, "strokeWidth": k.FOCUS_W, "strokeAlign": "outer"}, abs=True, x=0,
                  y=rb.HEAD_H + j * rb.ROW_H)


def beside(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    hr = rb.heat_region("heatmap region", 0)
    lad = rb.ladder("ladder region", 0, last_book(), k.MARKS[-1], show_own=True)
    j = rb.row_offs(0).index(SUPPORT)
    w = hr["w"] + 16 + lad["w"]
    pair = k.hbox("regions · beside", [hr, k.rect("gutter", 16, 20, None), lad,
                                       read_across(j, w, k.price(k.px(SUPPORT)))],
                  {"align": "start"}, w=w, h=rb.HEAD_H + 17 * rb.ROW_H + 18)
    k.derive(f"beside: {k.TRAIL_COLS} columns × 17 rows from {k.price(k.px(k.HALF))} down to "
             f"{k.price(k.px(-k.HALF))}, one tick ({k.TICK}) a row in both regions; the read-across row is the bid "
             f"wall at {k.price(k.px(SUPPORT))} ({k.size_fmt(last_book()[SUPPORT])} BTC, still resting at the last "
             f"column)")
    d, _ln = k.DEFAULTS["Heatmap placement"]
    tr, _l = k.DEFAULTS["Trail length"]
    k5, _k = k.KILLS["K5"]
    chip = k.hbox("header · trail chip", [rb.badge(k.memo("trail [60s v]"), strong=True),
                                          k.text("words", f"{k.memo('Trail length')}: {tr[1]}", k.CAPTION, k.TEXT_1,
                                                 w=IW - 140)], {"gap": k.INSET_SM, "align": "start"}, w=IW, h=32)
    return (k.frame(fid, [chip, pair, rb.marker(f"W1: read across on {k.price(k.px(SUPPORT))}", None),
                          k.hbox("cards", [rb.card("Default (PROPOSED)", [d[1]], (IW - 12) // 2),
                                           rb.card("Persona rationale (heuristic)", [d[2]], (IW - 12) // 2)],
                                 {"gap": k.INSET_MD, "align": "start"}, w=IW),
                          rb.card(f"K5 · {k5[1]} (a longer span changes resolution)", [k5[2], k5[3]], IW)],
                    FW, "Beside: the heatmap in its own region left of the ladder; nothing under a price, size or "
                        "own-order cell (AD-1)", proposed=True),
            k.frame_block(fid, ["The dashed row is the W1 read: from the band in the heatmap, along the same row, "
                                "into the ladder's size", "The header chip is the catalogue's trail default (memo "
                                "F-13 evidence); OQ-1 (chip = window_seconds or a zoom) is open"],
                          ads=["AD-1", "AD-9"], fs=["F-4", "F-13"]))


def behind(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    lad = rb.ladder("ladder region · clear rows", 0, last_book(), k.MARKS[-1], show_own=True, clear=True)
    heat = rb.heatmap("heatmap · under the ladder", 0, behind=True)
    layer = k.box("regions · behind", [dict(heat, x=0, y=rb.HEAD_H, w=lad["w"]), dict(lad, x=0, y=0)],
                  {"fill": k.SUNKEN}, w=lad["w"], h=lad["h"])
    d, _ln = k.DEFAULTS["Heatmap placement"]
    c1, _l = k.CONTRAS["C1"]
    return (k.frame(fid, [k.hbox("layout", [layer, k.vbox("notes", [
        rb.marker("recorded other position — violates AD-1 as drawn", 400),
        rb.card("Other position recorded (memo §6)", [d[3]], 400),
        rb.card("C1", [c1[1], c1[2]], 400),
        rb.card("F-4 (heuristic) · Major", [k.FINDINGS["F-4"][0][1]], 400)], {"gap": k.STACK_SM}, w=400)],
        {"gap": k.INSET_XL, "align": "start"}, w=IW)],
        FW, "Behind: the heatmap ramp under the size numbers and the own-order cells (the recorded other position, "
            "C1); the size text sits on a moving ramp", proposed=True),
        k.frame_block(fid, ["Same rows, same columns as the beside frame; the heatmap is stretched under the "
                            f"ladder's {lad['w']} px", "T1 (board 08) decides between the two"],
                      ads=["AD-1"], fs=["F-4"]))


def locked_zoom(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    zs = []
    for step, words in ((k.ZOOM_OUT, f"1 row = {k.TICK * k.ZOOM_OUT} ({k.ZOOM_OUT} ticks)"),
                        (1, f"after +: 1 row = {k.TICK} (1 tick)")):
        hr = rb.heatmap("heatmap", 0, step=step, carriers=False)
        lad = rb.ladder("ladder", 0, last_book(), k.MARKS[-1], step=step)
        zs.append(k.vbox(f"zoom · {step}", [k.text("zoom", words, k.NUM_SM, k.TEXT_1),
                                            k.hbox("regions", [k.vbox("heat", [k.rect("head", hr["w"], rb.HEAD_H,
                                                                                      k.RAISED), hr], {},
                                                                      w=hr["w"], h=rb.HEAD_H + hr["h"]),
                                                               k.rect("gutter", ZOOM_GUTTER, 20, None), lad],
                                                   {"align": "start"}, w=hr["w"] + ZOOM_GUTTER + lad["w"], h=lad["h"])],
                         {"gap": k.STACK_XS}, w=hr["w"] + ZOOM_GUTTER + lad["w"]))
    if sum(z["w"] for z in zs) + k.PX[k.INSET_XL] * (len(zs) - 1) > IW:
        raise ValueError(f"locked-zoom: zooms {[z['w'] for z in zs]} + gaps overflow IW {IW}")
    lo, hi = rb.row_offs(0, k.ZOOM_OUT)[-1], rb.row_offs(0, k.ZOOM_OUT)[0] + k.ZOOM_OUT - 1
    k.derive(f"zoom: {k.ZOOM_OUT}-tick rows sum the ticks of each row in both regions ({k.price(k.px(lo))}–"
             f"{k.price(k.px(hi))}); after + one tick a row; the heatmap and the ladder use the same step in both")
    kc, _ln = k.KILLS["K4"]
    keys = k.hbox("keys", [rb.key_cap("+"), rb.key_cap("-"), k.text("words", k.memo("+/- = price zoom"), k.CAPTION,
                                                                   k.TEXT_1)], {"gap": k.INSET_XS}, h=20)
    return (k.frame(fid, [keys, k.hbox("zooms", zs, {"gap": k.INSET_XL, "align": "start"}, w=IW),
                          rb.card(f"K4 · {kc[1]}", [kc[2], kc[3]], IW)],
                    FW, "One locked price axis: heatmap rows and ladder rows align tick for tick; +/- zoom moves both "
                        "(AD-2)", proposed=True),
            k.frame_block(fid, ["No separate heatmap zoom control is drawn (K4 killed it for SCR-050)",
                                f"Lo-fi: the {k.ZOOM_OUT}-tick row that holds the mark sums the best bid and the asks "
                                "inside it"],
                          ads=["AD-2"], fs=["F-6"]))


if __name__ == "__main__":
    built = [f(fid) for f, fid in zip((beside, behind, locked_zoom), k.BOARDS[NN].frames)]
    rb.run(NN, ([b[0] for b in built], [b[1] for b in built]), 1,
           board_lines=[f"Trail excerpt: the last {k.TRAIL_COLS} columns × {k.COL_MS} ms of the {k.TRAIL_S} s trail "
                        "(seeded); prints are filled dots; the pulled carrier is the hatched outline (board 04)"])
