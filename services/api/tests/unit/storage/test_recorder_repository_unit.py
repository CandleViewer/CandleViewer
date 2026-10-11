"""Unit tests for `SqlAlchemyRecorderRepository` using a recording fake unit of work (E16-T01).

SQL semantics (constraints, resolution order) are covered by the docker-backed
`tests/integration/storage/test_recorder_repository.py`; here we pin the
parameter plumbing and result mapping of every public method.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from candleviewer.storage.repositories.recorder_sqlalchemy import (
    HARD_DEFAULT_RETAIN_DAYS,
    SqlAlchemyRecorderRepository,
)


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _Session:
    def __init__(self, owner: _Relational) -> None:
        self._owner = owner

    async def execute(self, stmt: Any, params: dict[str, Any]) -> _Result:
        self._owner.calls.append((str(stmt), params))
        return _Result(self._owner.rows)


class _Uow:
    def __init__(self, owner: _Relational) -> None:
        self.session = _Session(owner)

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class _Relational:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def unit_of_work(self) -> _Uow:
        return _Uow(self)


def _repo(
    rows: list[dict[str, Any]] | None = None,
) -> tuple[SqlAlchemyRecorderRepository, _Relational]:
    rel = _Relational(rows)
    return SqlAlchemyRecorderRepository(rel), rel  # type: ignore[arg-type]


async def test_list_and_get_pass_env() -> None:
    repo, rel = _repo([{"symbol": "BTCUSDT"}])
    assert await repo.list_recorded("live") == [{"symbol": "BTCUSDT"}]
    assert await repo.get_by_symbol("BTCUSDT", "live") == {"symbol": "BTCUSDT"}
    assert rel.calls[0][1] == {"env": "live"}
    assert rel.calls[1][1] == {"symbol": "BTCUSDT", "env": "live"}


async def test_get_by_symbol_none_when_absent() -> None:
    repo, _ = _repo([])
    assert await repo.get_by_symbol("ETHUSDT") is None


async def test_upsert_auto_serialises_ref_and_returns_id() -> None:
    repo, rel = _repo([{"id": "abc"}])
    got = await repo.upsert_auto("BTCUSDT", "chart_open", {"kind": "chart", "id": "c1"})
    assert got == "abc"
    assert json.loads(rel.calls[0][1]["ref"]) == {"kind": "chart", "id": "c1"}
    assert rel.calls[0][1]["reason"] == "chart_open"
    assert "ON CONFLICT" in rel.calls[0][0]


async def test_reason_ref_updates_are_single_statements() -> None:
    repo, rel = _repo([{"?column?": 1}])
    assert await repo.add_reason_ref("id1", {"kind": "chart", "id": "c1"}) is True
    assert await repo.remove_reason_ref("id1", {"kind": "chart", "id": "c1"}) is True
    assert len(rel.calls) == 2
    repo2, _ = _repo([])
    assert await repo2.add_reason_ref("x", {}) is False
    assert await repo2.remove_reason_ref("x", {}) is False


async def test_soft_remove_sets_removed_at_never_deletes() -> None:
    repo, rel = _repo([{"x": 1}])
    assert await repo.soft_remove("id1") is True
    sql = rel.calls[0][0]
    assert "removed_at = now()" in sql and "DELETE" not in sql.upper()


async def test_open_and_close_session() -> None:
    repo, rel = _repo([{"x": 1}])
    sid = await repo.open_session(
        recorded_symbol_id="rs1",
        symbol="BTCUSDT",
        streams=["trades", "tickers"],
        orderbook_depth=200,
        ws_endpoint="wss://example.invalid",
    )
    assert rel.calls[0][1]["streams"] == ["trades", "tickers"]
    assert rel.calls[0][1]["id"] == sid
    assert await repo.close_session(sid, "manual_stop") is True
    assert rel.calls[1][1] == {"id": sid, "reason": "manual_stop"}


async def test_record_gap_returns_id() -> None:
    repo, rel = _repo([{"id": 7}])
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    gid = await repo.record_gap(
        session_id="s1",
        symbol="BTCUSDT",
        stream="trades",
        gap_start=t0,
        gap_end=t1,
        cause="ws_disconnect",
    )
    assert gid == 7
    assert rel.calls[0][1]["cause"] == "ws_disconnect"


@pytest.mark.parametrize(
    ("rows", "expected"),
    [([], HARD_DEFAULT_RETAIN_DAYS), ([{"retain_days": 3}], 3), ([{"retain_days": None}], None)],
)
async def test_resolve_policy_maps_rows(rows: list[dict[str, Any]], expected: int | None) -> None:
    repo, _ = _repo(rows)
    assert await repo.resolve_policy("ETHUSDT", "trades") == expected


async def test_resolve_policy_sql_orders_pinned_then_symbol_then_default() -> None:
    repo, rel = _repo([])
    await repo.resolve_policy("ETHUSDT", "trades")
    sql = rel.calls[0][0]
    assert "pinned" in sql and "ORDER BY ord LIMIT 1" in sql


async def test_add_session_counters_targets_live_session_as_deltas() -> None:
    repo, rel = _repo([{"?column?": 1}])
    ok = await repo.add_session_counters(
        "BTCUSDT", messages_received=5, messages_dropped=1, bytes_written=900, reconnect_count=0
    )
    sql, params = rel.calls[0]
    assert ok and "messages_received = messages_received + :rx" in sql
    assert "state IN ('starting','recording','degraded')" in sql
    assert params == {"symbol": "BTCUSDT", "rx": 5, "dropped": 1, "bytes": 900, "reconnects": 0}


async def test_record_live_gap_false_without_live_session() -> None:
    repo, rel = _repo([])
    start = datetime(2026, 10, 1, tzinfo=UTC)
    ok = await repo.record_live_gap(
        symbol="BTCUSDT",
        stream="trades",
        gap_start=start,
        gap_end=start.replace(second=1),
        cause="backpressure_drop",
    )
    sql, params = rel.calls[0]
    assert not ok and "INSERT INTO recording_gaps" in sql and "CAST(:stream AS stream_kind)" in sql
    assert params["cause"] == "backpressure_drop"


async def test_e16_t04_session_and_gap_methods_plumb_params() -> None:
    """E16-T04: explicit-time open/close, state mirror, event bounds, windows, backfill flag."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    repo, rel = _repo([{"id": "s", "first": t0}])
    sid = await repo.open_session_at(recorded_symbol_id="rs", symbol="BTCUSDT",
                                     streams=["trades"], orderbook_depth=1, ws_endpoint="w",
                                     started_at=t0)  # fmt: skip
    assert rel.calls[-1][1]["started"] == t0 and rel.calls[-1][1]["id"] == sid
    assert await repo.close_session_at("s", reason="process_restart", ended_at=t1)
    assert rel.calls[-1][1] == {"id": "s", "ended": t1, "reason": "process_restart",
                                "state": "stopped"}  # fmt: skip
    assert await repo.close_session_at("s", reason="error", ended_at=t1, error=True)
    assert rel.calls[-1][1]["state"] == "error"
    assert await repo.set_session_state("s", "degraded")
    assert await repo.touch_session_events("s", first=t0, last=t1)
    assert "COALESCE(first_event_ts" in rel.calls[-1][0]
    assert await repo.list_live_sessions() == [{"id": "s", "first": t0}]
    assert await repo.sessions_in("BTCUSDT", t0, t1)
    assert await repo.gaps_in("BTCUSDT", t0, t1)
    assert rel.calls[-1][1] == {"symbol": "BTCUSDT", "lo": t0, "hi": t1}
    assert await repo.earliest_first_event("BTCUSDT") == t0
    assert await repo.mark_gap_backfilled(7, "kline")
    sql = rel.calls[-1][0]
    assert "backfilled = true" in sql and "gap_start" not in sql.split("WHERE")[0]
    assert "DELETE" not in " ".join(c[0].upper() for c in rel.calls)


async def test_earliest_first_event_none_when_no_sessions() -> None:
    repo, _ = _repo([{"first": None}])
    assert await repo.earliest_first_event("BTCUSDT") is None
