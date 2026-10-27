"""gen_01: E05-D02 / 01 actions (CMP-001 Button, CMP-002 IconButton, CMP-003 SegmentedControl, CMP-004 Toggle).

Slice 1 (spec/E05-D02@966f9edcd.md §8 L621-908), conventions 2 matrix rule at compact density, T2 per E09-D09 §2.2.
Run: python3 -I -B gen/gen_01.py   (writes 01-actions.json + .md, validates, packs into ../E05-D02-v4/)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s1parts as p

import e05d02kit as k

NN = 1
VARIANTS = ("primary", "secondary", "ghost", "danger", "buy", "sell")
B_STATES = (
    "default",
    "hover",
    "focus-visible",
    "active",
    "disabled",
    "disabled-with-reason",
    "loading",
)
STATES5 = ("default", "hover", "focus-visible", "disabled", "disabled-with-reason")


# --- CMP-001 Button.
def overlay_loading(label: str, variant: str) -> k.Node:
    """primary / secondary / ghost / danger loading: the width-locked button with the CMP-014 overlay spinner in the
    label's ink (EXC-CMP-001-1, B3); the label stays in the DOM at opacity 0, so it is not drawn."""
    ref = k.button(label, variant)
    fill, ink = k.BUTTON_LOOK[variant][:2]
    o = {"radius": k.R_CONTROL, "justify": "center", **({"fill": fill} if fill else {})}
    return k.hbox(
        f"CMP-001 button · {variant} · loading",
        [k.spinner(16, ink, name="CMP-014 spinner overlay")],
        o,
        w=round(k.est_width(ref)),
        h=k.CONTROL_PX,
    )


def button_cell(variant: str, state: str, label: str) -> k.Node:
    """One CMP-001 cell (T2 with the 2a reason; overlay loading for the non-directional variants)."""
    if state == "loading" and variant not in ("buy", "sell"):
        return k.cell(
            state, overlay_loading(label, variant), note="overlay spinner, label kept at opacity 0"
        )
    reason = k.say(p.OWNER_ONLY, "CMP-001") if state == "disabled-with-reason" else None
    b = k.button(label, variant, state, reason=reason)
    if state == "disabled-with-reason":
        b = p.t2(b)
    note = {
        "loading": "spinner trails, word and arrow stay (D1)",
        "disabled-with-reason": "T2 2a",
    }.get(state)
    return k.cell(state, b, note=note)


def cmp001() -> k.Node:
    save = k.say("Save", "CMP-001")
    words = {"buy": k.say("Buy / Long", "CMP-001"), "sell": k.say("Sell / Short", "CMP-001")}
    rows = [
        k.state_row(v, [button_cell(v, s, words.get(v, save)) for s in B_STATES]) for v in VARIANTS
    ]
    for size in ("sm", "lg"):
        rows.append(
            k.state_row(
                f"size {size}",
                [k.cell(v, k.button(words.get(v, save), v, size=size)) for v in VARIANTS],
            )
        )
    return k.block(
        "CMP-001",
        rows,
        states=list(B_STATES),
        proposed=["D1", "D13", "D16", "A12", "B3", "A11", "A2"],
        ruled=["#3925", "E09-D09 §2.2"],
        note=(
            "Rows = Variant at size md (conventions 2); sizes sm / lg at State=default. Buy / sell lead "
            "with arrow-up / arrow-down in every cell and carry color.text.inverse (A12). Danger hover and "
            "active stay color.status.danger.default (no state tokens, A2)."
        ),
        not_drawn=[
            "comfortable density (size.control.height 32)",
            "sizes sm / lg x every non-default State (derivable, s1 §6 C13)",
            "the 5 s slow-path text 'Checking with the exchange…' (CMP-038, board 08)",
            "iconLeft / iconRight on the non-directional variants",
            "the CMP-044 confirm wrapper Variant=danger opens (board 09)",
        ],
    )


