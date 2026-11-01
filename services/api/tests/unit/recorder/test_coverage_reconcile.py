"""E16-FR-03 (#1739, threat model R-T1): coverage is reconciled with the data actually stored, so
a deleted or shrunk gap row cannot make absent data read as present. Presence is faked; fake
clocks, no I/O, no sleeps."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

from candleviewer.api.market_coverage import _gap
from candleviewer.recorder.coverage import (
    PRESENCE_TTL_US,
    UNVERIFIED_CAUSE,
    CoverageService,
    StreamCoverage,
    WatermarkReader,
)
from candleviewer.recorder.integrity import mark_kline_backfill
from candleviewer.recorder.metrics import recorder_coverage_reconcile_mismatch_total
from candleviewer.recorder.sessions import to_dt, to_us
from candleviewer.storage.models import StreamKind
from candleviewer.storage.questdb.stored_presence import StoredPresenceTimeout
from tests.unit.recorder._session_fakes import MemRecorderStore, UsClock

S = 1_000_000
STREAMS = ["trades", "orderbook_delta", "tickers", "liquidations"]


def _us(d: int, hh: int = 0, mm: int = 0) -> int:
    return to_us(datetime(2026, 9, d, hh, mm, tzinfo=UTC))


WATERMARK = _us(7)
NOW = _us(14, 10)
LO, HI = _us(1), _us(14)


class _Mark:
    archived_through_us = WATERMARK


class _FakeMarks:
    async def get(self, symbol: str, stream: StreamKind) -> _Mark:
        return _Mark()


def _marks() -> WatermarkReader:
    return cast(WatermarkReader, _FakeMarks())  # only `get` is read, as `CoverageService` says


class FakePresence:
    """Rows everywhere except `missing` (per stream); `fail` raises instead."""

    def __init__(self, missing: dict[str, list[tuple[int, int]]] | None = None) -> None:
        self.missing = missing or {}
        self.fail: BaseException | None = None
        self.calls: list[tuple[str, str, int, int]] = []

    async def stored_spans(
        self, symbol: str, stream: str, lo: int, hi: int
    ) -> list[tuple[int, int]]:
        self.calls.append((symbol, stream, lo, hi))
        if self.fail is not None:
            raise self.fail
        out, at = [], lo
        for a, b in sorted(self.missing.get(stream, [])):
            if a > at:
                out.append((at, a))
            at = max(at, b)
        if at < hi:
            out.append((at, hi))
        return out


class _Archive:
    async def archive_windows(self, symbol: str, lo: int, hi: int) -> list[tuple[int, int]]:
        return [(_us(10, 1), _us(10, 2))]


async def _store(*gaps: tuple[str, int, int]) -> tuple[MemRecorderStore, str]:
    store = MemRecorderStore()
    sid = await store.open_session_at(
        recorded_symbol_id="r", symbol="BTCUSDT", streams=STREAMS, orderbook_depth=200,
        ws_endpoint="x", started_at=to_dt(LO),
    )  # fmt: skip
    await store.close_session_at(sid, reason="stopped", ended_at=to_dt(HI))
    await store.record_gap(
        session_id=sid, symbol="BTCUSDT", stream="trades", gap_start=to_dt(_us(4, 2)),
        gap_end=to_dt(_us(4, 3)), cause="ws_disconnect",
    )  # fmt: skip
    for stream, a, b in gaps:
        await store.record_gap(
            session_id=sid, symbol="BTCUSDT", stream=stream, gap_start=to_dt(a),
            gap_end=to_dt(b), cause="ws_disconnect",
        )  # fmt: skip
    return store, sid


def _svc(store: MemRecorderStore, presence: Any = None, **kw: Any) -> CoverageService:
    clock = kw.pop("clock", UsClock(NOW))
    return CoverageService(store, now_us=clock, watermarks=_marks(), presence=presence, **kw)


def _by(report: list[StreamCoverage]) -> dict[str, StreamCoverage]:
    return {sc.stream: sc for sc in report}


def _mismatches(stream: str) -> float:
    return float(recorder_coverage_reconcile_mismatch_total.labels(stream=stream)._value.get())


async def test_stored_data_that_matches_changes_nothing() -> None:
    """Golden: the pre-change output, with a hot gap row whose window holds no rows."""
    gap = ("orderbook_delta", _us(10, 1), _us(10, 2))
    store, _ = await _store(gap)
    baseline = await _svc(store).coverage("BTCUSDT", STREAMS, LO, HI)
    presence = FakePresence({"orderbook_delta": [(gap[1], gap[2])]})
    assert await _svc(store, presence).coverage("BTCUSDT", STREAMS, LO, HI) == baseline
    assert {c[1] for c in presence.calls} == {"trades", "orderbook_delta", "tickers"}


async def test_a_deleted_gap_row_cannot_make_absent_data_read_as_covered() -> None:
    store, _ = await _store()  # the row for 10th 01:00-02:00 was deleted
    hole = (_us(10, 1), _us(10, 2))
    before = _mismatches("orderbook_delta")
    got = _by(
        await _svc(store, FakePresence({"orderbook_delta": [hole]})).coverage(
            "BTCUSDT", STREAMS, LO, HI
        )
    )["orderbook_delta"]
    assert all(not (i.lo < hole[1] and i.hi > hole[0]) for i in got.intervals)
    assert [(g.lo, g.hi, g.cause) for g in got.gaps] == [(*hole, UNVERIFIED_CAUSE)]
    assert _mismatches("orderbook_delta") == before + 1
    assert "reason" not in _gap(*hole, UNVERIFIED_CAUSE)  # the route omits the reason


async def test_a_shrunk_gap_row_reports_the_rest_of_the_hole() -> None:
    store, _ = await _store(("tickers", _us(10, 1), _us(10, 1, 10)))
    got = _by(
        await _svc(store, FakePresence({"tickers": [(_us(10, 1), _us(10, 2))]})).coverage(
            "BTCUSDT", STREAMS, LO, HI
        )
    )["tickers"]
    assert [(g.lo, g.hi, g.cause) for g in got.gaps] == [
        (_us(10, 1), _us(10, 1, 10), "ws_disconnect"),
        (_us(10, 1, 10), _us(10, 2), UNVERIFIED_CAUSE),
    ]
    assert all(not (i.lo < _us(10, 2) and i.hi > _us(10, 1)) for i in got.intervals)


async def test_an_absent_span_within_the_tolerance_is_not_a_gap() -> None:
    store, _ = await _store()
    short = {
        "orderbook_delta": [(_us(10, 1), _us(10, 1, 1))],
        "trades": [(_us(10), _us(10, 0, 10))],
    }
    got = _by(await _svc(store, FakePresence(short)).coverage("BTCUSDT", STREAMS, LO, HI))
    assert got["orderbook_delta"].gaps == () and len(got["trades"].gaps) == 1  # the cold ws gap


@pytest.mark.parametrize(
    "fail", [OSError("down"), StoredPresenceTimeout("slow")], ids=["down", "timeout"]
)
async def test_a_presence_failure_fails_closed_without_raising(fail: Exception) -> None:
    store, _ = await _store()
    presence = FakePresence()
    presence.fail = fail
    with capture_logs() as logs:
        got = _by(await _svc(store, presence).coverage("BTCUSDT", STREAMS, LO, HI))
    for stream in ("trades", "orderbook_delta", "tickers"):
        assert all(i.tier == "parquet" for i in got[stream].intervals)
        assert (WATERMARK, HI, UNVERIFIED_CAUSE) in [
            (g.lo, g.hi, g.cause) for g in got[stream].gaps
        ]
    assert any(e["event"] == "recorder_coverage_reconcile_failed" for e in logs)
    liquidations = [(i.lo, i.hi) for i in got["liquidations"].intervals]
    assert liquidations == [(LO, WATERMARK), (WATERMARK, HI)]  # not a reconciled stream


async def test_the_cold_tier_and_archive_windows_are_untouched() -> None:
    store, _ = await _store()
    everything = {"trades": [(LO, HI)]}
    svc = CoverageService(
        store, now_us=UsClock(NOW), watermarks=_marks(), archive=_Archive(),
        presence=FakePresence(everything),
    )  # fmt: skip
    (got,) = await svc.coverage("BTCUSDT", ["trades"], LO, HI)
    assert [(i.lo, i.hi, i.tier, i.source) for i in got.intervals] == [
        (LO, _us(4, 2), "parquet", "recorded"),
        (_us(4, 3), WATERMARK, "parquet", "recorded"),
        (_us(10, 1), _us(10, 2), "parquet", "archive"),  # the archive fills the absent window
    ]
    assert (WATERMARK, HI, UNVERIFIED_CAUSE) in [(g.lo, g.hi, g.cause) for g in got.gaps]


async def test_without_a_presence_port_the_output_is_as_before() -> None:
    store, _ = await _store()
    report = await _svc(store).coverage("BTCUSDT", STREAMS, LO, HI)
    assert all(g.cause != UNVERIFIED_CAUSE for sc in report for g in sc.gaps)
    assert [(i.lo, i.hi) for i in _by(report)["tickers"].intervals] == [
        (LO, WATERMARK),
        (WATERMARK, HI),
    ]


async def test_a_backfilled_kline_gap_stays_a_gap_when_reconciled() -> None:
    """ADR-0015 d7: bars never make a tick-level window covered."""
    store, _ = await _store(("trades", _us(10, 1), _us(10, 2)))

    async def backfill(symbol: str, lo: int, hi: int) -> int:
        return 3

    await mark_kline_backfill(store, backfill, "BTCUSDT", LO, HI)
    presence = FakePresence({"trades": [(_us(10, 1), _us(10, 2))]})
    (got,) = await _svc(store, presence).coverage("BTCUSDT", ["trades"], LO, HI)
    hot_gap = [g for g in got.gaps if g.lo == _us(10, 1)]
    assert [(g.hi, g.cause, g.backfilled) for g in hot_gap] == [(_us(10, 2), "ws_disconnect", True)]
    assert all(not (i.lo < _us(10, 2) and i.hi > _us(10, 1)) for i in got.intervals)


async def test_presence_is_cached_for_the_ttl_and_dropped_by_invalidate() -> None:
    store, _ = await _store()
    clock = UsClock(NOW)
    presence = FakePresence({"tickers": [(_us(10, 1), _us(10, 2))]})
    svc = _svc(store, presence, clock=clock)
    before = _mismatches("tickers")
    await svc.coverage("BTCUSDT", ["tickers"], LO, HI)
    await svc.coverage("BTCUSDT", ["tickers"], LO, HI)
    assert len(presence.calls) == 1 and _mismatches("tickers") == before + 1  # counted once
    svc.invalidate("BTCUSDT")
    await svc.coverage("BTCUSDT", ["tickers"], LO, HI)
    assert len(presence.calls) == 2
    clock.t += PRESENCE_TTL_US
    await svc.coverage("BTCUSDT", ["tickers"], LO, HI)
    assert len(presence.calls) == 3


async def test_a_cached_read_that_ended_early_is_not_reused_for_a_later_window() -> None:
    store, _ = await _store()
    presence = FakePresence()
    svc = _svc(store, presence)
    await svc.coverage("BTCUSDT", ["tickers"], LO, _us(10))
    (got,) = await svc.coverage("BTCUSDT", ["tickers"], LO, HI)
    assert len(presence.calls) == 2 and got.gaps == ()
