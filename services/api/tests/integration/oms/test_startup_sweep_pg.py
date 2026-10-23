"""Integration (E29-T04 #913 slice 3E): the OMS runtime's startup sweep on real Postgres 16 (20
Sec.6.2), over C6's database and pipeline (`test_submission_pipeline_pg.py`). A first process goes
down with an entry recorded and never sent, its attach rows pending, or with a create at the
venue's door; a second process's runtime, its stores on `pg_stores`' own pool and its standalone
`machine_events` WAL sink in `tmp_path`, sweeps them: the unsent entry is abandoned with its stops
void, audited `unplaced_entry_swept`, and the create resumes under the same id. Not run locally
(no Docker); CI's `integration` job runs it.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from collections import OrderedDict
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import psycopg
import pytest
import pytest_asyncio
from pydantic import SecretStr
from testcontainers.postgres import PostgresContainer

from candleviewer.observability.metrics import Metrics
from candleviewer.oms.fakes import FakeClockHealth
from candleviewer.oms.order_machine import OrderMachines
from candleviewer.oms_wiring import OmsRuntime, pg_stores
from candleviewer.settings import Settings
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.trading_accounts import (
    InMemoryTradingAccountReads,
    TradingAccountRow,
)
from tests.integration.oms.test_submission_pipeline_pg import (
    _APP,
    _BOOTSTRAP,
    _RESUME_BOUND_S,
    _ROOT,
    Clock,
    Rig,
    _build,
    _db_now,
    _login,
    _order,
    _orders,
    _stops,
    _trading_account,
    _uid,
    _user,
)
from tests.unit.oms import command_rig as cr
from tests.unit.oms.submit_rig import REGISTRY, STOP, Profiles, ReadOnly
from tests.unit.oms.test_oms_runtime import Flag, Port, Venue, Writer

pytestmark = pytest.mark.integration

#: How long the sweep may take to set `ready`: the bound only turns a hang into a failure.
_READY_BOUND_S = 30.0


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Superuser DSN of a database set up like production (C6's recipe)."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        info = psycopg.conninfo.conninfo_to_dict(dsn.replace("postgresql+asyncpg", "postgresql"))
        psql = shutil.which("psql")
        assert psql is not None, "the CI integration and migrations jobs have postgresql-client"
        bootstrap = subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv, no shell
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1", "-v", "owner_pw=cv_owner_test_pw",
             "-v", "app_pw=cv_app_test_pw", "-v", "ro_pw=cv_ro_test_pw", "-f", str(_BOOTSTRAP)],
            check=False, capture_output=True, text=True, timeout=120,
            env={**os.environ, "PGPASSWORD": str(info["password"])},
        )  # fmt: skip
        assert bootstrap.returncode == 0, bootstrap.stderr
        owner = _login(dsn, "cv_owner").replace("postgresql+asyncpg", "postgresql+psycopg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT, env={**os.environ, "CV_PG_DSN": owner}, check=True, timeout=300,
        )  # fmt: skip
        yield dsn


@pytest_asyncio.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(_login(pg_dsn, "cv_app"), _APP)
    try:
        yield repo
    finally:
        await repo.dispose()


class _Venue(Venue):
    """The first process's venue, which the second's runtime reaches again."""

    def trading_port(self, env: str, *, clock_offset_ms: Any = None) -> Port:
        return self.ports[0]


async def _crashed(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str, monkeypatch: pytest.MonkeyPatch, at: str
) -> tuple[Rig, UUID]:
    """A first process that goes down with its request held `at` the venue's door (`place`) or at
    its `SEND` (`send`), then stops its facade, its attempts gone with its memory. Answers it and
    the order it left."""
    clock = Clock(_db_now(pg_dsn))
    rig = _build(
        rel,
        account=_trading_account(pg_dsn),
        user=_user(pg_dsn),
        clock=clock,
        demo=Port(environment="demo", now_us=clock.us),
    )
    reached, command, place = asyncio.Event(), OrderMachines.command, rig.demo.place_order

    async def held_send(self: OrderMachines, *args: Any, **kwargs: Any) -> str:
        if args[2] == "SEND":
            reached.set()
            await asyncio.Event().wait()
        return await command(self, *args, **kwargs)

    async def held_place(create: Any) -> Any:
        reached.set()
        await asyncio.Event().wait()

    if at == "send":
        monkeypatch.setattr(OrderMachines, "command", held_send)
    else:
        monkeypatch.setattr(rig.demo, "place_order", held_place)
    task = asyncio.create_task(rig.submit())
    await reached.wait()
    task.cancel()  # the process goes down: the request first, then its facade
    await asyncio.gather(task, return_exceptions=True)
    monkeypatch.setattr(OrderMachines, "command", command)
    monkeypatch.setattr(rig.demo, "place_order", place)
    await rig.machines.stop()
    b01._ATTEMPTS.clear()
    [(order_id, _link, _state)] = _orders(pg_dsn, rig.account)
    return rig, order_id


def _runtime(rig: Rig, pg_dsn: str, tmp_path: Path, writer: Writer) -> OmsRuntime:
    """The second process's runtime over the same database and venue: the real stores and the
    standalone WAL sink; the account read in memory, as C6's is (no key row is seeded)."""
    settings = Settings(
        storage_backend="real",
        pg_dsn=SecretStr(_login(pg_dsn, "cv_app")),
        machine_event_wal_path=str(tmp_path / "machine_events.wal"),
    )
    metrics = Metrics("demo")
    key = UUID(cr.KEYS["demo"])
    row = TradingAccountRow(rig.account, "demo", _uid(rig.account), False, key)
    flags = (Flag(), Flag())
    for flag in flags:
        flag.read()
    health = FakeClockHealth(cr.Monotonic())
    health.measure()
    assert isinstance(rig.demo, Port)  # `_crashed` built it so
    return OmsRuntime(
        settings,
        venue=_Venue(ports=[rig.demo]),
        ingestion=SimpleNamespace(
            clock=health, tickers=None, instruments=None, clock_offset_ms=lambda: None
        ),
        read_only=ReadOnly(),
        metrics=metrics,
        audit=writer,
        gate=SimpleNamespace(refusal=lambda _account: None),
        standings=SimpleNamespace(read_once=True, credential_rejected=lambda *_args: None),
        oms_enabled=flags[0],
        live_enabled=flags[1],
        profiles=Profiles(),
        persistence=None,
        feed=SimpleNamespace(bind=lambda _b: SimpleNamespace(publish=lambda *_a, **_k: None)),
        stores=lambda: replace(
            pg_stores(settings, metrics), accounts=InMemoryTradingAccountReads(row)
        ),
        now=rig.clock,
        registry=REGISTRY,
    )


