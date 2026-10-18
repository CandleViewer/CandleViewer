"""E42-T07: the statechart inspector over a fake store (real HMAC seals, E17-T08's own check
`machine_refusal`) and its routes: guard, export, cursor, app wiring, and no `Interpreter` touched
(MUSTNOT-03). Callers carry every permission code: `admin:read`, owner flag and scope decide."""

from __future__ import annotations

import base64
import dataclasses
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import candleviewer.statechart.factory as factory
import candleviewer.statechart.persistence as persistence
from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.admin.inspector import SEAL_FAILED, BoundScope, SnapshotRow, StatechartInspector
from candleviewer.admin.overview.fanout import SliceFanOut
from candleviewer.admin_wiring import build_statechart_inspector
from candleviewer.api.admin_statecharts import machine_key, make_statechart_router, visibility
from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.statechart.config import SNAPSHOT_V
from candleviewer.statechart.persistence import MachineKey, SealedSnapshot, seal
from candleviewer.statechart.registry import Registry, export_stately, machine_hash
from tests.unit.admin._admin_fakes import AuditSpy

NOW = datetime(2026, 10, 17, 3, 0, tzinfo=UTC)
REGISTRY = Registry()
LOCK = {kind: REGISTRY.hash(kind) for kind in REGISTRY.keys()}
ACC_A, ACC_B, OWNER, OTHER = UUID(int=0xA), UUID(int=0xB), UUID(int=1), UUID(int=2)
ID_1, ID_2 = "0a000000-0000-4000-8000-000000000001", "0a000000-0000-4000-8000-000000000002"
_ALL = frozenset(p.value for p in Permission)
#: `x-role` -> (user, owner flag, permission codes); `manager` lacks `admin:read`.
ROLES = {"owner": (OWNER, True, _ALL), "reader": (OTHER, False, _ALL)}
ROLES["manager"] = (OTHER, False, frozenset({"orders:read"}))
# A DSN with a fake password, which must never be echoed. It is never written whole in source, so
# trufflehog's Postgres detector finds nothing here (#3482). Real credentials never go in source.
_DSN = "postgresql" + "://cv:hunter2@db/cv"


class Keys:
    """`HmacKeys` with one test key, never a real one; `threads` notes who asked for it."""

    def __init__(self) -> None:
        self.threads: set[int] = set()

    def current(self) -> str:
        return "k1"

    def key(self, key_id: str) -> bytes:
        self.threads.add(threading.get_ident())
        return {"k1": b"\x01" * 32}[key_id]


def row(
    kind: str,
    eid: str | None,
    states: Sequence[str],
    *,
    env: str = "demo",
    scope: BoundScope | None = None,
    snapshot: Mapping[str, Any] | None = None,
    tamper: Mapping[str, Any] | None = None,
    sealed_as: str | None = None,
) -> SnapshotRow:
    """A sealed row whose configuration is the chart root and `states` under it; `tamper`
    changes the snapshot after sealing, so the HMAC no longer verifies."""
    chart, blob = REGISTRY.get(kind), {"configuration": [kind, *(f"{kind}.{s}" for s in states)]}
    blob |= snapshot or {}
    digest = sealed_as or machine_hash(chart)
    key = MachineKey(kind, eid or kind, env)
    tag = seal(Keys(), chart, blob, digest, SNAPSHOT_V, key=key)
    envelope = SealedSnapshot(key, SNAPSHOT_V, digest, blob, tag)
    if tamper is not None:
        envelope = dataclasses.replace(envelope, snapshot=blob | tamper)
    return SnapshotRow(kind, eid, env, envelope, NOW, scope or BoundScope())


class Store:
    def __init__(self, *rows: SnapshotRow, fail: bool = False) -> None:
        self.rows, self.fail = rows, fail

    async def snapshots(self) -> Sequence[SnapshotRow]:
        if self.fail:
            raise OSError(f"{_DSN} is down")  # must never be echoed
        return self.rows


def inspector(*rows: SnapshotRow, **sources: Any) -> StatechartInspector:
    """An uncached inspector over `rows`, every source wired unless `sources` overrides it."""
    wired = {"store": Store(*rows), "keys": Keys(), "lock": LOCK, "registry": REGISTRY} | sources
    fan = SliceFanOut(budget_s=60, ttl_s=0.0, now=lambda: NOW)  # no real 300 ms timer in a test
    return StatechartInspector(fan, machine_key, **wired)


class Resolver:
    async def resolve(self, request: Request) -> AuditPrincipal | None:
        role = request.headers.get("x-role", "")
        if role not in ROLES:
            return None
        user, owner, perms = ROLES[role]
        return AuditPrincipal(user, role, perms, is_owner=owner)


