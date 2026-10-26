"""#906 slice D1a (E28-T02): the composition-root wiring of the account profiles.

`wire_profiles` builds the process's one profile store, the order path's effective-profile cache
over it and the domain facade over both, with the two E28-T01 counters on the process registry,
and binds the facade's doorbell over the process's bus (D3a). The fake backend has no store. The
store's methods are patched at class level, so nothing connects: the engine behind it is built
lazily and never opened. No network. D2-m: `profile_writes` builds the writes over the same wiring.
"""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from candleviewer.accounts.profile_changes import ProfilesChanged, ProfileVersion
from candleviewer.accounts.profile_validator import SizingWarningsPort
from candleviewer.bus import Bus, QueuePolicy, Topic
from candleviewer.instrument_limits_wiring import CatalogueLimits
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.profiles_wiring import (
    DISPOSE_S,
    BusProfileChanges,
    ProfilesWiring,
    profile_writes,
    wire_profiles,
)
from candleviewer.rules_store_pg import PostgresArmedRules
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.account_profiles_sqlalchemy import (
    SqlAlchemyAccountProfileStore,
)
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.storage.repositories.accounts_sqlalchemy import SqlAlchemyAccountsStore
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.unit.accounts.test_profile_cache import _P, _row
from tests.unit.accounts.test_profile_repository import _NO

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
    await wired.repository.update_profile(
        scope, _ACCOUNT, _PROFILE, _P, expected_version=3, write_ahead=_NO
    )
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


def _change(account: UUID) -> ProfilesChanged:
    one = (ProfileVersion(profile_id=_PROFILE, version=4),)
    return ProfilesChanged(
        exchange_account_id=account, change="updated", profiles=one, ts_event=1_792_486_805_000_000
    )


async def test_the_bus_doorbell_publishes_on_its_accounts_topic() -> None:
    """#906 D3a: the account's id where a market topic carries its symbol (20 Sec.3), so a consumer
    holds one account's topic or the pattern over all of them."""
    bus, other = Bus(), uuid4()
    mine = bus.subscribe("mine", f"demo.profiles.{_ACCOUNT}.changed", QueuePolicy.NEVER_DROP)
    every = bus.subscribe("every", "demo.profiles.*.changed", QueuePolicy.NEVER_DROP)
    doorbell, event = BusProfileChanges(bus, "demo"), _change(_ACCOUNT)
    await doorbell.changed(event)
    await doorbell.changed(_change(other))
    assert doorbell.topic(_ACCOUNT).key == f"demo.profiles.{_ACCOUNT}.changed"
    assert mine.get_nowait() is event and mine.qsize() == 0
    assert [every.get_nowait().exchange_account_id for _ in range(2)] == [_ACCOUNT, other]


class _CountingBus:
    """Counts the publishes in flight; each waits until `release` is set."""

    def __init__(self) -> None:
        self.in_flight = self.most = 0
        self.keys: list[str] = []
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    async def publish(self, topic: Topic, event: object) -> None:
        self.in_flight += 1
        self.most = max(self.most, self.in_flight)
        self.entered.set()
        await self.release.wait()
        self.keys.append(topic.key)
        self.in_flight -= 1


async def test_the_bus_doorbell_is_its_topics_one_producer() -> None:
    """The bus orders a topic only for a single producer: concurrent writes publish one at a time,
    in the order they rang."""
    bus, accounts = _CountingBus(), [uuid4() for _ in range(3)]
    doorbell = BusProfileChanges(cast(Bus, bus), "demo")
    ringing = [asyncio.ensure_future(doorbell.changed(_change(a))) for a in accounts]
    await asyncio.wait_for(bus.entered.wait(), 5)  # the first publishes; the others wait
    bus.release.set()
    await asyncio.gather(*ringing)
    assert bus.most == 1
    assert bus.keys == [f"demo.profiles.{a}.changed" for a in accounts]


async def test_wire_profiles_hands_the_facade_the_doorbell_of_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A committed write through the wired facade rings on the bus it was handed, under the
    process's environment; without a bus there is no doorbell, and the fake backend wires none."""
    row = _row(version=4)

    async def update(self: Any, *args: Any, **kwargs: Any) -> Any:
        return row

    monkeypatch.setattr(SqlAlchemyAccountProfileStore, "update_profile", update)
    bus = Bus()
    heard = bus.subscribe("heard", "testnet.profiles.*.changed", QueuePolicy.NEVER_DROP)
    real = Settings(environment=Environment.TESTNET, storage_backend="real")
    wired = wire_profiles(real, _metrics(), bus)
    assert wired is not None
    owner = OwnerScope(uuid4())
    await wired.repository.update_profile(
        owner, _ACCOUNT, _PROFILE, _P, expected_version=3, write_ahead=_NO
    )
    event = heard.get_nowait()
    assert (event.exchange_account_id, event.change) == (_ACCOUNT, "updated")
    assert event.profiles == (ProfileVersion(profile_id=_PROFILE, version=4),)
    unrung = wire_profiles(real, _metrics())
    assert unrung is not None and unrung.repository._changes is None
    fake = Settings(environment=Environment.TESTNET, storage_backend="fake")
    assert wire_profiles(fake, _metrics(), bus) is None


def test_profile_writes_share_the_reads_wiring_and_the_process_environment() -> None:
    """#906 D2-m: the writes' facade is the reads' (one cache, SR-E28-15), their accounts and
    armed rules sit on its one pool, and the catalogue is the process environment's, read per
    call as it is attached late (C-2.11); no wiring (the fake backend) gives no writes (503)."""
    settings = Settings(environment=Environment.TESTNET, storage_backend="real")
    wired = wire_profiles(settings, _metrics())
    assert wired is not None
    ctx = SimpleNamespace(settings=settings, ingestion=SimpleNamespace(instruments=None))
    warnings = cast(SizingWarningsPort, object())
    writes = profile_writes(wired, cast(Any, ctx), warnings=warnings)
    assert writes is not None and writes.warnings is warnings
    assert writes.profiles is wired.repository and writes.accounts is wired.accounts
    assert writes.rules is wired.rules and writes.environment == "testnet"
    pool = cast(SqlAlchemyAccountProfileStore, wired.repository._store)._relational
    assert cast(SqlAlchemyAccountsStore, wired.accounts._store)._relational is pool
    assert cast(PostgresArmedRules, wired.rules)._relational is pool
    assert isinstance(writes.limits, CatalogueLimits) and writes.limits.environment == "testnet"
    ctx.ingestion.instruments = catalogue = cast(Any, object())
    assert writes.limits.catalogue() is catalogue
    assert profile_writes(None, cast(Any, ctx)) is None
    assert wire_profiles(Settings(storage_backend="fake"), _metrics()) is None
