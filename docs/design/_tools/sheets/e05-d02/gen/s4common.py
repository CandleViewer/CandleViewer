"""s4common: slice 4 pieces shared by gen_08.py (feedback-states) and gen_09.py (overlays), board pair 5.

Built only from e05d02kit primitives (no inst node, local icons only); every specimen string goes through k.say().
Glyphs other than the five local icons are text glyphs (kit choice `glyphs`), named "CMP-019 <name> (text glyph)".
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e05d02kit as k

Node = dict[str, Any]

# CMP-019 glyph names -> text glyphs (k.NOTATION); `close` and `locked` are the file's local icons.
GL = {
    "info": "ⓘ",
    "check": "✓",
    "warning": "⚠",
    "danger": "⊘",
    "disconnected": "✕",
    "search": "⌕",
    "chevron-down": "▾",
    "chevron-up": "▴",
    "chevron-right": "▸",
    "chevron-left": "◂",
    "more": "⋮",
    "copy": "⧉",
}
TONE_GLYPH = {
    "info": "info",
    "success": "check",
    "warning": "warning",
    "danger": "danger",
    "connection-reconnecting": "disconnected",
    "connection-disconnected": "disconnected",
}
TONE_KEY = {
    "info": "info",
    "success": "success",
    "warning": "warning",
    "danger": "danger",
    "connection-reconnecting": "danger",
    "connection-disconnected": "danger",
}  # §6 H5: connection on danger
MENU_W = 220
TOAST_W = 360  # CMP-045 surface (§5.1)
BLOCK_W = 480  # CMP-026's column (§5.1), CMP-027 panel, CMP-028 inline stand-in width
SCRIM_FILL = k.SUNKEN  # palette.black is a primitive colour the validator refuses (FALLBACK below)

FALLBACK_SCRIM = (
    "fallback: the scrim is palette.black at opacity.scrim (conventions 31, §6 H1 PROPOSED "
    "color.surface.scrim); the validator refuses a primitive colour, so it is drawn color.surface.sunken "
    "(#000000 in dark, the boards' theme) at opacity.scrim; live check: rebind the fill to palette.black"
)
FALLBACK_HATCH = (
    "fallback: CMP-028's hatched edge (45°, 1 px color.status.danger.strong lines at 6 px pitch on "
    "color.status.danger.subtle) is drawn as 1 px ticks at 6 px pitch on a 4 px subtle column: cvsheet "
    "has no rotation"
)


def say(chars: str, cid: str, doc: str | None = None) -> str:
    """k.say() with the CMP (doc= another slice for a nested slice-3 string)."""
    return k.say(chars, cid, doc=doc) if doc else k.say(chars, cid)


def glyph(name: str, color: str, typo: str = k.BODY) -> Node:
    """A CMP-019 glyph as a text glyph (decorative unless the caller says otherwise)."""
    return k.tglyph(GL[name], color, typo, name=f"CMP-019 {name} (text glyph)")


def tone_glyph(tone: str, typo: str = k.BODY) -> Node:
    """The tone's CMP-019 glyph in its .strong colour (glyph + word: never colour alone)."""
    return glyph(TONE_GLYPH[tone], k.STATUS[f"{TONE_KEY[tone]}.strong"], typo)


def t(
    name: str, chars: str, typo: str = k.BODY, color: str = k.TEXT_1, w: int | None = None
) -> Node:
    """A text node (chars already say()'d)."""
    return k.text(name, chars, typo, color, w=w)


def ibtn(glyph_name: str = "close", state: str = "default", *, name: str | None = None) -> Node:
    """CMP-002 ghost IconButton, 24 x 24: the local `close` icon or a text glyph; focus-visible adds CMP-039."""
    inner = (
        k.icon("CMP-019 close", "close", k.TEXT_2)
        if glyph_name == "close"
        else glyph(glyph_name, k.TEXT_2)
    )
    b = k.hbox(
        name or f"CMP-002 {glyph_name}",
        [inner],
        {"justify": "center", "radius": k.R_CONTROL},
        w=k.CONTROL_PX,
        h=k.CONTROL_PX,
    )
    return k.focus_ring(b) if state == "focus-visible" else b


