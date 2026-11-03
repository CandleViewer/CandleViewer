"""#5478: `api.user_list_params`, the query and cursor of `GET /users`: the parameters and bounds
22 declares, the cursor's round trip for its binding and its refusal of any other, and the paging
property through the route over the in-memory store that keeps the SQL store's order
(`user_list_world`)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, get_args

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.api import user_list_params as p
from tests.unit.api.user_list_world import SPEC, T0, Row, UserRows, World

_NOW = int(T0.timestamp())
_TIMES = st.datetimes(datetime(1, 1, 1), datetime(9999, 12, 31), timezones=st.just(UTC))
_Q = st.text(max_size=p.MAX_Q).filter(lambda q: "\x00" not in q)
_BINDINGS = st.tuples(
    st.none() | st.sampled_from(get_args(p.UserStatusName)),
    st.none() | st.sampled_from(get_args(p.RoleNameValue)),
    st.none() | _Q,
)


def _query(binding: tuple[str | None, ...], cursor: str | None = None) -> p.UserListQuery:
    status, role, q = binding
    read = {"status": status, "role": role, "q": q, "cursor": cursor}
    return p.UserListQuery.model_validate(read)


def test_user_list_params_read_exactly_22s_declared_query_and_bounds() -> None:
    op, params = SPEC["paths"]["/users"]["get"], SPEC["components"]["parameters"]
    declared = [params[x["$ref"].rsplit("/", 1)[1]] if "$ref" in x else x for x in op["parameters"]]
    assert {x["name"] for x in declared} == set(p.PARAMS)
    assert p.OPERATION == op["operationId"] == "listUsers"  # what a cursor is bound to
    schemas = SPEC["components"]["schemas"]
    assert list(get_args(p.UserStatusName)) == schemas["UserStatus"]["enum"]
    assert list(get_args(p.RoleNameValue)) == schemas["RoleName"]["enum"]
    limit, q = params["Limit"]["schema"], next(x for x in declared if x["name"] == "q")
    bounds = (limit["minimum"], limit["default"], limit["maximum"])
    assert bounds == (1, p.DEFAULT_LIMIT, p.MAX_LIMIT)
    assert p.MAX_Q == q["schema"]["maxLength"] and params["Cursor"]["schema"]["maxLength"] == 512


@given(at=_TIMES, key=st.uuids(), binding=_BINDINGS, caller=st.uuids())
@settings(max_examples=200, deadline=None, derandomize=True, database=None)
def test_cursor_round_trips_its_position_for_its_binding(
    at: datetime, key: uuid.UUID, binding: tuple[str | None, ...], caller: uuid.UUID
) -> None:
    cursor = p.next_cursor(_query(binding), caller, (at, key), _NOW)
    assert p.read_after(_query(binding, cursor), caller, _NOW) == (at, key)


@given(
    at=_TIMES, key=st.uuids(), binding=_BINDINGS, other=_BINDINGS, caller=st.uuids(),
    stranger=st.uuids(),
)  # fmt: skip
@settings(max_examples=200, deadline=None, derandomize=True, database=None)
def test_cursor_refuses_another_binding(
    at: datetime, key: uuid.UUID, binding: tuple[str | None, ...],
    other: tuple[str | None, ...], caller: uuid.UUID, stranger: uuid.UUID,
) -> None:  # fmt: skip
    cursor = p.next_cursor(_query(binding), caller, (at, key), _NOW)
    for who, bound in ((stranger, binding), (caller, other)):
        if (who, bound) != (caller, binding):
            with pytest.raises(p.CursorInvalid):
                p.read_after(_query(bound, cursor), who, _NOW)


@given(
    times=st.lists(st.integers(0, 3), max_size=12),
    size=st.integers(1, 5),
    inserts=st.lists(st.integers(0, 2), max_size=4),
)
@settings(max_examples=60, deadline=None, derandomize=True, database=None)
def test_pages_partition_any_user_set_for_any_page_size(
    times: list[int], size: int, inserts: list[int]
) -> None:
    """Any users, ties on `created_at` included, any page size, users created between pages:
    every user there at the start is listed exactly once, in `(created_at, id)` order, and no
    row repeats."""
    made = [
        Row(uuid.UUID(int=n * 7919 % 9973 + 1), f"user{n}", f"user{n}@x.invalid",
            T0 + timedelta(seconds=t))
        for n, t in enumerate(times)
    ]  # fmt: skip
    world, pending = World(UserRows(made)), list(inserts)
    client, seen, cursor = world.client(), list[str](), None
    for _ in range(len(made) + len(inserts) + 1):  # a page holds a row, but the first may not
        params: dict[str, Any] = {"limit": size} | ({} if cursor is None else {"cursor": cursor})
        body = client.get("/users", params=params).json()
        seen += [item["id"] for item in body["items"]]
        if (cursor := body["meta"]["next_cursor"]) is None:
            break
        if pending:  # created now: a later `created_at` than any user read so far
            uid = uuid.UUID(int=50_000 + len(world.store.rows))
            at = T0 + timedelta(seconds=9 + pending.pop())
            world.store.rows[uid] = Row(uid, f"late{uid.int}", f"late{uid.int}@x.invalid", at)
    else:
        raise AssertionError("the cursor never reached the last page")
    before = [str(r.id) for r in sorted(made, key=lambda r: (r.created_at, r.id))]
    assert len(seen) == len(set(seen))
    assert [uid for uid in seen if uid in set(before)] == before
