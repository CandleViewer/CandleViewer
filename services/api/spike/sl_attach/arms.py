"""The two arms (#856 Scope; the scout's §2; the Q5 ruling), one sample per call, over the real
`BybitTradingPort` behind #843's `GuardedPort`, here widened by one guarded call (`SlGuardedPort`).

- **Arm (a)**: a create carrying an attached `stopLoss` (`Full`, mark-triggered), timed from the
  call to its ack. Its protection evidence is the first position push showing the stop, after
  the first execution (`protected_lag_ms`, reported, not gated).
- **Arm (b)**: a create carrying a far attached **backstop** stop (5 to 10 % away, Q5), then, on
  the first execution push of that order, the `trading-stop` that tightens it. The create runs
  as its own task, so the stop is sent as soon as the push arrives, ack or not. It is timed from
  the execution's `execTime` to the `200`, on the exchange clock (`timing.ExposureTiming`). This
  times a modify after an attached open, not a first attach from naked, which the finding says.

Each sample then reads the position over REST: the stop the sample wrote must be there, or the
sample is discarded `incomplete` (the ticket's self-check), and closes it, reduce-only (its cost
is not counted). `Tap` sits on the port's transport and keeps every exchange: the host's wall
clock at send and reply, the envelope `time`, the code and the rate headers, from which come
the offset, each sample's skew, the retries and the requests per protected position.

No path here opens a position without a native stop: `GuardedPort` refuses such an opener before
anything is sent, and `SlGuardedPort` refuses a stop write that removes, loosens or names a
position the run did not open. No reconciler or watchdog is touched: the harness owns none.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import TYPE_CHECKING, Final

import httpx

from candleviewer.exchange.base.errors import ExchangeError, TransportError, UnknownStateError
from candleviewer.exchange.base.models import (
    Execution,
    OrderAck,
    PlaceOrderRequest,
    Position,
    PrivateStreamStatus,
    TradingStopRequest,
)
from candleviewer.observability.context import spawn
from spike.oms_demo_path.safety import GuardedPort, Refused, check_symbol
from spike.sl_attach import taxonomy
from spike.sl_attach.config import OFFSET_SAMPLES, Arm, ArmConfig
from spike.sl_attach.results import Discard, Outcome, Sample, Stage
from spike.sl_attach.timing import AckTiming, Exchanged, ExposureTiming, skew_discard, skew_ms

if TYPE_CHECKING:
    from candleviewer.domain.primitives import Side
    from candleviewer.exchange.base.models import AccountRef, PrivateEvent
    from candleviewer.exchange.base.ports import PrivateStream, TradingPort
    from spike.oms_demo_path.harness import Links
    from spike.oms_demo_path.measure import ClockOffset, Timings
    from spike.oms_demo_path.scrub import Scrubber

CREATE: Final = "/v5/order/create"
TRADING_STOP: Final = "/v5/position/trading-stop"
WALLET: Final = "/v5/account/wallet-balance"
_HEADERS: Final = {
    "limit_status": "x-bapi-limit-status",
    "limit_cap": "x-bapi-limit",
    "limit_reset_ms": "x-bapi-limit-reset-timestamp",
    "timenow_ms": "timenow",
}
_TRANSFER: Final = frozenset({"content-encoding", "content-length", "transfer-encoding"})


def _int(value: object) -> int | None:
    try:
        return int(str(value)) if value is not None else None
    except ValueError:
        return None


class Tap(httpx.AsyncBaseTransport):
    """The port's transport, each exchange kept (`log`): no header but the four rate and time
    headers, and no body, so nothing here can hold a key or a signature."""

    def __init__(self, inner: httpx.AsyncBaseTransport, wall_ms: Callable[[], float]) -> None:
        self._inner = inner
        self._wall_ms = wall_ms
        self.log: list[Exchanged] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        sent = self._wall_ms()
        response = await self._inner.handle_async_request(request)
        try:
            body = await response.aread()
        finally:
            await response.aclose()
        received = self._wall_ms()
        reply = taxonomy_reply(body)
        headers = {k: _int(response.headers.get(v)) for k, v in _HEADERS.items()}
        self.log.append(
            Exchanged(
                path=request.url.path,
                method=request.method,
                sent_wall_ms=sent,
                received_wall_ms=received,
                venue_ms=_int(reply.get("time")),
                ret_code=_int(reply.get("retCode")),
                status=response.status_code,
                **headers,
            )
        )
        kept = [(k, v) for k, v in response.headers.multi_items() if k.lower() not in _TRANSFER]
        return httpx.Response(response.status_code, headers=kept, content=body)

    async def aclose(self) -> None:
        await self._inner.aclose()


def taxonomy_reply(body: bytes) -> dict[str, object]:
    """The reply's envelope, or nothing when it is not a JSON object."""
    try:
        decoded = json.loads(body)
    except ValueError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


