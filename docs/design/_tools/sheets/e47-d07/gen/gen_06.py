"""Board 06 `E47-D07 / 06 scr117-panel` (dark): §8 — the Announcements FormSection in SCR-117: the Reduce toggle, one
fieldset per panel class with its RadioGroup, the fixed safety row T2 (§8.2), and the view-as state (every control
T2). Board 07 calls build_frame("light") for the default frame."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k  # noqa: E402

NN = 6
LEGEND_W, ROW_H = 220, 28
SAFETY = k.PANEL[0]["cls"]
if k.PANEL[0]["choice"] != "fixed: T2 per §8.2":
    raise SystemExit("board 06: §8.1's first row is no longer the fixed safety row")
W = k.CONTENT_W - 2 * k.CONTENT_PAD


def options(p: dict) -> list[str]:
    ch = p["choice"]
    if ch.startswith("fixed"):
        return ["Assertive", "Polite"]  # the six's classes offer no Off (§8.1); the kit's reading for the fixed row
    return [o.strip() for o in ch.split("(")[0].split("/")]


def class_row(p: dict, *, t2: bool, focused: bool, theme: str) -> dict:
    opts = options(p)
    if p["default"] not in opts:
        raise SystemExit(f"board 06: {p['cls']}'s default {p['default']} is not among {opts}")
    leg = k.lock_label(p["cls"], k.BODY_STRONG, name="legend") if t2 else k.text("legend", p["cls"], k.BODY_STRONG,
                                                                                  k.TEXT_1)
    leg = k.hbox("legend cell", [leg], {}, w=LEGEND_W, h=ROW_H)
    radios = [k.radio(o, o == p["default"], theme=theme, t2=t2, focused=focused and o == p["default"])
              for o in opts]
    go: dict = {"gap": k.INSET_LG}
    if t2:
        go.update(fill=k.RAISED, stroke=k.BORDER, strokeWidth=k.HAIR, strokeAlign="inner", padX=k.INSET_SM,
                  radius=k.R_CONTROL)
    group = k.hbox("CMP-006 RadioGroup", radios, go, h=ROW_H + (2 * k.extent("normal") if focused else 0),
                   note='role="radiogroup", roving tabindex, one Tab stop (`15`:108)'
                        + ("; T2: every radio aria-disabled, arrows move focus without checking (§8.2)" if t2 else ""))
    row = k.hbox(f"fieldset · {p['cls']}", [leg, group], {"gap": k.INSET_MD}, w=W,
                 note=f"CMP-065 fieldset, legend \"{p['cls']}\"; {p['rows']}; default {p['default']} (§8.1 L{p['line']})"
                      + ("; CMP-079 RbacGate, rendering 2a" if t2 else ""))
    return row


def panel(theme: str, *, view_as: bool) -> dict:
    sec = k.SECTION_NAME
    kids: list[dict] = [k.text("h2", sec, k.HEADING_SM, k.TEXT_1, note="h2 inside the FormSection's legend (`15`:743)")]
    if view_as:
        kids.append(k.hbox("CMP-065 notice · view-as", [
            k.icon("glyph", "locked", k.TEXT_2), k.text("words", k.VIEW_AS_REASON.replace("{user}", k.VIEW_AS_USER),
                                                       k.BODY, k.TEXT_1)],
            {"gap": k.INSET_SM, "padX": k.INSET_MD, "fill": k.RAISED, "radius": k.R_CARD, "stroke": k.BORDER,
             "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=W, h=36,
            note=f"rbac.view_as (D09E09:{k.VIEW_AS_LINE}); every gated control's aria-describedby points here "
                 "(`15`:742)"))
    sw = k.switch(False, theme=theme, t2=view_as)
    lab = (k.lock_label(k.REDUCE_LABEL) if view_as else k.text("label", k.REDUCE_LABEL, k.BODY_STRONG, k.TEXT_1))
    kids.append(k.hbox("CMP-004 Toggle · Reduce announcements", [
        sw, k.vbox("text", [lab, k.text("help", k.REDUCE_HELP, k.CAPTION, k.TEXT_2)], {"gap": k.STACK_XS})],
        {"gap": k.INSET_MD, "align": "start"}, w=W,
        note="accessibility.reduce_announcements, PROPOSED (D07-G3; E47-S07 #1321's contract PR)"))
    rows = []
    for i, p in enumerate(k.PANEL):
        t2 = view_as or p["cls"] == SAFETY
        r = class_row(p, t2=t2, focused=(not view_as and p["cls"] == SAFETY), theme=theme)
        if p["cls"] == SAFETY:
            reason = k.text("reason · W-39", k.w("W-39"), k.CAPTION, k.TEXT_2,
                            note="the T2 reason node (a11y.safety_fixed, PROPOSED), in the DOM at mount, linked by "
                                 "aria-describedby, color.text.secondary (§8.2)")
            r = k.vbox(f"fieldset · {SAFETY} + reason", [r, k.hbox("reason row", [reason], {"padL": k.INSET_LG},
                                                                     w=W, h=16)], {"gap": k.STACK_XS}, w=W)
        rows.append(r)
    kids.append(k.vbox("the classes", rows, None, w=W,
                       note="accessibility.announce_classes, PROPOSED (D07-G3): one fieldset per §8.1 class"))
    pg = k.vbox(f"CMP-065 FormSection · {sec}", kids, {"gap": k.STACK_MD, "pad": k.INSET_XL, "fill": k.APP},
                w=k.CONTENT_W, note=f"after E47-D05's announcement controls (D05:201); §8.1 L{k.PANEL_LINE}")
    h = k.est_height(pg)
    if h > k.BODY_H:
        raise SystemExit(f"board 06: the section ({h:.0f} px) outruns the {k.BODY_H} px viewport")
    return pg


def build_frame(fid: str, theme: str, *, view_as: bool = False) -> dict:
    tags = [k.synthetic_tag(k.SHELL_TAG_X, k.FRAME_H - 40)]
    if not view_as:
        tags.append(k.tag("Tab stop: the T2 group, focused on its checked radio (§8.2)", k.NAV_W + k.SET_NAV_W + 560,
                          k.TOP_H + 64, name="tag · T2 focus"))
    else:
        tags.append(k.tag(f"view-as {k.VIEW_AS_USER} (synthetic user)", k.NAV_W + k.SET_NAV_W + 600, k.TOP_H + 16,
                          name="tag · view-as user"))
    return k.window(k.frame_name(fid), panel(theme, view_as=view_as), overlays=tags,
                    note="SCR-117 scrolled to the Announcements FormSection")


def blocks(fid: str, *, view_as: bool) -> list[str]:
    out = [f"§8.1 L{k.PANEL_LINE}: a CMP-004 Toggle \"{k.REDUCE_LABEL}\" (help \"{k.REDUCE_HELP}\"), then one CMP-065 "
           f"fieldset per class ({len(k.PANEL)}) with a CMP-006 RadioGroup, the class default checked; the two keys "
           "are drawn PROPOSED (D07-G3, E47-S07 #1321's contract PR, BQ-8)",
           f"§8.2 L{k.T2_LINE}: \"{SAFETY}\" is T2 — lock glyph leading the legend in color.text.tertiary, the reason "
           "W-39 under it in color.text.secondary, raised fill with a border.default hairline, every radio "
           "aria-disabled, still in the Tab order; never opacity.disabled or color.text.disabled",
           "The contrast of both T2 tokens on color.surface.raised is E47-D03's measured figure (D03:159, :160), cited "
           "not restated (C-16.5)"]
    if view_as:
        out.append(f"View-as: every control T2 with rbac.view_as (D09E09:{k.VIEW_AS_LINE}); one CMP-065 notice "
                   f"\"{k.VIEW_AS_REASON}\" with the synthetic user {k.VIEW_AS_USER}")
    else:
        out.append("Space / Enter / Ctrl+Shift+M on the T2 group changes nothing and re-shows W-39 with one polite "
                   "announcement, not again within 5 s (§8.2)")
    return out


def notes() -> None:
    k.ambiguity("Boards 06 / 07: §8.1's fixed row lists no options; the kit draws Assertive / Polite (the six's "
                "classes offer no Off, §8.1), Assertive checked")
    k.ambiguity(f"Boards 06 / 07: the fieldsets are drawn legend-beside-radios ({LEGEND_W} px legend) so the "
                "seventeen fit the viewport; §8.3's stacking applies at 400 % zoom and 200 % text (not drawn, §0)")
    k.ambiguity("Board 06 view-as: §8.2 gives one notice for every gated control; the safety row keeps its own W-39 "
                "reason as well")


def main() -> None:
    b = k.BOARDS[NN]
    notes()
    frames = [build_frame(b.frames[0], "dark"), build_frame(b.frames[1], "dark", view_as=True)]
    bl = [(b.frames[0], blocks(b.frames[0], view_as=False)), (b.frames[1], blocks(b.frames[1], view_as=True))]
    p, md, pk = k.build(NN, frames, bl, per_row=2)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()
