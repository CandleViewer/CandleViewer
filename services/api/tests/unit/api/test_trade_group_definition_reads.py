"""E28-T05 S2b (#909): the definition reads over a store faked as Postgres scopes it and the real
`GateReadiness`. Core3 (E28-A, B, C) and Pair (E28-A, C) are the E28 seed's: B's key self-check
fails, so Core3 is "2 of 3 ready" (US-PROF-005 AC 4); A and C's grantee sees Pair alone."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.accounts.trade_group_definitions import definition_etag, stored_definition
from candleviewer.api.trade_group_cursor import CURSOR_TTL_S, encode_cursor
from candleviewer.api.trade_group_definitions import make_trade_group_definitions_router as router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.domain.primitives import Environment
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories import trade_group_definitions as port
from candleviewer.storage.repositories.accounts import AccountScope, OwnerScope
from candleviewer.trade_groups_wiring import GateReadiness, NoLockouts

_E28 = "e28f0000-0000-4000-8000-{:0>12}"
OWNER_ID, A, B, C, CORE3, PAIR = (UUID(_E28.format(t)) for t in "1 d1 d2 d3 a1 a2".split())
MANAGER_ID, MISSING, LIVE = UUID(int=7), UUID(int=404), UUID(int=9)
_AT, NOW = datetime(2026, 10, 27, 9, tzinfo=UTC), datetime(2026, 10, 27, 12, tzinfo=UTC)
_LIST = "listTradeGroupDefinitions"


def principal(role: str, *granted: UUID, read: bool = True) -> PrincipalSnapshot:
    held = frozenset({Permission.ACCOUNTS_READ} if read else ())
    user, grants = MANAGER_ID, tuple(AccountGrant(a, True, False, False) for a in granted)
    return PrincipalSnapshot(OWNER_ID if role == "owner" else user, frozenset({role}), held, grants)


def record(
    key: UUID, name: str, *members: UUID, off: UUID | None = None, paused: UUID | None = None,
    env: Environment = "demo",
) -> port.DefinitionRecord:  # fmt: skip
    """As the store reads it, by account id: `off`'s account row and `paused`'s switch are off."""
    held = tuple(port.MemberRow(m, m != paused, env, m != off) for m in members)
    return port.DefinitionRecord(port.DefinitionRow(key, name, env, None, None, _AT, _AT), held)


class Store:
    """`DefinitionReads` as Postgres scopes it: a grant reads one if it holds every member's, and
    no scope reads one with no member (the store skips it)."""

    def __init__(self, *records: port.DefinitionRecord) -> None:
        self.records, self.deleted = {r.definition.id: r for r in records}, set[UUID]()
        self.fails: Exception | None = None
        self.reads = 0

    def _seen(self, scope: AccountScope) -> list[port.DefinitionRecord]:
        self.reads += 1
        if self.fails is not None:
            raise self.fails
        live = [r for i, r in self.records.items() if i not in self.deleted and r.members]
        if isinstance(scope, OwnerScope):
            return live
        held = scope.account_ids
        return [r for r in live if {m.exchange_account_id for m in r.members} <= held]

    async def get(self, scope: AccountScope, key: UUID) -> port.DefinitionRecord | None:
        return next((r for r in self._seen(scope) if r.definition.id == key), None)

    async def page(
        self, scope: AccountScope, *, after: tuple[str, UUID] | None, limit: int
    ) -> tuple[port.DefinitionRecord, ...]:
        keys = sorted((r.definition.name.lower(), r.definition.id, r) for r in self._seen(scope))
        start = None if after is None else (after[0].lower(), after[1])
        return tuple([r for *k, r in keys if start is None or tuple(k) > start][:limit])


class World:
    """The router over `Store` (Core3, Pair), and its order-entry gate, audit sink and resolver."""

    def __init__(self, unwired: str = "") -> None:  # "store", "readiness" or "resolver"
        self.store = Store(record(CORE3, "Core3", A, B, C), record(PAIR, "Pair", A, C))
        self.refusing = {B: OrderEntryRefusal("no_active_key", "No verified active key.")}
        self.asked, self.records = list[UUID](), list[dict[str, Any]]()
        self.fails: Exception | None = None
        self.principal: PrincipalSnapshot | None = principal("owner")
        self.source = GateReadiness(
            self, kill_switch=lambda _account: None, live_enabled=False,
            live_flag=lambda: False, lockouts=NoLockouts(),
        )  # fmt: skip
        reads = None if unwired == "store" else self.store
        source = None if unwired == "readiness" else self.source
        app, resolver = FastAPI(), None if unwired == "resolver" else self
        app.include_router(router(reads, source, self, resolver, clock=lambda: NOW))
        self.client = TestClient(app, raise_server_exceptions=False)

    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        self.asked.append(account_id)
        return self.refusing.get(account_id)

    async def emit(self, action: str, **kwargs: Any) -> None:
        if self.fails is not None:
            raise self.fails
        self.records.append({"action": action, **kwargs})

    def resolve(self, _request: Any) -> PrincipalSnapshot | None:
        return self.principal

    def read(self, definition_id: UUID | None = None, **params: Any) -> Any:
        path = "" if definition_id is None else f"/{definition_id}"
        return self.client.get(f"/trade-group-definitions{path}", params=params)

    def ids(self, **params: Any) -> list[str]:
        return [item["id"] for item in self.read(**params).json()["items"]]


@pytest.fixture
def world() -> World:
    return World()


def _state(account: UUID, reason: str | None = None) -> dict[str, Any]:
    return {"exchange_account_id": str(account), "ready": reason is None, "reason": reason}


def test_core3_reads_with_three_members_and_two_of_three_ready(world: World) -> None:
    got, at = world.read(CORE3), "2026-10-27T09:00:00.000000Z"
    members = [{"exchange_account_id": str(a), "enabled": True} for a in (A, B, C)]
    ready = [_state(A), _state(B, "key_invalid"), _state(C)]
    assert (got.status_code, got.json()) == (200, {
        "id": str(CORE3), "created_at": at, "updated_at": at,
        "definition": {"name": "Core3", "environment": "demo", "members": members},
        "readiness": {"ready": 2, "total": 3, "members": ready},
    })  # fmt: skip
    meta = {"next_cursor": None, "has_more": False, "count": 2}
    assert world.read().json() == {"items": [got.json(), world.read(PAIR).json()], "meta": meta}


def test_a_definition_with_an_ungranted_member_is_absent_and_404s_alike(world: World) -> None:
    """SR-E28-21, PF-I02: and its readiness is never read."""
    world.principal = principal("manager", A, C)
    hidden, missing = world.read(CORE3), world.read(MISSING)
    assert world.ids() == [str(PAIR)] and (hidden.status_code, hidden.text) == (404, missing.text)
    assert "etag" not in hidden.headers and world.records == [] and B not in world.asked


def test_a_viewer_reads_definitions(world: World) -> None:
    """Without `accounts:read`, a 403 before any read, its `rbac.denied` naming the definition."""
    world.principal = principal("viewer", A, C)
    assert world.ids() == [str(PAIR)] and world.read(PAIR).status_code == 200
    world.principal, world.store.reads = principal("viewer", A, C, read=False), 0
    assert [world.read().status_code, world.read(PAIR).status_code] == [403, 403]
    named = [(r["action"], r.get("object_kind"), r.get("object_id")) for r in world.records]
    assert world.store.reads == 0 and named == [
        ("rbac.denied", None, None), ("rbac.denied", "trade_group_definition", str(PAIR)),
    ]  # fmt: skip


def test_a_deleted_definition_is_neither_listed_nor_read(world: World) -> None:
    world.store.deleted.add(CORE3)
    gone, missing = world.read(CORE3), world.read(MISSING)
    assert world.ids() == [str(PAIR)] and (gone.status_code, gone.text) == (404, missing.text)


def test_a_page_has_more_only_past_its_limit_and_its_limit_is_1_to_500(world: World) -> None:
    meta = {"next_cursor": None, "has_more": False, "count": 2}  # `limit` 2 over exactly two
    assert world.read(limit=2).json()["meta"] == meta
    assert [world.read(limit=n).status_code for n in (0, 501, 500)] == [422, 422, 200]


def test_a_paused_member_reads_disabled_and_a_live_one_meets_the_live_gate(world: World) -> None:
    """`member_disabled` is outside `total`; the live gate (off here) asks the environment."""
    world.store.records[LIVE] = record(LIVE, "Live", A, B, C, paused=B, env="live")
    got = world.read(LIVE).json()
    assert [m["enabled"] for m in got["definition"]["members"]] == [True, False, True]
    off = "trading_disabled"
    assert got["readiness"] == {"ready": 0, "total": 2, "members": [
        _state(A, off), _state(B, "member_disabled"), _state(C, off),
    ]}  # fmt: skip


def test_a_bad_or_foreign_cursor_is_400_invalid_cursor(world: World) -> None:
    """A cursor names the last one read, bound to operation, caller and filters for an hour."""
    issued, key = int(NOW.timestamp()), CORE3.bytes + b"Core3"
    first, cursor = world.read(limit=1).json(), encode_cursor(_LIST, OWNER_ID, (), key, issued)
    assert first["meta"] == {"next_cursor": cursor, "has_more": True, "count": 1}
    old = encode_cursor(_LIST, OWNER_ID, (), key, issued - CURSOR_TTL_S)  # an hour old: still good
    assert [world.ids(limit=1), world.ids(cursor=old)] == [[str(CORE3)], [str(PAIR)]]
    for sent in (
        "not a cursor", cursor + "A" * (513 - len(cursor)),  # past 22's `maxLength`
        encode_cursor("listTradeGroups", OWNER_ID, (), key, issued),  # another operation
        encode_cursor(_LIST, MANAGER_ID, (), key, issued),  # another caller
        encode_cursor(_LIST, OWNER_ID, ("BTCUSDT",), key, issued),  # other filters
        encode_cursor(_LIST, OWNER_ID, (), key, issued - CURSOR_TTL_S - 1),  # expired
        encode_cursor(_LIST, OWNER_ID, (), key, issued + 1),  # issued later than now
        encode_cursor(_LIST, OWNER_ID, (), CORE3.bytes, issued),  # an id and no name
        encode_cursor(_LIST, OWNER_ID, (), CORE3.bytes + b"\x00", issued),  # a NUL `text` refuses
        encode_cursor(_LIST, OWNER_ID, (), CORE3.bytes + b"\xff", issued),  # not UTF-8
    ):  # fmt: skip
        got = world.read(cursor=sent)
        assert (got.status_code, got.json()["code"]) == (400, "invalid_cursor"), sent


def test_the_etag_ignores_readiness(world: World) -> None:
    before = world.read(CORE3)
    world.refusing.clear()
    after, tag = world.read(CORE3), definition_etag(stored_definition(world.store.records[CORE3]))
    ready = [r.json()["readiness"]["ready"] for r in (before, after)]
    assert (ready, before.headers["etag"], after.headers["etag"]) == ([2, 3], tag, tag)


def test_a_member_whose_account_row_is_off_reads_account_disabled(world: World) -> None:
    world.store.records[PAIR] = record(PAIR, "Pair", A, C, off=C)
    got = world.read(PAIR).json()["readiness"]
    assert got == {"ready": 1, "total": 2, "members": [_state(A), _state(C, "account_disabled")]}


def test_faults_are_refused_or_503_logged_by_class_and_sqlstate_or_500(world: World) -> None:
    """The owner gate (SR-051) audited as `enforce` would, a record unwritten logged, still 403; a
    timeout or a row the model refuses (21 members, which the schema allows), 503 logged by class
    and SQLSTATE (C-12.6); a defect 500."""
    world.store.fails = port.DefinitionScopeDeniedError()
    assert world.read(PAIR).status_code == 403
    assert [(r["reason"], r["object_id"]) for r in world.records] == [
        ("not_owner:accounts:read:granted_accounts", str(PAIR))
    ]
    world.fails = RuntimeError("the audit writer is not started")
    with capture_logs() as logs:
        gated, world.principal = world.read(), principal("viewer", read=False)
        bare, world.principal = world.read(), principal("owner")
        world.store.fails = StorageQueryFailed("57014")
        timeout, world.store.fails = world.read(), None
        world.store.records[PAIR] = record(PAIR, "Pair", *(UUID(int=n) for n in range(100, 121)))
        unreadable, world.store.fails = world.read(PAIR), TypeError("a defect")
        defect = world.read()
    sent = [r.status_code for r in (gated, bare, timeout, unreadable, defect)]
    assert (sent, "defect" in defect.text) == ([403, 403, 503, 503, 500], False)
    events = [e for e in logs if "definition_" in e["event"]]
    assert [(e["error"], e.get("sqlstate")) for e in events] == [
        ("RuntimeError", None), ("RuntimeError", None), ("StorageQueryFailed", "57014"),
        ("AccountsError", None),
    ]  # fmt: skip
    denial = ["error", "event", "log_level", "principal_user_id"]  # a class, an id: no value
    unavailable = ["error", "event", "log_level", "sqlstate"]
    assert [sorted(e) for e in events] == [denial, denial, unavailable, unavailable]