class SlGuardedPort(GuardedPort):
    """#843's guarded surface plus one call, `set_trading_stop`, admitted only to tighten the
    stop of a position one of the run's own openers opened (Q5; C-2.6). Every opener is still
    refused without its native stop, before anything is sent (`GuardedPort.place_order`)."""

    def __init__(self, port: TradingPort, timings: Timings | None = None) -> None:
        super().__init__(port, timings)
        #: The stop each of the run's openers attached, by (symbol, positionIdx): the floor a
        #: stop write may tighten from.
        self.protected: dict[tuple[str, int], tuple[Side, Decimal]] = {}

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck:
        key = (req.symbol, req.position_idx)
        if not req.reduce_only and req.stop_loss is not None:
            self.protected[key] = (req.side, req.stop_loss)
        try:
            return await super().place_order(req)
        except Refused:
            if not req.reduce_only:
                self.protected.pop(key, None)
            raise

    async def set_trading_stop(self, req: TradingStopRequest) -> OrderAck:
        check_symbol(req.symbol)
        held = self.protected.get((req.symbol, req.position_idx))
        if held is None:
            raise Refused("a stop write names only a position one of the run's openers opened")
        stop = req.stop_loss
        if stop is None or not stop.is_finite() or stop <= 0:
            raise Refused("C-2.6: a stop write never removes or zeroes the native stop")
        side, floor = held
        if stop < floor if side == "buy" else stop > floor:
            raise Refused("Q5: the measured trading-stop tightens the backstop, never loosens it")
        if req.tpsl_mode != "full" or req.trailing_distance is not None:
            raise Refused("the arms write a Full-mode stop and nothing else")
        async with self._call("trading_stop"):
            ack = await self._port.set_trading_stop(req)
        if ack.ok:
            self.protected[(req.symbol, req.position_idx)] = (side, stop)
        return ack


class Watch:
    """The private stream, read by one task: the first execution of each `orderLinkId`, the
    position pushes in arrival order, and whether the stream is up. `wait` re-checks a
    predicate on each item, bounded by the injected clock's `sleep`."""

    def __init__(self, sleep: Callable[[float], Awaitable[None]]) -> None:
        self._sleep = sleep
        self._changed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stream: PrivateStream | None = None
        self.live = False
        self.first: dict[str, Execution] = {}
        self.positions: list[Position] = []

    async def open(self, port: SlGuardedPort, account: AccountRef) -> None:
        self._stream = await port.subscribe_private(account)
        self._task = spawn(self._pump(self._stream), name="sl-attach-watch")

    async def _pump(self, stream: PrivateStream) -> None:
        async for item in stream:
            self.observe(item)

    def observe(self, item: PrivateEvent | PrivateStreamStatus) -> None:
        if isinstance(item, PrivateStreamStatus):
            self.live = item.state in ("resyncing", "heartbeat")
        elif isinstance(item.payload, Execution):
            self.first.setdefault(item.payload.order_link_id, item.payload)
        elif isinstance(item.payload, Position):
            self.positions.append(item.payload)
        self.poke()

    def poke(self) -> None:
        self._changed.set()

    async def wait(self, predicate: Callable[[], bool], timeout_s: float) -> bool:
        async def nap() -> None:
            await self._sleep(timeout_s)

        timer = spawn(nap(), name="sl-attach-wait")
        try:
            while not predicate():
                if timer.done():
                    return predicate()
                self._changed.clear()
                changed = spawn(self._changed.wait(), name="sl-attach-changed")
                await asyncio.wait({changed, timer}, return_when=asyncio.FIRST_COMPLETED)
                changed.cancel()
            return True
        finally:
            timer.cancel()

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        if self._stream is not None:
            await self._stream.aclose()


def _round(value: Decimal, tick: Decimal, *, up: bool) -> Decimal:
    return (value / tick).to_integral_value(ROUND_CEILING if up else ROUND_FLOOR) * tick


