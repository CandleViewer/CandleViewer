"""The two runs of the E29-K01 harness (#843) on the demo account.

`orders`: N cycles over a duration (defaults 200 and 4 h). A cycle reads the touch and the REST
position (exposure cap), places a small Buy limit carrying a native stopLoss (C-2.6) at the bid
(every `taker_every`-th cycle one tick through the ask, so fills happen), waits for a fill on the
private stream, amends the rest one tick lower and cancels it. The first order is sent twice with
the same `orderLinkId` (the duplicate capture, C-2.10). Whatever happens, the run cancels what it
left open and flattens what it opened. `soak`: the private stream alone. Both end with a REST
execution backfill over the run window and always write the run directory.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Final, Literal
from uuid import uuid4

import httpx
import structlog

from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import (
    AuthError,
    ClockDriftError,
    DuplicateClientIdError,
    ExchangeError,
    RateLimitError,
    TransportError,
    UnknownStateError,
)
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.instruments import parse_instrument
from candleviewer.exchange.bybit.key_info import KEY_INFO_PATH, parse_key_info
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.signer import BybitSigner
from candleviewer.observability.metrics import CONTENT_TYPE_LATEST, Metrics, generate_latest
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms.order_link import OrderPurpose

from .capture import FixtureSink, RestRecorder, labelled
from .report import build_report, write_outputs
from .safety import (
    DEMO,
    DEMO_REST_BASE,
    MAX_ORDER_NOTIONAL,
    MAX_RUN_EXPOSURE,
    SYMBOLS,
    EnvCredentials,
    GuardedTransport,
    SafetyRefusal,
    check_permissions,
    new_link,
)
from .scrub import Scrubber
from .stats import EXEC_TOPICS, WsItem, as_decimal, items_from_frame
from .stream import PrivateStream

SKEW_MS: Final = 30_000  # far outside the 5 s recv_window: the 10002 capture
BURST_CEILING: Final = 1000
_OPEN: Final = ("New", "PartiallyFilled", "Untriggered")
#: A create that may have landed: looked up by its `orderLinkId` (24 §8.3 rule 3), never re-sent.
_UNRESOLVED: Final = (DuplicateClientIdError, TransportError, UnknownStateError)
_MAX_ITEMS: Final = 500_000
_MAX_PAGES: Final = 100


def _log() -> Any:
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Config:
    mode: Literal["orders", "soak"]
    symbol: str
    out: Path
    staging: Path
    hours: float
    orders: int = 200
    lots: int = 5
    max_order_usdt: Decimal = MAX_ORDER_NOTIONAL
    max_exposure_usdt: Decimal = MAX_RUN_EXPOSURE
    sl_pct: Decimal = Decimal("0.02")
    fill_wait_s: float = 30.0
    taker_every: int = 5
    capture_10002: bool = False
    capture_10018: bool = False
    burst_max: int = 700
    retention_probe: Path | None = None
    metrics_port: int = 0

    def __post_init__(self) -> None:
        if self.symbol not in SYMBOLS:
            raise SafetyRefusal("symbol is not on the allow-list")
        if not (0 < self.max_order_usdt <= MAX_ORDER_NOTIONAL):
            raise SafetyRefusal("the per-order cap may only be lowered")
        if not (0 < self.max_exposure_usdt <= MAX_RUN_EXPOSURE):
            raise SafetyRefusal("the run exposure cap may only be lowered")
        if not (0 < self.sl_pct <= Decimal("0.1")) or self.lots < 2 or self.orders < 1:
            raise SafetyRefusal("need 0 < sl-pct <= 10, lots >= 2 and orders >= 1")
        if not (0 < self.burst_max <= BURST_CEILING) or self.hours <= 0:
            raise SafetyRefusal(f"need 0 < burst-max <= {BURST_CEILING} and hours > 0")


def _rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    result = body.get("result")
    rows = result.get("list") if isinstance(result, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _need(value: object, what: str) -> Decimal:
    parsed = as_decimal(value)
    if parsed is None:
        raise SafetyRefusal(f"malformed {what} in an exchange reply")
    return parsed


def _code(error: ExchangeError | None) -> str:
    return "0" if error is None else str(error.exchange_ret_code or type(error).__name__)


def _describe(error: ExchangeError | None) -> str:
    if error is None:
        return "accepted (retCode 0)"
    return f"retCode {error.exchange_ret_code}: {type(error).__name__} ({error.code.value})"


def _plain_ok(reply: httpx.Response) -> bool:
    try:
        body = reply.json()
    except ValueError:
        return False
    return reply.status_code == 200 and isinstance(body, dict) and body.get("retCode") == 0


def _why(exc: BaseException) -> str:
    leaves = exc.exceptions if isinstance(exc, BaseExceptionGroup) else (exc,)
    return "stopped early: " + "; ".join(f"{type(e).__name__}: {e}" for e in leaves)


class Harness:
    def __init__(self, cfg: Config, creds: EnvCredentials) -> None:
        self.cfg, self.symbol = cfg, cfg.symbol
        self.scrubber = Scrubber([creds.key_id])
        self.recorder = RestRecorder(self.scrubber)
        self.governor = TokenBucketGovernor()
        self.signer = BybitSigner(creds, uuid4())
        self.metrics = Metrics(DEMO)
        spec = next(s for s in CATALOGUE if s.name == "order_submit_seconds")
        self.submit = self.metrics.histogram(
            spec.name, spec.help, spec.labels, buckets=spec.buckets or (), max_series=4
        )
        self.offset_ms, self.offset_err_ms, self.started_ms = 0, 0.0, 0
        self.client = self._client(lambda: self.offset_ms)
        today = datetime.now(UTC).date().isoformat()
        self.sink = FixtureSink(
            cfg.staging, symbol=cfg.symbol, mode=cfg.mode, date=today, scrubber=self.scrubber
        )
        self.stream = PrivateStream(self.signer, self._on_frame, now_ms=self.now_ms)
        self.items: list[WsItem] = []
        self.fills: dict[str, asyncio.Event] = {}
        self.links: set[str] = set()
        self.rows: list[dict[str, Any]] = []
        self.submit_ms: list[float] = []
        self.notes: dict[str, Any] = {}
        self.account_id = AccountId(uuid4())
        self.inst: Instrument | None = None
        self.stopping = asyncio.Event()
        self._failures = 0

    def now_ms(self) -> int:
        """The exchange clock: local wall clock plus the measured offset."""
        return int(time.time() * 1000) + self.offset_ms

    def _client(self, offset: Callable[[], int], retries: int = 3) -> BybitRestClient:
        transport = GuardedTransport(
            httpx.AsyncHTTPTransport(), self.recorder, max_notional=self.cfg.max_order_usdt
        )
        return BybitRestClient(
            RestClientConfig(base_url=DEMO_REST_BASE, max_retries=retries),
            uid="e29-k01",
            signer=self.signer,
            governor=self.governor,
            transport=transport,
            clock_offset_ms_provider=offset,
        )

    def _on_frame(self, frame: dict[str, Any], recv_ms: int) -> None:
        self.sink.ws_frame(frame)
        items = items_from_frame(frame, recv_seq=len(self.items), recv_ms=recv_ms)
        if len(self.items) < _MAX_ITEMS:
            self.items.extend(items)
        for it in items:
            if it.topic in EXEC_TOPICS and it.link_id in self.fills:
                self.fills[it.link_id].set()

    async def _pause(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.stopping.wait(), max(0.0, seconds))

    # -- reads ----------------------------------------------------------------------------

    async def sync_clock(self) -> None:
        """Exchange-minus-host offset from the fastest of five server-time reads."""
        samples: list[tuple[float, int]] = []
        for _ in range(5):
            t0 = time.time()
            server = await self.client.server_time()
            t1 = time.time()
            samples.append((t1 - t0, server.time_us // 1000 - round((t0 + t1) * 500)))
        rtt_s, self.offset_ms = min(samples)
        self.offset_err_ms = rtt_s * 500

    async def _get(
        self, path: str, cls: EndpointClass, client: BybitRestClient | None = None, **params: object
    ) -> dict[str, Any]:
        query = {"category": "linear", "symbol": self.symbol, **params}
        return await (client or self.client).signed_request(
            "GET", path, params=query, endpoint_class=cls
        )

    async def _position(self) -> tuple[Decimal, str, Decimal]:
        """(size, side, value) of the symbol's position from REST: the exchange is truth."""
        size, side, value = Decimal(0), "", Decimal(0)
        for row in _rows(await self._get("/v5/position/list", EndpointClass.POSITION)):
            size += _need(row.get("size"), "position size")
            value += as_decimal(row.get("positionValue")) or Decimal(0)
            side = str(row.get("side") or side)
        return size, side, value

    async def _open_orders(self) -> list[dict[str, Any]]:
        return _rows(await self._get("/v5/order/realtime", EndpointClass.ORDER))

    async def _order(self, link: str) -> dict[str, Any] | None:
        for path in ("/v5/order/realtime", "/v5/order/history"):
            rows = _rows(await self._get(path, EndpointClass.ORDER, orderLinkId=link))
            if rows:
                return rows[0]
        return None

    async def _public(self, path: str) -> list[dict[str, Any]]:
        query = {"category": "linear", "symbol": self.symbol}
        return _rows(await self.client.get_public(path, params=query))

    async def _touch(self) -> tuple[Decimal, Decimal]:
        rows = await self._public("/v5/market/tickers")
        bid = _need(rows[0].get("bid1Price") if rows else None, "bid")
        ask = _need(rows[0].get("ask1Price"), "ask")
        if not 0 < bid < ask:
            raise SafetyRefusal("no usable top of book")
        return bid, ask

    async def preflight(self) -> None:
        """Clock, key permissions (C-2.8), and for `orders` a tradable USDT perpetual that is flat
        with no open orders, so the end-of-run flatten closes only what the run opened."""
        await self.sync_clock()
        facts = parse_key_info(await self.client.signed_request("GET", KEY_INFO_PATH))
        check_permissions(facts.read_only, facts.permissions)
        self.scrubber.add_known(facts.uid)
        if self.cfg.mode == "soak":
            return
        rows = await self._public("/v5/market/instruments-info")
        kind = (rows[0].get("contractType"), rows[0].get("settleCoin")) if rows else None
        if len(rows) != 1 or kind != ("LinearPerpetual", "USDT"):
            raise SafetyRefusal("the symbol must be one USDT linear perpetual")
        self.inst = parse_instrument(rows[0], fetched_at_us=self.now_ms() * 1000)
        if self.inst.status != "trading":
            raise SafetyRefusal("the symbol is not trading")
        if (await self._position())[0] or await self._open_orders():
            raise SafetyRefusal("the symbol must be flat with no open orders before the run")

    # -- orders ---------------------------------------------------------------------------

    def _link(self, purpose: OrderPurpose) -> str:
        link = new_link(self.account_id, purpose)
        self.links.add(link)
        return link

    async def _post(
        self, op: str, path: str, body: dict[str, Any]
    ) -> tuple[ExchangeError | None, float]:
        started, error = time.perf_counter(), None
        with labelled(op):
            try:
                await self.client.signed_request(
                    "POST", path, body=body, endpoint_class=EndpointClass.ORDER
                )
            except ExchangeError as exc:
                error = exc
        elapsed = time.perf_counter() - started
        if op == "create" and error is None:
            self.submit.labels("rest").observe(elapsed)
            self.submit_ms.append(elapsed * 1e3)
        return error, elapsed

    async def cycle(self, i: int) -> None:
        inst, cfg = self.inst, self.cfg
        if inst is None:
            raise SafetyRefusal("no instrument: the preflight did not run")
        bid, ask = await self._touch()
        taker = cfg.taker_every > 0 and (i + 1) % cfg.taker_every == 0
        price, tick = (ask + inst.tick_size if taker else bid), inst.tick_size
        qty = max(inst.qty_step * cfg.lots, inst.min_order_qty)
        stop = (price * (1 - cfg.sl_pct) / tick).to_integral_value(ROUND_FLOOR) * tick
        await self._cap_exposure(qty * price)
        link = self._link("entry")
        ref: dict[str, Any] = {"category": "linear", "symbol": self.symbol, "orderLinkId": link}
        body = {**ref, "side": "Buy", "orderType": "Limit", "qty": str(qty), "price": str(price)}
        body |= {"timeInForce": "GTC", "positionIdx": 0, "stopLoss": str(stop)}
        body |= {"slTriggerBy": "MarkPrice", "tpslMode": "Full"}
        row: dict[str, Any] = {"cycle": i, "order_link_id": link, "created_ms": self.now_ms()}
        row["kind"] = "taker" if taker else "passive"
        self.fills[link] = asyncio.Event()
        try:
            error, took = await self._post("create", "/v5/order/create", body)
            row.update(create=_code(error), create_ms=round(took * 1e3, 1))
            self._judge(error)
            if i == 0:
                duplicate, _ = await self._post("duplicate", "/v5/order/create", body)
                self.notes["duplicate_order_link_id"] = _describe(duplicate)
            if error is not None and not isinstance(error, _UNRESOLVED):
                return
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(5 if taker else cfg.fill_wait_s):
                    await self.fills[link].wait()
            order = await self._order(link)
            if order is not None and order.get("orderStatus") in _OPEN:
                row["partial"] = order.get("orderStatus") == "PartiallyFilled"
                if price - tick > stop:  # an amend never moves the price to the stop (C-2.6)
                    err, took = await self._post(
                        "amend", "/v5/order/amend", {**ref, "price": str(price - tick)}
                    )
                    row.update(amend=_code(err), amend_ms=round(took * 1e3, 1))
                err, took = await self._post("cancel", "/v5/order/cancel", ref)
                row.update(cancel=_code(err), cancel_ms=round(took * 1e3, 1))
            final = await self._order(link) or {}
            row.update(status=final.get("orderStatus", ""), filled=final.get("cumExecQty", ""))
        finally:
            self.fills.pop(link, None)
            self.rows.append(row)

    def _judge(self, error: ExchangeError | None) -> None:
        """Stop on a system-level refusal (key, clock, rate) or three failed creates in a row."""
        accepted = error is None or isinstance(error, DuplicateClientIdError)
        self._failures = 0 if accepted else self._failures + 1
        if isinstance(error, AuthError | ClockDriftError | RateLimitError) or self._failures >= 3:
            raise SafetyRefusal(f"create refused ({_describe(error)}): stopping the run")

    async def _exposure(self) -> Decimal:
        """Position value plus the resting Buy orders of the run, from REST."""
        value = (await self._position())[2]
        for order in await self._open_orders():
            if order.get("orderLinkId") in self.links and order.get("side") == "Buy":
                leaves = _need(order.get("leavesQty"), "leaves qty")
                value += leaves * _need(order.get("price"), "order price")
        return value

    async def _cap_exposure(self, notional: Decimal) -> None:
        if await self._exposure() + notional <= self.cfg.max_exposure_usdt:
            return
        await self.flatten("exposure")
        if await self._exposure() + notional > self.cfg.max_exposure_usdt:
            raise SafetyRefusal("the run exposure cap would be exceeded")

    async def flatten(self, reason: str) -> None:
        """A reduce-only market order for the whole position, then wait for REST to show flat."""
        size, side, _ = await self._position()
        if size > 0:
            link = self._link("flatten")
            body: dict[str, Any] = {"category": "linear", "symbol": self.symbol}
            body |= {"orderLinkId": link, "side": "Sell" if side == "Buy" else "Buy"}
            body |= {"orderType": "Market", "qty": str(size), "reduceOnly": True}
            body |= {"timeInForce": "IOC", "positionIdx": 0}
            error, took = await self._post("flatten", "/v5/order/create", body)
            row = {"cycle": -1, "order_link_id": link, "created_ms": self.now_ms()}
            row |= {"kind": f"flatten:{reason}", "create": _code(error)}
            self.rows.append(row | {"create_ms": round(took * 1e3, 1)})
        for _ in range(15):
            if (await self._position())[0] == 0:
                return
            await asyncio.sleep(2)
        raise SafetyRefusal("the position is still open after the flatten")

    async def cleanup(self) -> None:
        """Cancel what the run left open, then flatten, bounded. A position this cannot close
        keeps its native SL, and the log says to flatten it in the demo UI."""
        try:
            async with asyncio.timeout(120):
                for order in await self._open_orders():
                    if order.get("orderLinkId") in self.links:
                        cancel = {"category": "linear", "symbol": self.symbol}
                        cancel["orderId"] = str(order.get("orderId"))
                        await self._post("cleanup", "/v5/order/cancel", cancel)
                await self.flatten("end")
            self.notes["cleanup"] = "own orders cancelled, position flat"
        except Exception as exc:
            self.notes["cleanup"] = f"INCOMPLETE ({type(exc).__name__}): flatten in the demo UI"
            _log().error("cleanup_incomplete_flatten_by_hand", error=type(exc).__name__)

    async def trade(self) -> None:
        if self.cfg.capture_10002:
            await self.skew()
        interval, t0 = self.cfg.hours * 3600 / self.cfg.orders, time.monotonic()
        try:
            for i in range(self.cfg.orders):
                if self.stopping.is_set():
                    break
                await self.cycle(i)
                if i % 10 == 9:
                    _log().info("orders_progress", done=i + 1, of=self.cfg.orders)
                    with contextlib.suppress(ExchangeError):
                        await self.sync_clock()
                await self._pause(t0 + (i + 1) * interval - time.monotonic())
        finally:
            await self.cleanup()
            await asyncio.sleep(10)  # the flatten's trailing pushes

    async def soak(self) -> None:
        end = time.monotonic() + self.cfg.hours * 3600
        while not self.stopping.is_set() and (left := end - time.monotonic()) > 0:
            await self._pause(min(600.0, left))
            with contextlib.suppress(ExchangeError):
                await self.sync_clock()
            stats = self.stream.stats
            _log().info("soak_progress", connects=stats.connects, drops=len(stats.drops))

    # -- captures -------------------------------------------------------------------------

    async def skew(self) -> None:
        """10002: one signed read stamped 30 s behind (the adapter retries it once)."""
        client = self._client(lambda: self.offset_ms - SKEW_MS, retries=0)
        try:
            with labelled("skew"):
                await self._get("/v5/order/realtime", EndpointClass.ORDER, client)
            self.notes["clock_skew_10002"] = f"accepted with a timestamp {SKEW_MS} ms behind"
        except ExchangeError as exc:
            self.notes["clock_skew_10002"] = _describe(exc)
        finally:
            await client.aclose()

    async def burst(self) -> None:
        """10018: ONE bounded burst of unsigned server-time reads that bypasses the governor on
        purpose (flag-gated): waves of 50 until a reply is not a plain success, at most
        `burst_max` requests. The IP may then be held for 10 minutes or more: it runs last."""
        transport = GuardedTransport(
            httpx.AsyncHTTPTransport(), self.recorder, max_notional=self.cfg.max_order_usdt
        )
        sent, stopped_by = 0, "no limit reply"
        async with httpx.AsyncClient(base_url=DEMO_REST_BASE, transport=transport) as client:
            while sent < self.cfg.burst_max and stopped_by == "no limit reply":
                wave = min(50, self.cfg.burst_max - sent)
                with labelled("burst"):
                    replies = await asyncio.gather(
                        *(client.get("/v5/market/time") for _ in range(wave)),
                        return_exceptions=True,
                    )
                sent += wave
                for reply in replies:
                    if isinstance(reply, BaseException):
                        stopped_by = type(reply).__name__
                    elif not _plain_ok(reply):
                        stopped_by = f"HTTP {reply.status_code}"
        self.notes["ip_limit_10018"] = {"sent": sent, "stopped_by": stopped_by}

    async def retention(self, path: Path) -> None:
        """Demo order retention (24 §8.3 rule 6): look up a sample of an earlier run's ids."""
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        rows = [r for r in csv.DictReader(io.StringIO(text)) if r.get("cycle", "-1") != "-1"]
        found = []
        for r in rows[:2] + rows[-2:]:
            order = await self._order(r["order_link_id"])
            age_days = (self.now_ms() - int(r["created_ms"])) / 86_400_000
            found.append({"age_days": round(age_days, 2), "found": order is not None})
        self.notes["demo_retention"] = found

    # -- run ------------------------------------------------------------------------------

    async def backfill(self) -> dict[str, str]:
        """`execId` -> `execType` of every execution REST lists for the run, 5 s overlap."""
        rest: dict[str, str] = {}
        window = {"startTime": self.started_ms - 5_000, "endTime": self.now_ms(), "limit": 100}
        cursor = ""
        for _ in range(_MAX_PAGES):
            page = {**window, "cursor": cursor} if cursor else window
            body = await self._get("/v5/execution/list", EndpointClass.ORDER, **page)
            rest |= {str(r.get("execId")): str(r.get("execType")) for r in _rows(body)}
            result = body.get("result")
            cursor = str(result.get("nextPageCursor") or "") if isinstance(result, dict) else ""
            if not cursor:
                break
        return rest

    async def session(self) -> None:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.stream.run())
            try:
                async with asyncio.timeout(20):
                    await self.stream.ready.wait()
                await (self.trade() if self.cfg.mode == "orders" else self.soak())
            finally:
                await self.stream.stop()

    async def wrap_up(self, outcome: str) -> dict[str, Any]:
        rest: dict[str, str] = {}
        try:
            rest = await self.backfill()
            if self.cfg.retention_probe is not None:
                await self.retention(self.cfg.retention_probe)
            if self.cfg.capture_10018 and outcome == "completed":
                await self.burst()
        except Exception as exc:
            self.notes["wrap_up"] = _why(exc)
        report = build_report(self, rest, outcome)
        await asyncio.to_thread(write_outputs, self, report)
        return report


