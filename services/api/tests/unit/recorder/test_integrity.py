"""E16-T04 daily integrity job: sequence continuity + stored-vs-session reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from candleviewer.observability.health_probes import SystemEvent
from candleviewer.recorder.integrity import IntegrityJob
from candleviewer.recorder.sessions import to_dt, to_us
from tests.unit.recorder._session_fakes import MemRecorderStore, UsClock

S = 1_000_000
NOW = to_us(datetime(2026, 9, 14, tzinfo=UTC))


class _Data:
    def __init__(self, spans: list[tuple[int, int]], breaks: list[tuple[int, int]]) -> None:
        self.spans, self.breaks = spans, breaks

    async def stored_spans(
        self, symbol: str, stream: str, lo: int, hi: int
    ) -> list[tuple[int, int]]:
        return self.spans

    async def seq_breaks(self, symbol: str, lo: int, hi: int) -> list[tuple[int, int]]:
        return self.breaks


class _Events:
    def __init__(self, fail: bool = False) -> None:
        self.events: list[SystemEvent] = []
        self.fail = fail

    async def write(self, event: SystemEvent) -> None:
        if self.fail:
            raise OSError("pg down")
        self.events.append(event)


async def _store() -> tuple[MemRecorderStore, str]:
    store = MemRecorderStore()
    sid = await store.open_session_at(
        recorded_symbol_id="r", symbol="BTCUSDT", streams=["trades", "orderbook_delta"],
        orderbook_depth=1, ws_endpoint="x", started_at=to_dt(NOW - 3600 * S),
    )  # fmt: skip
    return store, sid


async def test_integrity_clean_day_has_no_anomalies() -> None:
    store, sid = await _store()
    await store.record_gap(session_id=sid, symbol="BTCUSDT", stream="trades",
                           gap_start=to_dt(NOW - 60 * S), gap_end=to_dt(NOW - 30 * S),
                           cause="ws_disconnect")  # fmt: skip
    data = _Data([(NOW - 3600 * S, NOW - 60 * S), (NOW - 30 * S, NOW)], [])
    ev = _Events()
    rep = await IntegrityJob(store, data, ev, now_us=UsClock(NOW)).run(["BTCUSDT"], ["trades"])
    assert rep.checked == 1 and rep.anomalies == [] and ev.events == []


async def test_integrity_unexplained_hole_and_outside_data_raise_system_event() -> None:
    store, _ = await _store()
    data = _Data([(NOW - 7200 * S, NOW - 3000 * S), (NOW - 2000 * S, NOW)], [])
    ev = _Events()
    rep = await IntegrityJob(store, data, ev, now_us=UsClock(NOW)).run(["BTCUSDT"], ["trades"])
    assert [a["anomaly"] for a in rep.anomalies] == ["data_outside_session", "unexplained_hole"]
    assert {e.kind for e in ev.events} == {"recorder.integrity_anomaly"}
    assert all(e.severity == "critical" for e in ev.events)


async def test_integrity_seq_break_becomes_gap_or_event_and_is_idempotent() -> None:
    store, _ = await _store()
    breaks = [(NOW - 100 * S, NOW - 99 * S), (NOW - 9000 * S, NOW - 8999 * S), (5, 5)]
    data = _Data([(NOW - 3600 * S, NOW)], breaks)
    ev = _Events(fail=True)  # an event-write failure is logged, never raised
    inval: list[str] = []
    job = IntegrityJob(store, data, ev, now_us=UsClock(NOW), on_write=inval.append)
    rep = await job.run(["BTCUSDT"], ["orderbook_delta"])
    assert rep.gaps_written == 1 and inval == ["BTCUSDT"]
    assert store.gap_windows("seq_jump") == [
        ("orderbook_delta", NOW - 100 * S, NOW - 99 * S, "seq_jump")
    ]
    assert [a["anomaly"] for a in rep.anomalies] == ["seq_break_outside_session"]
    rep2 = await job.run(["BTCUSDT"], ["orderbook_delta"])  # now explained by the gap row
    assert rep2.gaps_written == 0


async def test_integrity_a_longer_break_with_the_same_start_is_still_written() -> None:
    """#2188 S4b0 (lens F1): a row of the same start that ends earlier does not cover a longer
    break, so its remainder is written, never dropped as "already written"."""
    store, sid = await _store()
    a = NOW - 100 * S
    await store.record_gap(session_id=sid, symbol="BTCUSDT", stream="orderbook_delta",
                           gap_start=to_dt(a), gap_end=to_dt(a + S), cause="seq_jump")  # fmt: skip
    data = _Data([(NOW - 3600 * S, NOW)], [(a, a + 3 * S)])
    rep = await IntegrityJob(store, data, _Events(), now_us=UsClock(NOW)).run(
        ["BTCUSDT"], ["orderbook_delta"]
    )
    assert rep.gaps_written == 1
    assert [w[1:3] for w in store.gap_windows("seq_jump")] == [(a, a + S), (a, a + 3 * S)]


class _Covered(MemRecorderStore):
    """A store that already holds a row covering every window it is asked for."""

    async def record_gap(self, **kw: Any) -> int | None:
        return None


async def test_integrity_a_gap_the_store_already_holds_is_not_counted() -> None:
    """#2188 S4b0 (lens F2): `record_gap` answering no id writes nothing, so nothing is counted
    and no coverage is invalidated."""
    store = _Covered()
    await store.open_session_at(
        recorded_symbol_id="r", symbol="BTCUSDT", streams=["orderbook_delta"],
        orderbook_depth=1, ws_endpoint="x", started_at=to_dt(NOW - 3600 * S),
    )  # fmt: skip
    data = _Data([(NOW - 3600 * S, NOW)], [(NOW - 100 * S, NOW - 99 * S)])
    inval: list[str] = []
    job = IntegrityJob(store, data, _Events(), now_us=UsClock(NOW), on_write=inval.append)
    rep = await job.run(["BTCUSDT"], ["orderbook_delta"])
    assert rep.gaps_written == 0 and inval == []
