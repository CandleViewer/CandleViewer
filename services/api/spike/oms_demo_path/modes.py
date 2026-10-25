"""`soak`, `shapes` and `retention` (#843 A4 brief item 4).

- `soak`: the private stream open for `--hours` with no orders: dials (reconnects), heartbeats
  and pongs, `auth` grants and refusals, `down`s and the gaps they open, the longest silence.
  The offset is re-measured every 10 minutes, so each `auth` is signed on the exchange's clock.
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
_DAY_US: Final = 86_400_000_000


async def run_soak(h: Harness, cfg: RunConfig) -> dict[str, object]:
    await h.measure_offset()
    deadline = h.monotonic() + cfg.hours * 3600
    async with h.private_stream():
        while (left := deadline - h.monotonic()) > 0:
            if await h.shutdown.pause(min(SOAK_OFFSET_EVERY_S, left)):
                break
            if deadline - h.monotonic() > 0:
                await h.measure_offset()
    connector = h.connector
    return {
        "hours": cfg.hours,
        "meets_ticket": cfg.hours >= SOAK_HOURS,
        "dials": None if connector is None else connector.dials,
        "reconnects": None if connector is None else max(0, connector.dials - 1),
        "frames": None if connector is None else dict(sorted(connector.counts.items())),
        "max_silence_s": None if connector is None else round(connector.max_silence_s, 3),
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
