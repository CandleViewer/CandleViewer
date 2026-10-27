"""gen_03: E05-D02 / 03 tags-badges-avatars (slice 2: CMP-011, 012, 013, 025, 032, 037). Python 3.12, stdlib only.

Run: python3 -I -B gen/gen_03.py   (writes 03-tags-badges-avatars.json + .md, validates, compacts into ../E05-D02-v4/)
Every specimen string comes from k.say() (slice 2 text); every shape is a primitive with token binds (no inst).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e05d02kit as k

NN = 3
NEUTRAL_SUBTLE, NEUTRAL_DEFAULT = "color.neutral.subtle", "color.neutral.default"
TONE_GLYPH = {
    "info": ("ⓘ", "info"),
    "success": ("✓", "check"),
    "warning": ("⚠", "warning"),
    "danger": ("⊘", "error"),
}
DEV: list[str] = []


def glyph(tone: str) -> k.Node:
    """The tone's registry glyph as a text glyph in color.status.{tone}.strong (conventions §4)."""
    ch, nm = TONE_GLYPH[tone]
    return k.tglyph(ch, k.STATUS[f"{tone}.strong"], k.CAPTION, name=f"CMP-019 {nm} (text glyph)")


# --- CMP-011 Tag
def remove_btn(state: str = "default") -> k.Node:
    """The nested CMP-002 IconButton (ghost, md, size.control.height square) with the local close icon."""
    hover = state == "hover"
    o = {"justify": "center", "radius": k.R_CONTROL, "height": k.CONTROL_H, "width": k.CONTROL_H}
    if hover:
        o["fill"] = k.HOVER
    if state == "disabled":
        o["opacity"] = k.OP_DISABLED
    if state == "T2":
        o.update(k.T2_SHAPE)
    ink = k.TEXT_1 if hover else (k.TEXT_3 if state == "T2" else k.TEXT_2)
    b = k.hbox(
        "CMP-002 remove" + (" T2" if state == "T2" else ""),
        [k.icon("CMP-019 close", "close", ink)],
        o,
        w=k.CONTROL_PX,
        h=k.CONTROL_PX,
    )
    if state == "focus-visible":
        b = k.focus_ring(b)
    if state == "T2":
        b = k.lock_badge(b)
    return b


def chip(
    label: str,
    variant: str = "neutral",
    *,
    removable: str | None = None,
    with_icon: bool = False,
    state: str = "default",
) -> k.Node:
    """A CMP-011 chip: size.control.height, radius.badge, space.inset.sm paddingX (left only when removable),
    space.inset.xs gap; neutral = neutral.subtle + 1 px border.default + text.secondary; status = status.subtle fill,
    text.primary label, status.strong glyph; estimated = 1 px status.info.strong outline (dash: live), no fill.
    """
    o: dict = {"radius": k.R_BADGE, "gap": k.INSET_XS, "height": k.CONTROL_H}
    kids: list = []
    ink = k.TEXT_2
    if variant == "neutral":
        o.update(fill=NEUTRAL_SUBTLE, stroke=k.BORDER_DEFAULT, strokeWidth=k.HAIRLINE)
        if with_icon:
            kids.append(k.tglyph("●", k.TEXT_2, k.CAPTION, name="CMP-019 pin (text glyph)"))
    elif variant == "estimated":
        o.update(stroke=k.STATUS["info.strong"], strokeWidth=k.HAIRLINE)
    else:
        o["fill"] = k.STATUS[f"{variant}.subtle"]
        ink = k.TEXT_1
        kids.append(glyph(variant))
    kids.append(k.text("label", label, k.CAPTION, ink))
    if removable:
        o.update(padL=k.INSET_SM, padR=k.INSET_XS)
        kids.append(remove_btn(removable))
    else:
        o["padX"] = k.INSET_SM
    c = k.hbox(f"CMP-011 chip · {variant}", kids, o, h=k.CONTROL_PX)
    if state == "focus-visible":
        c = k.focus_ring(c, radius=k.R_BADGE, name="focus-ring (chip)")
    return c


