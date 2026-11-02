"""The native-SL helper's own test (E35-T11 slice 3a): each assertion passes on a protected entry
and fails, naming its layer, on each doctored case: no stop, a stop that is no number, zero or
negative, a stop on the wrong side, no `entry_attach` row, no `sl.attached` record, a create
without its stop; a stop loosened or removed."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from candleviewer.exchange.base.fakes import FakeCall
from candleviewer.exchange.base.models import PlaceOrderRequest
from candleviewer.oms.ports import KeyedRecord, SubmitActor
from tests.rules.executor.native_sl import (
    assert_entry_carries_native_stop,
    assert_position_stop_untouched,
)
from tests.unit.oms import command_rig as cr

REFERENCE = Decimal("60000")
ROW = UUID(int=0x51)
OWNER = SubmitActor(user_id=UUID(int=0xA1), role="owner")


@dataclass(frozen=True)
class Entry:
    """An order row as the helper reads it: `NewOrder`'s own checks refuse a doctored stop."""

    id: UUID
    order_link_id: str
    side: str
    reduce_only: bool
    stop_loss: Decimal | None


@dataclass(frozen=True)
class Stop:
    id: UUID
    kind: str
    source: str
    order_id: UUID | None
    trigger_price: Decimal


def _world(**over: Any) -> dict[str, Any]:
    """A protected limit buy entry with its stop at 58000, recorded, audited and sent; `over`
    replaces any of its four parts."""
    order = cr.new_order()
    stop = Stop(ROW, "stop_loss", "entry_attach", order.id, cr.STOP)
    record = KeyedRecord(
        "sl.attached", str(ROW), cr.ACCOUNT, "recorded_stop", ROW, "success", "info",
        "entry_attach", OWNER.user_id, {}, None, OWNER,
    )  # fmt: skip
    create = PlaceOrderRequest(
        account=cr.ref(), symbol=order.symbol, side="buy", order_type="limit", qty=order.qty,
        price=order.price, order_link_id=order.order_link_id, stop_loss=order.stop_loss,
    )  # fmt: skip
    call = FakeCall("place_order", cr.ACCOUNT, create, "entry")
    return {"order": order, "stops": [stop], "records": [record], "calls": [call]} | over


def _check(world: dict[str, Any]) -> None:
    assert_entry_carries_native_stop(
        world["order"], reference_price=REFERENCE, stops=world["stops"],
        records=world["records"], calls=world["calls"],
    )  # fmt: skip


def _order(**over: Any) -> Entry:
    new = cr.new_order()
    return replace(
        Entry(new.id, new.order_link_id, new.side, new.reduce_only, new.stop_loss), **over
    )


def test_a_protected_entry_passes() -> None:
    _check(_world())
    above = Decimal("62000")
    sell = _order(side="Sell", stop_loss=above)
    world = _world(order=sell, stops=[Stop(ROW, "stop_loss", "entry_attach", sell.id, above)])
    create = world["calls"][0].request.model_copy(
        update={"side": "sell", "stop_loss": sell.stop_loss}
    )
    world["calls"] = [FakeCall("place_batch", cr.ACCOUNT, (create,), "entry")]
    _check(world)


_DOCTORED: dict[str, tuple[dict[str, Any], str]] = {
    "reduce-only": ({"order": _order(reduce_only=True)}, "not reduce-only"),
    "no-stop": ({"order": _order(stop_loss=None)}, "finite stop_loss above zero"),
    "nan-stop": ({"order": _order(stop_loss=Decimal("NaN"))}, "finite stop_loss above zero"),
    "zero-stop": ({"order": _order(stop_loss=Decimal(0))}, "finite stop_loss above zero"),
    "negative-stop": ({"order": _order(stop_loss=Decimal("-1"))}, "finite stop_loss above zero"),
    "wrong-side": ({"order": _order(stop_loss=Decimal("61000"))}, "protective side"),
    "no-entry-attach-row": ({"stops": []}, "entry_attach row"),
    "another-orders-row": (
        {"stops": [Stop(ROW, "stop_loss", "entry_attach", UUID(int=9), cr.STOP)]},
        "entry_attach row",
    ),
    "a-row-at-another-trigger": (
        {"stops": [Stop(ROW, "stop_loss", "entry_attach", None, Decimal("57000"))]},
        "entry_attach row",
    ),
    "no-sl-attached-record": ({"records": []}, "sl.attached record"),
    "no-create": ({"calls": []}, "carried its native stop"),
}


@pytest.mark.parametrize(("doctored", "names"), list(_DOCTORED.values()), ids=list(_DOCTORED))
def test_each_layer_of_an_entrys_stop_is_checked(doctored: dict[str, Any], names: str) -> None:
    with pytest.raises(AssertionError, match=names):
        _check(_world(**doctored))


def test_a_create_sent_without_its_stop_fails() -> None:
    world = _world()
    bare = world["calls"][0].request.model_copy(update={"stop_loss": None})
    world["calls"] = [*world["calls"], FakeCall("place_order", cr.ACCOUNT, bare, "entry")]
    with pytest.raises(AssertionError, match="carried its native stop"):
        _check(world)


@pytest.mark.parametrize(
    ("side", "before", "after"),
    [("Buy", "58000", "58000"), ("Buy", "58000", "58500"), ("sell", "62000", "61500"),
     ("Sell", None, None), ("buy", None, "57000")],
)  # fmt: skip
def test_a_stop_kept_or_tightened_is_untouched(side: Any, before: Any, after: Any) -> None:
    held = (None if before is None else Decimal(before), None if after is None else Decimal(after))
    assert_position_stop_untouched(side, before=held[0], after=held[1])


@pytest.mark.parametrize(
    ("side", "after", "names"),
    [("Buy", None, "removed"), ("Buy", "57500", "loosened"), ("Sell", "62500", "loosened")],
)
def test_a_stop_loosened_or_removed_fails(side: Any, after: str | None, names: str) -> None:
    before = Decimal("58000") if side == "Buy" else Decimal("62000")
    with pytest.raises(AssertionError, match=names):
        assert_position_stop_untouched(
            side, before=before, after=None if after is None else Decimal(after)
        )
