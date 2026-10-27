"""gen_07: E05-D02 / 07 table — CMP-049 Table, the spec's ten named cells (slice 3 L1066-1183), dark, compact.

Run: python3 -I -B gen/gen_07.py   (writes 07-table.json / .md beside the kit, validates, compacts into ../E05-D02-v4/)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e05d02kit as k

CID = "CMP-049"
NN = 7
ROW = k.CONTROL_PX  # size.row.height, compact (24)


def s(chars: str) -> str:
    """A specimen string from CMP-049's section (else slice 3)."""
    return k.say(chars, CID)


# Columns: (key, label, width, align, sort) — sort: "desc" (arrow-down), "none" (sortable, unsorted), None (static).
COLS = [
    ("name", "Name", 112, "start", "none"),
    ("role", "Role", 96, "start", None),
    ("value", "Value", 72, "end", "desc"),
]
SEL_W, ACT_W = (
    24,
    40,
)  # select column: the cell size.control.height wide; actions column: a 24 px IconButton + inset


def rows_data() -> list[tuple[str, str, str]]:
    """Three records, sorted by Value descending (the sorted column). Every string is the spec's (copy gap logged)."""
    k.gap(
        "CMP-049 names no sample records: the rows draw the section's own words (alex, slice 3's trader_01, the "
        "roles owner / manager / viewer of E42-D03's users.empty line) and three numbers the section itself "
        "cites (4.83, 4.79, 1.24) as the mono end-aligned numeric column; the third record's name is the em dash "
        "(no value) — never an invented name"
    )
    return [
        (s("trader_01"), s("manager"), s("4.83")),
        ("—", s("viewer"), s("4.79")),
        (s("alex"), s("owner"), s("1.24")),
    ]


def sort_glyph(sort: str | None) -> k.Node | None:
    """The sort slot after the label: arrow-down (descending), a neutral pair (sortable, unsorted), or CMP-014 sm
    (sortPending)."""
    if sort == "desc":
        return k.icon("CMP-019 arrow-down · sorted descending", "arrow-down", k.TEXT_3)
    if sort == "none":
        return k.hbox(
            "CMP-019 sort neutral (text glyphs)",
            [
                k.tglyph("▴", k.TEXT_3, k.CAPTION, name="up"),
                k.tglyph("▾", k.TEXT_3, k.CAPTION, name="down"),
            ],
        )
    if sort == "pending":
        return k.spinner(12, k.TEXT_3, name="CMP-014 sm · sortPending")
    return None


def th(label: str, w: int, align: str, sort: str | None) -> k.Node:
    """A header cell: label type.ui.label color.text.primary, the sort glyph after it at inset.xs."""
    kids = [k.text("label", s(label), k.LABEL, k.TEXT_1), sort_glyph(sort)]
    return k.hbox(
        f"th · {label}",
        kids,
        {"padX": k.INSET_SM, "gap": k.INSET_XS, "justify": "end" if align == "end" else "start"},
        w=w,
        h=ROW,
    )


def th_empty(name: str, w: int, kid: k.Node | None = None) -> k.Node:
    """A header cell with no label (the actions column) or holding the select-all box."""
    return k.hbox(name, [kid] if kid else [], {"justify": "center"}, w=w, h=ROW)


def header(sort_value: str = "desc", *, sel: k.Node | None = None, actions: bool = False) -> k.Node:
    """The sticky header row: color.surface.hover fill, a 1 px color.border.subtle rule under it."""
    cells: list[k.Node | None] = [th_empty("th · select all", SEL_W, sel) if sel else None]
    for _key, label, w, align, sort in COLS:
        cells.append(th(label, w, align, sort_value if sort == "desc" else sort))
    if actions:
        cells.append(th_empty("th · actions", ACT_W))
    width = table_w(sel is not None, actions)
    row = k.hbox("header row", cells, {"fill": k.HOVER}, w=width, h=ROW)
    rule = k.rect("rule · color.border.subtle", width, 1, k.BORDER_SUBTLE)
    return k.vbox("header", [row, rule], w=width)


def table_w(sel: bool = False, actions: bool = False) -> int:
    """The table's width: the three columns, plus the select / actions columns in grid mode."""
    return sum(c[2] for c in COLS) + (SEL_W if sel else 0) + (ACT_W if actions else 0)


