"""Pair 3 helpers (boards 03 range-renko and 07 sync-and-edge): one table frame from a sequence of bars and
separator rows, fitted to the panel (whole rows only). Uses the kit's public API; adds nothing to the kit."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e12d07kit as k  # noqa: E402

Sep = tuple  # ("sep", kind, {kwargs for k.sep_row})


def L(needle: str) -> int:
    """Spec line of the first line containing needle (E12-D07.md)."""
    return k.find_line(needle)


def HL(needle: str) -> int:
    """Hand-off line of the first line containing needle."""
    return k.find_line(needle, k.HANDOFF_LINES)


def is_sep(x: Any) -> bool:
    return isinstance(x, tuple) and x and x[0] == "sep"


def fit_frame(fid: str, mode: str, seq: list[Any], *, start: int, focus: Callable[[Any], bool],
              loaded: int, rail: str = "strip", banner_chars: str | None = None, older: bool = False,
              rows_all: list[k.Bar] | None = None, caption_extra: tuple[str, ...] = (),
              max_n: int | None = None) -> dict[str, Any]:
    """Build the window for seq[start:start+n] with n the largest count that fits the table. Returns the frame and
    what the annotation needs (cols, visible bars, the focused item, the caption)."""
    w = k.dock_w(rail)
    inner = w - 16
    full = k.shown_columns(mode, auto=True)
    cols = full if k.row_width(full, mode) <= inner else k.shown_columns(mode)
    rows_all = rows_all if rows_all is not None else [x for x in seq if not is_sep(x)]
    room = k.table_room()
    n = max_n or k.max_rows(h=room, caption_lines=2, banner=banner_chars is not None, footer=True)
    durations = "duration" in cols
    while n > 0:
        items = seq[start:start + n]
        bars = [x for x in items if not is_sep(x)]
        cap = k.caption_text(bars, mode, loaded=loaded, durations=durations, extra=caption_extra)
        rows: list[dict[str, Any]] = []
        fitem = None
        zebra = 0
        for x in items:
            f = focus(x)
            if f:
                fitem = x
            if is_sep(x):
                rows.append(k.sep_row(x[1], cols, mode, focused=f, **x[2]))
            else:
                zebra += 1
                rows.append(k.bar_row(x, cols, mode, zebra, focused=f, cvd=k.cvd_of(rows_all, x)))
        banner = k.stale_banner(banner_chars, inner) if banner_chars else None
        try:
            t = k.table(rows, w=w, h=room, caption_chars=cap, header=k.header_row(cols, mode), banner=banner,
                        footer=k.footer_row(inner, older=older))
        except ValueError:
            n -= 1
            continue
        fr = k.window(fid, k.panel(mode, t, w=w), rail=rail)
        return {"frame": fr, "cols": cols, "bars": bars, "items": items, "focus": fitem, "caption": cap, "n": n}
    raise ValueError(f"{fid}: nothing fits")


_SHELL_LINES = k.SHELL.read_text(encoding="utf-8").split("\n")


def SL(needle: str) -> int:
    """E11-D04 line (the SCR-045 shell) of the first line containing needle."""
    return k.find_line(needle, _SHELL_LINES)
