"""The OMS read routes (E29-T07 #915, PR 1; 22 `listOrders`, `getOrder`, `getOrderDiagnostics`,
`listPositions`, `getPosition`, `listExecutions`, `listClosedPnl`) on the fakes of
`oms_reads_world.py`: each admission step driven alone, the scope's refusals and their records,
the cursor's binding, the bodies' members, and three of #915's Gherkin scenarios by name:
"Scope is enforced server-side", "Diagnostics never leak secrets" and "Aggregate positions never
mix environments". Contract conformance is `tests/contract/test_oms_read_routes_contract.py`."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from starlette.datastructures import QueryParams

from candleviewer.api.oms_read_params import next_cursor, order_query
from candleviewer.api.order_diagnostics import RecordRefused, exchange_calls
from candleviewer.storage.repositories.exchange_payload import redact_exchange_payload
from candleviewer.storage.repositories.oms_reads import MAX_ORDER_EXECUTIONS, Keyset
from candleviewer.storage.repositories.orders import MAX_EVENT_PAGE
from tests.unit.api.oms_reads_world import (
    ACCOUNT_A,
    ACCOUNT_B,
    ACCOUNT_LIVE,
    MISSING,
    NOW,
    RECORD,
    T0,
    USERS,
    World,
    accounts_of,
    bearer,
    event,
    fill,
    ids,
    order,
    position,
    viewing_as,
)

_LISTS = ("/orders", "/executions", "/executions/closed-pnl")


async def _get(world: World, path: str, who: str = "owner", **params: Any) -> Any:
    async with world.client() as client:
        return await client.get(path, params=params, headers=bearer(who))


# -- admission ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", [*_LISTS, "/positions", f"/orders/{MISSING}", f"/positions/{MISSING}"]
)
async def test_a_read_without_a_session_is_401_and_a_missing_permission_403_audited(
    path: str,
) -> None:
    world = World()
    assert (await _get(world, path, "nobody")).status_code == 401
    refused = await _get(world, path, "bare")
    assert refused.status_code == 403 and refused.json()["code"] == "forbidden"
    assert world.audit.actions() == ["rbac.denied"] and world.store.calls == []


async def test_no_principal_source_is_501_and_its_store_down_503() -> None:
    assert (await _get(World(principals=None), "/orders")).status_code == 501
    world = World()
    assert world.principals is not None
    world.principals.fail = True
    answer = await _get(world, "/orders")
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")


@pytest.mark.parametrize("path", [*_LISTS, "/positions", f"/orders/{MISSING}"])
async def test_no_store_composed_is_503_after_rbac_and_a_failing_one_503(path: str) -> None:
    answer = await _get(World(composed=False), path)
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")
    world = World()
    world.store.fail = True
    answer = await _get(world, path)
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")


@pytest.mark.parametrize(
    ("path", "params", "code"),
    [
        ("/orders", {"limit": "0"}, "validation_failed"),
        ("/orders", {"limit": "501"}, "validation_failed"),
        ("/orders", {"state": "gone"}, "validation_failed"),
        ("/orders", {"intent": "entry2"}, "validation_failed"),
        ("/orders", {"exchange_account_ids": "not-a-uuid"}, "validation_failed"),
        ("/orders", {"symbol": "BTCUSD"}, "validation_failed"),
        ("/orders", {"open_only": "yes"}, "validation_failed"),
        ("/orders", {"from": "2026-10-29T12:00:00"}, "validation_failed"),  # no offset
        ("/orders", {"from": "2026-10-29T13:00:00Z", "to": "2026-10-29T12:00:00Z"},
         "invalid_time_range"),
        ("/executions", {"order_id": "1"}, "validation_failed"),
        ("/executions/closed-pnl", {"limit": "x"}, "validation_failed"),
        ("/positions", {"aggregate": "1"}, "validation_failed"),
        ("/orders/not-a-uuid", {}, "validation_failed"),
        (f"/orders/{MISSING}", {"include_events": "maybe"}, "validation_failed"),
        ("/positions/42", {}, "validation_failed"),
        ("/orders/42/diagnostics", {}, "validation_failed"),
    ],
)  # fmt: skip
async def test_a_malformed_parameter_is_400_and_reads_nothing(
    path: str, params: dict[str, str], code: str
) -> None:
    world = World()
    answer = await _get(world, path, **params)
    assert (answer.status_code, answer.json()["code"]) == (400, code)
    assert world.store.calls == [] and world.audit.emitted == []
    assert "errors" in answer.json()


async def test_more_than_25_accounts_is_refused() -> None:
    many = [f"a1000000-0000-4000-8000-{n:012x}" for n in range(26)]
    answer = await _get(World(), "/orders", exchange_account_ids=many)
    assert answer.status_code == 400
    assert answer.json()["errors"][0]["rule"] == "max_items"


# -- "Scope is enforced server-side" ------------------------------------------------------------


@pytest.mark.parametrize("path", [*_LISTS, "/positions"])
@pytest.mark.parametrize("who", ["manager", "viewer"])
async def test_scope_is_enforced_server_side_account_b_is_403_audited_and_reads_no_row(
    path: str, who: str
) -> None:
    """Gherkin "Scope is enforced server-side": a Manager granted only A who asks for B is answered
    `403 account_scope_denied`, no row for B is returned, and an audit row is written."""
    for asked in ([ACCOUNT_B], [ACCOUNT_A, ACCOUNT_B], [MISSING]):
        world = World()
        answer = await _get(world, path, who, exchange_account_ids=[str(a) for a in asked])
        assert (answer.status_code, answer.json()["code"]) == (403, "account_scope_denied")
        assert str(ACCOUNT_B) not in answer.text
        [record] = world.audit.emitted
        assert (record["action"], record["outcome"]) == ("rbac.denied", "denied")
        assert record["after_state"]["exchange_account_ids"] == [str(a) for a in asked]
        assert record["actor_user_id"] is not None and record["session_id"] is not None
        assert record["actor_label"] == f"user:{who}"


_COMBINATIONS: list[dict[str, Any]] = [
    {}, {"symbol": "BTCUSDT"}, {"state": "accepted"}, {"intent": "entry"}, {"open_only": "true"},
    {"trade_group_id": "0c000000-0000-4000-8000-00000000000b"},
    {"order_id": "00000000-0000-0000-0000-000000000a04"},
    {"from": "2026-10-29T11:00:00Z", "to": "2026-10-29T14:00:00Z"},
    {"exchange_account_ids": str(ACCOUNT_A)}, {"limit": "1"},
]  # fmt: skip


@pytest.mark.parametrize("path", [*_LISTS, "/positions"])
@pytest.mark.parametrize("params", _COMBINATIONS)
async def test_scope_is_enforced_server_side_no_filter_combination_returns_account_b_rows(
    path: str, params: dict[str, Any]
) -> None:
    """Gherkin "Scope is enforced server-side": no filter combination reaches B's rows (B's own
    group and order ids included), nor another environment's."""
    known = {"/orders": {"symbol", "state", "intent", "open_only", "trade_group_id"}}
    allowed = known.get(path, {"symbol", "trade_group_id", "order_id"})
    shown = {
        k: v for k, v in params.items()
        if k in allowed | {"from", "to", "exchange_account_ids", "limit"}
        and not (path == "/positions" and k in {"from", "to", "limit", "trade_group_id"})
    }  # fmt: skip
    answer = await _get(World(), path, "manager", **shown)
    assert answer.status_code == 200, answer.text
    assert accounts_of(answer.json()) <= {str(ACCOUNT_A)}


