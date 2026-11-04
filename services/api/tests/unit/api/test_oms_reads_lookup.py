"""`GET /orders?idempotency_key=` and `?order_link_id=` (#2303; 22 `listOrders`, Lookup) on the
fakes of `oms_reads_world.py`: #2303's three Gherkin scenarios by name ("In-flight order resolved
after unlock", "Never-admitted order", "Scope is enforced on the lookup"), the forbidden role and
the cross-account (IDOR) cases (C-12.4), how the lookup combines with the other filters and the
cursor, and the parameters' refusals, pinned to the contract's bounds."""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from starlette.datastructures import QueryParams

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.oms_read_params import MAX_LOOKUP, ParamsInvalid, order_query
from candleviewer.domain.order_link import EXT_ID, OUR_ID
from candleviewer.oms.submit import entry_order_id
from candleviewer.storage.repositories.oms_reads import AnchoredTarget
from tests.unit.api.oms_reads_world import (
    ACCOUNT_A,
    ACCOUNT_B,
    USERS,
    World,
    bearer,
    ids,
    order,
    viewing_as,
)

#: The client's keys: K, the manager's entry on A; R, the manager's reduce-only order on A;
#: F, the manager's entry on B, an account outside its grants; OWN, the owner's entry on A.
K = uuid.UUID("6f1c2b7e-3a4d-4e5f-8a6b-7c8d9e0f1a2b")
R = uuid.UUID("6f1c2b7e-3a4d-4e5f-8a6b-7c8d9e0f1a2c")
F = uuid.UUID("6f1c2b7e-3a4d-4e5f-8a6b-7c8d9e0f1a2d")
OWN = uuid.UUID("6f1c2b7e-3a4d-4e5f-8a6b-7c8d9e0f1a2e")
GROUP_K = uuid.UUID("0c000000-0000-4000-8000-0000000023a1")
GROUP_F = uuid.UUID("0c000000-0000-4000-8000-0000000023b1")
GROUP_O = uuid.UUID("0c000000-0000-4000-8000-0000000023c1")
REDUCE = uuid.UUID("0a000000-0000-4000-8000-0000000023a2")
LINK_K = "cvd-0MduI3fiqJ6h0wkltsuR4T-JelO-00en"
LINK_B = "ext-" + "b" * 32


def _world(state: str = "filled", lifecycle: str = "filled") -> World:
    """The seeded world plus the anchored orders of the keys above."""
    world, manager = World(), USERS["manager"]
    rows = [
        (order(21, ACCOUNT_A, id=entry_order_id(GROUP_K), state=state,
               lifecycle_state=lifecycle, order_link_id=LINK_K), GROUP_K),
        (order(22, ACCOUNT_A, id=REDUCE, reduce_only=True, intent="flatten",
               state="rejected", lifecycle_state="rejected"), None),
        (order(23, ACCOUNT_B, id=entry_order_id(GROUP_F), order_link_id=LINK_B), GROUP_F),
        (order(24, ACCOUNT_A, id=entry_order_id(GROUP_O)), GROUP_O),
    ]  # fmt: skip
    world.store.orders += rows
    world.store.anchors |= {
        (manager, K): AnchoredTarget(None, GROUP_K),
        (manager, R): AnchoredTarget(REDUCE, None),
        (manager, F): AnchoredTarget(None, GROUP_F),
        (USERS["owner"], OWN): AnchoredTarget(None, GROUP_O),
    }
    return world


async def _get(world: World, who: str = "manager", **params: Any) -> Any:
    async with world.client() as client:
        return await client.get("/orders", params=params, headers=bearer(who))


# -- "In-flight order resolved after unlock" -----------------------------------------------------


@pytest.mark.parametrize(
    ("state", "lifecycle"),
    [("filled", "filled"), ("rejected", "rejected"), ("accepted", "submitted"),
     ("submitted", "submitting"), ("unknown", "unknown")],
)  # fmt: skip
async def test_in_flight_order_resolved_after_unlock_the_page_is_exactly_its_order(
    state: str, lifecycle: str
) -> None:
    """Gherkin: the page holds exactly the order the OMS created for K, in its current state,
    terminal or still pending (`open_only` is false by default)."""
    answer = await _get(_world(state, lifecycle), idempotency_key=str(K))
    assert answer.status_code == 200
    [item] = answer.json()["items"]
    assert (item["id"], item["state"]) == (str(entry_order_id(GROUP_K)), state)
    assert item["trade_group_id"] == str(GROUP_K)
    assert answer.json()["meta"]["has_more"] is False


async def test_a_reduce_only_request_resolves_to_the_order_its_anchor_names() -> None:
    answer = await _get(_world(), idempotency_key=str(R))
    assert ids(answer.json()) == [str(REDUCE)]
    assert answer.json()["items"][0]["state"] == "rejected"


async def test_the_key_is_matched_as_a_uuid_whatever_its_case_and_once_when_repeated() -> None:
    world = _world()
    answer = await _get(world, idempotency_key=[str(K).upper(), str(K), str(R)])
    assert sorted(ids(answer.json())) == sorted([str(entry_order_id(GROUP_K)), str(REDUCE)])


