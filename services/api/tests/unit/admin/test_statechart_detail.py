"""E42-T07: `getStatechart` over a fake store (real HMAC seals, E17-T08's `machine_refusal`): the
scope bound from the topic's registry (`RegistryScopedStore`), a non-Owner's grants, one `404` for
an unknown machine and a hidden one, the seal checked after visibility, the redacted context
summary and the payload-free timeline."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from candleviewer.admin.inspector import (
    SEAL_FAILED,
    BoundScope,
    RecentEvent,
    SnapshotRow,
    StatechartInspector,
    context_summary,
)
from candleviewer.admin.overview.fanout import SliceFanOut
from candleviewer.admin_wiring import RegistryScopedStore, build_admin_grants
from candleviewer.api.admin_statecharts import machine_key
from candleviewer.auth.scopes import AccountGrant
from candleviewer.settings import Settings
from candleviewer.statechart.persistence import MachineKey
from candleviewer.storage.repositories.scope_sqlalchemy import SqlAlchemyScopeSource
from candleviewer.ws.topics import EntityScope
from tests.unit.admin.test_statechart_inspector import (
    ACC_A,
    ACC_B,
    ID_1,
    ID_2,
    LOCK,
    NOW,
    REGISTRY,
    Keys,
    Store,
    fleet,
    inspector,
    make_app,
    row,
)

_OWNER, _READER = {"x-role": "owner"}, {"x-role": "reader"}
_CONTEXT = {"symbol": "BTCUSDT", "halted_by_kill": False, "recon_misses": 1, "qty": "5"}
_EVENT = RecentEvent("FILL", "commit", ("order.a",), ("order.b",), False, NOW)


class Events:
    def __init__(self, *events: RecentEvent) -> None:
        self.events = events
        self.asked: list[tuple[MachineKey, int]] = []

    async def recent(self, key: MachineKey, limit: int) -> Sequence[RecentEvent]:
        self.asked.append((key, limit))
        return self.events


def _rows() -> tuple[SnapshotRow, ...]:
    """The fleet, its first order carrying a context with a key the topic never sends."""
    rows = list(fleet())
    on_a = rows[2].scope
    rows[2] = row("order", ID_1, ["lifecycle", "lifecycle.submitted"], scope=on_a,
                  snapshot={"context": _CONTEXT})  # fmt: skip
    return tuple(rows)


def _get(client: TestClient, key: str, headers: dict[str, str], env: str = "demo") -> Any:
    return client.get(f"/admin/statecharts/{key}", params={"environment": env}, headers=headers)


def _client(*rows: SnapshotRow, grants: Any = None, **sources: Any) -> TestClient:
    return TestClient(make_app(inspector(*(rows or _rows()), **sources), grants=grants))


def test_the_owner_reads_a_machines_redacted_detail_and_timeline() -> None:
    events = Events(_EVENT)
    body = _get(_client(events=events), f"order:{ID_1}", _OWNER).json()
    assert body["machine"]["machine_key"] == f"order:{ID_1}"
    summary = {"symbol": "BTCUSDT", "halted_by_kill": False, "recon_misses": 1}  # no `qty`
    assert body["context_summary"] == summary
    assert body["configuration"] == ["order", "order.lifecycle", "order.lifecycle.submitted"]
    assert body["config"] == REGISTRY.get("order")
    assert body["recent_events"] == [
        {"event_type": "FILL", "phase": "commit", "from_states": ["order.a"],
         "to_states": ["order.b"], "faulted": False, "occurred_at": "2026-10-17T03:00:00Z"}
    ]  # fmt: skip
    assert body["snapshots"]["status"] == body["events"]["status"] == "ok"
    assert events.asked == [(MachineKey("order", ID_1, "demo"), 50)]


def test_a_kind_without_summary_keys_sends_none_and_an_unwired_timeline_says_so() -> None:
    body = _get(_client(), "kill_switch", _OWNER).json()
    assert "context_summary" not in body and body["machine"]["state"] == "clear"
    assert body["events"] == {"status": "unavailable", "detail": "events: no provider wired",
                              "generated_at": "2026-10-17T03:00:00Z"}  # fmt: skip
    assert "recent_events" not in body


def test_an_algo_key_finds_the_chart_that_holds_the_entity() -> None:
    assert _get(_client(), f"algo:{ID_1}", _OWNER).json()["machine"]["machine_kind"] == "oco"


@pytest.mark.parametrize(
    ("key", "headers", "env"),
    [
        (f"order:{ID_2}", _READER, "demo"),  # another account's order: no grant on ACC_B
        (f"order:{ID_1}", _READER, "demo"),  # granted, but the grant source is not wired
        (f"session:{ID_2}", _OWNER, "demo"),  # another user's session, the Owner included
        (f"risk_lockout:{ID_1}", _OWNER, "demo"),  # a scoped kind bound to no account
        (f"order:{ID_1}", _OWNER, "live"),  # no such machine in that environment
        ("order:0a000000-0000-4000-8000-0000000000ff", _OWNER, "demo"),  # no such machine
        ("position_protection", _OWNER, "demo"),  # no public id
        (f"oco:{ID_1}", _OWNER, "demo"),  # off the grammar: `algo:{id}`
    ],
)
def test_an_unknown_machine_and_a_hidden_one_are_the_same_404(
    key: str, headers: dict[str, str], env: str
) -> None:
    missing = _get(_client(), "order:0a000000-0000-4000-8000-0000000000ee", _OWNER)
    response = _get(_client(), key, headers, env)
    assert (response.status_code, response.json()) == (404, missing.json())
    assert key.split(":")[-1] not in response.text  # a fixed detail, never the key


def test_a_non_owner_sees_only_its_granted_accounts_machines() -> None:
    async def grants(user: UUID) -> Sequence[AccountGrant]:
        return (AccountGrant(ACC_A, True, False, False),)

    client = _client(grants=grants)
    assert _get(client, f"order:{ID_1}", _READER).json()["machine"]["state"] == "submitted"
    assert _get(client, f"order:{ID_2}", _READER).status_code == 404
    listed = client.get("/admin/statecharts", headers=_READER).json()["items"]
    assert f"order:{ID_1}" in {i["machine_key"] for i in listed}
    assert f"order:{ID_2}" not in {i["machine_key"] for i in listed}


def test_a_grant_read_that_fails_grants_nothing() -> None:
    async def grants(user: UUID) -> Sequence[AccountGrant]:
        raise OSError("down")

    assert _get(_client(grants=grants), f"order:{ID_1}", _READER).status_code == 404


def test_the_seal_is_checked_after_visibility() -> None:
    rows = list(_rows())
    rows[3] = row("order", ID_2, ["lifecycle"], scope=rows[3].scope, tamper={"chain_trips": 9})
    client = _client(*rows)
    failed = _get(client, f"order:{ID_2}", _OWNER).json()
    assert failed["snapshots"]["status"] == "error" and failed["snapshots"]["detail"] == SEAL_FAILED
    assert set(failed) == {"snapshots"}  # no machine field and no timeline
    assert _get(client, f"order:{ID_2}", _READER).status_code == 404  # hidden first


@pytest.mark.parametrize(
    ("sources", "status"),
    [({"store": None}, "unavailable"), ({"store": Store(fail=True)}, "error")],
)
def test_an_unreadable_store_is_a_200_without_the_machine(sources: Any, status: str) -> None:
    body = _get(_client(**sources), "kill_switch", _OWNER).json()
    assert set(body) == {"snapshots"} and body["snapshots"]["status"] == status


def test_the_detail_needs_its_environment() -> None:
    response = _client().get("/admin/statecharts/kill_switch", headers=_OWNER)
    assert response.status_code == 422


def test_the_summary_keeps_only_the_topics_keys_of_their_types() -> None:
    assert context_summary("order", {"symbol": "btc", "recon_misses": -1, "x": 1}, None) == {}
    assert context_summary("book", {}, "ETHUSDT") == {"symbol": "ETHUSDT"}
    assert context_summary("order", {}, "ETHUSDT") == {}  # only a book's or a recording's id
    assert context_summary("trade_group", {"anything": 1}, ID_1) == {}
    assert context_summary("order", "not a mapping", ID_1) == {}


async def test_the_scope_is_the_registrys_for_the_serving_environment_only() -> None:
    bound = EntityScope(frozenset({ACC_B}))
    asked: list[str] = []

    def scope_of(ch: str) -> EntityScope | None:
        asked.append(ch)
        return bound if ch == f"machines.order:{ID_1}.state" else None

    rows = (
        row("order", ID_1, ["lifecycle"], scope=BoundScope(frozenset({ACC_A}))),  # never trusted
        row("order", ID_1, ["lifecycle"], env="live"),  # another environment
        row("order", ID_2, ["lifecycle"]),  # no live entry
        row("position_protection", None, ["sl"]),  # no public id
    )
    store = RegistryScopedStore(Store(*rows), scope_of, env="demo")
    scopes = [r.scope for r in await store.snapshots()]
    assert scopes == [BoundScope(frozenset({ACC_B})), BoundScope(), BoundScope(), BoundScope()]
    assert asked == [f"machines.order:{ID_1}.state", f"machines.order:{ID_2}.state"]
    one = await store.snapshot("order", ID_1, "demo")
    assert one is not None and one.scope == BoundScope(frozenset({ACC_B}))
    assert await store.snapshot("order", ID_1, "testnet") is None


def test_the_fake_backend_has_no_grant_source() -> None:
    assert build_admin_grants(Settings(storage_backend="fake")) is None


async def test_the_real_backend_reads_view_grants_without_trade_rights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def load_grants(self: Any, owner: UUID) -> list[tuple[UUID, bool, bool]]:
        return [(ACC_A, True, False), (ACC_B, False, True)]

    monkeypatch.setattr(SqlAlchemyScopeSource, "load_grants", load_grants)
    grants = build_admin_grants(Settings(storage_backend="real"))
    assert grants is not None
    assert await grants(UUID(int=2)) == (
        AccountGrant(ACC_A, True, False, False),
        AccountGrant(ACC_B, False, False, True),  # soft-revoked and frozen: `decide` refuses it
    )


def test_the_detail_reads_live_never_the_lists_cache() -> None:
    """The list's slice is cached for its `ttl`; a detail after a snapshot write sees the write."""
    store = Store(*_rows())
    fan = SliceFanOut(budget_s=60, ttl_s=3600.0, now=lambda: NOW)
    wired = StatechartInspector(fan, machine_key, LOCK, store=store, keys=Keys(), registry=REGISTRY)
    client = TestClient(make_app(wired))
    client.get("/admin/statecharts", headers=_OWNER)  # fills the list's cache
    assert _get(client, "kill_switch", _OWNER).json()["machine"]["state"] == "clear"
    store.rows = (row("kill_switch", None, ["engaged"]),)
    assert _get(client, "kill_switch", _OWNER).json()["machine"]["state"] == "engaged"
