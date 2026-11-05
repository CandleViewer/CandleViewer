"""Board 10 keyboard-table-reflow: §9 the focus order and the row menu, §9.2 the keys, §10 the Table view, §9.4 the
200 % reflow."""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 10


def focus_menu() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/streaming · focus order and row menu"
    p = ui.P()
    r = k.SINGLE_SELL_AT
    y_pane = ui.HEAD_H + ui.NOTICE_H + ui.COLHEAD_H
    order = [ui.header_x(p, "left", "depth"), ui.header_x(p, "right", "view switch"),
             ui.header_x(p, "right", "follow"), ui.header_x(p, "right", "⋯"),
             (8, y_pane + 8), (ui.LADDER_X + 8, y_pane + 8), (12, k.WIN_H - ui.FOOT_H - ui.STRIP_H + 4),
             (12, k.WIN_H - ui.STRIP_H + 2)]
    marks = [ui.announce(ui.row_reading(r, p.tier), how="the focused row's reading (values update silently, R-7)")]
    fr = ui.panel(fid, p, focus_row=r, menu_row=r, markers=marks)
    fr["kids"] += [ui.order_marker(i + 1, max(0, x - 10), max(0, y - 10)) for i, (x, y) in enumerate(order)]
    k.derive(f"the focused row {k.price0(r)} reads its six cells from the world (§9.2's form; its examples are "
             "illustrative)")
    return fr, k.frame_block(fid, [
        "Tab order (§9.1): 1-4 header controls (depth, view switch, follow toggle, ⋯; scale, trail, cell and ARM "
        "inside ⋯ at 1280 px) → 5 heatmap pane (one stop, role=\"img\") → 6 ladder grid (one stop, roving rows) → 7 "
        "footer → 8 detector strip; Ctrl+\\ cycles regions; initial focus the grid at the mark's row",
        "Enter on a row opens the row menu as `14`:1217 words it (C-4): limit, stop, TP T2 2a on W-20, then alert "
        "here and copy price enabled; focus on the first item; Esc returns focus to the row",
        "The ring color.focus.ring, 2 px, outside the 24 px row box, never under the sticky header or footer (§9.3)"])


def table() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/streaming · Table view"
    p = ui.P(table=True)
    return ui.panel(fid, p), k.frame_block(fid, [
        "`Ladder │ Table` (Alt+T) in the never-overflow set; a Viewer sees it; neither view is an alternative or a "
        "fallback — both are views of one panel; the same T2 notice",
        "Windowed with `05`'s keyboard-operable, focus-preserving \"load more rows\" (`05`:195): the 500 tier's rows "
        "201–500 reachable; `05` stopping at 200 is G-2; the heatmap table PROPOSED (G-4); checklist item 5 open"])


