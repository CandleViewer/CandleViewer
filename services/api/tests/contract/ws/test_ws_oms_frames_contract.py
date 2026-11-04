"""E29-Q02 (#1147), slice C3: the OMS's private payloads, swept against 23-ws-protocol.md Sec.15.

`orders`, `executions` and `positions` as `ws_wiring.oms_topics` serves them on the real `/ws`
router (the neighbour `test_ws_oms_topics_contract` wires it; every row runs under both
subprotocols), and `wallet` as the accounts module serves it (`test_wallet_topic_contract`'s
world). Each frame goes through `_harness.check_schema`, so a failure names its JSON path, the
schema and its section of 23, and its envelope is checked too; the payload must be what the
producer built, whole.

- `orders`: every `change` kind a committed step can carry, and a step with none, in every state a
  row is stored in (the 17 `ORDER_STATE_OF` pairs, and a row whose chart state is not recorded yet:
  `lifecycle_state: null`). A step that leaves the open set carries its id in `removed`, and an
  `open_only` subscriber gets that removal alone (Sec.6.2.3).
- `executions` and `positions`: each variant a row can take (type, side, hedge-mode index, a
  Partial-mode stop, absent amounts, the numeric(38,18) bounds), an empty snapshot, a flat position
  as a removal, and the merged and split `positions` windows (Sec.8.2).
- `wallet`: each (state, reason) the health monitor derives (AV-05, AV-06) and a balance that turns
  stale (AV-07).
- the vocabularies: what a producer can say is what the schema declares, both ways.
- AC2, "contract drift fails the build": a renamed or dropped member fails the check naming it,
  on a payload and on the wire.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any, Final, get_args
from uuid import UUID

import pytest

from candleviewer.accounts.health import HealthReason, HealthState
from candleviewer.oms import ws_topics as wt
from candleviewer.settings import ACCOUNT_DOWN_MAX_S, WALLET_STALE_S
from candleviewer.storage.repositories.orders import OPEN_STATES, ORDER_STATE_OF, OrderEventKind
from tests.contract.ws import _harness as h
from tests.contract.ws.test_ws_oms_topics_contract import subscribed, wired
from tests.unit.accounts._fakes import ACC
from tests.unit.accounts._wallet_ws import WalletWorld, owner
from tests.unit.oms.test_ws_topics import new_fill, order, position, step, stored
from tests.unit.ws._seq_support import ACC_A, ACC_B

ENVELOPE, ORDERS, EXECUTIONS, POSITIONS, WALLET = (
    f"cv://ws/v1/{name}.schema.json"
    for name in ("envelope", "orders", "executions", "positions", "wallet")
)
#: Past a `positions` window (100 ms), so that the next change leaves at once.
WINDOW_S: Final = 0.2
HIGH: Final = Decimal("99999999999999999999.999999999999999999")  # numeric(38,18)'s largest
LOW: Final = Decimal("0.000000000000000001")  # its smallest step
NEG_HIGH: Final = Decimal("-99999999999999999999.999999999999999999")  # and its most negative


def conforms(schema: str, frame: dict[str, Any], what: str) -> dict[str, Any]:
    """The frame against the envelope schema, and its payload (returned) against `schema`; a
    failure names `what`."""
    h.check_schema(ENVELOPE, frame, what)
    body = h.structured_of(frame)
    h.check_schema(schema, body, what)
    return body


def sent(world: h.World, topics: wt.OmsTopics[Any], *changes: wt.Change) -> None:
    """A's changes, one call each, through the production adapter on the serving loop."""
    for change in changes:
        world.call(topics.published, ACC_A, [change])


def member_enum(schema: str, collection: str, name: str) -> set[Any]:
    """The `enum` of `name` in the items of `collection` (23 Sec.15)."""
    items = h.SCHEMAS[schema]["properties"][collection]["items"]
    return set(items["properties"][name]["enum"])


