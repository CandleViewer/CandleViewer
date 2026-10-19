"""An in-memory Bybit demo venue for the harness tests (no network, C-13.5): REST through
`httpx.MockTransport` under the harness's own `GuardedTransport`, the private stream through
`FakeSocket`.

Replies reuse a recorded envelope wherever the corpus has one: the server-time reply, the ETHUSDT
row of `instruments_before.json` and the 10002, 10018 and 503 replies
(`packages/fixtures/bybit/2026-10-05/rest`), and the E27 key-info and stream-auth fixtures
(`tests/fixtures/key_verification`). Order, position, execution and ticker rows carry only the
documented Bybit v5 fields (`docs/research/06-bybit-api.md` §6 and §10) that the harness reads.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx

from spikes.oms_demo_path.stream import TOPICS

_API: Final = Path(__file__).resolve().parents[3]
_CORPUS: Final = _API.parents[1] / "packages" / "fixtures" / "bybit" / "2026-10-05" / "rest"
_KEYS: Final = _API / "tests" / "fixtures" / "key_verification"
SYMBOL: Final = "ETHUSDT"
#: The documentation address (RFC 5737) the key-info fixture is bound to.
BOUND_IP: Final = "203.0.113.7"
_OPEN: Final = ("New", "PartiallyFilled")
_LOT: Final = Decimal("0.001")


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _ok(result: dict[str, Any]) -> dict[str, Any]:
    return {"retCode": 0, "retMsg": "OK", "result": result, "retExtInfo": {}, "time": _now_ms()}


def refusal(code: int, message: str) -> dict[str, Any]:
    return {"retCode": code, "retMsg": message, "result": {}, "retExtInfo": {}, "time": _now_ms()}


def _corpus(name: str) -> dict[str, Any]:
    """A recorded reply of the corpus, stamped now."""
    return load(_CORPUS / name) | {"time": _now_ms()}


class FakeSocket:
    """One private-stream connection. It answers `auth`, `subscribe` and `ping` as the demo
    stream does and carries what the venue pushes; `drop()` ends it as a reset would."""

    def __init__(self, on_subscribed: Callable[[], None]) -> None:
        self._inbox: asyncio.Queue[str | None] = asyncio.Queue()
        self._on_subscribed, self._subscribed = on_subscribed, 0
        self.open = True

    async def send(self, message: str) -> None:
        frame = json.loads(message)
        if frame.get("op") == "auth":
            self._inbox.put_nowait(json.dumps(load(_KEYS / "ws_auth_ok.json")))
        elif frame.get("op") == "subscribe":
            ack = {"success": True, "ret_msg": "", "op": "subscribe", "req_id": frame["req_id"]}
            self._inbox.put_nowait(json.dumps(ack))
            self._subscribed += 1
            if self._subscribed == len(TOPICS):
                self._on_subscribed()

    async def recv(self) -> str:
        frame = await self._inbox.get()
        if frame is None:
            raise ConnectionError("connection reset")
        return frame

    async def close(self) -> None:
        self.drop()

    def push(self, frame: dict[str, Any]) -> None:
        if self.open:
            self._inbox.put_nowait(json.dumps(frame))

    def drop(self) -> None:
        self.open = False
        self._inbox.put_nowait(None)


class FakeBybit:
    """The venue: one symbol, a one-way long position, orders by `orderLinkId`. The knobs below
    script a run: failures, a stream drop, a refused cancel, a flatten that never fills."""

    def __init__(self, *, ips: list[str] | None = None) -> None:
        self.bid, self.ask = Decimal("3000.00"), Decimal("3000.50")
        self.key_info = load(_KEYS / "key_info_trade.json")
        self.key_info["result"]["ips"] = [BOUND_IP] if ips is None else ips
        self.orders: dict[str, dict[str, Any]] = {}
        self.size = Decimal(0)
        self.executions: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.sockets: list[FakeSocket] = []
        self.socket: FakeSocket | None = None
        #: Accepted create number (1-based) -> HTTP 503 replies its order lookups still get.
        self.fail_lookups: dict[int, int] = {}
        #: Every position read refused with this `(retCode, retMsg)`.
        self.refuse_positions: tuple[int, str] | None = None
        #: The read of the open orders (the realtime list with no `orderLinkId`) refused.
        self.refuse_open_orders: tuple[int, str] | None = None
        #: Every cancel refused with this `(retCode, retMsg)`; or, `cancel_raises`, broken.
        self.refuse_cancels: tuple[int, str] | None = None
        self.cancel_raises = False
        #: The n-th new `orderLinkId` (1-based, counted at its first create request) is refused,
        #: every request of it, with the `(retCode, retMsg)` this returns for n; `None` accepts.
        self.refuse_creates: Callable[[int], tuple[int, str] | None] | None = None
        #: HTTP 503 replies the execution list still gets.
        self.fail_executions = 0
        self.flatten_fills = True
        #: An opening taker fills in two executions (a partial fill first).
        self.split_fills = False
        #: The n-th opening taker drops the stream; it fills once the stream is back.
        self.drop_on_taker: int | None = None
        #: Called with the number of every accepted create.
        self.on_create: Callable[[int], None] | None = None
        #: Called with the path of every GET, signed or not, before it is answered.
        self.on_get: Callable[[str], None] | None = None
        #: Server-time reads after this many get the recorded 10018 reply.
        self.limit_time_reads: int | None = None
        self.time_reads = 0
        self._number: dict[str, int] = {}
        self._create_no: dict[str, int] = {}
        self._takers = 0
        self._deferred: list[Callable[[], None]] = []
        self._seq = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    async def dial(self, url: str) -> FakeSocket:
        self.socket = FakeSocket(self._subscribed)
        self.sockets.append(self.socket)
        return self.socket

    def drop(self) -> None:
        """The live private-stream connection resets."""
        if self.socket is not None:
            self.socket.drop()
            self.socket = None

    def rest_order(self, link: str, *, qty: str = "0.005") -> None:
        """A Buy limit of the run resting at the bid, as a cycle that stopped would leave it."""
        self._order(link, {"side": "Buy", "orderType": "Limit", "qty": qty, "price": str(self.bid)})

    def posts(self, path: str) -> list[dict[str, Any]]:
        return [body for method, at, body in self.calls if method == "POST" and at == path]

    # -- REST -----------------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        """A signed reply carries the per-UID rate headers, as the venue's do; the adapter's
        governor reads them back, so a fast test never waits on its token bucket."""
        path = request.url.path
        if request.method == "POST":
            body = json.loads(request.content)
            self.calls.append(("POST", path, body))
        else:
            body = dict(request.url.params)
            self.calls.append(("GET", path, body))
            if self.on_get is not None:
                self.on_get(path)
        stamp = request.headers.get("X-BAPI-TIMESTAMP")
        if stamp is None:
            return self._get(path, body)
        if abs(int(stamp) - _now_ms()) > 5_000:
            reply = httpx.Response(200, json=_corpus("error_10002.json"))
        else:
            reply = self._post(path, body) if request.method == "POST" else self._get(path, body)
        reply.headers.update({"X-Bapi-Limit": "20", "X-Bapi-Limit-Status": "19"})
        reply.headers["X-Bapi-Limit-Reset-Timestamp"] = str(_now_ms())
        return reply

    def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        link = params.get("orderLinkId")
        if path == "/v5/market/time":
            self.time_reads += 1
            if self.limit_time_reads is not None and self.time_reads > self.limit_time_reads:
                return httpx.Response(200, json=_corpus("error_10018.json"))
            now = time.time_ns()
            result = {"timeSecond": str(now // 10**9), "timeNano": str(now)}
            return httpx.Response(200, json=_corpus("server_time.json") | {"result": result})
        if path == "/v5/user/query-api":
            return httpx.Response(200, json=self.key_info)
        if path == "/v5/market/instruments-info":
            reply = _corpus("instruments_before.json")
            rows = [r for r in reply["result"]["list"] if r["symbol"] == params.get("symbol")]
            reply["result"]["list"] = rows
            return httpx.Response(200, json=reply)
        if path == "/v5/market/tickers":
            touch = {"symbol": SYMBOL, "bid1Price": str(self.bid), "bid1Size": "1.000"}
            touch |= {"ask1Price": str(self.ask), "ask1Size": "1.000"}
            return httpx.Response(200, json=_ok({"category": "linear", "list": [touch]}))
        if path == "/v5/position/list":
            if self.refuse_positions is not None:
                return httpx.Response(200, json=refusal(*self.refuse_positions))
            return httpx.Response(200, json=_ok({"category": "linear", "list": [self._position()]}))
        if path in ("/v5/order/realtime", "/v5/order/history"):
            if path == "/v5/order/realtime" and link is None and self.refuse_open_orders:
                return httpx.Response(200, json=refusal(*self.refuse_open_orders))
            number = self._number.get(str(link), 0)
            if self.fail_lookups.get(number, 0) > 0:
                self.fail_lookups[number] -= 1
                return httpx.Response(503, content=(_CORPUS / "error_503.json").read_bytes())
            live = path == "/v5/order/realtime"
            rows = [
                dict(o)
                for o in self.orders.values()
                if (link is None or o["orderLinkId"] == link)
                and (o["orderStatus"] in _OPEN) == live
            ]
            return httpx.Response(200, json=_ok({"category": "linear", "list": rows}))
        if path == "/v5/execution/list":
            if self.fail_executions > 0:
                self.fail_executions -= 1
                return httpx.Response(503, content=(_CORPUS / "error_503.json").read_bytes())
            return httpx.Response(200, json=_ok({"category": "linear", "list": self.executions}))
        return httpx.Response(404)

    def _post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        link = str(body.get("orderLinkId"))
        order = self.orders.get(link)
        ack = {"orderId": order["orderId"], "orderLinkId": link} if order else {}
        if path == "/v5/order/create":
            if order is not None:
                return httpx.Response(200, json=refusal(110072, "OrderLinkedID is duplicate"))
            number = self._create_no.setdefault(link, len(self._create_no) + 1)
            refused = self.refuse_creates(number) if self.refuse_creates is not None else None
            if refused is not None:
                return httpx.Response(200, json=refusal(*refused))
            return httpx.Response(200, json=self._create(link, body))
        if path == "/v5/order/cancel" and self.cancel_raises:
            raise RuntimeError("the venue broke mid-cancel")
        if path == "/v5/order/cancel" and self.refuse_cancels is not None:
            return httpx.Response(200, json=refusal(*self.refuse_cancels))
        if order is None or order["orderStatus"] not in _OPEN:
            return httpx.Response(200, json=refusal(110001, "order not exists or too late"))
        if path == "/v5/order/amend":
            order["price"] = body["price"]
        else:
            order["orderStatus"] = "Cancelled"
        self._push("order", [order])
        return httpx.Response(200, json=_ok(ack))

    def _order(self, link: str, body: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        order = {"orderId": str(UUID(int=self._seq)), "orderLinkId": link, "symbol": SYMBOL}
        order |= {key: body[key] for key in ("side", "orderType", "qty")}
        order |= {"price": body.get("price", "0"), "leavesQty": body["qty"], "cumExecQty": "0"}
        order |= {"orderStatus": "New", "updatedTime": str(_now_ms())}
        self.orders[link] = order
        return order

    def _create(self, link: str, body: dict[str, Any]) -> dict[str, Any]:
        order = self._order(link, body)
        self._number[link] = number = len(self._number) + 1
        if self.on_create is not None:
            self.on_create(number)
        qty = Decimal(body["qty"])
        if body.get("reduceOnly") is True:
            if self.flatten_fills:
                self._fill(order, self.bid, min(qty, self.size))
            else:  # an IOC that finds no liquidity
                order["orderStatus"] = "Cancelled"
        elif Decimal(body["price"]) >= self.ask:
            self._takers += 1
            if self._takers == self.drop_on_taker:  # it fills once the stream is back
                self.drop()
                self._deferred.append(lambda: self._taker_fill(order, qty))
            else:
                self._taker_fill(order, qty)
        else:
            self._push("order", [order])
        return _ok({"orderId": order["orderId"], "orderLinkId": link})

    def _taker_fill(self, order: dict[str, Any], qty: Decimal) -> None:
        first = (qty / 2).quantize(_LOT, rounding=ROUND_DOWN) if self.split_fills else qty
        for part in (first, qty - first):
            if part > 0:
                self._fill(order, self.ask, part)

    def _fill(self, order: dict[str, Any], price: Decimal, qty: Decimal) -> None:
        """One execution of `qty` at `price`, pushed before the order and position pushes."""
        self._seq += 1
        self.size += qty if order["side"] == "Buy" else -qty
        done = Decimal(order["cumExecQty"]) + qty
        status = "Filled" if done >= Decimal(order["qty"]) else "PartiallyFilled"
        order |= {"cumExecQty": str(done), "leavesQty": str(Decimal(order["qty"]) - done)}
        order |= {"orderStatus": status, "updatedTime": str(_now_ms())}
        execution = {key: order[key] for key in ("symbol", "orderId", "orderLinkId", "side")}
        execution |= {"execId": str(UUID(int=10**9 + self._seq)), "execPrice": str(price)}
        execution |= {"execQty": str(qty), "execType": "Trade", "execTime": str(_now_ms())}
        execution["seq"] = self._seq
        self.executions.append(execution)
        self._push("execution", [execution])
        self._push("execution.fast", [execution])
        self._push("order", [order])
        self._push("position", [self._position()])

    def _position(self) -> dict[str, Any]:
        row = {"symbol": SYMBOL, "side": "Buy" if self.size else "", "size": str(self.size)}
        return row | {"positionValue": str(self.size * self.ask), "positionIdx": 0}

    # -- private stream -------------------------------------------------------------------

    def _push(self, topic: str, data: list[dict[str, Any]]) -> None:
        if self.socket is not None:
            frame = {"topic": topic, "id": f"{topic}-{self._seq}", "creationTime": _now_ms()}
            self.socket.push(frame | {"data": [dict(row) for row in data]})

    def _subscribed(self) -> None:
        deferred, self._deferred = self._deferred, []
        for action in deferred:
            action()
