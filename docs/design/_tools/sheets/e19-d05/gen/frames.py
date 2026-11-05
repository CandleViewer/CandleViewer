"""E19-D05 frame builders: the motion strips (frame 0, the middle of the token duration, the end; the reduce strip
beneath), the timelines and the spec's tables. A key frame is a crop of the docked CMP-183 panel (FALLBACKS crop) or
of the SCR-030 pane under the overlay. Every drawn word is the spec's, D03's or D02's (k.S checks it verbatim, k.W
fills a copy-deck string) or is noted as a copy gap with its source; every number is derived from the kit's synthetic
world (seed 500) or the pinned motion primitives."""
from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e19d05kit as k  # noqa: E402
from e19d05kit import S, Node, box, rect, text, vbox  # noqa: E402

CANDLE_UP, CANDLE_DOWN, WICK = "color.candle.up", "color.candle.down", "color.candle.wick"
CROP_W, INSET, LANE, GUTTER = 280, 8, 10, 56  # D03 §10.1 redlines (PROPOSED there): panel 280, lane 10, gutter 56
RUN = CROP_W - 2 * INSET - LANE - GUTTER
X_AXIS, LANE_X, GUT_X = INSET + LANE, INSET, INSET + LANE + RUN
HEAD_H, LEG_H, LEG_LINE = 28, 92, 14
PLOT_H = 288  # 24 rows of 12 px at the 100-tick row size (kit choice)
PAD, LABEL_W, GAP, CAP_H, TITLE_H = 24, 168, 24, 36, 64


# --- words -----------------------------------------------------------------------------------------------------------
def say(chars: str, doc: str | None = None) -> str:
    """A drawn word that stands verbatim in a source (spec, D03 or D02)."""
    S(chars, doc)
    k.copy_key(f'"{chars}" ({k.SL(chars, doc)})')
    return chars


def gap_word(chars: str, src: str) -> str:
    k.copy_gap(f'"{chars}": {src}')
    return chars


def price(ticks: int | Decimal) -> str:
    """A price in USDT from integer ticks, grouped, at the tick's decimals (`62,550.0`)."""
    v = (Decimal(ticks) * k.TICK).quantize(k.TICK)
    return f"{v:,.{k.PRICE_DP}f}"


def hm(t: datetime) -> str:
    return f"{t:%H:%M}"


def hms(t: datetime) -> str:
    return f"{t:%H:%M:%S}"


def num(n: int) -> str:
    """An integer grouped as the spec writes it ("5 000")."""
    return f"{n:,}".replace(",", " ")


def ms(n: int) -> str:
    return num(n) + " ms"


def row_word(pr: k.Profile) -> str:
    return k.W("W-19", doc="d02", n=str(pr.row_ticks), price=price(pr.row_ticks))


def va_word() -> str:
    return k.tpl("VA 70 %", {"70": str(k.VA_PCT)}, "d02")


def w1(pr_from: k.Profile, pr_to: k.Profile) -> str:
    """W-1 on a POC move: the direction glyph and the row count ("1 row" in the singular, §8.3)."""
    n = pr_to.poc - pr_from.poc
    s = k.W("W-1", 0 if n > 0 else 1, price=price(pr_to.poc * pr_to.row_ticks), n=str(abs(n)))
    if abs(n) == 1:
        k.reading(f"W-1 singular: {k.SL('in the singular')} — \"1 rows\" is drawn \"1 row\"")
        s = s.replace("1 rows", "1 row")
    return s


def w1b(pr_from: k.Profile, pr_to: k.Profile) -> str:
    n = pr_to.poc - pr_from.poc
    return k.W("W-1b", 0 if n > 0 else 1, n=str(abs(n)))


def w33(pr: k.Profile) -> str:
    s = k.DECK["d02"]["W-33"][0][0]
    out = s
    for v in (pr.poc, pr.va[1], pr.va[0]):
        out = out.replace("{price}", price(v * pr.row_ticks), 1)
    k.copy_key(f'D02 W-33: "{s}" (D02 L{k.DECK["d02"]["W-33"][1]}) filled from the world')
    return out


def state_word(pr: k.Profile, at: datetime) -> str:
    return k.W("D03 W-11") if pr.complete else k.W("D03 W-10", **{"HH:MM": hm(at)})


# --- small pieces ----------------------------------------------------------------------------------------------------
def hidden(chars: str, *, w: int = 360, label: str = "visually hidden") -> Node:
    """A string a screen reader hears, drawn for the board (FALLBACKS hidden)."""
    k.fallback("hidden")
    k.copy_gap(f'"{label}": the kit\'s marker label for a string a screen reader hears (board marker)')
    return vbox(f"board marker · {label}", [text("marker", label, k.CAPTION, k.TEXT_3),
                                            text("words", chars, k.CAPTION, k.TEXT_2, w=w - 16)],
                {"gap": k.STACK_XS, "pad": k.INSET_SM, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                 "strokeAlign": "inner", "radius": k.R_CONTROL, "fill": k.SUNKEN}, w=w,
                note="board marker: not on screen in the product")


