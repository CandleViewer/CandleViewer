"""gen_05: E05-D02 / 05 text-inputs (slice 3: CMP-007, 008, 034, 040, 054, 065). Run: python3 -I -B gen/gen_05.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s3fields as f

import e05d02kit as k

Node = dict
NN = 5
ND_COMMON = [
    "every combination beyond the named cells",
    "comfortable density (only the height changes: 32)",
]


def cmp007() -> Node:
    cid = "CMP-007"
    v = [("value", "trader_01")]
    row1 = k.state_row(
        "Value=filled · Affix=none",
        [
            k.cell(
                s,
                f.well(s, v),
                note={
                    "disabled-with-reason": "T2: lock leads the value; reason line is CMP-040's",
                    "invalid": "2 px boundary; the message line is CMP-040's",
                    "focus-visible": "CMP-039 ring, boundary unchanged",
                }.get(s),
            )
            for s in f.WELL_STATES
        ],
    )
    row2 = k.state_row(
        "other axes (State=default)",
        [
            k.cell(
                "Value=empty",
                f.well("default", [("stub", "placeholder (CMP-007)", 64)]),
                note="placeholder in color.text.tertiary",
            ),
            k.cell(
                "Affix=both",
                f.well(
                    "default",
                    [("glyph", "⌕", "search"), ("value", "5", k.NUM_BASE), ("affix", "USDT")],
                ),
                note="leading search glyph, trailing unit",
            ),
        ],
    )
    return k.block(
        cid,
        [row1, row2],
        states=k.states(cid),
        proposed=["G1", "G2", "G4", "G23"],
        not_drawn=[k.not_drawn(cid), *ND_COMMON],
        note="Field box: conventions 21; states: 22; invalid: 23; T2 2a: 24.",
    )


def stepper(state: str, *, value: str = "5", unit: bool = False, at_max: bool = False) -> Node:
    cid = "CMP-008"
    t2 = state == "disabled-with-reason"
    parts: list = [("value", value, k.NUM_BASE)]
    if unit:
        parts.append(("affix", "%"))
    w = f.well(state, parts, cid=cid, w=96, justify="end")
    ink = k.TEXT_3 if t2 else k.TEXT_2
    minus = f.ghost_btn(f.glyph("−", "minus", ink), "CMP-002 [−] minus")
    plus = f.ghost_btn(f.glyph("+", "plus", ink), "CMP-002 [+] plus", opacity=at_max)
    o: dict = {"gap": k.INSET_XS}
    if state == "disabled":
        o["opacity"] = k.OP_DISABLED
        w = f.well("default", parts, cid=cid, w=96, justify="end")
    nm = f"CMP-008 stepper · {state}" + (" · T2" if t2 else "")
    return k.hbox(nm, [w, minus, plus], o)


def cmp008() -> Node:
    cid = "CMP-008"
    row1 = k.state_row(
        "Bound=none · Unit=false",
        [
            k.cell(
                s,
                stepper(s),
                note={
                    "disabled-with-reason": "T2: lock leads the value, [−] [+] tertiary",
                    "disabled": "whole component at opacity.disabled",
                }.get(s),
            )
            for s in f.WELL_STATES
        ],
    )
    row2 = k.state_row(
        "other axes (State=default)",
        [
            k.cell(
                "Bound=at-max",
                stepper("default", at_max=True),
                note="[+] plain disabled: availability, not T2",
            ),
            k.cell("Unit=true", stepper("default", unit=True), note='"5" with a "%" suffix'),
        ],
    )
    return k.block(
        cid,
        [row1, row2],
        states=k.states(cid),
        proposed=["G8", "G18", "G22", "G23"],
        not_drawn=[k.not_drawn(cid), *ND_COMMON],
        note="Value in type.num.base, end-aligned (conventions 27); [−] [+] ghost IconButtons outside the "
        "well, not tab stops.",
    )


def masked_box(revealed: bool) -> Node:
    """CMP-034's box: color.surface.raised, 1 px color.border.default (decorative), radius.control, inset.sm; the
    8-character mask in type.num.base color.text.secondary, or the value (S4 / S6: no sample value in the spec).
    """
    if revealed:
        kids = [f.stub("revealed value (CMP-034: no sample value; S4, S6)", 112, k.TEXT_1)]
    else:
        kids = [k.text("mask", "•", k.NUM_BASE, k.TEXT_2) for _ in range(8)]
    return k.hbox(
        "box" if not revealed else "box · revealed",
        kids,
        {
            "fill": k.RAISED,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CONTROL,
            "padX": k.INSET_SM,
            "height": k.CONTROL_H,
        },
        w=136,
        h=k.CONTROL_PX,
    )


def masked(state: str, *, copyable: bool = False) -> Node:
    revealed = state in ("revealed", "expiring")
    eye = f.ghost_btn(
        f.glyph("●" if revealed else "○", "eye-off" if revealed else "eye", k.TEXT_2),
        "CMP-002 toggle",
    )
    row = [masked_box(revealed), eye]
    if copyable:
        cp = (
            f.glyph("✓", "check", k.STATUS["success.default"])
            if state == "copied"
            else f.glyph("⧉", "copy", k.TEXT_2)
        )
        row.append(f.ghost_btn(cp, "CMP-033 copy"))
    top = k.hbox("row", row, {"gap": k.INSET_XS})
    kids = [top]
    if revealed:
        cd = "Hides in 8 s" if state == "revealed" else "Hides in 2 s"
        kids.append(k.text("countdown", k.say(cd, "CMP-034"), k.CAPTION, k.TEXT_3))
    return k.vbox(f"CMP-034 · {state}", kids, {"gap": k.STACK_XS})


def cmp034() -> Node:
    cid = "CMP-034"
    row = k.state_row(
        "Copyable=false",
        [
            k.cell(
                "masked", masked("masked"), note='toggle named "Show {label}" (label = API secret)'
            ),
            k.cell(
                "revealed",
                masked("revealed"),
                note='value in mono, toggle "Hide {label}" (label = API secret)',
            ),
            k.cell(
                "expiring",
                masked("expiring"),
                note='announced once: "Secret will hide in 2 seconds"',
            ),
        ],
    )
    row2 = k.state_row(
        "Copyable=true",
        [
            k.cell(
                "copied",
                masked("copied", copyable=True),
                note='CMP-033 copied: check glyph; "Copied" only in ' "its live region",
            ),
        ],
    )
    return k.block(
        cid,
        [row, row2],
        states=k.states(cid),
        proposed=["G19", "G20"],
        not_drawn=[k.not_drawn(cid), *ND_COMMON],
        note="S1-S7: every mount starts masked; the mask never tells the value's length; the revealed "
        "cell draws a stub bar, since the spec gives no sample value and a board never shows a "
        "secret-shaped string.",
    )


ROLE_SETTINGS = "Your role can't change settings."


def cmp040() -> Node:
    cid = "CMP-040"
    v = [("value", "trader_01")]
    ph = [("stub", "placeholder (CMP-007)", 64)]
    row1 = k.state_row(
        "Layout=stacked",
        [
            k.cell("default", f.field(f.well("default", v))),
            k.cell(
                "invalid",
                f.field(
                    f.well("invalid", ph),
                    state="invalid",
                    lines=[f.error_line("Enter your username.", cid)],
                ),
                note="glyph + words + 2 px boundary",
            ),
            k.cell(
                "disabled",
                f.field(f.well("default", v), state="disabled"),
                note="label, field and lines at " "opacity.disabled",
            ),
            k.cell(
                "disabled-with-reason",
                f.field(
                    f.well("disabled-with-reason", v),
                    state="disabled-with-reason",
                    lines=[f.reason(ROLE_SETTINGS, cid)],
                ),
                note="T2 2a: label unchanged, lock leads the value, rbac.permission reason",
            ),
            k.cell("read-only", f.field(f.well("read-only", v), state="read-only")),
        ],
    )
    row2 = k.state_row(
        "other axes (State=default)",
        [
            k.cell(
                "Help=true",
                f.field(
                    f.well("default", v),
                    lines=[
                        k.text("help", k.say("(rounded to nearest tick)", cid), k.CAPTION, k.TEXT_2)
                    ],
                ),
                note="CMP-100's help",
            ),
            k.cell(
                "Marker=optional",
                f.field(f.well("default", ph), lab="Display name", marker=True),
                note='"(optional)" in color.text.tertiary, no asterisk',
            ),
            k.cell(
                "Layout=inline",
                f.field(f.well("default", v), inline=True),
                note="label column, space.field.gap",
            ),
        ],
    )
    return k.block(
        cid,
        [row1, row2],
        states=k.states(cid),
        proposed=["G2", "G6", "G10", "G16", "G17", "G23"],
        not_drawn=[k.not_drawn(cid), *ND_COMMON],
        note="Each cell holds a CMP-007 child; lines in order reason, error, help, each stack.xs apart.",
    )


def search(state: str, filled: bool = False) -> Node:
    cid = "CMP-054"
    if filled:
        clear = f.ghost_btn(f.glyph("✕", "close", k.TEXT_2), "CMP-002 Clear search")
        return f.well(state, [("glyph", "⌕", "search"), ("value", "alex")], cid=cid, trail=clear)
    return f.well(
        state,
        [("glyph", "⌕", "search"), ("stub", "placeholder (CMP-054, the host's)", 72)],
        cid=cid,
    )


def cmp054() -> Node:
    cid = "CMP-054"
    row1 = k.state_row(
        "Value=empty",
        [k.cell(s, search(s)) for s in ("default", "hover", "focus-visible", "disabled")],
    )
    row2 = k.state_row(
        "Value=filled",
        [
            k.cell(
                "default",
                search("default", True),
                note='"alex" with the clear button ("Clear search"), flush',
            )
        ],
    )
    return k.block(
        cid,
        [row1, row2],
        states=k.states(cid),
        proposed=["G13"],
        not_drawn=[k.not_drawn(cid), *ND_COMMON],
        note='Named "Search users" through aria-label (G13); a placeholder is never its name.',
    )


def sec_field(state: str) -> Node:
    """A field inside the CMP-065 sample (its label and value are not in the spec: stubs)."""
    w = f.well(
        state, [("value", "5", k.NUM_BASE), ("affix", "%")], cid="CMP-008", w=96, justify="end"
    )
    return f.field(
        w,
        lab=None,
        state="default",
        name=f"field · {state}" + (" · T2" if "reason" in state else ""),
    )


def section(
    state: str, *, collapsible: bool = False, collapsed: bool = False, errors: bool = False
) -> Node:
    cid = "CMP-065"
    t2 = state == "disabled-with-reason"
    head: list = []
    if collapsible:
        head.append(
            f.glyph(
                "▸" if collapsed else "▾",
                "chevron-right" if collapsed else "chevron-down",
                k.TEXT_2,
            )
        )
    head.append(k.text("heading", k.say("Default SL/TP offsets", cid), k.HEADING_SM, k.TEXT_1))
    if errors:
        head += [
            f.glyph("⊘", "danger", k.STATUS["danger.strong"]),
            k.text("errors-within", k.say("2 problems", cid), k.CAPTION, k.TEXT_1),
        ]
    kids: list = [k.hbox("legend", head, {"gap": k.INSET_XS})]
    if not collapsed:
        kids.append(k.hbox("description", [f.stub("description (CMP-065)", 140, k.TEXT_2)], h=12))
        if t2:
            kids.append(f.reason(ROLE_SETTINGS, cid, w=200))
        fs = "disabled-with-reason" if t2 else "default"
        kids.append(k.vbox("fields", [sec_field(fs), sec_field(fs)], {"gap": k.STACK_MD}))
    o: dict = {"gap": k.STACK_XS}
    if state == "disabled":
        o["opacity"] = k.OP_DISABLED
        k._fallback("OPACITY")
    return k.vbox(f"CMP-065 section · {state}" + (" · T2" if t2 else ""), kids, o, w=208)


def cmp065() -> Node:
    cid = "CMP-065"
    row1 = k.state_row(
        "Collapsible=false",
        [
            k.cell(
                "default", section("default"), note="SCR-114's fieldset: description, two fields"
            ),
            k.cell("disabled", section("disabled"), note="plain, for everyone in the state"),
            k.cell(
                "disabled-with-reason",
                section("disabled-with-reason"),
                note="T2 one notice: every field's well led by the lock, no reason of its own",
            ),
        ],
    )
    row2 = k.state_row(
        "Collapsible=true",
        [
            k.cell("default (expanded)", section("default", collapsible=True)),
            k.cell("collapsed", section("collapsed", collapsible=True, collapsed=True)),
            k.cell(
                "errors-within",
                section("errors-within", collapsible=True, collapsed=True, errors=True),
                note='danger glyph + "2 problems" (proposed copy)',
            ),
        ],
    )
    return k.block(
        cid,
        [row1, row2],
        states=k.states(cid),
        proposed=["G14"],
        not_drawn=[k.not_drawn(cid), *ND_COMMON],
        note="A fieldset with no border or padding of its own; heading type.ui.heading-sm; fields "
        "stack.md apart.",
    )


def main() -> int:
    blocks = [cmp007(), cmp008(), cmp034(), cmp040(), cmp054(), cmp065()]
    bd = k.board(
        NN,
        blocks,
        cols=2,
        source="slice 3 (E05-D02-form-controls.md) §3 conventions 21-27, §7 CMP-007 "
        "L522-603, CMP-008 L604-670, CMP-034 L748-841, CMP-040 L842-912, "
        "CMP-054 L1184-1232, CMP-065 L1233-1286",
        notes=[
            (
                "T2 is 2a inline on every block (conventions 24): the lock leads the value inside the well, "
                "the label stays color.text.secondary, the reason sits under the field (CMP-040's line)."
            ),
            (
                "Copy gaps drawn as 6 px stub bars in the slot's ink: the placeholders, CMP-034's revealed "
                "value, CMP-065's description and field labels (the spec gives no string; never invented)."
            ),
            (
                "Glyphs: search ⌕, danger ⊘, minus −, plus +, eye ○ / eye-off ●, copy ⧉, check ✓, "
                "chevron-right ▸ / chevron-down ▾, close ✕ are text glyphs; the lock is the local icon."
            ),
            (
                "Bare invalid wells (CMP-007, CMP-008) draw only the 2 px boundary: the danger glyph + words "
                "live in the host's CMP-040 message line (conventions 23), drawn on CMP-040 invalid."
            ),
            (
                f"Field width {f.FIELD_W} px (stepper and section fields 96 px): an author choice; the spec "
                "sizes fields by their host."
            ),
        ],
    )
    path = k.KIT_DIR / f"{k.stem(NN)}.json"
    print(k.write_sheet(path, bd))
    rep = k.compact_sheet(path)
    print(rep)
    k.write_board_md(
        NN,
        bd,
        checks=[
            (
                "every cell the six Variants x States paragraphs / tables name is drawn once (CMP-007 9, CMP-008 9, "
                "CMP-034 4, CMP-040 8, CMP-054 5, CMP-065 6)"
            ),
            (
                "T2 cells: lock first in the well, value color.text.tertiary, label color.text.secondary, reason "
                "type.ui.caption color.text.secondary; no color.text.disabled / opacity.disabled on a T2 path (write_sheet)"
            ),
            "invalid: 2 px color.status.danger.default boundary + danger glyph + words (CMP-040's line)",
            "no inst node; only the local locked icon (close ✕ is a text glyph)",
        ],
        live=[
            "the 1 px color.text.tertiary well boundary reads on the color.surface.app plate",
            "CMP-008 at-max: only [+] is dimmed",
        ],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