# -- orders ---------------------------------------------------------------------------------------

#: What a stored order carries: 24 Sec.8.2's `state` of each B1 chart state, and a row whose chart
#: state is not recorded (23 Sec.15.1: `lifecycle_state` null).
PAIRS: Final = [*((state, chart) for chart, state in ORDER_STATE_OF.items()), ("accepted", None)]


def emitted_changes() -> set[str | None]:
    """The `change` `change_of` gives each event kind a step can have, as a first row and as a step
    out of `accepted` into `accepted`, `cancelled` and `triggered` (it tells the pushes apart)."""
    shapes = ((None, "accepted"), ("accepted", "accepted"), ("accepted", "cancelled"),
              ("accepted", "triggered"))  # fmt: skip
    kinds = get_args(OrderEventKind)
    return {wt.change_of(step(order(state=s), k, left)) for k in kinds for left, s in shapes}


def order_change(n: int, state: str, chart: str | None, change: str | None) -> wt.Change:
    """A's order `n` as the step publisher frames it: closed when its `state` is not open."""
    code = "PRICE_OUT_OF_BOUNDS" if state == "rejected" else None  # a reject names its code
    row = order(n, account=ACC_A, state=state, lifecycle_state=chart, reject_code=code)
    item = wt.order_item(row, environment="demo", stamp=100 + n, change=change)
    return wt.Change("orders", item, str(row.id), row.symbol, 100 + n, state not in OPEN_STATES)


@pytest.mark.parametrize("change", sorted(emitted_changes(), key=str), ids=str)
def test_orders_deltas_of_every_change_kind_conform_in_every_stored_state(
    change: str | None,
) -> None:
    """E29-TC-450, E29-TC-751: each `change` kind (and a step with none) x each state a row is
    stored in, as a delta of the real topic on the socket: valid against `orders.schema.json`, the
    payload what the producer built (its `removed` carrying the id when the state is not open),
    `s` one after the last (Sec.6.2.3, Sec.15.1)."""
    world, topics = wired()
    with h.connect(world) as c:
        subscribed(c, "orders")
        last = c.next_of("snap")["s"]
        for n, (state, chart) in enumerate(PAIRS, start=2):
            moved = order_change(n, state, chart, change)
            sent(world, topics, moved)
            frame = c.next_of_raw("d")
            what = f"d orders change={change} state={state} lifecycle_state={chart}"
            removed = {"removed": [moved.key]} if moved.closed else {}
            assert conforms(ORDERS, frame, what) == {"orders": [moved.item], **removed}, what
            assert frame["s"] == last + 1, what
            last = frame["s"]


