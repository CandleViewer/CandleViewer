"""s1parts: slice 1 control pieces shared by gen_01.py and gen_02.py (E05-D02 boards 01-02). Stdlib only.

Every piece is composed from board / rect / text / ellipse / local icons with token binds (no inst node). Geometry
comes from the slice 1 CMP sections (spec/E05-D02@966f9edcd.md): 24 px control height (compact), 16 px boxes, rings,
knobs and thumbs (size.icon), 40 x 24 switch track, 8 px slider track, 24 px swatch.
State looks: slice 1 §3 conventions 3 (hover, focus, active, selected, plain disabled) and E09-D09 §2.2 T2 for every
gated cell (k.KIT_CHOICES t2: stripped shape, the lock LEADS the full label, label + lock color.text.tertiary, the
reason under it (2a) or a CMP-016 echo (2b, icon-only); a selected outline stays (s1 §8 intro)).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e05d02kit as k

Node = dict[str, Any]
SEL = {
    "fill": k.ACTION["selected"],
    "stroke": k.BORDER_SELECTED,
    "strokeWidth": k.THICK,
}  # #3925 selected role
OWNER_ONLY = "Owner only: your role can't use this action."
READ_ONLY = "Read-only: your role can't change this setting."


def t2(node: Node) -> Node:
    """Rename a gated specimen so its path holds "T2" (write_sheet's never-disabled check covers it)."""
    return node if "T2" in node["name"] else dict(node, name=f"T2 {node['name']}")


def dim(node: Node) -> Node:
    """Plain disabled (availability only): the whole control at opacity.disabled (s1 conventions 3)."""
    k._fallback("OPACITY")
    o = dict(node.get("o") or {})
    o["opacity"] = k.OP_DISABLED
    return dict(node, o=o)


def hover_outline(o: dict[str, Any]) -> dict[str, Any]:
    """A selection control's hover: the fill stays and a 1 px inner color.text.secondary outline (conventions 3)."""
    return {**o, "stroke": k.TEXT_2, "strokeWidth": k.HAIRLINE}


# --- CMP-005 Checkbox / CMP-006 Radio indicator / CMP-004 Toggle track / CMP-010 Slider / CMP-031 Swatch shapes.
def box16(checked: str, state: str, *, radio: bool = False) -> Node:
    """The 16 px checkbox box (radius.control) or radio ring (radius.badge): unchecked = 1 px color.text.tertiary
    outline; checked / indeterminate = color.action.primary.default fill with an on-action ✓ / − (radio: a dot).
    """
    on = checked in ("true", "indeterminate")
    o: dict[str, Any] = {"radius": k.R_BADGE if radio else k.R_CONTROL, "justify": "center"}
    if on:
        o.update(fill=k.ACTION["primary"], stroke=k.ACTION["primary"], strokeWidth=k.HAIRLINE)
    else:
        o.update(stroke=k.TEXT_3, strokeWidth=k.HAIRLINE)
    if state == "hover":
        o = hover_outline(o)
    gated = state == "disabled-with-reason"
    if gated:
        o.update(k.T2_SHAPE)
    kids: list[Node] = []
    ink = k.TEXT_1 if gated else k.TEXT_ON_ACTION
    if on and radio:
        kids.append(k.ellipse("dot", 6, 6, {"fill": ink}))
    elif on:
        ch = "✓" if checked == "true" else "−"
        kids.append(
            k.tglyph(
                ch, ink, k.CAPTION, name=f"CMP-019 {'check' if ch == '✓' else 'minus'} (text glyph)"
            )
        )
    name = ("radio ring" if radio else "box") + (" · T2" if gated else "")
    return k.hbox(name, kids, o, w=16, h=16)


def labelled(
    control: Node,
    label: str,
    state: str,
    *,
    name: str,
    label_left: bool = False,
    strong: bool = False,
    lead: Node | None = None,
    ring_radius: str = k.R_RING,
) -> Node:
    """A selection control row (size.control.height, space.field.gap): control + label; T2 puts the lock before the
    label, label + lock color.text.tertiary (E09-D09 §2.2)."""
    typo = k.BODY_STRONG if strong else k.BODY
    if state == "disabled-with-reason":
        lab = k.t2_label(label, typo=typo)
    else:
        lab = k.hbox(
            "label row", [lead, k.text("label", label, typo, k.TEXT_1)], {"gap": k.INSET_XS}
        )
    ctl = k.focus_ring(control, radius=ring_radius) if state == "focus-visible" else control
    kids = [lab, ctl] if label_left else [ctl, lab]
    n = k.hbox(name, kids, {"gap": k.FIELD_GAP}, h=max(k.CONTROL_PX, round(k.est_height(ctl))))
    if state == "disabled":
        n = dim(n)
    if state == "disabled-with-reason":
        n = t2(n)
    return n


def track40(checked: bool, state: str, *, critical: bool = False) -> Node:
    """CMP-004's 40 x 24 track (radius.badge, space.inset.xs padding): off color.text.tertiary, on
    color.action.primary.default (critical + on: color.status.warning.strong, D4 held); a 16 px knob in
    color.text.on-action (critical armed: color.text.inverse) at the start (off) or end (on)."""
    fill = (
        (k.STATUS["warning.strong"] if critical else k.ACTION["primary"]) if checked else k.TEXT_3
    )
    o: dict[str, Any] = {
        "fill": fill,
        "radius": k.R_BADGE,
        "padX": k.INSET_XS,
        "justify": "end" if checked else "start",
    }
    if state == "hover":
        o = hover_outline(o)
    gated = state == "disabled-with-reason"
    knob_ink = k.TEXT_INVERSE if (critical and checked) else k.TEXT_ON_ACTION
    if gated:
        o.update(k.T2_SHAPE)
        knob_ink = k.TEXT_1
    knob = k.ellipse("knob", 16, 16, {"fill": knob_ink})
    return k.hbox("track" + (" · T2" if gated else ""), [knob], o, w=40, h=24)


def slider(state: str, *, marks: bool = False, w: int = 216) -> Node:
    """CMP-010 at the sample value 40 of 0-100: a 8 px track (80 px filled color.action.primary.default, the rest
    color.text.tertiary; hover color.text.secondary), a 16 px thumb in color.action.primary.default, radius.badge;
    marks = numeric labels in type.num.sm under the rail (C8)."""
    gated = state == "disabled-with-reason"
    rest = k.TEXT_2 if state == "hover" else k.TEXT_3
    filled_fill = k.ACTION["primary"]
    if gated:
        rest, filled_fill = k.RAISED, k.TEXT_3
    fw = round((w - 16) * 0.4)
    filled = k.rect("track-filled", fw, 8, filled_fill, o={"radius": k.R_BADGE})
    thumb = k.ellipse("thumb", 16, 16, {"fill": k.TEXT_1 if gated else k.ACTION["primary"]})
    rest_o = {
        "radius": k.R_BADGE,
        **({"stroke": k.BORDER_DEFAULT, "strokeWidth": k.HAIRLINE} if gated else {}),
    }
    rest_r = k.rect("track-rest", w - 16 - fw, 8, rest, o=rest_o)
    rail = k.hbox(
        "rail" + (" · T2" if gated else ""), [filled, thumb, rest_r], {}, w=w, h=k.CONTROL_PX
    )
    if state == "focus-visible":
        ring = k.focus_ring(thumb, radius=k.R_BADGE, name="focus-ring on thumb")
        rail = k.hbox("rail", [filled, ring, rest_r], {}, w=w + 4, h=k.CONTROL_PX + 4)
    if not marks:
        return rail
    labs = k.hbox(
        "marks",
        [k.text(f"mark {v}", k.say(v, "CMP-010"), k.NUM_SM, k.TEXT_2) for v in ("0", "40", "100")],
        {"justify": "space-between"},
        w=w,
    )
    return k.vbox("slider · marks", [rail, labs], {"gap": k.STACK_XS})


def swatch(selected: bool, state: str, color: str = "color.drawing.default") -> Node:
    """CMP-031: a 24 px colour swatch (radius.control) in its true colour (never dimmed when gated: the colour is the
    value); selected = a centred ✓ in color.text.inverse; hover = a 1 px color.text.secondary outline.
    """
    o: dict[str, Any] = {"fill": color, "radius": k.R_CONTROL, "justify": "center"}
    if state == "hover":
        o.update(stroke=k.TEXT_2, strokeWidth=k.HAIRLINE)
    kids = (
        [k.tglyph("✓", k.TEXT_INVERSE, k.BODY, name="CMP-019 check (text glyph)")]
        if selected
        else []
    )
    return k.hbox("swatch", kids, o, w=24, h=24)