def row(name: str, kids: list[Node | None], gap: str = k.INSET_SM, **o: Any) -> Node:
    """A flex row (centred items)."""
    return k.hbox(name, [x for x in kids if x], {"gap": gap, **o})


def col(
    name: str, kids: list[Node | None], gap: str = k.STACK_SM, w: int | None = None, **o: Any
) -> Node:
    """A flex column."""
    return k.vbox(name, [x for x in kids if x], {"gap": gap, **o}, w=w)


def spread(name: str, left: Node, right: Node, w: int, h: int | None = None) -> Node:
    """A row with left and right ends (justify space-between, fixed width)."""
    return k.hbox(name, [left, right], {"justify": "space-between"}, w=w, h=h)


def edge(name: str, color: str, h: int, w: int = 2) -> Node:
    """A start edge (border.thick, 2 px) as an abs rect at x 0."""
    return k.place(k.rect(name, w, h, color), 0, 0)


def hatched_edge(h: int) -> Node:
    """CMP-028's hatched 4 px start edge (FALLBACK_HATCH): ticks at 6 px pitch on a subtle column."""
    k.LOG.add("fallbacks", FALLBACK_HATCH)
    ticks = [
        k.place(k.rect(f"hatch {i}", 4, 1, k.STATUS["danger.strong"]), 0, 3 + 6 * i)
        for i in range(h // 6)
    ]
    return k.place(
        k.box(
            "edge hatched", [k.rect("column", 4, h, k.STATUS["danger.subtle"]), *ticks], w=4, h=h
        ),
        0,
        0,
    )


def field(
    label: str | None,
    value: str | None,
    *,
    w: int = 240,
    placeholder: bool = False,
    ring: bool = False,
    name: str = "CMP-040 field",
) -> Node:
    """A slice 3 field (conventions 21): label type.ui.label color.text.secondary over a color.surface.app well with a
    1 px color.text.tertiary boundary, radius.control, 24 px, padding-inline space.inset.sm."""
    kids = [t("value", value, k.BODY, k.TEXT_3 if placeholder else k.TEXT_1)] if value else []
    well = k.hbox(
        "CMP-007 well",
        kids,
        {
            "fill": k.APP,
            "stroke": k.TEXT_3,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CONTROL,
            "padX": k.INSET_SM,
        },
        w=w,
        h=k.CONTROL_PX,
    )
    if ring:
        well = k.focus_ring(well)
    return col(
        name, [t("label", label, k.LABEL, k.TEXT_2) if label else None, well], gap=k.STACK_XS
    )


def floating(
    name: str,
    kids: list[Node | None],
    *,
    w: int | None = None,
    h: int | None = None,
    pad: str = k.INSET_SM,
    gap: str = k.STACK_SM,
    **o: Any,
) -> Node:
    """Conventions 30's floating surface: color.surface.overlay, elevation.popover, radius.card, 1 px
    color.border.default edge."""
    return k.vbox(
        name,
        [x for x in kids if x],
        {
            "fill": k.OVERLAY,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CARD,
            "shadow": k.E_POPOVER,
            "pad": pad,
            "gap": gap,
            **o,
        },
        w=w,
        h=h,
    )


def modal_card(
    name: str, kids: list[Node | None], *, w: int, gap: str = k.STACK_MD, **o: Any
) -> Node:
    """Conventions 30's modal surface (CMP-043's card): overlay, elevation.dialog, radius.dialog, 1 px edge,
    space.dialog.padding."""
    return k.vbox(
        name,
        [x for x in kids if x],
        {
            "fill": k.OVERLAY,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_DIALOG,
            "shadow": k.E_DIALOG,
            "pad": k.DIALOG_PAD,
            "gap": gap,
            **o,
        },
        w=w,
    )


def host(
    name: str,
    inner: list[Node],
    *,
    w: int,
    h: int,
    scrim: bool = False,
    justify: str = "center",
    align: str = "center",
    pad: str | None = None,
) -> Node:
    """The cell's stand-in host: a w x h color.surface.app board with a 1 px color.border.subtle edge (so it reads on
    the app plate); scrim=True lays conventions 31's scrim over it (FALLBACK_SCRIM) under the surface.
    """
    kids: list[Node] = []
    if scrim:
        k.LOG.add("fallbacks", FALLBACK_SCRIM)
        k._fallback("OPACITY")
        kids.append(k.place(k.rect("scrim", w, h, SCRIM_FILL, o={"opacity": k.OP_SCRIM}), 0, 0))
    o: dict[str, Any] = {
        "fill": k.APP,
        "stroke": k.BORDER_SUBTLE,
        "strokeWidth": k.HAIRLINE,
        "justify": justify,
        "align": align,
    }
    if pad:
        o["pad"] = pad
    return k.hbox(name, kids + inner, o, w=w, h=h)


def footer(name: str, buttons: list[Node], w: int, lead: Node | None = None) -> Node:
    """A dialog footer: CMP-001 row, end-aligned, space.inset.sm apart (lead= a node at the start, e.g. a countdown)."""
    btns = row("buttons", buttons)
    if lead:
        return spread(name, lead, btns, w)
    return k.hbox(name, [btns], {"justify": "end"}, w=w)


def header(title: str, w: int, *, close: bool = True, typo: str = k.HEADING_SM) -> Node:
    """A dialog / drawer header: the title (type.ui.heading-sm, color.text.primary) and the CMP-002 ghost close."""
    tt = t("title", title, typo, k.TEXT_1, w=w - (40 if close else 0))
    return (
        spread("header", tt, ibtn("close", name="CMP-002 close · Close {title}"), w)
        if close
        else tt
    )


def skel_rows(n: int, w: int, on_overlay: bool = False) -> Node:
    """CMP-015 rows (size.row.height, three size.icon cell blocks, radius.control) for a loading body (§6 H3: on an
    overlay the blocks are color.surface.selected)."""
    fill = k.SELECTED if on_overlay else k.HOVER
    rows = []
    for i in range(n):
        cells = [
            k.rect(f"cell {j}", bw, k.PX[k.ICON], fill, o={"radius": k.R_CONTROL})
            for j, bw in enumerate((w * 2 // 5, w // 4, w // 6))
        ]
        rows.append(
            k.hbox(
                f"CMP-015 row {i + 1}", cells, {"gap": k.INSET_SM, "padX": k.INSET_SM}, w=w, h=24
            )
        )
    return k.vbox("CMP-015 rows", rows, {"gap": k.STACK_XS}, w=w, h=n * 24 + (n - 1) * 4)


def link(chars: str, typo: str = k.BODY) -> Node:
    """A CMP-021 link (color.text.link)."""
    return k.text("CMP-021 link", chars, typo, k.TEXT_LINK)


def disclosure(label: str, open_: bool = False) -> Node:
    """CMP-001 ghost with a trailing chevron (an APG Disclosure: "Technical details")."""
    return k.hbox(
        f"CMP-001 ghost disclosure · {'open' if open_ else 'closed'}",
        [
            t("label", label, k.BODY_STRONG, k.TEXT_2),
            glyph("chevron-up" if open_ else "chevron-down", k.TEXT_2),
        ],
        {"gap": k.INSET_XS, "padX": k.BTN_PADX, "radius": k.R_CONTROL},
        h=k.CONTROL_PX,
    )


def nd(cid: str, *extra: str) -> list[str]:
    """A block's not-drawn list: the spec's own Not drawn text, then the rest the board cap leaves to the text."""
    return [
        k.not_drawn(cid),
        *extra,
        "every combination beyond the named cells",
        "comfortable density",
    ]
