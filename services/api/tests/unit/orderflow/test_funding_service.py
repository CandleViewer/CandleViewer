from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from decimal import Decimal

import pytest

from candleviewer.domain.funding import (
    FundingIntervalUnknown,
    FundingSettlement,
    PredictedFunding,
    PredictedFundingRefused,
    SettledFunding,
    settle,
)
from candleviewer.orderflow.funding import (
    FundingInvalidRequest,
    FundingService,
    FundingSymbolUnknown,
    TimeWindow,
    decode_cursor,
    encode_cursor,
)
from candleviewer.storage.models import TimeRange
from candleviewer.storage.questdb.funding_store import InMemoryFundingStore

NOW_S = 1_700_100_000.0
BASE_US = 1_700_000_000_000_000


@dataclass(frozen=True)
class _Inst:
    funding_interval_min: int


@dataclass(frozen=True)
class _Tick:
    funding_rate: Decimal | None
    next_funding_time: int | None
    ts_event: int = BASE_US


class _Tickers:
    def __init__(self, tick: _Tick | None) -> None:
        self.tick = tick

    def latest(self, symbol: str) -> _Tick | None:
        return self.tick


class _Fetcher:
    """Serves rows newest-first honouring window + limit like the upstream."""

    def __init__(self, rows: list[FundingSettlement]) -> None:
        self.rows = sorted(rows, key=lambda r: -r.ts_us)
        self.calls = 0

    async def __call__(
        self, symbol: str, start_us: int, end_us: int, limit: int
    ) -> list[FundingSettlement]:
        self.calls += 1
        return [r for r in self.rows if start_us <= r.ts_us <= end_us][:limit]


def _service(
    store: InMemoryFundingStore,
    *,
    interval: int | None = 240,
    fetcher: _Fetcher | None = None,
    tick: _Tick | None = None,
) -> FundingService:
    return FundingService(
        store=store,
        fetcher=fetcher,
        instruments=lambda s: None if interval is None else _Inst(interval),
        tickers=lambda: _Tickers(tick),
        clock_s=lambda: NOW_S,
    )


def _settlements(n: int, step_us: int = 14_400_000_000) -> list[FundingSettlement]:
    return [
        FundingSettlement(BASE_US + i * step_us, "BTCUSDT", Decimal("0.0001")) for i in range(n)
    ]


async def _series(svc: FundingService, **kw: object) -> object:
    params: dict[str, object] = {"start_us": None, "end_us": None, "limit": 10, "cursor": None}
    params.update(kw)
    return await svc.series("BTCUSDT", **params)  # type: ignore[arg-type]


async def test_backfill_pages_to_completion_and_rerun_writes_no_duplicates() -> None:
    store, rows = InMemoryFundingStore(), _settlements(450)
    fetcher = _Fetcher(rows)
    svc = _service(store, fetcher=fetcher)
    window = TimeWindow(rows[0].ts_us, rows[-1].ts_us)
    assert await svc.backfill("BTCUSDT", window) == 450
    assert len(store) == 450 and fetcher.calls == 3
    await svc.backfill("BTCUSDT", window)
    assert len(store) == 450


async def test_backfill_annualises_with_instrument_interval_not_480() -> None:
    store, rows = InMemoryFundingStore(), _settlements(2)
    await _service(store, interval=240, fetcher=_Fetcher(rows)).backfill(
        "BTCUSDT", TimeWindow(rows[0].ts_us, rows[-1].ts_us)
    )
    got = await store.read_settled("BTCUSDT", TimeRange(start_us=0, end_us=2**62), 10)
    assert {r.interval_min for r in got} == {240}
    assert got[0].annualised_pct == Decimal("0.0001") * (Decimal(525600) / 240) * 100


async def test_backfill_window_boundary_rows_are_included_and_outside_excluded() -> None:
    store, rows = InMemoryFundingStore(), _settlements(3)
    await _service(store, fetcher=_Fetcher(rows)).backfill(
        "BTCUSDT", TimeWindow(rows[1].ts_us, rows[2].ts_us)
    )
    assert len(store) == 2


async def test_backfill_unknown_interval_raises_and_writes_nothing() -> None:
    store = InMemoryFundingStore()
    svc = _service(store, interval=None, fetcher=_Fetcher(_settlements(1)))
    with pytest.raises(FundingIntervalUnknown):
        await svc.backfill("BTCUSDT", TimeWindow(0, 2**60))
    assert len(store) == 0


async def test_backfill_without_fetcher_raises() -> None:
    with pytest.raises(Exception, match="fetcher"):
        await _service(InMemoryFundingStore()).backfill("BTCUSDT", TimeWindow(0, 1))


