"""Board 01 `E12-D07 / 01 time-bars` (§0; hand-off §H): time/default, time/forming-last, time/sorted-delta (dark)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pair1_helpers import d06, e11, k, name_line, rowindex, rows_that_fit, sl, time_loaded, write_all  # noqa: E402

NN, MODE = 1, "time"
W = k.dock_w("strip")  # 1,168: the one chart panel with the RightRail as its 48 px strip
INNER = W - 16
LOADED = time_loaded()
COLS = k.shown_columns(MODE)  # §3.1 time: P set only (time has no A column)
FORMING_DESC = "forming bar, values change until close"
KEYS = e11("| `Ctrl+Home` / `Ctrl+End`")
ANN = e11("**Table announcements (polite")


def cvd(b):
    return k.cvd_of(LOADED, b)


def frame_default():
    fid = k.BOARDS[NN].frames[0]
    i0 = next(i for i, b in enumerate(LOADED) if k.hhmm(b.t) == "10:10" and b.gen == 2)
    cap = k.caption_text(LOADED[i0:i0 + 20], MODE, loaded=len(LOADED))
    n = rows_that_fit(cap, W)
    sel = LOADED[i0:i0 + n]
    cap = k.caption_text(sel, MODE, loaded=len(LOADED))
    focus = sel[len(sel) // 2]
    rows = [k.bar_row(b, COLS, MODE, i + 1, focused=b is focus, cvd=cvd(b)) for i, b in enumerate(sel)]
    t = k.table(rows, w=W, h=k.table_room(), caption_chars=cap, header=k.header_row(COLS, MODE),
                footer=k.footer_row(INNER))
    fr = k.window(fid, k.panel(MODE, t, w=W))
    ri, rn = rowindex(LOADED, focus)
    blk = k.frame_block(
        fid, mode=MODE, cols=COLS,
        state=f"time/default: the time-mode set (§3.1 {sl('| time (row header) |')}), {len(sel)} closed 1m rows "
              f"{k.hhmm(sel[0].t)}–{k.hhmm(sel[-1].t)}, `state` — on every row (§6 {sl('| none of the above')}); the "
              f"caption with its units (§7.4 {sl('### 7.4')}; {e11('Header labels are lower-case')})",
        row_header_form=f"§2.1 {sl('### 2.1')}: hh:mm — " + name_line(focus, MODE),
        keyboard=f"Alt+T from the plot opened the table in place, focus on the cursor bar's row "
                 f"({e11('| `Alt+T` from the plot')}); ↑ / ↓ move it, origin table ({KEYS})",
        announcement=f"“Data table, row {ri:,} of {rn:,}” ({ANN}; the separator row counted, §7.2 "
                     f"{sl('### 7.2')})",
        tokens=k.frame_tokens(fr),
        extra=[f"Dashes: `state` — = a closed bar with no §6 word, unmarked (§6 {sl('One lowercase list')})"])
    info = f"`{k.frame_name(fid)}`: {len(sel)} rows, focus {k.hhmm(focus.t)} (row {ri} of {rn}); §3.1, §6, §7.4"
    return fr, blk, info


def frame_forming():
    fid = k.BOARDS[NN].frames[1]
    cap0 = k.caption_text(LOADED[-20:], MODE, loaded=len(LOADED))
    n = rows_that_fit(cap0, W)
    sel = LOADED[-n:]
    cap = k.caption_text(sel, MODE, loaded=len(LOADED))
    focus = sel[-1]
    rows = [k.bar_row(b, COLS, MODE, i + 1, focused=b is focus, cvd=cvd(b)) for i, b in enumerate(sel)]
    t = k.table(rows, w=W, h=k.table_room(), caption_chars=cap, header=k.header_row(COLS, MODE),
                footer=k.footer_row(INNER))
    fr = k.window(fid, k.panel(MODE, t, w=W))
    ri, rn = rowindex(LOADED, focus)
    flat = [b for b in sel if b.state == "no range"]
    blk = k.frame_block(
        fid, mode=MODE, cols=COLS,
        state=f"time/forming-last: following live, the latest rows {k.hhmm(sel[0].t)}–{k.hhmm(sel[-1].t)} with the "
              f"forming row LAST ({e11('the latest row is pinned at the bottom')}); its numbers color.text.secondary, "
              f"`forming` primary (§6 {sl('the bar is open (`confirm: false`)')}; {e11('- **Forming bar**')})",
        row_header_form=name_line(focus, MODE, f"aria-describedby “{FORMING_DESC}”"),
        keyboard=f"Ctrl+End to the last row (latest; resumes follow-live, {KEYS}); the forming row focused, ring "
                 f"2 px color.focus.ring",
        announcement=f"“Data table, row {ri:,} of {rn:,}” ({ANN})",
        tokens=k.frame_tokens(fr),
        extra=[f"Dashes: closed rows `state` —; the forming row's cells keep live values (no — on time bars: §3.1 "
               f"gives time no close time / duration)"]
        + ([f"Data: {k.hhmm(flat[0].t)} is the data's one-print minute, o = h = l = c, so its `state` reads "
            f"`no range` (§6 {sl('open = high = low = close')})"] if flat else []))
    info = f"`{k.frame_name(fid)}`: {len(sel)} rows to {k.hhmm(focus.t)}, the forming row last and focused; §6, D04E11"
    return fr, blk, info, cap


def frame_sorted(chart_caption: str):
    fid = k.BOARDS[NN].frames[2]
    closed = [b for b in LOADED if b.confirm]
    forming = [b for b in LOADED if not b.confirm]
    order = sorted(closed, key=lambda b: (-b.delta, b.t, b.gen, b.index)) + forming  # forming pinned after closed
    chips = k.chip_row(INNER, sort="delta", separators_hidden=True)
    n = rows_that_fit(chart_caption, W, chips=True)
    sel = order[-n:]
    focus = sel[-1]
    rows = [k.bar_row(b, COLS, MODE, i + 1, focused=b is focus, cvd=cvd(b)) for i, b in enumerate(sel)]
    t = k.table(rows, w=W, h=k.table_room(), caption_chars=chart_caption, chips=chips,
                header=k.header_row(COLS, MODE, sort="delta"), footer=k.footer_row(INNER))
    fr = k.window(fid, k.panel(MODE, t, w=W))
    chip = f"Sorted by delta ↓ — not in time order · {k.COPY['W-17'][0]}"
    blk = k.frame_block(
        fid, mode=MODE, cols=COLS,
        state=f"time/sorted-delta: the loaded rows by delta, descending (header arrow, aria-sort=descending); the end "
              f"of the order in view: the {len(sel) - 1} lowest-delta closed rows, then the forming row pinned after "
              f"the closed rows ({e11('- **Forming bar**')}; §11 {sl('the forming row stays last under a value sort')})"
              f"; the separator row of the loaded series hidden while sorted (§7.2 {sl('### 7.2')})",
        row_header_form=name_line(focus, MODE, f"aria-describedby “{FORMING_DESC}”"),
        keyboard=f"→ to the delta header, Enter twice (ascending → descending, {e11('| D8  |')}); Ctrl+End to the "
                 f"last row ({KEYS}): the forming row, focused",
        announcement=f"“Sorted by delta, descending” ({e11('Announcement (polite, once per change)')}), then "
                     f"“Data table, row {len(order):,} of {len(order):,}” (separators hidden: not counted)",
        copy_keys=("W-17",), tokens=k.frame_tokens(fr),
        extra=[f"Chip: “{chip}” + Reset ({e11('- A **sort-status chip**')}; W-17 §13 {sl('| W-17 |')})",
               "Caption: the chart's visible range, unchanged by the sort (as time/forming-last)"])
    info = f"`{k.frame_name(fid)}`: delta ↓, {len(sel)} rows (end of the order), forming row last and focused; W-17"
    return fr, blk, info


def main() -> None:
    f1, b1, i1 = frame_default()
    f2, b2, i2, cap2 = frame_forming()
    f3, b3, i3 = frame_sorted(cap2)
    first, last = LOADED[0], LOADED[-1]
    board_lines = [
        f"Data: one loaded 1m series, {len(LOADED)} trade-built bars {k.date_of(first.t)} {k.hhmm(first.t)} – "
        f"{k.date_of(last.t)} {k.hhmm(last.t)} UTC (generation 1, then 2); no kline coverage over 17:02–09:14, so "
        f"one separator row sits between the generations (§7.1 kline hole with the seam appended)",
        f"Owner walkthrough (hand-off §E L{k.find_line('Board 01:', k.HANDOFF_LINES)}): “the time set reads as "
        f"E11-D04's, with `state` words and the units in the caption”"]
    notes = {
        "live_checks": [
            "frame 1: read back the ring on the 'row .. · focused' node: 2 px color.focus.ring, stroke inner",
            "frame 2: the last child of 'rows' is the focused forming row; its 'state' text binds color.text.primary "
            "and its price cells color.text.secondary",
            "frame 3: 'th · delta' holds the arrow-down icon; 'filter and sort line' sits between the caption and the "
            "header row; the last child of 'rows' is the forming row",
            "every frame: no body row is cut at the table's bottom edge after relayout (whole 24 px rows)"],
        "spec_gaps": [
            f"CVD: E11-D04 D3 ({e11('| D3  |')}) has CVD rejoin automatically at ≥ 708 CSS px; §3.1 "
            f"({sl('| CVD               |')}) tiers it E. The 1,168 px panel is wider than 708, but the board draws "
            f"§3.1's set (the kit's reading for every board); flag for the set's consistency review",
            "sort order of rows whose delta is — : not ruled; avoided here (the loaded series holds trade-built bars "
            "only, so every closed row has a delta)",
            f"the separator row's text for this load (kline hole meeting the 09:15 restart) is §7.1's "
            f"“{k.COPY['W-4'][0]} · {k.COPY['W-1'][0]}”; it is off-screen in all three frames"],
        "deviations": []}
    summary = (f"Board 01 of ten (§0 {sl('| 01  |')}): {k.BOARDS[NN].draws}. Three 1280 × 800 windows, one chart "
               f"panel each (RightRail strip, dock 1,168 CSS px), compact density, dark.")
    paths = write_all(NN, [f1, f2, f3], [b1, b2, b3], board_lines=board_lines, notes=notes, summary=summary,
                      frames_info=[i1, i2, i3])
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
