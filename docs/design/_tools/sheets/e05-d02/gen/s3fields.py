"""s3fields: slice 3's shared field pieces for boards 05 (text-inputs) and 06 (pickers-and-gates), built on the kit.

Slice 3 conventions 21 (the field box), 22 (one look per state), 23 (validation), 24 (T2 2a: the lock leads the value
inside the well, the label stays color.text.secondary, the reason under the field) and 26 (popups). Every specimen
string goes through k.say(); a string the spec does not give is drawn as a copy-gap stub (a 6 px bar in the slot's
ink, named "copy gap · <slot>") and recorded with k.gap(), never invented.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e05d02kit as k

Node = dict
FIELD_W = 168  # an author choice: one field width for every slice-3 specimen (the spec sizes fields by their host)
S3 = "s3"
WELL_STATES = (
    "default",
    "hover",
    "focus-visible",
    "invalid",
    "disabled",
    "disabled-with-reason",
    "read-only",
)
_GAPS: set[str] = set()


def stub(slot: str, w: int, ink: str) -> Node:
    """A copy-gap stub: the spec gives no string for this slot, so a 6 px bar in the slot's ink stands for it."""
    if slot not in _GAPS:
        _GAPS.add(slot)
        k.gap(
            f"{slot}: the slice 3 spec gives no string; drawn as a 6 px stub bar in the slot's ink (never invented)"
        )
    return k.rect(f"copy gap · {slot}", w, 6, ink, o={"radius": k.R_BADGE})


def val(chars: str, cid: str, ink: str = k.TEXT_1, typo: str = k.BODY, name: str = "value") -> Node:
    """A say()'d value text."""
    return k.text(name, k.say(chars, cid), typo, ink)


def glyph(ch: str, icon_name: str, ink: str = k.TEXT_3) -> Node:
    """A CMP-019 glyph as a text glyph (kit choice glyphs)."""
    return k.tglyph(ch, ink, name=f"CMP-019 {icon_name} (text glyph)")


def cal_glyph(ink: str = k.TEXT_2) -> Node:
    """CMP-019 `calendar` from primitives (no text glyph stands for it): a 12 px outlined box with a 2 px top band."""
    k._choice("glyphs")
    body = k.place(
        k.rect("frame", 12, 11, o={"stroke": ink, "strokeWidth": k.HAIRLINE, "radius": k.R_BADGE}),
        2,
        3,
    )
    band = k.place(k.rect("band", 12, 2, ink), 2, 3)
    return k.box("CMP-019 calendar (primitives)", [body, band], w=16, h=16)


def ghost_btn(inner: Node, name: str, *, opacity: bool = False) -> Node:
    """A CMP-002 ghost IconButton, size.control.height square, its glyph centred (no fill at rest)."""
    o: dict = {"justify": "center", "radius": k.R_CONTROL}
    if opacity:
        o["opacity"] = k.OP_DISABLED
        k._fallback("OPACITY")
    return k.hbox(name, [inner], o, w=k.CONTROL_PX, h=k.CONTROL_PX)


