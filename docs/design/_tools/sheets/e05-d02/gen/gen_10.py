"""gen_10: E05-D02 / 10 light-composite — the contrast-critical variants of every slice in the LIGHT theme.

One block per component, light=True on each (the kit refuses board 10 without a block of each slice): slice 1 CMP-001
(primary, danger, buy, sell × default, focus-visible, T2); slice 2 CMP-012 Badge (count and dot × five tones); slice 3
CMP-007 TextInput (default, focus-visible, invalid, T2); slice 4 CMP-028 Callout (four tones), CMP-045 Toast (three
tones the spec gives copy for) and CMP-044 ConfirmDialog (standard default and gated, over the scrim).
Run: python3 -I -B gen/gen_10.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e05d02kit as k

NN = 10
TONES4 = ("info", "warning", "danger", "success")
NEUTRAL, NEUTRAL_SUBTLE = (
    "color.neutral.default",
    "color.neutral.subtle",
)  # tone="neutral" (slice 2 L505)
GLYPH = {
    "info": ("ⓘ", "info"),
    "success": ("✓", "check"),
    "warning": ("⚠", "warning"),
    "danger": ("⊘", "danger"),
}


def tone_glyph(tone: str, typo: str = k.BODY) -> k.Node:
    """CMP-019's tone glyph at size.icon in color.status.{tone}.strong (a text glyph: FALLBACKS ICONS)."""
    ch, nm = GLYPH[tone]
    return k.tglyph(ch, k.STATUS[f"{tone}.strong"], typo, name=f"CMP-019 {nm} (text glyph)")


# --- slice 1: CMP-001 Button.
def b_button() -> k.Node:
    """Primary, danger, buy, sell × default, focus-visible, disabled-with-reason (T2 2a)."""
    reason = k.say("Owner only: your role can't use this action.", "CMP-001")
    labels = {
        "primary": k.say("Save", "CMP-001"),
        "buy": k.say("Buy / Long", "CMP-001"),
        "sell": k.say("Sell / Short", "CMP-001"),
        "danger": k.say("Freeze sub_001 — cancel 3 working orders", doc="s4"),
    }
    rows = []
    for v in ("primary", "danger", "buy", "sell"):
        rows.append(
            k.state_row(
                v,
                [
                    k.cell("default", k.button(labels[v], v)),
                    k.cell(
                        "focus-visible",
                        k.button(labels[v], v, "focus-visible"),
                        note="CMP-039 ring",
                    ),
                    k.cell(
                        "disabled-with-reason",
                        k.button(labels[v], v, "disabled-with-reason", reason=reason),
                        note="T2 2a",
                    ),
                ],
            )
        )
    return k.block(
        "CMP-001",
        rows,
        states=["default", "focus-visible", "disabled-with-reason"],
        light=True,
        toks=[
            k.ACTION["primary"],
            k.STATUS["danger.default"],
            k.BUY,
            k.SELL,
            k.TEXT_ON_ACTION,
            k.TEXT_INVERSE,
            k.FOCUS_RING,
            k.RAISED,
            k.BORDER_DEFAULT,
            k.TEXT_3,
            k.TEXT_2,
        ],
        note="danger's label is CMP-044's destructive confirm (slice 4 L1683-1778), the slice-1 section "
        "names no danger label",
        not_drawn=[
            "secondary and ghost (not contrast-critical: text on a neutral fill)",
            ("hover, active, " "disabled and loading in light"),
            "sizes sm / lg",
        ],
        proposed=["A12", "D16", "D13"],
    )


# --- slice 2: CMP-012 Badge.
def count_badge(tone: str) -> k.Node:
    """The count: color.status.{tone}.subtle fill, .strong 1 px outline (neutral: color.neutral.*), numeral
    type.num.xs color.text.primary, size.icon tall, inset.xs paddingX, radius.badge."""
    fill, stroke = (
        (NEUTRAL_SUBTLE, NEUTRAL)
        if tone == "neutral"
        else (k.STATUS[f"{tone}.subtle"], k.STATUS[f"{tone}.strong"])
    )
    return k.hbox(
        f"CMP-012 count · {tone}",
        [k.text("numeral", "3", k.NUM_XS, k.TEXT_1)],
        {
            "fill": fill,
            "stroke": stroke,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_BADGE,
            "padX": k.INSET_XS,
            "justify": "center",
        },
        w=k.PX[k.ICON],
        h=k.PX[k.ICON],
    )


