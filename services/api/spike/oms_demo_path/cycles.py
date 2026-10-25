"""`cycles` (#843 A4 brief item 4): place, amend, drive to a fill or a partial fill, cancel the
remainder, close any position reduce-only; paced over the window, every step and transition
counted, every opener carrying its native stop (C-2.6).

Each cycle on BTCUSDT, `--qty-multiple` minimum quantities (2 by default: at the minimum, which is
one step, an order fills all or nothing, so no partial fill could be seen):

1. a GTC limit order `--away-bps` from the reference price, its `stop_loss` `--sl-bps` away on
   the protective side;
2. an amend one tick further away;
3. the drive: an amend to the touch, joining it (a maker that may fill in part) or crossing it
   by `--cross-bps` (a taker that fills whole), alternating by default; then the fill is waited
   for on the stream for `--fill-wait-s`, and the order is read back over REST (the exchange is
   truth) to record `filled`, `partial` or `unfilled`;
4. a cancel of any remainder;
5. a reduce-only market close of what filled, then a REST read that the book is flat (else the
   flatten of `safety.py`, over the run's own orders and fills only).

The outcome is read again after the cancel (R1C-10): a fill that landed meanwhile makes an
`unfilled` cycle `partial`. After each cycle the execution list is read back for the cycle's
window (parity), its ends on the exchange's clock (R1C-11); a venue or transport failure is
recorded, the cycle cleaned up and the run goes on, until three in a row.
"""

from __future__ import annotations

from collections import Counter
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Final, Literal

from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.base.models import (
    AmendOrderRequest,
    CancelOrderRequest,
    Order,
    OrderAck,
    PlaceOrderRequest,
)
from spike.oms_demo_path.config import SYMBOL, RunConfig
from spike.oms_demo_path.harness import Harness
from spike.oms_demo_path.safety import QtyLimits

type Side = Literal["buy", "sell"]
type FillMode = Literal["join", "cross"]

MAX_CONSECUTIVE_FAILURES: Final = 3
TERMINAL: Final = frozenset(
    {"filled", "cancelled", "partially_filled_canceled", "rejected", "deactivated"}
)
_BPS: Final = Decimal(10_000)


def side_of(mode: Literal["buy", "sell", "alternate"], n: int) -> Side:
    if mode == "alternate":
        return "buy" if n % 2 == 0 else "sell"
    return mode


