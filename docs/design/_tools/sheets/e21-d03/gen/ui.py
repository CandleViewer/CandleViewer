"""E21-D03 widgets and frames: the SCR-051 dialog (CMP-043 lg) over SCR-050 at compact, its five tabs, the footer, the
CMP-228 tile, and the SCR-153 shed row. Every string comes from the spec through k.W / k.S (or is a listed copy gap via
k.ui); every number from the kit's seeded world."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import e21d03kit as k  # noqa: E402

Node = k.Node
text, icon, rect, ellipse, box, hbox, vbox = k.text, k.icon, k.rect, k.ellipse, k.box, k.hbox, k.vbox
CTRL = k.ROW_H  # 32: size.control.comfortable
# the dialog (CMP-043 lg; kit geometry, §2.1's anatomy): centred in the 1280 × 800 window
DLG_W, DLG_H = 960, 720
DLG_X, DLG_Y = (k.WIN_W - DLG_W) // 2, (k.WIN_H - DLG_H) // 2
HEAD_H, TABS_H, FOOT_H = 56, 40, 64
BODY_Y = HEAD_H + TABS_H + 1
BODY_H = DLG_H - BODY_Y - FOOT_H - 1
PAD = k.PX[k.DIALOG_PAD]  # 24
TILE_W, TILE_H = 320, 200  # §2.3 (PROPOSED there: `15`:2948 gives no size)
LEFT_W = DLG_W - 2 * PAD - 32 - TILE_W  # 560
TILE_X = PAD + LEFT_W + 32
LABEL_W = 208  # the field label column


# --- placement by estimate (E26-D02's place / find)
def _pads(o: dict[str, Any]) -> tuple[float, float, float, float]:
    p, px_, py_ = k._px(o.get("pad")), k._px(o.get("padX")), k._px(o.get("padY"))
    return (p + px_ + k._px(o.get("padL")), p + py_ + k._px(o.get("padT")), p + px_ + k._px(o.get("padR")),
            p + py_ + k._px(o.get("padB")))


def place(n: Node, x0: float = 0, y0: float = 0, path: str = "") -> Iterable[tuple[str, Node, float, float, float,
                                                                                    float]]:
    """(path, node, x, y, w, h) for n and every descendant, in frame coordinates, by the kit's size estimates."""
    w, h = k.est_width(n), k.est_height(n)
    pth = f"{path}/{n['name']}" if path else n["name"]
    yield pth, n, x0, y0, w, h
    o = n.get("o") or {}
    kids = n.get("kids") or []
    if n["t"] != "board" or not kids:
        return
    pl, pt, pr, pb = _pads(o)
    gap = k._px(o.get("gap"))
    flow = [c for c in kids if not c.get("abs")]
    d = o.get("dir")
    if d in ("row", "column"):
        sizes = [(k.est_width(c), k.est_height(c)) for c in flow]
        main = sum(s[0] if d == "row" else s[1] for s in sizes) + gap * max(len(flow) - 1, 0)
        room = (w - pl - pr) if d == "row" else (h - pt - pb)
        cur = (pl if d == "row" else pt) + {"center": (room - main) / 2, "end": room - main}.get(o.get("justify"), 0)
        if o.get("justify") == "space-between" and len(flow) > 1:
            gap += (room - main) / (len(flow) - 1)
        for c, (cw, chh) in zip(flow, sizes):
            if d == "row":
                cy = pt + ((h - pt - pb - chh) / 2 if o.get("align", "center") == "center" else 0)
                yield from place(c, x0 + cur, y0 + cy, pth)
                cur += cw + gap
            else:
                cx = pl + ((w - pl - pr - cw) / 2 if o.get("align") == "center" else 0)
                yield from place(c, x0 + cx, y0 + cur, pth)
                cur += chh + gap
        for c in kids:
            if c.get("abs"):
                yield from place(c, x0 + c.get("x", 0), y0 + c.get("y", 0), pth)
    else:
        for c in kids:
            yield from place(c, x0 + c.get("x", 0), y0 + c.get("y", 0), pth)


def find(frame_kids: list[Node], test: Callable[[str, Node], bool]) -> tuple[float, float, float, float]:
    for top in frame_kids:
        for pth, n, x, y, w, h in place(top, top.get("x", 0), top.get("y", 0)):
            if test(pth, n):
                return x, y, w, h
    raise LookupError("no node matches")