def dot_badge(tone: str) -> k.Node:
    """The dot: color.status.{tone}.default (neutral color.neutral.default) in a size.icon slot."""
    fill = NEUTRAL if tone == "neutral" else k.STATUS[f"{tone}.default"]
    dot = k.ellipse("dot", 8, 8, {"fill": fill})
    return k.hbox(
        f"CMP-012 dot · {tone}", [dot], {"justify": "center"}, w=k.PX[k.ICON], h=k.PX[k.ICON]
    )


def b_badge() -> k.Node:
    """Count and dot × the five tones."""
    tones = ("neutral", "info", "success", "warning", "danger")
    rows = [
        k.state_row("count", [k.cell(t, count_badge(t)) for t in tones]),
        k.state_row("dot", [k.cell(t, dot_badge(t)) for t in tones]),
    ]
    return k.block(
        "CMP-012",
        rows,
        states=["default"],
        light=True,
        note="light contrast rows (slice 2 L501-512): dot ≥3:1 on app and canvas (lowest 3.22:1, light "
        "warning on canvas); count outline ≥3.64:1 vs canvas (lowest light success.strong)",
        not_drawn=[
            (
                "the dot on raised, overlay, hover, selected and sunken hosts (below 3:1 in light, "
                "slice 2 L503)"
            ),
            "99+ and the count's long values",
        ],
    )


# --- slice 3: CMP-007 TextInput (with CMP-040's lines where the cell names them).
FIELD_W = 200


def well(state: str) -> k.Node:
    """The well (conventions 21): color.surface.app, 1 px color.text.tertiary boundary, radius.control, 24 high,
    inset.sm padding; invalid a 2 px color.status.danger.default boundary; T2 the raised well with a 1 px
    color.border.default hairline and the lock leading the value, both color.text.tertiary."""
    value = k.say("trader_01", "CMP-007")
    o = {
        "fill": k.APP,
        "stroke": k.TEXT_3,
        "strokeWidth": k.HAIRLINE,
        "radius": k.R_CONTROL,
        "padX": k.INSET_SM,
        "gap": k.INSET_XS,
    }
    kids: list[k.Node | None] = []
    ink = k.TEXT_1
    if state == "invalid":
        o.update(stroke=k.STATUS["danger.default"], strokeWidth=k.THICK)
    if state == "T2":
        o.update(k.T2_SHAPE)
        kids.append(k.lock())
        ink = k.TEXT_3
    kids.append(k.text("value", value, k.BODY, ink))
    w = k.hbox(f"CMP-007 well · {state}", kids, o, w=FIELD_W, h=k.CONTROL_PX)
    return k.focus_ring(w, name="CMP-039 focus-ring") if state == "focus-visible" else w


def b_textinput() -> k.Node:
    """default, focus-visible, invalid (CMP-040's error line), disabled-with-reason (T2 2a, CMP-040's reason)."""
    err = k.hbox(
        "CMP-040 error line",
        [
            tone_glyph("danger", k.CAPTION),
            k.text("sentence", k.say("Enter your username.", "CMP-040"), k.CAPTION, k.TEXT_1),
        ],
        {"gap": k.INSET_XS},
    )
    t2 = k.t2_inline(
        well("T2"),
        k.say("Your role can't change settings.", "CMP-040"),
        w=FIELD_W,
        name="T2 2a · CMP-007",
    )
    rows = [
        k.state_row(
            "Value=filled",
            [
                k.cell("default", well("default")),
                k.cell(
                    "focus-visible", well("focus-visible"), note="CMP-039 ring, boundary unchanged"
                ),
                k.cell(
                    "invalid",
                    k.vbox("CMP-007 invalid", [well("invalid"), err], {"gap": k.STACK_XS}),
                    note="2 px danger.default boundary; CMP-040's error line",
                ),
                k.cell("disabled-with-reason", t2, note="T2 2a: lock leads the value"),
            ],
        )
    ]
    return k.block(
        "CMP-007",
        rows,
        states=["default", "focus-visible", "invalid", "disabled-with-reason"],
        light=True,
        proposed=["G23"],
        not_drawn=[
            (
                "hover, disabled, read-only, Value=empty and Affix=both in light (not "
                "contrast-critical beyond the drawn boundary and T2 cells)"
            )
        ],
    )


# --- slice 4: CMP-028 Callout, CMP-045 Toast, CMP-044 ConfirmDialog.
CALLOUT = {
    "info": (
        "Reconnected — backfilling history",
        "Recorded coverage catching up: 00:41 remaining.",
    ),
    "warning": (
        "Degraded — some data feeds are stale",
        "Book and tape are live; 1 of 4 topics stale 6s. Recent trades may lag.",
    ),
    "danger": ("Trading locked: daily loss limit −2 % reached at 13:41 UTC.", None),
    "success": ("Accepted — stop 63,900.0 held by the exchange · exchange id ends …5f60", None),
}


