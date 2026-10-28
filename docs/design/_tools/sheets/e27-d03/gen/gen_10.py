#!/usr/bin/env python3
"""gen_10.py: E27-D03 (#816) board 10, `E27-D03 / 10 keyboard-zoom-forced-colours` (offline; no Penpot, no network).

Draws (§0 L227; §11 L1918-2002; §3.6 L1108-1124): specimen cells only (no inventory frame) — focus order,
landmarks and live regions for SCR-125, SCR-126, SCR-127, SCR-129 and SCR-079 (§11's keyboard model and
announcement table); the 125 %, 200 % and 150 %-text specimens (§11 R1, §3.6, §2.2 sizes); a forced-colours strip
with the critical chip, the blocked row, a T2 menu item, the stale chip and the ring (§9 L1761-1780, R2). Every
string inside a specimen card is issued by the deck, §12.2 or the pinned text (k.copy / k.reason / k.say).
Reuses gen_03's row176 / card200 / health178 helpers.

Run: python3 -I -B docs/design/_tools/sheets/e27-d03/gen/gen_10.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
GEN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(GEN_DIR.parent))
sys.path.insert(0, str(GEN_DIR))
import gen_03 as g3

import e27d03kit as k

NN = 10
S = k.say
CW = 1240  # specimen card width (each card <= 1280, build notes §3)
COLW = (372, 352, 436)  # focus order · landmarks · live regions


# --- The three columns of a surface specimen.
def _num(i: int) -> k.Node:
    """A focus-order number: a 20 px ring in color.focus.ring holding the step number (board chrome look)."""
    k._fallback("PILL")
    return k.hbox(
        "n",
        [k.text("n", S(str(i)) if i > 9 else k.say(str(i)), k.CAPTION, k.TEXT_1)],
        {
            "justify": "center",
            "stroke": k.FOCUS_RING,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_PILL,
        },
        w=20,
        h=20,
    )


def order(
    items: list[str | tuple[str, str]], *, head: str | None = None, w: int = COLW[0]
) -> k.Node:
    """The Tab order as numbered steps; an item (label, second) carries a caption line."""
    rows: list[Any] = [k.text("head", head or S("Tab order"), k.LABEL, k.TEXT_2)]
    for i, it in enumerate(items, 1):
        lab, sec = (it, None) if isinstance(it, str) else it
        txt = k.vbox(
            "text",
            [
                k.text("label", lab, k.BODY, k.TEXT_1, w=w - 32),
                k.text("second", sec, k.CAPTION, k.TEXT_2, w=w - 32) if sec else None,
            ],
            {"gap": k.STACK_XS},
        )
        rows.append(k.hbox(f"step {i}", [_num(i), txt], {"gap": k.INSET_SM, "align": "start"}, w=w))
    return k.vbox("focus order", rows, {"gap": k.STACK_XS}, w=w)


def landmarks(items: list[tuple[str, str | None]], *, w: int = COLW[1]) -> k.Node:
    """Landmarks and roles: an outlined box per landmark, its role (num) and its name."""
    rows: list[Any] = [k.text("head", S("landmarks"), k.LABEL, k.TEXT_2)]
    for role, name in items:
        rows.append(
            k.vbox(
                f"landmark · {role[:30]}",
                [
                    k.text("role", role, k.NUM_BASE, k.TEXT_1, w=w - 18),
                    k.text("name", name, k.BODY, k.TEXT_2, w=w - 18) if name else None,
                ],
                {
                    "stroke": k.BORDER_DEFAULT,
                    "strokeWidth": k.HAIRLINE,
                    "radius": k.R_CONTROL,
                    "padX": k.INSET_SM,
                    "padY": k.INSET_XS,
                    "gap": k.STACK_XS,
                },
                w=w,
            )
        )
    return k.vbox("landmarks", rows, {"gap": k.STACK_XS}, w=w)


def live(rows_: list[tuple[str, str, str]], *, w: int = COLW[2]) -> k.Node:
    """Live regions: per event its region, when, and the text it speaks (§11's announcement table)."""
    rows: list[Any] = [k.text("head", S("live regions"), k.LABEL, k.TEXT_2)]
    for i, (region, when, said) in enumerate(rows_, 1):
        rows.append(
            k.vbox(
                f"announcement {i}",
                [
                    k.hbox(
                        "where",
                        [
                            k.text("region", region, k.CAPTION, k.TEXT_1),
                            k.tglyph("·", k.TEXT_2),
                            k.text("when", when, k.CAPTION, k.TEXT_2),
                        ],
                        {"gap": k.INSET_XS, "wrap": "wrap"},
                        w=w - 16,
                    ),
                    k.text("says", said, k.BODY, k.TEXT_1, w=w - 16),
                ],
                {
                    "gap": k.STACK_XS,
                    "padX": k.INSET_SM,
                    "padY": k.INSET_XS,
                    "fill": k.RAISED,
                    "radius": k.R_CONTROL,
                },
                w=w,
            )
        )
    return k.vbox("live regions", rows, {"gap": k.STACK_XS}, w=w)


def surface(title: str, cols: list[k.Node], extra: list[k.Node] | None = None, **kw: Any) -> k.Node:
    """One surface's specimen: the three columns side by side, then extra rows."""
    body = k.hbox("columns", cols, {"gap": k.INSET_XL, "align": "start"}, w=CW - 32)
    return k.specimen(title, [body, *(extra or [])], w=CW, **kw)


# --- The five surfaces (§11 L1928-1940 keyboard model; L1966-1997 announcements).
def scr125() -> k.Node:
    fo = order(
        [
            S("skip link"),
            S("strip items"),
            k.copy("e27.shell.cta.add"),
            (k.copy("e27.scr125.blocked.action"), S("(a blocked row only, first)")),
            k.copy("e27.scr125.row.actions", label="sub_002", ENV="LIVE"),
            k.copy("e27.scr125.row.details", label="sub_002", ENV="LIVE"),
            S("the SCR-128 disclosure"),
            S("SCR-128's per-key Actions"),
            S("the footer"),
        ]
    )
    lm = landmarks(
        [
            (S('role="region"'), S("Admin area")),
            (S("Needs your action"), None),
            (k.copy("e27.shell.h1"), S("the skip link lands on the h1")),
            (k.copy("e27.shell.region.compromise"), None),
            (k.copy("e27.shell.region.accounts"), None),
            (k.copy("e27.shell.region.health"), None),
        ]
    )
    lv = live(
        [
            (
                S("CMP-092's blocking row"),
                S("once per episode"),
                k.copy("e27.shell.banner.key_failed"),
            ),
            (
                S("the shell announcer, assertive"),
                S("once per transition, never on a refresh"),
                k.copy(
                    "e27.shared.announce.chip",
                    label="sub_002",
                    ENV="LIVE",
                    chip=k.copy("e27.scr125.chip.down"),
                ),
            ),
            (S("the shell announcer, polite"), S("once"), k.copy("e27.shell.banner.cleared")),
            (
                S("assertive on a fail, polite on a pass"),
                S("once"),
                k.copy("e27.scr125.test.failed", check=S("Withdrawal and transfer")),
            ),
            (
                S("none"),
                S("the line changes silently"),
                k.copy("e27.scr125.verdict.overdue", hh_mm="13:47"),
            ),
        ]
    )
    ring = k.hbox(
        "drawn focus",
        [
            k.focus_ring(k.add_account()),
            k.focus_ring(
                k.button(
                    k.copy("e27.scr125.row.actions", label="Main", ENV="LIVE"),
                    "secondary",
                    lead="more",
                )
            ),
        ],
        {"gap": k.INSET_XL},
    )
    return surface(
        "SCR-125 · focus order, landmarks and live regions (§11)",
        [fo, lm, lv],
        [ring],
        notes=[
            (
                "a plain <table> with a caption, two header rows and th scope=row: no grid, no roving "
                "tabindex (D22); comfortable, 32 px controls"
            )
        ],
    )


def scr126() -> k.Node:
    reg = order(
        [
            S("Label"),
            S("Bybit UID"),
            S("Kind"),
            S("Parent (a sub only)"),
            k.copy("e27.shared.cancel"),
            k.copy("e27.scr126.register.buttons"),
        ],
        head=k.copy("e27.scr126.stepper", 0),
    )
    key = order(
        [
            (k.copy("e27.shared.copy"), S("the target state before any check")),
            S("API key"),
            S("API secret"),
            k.copy("e27.shared.cancel"),
            k.copy("e27.scr126.buttons"),
        ],
        head=k.copy("e27.scr126.stepper", 1),
    )
    lm = landmarks(
        [
            (S("a page"), None),
            (S('the CMP-066 nav stepper with aria-current="step"'), None),
            (S("focus on the step heading after a step change"), None),
        ]
    )
    lv = live(
        [
            (S('CMP-027 role="alert"'), S("once"), k.copy("e27.scr126.refused.lead")),
            (
                S("polite"),
                S("once"),
                k.copy("e27.scr126.saved", key_id_masked="...a7b8", label="demo-1"),
            ),
            (S("polite"), S("once"), k.copy("e27.scr126.validating.long")),
        ],
        w=CW - 32 - 2 * COLW[0] - 48,
    )
    sp = surface(
        "SCR-126 add · focus order, landmarks and live regions (§11)",
        [reg, key, lm],
        [lv],
        proposed=["HD14"],
        notes=[
            (
                "Enter in a field sends the step's one action; after an answer focus moves to the result "
                "heading"
            )
        ],
    )
    return g3.strip_on(sp, g3.DG1, "Copy: the egress IP before any check (key step, Tab stop 1)")


def scr127() -> k.Node:
    fo = order(
        [
            S("stage content"),
            k.copy("e27.shared.cancel"),
            S("Back"),
            S("the primary (Next, Verify and switch, Close)"),
        ]
    )
    lm = landmarks(
        [
            (S('role="dialog"'), None),
            (S('aria-modal="true"'), None),
            (S("the stage heading"), S('aria-current="step"')),
        ]
    )
    lv = live(
        [
            (
                S("no live region: focus moves to the stage heading"),
                S("each stage"),
                k.copy("e27.scr127.stage2.h2"),
            ),
            (
                S("assertive"),
                S("once"),
                k.copy("e27.scr127.stage3.refused", key_id_masked="...e5f6"),
            ),
            (
                S("polite"),
                S("once each"),
                k.copy("e27.scr127.overlap.at60", old="...e5f6", hh_mm_ss="10:55:01"),
            ),
            (
                S("polite"),
                S("once each"),
                k.copy("e27.scr127.overlap.at10", old="...e5f6", hh_mm_ss="10:55:01"),
            ),
            (S("polite"), S("once"), k.copy("e27.scr127.stage5.revoked")),
        ]
    )
    return surface(
        "SCR-127 wizard · focus order, landmarks and live regions (§11)",
        [fo, lm, lv],
        notes=[
            (
                "Esc = Cancel at stages 1, 2 and 5; at stages 3 and 4 it closes the view only; the "
                "countdown never speaks per tick (CMP-035 aria-live=off)"
            )
        ],
        proposed=["HD7"],
    )


def scr129() -> k.Node:
    fo = order(
        [S("the radio group"), S("the typed field"), k.copy("e27.shared.cancel"), S("the confirm")]
    )
    lm = landmarks(
        [
            (S('role="alertdialog"'), S("aria-describedby the first consequence")),
            (S("while the summary loads only Cancel is rendered"), None),
        ]
    )
    lv = live(
        [
            (S("polite"), S("once"), k.copy("e27.scr129.loading.slow")),
            (S("polite; focus stays on Cancel"), S("once"), S("the first consequence sentence")),
            (
                S('CMP-027 role="alert"'),
                S("once"),
                k.copy("e27.scr129.error.timeout", label="sub_002", n=5),
            ),
            (S("polite"), S("once"), k.copy("e27.scr125.outcome.disabled", hh_mm="14:12")),
            (
                S("polite"),
                S("once"),
                k.copy("e27.shell.notice.deleted", label="sub_002", ENV="LIVE"),
            ),
        ]
    )
    return surface(
        "SCR-129 disable, delete, revoke · focus order, landmarks and live regions (§11)",
        [fo, lm, lv],
        notes=[
            (
                "E42-D03's rung order, PROPOSED over D02:765-767: the first Tab from "
                "Cancel reaches the confirm; Enter never confirms (D22)"
            )
        ],
        proposed=["HD8"],
    )


def scr079() -> k.Node:
    fo = order(
        [
            S("Close"),
            S("Change leverage…"),
            S("the position-mode segments"),
            S("the margin-mode segments"),
            (k.copy("e27.shared.copy"), S("the Owner's IP mismatch, where served")),
            S("the two links"),
        ]
    )
    lm = landmarks(
        [
            (S('role="dialog"'), S('aria-modal="true"')),
            (S("labelled by the h2"), S("focus on the h2")),
        ]
    )
    lv = live(
        [
            (S("none"), S("silent"), k.copy("e27.scr079.balances.caption", hh_mm_ss="14:02:11")),
            (S("polite"), S("once"), k.copy("e27.scr079.announce.stale", hh_mm_ss="14:02:11")),
            (S("assertive"), S("once"), k.reason("accounts.key_rejected")),
        ]
    )
    with k.density("compact"):
        ring = k.hbox(
            "drawn focus · compact",
            [k.focus_ring(k.button(S("Change leverage…"), "secondary"))],
            {"gap": k.INSET_XL},
        )
    return surface(
        "SCR-079 drawer · focus order, landmarks and live regions (§11)",
        [fo, lm, lv],
        [ring],
        notes=[
            (
                "compact: 24 px controls, exactly the WCAG 2.2 §2.5.8 minimum; T2 controls keep their "
                "place"
            )
        ],
    )


# --- Zoom and text scale (§11 R1 L1942-1958; §3.6 L1110-1116; §2.2 L580-592).
def zoom125() -> k.Node:
    with k.density("compact"):
        cmp_row = g3.row176("ok", w=688)
    return k.specimen(
        "125 % zoom · SCR-125 at 1024 CSS px, the compact SCR-128 row (§3.6; §11 R1)",
        [
            k.hbox(
                "facts",
                [
                    k.text("viewport", S("1024 × 640 CSS px"), k.NUM_BASE, k.TEXT_1),
                    k.text("content", S("the content is 720 px, 688 inside"), k.CAPTION, k.TEXT_2),
                    k.text("shares", S("25 · 25 · 29 · 20 %"), k.NUM_BASE, k.TEXT_2),
                ],
                {"gap": k.INSET_LG},
            ),
            g3.row176("ok", w=688),
            g3.row176("blocked", w=688),
            k.text("compact", S("every column kept"), k.LABEL, k.TEXT_2),
            cmp_row,
        ],
        notes=[
            (
                "the four columns keep their shares at 688 px; cells wrap and records grow, no column dropped "
                "(BQ-4); the compact row is the component's other mode (HD12)"
            )
        ],
        proposed=["HD12"],
        w=720,
    )


def zoom200() -> k.Node:
    dlg = k.rung_dialog(
        k.copy("e27.scr129.revoke.title", key_id_masked="...e5f6", label="sub_002", ENV="LIVE"),
        [k.copy("e27.scr129.revoke.not_last", label="sub_002", new="...d9e0")],
        rung=1,
        confirm=k.button(
            k.copy("e27.scr129.revoke.confirm", key_id_masked="...e5f6"), "destructive"
        ),
        marker="e27.scr129.marker.revoke",
        w=608,
    )
    return k.specimen(
        "200 % zoom · 640 × 400 CSS px: cards, collapsed steppers, the dialog (§11 R1)",
        [
            k.text("viewport", S("640 × 400 CSS px"), k.NUM_BASE, k.TEXT_1),
            g3.card200(w=608),
            k.text(
                "SCR-126 collapsed",
                k.copy("e27.scr126.stepper.collapsed", n=2, step=k.copy("e27.scr126.stepper", 1)),
                k.BODY_STRONG,
                k.TEXT_1,
            ),
            k.text(
                "SCR-127 collapsed",
                k.copy("e27.scr127.stepper.collapsed", n=2, stage=k.copy("e27.scr127.stepper", 1)),
                k.BODY_STRONG,
                k.TEXT_1,
            ),
            dlg,
            k.text("sticky", S("the footer stays one sticky row"), k.CAPTION, k.TEXT_2),
        ],
        notes=[
            (
                "the dialog fills the viewport, its body scrolls; a sticky header or footer leaves scroll padding "
                "equal to its height (WCAG 2.4.11)"
            )
        ],
        proposed=["HD12"],
        w=640,
    )


def text150() -> k.Node:
    return k.specimen(
        "150 % text scale · rows grow, chips wrap (§11 R1; §2.2)",
        [
            k.text("scale", S("150 % text scale"), k.NUM_BASE, k.TEXT_1),
            k.text("rows", S("rows grow"), k.LABEL, k.TEXT_2),
            g3.row176("blocked", w=560),
            k.text(
                "chips",
                S("chips wrap to a second line and never truncate"),
                k.CAPTION,
                k.TEXT_2,
                w=560,
            ),
        ],
        notes=[
            (
                "drawn at the token sizes: no 150 % type token exists, so the scale is shown by the narrower record "
                "(min-height lines growing by whole lines, chips wrapping), not by enlarged glyphs"
            )
        ],
        proposed=["HD12"],
        w=600,
    )


# --- Forced colours (§9 L1761-1780; R2): each carrier as normally drawn, then in forced colours. Stand-ins (no
# system-colour tokens exist): Canvas = color.surface.app, CanvasText = color.text.primary, GrayText =
# color.text.tertiary, Highlight = color.focus.ring; the system colour is named in words under each.
def _fc(name: str, kids: list[Any], *, stroke: bool = True, w: int | None = None) -> k.Node:
    o: dict[str, Any] = {
        "fill": k.APP,
        "gap": k.INSET_XS,
        "padX": k.INSET_SM,
        "padY": k.INSET_XS,
        "radius": k.R_BADGE,
    }
    if stroke:
        o.update(stroke=k.TEXT_1, strokeWidth=k.HAIRLINE)
    return k.hbox(name, kids, o, w=w)


def _pair(title: str, normal: k.Node, forced: k.Node, carries: str) -> k.Node:
    return k.vbox(
        f"carrier · {title[:36]}",
        [
            k.text("carrier", title, k.LABEL, k.TEXT_1),
            k.hbox(
                "looks",
                [normal, k.tglyph("→", k.TEXT_2), forced],
                {"gap": k.INSET_MD, "align": "center", "wrap": "wrap"},
                w=600,
            ),
            k.text("carries", carries, k.CAPTION, k.TEXT_2, w=600),
        ],
        {"gap": k.STACK_XS},
        w=600,
    )


def forced() -> k.Node:
    crit_word = k.copy("e27.cmp175.withdrawal_detected")
    crit = _pair(
        S("The critical mark"),
        k.cmp175("withdrawal-detected (critical)"),
        k.hbox(
            "forced · critical",
            [k.glyph("octagon", k.TEXT_1), k.text("word", crit_word, k.LABEL, k.TEXT_1)],
            {
                "fill": k.APP,
                "stroke": k.TEXT_1,
                "strokeWidth": k.THICK,
                "radius": k.R_BADGE,
                "padX": k.INSET_MD,
                "padY": k.INSET_XS,
                "gap": k.INSET_XS,
            },
        ),
        S("the border becomes CanvasText and survives; the bold survives"),
    )
    sent = k.copy("e27.scr125.blocked.line2", label="sub_002")
    blocked = _pair(
        S("CMP-176 blocked row"),
        g3.row176("blocked", w=560),
        k.hbox(
            "forced · blocked row",
            [k.rect("rule", 4, 56, k.TEXT_1), k.text("sentence", sent, k.BODY, k.TEXT_1, w=520)],
            {"fill": k.APP, "gap": k.INSET_SM, "align": "start"},
            w=560,
        ),
        S("the fill drops; the rule is a border, so it stays as CanvasText"),
    )
    mi = k.copies("e27.scr125.menu.items")
    t2n = k.menu([k.menu_item(mi[2], reason_key="keys.kek_unavailable")], w=280)
    t2f = k.vbox(
        "forced · T2 menu item",
        [
            k.hbox(
                "label",
                [k.lock(k.TEXT_3), k.text("label", mi[2], k.BODY, k.TEXT_3)],
                {"gap": k.INSET_XS},
            ),
            k.text("reason", k.reason("keys.kek_unavailable"), k.CAPTION, k.TEXT_1, w=240),
        ],
        {
            "fill": k.APP,
            "stroke": k.TEXT_1,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CARD,
            "padX": k.INSET_SM,
            "padY": k.INSET_XS,
            "gap": k.STACK_XS,
        },
        w=272,
    )
    t2 = _pair(
        S("A T2 control"),
        t2n,
        t2f,
        S("label and lock GrayText; the reason CanvasText; the hairline " "CanvasText"),
    )
    stale_w = k.copy("e27.scr079.stale", hh_mm_ss="14:02:11")
    stale = _pair(
        S("CMP-239 stale chip"),
        k.chip(stale_w, "warning", "clock", name="CMP-239 stale chip"),
        _fc(
            "forced · stale chip",
            [k.glyph("clock", k.TEXT_1), k.text("word", stale_w, k.CAPTION, k.TEXT_1)],
            stroke=False,
        ),
        S("the clock"),
    )  # §9: "the clock and 'Stale since …'"; the chip word itself is drawn
    btn = k.copy("e27.scr125.row.actions", label="Main", ENV="LIVE")
    ring = _pair(
        S("The focus ring"),
        k.focus_ring(k.button(btn, "secondary")),
        k.focus_ring(
            _fc("forced · button", [k.text("label", btn, k.BODY_STRONG, k.TEXT_1)]),
            name="Highlight ring",
        ),
        S("Highlight, the same width and offset"),
    )
    legend = k.hbox(
        "system colours",
        [
            k.text(f"sc · {x}", S(x), k.NUM_BASE, k.TEXT_2)
            for x in ("Canvas", "CanvasText", "GrayText", "Highlight")
        ],
        {"gap": k.INSET_LG},
    )
    return k.specimen(
        "Forced colours · the critical chip, the blocked row, a T2 menu item, the stale chip, the "
        "ring (§9; R2)",
        [
            legend,
            k.hbox(
                "carriers",
                [crit, blocked, t2, stale, ring],
                {"wrap": "wrap", "gap": k.INSET_XL, "align": "start"},
                w=CW - 32,
            ),
        ],
        notes=[
            (
                "stand-ins, no system-colour token exists: Canvas = color.surface.app, CanvasText = "
                "color.text.primary, GrayText = color.text.tertiary, Highlight = color.focus.ring"
            )
        ],
        proposed=["HD13"],
        w=CW,
    )


def cells() -> list[k.Node]:
    return [
        scr125(),
        scr126(),
        scr127(),
        scr129(),
        scr079(),
        zoom125(),
        zoom200(),
        text150(),
        forced(),
    ]


def main() -> int:
    k.reset_notes()
    cs = cells()
    bd = k.board(
        NN,
        cs,
        source="E27-D03 §0 L227; §11 L1918-2002 (keyboard model, text resize, targets and the "
        "ring, announcements); §3.6 L1108-1124; §9 L1761-1780 (forced colours, R2)",
        cols=3,
        not_drawn=[
            (
                "SCR-126 edit, SCR-016 step 3, the Test dialog, SCR-006 step-up, the compromise card "
                "and SCR-019's keyboard rows (§11's table is binding)"
            ),
            (
                "the 125 % / 200 % / 150 % rows "
                "of SCR-126, SCR-016, the Test dialog, the SCR-079 drawer and the compromise card"
            ),
        ],
        notes=[
            "the keyboard walkthrough item (§15) stays on this board",
            (
                "forced colours drawn with token stand-ins (kit has no system-colour tokens): Canvas = "
                "color.surface.app, CanvasText = color.text.primary, GrayText = color.text.tertiary, "
                "Highlight = color.focus.ring; the system colour named in words"
            ),
            "the rejected dimmed look is never drawn here (board 03 strikes it through)",
        ],
    )
    path = k.KIT_DIR / f"{k.stem(NN)}.json"
    res = k.write_sheet(path, bd)
    rep = k.compact_sheet(path)
    md = k.write_board_md(
        NN,
        bd,
        checks=[
            "specimen cells only (§0 L227: no inventory frame)",
            ("SCR-125, 126, 127, 129 and 079 each with focus order, landmarks and " "live regions"),
            "125 %, 200 % and 150 %-text specimens",
            (
                "a forced-colours strip: critical chip, blocked row, T2 menu item, "
                "stale chip, ring"
            ),
            f"validator: {res}",
        ],
    )
    print(res)
    print(rep)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
