"""E42-Q01 (#962): the latched-machine fixture (SC-CHAIN-TRIPS) over the real inspector, with a test
key that is never a real one. The Postgres half is
`tests/integration/admin/test_admin_latched_machine_pg.py`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import IteratorResult
from sqlalchemy.engine.result import SimpleResultMetaData

from candleviewer.admin.inspector import SEAL_FAILED, StatechartInspector
from candleviewer.admin.overview.fanout import SliceFanOut
from candleviewer.api.admin_statecharts import machine_key
from candleviewer.observability.redaction import redact_text
from candleviewer.statechart.registry import Registry
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.fixtures.admin.latched_machine import (
    CHAIN_TRIPS,
    CONFIGURATION,
    DEFERRED,
    ENTITY_ID,
    ENV,
    KIND,
    check_latched_machine,
    check_listed_degraded,
    latched_row,
    seed_latched_machine,
)
from tests.fixtures.admin.seed import FixtureCheckError, FixtureRefused

_NOW = datetime(2026, 10, 23, 7, 0, tzinfo=UTC)
_REGISTRY = Registry()


class Keys:
    """`HmacKeys` with one test key, never a real one."""

    def __init__(self, key: bytes = b"\x01" * 32) -> None:
        self._key = key

    def current(self) -> str:
        return "k1"

    def key(self, key_id: str) -> bytes:
        return {"k1": self._key}[key_id]


class _Rows:
    def __init__(self, *rows: Any) -> None:
        self.rows = rows

    async def snapshots(self) -> Any:
        return self.rows


def _inspector(*rows: Any) -> StatechartInspector:
    fan = SliceFanOut(budget_s=60, ttl_s=0.0, now=lambda: _NOW)  # no real 300 ms timer in a test
    lock = {KIND: _REGISTRY.hash(KIND)}
    return StatechartInspector(
        fan, machine_key, lock, store=_Rows(*rows), keys=Keys(), registry=_REGISTRY
    )


def _owner(machine_kind: str, scope: Any) -> bool:
    return True


async def test_the_latched_order_is_listed_degraded_with_its_trips_and_deferred_events() -> None:
    found = await _inspector(latched_row(Keys(), now=_NOW, registry=_REGISTRY)).listing(
        _owner, degraded=True
    )
    [order] = found.items
    assert (order.key, order.state) == (f"order:{ENTITY_ID}", "triggered")
    assert (order.chain_trips, order.deferred_depth) == (CHAIN_TRIPS, DEFERRED)
    [summary] = found.kinds
    assert (summary["chain_trips"], summary["degraded_machines"]) == (CHAIN_TRIPS, 1)


async def test_a_copy_altered_after_sealing_is_left_out_and_named() -> None:
    sealed = latched_row(Keys(), now=_NOW, registry=_REGISTRY)
    hidden = sealed.envelope.snapshot | {"chain_trips": 0}  # a forger hiding the trips
    forged = dataclasses.replace(
        sealed, envelope=dataclasses.replace(sealed.envelope, snapshot=hidden)
    )
    found = await _inspector(forged).listing(_owner)
    assert found.items == ()
    assert (found.snapshots.status, found.snapshots.detail) == ("error", SEAL_FAILED)


def test_the_same_keys_and_clock_seal_the_same_row() -> None:
    first = latched_row(Keys(), now=_NOW, registry=_REGISTRY)
    assert latched_row(Keys(), now=_NOW, registry=_REGISTRY) == first


def test_the_handle_is_a_kind_with_a_public_entity_id() -> None:
    assert machine_key(KIND, ENTITY_ID) == f"order:{ENTITY_ID}"


async def test_the_check_passes_on_the_handles_row() -> None:
    await check_listed_degraded(
        [latched_row(Keys(), now=_NOW, registry=_REGISTRY)], Keys(), now=_NOW, registry=_REGISTRY
    )


async def test_the_check_names_a_missing_row() -> None:
    with pytest.raises(FixtureCheckError, match="0 rows for order/"):
        await check_listed_degraded([], Keys(), now=_NOW, registry=_REGISTRY)


async def test_the_check_names_a_row_its_keys_do_not_open() -> None:
    other = latched_row(Keys(b"\x02" * 32), now=_NOW, registry=_REGISTRY)
    with pytest.raises(FixtureCheckError, match=r"lists \[\] \(trips, deferred\)"):
        await check_listed_degraded([other], Keys(), now=_NOW, registry=_REGISTRY)


def test_a_naive_clock_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        latched_row(Keys(), now=_NOW.replace(tzinfo=None), registry=_REGISTRY)


@pytest.mark.parametrize("value", [KIND, ENTITY_ID, ENV, *CONFIGURATION])
def test_no_latched_machine_value_is_secret_shaped(value: str) -> None:
    assert redact_text(value) == value


class _Conn:
    """Answers the database's name; every statement sent is kept."""

    def __init__(self, database: str, sent: list[str]) -> None:
        self.database, self.sent = database, sent

    async def execute(self, stmt: Any) -> IteratorResult[Any]:
        self.sent.append(str(stmt))
        return IteratorResult(SimpleResultMetaData(["name"]), iter([(self.database,)]))


class _Rel:
    """A relational repository whose engine connects to `database`; a unit of work is a write."""

    def __init__(self, database: str) -> None:
        self.sent: list[str] = []
        self._database = database

    @property
    def engine(self) -> Any:
        return self

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[_Conn]:
        yield _Conn(self._database, self.sent)

    def unit_of_work(self) -> Any:
        raise AssertionError("the fixture opened a unit of work on a refused database")


@pytest.mark.parametrize("run", [seed_latched_machine, check_latched_machine])
async def test_a_database_not_named_for_tests_is_refused_before_anything_else(run: Any) -> None:
    rel = _Rel("candleviewer")
    with pytest.raises(FixtureRefused):
        await run(cast(SqlAlchemyRelationalRepository, rel), Keys(), now=_NOW)
    assert rel.sent == [str(sa.text("SELECT current_database()"))]
