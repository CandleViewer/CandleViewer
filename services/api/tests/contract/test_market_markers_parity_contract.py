"""#5581 (#538): `GET /market/klines` names a range of its window it cannot serve in
`meta.coverage_holes` (22 `DataMeta.coverage_holes`: "Requested-range gaps the local cache has no
bars for yet"; "a missing range is named, never silently absent"): the parts the kline cache does
not cover (`KlineRead.holes`, each with a backfill started), minus the bars the page serves. The
router dropped `KlineRead.holes` before, and `app.py` wires no `coverage_index_provider`, so an
in-window gap was silent. Exchange klines carry no `gap_before` / `partial` / `tape_gap`; a
tape-built bar served on this route carries its stored flags.

`/market/klines` is composed as `app.py` composes it: a read service with a backfill (whose
coverage names the cache's gaps), the recorded 1m klines (`test_market_klines_contract`) or klines
for the recorded tape's bars, and the tape tier over `bars_time` rows
(`bars.reader.tape_time_bar_reader`); no `coverage_index_provider`. The parity check reads one
window on `/market/bars` and on the WS `bars` snapshot too (`test_bars_withheld_rows_contract`).
"""

from __future__ import annotations

from typing import Any, Final, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import KlineResponse
from candleviewer.api.market import make_market_router
from candleviewer.api.market_response import iso_us
from candleviewer.bars.models import Bar
from candleviewer.bars.reader import BarReader, tape_time_bar_reader
from candleviewer.bars.rows import KLINE_GENERATION, bar_param_for, bar_row, row_checksum
from candleviewer.ingestion.kline_coverage import CoverageIndex, Range
from candleviewer.ingestion.kline_read import KlineReadService
from tests.contract import test_bars_withheld_rows_contract as withheld
from tests.contract import test_market_bars_contract as bars_world
from tests.contract import test_market_klines_contract as klines_world

_TIME: Final = bars_world._SERIES["time", "1"]
_MIN: Final = 60_000_000


def _kline_twin(bar: Bar) -> dict[str, object]:
    """The exchange kline of `bar`'s open time as `bars_time` stores one (source `kline`)."""
    row = bar_row(bar, _TIME, generation=KLINE_GENERATION) | {"source": "kline", "index": None}
    row["row_checksum"] = row_checksum(row)
    return row


class _Backfill:
    """`KlineBackfillService`'s read-side surface: a coverage index of what the cache holds, as
    `load_coverage_from_cache` rebuilds it, and a job that never runs (no exchange call)."""

    def __init__(self, covered: list[Range]) -> None:
        self.index, self.started = CoverageIndex(), list[Range]()
        for rng in covered:
            self.index.mark_covered(rng)

    async def load_coverage_from_cache(self, symbol: str, interval: str, rng: Range) -> None: ...

    def coverage(self, symbol: str, interval: str) -> CoverageIndex:
        return self.index

    def start_backfill(self, symbol: str, interval: str, rng: Range) -> None:
        self.started.append(rng)

    def job_running(self, symbol: str, interval: str) -> bool:
        return False


def _klines_client(rows: list[dict[str, object]], klines: list[Any], covered: list[Range],
                   now: int) -> TestClient:  # fmt: skip
    """`/market/klines` as `app.py` composes it: a read service with a backfill (whose coverage
    names the cache's gaps) and the tape tier over `rows`; no `coverage_index_provider`."""
    reader = BarReader(bars_world._Fetch({bar_param_for(_TIME): rows}), bars_world._noop)

    async def started(symbol: str) -> int | None:
        return None

    service = KlineReadService(
        klines_world._Hot(klines), backfill=cast(Any, _Backfill(covered)),
        recording_started_at_us=started, tape=tape_time_bar_reader(reader, timeout_s=5.0),
    )  # fmt: skip
    app = FastAPI()
    app.include_router(
        make_market_router(
            lambda: klines_world._Hot([]),
            principal_resolver=klines_world._Resolver(klines_world._READ),
            read_service_provider=lambda: service, symbol_listed=lambda s: s == "BTCUSDT",
            now_us=lambda: now,
        )
    )  # fmt: skip
    return TestClient(app, client=("127.0.0.1", 50000))


_FLAGS: Final = ("gap_before", "partial", "tape_gap")


def _flags(body: dict[str, Any]) -> dict[str, tuple[bool, ...]]:
    return {b["t"]: tuple(b.get(f, False) for f in _FLAGS) for b in body["bars"]}


