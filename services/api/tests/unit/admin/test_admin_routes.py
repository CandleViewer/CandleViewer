"""E42-T01 route slice: the rendering hand-offs of `candleviewer.api.admin_overview`, the
composition-root wiring (`candleviewer.admin_wiring`) and the route latency benchmark
(`-m perf`). The audited guard itself is tested in `test_admin_http.py`."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import candleviewer.admin_wiring as wiring
from candleviewer.admin.overview.capacity import (
    CapacitySnapshot,
    DiskProjection,
    SubaccountCapacity,
    SymbolProjection,
)
from candleviewer.admin.overview.fanout import SliceResult, SliceStatus
from candleviewer.admin.overview.ports import AccountCounts, RecorderStatus, UserCounts
from candleviewer.admin.overview.service import OverviewSnapshot, StorageHeadroom, TradingState
from candleviewer.api.admin_overview import (
    capacity_payload,
    make_admin_overview_router,
    overview_payload,
)
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.admin_readmodel_sqlalchemy import AccountTotals, UserTotals
from tests.unit.admin._admin_fakes import AuditSpy, Resolver
from tests.unit.admin._route_fakes import NOW, Ports, make_app

_BLOCK = {"status", "detail", "generated_at"}
_AT = "2026-10-16T00:30:00Z"


def _slice(value: Any, status: SliceStatus = "ok") -> SliceResult[Any]:
    return SliceResult(status, NOW, value, None if status == "ok" else "source failed")


def _overview(trading: SliceResult[TradingState], incidents: SliceResult[int]) -> dict[str, Any]:
    users, accounts = _slice(UserCounts(1, 1, 0)), _slice(AccountCounts(1, 1, 0, 0))
    recorder, storage = _slice(RecorderStatus(1, 0, 0.1)), _slice(StorageHeadroom(1, 2, None))
    snap = OverviewSnapshot(NOW, users, accounts, recorder, storage, trading, incidents)
    return overview_payload(snap)


_ALL_READ = {"live_enabled": False, "kill_switch_engaged": False, "open_positions": 0}


@pytest.mark.parametrize(
    ("state", "shown"),
    [
        (TradingState(None, None, None), {}),
        (TradingState(None, True, 2), {"kill_switch_engaged": True, "open_positions": 2}),
        (TradingState(False, False, 0), _ALL_READ),
    ],
    ids=["none-none-none", "none-true-n", "all-read"],
)
def test_an_unread_trading_field_is_omitted_never_a_boolean(
    state: TradingState, shown: dict[str, Any]
) -> None:
    status: SliceStatus = "ok" if state.live_enabled is not None else "error"
    trading = _overview(_slice(state, status), _slice(0))["trading"]
    assert {k: v for k, v in trading.items() if k not in _BLOCK} == shown


@pytest.mark.parametrize(("status", "mirrored"), [("ok", True), ("error", False)])
def test_incidents_open_mirrors_the_slice_only_when_it_was_read(
    status: SliceStatus, mirrored: bool
) -> None:
    body = _overview(_slice(TradingState(False, False, 0)), _slice(3 if mirrored else None, status))
    assert ("incidents_open" in body, "open" in body["incidents"]) == (mirrored, mirrored)


def test_overview_storage_keeps_a_null_days_until_full() -> None:
    body = _overview(_slice(TradingState(False, False, 0)), _slice(0))
    assert body["storage"]["days_until_full"] is None  # no exhaustion ahead: a value, kept


_TIER_IDS = "recorded unrecorded tier-failed used-failed unrec-used-failed both-failed unread"
_TIER = {"tier": "regular", "cap": 5, "tier_source": "recorded", "recorded_at": _AT}
_UNRECORDED = dict.fromkeys(("tier", "cap", "recorded_at")) | {"tier_source": "unrecorded"}


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (SubaccountCapacity("regular", 5, 3, "recorded", NOW), _TIER | {"used": 3}),
        (SubaccountCapacity(None, None, 3, "unrecorded", None), _UNRECORDED | {"used": 3}),
        (SubaccountCapacity(None, None, 3, None, None), {"used": 3}),  # tier read failed
        (SubaccountCapacity("regular", 5, None, "recorded", NOW), _TIER),  # usage read failed
        (SubaccountCapacity(None, None, None, "unrecorded", None), _UNRECORDED),
        (SubaccountCapacity(None, None, None, None, None), {}),  # both parts failed
        (None, {}),  # the slice was not read at all
    ],
    ids=_TIER_IDS.split(),
)
def test_tier_fields_are_omitted_unless_the_tier_was_read(
    value: SubaccountCapacity | None, shown: dict[str, Any]
) -> None:
    complete = value is not None and None not in (value.used, value.tier_source)
    status: SliceStatus = "ok" if complete else "error"
    body = capacity_payload(_capacity(_slice(value, status)))["subaccounts"]
    assert {k: v for k, v in body.items() if k not in _BLOCK} == shown


def _capacity(sub: SliceResult[SubaccountCapacity]) -> CapacitySnapshot:
    pinned = SymbolProjection("BTCUSDT", 10, 0, True, None)
    disk = DiskProjection(10, 20, 0, None, 0, "nothing_recorded", False, (pinned,))
    return CapacitySnapshot(NOW, _slice(disk), _slice(None, "error"), _slice(None, "error"), sub)


def _capacity_body() -> dict[str, Any]:
    return capacity_payload(_capacity(_slice(None, "error")))


_PINNED = {"symbol": "BTCUSDT", "used_bytes": 10, "daily_growth_bytes": 0, "pinned": True}


@pytest.mark.parametrize(
    ("field", "sent"),
    [
        ("days_until_full", None),  # no exhaustion ahead: a value, kept
        ("projection_basis", "nothing_recorded"),  # the internal `basis`, renamed
        ("per_symbol", [_PINNED | {"retention_days": None}]),  # pinned: kept forever
    ],
    ids=["days-null-kept", "basis-renamed", "pinned-retention-null-kept"],
)
def test_capacity_storage_sends(field: str, sent: Any) -> None:
    assert _capacity_body()["storage"][field] == sent


def test_capacity_storage_never_sends_its_internal_fields() -> None:
    assert not {"projected_bytes", "basis"} & set(_capacity_body()["storage"])


def test_an_unread_rate_budget_sends_only_its_status() -> None:
    body = _capacity_body()
    assert "rate_budget" not in body and body["rate_budget_status"]["status"] == "error"


# -- composition-root wiring --------------------------------------------------------------------


class FakeCounts:
    """Stands in for `SqlAlchemyAdminCounts`; the test records what it was bound to."""

    expiring_before: Any = None

    async def user_totals(self) -> UserTotals:
        return UserTotals(5, 4, 1)

    async def account_totals(self, expiring_before: Any) -> AccountTotals:
        self.expiring_before = expiring_before
        return AccountTotals(6, 5, 2, 1)

    async def open_incidents(self) -> int:
        return 7

    async def subaccounts_in_use(self) -> int:
        return 3


async def test_the_real_backend_wires_env_bound_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    bound: list[tuple[Any, str]] = []
    counts = FakeCounts()

    def bind(relational: Any, *, env: str) -> FakeCounts:
        bound.append((relational, env))
        return counts

    monkeypatch.setattr(wiring, "SqlAlchemyRelationalRepository", lambda dsn, suffix: suffix)
    monkeypatch.setattr(wiring, "SqlAlchemyAdminCounts", bind)
    settings = Settings(storage_backend="real", environment=Environment.TESTNET)
    overview, capacity = wiring.build_admin_read_models(settings, now=lambda: NOW)
    snap, cap = await overview.overview(), await capacity.capacity()
    assert bound == [("admin", "testnet")]  # C-2.11: the serving environment only
    assert snap.users.value == UserCounts(5, 4, 1)
    assert snap.accounts.value == AccountCounts(6, 5, 2, 1)
    assert snap.incidents.value == 7 and cap.subaccounts.value is not None
    assert cap.subaccounts.value.used == 3 and cap.subaccounts.status == "unavailable"  # no tier
    assert counts.expiring_before == NOW + timedelta(days=30)  # the injected clock, passed on
    # ... to the overview, the capacity report and the fan-out (each slice's own stamp)
    assert (snap.generated_at, cap.generated_at, snap.users.generated_at) == (NOW, NOW, NOW)


def test_every_unwired_source_is_reported_unavailable_never_faked() -> None:
    overview, capacity = wiring.build_admin_read_models(Settings(storage_backend="fake"))
    router = make_admin_overview_router(overview, capacity, resolver=Resolver(), audit=AuditSpy())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    for path in ("/admin/overview", "/admin/capacity"):
        body = client.get(path, headers={"x-role": "owner"}).json()
        slices = {k: v for k, v in body.items() if isinstance(v, dict)}
        assert {v["status"] for v in slices.values()} == {"unavailable"}, path
        assert all(set(block) == _BLOCK for block in slices.values()), body  # no figures
        assert "incidents_open" not in body and "rate_budget" not in body


# -- perf (C-13.9; the issue's numbers, deselected by default) ----------------------------------


@pytest.mark.perf
@pytest.mark.parametrize(
    ("hang", "budget_ms", "n"), [(False, 300, 40), (True, 500, 20)], ids=["healthy", "one-hung"]
)
async def test_admin_routes_p95_within_budget(hang: bool, budget_ms: int, n: int) -> None:
    transport = httpx.ASGITransport(app=make_app(Ports(hang=hang), ttl_s=0.0)[0])  # no cache
    async with httpx.AsyncClient(transport=transport, base_url="http://cv") as client:
        for path in ("/admin/overview", "/admin/capacity"):
            samples = []
            for _ in range(n):
                t0 = time.perf_counter()
                response = await client.get(path, headers={"x-role": "owner"})
                samples.append(time.perf_counter() - t0)
                assert response.status_code == 200
            samples.sort()
            p95_ms = samples[int(0.95 * n) - 1] * 1000
            print(f"[perf][E42-T01] GET {path} hang={hang} p95={p95_ms:.1f}ms n={n}")
            assert p95_ms <= budget_ms