def td(chars: str, w: int, align: str, typo: str, color: str, *, ring: bool = False) -> k.Node:
    """A body cell: padding-inline inset.sm; ring=True draws CMP-039 on the focused cell (inside its edge)."""
    kids: list[k.Node | None] = [k.text("value", chars, typo, color)]
    if ring:
        k.LOG.add(
            "deviations",
            "CMP-049 grid: the focused cell's CMP-039 ring is drawn on the cell's edge (rows "
            "abut, so a ring 2 px outside would be cut by the next row; slice 4 H8's inset "
            "ring is the same open question for scrolled containers)",
        )
        kids.append(
            k.place(
                k.rect(
                    "focus-ring (inset)",
                    w,
                    ROW,
                    o={
                        "stroke": k.FOCUS_RING,
                        "strokeWidth": k.FOCUS_W,
                        "radius": k.R_CONTROL,
                        "strokeAlign": "inner",
                    },
                ),
                0,
                0,
            )
        )
    return k.hbox(
        f"td · {chars}",
        kids,
        {"padX": k.INSET_SM, "justify": "end" if align == "end" else "start"},
        w=w,
        h=ROW,
    )


def checkbox(state: str) -> k.Node:
    """CMP-005 at 16 px: checked / mixed on color.action.primary.default (#3925, s3 G3), unchecked a 1 px outline."""
    if state == "unchecked":
        return k.rect(
            "CMP-005 checkbox · unchecked",
            16,
            16,
            o={"stroke": k.BORDER_STRONG, "strokeWidth": k.HAIRLINE, "radius": k.R_CONTROL},
        )
    glyph = "✓" if state == "checked" else "−"
    return k.hbox(
        f"CMP-005 checkbox · {state}",
        [
            k.tglyph(
                glyph,
                k.TEXT_ON_ACTION,
                k.CAPTION,
                name=f"CMP-019 {'check' if glyph == '✓' else 'minus'}" " (text glyph)",
            )
        ],
        {"fill": k.ACTION["primary"], "radius": k.R_CONTROL, "justify": "center"},
        w=16,
        h=16,
    )


def icon_button(*, state: str = "default", name: str = "CMP-002 ghost · more-horizontal") -> k.Node:
    """CMP-002 ghost more-horizontal, 24 x 24 (the actions cell's button; open = color.surface.selected)."""
    o: dict = {"justify": "center", "radius": k.R_CONTROL}
    ink = k.TEXT_2
    if state == "open":
        o["fill"] = k.SELECTED
        ink = k.TEXT_1
    if state == "T2":
        o.update(k.T2_SHAPE)
        ink = k.TEXT_3
    return k.hbox(
        name,
        [k.tglyph("…", ink, k.BODY_STRONG, name="CMP-019 more-horizontal (text glyph)")],
        o,
        w=k.CONTROL_PX,
        h=k.CONTROL_PX,
    )


ZEBRA = (k.CANVAS, k.RAISED)  # odd color.surface.canvas, even color.surface.raised (E11-D04 §2)


def body_row(
    i: int,
    rec: tuple[str, str, str],
    *,
    fill: str | None = None,
    sel: str | None = None,
    actions: str | None = None,
    ring_col: str | None = None,
) -> k.Node:
    """Body row i (0-based): zebra fill unless fill= (hover / selected); sel= a checkbox state; actions= the actions
    cell's IconButton state; ring_col= the focused cell's column key."""
    cells: list[k.Node | None] = []
    if sel:
        cells.append(k.hbox("td · select", [checkbox(sel)], {"justify": "center"}, w=SEL_W, h=ROW))
    looks = {
        "name": (k.BODY, k.TEXT_1),
        "role": (k.BODY, k.TEXT_2),
        "value": (k.NUM_BASE, k.TEXT_1),
    }
    for (key, _label, w, align, _sort), chars in zip(COLS, rec, strict=True):
        typo, color = looks[key]
        cells.append(td(chars, w, align, typo, color, ring=ring_col == key))
    if actions:
        cells.append(
            k.hbox(
                "td · actions", [icon_button(state=actions)], {"justify": "center"}, w=ACT_W, h=ROW
            )
        )
    width = table_w(sel is not None, actions is not None)
    return k.hbox(f"row {i + 1}", cells, {"fill": fill or ZEBRA[i % 2]}, w=width, h=ROW)