def prices(cfg: ArmConfig, ref: Decimal, side: Side) -> tuple[Decimal, Decimal, Decimal]:
    """The opener's limit (through the touch), the measured stop and arm (b)'s backstop, each
    on the tick and each stop on the protective side (`GuardedPort` checks it again)."""
    sign = 1 if side == "buy" else -1
    price = _round(ref * (1 + sign * cfg.cross_bps / 10_000), cfg.tick, up=side == "buy")
    stop = _round(ref * (1 - sign * cfg.sl_bps / 10_000), cfg.tick, up=side == "sell")
    backstop = _round(ref * (1 - sign * cfg.backstop_pct / 100), cfg.tick, up=side == "sell")
    return price, stop, backstop


@dataclass
class Clock:
    """The host's clocks: monotonic seconds, wall ms, and the sleep every wait runs on."""

    monotonic: Callable[[], float]
    wall_ms: Callable[[], float]
    sleep: Callable[[float], Awaitable[None]]


def _costs(log: Sequence[Exchanged]) -> dict[str, int]:
    return {
        "requests_order_class": sum(1 for e in log if e.path.startswith("/v5/order/")),
        "requests_position_class": sum(1 for e in log if e.path == TRADING_STOP),
        "requests_reads": sum(1 for e in log if e.method == "GET"),
    }


def _failure(
    exc: ExchangeError, log: Sequence[Exchanged], path: str, *, create: bool
) -> taxonomy.Reading:
    if exc.exchange_ret_code is not None:
        msg = exc.exchange_ret_msg or ""
        return taxonomy.read_answer(exc.exchange_ret_code, msg, exc.code.value, create=create)
    status = next((e.status for e in reversed(log) if e.path == path), None)
    return taxonomy.read_transport(exc.code.value, status)


def _refusal(ack: OrderAck, *, create: bool) -> taxonomy.Reading:
    code = ack.exchange_ret_code
    if code is None:
        return taxonomy.read_transport(ack.error_code or "UNKNOWN_STATE", None)
    return taxonomy.read_answer(code, ack.exchange_ret_msg or "", ack.error_code, create=create)


def _open_outcome(exc: ExchangeError) -> Outcome:
    return "ambiguous" if isinstance(exc, TransportError | UnknownStateError) else "rejected"


