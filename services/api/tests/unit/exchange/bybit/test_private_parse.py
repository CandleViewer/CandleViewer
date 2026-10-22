"""Reading the private stream's frames (G-8b, #3963; 24 §14.2 rule 13), on the docs-transcribed
corpus frames and rows derived from them in-test (`_private.py`).

A frame is a reply or a push of a subscribed topic, else rejected whole; a push's rows become
events of the stream's account, with G-8's mappers, and a row the stream may not deliver is
dropped and counted, never raised; a row it cannot read rejects its frame, so no event of a
frame is yielded unless all of it was read.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from candleviewer.exchange.base.boundary import exchange_errors_total
from candleviewer.exchange.base.models import Execution, FastExecution, Order, Position, Wallet
from candleviewer.exchange.bybit import private_parse as pp
from candleviewer.exchange.bybit import trading_parse as tp
from candleviewer.exchange.bybit.metrics import (
    bybit_private_rows_refused_total,
    cv_bybit_unknown_fields_total,
)
from tests.unit.exchange.bybit._private import (
    frame,
    linear_order,
    push,
    raw,
    reply,
    row,
    usdt_wallet,
)
from tests.unit.exchange.bybit._trading import account

NOW_US = 1_790_000_000_000_000
LABELS = tp.MODEL_LABELS | pp.PUSH_MODEL_LABELS


def _unknown() -> dict[str, float]:
    return {m: cv_bybit_unknown_fields_total.labels(model=m)._value.get() for m in LABELS}


def _refused(topic: str, reason: str) -> float:
    value: float = bybit_private_rows_refused_total.labels(topic=topic, reason=reason)._value.get()
    return value


@pytest.fixture
def no_unknown_fields() -> Iterator[None]:
    before = _unknown()
    yield
    assert _unknown() == before


def _read(frame_text: str) -> tuple[Any, ...]:
    pushed = pp.classify(frame_text)
    assert isinstance(pushed, pp.Push)
    return pp.read_push(pushed, account(), now_us=NOW_US)


def test_every_push_model_label_is_one_of_the_closed_set() -> None:
    """`cv_bybit_unknown_fields_total{model}` stays a closed set (#2877 ruling R7)."""
    labels = {
        model.metric_model
        for model in vars(pp).values()
        if isinstance(model, type)
        and issubclass(model, tp._Venue)
        and model.__module__ == pp.__name__
    }
    assert labels == pp.PUSH_MODEL_LABELS
    assert not labels & tp.MODEL_LABELS


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("auth-ok", pp.Reply("auth", True)),
        ("subscribe-ok", pp.Reply("subscribe", True)),
        ("pong", pp.Reply("pong", None)),
    ],
)
def test_a_documented_reply_reads_as_its_op(name: str, expected: pp.Reply) -> None:
    assert pp.classify(raw(name)) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (reply("auth-ok", success=False), pp.Reply("auth", False)),
        (reply("subscribe-ok", success=False), pp.Reply("subscribe", False)),
        (reply("auth-ok", success="true"), pp.Reply("auth", None)),
        (reply("auth-ok", success=None), pp.Reply("auth", None)),
        (reply("pong", success=False), pp.Reply("pong", None)),
    ],
    ids=["auth-refused", "subscribe-refused", "success-text", "success-null", "pong-success"],
)
def test_a_reply_states_a_verdict_only_as_a_boolean(text: str, expected: pp.Reply) -> None:
    """A refused `auth` or `subscribe` is `success` false (derived: no page shows one); any other
    `success` states no verdict, which the stream never counts as a refusal."""
    assert pp.classify(text) == expected


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("order", "order"),
        ("execution", "execution"),
        ("execution-fast", "execution.fast"),
        ("position", "position"),
        ("wallet", "wallet"),
    ],
)
def test_a_documented_push_reads_as_its_topic(name: str, label: str) -> None:
    pushed = pp.classify(raw(name))
    assert isinstance(pushed, pp.Push)
    assert (pushed.topic, pushed.label) == (frame(name)["topic"], label)
    assert pushed.created_ms == frame(name)["creationTime"] and len(pushed.rows) == 1