async def test_scope_is_enforced_server_side_a_cursor_minted_for_another_caller_is_400() -> None:
    """Gherkin "Scope is enforced server-side": an Owner's cursor replayed by a Manager reaches
    nothing of the Owner's page; a tampered or expired one is refused alike."""
    world = World()
    first = (await _get(world, "/orders", "owner", limit="1")).json()
    cursor = first["meta"]["next_cursor"]
    assert cursor is not None
    for who, at in (("manager", NOW), ("owner", NOW.replace(hour=14, minute=1))):
        world.now = at
        answer = await _get(world, "/orders", who, limit="1", cursor=cursor)
        assert (answer.status_code, answer.json()["code"]) == (400, "invalid_cursor")
    world.now = NOW
    head = "B" if cursor[3] != "B" else "C"  # the binding's bytes: another query's or caller's
    for forged in (cursor[:3] + head + cursor[4:], "%%%", "x" * 600):
        answer = await _get(world, "/orders", "owner", limit="1", cursor=forged)
        assert answer.json()["code"] in ("invalid_cursor", "validation_failed")
    other = await _get(world, "/orders", "owner", limit="1", cursor=cursor, symbol="ETHUSDT")
    assert other.json()["code"] == "invalid_cursor"  # bound to its filters


@pytest.mark.parametrize("kind", ["orders", "positions"])
async def test_scope_is_enforced_server_side_a_foreign_id_is_the_missing_ids_404(kind: str) -> None:
    """Gherkin "Scope is enforced server-side" on the id routes (SR-E29-13): a foreign id and a
    missing one are one answer; the foreign one is audited."""
    world = World()
    foreign = "00000000-0000-0000-0000-000000000a04" if kind == "orders" else (
        "00000000-0000-0000-0000-000000000d02"
    )  # fmt: skip
    seen = await _get(world, f"/{kind}/{foreign}", "manager")
    unseen = await _get(world, f"/{kind}/{MISSING}", "manager")
    assert seen.status_code == unseen.status_code == 404
    assert seen.json() == unseen.json() and seen.headers.keys() == unseen.headers.keys()
    [record] = world.audit.emitted
    assert (record["action"], record["object_id"]) == ("rbac.denied", foreign)