def b011() -> k.Node:
    brk, est = k.say("Breakout", "CMP-011"), k.say("(estimated)", "CMP-011")
    reason = k.say("Owner only: your role can't use this action.", doc="s1")
    words = {
        "info": k.say("Syncing", "CMP-012"),
        "warning": k.say("Degraded", "CMP-012"),
        "danger": k.say("Blocked", "CMP-012"),
    }
    rows = [
        k.state_row(
            "neutral",
            [
                k.cell("default", chip(brk)),
                k.cell("Icon=true", chip(brk, with_icon=True), note="icon-left"),
            ],
        ),
        k.state_row(
            "neutral · Removable",
            [
                k.cell("default", chip(brk, removable="default")),
                k.cell("hover", chip(brk, removable="hover"), note="nested CMP-002 hover (E18)"),
                k.cell(
                    "focus-visible", chip(brk, removable="focus-visible"), note="the CMP-002 ring"
                ),
                k.cell(
                    "disabled",
                    chip(brk, removable="disabled"),
                    note="dimmed by the nested CMP-002 only",
                ),
                k.cell(
                    "T2 removal",
                    k.vbox(
                        "T2 2b", [chip(brk, removable="T2"), k.tooltip(reason)], {"gap": k.STACK_XS}
                    ),
                    note="2b lock badge + CMP-016 echo (E10)",
                ),
            ],
        ),
        k.state_row(
            "info · warning · danger",
            [
                k.cell(v, chip(words[v], v), note="glyph + word")
                for v in ("info", "warning", "danger")
            ],
        ),
        k.state_row(
            "estimated",
            [
                k.cell("default", chip(est, "estimated"), note="dashed outline: live"),
                k.cell("focus-visible", chip(est, "estimated", state="focus-visible")),
            ],
        ),
    ]
    DEV.append(
        "CMP-011 estimated chip: cvsheet has no dash key; the 1 px color.status.info.strong outline is drawn "
        "solid and set to Penpot's default dash live (live check); CMP-227 governs its look (E19)"
    )
    DEV.append(
        "CMP-011 icon-left: the hidden placeholder icon/pin is not a local icon; drawn as the text glyph ●"
    )
    return k.block(
        "CMP-011",
        rows,
        states=["default", "hover", "focus-visible", "disabled", "T2 removal"],
        not_drawn=[
            "Removable=true on info / warning / danger / estimated (E10: neutral only)",
            (
                "estimated State=disabled (E19: an honesty marker is never dimmed; CMP-227 has no "
                "disabled state, so the drawn variant becomes a note)"
            ),
            "Icon=true on the status chips (their registry glyph is always shown, E10)",
            "comfortable density (32 px chip and remove target)",
        ],
        proposed=["E10", "E18", "E19", "E9"],
        ruled=["#3953"],
    )


# --- CMP-012 Badge
def count(n: str, tone: str) -> k.Node:
    """Count: hug pill, size.icon high (min-width size.icon), space.inset.xs paddingX, tinted: status.subtle fill and
    1 px status.strong outline (neutral: neutral.subtle + neutral.default), type.num.xs color.text.primary numeral.
    """
    fill, edge = (
        (NEUTRAL_SUBTLE, NEUTRAL_DEFAULT)
        if tone == "neutral"
        else (k.STATUS[f"{tone}.subtle"], k.STATUS[f"{tone}.strong"])
    )
    o = {
        "fill": fill,
        "stroke": edge,
        "strokeWidth": k.HAIRLINE,
        "radius": k.R_BADGE,
        "padX": k.INSET_XS,
        "height": k.ICON,
        "minW": k.ICON,
        "justify": "center",
    }
    return k.hbox(f"CMP-012 count · {tone}", [k.text("value", n, k.NUM_XS, k.TEXT_1)], o, h=16)


def dot(tone: str) -> k.Node:
    """Dot: an 8 px radius.badge dot in color.status.{tone}.default (neutral.default) centred in a size.icon slot."""
    fill = NEUTRAL_DEFAULT if tone == "neutral" else k.STATUS[f"{tone}.default"]
    d = k.rect("dot", 8, 8, fill, o={"radius": k.R_BADGE})
    return k.hbox(
        f"CMP-012 dot · {tone}",
        [d],
        {"justify": "center", "width": k.ICON, "height": k.ICON},
        w=16,
        h=16,
    )


