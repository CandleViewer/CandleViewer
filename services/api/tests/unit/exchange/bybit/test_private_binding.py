"""#3963 scenario "A private push reaches the OMS only for its own account" (SR-E29-02), at the
parser: every row takes the stream's account, and a row carrying one of our ids of another
account or environment is dropped and counted in `bybit_private_rows_refused_total`, never
delivered as the stream's account's and never raised (24 §14.2 rules 11 to 13). Rows are derived
in-test from the docs-transcribed frames; ids come from the generator (`_trading.link`). The
stream's own tests prove it again with two streams open, B's push arriving on A's socket.
"""

from __future__ import annotations

import pytest

from candleviewer.domain.order_link import ext_key
from candleviewer.domain.primitives import Environment
from candleviewer.exchange.base.models import Execution, FastExecution, Order, PrivateEvent
from candleviewer.exchange.bybit import private_parse as pp
from candleviewer.exchange.bybit.metrics import bybit_private_rows_refused_total
from tests.unit.exchange.bybit._private import linear_order, push, row
from tests.unit.exchange.bybit._trading import ACCOUNT_A, ACCOUNT_B, account, link

NOW_US = 1_790_000_000_000_000
#: The topic of each linked row kind, and the row derived from its documented frame.
LINKED = {
    "order": lambda **f: push("order.linear", linear_order(**f)),
    "execution": lambda **f: push("execution.linear", row("execution") | f),
    "execution.fast": lambda **f: push("execution.fast.linear", row("execution-fast") | f),
}


def _counted(topic: str, reason: str) -> float:
    value: float = bybit_private_rows_refused_total.labels(topic=topic, reason=reason)._value.get()
    return value


def _read(text: str, *, environment: Environment = "demo") -> tuple[PrivateEvent, ...]:
    pushed = pp.classify(text)
    assert isinstance(pushed, pp.Push)
    return pp.read_push(pushed, account(environment=environment), now_us=NOW_US)


def _linked(event: PrivateEvent) -> Order | Execution | FastExecution:
    """The payload of an order or execution event, which names its order."""
    assert isinstance(event.payload, Order | Execution | FastExecution)
    return event.payload


@pytest.mark.parametrize("topic", sorted(LINKED))
def test_a_row_naming_another_account_never_reaches_this_streams_account(topic: str) -> None:
    """A push carrying account B's order on account A's stream is dropped and counted."""
    before = _counted(topic, "account")
    assert _read(LINKED[topic](orderLinkId=link(ACCOUNT_B))) == ()
    assert _counted(topic, "account") == before + 1


@pytest.mark.parametrize("topic", sorted(LINKED))
def test_a_row_naming_another_environment_is_dropped_and_counted(topic: str) -> None:
    before = _counted(topic, "environment")
    assert _read(LINKED[topic](orderLinkId=link(ACCOUNT_A, environment="live"))) == ()
    assert _counted(topic, "environment") == before + 1


@pytest.mark.parametrize("topic", sorted(LINKED))
def test_a_row_of_this_account_keeps_its_id_and_takes_the_streams_account(topic: str) -> None:
    ours = link(ACCOUNT_A, seq=3)
    [event] = _read(LINKED[topic](orderLinkId=ours))
    assert event.account_id == event.payload.account_id == ACCOUNT_A
    assert _linked(event).order_link_id == ours


@pytest.mark.parametrize("topic", sorted(LINKED))
@pytest.mark.parametrize("foreign", ["", "test-00001", "x" * 36])
def test_an_empty_or_foreign_id_is_kept_as_the_orders_ext_key(topic: str, foreign: str) -> None:
    """24 §14.2 rule 11: the id names no account of ours, so it binds nothing and is kept."""
    [event] = _read(LINKED[topic](orderLinkId=foreign))
    payload = _linked(event)
    assert payload.order_link_id == ext_key(payload.exchange_order_id)


def test_a_position_or_wallet_row_takes_the_streams_account() -> None:
    """They carry no id of ours to check: their account is the stream's, never the payload's."""
    [event] = _read(push("position.linear", row("position")))
    assert event.account_id == event.payload.account_id == ACCOUNT_A


def test_the_same_push_on_bs_stream_is_bs_and_on_as_is_dropped() -> None:
    text = LINKED["order"](orderLinkId=link(ACCOUNT_B))
    pushed = pp.classify(text)
    assert isinstance(pushed, pp.Push)
    [event] = pp.read_push(pushed, account(ACCOUNT_B), now_us=NOW_US)
    assert event.account_id == ACCOUNT_B
    assert pp.read_push(pushed, account(ACCOUNT_A), now_us=NOW_US) == ()