async def test_rest_ws_and_klines_agree_on_the_markers_and_holes_of_one_series() -> None:
    """#5581's Gherkin: one recorded series with two withheld rows, a partial bar and a tape-gap
    bar, read three ways. The row withheld where an exchange kline exists is served as that kline
    and not listed on REST or klines; the one withheld where none exists is listed on both
    (klines: its cache does not cover it). The WS snapshot sends tape-built bars only, so it lists
    both withheld rows. Every bar served carries the same three markers on all three (an exchange
    kline carries none: absent reads false, 22 `Bar`)."""
    closed = [b for b in bars_world._build(_TIME) if b.closed][:12]
    closed[2] = closed[2].model_copy(update={"gap_before": True, "tape_gap": True})
    closed[4] = closed[4].model_copy(update={"partial": True})
    filled, bare = 6, 9  # withheld with, and without, an exchange kline at its open time
    tape = [bar_row(b, _TIME, generation=0) for b in closed]
    tape[filled], tape[bare] = withheld._edited(tape[filled]), withheld._edited(tape[bare])
    twins = [b for n, b in enumerate(closed) if n != bare]
    rows = sorted([*tape, *map(_kline_twin, twins)], key=lambda r: int(str(r["ts"])))
    start, end = closed[0].open_time, closed[-1].open_time + _MIN
    window = {"from": bars_world._iso(start), "to": bars_world._iso(end), "limit": 1000}

    bars = withheld._get_bars(withheld._client(rows, _TIME), _TIME, **window)
    klines_rows = [klines_world._Kline(b.open_time, str(b.open), str(b.high), str(b.low),
                                       str(b.close), str(b.volume), str(b.turnover))
                   for b in twins]  # fmt: skip
    gap = closed[bare].open_time
    covered = [Range(start, gap), Range(gap + _MIN, end)]  # the cache holds every kline but one
    resp = _klines_client(rows, klines_rows, covered, end).get(
        "/market/klines", params={"symbol": "BTCUSDT", "interval": "1", **window}
    )
    assert resp.status_code == 200, resp.text
    klines = resp.json()
    KlineResponse.model_validate(klines)

    hole = [{"start_us": gap, "end_us": gap + _MIN}]
    assert bars["meta"]["coverage_holes"] == klines["meta"]["coverage_holes"] == hole
    assert _flags(bars) == _flags(klines)
    assert iso_us(closed[filled].open_time) in _flags(bars)  # served as the exchange kline
    assert _flags(bars)[iso_us(closed[2].open_time)] == (True, False, True)
    assert _flags(bars)[iso_us(closed[4].open_time)] == (False, True, False)

    frame = await withheld._snapshot(rows)  # the WS `bars` snapshot of the same stored rows
    ws = {
        iso_us(b["t_ms"] * 1_000): tuple(b.get(f, False) for f in _FLAGS)
        for b in frame["p"]["bars"]
    }
    assert ws == {t: f for t, f in _flags(bars).items() if t != iso_us(closed[filled].open_time)}
    assert frame["meta"]["coverage_holes"] == [
        withheld._span(_TIME, tape, tape[n]) for n in (filled, bare)
    ]


def _klines(rows: list[Any], covered: list[Range], tape: list[dict[str, object]] | None = None,
            ) -> dict[str, Any]:  # fmt: skip
    client = _klines_client(tape or [], rows, covered, 1_700_100_000_000_000)
    resp = client.get("/market/klines", params=klines_world._P)
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    KlineResponse.model_validate(body)
    return body


def test_klines_a_stored_gap_is_named_in_coverage_holes() -> None:
    """The klines `SilentGap` check: a minute the cache holds no kline for and does not cover is
    listed (the backfill's coverage, `KlineRead.holes`), and nothing else of the window is."""
    corpus = klines_world._corpus()
    gap = corpus[20].ts_us
    start, end = corpus[0].ts_us, corpus[-1].ts_us + _MIN
    body = _klines([r for r in corpus if r.ts_us != gap],
                   [Range(0, gap), Range(gap + _MIN, 2**62)])  # fmt: skip
    assert body["meta"]["coverage_holes"] == [{"start_us": gap, "end_us": gap + _MIN}]
    assert iso_us(gap) not in {b["t"] for b in body["bars"]} and start < gap < end


def test_klines_a_tape_bar_fills_a_minute_the_cache_does_not_cover() -> None:
    corpus = klines_world._corpus()
    gap = corpus[20].ts_us
    twin = bar_row(next(b for b in bars_world._build(_TIME) if b.closed), _TIME, generation=0)
    twin = {**twin, "ts": gap, "close_ts": gap + _MIN - 1}
    twin["row_checksum"] = row_checksum(twin)
    body = _klines([r for r in corpus if r.ts_us != gap],
                   [Range(0, gap), Range(gap + _MIN, 2**62)], tape=[twin])  # fmt: skip
    assert iso_us(gap) in {b["t"] for b in body["bars"]}
    assert body["meta"]["coverage_holes"] == []  # klines always sends the key