def fill_mode_of(mode: Literal["join", "cross", "alternate"], n: int) -> FillMode:
    if mode == "alternate":
        return "join" if (n // 2) % 2 == 0 else "cross"
    return mode


def on_tick(price: Decimal, tick: Decimal, *, up: bool) -> Decimal:
    return (price / tick).to_integral_value(ROUND_CEILING if up else ROUND_FLOOR) * tick


def prices(
    ref: Decimal, side: Side, cfg: RunConfig, tick: Decimal
) -> tuple[Decimal, Decimal, Decimal]:
    """(the entry away from the touch, the amend one tick further away, the stop)."""
    buy = side == "buy"
    sign = Decimal(-1 if buy else 1)
    away = on_tick(ref * (1 + sign * cfg.away_bps / _BPS), tick, up=not buy)
    further = away - tick if buy else away + tick
    stop = on_tick(ref * (1 + sign * cfg.sl_bps / _BPS), tick, up=not buy)
    return away, further, stop


def drive_price(ref: Decimal, side: Side, mode: FillMode, cfg: RunConfig, tick: Decimal) -> Decimal:
    """Join: the reference on our side of the book. Cross: through it by `--cross-bps`."""
    buy = side == "buy"
    if mode == "join":
        base = on_tick(ref, tick, up=False)
        return base if buy else base + tick
    sign = Decimal(1 if buy else -1)
    return on_tick(ref * (1 + sign * cfg.cross_bps / _BPS), tick, up=buy)


async def run_cycles(h: Harness, cfg: RunConfig) -> dict[str, object]:
    instrument = await h.public.instrument()
    limits, qty = QtyLimits.of(
        instrument, multiple=cfg.qty_multiple, max_multiple=cfg.max_qty_multiple
    )
    h.port.limits = limits
    await h.preflight()  # flat, the offset measured: armed
    outcomes: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    interval = cfg.min_hours * 3600 / max(cfg.cycles, 1)
    window_start = h.venue_now_us(slack=-1)
    failures = 0
    async with h.private_stream():
        for n in range(cfg.cycles):
            if h.shutdown.event.is_set():
                break
            began = h.monotonic()
            if cfg.offset_every and n and n % cfg.offset_every == 0:
                await h.measure_offset()
            cycle_start = h.venue_now_us(slack=-1)
            try:
                outcomes[await one_cycle(h, cfg, n, qty, instrument.tick_size, actions)] += 1
                failures = 0
            except ExchangeError as exc:  # recorded, the cycle cleaned up, the run goes on
                failures += 1
                errors[type(exc).__name__] += 1
                h.outputs.event("cycle_error", n=n, error=type(exc).__name__)
                await h.flatten()
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    h.shutdown.trip("error:consecutive_failures")
            await backfill(h, cycle_start)
            if await h.shutdown.pause(max(0.0, began + interval - h.monotonic())):
                break
        await h.shutdown.pause(min(cfg.fill_wait_s, 5.0))  # late pushes reach the monitor
    await backfill(h, window_start)
    return {
        "planned": cfg.cycles,
        "completed": sum(outcomes.values()),
        "outcomes": dict(sorted(outcomes.items())),
        "actions": dict(sorted(actions.items())),
        "errors": dict(sorted(errors.items())),
        "qty": str(qty),
        "partial_possible": qty >= 2 * limits.step,
        "interval_s": round(interval, 3),
    }


async def backfill(h: Harness, start_us: int) -> None:
    """The execution list from `start_us` to now on the exchange's clock: the REST side of the
    parity count, and the run's own fills for its scope."""
    fills = await h.port.executions(h.account, start_us, h.venue_now_us(slack=1))
    h.stream.rest_executions([f for f in fills if f.symbol == SYMBOL])
    h.scope.add(fills)


def _step(h: Harness, n: int, step: str, ack: OrderAck) -> None:
    h.outputs.event(
        "step",
        n=n,
        step=step,
        ok=ack.ok,
        error_code=ack.error_code,
        ret_code=ack.exchange_ret_code,
        latency_ms=ack.latency_ms,
        order_link_id=ack.order_link_id,
        exchange_order_id=ack.exchange_order_id,
    )


async def read_order(h: Harness, link: str) -> Order | None:
    """The order as the venue holds it now: open orders first, then history."""
    for orders in (
        await h.port.open_orders(h.account, SYMBOL, order_link_id=link),
        await h.port.order_history(h.account, order_link_id=link),
    ):
        for order in orders:
            if order.order_link_id == link:
                return order
    return None


async def one_cycle(
    h: Harness, cfg: RunConfig, n: int, qty: Decimal, tick: Decimal, actions: Counter[str]
) -> str:
    side = side_of(cfg.side, n)
    ref = await h.public.reference()
    away, further, stop = prices(ref, side, cfg, tick)
    link = h.links.new("entry")
    placed = await h.port.place_order(
        PlaceOrderRequest(
            account=h.account,
            symbol=SYMBOL,
            side=side,
            order_type="limit",
            qty=qty,
            price=away,
            time_in_force="gtc",
            order_link_id=link,
            stop_loss=stop,
        )
    )
    actions["place"] += 1
    _step(h, n, "place", placed)
    if not placed.ok or placed.exchange_order_id is None:
        return "rejected"
    oid = placed.exchange_order_id
    monitor = h.stream
    await monitor.wait(lambda: oid in monitor.orders, cfg.fill_wait_s)

    def amend(price: Decimal) -> AmendOrderRequest:
        return AmendOrderRequest(
            account=h.account,
            symbol=SYMBOL,
            order_link_id=link,
            exchange_order_id=oid,
            price=price,
        )

    _step(h, n, "amend", await h.port.amend_order(amend(further)))
    actions["amend"] += 1
    mode = fill_mode_of(cfg.fill_mode, n)
    _step(
        h,
        n,
        f"drive_{mode}",
        await h.port.amend_order(amend(drive_price(ref, side, mode, cfg, tick))),
    )
    actions["drive"] += 1

    def filled() -> bool:
        order = monitor.orders.get(oid)
        return order is not None and order.state in TERMINAL

    await monitor.wait(filled, cfg.fill_wait_s)
    order = await read_order(h, link)
    done = order.filled_qty if order is not None else Decimal(0)
    if order is not None and order.state == "filled":
        outcome = "filled"
    else:
        outcome = "partial" if done > 0 else "unfilled"
        _step(
            h,
            n,
            "cancel",
            await h.port.cancel_order(
                CancelOrderRequest(
                    account=h.account, symbol=SYMBOL, order_link_id=link, exchange_order_id=oid
                )
            ),
        )
        actions["cancel"] += 1
        await monitor.wait(lambda: oid in monitor.orders and filled(), cfg.fill_wait_s)
        after = await read_order(h, link)
        done = after.filled_qty if after is not None else done
        if after is not None and after.state == "filled":
            outcome = "filled"  # it filled whole before the cancel landed
        elif outcome == "unfilled" and done > 0:
            outcome = "partial"  # a fill landed between the read and the cancel
    if done > 0:
        closed = await h.port.place_order(
            PlaceOrderRequest(
                account=h.account,
                symbol=SYMBOL,
                side="sell" if side == "buy" else "buy",
                order_type="market",
                qty=done,
                order_link_id=h.links.flatten(),
                reduce_only=True,
                lane="critical",
            )
        )
        actions["close"] += 1
        _step(h, n, "close", closed)
        close_id = closed.exchange_order_id

        def close_done() -> bool:
            order = None if close_id is None else monitor.orders.get(close_id)
            return order is not None and order.state in TERMINAL

        await monitor.wait(close_done, cfg.fill_wait_s)
    if any(p.symbol == SYMBOL and p.qty > 0 for p in await h.port.positions(h.account)):
        if (await h.flatten())["flatten_orders"]:
            actions["residual_flatten"] += 1
    h.outputs.event("cycle", n=n, side=side, mode=mode, outcome=outcome)
    return outcome