def marker_box(name: str, lines: list[str], *, w: int = 320, title: str | None = None) -> Node:
    """A board marker box: a measurement or a reading note beside a specimen (never product UI)."""
    k.fallback("marker")
    kids = ([text("title", title, k.LABEL, k.TEXT_1, w=w - 16)] if title else []) + [
        text(f"line {i:02d}", ln, k.CAPTION, k.TEXT_2, w=w - 16) for i, ln in enumerate(lines, 1)]
    return vbox(f"board marker · {name}", kids, {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.CANVAS,
                                                "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                                                "strokeAlign": "inner", "radius": k.R_CARD}, w=w,
                note="board marker, not product UI")


def frame(fid: str, kids: list[Node], w: int, h: int, *, note: str | None = None) -> Node:
    return box(k.frame_name(fid), kids, {"fill": k.APP, "clip": True}, w=w, h=h, note=note)


def alpha_rect(name: str, w: int, h: int, ink: str, alpha: float, x: int, y: int) -> Node | None:
    """A shape at a key frame's opacity: 1 solid, 0 absent, between: its outline (FALLBACKS alpha)."""
    if alpha <= 0:
        return None
    if alpha >= 1:
        return rect(name, w, h, ink, x=x, y=y)
    k.fallback("alpha")
    return rect(f"{name} · outline", w, h, None, {"stroke": ink, "strokeWidth": k.HAIR, "strokeAlign": "inner"},
                x=x, y=y)


# --- the crop: the docked CMP-183 panel at one key frame -------------------------------------------------------------
@dataclass
class Ray:
    row: int
    label: str
    alpha: float = 1.0
    tested: bool = False


@dataclass
class Crop:
    pr: k.Profile
    window: tuple[int, int]  # [lo, hi) rows drawn, top = hi - 1
    period: str
    state: str
    extra: list[str] = field(default_factory=list)  # legend lines after the row-size line (W-1, counts, …)
    plot_h: int = PLOT_H
    busy: bool = False  # D03's 2 px busy bar under the header (§6.1)
    trace: tuple[int, int, float] | None = None  # (from row, to row, opacity): M-2's band
    emphasis: float = 0.0  # M-4's bracket emphasis opacity
    caps: str = "developing"  # "developing" (the open edge on the last price's side) | "final" (both caps)
    rays: list[Ray] = field(default_factory=list)
    shade: bool = False  # CMP-078's stale shade (the feed-break contrast case)
    status: str | None = None  # a header status word (E17's, on the contrast case)
    max_vol: int | None = None  # the scale maximum (default: the profile's)
    mark_rows: tuple[int, ...] = ()  # rows a board marker brackets (M-1's changed rows)


def crop_h(c: Crop) -> int:
    return HEAD_H + c.plot_h + LEG_H


def _merge(c: Crop) -> int:
    """Rows under 2 px merge by summing adjacent levels (`26`:238, D03 §7.4): k = ceil(2 px ÷ the row's height)."""
    rows = c.window[1] - c.window[0]
    return math.ceil(2 * rows / c.plot_h) if c.plot_h / rows < 2 else 1


def _label_stack(labels: list[tuple[str, list[str], float, str]], y_min: float, y_max: float) -> list[Node]:
    """Level words in the gutter (type.num.xs, 12 px a line), pushed apart so none overlaps; one dropped past the plot
    keeps its mark (the legend and the table carry it)."""
    out, last = [], y_min - 1000.0
    for key, lines, want, ink in sorted(labels, key=lambda a: a[2]):
        h = 12 * len(lines)
        y = max(want - h / 2, last, y_min)
        if y + h > y_max:
            continue
        last = y + h + 2
        for i, ln in enumerate(lines):
            out.append(text(f"{key} · line {i + 1}", ln, k.NUM_XS, k.TEXT_1 if i == 0 else k.TEXT_2,
                            x=GUT_X + 8, y=round(y + 12 * i)))
    return out


def crop(name: str, c: Crop) -> Node:
    """One key frame: header strip, plot (bars, POC rail, VA bracket and ticks, rays, the motion's shape), legend."""
    k.fallback("crop")
    lo, hi = c.window
    rows = hi - lo
    rowpx = c.plot_h / rows
    m = _merge(c)
    pt = HEAD_H

    def y_of(r: int) -> float:
        return pt + (hi - r - 1) * rowpx

    kids: list[Node | None] = [
        rect("header strip", CROP_W, HEAD_H, k.RAISED, x=0, y=0),
        text("header title", k.W("W-1", doc="d02"), k.LABEL, k.TEXT_1, x=INSET, y=7),
        text("header status", c.status, k.CAPTION, k.WARN_STRONG, x=CROP_W - INSET - round(k.text_w(c.status, k.CAPTION)),
             y=8) if c.status else None,
        rect("plot", CROP_W, c.plot_h, k.CANVAS, x=0, y=pt)]
    groups = [list(range(g, min(g + m, hi))) for g in range(lo, hi, m)]
    vols = [sum(c.pr.vol(r) for r in g) for g in groups]
    maxv = c.max_vol or max(vols)
    for g, v in zip(groups, vols):
        if not v:
            continue
        top, bot = y_of(g[-1]), y_of(g[0]) + rowpx
        h = bot - top
        hh = max(1, round(h - 1 if h >= 3 else h))
        ink = k.P_VA if any(c.pr.va[0] <= r <= c.pr.va[1] for r in g) else k.P_BAR
        kids.append(rect(f"bar {g[0]}", max(1, round(v / maxv * RUN)), hh, ink, x=X_AXIS, y=round(top)))
    labels: list[tuple[str, list[str], float, str]] = []
    poc_g = next((g for g in groups if c.pr.poc in g), None)
    if poc_g:
        top, bot = y_of(poc_g[-1]), y_of(poc_g[0]) + rowpx
        kids += [rect("POC rail top", RUN, 1, k.P_POC, x=X_AXIS, y=round(top)),
                 rect("POC rail bottom", RUN, 1, k.P_POC, x=X_AXIS, y=round(bot) - 1)]
        labels.append(("level POC", [say("POC"), price(c.pr.poc * c.pr.row_ticks)], (top + bot) / 2, k.P_POC))
    va_top = max(y_of(c.pr.va[1]), pt)
    va_bot = min(y_of(c.pr.va[0]) + rowpx, pt + c.plot_h)
    if va_bot > va_top:
        kids.append(rect("VA bracket", 2, round(va_bot - va_top), k.P_VA, x=LANE_X + 1, y=round(va_top)))
        last_up = c.pr.last_ticks >= (c.pr.va[0] + c.pr.va[1] + 1) * c.pr.row_ticks / 2
        for edge, yy, show in (("VAH", va_top, c.caps == "final" or not last_up),
                               ("VAL", va_bot - 2, c.caps == "final" or last_up)):
            if show and lo <= (c.pr.va[1] if edge == "VAH" else c.pr.va[0]) < hi:
                kids.append(rect(f"VA bracket cap {edge}", 6, 2, k.P_VA, x=LANE_X + 1, y=round(yy)))
        kids.append(alpha_rect("bracket emphasis", k.LANE_BRACKET, round(va_bot - va_top), k.P_VA, c.emphasis,
                               LANE_X + 1, round(va_top)) if c.emphasis else None)
    for word, r in (("VAH", c.pr.va[1]), ("VAL", c.pr.va[0])):
        if lo <= r < hi:
            yy = y_of(r) + rowpx / 2
            kids.append(rect(f"{word} tick", 6, 2, k.P_VA, x=GUT_X, y=round(yy - 1)))
            labels.append((f"level {word}", [say(word), price(r * c.pr.row_ticks)], yy, k.P_VA))
    if c.trace:
        a, b, al = c.trace
        t_top, t_bot = y_of(max(a, b)), y_of(min(a, b)) + rowpx
        kids.append(alpha_rect("POC trace band", k.LANE_TRACE, round(t_bot - t_top), k.P_POC, al, GUT_X,
                               round(t_top)))
    for i, ry in enumerate(c.rays):
        if not lo <= ry.row < hi:
            continue
        yy = round(y_of(ry.row) + rowpx / 2)
        if ry.tested:
            kids += [rect(f"tested ray {i} · dash {j}", 4, 1, k.TEXT_3, x=X_AXIS + 7 * j, y=yy)
                     for j in range(RUN // 7)]
        else:
            kids.append(alpha_rect(f"nPOC ray {i}", RUN, 1, k.P_POC, ry.alpha, X_AXIS, yy))
        if ry.alpha > 0 or ry.tested:
            kids.append(text(f"nPOC label {i}", ry.label, k.NUM_XS, k.TEXT_2,
                             x=GUT_X - 4 - round(k.text_w(ry.label, k.NUM_XS)), y=yy - 13))
    if c.mark_rows:
        mt = y_of(max(c.mark_rows)) - 2
        mb = y_of(min(c.mark_rows)) + rowpx + 2
        k.fallback("marker")
        kids.append(rect("board marker · changed rows", RUN + 4, round(mb - mt), None,
                         {"stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR, "strokeAlign": "inner"},
                         x=X_AXIS - 2, y=round(mt)))
    if c.shade:
        k.fallback("scrim")
        kids.append(rect("CMP-078 stale shade", CROP_W, c.plot_h, k.STALE_SURFACE, {"opacity": k.SCRIM}, x=0, y=pt))
    if c.busy:
        kids.append(rect("busy bar", CROP_W, 2, k.RING, x=0, y=HEAD_H - 2))
    kids += _label_stack(labels, pt + 2, pt + c.plot_h - 2)
    ly = pt + c.plot_h
    kids.append(rect("legend strip", CROP_W, LEG_H, k.RAISED, x=0, y=ly))
    first = f"{c.period} · {c.state}"
    head = [first] if k.text_w(first, k.CAPTION) <= CROP_W - 2 * INSET else [c.period, c.state]
    lines = [*head, f"{say('Volume')} · {row_word(c.pr)}", va_word(), *c.extra]
    if len(lines) > 5:
        raise ValueError(f"{name}: {len(lines)} legend lines > 5")
    for i, ln in enumerate(lines):
        if k.text_w(ln, k.CAPTION) > CROP_W - 2 * INSET:
            raise ValueError(f"{name}: legend line {ln!r} wider than the crop")
        kids.append(text(f"legend line {i + 1}", ln, k.CAPTION, k.TEXT_2 if i else k.TEXT_1, x=INSET,
                         y=ly + 6 + i * (LEG_LINE + 2)))
    return box(name, kids, {"fill": k.CANVAS, "clip": True}, w=CROP_W, h=crop_h(c))


# --- strips and frames -----------------------------------------------------------------------------------------------
@dataclass
class Strip:
    label: str
    lines: list[str]
    cells: list[tuple[list[str], Node]] = field(default_factory=list)  # (caption lines, crop)


def key_caption(key: k.Key, *extra: str) -> list[str]:
    """A key frame's time caption: §0's word for it and t in ms."""
    word = {"frame 0": say("frame 0"), "middle": say("the middle"), "end": say("the end")}[key.word]
    return [f"{word} · t = {ms(key.t_ms)}", *extra]


def strip_frame(fid: str, title: str, intro: list[str], strips: list[Strip], foot: list[Node], *,
                ncols: int = 4) -> tuple[Node, int]:
    w = PAD + LABEL_W + ncols * CROP_W + (ncols - 1) * GAP + PAD
    inner = w - 2 * PAD
    kids: list[Node] = [text("title", title, k.HEADING_SM, k.TEXT_1, x=PAD, y=PAD, w=inner)]
    y = PAD + round(k.est_height(kids[0])) + 8
    for i, ln in enumerate(intro):
        t = text(f"intro {i + 1}", ln, k.CAPTION, k.TEXT_2, x=PAD, y=y, w=inner)
        kids.append(t)
        y += round(k.est_height(t)) + 4
    y += 16
    for si, st in enumerate(strips, 1):
        lab = vbox(f"strip {si} label", [text("label", st.label, k.LABEL, k.TEXT_1, w=LABEL_W - 16)] +
                   [text(f"line {j}", ln, k.CAPTION, k.TEXT_2, w=LABEL_W - 16) for j, ln in enumerate(st.lines, 1)],
                   {"gap": k.STACK_XS}, w=LABEL_W - 16, x=PAD, y=y + (CAP_H if st.cells else 0))
        kids.append(lab)
        row_h = round(k.est_height(lab)) + (CAP_H if st.cells else 0)
        for ci, (cap, node) in enumerate(st.cells):
            x = PAD + LABEL_W + ci * (CROP_W + GAP)
            for li, ln in enumerate(cap):
                if k.text_w(ln, k.CAPTION) > CROP_W:
                    raise ValueError(f"{fid}: caption {ln!r} wider than a crop")
                kids.append(text(f"strip {si} cell {ci + 1} caption {li + 1}", ln, k.CAPTION,
                                 k.TEXT_1 if li == 0 else k.TEXT_2, x=x, y=y + li * 15))
            kids.append(dict(node, name=f"strip {si} cell {ci + 1} · {node['name']}", x=x, y=y + CAP_H))
            row_h = max(row_h, CAP_H + node["h"])
        y += row_h + GAP
    for fi, n in enumerate(foot, 1):
        kids.append(dict(n, x=PAD, y=y))
        y += round(k.est_height(n)) + GAP
    h = int(math.ceil((y + PAD - GAP) / 8) * 8)
    return frame(fid, kids, w, h), h


def case_line(row: str, *cols: str) -> str:
    """'M-n · <Duration · easing>' and other §2 cells for a row, plain (parsed, never typed)."""
    c = k.CASES[row]
    return " · ".join(k.plain(c[x]) for x in cols)


def matrix_line(row: str, col: str) -> str:
    return f"§3 {row} {k.plain(col)}: {k.plain(k.MATRIX[row][col])}"


def reduce_col() -> str:
    return k.MATRIX_HDR[1]


def frames_of(duration: str) -> str:
    return f"{ms(k.DUR[duration])} = {k.frames_at_60(k.DUR[duration])} frames at 60 Hz"


# --- shared words ----------------------------------------------------------------------------------------------------
def session() -> str:
    return say("Session", "d03")


def intro_for(row: str) -> list[str]:
    c = k.CASES[row]
    return [f"§2 L{k.CASE_LINE + list(k.CASES).index(row)} {row} · {k.plain(c['Case'])}: "
            f"{k.plain(c['Property'])}, {k.plain(c['From → to'])}, {k.plain(c['Duration · easing'])}",
            f"Trigger and cap: {k.plain(c['Trigger and cap'])}",
            f"Communicates: {k.plain(c['Communicates'])}",
            f"Carrier (MR-3): {k.plain(c['Carrier (MR-3)'])}"]


TRACE_READING = ("R-K3 (the trace lane): §5.1 puts the band 'in the rail's lane (4 px wide)' and says 'it never covers "
                 "a bar'; D03's rail is full-width, so the kit draws the 4 px lane at the bars' far end, the first "
                 "4 px of the price gutter (under the VAH ∕ VAL ticks), from the previous POC row to the new one")


# --- board 02: the POC jump (M-2) ------------------------------------------------------------------------------------
def f_poc_jump(fid: str) -> tuple[Node, list[str]]:
    j = k.JUMP
    win = (j.p0.poc - 11, j.p0.poc + 13)
    keys = k.keyframes("normal", "accelerate")
    st0, st1, st2 = (state_word(p, t) for p, t in ((j.p0, k.U0), (j.p1, k.U1), (j.p2, k.U2)))
    k.reading(TRACE_READING)
    k.derive(f"POC jump: U0 {hms(k.U0)} POC {price(j.p0.poc * 100)}; a print run of {j.burst1} qty steps at "
             f"{price((j.p0.poc + k.JUMP_ROWS) * 100)} lands by U1 {hms(k.U1)} (the {k.DEFAULT_THROTTLE_MS} ms "
             f"default), POC {price(j.p1.poc * 100)} ({j.p1.poc - j.p0.poc} rows); {j.burst2} more one row up by U2 "
             f"{hms(k.U2)}, POC {price(j.p2.poc * 100)} (1 row)")
    w1_01, w1_12 = w1(j.p0, j.p1), w1(j.p1, j.p2)

    def c(pr: k.Profile, st: str, extra: list[str], trace: tuple[int, int, float] | None = None) -> Crop:
        return Crop(pr, win, session(), st, extra, trace=trace)

    normal = [([f"before · U0 {hms(k.U0)} UTC", "no motion"], crop("CMP-183 crop", c(j.p0, st0, [])))]
    for key in keys:
        al = float(k.PEAK) * (1 - key.progress)
        normal.append((key_caption(key, f"trace opacity {k.fmt_alpha(al)}" + (" (outline)" if 0 < al < 1 else "")),
                       crop("CMP-183 crop", c(j.p1, st1, [w1_01], (j.p0.poc, j.p1.poc, al)))))
    one_row = [([f"before · U1 {hms(k.U1)} UTC", "the jump's end state"], crop("CMP-183 crop", c(j.p1, st1, [w1_01]))),
               ([f"frame 0 = the end · U2 {hms(k.U2)} UTC", "a cut: no band (1 row)"],
                crop("CMP-183 crop", c(j.p2, st2, [w1_12])))]
    reduce = [([f"before · U0 {hms(k.U0)} UTC", "no motion"], crop("CMP-183 crop", c(j.p0, st0, []))),
              (["frame 0 = the middle = the end", "a cut: the rail, the word, W-1"],
               crop("CMP-183 crop", c(j.p1, st1, [w1_01])))]
    ann = k.S("POC {price}, VAH {price}, VAL {price}, POC moved up 3 rows")
    spoken = f"{w33(j.p1)}, {w1b(j.p0, j.p1)}"
    k.derive(f'"{spoken}": §5.1\'s example "{ann}" ({k.SL(ann)}) with U1\'s values')
    foot = [hidden(f"U1 {hms(k.U1)} UTC, polite, both modes: \"{spoken}\" (D02 W-33 with W-1b appended, ≤ 1 per 2 s, "
                   f"latest wins; R-7). U2's 1-row move updates W-1 and is said no sooner than 2 s after it.", w=760),
            marker_box("timing", [f"{k.plain(k.CASES['M-2']['Duration · easing'])}: {frames_of('normal')}; "
                                  f"the middle at t = {ms(keys[1].t_ms)}: eased progress {keys[1].progress:.3f}, "
                                  f"opacity 0.25 × (1 − {keys[1].progress:.3f}) = "
                                  f"{k.fmt_alpha(float(k.PEAK) * (1 - keys[1].progress))}",
                                  f"R-1: {k.S('the POC rail and its word are at the new row (R-1)')}",
                                  f"§5.1: {k.S('Only the previous received POC is held (one value, never a path)')}",
                                  f"Reduce (§5.3): {k.S('the rail at its new row, D05 W-1 with its direction glyph and')} "
                                  f"row count, and D02 W-33 at ≤ 1 per 2 s"], w=760, title="M-2 · the numbers")]
    strips = [Strip(say("normal"), [f"M-2 runs: {j.p1.poc - j.p0.poc} rows ≥ 2", matrix_line("M-2", k.MATRIX_HDR[3])],
                    normal),
              Strip("1-row move", [k.S("a 1-row move is a cut"), "§5.1: ≥ 2 rows shows the band"], one_row),
              Strip(say("reduce"), [matrix_line("M-2", reduce_col())], reduce)]
    node, _h = strip_frame(fid, f"M-2 · {k.plain(k.CASES['M-2']['Case'])}", intro_for("M-2"), strips, foot)
    return node, [f"window rows {price(win[0] * 100)} – {price(win[1] * 100)} (24 × 12 px); POC {price(j.p0.poc * 100)}"
                  f" → {price(j.p1.poc * 100)} → {price(j.p2.poc * 100)}", TRACE_READING]


def text_strip(label: str, lines: list[str]) -> Strip:
    """A strip whose every column equals the row above's end state (a cut): stated, not redrawn."""
    return Strip(label, lines, [])


def reduce_same(row: str) -> Strip:
    return text_strip(say("reduce"), [matrix_line(row, reduce_col()), "every column is the normal strip's: a cut "
                                      "draws the same nodes in both modes (R-6)"])


# --- board 03: developing -> final (M-3, M-4) ------------------------------------------------------------------------
def f_developing_final(fid: str) -> tuple[Node, list[str]]:
    dev, fin = k.DEV_LAST, k.FINAL
    win = (fin.va[0] - 4, fin.va[0] + 20)
    keys = k.keyframes("normal", "accelerate")
    close = k.DAY_LIVE
    st_dev, st_fin = state_word(dev, k.DEV_AT), state_word(fin, close)
    k.derive(f"developing → final: the {k.CLOSE_DAY:%d %b} session; its last developing recompute as of "
             f"{hm(k.DEV_AT)} UTC (VA {price(dev.va[0] * 100)} – {price(dev.va[1] * 100)}), complete at "
             f"{close:%d %b %H:%M} UTC (VA {price(fin.va[0] * 100)} – {price(fin.va[1] * 100)}, POC "
             f"{price(fin.poc * 100)})")

    def c(pr: k.Profile, st: str, caps: str, em: float = 0.0) -> Crop:
        return Crop(pr, win, session(), st, [], emphasis=em, caps=caps)

    normal = [([f"before · as of {hm(k.DEV_AT)} UTC", "developing: the open edge"],
               crop("CMP-183 crop", c(dev, st_dev, "developing")))]
    for key in keys:
        al = float(k.PEAK) * (1 - key.progress)
        normal.append((key_caption(key, f"bracket emphasis {k.fmt_alpha(al)}" + (" (outline)" if 0 < al < 1 else "")),
                       crop("CMP-183 crop", c(fin, st_fin, "final", al))))
    reduce = [([f"before · as of {hm(k.DEV_AT)} UTC", "developing: the open edge"],
               crop("CMP-183 crop", c(dev, st_dev, "developing"))),
              (["frame 0 = the middle = the end", "a cut: D03 W-11 and the caps"],
               crop("CMP-183 crop", c(fin, st_fin, "final")))]
    foot = [hidden(f"{close:%d %b %H:%M:%S} UTC, polite, once, both modes: \"{k.W('D03 W-11')}\" (D02:250; R-7). "
                   f"{k.S('D03 W-11 \"Final\" spoken alone is flagged to E19-D06 for its context.')}", w=760),
            marker_box("timing", [f"{k.plain(k.CASES['M-4']['Duration · easing'])}: {frames_of('normal')}; "
                                  f"the middle at t = {ms(keys[1].t_ms)}: opacity 0.25 × (1 − {keys[1].progress:.3f}) "
                                  f"= {k.fmt_alpha(float(k.PEAK) * (1 - keys[1].progress))}",
                                  f"§5.2: {k.S('D03 W-10 becomes D03 W-11 and')} the bracket gains its end caps "
                                  f"(D03:267), in one frame; then the 8 px lane's emphasis, once",
                                  f"M-3 before it: {k.plain(k.CASES['M-3']['Duration · easing'])} per update; "
                                  f"{k.S('VAH / VAL can change on every `ProfileUpdate`')}",
                                  f"C-2: {k.plain(k.S('Neither `22`:20364 nor `23`:3136 carries `complete` yet'))}"],
                       w=760, title="M-4 · the numbers")]
    strips = [Strip(say("normal"), ["M-4 runs once per period close", matrix_line("M-4", k.MATRIX_HDR[3])], normal),
              Strip(say("reduce"), [matrix_line("M-4", reduce_col())], reduce)]
    node, _h = strip_frame(fid, f"M-4 · {k.plain(k.CASES['M-4']['Case'])}", intro_for("M-4"), strips, foot)
    return node, [f"window rows {price(win[0] * 100)} – {price(win[1] * 100)}; R-K4: the developing bracket's open "
                  "edge is the value-area edge on the last price's side (D03's kit reading R-K3)"]


# --- board 04: live growth (M-1) at the 120-row and 5 000-row arms ---------------------------------------------------
def _eased(g: k.Growth, p: float) -> k.Profile:
    """The drawn profile at eased progress p: changed rows between their old and new values; levels are U1's (R-1)."""
    lv = dict(g.p1.levels)
    for r in g.changed:
        lv[r] = round(k.lerp(g.p0.vol(r), g.p1.vol(r), p))
    return k.Profile(g.p1.label, g.row_ticks, lv, g.p1.vwap_ticks, g.p1.last_ticks, False, g.p1.poc, g.p1.va)


GROWTH_H = 360  # the growth arms' plot height (kit choice): 120 rows at 3 px; 5 000 rows merge


def f_growth_120(fid: str) -> tuple[Node, list[str]]:
    g = k.G120
    keys = k.keyframes("fast", "standard")
    st = state_word(g.p1, k.U1)
    maxv = g.p1.max_vol
    k.derive(f"growth arm: {g.rows} visible rows of {g.row_ticks} ticks around the last price; the prints of "
             f"U0 → U1 change {len(g.changed)} rows; the scale maximum {maxv} is unchanged")

    def c(pr: k.Profile, mark: bool = True) -> Crop:
        return Crop(pr, g.window, session(), st, [], plot_h=GROWTH_H, max_vol=maxv,
                    mark_rows=tuple(g.changed) if mark else ())

    normal = [([f"before · U0 {hms(k.U0)} UTC", "the bars at U0's values"], crop("CMP-183 crop", c(g.p0)))]
    for key in keys:
        normal.append((key_caption(key, f"{len(g.changed)} changed bars at progress {key.progress:.3f}"),
                       crop("CMP-183 crop", c(_eased(g, key.progress)))))
    reduce = [([f"before · U0 {hms(k.U0)} UTC", "the bars at U0's values"], crop("CMP-183 crop", c(g.p0))),
              (["frame 0 = the middle = the end", "a cut: the bars at U1's values"], crop("CMP-183 crop", c(g.p1)))]
    foot = [marker_box("timing", [f"{k.plain(k.CASES['M-1']['Duration · easing'])}: {frames_of('fast')}; the middle "
                                  f"at t = {ms(keys[1].t_ms)}: eased progress {keys[1].progress:.3f}",
                                  f"{g.rows} visible rows ≤ T_rows = {k.T_ROWS}: M-1 runs (§4.2); the board marker "
                                  f"brackets the {len(g.changed)} changed rows",
                                  f"R-2: {k.S('runs only while the topic')}'s effective.throttle_ms ≥ 500 ms: at the "
                                  f"{k.DEFAULT_THROTTLE_MS} ms default, {k.frames_at_60(k.DEFAULT_THROTTLE_MS)} frames "
                                  f"between updates, the entry ends in {k.frames_at_60(k.DUR['fast'])}"],
                       w=760, title="M-1 · the 120-row arm")]
    strips = [Strip(say("normal"), [f"M-1 runs: {g.rows} ≤ {k.T_ROWS}", "changed rows only; scale maximum unchanged"],
                    normal),
              Strip(say("reduce"), [matrix_line("M-1", reduce_col())], reduce)]
    node, _h = strip_frame(fid, f"M-1 · {k.plain(k.CASES['M-1']['Case'])} · {num(g.rows)} visible rows", intro_for("M-1"),
                           strips, foot)
    return node, [f"window {price(g.window[0] * g.row_ticks)} – {price(g.window[1] * g.row_ticks)}, {g.rows} rows of "
                  f"{GROWTH_H // g.rows} px; changed rows {', '.join(price(r * g.row_ticks) for r in g.changed)}"]


# --- tables (the spec's, parsed) -------------------------------------------------------------------------------------
def spec_table(name: str, hdr: list[str], rows: list[list[str]], widths: list[int], *,
               numeric: tuple[int, ...] = ()) -> Node:
    cols = [k.Col(f"c{i}", k.plain(h), w, i in numeric) for i, (h, w) in enumerate(zip(hdr, widths))]
    body = [k.table_row(cols, {f"c{i}": k.plain(v) for i, v in enumerate(r)}, f"row · {k.plain(r[0])}",
                        fill=k.RAISED if n % 2 else k.CANVAS) for n, r in enumerate(rows)]
    hd = k.header_row(cols)
    return vbox(name, [hd, *body], None, w=sum(widths), h=round(k.est_height(hd) + sum(k.est_height(b) for b in body)))


def f_growth_5000(fid: str) -> tuple[Node, list[str]]:
    g = k.G5000
    st = state_word(g.p1, k.U1)
    probe = Crop(g.p0, g.window, session(), st, [], plot_h=GROWTH_H)
    m = _merge(probe)
    merged = k.W("W-20", doc="d02", k=str(m)) if "W-20" in k.DECK["d02"] else k.W("W-12", doc="d03", k=str(m))
    k.reading("R-K5: D02 W-19 has no singular, so the 1-tick row size reads \"Row size: 1 ticks (0.1)\" as the "
              "template gives it (a copy question for E19-D06)")
    k.derive(f"5 000-row arm: {g.rows} rows of {g.row_ticks} tick in {GROWTH_H} px = {GROWTH_H / g.rows:.3f} px a row "
             f"< 2 px, so {m} levels merge per drawn row (`26`:238): {math.ceil(g.rows / m)} drawn rows")

    def c(pr: k.Profile) -> Crop:
        return Crop(pr, g.window, session(), st, [merged], plot_h=GROWTH_H)

    normal = [([f"before · U0 {hms(k.U0)} UTC", "the bars at U0's values"], crop("CMP-183 crop", c(g.p0))),
              ([f"frame 0 = the end · U1 {hms(k.U1)} UTC", "a cut: every bar at its value"],
               crop("CMP-183 crop", c(g.p1)))]
    t42 = spec_table("§4.2 table", k.THRESH_HDR, k.THRESH_ROWS, [360, 260, 260])
    t41 = spec_table("§4.1 table", k.CADENCE_HDR, k.CADENCE_ROWS, [200, 260, 140, 260])
    check = marker_box("arithmetic", [
        f"T_rows = ⌊{k.SHARE_MS} ms ÷ {k.COST_US} µs⌋ = {k.T_ROWS}; at T_rows {k.T_ROWS} × {k.BYTES_PER_INSTANCE} B = "
        f"{k.T_ROWS * k.BYTES_PER_INSTANCE} B a frame (re-derived; §4.2 L{k.THRESH_LINE})",
        f"{num(k.WORST_ROWS)} > {k.T_ROWS}: {k.plain(k.MATRIX['M-1'][k.MATRIX_HDR[3]])} (§3 (c))",
        f"{k.S('no row eases while any merge is active')} (`26`:238)"], w=900,
        title="§4.2 · the threshold")
    strips = [Strip(say("normal"), [f"{num(g.rows)} > T_rows {k.T_ROWS}", matrix_line("M-1", k.MATRIX_HDR[3])], normal),
              reduce_same("M-1")]
    node, _h = strip_frame(fid, f"M-1 · {k.plain(k.CASES['M-1']['Case'])} · {num(g.rows)} visible rows",
                           [f"PROPOSED planning arithmetic, measured by the PR 2 prototype: "
                            f"{k.S('a missed budget is \"inconclusive\" and the minimal form, a cut, ships')}"],
                           strips, [check, t42, t41], ncols=3)
    return node, [f"{g.rows} rows of {g.row_ticks} tick, {m} merged per drawn row; tables §4.2 L{k.THRESH_LINE} and "
                  f"§4.1 L{k.CADENCE_LINE} as parsed"]


# --- board 05: the developing value area (M-3) and HS-1 on a tied POC ------------------------------------------------
def f_developing_va(fid: str) -> tuple[Node, list[str]]:
    p0, p1 = k.VA0, k.VA1
    win = (p0.va[0] - 3, p0.va[0] + 21)
    k.derive(f"developing VA: as of {hm(k.VA_AT0)} VA {price(p0.va[0] * 100)} – {price(p0.va[1] * 100)}; the next "
             f"minute's prints one row under VAL move it to {price(p1.va[0] * 100)} – {price(p1.va[1] * 100)} as of "
             f"{hm(k.VA_AT1)} (POC unchanged at {price(p0.poc * 100)})")
    normal = [([f"before · as of {hm(k.VA_AT0)} UTC", "developing"],
               crop("CMP-183 crop", Crop(p0, win, session(), state_word(p0, k.VA_AT0), []))),
              ([f"frame 0 = the end · as of {hm(k.VA_AT1)} UTC", "a cut: VAH, VAL and the shading"],
               crop("CMP-183 crop", Crop(p1, win, session(), state_word(p1, k.VA_AT1), [])))]
    foot = [marker_box("cadence", [f"M-3: {k.plain(k.CASES['M-3']['Trigger and cap'])}",
                                   f"{k.plain(k.CASES['M-3']['Communicates'])}",
                                   f"R-1: {k.S('motion only follows the truth and never moves a level')}"],
                       w=760, title="M-3 · a cut per update")]
    strips = [Strip(say("normal"), [f"§2 Moves: {k.plain(k.CASES['M-3']['Moves'])}"], normal), reduce_same("M-3")]
    node, _h = strip_frame(fid, f"M-3 · {k.plain(k.CASES['M-3']['Case'])}", intro_for("M-3"), strips, foot, ncols=2)
    return node, [f"window rows {price(win[0] * 100)} – {price(win[1] * 100)}; VA "
                  f"{price(p0.va[0] * 100)}–{price(p0.va[1] * 100)} → {price(p1.va[0] * 100)}–{price(p1.va[1] * 100)}"]


def f_tie_cap(fid: str) -> tuple[Node, list[str]]:
    ev = k.TIE
    px_s = 96
    span = k.TIE_SECONDS
    w = PAD * 2 + 64 + span * px_s + 64
    a, b = k.TIE_ROWS
    starts = [e.t_ms for e in ev if e.band]
    worst = k.starts_in_any_second(starts)
    p0 = k.JUMP.p0
    k.derive(f"tied POC: {price(a * 100)} and {price(b * 100)} alternate on every update at the requested "
             f"{k.TIE_THROTTLE_MS} ms for {span} s; HS-1 gives {len(starts)} band starts, at most {worst} in any 1 s, "
             f"none from {k.HS1_QUIET_S} s on")
    pa = k.Profile("Session", 100, p0.levels, p0.vwap_ticks, p0.last_ticks, False, a, p0.va)
    pb = k.Profile("Session", 100, p0.levels, p0.vwap_ticks, p0.last_ticks, False, b, p0.va)
    up, dn = w1(pa, pb), w1(pb, pa)
    intro = [f"R-5 (§1.3 L{k.L('**R-5 HS-1 on every data-driven start**')}): "
             f"{k.S('≥ 500 ms between starts per element, the latest update wins')} and nothing queues; "
             f"{k.S('an element changing at ≥ 1 Hz for 10 s stops emphasising until quiet')}",
             f"§5.1: {k.S('A POC flipping between tied levels (`24`:1009) is HS-1')}'s case; W-1 still updates "
             f"on every move: \"{up}\" ∕ \"{dn}\"",
             f"§4.1 L{k.CADENCE_LINE + 1}: at {k.TIE_THROTTLE_MS} ms (a request) M-2 trace starts in any 1 s: "
             f"{k.plain(k.CADENCE_ROWS[1][3])}"]
    kids: list[Node] = [text("title", f"M-2 · HS-1 on a tied POC · {k.TIE_THROTTLE_MS} ms updates", k.HEADING_SM,
                             k.TEXT_1, x=PAD, y=PAD, w=w - 2 * PAD)]
    y = PAD + 28
    for i, ln in enumerate(intro):
        t = text(f"intro {i + 1}", ln, k.CAPTION, k.TEXT_2, x=PAD, y=y, w=w - 2 * PAD)
        kids.append(t)
        y += round(k.est_height(t)) + 4
    y += 12
    ch = 168
    x0 = 64
    ax = 112
    tl: list[Node | None] = [rect("axis", span * px_s, 1, k.TEXT_3, x=x0, y=ax)]
    for s_ in range(span + 1):
        tl.append(rect(f"second tick {s_}", 1, 6, k.TEXT_3, x=x0 + s_ * px_s, y=ax + 1))
        tl.append(text(f"second label {s_}", f"{s_} s", k.NUM_XS, k.TEXT_2, x=x0 + s_ * px_s - 6, y=ax + 10))
    for e in ev:
        x = x0 + round(e.t_ms * px_s / 1000)
        if e.band:
            tl.append(rect(f"band start {e.t_ms}", 4, 32, k.P_POC, x=x - 2, y=ax - 34))
        else:
            tl.append(rect(f"cut {e.t_ms}", 1, 12, k.TEXT_3, x=x, y=ax - 12))
    qx = x0 + k.HS1_QUIET_S * px_s
    tl.append(rect("board marker · quiet rule", (span - k.HS1_QUIET_S) * px_s, 64, None,
                   {"stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, x=qx, y=ax - 52))
    tl.append(text("quiet rule words", f"≥ 1 Hz for {k.HS1_QUIET_S} s: no band until quiet", k.CAPTION, k.TEXT_2,
                   x=qx + 6, y=ax - 50))
    tl.append(text("lane words", f"POC {price(a * 100)} ⇄ {price(b * 100)} (2 rows)", k.CAPTION, k.TEXT_2,
                   x=x0, y=8))
    k.fallback("marker")
    kids.append(box("timeline", tl, {"fill": k.CANVAS, "clip": True}, w=w - 2 * PAD, h=ch, x=PAD, y=y))
    y += ch + 16
    key = marker_box("key", [f"amber bar: a trace band starts ({len(starts)} starts; at most {worst} in any half-open "
                             f"1 000 ms window, MR-1 allows {k.MR1})",
                             f"grey tick: an update whose band is a cut (< {k.HS1_GAP_MS} ms since the last start, "
                             f"or the quiet rule); the rail, W-1 and the words still update",
                             "the tape goes quiet after 12 s (synthetic); the next ≥ 2-row move after quiet starts a "
                             "band again"], w=900, title="reading the timeline")
    kids.append(dict(key, x=PAD, y=y))
    y += round(k.est_height(key)) + PAD
    h = int(math.ceil(y / 8) * 8)
    return frame(fid, kids, w, h), [f"{len(ev)} updates every {k.TIE_THROTTLE_MS} ms over {span} s; starts at "
                                    f"{', '.join(str(t) for t in starts[:4])} … ms"]


# --- board 06: re-bucket, period change (M-5, M-6) and the feed-break contrast ---------------------------------------
def _rb_window(pr: k.Profile) -> tuple[int, int]:
    lo = (k.P100.poc - 11) * k.ROW_TICKS // pr.row_ticks
    return lo, lo + 24 * k.ROW_TICKS // pr.row_ticks


def _recompute_frame(fid: str, row: str, before: k.Profile, after: k.Profile, period_from: str, period_to: str,
                     what: str, said: str) -> tuple[Node, list[str]]:
    st = state_word(before, k.U0)
    k.derive(f"{what}: the action at t = 0 ({hms(k.U0)} UTC); the busy bar at t = {ms(k.BUSY_DELAY_MS)} (still "
             f"pending); the result lands at t = {ms(k.RESULT_MS)} (synthetic, > {ms(k.BUSY_DELAY_MS)})")
    cells = [(["action · t = 0", "last frame held, un-dimmed; aria-busy"],
              crop("CMP-183 crop", Crop(before, _rb_window(before), period_from, st, []))),
             ([f"pending · t = {ms(k.BUSY_DELAY_MS)}", "the 2 px busy bar, a cut, static"],
              crop("CMP-183 crop", Crop(before, _rb_window(before), period_from, st, [], busy=True))),
             ([f"the result · t = {ms(k.RESULT_MS)}", "a cut; words swapped; the end is silent"],
              crop("CMP-183 crop", Crop(after, _rb_window(after), period_to, st, [])))]
    foot = [hidden(f"polite, one region (R-7): the action's D02 word once at t = 0 (\"{said}\"); "
                   f"{k.S('the end of loading is silent')}, `aria-busy` alone (D02:246), and no new word is added "
                   f"(BQ-7's ruling; board 10)".replace("`", ""), w=900),
            marker_box("rules", [f"§6.1: {k.S('the panel keeps the last frame un-dimmed and sets')} aria-busy; "
                                 f"{k.S('appears under the header as a cut (D03:314). It is static and never sweeps')}",
                                 f"§6.1: {k.S('Focus stays on the control that started it')}; nothing moves it (R-7)",
                                 f"§1.4 T2: D03's {k.S('SCR-039 `Save` under view-as').replace('`', '')} is T2 "
                                 f"(2a inline, D03's statement); {k.S('No board of §0 draws it.')}",
                                 f"R-9: {k.S('the busy bar is drawn as a 2 px `Highlight` border-bottom of the header').replace('`', '')} "
                                 f"under forced colours"], w=900, title=f"{row} · the rules")]
    strips = [Strip(say("normal"), [f"§2 Moves: {k.plain(k.CASES[row]['Moves'])}",
                                    k.plain(k.CASES[row]['Trigger and cap'])], cells), reduce_same(row)]
    node, _h = strip_frame(fid, f"{row} · {k.plain(k.CASES[row]['Case'])}", intro_for(row), strips, foot, ncols=3)
    return node, [f"{what}; windows the same 240 USDT of price at both row sizes"]


def f_rebucket(fid: str) -> tuple[Node, list[str]]:
    return _recompute_frame(fid, "M-5", k.P100, k.P50, session(), session(),
                            f"re-bucket: row size {k.ROW_TICKS} → {k.ROW_TICKS_NEW} ticks from SCR-039",
                            k.W("W-38", doc="d02"))


def f_period_change(fid: str) -> tuple[Node, list[str]]:
    k.derive(f"period change: {k.FIXED.label} = the last {k.FIXED_MIN} minutes of bars before {hms(k.U0)} UTC "
             "(D03's kit choice for a fixed range)")
    return _recompute_frame(fid, "M-6", k.P100, k.FIXED, session(), say("Fixed range", "d03"),
                            f"period change: Session → Fixed range ({k.FIXED_MIN} minutes)",
                            k.tpl("Period: {mode}", {"{mode}": "Fixed range"}))


def f_feed_break(fid: str) -> tuple[Node, list[str]]:
    st = state_word(k.P100, k.U0)
    w18 = k.W("W-18", doc="d02", **{"HH:MM:SS": hms(k.U0)})
    cells = [([f"re-bucket pending · t = {ms(k.BUSY_DELAY_MS)}", "this spec: un-dimmed, the busy bar"],
              crop("CMP-183 crop", Crop(k.P100, _rb_window(k.P100), session(), st, [], busy=True))),
             (["feed break · E17's state", "never this spec's: the stale shade and words"],
              crop("CMP-183 crop", Crop(k.P100, _rb_window(k.P100), session(), st, [w18], shade=True)))]
    foot = [marker_box("contrast", [f"§6.1: {k.S('It never shows the stale shade, D02 W-18 or E17')}'s words, which "
                                    f"mean the feed broke; board 06 draws the two side by side",
                                    f"H-2: {k.S('never as E17')}'s broken-feed treatment",
                                    "CMP-078's stale shade: color.data-confidence.stale.surface at opacity.scrim "
                                    "(E17's, drawn here only as the contrast case)"], w=600, title="the contrast case")]
    strips = [Strip("side by side", ["re-bucket vs a feed break"], cells)]
    node, _h = strip_frame(fid, "M-5 ∕ M-6 · a recompute is not a feed break", [], strips, foot, ncols=2)
    return node, ["the contrast case (§6.1): re-bucket pending vs E17's stale treatment"]


# --- board 07: visible range, pan and settle (M-7) -------------------------------------------------------------------
def _vr_window() -> tuple[int, int]:
    """24 rows from two rows under the lowest VAL of the pan's recomputes (every VAH fits; the self-test checks)."""
    lo = min(p.va[0] for p in [*k.PAN.values(), k.SETTLED]) - 2
    return lo, lo + 24


def f_vr_pan(fid: str) -> tuple[Node, list[str]]:
    vr = say("Visible range", "d03")
    st = state_word(k.PAN[0], k.U0)
    cells = []
    for i, t in enumerate(k.PAN_STEPS):
        pr = k.PAN[t]
        cells.append(([f"t = {ms(t)} · recompute {i + 1}", f"a cut; {k.VIS_N} bars, {i} back"],
                      crop("CMP-183 crop", Crop(pr, _vr_window(), vr, st, []))))
    k.derive(f"pan: {k.VIS_N} bars visible, one bar further back per pointer step; recomputes at "
             f"{', '.join(ms(t) for t in k.PAN_STEPS)} (≤ {k.PAN_HZ} Hz); POC "
             f"{' → '.join(price(k.PAN[t].poc * 100) for t in k.PAN_STEPS)}")
    foot = [marker_box("rules", [f"§6.2: {k.S('each result is a cut, nothing eases during the gesture or at the settle')}",
                                 f"§6.2: {k.S('only the plot and the legend re-render')} (D02:319)",
                                 f"M-7: {k.plain(k.CASES['M-7']['Communicates'])}",
                                 "visible-range recomputes and growth are never announced (§8.2)"],
                       w=900, title="M-7 · during the gesture")]
    strips = [Strip(say("normal"), [f"≤ {k.PAN_HZ} Hz during the gesture", f"§2 Moves: {k.plain(k.CASES['M-7']['Moves'])}"],
                    cells), reduce_same("M-7")]
    node, _h = strip_frame(fid, f"M-7 · {k.plain(k.CASES['M-7']['Case'])} · the pan", intro_for("M-7"), strips, foot)
    return node, ["a time pan leaves the price scale unchanged, so the rows stay put (kit construction)"]


def f_vr_settle(fid: str) -> tuple[Node, list[str]]:
    vr = say("Visible range", "d03")
    st = state_word(k.PAN[0], k.U0)
    last = k.PAN[k.PAN_STEPS[-1]]
    t_set = k.PAN_END_MS + k.DEBOUNCE_MS
    cells = [([f"pointer up · t = {ms(k.PAN_END_MS)}", f"the {ms(k.PAN_STEPS[-1])} result still shown"],
              crop("CMP-183 crop", Crop(last, _vr_window(), vr, st, []))),
             ([f"debounce · t = {ms(k.PAN_END_MS + k.DEBOUNCE_MS // 2)}", "unchanged: nothing eases"],
              crop("CMP-183 crop", Crop(last, _vr_window(), vr, st, []))),
             ([f"the settle · t = {ms(t_set)}", "a cut to the final range"],
              crop("CMP-183 crop", Crop(k.SETTLED, _vr_window(), vr, st, [])))]
    k.derive(f"settle: pointer released at {ms(k.PAN_END_MS)}, one bar past the last throttled recompute; the "
             f"debounce ({ms(k.DEBOUNCE_MS)}, C-4) recomputes at {ms(t_set)}: POC {price(k.SETTLED.poc * 100)}, VA "
             f"{price(k.SETTLED.va[0] * 100)} – {price(k.SETTLED.va[1] * 100)}")
    foot = [marker_box("rules", [f"C-4: {k.plain(k.S('`14`:1013 debounce 100 ms vs `11`:1730 ≤ 10 Hz with a debounce on pan end'))}"
                                 f" — {k.S('D02-C6 as taken (D02:403)')}",
                                 f"§6.2: {k.S('story floor of ≥ 55 fps for interaction (`11`:1724) holds; it is a floor, not a pass line').replace('`', '')}"],
                       w=900, title="M-7 · the settle")]
    strips = [Strip(say("normal"), ["no ease at the settle"], cells), reduce_same("M-7")]
    node, _h = strip_frame(fid, f"M-7 · {k.plain(k.CASES['M-7']['Case'])} · the settle", [], strips, foot, ncols=3)
    return node, [f"debounce {ms(k.DEBOUNCE_MS)} from C-4's reading of `14`:1013"]


# --- board 08: naked-POC demotion (M-8), the tested cut, overlay show (M-9) and dock ---------------------------------
def _npoc_window() -> tuple[int, int]:
    lo = k.RETEST.row - 2
    return lo, lo + 24


def _rays(nearest: list[k.NakedPoc], alpha: float = 1.0, tested: bool = False) -> list[Ray]:
    out = []
    for n in nearest:
        lab = k.W("W-4", doc="d03", date=f"{n.day.day} {n.day:%b}")
        if n == k.RETEST:
            out.append(Ray(n.row, f"{lab} {k.W('D03 W-5')}" if tested else lab, alpha, tested))
        else:
            out.append(Ray(n.row, lab))
    return out


def f_npoc_fade(fid: str) -> tuple[Node, list[str]]:
    win = _npoc_window()
    keys = k.keyframes("normal", "accelerate")
    st0, st1 = state_word(k.JUMP.p0, k.U0), state_word(k.AT_CLOSE, k.BAR_CLOSE)
    hid0, hid1 = k.W("D03 W-2", k=str(k.HIDDEN_BEFORE)), k.W("D03 W-2", k=str(k.HIDDEN_AFTER))
    show = k.W("W-6", doc="d03")
    k.derive(f"naked POCs: {len(k.NAKED)} of the 20 earlier sessions are untested at U0; the nearest {k.NPOC_N} are "
             f"drawn, {k.HIDDEN_BEFORE} hidden; at the {hm(k.BAR_CLOSE)} UTC bar close the live bar's run down "
             f"retests {k.RETEST.day:%d %b}'s ({price(k.RETEST.row * 100)}); "
             f"{[n for n in k.NEAREST_AFTER if n not in k.NEAREST_BEFORE][0].day:%d %b}'s enters the nearest "
             f"{k.NPOC_N} (a cut, §7.2) and the count reads {k.HIDDEN_AFTER}")

    def c(pr: k.Profile, st: str, extra: list[str], rays: list[Ray]) -> Crop:
        return Crop(pr, win, session(), st, extra, rays=rays)

    normal = [([f"before · U0 {hms(k.U0)} UTC", "history off; the ray untested"],
               crop("CMP-183 crop", c(k.JUMP.p0, st0, [f"{hid0} · {show}"], _rays(k.NEAREST_BEFORE))))]
    for key in keys:
        al = 1 - key.progress
        normal.append((key_caption(key, f"ray opacity {k.fmt_alpha(al)}" + (" (outline)" if 0 < al < 1 else "")),
                       crop("CMP-183 crop", c(k.AT_CLOSE, st1, [f"{hid1} · {show}"], _rays(k.NEAREST_BEFORE, al)))))
    reduce = [([f"before · U0 {hms(k.U0)} UTC", "history off; the ray untested"],
               crop("CMP-183 crop", c(k.JUMP.p0, st0, [f"{hid0} · {show}"], _rays(k.NEAREST_BEFORE)))),
              (["frame 0 = the middle = the end", "a cut: the ray gone, the count"],
               crop("CMP-183 crop", c(k.AT_CLOSE, st1, [f"{hid1} · {show}"], _rays(k.NEAREST_BEFORE, 0.0))))]
    foot = [marker_box("rules", [f"§7.1: {k.S('history off (D03:235), the ray fades 1 → 0 over')} "
                                 f"{k.plain(k.CASES['M-8']['Duration · easing'])} and the count swaps in the same frame",
                                 f"§7.1: {k.S('More than 3 retests in one 1 000 ms window: the fourth and later cut.')}",
                                 f"§7.2: {k.S('A count change is a text swap; a ray entering the nearest N is a cut.')}",
                                 f"{frames_of('normal')}; the middle: opacity 1 − {keys[1].progress:.3f} = "
                                 f"{k.fmt_alpha(1 - keys[1].progress)}"], w=900, title="M-8 · history off")]
    strips = [Strip(say("normal"), ["history off", matrix_line("M-8", k.MATRIX_HDR[3])], normal),
              Strip(say("reduce"), [matrix_line("M-8", reduce_col())], reduce)]
    node, _h = strip_frame(fid, f"M-8 · {k.plain(k.CASES['M-8']['Case'])}", intro_for("M-8"), strips, foot)
    return node, [f"window rows {price(win[0] * 100)} – {price(win[1] * 100)}; nearest naked POCs "
                  f"{', '.join(f'{n.day:%d %b}' for n in k.NEAREST_BEFORE)}"]


def f_npoc_tested(fid: str) -> tuple[Node, list[str]]:
    win = _npoc_window()
    st0, st1 = state_word(k.JUMP.p0, k.U0), state_word(k.AT_CLOSE, k.BAR_CLOSE)
    hid0, hid1 = k.W("D03 W-2", k=str(k.HIDDEN_BEFORE)), k.W("D03 W-2", k=str(k.HIDDEN_AFTER))
    show = k.W("W-6", doc="d03")
    cells = [([f"before · U0 {hms(k.U0)} UTC", f"history on (\"{show}\" pressed)"],
              crop("CMP-183 crop", Crop(k.JUMP.p0, win, session(), st0, [f"{hid0} · {show} (pressed)"],
                                        rays=_rays(k.NEAREST_BEFORE)))),
             ([f"frame 0 = the end · {hms(k.BAR_CLOSE)} UTC", "a cut: the tested dash and D03 W-5"],
              crop("CMP-183 crop", Crop(k.AT_CLOSE, win, session(), st1, [f"{hid1} · {show} (pressed)"],
                                        rays=_rays(k.NEAREST_BEFORE, tested=True))))]
    k.reading("R-K7: '(pressed)' after D03 W-6 marks the toggle's aria-pressed state on the board (D03 draws a "
              "leading CMP-019 check glyph; the crop's legend is words only)")
    foot = [marker_box("rules", [f"M-8: {k.S('history on: a cut to D03 W-5')}",
                                 f"§3 M-8 (a) reduce: {k.plain(k.MATRIX['M-8'][reduce_col()])}"],
                       w=600, title="M-8 · history on")]
    strips = [Strip(say("normal"), ["history on: a cut"], cells), reduce_same("M-8")]
    node, _h = strip_frame(fid, "M-8 · the tested cut (history on)", [], strips, foot, ncols=2)
    return node, ["the tested dash: 4 px dashes, 3 px gaps, color.text.tertiary (D03's kit stand-in for "
                  "pattern.dashed.tested)"]


OV_LEG = 40


def overlay_crop(name: str, alpha: float) -> Node:
    """The SCR-030 price pane's right part with the overlay CMP-183 at one key frame: candles, the pane's price gutter,
    the overlay legend row (DOM, mounted in frame 0), the bars at the pane's right edge, 30 % of the pane wide."""
    k.fallback("crop")
    pr = k.PAN[0]
    lo, hi = _vr_window()
    rowpx = PLOT_H / (hi - lo)
    pane = CROP_W - GUTTER
    run = round(pane * 30 / 100)
    bars = k.bars_between(k.DAY_LIVE, k.DAY_LIVE + timedelta(days=1))[-k.VIS_N:]
    slot = pane / len(bars)

    def y_px(ticks: int) -> float:
        return OV_LEG + (hi * pr.row_ticks - ticks) / pr.row_ticks * rowpx

    leg = k.S("Profile · Visible range ▾ · Volume ▾ · Histogram │ Table · ⚙")
    kids: list[Node | None] = [rect("plot", CROP_W, PLOT_H, k.CANVAS, x=0, y=OV_LEG),
                               rect("legend strip", CROP_W, OV_LEG, k.RAISED, x=0, y=0),
                               text("CMP-199 legend row", leg, k.CAPTION, k.TEXT_1, x=INSET, y=4, w=CROP_W - 2 * INSET)]
    for i, b in enumerate(bars):
        x = round(i * slot + slot / 2)
        # every candle mark is clamped to y >= OV_LEG: a wick or body above the plot never crosses the legend
        w_top, w_bot = max(OV_LEG, y_px(b.h)), max(OV_LEG, y_px(b.l))
        if y_px(b.l) >= OV_LEG:
            kids.append(rect(f"wick {i}", 1, max(1, round(w_bot - w_top)), WICK, x=x, y=round(w_top)))
        top, bot = max(OV_LEG, y_px(max(b.o, b.c))), max(OV_LEG, y_px(min(b.o, b.c)))
        if y_px(min(b.o, b.c)) >= OV_LEG:
            kids.append(rect(f"body {i}", 5, max(1, round(bot - top)), CANDLE_UP if b.c >= b.o else CANDLE_DOWN,
                             x=x - 2, y=round(top)))
    maxv = max(pr.vol(r) for r in range(lo, hi))
    for r in range(lo, hi):
        v = pr.vol(r)
        if not v:
            continue
        ln = max(1, round(v / maxv * run))
        y = OV_LEG + (hi - r - 1) * rowpx
        ink = k.P_VA if pr.va[0] <= r <= pr.va[1] else k.P_BAR
        kids.append(alpha_rect(f"overlay bar {r}", ln, round(rowpx) - 1, ink, alpha, pane - ln, round(y)))
    if lo <= pr.poc < hi:
        y = OV_LEG + (hi - pr.poc - 1) * rowpx
        kids.append(alpha_rect("overlay POC rail top", run, 1, k.P_POC, alpha, pane - run, round(y)))
        kids.append(alpha_rect("overlay POC rail bottom", run, 1, k.P_POC, alpha, pane - run, round(y + rowpx) - 1))
    for j, r in enumerate(range(lo, hi, 6)):
        kids.append(text(f"tick label {j}", price(r * pr.row_ticks), k.NUM_XS, k.TEXT_2, x=pane + 4,
                         y=round(OV_LEG + (hi - r) * rowpx - 12)))
    return box(name, kids, {"fill": k.CANVAS, "clip": True}, w=CROP_W, h=OV_LEG + PLOT_H)


def f_overlay_show(fid: str) -> tuple[Node, list[str]]:
    keys = k.keyframes("fast", "standard")
    k.reading("R-K6: the overlay's DOM legend row mounts in frame 0 as a cut; only the canvas opacity uniform eases "
              "(§7.4 names one uniform)")
    normal = [(key_caption(key, f"overlay opacity {k.fmt_alpha(key.progress)}" +
                           (" (outline)" if 0 < key.progress < 1 else "")), overlay_crop("SCR-030 pane crop", key.progress))
              for key in keys]
    hide = [(["shown", "the overlay at 1"], overlay_crop("SCR-030 pane crop", 1.0)),
            (["hide · frame 0 = the end", "a cut"], overlay_crop("SCR-030 pane crop", 0.0))]
    reduce = [(["frame 0 = the middle = the end", "a cut: the overlay itself"], overlay_crop("SCR-030 pane crop", 1.0))]
    dock_rows = [r for r in k.LINES["spec"][k.L("### 7.3 Dock and undock"):k.L("### 7.4 Overlay and auto-fit")] if r]
    dock = " ".join(dock_rows)
    i_ids = re.findall(r"I-\d+", k.BOARDS[8].cell)
    parts = [k.S("the drop commit is a cut (E15-D14:71)"), k.S("a panel add fades per its row (E15-D14:79)"),
             k.S("pop out and return are cuts (E15-D14:87)")]
    if not all(p in dock for p in parts) or len(i_ids) != 3:
        raise ValueError("§7.3 / §0 board 08: the dock rows moved")
    foot = [marker_box("dock", [f"E15-D14 {i}: {p}" for i, p in zip(i_ids, parts)] +
                       [k.S("Nothing profile-specific is added.")], w=900, title="§7.3 · dock and undock (E15-D14's rows)"),
            marker_box("rules", [f"§7.4: {k.S('a show within 500 ms of the last is a cut')} (R-5's HS-1 gap)",
                                 f"§7.4: {k.S('focus stays on that control, the overlay')}'s show never moves it; a toggle "
                                 f"exposes its state as aria-pressed",
                                 f"{frames_of('fast')}; the middle at t = {ms(keys[1].t_ms)}: eased progress "
                                 f"{keys[1].progress:.3f}"], w=900, title="M-9 · overlay show")]
    strips = [Strip(say("normal"), ["show, after a user action", matrix_line("M-9", k.MATRIX_HDR[3])], normal),
              Strip("hide", [k.S("hides as a cut")], hide),
              Strip(say("reduce"), [matrix_line("M-9", reduce_col())], reduce)]
    node, _h = strip_frame(fid, f"M-9 · {k.plain(k.CASES['M-9']['Case'])}", intro_for("M-9"), strips, foot, ncols=3)
    return node, ["the overlay: the visible-range profile of the pane's last 24 bars; E15-D14 I-4, I-12, I-20 in "
                  "§7.3's order (kit mapping)"]


# --- board 01: §2's ten rows as a sheet ------------------------------------------------------------------------------
def _dur_cell(cell: str) -> str:
    m = re.search(r"motion\.duration\.([a-z]+)", cell)
    if not m:
        raise ValueError(f"§2: no duration token in {cell!r}")
    d = k.DUR[m.group(1)]
    return "0 ms · a cut" if d == 0 else f"{ms(d)} · {k.frames_at_60(d)} frames"


# live-check fold: frames whose drawn height is kept although a folded fix grew their content (board 09: the §3
# header row 24 -> 40 moved the load marker 403 -> 419 inside the drawn 512 px frame; the bottom inset is 8 px there)
LIVE_FRAME_H = {"SCR-038/suppression-matrix-dark": 512, "SCR-038/suppression-matrix-light": 512}


def table_frame(fid: str, title: str, intro: list[str], tables: list[Node], foot: list[Node]) -> tuple[Node, list[str]]:
    w = PAD * 2 + max(t["w"] for t in tables)
    kids: list[Node] = [text("title", title, k.HEADING_SM, k.TEXT_1, x=PAD, y=PAD, w=w - 2 * PAD)]
    y = PAD + 28
    for i, ln in enumerate(intro):
        t = text(f"intro {i + 1}", ln, k.CAPTION, k.TEXT_2, x=PAD, y=y, w=w - 2 * PAD)
        kids.append(t)
        y += round(k.est_height(t)) + 4
    y += 12
    for n in [*tables, *foot]:
        kids.append(dict(n, x=PAD, y=y))
        y += round(k.est_height(n)) + GAP
    h = int(math.ceil((y + PAD - GAP) / 8) * 8)
    if fid in LIVE_FRAME_H:
        if LIVE_FRAME_H[fid] < y - GAP + 8:
            raise ValueError(f"{fid}: the drawn h {LIVE_FRAME_H[fid]} no longer holds the content ({y - GAP} px)")
        h = LIVE_FRAME_H[fid]
    return frame(fid, kids, w, h), []


def f_cases(fid: str) -> tuple[Node, list[str]]:
    hdr = list(k.CASE_HDR)
    di = hdr.index("Duration · easing")
    hdr2 = hdr[:di + 1] + ["at 60 Hz"] + hdr[di + 1:]
    rows = [r[:di + 1] + [_dur_cell(r[di])] + r[di + 1:] for r in k.CASE_ROWS]
    widths = [64, 170, 150, 110, 180, 170, 220, 120, 300, 300, 200, 96]
    k.copy_gap('"at 60 Hz": the kit\'s derived column (PRIM\'s duration × 60 Hz, as §4.1 counts frames)')
    tab = spec_table("§2 table", hdr2, rows, widths)
    moving = [r for r, c in k.CASES.items() if k.plain(c["Moves"]).startswith("yes")]
    cuts = [r for r in k.CASES if r not in moving]
    intro = [f"§2 L{k.L('## 2. The motion table (AC 1)')}: {k.S('A cut changes in one frame and reads')} "
             f"motion.duration.instant · —; \"Communicates\" opens \"carries:\" for a moving row and \"static is not "
             f"worse:\" for a cut",
             f"R-3: {k.S('histogram ink takes `motion.duration.instant`').replace('`', '')}, fast or normal, never "
             f"slow; {k.S('No token is added (T OOS).')}",
             f"R-4: {k.S('One per-instance attribute or one uniform each, +0 draw calls')}"]
    foot = [marker_box("count", [f"moving: {', '.join(moving)} ({len(moving)}); cuts: {', '.join(cuts)} ({len(cuts)})",
                                 f"H-4: {k.S('five of ten rows are cuts; the moving rows animate one property, once.')}",
                                 f"every row's suppression: §3, drawn on board 09"], w=900, title="the ten rows")]
    node, _ = table_frame(fid, "SCR-038 · the profile motion cases (§2)", intro, [tab], foot)
    return node, [f"§2 L{k.CASE_LINE}–L{k.CASE_LINE + 9}, parsed; the 'at 60 Hz' column derived from PRIM"]


# --- board 09: §3's suppression matrix -------------------------------------------------------------------------------
def f_matrix(fid: str) -> tuple[Node, list[str]]:
    tab = spec_table("§3 table", k.MATRIX_HDR, k.MATRIX_ROWS, [64, 250, 240, 210, 230, 250, 210])
    intro = [f"AC 6 (§3 L{k.L('## 3. The suppression matrix')}): {k.S('Replay above 1× or a seek: all profile motion is off')}"
             f" — {k.S('every row, every mode, stated here once and drawn on board 09')}",
             f"(b) Delayed: {k.S('Delayed is E17')}'s state, not a new motion: saturated or overflowing with the "
             f"profile topic in degraded_topics, carried by E17's corner tag D02 W-16 \"{k.W('D02 W-16')}\"",
             f"(c): visible rows > T_rows = {k.T_ROWS} (§4.2)"]
    foot = [marker_box("load", [k.S("What replaces per-row animation under load (AC 3): column (c) and column (b) turn "
                                    "M-1 into a cut, so the bar is drawn at its value in the update's frame and nothing "
                                    "else moves per row; under (b) the only addition is E17's tag."),
                                k.S("A hidden window runs no entry; on return the latest state is drawn as a cut and no "
                                    "backlog of entries plays."),
                                k.S("WCAG 2.2.2: no entry lasts more than 5 s (the longest is `motion.duration.normal`);"
                                    ).replace("`", "") + f" {ms(k.DUR['normal'])}"], w=tab["w"],
                       title="every suppressed motion names its static carrier (MR-3)")]
    node, _ = table_frame(fid, "SCR-038 · the suppression matrix (§3)", intro, [tab], foot)
    return node, [f"§3 L{k.MATRIX_LINE}–L{k.MATRIX_LINE + 9}, parsed"]


# --- board 10: the flash audit and the announcement timeline (§8) ----------------------------------------------------
FLASH_TOKEN = {"M-2 trace": (k.P_POC, 0.25), "M-4 bracket": (k.P_VA, 0.25), "M-8 ray fade": (k.P_POC, 1.0),
               "Combined M-2 + M-4 + M-8": (k.P_POC, 1.0)}


def f_flash(fid: str) -> tuple[Node, list[str]]:
    tab = spec_table("§8.1 table", k.FLASH_HDR, k.FLASH_ROWS, [200, 260, 90, 90, 130, 130, 160, 80])
    re_rows = []
    for r in k.FLASH_ROWS:
        tok, al = FLASH_TOKEN[k.plain(r[0])]
        got = [f"{k.flash_step(t, tok, al):.3f}" for t in ("dark", "light", "high-contrast")]
        re_rows.append([r[0], *got, "equal" if got == [k.plain(x) for x in r[2:5]] else "DIFFERS"])
    if any(x[-1] != "equal" for x in re_rows):
        raise ValueError(f"§8.1: the kit's luminance steps differ from the spec's: {re_rows}")
    k.copy_gap('"re-derived" / "equal": the kit\'s check column (token-sync.json + contrast_check.relative_luminance)')
    tab2 = spec_table("re-derived table", ["Entry", "ΔL dark", "ΔL light", "ΔL high-contrast", "re-derived"], re_rows,
                      [200, 110, 110, 150, 110])
    # the combined cap's worst three starts in one 341 × 256 region: the bracket's 8 px lane and two 4 px trace lanes
    reg: list[Node | None] = [rect("region", k.REGION_W, k.REGION_H, k.CANVAS, x=0, y=0)]
    lanes = [("bracket lane", k.LANE_BRACKET, k.P_VA, 24), ("trace lane 1", k.LANE_TRACE, k.P_POC, 160),
             ("trace lane 2", k.LANE_TRACE, k.P_POC, 296)]
    for nm, lw, ink, x in lanes:
        reg.append(alpha_rect(nm, lw, k.REGION_H, ink, float(k.PEAK), x, 0))
    area = sum(lw * k.REGION_H for _n, lw, _i, _x in lanes)
    k.derive(f"combined area: {' + '.join(f'{lw} × {k.REGION_H}' for _n, lw, _i, _x in lanes)} = {area} px² ≤ "
             f"{k.AREA_CAP} px² (HS-1b)")
    k.fallback("marker")
    region = box("board marker · region", reg, {"clip": True, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                                                "strokeAlign": "inner"}, w=k.REGION_W, h=k.REGION_H)
    cap = text("region words", f"one {k.REGION_W} × {k.REGION_H} px region: the bracket's {k.LANE_BRACKET} px lane and "
               f"two {k.LANE_TRACE} px trace lanes at the 0.25 peak = {num(area)} px² of {num(k.AREA_CAP)} (R-5's "
               f"combined cap: {k.COMBINED_CAP} starts)", k.CAPTION, k.TEXT_2, w=900)
    intro = [f"§8.1 L{k.L('### 8.1 Flash audit')}: {k.S('high contrast takes dark')}'s profile inks; starts = "
             f"{k.S('the worst half-open 1 000 ms window (MR-1: ≤ 3)')}",
             k.S("The light steps exceed 0.1, so each start counts as a flash there; the caps hold them at or under "
                 "MR-1's 3 starts and far under HS-1b's area."),
             k.S("M-1 and M-9 have no luminance step to compute (a bar length; a user-started show).")]
    node, _ = table_frame(fid, "SCR-038 · the flash audit (§8.1)", intro, [tab, tab2], [region, cap])
    return node, ["ΔL re-derived with the checkout's contrast_check.relative_luminance() over token-sync.json: equal "
                  "to the spec's three places"]


def f_announce(fid: str) -> tuple[Node, list[str]]:
    j = k.JUMP
    say_ = k.Say
    w38 = k.W("W-38", doc="d02")
    wper = k.tpl("Period: {mode}", {"{mode}": "Fixed range"})
    runs = [("re-bucket from SCR-039, result at " + ms(k.RESULT_MS) + " (silent)", [say_(0, w38, "D02 W-38")]),
            ("period change, result at " + ms(k.RESULT_MS) + " (silent)", [say_(0, wper, "D02 period")]),
            ("POC jump, then a 1-row move",
             [say_(0, f"{w33(j.p1)}, {w1b(j.p0, j.p1)}", "D02 W-33 + W-1b"),
              say_(k.DEFAULT_THROTTLE_MS, w33(j.p2), "D02 W-33")])]
    span, px_s, x0 = 6, 180, 24
    w = PAD * 2 + x0 + span * px_s + 220
    kids: list[Node] = [text("title", "SCR-038 · the one polite region (§8.2, R-7)", k.HEADING_SM, k.TEXT_1, x=PAD,
                             y=PAD, w=w - 2 * PAD)]
    intro = [f"R-7: {k.S('one polite region per panel, ≤ 1 per 2 s per field, latest wins')}; "
             f"{k.S('no announcement waits on motion')}",
             f"§6.1: {k.S('Announcements reuse D02')}'s once-announcements and {k.S('add none (BQ-7')}'s ruling): the "
             f"action's own word, once; {k.S('the end of loading is silent')}",
             f"§8.2: {k.S('D05 W-2, the composite progress bar')}'s accessible name, never announced (not a region event)"]
    y = PAD + 28
    for i, ln in enumerate(intro):
        t = text(f"intro {i + 1}", ln, k.CAPTION, k.TEXT_2, x=PAD, y=y, w=w - 2 * PAD)
        kids.append(t)
        y += round(k.est_height(t)) + 4
    y += 12
    lane_h = 96
    for ri, (label, evs) in enumerate(runs, 1):
        res = k.region(evs)
        lane: list[Node | None] = [rect("axis", span * px_s, 1, k.TEXT_3, x=x0, y=40),
                                   text("run label", f"run {ri} · {label}", k.LABEL, k.TEXT_1, x=x0, y=4)]
        for s_ in range(span + 1):
            lane.append(rect(f"second tick {s_}", 1, 6, k.TEXT_3, x=x0 + s_ * px_s, y=41))
            lane.append(text(f"second label {s_}", f"{s_} s", k.NUM_XS, k.TEXT_2, x=x0 + s_ * px_s - 6, y=50))
        for ei, (e, at) in enumerate(res):
            x = x0 + round(e.t_ms * px_s / 1000)
            lane.append(rect(f"event {ei}", 2, 10, k.TEXT_2, x=x, y=30))
            if at is None:
                lane.append(text(f"event {ei} words", f"{e.src} due {ms(e.t_ms)}: replaced", k.CAPTION, k.TEXT_3,
                                 x=x0 + span * px_s + 16, y=4 + 14 * ei))
            else:
                sx = x0 + round(at * px_s / 1000)
                lane.append(rect(f"spoken {ei}", 6, 6, k.RING, x=sx - 3, y=64))
                lane.append(text(f"event {ei} words", f"{e.src} said at {ms(at)}", k.CAPTION, k.TEXT_1,
                                 x=x0 + span * px_s + 16, y=4 + 14 * ei))
        k.fallback("marker")
        kids.append(box(f"board marker · run {ri}", lane, {"fill": k.CANVAS, "clip": True}, w=w - 2 * PAD, h=lane_h,
                        x=PAD, y=y))
        y += lane_h + 12
    words = [f"\"{w38}\" (D02 W-38) · \"{wper}\" (D02 period) · no word at a result",
             f"run 3 at {ms(0)}: \"{w33(j.p1)}, {w1b(j.p0, j.p1)}\"; at {ms(2000)}: \"{w33(j.p2)}\""]
    hid = hidden(" · ".join(words), w=w - 2 * PAD)
    kids.append(dict(hid, x=PAD, y=y))
    y += round(k.est_height(hid)) + 16
    key = marker_box("key", ["grey tick: the event is due; blue dot: it is said; the right column lists each event",
                             f"{k.S('Visible-range recomputes and growth are never announced.')}"], w=900)
    kids.append(dict(key, x=PAD, y=y))
    y += round(k.est_height(key)) + PAD
    h = int(math.ceil(y / 8) * 8)
    return frame(fid, kids, w, h), [f"the region rule simulated: ≤ 1 per {ms(k.REGION_GAP_MS)}, latest wins"]
