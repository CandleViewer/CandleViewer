"""Unit tests for `storage.real_tiers` (#3874): building the E07 clients opens no connection and
lists the tiers in start order; each probe passes when its tier answers and raises when it cannot;
the questdb close drains the writer and always closes its wire. No network: the drivers are
replaced at the seams the module calls."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, ClassVar

import pytest
from structlog.testing import capture_logs

from candleviewer.settings import QUESTDB_PG_DEFAULT_PORT, Settings
from candleviewer.storage import real_tiers
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.wiring import LazyPgWire, TcpIlpTransport
from candleviewer.storage.real_tiers import (
    QUESTDB_ILP_DEFAULT_PORT,
    WIRE_CLOSE_S,
    QuestDbIlpUnreachable,
    RealTier,
    build_real_tiers,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in os.environ if n.upper().startswith("CV_")]:
        monkeypatch.delenv(name)


def _settings(root: Path, **overrides: Any) -> Settings:
    return Settings(storage_backend="real", parquet_root=str(root), **overrides)


def _tier(built: real_tiers.RealTiers, name: str) -> RealTier:
    return next(t for t in built.tiers if t.tier == name)


def _entries(path: Path) -> list[Path]:
    return list(path.iterdir())


def _exists(path: Path) -> bool:
    return path.exists()


class _FakeConn:
    def __init__(self, fail: bool) -> None:
        self.fail = fail
        self.sql: list[str] = []

    async def execute(self, statement: Any) -> None:
        self.sql.append(str(statement))
        if self.fail:
            raise ConnectionRefusedError("postgres down")


class _FakeEngine:
    def __init__(self) -> None:
        self.conn = _FakeConn(fail=False)

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[_FakeConn]:
        yield self.conn


class _FakeRelational:
    """Stands in for `SqlAlchemyRelationalRepository` (no engine, no pool)."""

    made: ClassVar[list[_FakeRelational]] = []

    def __init__(self, dsn: str, application_name_suffix: str) -> None:
        self.dsn, self.suffix = dsn, application_name_suffix
        self.engine = _FakeEngine()
        self.disposed = 0
        _FakeRelational.made.append(self)

    async def dispose(self) -> None:
        self.disposed += 1


@pytest.fixture
def relational(monkeypatch: pytest.MonkeyPatch) -> type[_FakeRelational]:
    _FakeRelational.made = []
    monkeypatch.setattr(real_tiers, "SqlAlchemyRelationalRepository", _FakeRelational)
    return _FakeRelational


def test_build_lists_the_tiers_in_start_order_with_no_connection_opened(
    tmp_path: Path, relational: type[_FakeRelational], monkeypatch: pytest.MonkeyPatch
) -> None:
    wires: list[tuple[tuple[Any, ...], dict[str, Any], LazyPgWire]] = []

    def wire(*args: Any, **kwargs: Any) -> LazyPgWire:
        made = LazyPgWire(*args, **kwargs)
        wires.append((args, kwargs, made))
        return made

    monkeypatch.setattr(real_tiers, "LazyPgWire", wire)
    built = build_real_tiers(_settings(tmp_path, questdb_pg="qdb-host:8813"))
    assert [t.tier for t in built.tiers] == ["postgres", "questdb", "cold"]
    ((args, kwargs, made),) = wires
    assert args[:3] == ("qdb-host", 8813, "admin")
    assert kwargs == {"name": "storage", "close_timeout_s": WIRE_CLOSE_S}
    assert made._conn is None  # lazy: no connection until the first probe or read
    (repo,) = relational.made
    assert repo.suffix == "storage" and repo.engine.conn.sql == []


def test_build_takes_the_default_ports_when_settings_omit_them(
    tmp_path: Path, relational: type[_FakeRelational], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, tuple[Any, ...]] = {}

    def wire(*args: Any, **kwargs: Any) -> LazyPgWire:
        seen["pg"] = args
        return LazyPgWire(*args, **kwargs)

    def transport(*args: Any, **kwargs: Any) -> Any:
        seen["ilp"] = args
        return TcpIlpTransport(*args, **kwargs)

    monkeypatch.setattr(real_tiers, "LazyPgWire", wire)
    monkeypatch.setattr(real_tiers, "TcpIlpTransport", transport)
    build_real_tiers(_settings(tmp_path, questdb_pg="qdb", questdb_ilp="ilp"))
    assert seen["pg"][:2] == ("qdb", QUESTDB_PG_DEFAULT_PORT)
    assert seen["ilp"] == ("ilp", QUESTDB_ILP_DEFAULT_PORT)


async def test_postgres_probe_runs_select_1_and_raises_when_postgres_cannot_answer(
    tmp_path: Path, relational: type[_FakeRelational]
) -> None:
    built = build_real_tiers(_settings(tmp_path))
    (repo,) = relational.made
    await _tier(built, "postgres").probe()
    assert repo.engine.conn.sql == ["SELECT 1"]
    repo.engine.conn.fail = True
    with pytest.raises(ConnectionRefusedError):
        await _tier(built, "postgres").probe()


async def test_postgres_close_disposes_the_engine(
    tmp_path: Path, relational: type[_FakeRelational]
) -> None:
    built = build_real_tiers(_settings(tmp_path))
    await _tier(built, "postgres").close(5.0)
    assert relational.made[0].disposed == 1


class _IlpPort:
    """Stands in for `TcpIlpTransport`'s connect and close (no socket)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []
        self.refuse = False

        async def connect(_self: TcpIlpTransport) -> None:
            self.calls.append("connect")
            if self.refuse:
                raise ConnectionRefusedError("ilp refused")

        async def close(_self: TcpIlpTransport) -> None:
            self.calls.append("close")

        monkeypatch.setattr(TcpIlpTransport, "connect", connect)
        monkeypatch.setattr(TcpIlpTransport, "close", close)


