"""Board 01 anatomy-redlines: SCR-050/streaming at 200 compact (§2: header, pane, six columns, footer, strip), the
SCR-050/free-scroll inset, the redlines and token map (§2.4); dark, exported again under light (the twin)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 1


def img_name() -> str:
    """The pane's role="img" name, §9.1's example form, derived from the header (trail) and the mark."""
    return k.S("Heatmap, BTCUSDT, last 60 s, mark 64,012.5")


def streaming() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/streaming"
    p = ui.P()
    marks = [ui.acc_name("region name", ui.region_name(p.env)), ui.acc_name('pane role="img" name', img_name())]
    rows = k.rows_window(ui.BODY_H // p.row_h)
    k.derive(f"streaming at 200 compact: {len(rows)} rows {k.price0(rows[-1])}–{k.price0(rows[0])} at a "
             f"{k.STEP:.0f} USDT zoom (bids floor, asks ceil); the mark rule between {k.price0(rows[len(rows) // 2])} "
             f"and {k.price0(rows[len(rows) // 2 - 1])}; stops {[str(x) for x in k.stops()]} BTC (STOP_Q of the "
             f"window's cells); Cum. depth from the touch; Prints at {', '.join(k.price(x) for x in k.PRINTS)}")
    return ui.panel(fid, p, markers=marks), k.frame_block(fid, [
        "Header at 1280 px (§2.1): title · LOCKED echo · depth · env badge · view switch · follow state · ⋯; scale, "
        "trail, cell and ARM sit in ⋯ (drawn open on the redlines frame)",
        "R-1: no heatmap colour under a ladder cell; the pane beside the ladder on one locked price axis (R-2)",
        "R-6: the pane is one focus stop (role=\"img\"), no per-cell DOM; the reveal reads a row's history (board 08)",
        f"Own orders (text first, glyph second) at {', '.join(k.price0(x) for x in (k.SINGLE_SELL_AT, k.AGG_AT, k.SINGLE_BUY_AT))}; "
        f"the position marker W-25 in the Price cell at {k.price0(k.POSITION_AT)} (§15 item 1)",
        "The detector strip is drawn populated on board 08; announced: W-29 polite once on return from stale or "
        "resyncing"])


def free_scroll() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-050/free-scroll"
    p = ui.P(state="free-scroll")
    top = k.rows_window(ui.BODY_H // p.row_h)[0]
    off = int((k.extent_end("ask", p.tier) - top) / k.STEP)
    k.derive(f"free-scroll: the grid scrolled {off} rows up (↑, auto-follow suspended) to the 200 tier's ask end "
             f"{k.price0(k.extent_end('ask', p.tier))} (the scroll extent's top)")
    k.decide("the free-scroll inset is drawn as a full 1280 × 800 window (§0's frame size), so the follow slot and the "
             "rows read together")
    return ui.panel(fid, p, offset=off, markers=[ui.announce(k.W("W-4"))]), k.frame_block(fid, [
        "W-4 in the follow slot; the toggle reads \"Follow\" (aria-pressed); Space, C or Follow resumes (C-4 holds "
        "Space); the trail's drawing pauses (2.2.2), the ladder values still update",
        "M AD-4 satisfied; the motion is E21-D05's"])


def redlines() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = k.REDLINES
    W_ = 1280 - 48
    tok = k.grid_table("§2.4 token map", [k.Col("el", "Element", 260), k.Col("tok", "Token", 760),
                                          k.Col("val", "Value at compact", 212)],
                       [{"el": k.plain(c[0]), "tok": k.plain(c[1]), "val": k.plain(c[2])} for _i, c in
                        k.REDLINE_ROWS], cap=f"§2.4 L{k.REDLINE_ROWS[0][0]}: redlines and the token map")
    slots = k.grid_table("§2.1 header slots", [k.Col("slot", "Slot", 140), k.Col("content", "Content", 420),
                                               k.Col("cmp", "Component", 140), k.Col("notes", "Notes", 532)],
                         [{"slot": k.plain(c[0]), "content": k.plain(c[1]), "cmp": k.plain(c[2]),
                           "notes": k.plain(c[3])} for _i, c in k.HEADER_SLOTS],
                         cap=f"§2.1 L{k.HEADER_SLOTS[0][0]}: the header, left to right")
    rowspec = []
    for dens, h in (("compact", k.COMPACT_ROW), ("comfortable", k.ROW_H)):
        r = k.AGG_AT
        rowspec.append(k.hbox(f"row specimen · {dens}", [
            k.box("row", [k.rect("fill", 680, h, k.CANVAS, x=0, y=0),
                          k.text("price", k.price0(r), k.NUM_SM, k.TEXT_1, x=8, y=(h - 13) // 2),
                          k.rect("rule", 680, 1, k.GRID, x=0, y=h - 1)], w=680, h=h),
            k.rect("redline", 2, h, k.RING),
            k.text("measure", f"{h} px · {k.ui(dens, 'density word of `16`')}", k.CAPTION, k.TEXT_1)],
            {"gap": k.INSET_SM}, h=h))
    over = ui.overflow_menu(ui.P(menu="overflow"))
    spec = k.vbox("specimens", [k.text("label", k.ui("⋯ open: scale, trail, cell and ARM (§2.1's overflow order)",
                                                     "board-marker caption"), k.CAPTION, k.TEXT_2), over,
                                *rowspec], {"gap": k.STACK_SM}, w=W_)
    return k.marker_frame(fid, [tok, slots, spec], 1280), k.frame_block(fid, [
        "Rows never below 24 px (`05`:100); the focus ring outside the row box (§9.3)",
        "T2 controls: color.text.tertiary label, color.text.secondary reason, color.surface.raised + "
        "color.border.default (R-3); never color.text.disabled nor opacity.disabled"])


if __name__ == "__main__":
    ui.run(NN, [streaming(), free_scroll(), redlines()], 2)
