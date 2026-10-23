"""`GET /admin/audit/signing-keys` (`listAuditSigningKeys`, #889 S7; ADR-0039 decision 4): the
Owner's list of the environment's keys, newest first, public material only, each `verified` mark
M2's, through `admin.wiring`'s directory over M2 booted with a rotated key. Then the forbidden
roles, another Owner, the budget (its record, its `429`, its `503`) and the store's `503`. No
database, no network."""

from __future__ import annotations

import base64
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from candleviewer.admin.wiring import secrets_bundle
from candleviewer.api.audit import make_audit_router
from candleviewer.api.audit_budget import AuditRecordBudget, filters_digest
from candleviewer.audit.access import AuditPrincipal
from tests.unit.credentials_m2.test_export_key_rotation import _Rig, _rig

_READ = frozenset({"audit:read"})
_WHO = {
    "owner": AuditPrincipal(uuid.UUID(int=1), "owner", _READ, is_owner=True),
    "owner2": AuditPrincipal(uuid.UUID(int=2), "owner2", _READ, is_owner=True),
    "manager": AuditPrincipal(uuid.UUID(int=3), "manager", _READ),  # holds `audit:read`
    "viewer": AuditPrincipal(uuid.UUID(int=4), "viewer", frozenset()),
    # #3085's fields by hand: the first Owner acting while viewing as an Owner, which the session
    # resolver never makes (a view-as target is never an Owner); it alone tells the budget's keys
    "acting": AuditPrincipal(
        uuid.UUID(int=5), "target", _READ, is_owner=True, actor_user_id=uuid.UUID(int=1)
    ),
}
_KEY = {"key_id", "alg", "public_key", "fingerprint_sha256", "status", "verified", "valid_from"}
_KEY |= {"valid_until", "retired_reason"}  # 22's `AuditSigningKey`, all of it and nothing else


class _World:
    """The audit router over M2's directory; it is also the session resolver and the writer."""

    is_active = True

    def __init__(self, rig: _Rig | None, budget: AuditRecordBudget | None = None) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []
        self.fail, self.writer, self.app = "", self, FastAPI()
        keys = None if rig is None else secrets_bundle(rig.svc).signing_keys
        self.app.include_router(make_audit_router(self, self, budget=budget, signing_keys=keys))

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        return _WHO.get(request.headers.get("x-who", ""))

    async def emit(self, action: str, **fields: Any) -> None:
        if action == self.fail:
            raise OSError("audit WAL unavailable")
        self.records.append((action, fields))

    async def get(self, who: str = "owner") -> httpx.Response:
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            return await client.get("/admin/audit/signing-keys", headers={"x-who": who})


async def _rotated() -> _Rig:
    rig = await _rig()
    await rig.rotate()
    return rig


async def test_the_owner_gets_the_keys_newest_first_with_m2s_marks_and_its_read_record() -> None:
    rig = await _rotated()
    world, (v1, v2) = _World(rig), rig.keys.rows
    r = await world.get()
    assert (r.status_code, r.headers["cache-control"]) == (200, "no-store")
    items = r.json()["items"]
    assert [set(item) for item in items] == [_KEY, _KEY]
    shown = [(i["key_id"], i["status"], i["verified"], i["retired_reason"]) for i in items]
    assert shown == [
        (v2["key_id"], "active", True, None),
        (v1["key_id"], "retired", False, "scheduled"),
    ]
    assert base64.b64decode(items[0]["public_key"]) == v2["public_key"]
    assert items[1]["valid_until"] == items[0]["valid_from"] and items[0]["alg"] == "ed25519"
    hidden = [v1["dek_ref"], v2["dek_ref"], v2["sealed_seed"].hex(), v2["client_body_sha256"]]
    assert not [h for h in hidden if h in r.text]  # no wrap, seal or request fingerprint
    [(action, fields)] = world.records
    digest = filters_digest({"view": "signing_keys"})
    assert (action, fields["object_kind"], fields["actor_user_id"]) == (
        "admin.audit_read", "audit_signing_key", _WHO["owner"].user_id
    )  # fmt: skip
    after = fields["after_state"]
    assert (after["filters"], after["returned_count"], after["filters_sha256"]) == (
        {"view": "signing_keys"}, 2, digest
    )  # fmt: skip