def test_orders_an_open_only_subscriber_gets_a_closing_step_as_a_removal_alone() -> None:
    """E29-TC-751: a step out of the open set (into `held` and `untracked` too, which are not
    open) is `{"orders": [], "removed": [id]}` for an `open_only: true` subscription (Sec.6.2.3)."""
    world, topics = wired()
    closing = [pair for pair in PAIRS if pair[0] not in OPEN_STATES]
    with h.connect(world) as c:
        c.sub({"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A)], "open_only": True}})
        c.next_of("snap")
        for n, (state, chart) in enumerate(closing, start=2):
            sent(world, topics, order_change(n, state, chart, "cancel"))
            what = f"d orders open_only state={state}"
            body = conforms(ORDERS, c.next_of_raw("d"), what)
            assert body == {"orders": [], "removed": [str(UUID(int=n))]}, what


@pytest.mark.parametrize("family", wt.FAMILIES)
def test_an_account_with_no_rows_gets_an_empty_snapshot_that_conforms(family: str) -> None:
    """E29-TC-751: the snapshot of an account holding no order, fill or position is `{family: []}`
    (Sec.6.2.3), valid against its schema."""
    world, _ = wired()
    with h.connect(world) as c:
        subscribed(c, family, account=ACC_B)
        body = conforms(f"cv://ws/v1/{family}.schema.json", c.next_of_raw("snap"), family)
    assert body == {family: []}


# -- executions and positions ---------------------------------------------------------------------

FILLS: Final[dict[str, dict[str, Any]]] = {
    **{f"{kind}-{side}": {"exec_type": kind, "side": side}
       for kind in sorted(wt.WS_EXEC_TYPES) for side in ("Buy", "Sell")},
    "maker-rebate-with-pnl": {"is_maker": True, "fee_rate": Decimal("-0.00025"),
                              "closed_pnl": Decimal("-1.5")},
    "no-fee-rate-no-pnl": {"fee_rate": None, "closed_pnl": None},
    "paper": {"is_paper": True},
    "amount-bounds": {"exec_qty": LOW, "exec_price": HIGH, "exec_value": HIGH},
}  # fmt: skip
#: The optional amounts a position row may lack, which its item then leaves out or sends null.
AMOUNTS: Final = ("avg_price", "mark_price", "leverage", "position_value", "unrealised_pnl",
                  "liq_price", "stop_loss")  # fmt: skip
POSITIONS_BY_VARIANT: Final[dict[str, dict[str, Any]]] = {
    "long": {},
    "short": {"side": "Sell"},
    "hedge-long": {"position_idx": 1},
    "hedge-short": {"position_idx": 2, "side": "Sell"},
    "partial-mode-stop": {"tpsl_mode": "Partial", "take_profit": Decimal(65000)},
    "row-without-amounts": dict.fromkeys(AMOUNTS),
    "amount-bounds": {"size": LOW, "unrealised_pnl": NEG_HIGH, "liq_price": HIGH},
    "flat": {"size": "0", "side": "None"},
}


@pytest.mark.parametrize("variant", FILLS)
def test_executions_each_variant_of_a_fill_conforms_as_a_delta(variant: str) -> None:
    """E29-TC-751: a fill of each type and side, with and without its optional members, a paper
    fill and one at the numeric bounds: valid against `executions.schema.json` and unchanged
    (Sec.15.3)."""
    world, topics = wired()
    row = stored(new_fill(), **FILLS[variant])
    item = wt.execution_item(row, environment="demo")
    assert item is not None
    with h.connect(world) as c:
        subscribed(c, "executions")
        c.next_of("snap")
        sent(world, topics, wt.Change("executions", item, item["id"], row.symbol, 10))
        frame = c.next_of_raw("d")
    assert conforms(EXECUTIONS, frame, f"d executions {variant}") == {"executions": [item]}


def position_change(stamp: int, **over: Any) -> wt.Change:
    """A's position as the store applied it, framed as the step publisher frames it."""
    row = position(account=ACC_A, **over)
    item = wt.position_item(row, environment="demo", stamp=stamp)
    return wt.Change("positions", item, item["id"], row.symbol, stamp, wt.is_flat(row))


@pytest.mark.parametrize("variant", POSITIONS_BY_VARIANT)
def test_positions_each_variant_of_a_row_conforms_as_a_delta(variant: str) -> None:
    """E29-TC-751, E29-TC-753: a long, a short, each hedge-mode index, a Partial-mode stop, a row
    lacking its amounts and one at the numeric bounds validate against `positions.schema.json` and
    arrive unchanged; a flat position is `{"positions": [], "removed": [id]}` (Sec.15.2)."""
    world, topics = wired()
    moved = position_change(10, **POSITIONS_BY_VARIANT[variant])
    with h.connect(world) as c:
        subscribed(c, "positions")
        c.next_of("snap")
        sent(world, topics, moved)
        frame = c.next_of_raw("d")
    flat = {"positions": [], "removed": [moved.key]}
    assert conforms(POSITIONS, frame, f"d positions {variant}") == (
        flat if moved.closed else {"positions": [moved.item]}
    )


def test_positions_the_updates_of_one_window_leave_as_one_merged_frame() -> None:
    """Sec.8.2: the first update leaves at once and opens a window; three more in it leave as one
    frame at its close, the latest item with `coalesced: true` and `coalesced_count: 3`."""
    world, topics = wired()
    with h.connect(world) as c:
        subscribed(c, "positions")
        c.next_of("snap")
        sent(world, topics, position_change(10))
        conforms(POSITIONS, c.next_of_raw("d"), "d positions first update")
        sent(
            world,
            topics,
            *(position_change(s, size=z) for s, z in ((11, "0.5"), (12, "0.6"), (13, "0.7"))),
        )
        world.clock.now += WINDOW_S
        body = conforms(POSITIONS, c.next_of_raw("d"), "d positions merged window")
    assert [(p["size"], p["updated_at_ms"]) for p in body["positions"]] == [("0.7", 13)]
    assert (body["coalesced"], body["coalesced_count"]) == (True, 3)


def test_positions_a_removal_and_a_re_open_of_one_window_leave_as_two_frames() -> None:
    """Sec.8.2: a position removed and upserted again in one window is closed before the upsert,
    so the removal and the re-open reach the client in two frames, the removal first."""
    world, topics = wired()
    reopened = position_change(22, size="0.8")
    with h.connect(world) as c:
        subscribed(c, "positions")
        c.next_of("snap")
        sent(world, topics, position_change(10))
        c.next_of_raw("d")
        sent(world, topics, position_change(21, size="0", side="None"), reopened)
        world.clock.now += WINDOW_S
        frames = [c.next_of_raw("d"), c.next_of_raw("d")]
    bodies = [conforms(POSITIONS, f, f"d positions split #{n}") for n, f in enumerate(frames)]
    assert bodies == [{"positions": [], "removed": [reopened.key]}, {"positions": [reopened.item]}]
    assert frames[1]["s"] == frames[0]["s"] + 1


# -- wallet ---------------------------------------------------------------------------------------

_NEVER: Final = UUID(int=3)  # monitored, never given evidence (`test_wallet_topic_contract`'s)
#: AV-05, AV-06: the account, the evidence its monitor gets, the seconds the clock then moves, and
#: the (state, reason) `AccountHealthMonitor` derives for it. `ws_silent` is a `degraded` reason
#: there (AV-06 lists it under `down`); `healthy` is the control.
HEALTH: Final[dict[str, tuple[UUID, tuple[str, ...], float, tuple[str, str]]]] = {
    "healthy": (ACC, (), 0, ("healthy", "ws_heartbeat")),
    "AV-05-ws-silent": (ACC, ("ws_dropped",), 0, ("degraded", "ws_silent")),
    "AV-05-rest-only": (ACC, ("ws_dropped", "rest_ok"), 0, ("degraded", "rest_only")),
    "AV-06-no-success": (ACC, (), ACCOUNT_DOWN_MAX_S + 1, ("down", "no_success")),
    "AV-06-never-connected": (_NEVER, (), 0, ("down", "never_connected")),
}


@pytest.mark.parametrize("case", HEALTH)
def test_wallet_health_reports_the_state_and_reason_the_monitor_derives(case: str) -> None:
    """E29-TC-351 (AV-05, AV-06): the account's health entry, in the snapshot and in the delta of
    its transition, validates against `wallet.schema.json` with the state and reason the evidence
    gives it, `rest_only` true exactly while `degraded`, `heartbeat_age_ms` null only for an
    account never heard from (Sec.15.4)."""
    account, evidence, wait_s, (state, reason) = HEALTH[case]
    world = WalletWorld()
    world.monitor.track(_NEVER)
    world.wallets.track(_NEVER)
    conn = world.conn(owner())
    for name in evidence:
        getattr(world.monitor, name)(account)
    world.clock.advance(wait_s)
    conn.sub(account)
    world.topic.health_changed(account)
    bodies = [conforms(WALLET, f, f"{f['t']} wallet {case}") for f in conn.frames]
    entries = [entry for body in bodies for entry in body["health"]]
    assert [f["t"] for f in conn.frames] == ["snap", "d"]
    assert [(e["state"], e["reason"], e["rest_only"]) for e in entries] == [
        (state, reason, state == "degraded")
    ] * 2
    assert [e["heartbeat_age_ms"] is None for e in entries] == [account == _NEVER] * 2


def test_wallet_a_balance_turns_stale_and_says_since_when() -> None:
    """E29-TC-012 (AV-07): a balance sent fresh (`stale: false`, `stale_since_ms: null`) goes out
    once more past the stale window (`stale: true`, `stale_since_ms` the refresh plus the window)
    while the private stream is down and REST answers: the health delta says `rest_only`."""
    world = WalletWorld()
    conn = world.conn(owner())
    conn.sub(ACC)
    world.topic.balance_refreshed(ACC)
    world.monitor.ws_dropped(ACC)
    world.monitor.rest_ok(ACC)
    world.clock.advance(WALLET_STALE_S + 1)
    world.topic.stale_check()
    world.topic.health_changed(ACC)
    bodies = [conforms(WALLET, f, f"{f['t']} wallet #{n}") for n, f in enumerate(conn.frames)]
    [fresh], [stale] = bodies[1]["balances"], bodies[2]["balances"]
    assert (fresh["stale"], fresh["stale_since_ms"]) == (False, None)
    assert (stale["stale"], stale["stale_since_ms"]) == (
        True, stale["updated_at_ms"] + int(WALLET_STALE_S) * 1000
    )  # fmt: skip
    assert [(e["state"], e["reason"]) for e in bodies[3]["health"]] == [("degraded", "rest_only")]


# -- the vocabularies -----------------------------------------------------------------------------


def sides() -> set[str]:
    """The `side` the item builder gives each variant of a position row."""
    return {position_change(1, **over).item["side"] for over in POSITIONS_BY_VARIANT.values()}


VOCABULARIES: Final[dict[str, tuple[set[Any], set[Any]]]] = {
    "orders.state": (member_enum(ORDERS, "orders", "state"), set(ORDER_STATE_OF.values())),
    "orders.lifecycle_state": (member_enum(ORDERS, "orders", "lifecycle_state"),
                               {*ORDER_STATE_OF, None}),
    "orders.change": (member_enum(ORDERS, "orders", "change"), emitted_changes() - {None}),
    "executions.exec_type": (member_enum(EXECUTIONS, "executions", "exec_type"),
                             set(wt.WS_EXEC_TYPES)),
    "positions.side": (member_enum(POSITIONS, "positions", "side"), sides()),
    "wallet.health.state": (member_enum(WALLET, "health", "state"),
                            {state.value for state in HealthState}),
    "wallet.health.reason": (member_enum(WALLET, "health", "reason"),
                             set(get_args(HealthReason))),
}  # fmt: skip


#: Values a schema declares before any producer sends them (contract first, C-6.1), by member: a
#: contract change that does so names each here with its ticket. None today.
UNSENT: Final[dict[str, set[Any]]] = {}


@pytest.mark.parametrize("member", VOCABULARIES)
def test_a_members_values_are_the_schemas_and_the_producers_both_ways(member: str) -> None:
    """E29-TC-450, E29-TC-751, E29-TC-351: what a producer can say of a member is what the schema
    declares for it: no value the schema refuses, and none it declares that no producer sends but
    those `UNSENT` names. The orders and executions sweeps above take their values from the
    producers, so a value added there is swept as well."""
    declared, emitted = VOCABULARIES[member]
    assert sorted(emitted - declared, key=str) == [], f"{member}: sent, never declared"
    assert declared - emitted == UNSENT.get(member, set()), f"{member}: declared, never sent"


# -- AC2: contract drift fails the build ----------------------------------------------------------


def valid_payloads() -> dict[str, dict[str, Any]]:
    """One payload of each private topic, as its producer builds it."""
    conn = WalletWorld().conn(owner())
    conn.sub(ACC)
    execution = wt.execution_item(stored(new_fill()), environment="demo")
    return {
        ORDERS: {"orders": [wt.order_item(order(), environment="demo", stamp=1, change="ack")]},
        EXECUTIONS: {"executions": [execution]},
        POSITIONS: {"positions": [wt.position_item(position(), environment="demo", stamp=1)]},
        WALLET: conn.frames[0]["p"],
    }


#: Breaking changes seeded into a payload: schema, the list holding the item, the edit and what the
#: failure must name (the item's JSON path, the member, the section of 23).
DRIFTS: Final[dict[str, tuple[str, str, Callable[[dict[str, Any]], object], tuple[str, ...]]]] = {
    "orders-state-renamed": (ORDERS, "orders", lambda i: i.update(status=i.pop("state")),
                             ("$.orders[0]", "'state' is a required property",
                              "'status' was unexpected", "§15.1 OrderUpdate")),
    "orders-updated_at_ms-dropped": (ORDERS, "orders", lambda i: i.pop("updated_at_ms"),
                                     ("$.orders[0]", "'updated_at_ms' is a required property")),
    "executions-exec_price-renamed": (EXECUTIONS, "executions",
                                      lambda i: i.update(price=i.pop("exec_price")),
                                      ("$.executions[0]", "'exec_price' is a required property",
                                       "'price' was unexpected", "§15.3 ExecutionUpdate")),
    "positions-size-a-json-number": (POSITIONS, "positions", lambda i: i.update(size=0.4),
                                     ("$.positions[0].size", "0.4 is not of type 'string'",
                                      "§15.2 PositionUpdate")),
    "wallet-health-state-renamed": (WALLET, "health", lambda i: i.update(status=i.pop("state")),
                                    ("$.health[0]", "'state' is a required property",
                                     "'status' was unexpected", "§15.4 WalletUpdate")),
}  # fmt: skip


@pytest.mark.parametrize("drift", DRIFTS)
def test_a_payload_with_a_renamed_or_dropped_member_fails_the_check_naming_it(drift: str) -> None:
    """AC2 (E29-TC-751, E29-TC-012): each private payload, valid as its producer builds it, fails
    `check_schema` once a member is renamed, dropped or sent as the wrong type, the failure naming
    the item's JSON path, the member and the section of 23 that defines the schema."""
    schema, collection, edit, named = DRIFTS[drift]
    payload = valid_payloads()[schema]
    h.check_schema(schema, payload, "the payload before the edit")
    edit(payload[collection][0])
    with pytest.raises(AssertionError) as failed:
        h.check_schema(schema, payload, f"d {collection}")
    assert [part for part in named if part not in str(failed.value)] == []


def test_a_producer_that_renames_a_member_fails_on_the_first_frame_that_carries_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2 on the wire, the twin of E12-Q04's `test_contract_bars_a_breaking_change_fails_ci`: an
    `order_item` that sends `status` for `state` fails the harness on the first delta that carries
    an order, on either wire, naming the member, the topic and 23's section; the snapshot before it
    passes."""
    real = wt.order_item

    def renamed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        item = real(*args, **kwargs)
        item["status"] = item.pop("state")
        return item

    world, topics = wired()
    with h.connect(world) as c:
        subscribed(c, "orders")
        c.next_of("snap")
        monkeypatch.setattr(wt, "order_item", renamed)
        sent(world, topics, order_change(2, "accepted", "submitted", "ack"))
        with pytest.raises(AssertionError) as failed:
            c.next_of("d")
    named = ("$.orders[0]: 'state' is a required property", "'status' was unexpected", "d orders",
             "23-ws-protocol.md §15.1 OrderUpdate")  # fmt: skip
    assert [part for part in named if part not in str(failed.value)] == []
