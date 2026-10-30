"""Pair 2 helpers (boards 02 `tick-volume-delta` and 08 `reflow-200`): one non-time table frame at 100 % from the
kit's primitives. Imports the kit read-only; adds nothing to it."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
import e12d07kit as k  # noqa: E402

SPEC = "E12-D07"  # cited by spec name + line in the annotations; never a path
KEYS_100 = ("Alt+T opens the table in place, focus on the cursor bar's row (D04E11:115); ↑ / ↓ move the row, "
            "Esc or Alt+T back (D04E11:129)")
CLOSING = {"tick": "W-11", "volume": "W-12", "range": "W-13", "delta": "W-14", "renko": "W-15"}
QTY_LINE = {"tick": f"§3.2 L{k.L('| tick   |')} (tick: trades in the bar)", "volume": f"§3.2 L{k.L('| volume |')} "
                                                                                      "(volume: base-asset volume)",
            "delta": f"§3.2 L{k.L('| delta  |')} (delta: net delta, buy and sell beside it)"}


def sweep_rows(mode: str, before: int = 3) -> tuple[list[k.Bar], int]:
    """The loaded series and the index of the first row shown: `before` rows ahead of the 10:22:11.412 sweep."""
    rows = k.series(mode)
    i = next(j for j, b in enumerate(rows) if b.t == k.SWEEP_AT)
    return rows, i - before


def dash_lines(sel: list[k.Bar], cols: list[str], mode: str) -> list[str]:
    """One line per "—" value cell the frame shows (R-6), with its reason; `state` "—" = closed, unmarked (§6)."""
    out = []
    reasons = {"trades": k.copy("W-19"), "close time": "forming: not closed yet", "duration": "forming: not closed yet",
               "delta": k.copy("W-21"), "buy": "delta is “—”", "sell": "delta is “—”"}
    for b in sel:
        for c in cols:
            if c in ("time", "state"):
                continue
            if k.cell(c, b, mode) == "—":
                out.append(f"“—” in {c} on {k.row_header(b, mode)}: {reasons.get(c, 'not sent')}")
    return out


def table_frame(fid: str, mode: str, *, rail: str, focus_k: int | None = 3, state: str, extra: list[str] = (),
                announce: str = "Data table, row k of N (D04E11:115 D2)", full: bool = True,
                base_cols: tuple[str, ...] = ()) -> tuple[dict[str, Any], tuple[str, list[str]]]:
    """A 1280 x 800 window, one chart panel, the table open in place; rows from 3 bars ahead of the sweep, as many as
    fit. Auto columns (close time, duration; delta's buy / sell) join when the auto set fits the dock (§5 L214)."""
    w = k.dock_w(rail)
    rows_all, i0 = sweep_rows(mode)
    auto_cols = k.shown_columns(mode, auto=True)
    auto = k.row_width(auto_cols, mode) + 16 <= w
    cols = auto_cols if auto else k.shown_columns(mode)
    room = k.table_room()
    cap = k.caption_text(rows_all[i0:i0 + 20], mode, loaded=len(rows_all), durations="duration" in cols)
    n = k.max_rows(h=room, caption_lines=k.caption_lines(cap, w))
    sel = rows_all[i0:i0 + n]
    cap = k.caption_text(sel, mode, loaded=len(rows_all), durations="duration" in cols)
    focus = next((b for b in sel if b.t == k.SWEEP_AT and b.k == focus_k), None) if focus_k else None
    rows = [k.bar_row(b, cols, mode, i + 1, focused=b is focus, cvd=k.cvd_of(rows_all, b)) for i, b in enumerate(sel)]
    t = k.table(rows, w=w, h=room, caption_chars=cap, header=k.header_row(cols, mode), footer=k.footer_row(w - 16))
    fr = k.window(fid, k.panel(mode, t, w=w), rail=rail)
    fb = focus or sel[len(sel) // 2]
    fi = sel.index(fb) + 1
    lines = [f"Width: dock {w} (rail {'open' if rail == 'open' else 'strip'}); {mode} {k.set_width(mode, 'P')} / "
             f"{k.set_width(mode, 'PA')} with auto (§5 L{k.L(f'| {mode:<6} | ', start=k.L('## 5. Widths'))})"
             " → auto columns "
             f"{'shown' if auto else f'hidden (in the row name, §3.1 L{k.L('| close time')}–{k.L('| duration')})'}",
             f"Rows: {len(sel)} of {len(rows_all):,} loaded from {k.row_header(sel[0], mode)}; served order (§2.2 "
             f"L{k.L('- **Order')})",
             *dash_lines(sel, cols, mode), *extra]
    if not any("“—”" in ln for ln in lines):
        lines.append("“—”: no value cell; `state` “—” = closed, unmarked (§6)")
    keyboard = (KEYS_100 if full else "as tick∕default") + (
        f"; ring on row {fi:02d} ({k.row_header(fb, mode)}), 2 px color.focus.ring, aria-current" if focus else "")
    head = [f"Frame: {k.frame_name(fid)}", f"State: {state}", f"Mode: {mode} ({k.SHORT[mode]}) · chart type: candle",
            "Columns: " + (k.columns_line(cols, mode) if full else
                           k.columns_line([c for c in cols if c not in base_cols], mode) + " · plus " +
                           ", ".join(c for c in cols if c in base_cols) + " as tick∕default"),
            ("Row header: as tick∕default" if not full and mode == "tick" else
             f"Row header: {k.row_header(fb, mode)} (§2.2 L{k.L('- **Visible')}) — name: {k.row_name(fb, mode)} (§2.2 "
             f"L{k.L('- **Accessible')})"),
            f"Keyboard and focus: {keyboard}", f"Announcement: {announce}",
            "Copy: " + " · ".join(f"{c} “{k.COPY[c][0]}” (L{k.COPY[c][1]})" for c in ("W-10", CLOSING[mode]))]
    for c in ("W-10", CLOSING[mode]):
        k.copy(c)
    blk = (k.frame_name(fid), head + lines)
    if focus:
        k.live(f"frame {k.frame_name(fid)!r}: read back row {fi:02d}'s stroke = 2 px color.focus.ring (inner) and its "
               f"row header text {k.row_header(fb, mode)!r}")
    k.live(f"frame {k.frame_name(fid)!r}: read back the header words {' · '.join(cols)} and {len(sel)} body rows; the "
           f"caption contains {k.copy('W-10')!r} and {k.copy(CLOSING[mode])!r}")
    return fr, blk