def well(
    state: str,
    parts: list,
    *,
    cid: str = "CMP-007",
    w: int = FIELD_W,
    trail: Node | None = None,
    justify: str | None = None,
    name: str | None = None,
) -> Node:
    """The slice-3 field well in one of WELL_STATES (conventions 21-24). parts: nodes, or ("value", chars[, typo]),
    ("affix", chars), ("placeholder", chars), ("glyph", ch, icon name), ("stub", slot, w). In T2 the lock leads every part and values turn
    color.text.tertiary; trail is an in-well ghost IconButton flush at the end (the well never grows).
    """
    t2 = state == "disabled-with-reason"
    kids: list = [k.lock()] if t2 else []
    for p in parts:
        if isinstance(p, dict):
            kids.append(p)
        elif p[0] == "value":
            kids.append(
                val(p[1], cid, k.TEXT_3 if t2 else k.TEXT_1, p[2] if len(p) > 2 else k.BODY)
            )
        elif p[0] == "placeholder":
            kids.append(val(p[1], cid, k.TEXT_3, name="placeholder"))
        elif p[0] == "affix":
            kids.append(val(p[1], cid, k.TEXT_3, name="affix"))
        elif p[0] == "glyph":
            kids.append(glyph(p[1], p[2]))
        elif p[0] == "stub":
            kids.append(
                stub(p[1], p[2], k.TEXT_3 if t2 or p[1].startswith("placeholder") else k.TEXT_1)
            )
    o: dict = {"gap": k.INSET_XS, "radius": k.R_CONTROL, "height": k.CONTROL_H, "padL": k.INSET_SM}
    if justify:
        o["justify"] = justify
    if trail is None:
        o["padR"] = k.INSET_SM
    if t2:
        o.update(k.T2_SHAPE)
    elif state == "read-only":
        o.update(stroke=k.BORDER_DEFAULT, strokeWidth=k.HAIRLINE)
    else:
        o.update(fill=k.APP, stroke=k.TEXT_3, strokeWidth=k.HAIRLINE)
        if state == "hover":
            o["stroke"] = k.TEXT_2
        elif state == "invalid":
            o.update(stroke=k.STATUS["danger.default"], strokeWidth=k.THICK)
        elif state == "disabled":
            o["opacity"] = k.OP_DISABLED
            k._fallback("OPACITY")
    if trail is not None:
        inner = k.hbox(
            "content", kids, {"gap": k.INSET_XS}, w=w - k.CONTROL_PX - 8 - 4, h=k.CONTROL_PX
        )
        kids = [inner, trail]
        o["justify"] = "space-between"
    nm = name or f"{cid} well · {state}" + (" · T2" if t2 else "")
    n = k.hbox(nm, kids, o, w=w, h=k.CONTROL_PX)
    return k.focus_ring(n) if state == "focus-visible" else n


def label(
    chars: str | None, cid: str = "CMP-040", *, marker: bool = False, stub_w: int = 72
) -> Node:
    """A CMP-040 label (type.ui.label, color.text.secondary, T2 included); marker adds "(optional)" tertiary; None
    draws a copy-gap stub."""
    if chars is None:
        return k.hbox("label", [stub("field label", stub_w, k.TEXT_2)], {"gap": k.INSET_XS}, h=16)
    kids = [k.text("label", k.say(chars, cid), k.LABEL, k.TEXT_2)]
    if marker:
        kids.append(k.text("marker", k.say("(optional)", "CMP-040"), k.LABEL, k.TEXT_3))
    return k.hbox("label row", kids, {"gap": k.INSET_XS})


def error_line(chars: str, cid: str, w: int = FIELD_W) -> Node:
    """The conventions 23 message line: the CMP-019 danger glyph (decorative) in color.status.danger.strong, then the
    sentence in type.ui.caption color.text.primary; three cues, never colour alone."""
    return k.hbox(
        "error",
        [
            glyph("⊘", "danger", k.STATUS["danger.strong"]),
            k.text("message", k.say(chars, cid), k.CAPTION, k.TEXT_1, w=w - 20),
        ],
        {"gap": k.INSET_XS, "align": "start"},
    )


def reason(chars: str, cid: str, w: int = FIELD_W) -> Node:
    """The 2a reason under a field: type.ui.caption color.text.secondary (a say()'d rbac.* string)."""
    return k.t2_reason(k.say(chars, cid), w=w)