# -- lists, pages and bodies -------------------------------------------------------------------


async def test_orders_page_newest_first_and_the_cursor_walks_every_row_once() -> None:
    world, seen = World(), []
    page = (await _get(world, "/orders", limit="2")).json()
    seen += ids(page)
    while page["meta"]["has_more"]:
        page = (await _get(world, "/orders", limit="2", cursor=page["meta"]["next_cursor"])).json()
        seen += ids(page)
    rows = [o for o, _ in world.store.orders if o.exchange_account_id != ACCOUNT_LIVE]
    assert seen == [str(o.id) for o in sorted(rows, key=lambda o: o.created_ts, reverse=True)]
    assert page["meta"] == {"next_cursor": None, "has_more": False, "count": len(ids(page))}


async def test_open_only_is_the_non_terminal_set_held_included() -> None:
    body = (await _get(World(), "/orders", "manager", open_only="true")).json()
    assert {item["state"] for item in body["items"]} == {"accepted", "held"}


async def test_an_order_carries_its_group_remaining_qty_and_creation_time() -> None:
    [first, *_] = (await _get(World(), "/orders", "manager", state="accepted")).json()["items"]
    assert first["trade_group_id"] == "0c000000-0000-4000-8000-00000000000a"
    assert (first["remaining_qty"], first["environment"]) == ("0.300", "demo")
    assert first["created_at"].endswith("Z") and first["side"] == "buy"


async def test_get_order_serves_fills_events_without_payload_and_its_etag() -> None:
    world = World()
    a1 = world.store.orders[0][0]
    world.versions[a1.id] = 7
    plain = await _get(world, f"/orders/{a1.id}")
    assert "events" not in plain.json() and len(plain.json()["executions"]) == 1
    assert plain.headers["etag"] == f'"{a1.id}:7"'
    full = (await _get(world, f"/orders/{a1.id}", include_events="true")).json()
    assert full["events"] == [
        {"id": 1, "kind": "ack", "event_ts": "2026-10-29T12:00:01.000000Z"},
        {"id": 2, "kind": "ack", "event_ts": "2026-10-29T12:00:02.000000Z"},
    ]  # no payload, no exchange text (SR-E29-09)
    world.versions.clear()
    assert "etag" not in (await _get(world, f"/orders/{a1.id}")).headers


async def test_fills_and_closed_pnl_serve_what_a_fill_holds() -> None:
    fills = (await _get(World(), "/executions", "manager")).json()["items"]
    assert [f["exec_id"] for f in fills] == ["E2", "E1"]
    assert fills[0]["exec_pnl"] == "-1.25" and "exec_pnl" not in fills[1]
    closed = (await _get(World(), "/executions/closed-pnl", "manager")).json()["items"]
    assert closed == [{
        "id": fills[0]["id"], "exchange_account_id": str(ACCOUNT_A), "symbol": "BTCUSDT",
        "side": "long", "avg_exit_price": "63099.80", "closed_pnl": "-8.191",
        "closed_at": "2026-10-29T12:02:00.000000Z",
    }]  # fmt: skip
    # -8.191 is -1.25 less the closing fill's 6.941 fee: net of fees (22 ClosedPnl, #915)


