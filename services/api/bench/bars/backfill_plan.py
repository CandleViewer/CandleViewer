"""Backfill load plan and verdict (E12-Q05 slice 4, #528; budget #13 reads p95 < 150 ms).

`build_plan` pages `GET /market/klines` over a 30-day window (the same query shape as
`bench.ingestion.fixture_app.requests_plan`) into the request list `tests/load/k6/bars/backfill.js`
walks as one chart open; `judge` reads k6's summary JSON (`handleSummary` or
`--summary-export`). Pure and offline: the target is only the loopback fixture backend
(`guard`), never an exchange (C-13.5).
The simulated upstream `10018` leg (a rate-limited backfill must not stall other requests) needs a
fixture hook that does not exist yet: the plan carries no `backoff` route and the verdict lists it
as pending (owner: E12-S05 follow-up, no ticket yet).
Run by hand (writes the plan): `python -m bench.bars.backfill_plan <end_us> plan.json`.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIN_US = 60_000_000
DAY_US = 86_400_000_000
WINDOW_DAYS = 30
PAGE_LIMIT = 1_000  # Bybit's page size; the read route caps the same
BUDGET_READ_P95_MS = 150.0  # budget #13 (reads)
PENDING = (
    "simulated upstream 10018 leg: pending (fixture hook; E12-S05 follow-up, no ticket yet)",
)


def _iso(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_plan(
    symbol: str,
    end_us: int,
    *,
    days: int = WINDOW_DAYS,
    interval_min: int = 1,
    limit: int = PAGE_LIMIT,
) -> dict[str, Any]:
    """`pages`: consecutive windows of `limit` candles, oldest first, covering `days` exactly;
    `other`: one latest-page read, the request the stall probe sends beside the opens."""
    if days < 1 or interval_min < 1 or not 1 <= limit <= PAGE_LIMIT:
        raise ValueError("days and interval_min must be >= 1 and limit within 1..1000")
    step = interval_min * MIN_US
    span = limit * step
    start = end_us - days * DAY_US
    base = {"symbol": symbol, "interval": str(interval_min), "limit": limit}
    pages = []
    for lo in range(start, end_us, span):
        pages.append(
            {
                "path": "/market/klines",
                "params": {**base, "from": _iso(lo), "to": _iso(min(lo + span, end_us))},
            }
        )
    last = {**base, "from": _iso(end_us - span), "to": _iso(end_us)}
    return {"pages": pages, "other": {"path": "/market/klines", "params": last}}


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    budget: str
    measured: float
    limit: float
    passed: bool


def _p95(summary: Mapping[str, Any], metric: str) -> float:
    m = summary["metrics"].get(metric)
    m = m.get("values", m) if m is not None else None  # handleSummary nests; --summary-export not
    if m is None or not m.get("count"):
        raise ValueError(f"k6 summary has no samples for {metric}")
    return float(m["p(95)"])


def judge(summary: Mapping[str, Any]) -> list[Check]:
    """Read p95 must stay under budget #13 for the backfill pages and for the other requests
    running beside them (the stall check)."""
    out = []
    for name in ("backfill_page_ms", "other_route_ms"):
        v = _p95(summary, name)
        out.append(Check(name, "#13", v, BUDGET_READ_P95_MS, v < BUDGET_READ_P95_MS))
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m bench.bars.backfill_plan <end_us> <plan.json>", file=sys.stderr)
        return 2
    plan = build_plan("BTCUSDT", int(args[0]))
    Path(args[1]).write_text(json.dumps(plan), encoding="utf-8")
    print(f"{len(plan['pages'])} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
