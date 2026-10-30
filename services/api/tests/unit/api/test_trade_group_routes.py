"""E28-T05 S2f (#909): `listTradeGroups` and `getTradeGroup` over `TradeGroupReader` and a store
faked as Postgres scopes it (SR-E28-21): an Owner reads every group, a grant a group with a leg
whose every leg account it holds. Five groups on the E28 seed's accounts A, B and C: Core3 (a leg
on each) is hidden from a grant of A and C, and Twin is made in Solo's instant, so only the id
orders them."""

from __future__ import annotations

import asyncio
from collections.abc import Collection, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.accounts.trade_group_repository import TradeGroupReader
from candleviewer.api import trade_groups
from candleviewer.api.trade_group_cursor import CURSOR_TTL_S, decode_cursor, encode_cursor
from candleviewer.api.trade_group_projection import group_document
from candleviewer.api.trade_groups import make_trade_groups_router as router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.accounts import AccountScope, OwnerScope
from candleviewer.storage.repositories.trade_groups import (
    TradeGroupRecord,
    TradeGroupStatus,
    TradeGroupStoreScopeDeniedError,
)
from tests.unit.accounts.test_trade_group_repository import _GROUP_ROW, _LEG_ROW

_E28 = "e28f0000-0000-4000-8000-{:0>12}"
OWNER_ID, A, B, C = (UUID(_E28.format(t)) for t in "1 d1 d2 d3".split())
MANAGER_ID, MISSING = UUID(int=7), UUID(int=404)
T0, NOW = datetime(2026, 10, 20, 8, tzinfo=UTC), datetime(2026, 10, 27, 12, tzinfo=UTC)
_LIST, NO_FILTERS, NOTE = "listTradeGroups", (None, None, None, None), "planted note"
PRIVATE = {"created_by", "note", "client_group_ref"}


def principal(
    role: str, *granted: UUID, held: tuple[Permission, ...] = (Permission.ORDERS_READ,)
) -> PrincipalSnapshot:
    grants = tuple(AccountGrant(a, True, False, False) for a in granted)
    return PrincipalSnapshot(
        OWNER_ID if role == "owner" else MANAGER_ID, frozenset({role}), frozenset(held), grants
    )


def group(
    n: int, symbol: str, status: TradeGroupStatus, hours: int, *accounts: UUID,
    by: UUID = OWNER_ID,
) -> TradeGroupRecord:  # fmt: skip
    """Group `n`, made by `by` at T0 plus `hours` and updated half an hour later (a cursor's place
    is its creation, never its update), with a leg on each account; its note and ref are its own,
    so a value shown for one group is never another's."""
    at, key = T0 + timedelta(hours=hours), UUID(int=0x5000 + n)
    row = replace(
        _GROUP_ROW, id=key, symbol=symbol, status=status, created_by=by, created_at=at,
        updated_at=at + timedelta(minutes=30), intent_note=f"{NOTE} {n}",
        client_group_ref=str(UUID(int=0x6000 + n)),
    )  # fmt: skip
    legs = tuple(
        replace(_LEG_ROW, id=UUID(int=0x7000 + 16 * n + i), trade_group_id=key,
                exchange_account_id=a, sequence_no=i)
        for i, a in enumerate(accounts)
    )  # fmt: skip
    return TradeGroupRecord(group=row, legs=legs)


OLD, SOLO = group(1, "BTCUSDT", "closed", 1, A), group(2, "ETHUSDT", "closed", 2, A)
TWIN, CORE3 = group(3, "ETHUSDT", "open", 2, C), group(4, "BTCUSDT", "partially_open", 3, A, B, C)
PAIR = group(5, "BTCUSDT", "open", 4, A, C, by=MANAGER_ID)
NEWEST_FIRST = (PAIR, CORE3, TWIN, SOLO, OLD)  # created_at, then id, descending


def ids_of(*groups: TradeGroupRecord) -> list[str]:
    return [str(g.group.id) for g in groups]


