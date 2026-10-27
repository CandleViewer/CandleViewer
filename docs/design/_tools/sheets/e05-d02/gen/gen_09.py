"""gen_09: E05-D02 / 09 overlays (slice 4 §7: CMP-016 Tooltip, CMP-017 Popover, CMP-041 Menu, CMP-043 Dialog,
CMP-044 ConfirmDialog, CMP-046 Drawer).

Run: python3 -I -B gen/gen_09.py  -> 09-overlays.json (validated), its compacted twin in ../E05-D02-v4/ (compactOf sha
guard) and 09-overlays.md. Overlays sit on a color.surface.app stand-in host inside their cell; the modal ones over
conventions 31's scrim (stamp PROPOSED · H1; FALLBACK_SCRIM). CMP-041 menus are FLEX ROWS (every item an hbox with an
explicit h, E15-D04's menu_row() pattern). Every specimen string is k.say()'d; missing ones are k.gap()'d, never
invented.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from s4common import (
    MENU_W,
    Node,
    col,
    field,
    floating,
    footer,
    glyph,
    header,
    host,
    ibtn,
    k,
    modal_card,
    nd,
    row,
    say,
    skel_rows,
    spread,
    t,
    tone_glyph,
)

NN = 9


def S(chars: str, cid: str, doc: str | None = None) -> str:
    return say(chars, cid, doc)


# --- CMP-016 Tooltip --------------------------------------------------------------------------------------------
def tip(
    chars: str, cid: str = "CMP-016", *, w: int | None = None, name: str = "CMP-016 tooltip"
) -> Node:
    """CMP-016: overlay, elevation.popover, radius.card, 1 px border.default, inset.xs x inset.sm, caption primary,
    at most 320 px (k.tooltip)."""
    return k.tooltip(S(chars, cid), w=w, name=name)


def cmp016() -> Node:
    cid = "CMP-016"
    short = "Last data 00:12 ago."
    trig = lambda st="default": k.button(S("Retry now", cid), "secondary", st)
    above = lambda tp, tr, nm: k.vbox(nm, [tp, tr], {"gap": k.INSET_XS, "align": "center"})
    beside = lambda tr, tp, nm: k.hbox(nm, [tr, tp], {"gap": k.INSET_XS})
    reason = "Only the owner can change account settings."
    nav = k.hbox(
        "CMP-002 nav item",
        [glyph("search", k.TEXT_2)],
        {"justify": "center", "radius": k.R_CONTROL},
        w=k.CONTROL_PX,
        h=k.CONTROL_PX,
    )
    gated = k.lock_badge(
        k.hbox(
            "CMP-002 more",
            [glyph("more", k.TEXT_3)],
            {"justify": "center", "radius": k.R_CONTROL, **k.T2_SHAPE},
            w=k.CONTROL_PX,
            h=k.CONTROL_PX,
        )
    )
    options = k.vbox(
        "vertical list",
        [k.button(S("Retry now", cid), "ghost"), k.button(S("Details", cid), "ghost")],
        {"gap": k.STACK_XS},
    )
    rows = [
        k.state_row(
            "Content · Mode",
            [
                k.cell(
                    "default", above(tip(short), trig(), "top"), note="top, describes, short, hover"
                ),
                k.cell(
                    "long",
                    above(
                        tip(
                            "Closes 4 positions at market — all accounts, LIVE + DEMO · hold 800 ms or press "
                            "twice",
                            w=320,
                        ),
                        ibtn("more"),
                        "top long",
                    ),
                    note="wrapped at the 320 px maximum (E39-D03 S20)",
                ),
                k.cell(
                    "echo · name",
                    beside(nav, tip(S("Journal", cid)), "echo name"),
                    note="a collapsed NavRail item's name; aria-hidden, the name is the aria-label",
                ),
                k.cell(
                    "echo · reason",
                    above(tip(reason, name="CMP-016 tooltip · T2 2b echo"), gated, "T2 2b echo"),
                    note="CMP-079 form=tooltip: the lock badge marks it; the echo is never the only copy",
                ),
            ],
        ),
        k.state_row(
            "Trigger · Side",
            [
                k.cell(
                    "focus",
                    above(tip(short), trig("focus-visible"), "focus"),
                    note="keyboard focus: the trigger's CMP-039 ring and the tooltip at once",
                ),
                k.cell(
                    "right",
                    beside(options, tip(short), "right"),
                    note="beside an option in a vertical list",
                ),
                k.cell(
                    "bottom",
                    k.vbox("bottom", [trig(), tip(short)], {"gap": k.INSET_XS, "align": "center"}),
                    note="flipped below: no room above",
                ),
            ],
        ),
    ]
    k.gap(
        "CMP-016: slice 4 gives no short tooltip string; CMP-028's 'Last data 00:12 ago.' describes its 'Retry now' "
        "in the default, focus, right and bottom cells; the long cell's trigger is the host's (a CMP-002 stand-in)"
    )
    return k.block(
        cid,
        rows,
        states=["default", "long", "echo · name", "echo · reason", "focus", "right", "bottom"],
        not_drawn=nd(cid),
        proposed=["H10"],
    )


# --- CMP-017 Popover --------------------------------------------------------------------------------------------
POP_W = 240
SWATCH = (k.ACTION["primary"], k.BUY, k.SELL, k.STATUS["warning.default"], k.STATUS["info.default"])


def swatches() -> Node:
    return k.hbox(
        "CMP-031 swatches",
        [
            k.rect(
                f"swatch {i + 1}",
                16,
                16,
                f,
                o={"radius": k.R_CONTROL, "stroke": k.BORDER_DEFAULT, "strokeWidth": k.HAIRLINE},
            )
            for i, f in enumerate(SWATCH)
        ],
        {"gap": k.INSET_XS},
        h=16,
    )


def prop_form(ring: bool) -> list[Node]:
    cid = "CMP-017"
    return [
        field(S("Auto-scale margin", cid, "s3"), None, w=POP_W - 16, ring=ring),
        swatches(),
        footer(
            "footer",
            [k.button(S("Save as default", cid), "secondary"), k.button(S("Delete", cid), "ghost")],
            POP_W - 16,
        ),
    ]


def cmp017() -> Node:
    cid = "CMP-017"
    trig = ibtn("more", name="CMP-002 trigger")
    pop = lambda nm, ring=False: floating(nm, prop_form(ring), w=POP_W)
    days = [
        k.hbox(
            f"week {r + 1}",
            [
                k.hbox(
                    f"day {d}",
                    [t("d", S(str(d), cid, "s3"), k.NUM_SM, k.TEXT_1)],
                    {"justify": "center"},
                    w=24,
                    h=24,
                )
                for d in range(1 + 7 * r, 8 + 7 * r)
            ],
            {"gap": k.INSET_XS},
            h=24,
        )
        for r in range(2)
    ]
    cal = floating(
        "CMP-017 modal · CMP-047 calendar",
        [
            spread(
                "calendar head",
                t("heading", S("October 2026", cid, "s3"), k.BODY_STRONG, k.TEXT_1),
                row(
                    "months",
                    [
                        ibtn("chevron-left", name="CMP-002 Previous month"),
                        ibtn("chevron-right", name="CMP-002 Next month"),
                    ],
                    gap=k.INSET_XS,
                ),
                7 * 24 + 6 * 4,
            ),
            *days,
        ],
        w=7 * 24 + 6 * 4 + 16,
    )
    body = k.vbox(
        "body (scrolls)",
        [
            field(S("Auto-scale margin", cid, "s3"), None, w=POP_W - 32),
            swatches(),
            field(S("Auto-scale margin", cid, "s3"), None, w=POP_W - 32),
        ],
        {"gap": k.STACK_SM, "clip": True},
        w=POP_W - 16,
        h=64,
    )
    scroll = floating(
        "CMP-017 scrolls",
        [
            k.hbox(
                "body and bar",
                [body, k.rect("scrollbar", 4, 32, k.BORDER_STRONG, o={"radius": k.R_BADGE})],
                {"align": "start", "gap": k.INSET_XS},
                h=64,
            ),
            footer(
                "footer",
                [
                    k.button(S("Save as default", cid), "secondary"),
                    k.button(S("Delete", cid), "ghost"),
                ],
                POP_W - 16,
            ),
        ],
        w=POP_W,
    )
    col_ = lambda nm, kids: k.vbox(nm, kids, {"gap": k.INSET_XS, "align": "end"})
    rows = [
        k.state_row(
            "Modal · Placement · Overflow",
            [
                k.cell(
                    "default",
                    host(
                        "host",
                        [col_("below", [trig, pop("CMP-017 popover", True)])],
                        w=280,
                        h=220,
                        align="start",
                        pad=k.INSET_SM,
                    ),
                    note="non-modal, below, fits: SCR-037's property form; the ring on its first control",
                ),
                k.cell(
                    "modal",
                    host("host", [cal], w=280, h=140),
                    note="CMP-047's calendar dialog: heading, the trapped grid; focus returns to the calendar button",
                ),
                k.cell(
                    "above",
                    host(
                        "host",
                        [col_("above", [pop("CMP-017 popover above"), trig])],
                        w=280,
                        h=220,
                        align="end",
                        pad=k.INSET_SM,
                    ),
                    note="flipped above: no room below",
                ),
                k.cell(
                    "scrolls",
                    host("host", [scroll], w=280, h=160),
                    note="capped at the room to the edge: the body scrolls under a fixed footer",
                ),
            ],
        )
    ]
    k.gap(
        "CMP-017: SCR-037's property field label and the calendar's days are the hosts'; slice 3's 'Auto-scale "
        "margin', 'October 2026' and day numbers stand in"
    )
    return k.block(
        cid,
        rows,
        states=["default", "modal", "above", "scrolls"],
        not_drawn=nd(cid),
        proposed=["H11"],
    )


# --- CMP-041 Menu (flex rows, explicit h) ----------------------------------------------------------------------
ITEM_STATE = {"hover": k.HOVER, "focus-visible": k.HOVER, "active": k.SELECTED}


def item(
    label: str,
    *,
    lead: str | None = None,
    trail: str | None = None,
    state: str = "default",
    second: str | None = None,
    name: str | None = None,
) -> Node:
    """One CMP-041 item: an hbox row, size.row.height, padding-inline inset.sm, gap inset.xs; leading size.icon slot
    (glyph secondary / check primary / lock tertiary / CMP-014), label type.ui.body primary (T2: tertiary), trailing
    shortcut num.sm tertiary or chevron-right; hover / focus color.surface.hover, focus-visible the inset ring (§6
    H8), active color.surface.selected, disabled opacity.disabled; a second line (T2 reason / description) caption
    secondary."""
    cid = "CMP-041"
    t2 = state == "disabled-with-reason"
    ink = k.TEXT_3 if t2 else k.TEXT_1
    if t2:
        slot = k.lock()
    elif lead == "check":
        slot = glyph("check", k.TEXT_1)
    elif lead == "danger":
        slot = glyph("danger", k.STATUS["danger.strong"])
    elif lead == "busy":
        slot = k.spinner(16)
    else:
        slot = k.rect("slot", 16, 16)
    left = row("lead", [slot, t("label", S(label, cid), k.BODY, ink)], gap=k.INSET_XS)
    right = None
    if trail == "submenu":
        right = glyph("chevron-right", k.TEXT_2)
    elif trail:
        right = t("shortcut", S(trail, cid), k.NUM_SM, k.TEXT_3)
    o: dict[str, object] = {"padX": k.INSET_SM, "justify": "space-between"}
    if state in ITEM_STATE:
        o["fill"] = ITEM_STATE[state]
    if state == "focus-visible":
        o.update(
            stroke=k.FOCUS_RING, strokeWidth=k.FOCUS_W, strokeAlign="inner", radius=k.R_CONTROL
        )
    if state == "disabled":
        o["opacity"] = k.OP_DISABLED
        k._fallback("OPACITY")
    nm = name or f"item · {label}" + (" · T2" if t2 else "")
    r = k.hbox(
        nm if not second else "row", [left, right] if right else [left], o, w=MENU_W, h=k.CONTROL_PX
    )
    if not second:
        return r
    sec = (
        k.t2_reason(S(second, cid), w=MENU_W - 16 - 20, name="T2 reason")
        if t2
        else t("description", S(second, cid), k.CAPTION, k.TEXT_2, w=MENU_W - 36)
    )
    return k.vbox(
        nm, [r, k.hbox("second line", [sec], {"padL": k.INSET_SM, "padR": k.INSET_SM})], w=MENU_W
    )


def sep() -> Node:
    return k.hbox(
        "separator",
        [k.rect("rule", MENU_W, 1, k.BORDER_DEFAULT)],
        {"padY": k.INSET_XS},
        w=MENU_W,
        h=9,
    )


def group_label(chars: str) -> Node:
    return k.hbox(
        "group label",
        [t("label", S(chars, "CMP-041"), k.CAPTION, k.TEXT_3)],
        {"padX": k.INSET_SM},
        w=MENU_W,
        h=k.CONTROL_PX,
    )


def menu(items: list[Node], name: str = "CMP-041 menu") -> Node:
    """The menu surface: CMP-017's (conventions 30), padding-block space.inset.xs."""
    return k.vbox(
        name,
        items,
        {
            "fill": k.OVERLAY,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CARD,
            "shadow": k.E_POPOVER,
            "padY": k.INSET_XS,
        },
        w=MENU_W,
    )