def table(
    rows: list[k.Node],
    *,
    sort_value: str = "desc",
    sel: k.Node | None = None,
    actions: bool = False,
    name: str = "CMP-049 table",
) -> k.Node:
    """The table: the header row, then the body."""
    return k.vbox(
        name,
        [header(sort_value, sel=sel, actions=actions), *rows],
        w=table_w(sel is not None, actions),
    )


def populated(*, sort_value: str = "desc", hover: bool = True) -> k.Node:
    """Mode=table, Selection=none: zebra rows, one hovered row (the third), no in-row controls."""
    data = rows_data()
    rows = [body_row(i, r, fill=k.HOVER if hover and i == 2 else None) for i, r in enumerate(data)]
    return table(
        rows,
        sort_value=sort_value,
        name="CMP-049 table · " + ("sorting" if sort_value == "pending" else "populated"),
    )


def skeleton_row(i: int) -> k.Node:
    """A CMP-015 skeleton row: per column a size.icon tall block on color.surface.hover, radius.control; rows abut."""
    cells = []
    for _key, label, w, align, _sort in COLS:
        bar = k.rect(
            "CMP-015 block",
            round((w - 16) * (0.6 if align == "end" else 0.8)),
            k.PX[k.ICON],
            k.HOVER,
            o={"radius": k.R_CONTROL},
        )
        cells.append(
            k.hbox(
                f"td · {label} skeleton",
                [bar],
                {"padX": k.INSET_SM, "justify": "end" if align == "end" else "start"},
                w=w,
                h=ROW,
            )
        )
    return k.hbox(
        f"CMP-015 skeleton row {i + 1}", cells, {"fill": ZEBRA[i % 2]}, w=table_w(), h=ROW
    )


def loading() -> k.Node:
    """The header kept; skeleton rows; the caption's loading words (type.ui.label color.text.secondary)."""
    cap = k.text("caption · loading", s("Loading 5,000 bars…"), k.LABEL, k.TEXT_2)
    return k.vbox(
        "CMP-049 table · loading",
        [cap, table([skeleton_row(i) for i in range(3)])],
        {"gap": k.STACK_XS},
        w=table_w(),
    )


def state_panel(name: str, glyph: k.Node, line: k.Node, action: k.Node | None = None) -> k.Node:
    """CMP-026 / CMP-027's block across every column: centred, padding inset.xl, gaps stack.sm then stack.md."""
    top = k.vbox("glyph and line", [glyph, line], {"gap": k.STACK_SM, "align": "center"})
    kids = [top, action]
    return k.vbox(
        name, kids, {"pad": k.INSET_XL, "gap": k.STACK_MD, "align": "center"}, w=table_w()
    )


def empty() -> k.Node:
    """The header kept; CMP-026 no-data across every column."""
    w = table_w() - 2 * k.PX[k.INSET_XL]
    panel = state_panel(
        "CMP-026 empty-state · no-data",
        k.tglyph("○", k.TEXT_3, k.HEADING_LG, name="CMP-019 lg (text glyph)"),
        k.text(
            "description",
            s("You're the only user. Invite a manager or viewer to delegate."),
            k.BODY,
            k.TEXT_2,
            w=w,
            align="center",
        ),
    )
    return table([panel], name="CMP-049 table · empty")


def filtered_empty() -> k.Node:
    """CMP-026 filtered-empty with Clear filters (the CTA a CMP-001 primary, slice 4 CMP-026 anatomy)."""
    w = table_w() - 2 * k.PX[k.INSET_XL]
    panel = state_panel(
        "CMP-026 empty-state · filtered-empty",
        k.tglyph("⌕", k.TEXT_3, k.HEADING_LG, name="CMP-019 search lg (text glyph)"),
        k.text(
            "description",
            s("No rows match: Bid-stacked, Delta negative"),
            k.BODY,
            k.TEXT_2,
            w=w,
            align="center",
        ),
        k.button(s("Clear filters"), "primary", name="CMP-001 primary · Clear filters"),
    )
    return table([panel], name="CMP-049 table · filtered-empty")


def error() -> k.Node:
    """The header kept; CMP-027's panel with Retry (CMP-001 secondary), announced politely (s3 G17)."""
    w = table_w() - 2 * k.PX[k.INSET_XL]
    panel = state_panel(
        "CMP-027 error-state · panel",
        k.tglyph(
            "⊘", k.STATUS["danger.strong"], k.HEADING_LG, name="CMP-019 danger lg (text glyph)"
        ),
        k.text(
            "message",
            s("Couldn't load users — store unavailable."),
            k.BODY,
            k.TEXT_1,
            w=w,
            align="center",
        ),
        k.button(s("Retry"), "secondary", name="CMP-001 secondary · Retry"),
    )
    return table([panel], name="CMP-049 table · error")