class Store:
    """`TradeGroupReads` as Postgres scopes it: a page is newest first and strictly past `after`;
    each call is counted, and each page's keywords and each order read's legs are kept."""

    def __init__(self, *records: TradeGroupRecord) -> None:
        self.records, self.reads = {r.group.id: r for r in records}, 0
        self.listed, self.asked = list[dict[str, Any]](), list[tuple[UUID, ...]]()
        self.orders = dict[UUID, tuple[UUID, ...]]()
        self.fails: Exception | None = None

    def _seen(self, scope: AccountScope) -> list[TradeGroupRecord]:
        self.reads += 1
        if self.fails is not None:
            raise self.fails
        found = self.records.values()
        newest = sorted(found, key=lambda r: (r.group.created_at, r.group.id), reverse=True)
        if isinstance(scope, OwnerScope):
            return newest
        held = scope.account_ids  # a group with no leg is no grant's
        return [r for r in newest if r.legs and {x.exchange_account_id for x in r.legs} <= held]

    async def get_group(self, scope: AccountScope, group_id: UUID) -> TradeGroupRecord | None:
        return next((r for r in self._seen(scope) if r.group.id == group_id), None)

    async def list_groups(
        self, scope: AccountScope, *, symbol: str | None, statuses: Collection[TradeGroupStatus],
        created_from: datetime | None, created_to: datetime | None,
        after: tuple[datetime, UUID] | None, limit: int,
    ) -> tuple[TradeGroupRecord, ...]:  # fmt: skip
        self.listed.append({"symbol": symbol, "statuses": set(statuses), "after": after,
                            "created_from": created_from, "created_to": created_to,
                            "limit": limit})  # fmt: skip
        kept = [
            r for r in self._seen(scope)
            if symbol in (None, r.group.symbol) and (not statuses or r.group.status in statuses)
            and (created_from is None or r.group.created_at >= created_from)
            and (created_to is None or r.group.created_at < created_to)
            and (after is None or (r.group.created_at, r.group.id) < after)
        ]  # fmt: skip
        return tuple(kept[:limit])

    async def leg_order_ids(
        self, scope: AccountScope, leg_ids: Collection[UUID]
    ) -> Mapping[UUID, tuple[UUID, ...]]:
        self.asked.append(tuple(leg_ids))
        visible = {leg.id for r in self._seen(scope) for leg in r.legs}
        return {i: self.orders[i] for i in leg_ids if i in visible and i in self.orders}


class World:
    """The router over `TradeGroupReader(Store)`, and its audit sink and resolver."""

    def __init__(self, unwired: str = "") -> None:  # "store" or "resolver"
        self.store, self.audit = Store(OLD, SOLO, TWIN, CORE3, PAIR), list[dict[str, Any]]()
        self.fails: Exception | None = None
        self.principal: PrincipalSnapshot | None = principal("owner")
        reader = None if unwired == "store" else TradeGroupReader(self.store)
        app, resolver = FastAPI(), None if unwired == "resolver" else self
        app.include_router(router(reader, self, resolver, clock=lambda: NOW))
        self.client = TestClient(app, raise_server_exceptions=False)

    async def emit(self, action: str, **kwargs: Any) -> None:
        if self.fails is not None:
            raise self.fails
        self.audit.append({"action": action, **kwargs})

    def resolve(self, _request: Any) -> PrincipalSnapshot | None:
        return self.principal

    def read(self, group_id: UUID | None = None, /, **params: Any) -> Any:
        path = "" if group_id is None else f"/{group_id}"
        return self.client.get(f"/trade-groups{path}", params=params)

    def ids(self, **params: Any) -> list[str]:
        return [item["id"] for item in self.read(**params).json()["items"]]


@pytest.fixture
def world() -> World:
    return World()