async def _serve_metrics(h: Harness, port: int) -> asyncio.Server:
    """`order_submit_seconds` on 127.0.0.1 for a Prometheus scrape (Grafana panels)."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            with contextlib.suppress(TimeoutError, ConnectionError):
                await asyncio.wait_for(reader.readline(), 5)
                body = generate_latest(h.metrics.registry)
                head = f"HTTP/1.1 200 OK\r\nContent-Type: {CONTENT_TYPE_LATEST}\r\n"
                head += f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
                writer.write(head.encode() + body)
                await writer.drain()
        finally:
            writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", port)


def _on_signals(h: Harness) -> None:
    """The first SIGINT/SIGTERM stops between cycles (cleanup and outputs still run); a second
    one cancels the run outright."""
    main, loop = asyncio.current_task(), asyncio.get_running_loop()

    def handler() -> None:
        if h.stopping.is_set() and main is not None:
            main.cancel()
        h.stopping.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handler)


async def run(cfg: Config, creds: EnvCredentials) -> dict[str, Any]:
    """Preflight (a refusal leaves before any order), the run, then the wrap-up, which always
    writes the run directory and the fixture staging."""
    h = Harness(cfg, creds)
    _on_signals(h)
    server = await _serve_metrics(h, cfg.metrics_port) if cfg.metrics_port else None
    try:
        await h.preflight()
        h.started_ms, outcome = h.now_ms(), "completed"
        try:
            await h.session()
        except Exception as exc:
            outcome = _why(exc)
            _log().error("run_stopped_early", reason=outcome)
        return await h.wrap_up(outcome)
    finally:
        await h.client.aclose()
        if server is not None:
            server.close()
            await server.wait_closed()