@pytest.fixture(autouse=True)
def _own_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    """B1's command attempts are this test's (one facade per process)."""
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())


async def test_a_validated_entry_left_by_a_crash_is_abandoned_its_stops_void_and_audited(
    rel: SqlAlchemyRelationalRepository,
    pg_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """20 Sec.6.2 steps 2 to 4, SEC-2B2-02: an entry recorded with its attach rows, its request
    gone before its `SEND`, is swept: its rows void, audited `sl.modified` and `tp.modified` with
    `unplaced_entry_swept`, and the order abandoned with a KILL from `validated`, nothing sent."""
    rig, order_id = await _crashed(rel, pg_dsn, monkeypatch, "send")
    assert _order(pg_dsn, order_id).lifecycle_state == "validated"
    assert _stops(pg_dsn, order_id) == [
        ("stop_loss", "pending", False),
        ("take_profit", "pending", False),
    ]
    writer = Writer()
    runtime = _runtime(rig, pg_dsn, tmp_path, writer)
    await runtime.start()
    try:
        await asyncio.wait_for(runtime.wait_ready(), _READY_BOUND_S)
        assert _order(pg_dsn, order_id).lifecycle_state == "killed"
        assert _stops(pg_dsn, order_id) == [
            ("stop_loss", "void", False),
            ("take_profit", "void", False),
        ]
        swept = {("sl.modified", "unplaced_entry_swept"), ("tp.modified", "unplaced_entry_swept")}
        assert swept <= set(writer.actions)
        assert ("orders.cancel", "kill_no_cancel_unsubmitted") in writer.actions
        assert rig.creates() == []
    finally:
        await runtime.stop()


async def test_a_submitting_order_left_by_a_crash_is_resumed_under_its_own_id(
    rel: SqlAlchemyRelationalRepository,
    pg_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """20 Sec.6.2 step 3, 24 Sec.8.3 rule 6: a create at the venue's door when its process went
    down is hydrated `submitting` and resumed: looked up first, then sent once under its persisted
    id with its native stop (C-2.10, C-2.6)."""
    rig, order_id = await _crashed(rel, pg_dsn, monkeypatch, "place")
    row = _order(pg_dsn, order_id)
    assert (row.lifecycle_state, row.submit_attempts) == ("submitting", 1)
    runtime = _runtime(rig, pg_dsn, tmp_path, Writer())
    await runtime.start()
    try:
        await asyncio.wait_for(runtime.wait_ready(), _READY_BOUND_S)
        machines = runtime._composed().machines
        left = await machines.settled(
            rig.account, order_id, leaving="submitting", timeout_s=_RESUME_BOUND_S
        )
        assert left == "submitted"
        methods = rig.calls()
        sent = methods.index("place_order")
        assert methods.count("place_order") == 1
        assert sent > 0 and set(methods[:sent]) <= {"open_orders", "order_history"}
        [create] = rig.creates()
        assert (create.order_link_id, create.stop_loss) == (row.order_link_id, STOP)
    finally:
        await runtime.stop()
