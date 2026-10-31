"""E24-T03 (#667): the liquidation wiring: guarded store, fake/real composition, stream writer."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.app import _compose_liquidations, build_app_context, create_app
from candleviewer.domain.liquidations import LiqPrint
from candleviewer.liquidations_wiring import GuardedLiquidationStore, wire_liquidations
from candleviewer.orderflow.service import OrderflowService
from candleviewer.settings import Settings
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.questdb.liquidation_store import InMemoryLiquidationStore
from candleviewer.storage.questdb.repository import QuestDbMarketDataRepository


class _Storage:
    def __init__(self, repo: object | None) -> None:
        self._repo = repo

    @property
    def market_data(self) -> object:
        if self._repo is None:
            raise StorageTierUnavailable("not started")
        return self._repo


def _ctx(repo: object | None, listed: frozenset[str] | None = None) -> Any:
    snap = None
    if listed is not None:
        snap = SimpleNamespace(
            get=lambda s: SimpleNamespace(status="trading") if s in listed else None
        )
    instruments = None if snap is None else SimpleNamespace(snapshot=lambda: snap)
    return SimpleNamespace(
        storage=_Storage(repo),
        orderflow=OrderflowService(),
        ingestion=SimpleNamespace(instruments=instruments),
    )


P = LiqPrint(1_000, "BTCUSDT", "sell", Decimal(2), Decimal(3), Decimal(6), 0)


async def test_guarded_store_is_unavailable_until_the_tier_starts_then_builds_once() -> None:
    built: list[object] = []
    inner = InMemoryLiquidationStore()

    def factory(repo: object) -> InMemoryLiquidationStore:
        built.append(repo)
        return inner

    ctx = _ctx(None)
    guarded = GuardedLiquidationStore(ctx, None, factory)
    with pytest.raises(StorageTierUnavailable):
        await guarded.first_ts("BTCUSDT")
    ctx.storage._repo = "repo"
    await guarded.write_prints([P])
    assert await guarded.first_ts("BTCUSDT") == 1_000
    assert len(await guarded.read_prints("BTCUSDT", SimpleNamespace(start_us=0, end_us=9_999),
                                         None, 10)) == 1  # fmt: skip
    assert built == ["repo"]
    with pytest.raises(StorageTierUnavailable):
        await GuardedLiquidationStore(_ctx("repo"), None, lambda _r: None).first_ts("X")


async def test_wire_liquidations_attaches_the_service_with_a_listing_lookup() -> None:
    ctx = _ctx("repo", frozenset({"BTCUSDT"}))
    service = wire_liquidations(ctx, store=InMemoryLiquidationStore())
    assert ctx.orderflow.liquidations is service
    page = await service.page("BTCUSDT", start_us=None, end_us=None, limit=1, cursor=None,
                              side=None, min_notional=None, cluster_window_ms=0)  # fmt: skip
    assert page.coverage.no_coverage
    with pytest.raises(Exception, match="ETHUSDT"):
        await service.page("ETHUSDT", start_us=None, end_us=None, limit=1, cursor=None,
                           side=None, min_notional=None, cluster_window_ms=0)  # fmt: skip
    unlisted = wire_liquidations(_ctx("repo"), store=InMemoryLiquidationStore())
    assert (await unlisted.page("ETHUSDT", start_us=None, end_us=None, limit=1, cursor=None,
                                side=None, min_notional=None,
                                cluster_window_ms=0)).coverage.no_coverage  # fmt: skip


async def test_compose_fake_is_in_memory_and_real_builds_the_questdb_store_on_use() -> None:
    ctx = build_app_context(Settings())
    await ctx.storage.start(ctx)
    _compose_liquidations(ctx, Settings())
    service = ctx.orderflow.liquidations
    assert service is not None
    await service.write([])
    assert await service._store.first_ts("BTCUSDT") is None

    class _Writer:
        def __init__(self) -> None:
            self.rows: list[dict[str, object]] = []

        async def write_rows(self, table: str, rows: list[dict[str, object]], key: str) -> None:
            self.rows.extend(rows)

    _compose_liquidations(ctx, Settings(storage_backend="real"))
    real = ctx.orderflow.liquidations
    assert real is not None
    with pytest.raises(StorageTierUnavailable):  # the fake repository is no QuestDB one
        await real._store.first_ts("BTCUSDT")
    writer = _Writer()
    ctx.storage._market_data = QuestDbMarketDataRepository(writer, None)  # type: ignore[arg-type]  # a structural writer, no reader is read
    await real._store.write_prints([P])
    assert writer.rows[0]["stream"] == "all"


def test_create_app_mounts_liquidations() -> None:
    app = create_app(Settings())
    paths, todo = set(), list(app.routes)
    while todo:  # routers are included lazily: walk each one's own routes
        route = todo.pop()
        paths.add(getattr(route, "path", ""))
        todo.extend(getattr(getattr(route, "original_router", None), "routes", []))
    assert any(p.endswith("/market/liquidations") for p in paths)
