"""Board 06 `E12-D07 / 06 chart-type-cells` (§0; §4; hand-off §H): chart-type/baseline, chart-type/delta-volume,
chart-type/equi-volume (dark)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pair1_helpers import (capped, d06, e11, k, median_denom, name_line, rowindex, rows_that_fit, sl,  # noqa: E402
                           time_loaded, write_all)

NN = 6
W = k.dock_w("strip")
INNER = W - 16
TLOADED = time_loaded()
VLOADED = k.series("volume")
KEYS = e11("| `Ctrl+Home` / `Ctrl+End`")
ANN = e11("**Table announcements (polite")
ROW4 = sl("`vs base` (A):")


def window_rows(loaded, mode, start, **capkw):
    cap0 = k.caption_text(loaded[start:start + 20], mode, loaded=len(loaded), **capkw)
    sel = loaded[start:start + rows_that_fit(cap0, W)]
    return sel, k.caption_text(sel, mode, loaded=len(loaded), **capkw)


def frame_baseline():
    fid, mode = k.BOARDS[NN].frames[0], "time"
    cols = k.shown_columns(mode, auto=True, chart="baseline")  # + `vs base` (A)
    i0 = next(i for i, b in enumerate(TLOADED) if k.hhmm(b.t) == "11:00" and b.gen == 2)
    sel, cap = window_rows(TLOADED, mode, i0)
    base = sel[0].c  # D06:163 B = the first visible bar's close
    focus = next(b for b in sel[len(sel) // 2:] if round(b.c - base, 6) > 0)
    rows = [k.bar_row(b, cols, mode, i + 1, focused=b is focus, base=base, cvd=k.cvd_of(TLOADED, b))
            for i, b in enumerate(sel)]
    t = k.table(rows, w=W, h=k.table_room(), caption_chars=cap, header=k.header_row(cols, mode),
                footer=k.footer_row(INNER))
    fr = k.window(fid, k.panel(mode, t, w=W, chart="Baseline"))
    ri, rn = rowindex(TLOADED, focus)
    diff = k.f_signed(focus.c - base, "{:,.1f}")[1:]
    vs_name = f"above {k.f_price(base)} by {diff}"
    blk = k.frame_block(
        fid, mode=mode, cols=cols, chart="baseline",
        state=f"chart-type/baseline: the time set plus `vs base` (A), c − B, signed (§4 {ROW4}); B = "
              f"{k.f_price(base)}, the first visible bar's close ({d06('- **Base B:**')}); no other cell added",
        row_header_form=name_line(focus, mode, f"its `vs base` cell “{k.cell('vs base', focus, mode, base=base)}” "
                                               f"is named “{vs_name}” (§4's form; {d06('above base 64,100 by 132')})"),
        keyboard=f"Alt+T opened the table in place on the cursor bar's row; ↑ / ↓ origin table ({KEYS})",
        announcement=f"“Data table, row {ri:,} of {rn:,}” ({ANN})", tokens=k.frame_tokens(fr),
        extra=[f"Dashes: `state` — on every closed row (§6 {sl('| none of the above')})"])
    info = f"`{k.frame_name(fid)}`: time, Baseline, B {k.f_price(base)}, {len(sel)} rows; §4 {ROW4}, {d06('- **Base B:**')}"
    return fr, blk, info, vs_name


def frame_delta_volume():
    fid, mode = k.BOARDS[NN].frames[1], "volume"
    cols = k.shown_columns(mode, auto=True, chart="delta-volume")  # P + A (close time, duration) + buy, sell
    sel, cap = window_rows(VLOADED, mode, k.at(mode, "10:40"), durations=True)
    focus = sel[len(sel) // 2]
    rows = [k.bar_row(b, cols, mode, i + 1, focused=b is focus, cvd=k.cvd_of(VLOADED, b)) for i, b in enumerate(sel)]
    t = k.table(rows, w=W, h=k.table_room(), caption_chars=cap, header=k.header_row(cols, mode),
                footer=k.footer_row(INNER))
    fr = k.window(fid, k.panel(mode, t, w=W, chart="Delta-volume"))
    buy, sell = k.cell("buy", focus, mode), k.cell("sell", focus, mode)
    blk = k.frame_block(
        fid, mode=mode, cols=cols, chart="delta-volume",
        state=f"chart-type/delta-volume: the volume set (P), its auto columns close time and duration (the panel is "
              f"wider than {k.set_width(mode, 'PA'):,} CSS px, §5 {sl('WIDTH:volume.auto')}), plus `buy` = (v + delta) ÷ 2 "
              f"and `sell` = (v − delta) ÷ 2 (A; §4 {sl('`buy`, `sell` (A); the delta mode')}); no other cell added",
        row_header_form=name_line(focus, mode, f"buy {buy}, sell {sell} (the mirror's “delta … (buy …, sell …)”, "
                                               f"{d06('| Delta-volume, delta bars')})"),
        keyboard=f"Alt+T opened the table in place on the cursor bar's row; ↑ / ↓ origin table ({KEYS})",
        announcement="“Data table, row {:,} of {:,}” ({}; separator rows counted, §7.2)".format(
            *rowindex(VLOADED, focus), ANN),
        copy_keys=("W-10", "W-12"), tokens=k.frame_tokens(fr),
        extra=[f"Caption clauses (§7.4 {sl('### 7.4')}): W-10, W-12, “durations as h:mm:ss”",
               f"Dashes: `state` — on closed rows; close time / duration — only on a forming row (none in view)"])
    info = f"`{k.frame_name(fid)}`: Vol 50 BTC, Delta-volume, {len(sel)} rows + buy, sell; §4, W-10, W-12"
    return fr, blk, info


def frame_equi():
    fid, mode = k.BOARDS[NN].frames[2], "time"
    cols = k.shown_columns(mode)  # equi-volume adds no column: `state` widens to 12 characters (§5)
    denom = median_denom(TLOADED)
    i0 = next(i for i, b in enumerate(TLOADED) if k.hhmm(b.t) == "10:12" and b.gen == 2)
    sel0, _cap = window_rows(TLOADED, mode, i0)
    sel = [k.tag(b, "width capped") if capped(b, denom) else b for b in sel0]
    capd = [b for b in sel if b.state == "width capped"]
    if len(capd) != 1:
        raise RuntimeError(f"expected one capped row in view, got {len(capd)}")
    focus = capd[0]
    cap = k.caption_text(sel, mode, loaded=len(TLOADED))
    rows = [k.bar_row(b, cols, mode, i + 1, focused=b is focus, equi=True, cvd=k.cvd_of(TLOADED, b))
            for i, b in enumerate(sel)]
    t = k.table(rows, w=W, h=k.table_room(), caption_chars=cap, header=k.header_row(cols, mode, equi=True),
                footer=k.footer_row(INNER))
    fr = k.window(fid, k.panel(mode, t, w=W, chart="Equi-volume"))
    r = focus.v / denom
    ri, rn = rowindex(TLOADED, sel0[sel.index(focus)])
    nm = f"width capped ({r:.1f} × median)"
    blk = k.frame_block(
        fid, mode=mode, cols=cols, chart="equi-volume",
        state=f"chart-type/equi-volume: the time set with `state` widened to 12 characters ({k.set_width(mode, equi=True)}"
              f" CSS px, §5 {sl('WIDTH:equi.px')}); the one bar in view drawn at the cap reads `width capped` (§4 "
              f"{sl('the `state` word `width capped` (§6)')}; §6 {sl('equi-volume drew the bar at the cap')}); the "
              f"others —; no column added",
        row_header_form=name_line(focus, mode, f"`state` adds “{nm}” ({d06('- **Cap:**')}: N = r to one decimal; r "
                                               f"= v ÷ median v over the loaded series, {d06('r = x / max(median x')})"),
        keyboard=f"Alt+T opened the table in place on the cursor bar's row (the capped bar); ↑ / ↓ origin table "
                 f"({KEYS})",
        announcement=f"“Data table, row {ri:,} of {rn:,}” ({ANN})", tokens=k.frame_tokens(fr),
        extra=[f"Cap rule: drawn at the cap when roundHalfUp(14 r) > 48 ({d06('- w0 = clamp(')}); in view only "
               f"{k.hhmm(focus.t)} (r = {r:.1f}) qualifies"])
    info = f"`{k.frame_name(fid)}`: time, Equi-volume, `state` 12 ch, {k.hhmm(focus.t)} `width capped`; §4, §5, §6"
    return fr, blk, info, nm


def main() -> None:
    f1, b1, i1, vs_name = frame_baseline()
    f2, b2, i2 = frame_delta_volume()
    f3, b3, i3, cap_name = frame_equi()
    board_lines = [
        f"§4 {sl('## 4. Chart-type cells')}: the table keeps the mode's set under every chart type and adds only the "
        f"cells D06's mirror rows add",
        f"Data: frames 1 and 3 the loaded 1m series ({len(TLOADED)} trade-built bars, as board 01); frame 2 the "
        f"Vol 50 BTC series ({len(VLOADED)} bars)",
        f"Owner walkthrough (hand-off §E L{k.find_line('Board 06:', k.HANDOFF_LINES)}): “baseline, delta-volume and "
        f"equi-volume add their cells and nothing else”"]
    notes = {
        "live_checks": [
            "frame 1: the header row's last value cell reads 'vs base' and every 'vs base' cell is signed (+ / −)",
            "frame 2: read back the header words in order: time, open, high, low, close, volume, delta, buy, sell, "
            "state, close time, duration; the focused row's buy + sell equals its volume",
            f"frame 3: the 'state' header cell is 95 px wide (12 characters) and the focused row's state reads "
            f"'width capped'; ring 2 px color.focus.ring",
            "every frame: no body row is cut at the table's bottom edge after relayout (whole 24 px rows)"],
        "spec_gaps": [
            f"§4's baseline cell name “above 64,100 by 132” vs D06's summary “above base 64,100 by 132” "
            f"({d06('above base 64,100 by 132')}): the cell's name takes §4's form (“{vs_name}”); the below form "
            f"(“below … by …”) is not written in either and is not drawn (the focused row is above B)",
            "B is not printed in the table (no caption clause in §7.4 names it); it is in the cell names and on the "
            "chart's base tag only",
            f"§6's name “width capped (N × median)” leaves N to the data (ruling P-3); the frame shows the computed "
            f"N: “{cap_name}”",
            f"CVD: E11-D04 D3 rejoins CVD at ≥ 708 CSS px but §3.1 tiers it E; the board draws §3.1's set (as board 01)",
            f"`vs base` width: §3.1 / §5 give none; the kit reserves 9 characters (build notes A-9)"],
        "deviations": []}
    summary = (f"Board 06 of ten (§0 {sl('| 06  |')}): {k.BOARDS[NN].draws}. Three 1280 × 800 windows, one chart "
               f"panel each (RightRail strip, dock 1,168 CSS px), compact density, dark.")
    paths = write_all(NN, [f1, f2, f3], [b1, b2, b3], board_lines=board_lines, notes=notes, summary=summary,
                      frames_info=[i1, i2, i3])
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
