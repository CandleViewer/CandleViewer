"""`SqlAlchemyRecorderRepository.recording_gaps` (E26-T02): gap rows as `RecordedGap`s.

The SQL itself (window, stream filter, order and limit) runs against real Postgres in
`tests/integration/storage/test_recorder_repository.py`; here the bound query and the
refusals the port promises before any storage read.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa

from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import (
    REPLAYABLE_STREAMS,
    RecordedGap,
    RecordedQueryRejected,
    RecordingGapReader,
)
from candleviewer.storage.testing import StaticGapReader
from tests.unit.storage.test_recorder_repository_unit import _repo

H0 = 1_790_812_800_000_000  # 2026-10-01 00:00 UTC
WINDOW = TimeRange(start_us=H0, end_us=H0 + 10_000_000)
ROW = {
    "stream": "funding",  # the Postgres `stream_kind` spelling
    "gap_start": datetime(2026, 10, 1, 0, 0, 5, tzinfo=UTC),
    "gap_end": datetime(2026, 10, 1, 0, 0, 9, tzinfo=UTC),
    "cause": "ws_disconnect",
}


async def test_gap_rows_become_recorded_gaps_read_over_the_window_streams_and_limit() -> None:
    repo, rel = _repo([ROW])

    streams = (StreamKind.TRADES, StreamKind.FUNDING_RATES)
    got = await repo.recording_gaps("BTCUSDT", WINDOW, streams=streams, limit=8_193)

    assert isinstance(repo, RecordingGapReader)
    assert got == [
        RecordedGap(
            "BTCUSDT", StreamKind.FUNDING_RATES, H0 + 5_000_000, H0 + 9_000_000, "ws_disconnect"
        )
    ]
    sql, params = rel.calls[-1]
    assert params == {
        "symbol": "BTCUSDT",
        "lo": datetime(2026, 10, 1, tzinfo=UTC),
        "hi": datetime(2026, 10, 1, 0, 0, 10, tzinfo=UTC),
        "streams": ["funding", "trades"],
        "limit": 8_193,
    }
    assert "stream = ANY(CAST(:streams AS stream_kind[]))" in sql
    assert sql.endswith("ORDER BY gap_start, id LIMIT :limit")


@pytest.mark.parametrize("limit", [0, -1, True])
async def test_a_limit_below_one_is_refused_before_the_query(limit: int) -> None:
    repo, rel = _repo([ROW])

    with pytest.raises(RecordedQueryRejected):
        await repo.recording_gaps("BTCUSDT", WINDOW, streams=(StreamKind.TRADES,), limit=limit)

    assert rel.calls == []


@pytest.mark.parametrize("recorded", [(), (StreamKind.TRADES,)], ids=["alone", "among-recorded"])
async def test_a_stream_that_is_not_recorded_is_refused_before_the_query(
    recorded: tuple[StreamKind, ...],
) -> None:
    repo, rel = _repo([ROW])
    derived = next(s for s in StreamKind if s not in REPLAYABLE_STREAMS)

    with pytest.raises(RecordedQueryRejected):
        await repo.recording_gaps("BTCUSDT", WINDOW, streams=(*recorded, derived), limit=10)

    assert rel.calls == []


class _DriverError(Exception):
    """A DBAPI error as asyncpg raises it: a SQLSTATE, and a message naming the server."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__('connection to server at "10.0.0.5", port 5432 failed')
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    ("failure", "sqlstate"),
    [
        (
            sa.exc.OperationalError("SELECT ...", {"symbol": "BTCUSDT"}, _DriverError("08006")),
            "08006",
        ),
        (sa.exc.ProgrammingError("SELECT ...", {}, _DriverError("42P01")), "42P01"),
        (sa.exc.InterfaceError("SELECT ...", {}, Exception("closed: 10.0.0.5:5432")), None),
        (sa.exc.InvalidRequestError("pool at 10.0.0.5:5432 is closed"), None),
        (ConnectionRefusedError(111, "Connect call failed ('10.0.0.5', 5432)"), None),
    ],
    ids=["operational", "programming", "interface-no-sqlstate", "not-dbapi", "socket"],
)
async def test_a_database_failure_is_a_typed_error_that_names_no_server(
    failure: Exception, sqlstate: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """24 Sec.13.7: an unreadable gap table fails the replay as one typed storage error, with
    only the SQLSTATE: never the driver's text, whose message may name the server (RP-I02)."""
    repo, _ = _repo([ROW])

    async def fail(*_: object) -> list[dict[str, Any]]:
        raise failure

    monkeypatch.setattr(repo, "_all", fail)

    with pytest.raises(StorageQueryFailed) as caught:
        await repo.recording_gaps("BTCUSDT", WINDOW, streams=(StreamKind.TRADES,), limit=10)

    assert caught.value.sqlstate == sqlstate
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "10.0.0.5" not in str(caught.value)


async def test_a_cancelled_gap_read_raises_the_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _ = _repo([ROW])

    async def cancelled(*_: object) -> list[dict[str, Any]]:
        raise asyncio.CancelledError

    monkeypatch.setattr(repo, "_all", cancelled)

    with pytest.raises(asyncio.CancelledError):
        await repo.recording_gaps("BTCUSDT", WINDOW, streams=(StreamKind.TRADES,), limit=10)


def test_the_adapter_and_the_fake_take_the_same_keyword_only_arguments() -> None:
    """One port, two implementations (conformance): the merge calls both the same way."""
    repo, _ = _repo([])

    def shape(method: Callable[..., object]) -> list[tuple[str, object]]:
        return [(p.name, p.kind) for p in inspect.signature(method).parameters.values()]

    assert shape(repo.recording_gaps) == shape(StaticGapReader().recording_gaps)
    assert [
        n for n, kind in shape(repo.recording_gaps) if kind is inspect.Parameter.KEYWORD_ONLY
    ] == [
        "streams",
        "limit",
    ]