# --- CMP-002 IconButton.
IB_LOOK = {  # variant -> (fill, glyph ink, hover fill, hover ink): slice 1 CMP-002 token mapping (as CMP-001)
    "primary": (k.ACTION["primary"], k.TEXT_ON_ACTION, k.ACTION["primary.hover"], k.TEXT_ON_ACTION),
    "secondary": (k.ACTION["secondary"], k.TEXT_1, k.ACTION["secondary.hover"], k.TEXT_1),
    "ghost": (None, k.TEXT_2, k.HOVER, k.TEXT_1),
    "danger": (
        k.STATUS["danger.default"],
        k.TEXT_ON_ACTION,
        k.STATUS["danger.default"],
        k.TEXT_ON_ACTION,
    ),
}


def iconbutton(
    variant: str, state: str = "default", *, size: str = k.ICON, pressed: bool = False
) -> k.Node:
    """A 24 px square CMP-002 (radius.control) holding the local `close` icon (the sample glyph; its name is the
    aria-label); sm / lg scale the glyph only (size.icon.sm / .lg), never the box."""
    fill, ink, hfill, hink = IB_LOOK[variant]
    if state == "hover":
        fill, ink = hfill, hink
    o: dict = {"radius": k.R_CONTROL, "justify": "center"}
    if pressed:
        o.update(p.SEL)
        ink = k.TEXT_1
    elif fill:
        o["fill"] = fill
    gated = state == "disabled-with-reason"
    if gated:
        o.update(k.T2_SHAPE)
        if pressed:
            o.update(stroke=k.BORDER_SELECTED, strokeWidth=k.THICK)
        ink = k.TEXT_3
    n = k.hbox(
        f"CMP-002 iconbutton · {variant}"
        + (" · pressed" if pressed else "")
        + (" · T2" if gated else ""),
        [k.icon("CMP-019 close", "close", ink, size=size)],
        o,
        w=k.CONTROL_PX,
        h=k.CONTROL_PX,
    )
    if state == "focus-visible":
        n = k.focus_ring(n)
    if state == "disabled":
        n = p.dim(n)
    return n


def ib_cell(variant: str, state: str, *, pressed: bool = False) -> k.Node:
    """A CMP-002 cell; T2 is 2b: the size.icon.sm corner lock badge plus the CMP-016 echo of the reason."""
    ib = iconbutton(variant, state, pressed=pressed)
    if state == "disabled-with-reason":
        echo = k.tooltip(k.say(p.OWNER_ONLY, "CMP-002"), w=180, name="CMP-016 reason echo")
        return k.cell(
            state,
            p.t2(k.vbox("2b", [k.lock_badge(ib), echo], {"gap": k.STACK_XS})),
            note="T2 2b + echo",
        )
    return k.cell(state, ib)


def cmp002() -> k.Node:
    rows = [k.state_row(v, [ib_cell(v, s) for s in STATES5]) for v in IB_LOOK]
    rows.append(
        k.state_row(
            "sizes",
            [
                k.cell("size sm", iconbutton("secondary", size=k.ICON_SM)),
                k.cell("size lg", iconbutton("secondary", size=k.ICON_LG)),
            ],
        )
    )
    rows.append(
        k.state_row(
            "Pressed=true",
            [
                k.cell("secondary", iconbutton("secondary", pressed=True)),
                k.cell("ghost", iconbutton("ghost", pressed=True)),
                ib_cell("secondary", "disabled-with-reason", pressed=True),
            ],
        )
    )
    return k.block(
        "CMP-002",
        rows,
        states=list(STATES5) + ["Pressed=true"],
        proposed=["C1", "D10", "D13", "A10"],
        ruled=["#3925"],
        note=(
            "Sample glyph: the local icon close (the name is aria-label, e.g. 'Panel settings'). Pressed "
            "= #3925's selected role (color.action.selected, 2 px color.border.selected), toggle mode on "
            "secondary and ghost only (OWNER APPROVAL B); the gated pressed cell keeps its outline."
        ),
        not_drawn=[
            "sizes sm / lg x every non-default State",
            "Pressed=true on primary / danger (C1 B)",
            "the D10 name tooltip (proposed, not in the catalogue)",
            "comfortable density (32 px)",
        ],
    )