def tree_menu(focus: str | None = None, state: str = "default") -> Node:
    lab = ("Duplicate", "Reveal on chart", "Move up", "Move down")
    its = [item(x, state=state if x == focus else "default") for x in lab]
    return menu(its + [sep(), item("Remove", lead="danger", trail="Del")])


def cmp041() -> Node:
    cid = "CMP-041"
    trig = k.button(
        S("Details", cid, "s4"), "secondary"
    )  # the trigger stand-in: a CMP-001 (host-owned label)
    with_trig = lambda m, nm: k.vbox(nm, [trig, m], {"gap": k.INSET_XS})
    sub = k.hbox(
        "submenu pair",
        [
            menu(
                [
                    item("Open chart"),
                    item("Snooze", trail="submenu", state="focus-visible"),
                    item("Disable"),
                ]
            ),
            menu([item("15 m"), item("1 h"), item("until tomorrow")], name="CMP-041 submenu"),
        ],
        {"align": "start"},
    )
    grid_row = k.hbox(
        "grid row stand-in",
        [
            k.rect(f"cell {i}", w, 12, k.HOVER, o={"radius": k.R_CONTROL})
            for i, w in enumerate((80, 56, 64))
        ],
        {"fill": k.SELECTED, "gap": k.INSET_SM, "padX": k.INSET_SM},
        w=MENU_W + 40,
        h=24,
    )
    ctx = k.vbox(
        "context",
        [
            grid_row,
            k.hbox(
                "at the pointer",
                [
                    menu(
                        [
                            item("Duplicate"),
                            item("Reveal on chart"),
                            sep(),
                            item("Remove", lead="danger", trail="Del"),
                        ]
                    )
                ],
                {"padL": k.INSET_XL},
            ),
        ],
        {"gap": k.INSET_XS},
    )
    rows = [
        k.state_row(
            "ItemState (pointer, keys)",
            [
                k.cell(
                    "default",
                    with_trig(tree_menu(), "button trigger"),
                    note="E14-D02's tree-row menu; Remove last with its Del shortcut",
                ),
                k.cell(
                    "hover",
                    tree_menu("Reveal on chart", "hover"),
                    note="color.surface.hover, no ring",
                ),
                k.cell(
                    "focus-visible",
                    tree_menu("Reveal on chart", "focus-visible"),
                    note="color.surface.hover + the inset ring (§6 H8)",
                ),
                k.cell(
                    "active",
                    tree_menu("Reveal on chart", "active"),
                    note="a press: color.surface.selected",
                ),
            ],
        ),
        k.state_row(
            "ItemState (kinds)",
            [
                k.cell(
                    "checked",
                    menu(
                        [
                            item("Lock", lead="check"),
                            item("Invert"),
                            item("Merge"),
                            item("Scale price only", lead="check"),
                        ]
                    ),
                    note="E11-D03's price-scale checkboxes; the check marks the chosen",
                ),
                k.cell(
                    "disabled",
                    menu([item("Duplicate"), item("Move up", state="disabled"), item("Move down")]),
                    note="plain disabled: opacity.disabled (unavailable to everyone)",
                ),
                k.cell(
                    "disabled-with-reason",
                    menu(
                        [
                            item(
                                "Edit risk caps",
                                state="disabled-with-reason",
                                second="Only the owner can change account settings.",
                            )
                        ]
                    ),
                    note="CMP-079 2a: the lock leads the full label (tertiary); the reason its second line",
                ),
                k.cell(
                    "danger",
                    menu([item("Move down"), sep(), item("Remove", lead="danger", trail="Del")]),
                    note="the last group: glyph danger.strong, label primary (§6 H16)",
                ),
            ],
        ),
        k.state_row(
            "ItemState · Trigger",
            [
                k.cell("submenu", sub, note="Snooze open on its presets"),
                k.cell(
                    "busy",
                    menu([item("Flatten account…", lead="busy", second="Loading Sub-1 · LIVE…")]),
                    note="CMP-014 leads the label; the header line its description; no lock, no reason",
                ),
                k.cell("context", ctx, note="opened at the pointer on a grid row (or Shift+F10)"),
            ],
        ),
    ]
    k.gap(
        "CMP-041 checked: the 'Scale mode' radio values are E11-D03's (not in slice 4): the radio group is not drawn, "
        "the four checkboxes are; the button trigger's label is the host's ('Details' stands in)"
    )
    return k.block(
        cid,
        rows,
        states=[
            "default",
            "hover",
            "focus-visible",
            "active",
            "checked",
            "disabled",
            "disabled-with-reason",
            "danger",
            "submenu",
            "busy",
            "context",
        ],
        not_drawn=nd(cid, "the checked cell's Scale mode radio group (E11-D03's values)"),
        proposed=["H8", "H16"],
    )


