"""`placeOrder`'s `202` body (E29-T04 #913 slice 3; `api.order_acceptance`): each answer validated
with jsonschema against 22 `OrderAcceptance`, and each object holding members of its own schema
only (SEC-S3D-03). The rows are the order store contract's (`submission_contract`)."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from candleviewer.accounts.trade_groups import TradeGroupWithLegs
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.order_acceptance import UNRESOLVED, first_acceptance, replayed_acceptance
from candleviewer.oms import submit
from candleviewer.oms.submit import RECONCILING, SubmitOutcome, WrittenRows, entry_order_id
from candleviewer.storage.repositories.orders import NewOrder, OrderRow
from tests.openapi_helpers import deref
from tests.unit.accounts.test_trade_groups import _group, _leg
from tests.unit.oms.submission_contract import SHA, entry, reduce_only

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_FORMATS = Draft202012Validator.FORMAT_CHECKER
USER = UUID("3a7c1e2d-5b40-4c6f-8e9a-1b2c3d4e5f60")
ACCOUNT = UUID("a1000000-0000-4000-8000-000000000001")
PROFILE = UUID("50000000-0000-4000-8000-000000000001")
OTHER = UUID("0c000000-0000-4000-8000-0000000000ff")  # a group no outcome here names
T0 = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def schema(name: str) -> Any:
    return deref(_SPEC, {"$ref": f"#/components/schemas/{name}"})


def validate(body: object) -> None:
    Draft202012Validator(schema("OrderAcceptance"), format_checker=_FORMATS).validate(body)


def stored(order: NewOrder, **over: Any) -> OrderRow:
    """`order`'s row as a read returns it."""
    read: dict[str, object] = {"leaves_qty": order.qty, "reject_code": None}
    read |= {"reject_message": None}
    read |= {"submit_attempts": 1, "idempotency_state": "acked", "created_ts": T0}
    read |= {"submitted_ts": T0, "last_reconciled_at": None}
    return OrderRow(**(asdict(order) | read | over))


def first_entry(chart: str = "submitted") -> SubmitOutcome:
    """An entry's first `202`, B1 having left its order in `chart`: the order named from its
    group, as the pipeline names it (`entry_order_id`)."""
    first, order = entry(USER, ACCOUNT, PROFILE)
    assert first.group is not None
    order = replace(order, id=entry_order_id(first.group.id))
    rows = WrittenRows(order, first.group, first.legs)
    return SubmitOutcome(202, first.anchor.id, order.id, first.group.id, chart, written=rows)


def first_reduce_only(chart: str = "submitted") -> SubmitOutcome:
    first, order = reduce_only(USER, ACCOUNT)
    return SubmitOutcome(202, first.anchor.id, order.id, None, chart, written=WrittenRows(order))


def read_entry(outcome: SubmitOutcome, **over: Any) -> tuple[OrderRow, TradeGroupWithLegs]:
    """The rows `outcome`'s entry holds now: its order as read, and its group and leg as the
    scoped read returns them."""
    written = outcome.written
    assert written is not None and written.group is not None
    group = _group(group_id=written.group.id, status="open", created_by=USER)
    leg_id = written.order.trade_group_leg_id
    leg = _leg(leg_id=leg_id, group_id=group.group_id, account_id=ACCOUNT, status="open")
    return stored(written.order, **over), TradeGroupWithLegs(group=group, legs=(leg,))


def replay_of(outcome: SubmitOutcome, chart: str = "filled") -> SubmitOutcome:
    """`outcome`'s repeat, as `OrderSubmission.answer_replay` answers it."""
    return replace(outcome, lifecycle=chart, replayed=True, written=None)


def _members(body: dict[str, Any]) -> list[tuple[str, set[str]]]:
    """Each object of `body` with the schema it is: the group, each leg and each order."""
    group, order = body["trade_group"], body["order"]
    legs = [] if group is None else group["legs"]
    orders = [order] if group is None else [o for leg in legs for o in leg["order_details"]]
    found = [("TradeGroup", set(group))] if group is not None else []
    found += [("TradeGroupLeg", set(leg)) for leg in legs]
    return found + [("Order", set(o)) for o in orders]


def test_a_first_entry_answer_holds_its_order_in_its_one_leg_in_the_state_b1_gave_it() -> None:
    outcome = first_entry("submitted")
    body = first_acceptance(outcome, "demo")
    validate(body)
    group = cast(dict[str, Any], body["trade_group"])
    (leg,) = group["legs"]
    (order,) = leg["order_details"]
    order_id = str(outcome.order_id)
    assert (body["order"], body["reconciling"], group["status"]) == (None, False, "submitting")
    assert (leg["status"], leg["orders"], order["id"]) == ("submitted", [order_id], order_id)
    assert (order["state"], order["lifecycle_state"]) == ("accepted", "submitted")
    assert order["trade_group_id"] == group["id"] == str(outcome.trade_group_id)
    assert group["intent"] == order["intent"] == "entry" and order["exchange_order_id"] is None


