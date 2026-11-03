"""SCR-093 Journal list parts shared by boards 02, 03, 08 and 10."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wf  # noqa: E402
from wf import k  # noqa: E402

ROWS_SHOWN = 12
RANGE_WORDS = k.day_range(*k.RANGE)
ALL = k.cat("[all v]", "### SCR-093")[1:-2]  # `14`'s filter value "all"


def header(env: str = "LIVE", *, t2: bool = False, focus: str | None = None) -> Any:
    mt, ex = k.memo('"Manage tags"')[1:-1], k.memo('"Export"')[1:-1]
    b1, b2 = wf.btn(mt, t2=t2), wf.btn(ex)
    if focus == "Manage tags":
        b1 = wf.ring(b1)
    return wf.page_header("Journal", "/journal", wf.PAGE_W, env=env, actions=[b1, b2])


def filters(env: str = "LIVE", **over: str) -> Any:
    vals = {"environment": env, "range": RANGE_WORDS, "account": ALL, "symbol": ALL, "tag": ALL, "outcome": ALL}
    vals.update(over)
    for lab in vals:
        k.cat(lab, "### SCR-093")
    return wf.filter_bar(list(vals.items()), wf.PAGE_W - 32)


def rows(env: str = "LIVE", **kw: Any) -> list[k.Trade]:
    return k.trades(env, **kw)


def screen(env: str = "LIVE", *, n: int = ROWS_SHOWN, selected: tuple[int, ...] = (), t2: bool = False,
           pre_table: list[Any] | None = None, table: Any = None, totals: bool = True, extra: dict[int, str] | None = None,
           filt: dict[str, str] | None = None, focus: str | None = None) -> Any:
    rs = rows(env)
    body = table if table is not None else wf.journal_table(rs[:n], selected=selected, t2=t2, extra=extra)
    return wf.page("/journal", [header(env, t2=t2, focus=focus), filters(env, **(filt or {})), *(pre_table or []),
                                body, wf.totals_bar(rs, env, f"{RANGE_WORDS} · all accounts", wf.TABLE_W)
                                if totals else None, wf.pager(min(n, len(rs)), len(rs), wf.TABLE_W) if totals else None])