async def test_closed_pnl_is_net_of_the_closing_fills_fee() -> None:
    """#915 (the #848 notes): 22 `ClosedPnl.closed_pnl` is net of fees; the fill's stored PnL is
    gross of its own fee, so the fee is taken off, in `Decimal`."""
    world = World()
    row, group = world.store.fills[1]
    world.store.fills[1] = (_replace(row, closed_pnl=Decimal("10.5"), exec_fee=Decimal("0.25")),
                            group)  # fmt: skip
    [shown] = (await _get(world, "/executions/closed-pnl", "manager")).json()["items"]
    assert shown["closed_pnl"] == "10.25"


async def test_closed_pnl_never_carries_a_settlement_row_that_closes_no_size() -> None:
    """#915 (the #848 notes): a `Settle`, `SessionSettlePnl` or `Funding` row carries a PnL and
    closes nothing: it is not a closed position."""
    world = World()
    row, group = world.store.fills[1]
    for kind in ("Settle", "SessionSettlePnl", "Funding"):
        world.store.fills[1] = (_replace(row, exec_type=kind), group)
        listed = (await _get(world, "/executions/closed-pnl", "manager")).json()["items"]
        assert listed == [], kind


async def test_closed_pnl_a_fill_recovered_by_rest_holds_none_and_is_absent() -> None:
    """#915: the venue's execution list carries no closed PnL, so a REST-recovered fill keeps
    NULL and is not listed; a complete listing needs the venue's closed-PnL endpoint."""
    world = World()
    row, group = world.store.fills[1]
    world.store.fills[1] = (_replace(row, closed_pnl=None), group)
    assert (await _get(world, "/executions/closed-pnl", "manager")).json()["items"] == []


async def test_a_stored_exec_type_22_does_not_name_is_absent() -> None:
    world = World()
    row, group = world.store.fills[0]
    world.store.fills[0] = (_replace(row, exec_type="SessionSettlePnl"), group)
    [*_, shown] = (await _get(world, "/executions", "manager")).json()["items"]
    assert "exec_type" not in shown


def _replace(row: Any, **over: Any) -> Any:
    from dataclasses import replace

    return replace(row, **over)


async def test_positions_render_22s_vocabulary_and_absent_members() -> None:
    body = (await _get(World(), "/positions", "manager", open_only="false")).json()
    by_symbol = {item["symbol"]: item for item in body["items"]}
    btc, eth, sol = by_symbol["BTCUSDT"], by_symbol["ETHUSDT"], by_symbol["SOLUSDT"]
    assert (btc["side"], btc["native_stop_present"], btc["trailing_stop"]) == ("long", True, "0")
    assert (eth["side"], "native_stop_present" in eth) == ("flat", False)
    assert sol["native_stop_present"] is False  # C-2.6's alarm, said
    assert "margin_mode" not in btc and "realised_pnl_session" not in btc
    assert body["aggregates"] == []
    shown = await _get(World(), f"/positions/{btc['id']}", "viewer")
    assert shown.json() == btc


# -- "Aggregate positions never mix environments" ------------------------------------------------


async def test_aggregate_positions_never_mix_environments() -> None:
    """Gherkin "Aggregate positions never mix environments": with a demo and a live account
    holding BTCUSDT, this demo server's aggregate sums its own environment's legs alone (one OMS
    per environment, 20 Sec.6.2), and the live leg is in neither the items nor the breakdown."""
    body = (await _get(World(), "/positions", "owner", aggregate="true")).json()
    assert str(ACCOUNT_LIVE) not in json.dumps(body)
    btc = next(a for a in body["aggregates"] if a["symbol"] == "BTCUSDT")
    assert {leg["exchange_account_id"] for leg in btc["accounts"]} == {
        str(ACCOUNT_A),
        str(ACCOUNT_B),
    }
    assert (btc["net_size"], btc["gross_size"]) == ("0.100", "0.300")  # 0.2 long, 0.1 short
    assert "weighted_avg_price" not in btc  # across a long and a short: not defined by 22
    assert btc["unrealised_pnl"] == "7.64"
    one_side = (await _get(World(), "/positions", "manager", aggregate="true")).json()
    [btc] = [a for a in one_side["aggregates"] if a["symbol"] == "BTCUSDT"]
    assert (btc["net_size"], btc["weighted_avg_price"]) == ("0.200", "63000")


