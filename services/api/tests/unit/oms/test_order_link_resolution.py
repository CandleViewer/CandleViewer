"""Success-after-lookup and history retention (§8.3 rules 3 and 6; E29-T02, #846).

Ruling B4: no recorded exchange payloads here. The fake below speaks domain
`Order`/`OrderAck` models only; the fixture-driven integration test belongs to
E29-T04. Ruling Q5: `open_orders` has no id filter yet, so the OMS filters
locally, and the fake's `order_history` ignores its filter to prove the OMS
re-checks it.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.primitives import (
    AccountId,
    GroupId,
    OrderId,
    OrderLinkId,
    Symbol,
    TsUs,
)
from candleviewer.exchange.base.errors import DuplicateClientIdError, OmsErrorCode, TransportError
from candleviewer.exchange.base.models import (
    AccountRef,
    ExchangeCapabilities,
    Order,
    OrderAck,
    PlaceOrderRequest,
)
from candleviewer.exchange.base.ports import TradingPort
from candleviewer.oms.fakes import InMemoryOrderLinkLookup
from candleviewer.oms.order_link import OrderLinkIdParts
from candleviewer.oms.order_link_allocator import OrderLinkIdAllocator
from candleviewer.oms.order_link_resolution import (
    DEMO_RETENTION_EXPIRED,
    Adopted,
    HistoryRetentionPolicy,
    PlacementPort,
    Sent,
    Unresolved,
    place_or_adopt,
)

ACCOUNT = AccountId(UUID("5b1c9d2e-7f30-4a6b-8c4d-2e3f4a5b6c7d"))
GROUP = GroupId(UUID("0f8e2b6c-3d4a-4b5c-9e7f-1a2b3c4d5e6f"))
ACCOUNT_REF = AccountRef(account_id=ACCOUNT, uid="100001", environment="demo", key_ref="kref-1")
SYMBOL = "BTCUSDT"
STOP_LOSS = Decimal("58000")
DAY_US = 86_400_000_000
T0: TsUs = 1_790_000_000_000_000


CANDIDATE = OrderLinkIdParts.generate(
    mode="exchange", environment="demo", group_id=GROUP, account_id=ACCOUNT, seq=0, purpose="entry"
)
LINK = CANDIDATE.value
OTHER_LINK = CANDIDATE.with_seq(1).value


def _request(order_link_id: OrderLinkId = LINK) -> PlaceOrderRequest:
    return PlaceOrderRequest(
        account=ACCOUNT_REF,
        symbol=SYMBOL,
        side="buy",
        order_type="limit",
        qty=Decimal("0.010"),
        price=Decimal("60000"),
        order_link_id=order_link_id,
        stop_loss=STOP_LOSS,
    )


def _order(order_link_id: OrderLinkId = LINK, *, state: str = "new") -> Order:
    return Order(
        order_id=OrderId(uuid5(NAMESPACE_URL, order_link_id)),
        order_link_id=order_link_id,
        exchange_order_id=f"x-{order_link_id[-6:]}",
        account_id=ACCOUNT,
        symbol=SYMBOL,
        side="buy",
        order_type="limit",
        qty=Decimal("0.010"),
        price=Decimal("60000"),
        state=state,
        filled_qty=Decimal("0"),
        leaves_qty=Decimal("0.010"),
        avg_fill_price=None,
        created_at=T0,
        terminal_at=None,
    )


def _ack(*, ok: bool, error_code: str | None = None) -> OrderAck:
    return OrderAck(
        ok=ok,
        order_link_id=LINK,
        exchange_order_id="x-1" if ok else None,
        error_code=error_code,
        latency_ms=1,
        transport="rest",
    )


class _FakeExchange:
    """A `PlacementPort` that deduplicates on `order_link_id` like the exchange.

    An id it has seen is rejected with `DuplicateClientIdError`, even once the
    order has left `open` and `history`. `timeout_after_send` makes a create
    land and then fail with `TransportError`, the ambiguous timeout.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID, str | None]] = []
        self.sent: list[PlaceOrderRequest] = []
        self.seen: set[str] = set()
        self.open: list[Order] = []
        self.history: list[Order] = []
        self.reply: OrderAck | None = None
        self.timeout_after_send = False

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck:
        self.calls.append(("place_order", req.account.account_id, req.order_link_id))
        self.sent.append(req)
        if self.reply is not None:
            return self.reply
        if req.order_link_id in self.seen:
            raise DuplicateClientIdError("order_link_id already accepted")
        self.seen.add(req.order_link_id)
        self.open.append(_order(req.order_link_id))
        if self.timeout_after_send:
            raise TransportError("timed out after send")
        return _ack(ok=True)

    async def open_orders(
        self, account: AccountRef, symbol: Symbol | None = None
    ) -> Sequence[Order]:
        self.calls.append(("open_orders", account.account_id, symbol))
        return list(self.open)

    async def order_history(
        self,
        account: AccountRef,
        *,
        order_link_id: OrderLinkId | None = None,
        start: TsUs | None = None,
        end: TsUs | None = None,
    ) -> Sequence[Order]:
        self.calls.append(("order_history", account.account_id, order_link_id))
        return list(self.history)


def _placement_port(port: TradingPort) -> PlacementPort:
    """Type-level check: mypy --strict fails here if a `TradingPort` stops being a
    `PlacementPort`, so T04 can pass the real adapter unchanged."""
    return port