# --- board markers (never product UI)
def marker_box(name: str, kids: list[Node], *, w: int | None = None, tight: bool = False, **kw: Any) -> Node:
    """tight: 4 px top and bottom padding (the foot-strip announcements, which must fit the 40 px under the dialog)."""
    k.fallback("marker")
    pads = {"padX": k.INSET_SM, "padY": k.INSET_XS} if tight else {"pad": k.INSET_SM}
    return vbox(f"board marker · {name}", kids, {"gap": k.STACK_XS, **pads, "fill": k.CANVAS,
                                                 "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                                                 "strokeAlign": "inner", "radius": k.R_CONTROL},
                **({"w": w} if w else {}), note="board marker, not product UI", **kw)


def foot_strip_y(n: Node) -> int:
    """y of a foot-strip marker: under the dialog's lower edge and inside the window (it sat 16 px over the dialog's
    edge on 02, 05, 07, 08 and 10 when drawn), so it must fit the strip."""
    top, room = DLG_Y + DLG_H, k.WIN_H - (DLG_Y + DLG_H)
    if n["h"] > room:
        raise ValueError(f"{n['name']}: {n['h']} px does not fit the {room} px foot strip under the dialog")
    return top + (room - n["h"]) // 2


def announce(chars: str, *, how: str = "polite, once", w: int = 520, x: int = 16, dialog: bool = True) -> Node:
    """The words a screen reader hears (R-5): a board marker at the window's foot; in a dialog frame it sits in the
    foot strip under the dialog (tight padding), in a frame with no dialog (SCR-153) 8 px over the window's edge."""
    kids = [text("how", k.ui(f"announced: {how}", "board-marker label"), k.CAPTION, k.TEXT_3),
            text("words", chars, k.CAPTION, k.TEXT_1, w=w - 16)]
    if dialog:
        n = marker_box("announcement", kids, w=w, tight=True)
        n = dict(n, h=k.est_drawn_height(n), x=x)
        return dict(n, y=foot_strip_y(n))
    n = marker_box("announcement", kids, w=w)
    hh = math.ceil(k.est_height(n) / 4) * 4
    return dict(n, h=hh, x=x, y=k.WIN_H - hh - 8)


def hidden_name(chars: str, *, w: int = 320) -> Node:
    """A visually hidden accessible name (the tile's role="img" name): a board marker."""
    kids = [text("how", k.ui("accessible name (not on screen)", "board-marker label"), k.CAPTION, k.TEXT_3),
            text("words", chars, k.CAPTION, k.TEXT_1, w=w - 16)]
    n = marker_box("accessible name", kids, w=w)
    return dict(n, h=math.ceil(k.est_height(n) / 4) * 4)


def illustrative(w: int | None = None) -> Node:
    """The "illustrative, PROPOSED, not a budget" marker: one line, or wrapped to a fixed width w (07 beside the
    dialog, where one line ran 47 px past the frame: SHEET-FIX 07)."""
    if not w:
        return dict(marker_box("illustrative", [text("words", k.ILLUSTRATIVE, k.CAPTION, k.TEXT_1)]), h=28)
    n = marker_box("illustrative", [text("words", k.ILLUSTRATIVE, k.CAPTION, k.TEXT_1, w=w - 16)], w=w)
    return dict(n, h=k.est_drawn_height(n))


def order_marker(n: int, x: float, y: float) -> Node:
    k.fallback("badge")
    return hbox(f"focus order marker {n:02d}", [text("number", str(n), k.CAPTION, k.TEXT_ON_ACTION)],
                {"fill": k.RING, "radius": k.R_BADGE, "justify": "center"}, w=20, h=20, x=round(x), y=round(y),
                note="board marker, not product UI")


# --- primitives of the controls
def ring(n: Node, radius: str = k.R_CONTROL, name: str = "focus-ring") -> Node:
    """color.focus.ring, 2 px outside the control (§2.4): a wrapper padded 4 around it."""
    w = round(k.est_width(n)) + 8
    return box(name, [dict(n, x=4, y=4)], {"radius": radius, "stroke": k.RING, "strokeWidth": k.FOCUS_W,
                                           "strokeAlign": "inner"}, w=w, h=round(k.est_height(n)) + 8,
               note="focus-visible: color.focus.ring 2 px outside the control")


def lock(name: str = "CMP-019 lock") -> Node:
    """CMP-019 `lock` (decorative=false, name "Not available"), leading the label, color.text.tertiary (R-3)."""
    return icon(name, "locked", k.TEXT_3, k.ICON_SM, note='CMP-019 lock, accessible name "Not available"')


def reason(chars: str, name: str = "T2 reason (2a)", w: int | None = None) -> Node:
    return text(name, chars, k.CAPTION, k.TEXT_2, **({"w": w} if w else {}))


def radio_mark(checked: bool, *, t2: bool = False) -> Node:
    k.fallback("radio")
    if checked and not t2:
        return box("radio mark · checked", [ellipse("dot", 8, 8, {"fill": k.ACTION_PRIMARY}, x=4, y=4)],
                   {"radius": k.R_BADGE, "stroke": k.ACTION_PRIMARY, "strokeWidth": k.THICK, "strokeAlign": "inner"},
                   w=16, h=16)
    return box("radio mark", [], {"radius": k.R_BADGE, "stroke": k.TEXT_3, "strokeWidth": k.HAIR,
                                  "strokeAlign": "inner"}, w=16, h=16)


def check_mark(on: bool) -> Node:
    k.fallback("radio")
    if on:
        return box("box · checked", [icon("check", "check", k.TEXT_ON_ACTION, k.ICON_SM, x=2, y=2)],
                   {"fill": k.ACTION_PRIMARY, "radius": k.R_CONTROL}, w=16, h=16)
    return box("box", [], {"stroke": k.TEXT_3, "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL},
               w=16, h=16)


# --- controls (CMP-005, CMP-006, CMP-008, CMP-009, CMP-001, the T2 anatomy of R-3)
def radio(label: str, *, checked: bool = False, desc: str | None = None, t2: str | None = None,
          focused: bool = False) -> Node:
    """A CMP-006 option: 24 px hit row (size.target.min), the description line under it; T2 (R-3, 2a): the lock leads
    the label, both color.text.tertiary, the reason color.text.secondary under it, in a color.surface.raised well with a
    color.border.default hairline; arrow-reachable, never checked by arrowing."""
    if t2:
        row = hbox("option row", [lock(), radio_mark(False, t2=True), text("label", label, k.BODY, k.TEXT_3)],
                   {"gap": k.INSET_XS}, h=24)
        kids = [row] + ([text("description", desc, k.CAPTION, k.TEXT_3)] if desc else []) + [reason(t2)]
        n = vbox(f"CMP-006 option {label} · T2 2a", kids,
                 {"gap": k.STACK_XS, "padX": k.INSET_SM, "padY": k.INSET_XS, "fill": k.RAISED, "stroke": k.BORDER,
                  "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL},
                 note=f'T2 2a (R-3): aria-disabled="true", in the group, aria-describedby → "{t2}"')
        n["h"] = math.ceil(k.est_height(n))
    else:
        row = hbox("option row", [radio_mark(checked), text("label", label, k.BODY, k.TEXT_1)], {"gap": k.INSET_SM},
                   h=24)
        if desc:
            n = vbox(f"CMP-006 option {label}", [row, text("description", desc, k.CAPTION, k.TEXT_2)],
                     {"gap": k.STACK_XS}, note="checked" if checked else None)
            n["h"] = math.ceil(k.est_height(n))
        else:
            n = dict(row, name=f"CMP-006 option {label}", note="checked" if checked else None)
    return ring(n) if focused else n


def group(label: str, options: list[Node], *, horizontal: bool = True, w: int = LEFT_W, after: Iterable[Node] = (),
          name: str | None = None) -> Node:
    """A labelled group (CMP-065 FormSection block): the label (type.ui.label) over its options."""
    opts = (hbox if horizontal else vbox)("options", options,
                                          {"gap": k.INSET_LG if horizontal else k.STACK_SM, "align": "start",
                                           **({"wrap": "wrap"} if horizontal else {})}, w=w)
    opts["h"] = math.ceil(k.est_height(opts))
    kids = [text("group label", label, k.LABEL, k.TEXT_1), opts, *after]
    n = vbox(name or f"group · {label}", kids, {"gap": k.STACK_SM}, w=w)
    n["h"] = k.est_drawn_height(n)  # whole-px texts: the 1-2 px rounding allowance (SHEET-FIX 02, 07)
    return n


def checkbox(label: str, *, on: bool, focused: bool = False, name: str | None = None) -> Node:
    b = hbox(name or f"CMP-005 {label}", [check_mark(on), text("label", label, k.BODY, k.TEXT_1)], {"gap": k.INSET_SM},
             h=24, note=f"checkbox, {'checked' if on else 'unchecked'}")
    return ring(b) if focused else b


def input_box(value: str, *, w: int = 96, unit: str | None = None, state: str = "rest", focused: bool = False,
              chevron: bool = False, name: str = "input") -> Node:
    """CMP-008 (or CMP-009 with the chevron): 32 px, the rest stroke color.text.tertiary (E05-D04 F-03); error stroke
    color.status.danger.strong, warning color.status.warning.strong."""
    stroke = {"rest": k.TEXT_3, "error": k.DANGER_STRONG, "warning": k.WARN_STRONG}[state]
    kids: list[Node] = [text("value", value, k.NUM, k.TEXT_1)] if value else [rect("empty", 8, 16)]
    if unit:
        kids.append(text("unit", unit, k.CAPTION, k.TEXT_2))
    if chevron:
        kids.append(icon("chevron", "chevron-down", k.TEXT_2, k.ICON))
    b = hbox(name, kids, {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.SUNKEN, "stroke": stroke,
                          "strokeWidth": k.THICK if state != "rest" else k.HAIR, "strokeAlign": "inner",
                          "radius": k.R_CONTROL, "justify": "space-between" if chevron else "start"}, w=w, h=CTRL)
    return ring(b) if focused else b


def callout(chars: str, *, tone: str = "error", w: int = LEFT_W, name: str | None = None, focus: bool = False) -> Node:
    """CMP-027 inline under a field: the glyph (danger / warning .strong), the message color.text.primary."""
    gl, gc = {"error": ("danger", k.DANGER_STRONG), "warning": ("warning", k.WARN_STRONG)}[tone]
    words = text("message", chars, k.CAPTION, k.TEXT_1, w=w - 24)
    n = hbox(name or f"CMP-027 inline · {tone}", [icon("glyph", gl, gc, k.ICON), words], {"gap": k.INSET_XS,
                                                                                        "align": "start"}, w=w)
    n["h"] = max(16, math.ceil(k.est_height(words)))
    return ring(n) if focus else n


def field(label: str, value: str, *, w_input: int = 96, unit: str | None = None, msg: tuple[str, str] | None = None,
          focused: bool = False, chevron: bool = False, w: int = LEFT_W, name: str | None = None,
          label_w: int = LABEL_W) -> Node:
    """A labelled form field: the label (type.ui.label, the unit in it) left of its input; an error / warning callout
    under it (aria-describedby)."""
    st = msg[0] if msg else "rest"
    row = hbox("field row", [text("label", label, k.LABEL, k.TEXT_1, w=label_w),
                             input_box(value, w=w_input, unit=unit, state=st, focused=focused, chevron=chevron)],
               {"gap": k.INSET_MD}, w=w, h=CTRL + (8 if focused else 0))
    if not msg:
        return dict(row, name=name or f"field · {label}")
    c = callout(msg[1], tone=msg[0], w=w - label_w - 12)
    under = hbox("under", [rect("indent", label_w, 1), c], {"gap": k.INSET_MD, "align": "start"}, w=w, h=c["h"])
    n = vbox(name or f"field · {label}", [row, under], {"gap": k.STACK_XS}, w=w)
    n["h"] = math.ceil(k.est_height(n))
    return n


def button(label: str, *, kind: str = "secondary", focused: bool = False, busy: bool = False,
           t2: bool = False, name: str | None = None) -> Node:
    """CMP-001 primary / secondary / ghost (32 px); busy: CMP-043's loading Save (aria-disabled, never disabled);
    T2 (R-3, 2a): the lock leads the label, color.text.tertiary on color.surface.raised + a color.border.default
    hairline, never color.text.disabled nor opacity.disabled."""
    nm = name or f"CMP-001 {label}"
    lw = round(k.text_w(label, k.BODY_STRONG))
    if t2:
        b = hbox(nm + " · T2 2a", [lock(), text("label", label, k.BODY_STRONG, k.TEXT_3)],
                 {"gap": k.INSET_XS, "padX": k.BUTTON_PADX, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                  "strokeAlign": "inner", "radius": k.R_CONTROL, "justify": "center"}, w=lw + 12 + 4 + 26, h=CTRL,
                 note='T2 2a (R-3): aria-disabled="true", aria-describedby → the footer notice')
        return ring(b) if focused else b
    fill, col = {"primary": (k.ACTION_PRIMARY, k.TEXT_ON_ACTION), "secondary": (k.ACTION_SECONDARY, k.TEXT_1),
                 "ghost": (None, k.TEXT_1)}[kind]
    if busy:
        k.fallback("spinner")
        kids = [ellipse("spinner", 12, 12, {"stroke": k.TEXT_ON_ACTION, "strokeWidth": k.THICK, "strokeAlign": "inner"}),
                text("label", label, k.BODY_STRONG, col)]
    else:
        kids = [text("label", label, k.BODY_STRONG, col)]
    o = {"padX": k.BUTTON_PADX, "radius": k.R_CONTROL, "justify": "center", "gap": k.INSET_SM}
    if fill:
        o["fill"] = fill
    b = hbox(nm + (" · busy" if busy else ""), kids, o, w=lw + 26 + (20 if busy else 0), h=CTRL,
             note='busy (CMP-043 loading): aria-disabled="true", never disabled' if busy else kind)
    return ring(b) if focused else b


def env_badge(env: str) -> Node:
    """E10-D03's pill (§2.4): the word type.ui.label color.text.primary on color.surface.raised; the glyph and the 2 px
    border in color.env.demo / color.env.live (the env colour is never text)."""
    k.fallback("env-glyph")
    tok = {"DEMO": k.ENV_DEMO, "LIVE": k.ENV_LIVE}[env]
    dot = ellipse("glyph", 8, 8, {"stroke": tok, "strokeWidth": k.THICK, "strokeAlign": "inner"} if env == "DEMO"
                  else {"fill": tok})
    return hbox(f"env badge · {env}", [dot, text("word", k.S(env), k.LABEL, k.TEXT_1)],
                {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.RAISED, "stroke": tok, "strokeWidth": k.THICK,
                 "strokeAlign": "inner", "radius": k.R_BADGE}, h=22, note="the session environment (R-4), not the feed")


def close_btn(focused: bool = False) -> Node:
    b = box("close button", [icon("glyph", "close", k.TEXT_2, k.ICON, x=4, y=4)], {"radius": k.R_CONTROL}, w=24, h=24,
            note='"Close": 24 × 24 (size.target.min); discards unsaved changes at once (§2.1)')
    return ring(b) if focused else b


# --- the CMP-228 tile (§2.3), the CMP-113 legend, the stops bar (C-10), the CMP-069 cost panel (§3.4)
TILE_M = 40  # the color.surface.sunken margin carrying "Ask" / "Bid"
CELL_W, BAND_H = 16, 18
GRID_X, GRID_Y = TILE_M, 10
MID_Y = GRID_Y + k.BANDS * BAND_H


def tile_name(tier: int = k.DEFAULT_TIER, *, cvd: bool = False, sim: str | None = None) -> str:
    """The tile's role="img" name in §2.3's form (the example verbatim at the default)."""
    s = f"Preview, asks above, bids below: depth {tier}, log scale, gamma 1.0, {'CVD-safe' if cvd else 'standard'} palette"
    if (tier, cvd, sim) == (k.DEFAULT_TIER, False, None):
        return k.S(s)
    k.derive(f"tile name in §2.3's form (L{k.L('Its `role=\"img\"` name states')}): \"{s}\""
             + (f" + \", simulated {sim}\" (§4)" if sim else ""))
    return s + (f", simulated {sim}" if sim else "")


def tile(tier: int = k.DEFAULT_TIER, *, cvd: bool = False, unavailable: bool = False, name: str = "CMP-228 tile") -> Node:
    """CMP-228 `heatmap`, source "sample": 320 × 200 on color.surface.sunken with a color.border.default edge; asks above
    the mid-price line, bids below, the words "Ask" / "Bid" on the margin (type.ui.caption, color.text.primary); cells
    color.heatmap.* (or the CVD set) over color.heatmap.zero; W-31 when it cannot render."""
    k.fallback("tile")
    gw = k.TILE_COLS * CELL_W
    kids: list[Node] = [rect("cells · zero", gw, 2 * k.BANDS * BAND_H, k.HM_ZERO, x=GRID_X, y=GRID_Y)]
    if unavailable:
        msg = k.W("W-31")
        tw = k.text_w(msg, k.BODY)
        kids.append(text("W-31", msg, k.BODY, k.TEXT_2, x=round(GRID_X + (gw - tw) / 2), y=MID_Y - 9))
    else:
        runs = k.tile_runs(tier)
        for side in ("ask", "bid"):
            for b, rs in enumerate(runs[side]):
                y = MID_Y - (b + 1) * BAND_H if side == "ask" else MID_Y + b * BAND_H
                for c0, c1, lv in rs:
                    kids.append(rect(f"cell · {side} band {b + 1} cols {c0 + 1}-{c1 + 1} · {lv}", (c1 - c0 + 1) * CELL_W,
                                     BAND_H, k.hm(side, lv, cvd), x=GRID_X + c0 * CELL_W, y=y))
        kids.append(rect("mid-price line", gw, 1, k.TEXT_1, x=GRID_X, y=MID_Y))
    kids += [text("side · Ask", k.S("Ask"), k.CAPTION, k.TEXT_1, x=8, y=MID_Y - 24),
             text("side · Bid", k.S("Bid"), k.CAPTION, k.TEXT_1, x=8, y=MID_Y + 10)]
    return box(name, kids, {"fill": k.SUNKEN, "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                            "radius": k.R_CONTROL}, w=TILE_W, h=TILE_H,
               note='role="img" (its name in the annotations); static sample frames, never a live subscription')


def legend(*, cvd: bool = False, anchors: tuple[Any, ...] | None = None) -> Node:
    """CMP-113 under the tile (E21-D04's component): the convention in words and the scale with numeric anchors."""
    an = anchors or k.stops()
    seg = [rect(f"ramp · ask {i}", 16, 8, k.hm("ask", i, cvd)) for i in range(5, 0, -1)] + \
          [rect(f"ramp · bid {i}", 16, 8, k.hm("bid", i, cvd)) for i in range(1, 6)]
    k.derive(f"legend anchors = the tier-{k.DEFAULT_TIER} stops {', '.join(k.size_fmt(a) for a in an)} BTC")
    return vbox("CMP-113 legend", [
        hbox("ramp", seg, {"gap": k.INSET_XS}, h=8),
        text("convention", k.ui(f"{k.S('Green = bid')} · {'CVD-safe' if cvd else 'standard'} set · asks above the mid, "
                                f"bids below", "CMP-113's words are E21-D04 #504's"), k.CAPTION, k.TEXT_1, w=TILE_W),
        text("scale", k.ui(f"log scale · stops {k.size_fmt(an[0])} – {k.size_fmt(an[-1])} BTC", "CMP-113's words are "
                           "E21-D04 #504's"), k.CAPTION, k.TEXT_2, w=TILE_W)], {"gap": k.STACK_XS}, w=TILE_W, h=48)


def stops_editor(anchors: tuple[Any, ...], *, w: int = LEFT_W) -> Node:
    """§4 Stops (C-10): a gradient bar with one 24 × 24 handle per stop, and one CMP-008 input per stop beside it,
    labelled "Stop 1 (BTC)" …"""
    k.fallback("gradient")
    cw = (w - 4 * 12) // 5
    bar = box("gradient bar", [rect(f"segment {i}", cw + (12 if i < 5 else 0), 8, k.hm("bid", i), x=(i - 1) * (cw + 12),
                                    y=8) for i in range(1, 6)] +
              [box(f"handle · Stop {i}", [], {"fill": k.SUNKEN, "stroke": k.TEXT_3, "strokeWidth": k.HAIR,
                                              "strokeAlign": "inner", "radius": k.R_CONTROL}, w=24, h=24,
                   x=(i - 1) * (cw + 12), y=0, note="one CMP-010-like handle (24 × 24, size.target.min)")
               for i in range(1, 6)], {}, w=w, h=24)
    first = k.S("Stop 1 (BTC)")
    k.derive("stop labels 2–5 follow §4's \"Stop 1 (BTC)\" …")
    ins = [vbox(f"stop {i}", [text("label", first if i == 1 else f"Stop {i} (BTC)", k.CAPTION, k.TEXT_1),
                              input_box(k.size_fmt(a), w=cw, name=f"CMP-008 Stop {i}")], {"gap": k.STACK_XS}, w=cw,
                h=16 + 4 + CTRL) for i, a in enumerate(anchors, 1)]
    return vbox("group · Stops", [text("group label", k.S("Stops"), k.LABEL, k.TEXT_1), bar,
                                  hbox("inputs", ins, {"gap": k.INSET_MD, "align": "start"}, w=w, h=52)],
                {"gap": k.STACK_SM}, w=w, h=14 + 8 + 24 + 8 + 52)


def cost_panel(measured: tuple[int, ...], *, w: int = LEFT_W) -> Node:
    """CMP-069 `inline`, always open (A-6): W-6, then one W-7 per measured tier, a W-8 for each other; a measured
    figure is the kit model's, marked "illustrative, PROPOSED, not a budget" (§3.4)."""
    lines: list[Node] = [text("W-6", k.W("W-6"), k.BODY, k.TEXT_1, w=w - 24)]
    for t in k.TIERS:
        if t in measured:
            p95, rate = k.cost(t)
            k.derive(f"W-7 at {t}: p95 {p95} ms, inbound {rate}/s from the kit model (seed {k.SEED}, "
                     f"{k.FRAME_MS_BASE} + {k.FRAME_MS_PER_LEVEL} ms × levels, p95 of 600 frames; 10 s of 20 Hz "
                     f"updates at p {k.UPDATE_P} a level) — {k.ILLUSTRATIVE}")
            lines.append(text(f"W-7 · {t}", k.W("W-7", tier=t, p95=p95, rate=rate), k.CAPTION, k.TEXT_2, w=w - 24))
        else:
            lines.append(text(f"W-8 · {t}", k.W("W-8", tier=t), k.CAPTION, k.TEXT_2, w=w - 24))
    if measured:
        lines.append(illustrative())
    n = vbox("CMP-069 cost warning (inline, always open)", lines,
             {"gap": k.STACK_XS, "pad": k.INSET_MD, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
              "strokeAlign": "inner", "radius": k.R_CONTROL}, w=w, note="text, not a Tab stop")
    n["h"] = math.ceil(k.est_height(n))
    return n


# --- the dialog state and its five tabpanels
from dataclasses import dataclass, field as dfield  # noqa: E402


@dataclass
class Dlg:
    tab: str = "Depth & scale"
    env: str = "DEMO"
    tier: int = k.DEFAULT_TIER
    t2_500: bool = False
    w4: bool = False
    trail: str = "60"
    trail_msg: tuple[str, str] | None = None
    measured: tuple[int, ...] = k.MEASURED_TIERS
    focus: str = ""  # the name prefix of the focused control
    cvd: bool = False
    sim: str = "Off"
    tile_off: bool = False
    row_h: str = "24"
    row_msg: tuple[str, str] | None = None
    live_confirm: bool = True
    presets: tuple[str, ...] = k.PRESETS
    presets_msg: str | None = None
    status: str = ""  # the footer status node's words
    save: str = "rest"  # rest | busy | t2
    notice: str = ""  # the footer's T2 notice (§8.4)
    refused: str = ""  # W-9 under the Save row (§8.3)
    extra: list[Node] = dfield(default_factory=list)  # positioned frame-level nodes (markers)


def _f(d: Dlg, name: str) -> bool:
    return bool(d.focus) and name.startswith(d.focus)


def depth_tab(d: Dlg) -> list[Node]:
    desc = k.S("levels per side")
    opts = [radio(str(t), checked=(t == d.tier and not (t == 500 and d.t2_500)), desc=desc,
                  t2=k.W("W-3") if (t == 500 and d.t2_500) else None, focused=_f(d, f"tier {t}")) for t in k.TIERS]
    after = [text("W-4", k.W("W-4"), k.CAPTION, k.TEXT_2, w=LEFT_W)] if d.w4 else []
    trail_row = hbox("row · trail and decay", [
        text("label", k.S("Trail length (s)"), k.LABEL, k.TEXT_1, w=LABEL_W),
        input_box(d.trail, w=96, state=d.trail_msg[0] if d.trail_msg else "rest", focused=_f(d, "trail"),
                  name="CMP-008 Trail length"),
        text("label · decay", k.S("Decay"), k.LABEL, k.TEXT_1),
        input_box(k.S("Smooth"), w=128, chevron=True, name="CMP-009 Decay")], {"gap": k.INSET_MD}, w=LEFT_W,
        h=CTRL + (8 if _f(d, "trail") else 0))
    trail = trail_row
    if d.trail_msg:
        c = callout(d.trail_msg[1], tone=d.trail_msg[0], w=LEFT_W - LABEL_W - 12)
        trail = vbox("field · Trail length", [trail_row, hbox("under", [rect("indent", LABEL_W, 1), c],
                                                                 {"gap": k.INSET_MD, "align": "start"}, w=LEFT_W,
                                                                 h=c["h"])], {"gap": k.STACK_XS}, w=LEFT_W)
        trail["h"] = math.ceil(k.est_height(trail))
    cols = [radio(k.W("W-14"), checked=True)] + [radio(k.S(x)) for x in ("100 ms", "250 ms", "500 ms", "1 s", "5 s")]
    return [group(k.S("Depth tier"), opts, after=after),
            checkbox(k.W("W-15"), on=False, focused=_f(d, "pin")),
            field(k.S("Row aggregation (ticks per row)"), "1", w_input=72, name="field · Row aggregation"),
            group(k.S("Columns"), cols),
            trail,
            cost_panel(d.measured)]


def colour_tab(d: Dlg) -> list[Node]:
    scale = group(k.S("Colour scale"), [radio(k.S("log"), checked=True), radio(k.S("linear"))], w=300)
    gamma = field(k.S("gamma"), "1.0", w_input=72, w=240, label_w=56, name="field · gamma")
    # the row hugs its tallest child (it was a fixed 46 under the 47 px group: SHEET-FIX 03)
    return [hbox("row · scale and gamma", [scale, gamma], {"gap": k.INSET_LG, "align": "end"}, w=LEFT_W,
                 h=max(scale["h"], k.est_drawn_height(gamma))),
            group(k.S("Scale"), [radio(k.S("Adaptive"), checked=True), radio(k.S("Locked"))]),
            stops_editor(k.stops()),
            group(k.S("Set"), [radio(k.S("Standard"), checked=not d.cvd), radio(k.S("CVD-safe"), checked=d.cvd)]),
            group(k.S("Convention"), [radio(k.S("Green = bid"), checked=True), radio(k.S("Red = bid"))]),
            field(k.W("W-34"), d.sim, w_input=160, chevron=True, focused=_f(d, "sim"), name="field · simulation")]


def ladder_tab(d: Dlg) -> list[Node]:
    cl = [radio(k.S("Auto-follow"), checked=True), radio(k.S("Free scroll")),
          radio(k.S("Centre lock"), desc=k.W("W-16"), focused=_f(d, "centre lock"))]
    show = [checkbox(k.S(x), on=True) for x in ("Your orders", "Position", "Prints", "Cumulative depth")] + \
           [checkbox(k.W("W-17"), on=False)]
    return [field(k.S("Row height (px)"), d.row_h, w_input=72, msg=d.row_msg, focused=_f(d, "row height"),
                  name="field · Row height"),
            group(k.S("Centring"), cl, horizontal=False),
            group(k.S("Show"), show, horizontal=False)]


def presets_row(d: Dlg) -> Node:
    label = k.ui("Quantity presets (BTC)", "§2.2 names the field \"Quantity presets 1–4\"; the unit in the label "
                                            "(T A11y)")
    ins = [input_box(v, w=72, state="error" if d.presets_msg else "rest", name=f"CMP-008 preset {i}")
           for i, v in enumerate(d.presets, 1)]
    row = hbox("field row", [text("label", label, k.LABEL, k.TEXT_1, w=LABEL_W), *ins], {"gap": k.INSET_SM}, w=LEFT_W,
               h=CTRL)
    if not d.presets_msg:
        return dict(row, name="field · Quantity presets")
    c = callout(d.presets_msg, w=LEFT_W - LABEL_W - 12)
    n = vbox("field · Quantity presets", [row, hbox("under", [rect("indent", LABEL_W, 1), c],
                                                     {"gap": k.INSET_MD, "align": "start"}, w=LEFT_W, h=c["h"])],
             {"gap": k.STACK_XS}, w=LEFT_W)
    n["h"] = math.ceil(k.est_height(n))
    return n


def trading_tab(d: Dlg) -> list[Node]:
    kids: list[Node] = [presets_row(d), checkbox(k.W("W-18"), on=d.live_confirm, focused=_f(d, "live confirm"),
                                                  name="CMP-005 live confirm")]
    if not d.live_confirm:
        warn = vbox("CMP-028 warning · W-20", [hbox("line", [icon("glyph", "warning", k.WARN_STRONG, k.ICON),
                                                             text("words", k.W("W-20"), k.BODY, k.TEXT_1,
                                                                  w=LEFT_W - 52)], {"gap": k.INSET_SM,
                                                                                    "align": "start"},
                                                        w=LEFT_W - 24, h=20)],
                    {"pad": k.INSET_MD, "fill": k.WARN_SUBTLE, "radius": k.R_CONTROL}, w=LEFT_W, h=44,
                    note="inline under the checkbox, no modal (§6)")
        kids.append(warn)
    kids += [text("W-19", k.W("W-19"), k.BODY, k.TEXT_1, w=LEFT_W),
             vbox("click-trade behaviour (read-only)", [
                 text("label", k.S("Click-trade behaviour"), k.LABEL, k.TEXT_1),
                 text("W-30", k.W("W-30"), k.BODY, k.TEXT_2, w=LEFT_W),
                 text("arm", k.S("Ctrl+Shift+T = arm/disarm one-click"), k.CAPTION, k.TEXT_2)],
                 {"gap": k.STACK_XS}, w=LEFT_W, h=14 + 4 + 36 + 4 + 14)]
    return kids


def detectors_tab(d: Dlg) -> list[Node]:
    return [group(k.ui("Detectors", "§7 names no group label; the tab's name"), [
                checkbox(k.S(x), on=True) for x in ("Iceberg (estimated)", "Stop-run (estimated)",
                                                    "Absorption (estimated)")], horizontal=False),
            field(k.S("Sensitivity"), k.S("Medium"), w_input=128, chevron=True, name="field · Sensitivity"),
            field(k.W("W-28"), "", w_input=96, unit="BTC", focused=_f(d, "big"), name="field · big orders")]


TAB_BODY = {"Depth & scale": depth_tab, "Colour": colour_tab, "Ladder": ladder_tab, "Trading": trading_tab,
            "Detectors": detectors_tab}


# --- header, tablist, footer, the card
def header(d: Dlg) -> Node:
    title = text("W-1 title", k.W("W-1"), k.HEADING_SM, k.TEXT_1)
    lead = hbox("title and badge", [title, env_badge(d.env)], {"gap": k.INSET_MD}, h=24)
    return hbox("header", [lead, close_btn(_f(d, "close"))],
                {"padX": k.DIALOG_PAD, "justify": "space-between"}, w=DLG_W, h=HEAD_H,
                note=f'role="dialog", aria-modal="true", named by W-2: "{k.W("W-2", symbol=k.SYM, env=d.env)}"')


def tablist(d: Dlg) -> Node:
    tabs = []
    for t in k.TABS:
        sel = t == d.tab
        lab = hbox("label", [text("words", k.S(t), k.LABEL, k.TEXT_1 if sel else k.TEXT_2)], {"padX": k.INSET_MD},
                   h=TABS_H - 2)
        rule = rect("selected rule", round(k.est_width(lab)), 2, k.BORDER_SELECTED) if sel else \
            rect("rule slot", round(k.est_width(lab)), 2)
        tb = vbox(f"tab · {t}" + (" (selected)" if sel else ""), [lab, rule], {}, h=TABS_H,
                  note='role="tab", aria-selected="true"' if sel else 'role="tab"')
        tabs.append(ring(tb) if sel and _f(d, "tablist") else tb)
    return hbox("CMP-042 tablist", tabs, {"padX": k.INSET_LG, "align": "end"}, w=DLG_W, h=TABS_H + (4 if
                                                                                                    _f(d, "tablist")
                                                                                                    else 0),
                note='one Tab stop; arrows move and activate (automatic)')


def footer(d: Dlg) -> Node:
    left = [button(k.S("Reset to defaults"), kind="ghost", focused=_f(d, "reset all")),
            button(k.S("Reset this tab"), kind="ghost", focused=_f(d, "reset tab"))]
    right = [button(k.S("Cancel"), focused=_f(d, "cancel")),
             button(k.S("Save"), kind="primary", busy=d.save == "busy", t2=d.save == "t2", focused=_f(d, "save"))]
    room = DLG_W - 2 * PAD - sum(k.est_width(b) for b in left + right) - 4 * 8
    if d.notice:
        st: Node = hbox("footer notice (G-T2.5)", [lock("CMP-019 lock · notice"),
                                                   text("words", d.notice, k.CAPTION, k.TEXT_2, w=round(room) - 24)],
                        {"gap": k.INSET_XS, "align": "start"}, w=round(room), h=32,
                        note="Save's aria-describedby points here (G-T2.5, adapted: the footer stands in for the header)")
    elif d.status:
        st = vbox("status node", [text("words", d.status, k.CAPTION, k.TEXT_2, w=round(room) - 8)], {"justify": "center"},
                  w=round(room), h=32, note='role="status" (R-5): writes into the app shell\'s polite pair')
    else:
        st = rect("status node (empty)", round(room), 32)
    row = hbox("buttons", [*left, st, *right], {"gap": k.INSET_SM}, w=DLG_W - 2 * PAD, h=CTRL + 8)
    kids: list[Node] = [row]
    if d.refused:
        c = callout(d.refused, tone="warning", w=420, name="W-9 (T4, tabindex=-1)", focus=True)
        kids.append(hbox("under the Save row", [rect("indent", DLG_W - 2 * PAD - 428, 1), c], {"align": "start"},
                         w=DLG_W - 2 * PAD, h=c["h"]))
    n = vbox("footer (sticky)", kids, {"gap": k.STACK_XS, "padX": k.DIALOG_PAD, "padY": k.INSET_MD, "justify": "center"},
             w=DLG_W)
    n["h"] = max(FOOT_H, math.ceil(k.est_height(n)))
    return n


def card(d: Dlg) -> Node:
    ft = footer(d)
    body_h = DLG_H - BODY_Y - ft["h"] - 1
    left = vbox(f"tabpanel · {d.tab}", TAB_BODY[d.tab](d), {"gap": k.STACK_MD}, w=LEFT_W, x=PAD, y=BODY_Y + PAD,
                note='role="tabpanel"; fields in CMP-065 FormSection blocks')
    lh = k.est_height(left)
    if lh > body_h - 2 * PAD:
        raise ValueError(f"{d.tab}: the tabpanel ({lh:.0f} px) overflows the body ({body_h - 2 * PAD} px)")
    left["h"] = math.ceil(lh)
    rk: list[Node] = [tile(d.tier, cvd=d.cvd, unavailable=d.tile_off)]
    if d.tab == "Colour":
        rk.append(legend(cvd=d.cvd))
    right = vbox("preview column", rk, {"gap": k.STACK_MD}, w=TILE_W, x=TILE_X, y=BODY_Y + PAD)
    right["h"] = math.ceil(k.est_height(right))
    kids = [header(d), dict(tablist(d), x=0, y=HEAD_H), rect("tabs rule", DLG_W, 1, k.BORDER, x=0, y=HEAD_H + TABS_H),
            left, right, rect("footer rule", DLG_W, 1, k.BORDER, x=0, y=DLG_H - ft["h"] - 1),
            dict(ft, x=0, y=DLG_H - ft["h"])]
    return box("CMP-043 dialog (lg)", kids, {"fill": k.OVERLAY, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                             "strokeAlign": "inner", "radius": k.R_DIALOG, "clip": True},
               w=DLG_W, h=DLG_H, x=DLG_X, y=DLG_Y,
               note="CMP-043 size lg, comfortable; color.surface.overlay, space.dialog.padding, 1 px color.border.default")


# --- SCR-050 behind the dialog (E21-D02 #440's anatomy, drawn as context at compact)
LCOLS = (("Price", 96), ("Bid (B)", 96), ("Ask (A)", 96), ("Prints", 80), ("Cum. depth", 104), ("Your orders", 168))
PANE_W = k.WIN_W - sum(w for _n, w in LCOLS)  # 640: the heatmap pane
HIST_W = PANE_W // k.HIST_COLS  # 40


def _inside(n: Node, r: tuple[int, int, int, int]) -> bool:
    x, y, w, h = r
    nx, ny = n.get("x", 0), n.get("y", 0)
    nw, nh = k.est_width(n), k.est_height(n)
    return nx >= x and ny >= y and nx + nw <= x + w and ny + nh <= y + h


def backdrop(tier: int = k.DEFAULT_TIER, *, y0: int = 0, hide: tuple[int, int, int, int] | None = None,
             notice: str | None = None, depth_focus: bool = False, pinned: bool = False,
             env: str = "DEMO") -> list[Node]:
    """SCR-050 at compact (24 px rows) from the seeded book; nodes wholly under the opaque dialog card are not drawn."""
    k.fallback("background")
    out: list[Node] = []
    depth = hbox("depth control", [text("label", k.ui("depth", "E21-D02's header"), k.CAPTION, k.TEXT_2),
                                   input_box(str(tier), w=64, chevron=True, name="depth listbox")], {"gap": k.INSET_XS},
                 h=32)
    if depth_focus:
        depth = ring(depth)
    head = hbox("SCR-050 header", [text("title", k.ui(f"{k.SYM} · Heatmap + Ladder", "E21-D02's panel title"),
                                        k.BODY_STRONG, k.TEXT_1), depth,
                                   *([text("pin", k.ui("pinned", "E21-D02's pin display"), k.CAPTION, k.TEXT_2)]
                                     if pinned else []),
                                   env_badge(env), text("view", k.ui("Ladder │ Table", "E21-D02's view switch"),
                                                           k.CAPTION, k.TEXT_2),
                                   icon("more", "more-horizontal", k.TEXT_2, k.ICON)],
                {"gap": k.INSET_MD, "padX": k.INSET_SM, "fill": k.CANVAS}, w=k.WIN_W, h=32 + (8 if depth_focus else 0),
                x=0, y=y0)
    out.append(head)
    y = y0 + head["h"]
    out.append(rect("column header", k.WIN_W, 24, k.CANVAS, x=0, y=y))
    out.append(text("pane label", k.ui("Heatmap (time →)", "E21-D02's pane"), k.CAPTION, k.TEXT_2, x=8, y=y + 5))
    x = PANE_W
    for nm, w in LCOLS:
        out.append(text(f"th · {nm}", k.ui(nm, "E21-D02's ladder column header"), k.CAPTION, k.TEXT_2, x=x + 8,
                        y=y + 5))
        x += w
    y += 24
    if notice:
        out.append(hbox("D02 in-panel shed notice (W-21)", [icon("glyph", "warning", k.WARN_STRONG, k.ICON),
                                                             text("words", notice, k.CAPTION, k.TEXT_1)],
                        {"gap": k.INSET_SM, "padX": k.INSET_SM, "fill": k.WARN_SUBTLE}, w=k.WIN_W, h=28, x=0, y=y,
                        note="E21-D02's panel notice; visible, not re-announced (C-5)"))
        y += 28
    n_rows = (k.WIN_H - y) // k.COMPACT_ROW
    m = n_rows // 2
    an = k.level_stops()
    cum = {"bid": k.Decimal(0), "ask": k.Decimal(0)}
    rows: list[tuple[int, str, int]] = [(i, "ask", m - i) for i in range(m)] + [(i, "bid", i - m + 1)
                                                                               for i in range(m, n_rows)]
    for side in ("ask", "bid"):  # cumulative depth from the touch
        for _i, s, lv in sorted((r for r in rows if r[1] == side), key=lambda r: r[2]):
            cum[f"{side}{lv}"] = cum[side] = cum[side] + k.BOOK[side][-1][lv - 1]  # type: ignore[index]
    cells: list[tuple[int, Node]] = []  # (row index, node): grouped into 8-row bands below (fewer render sections)
    for i, side, lv in rows:
        ry = y + i * k.COMPACT_ROW
        off = lv if side == "ask" else 1 - lv
        sz = k.BOOK[side][-1][lv - 1]
        lvls = [k.bucket(k.BOOK[side][c][lv - 1], an) for c in range(1, k.HIST_COLS + 1)]
        c0 = 0
        for c in range(1, k.HIST_COLS + 1):
            if c == k.HIST_COLS or lvls[c] != lvls[c0]:
                if lvls[c0]:
                    cells.append((i, rect(f"hm · {side} {lv} · {c0 + 1}-{c}", (c - c0) * HIST_W, k.COMPACT_ROW,
                                          k.hm(side, lvls[c0]), x=c0 * HIST_W, y=ry)))
                c0 = c
        prev = k.BOOK[side][-2][lv - 1]
        prints = prev - sz if lv <= 6 and prev > sz else None
        own = next((o for o in k.OWN if o[0] == off), None)
        vals = [k.price(k.px(off)), f"B {k.size_fmt(sz)}" if side == "bid" else "",
                f"A {k.size_fmt(sz)}" if side == "ask" else "", k.size_fmt(prints) if prints else "",
                k.size_fmt(cum[f"{side}{lv}"]),  # type: ignore[index]
                f"{own[1]} {k.size_fmt(own[2])}" if own else ""]
        x = PANE_W
        for (nm, w), v in zip(LCOLS, vals):
            if v:
                cells.append((i, text(f"td · {side} {lv} · {nm}", v, k.NUM_SM, k.TEXT_1, x=x + 8, y=ry + 5)))
            x += w
    if hide:
        cells = [(i, n) for i, n in cells if not _inside(n, hide)]
    band = 8
    for b0 in range(0, n_rows, band):
        ks = [n for i, n in cells if b0 <= i < b0 + band]
        by = y + b0 * k.COMPACT_ROW
        if ks:
            out.append(box(f"SCR-050 rows {b0 + 1}-{min(n_rows, b0 + band)}", [dict(n, y=n["y"] - by) for n in ks], {},
                           w=k.WIN_W, h=min(band, n_rows - b0) * k.COMPACT_ROW, x=0, y=by))
    out.append(rect("mark line", k.WIN_W, 1, k.TEXT_1, x=0, y=y + m * k.COMPACT_ROW))
    k.derive(f"SCR-050 behind: {n_rows} rows at compact around mark {k.price(k.MID0)} (best bid {k.price(k.px(0))}, "
             f"best ask {k.price(k.px(1))}); cum. depth from the touch; prints = the drop between the last two "
             f"columns within 6 levels; own orders {', '.join(f'{s} {k.size_fmt(q)} at {k.price(k.px(o))}' for o, s, q in k.OWN)}")
    if hide:
        out = [n for n in out if not _inside(n, hide)]
    return out


def scrim() -> Node:
    k.fallback("scrim")
    return rect("CMP-043 backdrop scrim", k.WIN_W, k.WIN_H, k.APP, {"opacity": k.SCRIM}, x=0, y=0)


def dialog_window(fid: str, d: Dlg) -> Node:
    """A SCR-051 frame: SCR-050 behind (what the card leaves visible), the scrim, the card, the frame's markers."""
    kids = [*backdrop(hide=(DLG_X, DLG_Y, DLG_W, DLG_H), env=d.env), scrim(), card(d), *d.extra]
    return k.window(fid, kids)


# --- SCR-153: the depth-shed row (§11) in the banner slot, SCR-050 under it
def shed_row(state: str, *, frm: int = k.DEFAULT_TIER, to: int = 50) -> Node:
    """CMP-092 `info` (E15-D12's dress): color.status.info.subtle, the info glyph color.status.info.strong, the message
    type.ui.body color.text.primary, the still-works line type.ui.caption color.text.secondary; not dismissible while
    the shed holds. shed: W-22, W-23, W-24 and the W-25 pin button; pinned: W-26 alone (no pin button), focused."""
    tw, plain = k.WIN_W - 2 * 16 - 16 - 12, 0
    if state == "shed":
        pin = button(k.W("W-25"), name="CMP-001 secondary · pin (W-25)")
        tw -= round(k.est_width(pin)) + 12
        words = vbox("message", [text("W-22", k.W("W-22", **{"from": frm, "to": to}), k.BODY, k.TEXT_1, w=tw),
                                 text("W-23", k.W("W-23"), k.CAPTION, k.TEXT_2, w=tw),
                                 text("W-24", k.W("W-24", **{"from": frm}), k.CAPTION, k.TEXT_2, w=tw)],
                     {"gap": k.STACK_XS}, w=tw)
        plain = math.ceil(k.est_height(words))
        # whole-px texts: the three lines take 2 px more than the plain estimate (SHEET-FIX 09); the row keeps the
        # plain height, so the SCR-050 header under it does not move, by taking the 2 px from its bottom padding
        words["h"] = k.est_drawn_height(words)
        kids = [icon("glyph", "info", k.INFO_STRONG, k.ICON), words, pin]
    else:
        msg = text("W-26", k.W("W-26", **{"from": frm}), k.BODY, k.TEXT_1, w=tw - 16)
        words = ring(vbox("message (tabindex=-1)", [msg], {}, w=tw - 8, h=math.ceil(k.est_height(msg))))
        kids = [icon("glyph", "info", k.INFO_STRONG, k.ICON), words]
    grown = state == "shed" and words["h"] > plain
    pads = {"padT": k.INSET_MD, "padB": k.INSET_SM} if grown else {"padY": k.INSET_MD}
    n = hbox(f"CMP-092 info row · depth shed ({state})", kids,
             {"gap": k.INSET_MD, "padX": k.INSET_LG, **pads, "fill": k.INFO_SUBTLE, "align": "start"},
             w=k.WIN_W, x=0, y=0, note="banner slot, after E15-D12's rows; the banner's persistent role=\"status\" "
                                        "carries the announcement (C-11)")
    n["h"] = 2 * k.PX[k.INSET_MD] + plain if grown else math.ceil(k.est_height(n))
    return n


def shed_window(fid: str, state: str) -> Node:
    """SCR-153 frames: the banner slot (the shed row, or none once restored) over SCR-050 at compact."""
    if state == "restored":
        kids = [*backdrop(k.DEFAULT_TIER, depth_focus=True),
                announce(k.W("W-27", **{"from": k.DEFAULT_TIER}), how="polite, once (the banner's role=\"status\")",
                         dialog=False)]
    else:
        row = shed_row(state)
        kids = [row, *backdrop(50 if state == "shed" else k.DEFAULT_TIER, y0=row["h"],
                               notice=k.W("W-21") if state == "shed" else None, pinned=state == "pinned"),
                announce(k.W("W-22", **{"from": k.DEFAULT_TIER, "to": 50}) if state == "shed"
                         else k.W("W-26", **{"from": k.DEFAULT_TIER}),
                         how="polite, once (the banner's role=\"status\")", dialog=False)]
    return k.window(fid, kids)


def run(nn: int, built: list[tuple[Node, tuple[str, list[str]]]], cols: int, board_lines: Iterable[str] = ()) -> None:
    """The generators' last step: the twin's live check, then k.build (validator exit 0, .md, packed)."""
    b = k.BOARDS[nn]
    if b.twin:
        k.live(f"light twin: after the dark export, switch to the light theme (wait as the sheets README says) and export "
               f"the same board as {b.export_light}")
    k.build(nn, [x[0] for x in built], [x[1] for x in built], cols, board_lines=board_lines)
    print("ok", b.sheet)


def under_tile(n: Node, *, legend_h: int = 0) -> Node:
    """Place a board marker under the tile (and the legend) in the window."""
    return dict(n, x=DLG_X + TILE_X, y=DLG_Y + BODY_Y + PAD + TILE_H + 12 + (legend_h + 12 if legend_h else 0))