def field(
    control: Node,
    *,
    lab: str | None = "Username",
    lab_cid: str = "CMP-040",
    marker: bool = False,
    lines: list | None = None,
    state: str = "default",
    inline: bool = False,
    name: str | None = None,
) -> Node:
    """A CMP-040 FormField: label (stack.xs) control, then its lines (reason, error, help) stack.xs apart; plain
    disabled puts the whole field at opacity.disabled; inline puts the label in a column space.field.gap before it.
    """
    t2 = state == "disabled-with-reason"
    nm = name or f"CMP-040 field · {state}" + (" · T2" if t2 else "")
    lb = label(lab, lab_cid, marker=marker)
    o: dict = {"gap": k.STACK_XS}
    if state == "disabled":
        o["opacity"] = k.OP_DISABLED
        k._fallback("OPACITY")
    if inline:
        col = k.vbox("control column", [control, *(lines or [])], {"gap": k.STACK_XS})
        return k.hbox(nm, [lb, col], {**o, "gap": k.FIELD_GAP, "align": "start"})
    return k.vbox(nm, [lb, control, *(lines or [])], o)


def popup(rows: list, *, w: int = FIELD_W, name: str = "popup") -> Node:
    """Conventions 26's popup: color.surface.overlay, elevation.popover, radius.card, 1 px color.border.default,
    padding-block space.inset.xs, at least as wide as the field."""
    return k.vbox(
        name,
        rows,
        {
            "fill": k.OVERLAY,
            "shadow": k.E_POPOVER,
            "radius": k.R_CARD,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "padT": k.INSET_XS,
            "padB": k.INSET_XS,
        },
        w=w,
    )


def option(
    lab: list,
    look: str = "rest",
    *,
    second: str | None = None,
    cid: str = "CMP-009",
    w: int = FIELD_W,
) -> Node:
    """A popup option row (conventions 26): a leading size.icon check slot, the label in type.ui.body
    color.text.primary (lab: nodes), min-height size.row.height, padding-inline space.inset.sm. look: rest, active
    (color.surface.hover), selected (the check glyph), disabled (plain: the row at opacity.disabled), validity (the
    label only at opacity.disabled, the reason as its second line at full opacity, no lock), T2 (the lock and the
    full label in color.text.tertiary, the reason as its second line)."""
    t2 = look == "T2"
    if look == "selected":
        slot = glyph("✓", "check", k.TEXT_1)
    elif t2:
        slot = k.lock()
    else:
        slot = k.rect("check slot", 16, 16)
    lab_o: dict = {}
    if look == "validity":
        lab_o["opacity"] = k.OP_DISABLED
        k._fallback("OPACITY")
    lab_n = k.hbox("label", lab, lab_o, h=None if any(k._has_text(x) for x in lab) else 16)
    line1 = k.hbox("line 1", [slot, lab_n], {"gap": k.INSET_XS}, h=k.CONTROL_PX)
    kids = [line1]
    if second:
        kids.append(
            k.hbox(
                "second line",
                [
                    k.rect("indent", 16, 4),
                    k.text("reason", k.say(second, cid), k.CAPTION, k.TEXT_2, w=w - 44),
                ],
                {"gap": k.INSET_XS, "align": "start"},
            )
        )
    o: dict = {"padX": k.INSET_SM, "minH": k.ROW_H}
    if look == "active":
        o["fill"] = k.HOVER
    if look == "disabled":
        o["opacity"] = k.OP_DISABLED
        k._fallback("OPACITY")
    nm = f"option · {look}" + (" · T2" if t2 else "")
    return k.vbox(nm, kids, o, w=w, h=None if second or k._has_text(line1) else k.CONTROL_PX)


def opt_text(chars: str, cid: str, ink: str = k.TEXT_1, typo: str = k.BODY) -> Node:
    """An option label text."""
    return k.text("text", k.say(chars, cid), typo, ink)


def status_row(kids: list, name: str = "status row", w: int = FIELD_W) -> Node:
    """A popup status row (conventions 26): text in color.text.secondary, padding-inline space.inset.sm."""
    return k.hbox(name, kids, {"gap": k.INSET_XS, "padX": k.INSET_SM, "minH": k.ROW_H}, w=w)