async def test_questdb_probe_needs_a_row_from_select_1_then_the_ilp_port(
    tmp_path: Path, relational: type[_FakeRelational], monkeypatch: pytest.MonkeyPatch
) -> None:
    rows: list[dict[str, object]] = []
    queries: list[str] = []

    async def fetch(_self: LazyPgWire, sql: str, *params: object) -> list[dict[str, object]]:
        queries.append(sql)
        return rows

    monkeypatch.setattr(LazyPgWire, "fetch", fetch)
    ilp = _IlpPort(monkeypatch)
    probe = _tier(build_real_tiers(_settings(tmp_path)), "questdb").probe
    with pytest.raises(ConnectionError):
        await probe()
    assert ilp.calls == []  # PG-wire is asked first
    rows.append({"1": 1})
    await probe()
    assert queries == ["SELECT 1", "SELECT 1"]
    assert ilp.calls == ["connect", "close"]


async def test_questdb_probe_names_an_ilp_failure_apart_and_closes_its_socket(
    tmp_path: Path, relational: type[_FakeRelational], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fetch(_self: LazyPgWire, sql: str, *params: object) -> list[dict[str, object]]:
        return [{"1": 1}]

    monkeypatch.setattr(LazyPgWire, "fetch", fetch)
    ilp = _IlpPort(monkeypatch)
    ilp.refuse = True
    with pytest.raises(QuestDbIlpUnreachable) as refused:
        await _tier(build_real_tiers(_settings(tmp_path)), "questdb").probe()
    assert refused.value.__cause__ is None and refused.value.__suppress_context__
    assert "ilp refused" not in str(refused.value)  # the driver's message stays out
    assert ilp.calls == ["connect", "close"]


async def test_questdb_close_drains_within_its_budget_then_closes_the_wire(
    tmp_path: Path, relational: type[_FakeRelational], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def stop(_self: IlpWriter, timeout_s: float | None = None) -> None:
        calls.append(f"stop:{timeout_s}")

    async def close(_self: LazyPgWire) -> None:
        calls.append("wire.close")

    monkeypatch.setattr(IlpWriter, "stop", stop)
    monkeypatch.setattr(LazyPgWire, "close", close)
    await _tier(build_real_tiers(_settings(tmp_path)), "questdb").close(7.5)
    assert calls == [f"stop:{7.5 - WIRE_CLOSE_S}", "wire.close"]


async def test_questdb_close_with_a_budget_below_the_wire_bound_drains_for_zero(
    tmp_path: Path, relational: type[_FakeRelational], monkeypatch: pytest.MonkeyPatch
) -> None:
    timeouts: list[float | None] = []

    async def stop(_self: IlpWriter, timeout_s: float | None = None) -> None:
        timeouts.append(timeout_s)

    async def close(_self: LazyPgWire) -> None:
        return None

    monkeypatch.setattr(IlpWriter, "stop", stop)
    monkeypatch.setattr(LazyPgWire, "close", close)
    await _tier(build_real_tiers(_settings(tmp_path)), "questdb").close(WIRE_CLOSE_S / 2)
    assert timeouts == [0.0]


async def test_questdb_close_closes_the_wire_when_the_drain_fails(
    tmp_path: Path, relational: type[_FakeRelational], monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[bool] = []

    async def stop(_self: IlpWriter, timeout_s: float | None = None) -> None:
        raise StorageTierUnavailable("drain failed")

    async def close(_self: LazyPgWire) -> None:
        closed.append(True)

    monkeypatch.setattr(IlpWriter, "stop", stop)
    monkeypatch.setattr(LazyPgWire, "close", close)
    with capture_logs() as logs, pytest.raises(StorageTierUnavailable):
        await _tier(build_real_tiers(_settings(tmp_path)), "questdb").close(5.0)
    assert closed == [True]
    assert logs == []  # the writer's own bound logged its rows (`questdb_ilp_drain_failed`)


async def test_questdb_close_cut_short_logs_the_rows_still_buffered_and_closes_the_wire(
    tmp_path: Path, relational: type[_FakeRelational], monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[bool] = []

    async def stop(_self: IlpWriter, timeout_s: float | None = None) -> None:
        await asyncio.Event().wait()  # a drain that outlives the caller's bound

    async def close(_self: LazyPgWire) -> None:
        closed.append(True)

    monkeypatch.setattr(IlpWriter, "stop", stop)
    monkeypatch.setattr(IlpWriter, "total_buffered", property(lambda _self: 3))
    monkeypatch.setattr(LazyPgWire, "close", close)
    with capture_logs() as logs, pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):  # the service's share, cutting the drain
            await _tier(build_real_tiers(_settings(tmp_path)), "questdb").close(5.0)
    assert closed == [True]
    assert logs == [{"event": "storage_questdb_drain_cut", "buffered": 3, "log_level": "error"}]


async def test_questdb_close_cut_short_with_nothing_buffered_logs_nothing(
    tmp_path: Path, relational: type[_FakeRelational], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def stop(_self: IlpWriter, timeout_s: float | None = None) -> None:
        await asyncio.Event().wait()

    async def close(_self: LazyPgWire) -> None:
        return None

    monkeypatch.setattr(IlpWriter, "stop", stop)
    monkeypatch.setattr(LazyPgWire, "close", close)
    with capture_logs() as logs, pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await _tier(build_real_tiers(_settings(tmp_path)), "questdb").close(5.0)
    assert logs == []  # a cut that lost no row is not an error


async def test_questdb_close_bounds_a_wire_close_that_waits_on_the_lock(
    tmp_path: Path, relational: type[_FakeRelational], monkeypatch: pytest.MonkeyPatch
) -> None:
    timeouts: list[float | None] = []

    async def stop(_self: IlpWriter, timeout_s: float | None = None) -> None:
        timeouts.append(timeout_s)

    async def close(_self: LazyPgWire) -> None:
        await asyncio.Event().wait()  # the lock held by a read that never ends

    monkeypatch.setattr(real_tiers, "WIRE_CLOSE_S", 0.01)
    monkeypatch.setattr(IlpWriter, "stop", stop)
    monkeypatch.setattr(LazyPgWire, "close", close)
    async with asyncio.timeout(5.0):  # a guard: the close is bounded by WIRE_CLOSE_S
        await _tier(build_real_tiers(_settings(tmp_path)), "questdb").close(1.0)
    assert timeouts == [1.0 - 0.01]


async def test_cold_probe_passes_on_an_existing_writable_root(
    tmp_path: Path, relational: type[_FakeRelational]
) -> None:
    built = build_real_tiers(_settings(tmp_path))
    await _tier(built, "cold").probe()
    await _tier(built, "cold").close(5.0)  # nothing to release
    assert _entries(tmp_path) == []  # the probe creates nothing


async def test_cold_probe_refuses_a_missing_root_and_creates_nothing(
    tmp_path: Path, relational: type[_FakeRelational]
) -> None:
    root = tmp_path / "missing"
    with pytest.raises(NotADirectoryError):
        await _tier(build_real_tiers(_settings(root)), "cold").probe()
    assert not _exists(root)


async def test_cold_probe_refuses_a_root_it_cannot_write(
    tmp_path: Path, relational: type[_FakeRelational], monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[int] = []

    def access(_path: object, mode: int) -> bool:
        asked.append(mode)
        return False

    monkeypatch.setattr(os, "access", access)
    with pytest.raises(PermissionError):
        await _tier(build_real_tiers(_settings(tmp_path)), "cold").probe()
    assert asked == [os.W_OK | os.X_OK]