@dataclass
class ArmRunner:
    """One run's arms over one account (see the module docstring)."""

    port: SlGuardedPort
    account: AccountRef
    tap: Tap
    watch: Watch
    offset: ClockOffset
    clock: Clock
    links: Links
    scrubber: Scrubber
    reference: Callable[[], Awaitable[Decimal]]
    cfg: ArmConfig
    run_id: str
    samples: list[Sample] = field(default_factory=list)

    async def measure_offset(self) -> None:
        """The best of `OFFSET_SAMPLES` wallet reads (#843's `ClockOffset`)."""
        self.offset.reset_best()
        for _ in range(OFFSET_SAMPLES):
            await self.port.wallet(self.account)
            read = next(e for e in reversed(self.tap.log) if e.path == WALLET)
            if read.venue_ms is not None:
                self.offset.sample(read.sent_wall_ms, read.received_wall_ms, read.venue_ms)

    async def run(self, arm: Arm, count: int) -> list[Sample]:
        out: list[Sample] = []
        for i in range(count):
            if i % self.cfg.offset_every == 0:
                await self.measure_offset()
            sample = await (self.sample_a(i) if arm == "a" else self.sample_b(i))
            out.append(sample)
        self.samples.extend(out)
        return out

    def _base(self, i: int, arm: Arm, side: Side, link: str) -> dict[str, object]:
        uncertainty = self.offset.best_rtt_ms
        return {
            "run_id": self.run_id,
            "sample_id": len(self.samples) + i,
            "arm": arm,
            "symbol": self.cfg.symbol,
            "side": side,
            "position_idx": 0,
            "qty": format(self.cfg.qty, "f"),
            "order_ref": self.scrubber.known("link", link),
            "offset_ms": self.offset.value,
            "offset_uncertainty_ms": None if uncertainty is None else uncertainty / 2,
        }

    def _clock(self, log: Sequence[Exchanged], path: str) -> dict[str, object]:
        """The measured call's clock fields and its skew verdict (`skew_discard`)."""
        measured = next((e for e in reversed(log) if e.path == path), None)
        offset = self.offset.value
        if measured is None or offset is None:
            return {"_discard": True}
        skew = skew_ms(measured, offset)
        uncertainty = None if self.offset.best_rtt_ms is None else self.offset.best_rtt_ms / 2
        return {
            "skew_ms": skew,
            "server_time_ms": measured.venue_ms,
            "timenow_ms": measured.timenow_ms,
            "limit_status": measured.limit_status,
            "limit_cap": measured.limit_cap,
            "limit_reset_ms": measured.limit_reset_ms,
            "_discard": skew_discard(skew, uncertainty),
        }

    def _opener(self, link: str, side: Side, price: Decimal, stop: Decimal) -> PlaceOrderRequest:
        return PlaceOrderRequest(
            account=self.account,
            symbol=self.cfg.symbol,
            side=side,
            order_type="limit",
            qty=self.cfg.qty,
            price=price,
            time_in_force="ioc",
            order_link_id=link,
            stop_loss=stop,
            sl_trigger_by="mark",
            tpsl_mode="full",
        )

    async def _protected(self, stop: Decimal) -> bool:
        """The REST position read shows `stop` on the open position (the self-check)."""
        rows = await self.port.positions(self.account)
        return any(p.symbol == self.cfg.symbol and p.qty > 0 and p.stop_loss == stop for p in rows)

    async def _close(self, side: Side) -> None:
        close_side: Side = "sell" if side == "buy" else "buy"
        await self.port.place_order(
            PlaceOrderRequest(
                account=self.account,
                symbol=self.cfg.symbol,
                side=close_side,
                order_type="market",
                qty=self.cfg.qty,
                time_in_force="ioc",
                order_link_id=self.links.flatten(),
                reduce_only=True,
            )
        )
        self.port.protected.pop((self.cfg.symbol, 0), None)

    def _finish(
        self,
        fields: dict[str, object],
        outcome: Outcome,
        reading: taxonomy.Reading | None,
        stage: Stage,
        discard: Discard | None = None,
    ) -> Sample:
        if fields.pop("_discard", False) and outcome == "ok" and discard is None:
            discard = "skew"
        if discard is not None:
            outcome = "discarded"
        if reading is not None:
            fields |= {
                "stage": stage,
                "ret_code": reading.ret_code,
                "ret_msg_class": reading.ret_msg_class,
                "adapter_error_code": reading.adapter_error_code,
                "s86_code": reading.s86_code,
                "retryable": reading.retryable,
                "taxonomy_divergent": reading.divergent,
            }
        return Sample.model_validate(fields | {"outcome": outcome, "discard_reason": discard})

    async def sample_a(self, i: int) -> Sample:
        side: Side = "buy" if i % 2 == 0 else "sell"
        link = self.links.new()
        price, stop, _ = prices(self.cfg, await self.reference(), side)
        fields = self._base(i, "a", side, link)
        mark, pushes = len(self.tap.log), len(self.watch.positions)
        t_send = self.clock.monotonic()
        try:
            ack = await self.port.place_order(self._opener(link, side, price, stop))
        except ExchangeError as exc:
            log = self.tap.log[mark:]
            fields |= _costs(log) | {"attempts": sum(1 for e in log if e.path == CREATE)}
            reading = _failure(exc, log, CREATE, create=True)
            return self._finish(fields, _open_outcome(exc), reading, "create")
        t_ack = self.clock.monotonic()
        log = self.tap.log[mark:]
        create = next((e for e in reversed(log) if e.path == CREATE), None)
        rtt = None if create is None else create.received_wall_ms - create.sent_wall_ms
        timing = AckTiming(t_send, t_ack, rtt)
        fields |= {
            "ack_ms": timing.ack_ms,
            "port_latency_ms": float(ack.latency_ms),
            "rtt_ms": rtt,
            "overhead_ms": timing.overhead_ms,
            "attempts": sum(1 for e in log if e.path == CREATE),
        }
        fields |= self._clock(log, CREATE) | _costs(log)
        if not ack.ok:
            return self._finish(fields, "rejected", _refusal(ack, create=True), "create")
        if not await self.watch.wait(lambda: link in self.watch.first, self.cfg.fill_wait_s):
            return self._finish(fields, "ok", taxonomy.OK, "create", "no_fill")
        fill = self.watch.first[link]
        exec_ms = fill.ts_exec // 1000

        def shown() -> bool:
            return any(p.stop_loss == stop and p.qty > 0 for p in self.watch.positions[pushes:])

        if await self.watch.wait(shown, self.cfg.settle_wait_s):
            seen = next(p for p in self.watch.positions[pushes:] if p.stop_loss == stop)
            fields["protected_lag_ms"] = float(seen.updated_at // 1000 - exec_ms)
        fields |= {"exec_time_ms": exec_ms, "ingest_us": fill.ts_ingest}
        discard: Discard | None = None if await self._protected(stop) else "incomplete"
        await self._close(side)
        return self._finish(fields, "ok", taxonomy.OK, "create", discard)

    async def sample_b(self, i: int) -> Sample:
        side: Side = "buy" if i % 2 == 0 else "sell"
        link = self.links.new()
        price, stop, backstop = prices(self.cfg, await self.reference(), side)
        fields = self._base(i, "b", side, link)
        mark = len(self.tap.log)
        create = spawn(
            self.port.place_order(self._opener(link, side, price, backstop)),
            name="sl-attach-create",
        )
        create.add_done_callback(lambda _t: self.watch.poke())
        filled = await self.watch.wait(
            lambda: link in self.watch.first or create.done(), self.cfg.fill_wait_s
        )
        if filled and link in self.watch.first:
            return await self._tighten(fields, link, side, stop, create, mark)
        try:
            ack = await create
        except ExchangeError as exc:
            log = self.tap.log[mark:]
            fields |= _costs(log)
            return self._finish(
                fields, _open_outcome(exc), _failure(exc, log, CREATE, create=True), "create"
            )
        fields |= _costs(self.tap.log[mark:])
        if not ack.ok:
            return self._finish(fields, "rejected", _refusal(ack, create=True), "create")
        if await self.watch.wait(lambda: link in self.watch.first, self.cfg.fill_wait_s):
            return await self._tighten(fields, link, side, stop, create, mark)
        return self._finish(fields, "ok", taxonomy.OK, "create", "no_fill")

    async def _tighten(
        self,
        fields: dict[str, object],
        link: str,
        side: Side,
        stop: Decimal,
        create: asyncio.Task[OrderAck],
        mark: int,
    ) -> Sample:
        """The measured call: the first execution has arrived; the stop goes now."""
        fill = self.watch.first[link]
        t0_wall, t0 = self.clock.wall_ms(), self.clock.monotonic()
        request = TradingStopRequest(
            account=self.account,
            symbol=self.cfg.symbol,
            stop_loss=stop,
            sl_trigger_by="mark",
            tpsl_mode="full",
        )
        try:
            ack = await self.port.set_trading_stop(request)
            failure: ExchangeError | None = None
        except ExchangeError as exc:
            ack, failure = None, exc
        t1, t1_wall = self.clock.monotonic(), self.clock.wall_ms()
        await asyncio.gather(create, return_exceptions=True)
        log = self.tap.log[mark:]
        exec_ms = fill.ts_exec // 1000
        fields |= _costs(log) | {
            "attempts": sum(1 for e in log if e.path == TRADING_STOP),
            "exec_time_ms": exec_ms,
            "ingest_us": fill.ts_ingest,
        }
        if failure is not None:
            await self._close(side)
            reading = _failure(failure, log, TRADING_STOP, create=False)
            return self._finish(fields, _open_outcome(failure), reading, "trading_stop")
        if ack is None or not ack.ok:
            await self._close(side)
            reading = taxonomy.OK if ack is None else _refusal(ack, create=False)
            return self._finish(fields, "rejected", reading, "trading_stop")
        clock = self._clock(log, TRADING_STOP)
        timing = ExposureTiming(
            exec_time_ms=exec_ms,
            ingest_us=fill.ts_ingest,
            t_stop_send_wall_ms=t0_wall,
            t_stop_send_s=t0,
            t_stop_ok_s=t1,
            t_stop_ok_wall_ms=t1_wall,
            stop_venue_ms=_int(clock.get("server_time_ms")),
            offset_ms=float(self.offset.value or 0),
        )
        fields |= clock | {
            "exposure_ms": timing.exposure_ms,
            "exposure_venue_ms": timing.exposure_venue_ms,
            "push_lag_ms": timing.push_lag_ms,
            "react_ms": timing.react_ms,
            "stop_rtt_ms": timing.stop_rtt_ms,
        }
        discard: Discard | None = None if await self._protected(stop) else "incomplete"
        await self._close(side)
        return self._finish(fields, "ok", taxonomy.OK, "trading_stop", discard)