def b012() -> k.Node:
    three = k.say("3", "CMP-012")
    words = {
        "neutral": "Idle",
        "info": "Syncing",
        "success": "Healthy",
        "warning": "Degraded",
        "danger": "Blocked",
    }
    tones = ("neutral", "info", "success", "warning", "danger")

    def paired(t: str) -> k.Node:
        kids = [dot(t)] + ([] if t == "neutral" else [glyph(t)])
        kids.append(k.text("word", k.say(words[t], "CMP-012"), k.CAPTION, k.TEXT_1))
        return k.hbox(f"dot pairing · {t}", kids, {"gap": k.INSET_XS})

    alerts = k.hbox(
        "usage · Alerts",
        [k.text("word", k.say("Alerts", "CMP-012"), k.CAPTION, k.TEXT_1), count(three, "danger")],
        {"gap": k.INSET_XS},
    )
    rows = [
        k.state_row("count", [k.cell(t, count(three, t)) for t in tones]),
        k.state_row(
            "dot (paired)",
            [
                k.cell(
                    t, paired(t), note="word only" if t == "neutral" else "dot + glyph + " "word"
                )
                for t in tones
            ],
        ),
        k.state_row(
            "usage",
            [k.cell("count beside its word", alerts, note='role=img, e.g. "3 unread alerts"')],
        ),
    ]
    DEV.append(
        "CMP-012 / CMP-032 dots: drawn as 8 x 8 px radius.badge rects (cvsheet sizes by w / h); the spec's "
        "space.inset.xs-padded empty board and its 0.01 px spacer are Penpot workarounds (§4.1, E5)"
    )
    return k.block(
        "CMP-012",
        rows,
        states=["default (the only State)"],
        not_drawn=[
            'multi-digit counts and the "99+" cap (E11, held)',
            "a dot alone (never rendered alone: always with its word)",
        ],
        proposed=["E11", "E5", "E3"],
    )


# --- CMP-013 Avatar, CMP-025 Avatar Group
def avatar(initials: str, size: str = "md") -> k.Node:
    """CMP-013: a radius.badge circle on a square box (md size.control.height, sm size.icon), interim
    color.neutral.subtle fill, color.text.primary initials (md type.ui.label, sm type.ui.caption).
    """
    px, tok, typo = (24, k.CONTROL_H, k.LABEL) if size == "md" else (16, k.ICON, k.CAPTION)
    o = {
        "fill": NEUTRAL_SUBTLE,
        "radius": k.R_BADGE,
        "justify": "center",
        "width": tok,
        "height": tok,
    }
    return k.hbox(
        f"CMP-013 avatar · {size}", [k.text("initials", initials, typo, k.TEXT_1)], o, w=px, h=px
    )


def ring(n: k.Node, w: int, name: str) -> k.Node:
    """The 2 px color.surface.canvas cut-out ring (CMP-025): a canvas pill 4 px larger than n, n centred."""
    return k.hbox(
        name, [n], {"fill": k.CANVAS, "radius": k.R_BADGE, "justify": "center"}, w=w + 4, h=28
    )


def group(inits: list[str], more: str | None) -> k.Node:
    """CMP-025: avatars in size.icon-wide slots (8 px overlap at compact), each in its cut-out ring; +N chip last."""
    kids = [k.place(ring(avatar(t), 24, f"slot {i + 1}"), 16 * i, 0) for i, t in enumerate(inits)]
    w = 16 * (len(inits) - 1) + 28
    if more:
        chip_ = k.hbox(
            "overflow +N",
            [k.text("value", more, k.NUM_SM, k.TEXT_2)],
            {
                "fill": NEUTRAL_SUBTLE,
                "radius": k.R_BADGE,
                "padX": k.INSET_XS,
                "height": k.CONTROL_H,
                "minW": k.CONTROL_H,
                "justify": "center",
            },
            w=24,
            h=24,
        )
        kids.append(k.place(ring(chip_, 24, "slot +N"), 16 * len(inits), 0))
        w += 16
    return k.box("CMP-025 group", kids, w=w, h=28)


