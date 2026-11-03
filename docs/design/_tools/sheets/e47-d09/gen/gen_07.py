"""E47-D09 / 07 cheatsheet: SCR-013 deltas on E10-D03's chassis — search by name and by key, the remap mark, the
nine contexts, no match (§9; AC4 traced on positions.close_all)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
from common import k  # noqa: E402

NN = 7
S9 = k.L("## 9. SCR-013 hotkey cheatsheet")
DLG_W = 880  # kit choice (no source gives SCR-013's width at 1280; two columns of 400 + gaps)
COL_W = (DLG_W - 2 * 24 - 16) // 2  # 400
COLS = (k.Col("action", "Action", COL_W - 184), k.Col("keys", "Keys", 184))
VIS_H = 520  # the dialog body's visible height (it scrolls; E10-D03's 125 % inset stands)
RX = k.FRAME_W - k.RIGHT_W + 6
RW = k.RIGHT_W - 12
TITLE = "Keyboard shortcuts"  # D03E10:285 (the shipped Cheatsheet.tsx heading)


def ctx_table(ctx: str, cmds: list[k.Cmd]) -> c.Node:
    rows = [k.table_row(COLS, {"action": cm.label, "keys": c.binding_cell(cm.id)}, f"row {cm.id}", i, h=None)
            for i, cm in enumerate(cmds, 1)]
    hd = k.header_row(COLS)
    hd = dict(hd, h=k.ROW_H, kids=[dict(x, h=k.ROW_H) for x in hd["kids"]])
    return k.table(f"table · {ctx}", ctx, hd, rows, note=f"<table> with <caption>{ctx}</caption>")


def columns(cmds: list[k.Cmd]) -> tuple[c.Node, list[str]]:
    """The contexts in cheatsheetContexts order, split into two columns at the row count's midpoint."""
    groups = [(x, [cm for cm in cmds if cm.context == x]) for x in k.CONTEXTS]
    groups = [(x, g) for x, g in groups if g]
    total, run, split = sum(len(g) for _x, g in groups), 0, len(groups)
    for i, (_x, g) in enumerate(groups):
        if run + len(g) / 2 > total / 2:
            split = i
            break
        run += len(g)
    split = max(1, split) if len(groups) > 1 else 1
    cols = [k.vbox(f"column {j + 1}", [ctx_table(x, g) for x, g in part], {"gap": k.STACK_LG}, w=COL_W)
            for j, part in enumerate((groups[:split], groups[split:])) if part]
    return k.hbox("columns", cols, {"gap": k.INSET_LG, "align": "start"}), [x for x, _g in groups]


