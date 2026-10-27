"""gen_04: E05-D02 / 04 text-and-dividers (slice 2: CMP-018, 020, 021, 024, 030, 033). Python 3.12, stdlib only.

Run: python3 -I -B gen/gen_04.py   (writes 04-text-and-dividers.json + .md, validates, compacts into ../E05-D02-v4/)
Every specimen string comes from k.say() (slice 2 text); every shape is a primitive with token binds (no inst).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e05d02kit as k

NN = 4
NEUTRAL_DEFAULT = "color.neutral.default"
TYPO = {
    "caption": k.CAPTION,
    "body": k.BODY,
    "body-strong": k.BODY_STRONG,
    "label": k.LABEL,
    "heading-sm": k.HEADING_SM,
    "heading-md": k.HEADING_MD,
    "heading-lg": k.HEADING_LG,
    "display": "type.ui.display",
    "num-xs": k.NUM_XS,
    "num-sm": k.NUM_SM,
    "num-base": k.NUM_BASE,
    "num-md": k.NUM_MD,
    "num-lg": "type.num.lg",
    "num-xl": "type.num.xl",
}
DEV: list[str] = []


# --- CMP-018 Divider, CMP-030 Divider-Label
def divider(orient: str, inset: bool) -> k.Node:
    """CMP-018: a 1 px color.border.subtle rule; horizontal 240 px sample (inset: space.inset.md both ends), vertical
    size.control.height (inset: space.inset.xs both ends)."""
    if orient == "horizontal":
        o = {"padX": k.INSET_MD} if inset else {}
        rule = k.rect("rule", 216 if inset else 240, 1, k.BORDER_SUBTLE, hs="fill")
        return k.hbox(f"CMP-018 · horizontal · inset={str(inset).lower()}", [rule], o, w=240, h=1)
    o = {"padY": k.INSET_XS, "height": k.CONTROL_H} if inset else {"height": k.CONTROL_H}
    rule = k.rect("rule", 1, 16 if inset else 24, k.BORDER_SUBTLE, vs="fill")
    return k.hbox(
        f"CMP-018 · vertical · inset={str(inset).lower()}",
        [rule],
        {"dir": "column", **o},
        w=1,
        h=24,
    )


def divider_label(label: str, w: int) -> k.Node:
    """CMP-030: the caption (type.ui.caption color.text.secondary) leading, space.inset.sm, then the rule filling."""
    lw = round(k.text_w(label, k.CAPTION))
    rule = k.rect("rule", max(0, w - lw - 8), 1, k.BORDER_SUBTLE, hs="fill")
    return k.hbox(
        f"CMP-030 · {w}",
        [k.text("label", label, k.CAPTION, k.TEXT_2), rule],
        {"gap": k.INSET_SM},
        w=w,
    )


def b018() -> k.Node:
    rows = [
        k.state_row(
            f"{o_}", [k.cell(f"Inset={str(i).lower()}", divider(o_, i)) for i in (False, True)]
        )
        for o_ in ("horizontal", "vertical")
    ]
    return k.block(
        "CMP-018",
        rows,
        states=["Orientation × Inset (4 variants)"],
        note="The 1 px color.border.subtle rule is 1.31:1 on the app plate (dark): barely visible at 1x, "
        "as slice 2 §4.3 records; judge it in the cells.",
        not_drawn=[
            (
                "the light Menu / Popover case (border.subtle = surface.overlay, 1.00:1; CMP-018's "
                "open question)"
            ),
            "the decorative / separator semantics (not visual)",
        ],
        proposed=["E13"],
    )


def b030() -> k.Node:
    tp, sl = k.say("Take profit", "CMP-030"), k.say("Stop loss", "CMP-030")
    rows = [
        k.state_row("State=default", [k.cell("240 px root", divider_label(tp, 240))]),
        k.state_row(
            "fill demo",
            [
                k.cell("120 px", divider_label(tp, 120), note="the rule shrinks"),
                k.cell("400 px", divider_label(sl, 400), note="the rule fills"),
            ],
        ),
    ]
    return k.block(
        "CMP-030",
        rows,
        states=["default (the only State)"],
        not_drawn=["a wrapped caption in a very narrow container"],
        proposed=["E24"],
    )


# --- CMP-020 Typography primitives
def txt(chars: str, style: str, color: str = k.TEXT_1, name: str | None = None) -> k.Node:
    return k.text(name or f"CMP-020 · {style}", chars, TYPO[style], color)


def b020() -> k.Node:
    tp = k.say("Take profit", "CMP-020")
    p, n, z = (k.say(x, "CMP-020") for x in ("+420.00", "-420.00", "0.00"))
    plain, abbr, mono = (
        k.say("420.00", "CMP-020"),
        k.say("1.2M", "CMP-020"),
        k.say("17279edf", "CMP-020"),
    )
    rows = [
        k.state_row(
            "text", [k.cell(s, txt(tp, s)) for s in ("caption", "body", "body-strong", "label")]
        ),
        k.state_row(
            "heading",
            [k.cell(s, txt(tp, s)) for s in ("heading-sm", "heading-md", "heading-lg", "display")],
        ),
        k.state_row(
            "numeric-text",
            [
                k.cell(s, txt(plain, s))
                for s in ("num-xs", "num-sm", "num-base", "num-md", "num-lg", "num-xl")
            ],
        ),
        k.state_row(
            "numeric · sign",
            [
                k.cell(
                    "ColorBySign · positive",
                    txt(p, "num-base", k.BUY),
                    note="color.buy.default, + sign",
                ),
                k.cell(
                    "ColorBySign · negative",
                    txt(n, "num-base", k.SELL),
                    note="color.sell.default, − sign",
                ),
                k.cell(
                    "ColorBySign · zero",
                    txt(z, "num-base", NEUTRAL_DEFAULT),
                    note="unsigned, neutral",
                ),
                k.cell("SignDisplay=always", txt(p, "num-base"), note="color.text.primary"),
                k.cell("Format=notional", txt(abbr, "num-base"), note='reads "1,200,000" (E15)'),
            ],
        ),
        k.state_row(
            "mono-text", [k.cell("num-sm", txt(mono, "num-sm"), note="an id, left-aligned")]
        ),
    ]
    return k.block(
        "CMP-020",
        rows,
        states=["Variant × Style as drawn; Sign / ColorBySign / Format once"],
        toks=[
            "type.ui.caption",
            "type.ui.body",
            "type.ui.body-strong",
            "type.ui.label",
            "type.ui.heading-sm",
            "type.ui.heading-md",
            "type.ui.heading-lg",
            "type.ui.display",
            "type.num.xs",
            "type.num.sm",
            "type.num.base",
            "type.num.md",
            "type.num.lg",
            "type.num.xl",
            "color.buy.default",
            "color.sell.default",
            "color.neutral.default",
        ],
        not_drawn=[
            "Format qty / pct / pnl (pnl and colorBySign require SignDisplay=always, E14)",
            "SignDisplay=never",
            "the right-aligned 160 px numeric column (align-demo)",
            "mono-text in every num-* style",
        ],
        proposed=["E1", "E14", "E15"],
    )


# --- CMP-021 Link
def link(label: str, external: bool, state: str = "default") -> k.Node:
    """CMP-021: type.ui.body color.text.link, always underlined (a 1 px color.text.link rule under the label), the
    external-link glyph space.inset.xs after it; focus-visible: the ring on radius.control (E8); disabled:
    opacity.disabled."""
    lw = round(k.text_w(label, k.BODY))
    lab = k.vbox(
        "label + underline",
        [k.text("label", label, k.BODY, k.TEXT_LINK), k.rect("underline", lw, 1, k.TEXT_LINK)],
    )
    kids = [lab]
    if external:
        kids.append(k.tglyph("→", k.TEXT_LINK, k.BODY, name="CMP-019 external-link (text glyph)"))
    o: dict = {"gap": k.INSET_XS}
    if state == "disabled":
        o["opacity"] = k.OP_DISABLED
    n = k.hbox(f"CMP-021 link · external={str(external).lower()}", kids, o)
    return k.focus_ring(n, radius=k.R_CONTROL) if state == "focus-visible" else n


def b021() -> k.Node:
    internal, ext = k.say("Shortcut settings", "CMP-021"), k.say(
        "Bybit API documentation", "CMP-021"
    )
    rows = [
        k.state_row(
            f"External={str(e).lower()}",
            [
                k.cell(
                    s,
                    link(internal if not e else ext, e, s),
                    note=("ring on radius.control (E8)" if s == "focus-visible" else None),
                )
                for s in ("default", "focus-visible", "disabled")
            ],
        )
        for e in (False, True)
    ]
    DEV.append(
        "CMP-021: the underline (a text property in Penpot) is drawn as a 1 px color.text.link rect under the "
        "label; the external-link icon is not a local icon, drawn as the text glyph → (FALLBACKS ICONS)"
    )
    return k.block(
        "CMP-021",
        rows,
        states=["default", "focus-visible", "disabled"],
        not_drawn=[
            (
                "State=disabled-with-reason: held until slice 2 §5 E27 is answered (s2 L750: a T2 "
                "link or none; the host owns the gating)"
            ),
            ("hover, active and visited (E18: none for " "v0)"),
            "an inline link wrapping with its sentence",
        ],
        proposed=["E27", "E8", "E18", "E25"],
    )


# --- CMP-024 Sparkline
SERIES = {  # 16 normalised y values (0 = top) per trend, inside the spec's 0.15-0.85 margins
    "up": (
        0.80,
        0.78,
        0.72,
        0.74,
        0.66,
        0.62,
        0.64,
        0.55,
        0.50,
        0.52,
        0.44,
        0.38,
        0.36,
        0.28,
        0.22,
        0.18,
    ),
    "down": (
        0.20,
        0.22,
        0.28,
        0.26,
        0.34,
        0.38,
        0.36,
        0.45,
        0.50,
        0.48,
        0.56,
        0.62,
        0.64,
        0.72,
        0.78,
        0.82,
    ),
    "flat": (
        0.50,
        0.48,
        0.52,
        0.50,
        0.47,
        0.51,
        0.53,
        0.50,
        0.48,
        0.50,
        0.52,
        0.49,
        0.50,
        0.51,
        0.49,
        0.50,
    ),
}


def sparkline(trend: str, by_sign: bool) -> k.Node:
    """CMP-024 at its 64 x 16 sample: the polyline as 16 short 4 x 2 px segments (cvsheet has no path node), in
    color.text.tertiary, or by sign: up color.buy.default, down color.sell.default, flat color.neutral.default.
    """
    ink = {"up": k.BUY, "down": k.SELL, "flat": NEUTRAL_DEFAULT}[trend] if by_sign else k.TEXT_3
    segs = [
        k.place(
            k.rect(f"seg {i + 1}", 4, 2, ink, o={"radius": k.R_CONTROL}), 4 * i, round(y * 16) - 1
        )
        for i, y in enumerate(SERIES[trend])
    ]
    return k.box(f"CMP-024 · {trend}", segs, w=64, h=16)


def b024() -> k.Node:
    rows = [
        k.state_row(
            f"Trend={t}",
            [
                k.cell(
                    f"ColorBySign={str(c).lower()}",
                    sparkline(t, c),
                    note=(
                        "color.text.tertiary"
                        if not c
                        else {
                            "up": "color.buy.default",
                            "down": "color.sell.default",
                            "flat": "color.neutral.default",
                        }[t]
                    ),
                )
                for c in (False, True)
            ],
        )
        for t in ("up", "down", "flat")
    ]
    DEV.append(
        "CMP-024: cvsheet has no path node, so the 1.5 px round-capped polyline is drawn as 16 short 4 x 2 px "
        "segments on the 64 x 16 sample; the slope and colour read as the spec's (live check)"
    )
    return k.block(
        "CMP-024",
        rows,
        states=["Trend × ColorBySign (6 variants)"],
        not_drawn=["the 256 x 64 size demo", "the y-range floor (E22, proposed)"],
        proposed=["E22"],
    )


# --- CMP-033 CopyButton
def copy_btn(state: str) -> k.Node:
    """CMP-033: the nested CMP-002 ghost md (size.control.height square): copy glyph color.text.secondary; hover
    color.surface.hover + color.text.primary (E18); copied: check glyph color.status.success.default; focus-visible:
    the CMP-002 ring; disabled: opacity.disabled on the nested button only (conventions 20, E21)."""
    o: dict = {
        "justify": "center",
        "radius": k.R_CONTROL,
        "height": k.CONTROL_H,
        "width": k.CONTROL_H,
    }
    ch, ink, nm = "⧉", k.TEXT_2, "copy"
    if state == "hover":
        o["fill"], ink = k.HOVER, k.TEXT_1
    if state == "copied":
        ch, ink, nm = "✓", k.STATUS["success.default"], "check"
    if state == "disabled":
        o["opacity"] = k.OP_DISABLED
    b = k.hbox(
        "CMP-002 iconbutton · ghost",
        [k.tglyph(ch, ink, k.BODY, name=f"CMP-019 {nm} (text glyph)")],
        o,
        w=k.CONTROL_PX,
        h=k.CONTROL_PX,
    )
    return k.focus_ring(b) if state == "focus-visible" else b


def b033() -> k.Node:
    k.say("Copied", "CMP-033")
    notes = {
        "default": 'aria-label "Copy order ID"',
        "hover": "nested CMP-002 hover (E18)",
        "copied": '"Copied" only in the live region',
        "focus-visible": "the CMP-002 ring",
        "disabled": "dimmed by the nested CMP-002 only",
    }
    rows = [
        k.state_row(
            "md (24 px)",
            [
                k.cell(s, copy_btn(s), note=notes[s])
                for s in ("default", "hover", "copied", "focus-visible", "disabled")
            ],
        )
    ]
    return k.block(
        "CMP-033",
        rows,
        states=["default", "hover", "copied", "focus-visible", "disabled"],
        not_drawn=[
            "State=disabled-with-reason (E21: copying a visible value is never gated)",
            "a copy-failure state (E20, proposed)",
            "comfortable density (32 px)",
        ],
        proposed=["E18", "E20", "E21"],
    )


def main() -> int:
    blocks = [b018(), b020(), b021(), b024(), b030(), b033()]
    bd = k.board(
        NN,
        blocks,
        source="slice 2 §3 conventions 15-20, §6 CMP-018 L604-661, CMP-020 L662-735, CMP-021 "
        "L736-811, CMP-024 L812-871, CMP-030 L939-1000, CMP-033 L1066-1133",
        cols=3,
        notes=[
            "Static atoms (conventions 19): CMP-018, 020, 024 and 030 draw no focus or disabled state",
            "CMP-021's gated state is held for slice 2 §5 E27 (s2 L750): not drawn, stamped PROPOSED",
            "colorBySign always carries its + / − sign and zero is unsigned (conventions 16, E14)",
            *DEV,
        ],
        not_drawn=[
            "every combination beyond the drawn cells (slice 1 conventions 2 matrix rule)",
            (
                "comfortable density and the light / high-contrast themes (board 10 holds the light "
                "Link)"
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
            "every specimen string is say()'d from slice 2; no inst node; no icon (every glyph a text glyph)",
            (
                "CMP-021 draws default / focus-visible / disabled x External and lists disabled-with-reason as not drawn "
                "(E27 PROPOSED), per build-notes §4 board 04"
            ),
            "colorBySign cells carry the sign; the zero cell is unsigned in color.neutral.default",
        ],
        live=[
            "CMP-024 segments: check the stepped polyline reads as one line at 1x",
            (
                "CMP-018 / CMP-030 rules: 1.31:1 on app (slice 2 §4.3), confirm they render (1 px, not anti-aliased "
                "away)"
            ),
        ],
        summary=f"validator: {summary}",
    )
    print(summary)
    print(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
