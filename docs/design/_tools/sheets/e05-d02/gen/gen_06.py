"""gen_06: E05-D02 / 06 pickers-and-gates (slice 3: CMP-009, 047, 048, 079). Run: python3 -I -B gen/gen_06.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import e05d02kit as k
import s3fields as f

Node = dict
NN = 6
ND_COMMON = [
    "every combination beyond the named cells",
    "comfortable density (only the height changes: 32)",
]
VIEW_AS = "Read-only while viewing as alex."
ACCOUNT_RO = "You can view this account, not trade it."


def trigger(state: str, parts: list, *, up: bool = False, cid: str = "CMP-009") -> Node:
    """CMP-009's trigger: the CMP-007 well with the value or placeholder and a trailing decorative chevron-down in
    color.text.secondary (chevron-up when open)."""
    ink = k.TEXT_3 if state == "disabled-with-reason" else k.TEXT_2
    chev = f.glyph("▴" if up else "▾", "chevron-up" if up else "chevron-down", ink)
    return f.well(
        state,
        parts,
        cid=cid,
        trail=k.hbox("chevron", [chev], {"justify": "center"}, w=k.CONTROL_PX, h=k.CONTROL_PX),
    )


def cmp009() -> Node:
    cid = "CMP-009"
    v = [("value", "sub_001")]
    row1 = k.state_row(
        "Value=selected",
        [
            k.cell(
                s,
                (
                    k.vbox("T2 2a", [trigger(s, v), f.reason(ACCOUNT_RO, cid)], {"gap": k.STACK_XS})
                    if s == "disabled-with-reason"
                    else trigger(s, v)
                ),
                note={
                    "disabled-with-reason": "T2 2a: lock leads the value; reason under the field (rbac.account_read_only, "
                    "the open cell's key: the spec names none for the trigger)",
                    "invalid": "2 px boundary; the message line is CMP-040's",
                }.get(s),
            )
            for s in (
                "default",
                "hover",
                "focus-visible",
                "invalid",
                "disabled",
                "disabled-with-reason",
            )
        ],
    )
    lst = f.popup(
        [
            f.option([f.stub("option label (rest)", 56, k.TEXT_1)], "rest"),
            f.option([f.stub("option label (active)", 56, k.TEXT_1)], "active"),
            f.option([f.opt_text("sub_001", cid)], "selected"),
            f.option([f.stub("option label (plain disabled)", 56, k.TEXT_1)], "disabled"),
            f.option([f.opt_text("sub_002", cid, k.TEXT_3)], "T2", second=ACCOUNT_RO),
        ],
        name="listbox",
    )
    opened = k.vbox("CMP-009 · open", [trigger("default", v, up=True), lst], {"gap": k.INSET_XS})
    tif = f.popup(
        [
            f.option([f.opt_text("IOC", cid)], "selected"),
            f.option(
                [f.opt_text("FOK", cid)], "validity", second="Market orders are always IOC on Bybit"
            ),
        ],
        name="CMP-231 sample listbox",
    )
    searchable = k.vbox(
        "CMP-009 · searchable open",
        [
            f.well(
                "focus-visible", [("value", "sub_001"), k.rect("caret", 1, 14, k.TEXT_1)], cid=cid
            ),
            f.popup([f.option([f.opt_text("sub_001", cid)], "selected")], name="listbox"),
        ],
        {"gap": k.INSET_XS},
    )
    row2 = k.state_row(
        "open and other axes",
        [
            k.cell(
                "open",
                opened,
                note="five option looks: rest, active, selected (check), plain disabled, T2",
            ),
            k.cell(
                "open — validity sample",
                tif,
                note="CMP-231 under a market order: FOK in the validity look, no "
                "lock (documentation sample)",
            ),
            k.cell(
                "Value=placeholder",
                trigger("default", [("placeholder", "Choose…")]),
                note='"Choose…" in color.text.tertiary',
            ),
            k.cell(
                "Searchable=true (open)",
                searchable,
                note="CMP-048's editable input in the trigger (G9)",
            ),
        ],
    )
    return k.block(
        cid,
        [row1, row2],
        states=k.states(cid),
        proposed=["G3", "G7", "G9", "G23"],
        not_drawn=[k.not_drawn(cid), *ND_COMMON],
        note="Trigger: the CMP-007 well, chevron decorative; listbox: conventions 26 (overlay, "
        "elevation.popover, rows size.row.height).",
    )


def cal_btn(state: str) -> Node:
    """The DatePicker's calendar button: a CMP-002 ghost IconButton flush in the well's end (conventions 21)."""
    return f.ghost_btn(
        f.cal_glyph(k.TEXT_3 if state == "disabled-with-reason" else k.TEXT_2),
        "CMP-002 Choose date",
    )


def date_well(state: str, value: str = "2026-10-23", *, btn: bool = True, w: int = 156) -> Node:
    parts = [("value", value, k.NUM_BASE), ("affix", "UTC")]
    return f.well(state, parts, cid="CMP-047", w=w, trail=cal_btn(state) if btn else None)


DAY = 28  # a 24 px day cell (size.control.height) in a 28 px slot: 4 px between cells, room for the focus ring


def day(n: int | None, look: str = "plain") -> Node:
    """One day slot: blank (other months), plain, today (1 px color.text.tertiary ring inside), selected / range end
    (color.action.selected, 2 px inner color.border.selected), in-range (color.surface.selected), out (the number at
    opacity.disabled), focused (the CMP-039 ring at the slot's edge)."""
    if n is None:
        return k.box("blank", [], w=DAY, h=DAY)
    num = k.text("n", str(n) if n < 10 else k.say(str(n), "CMP-047"), k.NUM_BASE, k.TEXT_1)
    if look == "plain":
        return k.hbox(f"d{n}", [num], {"justify": "center"}, w=DAY, h=DAY)
    o: dict = {"justify": "center", "radius": k.R_CONTROL}
    if look == "today":
        o.update(stroke=k.TEXT_3, strokeWidth=k.HAIRLINE, strokeAlign="inner")
    elif look == "selected":
        o.update(
            fill=k.ACTION["selected"],
            stroke=k.BORDER_SELECTED,
            strokeWidth=k.THICK,
            strokeAlign="inner",
        )
    elif look == "in-range":
        o["fill"] = k.SELECTED
    elif look == "out":
        o["opacity"] = k.OP_DISABLED
        k._fallback("OPACITY")
    cell_ = k.hbox(f"day {n} · {look}", [num], o, w=k.CONTROL_PX, h=k.CONTROL_PX)
    kids = [cell_]
    if look == "focused":
        k._choice("focus")
        k._fallback("RING")
        kids.append(
            k.place(
                k.rect(
                    "ring",
                    DAY,
                    DAY,
                    o={
                        "stroke": k.FOCUS_RING,
                        "strokeWidth": k.FOCUS_W,
                        "radius": k.R_RING,
                        "strokeAlign": "inner",
                    },
                ),
                0,
                0,
            )
        )
    return k.hbox(f"slot {n}", kids, {"justify": "center"}, w=DAY, h=DAY)


def week(days: list, name: str) -> Node:
    return k.hbox(name, days, w=7 * DAY, h=DAY)


def weekday_row() -> Node:
    return k.hbox(
        "weekday row",
        [
            k.hbox(
                f"weekday {i}",
                [f.stub("weekday abbreviation (CMP-047)", 12, k.TEXT_3)],
                {"justify": "center"},
                w=DAY,
                h=16,
            )
            for i in range(1, 8)
        ],
        w=7 * DAY,
        h=16,
    )


def calendar(weeks: list, *, caption: bool = True) -> Node:
    """The dialog (conventions 26's surface, padding space.inset.md): a header with the month between two ghost
    IconButtons, the weekday row (Monday first), the grid, the caption."""
    head = k.hbox(
        "header",
        [
            f.ghost_btn(f.glyph("◂", "chevron-left", k.TEXT_2), "CMP-002 previous month"),
            k.text("month", k.say("October 2026", "CMP-047"), k.HEADING_SM, k.TEXT_1),
            f.ghost_btn(f.glyph("▸", "chevron-right", k.TEXT_2), "CMP-002 next month"),
        ],
        {"justify": "space-between"},
        w=7 * DAY,
    )
    kids = [head, weekday_row(), *weeks]
    if caption:
        kids.append(
            k.text(
                "caption",
                k.say("Recorded history: 2026-09-01 – today", "CMP-047"),
                k.CAPTION,
                k.TEXT_2,
                w=7 * DAY,
            )
        )
    return k.vbox(
        "dialog",
        kids,
        {
            "fill": k.OVERLAY,
            "shadow": k.E_POPOVER,
            "radius": k.R_CARD,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "pad": k.INSET_MD,
            "gap": k.STACK_XS,
        },
    )


def october(look_of) -> list:
    """October 2026, Monday first: the 1st is a Thursday (three blanks), 31 days, five weeks."""
    slots: list = [None, None, None] + list(range(1, 32))
    slots += [None] * (35 - len(slots))
    return [
        week(
            [day(n, look_of(n)) if n else day(None) for n in slots[i : i + 7]], f"week {i // 7 + 1}"
        )
        for i in range(0, 35, 7)
    ]


def cmp047() -> Node:
    cid = "CMP-047"
    cells = []
    for s in (
        "default",
        "hover",
        "focus-visible",
        "invalid",
        "disabled",
        "disabled-with-reason",
        "read-only",
    ):
        w = date_well(s)
        if s == "invalid":
            w = k.vbox(
                "field · invalid",
                [w, f.error_line("Nothing is recorded for that window.", cid, 156)],
                {"gap": k.STACK_XS},
            )
            note = "14:2096's message on CMP-040's line"
        elif s == "disabled-with-reason":
            w = k.vbox(
                "T2 2a",
                [w, f.reason("Your role can't control replay.", cid, 156)],
                {"gap": k.STACK_XS},
            )
            note = "T2 2a: SCR-098's range for a viewer; the button shares the reason"
        else:
            note = None
        cells.append(k.cell(s, w, note=note))
    row1 = k.state_row("Mode=single · Time=false", cells)
    looks = {27: "today", 23: "selected", 24: "focused", 28: "out", 29: "out", 30: "out", 31: "out"}
    opened = k.vbox(
        "CMP-047 · open",
        [date_well("default"), calendar(october(lambda n: looks.get(n, "plain")))],
        {"gap": k.INSET_XS},
    )
    start = f.field(
        date_well("default", "2026-10-01", btn=False, w=120), lab="Start", lab_cid=cid, name="Start"
    )
    end = f.field(date_well("default", "2026-10-07", w=148), lab="End", lab_cid=cid, name="End")
    rng = k.hbox("CMP-047 · range", [start, end], {"gap": k.INSET_SM, "align": "start"})
    rlooks = {
        1: "selected",
        2: "in-range",
        3: "in-range",
        4: "in-range",
        5: "in-range",
        6: "in-range",
        7: "in-range",
    }
    weeks = [
        week(
            [day(None), day(None), day(None)]
            + [day(n, rlooks.get(n, "plain")) for n in range(1, 5)],
            "week 1",
        ),
        week([day(n, rlooks.get(n, "plain")) for n in range(5, 12)], "week 2"),
    ]
    rng_open = k.vbox(
        "CMP-047 · range open",
        [
            k.hbox(
                "fields",
                [
                    f.field(
                        date_well("default", "2026-10-01", btn=False, w=120),
                        lab="Start",
                        lab_cid=cid,
                        name="Start",
                    ),
                    f.field(
                        f.well(
                            "focus-visible",
                            [("placeholder", "YYYY-MM-DD")],
                            cid=cid,
                            w=148,
                            trail=cal_btn("default"),
                        ),
                        lab="End",
                        lab_cid=cid,
                        name="End",
                    ),
                ],
                {"gap": k.INSET_SM, "align": "start"},
            ),
            calendar(weeks, caption=False),
        ],
        {"gap": k.INSET_XS},
    )
    timed = k.hbox(
        "CMP-047 · time",
        [
            date_well("default"),
            f.well("default", [("value", "14:05", k.NUM_BASE), ("affix", "UTC")], cid=cid, w=88),
        ],
        {"gap": k.INSET_XS},
    )
    row2 = k.state_row(
        "open and other axes",
        [
            k.cell(
                "open",
                opened,
                note="October 2026: today 27 (ring), selected 23, focused 24; 28-31 after max "
                "(today) at opacity.disabled",
            ),
            k.cell("Mode=range", rng, note="Start and End, one calendar button on End"),
            k.cell(
                "Mode=range, open",
                rng_open,
                note="start 1 picked, end pending, band 2-7 under the pointer's day "
                "(first two weeks shown)",
            ),
            k.cell("Time=true", timed, note='"14:05" beside the date; typed only'),
        ],
    )
    return k.block(
        cid,
        [row1, row2],
        states=k.states(cid),
        proposed=["G3", "G5", "G11", "G23"],
        not_drawn=[
            k.not_drawn(cid),
            *ND_COMMON,
            "Mode=range, open: weeks 3-5 of October (the band and the ends are in weeks 1-2)",
        ],
        note="Day cells size.control.height square; selected and range ends on #3925's selected role "
        "(G3); weeks start Monday (G11); every value UTC.",
    )


def result(look: str, rest: Node) -> Node:
    """A Combobox result: the matched "BTC" in type.ui.body-strong (weight, not colour), the rest in type.ui.body."""
    return f.option([f.opt_text("BTC", "CMP-048", typo=k.BODY_STRONG), rest], look, cid="CMP-048")


def cmp048() -> Node:
    cid = "CMP-048"
    v = [("value", "BTC")]
    cells = []
    for s in ("default", "hover", "focus-visible", "invalid", "disabled", "disabled-with-reason"):
        w = f.well(s, v, cid=cid)
        note = None
        if s == "disabled-with-reason":
            w = k.vbox("T2 2a", [w, f.reason(VIEW_AS, cid)], {"gap": k.STACK_XS})
            note = "T2 2a: a rule's metric picker while viewing as (rbac.view_as)"
        elif s == "invalid":
            note = "2 px boundary; the message line is CMP-040's"
        cells.append(k.cell(s, w, note=note))
    row1 = k.state_row("closed", cells)
    inp = f.well("focus-visible", v, cid=cid)
    opened = k.vbox(
        "CMP-048 · open",
        [
            inp,
            f.popup(
                [
                    result("rest", f.opt_text("USDT", cid)),
                    result("active", f.stub("result remainder (CMP-048)", 40, k.TEXT_1)),
                    result("rest", f.stub("result remainder (CMP-048)", 48, k.TEXT_1)),
                ],
                name="listbox",
            ),
        ],
        {"gap": k.INSET_XS},
    )

    def with_status(kids: list, nm: str) -> Node:
        return k.vbox(
            nm,
            [f.well("focus-visible", v, cid=cid), f.popup([f.status_row(kids)], name="listbox")],
            {"gap": k.INSET_XS},
        )

    loading = with_status(
        [
            k.spinner(12, k.TEXT_2, name="CMP-014 spinner sm"),
            k.text("words", k.say("Searching…", cid), k.BODY, k.TEXT_2),
        ],
        "CMP-048 · loading",
    )
    nores = k.vbox(
        "CMP-048 · no-results",
        [
            f.well("focus-visible", [("value", "xyz")], cid=cid),
            f.popup(
                [
                    f.status_row(
                        [
                            k.text(
                                "words",
                                k.say("No USDT perpetual matches 'xyz'.", cid),
                                k.BODY,
                                k.TEXT_2,
                                w=f.FIELD_W - 16,
                            )
                        ]
                    )
                ],
                name="listbox",
            ),
        ],
        {"gap": k.INSET_XS},
    )
    failed = with_status(
        [
            f.glyph("⊘", "danger", k.STATUS["danger.strong"]),
            k.text("words", k.say("catalogue load failed", cid), k.BODY, k.TEXT_2),
        ],
        "CMP-048 · search-failed",
    )
    row2 = k.state_row(
        "open",
        [
            k.cell(
                "open",
                opened,
                note='three results, the second active; "BTC" matched in body-strong',
            ),
            k.cell("loading", loading, note='CMP-014 sm + "Searching…" (CMP-038)'),
            k.cell("no-results", nores, note="14:979's sentence"),
            k.cell("search-failed", failed, note="danger glyph + the host's sentence (SCR-102)"),
        ],
    )
    return k.block(
        cid,
        [row1, row2],
        states=k.states(cid),
        proposed=["G9", "G17", "G23"],
        not_drawn=[k.not_drawn(cid), *ND_COMMON],
        note="Input: the CMP-007 well; results: conventions 26; status rows type.ui.body "
        "color.text.secondary.",
    )


def gate_field(state: str, lines: list | None = None) -> Node:
    return f.field(f.well(state, [("value", "trader_01")]), state=state, lines=lines)


def cmp079() -> Node:
    cid = "CMP-079"
    ib = k.hbox(
        "CMP-002 row action",
        [f.glyph("⋮", "more", k.TEXT_3)],
        {"justify": "center", "radius": k.R_CONTROL, **k.T2_SHAPE},
        w=k.CONTROL_PX,
        h=k.CONTROL_PX,
    )
    tip = k.vbox(
        "T2 2b",
        [
            k.lock_badge(ib),
            k.tooltip(k.say("Only the owner can change account settings.", cid), w=180),
        ],
        {"gap": k.STACK_XS},
    )
    notice = k.vbox(
        "CMP-065 section · notice · T2",
        [
            k.text("heading", k.say("Default SL/TP offsets", "CMP-065"), k.HEADING_SM, k.TEXT_1),
            f.reason("Your role can't change settings.", "CMP-065", w=200),
            k.vbox(
                "fields",
                [gate_field("disabled-with-reason"), gate_field("disabled-with-reason")],
                {"gap": k.STACK_MD},
            ),
        ],
        {"gap": k.STACK_XS},
    )
    row = k.state_row(
        "Form",
        [
            k.cell("Allowed=true", gate_field("default"), note="T1: the CMP-040 field unchanged"),
            k.cell(
                "Allowed=false · inline",
                gate_field("disabled-with-reason", [f.reason(VIEW_AS, cid)]),
                note="T2 2a: label unchanged, lock leads the value",
            ),
            k.cell(
                "Allowed=false · tooltip",
                tip,
                note="T2 2b: CMP-049 row-action IconButton, lock badge, CMP-016 "
                "echo on hover and focus (rbac.owner_only)",
            ),
            k.cell(
                "Allowed=false · notice",
                notice,
                note="one notice, two fields pointing at it; each well led by the "
                "lock, no reason of its own",
            ),
        ],
    )
    return k.block(
        cid,
        [row],
        states=["Allowed=true", "inline", "tooltip", "notice"],
        proposed=["G15", "G23"],
        not_drawn=[
            k.not_drawn(cid),
            *ND_COMMON,
            "the sentence form (CMP-026 with cta omitted, D09 §8): not this component",
        ],
        note="A behavioural wrapper with no anatomy of its own: the T2 look is the wrapped control's "
        "(conventions 24).",
    )


def main() -> int:
    blocks = [cmp009(), cmp047(), cmp048(), cmp079()]
    bd = k.board(
        NN,
        blocks,
        cols=2,
        source="slice 3 (E05-D02-form-controls.md) §3 conventions 21-27, §7 CMP-009 "
        "L671-747, CMP-047 L913-1003, CMP-048 L1004-1065, CMP-079 L1287-1332",
        notes=[
            (
                "T2 is 2a inline (conventions 24) on CMP-009 / 047 / 048 and CMP-079 inline; CMP-079 draws "
                "Allowed=false in its three forms (inline, tooltip = 2b, notice) and Allowed=true once."
            ),
            (
                "Popups: conventions 26 (color.surface.overlay, elevation.popover, radius.card, 1 px "
                "color.border.default, rows size.row.height); option looks: rest, active, selected (check "
                "glyph), plain disabled, validity (label only dimmed, no lock), T2 (lock + tertiary label + "
                "reason line)."
            ),
            (
                "Copy gaps drawn as 6 px stub bars in the slot's ink: CMP-009's rest / active / disabled "
                "option labels, CMP-048's result remainders, CMP-047's weekday abbreviations (the spec gives "
                "only sub_001, sub_002, BTCUSDT and the full weekday names)."
            ),
            (
                "CMP-047 open: today drawn as 27 October 2026 (the board's date) and 28-31 out of range after "
                "max = today, the caption's bound ('Recorded history: 2026-09-01 – today'); the spec's "
                "'days before min' has no October day under that caption (author choice)."
            ),
            (
                "Bare invalid wells (CMP-009, CMP-048 closed) draw only the 2 px boundary: the danger "
                "glyph + words live in the host's CMP-040 message line (conventions 23); drawn on CMP-047 "
                "invalid and CMP-048 search-failed."
            ),
            (
                "Glyphs: chevron-down ▾ / up ▴ / left ◂ / right ▸, check ✓, danger ⊘, more ⋮ are text "
                "glyphs; calendar is primitives; the lock is the local icon."
            ),
        ],
    )
    path = k.KIT_DIR / f"{k.stem(NN)}.json"
    print(k.write_sheet(path, bd))
    print(k.compact_sheet(path))
    k.write_board_md(
        NN,
        bd,
        checks=[
            "every named cell drawn once: CMP-009 9 (+ the CMP-231 validity sample), CMP-047 11, CMP-048 10, CMP-079 4",
            (
                "T2: lock first in the well / option, value or label color.text.tertiary, reason type.ui.caption "
                "color.text.secondary; no color.text.disabled / opacity.disabled on a T2 path (write_sheet)"
            ),
            "status rows never colour alone: danger glyph + words; loading = spinner + words",
            "no inst node; only the local locked icon",
        ],
        live=[
            "the popups' elevation.popover shadow and 1 px edge read on the color.surface.app plate",
            "CMP-047's today ring (1 px color.text.tertiary) and the focused day's ring both read at 1x",
        ],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