def reflow() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = k.REFLOW
    W_, H_ = k.WIN_W // 2, k.WIN_H // 2  # 200 % in the 1280 × 800 frame: 640 × 400 CSS px
    p = ui.P()
    kept = (0, 1, 2, 5)
    lw = sum(ui.LCOL_W[i] for i in kept)
    pane_room = W_ - lw
    if pane_room >= W_ // 4:
        raise ValueError("the pane would not hide")
    k.derive(f"200 %: {W_} × {H_} CSS px; the ladder keeps Price, Bid (B), Ask (A), Your orders = {lw} px, leaving "
             f"{pane_room} px < 25 % ({W_ // 4} px), so the pane hides behind the Heatmap toggle")
    hd = ui.header(p)
    lb, rb = hd["kids"][0], hd["kids"][1]
    head = k.box("panel header (two rows)", [dict(lb, x=12, y=8), dict(rb, x=12, y=8 + ui.CTRL + 8),
                                             k.rect("rule", W_, 1, k.BORDER, x=0, y=2 * ui.CTRL + 23)],
                 {"fill": k.CANVAS}, w=W_, h=2 * ui.CTRL + 24, x=0, y=0)
    y = head["h"]
    nt = dict(ui.notice(p, w=W_), y=y)
    y += ui.NOTICE_H
    tog = ui.button(k.ui("Heatmap", "§9.4's toggle name"), kind="ghost", h=24, name="Heatmap toggle (aria-pressed)")
    tg = k.box("heatmap toggle row", [dict(tog, x=12, y=4)], {"fill": k.CANVAS}, w=W_, h=32, x=0, y=y)
    y += 32
    xs, kids = 0, []
    for i in kept:
        kids.append(k.text(f"th · {k.COL_HEADS[i]}", k.COL_HEADS[i], k.CAPTION, k.TEXT_2, x=xs + 8, y=5))
        xs += ui.LCOL_W[i]
    ch = k.box("column header row (four kept)", kids, {"fill": k.CANVAS}, w=W_, h=ui.COLHEAD_H, x=0, y=y)
    y += ui.COLHEAD_H
    foot = ui.footer(0, w=W_, two_rows=True)
    strip = ui.strip(p, 0, w=W_)
    body_h = H_ - y - foot["h"] - strip["h"]
    n = math.floor(body_h / p.row_h)
    rows = k.rows_window(25)[12 - n // 2:12 - n // 2 + n]
    rk = []
    for j, r in enumerate(rows):
        vals = [k.price0(r), ui.side_cell(r, "bid", p.tier), ui.side_cell(r, "ask", p.tier), ui.own_words(r)]
        x0 = 0
        for i, v in zip(kept, vals):
            if v:
                rk.append(k.text(f"td · {k.price0(r)} · {k.COL_HEADS[i]}", v, k.NUM_SM, k.TEXT_1, x=x0 + 8,
                                 y=j * p.row_h + 5))
            x0 += ui.LCOL_W[i]
        rk.append(k.rect(f"row rule · {j:02d}", W_, 1, k.GRID, x=0, y=j * p.row_h + p.row_h - 1))
    bd = k.box("ladder body (Prints and Cum. depth in the row reveal)", rk, {"fill": k.CANVAS}, w=W_, h=body_h, x=0,
               y=y)
    y += body_h
    kids2 = [head, nt, tg, ch, bd, dict(foot, y=y), dict(strip, y=y + foot["h"])]
    return k.window(fid, kids2, w=W_, h=H_, note="200 % zoom, drawn in CSS px"), k.frame_block(fid, [
        "Drawn in CSS px (640 × 400 = the 1280 × 800 frame at 200 %); the header keeps title · depth · env badge · "
        "view switch · follow toggle · ⋯ (two rows); the notice wraps, never clipped; the footer wraps to two rows",
        "The pane hides behind the Heatmap toggle (native button, aria-pressed, just before the pane's stop), the "
        "reveal still reachable; Prints and Cum. depth move to the row reveal",
        "At 400 % (320 CSS px) the header, notice and footer reflow to one column; the grid scrolls horizontally "
        "inside itself (the data-table exception); the Table view stacks per row — not drawn, the text is binding"])


def keys() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = k.KEYS
    tbl = k.grid_table("§9.2 keys", [k.Col("k", "Key", 200), k.Col("w", "Where", 120), k.Col("e", "Effect", 880)],
                       [{"k": k.plain(c[0]), "w": k.plain(c[1]), "e": k.plain(c[2])} for _i, c in k.KEY_ROWS],
                       cap=f"§9.2 L{k.KEY_ROWS[0][0]}: the keys (single keys only while focus is in the panel)")
    return k.marker_frame(fid, [tbl], 1248), k.frame_block(fid, [
        "Home / End and Shift+Enter are PROPOSED (C-4, OQ-2); every binding remappable (`05`:32); Ctrl+Shift+T is "
        "the app-wide arm key (D02E30:355)"])


if __name__ == "__main__":
    ui.run(NN, [focus_menu(), table(), reflow(), keys()], 2)