def test_a_first_reduce_only_answer_is_its_order_alone() -> None:
    body = first_acceptance(first_reduce_only("unknown"), "live")
    validate(body)
    order = cast(dict[str, Any], body["order"])
    assert (body["trade_group"], body["reconciling"]) == (None, True)
    assert (order["reduce_only"], order["environment"], order["trade_group_id"]) == (
        True, "live", None,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("chart", "reconciling", "leg"),
    [
        ("submitted", False, "submitted"),
        ("partially_filled", False, "submitted"),
        ("held", False, "pending"),
        ("unknown", True, "submitted"),
        ("submitting", True, "submitted"),
    ],
)
def test_a_first_answer_is_reconciling_while_b1_has_not_resolved_its_order(
    chart: str, reconciling: bool, leg: str
) -> None:
    """The leg as `_settle_group` leaves it: `submitted`, or as written for a `held` order."""
    body = first_acceptance(first_entry(chart), "demo")
    validate(body)
    group = cast(dict[str, Any], body["trade_group"])
    assert (body["reconciling"], group["legs"][0]["status"]) == (reconciling, leg)


@pytest.mark.parametrize("outcome", [first_entry(), first_reduce_only()], ids=["entry", "reduce"])
def test_each_object_holds_members_of_its_22_schema_only(outcome: SubmitOutcome) -> None:
    """SEC-S3D-03: never the request's fingerprint, the leg's profile snapshot or another column."""
    body = first_acceptance(outcome, "demo")
    for name, members in _members(body):
        assert members <= set(schema(name)["properties"]), name
    text = json.dumps(body)
    assert SHA not in text and "profile_snapshot" not in text and "client_body" not in text


def test_a_first_answer_is_rendered_from_its_written_rows_only() -> None:
    outcome = first_entry()
    for unwritten in (replace(outcome, written=None), replay_of(outcome)):
        with pytest.raises(ValueError, match="rows its persist wrote"):
            first_acceptance(unwritten, "demo")


def test_a_repeat_answers_its_entrys_rows_as_read_now() -> None:
    outcome = first_entry()
    row, found = read_entry(outcome, state="partially_filled", lifecycle_state="partially_filled")
    body = replayed_acceptance(row, found, replay_of(outcome, "partially_filled"), "demo")
    validate(body)
    group = cast(dict[str, Any], body["trade_group"])
    (leg,) = group["legs"]
    assert (body["reconciling"], group["status"], leg["status"]) == (False, "open", "open")
    assert (group["intent"], leg["order_details"][0]["lifecycle_state"]) == (
        "entry", "partially_filled",
    )  # fmt: skip
    for name, members in _members(body):
        assert members <= set(schema(name)["properties"]), name


def test_a_repeat_is_rendered_with_the_group_its_outcome_names_or_none() -> None:
    """An entry's repeat without its group would read as a reduce-only order; a reduce-only one's
    with a group, or an entry's with another, would answer a group the request did not create."""
    entry, reduce = first_entry(), first_reduce_only()
    row, found = read_entry(entry)
    another = TradeGroupWithLegs(group=_group(group_id=OTHER, created_by=USER), legs=())
    assert reduce.written is not None
    cases = [(row, None, entry), (stored(reduce.written.order), found, reduce)]
    for read, group, outcome in [*cases, (row, another, entry)]:
        with pytest.raises(ValueError, match="the group its outcome names"):
            replayed_acceptance(read, group, replay_of(outcome), "demo")


@pytest.mark.parametrize(
    ("read", "answered", "reconciling"),
    [("filled", "filled", False), ("unknown", "filled", True), ("filled", RECONCILING, True)],
)
def test_a_repeat_is_reconciling_while_its_order_is_unresolved_or_unread(
    read: str, answered: str, reconciling: bool
) -> None:
    """Either read may say so: the row now, or the pipeline's reconciled state."""
    outcome = first_reduce_only()
    written = outcome.written
    assert written is not None
    row = stored(written.order, state=read, lifecycle_state=read)  # both name these alike
    body = replayed_acceptance(row, None, replay_of(outcome, answered), "demo")
    validate(body)
    assert (body["reconciling"], body["trade_group"]) == (reconciling, None)


def test_the_unresolved_states_are_the_pipelines() -> None:
    assert UNRESOLVED == submit._UNRESOLVED