# --- CMP-003 SegmentedControl.
def segmented(state: str, *, content: str = "text", options: int = 3, size: str = "md") -> k.Node:
    """A CMP-003 track (color.surface.raised, radius.control) of segments, option 1 checked (#3925 selected role);
    hover = option 2 on color.surface.hover + color.text.primary; focus = the ring on the checked segment; T2 = the
    stripped track, the lock leading, labels color.text.tertiary, the selected outline kept."""
    names = ["Ascending", "Unsorted", "Descending"] if options == 3 else ["Ascending", "Descending"]
    gated = state == "disabled-with-reason"
    segs: list[k.Node] = []
    for i, nm in enumerate(names):
        label = k.say(nm, "CMP-003")
        sel, hov = i == 0, state == "hover" and i == 1
        ink = k.TEXT_1 if (sel or hov) else k.TEXT_2
        if gated:
            ink = k.TEXT_3
        o: dict = {
            "radius": k.R_CONTROL,
            "justify": "center",
            "padX": k.INSET_SM if (size == "sm" or content == "icon-only") else k.BTN_PADX,
        }
        if sel:
            o.update({"stroke": k.BORDER_SELECTED, "strokeWidth": k.THICK} if gated else p.SEL)
        elif hov:
            o["fill"] = k.HOVER
        if content == "icon-only":
            g = {
                "Ascending": k.icon("CMP-019 arrow-up", "arrow-up", ink),
                "Descending": k.icon("CMP-019 arrow-down", "arrow-down", ink),
            }.get(nm) or k.tglyph("−", ink, name="CMP-019 minus " "(text glyph)")
            seg = k.hbox(f"segment-{i + 1} · {nm}", [g], o, w=32, h=k.CONTROL_PX)
        else:
            seg = k.hbox(
                f"segment-{i + 1}",
                [k.text("label", label, k.LABEL if size == "sm" else k.BODY, ink)],
                o,
                h=k.CONTROL_PX,
            )
        if sel and state == "focus-visible":
            seg = k.focus_ring(seg, name="focus-ring on checked")
        segs.append(seg)
    o = {"fill": k.RAISED, "radius": k.R_CONTROL}
    if gated:
        o.update(k.T2_SHAPE)
        segs.insert(0, k.hbox("lock slot", [k.lock()], {"padX": k.INSET_XS}, h=k.CONTROL_PX))
    n = k.hbox("CMP-003 track" + (" · T2" if gated else ""), segs, o)
    if state == "disabled":
        n = p.dim(n)
    if gated:
        n = p.t2(k.t2_inline(n, k.say(p.READ_ONLY, "CMP-003")))
    return n


def cmp003() -> k.Node:
    rows = [
        k.state_row(
            c,
            [
                k.cell(
                    s,
                    segmented(s, content=c),
                    note="T2 2a" if s == "disabled-with-reason" else None,
                )
                for s in STATES5
            ],
        )
        for c in ("text", "icon-only")
    ]
    rows.append(
        k.state_row(
            "other axes",
            [
                k.cell("size sm", segmented("default", size="sm")),
                k.cell("Options 2", segmented("default", options=2)),
            ],
        )
    )
    return k.block(
        "CMP-003",
        rows,
        states=list(STATES5),
        proposed=["C2", "C3", "C14", "D5", "D13", "D17"],
        ruled=["#3925"],
        note=(
            "Sample options: the sort trio Ascending / Unsorted / Descending (icon-only: arrow-up, a "
            "minus text glyph, arrow-down); the checked option is segment-1."
        ),
        not_drawn=[
            "Options 6 (the spec gives no six sample labels: a copy gap)",
            "fullWidth",
            "size sm x every non-default State",
            "comfortable density",
        ],
    )