async def test_an_accepted_create_is_returned_without_lookups() -> None:
    exchange = _FakeExchange()
    request = _request()

    outcome = await place_or_adopt(exchange, request)

    assert outcome == Sent(_ack(ok=True))
    assert exchange.calls == [("place_order", ACCOUNT, LINK)]
    assert exchange.sent == [request]
    assert exchange.sent[0].stop_loss == STOP_LOSS  # the native SL rides the send (C-2.6)


async def test_duplicate_rejection_is_adopted_not_failed() -> None:
    """Scenario: Duplicate rejection is adopted, not failed."""
    exchange = _FakeExchange()
    live = _order()
    exchange.seen.add(LINK)
    exchange.open += [_order(OTHER_LINK), live]

    with capture_logs() as logs:
        outcome = await place_or_adopt(exchange, _request())

    assert outcome == Adopted(order=live, source="realtime")
    assert exchange.calls == [("place_order", ACCOUNT, LINK), ("open_orders", ACCOUNT, SYMBOL)]
    assert logs == [
        {
            "event": "order_link_id_duplicate_adopted",
            "log_level": "info",
            "order_link_id": LINK,
            "source": "realtime",
            "state": "new",
        }
    ]


async def test_duplicate_absent_from_open_orders_is_adopted_from_history() -> None:
    exchange = _FakeExchange()
    filled = _order(state="filled")
    exchange.seen.add(LINK)
    exchange.open.append(_order(OTHER_LINK))
    exchange.history += [_order(OTHER_LINK, state="cancelled"), filled]

    outcome = await place_or_adopt(exchange, _request())

    assert outcome == Adopted(order=filled, source="history")
    assert exchange.calls == [
        ("place_order", ACCOUNT, LINK),
        ("open_orders", ACCOUNT, SYMBOL),
        ("order_history", ACCOUNT, LINK),
    ]


async def test_duplicate_found_by_neither_lookup_is_left_to_reconciliation() -> None:
    exchange = _FakeExchange()
    exchange.seen.add(LINK)
    exchange.history.append(_order(OTHER_LINK, state="filled"))  # another id: never adopted

    with capture_logs() as logs:
        outcome = await place_or_adopt(exchange, _request())

    assert outcome == Unresolved(order_link_id=LINK)
    assert logs == [
        {
            "event": "order_link_id_duplicate_unresolved",
            "log_level": "warning",
            "order_link_id": LINK,
        }
    ]


async def test_duplicate_reported_in_the_ack_is_adopted_too() -> None:
    exchange = _FakeExchange()
    live = _order()
    exchange.reply = _ack(ok=False, error_code=OmsErrorCode.DUPLICATE_CLIENT_ID)
    exchange.open.append(live)

    outcome = await place_or_adopt(exchange, _request())

    assert outcome == Adopted(order=live, source="realtime")


async def test_another_rejection_is_returned_to_the_caller_without_lookups() -> None:
    exchange = _FakeExchange()
    rejection = _ack(ok=False, error_code=OmsErrorCode.INSUFFICIENT_MARGIN)
    exchange.reply = rejection

    outcome = await place_or_adopt(exchange, _request())

    assert outcome == Sent(rejection)
    assert exchange.calls == [("place_order", ACCOUNT, LINK)]


async def test_a_transport_failure_after_send_propagates_without_lookups() -> None:
    exchange = _FakeExchange()
    exchange.timeout_after_send = True

    with pytest.raises(TransportError):
        await place_or_adopt(exchange, _request())

    assert exchange.calls == [("place_order", ACCOUNT, LINK)]


async def test_retry_reuses_the_id() -> None:
    """Scenario: Retry reuses the id."""
    lookup = InMemoryOrderLinkLookup()
    allocated = await OrderLinkIdAllocator(lookup).allocate(CANDIDATE)
    lookup.add(allocated.order_link_id)  # persisted before the first send (rule 1)
    exchange = _FakeExchange()
    exchange.timeout_after_send = True
    with pytest.raises(TransportError):
        await place_or_adopt(exchange, _request(allocated.order_link_id))

    outcome = await place_or_adopt(exchange, _request(allocated.order_link_id))

    assert [sent.order_link_id for sent in exchange.sent] == [LINK, LINK]
    assert [sent.stop_loss for sent in exchange.sent] == [STOP_LOSS, STOP_LOSS]  # C-2.6
    assert len(exchange.open) == 1  # the exchange deduplicated: one order, not two
    assert outcome == Adopted(order=exchange.open[0], source="realtime")
    assert lookup.lookups == [LINK]  # the retry never allocated again


@pytest.mark.parametrize(("age_us", "expired"), [(6 * DAY_US, False), (6 * DAY_US + 1, True)])
def test_seven_day_retention_expires_ids_older_than_six_days(age_us: int, expired: bool) -> None:
    policy = HistoryRetentionPolicy(retention_days=7)

    assert policy.unresolvable_by_history(created_at=T0, now=T0 + age_us) is expired


def test_unbounded_retention_never_expires() -> None:
    policy = HistoryRetentionPolicy(retention_days=None)

    assert policy.unresolvable_by_history(created_at=T0, now=T0 + 3650 * DAY_US) is False


def test_retention_comes_from_the_exchange_capabilities() -> None:
    capabilities = ExchangeCapabilities.model_construct(order_retention_days=7)

    assert HistoryRetentionPolicy.from_capabilities(capabilities).retention_days == 7


def test_expired_ids_close_with_the_contract_reject_code() -> None:
    assert DEMO_RETENTION_EXPIRED == "DEMO_RETENTION_EXPIRED"
