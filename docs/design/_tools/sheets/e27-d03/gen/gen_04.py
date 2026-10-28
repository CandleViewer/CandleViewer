"""E27-D03 / 04 scr-125-128-accounts (dark): SCR-125's accounts route in CMP-087 and SCR-128's panel (§0 L221).

Run:  python3 -I -B docs/design/_tools/sheets/e27-d03/gen/gen_04.py
Writes 04-scr-125-128-accounts.json beside e27d03kit.py (k.write_sheet validates it: exit 0 or it raises), compacts it
into v4/ (compactOf sha guard) and writes 04-scr-125-128-accounts.md. gen_05.py imports build_cells() for
the light twin. No Penpot, no network; never edits the kit.

Sources: §3.1 L973-1008 (anatomy, redline), §3.2 L1009-1061 (the record, the state slot), §3.4 L1079-1091 (hi-fi
rows 1 and 6-17), §6 L1305-1388 (SCR-128 anatomy, columns, hi-fi rows 42-48), §10.1 (T2), §12 (the deck).
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
KIT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT_DIR))
import e27d03kit as k

Node = dict[str, Any]
NN = 4
W = k.INNER_W  # 944
C1, C2, C3, C4 = k.COLS  # 240 · 240 · 272 · 192 (§3.1 block H)
PAD = 8  # space.inset.sm inside a table cell
HH = "14:02"  # the verdict / verification time (§3.1 E)

# The fixture accounts (L62-65) with frame 42's key facts (D02:597-603).
ACCTS: dict[str, dict[str, Any]] = {
    "Main": {"uid": "1234567", "env": "LIVE", "key": "...a1b2", "age": 41, "due": "2026-12-11"},
    "sub_001": {"uid": "1234568", "env": "LIVE", "key": "...c3d4", "age": 12, "due": "2027-01-09"},
    "sub_002": {"uid": "1234569", "env": "LIVE", "key": "...e5f6", "age": 78, "due": "2026-11-04"},
    "demo-1": {"uid": "9000001", "env": "DEMO", "key": "...a7b8", "age": 30, "due": "2026-12-22"},
}


def T(name: str, chars: str, typo: str = k.BODY, color: str = k.TEXT_1, **kw: Any) -> Node:
    """A text node (chars issued by the caller)."""
    return k.text(name, chars, typo, color, **kw)


def part(sub: str, whole: str) -> str:
    """A substring of an issued deck string (a CTA split off "… [Change]"), issued as part of it, never invented."""
    if sub not in whole or whole not in k._ISSUED:
        raise ValueError(f"part({sub!r}): not a part of an issued string")
    return k._issue(sub)


def split_cta(whole: str) -> tuple[str, str]:
    """'words [Cta]' -> ('words', 'Cta'), both issued as parts of the deck string."""
    head, _, rest = whole.rpartition(" [")
    return part(head, whole), part(rest.rstrip("]"), whole)


def btn(label: str, variant: str = "secondary", state: str = "default", **kw: Any) -> Node:
    """k.button (label issued)."""
    return k.button(label, variant, state, **kw)


def wrap_button(label: str, w: int) -> Node:
    """A CMP-001 secondary whose long label wraps inside a narrow cell (never clips; §3.1 block J cell 4)."""
    k._fallback("DENSITY")
    return k.hbox(
        "CMP-001 button · secondary · default",
        [T("label", label, k.BODY_STRONG, k.TEXT_1, w=w - 24)],
        {
            "fill": k.ACTION["secondary"],
            "padX": k.BTN_PADX,
            "padY": k.INSET_XS,
            "radius": k.R_CONTROL,
            "minH": k.CONTROL_COMFORTABLE,
        },
        w=w,
    )


def tcell(name: str, kids: list[Node | None], w: int, **o: Any) -> Node:
    """A table cell: a flex column padded space.inset.sm."""
    return k.vbox(name, kids, {"padX": k.INSET_SM, "padY": k.INSET_XS, "gap": k.STACK_XS, **o}, w=w)


# --- SCR-125's table (CMP-049, §3.1 blocks H-J; §3.2).
def table_head() -> Node:
    """Block H: two 32 px header rows on color.surface.hover, type.ui.label, a 1 px color.border.subtle rule."""
    hs = k.copies("e27.scr125.table.headers")
    r1 = k.hbox(
        "header row 1",
        [
            k.hbox(f"th {i}", [T("label", h, k.LABEL)], {"padX": k.INSET_SM}, w=w_, h=32)
            for i, (h, w_) in enumerate(zip(hs[:4], k.COLS), 1)
        ],
        {"fill": k.HOVER},
        w=W,
        h=32,
    )
    r2 = k.hbox(
        "header row 2",
        [k.rect("th 1 (spanned)", C1, 32, k.HOVER)]
        + [
            k.hbox(f"th {i}", [T("label", h, k.LABEL)], {"padX": k.INSET_SM}, w=w_, h=32)
            for i, (h, w_) in enumerate(zip(hs[4:], k.COLS[1:]), 2)
        ],
        {"fill": k.HOVER},
        w=W,
        h=32,
    )
    return k.vbox(
        "CMP-049 table head",
        [r1, r2, k.rect("rule", W, 1, k.BORDER_SUBTLE)],
        {},
        w=W,
        note="a plain table with a visually hidden caption (e27.scr125.table.caption)",
    )


def group_row(env: str, n: int) -> Node:
    """Block I: the group row, its h3 "LIVE (3)" with the environment word as the CMP-075 pill."""
    whole = k.copies("e27.scr125.group", n=n)[0 if env == "LIVE" else 1]
    return k.hbox(
        f"group row · {env}",
        [k.env_pill(env), T("h3 count", part(f"({n})", whole), k.HEADING_SM)],
        {"fill": k.RAISED, "padX": k.INSET_SM, "gap": k.INSET_XS},
        w=W,
        h=32,
        note=f'th scope="rowgroup" colspan="4"; h3 "{whole}"',
    )


def health(state: str = "ok", n: int = 2) -> Node:
    """CMP-178 inline (HD10): word, glyph, heartbeat age; "Not monitored yet" with the dash while health is null."""
    if state == "ok":
        kids = [
            k.glyph("check", k.STATUS["success.strong"]),
            T("word", k.copy("e27.scr125.row.health", n=n), k.BODY, k.TEXT_2),
        ]
    elif state == "none":
        kids = [
            k.glyph("dash", k.TEXT_2),
            T("word", k.copy("e27.scr125.row.health_none"), k.BODY, k.TEXT_2),
        ]
    elif state == "degraded":
        kids = [
            k.glyph("triangle", k.STATUS["warning.strong"]),
            T("word", k.copy("e27.scr125.chip.degraded"), k.BODY, k.TEXT_2, w=C4 - 40),
        ]
    else:
        kids = [
            k.glyph("octagon", k.STATUS["danger.strong"]),
            T("word", k.copy("e27.scr125.chip.down"), k.BODY, k.TEXT_2, w=C4 - 40),
        ]
    return k.hbox(f"CMP-178 inline · {state}", kids, {"gap": k.INSET_XS, "align": "start"})


def verified_parts() -> list[Node]:
    """CMP-175 `verified` inline (§2.1 L308) as its glyph and two words, so the line breaks before "verified" and
    never inside it (§3.1 J; AD-3: never undated): the check in color.status.success.strong, the words row-text.
    """
    whole = k.copy("e27.cmp175.verified", hh_mm=HH)
    k.LOG.add("sources", f"CMP-175 verified: {k.cite(k.CMP175['verified'].line)}")
    head, _, tail = whole.partition(" · ")
    return [
        k.hbox(
            "CMP-175 verified · inline",
            [k.glyph("check", k.STATUS["success.strong"]), T("word", part(head, whole))],
            {"gap": k.INSET_XS},
        ),
        k.tglyph("·"),
        T("CMP-175 verified · time", part(tail, whole)),
    ]


def key_line(label: str) -> Node:
    """Cell 3 line 1: CMP-034 then the trade facet and the dated withdrawal facet, breaking before "verified"."""
    a = ACCTS[label]
    return k.hbox(
        "key and rights",
        [
            k.masked_id(a["key"]),
            k.tglyph("·"),
            k.cmp175("trade-only", "inline"),
            k.tglyph("·"),
            *verified_parts(),
        ],
        {"gap": k.INSET_XS, "wrap": "wrap", "align": "start"},
        w=C3 - 2 * PAD,
    )


def blocked_key_line(label: str) -> Node:
    """Cell 3 line 1 on a blocked record: CMP-034 and the trade facet only. The withdrawal facet's critical state
    is the state slot's badge, never a facet beside it (§2.1 L373; BQ-7; L2420): "Withdrawal OFF ✓ · verified"
    next to "BLOCKED — fund right found" would be a false-safe contradiction."""
    a = ACCTS[label]
    return k.hbox(
        "key and rights",
        [k.masked_id(a["key"]), k.tglyph("·"), k.cmp175("trade-only", "inline")],
        {"gap": k.INSET_XS, "wrap": "wrap", "align": "start"},
        w=C3 - 2 * PAD,
    )


def age_line(label: str) -> Node:
    """Cell 3 line 2: the key age and its rotation due date (type.num.base on row-secondary)."""
    a = ACCTS[label]
    return T(
        "age · due", k.copy("e27.scr125.row.age", n=a["age"], date=a["due"]), k.NUM_BASE, k.TEXT_2
    )


def actions(label: str, *, blocked: bool = False, focused: bool = False) -> Node:
    """Cell 4 line 1: [Start the compromise response] where blocked, then [Actions] [Details]."""
    env = ACCTS[label]["env"]
    acts = btn(
        k.say("Actions"),
        "secondary",
        "focus" if focused else "default",
        name=f"CMP-041 trigger · {k.copy('e27.scr125.row.actions', label=label, ENV=env)}",
    )
    dets = btn(
        k.say("Details"),
        "ghost",
        name=f"CMP-001 ghost · {k.copy('e27.scr125.row.details', label=label, ENV=env)}",
    )
    pair = k.fit_row(
        k.hbox("Actions and Details", [acts, dets], {"gap": k.INSET_SM}, w=C4 - 2 * PAD)
    )
    first = wrap_button(k.copy("e27.scr125.blocked.action"), C4 - 2 * PAD) if blocked else None
    return k.vbox("buttons", [first, pair], {"gap": k.INSET_XS})


def record(
    label: str,
    *,
    state: Node | None = None,
    facet: Node | str | None = None,
    line3: Node | None = None,
    span3: Node | None = None,
    hl: Node | None = None,
    blocked_line2: str | None = None,
    focused: bool = False,
) -> Node:
    """Block J / §3.2: one CMP-176 record as two lines on color.surface.raised (cell 1 spans both): label · UID ·
    pill | state / allowlist facet | key and rights / age | buttons / health. blocked_line2= draws HD4's danger
    treatment: both lines on color.status.danger.subtle, the 4 px inline-start rule, the critical badge, [Start the
    compromise response] first, line 2 one cell across cells 2-4."""
    a = ACCTS[label]
    blocked = blocked_line2 is not None
    fill = k.STATUS["danger.subtle"] if blocked else k.RAISED
    ident = k.hbox(
        "identity",
        [
            T("label", k.fixture(label), k.BODY_STRONG),
            k.tglyph("·"),
            T("UID", k.fixture(a["uid"]), k.NUM_BASE),
            k.env_pill(a["env"]),
        ],
        {"gap": k.INSET_XS, "wrap": "wrap"},
        w=C1 - 2 * PAD - (4 if blocked else 0),
    )
    c1_kids: list[Node | None] = [ident]
    if blocked:
        k._fallback("RULE4")
        c1_kids.insert(
            0, k.place(k.rect("danger rule (4 px)", 4, 72, k.STATUS["danger.strong"]), 0, 0)
        )
    c1 = k.vbox(
        "cell 1 · th row",
        c1_kids,
        {"padL": k.INSET_MD if blocked else k.INSET_SM, "padR": k.INSET_SM, "padY": k.INSET_XS},
        w=C1,
    )
    st = state or k.state_badge("OK")
    fc = (
        facet
        if isinstance(facet, dict)
        else (None if facet == "none" else k.cmp175("allowlist matches", "inline", lead=False))
    )
    l3 = line3 or (blocked_key_line(label) if blocked else key_line(label))
    hl_ = hl or health()
    top = k.hbox(
        "line 1",
        [
            tcell("cell 2", [st], C2),
            tcell("cell 3", [l3], C3),
            tcell("cell 4", [actions(label, blocked=blocked, focused=focused)], C4),
        ],
        {"align": "start"},
        w=W - C1,
    )
    if blocked:
        bottom = k.hbox(
            "line 2",
            [
                tcell(
                    "cells 2-4",
                    [T("blocked line 2", blocked_line2, k.BODY, k.TEXT_1, w=W - C1 - 2 * PAD)],
                    W - C1,
                )
            ],
            {"align": "start"},
            w=W - C1,
        )
    elif span3 is not None:
        bottom = k.hbox(
            "line 2",
            [
                (
                    tcell("cell 2", [fc], C2)
                    if facet != "none"
                    else k.rect("cell 2 (no key: no facet)", C2, 8)
                ),
                k.rect("cell 3 (spanned)", C3, 8),
                tcell("cell 4", [hl_], C4),
            ],
            {"align": "start"},
            w=W - C1,
        )
    else:
        bottom = k.hbox(
            "line 2",
            [
                tcell("cell 2", [fc], C2),
                tcell("cell 3", [age_line(label)], C3),
                tcell("cell 4", [hl_], C4),
            ],
            {"align": "start"},
            w=W - C1,
        )
    if span3 is not None:
        top = k.hbox(
            "line 1",
            [
                tcell("cell 2", [st], C2),
                tcell("cell 3 · spans both lines", [span3], C3),
                tcell("cell 4", [actions(label, focused=focused)], C4),
            ],
            {"align": "start"},
            w=W - C1,
        )
    right = k.vbox("lines", [top, bottom], {}, w=W - C1)
    row = k.hbox(
        f"CMP-176 record · {label}",
        [c1, right],
        {"fill": fill, "align": "start"},
        w=W,
        note="two tr; CMP-176's record fill replaces CMP-049's zebra (§3.1 J)",
    )
    return k.vbox(f"record · {label}", [row, k.rect("hairline", W, 1, k.BORDER_DEFAULT)], {}, w=W)


def details(label: str, lines: list[Node]) -> Node:
    """The details row (§3.2): one td colspan 4, space.inset.lg, type.ui.body; labels row-secondary, values
    row-text."""
    return k.vbox(
        f"details row · {label}",
        lines,
        {"fill": k.RAISED, "pad": k.INSET_LG, "gap": k.STACK_XS},
        w=W,
        note="Details' aria-controls target",
    )


def dtext(chars: str, color: str = k.TEXT_1, name: str = "detail") -> Node:
    """A details sentence at the details row's measure."""
    return T(name, chars, k.BODY, color, w=W - 32)