def edged(box: k.Node, color: str) -> k.Node:
    """box with a 2 px border.thick start edge in color (an abs rect over the box's left edge, its estimated
    height)."""
    h = round(k.est_height(box))
    edge = k.place(k.rect("edge · border.thick", 2, h, color), 0, 0)
    return dict(box, kids=[*box["kids"], edge])


def callout(tone: str) -> k.Node:
    """The inline callout: color.status.{tone}.subtle, radius.card, inset.sm block / inset.md inline, the glyph in
    .strong, title body-strong primary, body secondary; the 2 px start edge in .strong."""
    title, body = CALLOUT[tone]
    tw = 300
    col = [
        k.text("title", k.say(title, "CMP-028"), k.BODY_STRONG, k.TEXT_1, w=tw),
        k.text("body", k.say(body, "CMP-028"), k.BODY, k.TEXT_2, w=tw) if body else None,
    ]
    box = k.hbox(
        f"CMP-028 callout · {tone}",
        [tone_glyph(tone), k.vbox("text", col, {"gap": k.STACK_XS})],
        {
            "fill": k.STATUS[f"{tone}.subtle"],
            "radius": k.R_CARD,
            "padY": k.INSET_SM,
            "padX": k.INSET_MD,
            "gap": k.INSET_SM,
            "align": "start",
        },
        w=tw + 2 * k.PX[k.INSET_MD] + k.PX[k.INSET_SM] + 16,
    )
    return edged(box, k.STATUS[f"{tone}.strong"])


def b_callout() -> k.Node:
    """info, warning, danger, success (inline)."""
    rows = [
        k.state_row("info, warning", [k.cell(t, callout(t), note=f"Tone={t}") for t in TONES4[:2]]),
        k.state_row(
            "danger, success", [k.cell(t, callout(t), note=f"Tone={t}") for t in TONES4[2:]]
        ),
    ]
    return k.block(
        "CMP-028",
        rows,
        states=list(TONES4),
        light=True,
        proposed=["H5", "s1:A6"],
        note="glyph + words carry the tone, never colour alone; light danger and warning glyphs: s1 A6",
        not_drawn=[
            (
                "the default cell's CMP-023 progress, reconnecting, disconnected, band, dismissible "
                "and the hatched unprotected banner in light"
            )
        ],
    )


TOAST_W = 360  # the surface's width (slice 4 §5.1)


def dismiss() -> k.Node:
    """CMP-002 ghost close (the file's local icon close), 24 x 24."""
    return k.hbox(
        "CMP-002 ghost · close",
        [k.icon("CMP-019 close", "close", k.TEXT_2)],
        {"justify": "center"},
        w=k.CONTROL_PX,
        h=k.CONTROL_PX,
    )


def toast(tone: str) -> k.Node:
    """CMP-045 (conventions 30 surface, 360 px, inset.md, rows stack.sm) with a 2 px border.thick start edge in
    color.status.{tone}.default (H6); the glyph in .strong; kicker / title / body / meta / actions as the cell
    gives them."""
    tw = TOAST_W - 2 * k.PX[k.INSET_MD] - 16 - 2 * k.PX[k.INSET_SM] - k.CONTROL_PX
    s = lambda x: k.say(x, "CMP-045")
    if tone == "info":
        col = [
            k.text(
                "title",
                s("Session extended. Idle timer reset. Next warning in 14:00."),
                k.BODY_STRONG,
                k.TEXT_1,
                w=tw,
            )
        ]
    elif tone == "success":
        col = [
            k.text(
                "title",
                s("Accepted — stop 63,900.0 held by the exchange"),
                k.BODY_STRONG,
                k.TEXT_1,
                w=tw,
            )
        ]
    else:
        acts = [
            k.button(s("Open chart"), "secondary", name="CMP-001 secondary · Open chart"),
            k.button(s("Snooze ▾"), "secondary", name="CMP-001 secondary · Snooze"),
            k.button(s("Disable"), "ghost", name="CMP-001 ghost · Disable"),
            k.button(s("Details"), "ghost", name="CMP-001 ghost · Details"),
        ]
        col = [
            k.text("kicker", s("Warning · Alert"), k.CAPTION, k.TEXT_2),
            k.text("title", s("BTC above 65k"), k.BODY_STRONG, k.TEXT_1),
            k.text("body", s("Last price 65,012.5 crossed above 65,000"), k.BODY, k.TEXT_2, w=tw),
            k.text("meta", s("BTCUSDT · 5m"), k.NUM_SM, k.TEXT_3),
            k.hbox(
                "actions", acts, {"gap": k.INSET_SM, "wrap": "wrap", "rowGap": k.INSET_XS}, w=tw
            ),
        ]
    box = k.hbox(
        f"CMP-045 toast · {tone}",
        [tone_glyph(tone), k.vbox("content", col, {"gap": k.STACK_SM}), dismiss()],
        {
            "fill": k.OVERLAY,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CARD,
            "shadow": k.E_POPOVER,
            "pad": k.INSET_MD,
            "gap": k.INSET_SM,
            "align": "start",
        },
        w=TOAST_W,
    )
    return edged(box, k.STATUS[f"{tone}.default"])