def b013() -> k.Node:
    ad, a = k.say("AD", "CMP-013"), k.say("A", "CMP-013")
    named = k.hbox(
        "beside its name",
        [avatar(ad), k.text("name", k.say("Alpha Desk", "CMP-013"), k.BODY, k.TEXT_1)],
        {"gap": k.INSET_SM},
    )
    rows = [
        k.state_row(
            "md",
            [
                k.cell("default", avatar(ad), note="two initials"),
                k.cell("beside its name", named, note="decorative (aria-hidden)"),
            ],
        ),
        k.state_row("sm", [k.cell("default", avatar(a, "sm"), note="one initial (E12)")]),
    ]
    return k.block(
        "CMP-013",
        rows,
        states=["default (the only State)"],
        not_drawn=[
            "Size lg (no token above size.control.height)",
            ("the ColorPalette story (E2: no " "avatar palette token yet)"),
            "comfortable density (md 32 px)",
        ],
        proposed=["E2", "E12"],
    )


def b025() -> k.Node:
    ini = [k.say(x, "CMP-025") for x in ("AD", "BS", "CF")]
    rows = [
        k.state_row("Overflow=false", [k.cell("default", group(ini, None), note="3 accounts")]),
        k.state_row(
            "Overflow=true",
            [
                k.cell(
                    "default",
                    group(ini, k.say("+2", "CMP-025")),
                    note="max 3, +N chip (5 accounts)",
                )
            ],
        ),
    ]
    DEV.append(
        "CMP-025 overlap: avatars and the +N chip sit at 16 px pitch (the size.icon slot width) inside a fixed "
        "board, positioned (abs) because cvsheet has no clip-off slot; the spec's flex slots are the build's"
    )
    return k.block(
        "CMP-025",
        rows,
        states=["default (the only State)"],
        not_drawn=[
            "the ring on raised / hover surfaces (E23)",
            "comfortable density (16 px overlap)",
        ],
        proposed=["E6", "E23", "E4"],
    )


# --- CMP-032 Confidence Dots, CMP-037 SwatchLegendItem
def dots(level: str) -> k.Node:
    """CMP-032: three 8 px dots (space.inset.xs apart), the filled count in color.status.info.default, empty dots a
    1 px color.text.tertiary ring; the label (type.ui.caption, color.text.secondary) space.inset.sm after them.
    """
    n = {"low": 1, "medium": 2, "high": 3}[level]
    ds = [
        k.rect(
            f"dot {i + 1}",
            8,
            8,
            k.STATUS["info.default"] if i < n else None,
            o=(
                {"radius": k.R_BADGE}
                if i < n
                else {"radius": k.R_BADGE, "stroke": k.TEXT_3, "strokeWidth": k.HAIRLINE}
            ),
        )
        for i in range(3)
    ]
    row = k.hbox("dots", ds, {"gap": k.INSET_XS}, w=32, h=8)
    lab = k.say(f"{level.capitalize()} confidence", "CMP-032")
    return k.hbox(
        f"CMP-032 · {level}", [row, k.text("label", lab, k.CAPTION, k.TEXT_2)], {"gap": k.INSET_SM}
    )


def legend(swatch: str, label: str, value: str | None, glyph_: bool = False) -> k.Node:
    """CMP-037: a 200 px row, size.row.height, gap space.inset.sm: the size.icon swatch (keyed data fill, 1 px
    color.border.strong outline), the optional glyph, the label (type.ui.caption color.text.secondary, fills) and
    the value (type.num.sm color.text.primary, right)."""
    kids: list = [
        k.rect("swatch", 16, 16, swatch, o={"stroke": k.BORDER_STRONG, "strokeWidth": k.HAIRLINE})
    ]
    if glyph_:
        kids.append(k.text("glyph", k.say("▼", "CMP-037"), k.CAPTION, k.TEXT_2))
    kids.append(k.text("label", k.say(label, "CMP-037"), k.CAPTION, k.TEXT_2, hs="fill"))
    if value:
        kids.append(k.text("value", k.say(value, "CMP-037"), k.NUM_SM, k.TEXT_1))
    return k.hbox("CMP-037 item", kids, {"gap": k.INSET_SM, "height": k.ROW_H}, w=200, h=24)