def list_block(recs: dict[str, Node], extra: dict[str, list[Node]] | None = None) -> list[Node]:
    """Blocks G-J: the h2, the capacity line, the table head and the LIVE / DEMO groups with the records (and any
    details rows after their record)."""
    ex = extra or {}
    live = [n for lb in ("Main", "sub_001", "sub_002") for n in [recs[lb], *ex.get(lb, [])]]
    demo = [recs["demo-1"], *ex.get("demo-1", [])]
    table = k.vbox(
        "CMP-049 Table",
        [table_head(), group_row("LIVE", 3), *live, group_row("DEMO", 1), *demo],
        {},
        w=W,
        note=f'caption "{k.copy("e27.scr125.table.caption")}" (visually hidden)',
    )
    return [k.section_heading("e27.shell.region.accounts"), capacity("recorded"), table]


def capacity(form: str) -> Node:
    """Block G's capacity line (consumed from E42-D03): type.ui.body color.text.secondary; [Change] / [Record tier]
    CMP-001 ghost, 32 px."""
    if form == "recorded":
        s = k.copy("e27.scr125.cap.recorded", used=2, cap=5, Tier="Regular", date="2026-09-12")
    elif form == "cap":
        s = k.copy("e27.scr125.cap.recorded", used=5, cap=5, Tier="Regular", date="2026-09-12")
    elif form == "unrecorded":
        s = k.copy("e27.scr125.cap.unrecorded", used=5)
    else:
        s = k.copy("e27.scr125.cap.unavailable", used=5)
        return k.hbox(
            f"capacity line · {form}",
            [T("line", s, k.BODY, k.TEXT_2)],
            {"gap": k.INSET_MD},
            w=W,
            h=32,
        )
    words, cta = split_cta(s)
    return k.hbox(
        f"capacity line · {form}",
        [T("line", words, k.BODY, k.TEXT_2), btn(cta, "ghost")],
        {"gap": k.INSET_MD},
        w=W,
        h=32,
    )


