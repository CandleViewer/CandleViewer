"""E42-Q01 (#962): SC-FORGED-SEAL over the real inspector, with a test key that is never a real
one: the row's seal fails and the inspector leaves it out; a refusal writes nothing. The Postgres
half is `tests/integration/admin/test_admin_fixture_b4a_pg.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from candleviewer.statechart.persistence import MachineKey, open_sealed
from candleviewer.statechart.registry import Registry, machine_hash
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.fixtures.admin.forged_seal import (
    check_forged_seal,
    check_left_out,
    forged_row,
    seed_forged_seal,
)
from tests.fixtures.admin.latched_machine import ENTITY_ID, ENV, KIND, latched_row
from tests.fixtures.admin.seed import FixtureCheckError, FixtureRefused
from tests.unit._admin_fake_db import FakeDb

_NOW = datetime(2026, 10, 23, 19, 0, tzinfo=UTC)
_REGISTRY = Registry()


class Keys:
    """`HmacKeys` with one test key under `key_id`, never a real one."""

    def __init__(self, key_id: str = "k1") -> None:
        self._id = key_id

    def current(self) -> str:
        return self._id

    def key(self, key_id: str) -> bytes:
        return {self._id: b"\x01" * 32}[key_id]


def _open(row: Any) -> dict[str, Any]:
    chart = _REGISTRY.get(KIND)
    key = MachineKey(KIND, ENTITY_ID, ENV)
    return open_sealed(
        Keys(), chart, row.envelope, key=key, expected_machine_hash=machine_hash(chart)
    )


def test_the_latched_row_opens_and_the_forged_row_fails_on_its_hmac() -> None:
    assert _open(latched_row(Keys(), now=_NOW, registry=_REGISTRY))["chain_trips"] == 2
    with pytest.raises(ValueError, match="bad HMAC"):
        _open(forged_row(Keys(), now=_NOW, registry=_REGISTRY))


def test_the_forged_row_keeps_the_seal_and_clears_the_trips() -> None:
    sealed = latched_row(Keys(), now=_NOW, registry=_REGISTRY)
    forged = forged_row(Keys(), now=_NOW, registry=_REGISTRY)
    changed = {k for k, v in forged.envelope.snapshot.items() if v != sealed.envelope.snapshot[k]}
    assert (forged.envelope.seal, changed) == (sealed.envelope.seal, {"chain_trips"})
    assert forged.envelope.snapshot["chain_trips"] == 0


async def test_the_check_passes_the_forged_row() -> None:
    row = forged_row(Keys(), now=_NOW, registry=_REGISTRY)
    await check_left_out([row], Keys(), now=_NOW, registry=_REGISTRY)


#: A world the check refuses: the rows it holds, and what is named.
_SPOILED: dict[str, tuple[list[Any], str]] = {
    "no row": ([], "0 rows for order/"),
    "a seal that holds": ([latched_row(Keys(), now=_NOW, registry=_REGISTRY)], "its seal verifies"),
    "a key the provider lacks": (
        [latched_row(Keys("k2"), now=_NOW, registry=_REGISTRY)],
        "not on the HMAC",
    ),
}


@pytest.mark.parametrize(("rows", "named"), _SPOILED.values(), ids=list(_SPOILED))
async def test_the_check_names_a_row_that_is_not_a_forged_one(rows: list[Any], named: str) -> None:
    with pytest.raises(FixtureCheckError, match=named):
        await check_left_out(rows, Keys(), now=_NOW, registry=_REGISTRY)


async def test_the_check_names_what_the_inspector_makes_of_a_row_whose_seal_holds() -> None:
    held = latched_row(Keys(), now=_NOW, registry=_REGISTRY)
    with pytest.raises(FixtureCheckError) as named:
        await check_left_out([held], Keys(), now=_NOW, registry=_REGISTRY)
    assert "the inspector lists 1 machines" in str(named.value)
    assert "snapshots is 'ok'" in str(named.value)


@pytest.mark.parametrize("run", [seed_forged_seal, check_forged_seal])
async def test_a_database_not_named_for_tests_is_refused_before_anything_else(run: Any) -> None:
    db = FakeDb("candleviewer")
    with pytest.raises(FixtureRefused):
        await run(cast(SqlAlchemyRelationalRepository, db), Keys(), now=_NOW)
    assert db.shapes == ["SELECT current_database()"]
