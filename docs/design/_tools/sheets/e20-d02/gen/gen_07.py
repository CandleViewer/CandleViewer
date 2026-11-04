"""Board 07 scr033-catalogue-reorder: SCR-033/catalogue, -reorder-keyboard, -row-menu, -thresholds (§6.1-§6.4,
§6.6; AC 2)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 7
MW = 248  # marker width beside the dialog
LIST_Y = ui.HEAD_DLG + ui.TOOL_H


def rows(enabled: tuple[str, ...] = ui.DEFAULT, **per: dict) -> list[ui.R]:
    return [ui.R(lab, on=lab in enabled, **per.get(lab, {})) for lab in ui.list_order(enabled)]


def catalogue() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-033/catalogue"
    rs = rows(**{"Delta": {"focus": "row"}})
    n = len(ui.DEFAULT)
    ann = ui.announce(k.W("W-22", n=n), how="polite, once, on Apply", w=MW)
    return ui.dialog(fid, rs, markers=[ann]), k.frame_block(fid, [
        f"CMP-043 Dialog, size md, title \"{k.S('Deep Stats rows')}\"; a CMP-056 list of the {len(k.CATALOGUE)} rows "
        f"in the user's order, enabled rows first, the rest in 24 §7 order; the body scrolls (§6.1)",
        "Per row: the drag handle (pointer only, not a stop), the enable checkbox with the §7 label, Format (W-21, "
        "PROPOSED, D02-G3), Sparkline (PROPOSED, D02-A4), Threshold (aria-expanded; absent on flag and price rows: "
        "\"No threshold\"), ⋯; every target ≥ 24 × 24 (2.5.8)",
        "SCR-033's Big-trade count and Imbalance count are not drawn (no §7 descriptor; MEMO G2, D02-C5); CMP-031 "
        "is not drawn (colour is E20-D03's)",
        "Not drawn (§0 lists no open-menu frame): the Format menu's W-21 items, \"Decimals\" and \"Abbreviate (1.2k)\" (§6.2, PROPOSED, D02-G3); the text is binding",
        "On open, focus lands on the first enabled row's checkbox (drawn); the list is one Tab stop with a roving row",
        f"Apply closes the dialog, applies everything, announces W-22 once and returns focus to the gear; "
        f"chart.deepstats_rows_changed with {{rows}} fires on Apply only, never per toggle (14:875; §6.6)",
        "Cancel and Esc discard every change"])


def reorder() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-033/reorder-keyboard"
    moved = "Cumulative Delta"
    order = ("Delta", "Delta %", "Total Volume", moved, "# Trades")  # after one Alt+↑ from position 5
    rs = rows(order, **{moved: {"hint": True, "focus": "row"}})
    words = k.W("W-15", row=moved, n=order.index(moved) + 1, total=len(order))
    return ui.dialog(fid, rs, markers=[ui.announce(words, how="polite, one live region in the dialog, replaced "
                                                                  "never queued, ≤ 1 a second", w=MW)]), \
        k.frame_block(fid, [
            f"Alt+↑ / Alt+↓ on the focused row (its checkbox) move it one position (E47-D09:173, DE-13; 14:871): "
            f"{moved} after one Alt+↑ from position {len(order)}",
            "The focused row shows the hint chip right of its label; the keys are ignored on Format, Threshold, ⋯ "
            "and the threshold select and field (the row menu is the path there)",
            "The moved row keeps focus: the ring (E47-D04:229) moves with the row, never on the handle alone; the row "
            "is scrolled clear of the sticky toolbar and footer (2.4.11)",
            "{total} counts the enabled rows (E20.json:394's example); the list reorders at once, the strip changes "
            "on Apply (D02-F2)"])


def row_menu() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-033/row-menu"
    first, last = k.W("W-16", 0), k.W("W-16", 1)
    up = ui.t2_box(k.S("Move up"), name="menuitem Move up", typo=k.BODY, h=28, w=184, focused=True, rendering="2b",
                   note='T2 2b (§1.4): menu item, aria-disabled="true", arrow-reachable; the reason node visually '
                        'hidden, echoed by CMP-016 on hover and focus')
    down = ui.item(k.S("Move down"), 184)
    menu = ui.menu_at(LIST_Y, [up, down])
    tip = ui.card("CMP-016 tooltip echo", [ui.reason(first, 120, "T2 reason (W-16, echoed)")], 136,
                  "the tooltip duplicates the reason; never the only copy", pad=k.INSET_SM)
    tip = dict(tip, x=menu["x"] - 136 - 8, y=menu["y"] + 4)
    rs = rows(**{"Delta": {"focus": None}})
    return ui.dialog(fid, rs, extra=[menu, tip], markers=[
        ui.acc_name("Move up's description (visually hidden)", first, w=MW)]), k.frame_block(fid, [
        "The second path: the row menu's Move up / Move down on ⋯ (E47-D09:140); CMP-056's per-row \"Move {row} up "
        "/ down\" buttons are not drawn (D02-F1; MEMO A9)",
        f"At the range ends Move up or Move down is T2 2b: \"{first}\" on the first row (drawn), \"{last}\" on the "
        f"last (§1.4); Enter or Space changes nothing and re-shows the reason with one polite announcement",
        "After a row-menu move focus returns to the row's menu button"])


def thresholds() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-033/thresholds"
    rs = rows(**{"Delta": {"expanded": (k.S("abs >"), f"{k.DELTA_BOUND}")},
                 "Delta %": {"expanded": (k.S("abs >"), f"{k.PCT_BOUND}"), "focus": "field"}})
    return ui.dialog(fid, rs, set_words=k.S("Set: Global"), markers=[ui.note_marker(k.ui(
        f"{k.DELTA_BOUND} BTC: example, never a recommendation (MEMO OQ-3)", "board-marker note"), w=MW)]), \
        k.frame_block(fid, [
            "Under a row whose Threshold toggle is expanded: a comparison select (>, <, >=, <=, abs >; E20.json:420), "
            "abs > by default on signed rows (MEMO AD-6), and a bound field",
            f"Delta % (a percent row): 0–100 % (14:870), the story's {k.PCT_BOUND} %; Delta (a unit row): an "
            f"absolute field in BTC, its bounds E20-S03's (D02-A3); flag and price rows show \"No threshold\"",
            "The set selector above the list (PROPOSED): \"Set: Global\" or \"Set: ETHUSDT (this symbol)\", naming "
            "what the legend will say (W-1, W-2); a symbol with no set falls back to the default (E20.json:420)",
            "The entry opens only on the toggle, never on focus: tabbing never shifts the rows below (§6.2)"])


if __name__ == "__main__":
    ui.run(NN, [catalogue(), reorder(), row_menu(), thresholds()], 2)
