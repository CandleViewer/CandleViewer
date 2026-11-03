"""The Q05 rows that cannot run yet, each with its owner (BQ ruling 15:33Z).

A row is `pending <owner>` until its owner lands; none is a silent pass. `render` is the table
both reports append. Quoted budget text is verbatim from 06-performance section 2.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Row:
    key: str
    what: str
    owner: str  # the ticket or ruling the row waits on, or "recorded"


#: 06 :31 and :174, verbatim (budget #7's workload, which the engine soak row uses).
BUDGET_7 = "100k bars, all overlays, 4-pane layout"
BUDGET_8 = (
    "<=300MB resident per actively-recorded symbol (book state + bar builders + rolling "
    "aggregation buffers)"
)
ROWS: tuple[Row, ...] = (
    Row("volume-pane", "volume sub-pane frame time, 10k and 100k bars", "pending E12-S08 (#534)"),
    Row("switching", "symbol/timeframe switching soak, no GL context after the first",
        "pending E12-S11 (#451)"),
    Row("growth", f"memory growth < 5 %/h after warm-up (C-14.2); budget #7 workload: {BUDGET_7}",
        "pending engine soak driver"),
    Row("budget-8", f"backend budget #8 from soak_bars, verbatim: {BUDGET_8}", "recorded"),
    Row("adr-0033", "cancel p95 <= 250 ms under load: Decimal builders, PGWire with cursor "
        "release, reference VPS", "pending E12-S12 (#535); gate owned by Q05"),
    Row("AC-01", "from=0&limit=5000 on bars_time and each non-time type (BR-28)",
        "pending stack run; executed by E12-X02"),
    Row("AC-05", "rebuild storm: 50 parameter changes in 10 s, disconnect mid-rebuild, cancel by "
        "another user (BR-31, BR-04)", "pending E12-S12 (#535)"),
    Row("AC-06", "slow bars.* consumer beside a healthy book.* client; 17th subscription; "
        "history=1001 (BR-32, BR-38)", "pending true slow reader (E17-Q03) and stack run"),
    Row("F3", "one session looping maximal pages is throttled (BR-36): strict xfail at "
        "services/api/tests/security/bars/test_caps_and_cost.py:338-346",
        "pending E12-X04 (#538)"),
)  # fmt: skip


def render() -> str:
    out = ["| row | what | status |", "|---|---|---|"]
    out += [f"| {r.key} | {r.what} | {r.owner} |" for r in ROWS]
    return "\n".join(out)
