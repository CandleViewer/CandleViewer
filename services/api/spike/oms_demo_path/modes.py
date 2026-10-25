"""`soak`, `shapes` and `retention` (#843 A4 brief item 4).

- `soak`: the private stream open for `--hours` with no orders: dials (reconnects), heartbeats
  and pongs, `auth` grants and refusals, `down`s and the gaps they open, the longest silence.
  The offset is re-measured every 10 minutes, so each `auth` is signed on the exchange's clock.
  Its idle phase (ADR-0006's Spike S3) is a block of its own: the window the stream was held,
  the orders sent (none), the reconnects, the ping and message gap distributions, and, read at
  the end through the port's own `executions` over that window, the executions the stream never
  delivered, with the verdict on "zero missed executions": `met`, `not met` or `no data`.
- `shapes`: the exact replies the adapter maps. A duplicate `orderLinkId`: an opener with its
  stop, `post_only` and away from the touch, then the same create again; the adapter keeps no
  local record of ids it sent, so the venue answers, the port raises `DuplicateClientIdError`
  and the recording transport has the venue's whole reply; then the order is cancelled. `10002`:
  a second port from the adapter's own factory signs on a clock `SKEW_MS` behind
  (`clock_offset_ms`), and reads the wallet: the client re-signs once with the same offset and
  the read raises `ClockDriftError`, both replies recorded; nothing is created on that port.
  `10018` is never provoked (it would hold this process for 600 s and the venue's IP limit
  covers cv-api's egress too); a run of any mode that meets one records its shape.
- `retention`: on day 8 or later of an earlier run, the order history from its start, counted by
  state and age (24 §8.3 rule 6: demo keeps orders 7 days; a cancelled one may show 24 h only).
"""

from __future__ import annotations

from collections import Counter
from typing import Final

from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.base.models import CancelOrderRequest, PlaceOrderRequest
from spike.oms_demo_path.config import SOAK_HOURS, SYMBOL, RunConfig
from spike.oms_demo_path.cycles import prices
from spike.oms_demo_path.harness import Harness
from spike.oms_demo_path.measure import stats
from spike.oms_demo_path.safety import QtyLimits, Refused

#: The skew of the `10002` probe: far past the 5 s receive window (`RestClientConfig`).
SKEW_MS: Final = 60_000
#: How often a soak re-measures the clock offset.
SOAK_OFFSET_EVERY_S: Final = 600.0
#: The idle phase's verdicts on ADR-0006's "zero missed executions".
MET: Final = "met"
NOT_MET: Final = "not met"
NO_DATA: Final = "no data"
#: The port calls that write orders: a soak sends none.
ORDER_CALLS: Final = ("create", "amend", "cancel", "cancel_all")
_DAY_US: Final = 86_400_000_000


def _venue_now_us(h: Harness, *, slack: int) -> int:
    """Now on the exchange's clock (host plus the measured offset), as `execTime` reads, moved
    by `slack` times the offset's own uncertainty: half its best round trip, plus the 1 ms the
    venue's whole-ms `time` truncates. The soak's window is widened by it at both ends, so no
    execution of the window falls outside it (the end is the read itself: nothing later)."""
    rtt = h.offset.best_rtt_ms or 0.0
    return h.now_us() + (h.offset.value or 0) * 1000 + slack * round((1 + rtt / 2) * 1000)


def zero_missed(backfill_only: int | None) -> str:
    """ADR-0006's claim over a soak's window: `met` when the backfill listed no execution the
    stream missed, `not met` when it listed one or more (that is the finding), `no data` when
    the read did not happen."""
    if backfill_only is None:
        return NO_DATA
    return MET if backfill_only == 0 else NOT_MET


async def _missed(h: Harness, start_us: int) -> tuple[int | None, dict[str, object]]:
    """The execution list from `start_us` to now, through the port: how many executions it
    holds that the stream never delivered, or `None` with the error class if it failed."""
    end_us = max(start_us, _venue_now_us(h, slack=1))
    try:
        fills = await h.port.executions(h.account, start_us, end_us)
    except ExchangeError as exc:
        return None, {"error": type(exc).__name__}
    h.stream.rest_executions(fills)
    listed = {f.exec_id for f in fills}
    missed = len(listed - h.stream.stream_execs)
    return missed, {"listed": len(listed), "on_stream": len(h.stream.stream_execs)}