# -- getOrderDiagnostics -----------------------------------------------------------------------


def _diagnostics(world: World, who: str = "owner", order_id: object = None) -> Any:
    target = world.store.orders[0][0].id if order_id is None else order_id
    return _get(world, f"/orders/{target}/diagnostics", who)


async def test_diagnostics_serve_the_order_events_and_records_after_the_audit_row() -> None:
    world = World()
    answer = await _diagnostics(world)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["exchange_calls"] == [{"event_id": 1, "at": "2026-10-29T12:00:01Z", **RECORD}]
    assert [e["id"] for e in body["events"]] == [1, 2] and "reconciliation" not in body
    [record] = world.audit.emitted
    assert (record["action"], record["object_kind"]) == ("order.diagnostics_viewed", "order")
    assert record["actor_label"] == "user:owner"  # 24 Sec.15.5's `user:<role>` (#4997 M2)
    assert record["object_id"] == body["order"]["id"]
    assert record["after_state"] == {"account_id": str(ACCOUNT_A)}
    assert record["session_id"] is not None and record["actor_user_id"] is not None


@pytest.mark.parametrize("who", ["manager", "viewer"])
async def test_diagnostics_are_the_owners_alone_whatever_the_id(who: str) -> None:
    """D7 (ruled on #915): a Manager or Viewer holding `orders:read` on A is refused `403
    forbidden` for A's order, B's and a missing one alike, before any order is read."""
    answers = []
    for target in (None, "00000000-0000-0000-0000-000000000a04", MISSING):
        world = World()
        answer = await _diagnostics(world, who, target)
        answers.append((answer.status_code, answer.json()))
        assert world.store.calls == [] and world.audit.actions() == ["rbac.denied"]
        assert answer.json()["required_permissions"] == ["orders:read", "admin:read"]
    assert {a[0] for a in answers} == {403} and answers[0][1] == answers[1][1] == answers[2][1]


async def test_diagnostics_of_another_environments_or_a_missing_order_are_one_404() -> None:
    world = World()
    live = await _diagnostics(world, "owner", "00000000-0000-0000-0000-000000000a05")
    missing = await _diagnostics(world, "owner", MISSING)
    assert live.status_code == missing.status_code == 404 and live.json() == missing.json()
    assert world.audit.actions() == ["rbac.denied"]  # the other environment's holder, recorded


async def test_a_diagnostics_read_that_cannot_be_recorded_is_503_with_no_body() -> None:
    world = World()
    world.audit.fail = True
    answer = await _diagnostics(world)
    assert (answer.status_code, answer.json()["code"]) == (503, "audit_unavailable")
    assert "exchange_calls" not in answer.text and "/v5/order/create" not in answer.text


_KEY = "DUMMYKEY" + "Q3w9" * 5  # synthetic, built at run time (SR-145)
_SIGN = "9f" * 32
_SECRETS = (_KEY, _SIGN, "recv_window", "X-BAPI")


def _stored(payload: dict[str, object]) -> dict[str, object]:
    """A payload as the store keeps it: redacted before insert (E29-T01)."""
    return redact_exchange_payload(payload)


async def test_diagnostics_never_leak_secrets() -> None:
    """Gherkin "Diagnostics never leak secrets": a payload holding a key, a signature and a
    recv-window credential beside its record serves the record alone, and a record holding any
    of them is never served (the read fails closed); the read itself is audited."""
    world = World()
    a1 = world.store.orders[0][0]
    beside = {
        "headers": {"X-BAPI-API-KEY": _KEY, "X-BAPI-SIGN": _SIGN, "X-BAPI-RECV-WINDOW": "5000"},
        "api_key": _KEY, "sign": _SIGN, "recv_window": "5000", "record": RECORD,
    }  # fmt: skip
    world.store.events[a1.id] = [event(1, a1.id, _stored(beside))]
    answer = await _diagnostics(world)
    assert answer.status_code == 200
    assert not [s for s in _SECRETS if s in answer.text]
    assert answer.json()["exchange_calls"][0]["request_redacted"] == RECORD["request_redacted"]
    assert world.audit.actions() == ["order.diagnostics_viewed"]
    inside: list[dict[str, object]] = [
        {**RECORD, "api_key": _KEY},
        {**RECORD, "request_redacted": {"symbol": "BTCUSDT", "sign": _SIGN}},
        {**RECORD, "headers": {"X-BAPI-RECV-WINDOW": "5000"}},
        {**RECORD, "ret_msg": f"error sign! origin_string[1760630400000{_KEY}5000]"},
    ]
    for record in inside:
        for stored in (True, False):  # as the store keeps it, or as no redactor left it
            world = World()
            payload = _stored({"record": record}) if stored else {"record": record}
            world.store.events[a1.id] = [event(1, a1.id, payload)]
            answer = await _diagnostics(world)
            assert not [s for s in _SECRETS if s in answer.text]
            if answer.status_code == 200:  # only a stored record whose secret the store masked
                assert stored and record["ret_msg"] != RECORD["ret_msg"]
                assert world.audit.actions() == ["order.diagnostics_viewed"]
                continue
            assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")
            assert world.audit.emitted == []  # nothing served, nothing viewed


