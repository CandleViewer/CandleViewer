"""The exchange's `TradingPort` over the governed REST client (G-8, #2877; E29-X01).

The order path's invariants (`docs/security/threat-models/E29-oms.md` §11.1, #2877), each
pinned by a test under `tests/unit/exchange/bybit/test_trading_*.py`:

1. The `orderLinkId` guard covers creates only (the REST client, OM-D09); cancel and
   `cancel-all` go on the order class in the `critical` lane, and an amend by `orderId` on the
   order class in its request's lane, `critical` when the OMS sets it (AC-31, SR-E29-14).
2. Every account's client draws on the process's one governor (OM-D08, ruling R5); each
   attempt of a call takes its own token, and the lane's wait bounds the whole call, retries
   included (T04's rate step, 24 §8.7).
3. Orders go over REST only: this module holds no trade socket (C-2.11, SR-040a); the private
   stream it hands out (G-8b, `private_stream.py`) reads and never trades.
4. `category` is `linear`, written on every call that takes it (SR-054).
5. Replies are parsed strictly and every row is checked against the call's account (E8-8,
   SR-E29-02, ruling R12).
6. Only an allow-listed `ExchangeRecord` leaves with an ack, built from the body that went on
   the wire; no exception leaves with the cause or context that could hold the signed request
   (SR-E29-08, ruling 11).
7. `open_orders` and `order_history` take keyword-only id filters, sent and re-applied (Q5).

And `cancel-all` always sends `orderFilter=Order` (SR-E29-06, ruling R10: assumed pending
E29-K01 to leave a position's TP/SL orders alone). A venue answer with a return code is an
`OrderAck(ok=False)`; a create's duplicate, a create's open outcome, the venue's outage (10016
or 10019 after the client's retries, #2863), a transport fault and a local refusal raise; a read
raises on every failure (ruling 11). A batch answers one ack per request instead (24 §14.4): an
item whose outcome is open is an ack with `retryable` false and `error_code` `TRANSPORT_ERROR` or
`UNKNOWN_STATE`, never a rejection.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal

import httpx
import structlog

from candleviewer.domain.order_link import EXT_ID, ext_key
from candleviewer.domain.primitives import AccountId, Environment, OrderLinkId, Symbol, TsUs
from candleviewer.exchange.base.boundary import exchange_errors_total
from candleviewer.exchange.base.errors import (
    AmbiguousResultError,
    AuthError,
    DuplicateClientIdError,
    ExchangeError,
    ServiceUnavailableError,
    TransportError,
    UnknownStateError,
)
from candleviewer.exchange.base.guards import (
    check_create_id,
    check_exit_ids,
    check_key_ref,
    check_lookup_id,
    check_window,
)
from candleviewer.exchange.base.models import (
    AccountInfo,
    AccountRef,
    AmendOrderRequest,
    CancelOrderRequest,
    ClosedPnl,
    ExchangeCapabilities,
    Execution,
    FeeRate,
    Order,
    OrderAck,
    PlaceOrderRequest,
    Position,
    RateHeadroom,
    RateLane,
    TradingStopRequest,
    Wallet,
)
from candleviewer.exchange.bybit import record as rec
from candleviewer.exchange.bybit.capabilities import capabilities_for
from candleviewer.exchange.bybit.config import SIGNED_REST_BASES, EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.mapping import OPEN_CREATE_CODES, map_ret_code
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.signer import BybitSigner
from candleviewer.exchange.bybit.trading_parse import (
    AccountInfoResult,
    BatchReply,
    CancelAllResult,
    ClosedPnlPage,
    ClosedPnlRow,
    ExecutionPage,
    ExecutionRow,
    FeeRatePage,
    OrderPage,
    OrderReply,
    PositionPage,
    WalletPage,
    envelope_ms,
    kept,
    normalised_link,
    other_contract,
    parse,
    refuse_row,
    set_aside,
    to_account_info,
    to_closed_pnl,
    to_execution,
    to_fee_rate,
    to_order,
    to_position,
    to_wallet,
    unknown_reply,
    validated,
)
from candleviewer.secrets import KekUnavailable, SecretsError

if TYPE_CHECKING:
    from candleviewer.exchange.base.ports import PrivateStream, RateHeadroomPort, TradingPort
    from candleviewer.exchange.bybit.private_stream import PrivateStreams
    from candleviewer.secrets import SigningCapability

__all__ = [
    "CANCEL_ALL_FILTER",
    "CRITICAL_WAIT_S",
    "DEFAULT_ENTRY_WAIT_S",
    "ENDPOINTS",
    "POLL_WAIT_S",
    "BybitTradingPort",
    "Endpoint",
]


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Endpoint:
    """One call of the port: its route, its endpoint class and its lane (`None`: the
    request's own, set by the OMS by effect, SR-E29-01)."""

    method: Literal["GET", "POST"]
    path: str
    endpoint_class: EndpointClass
    lane: RateLane | None


_ORDER, _POSITION, _READS = EndpointClass.ORDER, EndpointClass.POSITION, EndpointClass.ACCOUNT

#: The port's closed endpoint table (24 §14.2 rule 12; C-2.8: nothing under `/v5/asset/` and
#: no `/v5/user/` write, pinned by a test). Reads go on the account-reads class in the `poll`
#: lane, never on the order or position classes that exits draw from.
ENDPOINTS: Final[Mapping[str, Endpoint]] = MappingProxyType(
    {
        "place_order": Endpoint("POST", "/v5/order/create", _ORDER, None),
        "place_batch": Endpoint("POST", "/v5/order/create-batch", _ORDER, None),
        "amend_order": Endpoint("POST", "/v5/order/amend", _ORDER, None),
        "cancel_order": Endpoint("POST", "/v5/order/cancel", _ORDER, "critical"),
        "cancel_all": Endpoint("POST", "/v5/order/cancel-all", _ORDER, "critical"),
        "set_trading_stop": Endpoint("POST", "/v5/position/trading-stop", _POSITION, "critical"),
        "set_leverage": Endpoint("POST", "/v5/position/set-leverage", _POSITION, "entry"),
        "open_orders": Endpoint("GET", "/v5/order/realtime", _READS, "poll"),
        "order_history": Endpoint("GET", "/v5/order/history", _READS, "poll"),
        "positions": Endpoint("GET", "/v5/position/list", _READS, "poll"),
        "executions": Endpoint("GET", "/v5/execution/list", _READS, "poll"),
        "closed_pnl": Endpoint("GET", "/v5/position/closed-pnl", _READS, "poll"),
        "wallet": Endpoint("GET", "/v5/account/wallet-balance", _READS, "poll"),
        "fee_rate": Endpoint("GET", "/v5/account/fee-rate", _READS, "poll"),
        "account_info": Endpoint("GET", "/v5/account/info", _READS, "poll"),
    }
)

#: Ruling R10: plain orders only, never a position's TP/SL (assumed pending E29-K01).
CANCEL_ALL_FILTER: Final = "Order"
#: T04's rate step: `entry` waits up to a factory-set bound (20 §4.3's admission wait is the
#: default), `critical` up to 24 §8.7's 5 s, `poll` up to 5 s; past it, nothing is sent.
DEFAULT_ENTRY_WAIT_S: Final = 0.75
CRITICAL_WAIT_S: Final = 5.0
POLL_WAIT_S: Final = 5.0
#: USDT linear perpetuals only (C-1.2 item 3): reads without a symbol name the settle coin.
_SETTLE: Final = "USDT"
#: The venue answers at most 7 days per history call; it keeps two years of it.
_WINDOW_MS: Final = 7 * 86_400_000
_MAX_WINDOWS: Final = 106
_MAX_PAGES: Final = 200
_PAGE_LIMIT: Final[Mapping[str, int]] = MappingProxyType(
    {"open_orders": 50, "order_history": 50, "executions": 100, "positions": 200, "closed_pnl": 100}
)

_SIDE: Final = {"buy": "Buy", "sell": "Sell"}
_TYPE: Final = {"market": "Market", "limit": "Limit"}
_TIF: Final = {"gtc": "GTC", "ioc": "IOC", "fok": "FOK", "post_only": "PostOnly"}
_TRIGGER: Final = {"last": "LastPrice", "mark": "MarkPrice", "index": "IndexPrice"}
_DIRECTION: Final = {"rise": 1, "fall": 2}
_TPSL: Final = {"full": "Full", "partial": "Partial"}


def _text(value: Decimal) -> str:
    return format(value, "f")


def _wall_us() -> TsUs:
    return int(time.time() * 1_000_000)


@dataclass(frozen=True, slots=True)
class _Answer:
    """A trade call's outcome: the venue's success body, or its answer with a code."""

    reply: Mapping[str, Any]
    refusal: ExchangeError | None
    latency_ms: int


def _bare[E: BaseException](error: E) -> E:
    """`error` with no cause, context or traceback: the client's frames and an httpx cause can
    hold the signed request (SR-E29-08)."""
    error.__cause__ = None
    error.__context__ = None
    error.__suppress_context__ = True
    error.__traceback__ = None
    return error


def _leaving(failure: Exception) -> ExchangeError:
    """The taxonomy error a failed call leaves the port with, stripped (ruling 11). The client
    counted its own errors; an M2 refusal and any other failure are counted here."""
    if isinstance(failure, ExchangeError):
        return _bare(failure)
    if isinstance(failure, SecretsError):  # M2 refused to sign: nothing was sent (24 §14.4)
        code = getattr(type(failure), "code", None)
        named = code if isinstance(code, str) else "refused"
        mapped: ExchangeError
        if isinstance(failure, KekUnavailable):  # the vault, not the key: retried later
            mapped = TransportError(f"the key vault could not sign ({named}); nothing was sent")
        else:  # the key itself: revoked, unreadable or refused by the permission gate
            mapped = AuthError(f"the account's key could not sign the request ({named})")
    else:  # an undecodable or over-nested answer, or anything unforeseen: never its text
        mapped = UnknownStateError(f"unreadable exchange answer ({type(failure).__name__})")
    exchange_errors_total.labels(**{"class": mapped.code.value}).inc()
    return mapped


def _venue_answer(error: ExchangeError, *, create: bool) -> ExchangeError | None:
    """`error` when it is a venue answer with a return code that settles the call, an
    `OrderAck(ok=False)`; `None` for what raises instead: a create's duplicate, a create's open
    outcome, the venue's outage (10016 or 10019: whether it applied the call is open, 24 §8.6
    and §14.4, #2863), and every failure without a venue code (ruling 11)."""
    if error.exchange_ret_code is None:
        return None
    if isinstance(error, AmbiguousResultError | DuplicateClientIdError | ServiceUnavailableError):
        return None
    if create and isinstance(error, UnknownStateError):
        return None
    return error


def _lane(endpoint: Endpoint, requested: RateLane | None) -> RateLane:
    """The lane a call goes in, named in one place: the endpoint table's, or for a create, a
    batch or an amend (no lane in the table) the request's own, which the OMS sets by effect
    (SR-E29-01). A call that names both, or neither, is a defect of the port: refused."""
    if endpoint.lane is None and requested is not None:
        return requested
    if endpoint.lane is not None and requested is None:
        return endpoint.lane
    raise ValueError(f"{endpoint.path}: its lane is the endpoint table's or its request's")


def _rest_offset(provider: Callable[[], int | None] | None) -> Callable[[], int] | None:
    """The REST client's offset: the measured one, the host's (0) while unmeasured."""
    if provider is None:
        return None
    return lambda: provider() or 0


def _windows(start: TsUs, end: TsUs) -> list[tuple[int, int]]:
    """`[start, end]` in ms as consecutive windows of at most 7 days, the venue's longest."""
    low, high = start // 1000, -(-end // 1000)
    out: list[tuple[int, int]] = []
    while len(out) < _MAX_WINDOWS:
        top = min(low + _WINDOW_MS, high)
        out.append((low, top))
        if top >= high:
            return out
        low = top + 1
    raise ValueError("the window is longer than the exchange keeps")


class BybitTradingPort:
    """`TradingPort` for one environment, over one signed client per account.

    Built only by `ExchangeBybitService.trading_port` (the process's environment, its one
    governor and its private streams). Each method refuses an account of another environment
    before a client exists, a token is taken or anything is signed (C-2.11). `clock_offset_ms`
    is the exchange clock's measured offset, `None` while unmeasured: REST signs on the host's
    clock then, and the private stream counts no `auth` refusal (G-8b OQ-4).
    """

    def __init__(
        self,
        *,
        environment: str,
        credentials: SigningCapability,
        governor: TokenBucketGovernor,
        transport: httpx.AsyncBaseTransport | None,
        clock_offset_ms: Callable[[], int | None] | None = None,
        entry_wait_s: float = DEFAULT_ENTRY_WAIT_S,
        max_retries: int = 3,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now_us: Callable[[], TsUs] = _wall_us,
        private_streams: PrivateStreams | None = None,
    ) -> None:
        self.capabilities: ExchangeCapabilities = capabilities_for(environment)
        self.environment: Environment = self.capabilities.environment
        self._config = RestClientConfig(
            base_url=SIGNED_REST_BASES[self.environment], max_retries=max_retries
        )
        self._credentials = credentials
        self._governor = governor
        self._transport = transport
        self._clock_offset_ms = clock_offset_ms
        self._sleep = sleep
        self._monotonic = monotonic
        self._now_us = now_us
        self._waits: Mapping[RateLane, float] = MappingProxyType(
            {"critical": CRITICAL_WAIT_S, "entry": entry_wait_s, "poll": POLL_WAIT_S}
        )
        self._clients: dict[AccountId, tuple[str, BybitRestClient]] = {}
        self._streams = private_streams

    async def aclose(self) -> None:
        clients, self._clients = self._clients, {}
        for _, client in clients.values():
            await client.aclose()

    # -- clients and calls --------------------------------------------------------------------

    def _check_environment(self, account: AccountRef) -> None:
        """The account is of this port's environment (C-2.11) and names its key by the key's
        `api_keys.id` (ruling R13), or the call is refused before anything else."""
        if account.environment != self.environment:
            raise ValueError("the account belongs to another environment")
        check_key_ref(account)

    async def _client(self, account: AccountRef) -> BybitRestClient:
        """The account's client on its active key; a new key retires the old key's client."""
        self._check_environment(account)
        held = self._clients.get(account.account_id)
        if held is not None and held[0] == account.key_ref:
            return held[1]
        signer = BybitSigner(self._credentials, check_key_ref(account))
        client = BybitRestClient(
            self._config,
            uid=account.uid,
            signer=signer,
            governor=self._governor,
            clock_offset_ms_provider=_rest_offset(self._clock_offset_ms),
            transport=self._transport,
            sleep=self._sleep,
            monotonic=self._monotonic,
        )
        self._clients[account.account_id] = (account.key_ref, client)
        if held is not None:
            await held[1].aclose()
        return client

    async def _attempt(
        self,
        name: str,
        account: AccountRef,
        *,
        lane: RateLane | None = None,
        params: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> tuple[Mapping[str, Any], ExchangeError | None, int]:
        """One call through the account's client: its reply, or its failure as it leaves. The
        client's local refusals run before the handler, so they leave as they are, never as an
        unreadable answer (24 §14.4: a local refusal raises; nothing was taken, signed or sent)."""
        endpoint = ENDPOINTS[name]
        use = _lane(endpoint, lane)
        client = await self._client(account)
        client.preflight(endpoint.method, endpoint.path, params=params, body=body)
        started = self._monotonic()
        failure: Exception | None = None
        reply: Mapping[str, Any] = {}
        try:
            reply = await client.signed_request(
                endpoint.method,
                endpoint.path,
                params=params,
                body=body,
                endpoint_class=endpoint.endpoint_class,
                lane=use,
                budget_wait_s=self._waits[use],
            )
        except Exception as exc:  # every failure is mapped below, outside this handler
            failure = exc
        latency_ms = max(0, int((self._monotonic() - started) * 1000))
        return reply, None if failure is None else _leaving(failure), latency_ms

    async def _trade(
        self,
        name: str,
        account: AccountRef,
        *,
        body: Mapping[str, Any],
        lane: RateLane | None = None,
        create: bool = False,
    ) -> _Answer:
        reply, error, latency_ms = await self._attempt(name, account, lane=lane, body=body)
        if error is None:
            return _Answer(reply, None, latency_ms)
        refusal = _venue_answer(error, create=create)
        if refusal is None:
            raise error
        return _Answer({}, refusal, latency_ms)

    async def _read(
        self, name: str, account: AccountRef, params: Mapping[str, Any] | None
    ) -> Mapping[str, Any]:
        reply, error, _ = await self._attempt(name, account, params=params)
        if error is not None:
            raise error
        return reply

    async def _pages[R](
        self,
        name: str,
        account: AccountRef,
        params: Mapping[str, Any],
        read: Callable[[object], tuple[Sequence[R], str]],
    ) -> list[R]:
        """Every page of one read, following the venue's cursor; bounded."""
        rows: list[R] = []
        cursor = ""
        seen: set[str] = set()
        for _ in range(_MAX_PAGES):
            query = {**params, "cursor": cursor} if cursor else dict(params)
            page_rows, cursor = read((await self._read(name, account, query)).get("result"))
            rows.extend(page_rows)
            if not cursor:
                return rows
            if cursor in seen:
                raise unknown_reply(name, f"malformed {name} reply: the cursor repeats")
            seen.add(cursor)
        raise unknown_reply(name, f"{name} answered more pages than the port reads")

    # -- acks -----------------------------------------------------------------------------------

    def _refused(
        self,
        link: OrderLinkId | None,
        error: ExchangeError,
        latency_ms: int,
        name: str,
        request: rec.Fields,
    ) -> OrderAck:
        return OrderAck(
            ok=False,
            order_link_id=link,
            exchange_order_id=None,
            error_code=error.code.value,
            exchange_ret_code=error.exchange_ret_code,
            exchange_ret_msg=error.exchange_ret_msg,
            retryable=error.retryable,
            latency_ms=latency_ms,
            transport="rest",
            record=rec.record(
                method="POST",
                endpoint=ENDPOINTS[name].path,
                request=request,
                response=None,
                ret_code=error.exchange_ret_code,
                ret_msg=error.exchange_ret_msg,
                latency_ms=latency_ms,
            ),
        )

    def _accepted(
        self,
        link: OrderLinkId | None,
        exchange_order_id: str | None,
        answer: _Answer,
        name: str,
        request: rec.Fields,
        response: rec.Fields | None,
    ) -> OrderAck:
        ret_msg = answer.reply.get("retMsg")
        return OrderAck(
            ok=True,
            order_link_id=link,
            exchange_order_id=exchange_order_id,
            latency_ms=answer.latency_ms,
            transport="rest",
            record=rec.record(
                method="POST",
                endpoint=ENDPOINTS[name].path,
                request=request,
                response=response,
                ret_code=0,
                ret_msg=ret_msg if isinstance(ret_msg, str) else None,
                latency_ms=answer.latency_ms,
            ),
        )

    # -- trade calls ------------------------------------------------------------------------------

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck:
        self._check_environment(req.account)
        check_create_id(req.account, req.order_link_id)
        body = {"category": "linear", **_create_item(req)}
        answer = await self._trade(
            "place_order", req.account, lane=req.lane, body=body, create=True
        )
        fields = rec.request_fields(body)
        if answer.refusal is not None:
            return self._refused(
                req.order_link_id, answer.refusal, answer.latency_ms, "place_order", fields
            )
        reply = _create_reply(answer.reply.get("result"), req.order_link_id)
        response = rec.reply_fields(reply.orderLinkId, reply.orderId)
        return self._accepted(
            req.order_link_id, reply.orderId, answer, "place_order", fields, response
        )

    async def place_batch(self, reqs: Sequence[PlaceOrderRequest]) -> Sequence[OrderAck]:
        if not reqs or len(reqs) > self.capabilities.max_batch_size:
            raise ValueError("a batch holds 1 to max_batch_size orders")
        if len({r.account for r in reqs}) != 1 or len({r.lane for r in reqs}) != 1:
            raise ValueError("a batch is one account's, in one lane")
        account = reqs[0].account
        self._check_environment(account)
        for req in reqs:
            check_create_id(account, req.order_link_id)
        items = [_create_item(r) for r in reqs]
        answer = await self._trade(
            "place_batch",
            account,
            lane=reqs[0].lane,
            body={"category": "linear", "request": items},
            create=True,
        )
        requests = [rec.request_fields({"category": "linear", **item}) for item in items]
        refusal = answer.refusal
        if refusal is not None:
            return [
                self._refused(r.order_link_id, refusal, answer.latency_ms, "place_batch", f)
                for r, f in zip(reqs, requests, strict=True)
            ]
        return self._batch_acks(reqs, requests, answer)

    def _batch_acks(
        self, reqs: Sequence[PlaceOrderRequest], requests: Sequence[rec.Fields], answer: _Answer
    ) -> list[OrderAck]:
        """Pairs each request with its item and code (24 §14.4's item contract); a reply that
        cannot be paired leaves every create's outcome open (24 §8.6 "Order creates")."""
        reply = validated(BatchReply, answer.reply)
        items = [] if reply is None else reply.result.items
        codes = [] if reply is None else reply.retExtInfo.codes
        if not (len(items) == len(codes) == len(reqs)) or any(
            item.orderLinkId != req.order_link_id for item, req in zip(items, reqs, strict=True)
        ):
            raise _open_outcome(
                "the batch answer pairs with no request; outcomes open",
                order_link_ids=[r.order_link_id for r in reqs],
            )
        acks: list[OrderAck] = []
        for req, fields, item, code in zip(reqs, requests, items, codes, strict=True):
            if code.code == 0 and item.orderId:
                response = rec.reply_fields(item.orderLinkId, item.orderId)
                acks.append(
                    self._accepted(
                        req.order_link_id, item.orderId, answer, "place_batch", fields, response
                    )
                )
            else:
                error = _item_error(code.code, code.msg)
                acks.append(
                    self._refused(
                        req.order_link_id, error, answer.latency_ms, "place_batch", fields
                    )
                )
        return acks

    async def amend_order(self, req: AmendOrderRequest) -> OrderAck:
        self._check_environment(req.account)
        check_exit_ids(req.order_link_id, req.exchange_order_id)
        body = _amend_body(req)
        answer = await self._trade("amend_order", req.account, lane=req.lane, body=body)
        fields = rec.request_fields(body)
        if answer.refusal is not None:
            return self._refused(
                req.order_link_id, answer.refusal, answer.latency_ms, "amend_order", fields
            )
        reply = _exit_reply(answer, req.order_link_id, req.exchange_order_id, "amend")
        response = rec.reply_fields(reply.orderLinkId, reply.orderId)
        return self._accepted(
            req.order_link_id, reply.orderId, answer, "amend_order", fields, response
        )

    async def cancel_order(self, req: CancelOrderRequest) -> OrderAck:
        self._check_environment(req.account)
        check_exit_ids(req.order_link_id, req.exchange_order_id)
        body = _cancel_body(req)
        answer = await self._trade("cancel_order", req.account, body=body)
        fields = rec.request_fields(body)
        if answer.refusal is not None:  # named as an accepted cancel names it (rule 11)
            named = req.order_link_id
            if named is None and req.exchange_order_id:
                named = ext_key(req.exchange_order_id)
            return self._refused(named, answer.refusal, answer.latency_ms, "cancel_order", fields)
        reply = _exit_reply(answer, req.order_link_id, req.exchange_order_id, "cancel")
        link = normalised_link(reply.orderLinkId, reply.orderId)
        response = rec.reply_fields(reply.orderLinkId, reply.orderId)
        return self._accepted(link, reply.orderId, answer, "cancel_order", fields, response)

    async def cancel_all(self, account: AccountRef, symbol: Symbol | None) -> Sequence[OrderAck]:
        """One call cancels at most the venue's cap and only what it lists: no proof of a flat
        book, so the OMS repeats it until `open_orders` is empty (24 §14.2 rule 12). A call the
        venue accepts with none of the account's orders cancelled answers one `ok` ack that
        names no order and carries the call's record, so every cancel-all leaves evidence of
        the call (C-2.9, SR-E29-08)."""
        self._check_environment(account)
        body = _cancel_all_body(symbol)
        answer = await self._trade("cancel_all", account, body=body)
        fields = rec.request_fields(body)
        if answer.refusal is not None:
            return [self._refused(None, answer.refusal, answer.latency_ms, "cancel_all", fields)]
        result = parse(CancelAllResult, answer.reply.get("result"), "cancel-all")
        if result.success == "0":
            raise unknown_reply("cancel-all", "the exchange reported the cancel-all as failed")
        rows = kept(
            [(normalised_link(r.orderLinkId, r.orderId), r) for r in result.cancelled],
            lambda pair: pair[0],
            account,
        )
        if not rows:
            return [self._accepted(None, None, answer, "cancel_all", fields, None)]
        return [
            self._accepted(
                link,
                row.orderId,
                answer,
                "cancel_all",
                fields,
                rec.reply_fields(row.orderLinkId, row.orderId),
            )
            for link, row in rows
        ]

    async def set_trading_stop(self, req: TradingStopRequest) -> OrderAck:
        """Both sides go in one call (24 §8.9): the OMS sends the unchanged side's value; a side
        left `None` is not sent."""
        self._check_environment(req.account)
        body = _stop_body(req)
        answer = await self._trade("set_trading_stop", req.account, body=body)
        fields = rec.request_fields(body)
        if answer.refusal is not None:
            return self._refused(
                None, answer.refusal, answer.latency_ms, "set_trading_stop", fields
            )
        if not isinstance(answer.reply.get("result"), dict):
            raise unknown_reply("trading-stop", "malformed trading-stop reply")
        return self._accepted(None, None, answer, "set_trading_stop", fields, None)

    async def set_leverage(self, account: AccountRef, symbol: Symbol, leverage: Decimal) -> None:
        self._check_environment(account)
        if not leverage.is_finite() or leverage <= 0:
            raise ValueError("leverage must be a positive number")
        body = {
            "category": "linear",
            "symbol": symbol,
            "buyLeverage": _text(leverage),
            "sellLeverage": _text(leverage),
        }
        answer = await self._trade("set_leverage", account, body=body)
        if answer.refusal is not None:
            raise answer.refusal  # no ack carries it: the venue's answer leaves as raised
        if not isinstance(answer.reply.get("result"), dict):
            raise unknown_reply("set-leverage", "malformed set-leverage reply")

    # -- reads ----------------------------------------------------------------------------------

    async def open_orders(
        self,
        account: AccountRef,
        symbol: Symbol | None = None,
        *,
        order_link_id: OrderLinkId | None = None,
    ) -> Sequence[Order]:
        self._check_environment(account)
        check_lookup_id(order_link_id)
        params: dict[str, Any] = {"category": "linear", "limit": _PAGE_LIMIT["open_orders"]}
        params |= {"settleCoin": _SETTLE} if symbol is None else {"symbol": symbol}
        if order_link_id is not None:
            params["orderLinkId"] = order_link_id
        orders = await self._orders("open_orders", account, params)
        return [
            o
            for o in orders
            if symbol in (None, o.symbol) and order_link_id in (None, o.order_link_id)
        ]

    async def order_history(
        self,
        account: AccountRef,
        *,
        order_link_id: OrderLinkId | None = None,
        exchange_order_id: str | None = None,
        start: TsUs | None = None,
        end: TsUs | None = None,
    ) -> Sequence[Order]:
        """The orders the venue's history read lists: with no bound, its default window; with
        one, the venue's span for it, the 7 days from `start` or to `end`; with both, every 7-day
        window between them (24 §14.1)."""
        self._check_environment(account)
        check_lookup_id(order_link_id)
        check_window(start, end)
        params: dict[str, Any] = {
            "category": "linear",
            "settleCoin": _SETTLE,
            "limit": _PAGE_LIMIT["order_history"],
        }
        if exchange_order_id is not None:
            params["orderId"] = exchange_order_id
        elif order_link_id is not None:
            params["orderLinkId"] = order_link_id
        orders: list[Order] = []
        for window in _maybe_windows(start, end):
            orders += await self._orders("order_history", account, {**params, **window})
        return [
            o
            for o in _unique(orders, lambda o: o.exchange_order_id)
            if order_link_id in (None, o.order_link_id)
            and exchange_order_id in (None, o.exchange_order_id)
        ]

    async def _orders(
        self, name: str, account: AccountRef, params: Mapping[str, Any]
    ) -> list[Order]:
        def read(result: object) -> tuple[Sequence[Order], str]:
            page = parse(OrderPage, result, name)
            return [to_order(row, account) for row in page.rows], page.nextPageCursor

        orders = _unique(
            await self._pages(name, account, params, read),
            lambda o: o.exchange_order_id,
        )
        return kept(orders, lambda o: o.order_link_id, account)

    async def positions(self, account: AccountRef) -> Sequence[Position]:
        self._check_environment(account)
        params = {"category": "linear", "settleCoin": _SETTLE, "limit": _PAGE_LIMIT["positions"]}

        def read(result: object) -> tuple[Sequence[Position], str]:
            page = parse(PositionPage, result, "positions")
            return [to_position(row, account) for row in page.rows], page.nextPageCursor

        return await self._pages("positions", account, params, read)

    async def executions(self, account: AccountRef, start: TsUs, end: TsUs) -> Sequence[Execution]:
        self._check_environment(account)
        check_window(start, end)
        params = {"category": "linear", "settleCoin": _SETTLE, "limit": _PAGE_LIMIT["executions"]}
        ingested = self._now_us()

        def read(result: object) -> tuple[Sequence[Execution], str]:
            page = parse(ExecutionPage, result, "executions")
            fills: list[Execution] = []
            for raw in page.rows:
                if (reason := set_aside(raw)) is not None:
                    refuse_row(reason, "", exec_type=raw["execType"])
                    continue
                fills.append(
                    to_execution(parse(ExecutionRow, raw, "executions"), account, ingested)
                )
            return fills, page.nextPageCursor

        fills: list[Execution] = []
        for window in _windows(start, end):
            fills += await self._pages("executions", account, {**params, **_window(window)}, read)
        return kept(_unique(fills, lambda e: e.exec_id), lambda e: e.order_link_id, account)

    async def closed_pnl(self, account: AccountRef, start: TsUs, end: TsUs) -> Sequence[ClosedPnl]:
        """The account's USDT records only (C-1.2 item 3): the venue's read takes no settle coin,
        so it can list a USDC perpetual (its documented example) or a dated future. A row of a
        contract whose name does not end in the settle coin is set aside before the strict
        parse and counted (`not_usdt`), never read as USDT and never failing the read on a
        field of its own (24 §14.2 rule 12)."""
        self._check_environment(account)
        check_window(start, end)
        params = {"category": "linear", "limit": _PAGE_LIMIT["closed_pnl"]}

        def read(result: object) -> tuple[Sequence[ClosedPnl], str]:
            page = parse(ClosedPnlPage, result, "closed-pnl")
            usdt: list[ClosedPnl] = []
            for raw in page.rows:
                if (other := other_contract(raw, _SETTLE)) is not None:
                    refuse_row("not_usdt", "", symbol=other)
                    continue
                usdt.append(to_closed_pnl(parse(ClosedPnlRow, raw, "closed-pnl"), account))
            return usdt, page.nextPageCursor

        records: list[ClosedPnl] = []
        for window in _windows(start, end):
            records += await self._pages("closed_pnl", account, {**params, **_window(window)}, read)
        return records

    async def wallet(self, account: AccountRef) -> Wallet:
        self._check_environment(account)
        # The wallet takes no category (an account endpoint), only the account type and coin.
        reply = await self._read("wallet", account, {"accountType": "UNIFIED", "coin": _SETTLE})
        at_ms = envelope_ms(reply.get("time"), "wallet")
        page = parse(WalletPage, reply.get("result"), "wallet")
        return to_wallet(page, account, _SETTLE, at_ms)

    async def fee_rate(self, account: AccountRef, symbol: Symbol) -> FeeRate:
        self._check_environment(account)
        reply = await self._read("fee_rate", account, {"category": "linear", "symbol": symbol})
        page = parse(FeeRatePage, reply.get("result"), "fee-rate")
        return to_fee_rate(page, symbol, self._now_us())

    async def account_info(self, account: AccountRef) -> AccountInfo:
        self._check_environment(account)
        # The account read takes no parameter at all, so no category either.
        reply = await self._read("account_info", account, None)
        result = parse(AccountInfoResult, reply.get("result"), "account-info")
        return to_account_info(result, account)

    async def subscribe_private(self, account: AccountRef) -> PrivateStream:
        """G-8b (#3963): the account's private stream (24 §14.1, §14.2 rule 13), from the
        adapter's one registry. Another environment's account is refused first, a port built
        with no registry refuses every account; the registry's own refusals come before anything
        is signed, dialled or built, and once returned the stream raises nothing."""
        self._check_environment(account)
        if self._streams is None:
            raise RuntimeError("no private stream is wired")
        return await self._streams.open(account, clock_offset_ms=self._clock_offset_ms)

    # -- the rate budget, read (RateHeadroomPort) -------------------------------------------------

    def headroom(self, account: AccountRef, lane: RateLane) -> RateHeadroom:
        """The local rate budget the account's next request in `lane` would meet, read without
        taking a token or sending anything (#2877 ruling 4; 24 §14.1 `RateHeadroomPort`): the
        order class for `critical` and `entry`, which creates and exits draw, the account-reads
        class for `poll` (24 §14.2 rule 12). A request whose `wait_s` passes its lane's wait is
        refused with nothing sent (24 §8.7)."""
        self._check_environment(account)
        endpoint_class = _READS if lane == "poll" else _ORDER
        tokens, wait_s = self._governor.headroom(account.uid, endpoint_class, lane=lane)
        return RateHeadroom(lane=lane, tokens=tokens, wait_s=wait_s)


def _create_item(req: PlaceOrderRequest) -> dict[str, Any]:
    """§8.9's create mapping; the price goes only with a limit order, and the attached TP/SL
    fields only with their price."""
    item: dict[str, Any] = {
        "symbol": req.symbol,
        "side": _SIDE[req.side],
        "orderType": _TYPE[req.order_type],
        "qty": _text(req.qty),
        "timeInForce": _TIF[req.time_in_force],
        "orderLinkId": req.order_link_id,
        "reduceOnly": req.reduce_only,
        "closeOnTrigger": req.close_on_trigger,
        "positionIdx": req.position_idx,
    }
    if req.order_type == "limit" and req.price is not None:
        item["price"] = _text(req.price)
    if req.trigger_price is not None:
        item["triggerPrice"] = _text(req.trigger_price)
        if req.trigger_by is not None:
            item["triggerBy"] = _TRIGGER[req.trigger_by]
        if req.trigger_direction is not None:
            item["triggerDirection"] = _DIRECTION[req.trigger_direction]
    if req.take_profit is not None:
        item |= {"takeProfit": _text(req.take_profit), "tpTriggerBy": _TRIGGER[req.tp_trigger_by]}
    if req.stop_loss is not None:
        item |= {"stopLoss": _text(req.stop_loss), "slTriggerBy": _TRIGGER[req.sl_trigger_by]}
    if req.take_profit is not None or req.stop_loss is not None:
        item["tpslMode"] = _TPSL[req.tpsl_mode]
    return item


def _amend_body(req: AmendOrderRequest) -> dict[str, Any]:
    """An amend names its order (rule 11) and sends only the values it changes."""
    body: dict[str, Any] = {
        "category": "linear",
        "symbol": req.symbol,
        **_order_ref(req.order_link_id, req.exchange_order_id),
    }
    for name, value in (
        ("qty", req.qty),
        ("price", req.price),
        ("triggerPrice", req.trigger_price),
        ("takeProfit", req.take_profit),
        ("stopLoss", req.stop_loss),
    ):
        if value is not None:
            body[name] = _text(value)
    return body


def _cancel_body(req: CancelOrderRequest) -> dict[str, Any]:
    return {
        "category": "linear",
        "symbol": req.symbol,
        **_order_ref(req.order_link_id, req.exchange_order_id),
    }


def _cancel_all_body(symbol: Symbol | None) -> dict[str, Any]:
    """Ruling R10's filter always; the symbol, or the settle coin when none is named."""
    scope = {"settleCoin": _SETTLE} if symbol is None else {"symbol": symbol}
    return {"category": "linear", "orderFilter": CANCEL_ALL_FILTER, **scope}


def _stop_body(req: TradingStopRequest) -> dict[str, Any]:
    """§8.9's stop write: a side left `None` is not sent, nor its trigger source."""
    body: dict[str, Any] = {
        "category": "linear",
        "symbol": req.symbol,
        "tpslMode": _TPSL[req.tpsl_mode],
        "positionIdx": req.position_idx,
    }
    if req.take_profit is not None:
        body["takeProfit"] = _text(req.take_profit)
        body["tpTriggerBy"] = _TRIGGER[req.tp_trigger_by]
    if req.stop_loss is not None:
        body["stopLoss"] = _text(req.stop_loss)
        body["slTriggerBy"] = _TRIGGER[req.sl_trigger_by]
    if req.trailing_distance is not None:
        body["trailingStop"] = _text(req.trailing_distance)
    if req.active_price is not None:
        body["activePrice"] = _text(req.active_price)
    return body


def _order_ref(link: OrderLinkId | None, exchange_order_id: str | None) -> dict[str, str]:
    """How an exit names its order: by `orderId` when known, so an `ext-` key never goes on the
    wire (24 §14.2 rule 11); else by our own id (`check_exit_ids` has required one)."""
    if exchange_order_id:
        return {"orderId": exchange_order_id}
    if link is None or EXT_ID.fullmatch(link) is not None:
        raise ValueError("this order can only be named by its exchange_order_id")
    return {"orderLinkId": link}


def _item_error(code: int, msg: str) -> ExchangeError:
    """One batch item's code as the taxonomy reads it. An open outcome (10016, 10019, an
    `UNKNOWN_STATE` code, or a success naming no order) is never retryable, so its order goes
    to `unknown`, never `rejected` (24 §8.6 "Order creates")."""
    if code == 0:
        return AmbiguousResultError("the item was accepted without an order id")
    if code in OPEN_CREATE_CODES:
        return AmbiguousResultError(msg, exchange_ret_code=code, exchange_ret_msg=msg)
    error = map_ret_code(code, msg, create=True)
    if isinstance(error, UnknownStateError):
        error.retryable = False
    return error


def _create_reply(result: object, link: OrderLinkId) -> OrderReply:
    """A create's accepted answer must name the order it created; anything else leaves the
    create's outcome open (24 §8.6 "Order creates")."""
    reply = validated(OrderReply, result)
    if reply is None or normalised_link(reply.orderLinkId, reply.orderId) != link:
        raise _open_outcome(
            "the create's answer names no order of this id; its outcome is open",
            order_link_id=link,
        )
    return reply


def _open_outcome(
    message: str, *, order_link_id: str | None = None, order_link_ids: Sequence[str] = ()
) -> AmbiguousResultError:
    """A create whose answer leaves its outcome open (24 §8.6 "Order creates"), bare: counted and
    logged with its ids only, as the REST client counts the open outcomes it raises."""
    exchange_errors_total.labels(**{"class": AmbiguousResultError.code.value}).inc()
    logger().warning(
        "bybit_create_answer_ambiguous",
        order_link_id=order_link_id,
        order_link_ids=list(order_link_ids),
    )
    return _bare(
        AmbiguousResultError(message, order_link_id=order_link_id, order_link_ids=order_link_ids)
    )


def _exit_reply(
    answer: _Answer, link: OrderLinkId | None, exchange_order_id: str | None, what: str
) -> OrderReply:
    """An exit's accepted answer names the order the call named, or the call is unread."""
    reply = parse(OrderReply, answer.reply.get("result"), what)
    named = normalised_link(reply.orderLinkId, reply.orderId)
    if (exchange_order_id and reply.orderId != exchange_order_id) or (
        link is not None and named != link
    ):
        raise unknown_reply(what, f"the {what} answer names another order")
    return reply


def _window(window: tuple[int, int]) -> dict[str, int]:
    return {"startTime": window[0], "endTime": window[1]}


def _maybe_windows(start: TsUs | None, end: TsUs | None) -> list[dict[str, int]]:
    """No bound: one call, the venue's own default window. One bound: one call over the venue's
    span for it, the 7 days from `start` or to `end` in whole ms (`start` rounded down, `end`
    up, as `_windows` rounds them), sent as both bounds. Both: 7-day windows covering them."""
    if start is not None and end is not None:
        return [_window(w) for w in _windows(start, end)]
    if start is not None:
        low = start // 1000
        return [_window((low, low + _WINDOW_MS))]
    if end is not None:
        high = -(-end // 1000)
        return [_window((high - _WINDOW_MS, high))]
    return [{}]


def _unique[T](items: Sequence[T], key: Callable[[T], str]) -> list[T]:
    seen: set[str] = set()
    out: list[T] = []
    for item in items:
        if (k := key(item)) not in seen:
            seen.add(k)
            out.append(item)
    return out


if TYPE_CHECKING:  # CI's mypy checks the signatures, which the runtime protocol check cannot
    _TRADING: type[TradingPort] = BybitTradingPort
    _HEADROOM: type[RateHeadroomPort] = BybitTradingPort