def b_toast() -> k.Node:
    """info, success, warning (with actions); danger has no copy in the cell (not drawn, a copy gap)."""
    k.gap(
        "CMP-045 danger: the cell names 'an order rejection with Details' but gives no title or body: the danger "
        "toast is not drawn on board 10 (board 08 owns CMP-045)"
    )
    rows = [
        k.state_row(
            "timed",
            [
                k.cell("info", toast("info"), note="Tone=info, default"),
                k.cell("success", toast("success"), note="Tone=success"),
            ],
        ),
        k.state_row(
            "actions", [k.cell("warning", toast("warning"), note="Tone=warning, Action=actions")]
        ),
    ]
    return k.block(
        "CMP-045",
        rows,
        states=["info", "success", "warning"],
        light=True,
        proposed=["H6", "H26"],
        not_drawn=["danger (no copy in the cell)", "focused, T2 action and undo in light"],
    )


def dialog(gated: bool) -> k.Node:
    """CMP-044 standard over the scrim: modal surface (elevation.dialog, radius.dialog, space.dialog.padding), the
    title, the "What this does" group on color.surface.raised, Cancel (secondary, focused) then the danger confirm;
    gated: the confirm in T2 with its reason under the footer."""
    s = lambda x: k.say(x, "CMP-044")
    dw = 440
    inner = dw - 2 * k.PX[k.DIALOG_PAD]
    group = k.vbox(
        "restatement · What this does",
        [k.text("label", s("What this does"), k.LABEL, k.TEXT_1)],
        {"fill": k.RAISED, "radius": k.R_CARD, "pad": k.INSET_MD},
        w=inner,
    )
    confirm = k.button(
        s("Freeze sub_001 — cancel 3 working orders"),
        "danger",
        "disabled-with-reason" if gated else "default",
        name="CMP-001 danger · confirm" + (" · T2" if gated else ""),
    )
    cancel = k.button(
        s("Cancel"),
        "secondary",
        "default" if gated else "focus-visible",
        name="CMP-001 secondary · Cancel",
    )
    foot = k.hbox("footer", [cancel, confirm], {"gap": k.INSET_SM, "justify": "end"}, w=inner)
    kids = [k.text("title", s("Freeze sub_001?"), k.HEADING_MD, k.TEXT_1), group, foot]
    if gated:
        kids.append(
            k.t2_reason(
                s("Your role can't use the kill switch."), w=inner, name="T2 reason · footer"
            )
        )
    surf = k.vbox(
        "CMP-044 dialog" + (" · gated" if gated else ""),
        kids,
        {
            "fill": k.OVERLAY,
            "radius": k.R_DIALOG,
            "shadow": k.E_DIALOG,
            "pad": k.DIALOG_PAD,
            "gap": k.STACK_MD,
        },
        w=dw,
    )
    pad = k.PX[k.INSET_XL]
    w, h = dw + 2 * pad, round(k.est_height(surf)) + 2 * pad
    k.LOG.add(
        "fallbacks",
        "fallback: the scrim is palette.black at opacity.scrim (s4 conventions 31, H1), a "
        "primitive colour the validator refuses: the sheet binds color.surface.sunken at "
        "opacity.scrim (E15-D06's SCRIM precedent); sunken is black only in dark, so the live "
        "step MUST rebind the two scrim rects to palette.black before the light export (s4 "
        "conventions 31: never color.surface.sunken)",
    )
    k.LOG.add(
        "live_checks",
        "board 10: rebind both 'scrim · …' rects' fill to palette.black (opacity.scrim kept) "
        "before export; the light export must show a black 60 % scrim, not light sunken",
    )
    scrim = k.place(
        k.rect(
            "scrim · palette.black at opacity.scrim (H1) · rebind live",
            w,
            h,
            k.SUNKEN,
            o={"opacity": k.OP_SCRIM},
        ),
        0,
        0,
    )
    return k.hbox("scrim host", [scrim, surf], {"justify": "center", "fill": k.CANVAS}, w=w, h=h)