async def test_backfill_fetch_error_propagates() -> None:
    class _Boom:
        async def __call__(self, *a: object) -> list[FundingSettlement]:
            raise RuntimeError("upstream")

    svc = FundingService(
        store=InMemoryFundingStore(),
        fetcher=_Boom(),  # type: ignore[arg-type]  # minimal stub
        instruments=lambda s: _Inst(480),
        tickers=lambda: None,
    )
    with pytest.raises(RuntimeError):
        await svc.backfill("BTCUSDT", TimeWindow(0, 1))


async def test_store_refuses_predicted_and_forged_rows() -> None:
    store = InMemoryFundingStore()
    predicted = PredictedFunding(1, "BTCUSDT", Decimal("0.0001"))
    with pytest.raises(PredictedFundingRefused):
        await store.write_settled([predicted])  # type: ignore[list-item]  # the point of the test
    forged = SettledFunding(1, "BTCUSDT", Decimal(1), 480, Decimal(1), source="ticker")
    with pytest.raises(PredictedFundingRefused):
        await store.write_settled([forged])
    assert len(store) == 0


async def test_series_flags_predicted_and_serves_next_funding_time() -> None:
    store = InMemoryFundingStore()
    await store.write_settled([settle("BTCUSDT", BASE_US, Decimal("0.0001"), 240)])
    tick = _Tick(Decimal("0.00015"), BASE_US + 14_400_000_000)
    series = await _series(_service(store, tick=tick))
    assert series.funding_interval_minutes == 240  # type: ignore[attr-defined]
    predicted = series.predicted  # type: ignore[attr-defined]
    assert predicted is not None and predicted.predicted and predicted.estimated
    assert series.next_funding_time_us == BASE_US + 14_400_000_000  # type: ignore[attr-defined]
    assert len(series.settled) == 1 and not series.has_more  # type: ignore[attr-defined]


async def test_series_predicted_absent_returns_no_item() -> None:
    series = await _series(_service(InMemoryFundingStore(), tick=_Tick(None, 5)))
    assert series.predicted is None and series.next_funding_time_us == 5  # type: ignore[attr-defined]
    bare = await _series(_service(InMemoryFundingStore(), tick=None))
    assert bare.predicted is None  # type: ignore[attr-defined]


async def test_predicted_without_next_time_uses_event_ts() -> None:
    svc = _service(InMemoryFundingStore(), tick=_Tick(Decimal("0.1"), None, ts_event=77))
    predicted, next_us = svc.predicted("BTCUSDT")
    assert predicted is not None and predicted.ts_us == 77 and next_us is None


async def test_series_cursor_pagination_covers_all_rows_once() -> None:
    store = InMemoryFundingStore()
    rows = [settle("BTCUSDT", BASE_US + i * 10**9, Decimal("0.0001"), 240) for i in range(5)]
    await store.write_settled(rows)
    svc = _service(store, tick=_Tick(Decimal("0.1"), None))
    seen: list[int] = []
    cursor: str | None = None
    while True:
        page = await _series(svc, limit=2, cursor=cursor)
        seen += [r.ts_us for r in page.settled]  # type: ignore[attr-defined]
        if not page.has_more:  # type: ignore[attr-defined]
            assert page.predicted is not None  # type: ignore[attr-defined]
            break
        assert page.predicted is None  # type: ignore[attr-defined]
        cursor = page.next_cursor  # type: ignore[attr-defined]
    assert seen == [r.ts_us for r in rows]


def _forged_cursor(t: object) -> str:
    raw = json.dumps({"s": "BTCUSDT", "t": t, "i": int(NOW_S)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"limit": 0}, "validation_failed"),
        ({"limit": 501}, "validation_failed"),
        ({"start_us": 10, "end_us": 5}, "invalid_time_range"),
        ({"start_us": 0, "end_us": 401 * 86_400 * 1_000_000}, "invalid_time_range"),
        ({"cursor": "!!notbase64"}, "invalid_cursor"),
        ({"cursor": "a" * 513}, "invalid_cursor"),
        ({"cursor": _forged_cursor(2**63)}, "invalid_cursor"),
        ({"cursor": _forged_cursor(-1)}, "invalid_cursor"),
        ({"cursor": _forged_cursor("12")}, "invalid_cursor"),
    ],
)
async def test_series_rejects_out_of_bounds_before_querying(
    kw: dict[str, object], code: str
) -> None:
    class _NoQuery(InMemoryFundingStore):
        async def read_settled(self, *a: object) -> list[SettledFunding]:  # type: ignore[override]
            raise AssertionError("storage queried for an invalid request")

    with pytest.raises(FundingInvalidRequest) as exc:
        await _series(_service(_NoQuery()), **kw)
    assert exc.value.code == code