def key_health_button(open_: bool = False) -> Node:
    """Block K / §6 disclosure: the h2's own button "Key health and secrets policy" with its chevron."""
    ch = k.glyph("chevron", k.TEXT_2) if open_ else k.tglyph("▸", k.TEXT_2)
    return k.hbox(
        "CMP-051 disclosure · h2 button",
        [T("h2", k.copy("e27.shell.region.health"), k.HEADING_SM), ch],
        {"gap": k.INSET_SM},
        h=32,
        note=f'aria-expanded="{str(open_).lower()}"',
    )


def std_records(**over: Node) -> dict[str, Node]:
    """Frame 6's four records, each "OK", unless over= replaces one."""
    out = {lb: over.get(lb) or record(lb) for lb in ACCTS}
    return out


# --- Frame geometry helpers.
def need_h(nodes: list[Node | None], n_banners: int = 0) -> int:
    """The frame height admin_frame needs to draw nodes (verdict, notices, content) whole: §3.1's chrome (TopBar,
    banners, band, rule, strip, PageHeader, footer, StatusBar) plus the content; at least 800 (a taller frame draws
    §3.1's continuation under the viewport line)."""
    ns = [n for n in nodes if n]
    fixed = 32 + 4 + 32 + 32 + 16  # band, rule, strip, PageHeader, footer marker
    used = (
        48
        + 32 * n_banners
        + 48
        + 32
        + fixed
        + sum(k.est_height(n) for n in ns)
        + 12 * (len(ns) + 4)
    )
    return max(k.FRAME_H, int(-(-used // 8) * 8))


def page(
    verdict: Node | None = None,
    notices: list[Node] | None = None,
    content: list[Node] | None = None,
    banners: list[Node] | None = None,
    h: int | None = None,
    **kw: Any,
) -> dict[str, Any]:
    """admin_frame kwargs with the height the content needs (h= overrides)."""
    ns, cs, bs = notices or [], content or [], banners or []
    return dict(
        verdict=verdict,
        notices=ns,
        content=cs,
        banners=bs,
        h=h or need_h([verdict, *ns, *cs], len(bs)),
        meta=k.copy("e27.shell.meta", hh_mm_ss="14:02:11"),
        **kw,
    )


def scrolled(
    name: str,
    content: list[Node],
    *,
    banners: list[Node] | None = None,
    overlays: Callable[[int], list[Node]] | None = None,
) -> Node:
    """A 1280 x 800 CMP-087 viewport scrolled to SCR-128's panel (§6: "1280 × 800, inside SCR-125's page"): the
    TopBar, any CMP-092 rows, the NavRail | the page from the panel down (blocks C-J are above the viewport, as frame
    6) | the RightRail, the StatusBar; taller only to draw the panel's continuation."""
    bs = banners or []
    cs = [*content, k.footer_marker()]
    body_need = sum(k.est_height(n) for n in cs) + 12 * (len(cs) - 1) + 32
    h = max(k.FRAME_H, int(-(-(48 + 32 * len(bs) + body_need + 48) // 8) * 8))
    body_h = h - 48 - 32 * len(bs) - 48
    main = k.vbox(
        "content (scrolled to the panel)",
        cs,
        {"pad": k.INSET_LG, "gap": k.STACK_MD, "fill": k.APP, "clip": True},
        w=k.MAIN_W,
        h=body_h,
        note="the page scrolled: blocks C-J sit above the viewport (frame 6)",
    )
    body = k.hbox(
        "body",
        [k.navrail(body_h), main, k.rightrail(body_h)],
        {"align": "start"},
        w=k.FRAME_W,
        h=body_h,
    )
    kids = [k.topbar(), *bs, body, k.statusbar(), *(overlays(h) if overlays else [])]
    if h > k.FRAME_H:
        kids.append(
            k.place(
                k.rect("viewport line (800)", k.FRAME_W, 1, k.STATUS["warning.strong"]),
                0,
                k.FRAME_H,
            )
        )
    return k.vbox(
        name,
        kids,
        {"fill": k.APP, "clip": True},
        w=k.FRAME_W,
        h=h,
        note="CMP-087 AdminLayout, 1280 x 800, comfortable (§3.1), scrolled to SCR-128 (§6)",
    )


def inset(name: str, kids: list[Node | None], w: int) -> Node:
    """An inset card drawn over the frame (E27-D02's insets): color.surface.raised, a hairline, radius.card."""
    return k.vbox(
        name,
        kids,
        {
            "fill": k.RAISED,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CARD,
            "pad": k.INSET_MD,
            "gap": k.STACK_SM,
        },
        w=w,
    )


def layer(panel: Node, x: int, y: int, h: int, name: str) -> Node:
    """A popover / inset on the overlay layer, no scrim."""
    return k.overlay(panel, x=x, y=y, h=h, scrim=False, name=name)


def row_menu(
    label: str,
    *,
    gated: dict[str, str] | None = None,
    focused: str | None = None,
    keyless: bool = False,
    **fills: Any,
) -> Node:
    """SCR-125's CMP-041 row menu (E27-D02's order, D02:421-426): the keys-class items carry the ask line, Disable
    and Delete the label ask; gated= {item: reason key} draws T2 items (§10.1)."""
    its = k.copies("e27.scr125.menu.items")
    ask_k, ask_l = k.copy("e27.scr125.menu.ask.keys"), k.copy("e27.scr125.menu.ask.label")
    second = {its[1]: ask_k, its[2]: ask_k, its[4]: ask_l, its[6]: ask_l, its[7]: ask_l}
    order = (
        [its[0], its[1], its[6]]
        if keyless
        else [its[0], its[2], its[3], its[4], its[5], its[6], its[7]]
    )
    g = gated or {}
    out = [
        (
            k.menu_item(it, reason_key=g[it], **fills)
            if it in g
            else k.menu_item(it, second=second.get(it), focused=it == focused)
        )
        for it in order
    ]
    return k.menu(out, w=280, name=f"CMP-041 Menu · {label}")


# --- The Test dialog (CMP-043, 560 px; §3.4 frame 11 (b), §6 frame 44).
DLG_W = 560


def test_checks(label: str, hh: str) -> Node:
    """CMP-203 tri-state on the overlay: the nine pipeline rows for label's key, all passed (§2.5)."""
    a = ACCTS[label]
    nm = k.copies("e27.checks.names")
    words = [
        k.copy("e27.checks.env.passed", ENV=a["env"]),
        k.copy("e27.checks.withdrawal.passed", hh_mm=hh),
        k.copy("e27.checks.rights.passed"),
        k.copy("e27.checks.trade.passed"),
        k.copy("e27.checks.uta.passed"),
        k.copy("e27.checks.uid.passed", uid=a["uid"]),
        k.copy("e27.checks.allowlist.passed", egress_ip="203.0.113.10"),
        k.copy("e27.checks.expiry.passed"),
        k.copy("e27.checks.probe.passed", n=4),
    ]
    return k.check_list([(n, "passed", w) for n, w in zip(nm, words)], w=DLG_W - 48)


def probes() -> Node:
    """The diagnostic lines under the check list: REST probe passed, WebSocket not checked."""
    return k.vbox(
        "probes",
        [
            k.hbox(
                "REST probe",
                [
                    k.glyph("check", k.STATUS["success.strong"]),
                    T("words", k.copy("e27.checks.rest_probe", n=118)),
                ],
                {"gap": k.INSET_XS},
            ),
            k.hbox(
                "WebSocket",
                [
                    k.glyph("dash", k.TEXT_2),
                    T("words", k.copy("e27.checks.ws_probe"), k.BODY, k.TEXT_2),
                ],
                {"gap": k.INSET_XS},
            ),
        ],
        {"gap": k.STACK_XS},
    )


def test_dialog(label: str, *, outcome_key: str, hh_mm_ss: str = "14:03:10") -> Node:
    """The Test dialog in its result form: the title, CP-6's before-sentence as its description, the result heading,
    the check list, the probes, the outcome sentence, [Close] (e27.shared.close)."""
    a = ACCTS[label]
    iw = DLG_W - 48
    items = [
        T(
            "title",
            k.copy("e27.scr125.test.title", label=label, key_id_masked=a["key"], ENV=a["env"]),
            k.HEADING_MD,
            w=iw,
        ),
        T("description", k.copy("e27.scr125.test.before"), k.BODY, k.TEXT_2, w=iw),
        T(
            "result heading",
            k.copy("e27.scr125.test.result", key_id_masked=a["key"], hh_mm_ss=hh_mm_ss),
            k.HEADING_SM,
            w=iw,
        ),
        test_checks(label, hh_mm_ss[:5]),
        probes(),
        T("outcome", k.copy(outcome_key), k.BODY_STRONG, w=iw),
        k.fit_row(k.hbox("footer", [btn(k.copy("e27.shared.close"))], {"justify": "end"}, w=iw)),
    ]
    return k.vbox(
        "CMP-043 Dialog · Test",
        items,
        {
            "fill": k.OVERLAY,
            "shadow": k.E_DIALOG,
            "radius": k.R_DIALOG,
            "pad": k.DIALOG_PAD,
            "gap": k.STACK_MD,
        },
        w=DLG_W,
        note='role="dialog"; after the answer focus is on the result heading',
    )


def error_row(s: str) -> Node:
    """CMP-027 inline error in a td colspan 4 with its [Retry]."""
    words, cta = split_cta(s)
    return k.hbox(
        "CMP-027 error · td colspan 4",
        [k.glyph("octagon", k.STATUS["danger.strong"]), T("words", words), btn(cta)],
        {"fill": k.RAISED, "padX": k.INSET_SM, "gap": k.INSET_SM},
        w=W,
        h=64,
    )


def skeleton_record(i: int) -> Node:
    """A CMP-015 shape row: two static 32 px lines (reduced motion)."""
    k._fallback("SKELETON")
    bars = [
        k.rect(f"bar {j}", w_ - 24, 12, k.HOVER, o={"radius": k.R_CONTROL})
        for j, w_ in enumerate(k.COLS, 1)
    ]
    line = k.hbox("line", bars, {"gap": k.INSET_XL, "padX": k.INSET_SM}, w=W, h=32)
    return k.vbox(
        f"CMP-015 skeleton record {i}",
        [line, dict(line, name="line · 2"), k.rect("hairline", W, 1, k.BORDER_DEFAULT)],
        {"fill": k.RAISED},
        w=W,
        h=65,
    )


# --- SCR-125's frames (§3.4 L1079-1091).
def k_button() -> Node:
    """Block K, collapsed."""
    return key_health_button(False)


def f1() -> dict[str, Any]:
    """CMP-087 / the accounts route: frame 6's content with the keys grace line and one strip item."""
    return page(
        verdict=k.verdict_line("dated", n=4, hh_mm=HH),
        content=[*list_block(std_records()), k_button()],
        grace="02:14",
        strip_items=[k.strip_item("e27.shell.strip.rotation_due", label="sub_002", n=12)],
    )


def f6() -> dict[str, Any]:
    """SCR-125 / ok: §3.1 exactly."""
    return page(
        verdict=k.verdict_line("dated", n=4, hh_mm=HH),
        content=[*list_block(std_records()), k_button()],
    )


def f7() -> dict[str, Any]:
    """SCR-125 / empty: the header rows over one CMP-026 body row; the verdict's no-keys form; no capacity line."""
    empty = k.hbox(
        "CMP-026 EmptyState · td colspan 4",
        [T("words", k.copy("e27.scr125.empty"), k.BODY, k.TEXT_2)],
        {"fill": k.RAISED, "padX": k.INSET_SM},
        w=W,
        h=64,
        note="no-data, cta omitted",
    )
    table = k.vbox("CMP-049 Table · emptyState", [table_head(), empty], {}, w=W)
    return page(
        verdict=k.verdict_line("no keys"),
        content=[k.section_heading("e27.shell.region.accounts"), table, k_button()],
    )


def f8() -> dict[str, Any]:
    """SCR-125 / loading and error: loading (three CMP-015 records, aria-busy) then the error inset (CMP-027 and the
    verdict's read-failed form); the capacity line keeps its own read."""
    loading = k.vbox(
        "CMP-049 Table · loading",
        [table_head(), *[skeleton_record(i) for i in (1, 2, 3)]],
        {},
        w=W,
        note='aria-busy="true"',
    )
    k.gap(
        "SCR-125 / loading and error: e27.scr125.error's {detail} is the server's text and no pinned doc gives an "
        "example, so the frame draws the slot '{detail}' as the deck writes it (never an invented reason)"
    )
    err = error_row(k.copy("e27.scr125.error", detail="{detail}"))
    err_state = k.vbox(
        "error state (nested)",
        [
            k.verdict_line("read failed"),
            k.vbox("CMP-049 Table · error", [table_head(), err], {}, w=W),
        ],
        {
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CARD,
            "padY": k.INSET_MD,
            "gap": k.STACK_SM,
        },
        w=W,
    )
    return page(
        verdict=k.verdict_line("loading"),
        content=[
            k.section_heading("e27.shell.region.accounts"),
            capacity("recorded"),
            loading,
            err_state,
        ],
    )


def f9() -> dict[str, Any]:
    """SCR-125 / key expiring: sub_002 rotation due (triangle), demo-1 Bybit expiry; both details open."""
    recs = std_records(
        sub_002=record("sub_002", state=k.state_badge("Rotation due in {n} d", n=12)),
        **{"demo-1": record("demo-1", state=k.state_badge("Bybit expiry in {n} d", n=9))},
    )
    ex = {
        "sub_002": [details("sub_002", [dtext(k.copy("e27.scr125.details.overdue_note"))])],
        "demo-1": [
            details("demo-1", [dtext(k.copy("e27.scr125.details.bybit_expiry", date="2026-11-01"))])
        ],
    }
    return page(
        verdict=k.verdict_line("dated", n=4, hh_mm=HH),
        content=[*list_block(recs, ex), k_button()],
        strip_items=[k.strip_item("e27.shell.strip.rotation_due", label="sub_002", n=12)],
    )


def f10() -> dict[str, Any]:
    """SCR-125 / within Bybit's 48 h restriction: sub_002 keyless; cell 3 spans both lines; health null; the menu
    inset opens on Add a key…."""
    span = T("first key 48 h", k.copy("e27.shared.first_key_48h"), k.BODY, k.TEXT_1, w=C3 - 2 * PAD)
    recs = std_records(
        sub_002=record(
            "sub_002",
            state=k.state_badge("No key — inactive"),
            facet="none",
            span3=span,
            hl=health("none"),
        )
    )
    kw = page(
        verdict=k.verdict_line("dated", n=3, hh_mm=HH), content=[*list_block(recs), k_button()]
    )
    mn = row_menu("sub_002", keyless=True, focused=k.copies("e27.scr125.menu.items")[1])
    kw["overlays"] = [layer(mn, 752, 664, kw["h"], "overlay · menu inset · sub_002")]
    return kw


def f11() -> dict[str, Any]:
    """SCR-125 / row menu and Test: (a) sub_001's menu, (b) the Test dialog's result, (c) the throttled minute,
    (d) another session's 429."""
    its = k.copies("e27.scr125.menu.items")
    kw = page(
        verdict=k.verdict_line("dated", n=4, hh_mm=HH),
        content=[*list_block(std_records()), k_button()],
    )
    h = kw["h"]
    a = row_menu("sub_001", focused=its[3])
    c = inset(
        "inset (c) · throttled",
        [
            k.menu(
                [k.menu_item(its[3], reason_key="keys.test_throttled", w=272, hh_mm_ss="14:04:10")],
                w=288,
            ),
            k.fit_row(
                k.hbox(
                    "dialog buttons",
                    [
                        btn(k.copy("e27.shared.cancel")),
                        k.t2_button(
                            k.copy("e27.scr125.test.buttons"),
                            "keys.test_throttled",
                            "primary",
                            w=180,
                            hh_mm_ss="14:04:10",
                        ),
                    ],
                    {"gap": k.INSET_SM, "align": "start", "justify": "end"},
                    w=288,
                )
            ),
        ],
        312,
    )
    d = inset(
        "inset (d) · 429",
        [
            k.hbox(
                "CMP-027 error",
                [
                    k.glyph("octagon", k.STATUS["danger.strong"]),
                    T(
                        "words",
                        k.say("Tested at 14:03:10 UTC; the next test can run at 14:04:10 UTC."),
                        k.BODY,
                        k.TEXT_1,
                        w=260,
                    ),
                ],
                {"gap": k.INSET_XS, "align": "start"},
            )
        ],
        312,
    )
    dlg = test_dialog("sub_001", outcome_key="e27.scr125.test.passed")
    kw["overlays"] = [
        k.overlay(dlg, x=704, y=72, h=h, name="overlay · Test dialog"),
        layer(a, 80, 72, h, "overlay · inset (a) · menu"),
        layer(c, 376, 72, h, "overlay · inset (c)"),
        layer(d, 376, 400, h, "overlay · inset (d)"),
    ]
    return kw


def f12() -> dict[str, Any]:
    """SCR-125 / at the sub-account cap: three insets of block G (h2 and the capacity line, no records)."""
    ins = [
        inset(
            f"block G inset · {f}", [k.section_heading("e27.shell.region.accounts"), capacity(f)], W
        )
        for f in ("cap", "unrecorded", "unavailable")
    ]
    for n in ins:
        n["kids"][1]["w"] = W - 24
    return page(verdict=k.verdict_line("dated", n=4, hh_mm=HH), content=ins)


def pop(kw: dict[str, Any], panel: Node, x: int, y: int, name: str) -> Node:
    """A popover / inset on the overlay layer at x, y, raised so it ends inside the frame."""
    y_ = min(y, kw["h"] - round(k.est_height(panel)) - 8)
    return layer(panel, x, y_, kw["h"], name)


def failed_head() -> list[Node]:
    """The verdict's failed form and the audit hint under it (e27.scr125.verdict.audit_hint)."""
    return [
        k.verdict_line("failed"),
        T("audit hint", k.copy("e27.scr125.verdict.audit_hint"), k.BODY, k.TEXT_2),
    ]


def f13() -> dict[str, Any]:
    """SCR-125 / withdrawal permission detected: BLOCKED beside the ordinary warnings; the menu inset."""
    its = k.copies("e27.scr125.menu.items")
    recs = std_records(
        sub_001=record(
            "sub_001", state=k.state_badge("Degraded — REST only"), hl=health("degraded")
        ),
        sub_002=record(
            "sub_002",
            state=k.state_badge("BLOCKED — fund right found"),
            blocked_line2=k.copy("e27.scr125.blocked.line2", label="sub_002"),
        ),
        **{"demo-1": record("demo-1", state=k.state_badge("Bybit expiry in {n} d", n=9))},
    )
    fh = failed_head()
    kw = page(
        verdict=fh[0],
        notices=[fh[1]],
        content=[*list_block(recs), k_button()],
        banners=[k.banner("e27.shell.banner.key_failed")],
        strip_items=[k.strip_item("e27.shell.strip.withdrawal", ENV="LIVE", label="sub_002")],
    )
    mn = row_menu("sub_002", gated={its[2]: "keys.compromise_path"}, focused=its[5])
    kw["overlays"] = [pop(kw, mn, 984, 760, "overlay · menu inset · sub_002")]
    return kw


def f14() -> dict[str, Any]:
    """SCR-125 / IP whitelist: sub_001 no match (details open, the address after a Test), Main none set."""
    s = k.copy("e27.scr125.details.allowlist", egress_ip="203.0.113.10")
    head, _, tail = s.partition(" [Copy]")
    copy_btn = btn(k.copy("e27.shared.copy"), "secondary", lead="copy", name="CMP-033 CopyButton")
    det = details(
        "sub_001",
        [
            dtext(part(head, s)),
            k.hbox(
                "Copy and the rest",
                [copy_btn, T("rest", part(tail.lstrip(), s), k.BODY)],
                {"gap": k.INSET_SM},
            ),
        ],
    )
    recs = std_records(
        Main=record(
            "Main",
            state=k.state_badge("IP allowlist: none set"),
            facet=k.cmp175("IP-missing", "inline", lead=False),
        ),
        sub_001=record(
            "sub_001",
            state=k.state_badge("IP allowlist: no match"),
            facet=k.cmp175("IP-mismatch", "inline", lead=False),
        ),
    )
    fh = failed_head()
    return page(
        verdict=fh[0],
        notices=[fh[1]],
        content=[*list_block(recs, {"sub_001": [det]}), k_button()],
        banners=[k.banner("e27.shell.banner.key_failed")],
    )


def f15() -> dict[str, Any]:
    """SCR-125 / key invalid: sub_002 "Key refused by Bybit" outranks its Down health; details open."""
    recs = std_records(
        sub_002=record("sub_002", state=k.state_badge("Key refused by Bybit"), hl=health("down"))
    )
    det = details(
        "sub_002", [dtext(k.copy("e27.scr125.details.key_refused", key_id_masked="...e5f6"))]
    )
    return page(
        verdict=k.verdict_line("dated", n=4, hh_mm=HH),
        content=[*list_block(recs, {"sub_002": [det]}), k_button()],
    )


def f16() -> dict[str, Any]:
    """SCR-125 / health degraded and down: sub_001 degraded (triangle), sub_002 down (octagon); details open."""
    recs = std_records(
        sub_001=record(
            "sub_001", state=k.state_badge("Degraded — REST only"), hl=health("degraded")
        ),
        sub_002=record(
            "sub_002",
            state=k.state_badge("Down — order entry off for this account"),
            hl=health("down"),
        ),
    )
    ex = {
        "sub_001": [details("sub_001", [dtext(k.copy("e27.scr125.details.degraded"))])],
        "sub_002": [
            details(
                "sub_002", [dtext(k.copy("e27.scr125.details.down", n=30, hh_mm_ss="14:01:31"))]
            )
        ],
    }
    return page(
        verdict=k.verdict_line("dated", n=4, hh_mm=HH), content=[*list_block(recs, ex), k_button()]
    )


def f17() -> dict[str, Any]:
    """SCR-125 / KEK unavailable: CMP-092's row, the one CMP-028 notice under the h1, the gated key items."""
    its = k.copies("e27.scr125.menu.items")
    kw = page(
        notices=[k.kek_notice(), k.verdict_line("unavailable")],
        content=[*list_block(std_records()), k_button()],
        banners=[k.banner("e27.shell.banner.kek")],
    )
    mn = row_menu("sub_001", gated={its[2]: "keys.kek_unavailable", its[3]: "keys.kek_unavailable"})
    kl = row_menu("a keyless record", keyless=True, gated={its[1]: "keys.kek_unavailable"})
    kw["overlays"] = [
        pop(kw, mn, 984, 600, "overlay · menu inset · sub_001"),
        pop(kw, kl, 688, 600, "overlay · menu inset · a keyless record"),
    ]
    return kw


# --- SCR-128 (§6 L1305-1388): the panel, its key table, the policy, the compromise card.
KCOLS = (
    96,
    72,
    80,
    56,
    168,
    216,
    128,
    56,
)  # Account · Key · Status · Age · Rotation due · Rights · Allowlist · Actions
KW = sum(KCOLS)


def kcell(i: int, kids: list[Node | None], **o: Any) -> Node:
    """A key-table cell, space.inset.sm."""
    return k.vbox(
        f"td {i}",
        kids,
        {"padX": k.INSET_SM, "padY": k.INSET_XS, "gap": k.STACK_XS, **o},
        w=KCOLS[i - 1],
    )


def ktable_head() -> Node:
    """The header row: color.surface.hover, type.ui.label color.text.primary, a 1 px color.border.subtle rule."""
    hs = k.copies("e27.scr128.table.headers")
    r = k.hbox(
        "header row",
        [
            k.hbox(f"th {i}", [T("label", h, k.LABEL)], {"padX": k.INSET_SM}, w=w_, h=32)
            for i, (h, w_) in enumerate(zip(hs, KCOLS), 1)
        ],
        {"fill": k.HOVER},
        w=KW,
        h=32,
    )
    return k.vbox("head", [r, k.rect("rule", KW, 1, k.BORDER_SUBTLE)], {}, w=KW)


def kgroup(env: str, n: int) -> Node:
    """A row group: th scope="rowgroup" with CMP-075's badge."""
    whole = k.copies("e27.scr125.group", n=n)[0 if env == "LIVE" else 1]
    return k.hbox(
        f"rowgroup · {env}",
        [k.env_pill(env), T("count", part(f"({n})", whole), k.LABEL)],
        {"fill": k.RAISED, "padX": k.INSET_SM, "gap": k.INSET_XS},
        w=KW,
        h=32,
    )


def actions_btn(label: str) -> Node:
    """The CMP-041 trigger: a 32 px target with the ⋮ glyph, named "Actions for ...{last4}"."""
    nm = k.copy("e27.scr128.row.actions", key_id_masked=ACCTS[label]["key"])
    return k.hbox(
        f"CMP-041 trigger · {nm}",
        [k.glyph("more", k.TEXT_1)],
        {"fill": k.ACTION["secondary"], "radius": k.R_CONTROL, "justify": "center"},
        w=32,
        h=32,
    )


def krow(label: str, *, chip: Node | None = None) -> Node:
    """A key row on color.surface.raised: label, CMP-034, the KeyStatus word, age, the due date (+ the CMP-011
    chip), the rights facets (dated), the allowlist facet, Actions."""
    a = ACCTS[label]
    rights = k.hbox(
        "rights",
        [k.cmp175("trade-only", "inline"), k.tglyph("·"), *verified_parts()],
        {"gap": k.INSET_XS, "wrap": "wrap", "align": "start"},
        w=KCOLS[5] - 16,
    )
    cells = [
        kcell(1, [T("account", k.fixture(label))]),
        kcell(2, [k.masked_id(a["key"])]),
        kcell(3, [T("status", k.copies("e27.scr128.status")[0])]),
        kcell(
            4,
            [
                T(
                    "age",
                    part(f"{a['age']} d", k.copy("e27.scr125.row.age", n=a["age"], date=a["due"])),
                    k.NUM_BASE,
                )
            ],
            align="end",
        ),
        kcell(
            5,
            [
                T(
                    "due",
                    part(
                        f"{a['due']} UTC", k.copy("e27.scr125.row.age", n=a["age"], date=a["due"])
                    ),
                    k.NUM_BASE,
                ),
                chip,
            ],
        ),
        kcell(6, [rights]),
        kcell(7, [k.cmp175("allowlist matches", "inline", lead=False)]),
        kcell(8, [actions_btn(label)]),
    ]
    row = k.hbox(f"key row · {label}", cells, {"fill": k.RAISED, "align": "start"}, w=KW)
    return k.vbox(f"tr · {label}", [row, k.rect("hairline", KW, 1, k.BORDER_DEFAULT)], {}, w=KW)


def ktable(chips: dict[str, Node] | None = None) -> Node:
    """CMP-049 table form: the visible caption, the head, LIVE (3) and DEMO (1)."""
    ch = chips or {}
    rows = [
        kgroup("LIVE", 3),
        *[krow(lb, chip=ch.get(lb)) for lb in ("Main", "sub_001", "sub_002")],
        kgroup("DEMO", 1),
        krow("demo-1", chip=ch.get("demo-1")),
    ]
    return k.vbox(
        "CMP-049 Table · keys",
        [T("caption", k.copy("e27.scr128.table.caption"), k.LABEL, k.TEXT_2), ktable_head(), *rows],
        {},
        w=KW,
        note="a plain table, no grid",
    )


POLICY = ("encrypted", "write_only", "backups", "allowlist", "withdrawal", "rotation", "kek")


def policy() -> Node:
    """The h3 and the seven sentences (D02:607-619), type.ui.body color.text.primary, a 720 px measure."""
    fills: dict[str, dict[str, Any]] = {
        "allowlist": {"egress_ip": "203.0.113.10"},
        "rotation": {"n": 90},
    }
    items = [
        T(
            f"sentence {i}",
            k.copy(f"e27.scr128.policy.{p}", **fills.get(p, {})),
            k.BODY,
            k.TEXT_1,
            w=720,
        )
        for i, p in enumerate(POLICY, 1)
    ]
    return k.vbox(
        "policy",
        [
            T("h3", k.copy("e27.scr128.policy.h3"), k.BODY_STRONG),
            k.vbox("list", items, {"gap": k.STACK_SM}, note="a list"),
        ],
        {"gap": k.STACK_SM},
    )


def panel(
    *, chips: dict[str, Node] | None = None, overdue: bool = False, kek: bool = False
) -> list[Node]:
    """SCR-128 open: the disclosure, [the KEK notice], the rate line, the key table, the Test sentence [+ the
    overdue note], the policy."""
    out: list[Node | None] = [
        key_health_button(True),
        k.kek_notice() if kek else None,
        T(
            "rate line",
            k.copy("e27.scr128.rate_budget", n=72, hh_mm_ss="14:02:11"),
            k.CAPTION,
            k.TEXT_2,
        ),
        ktable(chips),
        T("Test sentence", k.copy("e27.scr128.test_note"), k.BODY, k.TEXT_2, w=720),
        (
            T("overdue note", k.copy("e27.scr125.details.overdue_note"), k.BODY, k.TEXT_2)
            if overdue
            else None
        ),
        policy(),
    ]
    return [n for n in out if n]


def kmenu(label: str, *, gated: str | None = None) -> Node:
    """SCR-128's row menu: Test key… · Rotate key… (its ask line) · Suspected compromise…; gated= a reason key
    drawn on Test and Rotate (T2, §10.1)."""
    its = k.copies("e27.scr125.menu.items")
    if gated:
        items = [
            k.menu_item(its[3], reason_key=gated),
            k.menu_item(its[2], reason_key=gated),
            k.menu_item(its[5]),
        ]
    else:
        items = [
            k.menu_item(its[3]),
            k.menu_item(its[2], second=k.copy("e27.scr125.menu.ask.keys")),
            k.menu_item(its[5]),
        ]
    return k.menu(
        items,
        w=280,
        name=f"CMP-041 Menu · {k.copy('e27.scr128.row.actions', key_id_masked=ACCTS[label]['key'])}",
    )


def f42() -> Node:
    """SCR-128 / key table and the secrets-at-rest policy (the viewport scrolled to the open panel)."""
    return scrolled(
        k.BOARDS[NN].frames[13],
        panel(chips={"sub_002": k.state_badge("Rotation due in {n} d", n=12)}),
    )


def f43() -> Node:
    """SCR-128 / overdue rotation: sub_002's due cell over CMP-011's warning chip with the clock."""
    return scrolled(
        k.BOARDS[NN].frames[14],
        panel(chips={"sub_002": k.state_badge("Rotation overdue")}, overdue=True),
    )


def f44() -> Node:
    """SCR-128 / Test passed while trading is read-only: the Test dialog over the panel for Main's key (the viewport
    scrolled to the panel); the banner stays; Main's SCR-125 row keeps CMP-176's off-by-policy form, with no
    control (an inset: the row sits above the viewport)."""
    off = k.vbox(
        "off by policy",
        [
            k.state_badge("Off by policy"),
            T("sentence", k.copy("e27.scr128.off_by_policy"), k.BODY, k.TEXT_1, w=C2 - 16),
        ],
        {"gap": k.STACK_XS},
    )
    main_row = inset("inset · Main's SCR-125 row", [record("Main", state=off)], W + 24)
    dlg = test_dialog("Main", outcome_key="e27.scr125.test.passed_read_only")
    dh = round(k.est_height(dlg))

    def ovs(h: int) -> list[Node]:
        return [
            k.overlay(dlg, y=72, h=h, name="overlay · Test dialog"),
            layer(
                main_row, (k.FRAME_W - W - 24) // 2, 72 + dh + 16, h, "overlay · inset · Main's row"
            ),
        ]

    return scrolled(
        k.BOARDS[NN].frames[15],
        panel(),
        banners=[k.banner("e27.shell.banner.key_failed")],
        overlays=ovs,
    )


def f45() -> Node:
    """SCR-128 / KEK unavailable: the panel's one CMP-028 notice first in its body; Test and Rotate gated."""
    mn = kmenu("sub_001", gated="keys.kek_unavailable")
    return scrolled(
        k.BOARDS[NN].frames[16],
        panel(kek=True),
        banners=[k.banner("e27.shell.banner.kek")],
        overlays=lambda h: [layer(mn, 744, 400, h, "overlay · menu · ...c3d4")],
    )


# --- The compromise card (§6 Compromise card; D9's five steps in C-12.12's order).
CARD_W = W
SW = CARD_W - 32 - 4 - 32  # a step's text measure (padding, the rule, the number column)


def step(n: int, kids: list[Node | None]) -> Node:
    """One ordered step: its number, then its sentence(s) and control."""
    return k.hbox(
        f"step {n}",
        [
            k.hbox("number", [T("n", k._issue(str(n)), k.BODY_STRONG)], {}, w=24, h=20),
            k.vbox("body", kids, {"gap": k.STACK_XS}, w=SW),
        ],
        {"gap": k.INSET_SM, "align": "start"},
    )


def note_box(checked: bool) -> Node:
    """Step 2's CMP-005 note (BQ-15 item 6): it unlocks nothing and records nothing."""
    boxn = k.box(
        "CMP-005 box",
        [
            k.at(
                k.rect(
                    "box",
                    16,
                    16,
                    k.APP if not checked else k.ACTION["primary"],
                    o={"stroke": k.TEXT_3, "strokeWidth": k.HAIRLINE, "radius": k.R_CONTROL},
                ),
                0,
                0,
            ),
            (
                k.at(k.text("tick", k._issue("✓"), k.CAPTION, k.TEXT_ON_ACTION), 3, 0)
                if checked
                else None
            ),
        ],
        w=16,
        h=16,
    )
    return k.hbox(
        "CMP-005 Checkbox · note",
        [
            boxn,
            T("label", k.copy("e27.shared.bybit_note", key_id_masked="...c3d4"), k.BODY, w=SW - 24),
        ],
        {"gap": k.INSET_SM, "align": "start"},
    )


def card(step3: list[Node], *, checked: bool = False) -> Node:
    """CMP-050 region: color.surface.raised, radius.card, elevation.card, space.inset.lg; the danger rule on its
    inline-start edge; the h2 led by the octagon, [Close card]; the five steps; the tail and the marker.
    """
    lab = {"label": "sub_001", "key_id_masked": "...c3d4", "ENV": "LIVE"}
    head = k.hbox(
        "heading",
        [
            k.glyph("octagon", k.STATUS["danger.strong"]),
            T("h2", k.copy("e27.scr128.card.h2", **lab), k.HEADING_MD, w=SW - 140),
            btn(k.copy("e27.scr128.card.close"), "ghost"),
        ],
        {"gap": k.INSET_SM},
        w=CARD_W - 36,
    )
    steps = [
        step(
            1,
            [
                T("sentence", k.copy("e27.scr128.card.step1", label="sub_001"), w=SW),
                btn(k.copy("e27.scr128.card.step1.button", label="sub_001")),
            ],
        ),
        step(
            2,
            [
                T("sentence", k.copy("e27.scr128.card.step2", key_id_masked="...c3d4"), w=SW),
                note_box(checked),
            ],
        ),
        step(3, step3),
        step(4, [T("sentence", k.copy("e27.scr128.card.step4"), w=SW)]),
        step(
            5,
            [
                T("sentence", k.copy("e27.scr128.card.step5"), w=SW),
                btn(k.copy("e27.scr128.card.step5.button")),
            ],
        ),
    ]
    body = [
        head,
        T("lead", k.copy("e27.scr128.card.lead", label="sub_001"), w=CARD_W - 36),
        k.vbox("ordered steps", steps, {"gap": k.STACK_MD}, note="an ordered list (ol)"),
        T("tail", k.copy("e27.scr128.card.tail"), w=CARD_W - 36),
        T("marker", k.copy("e27.scr128.card.marker"), k.CAPTION, k.TEXT_3, w=CARD_W - 36),
    ]
    inner = k.vbox("card body", body, {"gap": k.STACK_MD}, w=CARD_W - 36)
    hh = round(k.est_height(inner)) + 32
    k._fallback("RULE4")
    rule = k.place(k.rect("danger rule (4 px)", 4, hh, k.STATUS["danger.strong"]), 0, 0)
    return k.vbox(
        "CMP-050 compromise card",
        [rule, inner],
        {
            "fill": k.RAISED,
            "radius": k.R_CARD,
            "shadow": k.E_CARD,
            "padL": k.INSET_LG,
            "padR": k.INSET_LG,
            "padY": k.INSET_LG,
        },
        w=CARD_W,
        h=hh,
        note='role="region" labelled by its h2; region "Suspected compromise" first under the h1',
    )


def step3_default() -> list[Node]:
    """Step 3 as the card opens."""
    return [
        T("sentence", k.copy("e27.scr128.card.step3"), w=SW),
        btn(k.copy("e27.scr128.card.step3.button")),
        T("note", k.copy("e27.scr128.card.step3.note"), k.BODY, k.TEXT_2, w=SW),
    ]


def card_page(c: Node, *, dead: bool = False) -> dict[str, Any]:
    """The card first under the h1, then the Accounts region (the viewport ends under the card: a page scroll).
    dead=True (frame 48): the key failed its check at Bybit, so a read-only notice holds and §2.1's dated form
    (no read-only notice, every stored key passed, L386) cannot: the verdict takes its failed form under CMP-092's
    key_failed row, and sub_001's record reads "Key refused by Bybit" with its Down health (frame 15's form).
    """
    if not dead:
        kw = page(
            verdict=k.verdict_line("dated", n=4, hh_mm=HH),
            content=[c, *list_block(std_records()), k_button()],
        )
        kw["h"] = need_h([kw["verdict"], c, k.section_heading("e27.shell.region.accounts")])
        return kw
    recs = std_records(
        sub_001=record("sub_001", state=k.state_badge("Key refused by Bybit"), hl=health("down"))
    )
    fh = failed_head()
    kw = page(
        verdict=fh[0],
        notices=[fh[1]],
        content=[c, *list_block(recs), k_button()],
        banners=[k.banner("e27.shell.banner.key_failed")],
    )
    kw["h"] = need_h([kw["verdict"], fh[1], c, k.section_heading("e27.shell.region.accounts")], 1)
    return kw


def f46() -> dict[str, Any]:
    """SCR-128 / mark as compromised: the ordered card."""
    return card_page(card(step3_default()))


def f47() -> dict[str, Any]:
    """The revoke refused: step 3's line becomes the CMP-027 inline error and the next step at once."""
    err = k.hbox(
        "CMP-027 inline error",
        [
            k.glyph("octagon", k.STATUS["danger.strong"]),
            T(
                "words",
                k.copy("e27.scr128.card.refused", symbol="BTCUSDT", side="long", qty="0.250"),
                w=SW - 24,
            ),
        ],
        {"gap": k.INSET_XS, "align": "start"},
        note='role="alert", assertive once',
    )
    s3 = [
        T("sentence", k.copy("e27.scr128.card.step3"), w=SW),
        btn(k.copy("e27.scr128.card.step3.button")),
        err,
        T("next", k.copy("e27.scr128.card.refused.next"), k.BODY_STRONG, w=SW),
    ]
    return card_page(card(s3))


def f48() -> dict[str, Any]:
    """After the Bybit delete, the account reads dead: step 3's two sentences; the note as the owner left it."""
    s3 = [
        T(
            "dead",
            k.copy("e27.scr128.card.dead", key_id_masked="...c3d4", label="sub_001", n=2),
            w=SW,
        ),
        T("containment", k.copy("e27.scr128.card.containment"), w=SW),
        btn(k.copy("e27.scr128.card.step3.button")),
    ]
    return card_page(card(s3, checked=True), dead=True)


# --- The cells (frame, strips, notes, PROPOSED stamps) in §0's order.
REC = [
    "HD3",
    "HD5",
    "HD10",
]  # CMP-176 slots, CMP-034 text-only, CMP-178 inline: on every frame drawing records
SPEC: list[tuple[Callable[[], Any], list[tuple[str, str]], list[str], list[str]]] = [
    (
        f1,
        [],
        [
            (
                "Redline (§3.1): A TopBar y 0-48, NavRail x 0-64, RightRail x 1040-1280, StatusBar y 752-800; C band "
                "y 48-80, rule 80-84, strip 84-116; D PageHeader y 132-164; E verdict y 176-208; G h2 y 224-256, "
                "capacity 256-288; H head 288-352; I/J LIVE 352-612, DEMO 612-720; K 736-768 and L 780-796 under the "
                "viewport line (a page scroll)"
            ),
            (
                "the route content is frame 6's; the strip item's accessible name "
                "leads with Attention: (D02:150)"
            ),
        ],
        REC,
    ),
    (
        f6,
        [],
        [
            "§3.1 exactly: four records OK, Healthy · 2 s; K and L drawn as the continuation under the 800 px line"
        ],
        REC,
    ),
    (f7, [], ["no capacity line; + Add account is the one call to action"], []),
    (
        f8,
        [],
        [
            (
                "upper: loading (static under reduced motion); the inset: the error state; {detail} is the server's "
                "text (no pinned example), drawn as its slot"
            )
        ],
        [],
    ),
    (
        f9,
        [],
        [
            (
                "both details rows drawn open in place (demo-1's is an inset in E27-D02); E42-D03's strip.key_expiry "
                "says 'expires' for the policy clock, which D7 forbids: D03-C6"
            )
        ],
        REC + ["D03-C6"],
    ),
    (
        f10,
        [],
        [
            (
                "the menu inset opens on Add a key…; Delete (keeps history)… on a never-keyed account is T2 "
                "(accounts.never_keyed), drawn on board 08 (SCR-129 frame 60): not drawn here; the timed form waits "
                "for G-3 (D02:1001-1003)"
            )
        ],
        REC,
    ),
    (
        f11,
        [("G-8, #895 / #898", "the password-and-code ask on Disable… and Delete…")],
        [
            (
                "(a) sub_001's menu, left; (b) the Test dialog's result, right (Run test busy is not drawn — the text is "
                "binding); (c) the minute after this client's test: Test key… and Run test gated by keys.test_throttled; "
                "(d) another session's 429, a refusal at the point of action, never gated"
            ),
            "Close is e27.shared.close (new)",
        ],
        REC,
    ),
    (
        f12,
        [],
        [
            "three insets of block G: at the cap, tier unrecorded, cap unavailable; + Add account stays enabled"
        ],
        [],
    ),
    (
        f13,
        [("G-1, #895 / #896", "the blocked record, its strip item and its gated Rotate key…")],
        [
            "E42-D03's strip.withdrawal says 'remove it on Bybit'; C-12.12 deletes the key at Bybit: D03-C7"
        ],
        REC + ["HD4", "BQ-6", "D03-C7"],
    ),
    (
        f14,
        [
            ("D03-G1, #896", "the egress IP and its Copy before a Test this client ran"),
            ("G-1, #895 / #896", "the record"),
        ],
        [
            (
                "drawn after a Test this client ran (CMP-033 on 203.0.113.10); Main's empty allowlist drawn in place (an "
                "inset in E27-D02)"
            )
        ],
        REC + ["HD14"],
    ),
    (
        f15,
        [],
        ["'Key refused by Bybit' outranks the Down its health line shows (§3.2 rank 2 over 4)"],
        REC,
    ),
    (f16, [], ["no number for a value not received"], REC),
    (
        f17,
        [],
        [
            (
                "two menu insets: sub_001's (Rotate key… and Test key… gated) and a keyless record's (Add a key… "
                "gated), all by keys.kek_unavailable; Revoke key… stays live (D17)"
            )
        ],
        REC + ["HD6"],
    ),
    (
        f42,
        [("D03-G1, #896", "the policy's address (BQ-15 item 7)")],
        [
            "the viewport scrolled to the open panel (§6: 1280 × 800 inside SCR-125's page; blocks C-J as frame 6)"
        ],
        ["HD16", "HD14"],
    ),
    (
        f43,
        [],
        [
            (
                "the viewport scrolled to the panel; the shell's strip carries 'Rotation overdue for sub_002 → "
                "Rotate' (above the viewport); the cell's accessible text is 'Rotation overdue since 2026-11-04 UTC'"
            )
        ],
        ["HD16"],
    ),
    (
        f44,
        [("G-12, #3657", "Main's off-by-policy form")],
        [
            (
                "the viewport scrolled to the panel, the dialog over it; Main's SCR-125 row (above the viewport) drawn as an "
                "inset under the dialog; nothing on the frame says trading resumed (AD-1); focus on the result's heading"
            )
        ],
        REC + ["HD4", "HD16"],
    ),
    (
        f45,
        [],
        [
            (
                "the viewport scrolled to the panel; one notice per screen (D17, BQ-9); Suspected compromise… and "
                "the card's Revoke here… stay enabled"
            )
        ],
        ["HD6"],
    ),
    (
        f46,
        [],
        [
            "no Rotate on the card; no step is a wait; the viewport ends under the card (the list scrolls)"
        ],
        [],
    ),
    (
        f47,
        [],
        [
            (
                "or 'Not revoked: the account is not flat.' (e27.scr128.card.refused.not_flat; not drawn — the text "
                "is binding); Revoke here… stays enabled for a retry"
            )
        ],
        [],
    ),
    (
        f48,
        [],
        [
            "Revoke here… opens §7's revoke dialog with leaving the positions as its only choice (board 08)",
            (
                "the row is silent on the verdict: the card says trading is read-only for every account, so §2.1's "
                "dated form (no read-only notice, every stored key passed) cannot hold; drawn in its failed form "
                "under CMP-092's key_failed row, sub_001 as frame 15's 'Key refused by Bybit' (owner to confirm)"
            ),
        ],
        [],
    ),
]


def build_cells() -> list[Node]:
    """Board 04's 20 cells in §0's order (gen_05 draws them again for the light twin)."""
    frames = k.BOARDS[NN].frames
    if len(frames) != len(SPEC):
        raise SystemExit(
            f"§0 names {len(frames)} frames for board 04; the generator builds {len(SPEC)}"
        )
    out = []
    for name, (fn, strips, notes, prop) in zip(frames, SPEC):
        out.append(k.frame(name, fn, strips=strips, notes=notes, proposed=prop))
    return out


SOURCE = "E27-D03 §0 L221; §3.1 L973-1008, §3.2 L1009-1061, §3.4 L1079-1091; §6 L1305-1388"
NOT_DRAWN = [
    (
        "SCR-125's Run test busy and the Test dialog's before form (frame 11 (b)); the error alternative "
        "'Not revoked: the account is not flat.' (frame 47); the 200 % reflow (board 10)"
    )
]


def emit(nn: int, cells: list[Node]) -> None:
    """Board, sheet, compacted twin, .md."""
    bd = k.board(
        nn,
        cells,
        source=SOURCE,
        cols=4,
        not_drawn=NOT_DRAWN,
        notes=[
            (
                "records: Main ...a1b2 41 d, sub_001 ...c3d4 12 d, sub_002 ...e5f6 78 d, demo-1 ...a7b8 30 d "
                "(frame 42's facts, D02:597-603); Healthy · 2 s and verified 14:02 UTC throughout"
            ),
            "frames taller than 800 draw §3.1's continuation under the viewport line",
        ],
    )
    path = k.KIT_DIR / f"{k.stem(nn)}.json"
    print(k.write_sheet(path, bd))
    rep = k.compact_sheet(path)
    md = k.write_board_md(
        nn,
        bd,
        checks=[
            "§0's 20 frames by exact name, in §0's order; T2 only on frames 11, 13, 17, 45 (E27-D02 §7 'shows T2')",
            "every frame string issued from the deck / §12.2 reasons / quoted hi-fi text / fixtures",
            "stamps and 'not yet served' strips on the annotation layer only",
        ],
    )
    print(md.name, rep)


if __name__ == "__main__":
    emit(NN, build_cells())