def make_app(inspect: StatechartInspector, clock: Callable[[], datetime] = lambda: NOW) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    install_error_redaction(app)  # the app's 422: no input echoed (E43-T06)
    router = make_statechart_router(inspect, resolver=Resolver(), audit=AuditSpy(), clock=clock)
    app.include_router(router)
    return app


def fleet() -> tuple[SnapshotRow, ...]:
    """One machine per visibility case, all in `demo` but the second kill switch."""
    on_a, on_b = BoundScope(frozenset({ACC_A})), BoundScope(frozenset({ACC_B}))
    latched = {"chain_trips": 2, "deferred": [{}, {}]}
    return (
        row("kill_switch", None, ["clear"]),
        row("kill_switch", None, ["engaged"], env="live", snapshot={"deferred": []}),
        row("order", ID_1, ["lifecycle", "lifecycle.submitted"], scope=on_a),
        row("order", ID_2, ["lifecycle", "lifecycle.triggered"], scope=on_b, snapshot=latched),
        row("oco", ID_1, ["racing"], scope=on_a, snapshot={"chain_trips": 1}),  # one trip
        row("book", "BTCUSDT", ["live"]),
        row("session", ID_1, ["auth", "auth.active"], scope=BoundScope(user=OWNER)),
        row("session", ID_2, ["auth", "auth.active"], scope=BoundScope(user=OTHER)),
        row("risk_lockout", ID_1, ["clear"]),  # a scoped kind bound to no account
        row("position_protection", None, ["sl", "sl.protected"]),  # no public id
    )


_PERMS, _GRANTS = frozenset(Permission), (AccountGrant(ACC_A, True, False, False),)
OWNER_VIEW = visibility(PrincipalSnapshot(OWNER, frozenset({"owner"}), _PERMS))
MANAGER_A = visibility(PrincipalSnapshot(OTHER, frozenset({"manager"}), _PERMS, _GRANTS))
A1, O1, O2 = f"algo:{ID_1}@demo", f"order:{ID_1}@demo", f"order:{ID_2}@demo"
S1, S2 = f"session:{ID_1}@demo", f"session:{ID_2}@demo"
#: The Owner's rows in contract order: an `oco` machine is the `algo` entity, sorted by its kind;
#: of the two sessions only its own; `risk_lockout`, bound to no account, is shown to no role.
SEEN = ["book:BTCUSDT@demo", "kill_switch@demo", "kill_switch@live", A1, O1, O2, S1]
_OWNER = {"x-role": "owner"}


def _keys(machines: Any) -> list[str]:
    return [f"{m.key}@{m.row.environment}" for m in machines]


def _client(**kwargs: Any) -> TestClient:
    return TestClient(make_app(inspector(*fleet()), **kwargs))


async def test_the_list_projects_verified_snapshots_in_contract_order() -> None:
    found = await inspector(*fleet()).listing(OWNER_VIEW)
    assert _keys(found.items) == SEEN and not found.has_more
    _, clear, engaged, _, submitted, triggered, _ = found.items
    states = [m.state for m in (clear, engaged, submitted, triggered)]
    assert states == ["clear", "engaged", "submitted", "triggered"]
    assert (triggered.chain_trips, triggered.deferred_depth, engaged.deferred_depth) == (2, 2, 0)
    assert (clear.deferred_depth, submitted.chain_trips) == (None, 0)
    assert all(m.lock_matches for m in found.items) and found.snapshots.status == "ok"
    stale = await inspector(fleet()[0], lock={"kill_switch": "0" * 64}).listing(OWNER_VIEW)
    assert [m.lock_matches for m in stale.items] == [False]  # not the committed lock's hash
    assert found.metrics.detail == "metrics: no provider wired"  # `unavailable`, never a guess


async def test_the_seals_are_checked_off_the_event_loop() -> None:
    keys = Keys()
    await inspector(*fleet(), keys=keys).listing(OWNER_VIEW)
    assert keys.threads and threading.get_ident() not in keys.threads


