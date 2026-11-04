"""#5478: `GET /users` (22 `listUsers`) over `user_list_world`: an in-memory store that keeps the
SQL store's order, keyset and filters, a recording audit writer, the caller's session and a fake
clock. The store: `tests/unit/storage/test_user_list_store.py`; Postgres:
`tests/integration/admin/test_user_list_pg.py`; the deployed app and the matrix cells:
`tests/unit/architecture/test_owner_routes_composition.py`, `tests/contract/rbac`,
`tests/security/admin`.

No object id can be swapped here (scope `none`): a Manager or a Viewer is refused whatever it asks,
and a cursor serves only the caller and the filters it was issued for.
"""

from __future__ import annotations

import base64
import struct
import uuid
from datetime import datetime, timedelta
from typing import Any, cast

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api.trade_group_cursor import CURSOR_TTL_S, encode_cursor
from candleviewer.api.user_list_params import OPERATION
from candleviewer.api.users import make_user_admin_router
from candleviewer.audit.writer import AuditUnavailable
from tests.unit.admin.test_view_as_service import _at
from tests.unit.api.test_view_as_gate import _code, _Gate
from tests.unit.api.user_list_world import (
    CALLER,
    SESSION,
    SPEC,
    T0,
    Records,
    Row,
    UserRows,
    World,
    principal,
    rows,
    viewing_as,
)

_PROBLEM = {"$ref": "#/components/schemas/Problem", "components": SPEC["components"]}
_NO_FILTER = (None, None, None)


def _valid(name: str, value: Any) -> bool:
    schema = {"$ref": f"#/components/schemas/{name}", "components": SPEC["components"]}
    return jsonschema.Draft202012Validator(schema).is_valid(value)


def _refused(r: Any, status: int, code: str) -> None:
    """A refusal 22 declares for `listUsers`: its status, its code, 22's `Problem`."""
    assert (r.status_code, r.json().get("code")) == (status, code), r.text
    assert str(status) in SPEC["paths"]["/users"]["get"]["responses"]
    assert jsonschema.Draft202012Validator(_PROBLEM).is_valid(r.json()), r.text
    assert r.headers["content-type"].startswith("application/problem+json")


def _ids(body: dict[str, Any]) -> list[str]:
    return [item["id"] for item in body["items"]]


def _in_order(found: list[Row]) -> list[str]:
    return [str(row.id) for row in sorted(found, key=lambda row: (row.created_at, row.id))]


def _cursor(world: World, **params: Any) -> str:
    cursor: str = world.get(limit=1, **params).json()["meta"]["next_cursor"]
    return cursor


def _walk(world: World, **params: Any) -> list[list[str]]:
    """Every page, following `meta.next_cursor` to the end; a cursor that never ends fails."""
    pages, cursor = list[list[str]](), None
    for _ in range(len(world.store.rows) + 1):
        body = world.get(**params, **({} if cursor is None else {"cursor": cursor})).json()
        pages.append(_ids(body))
        if (cursor := body["meta"]["next_cursor"]) is None:
            return pages
    raise AssertionError(f"no last page after {len(pages)} pages")


def _counted() -> float:
    labels = {"permission": "users:read"}
    return float(REGISTRY.get_sample_value("authz_denied_total", labels) or 0.0)


def _errors(r: Any) -> list[tuple[str, str]]:
    return [(e["field"], e["rule"]) for e in r.json()["errors"]]


def test_scenario_owner_lists_users_first_page_in_22s_shape_with_an_opaque_next_cursor() -> None:
    """AC1: an Owner's `GET /users?limit=50` over 51 users: the first 50 in 22's shape, and a
    `next_cursor` that holds no username, e-mail or display name."""
    made = rows(51)
    r = World(UserRows(made)).get(limit=50)
    assert r.status_code == 200
    body, meta = r.json(), r.json()["meta"]
    assert _ids(body) == _in_order(made)[:50] and all(_valid("User", u) for u in body["items"])
    assert _valid("PageMeta", meta) and (meta["has_more"], meta["count"]) == (True, 50)
    assert "total" not in meta
    cursor = meta["next_cursor"]
    raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
    for row in made:
        for text in (row.username, row.email, str(row.display_name)):
            assert text not in cursor and text.encode() not in raw