def b032() -> k.Node:
    rows = [
        k.state_row(f"Level={lv}", [k.cell("default", dots(lv), note=f"{n} of 3 dots filled")])
        for lv, n in (("low", 1), ("medium", 2), ("high", 3))
    ]
    return k.block(
        "CMP-032",
        rows,
        states=["default (the only State)"],
        not_drawn=[
            "a label override (it must still name the level)",
            ('inside CMP-227 ("Estimated, low ' 'confidence")'),
        ],
        proposed=["E17", "E5"],
    )


def b037() -> k.Node:
    rows = [
        k.state_row(
            "HasValue=true",
            [
                k.cell(
                    "HasGlyph=false",
                    legend("color.heatmap.bid.3", "Bid liquidity", "1.2M"),
                    note="the master: color.heatmap.bid.3",
                ),
                k.cell(
                    "HasGlyph=true",
                    legend("color.sell.default", "Sell volume", "0.9M", True),
                    note="override: color.sell.default + ▼",
                ),
            ],
        ),
        k.state_row(
            "HasValue=false",
            [
                k.cell(
                    "HasGlyph=false",
                    legend("color.heatmap.zero", "Zero intensity", None),
                    note="override: color.heatmap.zero, the outline keeps the box",
                )
            ],
        ),
    ]
    return k.block(
        "CMP-037",
        rows,
        states=["HasValue × HasGlyph as drawn (3 variants)"],
        not_drawn=[
            "HasValue=false + HasGlyph=true (not in the draw list; E16)",
            'the color.heatmap.ask.3 "Ask liquidity" 0.8M override row (a third keyed sample)',
            "a two-line label (the row grows in code)",
        ],
        proposed=["E16", "E26"],
    )


def main() -> int:
    blocks = [b011(), b012(), b013(), b025(), b032(), b037()]
    bd = k.board(
        NN,
        blocks,
        source="slice 2 §3 conventions 15-20, §6 CMP-011 L384-466, CMP-012 L467-540, CMP-013 "
        "L541-603, CMP-025 L872-938, CMP-032 L1001-1065, CMP-037 L1134-1199",
        cols=3,
        notes=[
            (
                "Static atoms (conventions 19): CMP-012, 013, 025, 032 and 037 draw no focus or disabled "
                "state; CMP-011's own ring is on the estimated chip only (conventions 20)"
            ),
            (
                "Status tones are never colour alone: chips carry glyph + word; dots pair with a glyph and a "
                "word (conventions 4); in dark, danger.strong renders amber (slice 1 A6)"
            ),
            "Tone glyphs are text glyphs: info ⓘ, success ✓, warning ⚠, danger ⊘ (FALLBACKS ICONS)",
            *DEV,
        ],
        not_drawn=[
            "every combination beyond the drawn cells (slice 1 conventions 2 matrix rule)",
            (
                "comfortable density and the light / high-contrast themes (board 10 holds the light "
                "Badge tones)"
            ),
        ],
    )
    path = k.KIT_DIR / f"{k.stem(NN)}.json"
    summary = k.write_sheet(path, bd, notes={"deviations": DEV})
    rep = k.compact_sheet(path)
    k.write_board_md(
        NN,
        bd,
        checks=[
            "every specimen string is say()'d from slice 2 (or slice 1's rbac reason); no inst node; icons: close, locked",
            "every gated cell is T2: CMP-011's remove button 2b (lock badge + CMP-016 echo), no disabled token on it",
            "status chips and dots carry a glyph and a word; Badge numerals in color.text.primary (E3 tinted count)",
        ],
        live=[
            "set the estimated chip's 1 px outline to Penpot's default dash (cvsheet has no dash key)",
            "check the CMP-025 cut-out rings read on the app plate (E23: an outline on app)",
        ],
        summary=f"validator: {summary}",
    )
    print(summary)
    print(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