_NAMES = st.sampled_from(
    ["api_key", "apiKey", "sign", "signature", "recv_window", "secret", "auth"]
)


@settings(max_examples=60, deadline=None, derandomize=True)
@given(name=_NAMES, value=st.text(min_size=8, max_size=40), where=st.sampled_from(["top", "req"]))
def test_diagnostics_never_leak_secrets_under_any_extra_member(
    name: str, value: str, where: str
) -> None:
    """Gherkin "Diagnostics never leak secrets", fuzzed: a member the contract does not name, at
    the record's top or in its request, whatever its value, is never served."""
    record: dict[str, object] = dict(RECORD)
    if where == "top":
        record[name] = value
    else:
        record["request_redacted"] = {**RECORD["request_redacted"], name: value}  # type: ignore[dict-item]  # a mapping
    row = event(1, order(1, ACCOUNT_A).id, _stored({"record": record}))
    with pytest.raises(RecordRefused):
        exchange_calls([row])


@settings(max_examples=60, deadline=None, derandomize=True)
@given(
    st.text(
        alphabet="ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0123456789",
        min_size=18,
        max_size=40,
    ).filter(lambda t: any(c.isalpha() for c in t) and any(c.isdigit() for c in t))
)
def test_diagnostics_never_leak_secrets_echoed_in_the_message(token: str) -> None:
    """A key-shaped token the exchange echoes in `ret_msg` is masked by the store; a record that
    still holds one is never served."""
    record = {**RECORD, "ret_msg": f"error sign! origin_string[1760630400000{token}5000]"}
    try:
        [served] = exchange_calls([event(1, order(1, ACCOUNT_A).id, _stored({"record": record}))])
    except RecordRefused:
        return
    assert token not in json.dumps(served)


def test_a_cursor_names_its_last_row_and_reads_back_its_place() -> None:
    from starlette.datastructures import QueryParams

    from candleviewer.api.oms_read_params import read_after

    listing = order_query(QueryParams("limit=2"))
    last = Keyset(T0, order(1, ACCOUNT_A).id)
    cursor = next_cursor(listing, "listOrders", ACCOUNT_A, last, 1000)
    again = order_query(QueryParams(f"limit=2&cursor={cursor}"))
    assert read_after(again, "listOrders", ACCOUNT_A, 1000) == last
    assert Decimal("0.300") == Decimal(order(1, ACCOUNT_A).leaves_qty)
    assert position(1, ACCOUNT_A).size == Decimal("0.200")


# -- the lens's folds (#4997) -------------------------------------------------------------------


async def test_scope_is_enforced_server_side_a_forged_cursor_position_reaches_no_foreign_row() -> (
    None
):
    """The cursor is no security boundary: its digest is unkeyed, so a caller can forge any
    position under its own binding; one pointing at B's row still reads only A's (scope in SQL)."""
    world = World()
    b1 = next(o for o, _ in world.store.orders if o.exchange_account_id == ACCOUNT_B)
    listing = order_query(QueryParams("limit=1"))
    me = world.principals.tokens["manager"].snapshot.user_id  # type: ignore[union-attr]  # composed
    forged = next_cursor(
        listing, "listOrders", me, Keyset(b1.created_ts, b1.id), int(NOW.timestamp())
    )
    answer = await _get(world, "/orders", "manager", limit="1", cursor=forged)
    assert answer.status_code == 200 and accounts_of(answer.json()) <= {str(ACCOUNT_A)}