@pytest.mark.parametrize("topic", sorted(pp.TOPICS))
def test_a_categorised_or_all_in_one_topic_is_the_same_topic(topic: str) -> None:
    pushed = pp.classify(push(topic))
    assert isinstance(pushed, pp.Push) and pushed.label == pp.TOPICS[topic]


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("[" * 40 + "]" * 40, "depth_limit"),
        ('{"topic":"order","data":' + "[" * 40 + "]" * 40 + "}", "depth_limit"),
        ("not json", "malformed"),
        ("[]", "malformed"),
        ('"text"', "malformed"),
        ('{"topic":"order"}', "malformed"),
        ('{"topic":"order","creationTime":"1672364262474","data":[]}', "malformed"),
        ('{"topic":"order","creationTime":true,"data":[]}', "malformed"),
        ('{"topic":"order","creationTime":1672364262474,"data":{}}', "malformed"),
        ('{"topic":"order","creationTime":1672364262474,"data":[1]}', "malformed"),
        ('{"topic":"order","creationTime":1,"data":[]}', "malformed"),
        ('{"topic":"greeks","creationTime":1672364262474,"data":[]}', "unknown_frame"),
        ('{"topic":7,"data":[]}', "unknown_frame"),
        ('{"op":"ping","success":true,"ret_msg":"pong"}', "unknown_frame"),
        ('{"op":"unsubscribe","success":true}', "unknown_frame"),
        ('{"success":true}', "unknown_frame"),
    ],
    ids=[
        "too-deep",
        "too-deep-push",
        "not-json",
        "an-array",
        "a-string",
        "no-rows",
        "time-as-text",
        "time-as-boolean",
        "rows-an-object",
        "a-row-not-an-object",
        "time-implausible",
        "unsubscribed-topic",
        "topic-not-text",
        "public-pong-shape",
        "another-op",
        "no-op-no-topic",
    ],
)
def test_a_frame_the_stream_cannot_read_is_rejected_whole(text: str, reason: str) -> None:
    with pytest.raises(pp.FrameRejected) as info:
        pp.classify(text)
    assert info.value.reason == reason


def test_a_frame_of_more_than_1000_rows_is_rejected_before_any_is_read() -> None:
    with pytest.raises(pp.FrameRejected) as info:
        pp.classify(push("order.linear", *[linear_order()] * (pp.FRAME_ROWS_MAX + 1)))
    assert info.value.reason == "too_many_rows"
    assert len(_read(push("order.linear", *[linear_order()] * pp.FRAME_ROWS_MAX))) == 1000


@pytest.mark.usefixtures("no_unknown_fields")
def test_each_documented_row_maps_to_its_events_payload_and_record() -> None:
    """The documented execution, fast-execution and position rows as they are, the order and
    wallet rows derived as linear USDT ones: every field known to its model, each event of the
    stream's account, stamped with the push's creation time and the read's ingest time."""
    [order] = _read(push("order.linear", linear_order()))
    [fill] = _read(raw("execution"))
    [fast] = _read(raw("execution-fast"))
    [position] = _read(raw("position"))
    [wallet] = _read(push("wallet", usdt_wallet()))
    kinds = [type(e.payload) for e in (order, fill, fast, position, wallet)]
    assert kinds == [Order, Execution, FastExecution, Position, Wallet]
    for event in (order, fill, fast, position, wallet):
        assert event.account_id == event.payload.account_id == account().account_id
        assert event.ts_ingest == NOW_US
    assert fill.ts_event == frame("execution")["creationTime"] * 1000
    assert (order.seq, fill.seq, fast.seq, position.seq, wallet.seq) == (
        None,
        row("execution")["seq"],
        row("execution-fast")["seq"],
        row("position")["seq"],
        None,
    )
    assert [e.record is not None for e in (order, fill, fast, position, wallet)] == [
        True,
        True,
        True,
        False,
        False,
    ]
    assert fast.record is not None and fast.record.topic == "execution.fast"


def test_a_pushed_row_reads_as_g8_reads_it_over_rest() -> None:
    """One mapper for both paths: the documented execution row, read as a push and through
    G-8's REST model, is the same `Execution`."""
    [event] = _read(raw("execution"))
    over_rest = tp.to_execution(tp.parse(tp.ExecutionRow, row("execution"), "x"), account(), NOW_US)
    assert event.payload == over_rest


def test_the_documented_fast_fill_names_its_order_by_its_exchange_id() -> None:
    """24 §14.2 rule 11: the sample's `orderLinkId` is foreign: the fill is `ext_key(orderId)`."""
    [event] = _read(raw("execution-fast"))
    assert isinstance(event.payload, FastExecution)
    assert event.payload.order_link_id == "ext-" + row("execution-fast")["orderId"].replace("-", "")
    assert event.payload.ts_exec == int(row("execution-fast")["execTime"]) * 1000