def sheet(q: str, cmds: list[k.Cmd], *, empty: str | None = None, scroll: int = 0) -> c.Node:
    iw = DLG_W - 48
    srch = k.hbox("CMP-054 search", [k.icon("glyph", "search", k.TEXT_2),
                                     k.text("value", q or "Filter", k.BODY, k.TEXT_1 if q else k.TEXT_2)],
                  {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.CANVAS, "radius": k.R_CONTROL,
                   "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=iw - 12, h=k.CONTROL_H + 8)
    head = k.hbox("head", [k.text("h2", TITLE, k.HEADING_MD, k.TEXT_1), k.button("Close", "ghost")],
                  {"justify": "space-between"}, w=iw, h=k.CONTROL_H + 4)
    if empty:
        body: c.Node = k.vbox("no match", [k.text("W-10", empty, k.BODY, k.TEXT_1)], {"padY": k.INSET_MD}, w=iw)
    else:
        cols, _names = columns(cmds)
        body = k.box("body · scrolls", [dict(cols, x=0, y=-scroll)], {"clip": True}, w=iw,
                     h=min(VIS_H, round(k.est_height(cols))), note="the body scrolls; the head and foot stay")
    foot = k.hbox("foot", [k.button("Customise…", "secondary")], {"justify": "end"}, w=iw, h=k.CONTROL_H + 4)
    return k.vbox("CMP-094 hotkey overlay", [head, k.focus_ring(srch), body, foot],
                  {"gap": k.STACK_MD, "pad": k.DIALOG_PAD, "fill": k.OVERLAY, "radius": k.R_DIALOG,
                   "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=DLG_W,
                  note='role="dialog" aria-modal="true" (D09-C11); one captioned table per context')


def window(fid: str, sh: c.Node, extra: list[c.Node], note: str) -> c.Node:
    ovl, _r = k.modal(sh, x=48, y=k.TOP_H + 8)
    return k.workspace_window(fid, {}, overlays=[ovl, *extra], note=note)


def common_lines() -> list[str]:
    return [f"§9 L{S9 + 2}: E10-D03 §6.2's cheatsheet stands (D03E10:285): Ctrl+/ (global.cheatsheet, "
            f"KMAP:{k.kmap_line('global.cheatsheet')}; {k.crow('D09-C1')}), one captioned table per context, "
            "Customise… to SCR-113; deltas only",
            f"Modal, as shipped and as `15` says ({k.crow('D09-C11')}); focus in the search on open (E47-D04 board 06)"]


def w23(n: int) -> str:
    k.spec_gap("W-23 \"{n} shortcuts match\" has no singular form: a one-row result is drawn as the deck gives it "
               "(\"1 shortcuts match\"); the words are E47-D07's (#1306)")
    return k.w("W-23", n)


def frame_search(state: str, q: str) -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(NN, state)
    hits = k.search(q)
    assert [h.id for h in hits] == ["positions.close_all"], hits
    sh = sheet(q, hits)
    kq = k.keys_query(q)
    ov = [k.callout("count", ["Once per settled query (polite; CMP-059's settle):", f"“{w23(len(hits))}”",
                              ("Parsed as keys: " + kq + " matches the binding") if kq else
                              "Plain text matches the action's name"], RX, 120, RW)]
    fr = window(fid, sh, ov, f"Ctrl+/, then \"{q}\"")
    by = "by key" if kq else "by name"
    blk = [*common_lines(),
           f"§9 L{k.L('- **Search (K-9).**', start=S9)}: a CMP-054 SearchBox heads the dialog and filters {by}"
           + (f": \"{q}\" parses as keys ({kq}) and matches the binding" if kq else f": \"{q}\" matches the label"),
           f"§9 L{k.L('- **Remaps.**', start=S9)}: AC4 traced on positions.close_all (KMAP:"
           f"{k.kmap_line('positions.close_all')}) remapped {k.CMD['positions.close_all'].default} → "
           f"{k.binding('positions.close_all')}: the row shows the binding · {k.w('W-11')}; matches keep their "
           "context caption (Positions)",
           f"{k.wcite('W-23')}; {k.krule('K-9')}; hand-off §G QA-3"]
    return fr, k.frame_block(fid, blk, keyboard="Ctrl+/ opens with focus in the search; type; Tab to the tables; Esc "
                                                "closes and restores", waits=["D09-G1"] if not kq else [])


def frame_remapped() -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(NN, "cheatsheet/remapped")
    cmds = list(k.COMMANDS)
    cols, names = columns(cmds)
    col2 = cols["kids"][1]["kids"]
    scroll = round(k.est_height(col2[0]) + k.PX[k.STACK_LG])  # scrolled so column 2 starts at Positions
    sh = sheet("", cmds, scroll=scroll)
    rem = [cid for cid in k.PROFILE if k.remapped(cid)]
    ov = [k.callout("remaps", ["The profile's remaps, each with \"remapped\":",
                               *[f"{k.CMD[x].label}: {k.CMD[x].default} → {k.binding(x)}" for x in rem],
                               f"Unbound: {k.CMD['dom.centre_mark'].label} reads \"{k.w('W-7')}\" (DOM, column 1)"], RX, 120, RW)]
    fr = window(fid, sh, ov, f"Ctrl+/ with no query, the body scrolled {scroll} px: column 2 at Positions")
    blk = [*common_lines(),
           f"§9 L{k.L('- **Grouping.**', start=S9)}: the nine shipped contexts in cheatsheetContexts order "
           f"(KMAP:5-15): {', '.join(names)} ({k.crow('D09-C10')}); column 1 holds the first "
           "five, column 2 the rest (split at the row midpoint); the body scrolls, the head and foot stay; drawn "
           f"scrolled {scroll} px so Positions and Replay (two remaps) are in view",
           f"§9 L{k.L('- **Remaps.**', start=S9)}: a remapped row shows the current binding with W-11 beside it "
           f"({len(rem)} remaps drawn: {', '.join(rem)}; QA-3)",
           f"{k.wcite('W-11')}; {k.wcite('W-7')}; the printable and 125 % variants stand (E10-D03 board 07; not drawn)"]
    return fr, k.frame_block(fid, blk, keyboard="Tab from the search to the tables; arrows within; Esc closes")


def frame_no_match() -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(NN, "cheatsheet/no-match")
    q = "flatten"
    assert not k.search(q)
    s10 = k.w("W-10", q)
    sh = sheet(q, [], empty=s10)
    ov = [k.callout("none", ["Shown, and said once (polite):", f"“{s10}”",
                             f"No flatten-all command is registered ({k.crow('D09-C2')}; D09-G1)"], RX, 120, RW)]
    fr = window(fid, sh, ov, f"Ctrl+/, then \"{q}\": nothing matches")
    blk = [*common_lines(),
           f"§9 L{k.L('- **Search (K-9).**', start=S9)}: no match shows W-10",
           f"{k.wcite('W-10')}"]
    return fr, k.frame_block(fid, blk, keyboard="type; Esc closes and restores", waits=["D09-G1"])


def build() -> None:
    fr = [frame_search("cheatsheet/search-name", "close all"), frame_search("cheatsheet/search-key", "ctrl shift f"),
          frame_remapped(), frame_no_match()]
    k.reading("SCR-013's dialog is drawn 880 px wide at the frame's left (no source gives its width); the "
              "placeholder of the search is \"Filter\" (E10-D03 §6.2 names Filter, CMP-054)")
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()
