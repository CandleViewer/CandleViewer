"""E29-T13 (#4207): the OMS runtime's composition of its WS topics (`oms_wiring`, `app.py`): on the
real backend `build_oms_runtime` hands the runtime the topics; its start hooks the step publisher
into the step writer, so a step the startup sweep commits reaches the topics with its account; it
attaches the lane's snapshot reads once `ready`, each read hopped to the lane and scoped to the
process's environment (C-2.11); its stop detaches them; without topics none of it is composed.
`create_app` serves the three families from one adapter over the gateway's hub, in
`PRIVATE_CAUSAL_ORDER`. The OMS runtime's own rig (`test_oms_runtime`): no network, no sleeps."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from candleviewer import app as appmod
from candleviewer.oms import ws_topics as wt
from candleviewer.oms.errors import OmsNotReady
from candleviewer.oms_wiring import OmsRuntime, OnLaneTopicReads, build_oms_runtime
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.orders import OPEN_STATES
from candleviewer.storage.repositories.trading_accounts import TradingAccountRow
from candleviewer.ws.sequencing import PRIVATE_CAUSAL_ORDER
from tests.unit.oms import command_rig as cr
from tests.unit.oms.test_oms_runtime import (
    KEY,
    LIVE_UNSENT,
    SENDING,
    UNSENT,
    Hub,
    Tracked,
    Venue,
    World,
    crashed,
    started,
    until,
)


class Topics:
    """The gateway's topics as the runtime holds them (`AttachedTopics`), every call recorded."""

    def __init__(self) -> None:
        self.changes: list[tuple[UUID, wt.Change]] = []
        self.resyncs: list[tuple[UUID, tuple[str, ...]]] = []
        self.attached: list[Any] = []
        self.detached = 0

    def published(self, account: UUID, changes: Any) -> None:
        self.changes += [(account, change) for change in changes]

    def resync(self, account: UUID, families: Any) -> None:
        self.resyncs.append((account, tuple(families)))

    def attach(self, reads: wt.SnapshotReads) -> None:
        self.attached.append(reads)

    async def detach(self) -> None:
        self.detached += 1


def test_the_families_are_the_causal_orders_private_prefix() -> None:
    """Sec.16.1 S5's one source is `ws/sequencing.py`; the OMS module, which may not import `ws`,
    names the same order for its three families."""
    assert wt.FAMILIES == PRIVATE_CAUSAL_ORDER[: len(wt.FAMILIES)]


def test_the_real_backends_runtime_holds_the_topics_it_was_handed() -> None:
    ctx = SimpleNamespace(exchange_bybit=Venue(), ingestion=None, oms_read_only_gate=None)
    names = ("metrics", "gate", "standings", "oms_enabled", "live_enabled", "profiles")
    unused = dict.fromkeys((*names, "persistence", "feed", "lane_signing"))
    topics = Topics()
    runtime = build_oms_runtime(
        cast(Any, ctx), Settings(storage_backend="real"), **cast(Any, unused), health=Tracked(),
        hub=Hub(), topics=topics,
    )  # fmt: skip
    assert isinstance(runtime, OmsRuntime) and runtime._topics is topics


async def test_a_step_the_sweep_commits_reaches_the_topics_and_the_reads_attach_once_ready() -> (
    None
):
    """The startup sweep abandons the entry a crash left unsent (a KILL from `validated`): that
    committed step reaches the topics as its account's `orders` change, out of the open set; once
    `ready`, the topics hold the lane's reads, which answer the account's open order through the
    lane; the stop detaches them."""
    world, topics = World(), Topics()
    await crashed(world)
    async with started(world.runtime(topics=topics)) as runtime:
        for flag in world.flags:
            flag.read()
        await until(lambda: runtime.state == "ok")
        killed = [c for _, c in topics.changes if c.key == str(UNSENT.id)]
        assert killed and killed[-1].item["state"] == "killed" and killed[-1].closed
        assert {account for account, _ in topics.changes} == {cr.ACCOUNT}
        [reads] = topics.attached
        assert isinstance(reads, OnLaneTopicReads)
        await until(lambda: world.store._orders[SENDING.id].lifecycle_state == "submitted")
        view = await reads.read("orders", cr.ACCOUNT)
        assert [item["id"] for item in view.items] == [str(SENDING.id)]
    assert topics.detached == 1


async def test_the_lanes_snapshot_reads_are_scoped_to_the_process_environment() -> None:
    """C-2.11 as composed: on the demo process, the live account's entry, open in the shared store,
    reads as an account with no rows in each family, as an account no row names does; the demo
    account's open order still reads."""
    world, topics = World(), Topics()
    await crashed(world, live=True)
    world.accounts.append(TradingAccountRow(cr.LIVE_ACCOUNT, "live", cr.UIDS["live"], False, KEY))
    async with started(world.runtime(topics=topics)) as runtime:
        for flag in world.flags:
            flag.read()
        await until(lambda: runtime.state == "ok")
        [reads] = topics.attached
        assert world.store._orders[LIVE_UNSENT.id].state in OPEN_STATES
        for account in (cr.LIVE_ACCOUNT, UUID(int=0xFEED)):
            views = [await reads.read(family, account) for family in wt.FAMILIES]
            assert [view.items for view in views] == [(), (), ()]
        await until(lambda: world.store._orders[SENDING.id].lifecycle_state == "submitted")
        view = await reads.read("orders", cr.ACCOUNT)
        assert [item["id"] for item in view.items] == [str(SENDING.id)]


async def test_without_topics_nothing_is_published_or_read() -> None:
    world = World()
    await crashed(world)
    async with started(world.runtime()) as runtime:
        for flag in world.flags:
            flag.read()
        await until(lambda: runtime.state == "ok")
        parts = runtime._composed()
        assert parts.topic_reads is None
        with pytest.raises(OmsNotReady):
            await OnLaneTopicReads(parts).read("orders", cr.ACCOUNT)


def test_create_app_serves_the_three_families_from_one_adapter_over_the_hub() -> None:
    app = appmod.create_app(Settings(environment=Environment.TESTNET))
    services = app.state.ws_registry.services
    sources: dict[str, Any] = services.snapshots._sources
    topic = sources["orders"]
    assert isinstance(topic, wt.OmsTopics)
    assert sources["executions"] is topic and sources["positions"] is topic
    assert topic._publish == services.sequencing.publish
    assert list(topic._rank) == list(PRIVATE_CAUSAL_ORDER)