# --- CMP-004 Toggle.
def toggle(state: str, checked: bool, *, critical: bool = False, pos: str = "right") -> k.Node:
    """CMP-004: the 40 x 24 track + its label (Label Position right / left / hidden); Critical leads the label with the
    warning glyph (color.status.warning.strong) in type.ui.body-strong (D4, held)."""
    label = k.say("1-click arm" if critical else "Increase focus-ring thickness", "CMP-004")
    tr = p.track40(checked, state, critical=critical)
    if pos == "hidden":
        n = k.focus_ring(tr, radius=k.R_BADGE) if state == "focus-visible" else tr
        return k.hbox(
            "CMP-004 toggle · hidden", [n], {}, w=round(k.est_width(n)), h=round(k.est_height(n))
        )
    lead = (
        k.tglyph("⚠", k.STATUS["warning.strong"], name="CMP-019 warning (text glyph)")
        if critical
        else None
    )
    return p.labelled(
        tr,
        label,
        state,
        name=f"CMP-004 toggle · {'on' if checked else 'off'}",
        label_left=pos == "left",
        strong=critical,
        lead=lead,
        ring_radius=k.R_BADGE,
    )


def cmp004() -> k.Node:
    reason = k.say(p.READ_ONLY, "CMP-003")

    def c(s: str, on: bool) -> k.Node:
        n = toggle(s, on)
        if s == "disabled-with-reason":
            n = p.t2(k.t2_inline(n, reason))
        return k.cell(s, n, note="T2 2a" if s == "disabled-with-reason" else None)

    rows = [
        k.state_row("Checked=false", [c(s, False) for s in STATES5]),
        k.state_row(
            "Checked=true",
            [c(s, True) for s in ("default", "hover", "focus-visible", "disabled-with-reason")],
        ),
        k.state_row(
            "other axes",
            [
                k.cell("Critical=true · off", toggle("default", False, critical=True)),
                k.cell("Critical=true · on (armed)", toggle("default", True, critical=True)),
                k.cell("Label Position left", toggle("default", False, pos="left")),
                k.cell("Label Position hidden", toggle("default", False, pos="hidden")),
            ],
        ),
    ]
    return k.block(
        "CMP-004",
        rows,
        states=list(STATES5),
        proposed=["D3", "D4", "C4", "A3", "D13"],
        note=(
            "Off track color.text.tertiary, on color.action.primary.default, knob color.text.on-action; "
            "hover keeps the fill and adds a 1 px color.text.secondary outline. Critical (D4, held): the "
            "warning glyph leads a body-strong label; armed = color.status.warning.strong track with a "
            "color.text.inverse knob."
        ),
        not_drawn=[
            "Checked=true x disabled (derivable)",
            "Critical x every non-default State",
            "the critical confirm wrapper (D3: CMP-044, board 09)",
            "comfortable density",
        ],
    )


def main() -> int:
    blocks = [cmp001(), cmp002(), cmp003(), cmp004()]
    bd = k.board(
        NN,
        blocks,
        source="slice 1 §3 conventions 2-4, §6 decisions, §8 CMP-001 to CMP-004 L621-908",
        notes=[
            (
                "T2 (E09-D09 §2.2) replaces slice 1 §3's trailing lock and D13's dimmed plate in every gated "
                "cell; reasons are the slice's rbac strings (CMP-001 / CMP-003 accessible-name tables)."
            ),
            "Sample labels the spec does not give are named in the block notes; nothing is invented.",
        ],
    )
    path = k.KIT_DIR / f"{k.stem(NN)}.json"
    summary = k.write_sheet(path, bd)
    rep = k.compact_sheet(path)
    k.write_board_md(
        NN,
        bd,
        summary=summary,
        checks=[
            "every CMP-001 Variant x the seven States at md; sm / lg at default; buy / sell arrows in every cell",
            "CMP-002 four variants x five States, sizes, Pressed=true (incl. gated pressed, outline kept)",
            "CMP-003 text and icon-only x five States; size sm; Options 2",
            (
                "CMP-004 Checked=false x five States, Checked=true default / hover / focus / T2, Critical off / on, left, "
                "hidden"
            ),
            "T2 cells: lock leads, label + lock color.text.tertiary, reason in caption secondary",
        ],
    )
    print(summary)
    print(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