@pytest.mark.parametrize(
    ("role", "grant"), [("manager", True), ("manager", False), ("viewer", False)]
)
def test_scenario_manager_or_viewer_is_refused_403_and_nothing_listed(
    role: str, grant: bool
) -> None:
    """AC2 (C-12.4, BQ-5): one 403, nothing read, one `rbac.denied` naming the caller and the
    caller's session, counted in `authz_denied_total` (SR-125)."""
    world, before = World(UserRows(rows(3)), principal(role, grant=grant)), _counted()
    r = world.get()
    _refused(r, 403, "forbidden")
    assert world.store.reads == [] and "items" not in r.json()
    (record,) = world.records.calls
    assert (record["action"], record["reason"]) == (
        "rbac.denied",
        "missing_permission:users:read:none",
    )
    assert (record["actor_user_id"], record["session_id"]) == (CALLER, SESSION)
    assert _counted() == before + 1


def test_scenario_unauthenticated_caller_gets_401_unauthenticated() -> None:
    world = World(UserRows(rows(3)), None)
    _refused(world.get(), 401, "unauthenticated")
    assert world.store.reads == [] and world.records.calls == []


def test_scenario_view_as_live_read_answers_403_forbidden_recorded_for_the_viewer() -> None:
    """AC4, BQ-4: in a live context the principal is the target's (a Manager), so the read is
    refused as the target's would be, and its record names the viewer and the viewer's session."""
    target = uuid.UUID(int=0x7A)
    world = World(UserRows(rows(3)), principal("manager", target, grant=True))
    world.viewing = viewing_as(target)
    _refused(world.get(), 403, "forbidden")
    (record,) = world.denied()
    assert (record["actor_user_id"], record["session_id"]) == (CALLER, SESSION)
    assert world.store.reads == []


async def test_scenario_view_as_held_context_answers_403_view_as_expired() -> None:
    """AC4, BQ-4: a held context refuses the read before any route, one `admin.view_as_refused`
    naming the operation (the view-as guard's harness)."""
    gate = _Gate()
    record = await gate.rig.viewing()
    gate.rig.clock.now = _at(31)  # past `expires_at`: held
    response = await gate.call("GET", "/users", record)
    assert _code(response) == (403, "view_as_expired") and gate.seen == []
    refusals = [(r["reason"], r["after_state"]) for r in gate.refused()]
    assert refusals == [("view_as_expired", {"method": "GET", "path": "/users"})]


def test_list_users_pages_partition_the_users_in_created_then_id_order() -> None:
    made = rows(7, tie=3)  # three users share each `created_at`
    pages = _walk(World(UserRows(made)), limit=2)
    assert [len(page) for page in pages] == [2, 2, 2, 1]
    assert [uid for page in pages for uid in page] == _in_order(made)


def test_list_users_last_page_has_no_cursor_and_has_more_false() -> None:
    world = World(UserRows(rows(4)))
    assert world.get(limit=4).json()["meta"] == {"next_cursor": None, "has_more": False, "count": 4}
    assert world.store.reads[-1].limit == 5  # one row past the page


def test_list_users_default_limit_is_100() -> None:
    world = World(UserRows(rows(101)))
    assert world.get().json()["meta"]["count"] == 100 and world.store.reads[0].limit == 101


def test_list_users_no_match_is_200_with_no_items() -> None:
    r = World(UserRows(rows(3))).get(q="nobody")
    empty = {"items": [], "meta": {"next_cursor": None, "has_more": False, "count": 0}}
    assert r.status_code == 200 and r.json() == empty


def test_list_users_status_role_and_q_narrow_the_list() -> None:
    """`status`; `role` among the grants that have not expired, either of two; `q` on the
    username or the e-mail, either case, `%` and `_` taken literally."""
    a = Row(
        uuid.UUID(int=1), "ann_lee", "ann@example.invalid", roles={"manager": None, "viewer": None}
    )
    expired: dict[str, datetime | None] = {"manager": T0 - timedelta(hours=1)}
    b = Row(uuid.UUID(int=2), "annXlee", "b@example.invalid", status="disabled", roles=expired)
    c = Row(uuid.UUID(int=3), "carl", "C.100%@Example.invalid", status="locked")
    world = World(UserRows([a, b, c]))
    ab, abc = [str(a.id)], [str(a.id), str(b.id), str(c.id)]
    assert _ids(world.get(status="disabled").json()) == [str(b.id)]
    assert _ids(world.get(role="manager").json()) == ab  # b's grant has expired
    assert _ids(world.get(role="viewer").json()) == [str(a.id), str(c.id)]
    assert _ids(world.get(q="N_L").json()) == ab  # `_` is no wildcard: not annXlee
    assert _ids(world.get(q="EXAMPLE.INVALID").json()) == abc
    assert [_ids(world.get(q=q).json()) for q in ("100%", "%", "0%@")] == [[str(c.id)]] * 3
    assert _ids(world.get(status="active", role="viewer", q="ANN").json()) == ab