def idle_phase(
    h: Harness, held_s: float, missed: int | None, backfill: dict[str, object]
) -> dict[str, object]:
    """The soak's idle-phase block (see the module docstring). `orders_sent` counts every
    order call the guard let through, answered or not."""
    connector = h.connector
    gaps = {} if connector is None else connector.gaps()
    sent = sum(len(h.port.timings.port_ms.get(call, [])) for call in ORDER_CALLS)
    return {
        "held_s": round(held_s, 1),
        "orders_sent": sent,
        "dials": None if connector is None else connector.dials,
        "reconnects": None if connector is None else max(0, connector.dials - 1),
        "outages": len(h.stream.gaps_s),
        **gaps,
        "backfill": backfill,
        "backfill_only_executions": missed,
        "zero_missed_executions": zero_missed(missed),
    }


async def run_soak(h: Harness, cfg: RunConfig) -> dict[str, object]:
    await h.measure_offset()
    deadline = h.monotonic() + cfg.hours * 3600
    async with h.private_stream():
        held_from, window_start = h.monotonic(), _venue_now_us(h, slack=-1)
        while (left := deadline - h.monotonic()) > 0:
            if await h.shutdown.pause(min(SOAK_OFFSET_EVERY_S, left)):
                break
            if deadline - h.monotonic() > 0:
                await h.measure_offset()
        held_s = h.monotonic() - held_from
        missed, backfill = await _missed(h, window_start)
    connector = h.connector
    return {
        "hours": cfg.hours,
        "meets_ticket": cfg.hours >= SOAK_HOURS,
        "dials": None if connector is None else connector.dials,
        "reconnects": None if connector is None else max(0, connector.dials - 1),
        "frames": None if connector is None else dict(sorted(connector.counts.items())),
        "max_silence_s": None if connector is None else round(connector.max_silence_s, 3),
        "idle_phase": idle_phase(h, held_s, missed, backfill),
    }


async def run_shapes(h: Harness, cfg: RunConfig) -> dict[str, object]:
    instrument = await h.public.instrument()
    limits, qty = QtyLimits.of(instrument, multiple=1, max_multiple=cfg.max_qty_multiple)
    h.port.limits = limits
    await h.preflight()
    await h.measure_offset()
    ref = await h.public.reference()
    away, _, stop = prices(ref, "buy", cfg, instrument.tick_size)
    link = h.links.new("entry")
    create = PlaceOrderRequest(
        account=h.account,
        symbol=SYMBOL,
        side="buy",
        order_type="limit",
        qty=qty,
        price=away,
        time_in_force="post_only",
        order_link_id=link,
        stop_loss=stop,
    )
    first = await h.port.place_order(create)
    duplicate: dict[str, object] = {"first_ok": first.ok}
    try:
        again = await h.port.place_order(create)
        duplicate |= {"raised": None, "second_ok": again.ok, "code": again.exchange_ret_code}
    except ExchangeError as exc:
        duplicate |= {"raised": type(exc).__name__, "code": exc.exchange_ret_code}
    finally:
        if first.ok:
            await h.port.cancel_order(
                CancelOrderRequest(
                    account=h.account,
                    symbol=SYMBOL,
                    order_link_id=link,
                    exchange_order_id=first.exchange_order_id,
                )
            )
    drift: dict[str, object] = {"skew_ms": -SKEW_MS}
    if h.skewed_port is None:
        raise Refused("the 10002 probe needs the adapter's port factory")
    skewed = h.skewed_port(-SKEW_MS)
    try:
        await skewed.wallet(h.account)
        drift["raised"] = None
    except ExchangeError as exc:
        drift |= {"raised": type(exc).__name__, "code": exc.exchange_ret_code}
    recorder = h.recorder
    replies = {} if recorder is None else recorder.shapes
    attempts = {} if recorder is None else dict(recorder.codes)
    for code in (110072, 10001):
        if code in replies:
            duplicate |= {"reply": replies[code], "attempts": attempts.get(code, 0)}
            break
    drift |= {"reply": replies.get(10002), "attempts": attempts.get(10002, 0)}
    return {"duplicate": duplicate, "10002": drift, "10018": replies.get(10018)}


async def run_retention(h: Harness, cfg: RunConfig) -> dict[str, object]:
    now = h.now_us()
    since = now - 9 * _DAY_US if cfg.since_ms is None else cfg.since_ms * 1000
    orders = await h.port.order_history(h.account, start=since, end=now)
    ages = [(now - o.created_at) / _DAY_US for o in orders]
    return {
        "since_ms": since // 1000,
        "rows": len(orders),
        "by_state": dict(sorted(Counter(o.state for o in orders).items())),
        "older_than_7d": sum(1 for age in ages if age > 7),
        "older_than_1d": sum(1 for age in ages if age > 1),
        "age_days": stats(ages),
    }
