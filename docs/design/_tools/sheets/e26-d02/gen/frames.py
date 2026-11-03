"""E26-D02 frame builders: the SCR-097 replay page (§3 anatomy; §4 chrome; §5 transport; §6 scrubber; §7 states;
§8 paper; §9 panels) and every §16 frame by its id. Every drawn string is the spec's (k.S checks it verbatim) or is
noted as a copy gap with its source; every number is derived from the kit's synthetic world (seed 509)."""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e26d02kit as k  # noqa: E402
from e26d02kit import (S, SL, L, Node, box, ellipse, hbox, icon, rect, text, vbox)  # noqa: E402

TOP_H, HEAD_H, STATUS_H = 48, 32, 24  # TopBar (placeholder), header strip (§11 compact 32), StatusBar (placeholder)
CTRL = 24  # compact control and row height (§11)
TR_PAD, TR_GAP = 8, 4  # transport padding and row gap (§11 compact)
ROW_TRACK = 40
FRAME_IN = 4  # the replay frame: 4 px inset (§4, §11)
CHIP_H = 20


# --- small pieces
def gap_text(name: str, chars: str, src: str, typo: str = k.CAPTION, color: str = k.TEXT_1, **kw: Any) -> Node:
    """A string the spec does not word: drawn and noted with its source."""
    k.copy_gap(f'"{chars}": {src}')
    return text(name, chars, typo, color, **kw)


def spacer(name: str, w: float, h: int = 1) -> Node:
    return rect(name, max(0, round(w)), h)


def dashes(name: str, x: int, y: int, length: int, color: str, *, vertical: bool = False, dash: int = 4) -> Node:
    k.fallback("dash")
    kids, i, p = [], 0, 0
    while p < length:
        d = min(dash, length - p)
        kids.append(rect(f"dash {i:02d}", 1 if vertical else d, d if vertical else 1, color,
                         x=0 if vertical else p, y=p if vertical else 0))
        i, p = i + 1, p + 2 * dash
    return box(name, kids, w=1 if vertical else length, h=length if vertical else 1, x=x, y=y)


def hatch_strip(name: str, w: int, h: int = 6, x: int = 0, y: int = 0) -> Node:
    """§11's hatch: 45° strokes, 2 px, at a 6 px pitch, in color.neutral.default, as 2 × 2 steps (FALLBACKS hatch)."""
    k.fallback("hatch")
    kids: list[Node] = []
    for row in range(0, h, 2):
        for s0 in range(-h, w + h, 6):
            x0 = s0 + (h - 2 - row)
            if 0 <= x0 <= w - 2:
                kids.append(rect(f"step {len(kids):03d}", 2, 2, k.NEUTRAL, x=x0, y=row))
    return box(name, kids, {"clip": True}, w=w, h=h, x=x, y=y)


def glyph_replay(size: str = k.ICON) -> Node:
    k.fallback("replay-glyph")
    return icon("icon∕replay (stand-in)", "refresh", k.TEXT_1, size)


def lock(name: str = "CMP-019 lock") -> Node:
    """The T2 lock (CMP-019, decorative=false, name "Not available"), color.text.tertiary (§5.3 G-T2.2)."""
    return icon(name, "locked", k.TEXT_3, k.ICON_SM, note='CMP-019 Icon "lock", accessible name "Not available"')


def ring(n: Node, radius: str = k.R_CONTROL, name: str = "focus-ring") -> Node:
    """CMP-039: a 2 px color.focus.ring, offset 2 (§11), as a wrapper padded 4 around the control."""
    w = round(k.est_width(n)) + 8
    return box(name, [dict(n, x=4, y=4)], {"radius": radius, "stroke": k.RING, "strokeWidth": k.FOCUS_W,
                                           "strokeAlign": "inner"}, w=w, h=round(k.est_height(n)) + 8,
               note="focus-visible (CMP-039)")


def divider(name: str = "group divider") -> Node:
    """§11: 1 × 16, color.border.default."""
    return rect(name, 1, 16, k.BORDER)


# live-check fold: (tray h, moment h) where the estimate cut a text (board 06: the caption wraps to two lines and
# "cancelled" ended 4 px below the moment; board 09: "reason" measured 19 px)
TRAY_MEASURED_H = {"landed and cancelled": (192, 131), "the 25× reason": (65, 19)}
_TRAY_EST_H: dict[str, int] = {}  # the estimate a measured tray replaced: the tray row keeps its drawn y (page())


