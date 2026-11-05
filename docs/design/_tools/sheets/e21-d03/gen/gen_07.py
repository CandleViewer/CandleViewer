"""Board 07 validation-clamp: SCR-051/validation-error and /trail-clamped (§9), with the W-11 / W-12 specimens."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 7


def rng(field: str) -> tuple[int, int]:
    c, _ln = k.RANGES[field]
    m = re.match(r"(\d+)–(\d+)", k.plain(c[1]))
    return int(m.group(1)), int(m.group(2))  # type: ignore[union-attr]


TRAIL_MIN, TRAIL_MAX = rng("Trail length")
ROW_MIN, ROW_MAX = rng("Row height")


def error() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/validation-error"
    w10 = k.W("W-10", min=TRAIL_MIN, max=TRAIL_MAX)
    bad = str(TRAIL_MIN // 2)
    label = k.S("Trail length (s)")
    d = ui.Dlg(trail=bad, trail_msg=("error", w10), focus="trail",
               extra=[ui.announce(f"{label}: {w10}", how="on blur, once through the status node (R-5)")])
    k.derive(f"the invalid trail {bad} s = half the minimum {TRAIL_MIN} s (§9.1)")
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        f"Trail length {bad} s, below {TRAIL_MIN}–{TRAIL_MAX} s (`window_seconds`, `23`:2452; A-7): aria-invalid=\"true\", "
        "CMP-027 inline under the field (live off) linked by aria-describedby",
        "On blur the error is written once through the status node, prefixed with the field's label; at Save focus "
        "moves to the first field in error, its tab selected, and the error is read there; a tab switch validates "
        "nothing",
        "The copy takes {min} / {max} as fills, so E21-S04 #704 can re-range the trail without a copy change"])


def clamped() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-051/trail-clamped"
    mx = k.clamp_max(500)
    w13 = k.W("W-13", max=mx, tier=500)
    k.derive(f"clamp at 500: {k.CLAMP_CELLS:,} cells ÷ (2 × 500 levels × {k.AUTO_COLS_PER_S} column/s, Columns Auto "
             f"1 s) = {mx} s; the typed {TRAIL_MAX} s is clamped — kit model, {k.ILLUSTRATIVE} (the maximum is G-4's)")
    mark_x = ui.DLG_X + ui.DLG_W + 8  # beside the dialog: the marker wraps to the 136 px left before the frame's edge
    mark = dict(ui.illustrative(k.WIN_W - mark_x - 16), x=mark_x, y=ui.DLG_Y + 120)
    d = ui.Dlg(tier=500, w4=True, trail=str(mx), trail_msg=("warning", w13), focus="trail",
               extra=[ui.announce(w13), mark])
    return ui.dialog_window(fid, d), k.frame_block(fid, [
        f"500 picked and {TRAIL_MAX} s typed: on blur the field takes {{max}} = {mx} s and W-13 shows under it as a "
        "CMP-027 warning, not an error: Save stays possible (§9.2, `11`:2044–`11`:2045)",
        f"The maximum comes from E21-S04 #704's model (G-4); the board's {mx} s is {k.ILLUSTRATIVE}"])


def specimens() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = k.SPEC07
    w11 = k.W("W-11", min=ROW_MIN, max=ROW_MAX)
    w12 = k.W("W-12")
    d = ui.Dlg(tab="Trading", presets=("", "", "", ""), presets_msg=w12)
    rh = ui.field(k.S("Row height (px)"), "18", w_input=72, msg=("error", w11), name="field · Row height")
    fr = k.marker_frame(fid, [
        k.text("lead", k.ui("Ladder tab: Row height 18 px (the catalogue's old default)", "board-marker caption"),
               k.LABEL, k.TEXT_2), rh,
        k.text("lead 2", k.ui("Trading tab: every quantity preset cleared", "board-marker caption"), k.LABEL, k.TEXT_2),
        ui.presets_row(d)], ui.LEFT_W + 48)
    return fr, k.frame_block(fid, [
        f"W-11 with {{min}} {ROW_MIN}, {{max}} {ROW_MAX} (§9.1: `14`:1248 narrowed by C-2); W-12 at least one preset "
        "(`14`:1248); drawn at full scale as they stand in their tabs"])


if __name__ == "__main__":
    ui.run(NN, [error(), clamped(), specimens()], 2, board_lines=[
        "Owner walkthrough item 7 (§18): each error names its fix (H-6)"])