async def test_diagnostics_of_an_over_long_chain_fail_closed() -> None:
    world = World()
    a1 = world.store.orders[0][0]
    world.store.events[a1.id] = [event(n, a1.id, {}) for n in range(1, MAX_EVENT_PAGE + 2)]
    answer = await _diagnostics(world)
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")
    assert world.audit.emitted == []  # nothing served, nothing viewed


@pytest.mark.parametrize("member", ["event_id", "at"])
async def test_a_stored_record_naming_a_computed_member_is_never_served(member: str) -> None:
    world = World()
    a1 = world.store.orders[0][0]
    record = {**RECORD, member: 99 if member == "event_id" else "2020-01-01T00:00:00Z"}
    world.store.events[a1.id] = [event(1, a1.id, {"record": record})]
    answer = await _diagnostics(world)
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")


async def test_get_order_reads_its_version_before_its_row() -> None:
    """#4997: the `ETag` is never fresher than the body: the version is read first."""
    world = World()
    a1 = world.store.orders[0][0]
    world.versions = _Versions(world.store.calls)
    answer = await _get(world, f"/orders/{a1.id}")
    assert answer.headers["etag"] == f'"{a1.id}:3"'
    assert world.store.calls == ["version", "order"]


class _Versions(dict[Any, int]):
    """B1's versions as the route reads them, each read noted in the store's call log."""

    def __init__(self, calls: list[str]) -> None:
        super().__init__()
        self.calls = calls

    def get(self, key: Any, default: Any = None) -> int:  # type: ignore[override]  # a stand-in
        self.calls.append("version")
        return 3


# -- the security lens's folds (#4997) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/orders", {"exchange_account_ids": str(ACCOUNT_B)}),
        ("/positions", {"exchange_account_ids": str(ACCOUNT_B)}),
        ("/orders/00000000-0000-0000-0000-000000000a04", {}),  # B's order: the audited 404
    ],
)
async def test_a_refusal_under_a_live_view_as_names_the_viewer_never_the_target(
    path: str, params: dict[str, str]
) -> None:
    """#4997 M1: the Owner viewing as the Manager reads as the Manager; the scope refusal's
    `rbac.denied` names the viewer, so the app's tripwire writes it rather than refusing it."""
    world = World(viewing=viewing_as("manager"))
    answer = await _get(world, path, "manager", **params)
    assert answer.status_code in (403, 404)
    [record] = world.audit.emitted
    assert record["action"] == "rbac.denied"
    assert record["actor_user_id"] == USERS["owner"] and record["actor_label"] == "user:owner"


async def test_get_order_with_a_history_past_its_caps_fails_closed() -> None:
    """#4997 m3: a timeline past `MAX_EVENT_PAGE` events or `MAX_ORDER_EXECUTIONS` fills is never
    served cut: `getOrder` answers 503, as diagnostics does."""
    world = World()
    a1 = world.store.orders[0][0]
    world.store.events[a1.id] = [event(n, a1.id, {}) for n in range(1, MAX_EVENT_PAGE + 2)]
    answer = await _get(world, f"/orders/{a1.id}", include_events="true")
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")
    world = World()
    world.store.fills += [
        (fill(1000 + n, ACCOUNT_A, a1.id, exec_id=f"X{n}"), None)
        for n in range(MAX_ORDER_EXECUTIONS + 1)
    ]
    answer = await _get(world, f"/orders/{a1.id}")
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")


def test_closed_pnl_the_venues_figure_is_net_of_both_fees_documented_shape() -> None:
    """#915 (the #848 notes): the venue's closed-PnL row, which the nightly backfill will serve,
    is net of the opening and the closing fees: its `closedPnl` sits below its exit value less
    its entry value. The fixture is documented-shape (docs-transcribed, exception #1778 A), not
    recorded; it pins the semantics, never a live capture."""
    import json as _json
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[5] / (
        "packages/fixtures/bybit/2026-10-05/rest/trading-closed-pnl.json"
    )
    [row] = _json.loads(fixture.read_text(encoding="utf-8"))["result"]["list"]
    gross = Decimal(row["cumExitValue"]) - Decimal(row["cumEntryValue"])  # a long's, Sell side
    traded = Decimal(row["cumEntryValue"]) + Decimal(row["cumExitValue"])
    # both legs' taker fee, 0.06 % of what was traded in and out, is what the row takes off
    assert gross - Decimal(row["closedPnl"]) == traded * Decimal("0.0006")