def reflow() -> k.Node:
    """The stacked layout at 200 % zoom: one block per record, the first cell its heading line, the other cells as
    header-value pairs in a 2-column grid; still one row element per record."""
    blocks = []
    for i, (name, role, value) in enumerate(rows_data()[:2]):
        pairs = [
            k.hbox(
                f"pair · {lab}",
                [
                    k.text("header", s(lab), k.LABEL, k.TEXT_2, w=64),
                    k.text("value", v, typo, k.TEXT_1),
                ],
                {"gap": k.INSET_SM},
            )
            for lab, v, typo in (("Role", role, k.BODY), ("Value", value, k.NUM_BASE))
        ]
        blocks.append(
            k.vbox(
                f"record {i + 1}",
                [k.text("heading line", name, k.BODY_STRONG, k.TEXT_1), *pairs],
                {"fill": ZEBRA[i % 2], "padX": k.INSET_SM, "padY": k.INSET_XS, "gap": k.STACK_XS},
                w=200,
            )
        )
    return k.vbox("CMP-049 table · reflow", blocks, w=200)


def grid() -> k.Node:
    """Mode=grid, populated: the actions column (an interactive body column); the CMP-039 ring on a focused cell."""
    rows = [
        body_row(i, r, actions="default", ring_col="name" if i == 1 else None)
        for i, r in enumerate(rows_data())
    ]
    return table(rows, actions=True, name="CMP-049 grid · populated")


def selection() -> k.Node:
    """Selection=multiple (a grid): two rows on color.action.selected with checked boxes; select-all mixed."""
    data = rows_data()
    rows = [
        body_row(
            i,
            r,
            fill=k.ACTION["selected"] if i < 2 else None,
            sel="checked" if i < 2 else "unchecked",
        )
        for i, r in enumerate(data)
    ]
    return table(rows, sel=checkbox("mixed"), name="CMP-049 grid · selection multiple")


def menu_t2() -> k.Node:
    """The row menu open from alex's actions cell: CMP-041 (conventions 30 surface) with "Edit risk caps" in T2 (the
    lock leading the full label, both color.text.tertiary; rbac.owner_only as its second line)."""
    data = rows_data()
    rows = [body_row(i, r, actions="open" if i == 2 else "default") for i, r in enumerate(data)]
    tbl = table(rows, actions=True, name="CMP-049 grid · row menu")
    item_w = 232
    head = k.hbox(
        "T2 item row",
        [k.lock(), k.text("label", s("Edit risk caps"), k.BODY, k.TEXT_3)],
        {"gap": k.INSET_XS},
        h=ROW,
    )
    reason = k.text(
        "T2 reason · rbac.owner_only",
        s("Only the owner can change account settings."),
        k.CAPTION,
        k.TEXT_2,
        w=item_w - 2 * k.PX[k.INSET_SM],
    )
    item = k.vbox(
        "CMP-041 item · T2", [head, reason], {"padX": k.INSET_SM, "padB": k.INSET_XS}, w=item_w
    )
    k.gap(
        "CMP-049's row menu names one item (\"Edit risk caps\"); its other items are the host's (SCR-121) and are "
        "not drawn"
    )
    menu = k.vbox(
        "CMP-041 menu · row actions",
        [item],
        {
            "fill": k.OVERLAY,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CARD,
            "padY": k.INSET_XS,
            "shadow": k.E_POPOVER,
        },
        w=item_w,
    )
    return k.vbox(
        "CMP-049 grid · row menu open",
        [tbl, k.hbox("anchor end", [menu], {"justify": "end"}, w=table_w(actions=True))],
        {"gap": k.INSET_XS},
        w=table_w(actions=True),
    )


def inline_t2() -> k.Node:
    """A gated inline row-action IconButton: 2b, the size.icon.sm lock badge and the CMP-016 echo (conventions 24)."""
    ib = icon_button(state="T2", name="CMP-002 ghost · T2 · Actions for alex")
    echo = k.tooltip(
        s("Only the owner can change account settings."), w=200, name="CMP-016 T2 echo"
    )
    return k.vbox("T2 2b inline IconButton", [k.lock_badge(ib), echo], {"gap": k.INSET_XS})


