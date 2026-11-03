"""Board 08 `E47-D08 / 08 override-vs-os` (dark): §9 — the OS asks for reduced motion, the user's explicit choice is
Off (`Ctrl+Shift+M`), so full motion is effective; the one polite announcement W-2 and SCR-117's Effective line (a fill
of E47-D05 §5.1's template at its pin) state it. SCR-117's rows are drawn from E47-D05's strings at that pin."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k  # noqa: E402

NN = 8
D05_H1_LN = k.D5L("exactly one `h1`")
H1 = re.search(r'exactly one `h1` "([^"]+)"', k.D05_LINES[D05_H1_LN - 1]).group(1)
D05_ORDER_LN = k.D5L("**Motion**")
SECTION = "Motion"
KEY_LN = k.L("`Ctrl+Shift+M` writes")
KEYS = re.search(r"`(Ctrl\+Shift\+M)`", k.SPEC_LINES[KEY_LN - 1]).group(1)


def radio(label_: str, checked: bool) -> k.Node:
    dot = [k.ellipse("dot", 8, 8, {"fill": k.ACTION_PRIMARY}, x=4, y=4, abs=True)] if checked else []
    circle = k.box("circle", [k.ellipse("outline", 16, 16, {"fill": k.CANVAS, "stroke": k.BORDER_STRONG,
                                                           "strokeWidth": k.HAIR, "strokeAlign": "inner"}, x=0, y=0,
                                        abs=True), *dot], w=16, h=16)
    return k.hbox(f"radio · {label_}", [circle, k.text("label", label_, k.BODY, k.TEXT_1)], {"gap": k.INSET_SM},
                  h=k.CONTROL_H, note=f'role="radio" aria-checked="{str(checked).lower()}"')


def row_reduced(eff: str) -> k.Node:
    lab, desc, ln = k.D05_ROWS["reduced_motion"]
    group = k.hbox("CMP-006 RadioGroup", [radio(o, o == "Off") for o in k.D05_TRI], {"gap": k.INSET_LG}, h=32,
                   note="radiogroup: one Tab stop (E47-D05 §5.1); Off is the explicit choice")
    return k.vbox("option row · reduced_motion", [
        k.text("label", lab, k.BODY_STRONG, k.TEXT_1), k.text("description", desc, k.CAPTION, k.TEXT_2, w=560),
        group, k.text("Effective line", eff, k.CAPTION, k.TEXT_2, w=560,
                      note="in the row's aria-describedby; not a live region (E47-D05 §5.1)")],
        {"gap": k.STACK_XS}, w=560, note=f"E47-D05 §4 L{ln} at {k.D05_SHA}")


def row_canvas() -> k.Node:
    lab, desc, ln = k.D05_ROWS["disable_canvas_animation"]
    sw = k.box("switch", [k.ellipse("knob", 12, 12, {"fill": k.TEXT_2}, x=4, y=4, abs=True)],
               {"fill": k.HOVER, "radius": k.R_BADGE, "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                "strokeAlign": "inner"}, w=38, h=20, note='role="switch" aria-checked="false"')
    return k.vbox("option row · disable_canvas_animation", [
        k.hbox("label + switch", [k.text("label", lab, k.BODY_STRONG, k.TEXT_1), sw], {"gap": k.INSET_LG}, h=24),
        k.text("description", desc, k.CAPTION, k.TEXT_2, w=560)], {"gap": k.STACK_XS}, w=560,
        note=f"E47-D05 §4 L{ln}; off, so the tier is full (§2)")


def main() -> None:
    fid = k.BOARDS[NN].frames[0]
    eff = k.d05_effective(False, "your choice")
    full = k.TIER_TABLE["full"]
    page = k.vbox("SCR-117 page", [k.text("h1", H1, k.HEADING_LG, k.TEXT_1),
                                   k.text("h2", SECTION, k.HEADING_SM, k.TEXT_1),
                                   row_reduced(eff), row_canvas()], {"gap": k.STACK_LG, "pad": k.INSET_XL}, w=640)
    k.fallback("markers")
    over = [k.tag("OS: prefers-reduced-motion: reduce", 680, 24, name="tag · OS signal"),
            k.tag(f"{KEYS} pressed: explicit choice Off, persisted", 680, 48, name="tag · hotkey"),
            k.callout("announcement", [f"Polite, once, no toast: \"{k.w('W-2')}\" (W-2)",
                                      f"The words stay as RULED (BQ-9 overridden; §9 L{KEY_LN}); no \"overriding your "
                                      "system setting\" clause (D08-C13)"], 680, 80, 360),
            k.callout("effective", [f"SCR-117's Effective line: \"{eff}\"",
                                    f"The lasting statement of the override (W-3 \"{k.w('W-3')}\" is the On fill of "
                                    f"the same template, E47-D05 L{k.D05_COPY['W-13'][1]})"], 680, 200, 360),
            k.callout("tier", [f"Effective tier full: data-motion {full['motion']}; engine flags {full['flags']} "
                               f"(§2 L{full['line']})", "The budget of §4 still binds (R-1)"], 680, 320, 360)]
    content = k.box("workspace", [dict(page, x=0, y=0), *over], {"fill": k.APP}, w=k.MAIN_W, h=k.BODY_H)
    fr = k.window(fid, content, note="§9: OS reduce, the override Off")
    lines = [f"§9 L{KEY_LN}: the latest explicit choice wins over the OS in both directions; {KEYS} persists and "
             f"announces once, politely (W-1 / W-2)",
             f"State: OS reduce on, choice Off → full motion; announcement \"{k.w('W-2')}\"",
             f"Effective line \"{eff}\": E47-D05 §5.1's template (L{k._D05_TPL_LN}) filled Off / your "
             "choice",
             f"SCR-117 strings at E47-D05 {k.D05_SHA}: h1 L{D05_H1_LN}, section {SECTION} L{D05_ORDER_LN}, rows §4"]
    k.ambiguity(f"A-2: §0 L{k.BOARDS[NN].line} asks for SCR-117's Effective line with the override off; §15's W-3 is "
                "the On fill; the board draws the Off fill of the same E47-D05 template (\"" + eff + "\")")
    p, md, pk = k.build(NN, [fr], [(fid, lines)], per_row=1, board_lines=[
        "The motion preview tile (I-41) and SCR-117's other sections are not drawn here (E47-D05's boards draw them)"])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