@pytest.mark.parametrize(
    "query",
    [{"cursor": "garbage"}, {"limit": "0"}, {"status": "nope"}, [("q", "a"), ("q", "b")]],
)
def test_list_users_forbidden_caller_with_a_malformed_query_gets_403_not_400(query: Any) -> None:
    world = World(UserRows(rows(3)), principal("viewer"))
    _refused(world.client().get("/users", params=query), 403, "forbidden")
    assert len(world.denied()) == 1 and world.store.reads == []


@pytest.mark.parametrize(
    "error",
    [AuditUnavailable("WAL unwritable"), RuntimeError("audit service not started")],
    ids=["unwritable", "not_started"],
)
def test_list_users_unwritable_refusal_answers_503_audit_unavailable_and_reads_nothing(
    error: Exception,
) -> None:
    """BQ-5, C-2.9: a refusal whose record cannot be written, by the writer or because the audit
    service has not started (`RuntimeError`), is `503 audit_unavailable`, and nothing is read."""
    world = World(UserRows(rows(3)), principal("manager"), Records(fail=error))
    r = world.get()
    _refused(r, 503, "audit_unavailable")
    assert r.headers["retry-after"] == "5" and world.store.reads == []


def test_list_users_cursor_of_another_owner_is_400_invalid_cursor() -> None:
    made = rows(3)
    mine = _cursor(World(UserRows(made)))
    other = World(UserRows(made), principal("owner", uuid.UUID(int=0xB0B)))
    _refused(other.get(cursor=mine), 400, "invalid_cursor")
    assert other.store.reads == []
    assert _ids(World(UserRows(made)).get(cursor=mine).json()) == _in_order(made)[1:]


def test_list_users_cursor_for_other_filters_is_400_invalid_cursor() -> None:
    world = World(UserRows(rows(5)))
    cursor = _cursor(world, status="active", q="user")
    for other in ({}, {"status": "active"}, {"status": "active", "q": "USER"},
                  {"status": "active", "q": "user", "role": "viewer"}):  # fmt: skip
        _refused(world.get(cursor=cursor, **other), 400, "invalid_cursor")
    assert world.get(cursor=cursor, status="active", q="user", limit=9).status_code == 200


def test_list_users_cursor_at_3600_s_passes_and_at_3601_s_is_400() -> None:
    world = World(UserRows(rows(3)))
    cursor = _cursor(world)
    world.clock.now = T0 + timedelta(seconds=CURSOR_TTL_S)
    assert world.get(cursor=cursor).status_code == 200
    world.clock.now = T0 + timedelta(seconds=CURSOR_TTL_S + 1)
    _refused(world.get(cursor=cursor), 400, "invalid_cursor")


def test_list_users_malformed_cursor_is_400_invalid_cursor() -> None:
    world = World(UserRows(rows(3)))
    good, issued = _cursor(world), int(T0.timestamp())
    forged = (2**63 - 1).to_bytes(8, "big") + bytes(16)  # a time no `datetime` holds
    valid = struct.pack(">q16s", int(T0.timestamp()) * 1_000_000, CALLER.bytes)  # a real position
    for sent in (
        "not a cursor", "", good[:-6], good + "A" * (513 - len(good)),
        encode_cursor(OPERATION, CALLER, _NO_FILTER, forged, issued),
        encode_cursor(OPERATION, CALLER, _NO_FILTER, b"short", issued),
        encode_cursor("listTradeGroups", CALLER, _NO_FILTER, valid, issued),  # another list's
    ):  # fmt: skip
        _refused(world.get(cursor=sent), 400, "invalid_cursor")
    own = encode_cursor(OPERATION, CALLER, _NO_FILTER, valid, issued)  # the same, for this list
    assert world.get(cursor=own).status_code == 200
    assert len(world.store.reads) == 2  # the read that issued `good`, and `own`'s


@pytest.mark.parametrize(
    "limit",
    [
        "0",
        "501",
        "-1",
        "ten",
        "1.5",
        "",
        "99999",
        "00500",
        pytest.param("9" * 5000, id="5000-digits"),
    ],
)
def test_list_users_limit_outside_1_to_500_is_400_validation_failed(limit: str) -> None:
    """At most four digits: `00500` is refused though its value is in range, and 5,000 digits are
    refused before `int()`, which would reject them past its own digit limit."""
    world = World(UserRows(rows(3)))
    r = world.get(limit=limit)
    _refused(r, 400, "validation_failed")
    assert _errors(r) == [("limit", "range")] and world.store.reads == []
    assert [world.get(limit=n).status_code for n in ("1", "500")] == [200, 200]