def _at(hours: int) -> str:
    return (T0 + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def test_list_filters_by_symbol_status_and_time_and_pages(world: World) -> None:
    """Newest first, the id breaking a tie; each filter narrows the page, `from` inclusive and `to`
    exclusive; `meta` has no `total`, which would count groups the caller cannot read (OL-02); a
    `limit` of 500 asks the store for 501, the look-ahead row `check_page` allows (RC-02)."""
    assert world.ids() == ids_of(*NEWEST_FIRST)
    assert world.ids(symbol="ETHUSDT") == ids_of(TWIN, SOLO)
    assert world.ids(status="open") == ids_of(PAIR, TWIN)
    assert world.ids(status=["open", "closed"]) == ids_of(PAIR, TWIN, SOLO, OLD)
    assert world.ids(**{"from": _at(2), "to": _at(4)}) == ids_of(CORE3, TWIN, SOLO)
    assert world.ids(symbol="BTCUSDT", status="open", **{"from": _at(0)}) == ids_of(PAIR)
    pages, cursor = list[dict[str, Any]](), None
    for _ in NEWEST_FIRST:  # a page a group at most: a cursor that repeats a group fails, not loops
        pages.append(world.read(limit=2, **({} if cursor is None else {"cursor": cursor})).json())
        if (cursor := pages[-1]["meta"]["next_cursor"]) is None:
            break
    assert [[i["id"] for i in p["items"]] for p in pages] == [
        ids_of(PAIR, CORE3), ids_of(TWIN, SOLO), ids_of(OLD),
    ]  # fmt: skip
    metas = [p["meta"] for p in pages]
    assert [(m["has_more"], m["count"]) for m in metas] == [(True, 2), (True, 2), (False, 1)]
    assert all(set(m) == {"next_cursor", "has_more", "count"} for m in metas)
    exact = world.read(limit=5).json()["meta"]  # a page that fits all five is the last
    assert exact == {"next_cursor": None, "has_more": False, "count": 5}
    world.store.listed.clear()
    world.read(limit=500)
    world.read()
    assert [c["limit"] for c in world.store.listed] == [501, 101]


def test_a_page_ends_at_its_last_served_group_and_reads_the_served_orders_once(
    world: World,
) -> None:
    """The look-ahead row (`limit + 1`) is never served, has no orders read and sets no cursor: the
    next page begins with it, though it shares its instant with the last group served."""
    served = (PAIR, CORE3, TWIN)  # Solo, Twin's tie, is the look-ahead row
    world.store.orders = {leg.id: (UUID(int=0x8000 + i),) for i, leg in enumerate(
        leg for g in NEWEST_FIRST for leg in g.legs)}  # fmt: skip
    first = world.read(limit=3).json()
    legs = [leg for g in served for leg in g.legs]
    assert [i["id"] for i in first["items"]] == ids_of(*served) and first["meta"]["has_more"]
    assert [sorted(asked) for asked in world.store.asked] == [sorted(leg.id for leg in legs)]
    shown = [o for item in first["items"] for leg in item["legs"] for o in leg["orders"]]
    assert sorted(shown) == sorted(str(world.store.orders[leg.id][0]) for leg in legs)
    second = world.read(limit=3, cursor=first["meta"]["next_cursor"]).json()
    assert [i["id"] for i in second["items"]] == ids_of(SOLO, OLD)
    assert world.store.listed[1]["after"] == (TWIN.group.created_at, TWIN.group.id)
    one = world.read(PAIR.group.id).json()  # a get reads the orders of its own legs, once
    assert [leg["orders"] for leg in one["legs"]] == [
        [str(world.store.orders[x.id][0])] for x in PAIR.legs
    ]
    assert world.store.asked[2:] == [tuple(x.id for x in PAIR.legs)]


def _off_the_loop() -> bool:
    """True on a thread that runs no event loop: a worker's, never the serving loop's."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return True
    return False


def test_a_page_and_a_group_are_rendered_and_encoded_off_the_serving_loop(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1C-01 (AGENTS.md 5.2): a page of 500 groups with 20 legs takes about half a second to
    render and encode, so the list and the get do both on a worker thread, and answer the bytes
    the framework's own `JSONResponse` gives."""
    ran = list[tuple[str, bool]]()

    def rendered(*args: Any) -> Any:
        ran.append(("document", _off_the_loop()))
        return group_document(*args)

    class Encoded(JSONResponse):
        def render(self, content: Any) -> bytes:
            ran.append(("encode", _off_the_loop()))
            return super().render(content)

    monkeypatch.setattr(trade_groups, "group_document", rendered)
    monkeypatch.setattr(trade_groups, "JSONResponse", Encoded)
    for answer in (world.read(), world.read(PAIR.group.id)):
        inline = JSONResponse(answer.json())
        assert (answer.content, dict(answer.headers)) == (inline.body, dict(inline.headers))
    assert sorted(set(ran)) == [("document", True), ("encode", True)]  # both, never on the loop


@pytest.mark.parametrize(
    ("granted", "seen"),
    [((A, C), (PAIR, TWIN, SOLO, OLD)), ((A, B), (SOLO, OLD)), ((), ())],
    ids=["a-leg-on-ungranted-b", "legs-on-ungranted-c", "no-grant"],
)  # fmt: skip
def test_a_group_with_an_ungranted_leg_is_404_as_a_missing_one(
    world: World, granted: tuple[UUID, ...], seen: tuple[TradeGroupRecord, ...]
) -> None:
    """SR-E28-21, PF-I02, the route half of `test_group_with_ungranted_leg_is_invisible`: a leg
    outside the grants hides the whole group from the list and the get, in the one answer a missing
    group gets, byte for byte, naming no group, readiness or figure; no record, and no order of it
    is read."""
    world.principal = principal("manager", *granted)
    missing = world.read(MISSING)
    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")
    assert world.ids() == ids_of(*seen) and str(MISSING) not in missing.text
    for g in NEWEST_FIRST:
        world.store.asked.clear()
        got = world.read(g.group.id)
        if g in seen:
            assert got.status_code == 200
            continue
        same = (404, missing.headers, missing.content)
        assert (got.status_code, got.headers, got.content) == same
        assert world.store.asked == [] and str(g.group.id) not in got.text
    assert world.audit == []


def test_a_non_owner_never_sees_created_by_note_or_client_group_ref(world: World) -> None:
    """SR-E28-21, PF-I02: S2e's flag, per group, in the list and the get alike: an Owner and a
    group's creator see the three, anyone else none of them, nor any value of theirs."""
    owner = world.read(CORE3.group.id).json()
    assert PRIVATE <= set(owner) and owner["note"] == CORE3.group.intent_note
    world.principal = principal("manager", A, C)  # Pair is this manager's; the rest, the Owner's
    listed = world.read()
    items = {i["id"]: i for i in listed.json()["items"]}
    assert {k for k, item in items.items() if PRIVATE <= set(item)} == {str(PAIR.group.id)}
    assert all(not PRIVATE & set(i) for k, i in items.items() if k != str(PAIR.group.id))
    assert world.read(PAIR.group.id).json()["note"] == PAIR.group.intent_note
    for other in (OLD, SOLO, TWIN):
        got = world.read(other.group.id)
        row = other.group
        values = (row.intent_note, row.client_group_ref, str(row.created_by))
        text = got.text + listed.text
        assert not PRIVATE & set(got.json()) and not any(v in text for v in values)


def test_a_viewer_reads_groups(world: World) -> None:
    """`orders:read` alone (22), a viewer included; without it, and `accounts:read` is no stand-in,
    a 403 before any read, whose `rbac.denied` names the group on a get (C-2.9)."""
    world.principal = principal("viewer", A, C)
    got = world.read(PAIR.group.id)
    assert world.ids() == ids_of(PAIR, TWIN, SOLO, OLD) and got.status_code == 200
    world.store.reads = 0
    for held in ((), (Permission.ACCOUNTS_READ,)):
        world.principal = principal("viewer", A, C, held=held)
        listing, one = world.read(), world.read(PAIR.group.id)
        assert [listing.status_code, one.status_code] == [403, 403]
        assert listing.json()["required_permissions"] == ["orders:read"]
    named = [(r["action"], r.get("object_kind"), r.get("object_id")) for r in world.audit]
    assert world.store.reads == 0 and named == [
        ("rbac.denied", None, None), ("rbac.denied", "trade_group", str(PAIR.group.id)),
    ] * 2  # fmt: skip


def test_a_bad_cursor_and_an_inverted_range_are_400(world: World) -> None:
    """A cursor holds the last served group's place, bound to operation, caller and each filter as
    given for an hour; a naive time or `from` after `to` is `invalid_time_range`; no read is made
    for any."""
    cursor, now = world.read(limit=1).json()["meta"]["next_cursor"], int(NOW.timestamp())
    place = decode_cursor(cursor, _LIST, OWNER_ID, NO_FILTERS, now)
    assert place is not None
    old = encode_cursor(_LIST, OWNER_ID, NO_FILTERS, place, now - CURSOR_TTL_S)  # still good
    assert world.ids(limit=1, cursor=old) == ids_of(CORE3)
    eth = world.read(symbol="ETHUSDT", limit=1).json()["meta"]["next_cursor"]
    assert world.ids(symbol="ETHUSDT", limit=1, cursor=eth) == ids_of(SOLO)
    for sent in (
        "not a cursor", cursor + "A" * (513 - len(cursor)),  # past 22's `maxLength`
        encode_cursor("listTradeGroupDefinitions", OWNER_ID, NO_FILTERS, place, now),
        encode_cursor(_LIST, MANAGER_ID, NO_FILTERS, place, now),  # another caller
        encode_cursor(_LIST, OWNER_ID, ("BTCUSDT", None, None, None), place, now),
        encode_cursor(_LIST, OWNER_ID, NO_FILTERS, place, now - CURSOR_TTL_S - 1),  # expired
        encode_cursor(_LIST, OWNER_ID, NO_FILTERS, place, now + 1),  # issued later than now
        encode_cursor(_LIST, OWNER_ID, NO_FILTERS, place[:-1], now),  # a short place
        encode_cursor(_LIST, OWNER_ID, NO_FILTERS, place + b"\x00", now),  # a long place
        encode_cursor(_LIST, OWNER_ID, NO_FILTERS, (2**62).to_bytes(8, "big") + bytes(16), now),
    ):  # fmt: skip
        got = world.read(cursor=sent)
        assert (got.status_code, got.json()["code"]) == (400, "invalid_cursor"), sent
    assert world.read(limit=1, cursor=eth).status_code == 400  # issued under another filter
    for issued, replayed in (  # `status`, `from` and `to` each bind a cursor, as the symbol does
        ({"status": "open"}, {"status": "closed"}),
        ({"from": _at(2)}, {"from": _at(3)}), ({"to": _at(4)}, {"to": _at(5)}),
    ):  # fmt: skip
        page = world.read(limit=1, **issued).json()["meta"]["next_cursor"]
        assert world.read(limit=1, cursor=page, **issued).status_code == 200  # as it was issued
        again = world.read(limit=1, cursor=page, **replayed)
        assert (again.status_code, again.json()["code"]) == (400, "invalid_cursor"), replayed
    world.principal = principal("manager", A, C)
    theirs = world.read(limit=1).json()["meta"]["next_cursor"]  # issued to the manager
    world.principal = principal("owner")
    assert world.read(cursor=theirs).status_code == 400
    world.store.reads = 0
    for params in (
        {"from": _at(5), "to": _at(4)}, {"from": "2026-10-20T08:00:00"},
        {"to": "2026-10-20T08:00:00"}, {"from": "2026-10-20"},
        {"from": "0001-01-01T00:00:00+14:00"}, {"to": "9999-12-31T23:59:59-14:00"},  # no UTC date
    ):  # fmt: skip
        got = world.read(**params)
        assert (got.status_code, got.json()["code"]) == (400, "invalid_time_range"), params
    assert world.store.reads == 0
    assert world.read(**{"from": _at(2), "to": _at(2)}).json()["items"] == []  # empty, not inverted


@pytest.mark.parametrize(
    "params",
    [
        {"status": "bogus"}, {"status": ["open", "bogus"]}, {"symbol": "btcusdt"},
        {"symbol": "USDT"}, {"limit": 0}, {"limit": 501}, {"from": "yesterday"}, {"to": "soon"},
    ],
)  # fmt: skip
def test_a_bad_status_symbol_limit_time_or_id_is_the_shared_422_before_any_read(
    world: World, params: dict[str, Any]
) -> None:
    assert world.read(**params).status_code == 422
    assert world.client.get("/trade-groups/not-a-uuid").status_code == 422
    assert world.store.reads == 0


def test_faults_are_refused_or_503_logged_by_class_and_sqlstate_or_500(world: World) -> None:
    """The owner gate (SR-051), audited as `enforce` would, naming the group on a get, a record
    unwritten logged and the 403 standing; a timeout or a row the models refuse, 503 logged by
    class and SQLSTATE (C-12.6); a defect, 500, echoing nothing."""
    world.store.fails = TradeGroupStoreScopeDeniedError()
    assert [world.read(PAIR.group.id).status_code, world.read().status_code] == [403, 403]
    denied = {  # the whole record: its outcome, its severity and its actor included
        "action": "rbac.denied", "actor_label": str(OWNER_ID), "actor_user_id": OWNER_ID,
        "actor_ip": "testclient", "outcome": "denied", "severity": "warning", "request_id": None,
        "session_id": None, "reason": "not_owner:orders:read:granted_accounts",
    }  # fmt: skip
    named = {"object_kind": "trade_group", "object_id": str(PAIR.group.id)}
    assert world.audit == [denied | named, denied]
    world.fails = RuntimeError("the audit writer is not started")
    refused = replace(PAIR.legs[0], filled_qty=Decimal(9))  # above its target: no model holds it
    with capture_logs() as logs:
        gated, world.principal = world.read(), principal("viewer", held=())
        bare, world.principal = world.read(), principal("owner")
        world.store.fails = StorageQueryFailed("57014")
        timeout, world.store.fails = world.read(PAIR.group.id), None
        world.store.records[PAIR.group.id] = replace(PAIR, legs=(refused,))
        unreadable, world.store.fails = world.read(PAIR.group.id), RuntimeError("a defect")
        defect = world.read()
    sent = [r.status_code for r in (gated, bare, timeout, unreadable, defect)]
    assert (sent, "defect" in defect.text) == ([403, 403, 503, 503, 500], False)
    events = [e for e in logs if e["event"].startswith("trade_group_")]
    assert [(e["error"], e.get("sqlstate")) for e in events] == [
        ("RuntimeError", None), ("RuntimeError", None), ("StorageQueryFailed", "57014"),
        ("AccountsError", None),
    ]  # fmt: skip
    denial = ["error", "event", "log_level", "principal_user_id"]  # a class, an id: no value
    unavailable = ["error", "event", "log_level", "sqlstate"]
    assert [sorted(e) for e in events] == [denial, denial, unavailable, unavailable]
