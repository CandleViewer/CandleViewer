"""The private stream's frames as the Bybit v5 documentation shows them (G-8b, #3963, ruling 11).

Each `ws/private-*.jsonl` file is one documented frame, listed in the corpus manifest with its
`source_url` and `source_ref` (`test_contract_trading_drift.py` pins the listing and compares
each with E29-K01's recordings). These tests prove the stream's parser reads every documented
frame, field for field, with no field left unknown (`cv_bybit_unknown_fields_total`, #2877
ruling R7), and that the linear stream drops the documented examples of another product. Where
the documented sample is another product's (the option order, the BTC wallet row) the linear
USDT row is derived in-test (`_private.py`), never presented as evidence.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from candleviewer.exchange.base.models import Execution, FastExecution, Order, Position, Wallet
from candleviewer.exchange.bybit import private_parse as pp
from candleviewer.exchange.bybit import trading_parse as tp
from candleviewer.exchange.bybit.metrics import cv_bybit_unknown_fields_total
from tests._corpus import frames
from tests.unit.exchange.bybit._private import linear_order, push, usdt_wallet
from tests.unit.exchange.bybit._trading import account

NOW_US = 1_790_000_000_000_000
#: The documented replies and what each reads as.
REPLIES = {
    "ws/private-auth-ok.jsonl": pp.Reply("auth", True),
    "ws/private-subscribe-ok.jsonl": pp.Reply("subscribe", True),
    "ws/private-pong.jsonl": pp.Reply("pong", None),
}
#: The documented pushes and the payload each yields as it is (`None`: another product's, or
#: no USDT row, so the linear stream delivers nothing of it).
PUSHES: dict[str, type | None] = {
    "ws/private-order.jsonl": None,
    "ws/private-execution.jsonl": Execution,
    "ws/private-execution-fast.jsonl": FastExecution,
    "ws/private-position.jsonl": Position,
    "ws/private-wallet.jsonl": None,
}


def _counts() -> dict[str, float]:
    labels = tp.MODEL_LABELS | pp.PUSH_MODEL_LABELS
    return {m: cv_bybit_unknown_fields_total.labels(model=m)._value.get() for m in labels}


@pytest.fixture
def no_unknown_fields() -> Iterator[None]:
    """Every field of a documented frame is known to its model: none counted as drift."""
    before = _counts()
    yield
    assert _counts() == before


@pytest.mark.parametrize("path", sorted(REPLIES))
def test_every_documented_reply_reads_as_its_op(path: str) -> None:
    [frame] = frames(path)
    assert pp.classify(frame) == REPLIES[path]


@pytest.mark.usefixtures("no_unknown_fields")
@pytest.mark.parametrize("path", sorted(PUSHES))
def test_every_documented_push_is_read_field_for_field(path: str) -> None:
    [frame] = frames(path)
    pushed = pp.classify(frame)
    assert isinstance(pushed, pp.Push)
    events = pp.read_push(pushed, account(), now_us=NOW_US)
    expected = PUSHES[path]
    assert [type(e.payload) for e in events] == ([] if expected is None else [expected])


@pytest.mark.usefixtures("no_unknown_fields")
def test_an_order_push_carries_the_venues_update_time_not_the_frames() -> None:
    """24 Sec.8.12: B1's `updated_time` is the venue's own time of the order's last change, so the
    row keeps `updatedTime`, apart from the frame's creation time and from `createdTime`."""
    pushed = pp.classify(push("order", linear_order()))
    assert isinstance(pushed, pp.Push)
    [event] = pp.read_push(pushed, account(), now_us=NOW_US)
    assert isinstance(event.payload, Order)
    assert (event.payload.updated_at, event.payload.created_at) == (
        1_672_364_262_457_000,
        1_672_364_262_444_000,
    )
    assert event.ts_event == 1_672_364_262_474_000


@pytest.mark.usefixtures("no_unknown_fields")
def test_the_documented_order_and_wallet_rows_read_as_linear_usdt_ones() -> None:
    """Derived in-test: the option order as a linear USDT order, the BTC wallet row as USDT's."""
    for text, payload in (
        (push("order", linear_order()), Order),
        (push("wallet", usdt_wallet()), Wallet),
    ):
        pushed = pp.classify(text)
        assert isinstance(pushed, pp.Push)
        [event] = pp.read_push(pushed, account(), now_us=NOW_US)
        assert type(event.payload) is payload