def build() -> dict:
    """The board."""
    nd = [x.strip() for x in k.not_drawn(CID).rstrip(".").split("), ")]
    nd = [x if x.endswith(")") else x + ")" for x in nd[:-1]] + [nd[-1]]
    nd += [
        (
            "every combination beyond the ten named cells (e.g. loading / error in grid mode, a sorted ascending "
            "column, the selection with an actions column)"
        ),
        (
            "comfortable density (size.row.height 32: only the row height changes, the Anatomy's compact / "
            "comfortable line)"
        ),
        'the live region ("2 selected", sort and load results): announced, never drawn',
        (
            "the visually hidden caption of a table a heading already names; forced colours (CanvasText rules, "
            "Highlight)"
        ),
    ]
    r1 = k.state_row(
        "Mode=table",
        [
            k.cell(
                "populated",
                populated(),
                note="Value sorted descending (arrow-down), Name sortable unsorted, row 3 "
                "hovered",
            ),
            k.cell("loading", loading(), note="CMP-015 skeleton rows, aria-busy"),
            k.cell("empty", empty(), note="CMP-026 no-data"),
            k.cell(
                "filtered-empty", filtered_empty(), note="CMP-026 filtered-empty, Clear filters"
            ),
            k.cell("error", error(), note="CMP-027 panel, Retry; polite (G17)"),
        ],
    )
    r2 = k.state_row(
        "Mode=table · busy, zoom",
        [
            k.cell(
                "sorting",
                populated(sort_value="pending", hover=False),
                note="sortPending: CMP-014 sm in place of " "the glyph, aria-busy",
            ),
            k.cell("reflow", reflow(), note="200 % zoom: one block per record (conventions 28)"),
        ],
    )
    r3 = k.state_row(
        "Mode=grid",
        [
            k.cell("Mode=grid", grid(), note="actions column; CMP-039 ring on the focused cell"),
            k.cell(
                "Selection=multiple",
                selection(),
                note="two rows on color.action.selected; select-all mixed",
            ),
            k.cell(
                "row menu with a T2 item",
                menu_t2(),
                note="2a: lock leads, reason as the second line",
            ),
            k.cell("inline IconButton T2", inline_t2(), note="2b: lock badge + CMP-016 echo"),
        ],
    )
    states = [
        "populated",
        "loading",
        "empty",
        "filtered-empty",
        "error",
        "sorting",
        "reflow",
        "Mode=grid",
        "Selection=multiple",
        "row menu with a T2 item",
        "inline IconButton T2 (2b)",
    ]
    blk = k.block(
        CID, [r1, r2, r3], states=states, not_drawn=nd, proposed=["G3", "G12", "G17", "G21"]
    )
    return k.board(
        NN,
        [blk],
        source="slice 3 §7 CMP-049 Table L1066-1183; conventions 24 (T2), 28 (reflow); "
        "slice 4 CMP-015 / 026 / 027 / 041 anatomy for the nested pieces",
        notes=[
            (
                "CMP-049 draws all ten named cells of its Variants × States table plus the 2b inline "
                "IconButton (build-notes §4 07)"
            ),
            (
                "Rows: odd color.surface.canvas, even color.surface.raised, hover color.surface.hover, "
                "selected color.action.selected (s3 G3); cells never color.text.tertiary (4.79 / 4.83:1)"
            ),
            (
                "CMP-005 unchecked box: 1 px color.border.strong outline (board 02 owns CMP-005's own "
                "specimen)"
            ),
        ],
    )


def main() -> int:
    """Write, validate, compact and describe board 07."""
    bd = build()
    path = k.KIT_DIR / f"{k.stem(NN)}.json"
    summary = k.write_sheet(path, bd)
    rep = k.compact_sheet(path)
    k.write_board_md(
        NN,
        bd,
        summary=f"Validator: {summary}",
        checks=[
            (
                "ten named cells of CMP-049 drawn (populated, loading, empty, filtered-empty, error, sorting, reflow, "
                "Mode=grid, Selection=multiple, row menu with a T2 item) plus the inline 2b IconButton"
            ),
            "loading, empty and error explicitly drawn (the ticket's Gherkin)",
            "T2: lock leads the full label, color.text.tertiary; reason color.text.secondary; never disabled tokens",
            "every specimen string issued by say() (copy gaps logged)",
        ],
    )
    print(summary)
    print(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