# --- CMP-043 Dialog ---------------------------------------------------------------------------------------------
DLG_W = {"sm": 420, "md": 560, "lg": 960}  # §6 H17 maximum widths
INNER = lambda w: w - 2 * k.PX[k.DIALOG_PAD]


def over(name: str, card: Node, w: int, h: int | None = None) -> Node:
    """A modal card centred on a host stand-in under conventions 31's scrim."""
    hh = h or round(k.est_height(card)) + 48
    return host(name, [card], w=w + 48, h=hh, scrim=True)


def invite(size: str, state: str = "default", *, ring: bool = True) -> Node:
    cid = "CMP-043"
    w = DLG_W[size]
    iw = INNER(w)
    ro = state == "busy"
    fields = col(
        "body",
        [
            field(
                S("Username", cid, "s3"),
                S("alex", cid, "s3") if ro else None,
                w=iw,
                ring=ring and not ro,
            ),
            field(S("Display name (optional)", cid, "s3"), None, w=iw),
        ],
        gap=k.STACK_MD,
    )
    btns = [
        k.button(S("Cancel", cid), "secondary"),
        k.button(S("Invite a user", cid), "primary", "loading" if ro else "default"),
    ]
    return modal_card(
        f"CMP-043 card · {size}" + (" · busy" if ro else ""),
        [header(S("Invite a user", cid), iw), fields, footer("footer", btns, iw)],
        w=w,
    )