async def test_the_unhyphenated_form_of_a_key_is_accepted_and_canonicalised() -> None:
    """`Idempotency-Key` is read as a UUID (`order_admission.idempotency_key`), so its 32-digit
    form names the same anchor, `client_ref`'s canonical lower-case text."""
    world = _world()
    answer = await _get(world, idempotency_key=K.hex.upper())
    assert ids(answer.json()) == [str(entry_order_id(GROUP_K))]
    assert order_query(QueryParams([("idempotency_key", K.hex)])).query.idempotency_keys == {K}


# -- "Never-admitted order" ----------------------------------------------------------------------


async def test_never_admitted_order_the_page_is_empty() -> None:
    """Gherkin: a key refused before anything was recorded binds nothing, so the page is empty
    (no refusal), and no order carries it."""
    world, never = _world(), uuid.UUID("6f1c2b7e-3a4d-4e5f-8a6b-000000000000")
    answer = await _get(world, idempotency_key=str(never))
    assert (answer.status_code, answer.json()["items"]) == (200, [])
    assert all(key != never for _, key in world.store.anchors)
    assert world.audit.emitted == []


# -- "Scope is enforced on the lookup" -----------------------------------------------------------


async def test_scope_is_enforced_on_the_lookup_a_key_on_an_ungranted_account_is_an_empty_page() -> (
    None
):
    """Gherkin: the manager's own key whose order is on B, outside its grants, is answered as a
    key never seen: an empty page, no refusal and no audit, so nothing says the order exists."""
    world = _world()
    answer = await _get(world, idempotency_key=str(F))
    assert (answer.status_code, answer.json()["items"]) == (200, [])
    assert world.audit.emitted == []
    owner = await _get(world, "owner", idempotency_key=str(F))  # the manager's key, not the owner's
    assert owner.json()["items"] == []


async def test_scope_is_enforced_on_the_lookup_another_principals_key_reads_as_never_seen() -> None:
    """The anchor is the principal's (21 Sec.3.3.10): the owner's key on A, which the manager
    views, finds nothing for the manager, and the manager's keys nothing for the owner."""
    world = _world()
    assert (await _get(world, idempotency_key=str(OWN))).json()["items"] == []
    assert (await _get(world, "owner", idempotency_key=str(K))).json()["items"] == []
    found = await _get(world, "owner", idempotency_key=str(OWN))
    assert ids(found.json()) == [str(entry_order_id(GROUP_O))]


async def test_scope_is_enforced_on_the_lookup_an_order_link_id_on_b_is_an_empty_page() -> None:
    """IDOR by `order_link_id`: B's order is never served to a grant on A; the owner views it."""
    world = _world()
    answer = await _get(world, order_link_id=LINK_B)
    assert (answer.status_code, answer.json()["items"]) == (200, [])
    assert ids((await _get(world, "owner", order_link_id=LINK_B)).json()) == [
        str(entry_order_id(GROUP_F))
    ]
    named_b = await _get(world, idempotency_key=str(F), exchange_account_ids=str(ACCOUNT_B))
    assert (named_b.status_code, named_b.json()["code"]) == (403, "account_scope_denied")


async def test_scope_is_enforced_on_the_lookup_under_view_as_the_targets_keys_are_matched() -> None:
    """22 Lookup: the Owner viewing as the Manager reads with the Manager's scope, so the
    Manager's key resolves and the Owner's own key reads as empty while viewing."""
    world = _world()
    world.viewing = viewing_as("manager")
    found = await _get(world, "manager", idempotency_key=str(K))
    assert ids(found.json()) == [str(entry_order_id(GROUP_K))]
    own = await _get(world, "manager", idempotency_key=str(OWN))
    assert (own.status_code, own.json()["items"]) == (200, [])


async def test_a_named_foreign_account_refuses_alike_whatever_the_key_and_reads_no_anchor() -> None:
    """No oracle: the manager's own existing key and an unknown one, with B named, are the same
    `403 account_scope_denied` and the same audit record, refused before any anchor is read."""
    answers, records = [], []
    for key in (K, uuid.UUID("6f1c2b7e-3a4d-4e5f-8a6b-000000000000")):
        world = _world()
        answer = await _get(world, idempotency_key=str(key), exchange_account_ids=str(ACCOUNT_B))
        answers.append((answer.status_code, answer.json()))
        records.append(world.audit.emitted)
        assert "anchored" not in world.store.calls
    assert answers[0] == answers[1] and answers[0][0] == 403
    assert answers[0][1]["code"] == "account_scope_denied"
    assert records[0] == records[1] and len(records[0]) == 1


async def test_a_caller_without_orders_read_is_403_and_reads_no_anchor() -> None:
    world = _world()
    answer = await _get(world, "bare", idempotency_key=str(K))
    assert (answer.status_code, answer.json()["code"]) == (403, "forbidden")
    assert world.store.calls == [] and world.audit.actions() == ["rbac.denied"]


