"""E47-D04 / 04 retention: a re-seed with the level kept, the nearest level with W-4, a closed position's successor
with W-5, and 2.4.11 under a floating order ticket (§8, §7.5)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, bodies, BODY_W  # noqa: E402

NN = 4
F_KEPT, F_NEAR, F_ROW, F_OBS = k.frames_of(NN)
DOM_X, DOM_Y, _DW, _DH = k.GEO["dom"]
L8 = k.L("## 8. Retention under live data")
FOCUS = k.BEST_BID - 2 * k.TICK  # the level the user had focused before the re-seed
RESEED = k.SEED + 7  # the re-seeded book's sizes


def frame_kept() -> tuple[k.Node, tuple[str, list[str]]]:
    lv = k.ladder(seed=RESEED)
    ov = [k.callout("kept", [f"WS reconnect re-seeded the book; {k.px_fmt(FOCUS)} survives:",
                             "focus stays on the same price (R-3); nothing is announced"], DOM_X - 330, DOM_Y + 160,
                    320)]
    fr = k.workspace_window(F_KEPT, bodies(dom=k.ladder_table(lv, focus=FOCUS)), focus_panel="dom", overlays=ov,
                            note=f"after the re-seed: focus on {k.px_fmt(FOCUS)}, its size re-seeded")
    lines = [f"§8 L{L8} row 'WS reconnect re-seeds a book (level survives)': the same logical price level (R-3); "
             "announced: nothing",
             f"Drawn: before the re-seed focus was on {k.px_fmt(FOCUS)} (best bid {k.px_fmt(k.BEST_BID)} - 2 ticks of "
             f"{k.TICK}); after it the sizes are new (seed {RESEED}) and the focus is unchanged",
             f"{k.rule('R-3')}: identity is the price, never the DOM or row index",
             f"{k.rule('R-5')}: a data event never moves focus"]
    return fr, k.frame_block(F_KEPT, lines)


def frame_near() -> tuple[k.Node, tuple[str, list[str]]]:
    lv = k.ladder(seed=RESEED, vanished=[FOCUS])
    to = k.nearest_survivor(lv, FOCUS)
    say = k.w("W-4", k.px_fmt(FOCUS), k.px_fmt(to))
    ov = [k.callout("W-4", ["The level vanished; nearest by price, ties toward the touch:", f'"{say}" (once, polite)'],
                    DOM_X - 330, DOM_Y + 160, 320)]
    fr = k.workspace_window(F_NEAR, bodies(dom=k.ladder_table(lv, focus=to)), focus_panel="dom", overlays=ov,
                            note=f"{k.px_fmt(FOCUS)} has no size after the re-seed; focus on {k.px_fmt(to)}")
    lines = [f"§8 L{L8} row 'level vanished': the nearest surviving level by price, ties toward the touch (best bid "
             "or ask); an empty book → the grid's empty-state stop; W-4 once",
             f"Drawn: {k.px_fmt(FOCUS)} has no resting size; {k.px_fmt(FOCUS - k.TICK)} and {k.px_fmt(FOCUS + k.TICK)} "
             f"are one tick away, the tie goes toward the touch (best bid {k.px_fmt(k.BEST_BID)}): {k.px_fmt(to)}",
             f"W-4 (§15 L{k.COPY['W-4'].line}, PROPOSED; wording E47-D07's): \"{say}\"",
             "QA-3 (hand-off §G): one W-4 in the polite region; activeElement never the body (R-4)"]
    return fr, k.frame_block(F_NEAR, lines, waits=())


def frame_row() -> tuple[k.Node, tuple[str, list[str]]]:
    before = k.positions()
    gone = before[2]
    after = [p for p in before if p.key != gone.key]
    i = before.index(gone)
    nxt = after[i] if i < len(after) else (after[i - 1] if after else None)
    assert nxt is not None
    say = k.w("W-5", gone.key, nxt.key)
    px, py, _pw, _ph = k.GEO["positions"]
    ov = [k.callout("W-5", ["A position closed; focus to the next row in the current sort:", f'"{say}" (once)'],
                    px + 140, py - 120, 340)]
    fr = k.workspace_window(F_ROW, bodies(positions=k.positions_table(after, focus=nxt.key)),
                            focus_panel="positions", overlays=ov, note=f"{gone.key} closed; focus on {nxt.key}")
    lines = [f"§8 L{L8} row 'A position closes': the next row in the current sort, else the previous, else the "
             "grid's empty-state stop; W-5 once (R-4)",
             f"Drawn: sort = symbol, account, side; before: {len(before)} rows, focus on {gone.key} (row {i + 1}); "
             f"after: {len(after)} rows, focus on {nxt.key}",
             f"Identity = the position key (account, symbol, side) (§6.2 L{k.L('### 6.2 Entry and identity')})",
             f"W-5 (§15 L{k.COPY['W-5'].line}, PROPOSED): \"{say}\""]
    return fr, k.frame_block(F_ROW, lines)


def frame_obscured() -> tuple[k.Node, tuple[str, list[str]]]:
    px, py, pw, ph = k.GEO["positions"]
    body_top, body_bot = py + k.HEADER_H, py + ph
    tk_x, tk_y, tk_w, tk_h = px + 200, body_bot - 128, 280, 150  # the floating ticket's frame rect
    overlap = body_bot - tk_y
    e = k.extent("normal")
    ps = k.positions(12)
    focus_i = 9  # the row the user arrows to (1-based)
    row_bot = tk_y - e  # its bottom edge sits the ring's extent above the ticket
    scroll = k.ROW_H + focus_i * k.ROW_H - (row_bot - body_top)
    tbl = k.positions_table(ps, focus=ps[focus_i - 1].key)
    hdr, rows = tbl["kids"][0], tbl["kids"][2]
    body = k.box("grid · scrolled", [dict(rows, x=0, y=k.ROW_H - scroll), dict(hdr, x=0, y=0)],
                 {"fill": k.CANVAS, "clip": True}, w=BODY_W, h=ph - k.HEADER_H,
                 note=f"rows scrolled {scroll} px under the sticky header; end padding {overlap} px")
    ticket = k.vbox("floating order ticket", [k.placeholder("ticket title", 160, 14),
                                             *[k.placeholder(f"ticket field {j}", tk_w - 24, 24) for j in (1, 2)],
                                             k.placeholder("ticket submit", 120, 24)],
                    {"gap": k.STACK_SM, "pad": k.INSET_MD, "fill": k.RAISED, "radius": k.R_CARD,
                     "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR, "strokeAlign": "inner"},
                    w=tk_w, h=tk_h, x=tk_x, y=tk_y, abs=True, note="a floating panel over the grid")
    ov = [ticket, # boards lens M-1: the tag sits on the ticket's body, under its submit button, clear of the focused row
          k.tag(f"floating order ticket · overlaps the grid by {overlap} px", tk_x + 8, tk_y + tk_h - 22),
          k.callout("2.4.11", [f"scroll-padding-bottom = {overlap} + {e} = {overlap + e} px",
                               f"the focused row ends {e} px above the ticket"], px + pw + 40, body_bot - 80, 300)]
    fr = k.workspace_window(F_OBS, bodies(positions=None), focus_panel="positions", overlays=ov,
                            panel_extra={"positions": [dict(body, x=0, y=k.HEADER_H, abs=True)]},
                            note="2.4.11: the focused row is scrolled clear of the floating ticket")
    lines = [f"§7.5 L{k.L('### 7.5 Not obscured')}: scroll-padding = every sticky bar or floating panel overlapping "
             "the container + the ring's outer extent (6 px normal, 9 px thick); a container that cannot scroll that "
             "far adds end padding equal to the overlap (R-11)",
             f"Drawn: the ticket overlaps the grid's container by {overlap} px; scroll-padding-bottom {overlap + e} px;"
             f" row {focus_i} of {len(ps)} ({ps[focus_i - 1].key}) ends at y {row_bot}, {e} px above the ticket top "
             f"{tk_y}; the rows scroll {scroll} px under the sticky header",
             "Not 2.4.12 (AAA, not claimed): fully shown whenever the viewport allows"]
    return fr, k.frame_block(F_OBS, lines, waits=("D04-G3",))


def build(theme: str = "dark") -> None:
    del theme
    fr = [frame_kept(), frame_near(), frame_row(), frame_obscured()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