def scrolling_card(w: int, h: int, name: str) -> Node:
    """A capped card: sticky header and footer, the body clipped between them with a scroll bar."""
    cid = "CMP-043"
    iw = INNER(w)
    body_h = h - 2 * k.PX[k.DIALOG_PAD] - 24 - 24 - 2 * 12
    fl = [
        field(S("Username", cid, "s3"), None, w=iw - 12),
        field(S("Display name (optional)", cid, "s3"), None, w=iw - 12),
        field(S("Account", cid, "s3"), None, w=iw - 12),
        field(S("Username", cid, "s3"), None, w=iw - 12),
    ]
    body = k.hbox(
        "body and bar",
        [
            k.vbox("body (scrolls)", fl, {"gap": k.STACK_MD, "clip": True}, w=iw - 12, h=body_h),
            k.rect("scrollbar", 4, body_h // 2, k.BORDER_STRONG, o={"radius": k.R_BADGE}),
        ],
        {"align": "start", "gap": k.INSET_SM},
        h=body_h,
    )
    return k.vbox(
        name,
        [
            header(S("Invite a user", cid), iw),
            body,
            footer(
                "footer",
                [
                    k.button(S("Cancel", cid), "secondary"),
                    k.button(S("Invite a user", cid), "primary"),
                ],
                iw,
            ),
        ],
        {
            "fill": k.OVERLAY,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_DIALOG,
            "shadow": k.E_DIALOG,
            "pad": k.DIALOG_PAD,
            "gap": k.STACK_MD,
        },
        w=w,
        h=h,
    )


def cmp043() -> Node:
    cid = "CMP-043"
    iw = INNER(DLG_W["sm"])
    goto = modal_card(
        "CMP-043 card · sm",
        [
            header(S("Go to date", cid), iw),
            field(None, S("YYYY-MM-DD", cid, "s3"), w=iw, placeholder=True, ring=True),
            footer(
                "footer",
                [
                    k.button(S("Cancel", cid), "secondary"),
                    k.button(S("Go to date", cid), "primary"),
                ],
                iw,
            ),
        ],
        w=DLG_W["sm"],
    )
    iw = INNER(DLG_W["md"])
    alert = modal_card(
        "CMP-043 card · alertdialog",
        [
            header(S("Delete 497 drawings on BTCUSDT?", cid), iw, close=False),
            t("description", S("3 locked drawings stay. One undo.", cid), k.BODY, k.TEXT_2, w=iw),
            footer(
                "footer",
                [
                    k.button(S("Cancel", cid), "secondary", "focus-visible"),
                    k.button(S("Delete 497", cid), "danger"),
                ],
                iw,
            ),
        ],
        w=DLG_W["md"],
    )
    # 200 % zoom on 1280 x 800: a 640 x 400 CSS viewport; the card min(size, 100vw - 2 x space.inset.lg) = 608 wide
    reflow = host(
        "viewport 640 x 400",
        [scrolling_card(608, 368, "CMP-043 card · reflow")],
        w=640,
        h=400,
        scrim=True,
    )
    rows = [
        k.state_row(
            "Size",
            [
                k.cell(
                    "default",
                    over("host", invite("md"), DLG_W["md"]),
                    note="md, dialog, fits: title, two CMP-040 fields, Cancel and the primary; focus on the first field",
                ),
                k.cell("sm", over("host", goto, DLG_W["sm"]), note="E11-D03's Go to date, 420 px"),
                k.cell(
                    "lg",
                    over("host", invite("lg", ring=False), DLG_W["lg"]),
                    note="E42-D03's Invite a user, lg",
                ),
            ],
        ),
        k.state_row(
            "Role · Overflow · State",
            [
                k.cell(
                    "alertdialog",
                    over("host", alert, DLG_W["md"]),
                    note="no close button; Cancel focused; a scrim press does nothing",
                ),
                k.cell(
                    "scrolls",
                    host(
                        "host",
                        [scrolling_card(DLG_W["md"], 320, "CMP-043 card · scrolls")],
                        w=DLG_W["md"] + 48,
                        h=400,
                        scrim=True,
                    ),
                    note="the card at 80 % of the viewport: the body scrolls between a fixed header and footer",
                ),
                k.cell(
                    "busy",
                    over("host", invite("md", "busy"), DLG_W["md"]),
                    note="after the primary press: CMP-001 loading, the fields readOnly; Esc closes the view",
                ),
                k.cell(
                    "reflow",
                    reflow,
                    note="200 % zoom: the dialog fills the viewport, header and footer sticky",
                ),
            ],
        ),
    ]
    k.gap(
        "CMP-043 default / lg / scrolls / busy: slice 4 names E42-D03's 'Invite a user' (lg) only; its fields are "
        "slice 3's 'Username' and 'Display name (optional)' and its primary is drawn with the title's words; the "
        "default md cell's own title and description are the host's (not drawn: the md card reuses lg's content)"
    )
    return k.block(
        cid,
        rows,
        states=["default", "sm", "lg", "alertdialog", "scrolls", "busy", "reflow"],
        not_drawn=nd(
            cid, "the md default's own title and description (the host's; drawn with lg's content)"
        ),
        proposed=["H1", "H17", "H22", "H33"],
    )


# --- CMP-044 ConfirmDialog ---------------------------------------------------------------------------------------
CW = 560  # SCR-072's md card
CI = CW - 48
FREEZE = "Freeze sub_001 — cancel 3 working orders"


def restatement() -> Node:
    """SCR-072's role=group "What this does" on color.surface.raised, radius.card, inset.md; the irreversible line
    body-strong."""
    cid = "CMP-044"
    return k.vbox(
        "restatement",
        [
            t("group label", S("What this does", cid), k.LABEL, k.TEXT_2),
            t("irreversible", S("Open positions are NOT closed", cid), k.BODY_STRONG, k.TEXT_1),
        ],
        {"fill": k.RAISED, "radius": k.R_CARD, "pad": k.INSET_MD, "gap": k.STACK_XS},
        w=CI,
    )


def freeze(
    confirm_state: str = "default",
    *,
    extra: Node | None = None,
    reason: str | None = None,
    name: str = "CMP-044 freeze",
) -> Node:
    cid = "CMP-044"
    cancel_st = "focus-visible" if confirm_state == "default" else "default"
    conf = k.button(S(FREEZE, cid), "danger", confirm_state)
    kids = [
        header(S("Freeze sub_001?", cid), CI, close=False),
        restatement(),
        extra,
        footer("footer", [k.button(S("Cancel", cid), "secondary", cancel_st), conf], CI),
    ]
    if reason:
        kids.append(
            k.hbox(
                "T2 notice",
                [k.t2_reason(S(reason, cid), name="T2 reason")],
                {"justify": "end"},
                w=CI,
            )
        )
    return modal_card(name, kids, w=CW)


def hold_ring(pct: int) -> Node:
    """E39-D03 §5's hold ring: a ring in color.status.danger.default over a color.border.strong track (border.thick
    stands in for 3 px), beside its percentage in type.num.sm secondary (a static frame: the arc as a short rect).
    """
    cid = "CMP-044"
    kids = [
        k.place(
            k.ellipse("track", 16, 16, {"stroke": k.BORDER_STRONG, "strokeWidth": k.THICK}), 0, 0
        )
    ]
    if pct:
        kids.append(k.place(k.rect("arc", 8 * pct // 50, 2, k.STATUS["danger.default"]), 4, 0))
    ring = k.hbox("hold ring", kids, w=16, h=16)
    return row("hold", [ring, t("percent", S(f"{pct} %", cid), k.NUM_SM, k.TEXT_2)], gap=k.INSET_XS)


def crop(name: str, kids: list[Node | None]) -> Node:
    """The body and footer of a card whose title is the host's (a crop: no header drawn)."""
    return modal_card(name, kids, w=CW)


def cmp044() -> Node:
    cid = "CMP-044"
    cancel = lambda st="default": k.button(S("Cancel", cid), "secondary", st)
    delete = lambda st: k.button(S("Delete", cid), "danger", st)
    uname = S("Username", cid, "s3")
    closes = "Closes 4 positions at market — all accounts, LIVE + DEMO"
    hold_btn = lambda st="default": k.button(S(closes, cid), "danger", st)
    k.LOG.add(
        "fallbacks",
        "token: the hold ring's 3 px stroke has no token; border.thick (2 px) stands in; its arc is "
        "a static frame (a short rect), the percentage text carries the progress",
    )
    typed = crop(
        "CMP-044 typed",
        [field(uname, None, w=CI, ring=True), footer("footer", [cancel(), delete("disabled")], CI)],
    )
    match = crop(
        "CMP-044 typed match",
        [field(uname, S("alex", cid), w=CI), footer("footer", [cancel(), delete("default")], CI)],
    )
    hold = lambda pct, st="default", lab=None: crop(
        f"CMP-044 hold {pct}",
        [
            footer(
                "footer",
                [
                    cancel("focus-visible" if st == "default" and pct == 0 else "default"),
                    lab or hold_btn(st),
                ],
                CI,
                lead=hold_ring(pct),
            )
        ],
    )
    armed = k.button(
        S("Press again to flatten 4 positions — all accounts, LIVE + DEMO", cid),
        "danger",
        "focus-visible",
    )
    partial = row(
        "CMP-027 inline",
        [tone_glyph("danger"), k.button(S("Retry", cid, "s4"), "secondary")],
        gap=k.INSET_XS,
    )
    order = modal_card(
        "CMP-044 order",
        [
            header(S("Confirm order - BTCUSDT - LIVE - Main", cid), CI),
            footer(
                "footer",
                [
                    k.button(S("Cancel", cid), "secondary", "focus-visible"),
                    k.button(S("BUY 0.250 BTCUSDT limit 64,010.0 · stop 63,900.0", cid), "buy"),
                ],
                CI,
                lead=t("countdown", S("Cancels in 0:20", cid), k.NUM_SM, k.TEXT_1),
            ),
        ],
        w=CW,
    )
    inset = k.hbox(
        "inset · timed out",
        [
            t(
                "outcome",
                S("Confirmation timed out — nothing was sent. Attempt recorded", cid),
                k.BODY,
                k.TEXT_1,
                w=CW - 24,
            )
        ],
        {
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CARD,
            "pad": k.INSET_SM,
        },
        w=CW,
    )
    rows = [
        k.state_row(
            "standard",
            [
                k.cell(
                    "default",
                    over("host", freeze(), CW),
                    note="SCR-072: alertdialog md, Cancel focused",
                ),
                k.cell(
                    "busy",
                    over("host", freeze("loading"), CW),
                    note="after Confirm: CMP-001 loading",
                ),
                k.cell(
                    "partial failure",
                    over("host", freeze(extra=partial), CW),
                    note="a CMP-027 inline error with Retry above the footer",
                ),
            ],
        ),
        k.state_row(
            "typed · gated",
            [
                k.cell(
                    "typed",
                    over("host", typed, CW),
                    note="the username field empty; Confirm natively disabled",
                ),
                k.cell(
                    "typed · match",
                    over("host", match, CW),
                    note="the field matches exactly; Confirm enabled",
                ),
                k.cell(
                    "gated",
                    over(
                        "host",
                        freeze(
                            "disabled-with-reason", reason="Your role can't use the kill switch."
                        ),
                        CW,
                    ),
                    note="T2 through CMP-079: the lock leads the full label, raised fill + hairline; the reason under "
                    "the footer (§6 H30)",
                ),
            ],
        ),
        k.state_row(
            "hold · order",
            [
                k.cell(
                    "hold",
                    over("host", hold(0), CW),
                    note="the confirm names the effect; its ring at 0 %",
                ),
                k.cell(
                    "holding", over("host", hold(50), CW), note="a pointer hold: the ring at 50 %"
                ),
                k.cell(
                    "armed",
                    over("host", hold(0, lab=armed), CW),
                    note="the keyboard path after the first press; the 5 s window",
                ),
                k.cell(
                    "order",
                    k.vbox(
                        "order and inset", [over("host", order, CW), inset], {"gap": k.STACK_SM}
                    ),
                    note="SCR-076 counting down: dialog with close, the side-fill Confirm; inset: timed out at 0:00",
                ),
            ],
        ),
    ]
    k.gap(
        "CMP-044 typed / hold cells are drawn as crops (body and footer): the titles of E42-D02's rung 3 and E39-D03's "
        "hold confirm are the hosts'; the typed confirm's label is drawn 'Delete' (slice 4) — its full-effect label "
        "is E42-D02's; the hold confirm names its effect with E39-D03 S20's 'Closes 4 positions at market — all "
        "accounts, LIVE + DEMO'"
    )
    k.gap(
        "CMP-044 partial failure: SCR-072's failure line is the host's: the inline CMP-027 is drawn as its glyph and "
        "Retry; order: the restatement and the host's rows are E30-D03's (not drawn)"
    )
    return k.block(
        cid,
        rows,
        states=[
            "default",
            "typed",
            "typed · match",
            "hold",
            "holding",
            "armed",
            "busy",
            "partial failure",
            "gated",
            "order",
        ],
        not_drawn=nd(
            cid,
            "the typed and hold cards' titles (E42-D02's, E39-D03's: drawn as crops)",
            "SCR-072's partial-failure line; SCR-076's restatement and rows (the hosts')",
        ),
        proposed=["H1", "H24", "H25", "H30", "H32"],
    )


# --- CMP-046 Drawer ---------------------------------------------------------------------------------------------
DRW_W, HOST_W, HOST_H = 480, 640, 320


def drawer(
    w: int, h: int, *, modal: bool = True, loading: bool = False, name: str = "CMP-046 drawer"
) -> Node:
    """CMP-046: color.surface.overlay, square, a 1 px color.border.default inner edge, modal elevation.dialog /
    non-modal elevation.popover; sticky header (title heading-sm, close; space.panel.padding; a rule under it), the
    body (panel padding, gap stack.md), a sticky footer."""
    cid = "CMP-046"
    iw = w - 2 * k.PX[k.PANEL_PAD]
    head = k.vbox(
        "header",
        [header(S("BTC above 65k", cid, "s4"), iw)],
        {"pad": k.PANEL_PAD, "stroke": k.BORDER_DEFAULT, "strokeWidth": k.HAIRLINE},
        w=w,
    )
    if loading:
        body = k.vbox(
            "body",
            [skel_rows(3, iw, on_overlay=True)],
            {"pad": k.PANEL_PAD},
            w=w,
            h=3 * 24 + 8 + 24,
        )
    else:
        body = k.vbox(
            "body",
            [
                t(
                    "body",
                    S("Last price 65,012.5 crossed above 65,000", cid, "s4"),
                    k.BODY,
                    k.TEXT_1,
                    w=iw,
                ),
                t("meta", S("BTCUSDT · 5m", cid, "s4"), k.NUM_SM, k.TEXT_3),
            ],
            {"pad": k.PANEL_PAD, "gap": k.STACK_MD},
            w=w,
        )
    foot = k.hbox(
        "footer",
        [k.button(S("Open chart", cid, "s4"), "secondary")],
        {"pad": k.PANEL_PAD, "justify": "end"},
        w=w,
    )
    return k.vbox(
        name,
        [head, body, foot],
        {
            "fill": k.OVERLAY,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "strokeAlign": "inner",
            "shadow": k.E_DIALOG if modal else k.E_POPOVER,
            "justify": "space-between",
        },
        w=w,
        h=h,
    )


def cmp046() -> Node:
    cid = "CMP-046"
    ws = lambda kids, scrim, just, w=HOST_W: host(
        "workspace", kids, w=w, h=HOST_H, scrim=scrim, justify=just, align="start"
    )
    rows = [
        k.state_row(
            "Side · Modal",
            [
                k.cell(
                    "default",
                    ws([drawer(DRW_W, HOST_H)], True, "end"),
                    note="right, modal: 480 px between the TopBar and the StatusBar, the scrim over the workspace",
                ),
                k.cell(
                    "non-modal",
                    ws([drawer(DRW_W, HOST_H, modal=False)], False, "end"),
                    note="the alert detail drawer: elevation.popover, no scrim, the workspace live (§6 H31)",
                ),
                k.cell(
                    "left",
                    ws([drawer(DRW_W, HOST_H)], True, "start"),
                    note="the same anatomy mirrored",
                ),
            ],
        ),
        k.state_row(
            "State",
            [
                k.cell(
                    "loading",
                    ws([drawer(DRW_W, HOST_H, loading=True)], True, "end"),
                    note="aria-busy: CMP-015 rows in color.surface.selected on the overlay (§6 H3)",
                ),
                k.cell(
                    "narrow",
                    ws([drawer(360, HOST_H)], True, "start", w=360),
                    note="a viewport of 720 CSS px or less: the full width (drawn at 360 px)",
                ),
            ],
        ),
    ]
    k.gap(
        "CMP-046: SCR-103's instrument-rules content is E08-D06's; every drawer cell draws E40-D02's alert detail "
        "content ('BTC above 65k', its body and meta, 'Open chart') from slice 4's CMP-045 cell"
    )
    return k.block(
        cid,
        rows,
        states=["default", "non-modal", "left", "loading", "narrow"],
        not_drawn=nd(cid, "SCR-103's instrument-rules content (E08-D06's)"),
        proposed=["H1", "H31"],
    )


def main() -> int:
    blocks = [cmp016(), cmp017(), cmp041(), cmp043(), cmp044(), cmp046()]
    notes = [
        (
            "Overlays sit on a color.surface.app stand-in host (1 px color.border.subtle edge) inside their cell; modal "
            "cells add conventions 31's scrim (PROPOSED · H1: palette.black at opacity.scrim, drawn color.surface.sunken at "
            "opacity.scrim, a fallback — live check: rebind to palette.black)."
        ),
        "CMP-041 menus are flex rows: every item an hbox with an explicit 24 px h (E15-D04's menu_row() pattern).",
        (
            "CMP-044 draws standard, typed, hold and the gated cell (T2 2a: the lock leads the full Confirm label in "
            "color.text.tertiary, color.surface.raised + hairline, the reason in color.text.secondary under the footer)."
        ),
        "Glyph stand-ins: more ⋮, search ⌕, check ✓, danger ⊘, chevrons ▸ ◂ ▾; lock and close are the local icons.",
    ]
    bd = k.board(
        NN,
        blocks,
        source="slice 4 §3 conventions 30-39, §6 decisions H, §7 L1057-1183, L1518-1778, "
        "L1861-1930",
        notes=notes,
    )
    path = k.KIT_DIR / f"{k.stem(NN)}.json"
    print(k.write_sheet(path, bd))
    print(k.compact_sheet(path))
    k.write_board_md(
        NN,
        bd,
        summary="Board 09: slice 4's overlays, six blocks, the spec's named cells.",
        checks=[
            "every block draws the spec's named cells",
            "every specimen string k.say()'d from the frozen spec (slice 3 for nested fields)",
            "modal cells over the scrim stand-in; floating surfaces on conventions 30's tokens",
            "CMP-041 items are flex rows with explicit h; T2 item lock-led with its reason line",
            "CMP-044 gated Confirm in T2 2a; no inst node; only the local icons locked and close",
        ],
        live=[
            (
                "the scrim (color.surface.sunken at opacity.scrim) reads as a 60 % black veil at 1x; "
                "rebind it to palette.black when the drawer allows a primitive colour"
            ),
            "clipped bodies (CMP-017 scrolls, CMP-043 scrolls / reflow) clip at their h",
        ],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