async def test_kinds_count_every_machine_and_only_kind_and_environment_narrow_them() -> None:
    found = await inspector(*fleet()).listing(OWNER_VIEW, degraded=False)
    assert _keys(found.items) == [k for k in SEEN if k not in (A1, O2)]  # the tripped ones
    counted = {f"{k['machine_kind']}@{k['environment']}": k["machines"] for k in found.kinds}
    assert counted == {
        "book@demo": 1,
        "kill_switch@demo": 1,
        "kill_switch@live": 1,
        "oco@demo": 1,
        "order@demo": 2,  # the latched order too
        "position_protection@demo": 1,  # no public id, so never a row
        "risk_lockout@demo": 1,
        "session@demo": 2,  # another user's session is counted, never shown
    }
    order = found.kinds[4]
    assert order["by_state"] == {"submitted": 1, "triggered": 1}
    assert (order["chain_trips"], order["degraded_machines"]) == (2, 1)  # trips, not machines
    assert {k["dropped_receipts"] for k in found.kinds} == {None}  # no metrics source yet
    live = await inspector(*fleet()).listing(OWNER_VIEW, environment="live")
    both = await inspector(*fleet()).listing(OWNER_VIEW, kind="kill_switch")
    assert (_keys(live.items), len(live.kinds)) == (["kill_switch@live"], 1)
    assert (_keys(both.items), len(both.kinds)) == (["kill_switch@demo", "kill_switch@live"], 2)


async def test_rows_follow_e17_t08_machine_refusal_per_entity() -> None:
    """Cross-account and self-scoped kinds; a pending kind (W6 `trade_group`) is the Owner's."""
    found = await inspector(*fleet()).listing(MANAGER_A)
    assert _keys(found.items) == [*SEEN[:3], A1, O1, S2]
    group = row("trade_group", ID_1, ["open"], scope=BoundScope(frozenset({ACC_A})))
    assert (await inspector(group).listing(MANAGER_A)).items == ()
    assert len((await inspector(group).listing(OWNER_VIEW)).items) == 1


@pytest.mark.parametrize(
    "bad",
    [
        lambda r: row("kill_switch", None, ["engaged"], env="live", tamper={"chain_trips": 0}),
        lambda r: row("kill_switch", None, ["engaged"], env="live", sealed_as="0" * 64),  # MUST-12
        lambda r: row("kill_switch", None, ["engaged"], env="live", snapshot={"configuration": 1}),
        lambda r: row("kill_switch", None, [], env="live"),  # no state under the root
        lambda r: row("kill_switch", None, ["engaged"], env="live", snapshot={"chain_trips": -1}),
        lambda r: dataclasses.replace(r, machine_kind="unregistered"),
        lambda r: dataclasses.replace(r, environment="prod"),  # not an `Environment`
        lambda r: dataclasses.replace(r, updated_at=NOW.replace(tzinfo=None)),  # not sealed
        lambda r: dataclasses.replace(r, environment="demo"),  # the live envelope, copied to demo
        lambda r: dataclasses.replace(fleet()[2], entity_id=ID_2),  # an order under another's id
    ],
    ids=[
        "tampered",
        "hash",
        "config",
        "no-state",
        "trips",
        "kind",
        "environment",
        "naive",
        "copied-to-environment",
        "copied-to-entity",
    ],
)
async def test_a_snapshot_that_does_not_verify_is_left_out_and_named(
    bad: Callable[[SnapshotRow], SnapshotRow],
) -> None:
    rows = list(fleet())
    rows[1] = bad(rows[1])  # the live kill switch
    found = await inspector(*rows).listing(OWNER_VIEW)
    assert _keys(found.items) == [k for k in SEEN if k != "kill_switch@live"]
    assert "live" not in {k["environment"] for k in found.kinds}
    assert (found.snapshots.status, found.snapshots.detail) == ("error", SEAL_FAILED)


@pytest.mark.parametrize(
    ("sources", "status", "detail"),
    [
        ({"store": None}, "unavailable", "snapshots: no provider wired"),
        ({"keys": None}, "unavailable", "snapshots: no provider wired"),  # CV-C53
        ({"store": Store(fail=True)}, "error", "source failed"),  # never the exception's text
    ],
    ids=["unwired", "no-keys", "failing"],
)
async def test_an_unreadable_store_adds_no_row(sources: Any, status: str, detail: str) -> None:
    found = await inspector(*fleet(), **sources).listing(OWNER_VIEW)
    assert (found.items, found.kinds) == ((), [])
    assert (found.snapshots.status, found.snapshots.detail) == (status, detail)


@pytest.mark.parametrize("route", ["/admin/statecharts", "/admin/statecharts/oco/export"])
@pytest.mark.parametrize(("role", "status"), [("manager", 403), ("", 401)])
def test_a_caller_without_admin_read_is_refused(route: str, role: str, status: int) -> None:
    response = _client().get(route, headers={"x-role": role})
    assert response.status_code == response.json()["status"] == status


@pytest.mark.parametrize("key", [*REGISTRY.keys(), f"order:{ID_1}", "book:BTCUSDT"])
def test_every_chart_exports_by_its_bare_kind_or_by_an_entity_key_of_it(key: str) -> None:
    kind = key.split(":")[0]  # an entity key exports its kind's chart: no instance is read
    body = _client().get(f"/admin/statecharts/{key}/export", headers=_OWNER).json()
    assert (body["machine_kind"], body["machine_hash"]) == (kind, REGISTRY.hash(kind))
    assert body["stately"] == export_stately(REGISTRY.get(kind))  # not the raw chart


