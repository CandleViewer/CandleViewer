"""The offline edges (#843 A4 brief item 3): the corpus venue behind the two seams, and the stack
the harness would find on the host, in memory.

`CorpusVenue` answers the real port's REST calls and pushes the real private stream's frames, and
every answer is a shape of the recorded corpus (`packages/fixtures/bybit/2026-10-05/`): its values
are patched, its keys never (`patched` refuses a key the corpus row lacks; C-13.5, the
`with_result` rule of #2877 ruling R2). It keeps a small book of its own: an order away from the
touch rests; one that joins the touch fills one quantity step (a partial fill), one that crosses
it fills whole; a reduce-only market order closes the position. It answers `10002` to a request
signed outside the receive window, the transcribed `110072` to a reused `orderLinkId`, and
`10018` only when a test asks for one. `drop_every` and `reorder_every` withhold every Nth fill
from the stream or push its order update first, so the parity and ordering counters can be seen
to count; a run that sets either says so in its summary. Its list reads page by the request's
`limit`, each `nextPageCursor` in its corpus row's own form (R1C-08), so a run long enough to
list more than a page reads every page, as on the venue. A test can rest an order (on BTCUSDT or
another symbol), fill one or hold a position no run placed (`rest_foreign_order`, `fill_foreign`,
`hold_foreign_position`): the account's other users, which the harness must never touch. The
open-orders read answers the request's `symbol`, or every symbol for the `settleCoin` form. It
serves no cancel-all: the harness never sends one (ruling R1C-02 (b)), and one sent would be
refused here as an unknown route. Its key-info read (`GET /v5/user/query-api`) answers
`key_info`: by default the accounts pack's compliant reply (`packages/fixtures/accounts`, E27-Q01,
the key-info corpus), and a test serves another of that pack's replies (a withdrawal right, a
transfer right, no IP binding) through the pack's resolver.

`offline_stack` stands in for the host: the stack's M2 boots once over an in-memory store (which
enrols the KEK's check value, as cv-api's first boot does) and the owner imports one synthetic
key through M2's own import capability. The KEK is read as a file source, as on the demo host
(#4522's `CV_KEK_SOURCE=file`). The harness then composes over the same store exactly as it would
over Postgres (`compose.py`). Nothing here runs online, and nothing in it is a key.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import re
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Final, cast
from uuid import UUID, uuid4

import httpx

from candleviewer.admin.wiring import secrets_bundle
from candleviewer.audit.repository import AuditRepository
from candleviewer.observability.secret_type import Secret as Pasted
from candleviewer.secrets import SecretsService, StoredCredential
from candleviewer.secrets.store import InMemoryCredentialStore
from candleviewer.settings import Environment, Settings
from spike.oms_demo_path.config import DEMO_REST_HOST, SYMBOL
from spike.oms_demo_path.safety import Refused

CAPTURE: Final = "2026-10-05"
#: The venue's own account number in offline frames (a synthetic UID, as the push ids carry one).
OFFLINE_UID: Final = "100000001"
_QUEUE_BOUND: Final = 10_000
_DROP: Final = "\x00drop"
_TAKER, _MAKER = Decimal("0.00055"), Decimal("0.0002")
_OPEN: Final = frozenset({"New", "PartiallyFilled"})
#: A list read with no `limit`: the venue's own default page.
_DEFAULT_LIMIT: Final = 50
#: Where each list's corpus cursor carries a number: the offset of the next page goes there.
_CURSOR_NUMBER: Final = {
    "trading-execution-list": re.compile(r"^(\d+)(%3A\d+%2C)(\d+)"),
    "trading-order-realtime": re.compile(r"(symbol%3D)(\d+)(%26)$"),
    "trading-order-history": re.compile(r"(page_token%3D)(\d+)(%26)$"),
}


def default_corpus() -> Path:
    """The corpus beside this checkout: `services/api/spike/oms_demo_path` -> repository root."""
    return Path(__file__).resolve().parents[4] / "packages" / "fixtures" / "bybit" / CAPTURE


def default_accounts_pack() -> Path:
    """The accounts pack beside this checkout (E27-Q01): the corpus of key-info replies."""
    return Path(__file__).resolve().parents[4] / "packages" / "fixtures" / "accounts"


#: The key-info call, as the accounts pack's manifests name its stub.
KEY_INFO_STUB: Final = "GET /v5/user/query-api"


def key_info_reply(pack: Path | None = None) -> dict[str, Any]:
    """The accounts pack's compliant key-info reply: the payload its root scenario, `compliant`,
    answers `GET /v5/user/query-api` with, as the pack holds it (the harness judges rights and the
    allow-list, so the pack's clock anchoring is not applied)."""
    root = default_accounts_pack() if pack is None else pack
    manifest = json.loads((root / "compliant" / "manifest.json").read_text(encoding="utf-8"))
    payload = root / str(manifest["rest"][KEY_INFO_STUB]["payload"])
    body: dict[str, Any] = json.loads(payload.read_text(encoding="utf-8"))
    return body


def _wall_ms() -> int:
    return int(time.time() * 1000)


def _text(value: Decimal) -> str:
    return format(value, "f")


def patched(shape: Mapping[str, Any], **values: Any) -> dict[str, Any]:
    """`shape` with values replaced; a key the corpus shape does not hold is refused, so no
    answer is ever a hand-written shape (C-13.5)."""
    missing = sorted(set(values) - set(shape))
    if missing:
        raise KeyError(f"not in the corpus shape: {missing}")
    return {**shape, **values}


class Corpus:
    """The recorded corpus, read once per file."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: dict[str, Any] = {}

    def _load(self, rel: str) -> Any:
        if rel not in self._cache:
            text = (self.root / rel).read_text(encoding="utf-8")
            if rel.endswith(".jsonl"):
                [line] = [x for x in text.splitlines() if x.strip()]
                self._cache[rel] = line
            else:
                self._cache[rel] = json.loads(text)
        return self._cache[rel]

    def rest(self, name: str) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(json.dumps(self._load(f"rest/{name}.json")))
        return body

    def line(self, name: str) -> str:
        line: str = self._load(f"ws/private-{name}.jsonl")
        return line

    def push(self, name: str) -> dict[str, Any]:
        frame: dict[str, Any] = json.loads(self.line(name))
        return frame


@dataclass
class VenueOrder:
    order_id: str
    link: str
    side: str
    order_type: str
    qty: Decimal
    price: Decimal
    tif: str
    reduce_only: bool
    stop_loss: Decimal | None
    created_ms: int
    updated_ms: int
    status: str = "New"
    filled: Decimal = Decimal(0)
    value: Decimal = Decimal(0)
    symbol: str = SYMBOL

    @property
    def avg(self) -> Decimal | None:
        return None if not self.filled else (self.value / self.filled).quantize(Decimal("0.01"))

    @property
    def leaves(self) -> Decimal:
        return self.qty - self.filled if self.status in _OPEN else Decimal(0)


@dataclass
class VenueSocket:
    """One private socket: answers `auth`, `subscribe` and `ping` with the corpus's replies."""

    venue: CorpusVenue
    inbox: asyncio.Queue[str] = field(default_factory=lambda: asyncio.Queue(_QUEUE_BOUND))
    closed: bool = False

    async def send(self, frame: str) -> None:
        if self.closed:
            raise ConnectionError("socket closed")
        op = json.loads(frame).get("op")
        corpus = self.venue.corpus
        if op == "auth":
            reply = self.venue.auth_reply()
        elif op == "subscribe":
            reply = corpus.line("subscribe-ok")
        elif op == "ping":
            reply = corpus.line("pong")
        else:
            return
        self.inbox.put_nowait(reply)

    async def recv(self, max_bytes: int) -> str:
        frame = await self.inbox.get()
        if frame == _DROP:
            raise ConnectionResetError("the venue dropped the connection")
        return frame

    async def close(self) -> None:
        self.closed = True
        self.drop()

    def drop(self) -> None:
        self.inbox.put_nowait(_DROP)


class CorpusVenue:
    """The offline venue (see the module docstring)."""

    def __init__(
        self,
        corpus: Corpus,
        *,
        now_ms: Callable[[], int] = _wall_ms,
        tick: Decimal = Decimal("0.10"),
        step: Decimal = Decimal("0.001"),
        drop_every: int = 0,
        reorder_every: int = 0,
        rate_limit_once: bool = False,
        refuse_auth: int = 0,
        key_info: Mapping[str, Any] | None = None,
    ) -> None:
        self.corpus = corpus
        self.now_ms = now_ms
        trades = corpus.rest("recent_trade_BTCUSDT")["result"]["list"]
        self.ref = Decimal(trades[0]["price"])
        self.tick, self.step = tick, step
        self.drop_every, self.reorder_every = drop_every, reorder_every
        self.rate_limit_once = rate_limit_once
        self.refuse_auth = refuse_auth
        #: What `GET /v5/user/query-api` answers: an accounts-pack reply, whole.
        self.key_info: dict[str, Any] = (
            key_info_reply() if key_info is None else json.loads(json.dumps(key_info))
        )
        self.orders: dict[str, VenueOrder] = {}
        self.links: set[str] = set()
        self.executions: list[dict[str, Any]] = []
        self.creates: list[dict[str, Any]] = []
        #: Every REST path the venue served, in order (what a refused run must never have sent).
        self.paths: list[str] = []
        self.sockets: list[VenueSocket] = []
        self.size = Decimal(0)  # signed: long > 0
        self.entry: Decimal | None = None
        self.stop: Decimal | None = None
        self.fills = self.dropped = self.reordered = 0
        self._seq = itertools.count(4_688_002_127)
        self._ids = itertools.count(1)

    # -- the book's touch: bid at the reference price, ask one tick above ---------------------

    @property
    def bid(self) -> Decimal:
        return self.ref

    @property
    def ask(self) -> Decimal:
        return self.ref + self.tick

    # -- the private socket -------------------------------------------------------------------

    async def connect(self, url: str) -> VenueSocket:
        sock = VenueSocket(self)
        self.sockets.append(sock)
        return sock

    def auth_reply(self) -> str:
        frame = self.corpus.push("auth-ok")
        if self.refuse_auth > 0:
            self.refuse_auth -= 1
            frame = patched(frame, success=False)
        return json.dumps(frame, separators=(",", ":"))

    def _send(self, name: str, *rows: dict[str, Any]) -> None:
        frame = self.corpus.push(name)
        values: dict[str, Any] = {"data": list(rows), "creationTime": self.now_ms()}
        if "id" in frame:
            values["id"] = f"{OFFLINE_UID}_{SYMBOL}_{next(self._seq)}"
        text = json.dumps(patched(frame, **values), separators=(",", ":"))
        for sock in self.sockets:
            if not sock.closed:
                sock.inbox.put_nowait(text)

    # -- REST -----------------------------------------------------------------------------------

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != DEMO_REST_HOST:
            raise Refused("the offline venue serves the demo host only")
        self.paths.append(request.url.path)
        skewed = self._skewed(request)
        if skewed is not None:
            return skewed
        if self.rate_limit_once:
            self.rate_limit_once = False
            return self._reply(self.corpus.rest("error_10018"))
        body: dict[str, Any] = json.loads(request.content) if request.method == "POST" else {}
        params = dict(request.url.params)
        name = request.url.path.removeprefix("/v5/").replace("/", "_").replace("-", "_")
        route = getattr(self, f"_{name}", None)
        if route is None:
            raise Refused(f"the offline venue has no route for {request.url.path}")
        reply: dict[str, Any] = route(body, params)
        return self._reply(reply)

    def _reply(self, body: dict[str, Any]) -> httpx.Response:
        if "time" in body:
            body = patched(body, time=self.now_ms())
        return httpx.Response(200, json=body)

    def _skewed(self, request: httpx.Request) -> httpx.Response | None:
        """The venue's rule: `server - recv_window <= timestamp < server + 1000`, else 10002."""
        stamp = request.headers.get("X-BAPI-TIMESTAMP")
        window = request.headers.get("X-BAPI-RECV-WINDOW")
        if stamp is None or window is None:
            return None
        now = self.now_ms()
        if now - int(window) <= int(stamp) < now + 1000:
            return None
        return self._reply(self.corpus.rest("error_10002"))

    def _ok(self, name: str, **result: Any) -> dict[str, Any]:
        shape = self.corpus.rest(name)
        return patched(shape, result=patched(shape["result"], **result))

    def _order_create(self, body: dict[str, Any], _params: dict[str, str]) -> dict[str, Any]:
        self.creates.append(body)
        link = str(body["orderLinkId"])
        if link in self.links:
            return self.corpus.rest("trading-error-110072")
        self.links.add(link)
        now = self.now_ms()
        is_market = body["orderType"] == "Market"
        order = VenueOrder(
            order_id=str(uuid4()),
            link=link,
            side=str(body["side"]),
            order_type=str(body["orderType"]),
            qty=Decimal(body["qty"]),
            price=Decimal(0) if is_market else Decimal(body["price"]),
            tif=str(body["timeInForce"]),
            reduce_only=bool(body["reduceOnly"]),
            stop_loss=Decimal(body["stopLoss"]) if "stopLoss" in body else None,
            created_ms=now,
            updated_ms=now,
        )
        self.orders[order.order_id] = order
        self._send("order", self._push_order(order))
        self._match(order)
        return self._ok("trading-create-reply", orderId=order.order_id, orderLinkId=link)

    def _find(self, body: Mapping[str, Any]) -> VenueOrder | None:
        if "orderId" in body:
            return self.orders.get(str(body["orderId"]))
        return next((o for o in self.orders.values() if o.link == body.get("orderLinkId")), None)

    def _order_amend(self, body: dict[str, Any], _params: dict[str, str]) -> dict[str, Any]:
        order = self._find(body)
        if order is None or order.status not in _OPEN:
            return self.corpus.rest("trading-error-110001")
        if "price" in body:
            order.price = Decimal(body["price"])
        if "qty" in body:
            order.qty = Decimal(body["qty"])
        if "stopLoss" in body:
            order.stop_loss = Decimal(body["stopLoss"])
        order.updated_ms = self.now_ms()
        self._send("order", self._push_order(order))
        self._match(order)
        return self._ok("trading-amend-reply", orderId=order.order_id, orderLinkId=order.link)

    def _order_cancel(self, body: dict[str, Any], _params: dict[str, str]) -> dict[str, Any]:
        order = self._find(body)
        if order is None or order.status not in _OPEN:
            return self.corpus.rest("trading-error-110001")
        self._cancel(order)
        return self._ok("trading-cancel-reply", orderId=order.order_id, orderLinkId=order.link)

    def _cancel(self, order: VenueOrder) -> None:
        order.status = "PartiallyFilledCanceled" if order.filled else "Cancelled"
        order.updated_ms = self.now_ms()
        self._send("order", self._push_order(order))

    def _order_realtime(self, _body: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
        symbol = params.get("symbol")  # none: the `settleCoin` form, every symbol
        rows = [o for o in self.orders.values() if o.status in _OPEN and symbol in (None, o.symbol)]
        return self._order_page("trading-order-realtime", rows, params)

    def _order_history(self, _body: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
        low, high = int(params.get("startTime", 0)), int(params.get("endTime", 2**62))
        rows = [o for o in self.orders.values() if low <= o.created_ms <= high]
        return self._order_page("trading-order-history", rows, params)

    def _paged(
        self, name: str, rows: list[Any], params: Mapping[str, str]
    ) -> tuple[list[Any], str]:
        """One page of `rows` by the request's `limit` from its `cursor`, and the next page's
        cursor in the corpus row's own form (`""` after the last page)."""
        limit = int(params.get("limit", _DEFAULT_LIMIT))
        cursor = params.get("cursor", "")
        form = _CURSOR_NUMBER[name]
        start = 0
        if cursor:
            found = form.search(cursor)
            if found is None:
                raise Refused("the offline venue issued no such cursor")
            start = int(found.group(1 if name == "trading-execution-list" else 2))
        end = start + limit
        if end >= len(rows):
            return rows[start:end], ""
        template = str(self.corpus.rest(name)["result"]["nextPageCursor"])
        if name == "trading-execution-list":
            following = form.sub(lambda m: f"{end}{m.group(2)}{end}", template)
        else:
            following = form.sub(lambda m: f"{m.group(1)}{end}{m.group(3)}", template)
        return rows[start:end], following

    def _order_page(
        self, name: str, orders: list[VenueOrder], params: Mapping[str, str]
    ) -> dict[str, Any]:
        link, order_id = params.get("orderLinkId"), params.get("orderId")
        chosen = [o for o in orders if link in (None, o.link) and order_id in (None, o.order_id)]
        page, following = self._paged(name, chosen, params)
        shape = self.corpus.rest(name)
        [row] = shape["result"]["list"]
        result = patched(
            shape["result"],
            list=[self._order_row(row, o) for o in page],
            nextPageCursor=following,
        )
        return patched(shape, result=result)

    def _position_list(self, _body: dict[str, Any], _params: dict[str, str]) -> dict[str, Any]:
        shape = self.corpus.rest("trading-position-list")
        [row] = shape["result"]["list"]
        result = patched(
            shape["result"], list=[self._position_row(row, rest=True)], category="linear"
        )
        return patched(shape, result=result)

    def _execution_list(self, _body: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
        low, high = int(params.get("startTime", 0)), int(params.get("endTime", 2**62))
        rows = [e for e in self.executions if low <= int(e["execTime"]) <= high]
        page, following = self._paged("trading-execution-list", rows, params)
        shape = self.corpus.rest("trading-execution-list")
        return patched(shape, result=patched(shape["result"], list=page, nextPageCursor=following))

    def _account_wallet_balance(
        self, _body: dict[str, Any], _params: dict[str, str]
    ) -> dict[str, Any]:
        shape = self.corpus.rest("trading-wallet-balance")
        [account] = shape["result"]["list"]
        [coin] = account["coin"]
        unified = patched(account, coin=[patched(coin, coin="USDT", walletBalance="50000")])
        return patched(shape, result=patched(shape["result"], list=[unified]))

    def _user_query_api(self, _body: dict[str, Any], _params: dict[str, str]) -> dict[str, Any]:
        """The key-info read: `key_info`, a fresh copy (its envelope `time` the venue's)."""
        reply: dict[str, Any] = json.loads(json.dumps(self.key_info))
        return reply

    # -- matching -----------------------------------------------------------------------------

    def _match(self, order: VenueOrder) -> None:
        """The book's rule: a market order fills whole at the touch; a limit order through the
        touch fills whole at it, one at the touch fills one step at its own price."""
        if order.status not in _OPEN:
            return
        buy = order.side == "Buy"
        if order.reduce_only:
            held = abs(self.size)
            if not held or (self.size > 0) == buy:
                return
            qty = min(order.leaves, held)
        else:
            qty = order.leaves
        if order.order_type == "Market":
            self._fill(order, qty, self.ask if buy else self.bid, maker=False)
        elif (buy and order.price >= self.ask) or (not buy and order.price <= self.bid):
            self._fill(order, qty, self.ask if buy else self.bid, maker=False)
        elif (buy and order.price >= self.bid) or (not buy and order.price <= self.ask):
            self._fill(order, min(self.step, qty), order.price, maker=True)

    def _fill(self, order: VenueOrder, qty: Decimal, price: Decimal, *, maker: bool) -> None:
        now, seq = self.now_ms(), next(self._seq)
        self.fills += 1
        order.filled += qty
        order.value += qty * price
        order.status = "Filled" if order.filled >= order.qty else "PartiallyFilled"
        order.updated_ms = now
        signed = qty if order.side == "Buy" else -qty
        if not order.reduce_only and self.size == 0:
            self.stop, self.entry = order.stop_loss, price
        self.size += signed
        if self.size == 0:
            self.stop = self.entry = None
        fee = (qty * price * (_MAKER if maker else _TAKER)).quantize(Decimal("0.00000001"))
        exec_id = str(uuid4())
        rest_row = self.corpus.rest("trading-execution-list")["result"]["list"][0]
        self.executions.append(self._exec_row(rest_row, order, exec_id, qty, price, fee, maker))
        drop = bool(self.drop_every) and self.fills % self.drop_every == 0
        reorder = bool(self.reorder_every) and self.fills % self.reorder_every == 0
        self.dropped += drop
        self.reordered += reorder and not drop
        order_row = self._push_order(order)
        if reorder and not drop:
            self._send("order", order_row)
        if not drop:
            fast = self.corpus.push("execution-fast")["data"][0]
            self._send("execution-fast", self._fast_row(fast, order, exec_id, qty, price, maker))
            push = self.corpus.push("execution")["data"][0]
            row = self._exec_row(push, order, exec_id, qty, price, fee, maker)
            self._send("execution", patched(row, category="linear"))
        if not reorder or drop:
            self._send("order", order_row)
        position = self.corpus.push("position")["data"][0]
        self._send("position", self._position_row(position, rest=False, seq=seq))

    # -- rows, each a corpus row with its values patched ----------------------------------------

    def _order_row(self, row: Mapping[str, Any], o: VenueOrder) -> dict[str, Any]:
        avg = o.avg
        values: dict[str, Any] = {
            "orderId": o.order_id,
            "orderLinkId": o.link,
            "symbol": o.symbol,
            "price": _text(o.price),
            "qty": _text(o.qty),
            "side": o.side,
            "positionIdx": 0,
            "orderStatus": o.status,
            "avgPrice": "0" if avg is None else _text(avg),
            "leavesQty": _text(o.leaves),
            "leavesValue": _text(o.leaves * o.price),
            "cumExecQty": _text(o.filled),
            "cumExecValue": _text(o.value),
            "timeInForce": o.tif,
            "orderType": o.order_type,
            "stopOrderType": "",
            "triggerPrice": "",
            "takeProfit": "",
            "stopLoss": "" if o.stop_loss is None else _text(o.stop_loss),
            "tpslMode": "" if o.stop_loss is None else "Full",
            "reduceOnly": o.reduce_only,
            "createdTime": str(o.created_ms),
            "updatedTime": str(o.updated_ms),
        }
        return patched(row, **values)

    def _push_order(self, order: VenueOrder) -> dict[str, Any]:
        row = self.corpus.push("order")["data"][0]
        return patched(self._order_row(row, order), category="linear")

    def _exec_row(
        self,
        row: Mapping[str, Any],
        o: VenueOrder,
        exec_id: str,
        qty: Decimal,
        price: Decimal,
        fee: Decimal,
        maker: bool,
    ) -> dict[str, Any]:
        return patched(
            row,
            symbol=SYMBOL,
            orderId=o.order_id,
            orderLinkId=o.link,
            side=o.side,
            orderType=o.order_type,
            orderPrice=_text(o.price),
            orderQty=_text(o.qty),
            leavesQty=_text(o.leaves),
            execId=exec_id,
            execPrice=_text(price),
            execQty=_text(qty),
            execValue=_text(qty * price),
            execFee=_text(fee),
            feeRate=_text(_MAKER if maker else _TAKER),
            feeCurrency="USDT",
            execType="Trade",
            execTime=str(self.now_ms()),
            isMaker=maker,
            seq=next(self._seq),
            stopOrderType="UNKNOWN",
        )

    def _fast_row(
        self,
        row: Mapping[str, Any],
        o: VenueOrder,
        exec_id: str,
        qty: Decimal,
        price: Decimal,
        maker: bool,
    ) -> dict[str, Any]:
        return patched(
            row,
            symbol=SYMBOL,
            execId=exec_id,
            execPrice=_text(price),
            execQty=_text(qty),
            orderId=o.order_id,
            orderLinkId=o.link,
            side=o.side,
            isMaker=maker,
            execTime=str(self.now_ms()),
            seq=next(self._seq),
        )

    def _position_row(
        self, row: Mapping[str, Any], *, rest: bool, seq: int | None = None
    ) -> dict[str, Any]:
        side = "" if self.size == 0 else ("Buy" if self.size > 0 else "Sell")
        entry = "0" if self.entry is None else _text(self.entry)
        values: dict[str, Any] = {
            "positionIdx": 0,
            "symbol": SYMBOL,
            "side": side,
            "size": _text(abs(self.size)),
            "markPrice": _text(self.ref),
            "stopLoss": "0" if self.stop is None else _text(self.stop),
            "takeProfit": "0",
            "updatedTime": str(self.now_ms()),
        }
        values["avgPrice" if rest else "entryPrice"] = entry
        if not rest:
            values |= {"category": "linear", "seq": next(self._seq) if seq is None else seq}
        return patched(row, **values)

    # -- the public market reads, offline -----------------------------------------------------

    async def get_public(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        """The two public reads the harness makes, from the corpus: the last trades (patched to
        the venue's reference price) and the instruments row of the symbol."""
        if path == "/v5/market/recent-trade":
            shape = self.corpus.rest("recent_trade_BTCUSDT")
            rows = [patched(r, price=_text(self.ref)) for r in shape["result"]["list"]]
            return patched(shape, result=patched(shape["result"], list=rows))
        if path == "/v5/market/instruments-info":
            shape = self.corpus.rest("instruments_before")
            symbol = (params or {}).get("symbol")
            rows = [r for r in shape["result"]["list"] if symbol in (None, r["symbol"])]
            return patched(shape, result=patched(shape["result"], list=rows))
        raise Refused(f"no offline public read for {path}")

    def seed_history(self, count: int, *, age_days: float, status: str = "Cancelled") -> None:
        """Orders the venue holds from an earlier run, `age_days` old (the retention probe)."""
        created = self.now_ms() - int(age_days * 86_400_000)
        for _ in range(count):
            order = VenueOrder(
                order_id=str(uuid4()),
                link=f"cvd-0{secrets.token_hex(10)[:21]}-0000-00en",
                side="Buy",
                order_type="Limit",
                qty=self.step * 2,
                price=(self.ref * Decimal("0.99")).quantize(self.tick, ROUND_DOWN),
                tif="GTC",
                reduce_only=False,
                stop_loss=(self.ref * Decimal("0.97")).quantize(self.tick, ROUND_DOWN),
                created_ms=created,
                updated_ms=created,
                status=status,
            )
            self.orders[order.order_id] = order

    def rest_foreign_order(self, symbol: str = SYMBOL) -> VenueOrder:
        """An order no run of the harness placed (a manual one: no `orderLinkId`), resting
        away from the touch, on `symbol`."""
        now = self.now_ms()
        order = VenueOrder(
            order_id=str(uuid4()),
            link="",
            side="Buy",
            order_type="Limit",
            qty=self.step * 3,
            price=(self.ref * Decimal("0.95")).quantize(self.tick, ROUND_DOWN),
            tif="GTC",
            reduce_only=False,
            stop_loss=None,
            created_ms=now,
            updated_ms=now,
            symbol=symbol,
        )
        self.orders[order.order_id] = order
        return order

    def fill_foreign(self, qty: Decimal) -> VenueOrder:
        """A manual market buy no run placed (no `orderLinkId`), filled whole at the touch now:
        its execution listed and pushed as any fill's, and the position it opens (R2-11: inside
        a run's window, so a run that took every fill for its own would close it)."""
        now = self.now_ms()
        order = VenueOrder(
            order_id=str(uuid4()),
            link="",
            side="Buy",
            order_type="Market",
            qty=qty,
            price=Decimal(0),
            tif="IOC",
            reduce_only=False,
            stop_loss=None,
            created_ms=now,
            updated_ms=now,
        )
        self.orders[order.order_id] = order
        self._send("order", self._push_order(order))
        self._fill(order, qty, self.ask, maker=False)
        return order

    def hold_foreign_position(self, qty: Decimal) -> None:
        """A position no run opened (signed: long > 0), as a manual trade would leave it; it
        nets with the runs' own in the one-way position, as on the venue."""
        if self.size == 0:
            self.entry = self.ref
        self.size += qty

    def list_fills(self, count: int) -> None:
        """`count` executions the list holds and the stream never pushed, of an order no run
        placed: the list's paging, exercised."""
        for _ in range(count):
            self.plant_unpushed_fill()

    def plant_unpushed_fill(self) -> str:
        """One fill the execution list holds and the stream never pushed, of an order no run
        placed (a manual taker fill, no `orderLinkId`): the missed execution a soak's idle phase
        must count. Its `execId`."""
        now = self.now_ms()
        order = VenueOrder(
            order_id=str(uuid4()),
            link="",
            side="Buy",
            order_type="Market",
            qty=self.step,
            price=Decimal(0),
            tif="IOC",
            reduce_only=False,
            stop_loss=None,
            created_ms=now,
            updated_ms=now,
            status="Filled",
            filled=self.step,
            value=self.step * self.ask,
        )
        exec_id = str(uuid4())
        row = self.corpus.rest("trading-execution-list")["result"]["list"][0]
        fee = (self.step * self.ask * _TAKER).quantize(Decimal("0.00000001"))
        self.executions.append(
            self._exec_row(row, order, exec_id, self.step, self.ask, fee, maker=False)
        )
        self.dropped += 1
        return exec_id


# -- the stack the harness meets on the host, in memory ----------------------------------------


class MemoryAuditRepository:
    """The audit writer's one call (`insert`), in memory: the fake audit sink behind the real
    `AuditWriter`, so the harness's own WAL directory is exercised offline too."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def insert(self, record: dict[str, Any]) -> None:
        self.records.append(record)

    def actions(self) -> list[str]:
        return [str(r["action"]) for r in self.records]


def as_audit_repository(repo: MemoryAuditRepository) -> AuditRepository:
    """The writer calls `insert` only (`audit/writer.py`); the query side is never started."""
    return cast("AuditRepository", repo)


def assume_hardened() -> bool:
    """Offline only: the test process keeps its core dumps and ptrace (SR-009's `harden_process`
    would change them for the whole session); online M2 runs its own hardening."""
    return True


def offline_settings(state: Path) -> Settings:
    """Demo settings over a KEK file made for this run in `state` (0400, 32 random bytes, never
    written anywhere else and removed with the state directory), read as a file source as on the
    demo host (#4522), and the harness's own WAL."""
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    kek = state / "kek-offline.bin"
    if not kek.exists():
        fd = os.open(kek, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        try:
            os.write(fd, secrets.token_bytes(32))
        finally:
            os.close(fd)
    return Settings(  # type: ignore[call-arg]  # pydantic-settings' `_env_file` keyword
        _env_file=None,
        environment=Environment.DEMO,
        kek_source="file",
        kek_handle=str(kek),
        kek_version=1,
        audit_wal_path=str(state / "spike-audit" / "spike" / "audit.wal"),
    )


@dataclass(frozen=True)
class OfflineStack:
    store: InMemoryCredentialStore
    account_id: UUID
    key_ref: str


async def _discard(_action: str, _fields: dict[str, str]) -> None:
    return None


def _snapshot(fixture: Path) -> dict[str, Any]:
    """The synthetic account fixture's permission snapshot, its transfer right removed (C-2.8)."""
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    snapshot: dict[str, Any] = raw["accounts"][0]["permission_snapshot"]
    snapshot["permissions"]["Wallet"] = []
    return snapshot


async def offline_stack(
    settings: Settings, ctx: Any, *, accounts_fixture: Path, account_id: UUID | None = None
) -> OfflineStack:
    """cv-api's first boot (the KEK check value enrolled) and the owner's key import, in memory:
    the import goes through M2's own capability with a synthetic pasted pair, for the account
    `account_id` (a fresh one by default; a `flatten` test names its failed run's)."""
    store = InMemoryCredentialStore()
    stack = SecretsService(store=store, kcv_store=store, audit=_discard, harden=assume_hardened)
    bundle = secrets_bundle(stack)
    await bundle.lifecycle.start(ctx)
    account_id = uuid4() if account_id is None else account_id
    snapshot = _snapshot(accounts_fixture)

    async def check(_signer: object) -> Mapping[str, Any]:
        return snapshot

    async def activate(stored: StoredCredential) -> None:
        store.activate(stored.key_id)

    try:
        stored = await bundle.candidate_keys.store_if_verified(
            "demo",
            account_id,
            "spike-offline",
            Pasted(secrets.token_hex(9)),
            Pasted(secrets.token_hex(24)),
            check,
            actor_user_id=str(uuid4()),
            actor_role="owner",
            activate=activate,
        )
    finally:
        await bundle.lifecycle.stop(1.0)
    if stored is None:  # pragma: no cover - the check above always passes
        raise Refused("the offline key import was refused")
    return OfflineStack(store=store, account_id=account_id, key_ref=str(stored.key_id))


def default_accounts_fixture() -> Path:
    """The synthetic accounts fixture beside this checkout (its permission snapshot only)."""
    return (
        Path(__file__).resolve().parents[4] / "packages" / "fixtures" / "accounts" / "accounts.json"
    )
