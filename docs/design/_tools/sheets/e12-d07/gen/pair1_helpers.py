"""Pair 1 helpers (boards 01 time-bars and 06 chart-type-cells). Imports the kit; never edits it."""
from __future__ import annotations

import statistics
import sys
from pathlib import Path
from typing import Any

KIT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT_DIR))
import e12d07kit as k  # noqa: E402

SHELL_LINES = k._read(k.SHELL)
D06_LINES = k._read(k.D06)


def sl(needle: str, start: int = 1) -> str:
    """'L<n>' of the first E12-D07 spec line holding needle."""
    return f"L{k.find_line(needle, start=start)}"


def e11(needle: str, start: int = 1) -> str:
    """'D04E11:<n>' of the first E11-D04 line holding needle."""
    return f"D04E11:{k.find_line(needle, SHELL_LINES, start)}"


def d06(needle: str, start: int = 1) -> str:
    return f"D06:{k.find_line(needle, D06_LINES, start)}"


def time_loaded() -> list[Any]:
    """Pair 1's loaded time series: the trade-built 1m bars 2026-10-19 16:40 - 2026-10-20 13:42 (generation 1 and 2),
    with no kline coverage over the 17:02-09:14 recording gap (series(hole=True), the 16:00-16:39 kline rows older than
    the load). Every loaded row carries delta, so a delta sort orders every row."""
    return [b for b in k.series("time", hole=True) if not b.kline]


def grid_order(loaded: list[Any]) -> list[Any]:
    """Time order with the one separator row (None) between generation 1 and 2 (§7.1 kline hole + seam)."""
    out: list[Any] = []
    for i, b in enumerate(loaded):
        if i and b.gen != loaded[i - 1].gen:
            out.append(None)
        out.append(b)
    return out


def rowindex(loaded: list[Any], b: Any) -> tuple[int, int]:
    """(k, N) of 'Data table, row k of N': grid rows in time order, the separator row counted (§7.2)."""
    g = grid_order(loaded)
    return next(i for i, x in enumerate(g, 1) if x is b), len(g)


def rows_that_fit(cap: str, w: int, *, chips: bool = False, footer: bool = True, banner: bool = False) -> int:
    return k.max_rows(h=k.table_room(), caption_lines=k.caption_lines(cap, w), chips=chips, footer=footer,
                      banner=banner)


def median_denom(loaded: list[Any]) -> float:
    """D06:303's r denominator: max(median x, smallest non-zero x) over the loaded series (x = volume)."""
    xs = [b.v for b in loaded if b.v]
    return max(statistics.median(xs), min(xs))


def capped(b: Any, denom: float) -> bool:
    """D06:304 w0 = clamp(roundHalfUp(14 r), 6, 48): drawn at the cap when 14 r rounds above 48 (D06:311)."""
    return int(14 * b.v / denom + 0.5) > 48


def name_line(b: Any, mode: str, extra: str = "") -> str:
    return f"{k.row_header(b, mode)} — name: {k.row_name(b, mode)}" + (f"; {extra}" if extra else "")


def write_all(nn: int, frames: list[Any], blocks: list[Any], *, board_lines: list[str], notes: dict[str, list[str]],
              summary: str, frames_info: list[str]) -> tuple[Path, Path, Path]:
    ann = k.annotations(nn, blocks, board_lines=board_lines)
    path = k.write_sheet(nn, frames, ann, notes=notes)
    md = k.write_md(nn, path, summary=summary, frames_info=frames_info)
    packed = k.pack_sheet(path)
    return path, md, packed
