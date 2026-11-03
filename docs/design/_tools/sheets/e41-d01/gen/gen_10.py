"""Board 10 keyboard-and-reflow: SCR-093's keyboard and reading order, and board 10's three binding lines for the
SCR-096 modal and the SCR-093 export confirm — 200 % reflow, forced colours, focus return (memo §0)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import s093  # noqa: E402
import s096  # noqa: E402
import wf  # noqa: E402
from wf import k  # noqa: E402

NN = 10
VW = 640  # CSS px of a 1280 px window at 200 % zoom
FW_R = VW + 2 * k.FRAME_PAD
L_REFLOW = k.memo("at 200 % zoom both reflow to one column with no horizontal scroll and no clipped action")
L_FORCED = k.memo("borders, the focus ring, the scope label and the CMP-019 lock glyph stay visible in system colours")
L_RETURN = k.memo("focus enters the dialog on its heading, Escape or cancel closes it")


def export_dialog(w: int, *, stacked: bool = False, focus_heading: bool = False, focus_export: bool = False) -> k.Node:
    rs = s093.rows()
    words = k.deck("export.confirm", accounts=", ".join(sorted({t.account for t in rs})), env="LIVE",
                   range=s093.RANGE_WORDS, rows=len(rs))
    ex = wf.btn(k.memo('"Export"')[1:-1], primary=True)
    return wf.dialog(k.memo('"Export"')[1:-1], [k.text("confirm", words, k.BODY, k.TEXT_1, w=w - 48),
                                                 wf.select(k.ui("format"), "CSV", min(200, w - 48))],
                     [wf.btn(k.ui("Cancel")), wf.ring(ex) if focus_export else ex], w, stacked=stacked,
                     focus_heading=focus_heading)


def order_table(rows: list[tuple[str, str, str]], w: int) -> k.Node:
    k.fallback("marker")
    cols = [k.Col("n", "order", 56), k.Col("el", "element", 360), k.Col("keys", "keys", w - 416)]
    return k.grid_table("dashed · keyboard order (board marker)", cols,
                        [{"n": str(i + 1), "el": a, "keys": b + (f" — {c}" if c else "")} for i, (a, b, c) in
                         enumerate(rows)], row_h=24)


def keyboard(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rows = [("Manage tags (header)", "Tab; Enter opens SCR-096", "focus returns here on close"),
            ("Export (header)", "Tab; Enter opens the confirm", "focus returns here on close"),
            ("filters: environment, range, account, symbol, tag, outcome", "Tab between; Enter / Space opens", ""),
            ("table: sortable column headers", "Tab; Enter sorts", "`14` A11y: sortable headers"),
            ("table rows", "Tab to the table; Enter opens SCR-094 (a page)", "WD-12"),
            ("row checkbox", "Space toggles the selection", "bulk tag"),
            ("Next page", "Tab; Enter loads the next cursor page", "")]
    for _a, b, _c in rows:
        k.ui(b, "keyboard line (no journal hotkeys in `14`)")
    pg = s093.screen(n=5, focus="Manage tags")
    return (k.frame(fid, [pg, order_table(rows, wf.TABLE_W)], wf.SCREEN_W,
                    "SCR-093 keyboard order — reading order: heading, scope label, header actions, filters, table, "
                    "totals, pager; the focus ring on 'Manage tags'"),
            k.frame_block(fid, ["Dense focus `05`:90; every control reachable by Tab with a visible ring",
                                "No journal hotkeys exist in `14`; none are invented here"], wds=["WD-12", "WD-13"]))


def viewport(kids: list[k.Node | None], note: str) -> k.Node:
    return k.vbox("viewport · 640 CSS px", [wf.marker(note, VW - 8), *kids],
                  {"gap": k.STACK_SM, "pad": k.INSET_XS, "stroke": k.TEXT_1, "strokeWidth": k.HAIR,
                   "strokeAlign": "inner", "fill": k.SUNKEN}, w=VW)


def tag_cards(w: int) -> k.Node:
    cards = []
    for name, cat_, auto in k.TAGS:
        cards.append(k.vbox(f"tag card · {name}", [
            k.hbox("top", [k.text("name", name, k.BODY_STRONG, k.TEXT_1), k.icon("more", "more-horizontal", k.TEXT_2)],
                   {"justify": "space-between"}, w=w - 16, h=20),
            k.text("facts", f"category {cat_} · usage {s096.usage(name)} trades · colour {s096.COLOUR}", k.CAPTION,
                   k.TEXT_1, w=w - 16),
            k.text("auto", f"auto rule {auto}", k.CAPTION, k.TEXT_2, w=w - 16) if auto else None],
            {"pad": k.INSET_SM, "gap": k.STACK_XS, "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"},
            w=w))
    return k.vbox("tag list (one column)", cards, {"gap": k.STACK_XS}, w=w)


def reflow_096(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    dw = VW - 8
    inner = dw - 48
    dlg = wf.dialog(k.memo('"Manage tags"')[1:-1], [
        k.hbox("search field", [k.icon("glyph", "search", k.TEXT_2), k.text("placeholder", k.ui("Search tags"), k.BODY,
                                                                            k.TEXT_2)],
               {"padX": k.INSET_SM, "gap": k.INSET_XS, "stroke": k.BORDER, "strokeWidth": k.HAIR,
                "strokeAlign": "inner", "radius": k.R_CONTROL, "fill": k.SUNKEN}, w=inner, h=wf.CTRL_H),
        tag_cards(inner)], [wf.btn(k.ui("Close")), wf.btn(k.ui("Create tag"), primary=True)], dw, stacked=True,
        name="CMP-043 dialog · SCR-096")
    vp = viewport([dlg], "1280 px window at 200 % zoom = 640 CSS px wide; no horizontal scroll")
    return (k.frame(fid, [vp], FW_R, "SCR-096 at 200 % — the tag table reflows to one card per tag; every field "
                                     "stays as text; actions stack full width"),
            k.frame_block(fid, [f"memo §0 L{k.L('Board 10 is the carrier')}: reflow — {L_REFLOW}"]))


def reflow_export(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    vp = viewport([export_dialog(VW - 8, stacked=True)], "1280 px window at 200 % zoom = 640 CSS px wide; no "
                                                         "horizontal scroll")
    return (k.frame(fid, [vp], FW_R, "SCR-093 export confirm at 200 % — one column; the account-data line wraps, "
                                     "never clips; actions stack full width"),
            k.frame_block(fid, [f"reflow — {L_REFLOW}"], wds=["WD-10"]))


def forced_lines(items: list[str], w: int) -> k.Node:
    return k.vbox("dashed · forced-colours mapping (board marker)", [wf.marker(x, w, name=f"dashed · map {i + 1}")
                                                                     for i, x in enumerate(items)],
                  {"gap": k.STACK_XS}, w=w)


def forced_096(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    fw = s096.FRAME_W
    m = s096.modal([s096.table()], focus_create=True)
    items = [k.ui(x, "forced-colours mapping") for x in (
        "dialog, field and table borders → CanvasText (every edge is a stroke, none is a fill alone)",
        "focus ring on 'Create tag' → Highlight, 2 px",
        "colour swatch → its token name stays as text beside it; the swatch may lose its fill",
        "usage counts and the auto rule are text; no state rests on fill alone")]
    return (k.frame(fid, [wf.backdrop(m, fw - 48, words=s096.behind()), forced_lines(items, fw - 48)], fw,
                    "SCR-096 in forced colours — what stays visible in system colours"),
            k.frame_block(fid, [f"forced colours — {L_FORCED}"]))


def forced_export(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    items = [k.ui(x, "forced-colours mapping") for x in (
        "dialog border and the format field → CanvasText",
        "focus ring on 'Export' → Highlight, 2 px",
        "the scope behind the dialog and in the confirm (LIVE) is words, not a fill")]
    return (k.frame(fid, [export_dialog(VW - 8, focus_export=True), forced_lines(items, VW - 8)], FW_R,
                    "SCR-093 export confirm in forced colours"),
            k.frame_block(fid, [f"forced colours — {L_FORCED}"], wds=["WD-10"]))


def step(n: int, caption: str, kid: k.Node, w: int) -> k.Node:
    return k.vbox(f"step {n}", [wf.marker(f"{n}. {caption}", w), kid], {"gap": k.STACK_SM}, w=w)


def focus_return(fid: str, which: str) -> tuple[k.Node, tuple[str, list[str]]]:
    w = (wf.PAGE_W - 2 * 16) // 3
    opener = which
    b1, b2 = wf.btn(k.memo('"Manage tags"')[1:-1]), wf.btn(k.memo('"Export"')[1:-1])
    acts = k.hbox("actions", [wf.ring(b1), b2] if which == "Manage tags" else [b1, wf.ring(b2)], {"gap": k.INSET_SM},
                  h=wf.CTRL_H)
    if which == "Manage tags":
        dlg = wf.dialog(k.memo('"Manage tags"')[1:-1], [k.text("body", k.ui("(tag table)"), k.CAPTION, k.TEXT_3)],
                        [wf.btn(k.ui("Close"))], w, focus_heading=True, name="CMP-043 dialog · SCR-096")
    else:
        dlg = export_dialog(w, focus_heading=True)
    steps = [step(1, f"'{opener}' has focus; Enter opens", acts, w),
             step(2, "focus enters on the dialog heading; Tab stays inside", dlg, w),
             step(3, f"Escape, cancel or confirm closes; focus is back on '{opener}'", acts, w)]
    # SHEET-FIX 10 (live check): step 3 ended at 1151 px, so the sequence spans the page width (24 px margin kept)
    return (k.frame(fid, [k.hbox("sequence", steps, {"gap": k.INSET_LG, "align": "start"}, w=wf.PAGE_W)],
                    wf.SCREEN_W, f"{fid.split(' · ')[0]} focus return — open, inside, close"),
            k.frame_block(fid, [f"focus return — {L_RETURN}; on close, cancel or confirm focus returns to the "
                                f"control that opened it ('{opener}')", "`05`:90"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    fs = k.BOARDS[NN].frames
    out = [keyboard(fs[0]), reflow_096(fs[1]), reflow_export(fs[2]), forced_096(fs[3]), forced_export(fs[4]),
           focus_return(fs[5], "Manage tags"), focus_return(fs[6], "Export")]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    wf.run(NN, frames(), 2)
