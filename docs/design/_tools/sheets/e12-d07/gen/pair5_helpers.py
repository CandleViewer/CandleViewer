"""Pair 5 (boards 05 separator-rows and 10 separator-rows-light): the three frame builders, shared by gen_05.py and
gen_10.py (the light twin reuses the base frames with its own fid; same tokens, same data). Uses only the kit's
public API plus one helper: footer_history_start() (E11-D04 §10 "before recorded history": Older disabled with the
reason "History starts here", which the kit's footer_row() does not draw)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e12d07kit as k  # noqa: E402

SHELL_LINES = k._read(k.SHELL)
DAY1 = "2026-10-19"


def L(needle: str) -> int:
    return k.find_line(needle)


def LS(needle: str) -> int:
    return k.find_line(needle, SHELL_LINES)


SEP_L = {"seam": L("| seam "), "gap-non-time": L("| recording gap, non-time"),
         "gap-time": L("| recording gap, time axis"), "kline-hole": L("| kline hole, time axis"),
         "partial-history": L("| partial history"), "built-start": L("| built range start"),
         "lookback": L("| lookback "), "before-history": L("| before recorded history"),
         "loading-older": L("| loading older bars")}
L_MEET = L("Where two meet")
L_72 = L("### 7.2 The band-row form") + 2
L_73 = L("### 7.3 Rebuild")
L_74 = L("### 7.4 Units")
L_E11_OLDER = LS("| **loading older bars**")
L_E11_BEFORE = LS("| **before recorded history**")
CAPTIONS: list[str] = []  # (frame, caption) lines for the .md; the frames draw them
TOKENS: set[str] = set()  # the union of the frames' tokens: listed once in the Board block
TS = "16:40 UTC"  # W-5 / W-6 <ts>: the first order-flow minute / first built bar (generation 1 starts 16:40)


def sep_cite(kind: str) -> str:
    return f"§7.1 L{SEP_L[kind]}"


def _tok(fr: Any) -> list[str]:
    TOKENS.update(k.frame_tokens(fr))
    return ["listed once in the Board block"]


def _cap(fid: str, cap: str, short: str) -> str:
    CAPTIONS.append(f"{k.frame_name(fid)} caption: {cap}")
    return short


def fit_cols(mode: str, w: int) -> list[str]:
    auto = k.row_width(k.shown_columns(mode, auto=True), mode) + 16 <= w
    return k.shown_columns(mode, auto=auto)


def footer_history_start(w: int) -> Any:
    """E11-D04 §10 'before recorded history': the Older control disabled, reason "History starts here"; Export CSV
    disabled as in footer_row()."""
    older = k.hbox("CMP-053 Older (disabled)", [k.icon("lock", "locked", k.TEXT_3, k.ICON_SM),
                                                k.text("label", "Older", k.LABEL, k.TEXT_3)],
                   {"fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR, "radius": k.R_CONTROL,
                    "padX": k.INSET_SM, "gap": k.INSET_XS}, h=k.ROW_H, note="disabled: History starts here")
    exp = k.hbox("CMP-099 Export CSV (disabled)", [k.icon("lock", "locked", k.TEXT_3, k.ICON_SM),
                                                   k.text("label", "Export CSV", k.LABEL, k.TEXT_3)],
                 {"fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR, "radius": k.R_CONTROL,
                  "padX": k.INSET_SM, "gap": k.INSET_XS}, h=k.ROW_H)
    return k.hbox("footer", [older, k.text("reason · older", "History starts here", k.CAPTION, k.TEXT_2), exp,
                             k.text("reason", "Export arrives with E15", k.CAPTION, k.TEXT_2)],
                  {"gap": k.INSET_SM}, w=w, h=k.ROW_H)


def _table(items: list[tuple[str, Any]], bars: list[Any], mode: str, cols: list[str], *, w: int, h: int,
           loaded: int, footer: Any, rebuild: str | None = None, hole: bool = False) -> Any:
    """items: ("bar", Bar, focused) / ("sep", kind, kwargs) in order. Builds rows, caption, header and the table."""
    rows_all = k.series(mode, hole=hole)
    rows = []
    for i, it in enumerate(items, 1):
        if it[0] == "bar":
            b, foc = it[1], it[2]
            cvd = k.cvd_of(rows_all, b) if "CVD" in cols else None
            rows.append(k.bar_row(b, cols, mode, i, focused=foc, cvd=cvd))
        else:
            rows.append(k.sep_row(it[1], cols, mode, **it[2]))
    cap = k.caption_text(bars, mode, loaded=loaded, rebuild=rebuild, durations="duration" in cols)
    return k.table(rows, w=w, h=h, caption_chars=cap, header=k.header_row(cols, mode), footer=footer), cap


def room_rows(mode: str, w: int, h: int, bars: list[Any], loaded: int, rebuild: str | None = None,
              cols: tuple[str, ...] | list[str] = ()) -> int:
    cap = k.caption_text(bars, mode, loaded=loaded, rebuild=rebuild, durations="duration" in cols)
    return k.max_rows(h=h, caption_lines=k.caption_lines(cap, w))


def _fit(build, n0: int) -> Any:
    """Call build(n) from n0 down until the table fits (k.table raises on overflow)."""
    for n in range(n0, -1, -1):
        try:
            return build(n)
        except ValueError as e:
            if "show fewer rows" not in str(e):
                raise
    raise ValueError("nothing fits")


def frame_non_time(fid: str) -> tuple[Any, tuple[str, list[str]]]:
    """separators/non-time: Vol 50 BTC; lookback (W-7 + Load more) -> built range start (W-6 + Build earlier bars)
    -> generation 1's 12 bars -> the recording-gap row with the seam appended (focused) -> generation 2's bars."""
    mode, w = "volume", k.dock_w("strip")
    s = k.series(mode)
    g1 = [b for b in s if b.gen == 1]
    g2 = [b for b in s if b.gen == 2]
    cols = fit_cols(mode, w)

    def build(n: int) -> Any:
        items = [("sep", "lookback", {}), ("sep", "built-start", {"ts": TS})] + [("bar", b, False) for b in g1] + \
                [("sep", "gap-non-time", {"seam_too": True, "focused": True})] + [("bar", b, False) for b in g2[:n]]
        t, cap = _table(items, g1 + g2[:n], mode, cols, w=w, h=k.table_room(), loaded=len(s),
                        footer=k.footer_row(w - 16))
        return t, cap, n

    t, cap, n = _fit(build, 20 - 15)
    fr = k.window(fid, k.panel(mode, t, w=w))
    gap = k.sep_text("gap-non-time", seam_too=True)
    blk = k.frame_block(
        fid, state=f"separators/non-time (§7.1 L{SEP_L['lookback']}, L{SEP_L['built-start']}, "
                   f"L{SEP_L['gap-non-time']}, L{SEP_L['seam']}; order L{L_MEET}; band-row form §7.2 L{L_72})",
        mode=mode, cols=cols,
        row_header_form=f"{k.row_header(g2[0], mode)} — name: {k.row_name(g2[0], mode)}; generation 2 restarts at "
                        f"index 0 and its own bar k of n after the gap row (§2.2 L{L('### 2.2 Non-time bars')})",
        keyboard=f"Alt+T opened the table on the cursor bar's row; ↑ stops on the gap row (a grid row, §7.2 "
                 f"L{L_72}); its accessible name is its text; never selected by Ctrl+A",
        announcement=f"“Data table, row k of N” on entry (D04E11 D2); separator rows are not announced when they "
                     f"arrive (§7.2 L{L_72})",
        copy_keys=("W-1", "W-2", "W-6", "W-7", "W-10", "W-12"), tokens=_tok(fr),
        extra=[f"Rows: W-7 lookback + Load more (L{SEP_L['lookback']}); W-6 + Build earlier bars, <ts> = {TS} "
               f"(L{SEP_L['built-start']}); {len(g1)} generation 1 bars; W-2 gap row with W-1 appended after “·” "
               f"(L{L_MEET}), focused; {n} generation 2 bars",
               _cap(fid, cap, f"Caption: summariseRange() + §7.4 clauses W-10, W-12 (L{L_74})")])
    return fr, blk


def frame_time_axis(fid: str) -> tuple[Any, tuple[str, list[str]]]:
    """separators/time-axis: 1m; two stacked panels of the same series (generation 1 has 22 one-minute bars between
    W-5 and W-3 and a panel holds 20 rows): top = loading-older band, kline rows, W-5 (focused), 16:40; bottom = the
    last generation 1 rows, W-3, the kline rows inside the gap."""
    mode, w = "time", k.dock_w("strip")
    s = k.series(mode)
    i40 = k.at(mode, "16:40", day=DAY1)
    i02 = k.at(mode, "17:02", day=DAY1)
    hs = k.split_h(2)
    cols = fit_cols(mode, w)

    def top(n: int) -> Any:
        kl = s[i40 - n:i40]
        items = [("sep", "loading-older", {})] + [("bar", b, False) for b in kl] + \
                [("sep", "partial-history", {"ts": TS, "focused": True}), ("bar", s[i40], False)]
        t, cap = _table(items, kl + [s[i40]], mode, cols, w=w, h=k.table_room(hs[0]), loaded=len(s) - (i40 - n),
                        footer=k.footer_row(w - 16, older=True))
        return t, cap, n

    def bottom(n: int) -> Any:
        before, inside = s[i02 - n:i02], s[i02:i02 + 2]
        items = [("bar", b, False) for b in before] + [("sep", "gap-time", {})] + [("bar", b, False) for b in inside]
        t, cap = _table(items, before + inside, mode, cols, w=w, h=k.table_room(hs[1]), loaded=loaded[0],
                        footer=k.footer_row(w - 16))
        return t, cap, n

    t1, cap1, n1 = _fit(top, 3)
    loaded = [len(s) - (i40 - n1)]  # the loading-older band sits above the first loaded row
    t2, cap2, n2 = _fit(bottom, 3)
    if n1 < 1 or n2 < 1:
        raise ValueError("time-axis panels too short")
    fr = k.window(fid, [k.panel(mode, t1, w=w, h=hs[0], name="CMP-080 DockPanel (composition) · chart · top"),
                        k.panel(mode, t2, w=w, h=hs[1], name="CMP-080 DockPanel (composition) · chart · bottom")])
    k.copy("W-18")
    k.deviate("separators∕time-axis (boards 05 and 10): two panels of the same 1m series stacked in the dock (CMP-081 4 px "
              "gutter), the top scrolled to the partial-history row and the bottom to the W-3 row; 22 one-minute "
              "bars lie between them and one panel holds 20 rows")
    blk = k.frame_block(
        fid, state=f"separators/time-axis (§7.1 L{SEP_L['loading-older']}, L{SEP_L['partial-history']}, "
                   f"L{SEP_L['gap-time']}; D04E11 §10 L{L_E11_OLDER}); two stacked panels of one series (deviation)",
        mode=mode, cols=cols,
        row_header_form=f"{k.row_header(s[i40], mode)} — name: {k.row_name(s[i40], mode)} (§2.1)",
        keyboard=f"Home reached the first loaded row with a page in flight; ↓ stops on the partial-history row "
                 f"(focused, §7.2 L{L_72}); ↓ again lands on 16:40, the first bar with delta",
        announcement=f"once per page: “Loading older bars” (D04E11 L{L_E11_OLDER}); separator rows not announced "
                     f"on arrival (§7.2)",
        copy_keys=("W-3", "W-5", "W-18"), tokens=_tok(fr),
        extra=[f"Rows (top): band “Loading older bars…” (D04E11 L{L_E11_OLDER}; Older in the footer); {n1} kline "
               f"rows, delta and trades “—” (W-18); W-5, <ts> = {TS}, focused (L{SEP_L['partial-history']})",
               f"Rows (bottom): {n2} generation 1 rows to 17:01; W-3 above the first bar inside the gap, whose kline "
               f"bars stay rows (L{SEP_L['gap-time']})",
               _cap(fid, f"top “{cap1}”; bottom “{cap2}”", f"Captions: summariseRange() + §7.4 (L{L_74})")])
    return fr, blk


def frame_captions(fid: str) -> tuple[Any, tuple[str, list[str]]]:
    """captions/rebuild-and-cache (A-4): two stacked panels. Top: Vol 50 BTC rebuilding (caption W-8), the held
    series' oldest rows under the before-recorded-history band and the built-range-start row (L_MEET's order),
    Older disabled. Bottom: 1m loading 5m (caption W-9), no kline coverage in the gap: the kline-hole row (W-4)."""
    w, hs = k.dock_w("strip"), k.split_h(2)
    sv = k.series("volume")
    g1 = [b for b in sv if b.gen == 1]
    st = k.series("time", hole=True)
    i15 = k.at("time", "09:15", hole=True)
    cv, ct = fit_cols("volume", w), fit_cols("time", w)

    def top(n: int) -> Any:
        items = [("sep", "before-history", {}), ("sep", "built-start", {"ts": TS})] + [("bar", b, False)
                                                                                      for b in g1[:n]]
        t, cap = _table(items, g1[:n], "volume", cv, w=w, h=k.table_room(hs[0]), loaded=len(sv),
                        footer=footer_history_start(w - 16), rebuild="W-8")
        return t, cap, n

    def bottom(n: int) -> Any:
        before, after = st[i15 - n:i15], st[i15:i15 + n]
        items = [("bar", b, False) for b in before] + [("sep", "kline-hole", {})] + [("bar", b, False) for b in after]
        t, cap = _table(items, before + after, "time", ct, w=w, h=k.table_room(hs[1]), loaded=len(st),
                        footer=k.footer_row(w - 16), rebuild="W-9", hole=True)
        return t, cap, n

    t1, cap1, n1 = _fit(top, 4)
    t2, cap2, n2 = _fit(bottom, 3)
    if n1 < 1 or n2 < 1:
        raise ValueError("caption panels too short")
    fr = k.window(fid, [k.panel("volume", t1, w=w, h=hs[0], name="CMP-080 DockPanel (composition) · chart · top"),
                        k.panel("time", t2, w=w, h=hs[1], name="CMP-080 DockPanel (composition) · chart · bottom")])
    k.deviate("board 05 captions∕rebuild-and-cache: two chart panels stacked in the dock (CMP-081 4 px gutter), "
              "because W-8 and W-9 caption two different series (A-4); every other board 05 frame but "
              "separators∕time-axis holds one panel")
    blk = k.frame_block(
        fid, state=f"captions/rebuild-and-cache (§7.3 L{L_73}–{L_73 + 3}; §7.1 L{SEP_L['before-history']}, "
                   f"L{SEP_L['built-start']}, L{SEP_L['kline-hole']}; D04E11 §10 L{L_E11_BEFORE}); two stacked "
                   f"panels (A-4 deviation)",
        mode="volume", cols=cv,
        row_header_form=f"top {k.row_header(g1[0], 'volume')} — name: {k.row_name(g1[0], 'volume')}; bottom "
                        f"{k.row_header(st[i15], 'time')} — name: {k.row_name(st[i15], 'time')}",
        keyboard="no row change in this frame: the rebuild and the 5m request change captions only; focus stays on "
                 "the row it was on (not drawn)",
        announcement=f"top: once “Start of recorded history” (D04E11 L{L_E11_BEFORE}); captions are not live "
                     f"regions (D04E11 §6.2)",
        copy_keys=("W-4", "W-6", "W-8", "W-9", "W-10", "W-12"), tokens=_tok(fr),
        extra=[f"Bottom panel: mode time (1m) · chart type: candle · Columns: {' · '.join(ct)} (marks as board "
               f"05's time-axis frame)",
               f"Rows (top): band “{k.E11_BANDS['before-history']}” + Show coverage; W-6 + Build earlier bars; "
               f"{n1} held bars; Older disabled “History starts here” (D04E11 L{L_E11_BEFORE})",
               f"Rows (bottom): {n2} bars to 17:01; W-4 kline-hole row (L{SEP_L['kline-hole']}); {n2} bars from 09:15",
               _cap(fid, f"top “{cap1}”; bottom “{cap2}”", f"Captions: top ends with W-8 (rebuilding), bottom "
                    f"with W-9 (cache-loading); rows stay the held series' (§7.3 L{L_73 + 2}–{L_73 + 3})")])
    return fr, blk


BOARD_LINES = [f"Every separator row of §7.1 (L{SEP_L['seam']}–L{SEP_L['loading-older']}, 9 kinds; the seam "
               f"appended to the gap row, L{L_MEET})",
               f"Band-row form §7.2 L{L_72}; hand-off §E: each separator row says what happened in words"]

NOTES_05 = {
    "spec_gaps": [
        "W-5 / W-6 <ts> has no format in §13: drawn as “16:40 UTC” (hh:mm UTC, as W-1 / W-2 write their times)",
        "the caption's visible-range clause names one date (A-11); on the non-time frame it spans the gap, so it "
        "reads 2026-10-19 16:40–09:xx UTC with the next day's 09:xx",
        "W-7 “the last 30 days” and E11-D04's “History starts 2026-09-01 08:00 UTC” are kept verbatim; the seeded "
        "series starts 2026-10-19 (placeholders, as A-3 / A-5)",
        "§7.3 W-8 names only the held Volume 50; the new setting being built is not named, so the toolbar keeps the "
        "held Vol 50 BTC; likewise the bottom panel's toolbar keeps 1m while 5m loads",
        "separators∕time-axis: generation 1 has 22 one-minute bars between the partial-history row and the W-3 row "
        "and one panel holds 20 rows, so the frame stacks two panels of the same 1m series scrolled to each row"],
    "live_checks": [
        "focus ring: read back 2 px color.focus.ring on 'separator · gap-non-time · focused' (frame non-time) and "
        "'separator · partial-history · focused' (frame time-axis)",
        "every 'separator · *' row reads 24 px tall, fill color.surface.hover, text color.text.secondary, text on "
        "one line (no wrap)",
        "the gap row text reads exactly “Recording gap 17:02–09:14 UTC · Series restarted 09:15 UTC”",
        "two-panel frames: read back panel heights 318 and 318 with a 4 px gutter; each table's last row ends above "
        "its footer"],
}
