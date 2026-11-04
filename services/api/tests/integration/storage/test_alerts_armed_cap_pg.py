"""Integration (#1864) on real Postgres 16: the armed-alert cap is counted in SQL per owner, under
the owner's advisory lock, in the transaction of the write, so concurrent arming writes never
pass it together (the drawings quota's `small_quota` test, #2727). Needs docker
(testcontainers); exercised by CI `integration`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

from candleviewer.storage.repositories.alerts import AlertArmedLimitError, AlertRow
from candleviewer.storage.repositories.alerts_sqlalchemy import SqlAlchemyAlertRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.integration import _refused
from tests.integration._refused import seed_user

pytestmark = pytest.mark.integration
pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16 at head
_ALERT: dict[str, Any] = {"condition_ir": {"conditions": {}}, "condition_hash": "a" * 64}
_CAP = 3
_UPDATABLE = (
    "name condition_ir condition_hash trigger_mode cooldown_seconds expires_at severity channels "
    "message_template symbol scope_account_id enabled"
).split()


@pytest_asyncio.fixture
async def small_cap(pg_dsn: str) -> AsyncIterator[SqlAlchemyAlertRepository]:
    rel = SqlAlchemyRelationalRepository(pg_dsn, "alerts-armed-cap-it")
    try:
        yield SqlAlchemyAlertRepository(rel, max_armed=_CAP)
    finally:
        await rel.dispose()


async def _create(repo: SqlAlchemyAlertRepository, owner: str, name: str, **over: Any) -> AlertRow:
    return await repo.create(owner_user_id=owner, name=name, **_ALERT, **over)


async def _armed(repo: SqlAlchemyAlertRepository, owner: str) -> int:
    return len((await repo.list_page(owner, limit=50, enabled=True)).items)


async def test_concurrent_creates_pass_exactly_the_cap_per_owner(
    small_cap: SqlAlchemyAlertRepository, pg_dsn: str
) -> None:
    repo, (a, b) = small_cap, (seed_user(pg_dsn), seed_user(pg_dsn))
    for i in range(_CAP):
        await _create(repo, b, f"b-{i}")  # B at the cap never counts against A
    results = await asyncio.gather(
        *(_create(repo, a, f"a-{i}") for i in range(_CAP + 4)), return_exceptions=True
    )  # concurrent: the per-owner lock lets exactly the cap through
    refused = [r for r in results if isinstance(r, AlertArmedLimitError)]
    assert len(refused) == 4 and {e.limit for e in refused} == {_CAP}
    assert all(isinstance(r, AlertRow | AlertArmedLimitError) for r in results)
    assert await _armed(repo, a) == _CAP and await _armed(repo, b) == _CAP


async def test_concurrent_re_enables_pass_exactly_the_cap(
    small_cap: SqlAlchemyAlertRepository, pg_dsn: str
) -> None:
    repo, owner = small_cap, seed_user(pg_dsn)
    parked = [await _create(repo, owner, f"p-{i}", enabled=False) for i in range(_CAP + 3)]
    results = await asyncio.gather(
        *(repo.set_enabled(p.id, True) for p in parked), return_exceptions=True
    )
    assert sum(isinstance(r, AlertArmedLimitError) for r in results) == 3
    assert await _armed(repo, owner) == _CAP


async def test_a_disarm_and_a_write_to_an_armed_alert_pass_at_the_cap(
    small_cap: SqlAlchemyAlertRepository, pg_dsn: str
) -> None:
    repo, owner = small_cap, seed_user(pg_dsn)
    armed = [await _create(repo, owner, f"a-{i}") for i in range(_CAP)]
    parked = await _create(repo, owner, "parked", enabled=False)  # a disarmed create passes
    with pytest.raises(AlertArmedLimitError):
        await _create(repo, owner, "one more")
    with pytest.raises(AlertArmedLimitError):  # a replace that arms is held too, row kept
        fields = {k: getattr(parked, k) for k in _UPDATABLE} | {"enabled": True}
        await repo.update(parked.id, if_match=parked.updated_at, **fields)
    assert (await repo.get(parked.id)) == parked
    again = await repo.set_enabled(armed[0].id, True)  # already armed: no growth
    assert again is not None and again.enabled
    renamed = {k: getattr(again, k) for k in _UPDATABLE} | {"name": "renamed"}
    assert (await repo.update(again.id, if_match=again.updated_at, **renamed)).name == "renamed"
    off = await repo.set_enabled(armed[1].id, False)  # a disarm never takes the lock
    assert off is not None and not off.enabled
    on = await repo.set_enabled(parked.id, True)  # one slot free again
    assert on is not None and on.enabled and await _armed(repo, owner) == _CAP
