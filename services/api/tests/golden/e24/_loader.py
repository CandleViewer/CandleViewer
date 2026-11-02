"""E24-T06 loader: the recorded corpus plus the case manifest -> plain rows, and Parquet files.

Imports NO engine code: rows are plain ints and decimal strings, so the reference oracle and the
engine adapter both start from the same neutral input. Every input file is referenced by manifest
id (its path in the corpus `manifest.json`), never copied."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from tests import _corpus as corpus

REPO = Path(__file__).resolve().parents[5]
GOLDEN_DIR = REPO / "packages" / "fixtures" / "golden" / "derivatives"
CASES_PATH = GOLDEN_DIR / "cases.json"
BAR_MS = 60_000
SYMBOL = "BTCUSDT"


@dataclass(frozen=True)
class Case:
    id: str
    lane: str
    interval_min: int
    funding: str
    bar_from_ms: int
    bar_count: int
    drops: tuple[dict[str, Any], ...]
    paired: bool
    bar_minutes: int = 1


@dataclass(frozen=True)
class Rows:
    """Neutral inputs: bars (start, end, open, close), OI (ts, oi, value), tickers (ts, last,
    mark, index, funding fraction, next funding ms), settled funding (ts, fraction)."""

    interval_min: int
    bars: list[tuple[int, int, str, str]]
    oi: list[tuple[int, str, str]]
    tickers: list[tuple[int, str | None, str | None, str | None, str | None, int | None]]
    funding: list[tuple[int, str]]


def load_manifest() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return data


def cases(lane: str | None = None) -> list[Case]:
    out = []
    for c in load_manifest()["cases"]:
        case = Case(
            id=c["id"], lane=c["lane"], interval_min=c["interval_min"], funding=c["funding"],
            bar_from_ms=c["bars"]["from_ms"], bar_count=c["bars"]["count"],
            drops=tuple(c["drops"]), paired=bool(c.get("paired", False)),
            bar_minutes=c["bars"].get("minutes", 1),
        )  # fmt: skip
        if lane is None or case.lane == lane:
            out.append(case)
    return out


def case_by_id(case_id: str) -> Case:
    return next(c for c in cases() if c.id == case_id)


def _fixture(manifest: dict[str, Any], rel: str) -> Any:
    """Read one corpus file by manifest id, refusing one the corpus manifest does not list."""
    date = manifest["fixture_dir"]
    if rel not in {f["path"] for f in corpus.manifest(capture_date=date)["fixtures"]}:
        raise ValueError(f"{rel} is not in the fixture manifest")
    if rel.endswith(".jsonl"):
        return [json.loads(frame) for frame in corpus.frames(rel, capture_date=date)]
    return corpus.rest(rel, capture_date=date)


def _dropped(drops: tuple[dict[str, Any], ...], stream: str, ts: int) -> bool:
    return any(d["stream"] == stream and d["from_ms"] <= ts < d["to_ms"] for d in drops)


def _tickers(frames: list[dict[str, Any]]) -> list[Any]:
    """Cumulative state: a delta frame carries only the changed fields, so each emitted snapshot
    is the snapshot with every delta so far applied (the topic's documented semantics)."""
    state: dict[str, Any] = {}
    out = []
    for f in frames:
        if f["type"] == "snapshot":
            state = dict(f["data"])
        else:
            state.update(f["data"])
        nxt = state.get("nextFundingTime")
        out.append((
            int(f["ts"]), state.get("lastPrice"), state.get("markPrice"), state.get("indexPrice"),
            state.get("fundingRate"), int(nxt) if nxt is not None else None,
        ))  # fmt: skip
    return out


#: `funding_basis.sql` casts prices at 1e9 into HUGEINT, which rounds silently past 9 decimals.
MAX_PRICE_DECIMALS = 9


def check_price_scale(rows: Rows) -> None:
    """Refuse loudly a ticker price with more than 9 decimals (the reference cannot hold it)."""
    for ts, *prices, _rate, _next in rows.tickers:
        for price in prices:
            if price is None:
                continue
            exp = Decimal(price).normalize().as_tuple().exponent
            if isinstance(exp, int) and exp < -MAX_PRICE_DECIMALS:
                raise ValueError(
                    f"ticker price {price!r} at {ts} has more than {MAX_PRICE_DECIMALS} decimals; "
                    "funding_basis.sql would round it silently"
                )


_ROWS: dict[str, Rows] = {}


def build_rows(case: Case) -> Rows:
    """The case's rows, built once per case id; every caller gets its own copy of the lists."""
    if case.id not in _ROWS:
        _ROWS[case.id] = _build_rows(case)
    r = _ROWS[case.id]
    return Rows(r.interval_min, list(r.bars), list(r.oi), list(r.tickers), list(r.funding))


def _build_rows(case: Case) -> Rows:
    man = load_manifest()
    inp = man["inputs"]
    klines = sorted(
        (int(r[0]), r[1], r[4]) for p in inp["klines"] for r in _fixture(man, p)["result"]["list"]
    )
    step = case.bar_minutes * BAR_MS
    window = [
        k for k in klines if case.bar_from_ms <= k[0] < case.bar_from_ms + case.bar_count * step
    ]
    by_start = {k[0]: k for k in window}
    bars = []
    for i in range(
        case.bar_count
    ):  # a coarser bar is the 1 m klines folded: first open, last close
        start = case.bar_from_ms + i * step
        first, last = by_start.get(start), by_start.get(start + step - BAR_MS)
        if first is None or last is None:
            raise ValueError(f"{case.id}: the corpus lacks the klines of the bar at {start}")
        bars.append((start, start + step, first[1], last[2]))
    price = Decimal(man["oi_value_price"])
    oi = sorted(
        (int(r["timestamp"]), r["openInterest"], str(Decimal(r["openInterest"]) * price))
        for p in inp["oi"]
        for r in _fixture(man, p)["result"]["list"]
    )
    tickers = _tickers(_fixture(man, inp["tickers"]))
    funding = sorted(
        (int(r["fundingRateTimestamp"]), r["fundingRate"])
        for r in _fixture(man, inp["funding"][case.funding])["result"]["list"]
    )
    rows = Rows(
        interval_min=case.interval_min,
        bars=bars,
        oi=[r for r in oi if not _dropped(case.drops, "oi", r[0])],
        tickers=[t for t in tickers if not _dropped(case.drops, "tickers", t[0])],
        funding=funding,
    )
    check_price_scale(rows)
    return rows


def write_parquet(rows: Rows, root: Path) -> None:
    """The rows as Parquet in `root`, written by plain DuckDB. Tickers are hive-partitioned
    `symbol=/dt=` as 21 §5.1; OI and funding follow the registered `symbol,ym` / `symbol,y`
    templates (no production roll-off reads them yet)."""
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE bars(start_ms BIGINT, end_ms BIGINT, o DECIMAL(38,18), c DECIMAL(38,18))"
    )
    con.executemany("INSERT INTO bars VALUES (?, ?, ?, ?)", rows.bars)
    con.execute("CREATE TABLE oi(ts BIGINT, oi DECIMAL(38,18), oi_value DECIMAL(38,18))")
    con.executemany("INSERT INTO oi VALUES (?, ?, ?)", rows.oi)
    con.execute(
        "CREATE TABLE tickers(ts BIGINT, last DECIMAL(38,18), mark DECIMAL(38,18), "
        "idx DECIMAL(38,18), rate DECIMAL(38,18), next_ms BIGINT, dt VARCHAR)"
    )
    if rows.tickers:
        con.executemany(
            "INSERT INTO tickers VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(*t, _day(t[0])) for t in rows.tickers],
        )
    con.execute("CREATE TABLE funding(ts BIGINT, rate DECIMAL(38,18))")
    con.executemany("INSERT INTO funding VALUES (?, ?)", rows.funding)
    _write(con.table("bars"), root / "bars" / f"symbol={SYMBOL}" / "bars.parquet")
    sym = f"symbol={SYMBOL}"
    _write(con.table("oi"), root / "open_interest" / sym / "ym=2023-11" / "oi.parquet")
    _write(con.table("funding"), root / "funding_rates" / sym / "y=2023" / "f.parquet")
    days = sorted({t[6] for t in con.execute("SELECT * FROM tickers").fetchall()}) or ["empty"]
    for day in days:  # an empty schema-only file keeps the hive glob valid for a gap case
        part = con.sql("SELECT * EXCLUDE (dt) FROM tickers WHERE dt = $day", params={"day": day})
        _write(part, root / "tickers" / f"symbol={SYMBOL}" / f"dt={day}" / "part-0.parquet")
    con.close()


def _write(rel: duckdb.DuckDBPyRelation, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    rel.write_parquet(dest.as_posix())


def _day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
