"""#906 slice D1a (E28-T02): the composition-root wiring of the account profiles.

`wire_profiles` builds the process's one profile store, the order path's effective-profile cache
over it and the domain facade over both, with the two E28-T01 counters on the process registry.
The fake backend has no store. The store's methods are patched at class level, so nothing connects:
the engine behind it is built lazily and never opened. No network.
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.profiles_wiring import DISPOSE_S, ProfilesWiring, wire_profiles
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.account_profiles_sqlalchemy import (
    SqlAlchemyAccountProfileStore,
)
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.unit.accounts.test_profile_cache import _P, _row

_ACCOUNT, _PROFILE = _P.account_id, _P.profile_id


def _metrics() -> Metrics:
    metrics = Metrics("demo")
    register_r0(metrics)
    return metrics


def _wired(metrics: Metrics) -> ProfilesWiring:
    settings = Settings(environment=Environment.DEMO, storage_backend="real")
    wired = wire_profiles(settings, metrics)
    assert wired is not None
    return wired


def _count(metrics: Metrics, name: str, **labels: str) -> float | None:
    return metrics.registry.get_sample_value(name, {"env": "demo", **labels})


def test_the_fake_backend_wires_no_profile_store() -> None:
    settings = Settings(environment=Environment.DEMO, storage_backend="fake")
    assert wire_profiles(settings, _metrics()) is None


async def test_the_cache_and_the_facade_share_one_store_and_count_on_the_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write through the facade invalidates the very cache the order path reads, so the read
    after it is a miss, and the two counters are the registry's (SR-E28-15)."""
    row, released = _row(), list[Any]()

    async def effective(self: Any, account_id: UUID, profile_id: UUID | None) -> Any:
        return row

    async def update(self: Any, *args: Any, **kwargs: Any) -> Any:
        return row

    async def dispose(pool: Any) -> None:
        released.append(pool)

    monkeypatch.setattr(SqlAlchemyAccountProfileStore, "effective_profile", effective)
    monkeypatch.setattr(SqlAlchemyAccountProfileStore, "update_profile", update)
    monkeypatch.setattr(SqlAlchemyRelationalRepository, "dispose", dispose)
    metrics = _metrics()
    wired = _wired(metrics)
    await wired.effective.get_effective_profile(_ACCOUNT, _PROFILE)  # miss
    await wired.effective.get_effective_profile(_ACCOUNT, _PROFILE)  # hit
    scope = OwnerScope(uuid4())
    await wired.repository.update_profile(scope, _ACCOUNT, _PROFILE, _P, expected_version=3)
    await wired.effective.get_effective_profile(_ACCOUNT, _PROFILE)  # miss: the write dropped it
    lookups = "cv_profile_cache_lookups_total"
    assert _count(metrics, lookups, result="miss") == 2
    assert _count(metrics, lookups, result="hit") == 1
    assert _count(metrics, "cv_profile_version_bumps_total") == 1
    store = cast(SqlAlchemyAccountProfileStore, wired.repository._store)
    assert store is cast(object, wired.effective._reads)  # one store, so one pool
    await wired.dispose()
    assert released == [store._relational]


async def test_dispose_cancels_the_cache_loads_before_it_releases_the_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, entered = list[str](), asyncio.Event()

    async def hung(self: Any, account_id: UUID, profile_id: UUID | None) -> Any:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            events.append("cache")
            raise

    async def release() -> None:
        events.append("pool")

    monkeypatch.setattr(SqlAlchemyAccountProfileStore, "effective_profile", hung)
    wired = dataclasses.replace(_wired(_metrics()), release=release)
    reader = asyncio.ensure_future(wired.effective.get_effective_profile(_ACCOUNT))
    await entered.wait()  # a load is in flight
    await wired.dispose()
    assert events == ["cache", "pool"]
    await asyncio.wait({reader})
    assert reader.cancelled()  # the reader of a cancelled load is cancelled with it


async def test_a_pool_that_never_closes_is_left_at_the_bound() -> None:
    async def never() -> None:
        await asyncio.Event().wait()

    wired = _wired(_metrics())
    assert wired.dispose_s == DISPOSE_S == 5.0  # the container's stop budget
    closing = asyncio.ensure_future(
        dataclasses.replace(wired, release=never, dispose_s=0.0).dispose()
    )
    try:
        done, _ = await asyncio.wait({closing}, timeout=5)  # bounds the test; times nothing
        assert closing in done, "dispose waited for a pool that never closes"
        assert isinstance(closing.exception(), TimeoutError)
    finally:
        closing.cancel()