async def test_series_unknown_symbol() -> None:
    with pytest.raises(FundingSymbolUnknown):
        await _series(_service(InMemoryFundingStore(), interval=None))


def test_cursor_roundtrip_expiry_and_symbol_binding() -> None:
    c = encode_cursor("BTCUSDT", 123, now_s=NOW_S)
    assert decode_cursor(c, symbol="BTCUSDT", now_s=NOW_S + 10) == 123
    for kwargs in (
        {"symbol": "BTCUSDT", "now_s": NOW_S + 3601},
        {"symbol": "ETHUSDT", "now_s": NOW_S},
        {"symbol": "BTCUSDT", "now_s": NOW_S - 3600},
    ):
        with pytest.raises(FundingInvalidRequest):
            decode_cursor(c, **kwargs)  # type: ignore[arg-type]
    forged = json.dumps({"s": "BTCUSDT", "t": "x", "i": 1}).encode()
    for bad in (base64.urlsafe_b64encode(forged).decode(), ""):
        with pytest.raises(FundingInvalidRequest):
            decode_cursor(bad, symbol="BTCUSDT", now_s=NOW_S)


def _counter(metric: object, **labels: str) -> float:
    return metric.labels(**labels)._value.get()  # type: ignore[attr-defined,no-any-return]


async def test_backfill_counts_rejected_rows_persists_good_ones_and_continues() -> None:
    from candleviewer.domain.funding import FundingPage
    from candleviewer.orderflow.funding_metrics import deriv_upstream_schema_rejected_total

    good = _settlements(3)

    class _Mixed:
        async def __call__(self, *a: object) -> FundingPage:
            return FundingPage(good, ["rate_implausible"])

    store = InMemoryFundingStore()
    svc = FundingService(
        store=store,
        fetcher=_Mixed(),  # type: ignore[arg-type]
        instruments=lambda s: _Inst(240),
        tickers=lambda: _Tickers(None),
        clock_s=lambda: NOW_S,
    )
    before = _counter(
        deriv_upstream_schema_rejected_total, topic="funding_history", reason="rate_implausible"
    )
    written = await svc.backfill("BTCUSDT", TimeWindow(BASE_US, BASE_US + 3 * 14_400_000_000))
    after = _counter(
        deriv_upstream_schema_rejected_total, topic="funding_history", reason="rate_implausible"
    )
    assert written == 3 and after == before + 1


async def test_backfill_envelope_rejection_is_counted_and_reraised() -> None:
    from candleviewer.domain.funding import FundingRowRejected
    from candleviewer.orderflow.funding_metrics import deriv_upstream_schema_rejected_total

    class _Bad:
        async def __call__(self, *a: object) -> list[FundingSettlement]:
            raise FundingRowRejected("funding history: missing list")

    store = InMemoryFundingStore()
    svc = FundingService(
        store=store,
        fetcher=_Bad(),  # type: ignore[arg-type]
        instruments=lambda s: _Inst(240),
        tickers=lambda: _Tickers(None),
        clock_s=lambda: NOW_S,
    )
    before = _counter(
        deriv_upstream_schema_rejected_total, topic="funding_history", reason="envelope"
    )
    with pytest.raises(FundingRowRejected):
        await svc.backfill("BTCUSDT", TimeWindow(BASE_US, BASE_US + 14_400_000_000))
    assert (
        _counter(deriv_upstream_schema_rejected_total, topic="funding_history", reason="envelope")
        == before + 1
    )


async def test_backfill_empty_page_stops_and_writes_nothing() -> None:
    store = InMemoryFundingStore()
    written = await _service(store, fetcher=_Fetcher([])).backfill(
        "BTCUSDT", TimeWindow(BASE_US, BASE_US + 14_400_000_000)
    )
    assert written == 0


def test_symbol_label_is_bounded_and_malformed_maps_to_other() -> None:
    from candleviewer.orderflow.funding_metrics import symbol_label

    assert symbol_label("bad/sym") == "other"
    assert symbol_label("BTCUSDT") == symbol_label("BTCUSDT") == "BTCUSDT"


@pytest.mark.parametrize("tail", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_symbol_label_a_symbol_ending_in_a_newline_maps_to_other(
    tail: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#3539: `$` also matches before a final newline, so `match` made it a label of its own."""
    from candleviewer.orderflow import funding_metrics

    monkeypatch.setattr(funding_metrics, "_seen", set())  # the cap cannot refuse; the pattern can
    assert funding_metrics.symbol_label("BTCUSDT" + tail) == "other"
    assert funding_metrics.symbol_label("BTCUSDT") == "BTCUSDT"
