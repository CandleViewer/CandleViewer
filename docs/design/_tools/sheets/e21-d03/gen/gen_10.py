"""Board 10 keyboard-reflow: SCR-051/unsaved-esc with §13.1's focus order drawn over it, and the 200 % reflow
(§13.3) drawn in CSS px."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 10
# §13.1's Tab order on Depth & scale: close → tablist → the tabpanel's fields in reading order → the footer
# (a radio group is one stop, on its checked option: "checked" finds it, whatever its label)
STOPS = (("close button", "close"), ("CMP-042 tablist", "tablist (one stop)"), ("checked", "Depth tier"),
         ("CMP-005 Keep this tier", "W-15"), ("input", "Row aggregation"), ("CMP-006 option Auto", "Columns"),
         ("CMP-008 Trail length", "Trail length"), ("CMP-009 Decay", "Decay"),
         ("CMP-001 Reset to defaults", "Reset to defaults"), ("CMP-001 Reset this tab", "Reset this tab"),
         ("CMP-001 Cancel", "Cancel"), ("CMP-001 Save", "Save"))
# the live check's offsets (px) from the kit's estimate, by stop: the Depth tier options before the checked one are
# narrower live than estimated, so marker 03 moves onto the checked option's live corner (SHEET-FIX 10: 282 -> 266)
LIVE_DX = {3: -16}


def _stop(nm: str) -> Callable[[str, k.Node], bool]:
    def test(p: str, n: k.Node) -> bool:
        if nm == "input":
            return n["name"].startswith(nm) and "field · Row aggregation" in p
        if nm == "checked":
            return n["name"].startswith("CMP-006 option") and n.get("note") == "checked" and "group · Depth tier" in p
        return bool(n["name"].startswith(nm))
    return test


def unsaved() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/unsaved-esc"
    w29 = k.W("W-29")
    d = ui.Dlg(trail="120", status=w29, focus="trail", extra=[ui.announce(w29), reset_marker()])
    w = ui.dialog_window(fid, d)
    marks = []
    for i, (nm, _lab) in enumerate(STOPS, 1):
        x, y, _w, _h = ui.find(w["kids"], _stop(nm))
        marks.append(ui.order_marker(i, max(0, x - 10 + LIVE_DX.get(i, 0)), max(0, y - 10)))
    w["kids"] += marks
    k.derive("focus-order markers placed by the kit's size estimates (live check: each marker at its control's top-left)")
    k.live("board 10: every focus-order marker sits at its control's top-left corner; nudge in 4 px steps if not")
    rows = [f"{i} {lab}" for i, (_nm, lab) in enumerate(STOPS, 1)]
    return w, k.frame_block(fid, [
        "Trail length changed 60 → 120 s (a visual key), then Esc: W-29 in the footer, once through the status node; a "
        "second Esc discards; focus stays where it was (C-3: no nested modal)",
        "Tab order (§13.1): " + " → ".join(rows) + "; the tile and the cost panel are not stops; the focus trap holds",
        *(f"§13.1 L{ln}: {k.plain(c[0])} in {c[1]}: {c[2]}" for ln, c in k.KEYS13),
        *enter_t2(),
        "W-37 (the foot strip's right marker): either reset writes it once through the status node (R-5, §13.2) and "
        "keeps focus on its button; Cancel undoes it (§2.1); not this frame's state, drawn here so every R-5 "
        "announcement has a board"])


def reset_marker() -> k.Node:
    """W-37's two forms (§15), announced polite once on either reset: a foot-strip marker right of W-29's."""
    x = 16 + 520 + 16
    w = k.WIN_W - x - 16
    kids = [ui.text("how", k.ui("announced: polite, once, on Reset to defaults · on Reset this tab (W-37)",
                                "board-marker label"), k.CAPTION, k.TEXT_3),
            ui.hbox("words (two forms, one line: the strip stays as low as W-29's)",
                    [ui.text("words · Reset to defaults", k.W("W-37", 0), k.CAPTION, k.TEXT_1),
                     ui.text("words · Reset this tab", k.W("W-37", 1), k.CAPTION, k.TEXT_1)],
                    {"gap": k.INSET_LG}, w=w - 16, h=14)]
    n = ui.marker_box("announcement · W-37", kids, w=w, tight=True)
    n = dict(n, h=k.est_drawn_height(n), x=x)
    return dict(n, y=ui.foot_strip_y(n))


def enter_t2() -> list[str]:
    """The `Enter` row on a T2 option (§3.2 says `Space` or `Enter` re-shows W-3; review Minor carried to the boards
    PR): drawn as an annotation until §13.1 carries the row itself, then the parsed row above says it."""
    if any("Enter" in k.plain(c[0]) and "radio" in c[1] for _ln, c in k.KEYS13):
        return []
    k.S("Space or Enter re-shows W-3")
    return ["§13.1 + the Enter row (§3.2, G-T2.3): Enter on a T2 option (the 500 radio) re-shows W-3, as Space does; "
            "it never selects the option"]


def reflow() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = k.REFLOW
    vw, vh = k.WIN_W // 2, k.WIN_H // 2
    k.derive(f"200 % of the {k.WIN_W} × {k.WIN_H} window = a {vw} × {vh} CSS px viewport; drawn in CSS px")
    title = ui.text("W-1 title", k.W("W-1"), k.HEADING_SM, k.TEXT_1)
    head = ui.hbox("header", [ui.hbox("title and badge", [title, ui.env_badge("DEMO")], {"gap": k.INSET_SM}, h=24),
                              ui.close_btn()], {"padX": k.INSET_LG, "justify": "space-between"}, w=vw, h=48, x=0, y=0)
    tabs = []
    for t in k.TABS:
        sel = t == "Depth & scale"
        lab = ui.hbox("label", [ui.text("words", k.S(t), k.LABEL, k.TEXT_1 if sel else k.TEXT_2)], {"padX": k.INSET_MD},
                      h=30)
        tabs.append(ui.vbox(f"tab · {t}", [lab, ui.rect("selected rule" if sel else "rule slot",
                                                          round(k.est_width(lab)), 2,
                                                          k.BORDER_SELECTED if sel else None)], {}, h=32))
    tl = ui.vbox("CMP-042 tablist (wrapped to two rows)", [
        ui.hbox("tab row 1", tabs[:3], {"align": "start"}, h=32), ui.hbox("tab row 2", tabs[3:], {"align": "start"},
                                                                          h=32)],
        {"padX": k.INSET_SM, "gap": k.STACK_XS}, w=vw, note="§13.3: the tablist wraps to two rows")
    tl_h = math.ceil(k.est_height(tl))
    tl = dict(tl, h=tl_h, x=0, y=48)
    ft = ui.hbox("footer (sticky)", [ui.button(k.S("Reset to defaults"), kind="ghost"),
                                     ui.button(k.S("Reset this tab"), kind="ghost"), ui.button(k.S("Cancel")),
                                     ui.button(k.S("Save"), kind="primary")],
                 {"gap": k.INSET_XS, "padX": k.INSET_SM}, w=vw, h=56, x=0, y=vh - 56)
    body_y = 48 + tl_h + 1
    body_h = vh - 56 - 1 - body_y
    d = ui.Dlg(focus="tier 200")
    fields = ui.vbox("tabpanel · Depth & scale (scrolls)", ui.depth_tab(d)[:3], {"gap": k.STACK_MD}, w=vw - 48,
                     x=16, y=body_y + 12)
    fields["h"] = math.ceil(k.est_height(fields))
    body = ui.box("body (scroll region)", [fields, ui.rect("scroll thumb", 4, max(24, body_h // 3), k.BORDER_STRONG,
                                                            x=vw - 8, y=body_y + 4)], {"clip": True}, w=vw, h=vh,
                  x=0, y=0)
    card = ui.box("CMP-043 dialog (fills the viewport)", [body, head, tl,
                                                          ui.rect("tabs rule", vw, 1, k.BORDER, x=0, y=body_y - 1),
                                                          ui.rect("footer rule", vw, 1, k.BORDER, x=0, y=vh - 57), ft],
                  {"fill": k.OVERLAY, "clip": True}, w=vw, h=vh, x=0, y=0)
    return k.window(fid, [card], w=vw, h=vh), k.frame_block(fid, [
        "200 % in the 1280 × 800 frame: the dialog fills the viewport (CMP-043 reflow); the tablist wraps to two rows; "
        "the body scrolls between the fixed header and the sticky footer, so Save, Cancel and the status node stay "
        "visible; the tile moves under the fields at full width (below this scroll position)",
        "The focused field is never under the footer (`05`:99); at 400 % (320 CSS px) the footer wraps to two rows and "
        "every field is one column — not drawn, the text is binding (§13.3)",
        *(f"§13.4 forced colours: {k.plain(c[0])} — {c[1]}" for _ln, c in k.FORCED[:4])])


if __name__ == "__main__":
    ui.run(NN, [unsaved(), reflow()], 2, board_lines=[
        "Owner walkthrough item 9 (§18): walk the dialog with the keyboard and press Esc with a change unsaved",
        "The other tabs at 200 % are not drawn — the text is binding (§0)"])