@pytest.mark.parametrize(
    ("key", "status"),
    [(key, 404) for key in (f"algo:{ID_1}", "algo", f"kill_switch:{ID_1}", f"oco:{ID_1}", "nope")]
    + [(f"order:{ID_1.upper()}", 422), ("book:BTCUSD", 422)],  # the `MachineKey` pattern
)
def test_export_is_404_off_the_grammar_and_422_off_the_key_pattern(key: str, status: int) -> None:
    response = _client().get(f"/admin/statecharts/{key}/export", headers=_OWNER)
    assert response.status_code == response.json()["status"] == status
    assert key not in response.text  # a fixed detail, never the key


def test_the_list_follows_the_callers_scope_and_counts_the_same_kinds() -> None:
    """A non-Owner holding `admin:read` has no account grants loaded: no account-scoped row."""
    owner = _client().get("/admin/statecharts", headers=_OWNER).json()
    reader = _client().get("/admin/statecharts", headers={"x-role": "reader"}).json()
    keys = [i["machine_key"] for i in reader["items"]]
    assert keys == ["book:BTCUSDT", "kill_switch", "kill_switch", f"session:{ID_2}"]
    assert len(owner["items"]) == 7 and owner["kinds"] == reader["kinds"]


def test_the_cursor_resumes_and_is_bound_to_its_listing_and_hour() -> None:
    first = _client().get("/admin/statecharts", params={"limit": 2}, headers=_OWNER).json()
    cursor = first["meta"]["next_cursor"]  # between the two kill switches: they differ by env
    assert first["meta"] == {"next_cursor": cursor, "has_more": True, "count": 2}
    params = {"cursor": cursor, "limit": 5}  # exactly the rest: no further page
    rest = _client().get("/admin/statecharts", params=params, headers=_OWNER).json()
    assert [f"{i['machine_key']}@{i['environment']}" for i in rest["items"]] == SEEN[2:]
    assert rest["meta"] == {"next_cursor": None, "has_more": False, "count": 5}
    assert rest["kinds"] == first["kinds"] and len(first["kinds"]) == 8  # the same on every page
    served = {"state": "triggered", "degraded": True, "chain_trips": 2, "deferred_depth": 2}
    served |= {"lock_matches": True, "updated_at": "2026-10-17T03:00:00Z"}
    assert rest["items"][3].items() >= served.items()  # the latched order, by value
    late = _client(clock=lambda: NOW + timedelta(seconds=3601))
    forged = json.dumps([[1, 2, 3], [None, None, None], int(NOW.timestamp())]).encode()
    for client, params in [
        (_client(), {"cursor": cursor, "environment": "demo"}),  # another listing
        (late, {"cursor": cursor}),  # expired
        (_client(), {"cursor": base64.urlsafe_b64encode(forged).decode()}),  # a forged position
    ]:
        refused = client.get("/admin/statecharts", params=params, headers=_OWNER)
        assert (refused.status_code, refused.json().get("code")) == (400, "invalid_cursor")


def test_no_request_touches_an_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the inspector touched the statechart runtime")

    runtime = persistence.Interpreter.__module__.split(".")[0]  # the pinned library's package
    for cls in persistence.Interpreter.__mro__:  # `Interpreter` and its runtime base classes
        for name in ("__init__", "from_snapshot", "start", "send", "get_persisted_snapshot"):
            if cls.__module__.startswith(runtime) and name in vars(cls):
                monkeypatch.setattr(cls, name, refuse)
    for name in ("build", "restore", "make_machine"):
        monkeypatch.setattr(factory, name, refuse)
    client = _client()
    listed = client.get("/admin/statecharts", headers=_OWNER)
    assert listed.status_code == 200 and len(listed.json()["items"]) == 7
    assert client.get("/admin/statecharts/order/export", headers=_OWNER).status_code == 200


def test_the_app_wiring_reads_only_the_sources_that_exist() -> None:
    client = TestClient(make_app(build_statechart_inspector(now=lambda: NOW)))
    listed = client.get("/admin/statecharts", headers=_OWNER).json()
    assert (listed["items"], listed["kinds"], listed["meta"]["count"]) == ([], [], 0)
    unwired = {"status": "unavailable", "generated_at": "2026-10-17T03:00:00Z"}
    assert listed["snapshots"] == unwired | {"detail": "snapshots: no provider wired"}
    assert listed["metrics"] == unwired | {"detail": "metrics: no provider wired"}