def test_a_position_that_never_traded_states_no_sequence() -> None:
    """The position topic's `seq` is `-1` for a symbol never traded: no cross sequence."""
    for never in (-1, "-1"):
        [event] = _read(push("position.linear", row("position") | {"seq": never}))
        assert event.seq is None


def test_the_documented_position_reads_its_entry_price_as_the_average() -> None:
    [event] = _read(push("position", row("position") | {"entryPrice": "28100.5"}))
    assert isinstance(event.payload, Position)
    assert str(event.payload.avg_entry_price) == "28100.5"
    assert event.payload.side is None and event.payload.take_profit is None  # "" and "0": unset


def _execution(**fields: Any) -> str:
    return push("execution", row("execution") | fields)


#: A row the stream may not deliver, by case: (frame, topic label, reason).
NOT_DELIVERED: dict[str, tuple[str, str, str]] = {
    "documented-option-order": (raw("order"), "order", "category"),
    "documented-btc-wallet": (raw("wallet"), "wallet", "no_settle_coin"),
    "usdc-perpetual": (push("order.linear", linear_order(symbol="BTCPERP")), "order", "symbol"),
    "dated-future": (_execution(symbol="BTC-26DEC25"), "execution", "symbol"),
    "inverse-position": (
        push("position", row("position") | {"category": "inverse"}),
        "position",
        "category",
    ),
    "classic-wallet": (
        push("wallet", usdt_wallet(accountType="CONTRACT")),
        "wallet",
        "account_type",
    ),
    "funding-fee": (_execution(execType="Funding"), "execution", "not_a_fill"),
    "delivery": (_execution(execType="Delivery"), "execution", "unmapped_type"),
}


@pytest.mark.parametrize("case", sorted(NOT_DELIVERED))
def test_a_row_the_stream_may_not_deliver_is_dropped_and_counted(case: str) -> None:
    text, topic, reason = NOT_DELIVERED[case]
    before = _refused(topic, reason)
    assert _read(text) == ()
    assert _refused(topic, reason) == before + 1


@pytest.mark.parametrize(
    "rows",
    [
        [linear_order(price="abc")],
        [linear_order(), linear_order(orderStatus="Unheard")],
        [linear_order(orderType="Limit", price="0")],
        [{k: v for k, v in linear_order().items() if k != "category"}],
        [linear_order(symbol=7)],
        [linear_order(orderLinkId=None)],
    ],
    ids=[
        "price-not-decimal",
        "second-row-undocumented-status",
        "limit-without-price",
        "no-category",
        "symbol-not-text",
        "link-not-text",
    ],
)
def test_a_row_the_stream_cannot_read_rejects_its_whole_frame(rows: list[dict[str, Any]]) -> None:
    """No event of a frame is yielded unless all of it was read: a valid first row is no event
    when the second fails (24 §14.2 rule 13)."""
    with pytest.raises(pp.FrameRejected) as info:
        _read(push("order.linear", *rows))
    assert info.value.reason == "malformed"


def test_a_limit_push_without_a_price_never_counts_as_a_rest_reply_of_unknown_outcome() -> None:
    """SEC-G8B-B-01: the parser refuses it as malformed before G-8's mapper, whose own refusal
    feeds `exchange_errors_total{class="UNKNOWN_STATE"}`, the REST order-outcome counter."""
    unknown = exchange_errors_total.labels(**{"class": "UNKNOWN_STATE"})
    before = unknown._value.get()
    with pytest.raises(pp.FrameRejected) as info:
        _read(push("order.linear", linear_order(orderType="Limit", price="0")))
    assert info.value.reason == "malformed"
    assert unknown._value.get() == before


def test_a_wallet_the_stream_cannot_read_rejects_its_frame() -> None:
    """Two USDT rows (which is the account's is unknown), or no account type to check."""
    [coin] = usdt_wallet()["coin"]
    for wallet in (usdt_wallet(coin=[coin, coin]), {"accountIMRate": "0"}):
        with pytest.raises(pp.FrameRejected) as info:
            _read(push("wallet", wallet))
        assert info.value.reason == "malformed"


def test_an_undocumented_execution_type_rejects_its_frame() -> None:
    with pytest.raises(pp.FrameRejected):
        _read(push("execution", row("execution") | {"execType": "Mystery"}))


def test_a_reply_never_reads_its_text_or_connection_id() -> None:
    planted = reply("auth-ok", ret_msg="key DUMMYKEY_x refused", conn_id="c", req_id="r")
    assert pp.classify(planted) == pp.Reply("auth", True)
    assert json.loads(planted)["ret_msg"] not in repr(pp.classify(planted))