@pytest.mark.parametrize(
    ("who", "status", "code", "reason"),
    [
        ("manager", 403, "forbidden", "owner_only"),  # a Manager with `audit:read` (S2's ruling)
        ("viewer", 403, "forbidden", "missing_permission:audit:read"),
        ("", 401, "unauthenticated", None),
    ],
)
async def test_anyone_but_an_owner_is_refused_and_a_denial_recorded(
    who: str, status: int, code: str, reason: str | None
) -> None:
    world = _World(await _rotated())
    r = await world.get(who)
    assert (r.status_code, r.json()["code"], "items" in r.json()) == (status, code, False)
    denied = [(a, f["reason"], f["object_kind"]) for a, f in world.records]
    assert denied == ([] if reason is None else [("admin.audit_denied", reason, "audit_log")])


async def test_another_owner_sees_the_same_environment_keys_recorded_as_their_own_read() -> None:
    """Cross-user (C-12.4): the list holds no per-user data, so every Owner reads the same keys,
    each read recorded with its own reader."""
    world = _World(await _rotated())
    first, second = await world.get(), await world.get("owner2")
    assert first.json() == second.json()
    assert [f["actor_user_id"] for _, f in world.records] == [uuid.UUID(int=1), uuid.UUID(int=2)]


async def test_a_read_over_the_budget_is_429_with_retry_after_and_no_keys() -> None:
    world = _World(await _rotated(), AuditRecordBudget(owner_per_hour=1, flush_pages=1))
    assert (await world.get()).status_code == 200  # the hour's one record
    r = await world.get()  # due again (`flush_pages`), over the cap: counted, never served
    assert (r.status_code, r.json()["code"], "items" in r.json()) == (429, "rate_limited", False)
    assert int(r.headers["retry-after"]) >= 1 and len(world.records) == 1


async def test_the_429s_retry_after_is_the_actors_whose_budget_is_spent() -> None:
    """Code C3-3 (#3085): the budget is the actor's, so the wait is read from the actor's entry,
    as the sibling routes read it: the hour of the record just written, never a second."""
    now = [1000.0]
    budget = AuditRecordBudget(owner_per_hour=1, flush_pages=1, clock=lambda: now[0])
    world = _World(await _rotated(), budget)
    assert (await world.get("acting")).status_code == 200  # the actor's one record of the hour
    now[0] += 600
    r = await world.get("acting")
    assert (r.status_code, r.headers["retry-after"]) == (429, "3000")


async def test_a_counted_read_is_carried_by_the_next_record_as_a_page() -> None:
    """Code C3-2: a read within the filter set's flush is counted, not recorded, and served; the
    next due record carries it. With `flush_pages=2`: a record, a counted read, then a record of
    the set's two pages."""
    world = _World(await _rotated(), AuditRecordBudget(flush_pages=2))
    served = [(await world.get()).status_code for _ in range(3)]
    digest = filters_digest({"view": "signing_keys"})
    pages = [[(p["filters_sha256"], p["pages"]) for p in f["after_state"]["pages"]]
             for _, f in world.records]  # fmt: skip
    assert (served, pages) == ([200] * 3, [[(digest, 1)], [(digest, 2)]])


@pytest.mark.parametrize("cause", ["record", "store", "unwired"])
async def test_an_unwritten_record_or_an_unreadable_store_is_503_and_nothing_returned(
    cause: str,
) -> None:
    rig = await _rotated()
    world = _World(None if cause == "unwired" else rig)
    world.fail = "admin.audit_read" if cause == "record" else ""

    async def down(*_: object) -> Any:
        raise RuntimeError("store down")

    if cause == "store":
        setattr(rig.keys, "list_keys", down)  # noqa: B010
    r = await world.get()
    assert (r.status_code, r.json()["code"], "items" in r.json()) == (
        503,
        "store_unavailable",
        False,
    )