# -- combination, paging and refusals ------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "found"),
    [
        ({"open_only": "true"}, False),  # the filled order is no open one
        ({"state": "accepted"}, False),
        ({"state": "filled"}, True),
        ({"order_link_id": LINK_K}, True),
        ({"order_link_id": LINK_B}, False),  # AND, never OR
        ({"exchange_account_ids": str(ACCOUNT_A)}, True),
        ({"symbol": "ETHUSDT"}, False),
    ],
)
async def test_the_lookup_ands_with_every_other_filter(params: dict[str, str], found: bool) -> None:
    answer = await _get(_world(), idempotency_key=str(K), **params)
    assert answer.status_code == 200
    assert ids(answer.json()) == ([str(entry_order_id(GROUP_K))] if found else [])


async def test_the_order_link_id_alone_finds_its_order_in_scope() -> None:
    answer = await _get(_world(), order_link_id=LINK_K)
    assert ids(answer.json()) == [str(entry_order_id(GROUP_K))]


async def test_a_lookup_pages_like_any_list_and_its_cursor_is_bound_to_its_keys() -> None:
    world = _world()
    first = (await _get(world, idempotency_key=[str(K), str(R)], limit="1")).json()
    cursor = first["meta"]["next_cursor"]
    assert len(first["items"]) == 1 and cursor
    rest = await _get(world, idempotency_key=[str(R), str(K)], limit="1", cursor=cursor)
    assert {*ids(first), *ids(rest.json())} == {str(entry_order_id(GROUP_K)), str(REDUCE)}
    other = await _get(world, idempotency_key=str(K), limit="1", cursor=cursor)
    assert (other.status_code, other.json()["code"]) == (400, "invalid_cursor")


_TOO_MANY = [str(uuid.UUID(int=n)) for n in range(MAX_LOOKUP + 1)]


@pytest.mark.parametrize(
    ("params", "field", "rule"),
    [
        ({"idempotency_key": "not-a-key"}, "idempotency_key", "uuid"),
        ({"idempotency_key": _TOO_MANY}, "idempotency_key", "max_items"),
        ({"order_link_id": "cvl-short"}, "order_link_id", "pattern"),
        ({"order_link_id": [LINK_K] * (MAX_LOOKUP + 1)}, "order_link_id", "max_items"),
    ],
)
async def test_a_malformed_lookup_is_400_naming_its_parameter_and_reads_nothing(
    params: dict[str, Any], field: str, rule: str
) -> None:
    world = _world()
    answer = await _get(world, **params)
    assert (answer.status_code, answer.json()["code"]) == (400, "validation_failed")
    assert {(e["field"], e["rule"]) for e in answer.json()["errors"]} == {(field, rule)}
    assert world.store.calls == []


def test_twenty_values_of_each_pass_and_parse_to_their_sets() -> None:
    keys = [str(uuid.UUID(int=n)) for n in range(MAX_LOOKUP)]
    links = ["ext-" + f"{n:032x}" for n in range(MAX_LOOKUP)]
    params = QueryParams(
        [("idempotency_key", k) for k in keys] + [("order_link_id", v) for v in links]
    )
    query = order_query(params).query
    assert query.idempotency_keys == {uuid.UUID(k) for k in keys}
    assert query.order_link_ids == set(links) and query.order_ids is None
    with pytest.raises(ParamsInvalid):
        order_query(QueryParams([("order_link_id", LINK_K + "x")]))


def test_past_twenty_values_only_one_max_items_error_and_no_value_is_read() -> None:
    """Values past `MAX_LOOKUP` are never parsed: one `max_items`, no `uuid` error per extra."""
    pairs = [("idempotency_key", str(uuid.UUID(int=n))) for n in range(MAX_LOOKUP)]
    pairs += [("idempotency_key", "not-a-key")] * 1000
    with pytest.raises(ParamsInvalid) as refused:
        order_query(QueryParams(pairs))
    assert [(e.field, e.rule) for e in refused.value.errors] == [("idempotency_key", "max_items")]


def test_the_parser_holds_the_contracts_bounds_and_pattern() -> None:
    """22 `listOrders`' two parameters, as the parser reads them: at most 20, the key a UUID,
    the link id the `Order.order_link_id` pattern (`OUR_ID` or `EXT_ID`)."""
    spec: Any = load_openapi_spec()
    declared = {p.get("name"): p for p in spec["paths"]["/orders"]["get"]["parameters"]}
    key, link = declared["idempotency_key"]["schema"], declared["order_link_id"]["schema"]
    assert key["maxItems"] == link["maxItems"] == MAX_LOOKUP
    assert key["items"]["format"] == "uuid"
    pattern = link["items"]["pattern"]
    assert (
        pattern == spec["components"]["schemas"]["Order"]["properties"]["order_link_id"]["pattern"]
    )
    for sample in (LINK_K, LINK_B, "cvl-short", "ext-" + "B" * 32):
        ours = OUR_ID.fullmatch(sample) is not None or EXT_ID.fullmatch(sample) is not None
        assert ours is (re.fullmatch(pattern, sample) is not None), sample