def board_marker(name: str, caption: str, kids: list[Node], *, w: int, h: int | None = None) -> Node:
    """A 'board marker · tray' box (§16 readings): a moment of the state at full scale, never product UI."""
    k.fallback("tray")
    cap = text("tray caption", caption, k.LABEL, k.TEXT_2, w=w - 24)
    body = vbox("moment", kids, {"gap": k.STACK_SM}, w=w - 24)
    body["h"] = round(k.est_height(body))
    hh = h if h is not None else round(k.est_height(cap) + k.est_height(body) + 8 + 24)
    if name in TRAY_MEASURED_H:  # the live check's measured tray and moment heights (build-notes "Live-check fold")
        _TRAY_EST_H[f"board marker · tray · {name}"] = hh
        hh, body["h"] = TRAY_MEASURED_H[name]
    return vbox(f"board marker · tray · {name}", [cap, body],
                {"gap": k.STACK_SM, "pad": k.INSET_MD, "fill": k.CANVAS, "stroke": k.BORDER_STRONG,
                 "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CARD}, w=w, h=hh,
                note="board marker: a moment of this state at full scale, not product UI (§16 readings)")


def hidden(chars: str, *, w: int = 360, name: str = "visually hidden (drawn for the board)") -> Node:
    k.fallback("hidden")
    k.copy_gap('"visually hidden": the hidden-string marker label (kit form, board marker)')
    return vbox(name, [text("marker", "visually hidden", k.CAPTION, k.TEXT_3),
                       text("words", chars, k.CAPTION, k.TEXT_2, w=w - 16)],
                {"gap": k.STACK_XS, "pad": k.INSET_SM, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                 "strokeAlign": "inner", "radius": k.R_CONTROL, "fill": k.SUNKEN}, w=w,
                note="board marker: not on screen in the product")


def order_marker(n: int, x: int, y: int) -> Node:
    k.fallback("badge")
    return hbox(f"focus order marker {n:02d}", [text("number", str(n), k.CAPTION, k.TEXT_ON_ACTION)],
                {"fill": k.RING, "radius": k.R_BADGE, "justify": "center"}, w=20, h=20, x=x, y=y,
                note="board marker, not product UI")


# --- controls (CMP-002 icon buttons, CMP-001 buttons, the T2 anatomy of §5.3, busy)
GLYPHS = {"restart": "|<<", "back": "<", "fwd": ">", "leave": ">>|"}
GLYPH_NAMES = {"restart": "|<< restart", "back": "< step back", "fwd": "> step forward"}


def icon_btn(key: str, *, t2: str | None = None, focused: bool = False) -> Node:
    """CMP-002 icon-only, 24 × 24 (§11). T2 (§5.3, 2b): color.surface.raised + 1 px color.border.default, the glyph
    and the CMP-019 lock badge in color.text.tertiary; the description visually hidden (aria-describedby)."""
    k.fallback("glyphs")
    g = S(GLYPHS[key])
    gw = k.text_w(g, k.NUM)
    kids = [text("glyph", g, k.NUM, k.TEXT_3 if t2 else k.TEXT_1, x=round((24 - gw) / 2), y=4)]
    o: dict[str, Any] = {"fill": k.RAISED if t2 else k.ACTION_SECONDARY, "radius": k.R_CONTROL}
    if t2:
        o.update({"stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"})
        kids.append(dict(lock("CMP-019 lock badge (2b)"), x=13, y=-1))
    b = box(f"CMP-002 {GLYPH_NAMES[key]}" + (" · T2 2b" if t2 else ""), kids, o, w=24, h=24,
            note=(f"T2 2b: aria-disabled=\"true\", aria-describedby → \"{t2}\"" if t2 else None))
    return ring(b) if focused else b


def t2_label(label: str, name: str, *, w_extra: int = 0) -> Node:
    """§5.3 2a: the lock leading the full label, both color.text.tertiary, on color.surface.raised with a 1 px
    color.border.default hairline (Play trades color.action.primary.default for it)."""
    lw = round(k.text_w(label, k.BODY_STRONG))
    return hbox(name, [lock(), text("label", label, k.BODY_STRONG, k.TEXT_3)],
                {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                 "strokeAlign": "inner", "radius": k.R_CONTROL, "justify": "center"},
                w=12 + 4 + lw + 16 + 2 + w_extra, h=CTRL, note='T2 2a: aria-disabled="true", reason linked')


def reason(chars: str, name: str = "T2 reason", w: int | None = None) -> Node:
    return text(name, chars, k.CAPTION, k.TEXT_2, **({"w": w} if w else {}))


def play_btn(word: str = "Play", *, busy: bool = False, t2: str | None = None, focused: bool = False,
             with_reason: bool = True) -> Node:
    """`Play` / `Pause` / `Restart` / `Cancel seek`: CMP-001 primary, 64 × 24 with its word (§11). Busy: CMP-001's
    loading state, the spinner at the label's width, aria-busy (§5.3). T2: 2a with the reason beside it."""
    S(word)
    if t2:
        b = t2_label(word, f"CMP-001 {word} · T2 2a")
        out = hbox(f"{word} · T2 with reason", [b, reason(t2)], {"gap": k.INSET_SM}, h=CTRL) if with_reason else b
        return ring(out) if focused else out
    lw = round(k.text_w(word, k.BODY_STRONG))
    w = max(64, lw + 24)
    if busy:
        k.fallback("spinner")
        kids = [ellipse("spinner", 12, 12, {"stroke": k.TEXT_ON_ACTION, "strokeWidth": k.THICK,
                                            "strokeAlign": "inner"})]
        note = f'busy (CMP-001 loading): accessible name "{word}", aria-busy="true"; not T2 (§5.3)'
    else:
        kids, note = [text("label", word, k.BODY_STRONG, k.TEXT_ON_ACTION)], None
    b = hbox(f"CMP-001 {word}" + (" · busy" if busy else ""), kids,
             {"fill": k.ACTION_PRIMARY, "radius": k.R_CONTROL, "justify": "center"}, w=w, h=CTRL, note=note)
    return ring(b) if focused else b


def button(label: str, *, kind: str = "secondary", t2: str | None = None, focused: bool = False,
           with_reason: bool = True, name: str | None = None) -> Node:
    """CMP-001 secondary (or primary) with its words; T2 2a: lock + label tertiary and the reason beside it."""
    nm = name or f"CMP-001 {label}"
    if t2:
        b = t2_label(label, nm + " · T2 2a")
        out = hbox(nm + " · T2 with reason", [b, reason(t2)], {"gap": k.INSET_SM}, h=CTRL) if with_reason else b
        return ring(out) if focused else out
    fill, col = (k.ACTION_PRIMARY, k.TEXT_ON_ACTION) if kind == "primary" else (k.ACTION_SECONDARY, k.TEXT_1)
    b = hbox(nm, [text("label", label, k.BODY_STRONG, col)],
             {"fill": fill, "padX": k.BUTTON_PADX, "radius": k.R_CONTROL, "justify": "center"},
             w=round(k.text_w(label, k.BODY_STRONG)) + 2 * k.PX[k.BUTTON_PADX] + 2, h=CTRL)
    return ring(b) if focused else b


def leave_btn(*, focused: bool = False, exit_glyph: bool = False) -> Node:
    """`>>|` Leave replay: the glyph and its words, after a divider; T1 in every leg (navigation, §5.3)."""
    words = S("Leave replay")
    g = ">>|"
    w = round(k.text_w(g, k.NUM) + k.text_w(words, k.BODY_STRONG)) + 24 + 6
    b = hbox("CMP-001 >>| Leave replay", [text("glyph", g, k.NUM, k.TEXT_1), text("label", words, k.BODY_STRONG,
                                                                                   k.TEXT_1)],
             {"gap": k.INSET_XS, "padX": k.BUTTON_PADX, "fill": k.ACTION_SECONDARY, "radius": k.R_CONTROL,
              "justify": "center"}, w=w, h=CTRL, note="opens the R confirm (CMP-044, D-17); T1 in every leg")
    b = ring(b) if focused else b
    if not exit_glyph:
        return b
    k.fallback("exit-glyph")
    door = box("exit glyph", [rect("door", 12, 14, None, {"stroke": k.TEXT_1, "strokeWidth": k.HAIR,
                                                          "strokeAlign": "inner"}, x=0, y=1),
                              icon("arrow", "chevron-right", k.TEXT_1, k.ICON_SM, x=8, y=2)], w=20, h=16)
    cmp = hbox("board marker · exit glyph beside >>| (board 17, D-6)",
               [door, gap_text("words", "exit glyph, for comparison (D-6)", "board 17's comparison (spec L"
                               f"{L('an exit glyph beside')}, §16); a board marker", k.CAPTION, k.TEXT_2)],
               {"gap": k.INSET_XS, "padX": k.INSET_SM, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                "strokeAlign": "inner", "radius": k.R_CONTROL}, h=CTRL)
    return hbox("leave and the exit glyph", [cmp, b], {"gap": k.INSET_SM}, h=round(k.est_height(b)))


def step_unit(*, unit: str = "Bar", t2: str | None = None, focused: bool = False) -> Node:
    """The Bar / Tick step-unit switch beside < > (D-6): two segments, the chosen one selected (fill, border, no
    primary blue, D-7). T2 at an ended session (§5.1): lock + both labels tertiary on the raised fill."""
    segs = []
    for u in (S("Bar"), S("Tick")):
        sel = (u == unit) and not t2
        o: dict[str, Any] = {"padX": k.INSET_SM, "justify": "center", "radius": k.R_CONTROL}
        if u == unit:
            o.update({"stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR, "strokeAlign": "inner"})
            if sel:
                o["fill"] = k.SELECTED
        segs.append(hbox(f"segment {u}" + (" · selected" if u == unit else ""),
                         [text("label", u, k.LABEL, k.TEXT_3 if t2 else k.TEXT_1)], o,
                         w=max(32, round(k.text_w(u, k.LABEL)) + 16), h=CTRL))
    kids = ([lock()] if t2 else []) + segs
    b = hbox("step unit Bar∕Tick" + (" · T2 2a" if t2 else ""), kids,
             {"gap": k.INSET_XS, "fill": k.RAISED if t2 else None, "padX": k.INSET_XS if t2 else None, "stroke": k.BORDER if t2 else None,
              "strokeWidth": k.HAIR if t2 else None, "strokeAlign": "inner" if t2 else None,
              "radius": k.R_CONTROL}, h=CTRL)
    b["o"] = {kk: v for kk, v in b["o"].items() if v is not None}
    return ring(b) if focused else b


PRESETS = tuple(S("0.5 · 1 · 2 · 4 · 10 · 25 · 100").split(" · "))


def presets(*, selected: str = "4", t2_above: float | None = None, t2_all: bool = False,
            focused: bool = False) -> Node:
    """CMP-171's seven presets as one single-select row (D-7): selected = color.surface.selected + 1 px
    color.border.strong + check (size.icon.sm); a T2 preset keeps its radio, label tertiary, and a selected T2 preset
    drops the fill, keeping the check and the strong edge (§5.3). t2_above: presets above it are T2; t2_all: all."""
    segs = []
    for p in PRESETS:
        is_t2 = t2_all or (t2_above is not None and Decimal(p) > Decimal(str(t2_above)))
        sel = p == selected
        kids = []
        if sel:
            kids.append(icon("check", "check", k.TEXT_3 if is_t2 else k.TEXT_1, k.ICON_SM))
        kids.append(text("label", p, k.NUM_SM, k.TEXT_3 if is_t2 else k.TEXT_1))
        o: dict[str, Any] = {"gap": k.INSET_XS, "padX": k.INSET_SM, "justify": "center", "radius": k.R_CONTROL}
        if sel:
            o.update({"stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR, "strokeAlign": "inner"})
            if not is_t2:
                o["fill"] = k.SELECTED
        wd = round(k.text_w(p, k.NUM_SM)) + 16 + (16 if sel else 0)
        segs.append(hbox(f"radio {p}" + (" · selected" if sel else "") + (" · T2" if is_t2 else ""), kids, o,
                         w=max(32, wd), h=CTRL))
    b = hbox("CMP-171 presets (radiogroup \"Playback speed\")", segs, {"gap": k.INSET_XS}, h=CTRL)
    return ring(b) if focused else b


def custom_field(*, value: str | None = None, t2: str | None = None, focused: bool = False) -> Node:
    """`Custom…` (56 wide compact, §11); T2 2a when gated (the whole transport at an ended session)."""
    lab = S("Custom…")
    if t2:
        b = t2_label(lab, "Custom… · T2 2a")
        return ring(b) if focused else b
    kids = [text("label", value or lab, k.NUM_SM if value else k.LABEL, k.TEXT_2)]
    b = hbox("Custom… field", kids, {"padX": k.INSET_SM, "fill": k.SUNKEN, "stroke": k.BORDER,
                                     "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL},
             w=max(56, round(k.text_w(kids[0]["chars"], kids[0]["typo"])) + 18), h=CTRL)
    return ring(b) if focused else b


def readout(chars: str, *, warn: bool = False) -> Node:
    """§5.2's readout: type.num.sm color.text.secondary; the warning form on color.status.warning.subtle with the
    .strong glyph (§11)."""
    if not warn:
        return text("readout", chars, k.NUM_SM, k.TEXT_2)
    return hbox("readout · warning", [icon("glyph", "warning", k.WARN_STRONG, k.ICON_SM),
                                      text("words", chars, k.NUM_SM, k.TEXT_1)],
                {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.WARN_SUBTLE, "radius": k.R_CONTROL}, h=20)


def notice(chars: str, *, tone: str = "info", name: str = "CMP-028 notice", role: str = "", w: int | None = None,
           actions: Iterable[Node] = ()) -> Node:
    """CMP-028: info (color.status.info.subtle + .strong glyph) or warning / danger; text color.text.primary."""
    fill, gl, gc = {"info": (k.INFO_SUBTLE, "info", k.INFO_STRONG), "warning": (k.WARN_SUBTLE, "warning",
                                                                             k.WARN_STRONG),
                    "danger": (k.DANGER_SUBTLE, "danger", k.DANGER_STRONG)}[tone]
    actions = list(actions)
    words = text("words", chars, k.BODY, k.TEXT_1)
    h = CTRL + 4
    if w:
        room = w - 2 * 8 - 16 - 8 * (1 + len(actions)) - sum(k.est_width(a) for a in actions)
        if k.text_w(chars, k.BODY) > room:
            words = text("words", chars, k.BODY, k.TEXT_1, w=round(room))
            h = max(h, math.ceil((k.est_height(words) + 8) / 4) * 4)
    kids = [icon("glyph", gl, gc, k.ICON), words, *actions]
    return hbox(f"{name} · {tone}", kids, {"gap": k.INSET_SM, "padX": k.INSET_SM, "fill": fill,
                                          "radius": k.R_CONTROL}, h=h, **({"w": w} if w else {}),
                note=role or None)


# --- the track (CMP-170 in context, §6.1-§6.2, §11): one rule for every frame, from the kit's world
def tx(t: datetime, tw: int) -> int:
    return round((t - k.W_FROM) / (k.W_TO - k.W_FROM) * tw)


def segments() -> list[tuple[datetime, datetime, str]]:
    """The window's coverage spans in order, from k.recorded's boundaries (§6.1 classes)."""
    cuts = sorted({k.W_FROM, k.HISTORY_START, k.GAP_FROM, k.GAP_TO, k.PARTIAL_FROM, k.W_TO})
    return [(a, b, k.recorded(a)) for a, b in zip(cuts, cuts[1:])]


def thumb(x: int, y: int, *, focused: bool = False, t2: bool = False, name: str = "thumb") -> Node:
    """§6.2: a 16 px color.text.primary disc in a 2 px color.surface.raised halo (§12.2: the disc directly on the
    fill is below 3:1); the focus ring outside the halo (§11)."""
    kids = [ellipse("halo", 20, 20, {"fill": k.RAISED}, x=2, y=2),
            ellipse("disc", 16, 16, {"fill": k.TEXT_1}, x=4, y=4)]
    if focused:
        kids.insert(0, ellipse("focus ring", 24, 24, {"stroke": k.RING, "strokeWidth": k.FOCUS_W,
                                                       "strokeAlign": "inner"}, x=0, y=0))
    return box(name + (" · T2 (takes <'s reason)" if t2 else ""), kids, w=24, h=24, x=x - 12, y=y - 12,
               note=('role="slider" "Replay position"' + ("; T2: aria-describedby → replay.window_start" if t2
                                                          else "")))


def track(tw: int, thumb_t: datetime | None, *, focused: bool = False, t2: bool = False, labels: bool = True,
          extra: Iterable[Node] = (), bar: int = 6) -> Node:
    """The coverage track: groove color.surface.sunken (radius.pill), full = full-height color.neutral.default,
    partial = half height, no data (gap, not recorded) = the hatch between 1 px dashed color.text.tertiary edges,
    the history-start tick; the thumb at thumb_t; the labels inside the row (§3 track row 40)."""
    y0 = 8
    kids: list[Node] = [rect("groove", tw, bar, k.SUNKEN, {"radius": k.R_PILL}, x=0, y=y0)]
    for i, (a, b, cls) in enumerate(segments(), 1):
        xa, xb = tx(a, tw), tx(b, tw)
        if cls == "full":
            kids.append(rect(f"span {i} · recorded", xb - xa, bar, k.NEUTRAL, x=xa, y=y0))
        elif cls == "partial":
            kids.append(rect(f"span {i} · partial (half height)", xb - xa, bar // 2, k.NEUTRAL, x=xa,
                             y=y0 + bar - bar // 2))
        else:
            kids.append(hatch_strip(f"span {i} · no data ({cls}) · hatch", xb - xa, bar, x=xa, y=y0))
            kids.append(dashes(f"span {i} · edge left", xa, y0, bar, k.TEXT_3, vertical=True))
            kids.append(dashes(f"span {i} · edge right", xb - 1, y0, bar, k.TEXT_3, vertical=True))
    kids.append(rect("history start tick", 2, 14, k.TEXT_2, x=tx(k.HISTORY_START, tw) - 1, y=y0 - 4))
    if labels:
        for nm, t, chars in (("label · history start", k.HISTORY_START, S(f"Recorded from {k.hms(k.HISTORY_START)}")),
                             ("label · gap", k.GAP_FROM, S(f"{k.hm(k.GAP_FROM)} no data")),
                             ("label · partial", k.PARTIAL_FROM, S(f"partial after {k.hm(k.PARTIAL_FROM)}"))):
            kids.append(text(nm, chars, k.CAPTION, k.TEXT_3, x=min(tx(t, tw), tw - round(k.text_w(chars, k.CAPTION))),
                             y=24))
    kids += list(extra)
    o: dict[str, Any] = {}
    if thumb_t is not None:
        x = tx(thumb_t, tw)
        kids.append(thumb(x, y0 + bar // 2, focused=focused, t2=t2))
        if x < 12 or x > tw - 12:  # an end thumb: no clip, so the disc and its halo stay whole (boards lens #5)
            o["clip"] = False
    return box("CMP-170 coverage track", kids, o, w=tw, h=ROW_TRACK,
               note="the track is DOM, not canvas (§12.1); classes per §6.1")


def checkbox(label: str, *, on: bool, t2: str | None = None, focused: bool = False, name: str | None = None,
             with_reason: bool = True) -> Node:
    if t2:
        mark = [icon("check (on)", "check", k.TEXT_3, k.ICON_SM)] if on else []
        b = hbox((name or label) + " · T2 2a", [lock(), *mark, text("label", label, k.BODY, k.TEXT_3),
                                                *([reason(t2)] if with_reason else [])],
                 {"gap": k.INSET_XS, "padX": k.INSET_XS, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                  "strokeAlign": "inner", "radius": k.R_CONTROL}, h=CTRL,
                 note='T2 2a: aria-disabled="true", the reason linked')
        return ring(b) if focused else b
    boxk = box("box", [icon("check", "check", k.TEXT_ON_ACTION, k.ICON_SM, x=1, y=1)] if on else [],
               {"fill": k.ACTION_PRIMARY if on else k.SUNKEN, "stroke": None if on else k.BORDER_STRONG,
                "strokeWidth": None if on else k.HAIR, "radius": k.R_CONTROL}, w=14, h=14)
    boxk["o"] = {kk: v for kk, v in boxk["o"].items() if v is not None}
    b = hbox(name or label, [boxk, text("label", label, k.BODY, k.TEXT_1)], {"gap": k.INSET_SM}, h=CTRL,
             note=f"checkbox, {'checked' if on else 'unchecked'}")
    return ring(b) if focused else b


# --- the transport region (§3: controls · track · options; §5.3's one-line notice above the controls row)
@dataclass
class Tr:
    play: str = "Pause"
    play_busy: bool = False
    play_t2: str | None = None
    t2: dict[str, str] = field(default_factory=dict)  # restart / back / fwd -> reason (2b)
    unit: str = "Bar"
    unit_t2: str | None = None
    state_line: str = ""
    selected: str = "4"
    t2_above: float | None = None
    t2_all: bool = False
    presets_reason: str | None = None
    custom: str | None = None
    custom_t2: str | None = None
    readout: str = "4×"
    readout_warn: bool = False
    thumb: datetime | None = None
    thumb_t2: bool = False
    goto: str | None = None
    goto_t2: str | None = None
    paper: str = "on"  # on | off
    paper_label: str = ""
    paper_t2: str | None = None
    rt_t2: str | None = None
    expiry: str | None = None
    notice: Node | None = None
    callout: Node | None = None
    focus: frozenset[str] = frozenset()
    exit_glyph: bool = False
    track_extra: list[Node] = field(default_factory=list)
    no_window: bool = False  # R-170 without a session: the bare groove, no labels, no coverage line
    state_extra: list[Node] = field(default_factory=list)  # nodes on the state line (buffering `Cancel`)
    rt: bool = False  # Allow real-time panels on (frame 15)
    copy_reason: bool = True  # False under a whole-transport notice: worded controls show no second copy (G-T2.5)


def _row(name: str, parts: list[Node], w: int, h: int = CTRL, gap: str = k.INSET_SM) -> Node:
    """A row of parts with ONE spacer (the part named 'spacer') taking the rest of w."""
    fixed = sum(k.est_width(p) for p in parts if p["name"] != "spacer") + k.PX[gap] * (len(parts) - 1)
    if fixed > w:
        raise ValueError(f"{name}: parts need {fixed:.0f} px > {w}")
    out = [spacer("spacer", w - fixed) if p["name"] == "spacer" else p for p in parts]
    o = {"gap": gap, "align": "center"}
    return box(name, out, {"dir": "row", **o}, w=w, h=h)


def controls_row(tr: Tr, w: int) -> Node:
    f = tr.focus
    left = [icon_btn("restart", t2=tr.t2.get("restart"), focused="restart" in f),
            icon_btn("back", t2=tr.t2.get("back"), focused="back" in f),
            play_btn(tr.play, busy=tr.play_busy, t2=tr.play_t2, focused="play" in f, with_reason=tr.copy_reason),
            icon_btn("fwd", t2=tr.t2.get("fwd"), focused="fwd" in f),
            step_unit(unit=tr.unit, t2=tr.unit_t2, focused="unit" in f)]
    cluster = hbox("cluster", left, {"gap": k.INSET_XS}, h=round(max(k.est_height(x) for x in left)))
    state = text("state line", tr.state_line, k.BODY, k.TEXT_1) if tr.state_line else spacer("state line (empty)", 1)
    if tr.state_extra:
        state = hbox("state line and its action", [state, *tr.state_extra], {"gap": k.INSET_SM}, h=CTRL)
    speed = hbox("speed", [presets(selected=tr.selected, t2_above=tr.t2_above, t2_all=tr.t2_all,
                                   focused="presets" in f),
                           custom_field(value=tr.custom, t2=tr.custom_t2, focused="custom" in f),
                           readout(tr.readout, warn=tr.readout_warn)], {"gap": k.INSET_SM},
                 h=round(max(CTRL, 24 + 8 * ("presets" in f or "custom" in f))))
    parts = [cluster, divider(), state, spacer("spacer", 0), speed, divider("group divider · leave"),
             leave_btn(focused="leave" in f, exit_glyph=tr.exit_glyph)]
    return _row("controls row", parts, w, h=round(max(k.est_height(p) for p in parts)), gap=k.INSET_LG)


def track_row(tr: Tr, w: int) -> Node:
    start = text("start label", k.hm(k.W_FROM), k.NUM_XS, k.TEXT_3)
    end = text("end label", k.hm(k.W_TO), k.NUM_XS, k.TEXT_3)
    go_lab = S("Go to")
    go_val = tr.goto or k.hms(tr.thumb or k.PLAYHEAD)
    go = hbox("Go to (time field)", [text("label", go_lab, k.LABEL, k.TEXT_2),
                                     text("value", go_val, k.NUM_SM, k.TEXT_1)],
              {"gap": k.INSET_SM, "padX": k.INSET_SM, "fill": k.SUNKEN, "stroke": k.BORDER,
               "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL}, h=CTRL,
              note="the track row's time field itself (§3, §16 readings): hh:mm:ss UTC; Enter seeks")
    go_w = k.est_width(go)  # the T1 field's width: the track's share is the same in every frame
    if tr.goto_t2:
        # §5.3 2a, the control whole: lock + label + its time value, all color.text.tertiary, at the T1 field's
        # width so the track (and the thumb) keep frame 04's geometry (boards lens #4); the value at num.xs to fit
        gw = round(k.est_width(go))
        kids_ = [lock(), text("label", go_lab, k.LABEL, k.TEXT_3), text("value", go_val, k.NUM_XS, k.TEXT_3)]
        need = 2 * k.PX[k.INSET_XS] + sum(k.est_width(c) for c in kids_) + 2 * k.PX[k.INSET_XS]
        if need > gw:
            raise ValueError(f"Go to T2: {need:.1f} px > the T1 field's {gw}")
        go = hbox("Go to · T2 2a", kids_, {"gap": k.INSET_XS, "padX": k.INSET_XS, "fill": k.RAISED,
                                           "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                                           "radius": k.R_CONTROL}, w=gw, h=CTRL,
                  note='T2 2a: aria-disabled="true", reason linked; the field keeps its value (§3, §5.3)')
    elif "goto" in tr.focus:
        go = ring(go)
    fixed = k.est_width(start) + k.est_width(end) + (go_w if tr.goto_t2 else k.est_width(go)) + 3 * k.PX[k.INSET_MD]
    tw = int(w - fixed)
    if tr.no_window:
        tk = box("CMP-170 coverage track (no window)", [rect("groove", tw, 6, k.SUNKEN, {"radius": k.R_PILL}, x=0,
                                                             y=8)], w=tw, h=ROW_TRACK,
                 note="R-170 without a session: no window, so no classes, labels or thumb (kit reading)")
        start, end = spacer("start label (none)", k.est_width(start), 12), spacer("end label (none)",
                                                                                  k.est_width(end), 12)
    else:
        tk = track(tw, tr.thumb, focused="thumb" in tr.focus, t2=tr.thumb_t2, extra=tr.track_extra)
    return box("track row", [start, tk, end, go],
               {"dir": "row", "gap": k.INSET_MD, "align": "start"}, w=w, h=ROW_TRACK)


def options_row(tr: Tr, w: int) -> Node:
    cov = text("coverage line", S(f"Coverage: 1 gap · partial after {k.hm(k.PARTIAL_FROM)}"), k.CAPTION, k.TEXT_2)
    det = button(S("Details"), focused="details" in tr.focus, name="CMP-001 Details (T1 opener)")
    pf = checkbox(tr.paper_label or S(f"Paper fills · {k.PAPER}"), on=tr.paper == "on", t2=tr.paper_t2,
                  focused="paper" in tr.focus, name="Paper fills", with_reason=tr.copy_reason)
    rt = checkbox(S("Allow real-time panels"), on=tr.rt, t2=tr.rt_t2, focused="rt" in tr.focus,
                  name="Allow real-time panels", with_reason=tr.copy_reason)
    parts = ([] if tr.no_window else [cov, det]) + [pf, rt, spacer("spacer", 0)]
    if tr.expiry:
        parts.append(text("expiry text", tr.expiry, k.CAPTION, k.TEXT_2))
    return _row("options row", parts, w, h=round(max(k.est_height(p) for p in parts)), gap=k.INSET_XL)


def transport(tr: Tr, w: int) -> Node:
    """The transport region: color.surface.raised, top rule 1 px color.border.default, padding 8, rows 24 · 40 · 24,
    row gap 4 (§11 compact); a whole-transport notice or a gap callout above the controls row."""
    iw = w - 2 * TR_PAD
    rows = [r for r in (tr.notice, tr.callout) if r]
    ctrl = controls_row(tr, iw)
    rows += [ctrl]
    if tr.presets_reason:
        x_speed = iw - sum(k.est_width(c) for c in ctrl["kids"][-3:]) - 2 * 16
        rows.append(hbox("presets reason row", [spacer("indent", x_speed, 1),
                                                reason(tr.presets_reason, "presets T2 reason (one line under the "
                                                                          "group)")], h=16))
    rows += [track_row(tr, iw), options_row(tr, iw)]
    rows = [dict(r, w=iw) if r.get("name", "").startswith("CMP-028") else r for r in rows]
    h = round(2 * TR_PAD + sum(k.est_height(r) for r in rows) + TR_GAP * (len(rows) - 1))
    body = vbox("rows", rows, {"gap": k.STACK_XS}, w=iw, h=h - 2 * TR_PAD, x=TR_PAD, y=TR_PAD)
    return box("transport (region \"Replay transport\")", [rect("top rule", w, 1, k.BORDER, x=0, y=0), body],
               {"fill": k.RAISED}, w=w, h=h, note='region "Replay transport", Ctrl+\\ and "Skip to transport"')


# --- the chrome above the dock: TopBar (placeholder + the CMP-074 band position), header strip (D-5), StatusBar
def placeholder(name: str, w: int, h: int = 12) -> Node:
    k.fallback("chrome")
    return rect(f"placeholder · {name}", w, h, k.HOVER, {"radius": k.R_CONTROL})


def band(account: str) -> Node:
    """CMP-074 band (§4 table, D-4): `DEMO` with a paper account (and on the live DEMO terminal); `REPLAY · no account
    attached`, text-first, no hue, without one."""
    if account == "none":
        words = S("REPLAY · no account attached")
        return hbox("CMP-074 band · no account", [text("words", words, k.LABEL, k.TEXT_1)],
                    {"padX": k.INSET_SM, "stroke": k.TEXT_3, "strokeWidth": k.THICK, "strokeAlign": "inner",
                     "radius": k.R_CONTROL}, h=CTRL, note="text-first, no hue (D01 G13)")
    return hbox("CMP-074 band · DEMO", [ellipse("dot", 8, 8, {"stroke": k.ENV_DEMO, "strokeWidth": k.THICK,
                                                              "strokeAlign": "inner"}),
                                        text("words", S("DEMO"), k.LABEL, k.TEXT_1)],
                {"gap": k.INSET_XS, "padX": k.INSET_SM, "stroke": k.ENV_DEMO, "strokeWidth": k.THICK,
                 "strokeAlign": "inner", "radius": k.R_CONTROL}, h=CTRL)


def topbar(w: int, account: str) -> Node:
    left = hbox("left", [placeholder("wordmark", 88), band(account), placeholder("workspace switcher", 136)],
                {"gap": k.INSET_MD}, h=TOP_H)
    right = hbox("right", [placeholder("health chips", 160), placeholder("search", 16, 16),
                           placeholder("user menu", 72)], {"gap": k.INSET_MD}, h=TOP_H)
    return hbox("TopBar (placeholder; band position is §4's)", [left, spacer("spacer", w - 32 - k.est_width(left) -
                                                                             k.est_width(right)), right,
                                                               rect("divider", w, 1, k.BORDER_SUBTLE, x=0,
                                                                    y=TOP_H - 1, abs=True)],
                {"padX": k.INSET_LG, "fill": k.APP}, w=w, h=TOP_H,
                note="E10's TopBar, not this spec's: placeholders, except the CMP-074 band (D-4)")


def statusbar(w: int, y: int) -> Node:
    return hbox("StatusBar (placeholder)", [placeholder("connection chip", 120), spacer("spacer", w - 32 - 120 - 40),
                                            placeholder("version", 40),
                                            rect("divider", w, 1, k.BORDER_SUBTLE, x=0, y=0, abs=True)],
                {"padX": k.INSET_LG, "fill": k.APP}, w=w, h=STATUS_H, x=0, y=y)


@dataclass
class Head:
    t: datetime | None = None  # the header's position (None: no session)
    speed: str = "4×"
    kind: str = ""  # SIMULATED FILLS · Paper 1 | No account attached | ...
    seek_to: datetime | None = None
    focused: bool = False


def header(hd: Head, w: int) -> Node:
    """D-5: REPLAY with its glyph · symbol · the 27-character type.num.md timestamp · speed · session kind ·
    `Sessions`; color.surface.raised, bottom rule, inline padding 8, group gap 16 (§11)."""
    if hd.t is None:
        kids: list[Node] = [glyph_replay(), text("REPLAY · no session", S("REPLAY · no session"), k.HEADING_SM,
                                                 k.TEXT_1)]
    else:
        kids = [glyph_replay(), text("REPLAY", S("REPLAY"), k.HEADING_SM, k.TEXT_1),
                text("symbol", k.SYMBOL, k.BODY_STRONG, k.TEXT_1),
                text("timestamp (27 ch, type.num.md)", k.stamp(hd.t), k.NUM_MD, k.TEXT_1),
                text("speed", hd.speed, k.NUM, k.TEXT_1)]
        if hd.seek_to:
            kids.append(text("seek target", S(f"→ {k.hms(hd.seek_to)}"), k.NUM, k.TEXT_2))
        if hd.kind:
            kids.append(text("session kind", hd.kind, k.LABEL, k.TEXT_1))
    ses = button(S("Sessions"), focused=hd.focused, name="CMP-001 Sessions (T1 opener)")
    row = hbox("groups", kids, {"gap": k.SPACE_4}, h=CTRL)
    return hbox("header strip (region \"Replay session\")",
                [row, spacer("spacer", w - 16 - k.est_width(row) - k.est_width(ses)), ses,
                 rect("bottom rule", w, 1, k.BORDER, x=0, y=HEAD_H - 1, abs=True)],
                {"padX": k.INSET_SM, "fill": k.RAISED}, w=w, h=HEAD_H,
                note='region "Replay session"; the clock is role="timer" "Replay clock", aria-live off (D-19)')


# --- panels (§4 chrome on every replaying panel; §9)
def env_badge(account: str) -> Node:
    """CMP-075 (§4 table): `DEMO` with the outline-dot glyph and a 2 px color.env.demo border; `NO ACCOUNT` with no
    glyph and a 2 px color.text.tertiary border."""
    if account == "none":
        return hbox("CMP-075 env badge · NO ACCOUNT", [text("words", S("NO ACCOUNT"), k.CAPTION, k.TEXT_1)],
                    {"padX": k.INSET_SM, "stroke": k.TEXT_3, "strokeWidth": k.THICK, "strokeAlign": "inner",
                     "radius": k.R_BADGE}, h=18,
                    note='name "No account attached — replay of recorded data; nothing can be placed"')
    return hbox("CMP-075 env badge · DEMO", [ellipse("outline dot", 6, 6, {"stroke": k.ENV_DEMO, "strokeWidth": k.HAIR,
                                                                        "strokeAlign": "inner"}),
                                             text("words", S("DEMO"), k.CAPTION, k.TEXT_1)],
                {"gap": k.INSET_XS, "padX": k.INSET_SM, "stroke": k.ENV_DEMO, "strokeWidth": k.THICK,
                 "strokeAlign": "inner", "radius": k.R_BADGE}, h=18)


def chip(t: datetime, *, with_time: bool = True) -> Node:
    """D-2: `REPLAY 13 Sep 13:38:04`, 20 high, padding 8, 2 px color.replay.border, color.surface.raised,
    type.ui.caption + type.num.sm, radius.badge outside; fused to the frame at the right end (§11)."""
    S(f"REPLAY {k.chip_date(k.PLAYHEAD)} {k.hms(k.PLAYHEAD)}")  # the D-2 form, checked once
    kids = [glyph_replay(k.ICON_SM), text("word", "REPLAY", k.CAPTION, k.TEXT_1),
            text("date and time", f"{k.chip_date(t)} {k.hms(t)}" if with_time else k.chip_date(t), k.NUM_SM,
                 k.TEXT_1)]
    w = round(12 + 4 + k.text_w("REPLAY", k.CAPTION) + 4 + k.est_width(kids[2]) + 16 + 4)
    return hbox("REPLAY chip", kids, {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.RAISED, "stroke": k.REPLAY,
                                      "strokeWidth": k.THICK, "strokeAlign": "inner", "radius": k.R_BADGE},
                w=w, h=CHIP_H, note="the chip shows its panel's data time, never a target (D-3)")


def replay_frame(w: int, h: int) -> list[Node]:
    """§4: the 4 px inset frame in color.replay.border (PROPOSED local token, RULED BQ-10), never dashed or reduced."""
    c = k.REPLAY
    return [rect("replay frame · top", w, FRAME_IN, c, x=0, y=0), rect("replay frame · bottom", w, FRAME_IN, c, x=0,
                                                                         y=h - FRAME_IN),
            rect("replay frame · left", FRAME_IN, h, c, x=0, y=0), rect("replay frame · right", FRAME_IN, h, c,
                                                                         x=w - FRAME_IN, y=0)]


@dataclass
class P:
    """One dock panel: title words, size and position, content builder, the chrome it carries."""
    title: str
    x: int
    y: int
    w: int
    h: int
    content: Callable[[int, int], list[Node]]
    replay: bool = True
    account: str = "paper"
    chip_t: datetime | None = None
    head_extra: list[Node] = field(default_factory=list)
    realtime: bool = False
    overlay: list[Node] = field(default_factory=list)
    name: str = ""
    chip_short: bool = False  # the chip without its time (no frame shown yet)


HEAD_ROW = 28


def panel(p: P) -> Node:
    inner_w, inner_h = p.w - 2 * FRAME_IN, p.h - HEAD_ROW - FRAME_IN
    kids: list[Node] = []
    ch = chip(p.chip_t, with_time=not p.chip_short) if (p.replay and p.chip_t) else None
    head = [text("title", p.title, k.BODY_STRONG, k.TEXT_1), env_badge(p.account) if not p.realtime else None,
            *p.head_extra]
    head = [x for x in head if x]
    hw = p.w - 2 * FRAME_IN - 16 - (round(k.est_width(ch)) + 8 if ch else 0)
    kids.append(hbox("panel header", head, {"gap": k.INSET_SM}, w=hw, h=24, x=FRAME_IN + 8, y=FRAME_IN))
    body = box("content", p.content(inner_w, inner_h), {"clip": True}, w=inner_w, h=inner_h, x=FRAME_IN, y=HEAD_ROW)
    kids.append(body)
    kids += p.overlay
    if p.replay:
        kids += replay_frame(p.w, p.h)
        if ch:
            kids.append(dict(ch, x=p.w - round(k.est_width(ch)), y=0))
    else:
        kids.append(rect("panel edge (no frame: not replaying)", p.w, 1, k.BORDER, x=0, y=0))
    nm = p.name or f"panel · {p.title}" + (" (replaying)" if p.replay else "")
    return box(nm, kids, {"fill": k.CANVAS, "clip": True}, w=p.w, h=p.h, x=p.x, y=p.y,
               note=("region; name ends \"replay of 13 September 2026\" (D-2, §12.1)" if p.replay else None))


# --- panel contents (synthetic world, derived)
AXIS_W, AXIS_H = 64, 20
CHART_SPAN = timedelta(minutes=60)


def chart_range(t: datetime) -> tuple[datetime, datetime]:
    """60 one-minute slots: the playhead's minute 33 slots in, never before the history start's first full minute."""
    first = (k.HISTORY_START + k.STEP_1M).replace(second=0, microsecond=0)
    a = max(first, t.replace(second=0, microsecond=0) - timedelta(minutes=33))
    return a, a + CHART_SPAN


def chart(t: datetime, *, gap_band: bool = False, dim_future: bool = True,
          series: Callable[[datetime], list[k.Bar]] | None = None, fmt: Callable[[Decimal], str] | None = None,
          step_: Decimal | None = None) -> Callable[[int, int], list[Node]]:
    """Candles (color.candle.*) of the bars as the clock shows them at t, the dashed virtual-now line and the future
    dimmed by one color.surface.app quad at opacity.scrim (E11-D02 §7.2), the time and price axes; gap_band adds
    the chart's no-data band (the hatch, one meaning, D-12)."""
    def build(w: int, h: int) -> list[Node]:
        pw, ph = w - AXIS_W, h - AXIS_H
        a, b = chart_range(t)
        bars = [x for x in (series or k.bars_until)(t) if a <= x.t < b]
        lo, hi = min(x.l for x in bars), max(x.h for x in bars)
        pad = (hi - lo) * Decimal("0.12")
        lo, hi = lo - pad, hi + pad
        slot = pw / 60

        def py(p: Decimal) -> int:
            return round(float((hi - p) / (hi - lo)) * (ph - 1))

        def px(tt: datetime) -> int:
            return round((tt - a) / CHART_SPAN * pw)

        kids: list[Node] = []
        step = step_ or (Decimal(10) if hi - lo < 80 else Decimal(20))
        lv = (lo / step).to_integral_value(rounding="ROUND_CEILING") * step
        i = 0
        while lv <= hi:
            y = py(lv)
            if 8 <= y <= ph - 8:
                kids.append(rect(f"grid {i:02d}", pw, 1, k.GRID, x=0, y=y))
                kids.append(text(f"price label {i:02d}", (fmt or k.price)(lv), k.NUM_XS, k.AXIS_TEXT, x=pw + 6,
                                 y=y - 6))
                i += 1
            lv += step
        for j, x_ in enumerate(bars):
            x0 = px(x_.t)
            bw = max(1, round(slot * 0.7))
            kids.append(rect(f"wick {j:03d}", 1, max(1, py(x_.l) - py(x_.h)), k.WICK, x=x0 + round(slot / 2), y=py(x_.h)))
            top, bot = min(py(x_.o), py(x_.c)), max(py(x_.o), py(x_.c))
            kids.append(rect(f"body {j:03d}", bw, max(1, bot - top), k.CANDLE_UP if x_.c >= x_.o else k.CANDLE_DOWN,
                             x=x0 + round((slot - bw) / 2), y=top))
        tm = a + timedelta(minutes=(10 - a.minute % 10) % 10)
        while tm < b:
            kids.append(text(f"time label {k.hm(tm)}", k.hm(tm), k.NUM_XS, k.AXIS_TEXT, x=px(tm) - 14, y=ph + 4))
            tm += timedelta(minutes=10)
        if gap_band:
            ga, gb = px(k.GAP_FROM), px(k.GAP_TO)
            kids += [hatch_strip("gap band · hatch top", gb - ga, 12, x=ga, y=0),
                     hatch_strip("gap band · hatch foot", gb - ga, 12, x=ga, y=ph - 12),
                     dashes("gap band · edge left", ga, 0, ph, k.TEXT_3, vertical=True),
                     dashes("gap band · edge right", gb - 1, 0, ph, k.TEXT_3, vertical=True),
                     text("gap band · words", "no data", k.CAPTION, k.TEXT_2, x=ga + 4, y=20)]
            S("no data — recording was interrupted (connection lost)")
        vx = px(t)
        if not dim_future:
            return kids
        if dim_future:
            kids.append(rect("future dimmed (opacity.scrim)", pw - vx, ph, None, {"fill": k.APP, "opacity": k.SCRIM},
                             x=vx, y=0))
            k.fallback("scrim")
        kids.append(dashes("virtual now (dashed)", vx, 0, ph, k.TEXT_2, vertical=True))
        k.derive(f"chart at {k.hms_ms(t)}: slots {k.hm(a)}–{k.hm(b)} (60 × 1 min), {len(bars)} bars from the seeded "
                 f"prints, price axis {k.price(lo)}–{k.price(hi)} at {step} steps, virtual now at x {vx}")
        return kids
    return build


def chart_head(t: datetime, *, words: bool = True, live: bool = False) -> list[Node]:
    """§9 / D-15: the chart's status row shows `last` (from trades) and `mark —`; live (frame 18) it shows a mark."""
    if live:
        mk = k.last_at(t) - k.TICK
        k.derive(f"live chart status row at {k.hms(t)}: mark {k.price(mk)} = last {k.price(k.last_at(t))} less one tick "
                 f"({k.TICK}) of the synthetic world (D-15's `mark —` is replay-only)")
        return [text("last", f"last {k.price(k.last_at(t))}", k.NUM_SM, k.TEXT_1),
                text("mark", f"mark {k.price(mk)}", k.NUM_SM, k.TEXT_2)]
    k.copy_gap(f'"last {k.price(k.last_at(t))}" · "mark —": §3 sketch L{SL("last 64,011.0  mark —")}, D-15 '
               f"L{SL('`mark —` with that reason')} (last derived from the seeded prints at {k.hms(t)})")
    return [text("last", f"last {k.price(k.last_at(t))}", k.NUM_SM, k.TEXT_1),
            text("mark", "mark —", k.NUM_SM, k.TEXT_2)]


def dom(t: datetime) -> Callable[[int, int], list[Node]]:
    """A 200-level recorded book (seeded), ladder rows of 24 px: bid size · price · ask size, asks above."""
    def build(w: int, h: int) -> list[Node]:
        n = (h - 8) // 24
        bids, asks = k.book_at(t, n)
        cw = w // 3
        rows: list[tuple[str, str, str]] = []
        for p, q in reversed(asks[: n // 2]):
            rows.append(("", k.price(p), k.qty(q)))
        for p, q in bids[: n - n // 2]:
            rows.append((k.qty(q), k.price(p), ""))
        kids: list[Node] = []
        for i, (bq, pr, aq) in enumerate(rows):
            cells = []
            for j, (v, col) in enumerate(((bq, k.BUY), (pr, k.TEXT_1), (aq, k.SELL))):
                c = hbox(["bid", "price", "ask"][j], [text("value", v, k.NUM_SM, col)] if v else [],
                         {"padX": k.INSET_SM, "justify": "end" if j != 1 else "center"}, w=cw, h=24)
                cells.append(c)
            kids.append(hbox(f"row {i:02d}", cells, {"fill": k.RAISED if i % 2 else k.CANVAS}, w=3 * cw, h=24,
                             x=0, y=4 + 24 * i))
        k.derive(f"DOM at {k.hms(t)}: best bid {k.price(bids[0][0])}, best ask {k.price(asks[0][0])} (one tick over "
                 f"the last print), sizes seeded {k.SEED}")
        return kids
    return build


def tape(t: datetime) -> Callable[[int, int], list[Node]]:
    """The tape's newest prints first: time · price · size · side word (colour never the only signal)."""
    def build(w: int, h: int) -> list[Node]:
        n = (h - 8) // 24
        ps = list(reversed(k.prints_until(t, n)))
        k.copy_gap('"Buy" / "Sell" (the taker side word on tape rows): E22-D02\'s side words, not this spec\'s')
        widths = (120, 120, 100, 80)
        kids = []
        for i, x_ in enumerate(ps):
            vals = (k.hms(x_.t), k.price(x_.p), k.qty(x_.q), x_.side)
            cols = (k.TEXT_2, k.TEXT_1, k.TEXT_1, k.BUY if x_.side == "Buy" else k.SELL)
            cells = [hbox(nm, [text("value", v, k.NUM_SM, c)], {"padX": k.INSET_SM, "justify": "end" if j in (1, 2)
                                                                  else "start"}, w=cw, h=24)
                     for j, (nm, v, c, cw) in enumerate(zip(("time", "price", "size", "side"), vals, cols, widths))]
            kids.append(hbox(f"row {i:02d}", cells, {"fill": k.RAISED if i % 2 else k.CANVAS}, w=sum(widths), h=24,
                             x=0, y=4 + 24 * i))
        return kids
    return build


def centred(chars: str, *, typo: str = k.BODY, color: str = k.TEXT_2) -> Callable[[int, int], list[Node]]:
    def build(w: int, h: int) -> list[Node]:
        tw = min(w - 48, 520)
        return [text("panel text", chars, typo, color, w=tw, x=(w - tw) // 2, y=h // 2 - 20, align="center")]
    return build


ARMED = S("ARMED (REPLAY · DEMO)")
SUBMIT = "Simulated Buy / Long 0.250 BTC"


def ticket(mode: str = "armed", *, banner: str | None = None, tone: str = "info") -> Callable[[int, int], list[Node]]:
    """The replay ticket (E30-D02's, §8, D-10): `SIMULATED · Paper 1` in place of the account selector, the arm pill
    `ARMED (REPLAY · DEMO)`, `Simulated` the submit's first word. mode 'armed' | 'gated' (the banner slot carries the
    reason; side, quantity and submit T2 2a) | 'none' (read-only, no account: `replay.no_account`)."""
    def build(w: int, h: int) -> list[Node]:
        k.copy_gap(f'"{SUBMIT}": §3 sketch L{SL("Simulated  Buy / Long 0.250 BTC")} (its double space as one)')
        kids: list[Node] = []
        y = 8
        if mode == "live":
            kids.append(hbox("ticket head", [placeholder("account selector (E30-D02)", 180, 16)], {"gap": k.INSET_MD},
                             w=w - 24, h=24, x=12, y=y))
            y += 32
            kids.append(hbox("side and quantity", [button(S("Buy / Long"), name="side Buy ∕ Long"),
                                                   hbox("quantity", [text("label", "0.250 BTC", k.NUM_SM, k.TEXT_1)],
                                                        {"padX": k.INSET_SM, "fill": k.SUNKEN, "stroke": k.BORDER,
                                                         "strokeWidth": k.HAIR, "strokeAlign": "inner",
                                                         "radius": k.R_CONTROL}, w=160, h=24)],
                             {"gap": k.INSET_SM}, h=24, x=12, y=y))
            k.copy_gap('"Buy / Long 0.250 BTC" (the live ticket\'s submit): the replay submit without `Simulated` '
                       "(D-10), E30-D02's live form")
            kids.append(dict(button("Buy / Long 0.250 BTC", kind="primary", name="submit"), x=12, y=y + 32))
            return kids
        if mode != "none":
            head = hbox("ticket head", [text("account", S(f"SIMULATED · {k.PAPER}"), k.BODY_STRONG, k.TEXT_1),
                                        hbox("CMP-229 arm pill", [text("words", ARMED, k.CAPTION, k.TEXT_1)],
                                             {"padX": k.INSET_SM, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                                              "strokeAlign": "inner", "radius": k.R_BADGE}, h=20)],
                        {"gap": k.INSET_MD}, w=w - 24, h=24, x=12, y=y)
            kids.append(head)
            y += 32
        if banner:
            bn = notice(banner, tone=tone, name="CMP-028 E30-D02 banner slot", w=w - 24)
            kids.append(dict(bn, x=12, y=y))
            y += bn["h"] + 12
        gated = mode in ("gated", "none")
        rt = banner or S("No account is attached to this session.")
        side = (button(S("Buy / Long"), t2=rt, with_reason=False, name="side Buy ∕ Long") if gated else
                button(S("Buy / Long"), name="side Buy ∕ Long"))
        q = hbox("quantity", [text("label", "0.250 BTC", k.NUM_SM, k.TEXT_3 if gated else k.TEXT_1)],
                 {"padX": k.INSET_SM, "fill": k.SUNKEN if not gated else k.RAISED, "stroke": k.BORDER,
                  "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL}, w=160, h=24)
        S("0.250 BTC")
        kids.append(hbox("side and quantity", [side, q], {"gap": k.INSET_SM}, h=24, x=12, y=y))
        y += 32
        sub = (button(SUBMIT, t2=rt, with_reason=False, name="submit") if gated else
               button(SUBMIT, kind="primary", name="submit"))
        kids.append(dict(sub, x=12, y=y))
        return kids
    return build


def ticket_title(account: str) -> str:
    return "Ticket"


def scrim_closed(w: int, h: int, words: str) -> list[Node]:
    """D-20: after `destroyed` the panels freeze under a scrim inside their frames (color.surface.app at
    opacity.scrim, §11) with the closed line."""
    k.fallback("scrim")
    tw = min(w - 48, 420)
    return [rect("scrim (opacity.scrim)", w - 2 * FRAME_IN, h - HEAD_ROW - FRAME_IN, None,
                 {"fill": k.APP, "opacity": k.SCRIM}, x=FRAME_IN, y=HEAD_ROW),
            text("closed line", words, k.BODY_STRONG, k.TEXT_1, w=tw, x=(w - tw) // 2, y=(h + HEAD_ROW) // 2 - 10,
                 align="center")]


def strip(chars: str, w: int, *, tone: str = "warning", y: int = HEAD_ROW) -> Node:
    """E11-D02 §10's strip recipe inside the frame: one line naming the state and its time."""
    return dict(notice(chars, tone=tone, name="strip inside the frame", w=w - 2 * FRAME_IN), x=FRAME_IN, y=y)


# --- the page: TopBar · header strip · dock · transport · StatusBar (§3), absolutely placed in its frame
@dataclass
class Pg:
    account: str = "paper"  # paper | none
    head: Head | None = field(default_factory=Head)  # None: the live terminal (no header strip)
    tr: Tr | None = field(default_factory=Tr)  # None: no transport (the live terminal)
    panels: Callable[[int, int, int], list[P]] | None = None  # (y0, w, h) -> panels in the dock
    dock_words: str | None = None  # a dock without panels: one centred line
    overlay: list[Node] = field(default_factory=list)  # board markers (frame coordinates)
    trays: list[Node] = field(default_factory=list)  # 'board marker · tray' boxes, in a row at the dock's foot
    tray_x: int = 16  # the first tray's x (frame 22: past the ticket, so its T2 submit stays in view)


def page(pg: Pg, w: int, h: int) -> list[Node]:
    kids: list[Node] = [dict(topbar(w, pg.account), x=0, y=0)]
    y = TOP_H
    if pg.head is not None:
        kids.append(dict(header(pg.head, w), x=0, y=y))
        y += HEAD_H
    trn = transport(pg.tr, w) if pg.tr is not None else None
    tr_h = round(k.est_height(trn)) if trn else 0
    dock_h = h - y - tr_h - STATUS_H
    if dock_h < 400:
        raise ValueError(f"dock {dock_h} px: the transport ({tr_h}) leaves too little")
    dk: list[Node] = []
    if pg.panels:
        dk = [panel(p) for p in pg.panels(0, w, dock_h)]
    elif pg.dock_words:
        dk = centred(pg.dock_words, typo=k.BODY_STRONG, color=k.TEXT_2)(w, dock_h)
    kids.append(box("dock", dk, {"fill": k.APP, "clip": True}, w=w, h=dock_h, x=0, y=y,
                    note="the session's dock layout (D-1)"))
    if trn:
        kids.append(dict(trn, x=0, y=y + dock_h))
    kids.append(statusbar(w, h - STATUS_H))
    if pg.trays:
        th = max(_TRAY_EST_H.get(t_["name"], round(k.est_height(t_))) for t_ in pg.trays)
        x = pg.tray_x
        for t_ in pg.trays:
            kids.append(dict(t_, x=x, y=y + dock_h - th - 12))
            x += round(k.est_width(t_)) + 16
        if x > w:
            raise ValueError(f"trays need {x} px > {w}")
    kids += pg.overlay
    return kids


def frame(fid: str, theme: str, kids: list[Node], *, note: str | None = None) -> Node:
    fr = k.FRAMES[fid]
    return box(k.frame_name(fid, theme), kids, {"fill": k.APP, "clip": True}, w=fr.w, h=fr.h,
               note=note or f"§16 frame {fid}: {fr.shows[:120]}")


def dock_layout(t: datetime, account: str, *, ticket_mode: str = "armed", banner: str | None = None,
                tone: str = "info", chip_t: datetime | None = None, gap_band: bool = False,
                overlays: dict[str, list[Node]] | None = None, scrim: str | None = None,
                strip_words: str | None = None, strip_action: Node | None = None, live: bool = False,
                empty: bool = False) -> Callable[[int, int, int], list[P]]:
    """The anatomy's dock (§3, frame 01 without the REAL-TIME watchlist): chart and DOM over ticket and tape."""
    ct = chip_t or t
    ov = overlays or {}

    def build(y0: int, w: int, h: int) -> list[P]:
        g = 8
        top_h = round((h - 3 * g) * 0.62)
        bot_h = h - 3 * g - top_h
        cw = round((w - 3 * g) * 0.64)
        dw = w - 3 * g - cw
        tw = 520
        pw = w - 3 * g - tw
        rep = not live
        acct = "paper" if live else account
        specs = [P("Chart BTCUSDT 1m", g, y0 + g, cw, top_h,
                   chart(t, gap_band=gap_band, dim_future=rep), replay=rep, account=acct, chip_t=ct,
                   head_extra=[] if empty else chart_head(t, live=live)),
                 P("DOM BTCUSDT 200", 2 * g + cw, y0 + g, dw, top_h, dom(t), replay=rep, account=acct, chip_t=ct),
                 P(ticket_title(account), g, y0 + 2 * g + top_h, tw, bot_h,
                   ticket("live" if live else ticket_mode, banner=banner, tone=tone), replay=rep, account=acct,
                   chip_t=ct),
                 P("Tape BTCUSDT", 2 * g + tw, y0 + 2 * g + top_h, pw, bot_h, tape(t), replay=rep, account=acct,
                   chip_t=ct)]
        for s_ in specs:
            if empty:
                s_.content, s_.chip_short, s_.head_extra = (lambda _w, _h: []), True, []
            key = s_.title.split()[0].lower()
            extra = list(ov.get(key, []))
            if scrim:
                extra += scrim_closed(s_.w, s_.h, scrim)
            if strip_words:
                extra.append(strip(strip_words, s_.w, tone="warning"))
                if strip_action is not None and key == "chart":
                    extra.append(dict(strip_action, x=s_.w - FRAME_IN - 8 - round(k.est_width(strip_action)),
                                      y=HEAD_ROW + 2))
            s_.overlay = extra
        k.copy_gap("panel titles \"Chart BTCUSDT 1m\", \"DOM BTCUSDT 200\", \"Ticket\", \"Tape BTCUSDT\": §3 sketch "
                   f"L{SL('chart BTCUSDT 1m')}-L{SL('┏ ticket')} (capitalised; the tape names its symbol)")
        return specs
    return build


# --- positions by estimate (flex rows / columns as cvsheet lays them out), for board markers
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
        for c, (cw, chh) in zip(flow, sizes):
            if d == "row":
                cy = pt + ((h - pt - pb - chh) / 2 if o.get("align") == "center" else 0)
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


# ======================================================================================================================
# the §16 frames. Each builder takes the theme and returns (frame node, annotation lines).
SIM_KIND = S(f"SIMULATED FILLS · {k.PAPER}")
PW = k.DEFAULT_W  # every page is 1920 wide


def playing_line(speed: str = "4") -> str:
    return k.tpl("Playing at 4×", {"4": speed})


def paused_line(t: datetime) -> str:
    return k.tpl("Paused at 13:38:04", {"13:38:04": k.hms(t)})


def tr_playing(t: datetime, **kw: Any) -> Tr:
    return Tr(**{"play": "Pause", "state_line": playing_line(), "thumb": t, **kw})


def tr_paused(t: datetime, **kw: Any) -> Tr:
    return Tr(**{"play": "Play", "state_line": paused_line(t), "thumb": t, **kw})


def tray_w(n: int, w: int = PW) -> int:
    """n trays side by side across the dock's foot (16 px gutters)."""
    return (w - 16 * (n + 1)) // n


def tooltip(chars: str, w: int = 360) -> Node:
    """CMP-016: the echo of a 2b reason on hover and focus (color.surface.overlay)."""
    return vbox("CMP-016 tooltip (the reason's echo)", [text("words", chars, k.CAPTION, k.TEXT_1, w=w - 16)],
                {"pad": k.INSET_SM, "fill": k.OVERLAY, "radius": k.R_CONTROL, "stroke": k.BORDER,
                 "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=w)


def announce(chars: str, *, role: str = "polite", w: int = 360) -> Node:
    return hidden(f"{role}: {chars}", w=w, name=f"announcement ({role}, drawn for the board)")


def anatomy_page(theme: str, *, account: str = "paper", exit_glyph: bool = False, **trkw: Any) -> Pg:
    t = k.PLAYHEAD
    kind = SIM_KIND if account == "paper" else S("No account attached")
    tr = tr_playing(t, exit_glyph=exit_glyph, **trkw)
    if account == "none":
        tr.paper, tr.paper_t2, tr.paper_label = "off", k.why("replay.no_account"), S("Paper fills")
    return Pg(account=account, head=Head(t=t, kind=kind),
              tr=tr, panels=dock_layout(t, account, ticket_mode="armed" if account == "paper" else "none",
                                        banner=None if account == "paper" else k.why("replay.no_account")))


STOPS = ("CMP-001 Sessions (T1 opener)", "panel · Chart", "panel · DOM", "panel · Ticket", "panel · Tape",
         "CMP-002 |<< restart", "CMP-002 < step back", "CMP-001 Pause", "CMP-002 > step forward",
         "step unit Bar∕Tick", "CMP-171 presets", "Custom… field", "CMP-001 >>| Leave replay", "thumb",
         "Go to (time field)", "CMP-001 Details (T1 opener)", "Paper fills", "Allow real-time panels")


def focus_markers(kids: list[Node]) -> list[Node]:
    """B1's 18 stops (§12.1, RULED BQ-14): Sessions, the four replaying panel regions, the 13 transport stops."""
    out = []
    for i, nm in enumerate(STOPS, 1):
        x, y, _w, _h = find(kids, lambda p, n, nm=nm: n["name"].startswith(nm))
        out.append(order_marker(i, max(0, round(x) - 10), round(y) - 10))  # live-check fold: never left of the frame
    return out


def redlines(w: int, h: int, cols: int = 7) -> Node:
    """§11's rows as callouts under the anatomy: element, compact measures, tokens (the tokens cell to its first
    sentence; the full cell is §11)."""
    k.fallback("redline")
    a = L("| Element              | Compact")
    rows = []
    for i in range(a + 2, a + 40):
        ln = k.SPEC_LINES[i - 1]
        if not ln.startswith("|"):
            break
        c = k._cells(ln)
        tok = k.plain(c[3]).split(". ")[0]
        rows.append((i, k.plain(c[0]), k.plain(c[1]), tok))

    cw = (w - 32 - 16 * (cols - 1)) // cols
    boxes = []
    for j, (ln, el, comp, tok) in enumerate(rows):
        boxes.append(vbox(f"redline {j + 1:02d} · {el}", [
            hbox("head", [rect("leader", 16, 1, k.BORDER_STRONG), text("element", f"{el} (§11 L{ln})", k.LABEL,
                                                                        k.TEXT_1)], {"gap": k.INSET_SM}, h=16),
            text("compact", f"compact: {comp}", k.CAPTION, k.TEXT_1, w=cw - 16),
            text("tokens", f"tokens: {tok}", k.CAPTION, k.TEXT_2, w=cw - 16)], {"gap": k.STACK_XS}, w=cw))
    grid = [hbox(f"redline row {r + 1}", boxes[r * cols:(r + 1) * cols], {"gap": k.INSET_LG, "align": "start"},
                 w=w - 32, h=round(max(k.est_height(b) for b in boxes[r * cols:(r + 1) * cols])))
            for r in range(math.ceil(len(boxes) / cols))]
    body = vbox("board marker · §11 redlines", grid, {"gap": k.STACK_SM, "pad": k.INSET_LG, "fill": k.CANVAS},
                w=w, h=h, note="board marker: §11's redlines, compact (comfortable by table)")
    need = k.est_height(dict(body, h=None))
    if need > h:
        raise ValueError(f"redlines need {need:.0f} px > {h}")
    return body


def f01(theme: str) -> tuple[Node, list[str]]:
    pg = anatomy_page(theme, exit_glyph=True)
    kids = page(pg, PW, 1080)
    kids += focus_markers(kids)
    fr = k.FRAMES["01"]
    kids.append(dict(redlines(PW, fr.h - 1080), x=0, y=1080))
    k.live("frame 01: after relayout the §11 redline band (seven callouts a row, estimated 312 of 320 px) ends inside "
           "the frame; if a callout is cut, report it (SHEET-FIX: shorten that tokens cell)")
    k.reading("frame 01 is §3's anatomy playing, without the REAL-TIME watchlist (§3; §16 readings); B1 overlays "
              "board 19's 18 focus stops on it (§12.1 RULED BQ-14): Sessions, the chart, DOM, ticket and tape "
              "regions and the 13 transport stops |<< to Allow real-time panels; no bookmark, gap-callout or More stop")
    k.reading("§11's redlines are drawn as a callout band under the 1920 × 1080 anatomy inside the 1920 × 1400 frame, "
              "each callout naming its element; the tokens cell is cut at its first sentence (the rest stays §11's)")
    return frame("01", theme, kids), [
        f"Anatomy (§3 L{L('## 3. Anatomy')}): playing at 4×, paper fills on, Allow real-time panels off, so no "
        f"REAL-TIME panel; header {k.stamp(k.PLAYHEAD)} (27 ch type.num.md)",
        "Focus order (numbered markers, §12.1): " + " → ".join(f"{i} {n.split(' (')[0]}" for i, n in
                                                               enumerate(STOPS, 1)),
        "Exit glyph beside >>| for comparison (board 17, D-6; §16 not-drawn line)",
        "T2: none on this frame (every leg passes); CMP-079 RbacGate wraps each control (§5.3)"]


def _para(head: str, stop: str) -> str:
    """The plain text of one spec paragraph starting at the line containing head, up to (not incl.) stop."""
    a = L(head)
    b = L(stop, a + 1)
    return k.plain(" ".join(k.SPEC_LINES[a - 1:b - 1])).replace("**", "")


def f19(theme: str) -> tuple[Node, list[str]]:
    fr = k.FRAMES["19"]
    w = fr.w - 48
    a = L("| Key                   | Action")
    rows = []
    for i in range(a + 2, a + 20):
        ln = k.SPEC_LINES[i - 1]
        if not ln.startswith("|"):
            break
        c = [k.plain(x).replace("**", "") for x in k._cells(ln)]
        rows.append({"key": c[0], "action": c[1], "where": c[2], "change": c[4]})
    cols = [k.Col("key", "Key", 150), k.Col("action", "Action", 210), k.Col("where", "Where it applies on /replay", 560),
            k.Col("change", "Change", w - 920)]
    tbl = k.spec_table("SCR-013 Replay group (§10)", cols, rows, cap=f"§10 L{a}: the Replay group for the hotkey "
                       "overlay (SCR-013, CMP-094), each key with where it applies", w_=w)
    space = text("the Space rule", _para("**`Space`:** Space is play/pause", "**The scrub thumb**"), k.BODY, k.TEXT_1,
                 w=w)
    t2rule = text("on a T2 target", _para("**On a T2 target**", "## 11. Redlines"), k.BODY, k.TEXT_1, w=w)
    half = (len(STOPS) + 1) // 2
    listing = []
    for c0 in (0, half):
        items = [hbox(f"stop {i + 1:02d}", [hbox("marker", [text("number", str(i + 1), k.CAPTION, k.TEXT_ON_ACTION)],
                                                 {"fill": k.RING, "radius": k.R_BADGE, "justify": "center"}, w=20,
                                                 h=20),
                                            text("control", STOPS[i].split(" (")[0].replace("panel · ", "region · "),
                                                 k.BODY, k.TEXT_1)], {"gap": k.INSET_SM}, h=22)
                 for i in range(c0, min(c0 + half, len(STOPS)))]
        listing.append(vbox(f"stops {c0 + 1}-{min(c0 + half, len(STOPS))}", items, {"gap": k.STACK_XS}, w=360))
    order = vbox("focus order (18 stops, §12.1)", [
        text("caption", f"Focus order on frame 01 (§12.1 L{L('**B1')}): 18 stops; no bookmark (CC-15), gap-callout "
                        "(CC-2) or More stop", k.LABEL, k.TEXT_2, w=740),
        hbox("columns", listing, {"gap": k.INSET_LG, "align": "start"}, h=round(k.est_height(listing[0])))],
        {"gap": k.STACK_SM}, w=740)
    k.fallback("badge")
    end_key = k.why("replay.end_of_range")
    inset = board_marker("a key on a T2 target", "A key on a T2 target (§5.3 Keys, §10): `>` at the end of range, "
                         "focused; → changes nothing and re-shows the reason once",
                         [hbox("specimen", [icon_btn("fwd", t2=end_key, focused=True), tooltip(end_key, 300)],
                               {"gap": k.INSET_SM, "align": "start"}, h=40),
                          text("rule", S("change nothing and re-show the reason once, with one polite announcement"),
                               k.CAPTION, k.TEXT_2, w=640),
                          announce(end_key, w=640)], w=700)
    k.copy_gap('the tray captions (board markers) restate the spec\'s rule for the drawn moment; no product string')
    body = vbox("keyboard board", [text("title", "SCR-013 · Replay group, the precedence and the focus order",
                                        k.HEADING_MD, k.TEXT_1), tbl, space, t2rule,
                                   hbox("order and inset", [order, inset], {"gap": k.INSET_XL, "align": "start"},
                                        h=round(max(k.est_height(order), k.est_height(inset))))],
                {"gap": k.STACK_LG, "pad": k.INSET_XL, "fill": k.CANVAS}, w=fr.w, h=fr.h, x=0, y=0)
    k.copy_gap('"SCR-013 · Replay group, the precedence and the focus order", the table\'s column labels: board '
               'headings (§10\'s columns)')
    if k.est_height(dict(body, h=None)) > fr.h + 1:
        raise ValueError(f"frame 19 needs {k.est_height(dict(body, h=None)):.0f} px")
    return frame("19", theme, [body]), [
        "The Replay group (§10), the Space rule and the T2-target rule verbatim; C proposed for dom.recentre on "
        "/replay (the Space row's Change cell)",
        "The 18 stops are numbered on frame 01's anatomy (B1 overlay, RULED BQ-14)",
        f"Key on a T2 target: `>` 2b at finished, {end_key!r} echoed by CMP-016 (§5.3 2b)"]


def f04(theme: str) -> tuple[Node, list[str]]:
    kids = page(anatomy_page(theme, exit_glyph=True), PW, 1080)
    return frame("04", theme, kids), [
        f"Playing at 4× with paper fills on; the five carriers that show here: header {SIM_KIND!r}, the ticket's "
        f"{S('SIMULATED · Paper 1')!r} and Simulated submit, the arm pill {ARMED!r} (D-10)",
        "AC 1 stimulus (§14.3): the word, the past date, the 4 px width, the dimmed future and the glyph; the hue "
        "reinforces only",
        "Exit glyph beside >>| for comparison (board 17, D-6)",
        f"Analytics: replay.started fired when the session first reached paused (§13)"]


def f05(theme: str) -> tuple[Node, list[str]]:
    kids = page(anatomy_page(theme, account="none"), PW, 1080)
    k.reading("frame 05's Paper fills switch reads 'Paper fills' alone: no account is attached, so the switch names "
              "none (boards lens #7), off and T2 2a on replay.no_account")
    return frame("05", theme, kids), [
        "No account (D-4): NO ACCOUNT badges (no glyph, 2 px color.text.tertiary), band "
        f"{S('REPLAY · no account attached')!r}, header {S('No account attached')!r}",
        f"Ticket read-only: replay.no_account in E30-D02's banner slot; Paper fills T2 2a on it (§5.1); "
        "T2 = CMP-079 RbacGate + CMP-019 lock",
        "AC 1 stimulus (§14.3)"]


def f18(theme: str) -> tuple[Node, list[str]]:
    t = k.PLAYHEAD
    pg = Pg(account="paper", head=None, tr=None, panels=dock_layout(t, "paper", live=True))
    kids = page(pg, PW, 1080)
    k.reading("frame 18 (the AC 1 control) is the same dock live in DEMO: no header strip, transport, frame or chip, "
              "no dimmed future; the same synthetic prices, so only the replay carriers differ")
    return frame("18", theme, kids), [
        "The live terminal in DEMO with the same layout (AC 1 control, §14.3): band DEMO, DEMO badges, no replay "
        "carrier", "The live ticket's account selector and submit are E30-D02's (placeholders here)"]


def all_t2(why_: str, **kw: Any) -> dict[str, Any]:
    """A whole-transport condition (§5.3 G-T2.5): every write T2 on one notice, no second copy beside a worded
    control; the icon-only glyphs badged (2b)."""
    return {"t2": {"restart": why_, "back": why_, "fwd": why_}, "play_t2": why_, "t2_all": True, "custom_t2": why_,
            "goto_t2": why_, "thumb_t2": True, "copy_reason": False, **kw}


def f02(theme: str) -> tuple[Node, list[str]]:
    ns = k.why("replay.no_session")
    tr = Tr(play="Play", **all_t2(ns, unit_t2=ns, paper_t2=ns, rt_t2=ns), no_window=True,
            notice=notice(ns, name="CMP-028 transport notice (replay.no_session)", role='role="status", once'))
    tw = tray_w(3)
    sent = k.why("rbac.permission")
    viewer = board_marker("a Viewer's configuring", "A Viewer on R-170 (D-26): the sentence form (CMP-026, cta "
                          "omitted) in place of the transport and the panels; SCR-098's Start is E26-D03's",
                          [hbox("sentence form", [icon("glyph", "info", k.INFO_STRONG), text("words", sent, k.BODY,
                                                                                          k.TEXT_1)],
                                {"gap": k.INSET_SM, "padX": k.INSET_SM, "fill": k.RAISED, "radius": k.R_CONTROL},
                                w=tw - 24, h=32)], w=tw)
    rev = board_marker("revived", "Revived (`created` with a window and a cursor): no controls row; `Prepare` "
                       "only, then Leave replay (§7, §16 readings)",
                       [notice(S("Session restarted — prepare to continue at 13:38:04"), name="revived line",
                               w=tw - 24),
                        hbox("actions", [button(S("Prepare"), kind="primary"), leave_btn()], {"gap": k.INSET_SM},
                             h=CTRL), announce(S("Session restarted — prepare to continue at 13:38:04"),
                                               w=tw - 24)], w=tw)
    nf = board_marker("not found", "Not found (R-171, 404): the callout alone, no window or cursor (§7, §16 "
                      "readings); a Viewer's R-171 reads the same",
                      [notice(S("Replay session not found."), name="not found callout", w=tw - 24,
                              actions=[button(S("Choose a window"), name="CMP-001 Choose a window (T1 opener)")]),
                       leave_btn(), announce(S("Replay session not found."), w=tw - 24)], w=tw)
    k.fallback("tray")
    outline = board_marker("SCR-098 open (outline)", "SCR-098 open over R-170 (E26-D03 owns the modal; drawn as "
                           "an outline only)", [rect("outline body", 520, 200, k.SUNKEN,
                                                     {"stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                                                      "strokeAlign": "inner", "radius": k.R_CARD})], w=560)
    pg = Pg(account="paper", head=Head(t=None), tr=tr, dock_words=S("Choose a window to replay"),
            overlay=[dict(outline, x=(PW - 560) // 2, y=TOP_H + HEAD_H + 40)], trays=[viewer, rev, nf])
    kids = page(pg, PW, 1080)
    k.reading("R-170 without a session (configuring): the track row draws the bare groove only (no window, so no "
              "classes, labels, thumb or coverage line); every transport control is T2 on the one replay.no_session "
              "notice, Paper fills and Allow real-time panels included (kit reading: no session holds them)")
    return frame("02", theme, kids), [
        f"Configuring (R-170): header {S('REPLAY · no session')!r}; panels {S('Choose a window to replay')!r}; "
        "SCR-098 open (outline, E26-D03)",
        f"T2: the transport on one CMP-028 info notice replay.no_session ({ns!r}, role status once); icon glyphs 2b "
        "with the lock badge, Play / Custom… / Go to 2a with no second copy (G-T2.5); CMP-079 RbacGate, CMP-019 lock",
        "Trays: a Viewer's sentence form (rbac.permission), revived (Prepare), not found (the callout alone)"]


def f03(theme: str) -> tuple[Node, list[str]]:
    t = k.W_FROM
    win = f"{k.hm(k.W_FROM)}–{k.hm(k.W_TO)} UTC"
    line4 = S(f"Preparing {win} · reading recorded data · 4 s")
    tr = Tr(play="Play", play_busy=True, state_line=line4, thumb=t,
            state_extra=[button(S("Cancel"), name="CMP-001 Cancel (buffering: DELETE)")])
    tw = tray_w(2)
    late = k.tpl("Preparing 13:00–15:00 UTC · reading recorded data · 4 s", {"4 s": "12 s"}) + " " + \
        S("· a day is usually ready within 10 s")
    tray12 = board_marker("the 12 s line", "Buffering at 12 s: from 10 s the line adds its expectation (§7)",
                          [hbox("state line at 12 s", [play_btn("Play", busy=True), text("state line", late, k.BODY,
                                                                                         k.TEXT_1),
                                                        button(S("Cancel"), name="CMP-001 Cancel")],
                                {"gap": k.INSET_LG}, h=CTRL)], w=tw)
    ready = board_marker("ready", "Ready: the announcement, and the focus stays on the control pressed, now Play "
                         "(§12.1)", [announce(S("Replay ready at 13:00:00"), w=tw - 24)], w=tw)
    pg = Pg(account="paper", head=Head(t=t, kind=SIM_KIND), tr=tr, trays=[tray12, ready],
            panels=dock_layout(t, "paper", empty=True))
    kids = page(pg, PW, 1080)
    k.reading("buffering: the panels have no frame of data yet, so each chip shows the word and the date only "
              "(D-2's narrow form keeps the word and the date) and the panels are empty; the header shows the "
              "window start")
    return frame("03", theme, kids), [
        f"Buffering after PREPARE (§7): {line4!r} with `Cancel` (= DELETE; the window kept in SCR-098); Play busy "
        "(CMP-001 loading, aria-busy; busy is not T2, §5.3)",
        "No progress bar: elapsed time is not progress (D-16, CC-9)",
        "Analytics: replay.started fires when it reaches paused (§13)"]


def f06(theme: str) -> tuple[Node, list[str]]:
    t = k.STEPPED_TO
    tr = tr_paused(t)
    tw = tray_w(3)
    sb = k.why("replay.step_bar_time")
    t2tray = board_marker("step by bar on a non-time panel", "Step-bar T2 (2b) while a non-time bar panel "
                          "(E12-D02) has the focus, unit Bar: `>` badged, its reason echoed",
                          [hbox("specimen", [icon_btn("fwd", t2=sb, focused=True), tooltip(sb, tw - 80)],
                                {"gap": k.INSET_SM, "align": "start"}, h=48)], w=tw)
    stepping = board_marker("stepping", "Stepping (D-22): Play busy (aria-busy), every other control held, the "
                            "state line names the wait", [hbox("cluster", [icon_btn("restart"), icon_btn("back"),
                                                                          play_btn("Play", busy=True),
                                                                          icon_btn("fwd"),
                                                                          text("state line", S("Stepping…"), k.BODY,
                                                                               k.TEXT_1)],
                                                               {"gap": k.INSET_XS}, h=CTRL)], w=tw)
    held = board_marker("a preset held for Play", "Paused, a new preset chosen: held and sent with the next play "
                        "(D-7)", [hbox("picker", [presets(selected="10"),
                                                  readout(k.tpl("4× on Play", {"4": "10"}))], {"gap": k.INSET_SM},
                                       h=CTRL)], w=tw)
    pg = Pg(account="paper", head=Head(t=t, kind=SIM_KIND), tr=tr, trays=[t2tray, stepping, held],
            panels=dock_layout(t, "paper"))
    kids = page(pg, PW, 1080)
    kids.append(dict(announce(k.tpl("Stepped one bar to 13:39:00", {}), w=420), x=PW - 440, y=TOP_H + HEAD_H + 40))
    return frame("06", theme, kids), [
        f"Paused after one step-bar forward: {paused_line(t)!r}; announced \"Stepped one bar to {k.hms(t)}\" (§7)",
        "Trays: step-bar T2 2b (replay.step_bar_time, CMP-019 lock badge, CMP-016 echo), stepping (busy, not T2), "
        "a preset held for Play"]


def drag_pill(tw: int, at: datetime, words: list[str]) -> Node:
    """§6.2: the time pill following the pointer, with the class under it (and where the release lands)."""
    lines = [text(f"line {i + 1}", s_, k.NUM_SM if i == 0 else k.CAPTION, k.TEXT_1) for i, s_ in enumerate(words)]
    pw = round(max(k.est_width(x) for x in lines)) + 16
    pill = vbox("drag pill", lines, {"gap": k.STACK_XS, "padX": k.INSET_SM, "padY": k.INSET_XS, "fill": k.OVERLAY,
                                     "radius": k.R_CONTROL, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                     "strokeAlign": "inner"}, w=pw)
    return dict(pill, x=min(max(0, tx(at, tw) - pw // 2), tw - pw), y=0)


def f07(theme: str) -> tuple[Node, list[str]]:
    t, to = k.PLAYHEAD, k.SEEK_TO
    tr = Tr(play="Cancel seek", state_line=S(f"Seeking to {k.hms(to)}…"), thumb=to)
    tw = tray_w(3)
    drag_at = k._t("13:52:30")
    S(f"{k.hms(drag_at)} · no data")
    lands = S(f"lands at {k.hms(k.GAP_TO)}, where recording resumes")
    trk_w = tw - 24
    pill_tr = board_marker("the drag pill", "Dragging (§6.2): nothing is sent until release; a release inside a "
                           "no-data span lands at its end, and the pill says so",
                           [box("track with pill", [dict(track(trk_w, drag_at, focused=True, labels=False), x=0, y=48),
                                                    drag_pill(trk_w, drag_at, [f"{k.hms(drag_at)} · no data", lands])],
                                w=trk_w, h=88)], w=tw)
    rungs = board_marker("the rungs", "The rungs after 1 s and after 2 s (§6.3): the state line names the work; "
                         "over budget it offers Cancel", [
                             text("1-2 s", S("Rebuilding the order book from the nearest recorded snapshot · 1.4 s"),
                                  k.BODY, k.TEXT_1, w=tw - 24),
                             hbox("over 2 s", [text("words", S("Taking longer than the 2 s budget · 2.6 s — cancel to "
                                                             "stay at 13:38:04"), k.BODY, k.TEXT_1),
                                               button(S("Cancel"), name="CMP-001 Cancel (on the line)")],
                                  {"gap": k.INSET_SM}, h=CTRL)], w=tw)
    ends = board_marker("landed and cancelled", "Landed (polite once) and cancelled (§6.3); a second seek is held "
                        "busy and only the latest target is sent (D-16)", [
                            announce(S("At 13:52:04"), w=tw - 24),
                            announce(S("At 13:52:04, playing at 4×"), w=tw - 24),
                            text("cancelled", S("Seek cancelled — still at 13:38:04. Try again."), k.BODY, k.TEXT_1,
                                 w=tw - 24)], w=tw)
    pg = Pg(account="paper", head=Head(t=t, kind=SIM_KIND, seek_to=to), tr=tr, trays=[pill_tr, rungs, ends],
            panels=dock_layout(t, "paper"))
    fr = k.FRAMES["07"]
    kids = page(pg, fr.w, fr.h)
    k.reading("seeking: the thumb stands at the released target while the panels keep their last frame and their "
              "chips keep 13:38:04 (D-3); `Pause` reads `Cancel seek` (§6.3 rung 0.1–1 s)")
    return frame("07", theme, kids), [
        f"Seeking 0.1–1 s (§6.3): {tr.state_line!r}; the header adds → {k.hms(to)}; panels last frame, chips "
        "unchanged (D-3); Cancel seek (Esc on the transport or the thumb)",
        "Busy, not T2 (§5.3): no lock anywhere; never a spinner alone, never staggered panels",
        "AC 4; analytics replay.seek on land, cancel or refusal (§13)"]


def specimen_track(w: int, spans: list[tuple[str, int]], *, tick_at: int | None = None) -> Node:
    """A §6.1 class specimen: spans of (class, width) on the groove."""
    kids: list[Node] = [rect("groove", w, 6, k.SUNKEN, {"radius": k.R_PILL}, x=0, y=8)]
    x = 0
    for i, (cls, sw) in enumerate(spans, 1):
        if cls == "full":
            kids.append(rect(f"span {i} · recorded", sw, 6, k.NEUTRAL, x=x, y=8))
        elif cls == "partial":
            kids.append(rect(f"span {i} · partial", sw, 3, k.NEUTRAL, x=x, y=11))
        elif cls == "hatch":
            kids += [hatch_strip(f"span {i} · hatch", sw, 6, x=x, y=8),
                     dashes(f"span {i} · edge left", x, 8, 6, k.TEXT_3, vertical=True),
                     dashes(f"span {i} · edge right", x + sw - 1, 8, 6, k.TEXT_3, vertical=True)]
        x += sw
    if tick_at is not None:
        kids.append(rect("history start tick", 2, 14, k.TEXT_2, x=tick_at, y=4))
    return box("specimen track", kids, w=w, h=22)


def f16(theme: str) -> tuple[Node, list[str]]:
    fr = k.FRAMES["16"]
    t = k.PLAYHEAD
    w = fr.w - 48
    tr = tr_playing(t, focus=frozenset({"thumb"}))
    trn = transport(tr, fr.w)
    cls_rows = []
    a = L("| Class                 | Rule at an instant")
    for i in range(a + 2, a + 8):
        ln = k.SPEC_LINES[i - 1]
        if not ln.startswith("|"):
            break
        c = [k.plain(x) for x in k._cells(ln)]
        cls_rows.append((i, c[0], c[3]))
    shapes = {"Recorded (full)": [("full", 240)], "Partial (some)": [("partial", 240)],
              "No data: gap": [("full", 80), ("hatch", 80), ("full", 80)],
              "No data: not recorded": [("hatch", 80), ("full", 160)], "Coverage unknown": []}
    rows = []
    for ln, name, words in cls_rows:
        rows.append(hbox(f"class · {name}", [text("class", name, k.LABEL, k.TEXT_1, w=170),
                                             specimen_track(240, shapes[name], tick_at=79 if "not recorded" in name
                                                            else None),
                                             text("text", f"{words} (§6.1 L{ln})", k.CAPTION, k.TEXT_2, w=w - 460)],
                         {"gap": k.INSET_LG}, h=28))
    classes = vbox("the five classes (§6.1)", [text("caption", "Coverage classes: track and text (§6.1, D-12)",
                                                     k.LABEL, k.TEXT_2), *rows], {"gap": k.STACK_XS}, w=w)
    vt = S("13:38:04 UTC, 13 September 2026 — recorded")
    states = []
    for nm, kw in (("rest", {}), ("hover", {"tip": True}), ("focus", {"focused": True}), ("drag", {"drag": True})):
        sw = 230
        kids_ = [dict(track(sw, k._t("13:20:00") if nm != "drag" else k._t("13:53:00"), focused=kw.get("focused",
                                                                                                         False),
                            labels=False), x=0, y=64)]
        if kw.get("tip"):
            kids_.append(dict(tooltip(vt, 220), x=4, y=0))
        if kw.get("drag"):
            kids_.append(drag_pill(sw, k._t("13:53:00"), [k.tpl("13:52:30 · no data", {"13:52:30": "13:53:00"})]))
        states.append(vbox(f"thumb · {nm}", [text("state", nm, k.LABEL, k.TEXT_2),
                                             box("specimen", kids_, w=sw, h=104)], {"gap": k.STACK_XS}, w=sw))
    k.derive("thumb specimens: rest, hover and focus at 13:20:00, drag over the gap at 13:53:00 (inside "
             f"{k.hms(k.GAP_FROM)}–{k.hms(k.GAP_TO)}, so 'no data')")
    thumbs = hbox("thumb states (§6.2)", states, {"gap": k.INSET_LG, "align": "start"}, h=130)
    values = vbox("value texts", [hidden(f'aria-valuetext "{vt}"', w=420),
                                  hidden(S("coverage unknown before 24 Jul 2026") + " — the horizon: 90 days before "
                                         "the report's generated_at (§6.1, CC-20)", w=420)], {"gap": k.STACK_SM},
                  w=420)
    bm_w = 520
    bt = specimen_track(bm_w - 24, [("full", bm_w - 24)])
    t1 = k.BOOKMARK_1
    t2_ = k._t("14:20:00")
    k.derive(f"bookmark 2 at {k.hms(t2_)}: a kit-chosen second time (the sketch numbers ▲1 and ▲2, §3)")
    marks = []
    for n_, tt in ((1, t1), (2, t2_)):
        x = tx(tt, bm_w - 24)
        marks += [rect(f"marker {n_}", 8, 6, k.TEXT_2, x=x - 4, y=0), text(f"ordinal {n_}", str(n_), k.NUM_XS,
                                                                           k.TEXT_2, x=x + 6, y=0)]
    menu = vbox("Bookmarks menu", [text(f"item {i}", s_, k.NUM_SM, k.TEXT_1) for i, s_ in enumerate(
        (S("1 · 13:41:07 · label"), k.tpl("1 · 13:41:07 · label", {"1 ·": "2 ·", "13:41:07": k.hms(t2_)})), 1)],
        {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.OVERLAY, "radius": k.R_CONTROL}, w=240)
    inset = board_marker("bookmarks (needs CC-15)", S("needs CC-15 — not rendered until it lands"),
                         [box("markers on the track", [*marks, dict(bt, x=0, y=8)], w=bm_w - 24, h=32),
                          hbox("menu and the rules", [menu, text("rules", S("+N") + " when closer than 24 px; "
                                                                  + S("unavailable — the data was removed by the "
                                                                      "retention policy"), k.CAPTION, k.TEXT_2,
                                                                  w=bm_w - 24 - 256)],
                               {"gap": k.INSET_LG, "align": "start"}, h=60)], w=bm_w)
    lower = hbox("thumbs, values and the CC-15 inset", [vbox("left", [thumbs, values], {"gap": k.STACK_MD},
                                                              w=w - bm_w - 24), inset],
                 {"gap": k.INSET_XL, "align": "start"}, w=w,
                 h=round(max(130 + 12 + k.est_height(values), k.est_height(inset))) + 16)  # D1: +16, measured
    body = vbox("specimens", [classes, lower], {"gap": k.STACK_LG}, w=w, x=24, y=round(k.est_height(trn)) + 24)
    kids = [dict(trn, x=0, y=0), body]
    if k.est_height(body) + k.est_height(trn) + 24 > fr.h:
        raise ValueError(f"frame 16 overflows: {k.est_height(body) + k.est_height(trn):.0f}")
    k.reading("frame 16 draws CMP-170 in context as the 1600 px transport (playing, the thumb focused) over its "
              "specimens; the bookmark markers and menu only in the side inset stamped 'needs CC-15 — not rendered "
              "until it lands' (RULED BQ-9), never on a playing frame")
    return frame("16", theme, kids), [
        "AC 3: the five classes (full solid, half height, the hatch for gap and not recorded, the bare groove), "
        f"the history start {S('Recorded from 13:04:12')!r}, the horizon, the coverage line (§6.1, D-12)",
        "Thumb rest / hover (CMP-016 value text) / focus (ring outside the halo) / drag (the pill) (§6.2, §11)",
        "Bookmarks: only in the CC-15 inset (BQ-9); B, [ and ] wait for CC-15"]


def stamp_marker(chars: str, x: int, y: int) -> Node:
    """A board marker stamped on the frame's face (§16)."""
    return dict(hbox("board marker · stamp", [icon("glyph", "info", k.TEXT_1, k.ICON_SM),
                                              text("words", chars, k.LABEL, k.TEXT_1)],
                     {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.CANVAS, "stroke": k.BORDER_STRONG,
                      "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL}, h=24,
                     note="board marker, not product UI"), x=x, y=y)


GAP_CAUSE = "recording was interrupted (connection lost)"


def f08(theme: str) -> tuple[Node, list[str]]:
    t = k.GAP_FROM
    rng = f"{k.hms(k.GAP_FROM)}–{k.hms(k.GAP_TO)} UTC"
    stop = S(f"No data {rng} — {GAP_CAUSE}.")
    callout = notice(stop, tone="warning", name="CMP-028 gap callout (role alert, once)",
                     actions=[button(S("Skip gap"), name="CMP-001 Skip gap (a seek)"),
                              button(S("Stop here"), name="CMP-001 Stop here (T1)")])
    tr = tr_paused(t, callout=callout)
    tw = tray_w(2)
    book = S(f"Order book not recorded {rng} — ") + GAP_CAUSE + "."
    skip = S(f"Skipping jumps to {k.hms(k.GAP_TO)}: the tape won't show the trades inside; the chart's bars include "
             "them.")
    k.reading("the book-alone callout is D-13's 'Order book not recorded 13:52:10–13:55:40 UTC — …' with the same "
              "cause words as the no-data callout (the ellipsis stands for E11-D04's cause)")
    alone = board_marker("the book alone", "When only the order book is missing (a Partial span, §6.1): the stream "
                         "first, and what Skip gap leaves off the tape (D-13)",
                         [notice(book, tone="warning", name="gap callout · book alone", w=tw - 24),
                          text("skip line", skip, k.BODY, k.TEXT_1, w=tw - 24),
                          hbox("actions", [button(S("Skip gap")), button(S("Stop here"))], {"gap": k.INSET_SM},
                               h=CTRL)], w=tw)
    skipped = board_marker("the skipped notice", "Under today's shipped skip (X-7) nothing stops: the same range and "
                           "cause as a non-blocking notice; its Stop at gaps is omitted until CC-2",
                           [notice(S(f"Skipped a gap {rng} — {GAP_CAUSE}."), name="skipped notice (polite once)",
                                   w=tw - 24)], w=tw)
    pg = Pg(account="paper", head=Head(t=t, kind=SIM_KIND), tr=tr, trays=[alone, skipped],
            panels=dock_layout(t, "paper", gap_band=True))
    kids = page(pg, PW, 1080)
    kids.append(stamp_marker(S("gap stop needs CC-1/CC-2; today the clock skips (X-7)"), 24, TOP_H + HEAD_H + 48))
    k.reading("frame 08 draws Skip gap and Stop here; Always skip gaps in this session and the notice's Stop at gaps "
              "wait for CC-2 and are not drawn (RULED BQ-8)")
    return frame("08", theme, kids), [
        f"Gap encountered (AC 2, D-13): the callout {stop!r} (CMP-028 warning, assertive once) with Skip gap (a seek) "
        "and Stop here (T1), first in Tab order, never focused on their own; the chart's gap band and the track's "
        "hatch (one meaning: no data)",
        "Stamped 'gap stop needs CC-1/CC-2; today the clock skips (X-7)' (BQ-8)",
        "Analytics: replay.seek kind skip_gap (§13)"]


def f11(theme: str) -> tuple[Node, list[str]]:
    t = k.W_TO
    eor = k.why("replay.end_of_range")
    callout = notice(S(f"End of range — {k.hms(k.W_TO)} UTC"), name="CMP-028 end of range (polite once)",
                     actions=[button(S(f"Restart from {k.hm(k.W_FROM)}")), button(S("Extend window"),
                                                                                  name="CMP-001 Extend window (T1)"),
                              button(S("Results"), name="CMP-001 Results (T1, SCR-099)")])
    tr = Tr(play="Restart", thumb=t, t2={"fwd": eor}, callout=callout)
    tw = tray_w(2)
    echo = board_marker("> at the end of range", "`>` T2 2b on replay.end_of_range, focused: the lock badge and the "
                        "CMP-016 echo of its reason", [hbox("specimen", [icon_btn("fwd", t2=eor, focused=True),
                                                                        tooltip(eor, 360)],
                                                           {"gap": k.INSET_SM, "align": "start"}, h=48)], w=tw)
    quota = board_marker("a refused restart (quota)", "A restart refused by the quota: T4, its own notice (§7)",
                         [notice(S("You have reached your limit of open replay sessions. Close one to continue."),
                                 name="quota refusal (polite once)", w=tw - 24,
                                 actions=[button(S("Sessions"), name="CMP-001 Sessions")])], w=tw)
    pg = Pg(account="paper", head=Head(t=t, kind=SIM_KIND), tr=tr, trays=[echo, quota],
            panels=dock_layout(t, "paper"))
    kids = page(pg, PW, 1080)
    k.reading("end of range: the callout carries Restart from 13:00, Extend window and Results; Leave replay is the "
              "controls row's own (one Leave replay on screen)")
    return frame("11", theme, kids), [
        f"End of range (D-18): the last frame frozen, the chrome kept; Play becomes Restart (T1); `>` T2 2b {eor!r}",
        "Three restart routes kept (|<<, Restart, Restart from 13:00); Loop waits for its contract",
        "T2: CMP-079 RbacGate, CMP-019 lock badge; analytics replay.seek kind restart (§13)"]


def f12(theme: str) -> tuple[Node, list[str]]:
    t = k.CLOSED_AT
    ended = k.why("replay.ended")
    closed = S(f"Replay session closed — data as of {k.hms(t)}")
    resume = button(S(f"Resume at {k.hms(t)}"), kind="primary", name="CMP-001 Resume (T1)")
    tr = Tr(play="Play", thumb=t, **all_t2(ended, unit_t2=ended, paper_t2=ended, rt_t2=ended),
            notice=notice(ended, name="CMP-028 transport notice (replay.ended, no live role)", actions=[resume]))
    tw = 1340
    warn = board_marker("the 9:58 warning", "Before it happens (D-20): from 10 min the options row's expiry text, "
                        "polite at 60 s and 10 s (CMP-035)",
                        [options_row(tr_playing(k.PLAYHEAD, expiry=S("Closes after 2 h without a control — 9:58 "
                                                                     "left. Play, step or seek keeps it open.")),
                                     tw - 24)], w=tw)
    tw = PW - 48 - 1340
    cause = board_marker("the closed state's alert", "At expiry the closed state's alert is the one announcement "
                         "(the notice has no live role); the cause only when known (CC-6)",
                         [announce(S(f"Replay session closed — data as of {k.hms(t)}.") + " " +
                                   S("Sessions close after 2 h without a control."), role="assertive",
                                   w=tw - 24)], w=tw)
    pg = Pg(account="paper", head=Head(t=t, kind=SIM_KIND), tr=tr, trays=[warn, cause],
            panels=dock_layout(t, "paper", scrim=closed))
    kids = page(pg, PW, 1080)
    return frame("12", theme, kids), [
        f"Session expired (destroyed, D-20): panels frozen under a scrim inside their frames, {closed!r}; Resume at "
        f"{k.hms(t)} (T1) and Leave replay (T1)",
        f"T2: the whole transport on one replay.ended notice ({ended!r}), the step unit, Paper fills and Allow "
        "real-time panels included; 2b badges on the glyphs, the worded controls with no second copy; no live role",
        "OQ-5: simulated orders and positions at expiry are the owner's (§8)"]


def f13(theme: str) -> tuple[Node, list[str]]:
    t = k.STOPPED
    er = k.why("replay.error")
    head_ = S(f"Playback stopped at {k.hms_ms(t)}.")
    cause = S("The recorded data could not be read.")
    callout = notice(f"{head_} {cause}", tone="danger", name="CMP-028 error callout (role alert, once)",
                     actions=[button(S("Seek to retry"), name="CMP-001 Seek to retry (T1)")])
    tr = Tr(play="Play", play_t2=er, t2={"fwd": er}, thumb=t, callout=callout)
    tw = tray_w(2)
    book = board_marker("the book not archived", "Another mapped cause (§7.1): the archive edge, book not archived "
                        "(CC-8 says which case)",
                        [notice(f"{head_} {S('The order book of this window was not archived; replay trades only.')}",
                                tone="danger", name="error · book not archived", w=tw - 24)], w=tw)
    kill = board_marker("the kill switch", "The kill-switch variant (D-23): Seek to retry kept, T1 (the service "
                        "checks no kill switch)",
                        [notice(f"{head_} {S('The kill switch was engaged.')}", tone="danger",
                                name="error · kill switch", w=tw - 24,
                                actions=[button(S("Seek to retry"), name="CMP-001 Seek to retry (T1)")])], w=tw)
    pg = Pg(account="paper", head=Head(t=t, kind=SIM_KIND), tr=tr, trays=[book, kill],
            panels=dock_layout(t, "paper"))
    kids = page(pg, PW, 1080)
    k.reading("error: the mapped cause drawn is storage read failed (§7.1), the server's token never shown (D-23)")
    return frame("13", theme, kids), [
        f"Error (added, D-23): {head_!r} + a mapped cause; Seek to retry (T1) and Leave replay",
        f"T2: Play 2a and `>` 2b on replay.error ({er!r}); CMP-079 RbacGate, CMP-019 lock"]


def f09(theme: str) -> tuple[Node, list[str]]:
    t = k.PLAYHEAD
    above = k.why("replay.paper_above_25x")
    ach = S("achieved 41× of 100×")
    tr = tr_playing(t, selected="100", readout=ach, readout_warn=True, state_line=playing_line("100"), paper="off",
                    paper_label=S("Paper fills · off above 25×"), paper_t2=above)
    tw = tray_w(2)
    unk = board_marker("achieved unknown", "A window with no frame (D-8): the readout says so; a quiet market is not "
                       "a slow engine", [hbox("readout", [presets(selected="100"), readout(S("achieved —"))],
                                              {"gap": k.INSET_SM}, h=CTRL),
                                         hidden(S("No data arrived in the last second."), w=tw - 24)], w=tw)
    ann = board_marker("the announcement", "Below 90 % for two 1 s windows: the warning form, polite once (§5.2)",
                       [announce(S("Playback is slower than requested: 41 times of 100"), w=tw - 24)], w=tw)
    pg = Pg(account="paper", head=Head(t=t, kind=SIM_KIND, speed="100×"), tr=tr, trays=[unk, ann],
            panels=dock_layout(t, "paper", ticket_mode="gated", banner=above))
    kids = page(pg, PW, 1080)
    k.reading("frame 09's Paper fills switch reads 'Paper fills · off above 25×' (§5.2, D-9; §16 readings), off and "
              "T2 2a with its reason beside it")
    return frame("09", theme, kids), [
        f"Speed-limited (D-8): requested 100×, readout {ach!r} in the warning treatment (color.status.warning.subtle, "
        ".strong glyph)",
        "T2: Paper fills 2a on replay.paper_above_25x; the ticket read-only with the same key in E30-D02's banner slot "
        "(CMP-079 RbacGate, CMP-019 lock)",
        "Security: no account id, UID, key or balance; the paper account by its label only (§8)"]


def sim_table(name: str, cols: list[k.Col], rows: list[dict[str, Any]]) -> Callable[[int, int], list[Node]]:
    def build(w: int, h: int) -> list[Node]:
        if sum(c.w for c in cols) > w:
            raise ValueError(f"{name}: columns {sum(c.w for c in cols)} > {w}")
        out = [dict(k.header_row(cols), x=0, y=4)]
        for i, r in enumerate(rows):
            out.append(dict(k.table_row(cols, r, f"row · {i + 1:02d}", fill=k.CANVAS), x=0, y=4 + 24 * (i + 1)))
        return out
    return build


def f10(theme: str) -> tuple[Node, list[str]]:
    t = k.PLAYHEAD
    work = k.why("replay.paper_working")
    tr = tr_playing(t, t2_above=25, presets_reason=work, paper_t2=work)
    fill = next(x for x in k.PRINTS if x.t >= k._t("13:31:00"))
    order_px = (k.last_at(t) - Decimal(5)).quantize(k.TICK)
    k.derive(f"the simulated position: Buy / Long 0.250 filled at the first print from 13:31:00 "
             f"({k.hms(fill.t)}, {k.price(fill.p)}); the working order: Buy 0.100 limit at last − 5.0 = "
             f"{k.price(order_px)}")
    k.copy_gap('the private panels\' column labels (Symbol, Side, Size, Entry, Price, Time) and their titles '
               '(Positions, Orders, Fills): the E38 panels\' words, not this spec\'s; SIM, Cancel and Close are its')
    sim = S("SIM")
    pos = sim_table("positions", [k.Col("sim", sim, 48), k.Col("sym", "Symbol", 80), k.Col("side", "Side", 56),
                                  k.Col("size", "Size", 72, True), k.Col("entry", "Entry", 88, True),
                                  k.Col("act", "", 88)],
                    [{"sim": sim, "sym": k.SYMBOL, "side": "Long", "size": "0.250", "entry": k.price(fill.p),
                      "act": button(S("Close"), name="CMP-001 Close (kept, C-2.6)")}])
    ords = sim_table("orders", [k.Col("sim", sim, 56), k.Col("side", "Side", 64), k.Col("price", "Price", 96, True),
                                k.Col("size", "Size", 80, True), k.Col("act", "", 88)],
                     [{"sim": sim, "side": "Buy", "price": k.price(order_px), "size": "0.100",
                       "act": button(S("Cancel"), name="CMP-001 Cancel (kept, C-2.6)")}])
    fills = sim_table("fills", [k.Col("sim", sim, 56), k.Col("time", "Time", 88), k.Col("side", "Side", 64),
                                k.Col("price", "Price", 96, True), k.Col("size", "Size", 80, True)],
                      [{"sim": sim, "time": k.hms(fill.t), "side": "Buy", "price": k.price(fill.p), "size": "0.250"}])
    other = S(f"Includes simulated rows from other sessions on {k.PAPER}.")

    def lay(y0: int, w: int, h: int) -> list[P]:
        g = 8
        top_h = round((h - 3 * g) * 0.55)
        bot_h = h - 3 * g - top_h
        cw = round((w - 3 * g) * 0.64)
        tw_ = 460
        rest = (w - 5 * g - tw_) // 3
        mk = lambda title, x, fn: P(title, x, y0 + 2 * g + top_h, rest, bot_h, fn, chip_t=t)  # noqa: E731
        ps = [P("Chart BTCUSDT 1m", g, y0 + g, cw, top_h, chart(t), chip_t=t, head_extra=chart_head(t)),
              P("DOM BTCUSDT 200", 2 * g + cw, y0 + g, w - 3 * g - cw, top_h, dom(t), chip_t=t),
              P("Ticket", g, y0 + 2 * g + top_h, tw_, bot_h, ticket("armed"), chip_t=t),
              mk("Positions", 2 * g + tw_, pos), mk("Orders", 3 * g + tw_ + rest, ords),
              mk("Fills", 4 * g + tw_ + 2 * rest, fills)]
        # under the row (header 4 + 24, row 24, then 8), clear of the trays at the dock's foot (boards lens #1)
        ps[3].overlay = [text("other sessions line", other, k.CAPTION, k.TEXT_2, w=rest - 24, x=12,
                              y=HEAD_ROW + 4 + 2 * 24 + 8)]
        return ps
    tw = tray_w(2)
    inv = board_marker("the arm's invalidations", "The replay arm and its three invalidations (§8): each returns "
                       "the pill to LOCKED with the reason (E30's words)",
                       [hbox("pills", [hbox("armed", [text("w", ARMED, k.CAPTION, k.TEXT_1)],
                                            {"padX": k.INSET_SM, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                                             "strokeAlign": "inner", "radius": k.R_BADGE}, h=20),
                                       icon("then", "chevron-right", k.TEXT_2, k.ICON_SM),
                                       hbox("locked", [text("w", S("LOCKED"), k.CAPTION, k.TEXT_1)],
                                            {"padX": k.INSET_SM, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                                             "strokeAlign": "inner", "radius": k.R_BADGE}, h=20),
                                       text("causes", S("TTL expiry, kill switch, risk-cap breach"), k.CAPTION,
                                            k.TEXT_2)], {"gap": k.INSET_SM}, h=24)], w=tw)
    rule = board_marker("the 25× reason", "Why 25× (§5.2, OQ-7)", [text("reason", k.why("replay.paper_above_25x"),
                                                                          k.BODY, k.TEXT_1, w=tw - 24)], w=tw)
    pg = Pg(account="paper", head=Head(t=t, kind=SIM_KIND), tr=tr, trays=[inv, rule], panels=lay)
    fr = k.FRAMES["10"]
    kids = page(pg, fr.w, fr.h)
    k.reading("frame 10's Paper fills switch reads 'Paper fills · Paper 1' (§16 readings): on, and T2 2a on "
              "replay.paper_working while this page's simulated order and position exist")
    return frame("10", theme, kids), [
        f"Paper-fill mode (D-9 to D-11): the carriers {SIM_KIND!r}, {S('SIMULATED · Paper 1')!r} with the Simulated "
        f"submit, {ARMED!r}, the SIM column on is_paper rows; SCR-099's heading is E26-D04's",
        f"T2: presets above 25× (radios kept, one reason under the group) and Paper fills off on replay.paper_working "
        f"({work!r}); cancel and close kept on every row (D-11, C-2.6)",
        f"{other!r} (CC-17); analytics replay.paper_fill (§13); Security: the label only, never an id, UID or balance"]


def cvd(t: datetime) -> Callable[[int, int], list[Node]]:
    """CVD from trades: one column per minute of the taker delta (buys − sells), cvd.buy above, cvd.sell below."""
    def build(w: int, h: int) -> list[Node]:
        a, b = chart_range(t)
        mins = []
        m = a
        while m < b and m <= t:
            d = sum((x.q if x.side == "Buy" else -x.q) for x in k.PRINTS if m <= x.t < m + k.STEP_1M and x.t <= t)
            mins.append(d)
            m += k.STEP_1M
        top = max(abs(x) for x in mins) or Decimal(1)
        mid = h // 2
        slot = w / 60
        kids = [rect("zero line", w, 1, k.GRID, x=0, y=mid)]
        for i, d in enumerate(mins):
            hh = max(1, round(float(abs(d) / top) * (mid - 12)))
            kids.append(rect(f"delta {i:02d}", max(1, round(slot * 0.7)), hh, k.TEXT_2 if d == 0 else
                             ("color.cvd.buy" if d > 0 else "color.cvd.sell"), x=round(i * slot),
                             y=mid - hh if d > 0 else mid))
        return kids
    return build


def profile(t: datetime) -> Callable[[int, int], list[Node]]:
    """Volume profile from trades up to t, 5.0-wide price rows (color.profile.bar, the POC color.profile.poc)."""
    def build(w: int, h: int) -> list[Node]:
        ps = [x for x in k.PRINTS if x.t <= t]
        buckets: dict[Decimal, Decimal] = {}
        for x in ps:
            key_ = (x.p / 5).to_integral_value(rounding="ROUND_FLOOR") * 5
            buckets[key_] = buckets.get(key_, Decimal(0)) + x.q
        levels = sorted(buckets, reverse=True)
        rh = max(4, min(18, (h - 8) // max(1, len(levels))))
        top = max(buckets.values())
        kids = []
        for i, lv in enumerate(levels):
            if 4 + (i + 1) * rh > h:
                break
            bw = max(1, round(float(buckets[lv] / top) * (w - 96)))
            kids += [text(f"level {i:02d}", k.price(lv), k.NUM_XS, k.AXIS_TEXT, x=4, y=4 + i * rh),
                     rect(f"bar {i:02d}", bw, rh - 2, "color.profile.poc" if buckets[lv] == top else
                          "color.profile.bar", x=88, y=4 + i * rh)]
        return kids
    return build


def f15(theme: str) -> tuple[Node, list[str]]:
    t = k.PLAYHEAD
    nr = k.why("replay.not_replayed")
    rtp = k.why("replay.realtime_panel")
    menu = vbox("DOM panel menu (open)", [
        text("item · Re-centre", S("Re-centre and resume auto-follow"), k.BODY, k.TEXT_1),
        vbox("item · Centre on mark · T2", [hbox("first line", [lock(), text("label", S("Centre on mark"), k.BODY,
                                                                               k.TEXT_3)], {"gap": k.INSET_XS}, h=19),
                                            text("second line (reason)", nr, k.CAPTION, k.TEXT_2, w=300)],
             {"gap": k.STACK_XS}, w=300)], {"gap": k.STACK_SM, "pad": k.INSET_SM, "fill": k.OVERLAY,
                                            "radius": k.R_CONTROL, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                            "strokeAlign": "inner"}, w=316)
    eth = lambda tt: [b for b in k.ETH_BARS if b.t + k.STEP_1M <= tt]  # noqa: E731
    k.copy_gap(f'"{k.ETH}": the REAL-TIME panel\'s second symbol (kit choice; D-14 "a second-symbol chart", OQ-3), '
               "a second seeded walk at its fixture tick")
    k.copy_gap('panel titles "CVD BTCUSDT", "Profile BTCUSDT", "Open interest", "Chart ETHUSDT" and the '
               'feed chip "Live": the panels\' own words (E12, E17-D01), not this spec\'s')

    def lay(y0: int, w: int, h: int) -> list[P]:
        g = 8
        top_h = round((h - 3 * g) * 0.55)
        bot_h = h - 3 * g - top_h
        cw, dw = 820, 480
        vw = w - 4 * g - cw - dw
        tpw, pfw, nrw = 480, 420, 400
        rw = w - 5 * g - tpw - pfw - nrw
        rt_head = [text("REAL-TIME", S("REAL-TIME"), k.LABEL, k.TEXT_1),
                   hbox("feed chip", [ellipse("dot", 6, 6, {"fill": k.LIVE_IND}), text("w", "Live", k.CAPTION,
                                                                                       k.LIVE_TEXT)],
                        {"gap": k.INSET_XS}, h=18),
                   hbox("chart trading · T2 2a", [lock(), text("label", "Chart trading", k.CAPTION, k.TEXT_3),
                                                  reason(rtp)], {"gap": k.INSET_XS}, h=18)]
        ps = [P("Chart BTCUSDT 1m", g, y0 + g, cw, top_h, chart(t), chip_t=t, head_extra=chart_head(t)),
              P("DOM BTCUSDT 200", 2 * g + cw, y0 + g, dw, top_h, dom(t), chip_t=t),
              P("CVD BTCUSDT", 3 * g + cw + dw, y0 + g, vw, top_h, cvd(t), chip_t=t),
              P("Tape BTCUSDT", g, y0 + 2 * g + top_h, tpw, bot_h, tape(t), chip_t=t),
              P("Profile BTCUSDT", 2 * g + tpw, y0 + 2 * g + top_h, pfw, bot_h, profile(t), chip_t=t),
              P("Open interest", 3 * g + tpw + pfw, y0 + 2 * g + top_h, nrw, bot_h, centred(nr), chip_t=t),
              P(f"Chart {k.ETH}", 4 * g + tpw + pfw + nrw, y0 + 2 * g + top_h, rw, bot_h,
                chart(t, series=eth, dim_future=False, fmt=lambda d: f"{d:,.2f}", step_=Decimal(1)),
                replay=False, realtime=True, head_extra=rt_head)]
        ps[1].overlay = [dict(menu, x=dw - 316 - 12, y=HEAD_ROW + 8)]
        return ps
    tw = tray_w(2)
    pop = board_marker("a pop-out's strip", "A replaying panel popped out (§3): frame, chip and key layer kept; a gap "
                       "stop, an error or the expiry shows there as one strip inside the frame, naming the state and "
                       "its time", [notice(S(f"Playback stopped at {k.hms_ms(k.STOPPED)}."), tone="danger",
                                           name="pop-out strip", w=tw - 24)], w=tw)
    pg = Pg(account="paper", head=Head(t=t, kind=SIM_KIND), tr=tr_playing(t, rt=True), trays=[pop], panels=lay)
    fr = k.FRAMES["15"]
    kids = page(pg, fr.w, fr.h)
    k.reading("the REAL-TIME panel is a second-symbol chart (ETHUSDT, kit choice) with no frame or chip, the "
              "REAL-TIME word, its feed chip and chart trading T2 on replay.realtime_panel; it presumes Allow "
              "real-time panels on (D-14), so this frame's options row shows it checked (frame 01 has it off)")
    return frame("15", theme, kids), [
        "Panels under replay (§9): chart, DOM, CVD, tape and profile replaying (frame + chip); Open interest not "
        f"replayed ({nr[:40]}…, D-15); the DOM menu's Centre on mark T2 with the reason as its second line",
        f"A REAL-TIME panel (D-14): no frame, no chip, {S('REAL-TIME')!r} in its header, chart trading T2 2a "
        f"({rtp!r}); CMP-079 RbacGate, CMP-019 lock",
        "Tray: a pop-out's one-line strip"]


def f14(theme: str) -> tuple[Node, list[str]]:
    t = k.CLOSED_AT
    words = S(f"Disconnected — replay data as of {k.hms(t)}")
    retry = button(S("Retry now"), name="CMP-001 Retry now (SCR-152's)")
    pg = Pg(account="paper", head=Head(t=t, kind=SIM_KIND), tr=tr_paused(t),
            panels=dock_layout(t, "paper", strip_words=words, strip_action=retry))
    kids = page(pg, PW, 1080)
    k.reading("disconnected: the client paused over REST at once (D-24), so the transport reads paused at the last "
              "rendered frame; SCR-152's Retry now sits on the chart's strip only")
    return frame("14", theme, kids), [
        f"Disconnected (added, D-24): the SCR-152 strip inside each replay frame, {words!r} (E11-D02 §10's recipe); "
        "replay subscriptions never show the stale chip",
        "On reconnect: re-subscribe and seek back to the last rendered cursor (analytics replay.seek kind reconnect)"]


def leave_confirm(w: int, *, viewing_as: bool) -> Node:
    """CMP-044, D-17: the question (without its second sentence while viewing as) and `Also end the session` (T2
    while viewing as); `Stay` and `Leave replay`."""
    q = S("Leave replay and return to your LIVE workspace?")
    va = k.why("rbac.view_as").replace("{user}", VIEWED)
    also = checkbox(S("Also end the session"), on=False, t2=va if viewing_as else None, name="Also end the session")
    return vbox("CMP-044 leave confirm", [text("question", q, k.BODY_STRONG, k.TEXT_1, w=w - 32), also,
                                          hbox("buttons", [button(S("Stay"), name="CMP-001 Stay"),
                                                           button(S("Leave replay"), kind="primary",
                                                                  name="CMP-001 Leave replay")],
                                               {"gap": k.INSET_SM}, h=CTRL)],
                {"gap": k.STACK_MD, "pad": k.INSET_LG, "fill": k.OVERLAY, "radius": k.R_CARD, "stroke": k.BORDER,
                 "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=w)


VIEWED = "Manager 1"


def f22(theme: str) -> tuple[Node, list[str]]:
    t = k.PLAYHEAD
    va = k.tpl("Read-only while viewing as {user}.", {"{user}": VIEWED})
    k.copy_gap(f'"{VIEWED}": the viewed user in rbac.view_as\'s {{user}} slot (synthetic; a P2 Manager)')
    tr = tr_playing(t, **all_t2(va, play_t2=va),
                    notice=notice(va, name="CMP-028 transport notice (rbac.view_as)", role='role="status", once'))
    tw = tray_w(2)
    conf = board_marker("the leave confirm while viewing as", "While viewing as, Leave replay only navigates: the "
                        "confirm without its second sentence, Also end the session T2 (D-17)",
                        [leave_confirm(tw - 24, viewing_as=True)], w=tw)
    # the tray starts past the ticket (8 + 520, then the tape's 8 + 8): the T2 submit stays in view (boards lens #3)
    pg = Pg(account="paper", head=Head(t=t, kind=SIM_KIND), tr=tr, trays=[conf], tray_x=8 + 520 + 16,
            panels=dock_layout(t, "paper", ticket_mode="gated", banner=va))
    kids = page(pg, PW, 1080)
    k.reading("viewing as: the session plays as it is; Pause (Play's slot) is a write, so it is T2 2a on the notice; "
              "the step unit, Paper fills and Allow real-time panels send nothing and pass the view-as leg (§5.3)")
    return frame("22", theme, kids), [
        f"Viewing as (added): one CMP-028 info notice rbac.view_as ({va!r}, role status once); every write T2 on it "
        "(2b badges on the glyphs, Pause / Custom… / Go to 2a with no second copy, the presets with their radios); "
        "the ticket's own notice in E30-D02's banner slot",
        "CMP-079 RbacGate, CMP-019 lock; Leave replay navigates only (no pause, no disarm)"]


def f23(theme: str) -> tuple[Node, list[str]]:
    t = k.PLAYHEAD
    dg = k.why("replay.degraded")
    tr = tr_paused(t, **all_t2(dg), notice=notice(dg, tone="warning", name="CMP-028 transport notice "
                                                  "(replay.degraded)", role='role="alert", once'))
    tw = 1400
    playing = board_marker("on hold while playing", "Playing when the hold lands: Pause stays enabled (and Cancel "
                           "seek, Cancel, Leave replay); the steps, the seeks and the presets T2",
                           [controls_row(Tr(play="Pause", state_line=playing_line(), **{**all_t2(dg), "play_t2": None}),
                                         tw - 24)], w=tw)
    pg = Pg(account="paper", head=Head(t=t, kind=SIM_KIND), tr=tr, trays=[playing],
            panels=dock_layout(t, "paper"))
    kids = page(pg, PW, 1080)
    return frame("23", theme, kids), [
        f"On hold (added, CC-21): one CMP-028 warning notice replay.degraded ({dg!r}, role alert once); Play, the "
        "steps, the seeks, the thumb, Go to and the presets T2 on it; the state line keeps the state",
        "CMP-079 RbacGate, CMP-019 lock; the step unit sends nothing and stays T1"]


# --- registry and the board builder
BUILDERS: dict[str, Callable[[str], tuple[Node, list[str]]]] = {
    "01": f01, "19": f19, "04": f04, "05": f05, "18": f18, "02": f02, "03": f03, "06": f06, "16": f16, "07": f07,
    "08": f08, "11": f11, "12": f12, "13": f13, "10": f10, "09": f09, "15": f15, "14": f14, "22": f22, "23": f23}


def build_board(nn: int) -> tuple[Path, Path, Path]:
    b = k.BOARDS[nn]
    k.NOTES.reset()
    frames_, blocks = [], []
    for fid in b.frames:
        node_, lines = BUILDERS[fid](b.theme)
        frames_.append(node_)
        blocks.append(k.frame_block(fid, b.theme, lines))
    extra = []
    if b.twin_of:
        extra.append(f"Light twin: the same builders as {b.twin_of}; every colour is a token bind, so the light set "
                     "draws the light-critical pairs (§12.2 light column)")
    return k.build(nn, frames_, blocks, board_lines=extra)
