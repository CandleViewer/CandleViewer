"""`QuestDbStoredPresence` (E16-FR-03, #1739): which hot-tier minutes hold rows, and the book's
update-id breaks. QuestDB is faked at `fetch_records`; no network, no exchange payloads."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

import asyncpg
import pytest

from candleviewer.domain.sql_names import EPOCH_NAIVE, ts_param
from candleviewer.recorder.coverage import StoredPresence
from candleviewer.recorder.integrity import StoredData
from candleviewer.recorder.models import STREAM_KINDS
from candleviewer.storage.questdb import stored_presence
from candleviewer.storage.questdb.stored_presence import (
    BUCKET_US,
    MAX_BUCKETS,
    MAX_SEQ_ROWS,
    PRESENCE_SQL,
    SEQ_SQL,
    QuestDbStoredPresence,
    StoredPresenceError,
    StoredPresenceTimeout,
    build_presence,
    build_seq,
    find_breaks,
    merge_buckets,
)

M = BUCKET_US
_TABLES = {
    "trades": "trades",
    "orderbook_delta": "orderbook_deltas",
    "orderbook_snapshot": "orderbook_snapshots",
    "tickers": "tickers",
    "klines": "klines",
    "liquidations": "liquidations",
    "open_interest": "open_interest",
    "funding": "funding_rates",
}


def _at(us: int) -> datetime:
    return EPOCH_NAIVE + timedelta(microseconds=us)


class FakeWire:
    def __init__(self, rows: Sequence[Mapping[str, object]] = ()) -> None:
        self.rows = list(rows)
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch_records(self, sql: str, *params: object) -> Sequence[Mapping[str, object]]:
        self.calls.append((sql, params))
        return self.rows


class FailingWire:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    async def fetch_records(self, sql: str, *params: object) -> Sequence[Mapping[str, object]]:
        raise self.exc


class StuckWire:
    async def fetch_records(self, sql: str, *params: object) -> Sequence[Mapping[str, object]]:
        await asyncio.Event().wait()
        return []


def test_every_recorder_stream_maps_to_one_literal_allowlisted_statement() -> None:
    assert set(PRESENCE_SQL) == STREAM_KINDS
    for stream, sql in PRESENCE_SQL.items():
        table = re.search(r"\bFROM (\w+) ", sql)
        assert table is not None and table[1] == _TABLES[stream]
        assert "symbol = $1 AND ts >= $2" in sql and "ts < $3" in sql
        assert "{" not in sql and "%" not in sql
        assert sql.endswith("SAMPLE BY 1m ALIGN TO CALENDAR")
    assert "{" not in SEQ_SQL and "%" not in SEQ_SQL


def test_the_symbol_and_time_bounds_are_binds_and_only_the_limit_is_inlined() -> None:
    sql, params = build_presence("BTCUSDT", "trades", 0, 10 * M)
    assert sql == PRESENCE_SQL["trades"] + " LIMIT 12"
    assert params == ("BTCUSDT", ts_param(0), ts_param(10 * M))
    sql, params = build_seq("BTCUSDT", 0, M)
    assert sql == f"{SEQ_SQL} LIMIT {MAX_SEQ_ROWS}" and params[0] == "BTCUSDT"


@pytest.mark.parametrize(
    ("symbol", "stream", "lo", "hi", "reason"),
    [
        ("BTCUSDT", "trades; DROP TABLE trades", 0, M, "not a recorded table"),
        ("btc'--", "trades", 0, M, "plain instrument code"),
        ("BTCUSDT", "trades", M, M, "lo < hi"),
        ("BTCUSDT", "trades", 0, MAX_BUCKETS * M, "more than"),
    ],
    ids=["stream", "symbol", "empty", "too-wide"],
)
def test_a_query_outside_the_allowlist_or_its_bounds_is_refused(
    symbol: str, stream: str, lo: int, hi: int, reason: str
) -> None:
    with pytest.raises(StoredPresenceError, match=reason):
        build_presence(symbol, stream, lo, hi)


def test_buckets_merge_when_adjacent_and_are_clipped_to_the_window() -> None:
    assert merge_buckets([0, M, 3 * M], M // 2, 3 * M + M // 2) == [
        (M // 2, 2 * M), (3 * M, 3 * M + M // 2)
    ]  # fmt: skip
    assert merge_buckets([5 * M], 0, M) == []


async def test_stored_spans_reads_the_buckets_that_hold_rows() -> None:
    wire = FakeWire([{"ts": _at(0), "n": 4}, {"ts": _at(M), "n": 1}, {"ts": _at(5 * M), "n": 9}])
    got = await QuestDbStoredPresence(wire).stored_spans("BTCUSDT", "tickers", 0, 10 * M)
    assert got == [(0, 2 * M), (5 * M, 6 * M)]
    assert wire.calls[0][0].startswith(PRESENCE_SQL["tickers"])


def test_breaks_are_per_depth_and_span_the_missing_updates() -> None:
    rows = [
        {"depth": 200, "update_id": 10, "prev_update_id": 9, "first_ts": _at(1)},
        {"depth": 50, "update_id": 7, "prev_update_id": 6, "first_ts": _at(2)},
        {"depth": 200, "update_id": 11, "prev_update_id": 10, "first_ts": _at(3)},
        {"depth": 50, "update_id": 8, "prev_update_id": 7, "first_ts": _at(4)},
        {"depth": 200, "update_id": 15, "prev_update_id": 14, "first_ts": _at(9)},  # 12..14 lost
    ]
    assert find_breaks(rows) == [(3, 9)]


async def test_seq_breaks_reads_the_grouped_updates() -> None:
    wire = FakeWire(
        [
            {"depth": 1, "update_id": 1, "prev_update_id": 0, "first_ts": _at(M)},
            {"depth": 1, "update_id": 5, "prev_update_id": 4, "first_ts": _at(2 * M)},
        ]
    )
    assert await QuestDbStoredPresence(wire).seq_breaks("BTCUSDT", 0, 3 * M) == [(M, 2 * M)]


async def test_a_seq_read_at_its_row_cap_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stored_presence, "MAX_SEQ_ROWS", 1)
    wire = FakeWire([{"depth": 1, "update_id": 1, "prev_update_id": 0, "first_ts": _at(M)}])
    with pytest.raises(StoredPresenceError, match="too many"):
        await QuestDbStoredPresence(wire).seq_breaks("BTCUSDT", 0, 3 * M)


@pytest.mark.parametrize(
    "exc",
    [OSError("connect to db.internal:8812 failed"), asyncpg.PostgresError("table secret")],
    ids=["os", "postgres"],
)
async def test_a_driver_failure_is_typed_and_carries_no_driver_text(exc: Exception) -> None:
    with pytest.raises(StoredPresenceError) as caught:
        await QuestDbStoredPresence(FailingWire(exc)).stored_spans("BTCUSDT", "trades", 0, M)
    err = caught.value
    assert "8812" not in str(err) and "secret" not in str(err)
    assert err.__cause__ is None and err.__context__ is None


async def test_a_read_past_its_deadline_is_a_typed_timeout() -> None:
    reader = QuestDbStoredPresence(StuckWire(), timeout_s=0.01)
    with pytest.raises(StoredPresenceTimeout) as caught:
        await reader.stored_spans("BTCUSDT", "trades", 0, M)
    assert isinstance(caught.value, TimeoutError) and caught.value.__context__ is None


@pytest.mark.parametrize("timeout_s", [0.0, -1.0, float("nan"), float("inf")])
def test_a_deadline_that_could_never_fire_is_refused(timeout_s: float) -> None:
    with pytest.raises(ValueError, match="timeout_s"):
        QuestDbStoredPresence(FakeWire(), timeout_s=timeout_s)


def test_the_reader_is_both_the_coverage_port_and_the_integrity_data() -> None:
    reader = QuestDbStoredPresence(FakeWire())
    as_presence: StoredPresence = reader
    as_data: StoredData = reader
    assert as_presence is as_data
