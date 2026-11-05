"""E47-D09 / 03 anchors: a drawing's anchor nudge and the "Edit values…" fields (DE-07; F-10, F-03), and a
profile's anchor range (DE-08) (§2, §3, §14)."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
from common import k  # noqa: E402

NN = 3
RX = k.FRAME_W - k.RIGHT_W + 6
RW = k.RIGHT_W - 12
DRAW = "Rectangle"  # {object}: the drawing (a `14`:958 tool with two anchors); kit reading, recorded
I1, I2 = 18, 40  # the rectangle's anchor bars (seeded series indices)
BARS = k.SERIES[I1:I2 + 1]
P1 = max(b.h for b in BARS)  # anchor 1: the range's high at bar I1
P2 = min(b.l for b in BARS)  # anchor 2: the range's low at bar I2
NUDGE = 3  # `↑` three times on anchor 2 (one tick each, applied at once, D02E14:314)
P2N = k.tick_ladder(P2, NUDGE)
R0, R1 = 30, 44  # the profile's anchored range (bars), and the end moved by `→` three times (pending)
R1N = R1 + 3
HANDLE = 24  # D02E14:84: a handle's target >= 24 x 24 CSS px; the glyph 12 px


def bx(i: int) -> int:
    return c.x_of(i) + 4  # the bar's centre


def handle(name: str, *, focused: bool = False) -> c.Node:
    glyph = k.rect("glyph", 10, 10, k.DRAWING_SEL, {"radius": k.R_CONTROL}, x=7, y=7)
    h = k.box(f"handle · {name}", [glyph], {"radius": k.R_CONTROL}, w=HANDLE, h=HANDLE,
              note="a handle surrogate: target 24 x 24 CSS px, 12 px glyph (D02E14:84)")
    return k.focus_ring(h) if focused else h


def place(n: c.Node, cx: int, cy: int) -> c.Node:
    return dict(n, x=cx - int(n["w"]) // 2, y=cy - int(n["h"]) // 2)


def rectangle(p2: Decimal, *, focus2: bool) -> list[c.Node]:
    x1, x2, y1, y2 = bx(I1), bx(I2), c.y_of(P1), c.y_of(p2)
    shape = k.box(f"drawing · {DRAW}", [], {"stroke": k.DRAWING_SEL, "strokeWidth": k.THICK, "strokeAlign": "inner"},
                  w=x2 - x1, h=y2 - y1, x=x1, y=y1, note="the selected drawing (color.drawing.selected)")
    return [shape, place(handle("anchor 1"), x1, y1), place(handle("anchor 2", focused=focus2), x2, y2)]


def readout(chars: str, x: int, y: int, name: str) -> c.Node:
    return k.hbox(f"readout · {name}", [k.text("value", chars, k.NUM_XS, k.TEXT_1)],
                  {"padX": k.INSET_XS, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                   "strokeAlign": "inner", "radius": k.R_CONTROL},
                  w=round(k.text_w(chars, k.NUM_XS) + 12), h=18, x=x, y=y)


def frame_nudge() -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(NN, "drawing/anchor-nudge")
    ro = f"{k.px_fmt(P2)} → {k.px_fmt(P2N)}"
    lay = [*rectangle(P2N, focus2=True), readout(ro, bx(I2) + 24, c.y_of(P2N) + 14, "anchor 2")]
    chart = c.chart_body(c.position_lines(), lay)
    ov = [k.marker(1, c.CB_X + bx(I2) - 44, c.CB_Y + c.y_of(P2N) - 10, name="stop 1 · anchor 2"),
          k.callout("nudge", [f"↑ ×{NUDGE} on anchor 2 (applied at once, one undo):",
                              f"“{ro}”, coalesced (D02E14:314; the cadence D5, §6)"], RX, 120, RW),
          c.say("W-18", "W-18", DRAW, x=RX, y=260, wd=RW, head="Then Esc (polite): the nudge is kept",
                extra=["Ctrl+Z is the drawing's cancel (K-5; D09-C7)"])]
    fr = c.trading_window(fid, chart, focus="chart", overlays=ov,
                          note="the plot stop, then Tab into the handles stop; anchor 2 nudged by arrows")
    blk = [f"{k.de('DE-07')}: select = the handle surrogate after the plot stop; one tick / one bar, Shift ×10; "
           "applied at once, one undo",
           f"Drawn: {DRAW} from bar {BARS[0].hhmm} at {k.px_fmt(P1)} (anchor 1) to bar {BARS[-1].hhmm} at "
           f"{k.px_fmt(P2)} (anchor 2, its range's low); ↑ ×{NUDGE} = {k.px_fmt(P2N)} (tick {k.TICK})",
           f"{k.crow('D09-C6')}: PageUp / PageDown move between surrogates here, no ×100; {k.crow('D09-C7')}",
           f"A11Y-R-E14-D10-F-10 (§14 L{k.L('| A11Y-R-E14-D10-F-10')}): closed in design by this board",
           "Handles keep >= 24 x 24 CSS px (§13 2.5.8; D02E14:84)"]
    return fr, k.frame_block(fid, blk, keyboard="Tab into the handles stop; arrows nudge; PageUp / PageDown next "
                                                "surrogate; Esc keeps; Ctrl+Z undoes")


def stepper(label_: str, value: str, *, focused: bool = False, w_: int = 248) -> c.Node:
    minus, plus = (k.hbox(f"step · {nm}", [k.text("glyph", gl, k.BODY_STRONG, k.TEXT_1)],
                          {"justify": "center", "radius": k.R_CONTROL, "fill": k.ACTION_SECONDARY}, w=24, h=24)
                   for nm, gl in (("minus", "−"), ("plus", "+")))
    field = k.hbox("field", [k.text("value", value, k.NUM, k.TEXT_1)],
                   {"padX": k.INSET_SM, "fill": k.CANVAS, "radius": k.R_CONTROL, "stroke": k.BORDER_STRONG,
                    "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=w_ - 2 * 24 - 3 * 4 - 72 - (12 if focused else 0), h=k.CONTROL_H)
    if focused:
        field = k.focus_ring(field)
    return k.hbox(f"CMP-008 · {label_}", [k.text("label", label_, k.LABEL, k.TEXT_2, w=72), minus, field, plus],
                  {"gap": k.INSET_XS}, w=w_, h=k.CONTROL_H + (12 if focused else 0))


def frame_edit_values() -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(NN, "drawing/edit-values")
    k.copy_gap('"Edit values…" popover words "Anchors", "Anchor 1", "Anchor 2", "Time", "Price" and the title: '
               "E14-D02 §7.1's anchor field pairs (D02E14 §7.1) name no copy; the other popover fields are placeholders")
    pw = 280  # E14-D02 §7.1: 280 px compact (PROPOSED there)
    iw = pw - 2 * 12
    flds = [k.text("title", DRAW, k.HEADING_SM, k.TEXT_1),
            *[k.placeholder(f"field {i}", iw - 40 * (i % 2), 12) for i in (1, 2, 3)],
            k.text("anchors", "Anchors", k.LABEL, k.TEXT_2),
            k.text("a1", "Anchor 1", k.CAPTION, k.TEXT_2), stepper("Time", BARS[0].hhmm, w_=iw),
            stepper("Price", k.px_fmt(P1), w_=iw),
            k.text("a2", "Anchor 2", k.CAPTION, k.TEXT_2), stepper("Time", BARS[-1].hhmm, w_=iw),
            stepper("Price", k.px_fmt(P2N), focused=True, w_=iw)]
    pop = k.vbox("CMP-017 properties popover", flds, {"gap": k.STACK_SM, "pad": k.INSET_MD, "fill": k.OVERLAY,
                                                      "radius": k.R_CARD, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                                      "strokeAlign": "inner"}, w=pw,
                 note="non-modal (modal: false); Esc closes and returns focus to the drawing's surrogate")
    px_, py_ = bx(I2) + 40, 40
    chart = c.chart_body(c.position_lines(), [*rectangle(P2N, focus2=False), dict(pop, x=px_, y=py_)])
    ov = [k.callout("F-03", ["The price field: CMP-008, [−] / [+] one tick per click; the time: one bar per click "
                             "(F-03)", "Enter applies, tick-rounded; a pointer-only path, no drag"], RX, 120, RW)]
    fr = c.trading_window(fid, chart, focus="chart", overlays=ov, note="Enter on the selected drawing opened its "
                                                                         "properties; focus in anchor 2's price")
    blk = [f"§2.1 L{k.L('No coarse step depends on a key')}: a large move also has a typed path — \"Edit values…\" "
           "for a drawing (DE-07)",
           f"A11Y-R-E14-D10-F-03 (§14 L{k.L('| A11Y-R-E14-D10-F-03')}): the \"Edit values…\" path names its "
           "component, CMP-008 with one tick / one bar per step; handed to E14-D04",
           f"Drawn: the popover beside the selection, never over the focused handle (D02E14 §7.1); anchor 2 reads "
           f"{k.px_fmt(P2N)}, the nudged value of the previous frame"]
    return fr, k.frame_block(fid, blk, keyboard="Enter opens the popover; Tab through the fields; ↑ / ↓ step a "
                                                "field; Enter applies; Esc closes to the drawing")


def profile_buckets(r0: int, r1: int, size: int = 5) -> list[tuple[Decimal, int]]:
    """Seeded volume per bar (lcg), spread evenly over its low..high ticks, summed per `size`-tick bucket (bucket
    floor price, volume), top to bottom."""
    r = k.lcg(k.SEED + 38)
    acc: dict[Decimal, int] = {}
    for b in k.SERIES[r0:r1 + 1]:
        v = next(r) % 900 + 100
        n = int((b.h - b.l) / k.TICK) + 1
        for j in range(n):
            p = k.tick_ladder(b.l, j)
            fl = k.tick_ladder(k.MARK, (int((p - k.MARK) / k.TICK) // size) * size)
            acc[fl] = acc.get(fl, 0) + v // n
    return sorted(acc.items(), reverse=True)


def value_area(buckets: list[tuple[Decimal, int]], share: float = 0.70) -> tuple[int, set[int]]:
    """POC index and the value-area indices (grow from the POC toward the larger neighbour until >= share)."""
    vols = [v for _p, v in buckets]
    poc = vols.index(max(vols))
    lo = hi = poc
    tot = vols[poc]
    while tot < share * sum(vols):
        up = vols[lo - 1] if lo > 0 else -1
        dn = vols[hi + 1] if hi + 1 < len(vols) else -1
        if up >= dn:
            lo -= 1
            tot += up
        else:
            hi += 1
            tot += dn
    return poc, set(range(lo, hi + 1))


def vdashed(name: str, x: int, h: int, token: str) -> c.Node:
    k.fallback("dashed")
    return k.box(f"dashed · {name}", [k.rect(f"dash {i:02d}", 2, 8, token, x=0, y=i * 12) for i in range(h // 12)],
                 None, w=2, h=h, x=x, y=0)


def frame_profile() -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(NN, "profile/anchor-range")
    bk = profile_buckets(R0, R1)
    poc, va = value_area(bk)
    vmax = max(v for _p, v in bk)
    bars = []
    for i, (p, v) in enumerate(bk):
        tok = k.PROF_POC if i == poc else (k.PROF_VA if i in va else k.PROF_BAR)
        y0 = c.y_of(k.tick_ladder(p, 4))
        bars.append(k.rect(f"row {k.px_fmt(p)}", max(2, round(160 * v / vmax)), 5 * k.PX_PER_TICK - 2, tok,
                           x=bx(R0), y=y0))
    hb = c.CHART_H - 40
    lay = [k.box("profile · rows", bars, None, w=c.PLOT_W, h=c.CHART_H, x=0, y=0),
           k.rect("range start", 1, c.CHART_H, k.DRAWING, x=bx(R0), y=0),
           k.rect("range end", 1, c.CHART_H, k.DRAWING, x=bx(R1), y=0),
           vdashed("range end pending", bx(R1N), c.CHART_H, k.DRAWING_SEL),
           place(handle("range start"), bx(R0), hb), place(handle("range end", focused=True), bx(R1N), hb),
           readout(f"{k.SERIES[R1N].hhmm} pending", bx(R1N) + 22, hb - 9, "range end")]
    chart = c.chart_body([], lay)
    obj = "Profile range end"
    ov = [k.marker(1, c.CB_X + bx(R1N) - 44, c.CB_Y + hb - 10, name="stop 1 · range end"),
          c.say("W-25", "W-25", obj, k.SERIES[R1N].hhmm, x=RX, y=120, wd=RW,
                head=f"→ ×{R1N - R1} on the range end (polite):",
                extra=[f"Enter re-anchors {k.SERIES[R0].hhmm} – {k.SERIES[R1N].hhmm} as one undo; Esc restores "
                       f"{k.SERIES[R1].hhmm}"])]
    fr = c.trading_window(fid, chart, focus="chart", overlays=ov,
                          note="the anchor surrogate of a personalised-range profile; the end moved, pending")
    blk = [f"{k.de('DE-08')}: select = the anchor surrogate, as DE-07; one bar, Shift ×10, ×100; Enter re-anchors "
           "(one undo); Esc restores — PROPOSED → E19-D04",
           f"Drawn: the volume profile of bars {k.SERIES[R0].hhmm}–{k.SERIES[R1].hhmm} in 5-tick rows (POC "
           f"{k.px_fmt(bk[poc][0])}, value area 70 %, from the seeded volumes); the end's pending bar "
           f"{k.SERIES[R1N].hhmm} dashed with the word \"pending\"; the profile redraws only on Enter",
           f"{k.wcite('W-25')}; {k.krule('K-5')}"]
    return fr, k.frame_block(fid, blk, keyboard="Tab to the anchor surrogates; ← / → one bar; Enter applies; Esc "
                                                "restores")


def build() -> None:
    fr = [frame_nudge(), frame_edit_values(), frame_profile()]
    k.reading(f"board 03's drawing is a {DRAW} (two anchors, a `14`:958 tool) so both anchors and the time + price "
              "pairs show on one shape; the profile is a personalised-range volume profile on the chart (SCR-038 "
              "is also a chart overlay)")
    k.reading("the pending range end (DE-08, W-25) is drawn with a dashed vertical and the word \"pending\"; the "
              "profile rows keep the applied range until Enter")
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