@pytest.mark.parametrize(
    ("params", "rule"),
    [
        ({"status": "deleted"}, ("status", "enum")),
        ({"role": "admin"}, ("role", "enum")),
        ({"q": "x" * 121}, ("q", "max_length")),
        ({"q": "a\x00b"}, ("q", "nul")),
    ],
)
def test_list_users_bad_status_role_or_q_is_400_validation_failed(
    params: dict[str, str], rule: tuple[str, str]
) -> None:
    world = World(UserRows(rows(3)))
    r = world.get(**params)
    _refused(r, 400, "validation_failed")
    assert _errors(r) == [rule] and world.get(q="x" * 120).status_code == 200


@pytest.mark.parametrize("name", ["limit", "cursor", "status", "role", "q"])
def test_list_users_parameter_sent_twice_is_400_validation_failed(name: str) -> None:
    value = {"limit": "5", "cursor": "x", "status": "active", "role": "viewer", "q": "u"}[name]
    r = World(UserRows(rows(3))).client().get("/users", params=[(name, value), (name, value)])
    _refused(r, 400, "validation_failed")
    assert _errors(r) == [(name, "single")]


def test_list_users_problem_names_the_field_never_the_value() -> None:
    canary = "zz-canary-5478"
    sent = [("status", canary), ("role", canary), ("limit", canary), ("q", canary * 9)]
    r = World(UserRows(rows(3))).client().get("/users", params=sent)
    _refused(r, 400, "validation_failed")
    assert {field for field, _ in _errors(r)} == {"status", "role", "limit", "q"}
    assert canary not in r.text


def test_list_users_unknown_parameter_is_ignored() -> None:
    """BQ-3: as on every list; `sort` stays E42-D03 CG-29's."""
    world = World(UserRows(rows(3)))
    assert world.get(sort="username", statuss="locked").json() == world.get().json()


def test_list_users_store_outage_is_503_store_unavailable_with_retry_after() -> None:
    world = World(UserRows(rows(3)))
    world.store.error = ConnectionRefusedError(111, "database down")
    r = world.get()
    _refused(r, 503, "store_unavailable")
    assert r.headers["retry-after"] == "5"
    world.store.error = ValueError("a defect")
    assert world.get().status_code == 500  # anything but an outage is a defect


def test_list_users_no_store_wired_answers_501_after_rbac() -> None:
    owner = World(UserRows(rows(3)), wired=False)
    assert owner.get().json()["code"] == "not_implemented" and owner.get().status_code == 501
    _refused(World(UserRows(rows(3)), principal("viewer"), wired=False).get(), 403, "forbidden")
    app, never_called = FastAPI(), cast(Any, object())  # a notifier no list request reaches
    app.include_router(make_user_admin_router(None, Records(), None, never_called))
    assert TestClient(app).get("/users").status_code == 501  # no principal resolver wired


def test_list_users_answers_only_22s_user_fields() -> None:
    """The store's rows carry columns no `User` has; the answer holds 22's `User` fields only."""
    r = World(UserRows(rows(3))).get()
    fields = set(SPEC["components"]["schemas"]["User"]["properties"])
    assert r.status_code == 200 and all(set(item) <= fields for item in r.json()["items"])
    for canary in ("password_hash", "argon2id", "100.64.0.9", "failed_login_count", "purge"):
        assert canary not in r.text


def test_list_users_rows_equal_get_users_body_for_the_same_user() -> None:
    """The ruling's parity test: each listed row is `getUser`'s body for the same user, both
    built through the generated `User` model (`representation()`)."""
    client = World(UserRows(rows(5))).client()
    items = client.get("/users").json()["items"]
    assert len(items) == 5
    assert all(client.get(f"/users/{item['id']}").json() == item for item in items)


def test_list_users_served_read_writes_no_audit_record() -> None:
    world = World(UserRows(rows(3)))
    assert [world.get().status_code, world.get(status="active").status_code] == [200, 200]
    assert world.records.calls == []


def test_list_users_logs_carry_no_query_value_user_field_or_cursor() -> None:
    made, secret = rows(3), "q-canary-5478"
    world = World(UserRows(made))
    with capture_logs() as logs:
        cursor = _cursor(world, q="user")
        world.get(q="user", cursor=cursor)
        refused = World(UserRows(made), principal("viewer"), Records(fail=AuditUnavailable("down")))
        refused.get(q=secret)
        world.get(cursor=f"not-a-cursor-{secret}")
        world.store.error = OSError("down")
        world.get(q=secret)
    text = repr(logs)
    assert {entry.get("error") for entry in logs} >= {"AuditUnavailable", "OSError"}
    assert secret not in text and cursor not in text
    assert not any(row.username in text or row.email in text for row in made)