def b_dialog() -> k.Node:
    """standard default and gated, each over the scrim."""
    k.gap(
        "CMP-044 default: the 'What this does' group's sentences and the subtitle are SCR-072's (E39-D03 §4.1), "
        "not quoted in the cell: the group draws its label only"
    )
    rows = [
        k.state_row(
            "Variant=standard",
            [
                k.cell(
                    "default",
                    dialog(False),
                    note="Cancel focused (the initial focus); danger confirm",
                ),
                k.cell(
                    "gated",
                    dialog(True),
                    note="T2: lock leads the confirm; reason under the footer (H30)",
                ),
            ],
        )
    ]
    return k.block(
        "CMP-044",
        rows,
        states=["default", "gated"],
        light=True,
        proposed=["H1", "H24", "H30"],
        not_drawn=[
            (
                "typed, typed · match, hold, holding, armed, busy, partial failure and the order "
                "confirm in light (board 09 draws them dark)"
            )
        ],
    )


def build() -> dict:
    """Board 10."""
    blocks = [b_button(), b_badge(), b_textinput(), b_callout(), b_toast(), b_dialog()]
    return k.board(
        NN,
        blocks,
        cols=3,
        source="the contrast-critical cells of slices 1-4 in light: s1 CMP-001 L621-694 (A6, A12, D13, "
        "D16), s2 CMP-012 L467-540, s3 CMP-007 L522-603 with CMP-040's lines (conventions 21-24), "
        "s4 CMP-028 L1365-1435, CMP-045 L1779-1860, CMP-044 L1683-1778 (conventions 30-31, 36-37)",
        notes=[
            (
                "Light pairs the specs measure: CMP-012 dot ≥3:1 on app / canvas (lowest 3.22:1 light "
                "warning on canvas; 2.999 on raised, below 3:1 on overlay, hover, selected, sunken); count "
                "outline ≥3.64:1 vs canvas, ≥3.39:1 vs raised (s2 L503-505)"
            ),
            (
                "Floating text on color.surface.overlay: primary 13.27:1, secondary 8.14:1, tertiary "
                "5.20:1 or more (s4 conventions 30); color.border.subtle vanishes on light overlay (s1 A4), "
                "so floating edges bind color.border.default"
            ),
            (
                "s1 A6: light danger and warning glyphs share one amber family until the owner separates "
                "them — the callout and toast glyphs here bind .strong as the anatomy says"
            ),
            (
                "The scrim is black at opacity.scrim (0.6) in every theme, bound to palette.black + "
                "opacity.scrim until H1 ships color.surface.scrim (PROPOSED)"
            ),
            "Every other light combination: not drawn — the text is binding",
        ],
        not_drawn=[
            "slice 1 CMP-004 Toggle (Checked, Critical=true, T2) in light",
            "slice 2 CMP-021 Link (default, focus-visible) in light",
            (
                "slice 3 CMP-079 RbacGate (inline) in light — CMP-007's T2 cell carries the same "
                "2a look"
            ),
            "every other component and light combination of the four slices",
        ],
    )


def main() -> int:
    """Write, validate, compact and describe board 10."""
    bd = build()
    path = k.KIT_DIR / f"{k.stem(NN)}.json"
    summary = k.write_sheet(path, bd)
    rep = k.compact_sheet(path)
    k.write_board_md(
        NN,
        bd,
        summary=f"Validator: {summary}",
        checks=[
            "one light block per slice at least (s1 CMP-001; s2 CMP-012; s3 CMP-007; s4 CMP-028, CMP-045, CMP-044)",
            "status carried by glyph + words (callouts, toasts), never colour alone",
            "T2 cells: lock leads the full label / value, color.text.tertiary; reason color.text.secondary",
            "focus-visible cells carry CMP-039's 2 px color.focus.ring",
            "every specimen string issued by say() (copy gaps logged)",
        ],
        live=[
            (
                "the file's light theme (semantic-light over semantic-dark) is active when board 10 renders and "
                "exports; the dark boards keep the dark theme"
            )
        ],
    )
    print(summary)
    print(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
