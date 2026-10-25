"""The harness's safety checks (#843 A4 brief item 6). Online they guard a real demo account;
every one is proven offline (`tests/test_safety.py`).

- `check_environment`: `Settings.environment` is demo (C-2.11); `check_venue_urls`: the adapter's
  demo entries are the pinned allow-list, which the recording seams enforce on every request and
  dial (`recorder.py`).
- `check_online_args` and `confirm`: `--demo` needs `--i-understand-this-places-demo-orders`, the
  account and key ids, the ticket's floors and a typed confirmation.
- `check_audit_dir`: the harness's audit WAL is never the stack's (brief item 2).
- `check_flat`: an online run starts with no open order and no position.
- `GuardedPort`: the only trading surface the modes see. BTCUSDT only; no size above the cap;
  a native `stop_loss` on the protective side of every position-opening order (C-2.6); a close
  is a reduce-only market order with no stop (the venue refuses a stop on one), so it never
  opens; no amend removes a stop; no batch, leverage, stop write, withdrawal or transfer (C-2.8).
- `Shutdown` and `flatten`: SIGINT, SIGTERM or an unhandled error ends the mode, then
  `cancel_all` and a reduce-only flatten run before M2 and audit stop (`run.py`).
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final
from uuid import UUID

from candleviewer.exchange.base.models import (
    AccountRef,
    AmendOrderRequest,
    CancelOrderRequest,
    Execution,
    Order,
    OrderAck,
    PlaceOrderRequest,
    Position,
    Wallet,
)
from candleviewer.observability.context import spawn
from spike.oms_demo_path.config import (
    CONFIRMATION,
    DEMO_PRIVATE_WS,
    DEMO_REST_BASE,
    MIN_CYCLES,
    MIN_HOURS,
    QTY_MULTIPLE_CEILING,
    RETENTION_MIN_DAYS,
    SYMBOL,
    RunConfig,
)
from spike.oms_demo_path.measure import CallRecord, Timings

if TYPE_CHECKING:
    from candleviewer.domain.events import Instrument
    from candleviewer.domain.primitives import OrderLinkId, Symbol, TsUs
    from candleviewer.exchange.base.ports import PrivateStream, TradingPort
    from candleviewer.settings import Settings

#: Written into the harness's own WAL directory at its first start: a WAL without it is another
#: writer's, and the harness refuses it.
WAL_MARKER: Final = "SPIKE-E29-K01.harness-wal"
_DAY_MS: Final = 86_400_000


class Refused(RuntimeError):
    """A safety check refused the run or a request; nothing was sent."""


def check_environment(settings: Settings) -> None:
    if settings.environment.value != "demo":
        raise Refused("Settings.environment is not demo: the harness trades demo only (C-2.11)")


def check_venue_urls(rest_bases: Mapping[str, str], ws_urls: Mapping[str, str]) -> None:
    if rest_bases.get("demo") != DEMO_REST_BASE or ws_urls.get("demo") != DEMO_PRIVATE_WS:
        raise Refused("the adapter's demo host or stream is not the pinned demo allow-list")


#: A proxy httpx would mount for a matching URL ahead of the transport the adapter is given, so a
#: request would bypass the recording seam and its host check.
PROXY_VARIABLES: Final = frozenset({"http_proxy", "https_proxy", "all_proxy"})


def check_no_proxy(environ: Mapping[str, str]) -> None:
    if any(name.lower() in PROXY_VARIABLES and value for name, value in environ.items()):
        raise Refused("a proxy variable is set: the seam would be bypassed; unset it")


def _canonical_uuid(value: str | None) -> bool:
    try:
        return value is not None and str(UUID(value)) == value
    except ValueError:
        return False


def check_online_args(cfg: RunConfig, *, now_ms: int) -> None:
    """The run's arguments: the size bounds for every run; for `--demo`, consent, the ids and
    the ticket's floors (`cycles` >=200 over >=4 h; `retention` on day 8 or later)."""
    if cfg.max_qty_multiple > QTY_MULTIPLE_CEILING:
        raise Refused(f"--max-qty-multiple is above its ceiling of {QTY_MULTIPLE_CEILING}")
    if not 1 <= cfg.qty_multiple <= cfg.max_qty_multiple:
        raise Refused("--qty-multiple must be between 1 and --max-qty-multiple")
    if not cfg.online:
        return
    if not cfg.understood:
        raise Refused("--demo needs --i-understand-this-places-demo-orders")
    if cfg.account_id is None:
        raise Refused("--account-id (the exchange_accounts.id) is required with --demo")
    if not _canonical_uuid(cfg.key_ref):
        raise Refused("--key-ref must be the api_keys.id of the account's active key")
    if cfg.mode == "cycles" and cfg.cycles < MIN_CYCLES:
        raise Refused(f"an online run places at least {MIN_CYCLES} cycles")
    if cfg.mode == "cycles" and cfg.min_hours < MIN_HOURS:
        raise Refused(f"an online run paces its cycles over at least {MIN_HOURS:g} h")
    if cfg.mode == "retention":
        if cfg.since_ms is None:
            raise Refused("retention needs --since-ms, the earlier run's started_at_ms")
        if not RETENTION_MIN_DAYS * _DAY_MS <= now_ms - cfg.since_ms:
            raise Refused(f"retention runs on day {RETENTION_MIN_DAYS} or later of that run")


def confirm(read_line: Callable[[str], str]) -> None:
    typed = read_line(f'Type "{CONFIRMATION}" to place demo orders: ')
    if typed != CONFIRMATION:
        raise Refused("the typed confirmation did not match; nothing was sent")


def check_symbol(symbol: str) -> None:
    if symbol != SYMBOL:
        raise Refused(f"the harness trades {SYMBOL} only")


def _unescape(field: str) -> str:
    return field.replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")


def mount_root(directory: Path, mountinfo: str) -> str:
    """The `root` field (the source path) of the mount holding `directory`, `""` if unknown."""
    best, root = -1, ""
    for line in mountinfo.splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        point = Path(_unescape(fields[4]))
        if directory == point or point in directory.parents:
            depth = len(point.parts)
            if depth > best:
                best, root = depth, _unescape(fields[3])
    return root


def check_audit_dir(wal_path: str, *, stack_wal: str, stack_volume: str, mountinfo: str) -> Path:
    """The harness's WAL directory, made `0700` and marked; refused if it is, or could be, the
    stack's: its path or directory, a directory (or its parent) holding `lane/` or another
    writer's WAL, or a mount of the stack's audit volume. Two writers on one WAL truncate each
    other's frames (`audit/wal.py`: no lock), and the order lane's files are cv-api's alone."""
    path = Path(wal_path)
    if not path.is_absolute() or ".." in path.parts:
        raise Refused("the harness's audit WAL path must be absolute and free of '..'")
    directory, stack = path.parent, Path(stack_wal)
    if directory == stack.parent or os.path.realpath(path) == os.path.realpath(stack):
        raise Refused("that is the stack's audit WAL directory: the harness keeps its own")
    for holder in (directory, directory.parent):
        if (holder / "lane").exists() or (holder / "lane").is_symlink():
            raise Refused("the WAL directory or its parent holds lane/ (cv-api's audit lane)")
    if (directory.parent / stack.name).exists():
        raise Refused("the WAL directory's parent holds another writer's WAL")
    if path.exists() and not (directory / WAL_MARKER).exists():
        raise Refused("that WAL exists and the harness did not create it")
    if stack_volume and stack_volume in mount_root(directory, mountinfo):
        raise Refused("the WAL directory sits on the stack's audit volume")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    marker = directory / WAL_MARKER
    if not marker.exists():
        marker.write_text("the E29-K01 harness's own audit WAL; never cv-api's\n")
        marker.chmod(0o600)
    return directory


def check_flat(orders: Sequence[Order], positions: Sequence[Position]) -> None:
    if orders:
        raise Refused("the account has an open order: an online run starts flat")
    if any(p.qty > 0 for p in positions):
        raise Refused("the account holds a position: an online run starts flat")


@dataclass(frozen=True, slots=True)
class QtyLimits:
    """The instrument's minimum and step, and the cap (`--max-qty-multiple` minimums)."""

    min_qty: Decimal
    step: Decimal
    max_qty: Decimal

    @classmethod
    def of(
        cls, instrument: Instrument, *, multiple: int, max_multiple: int
    ) -> tuple[QtyLimits, Decimal]:
        """The limits and the order size, `multiple` minimums."""
        limits = cls(
            instrument.min_order_qty,
            instrument.qty_step,
            instrument.min_order_qty * max_multiple,
        )
        return limits, instrument.min_order_qty * multiple


def _check_opener_stop(req: PlaceOrderRequest) -> None:
    """C-2.6: a position-opening order carries a positive native stop on the protective side."""
    stop = req.stop_loss
    if stop is None or not stop.is_finite() or stop <= 0:
        raise Refused("C-2.6: a position-opening order carries a native stop_loss")
    if req.price is not None and (stop >= req.price if req.side == "buy" else stop <= req.price):
        raise Refused("C-2.6: the stop_loss must sit on the protective side of the entry")


class GuardedPort:
    """The only trading surface the modes see (see the module docstring); every call is timed
    (`Timings`), so the recording transport can split our overhead from the venue's RTT."""

    def __init__(self, port: TradingPort, timings: Timings | None = None) -> None:
        self._port = port
        self.timings = timings if timings is not None else Timings()
        self.limits: QtyLimits | None = None
        self.openers = 0
        self.closes = 0

    @asynccontextmanager
    async def _call(self, name: str) -> AsyncIterator[CallRecord]:
        async with self.timings.call(name) as record:
            yield record

    def _qty(self, qty: Decimal, *, closing: bool) -> None:
        limits = self.limits
        if limits is None:
            raise Refused("no size limits yet: nothing is sent before the instrument is read")
        off_step = qty <= 0 or qty % limits.step != 0
        if off_step or (not closing and not limits.min_qty <= qty <= limits.max_qty):
            raise Refused("an order size off the step, under the minimum or above the cap")

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck:
        check_symbol(req.symbol)
        if req.reduce_only:
            if req.stop_loss is not None or req.take_profit is not None:
                raise Refused("a reduce-only close carries no stop: the venue refuses one")
            if req.order_type != "market":
                raise Refused("a close is a reduce-only market order")
            self._qty(req.qty, closing=True)
        else:
            self._qty(req.qty, closing=False)
            _check_opener_stop(req)
        async with self._call("create"):
            ack = await self._port.place_order(req)
        if req.reduce_only:
            self.closes += 1
        else:
            self.openers += 1
        return ack

    async def amend_order(self, req: AmendOrderRequest) -> OrderAck:
        check_symbol(req.symbol)
        if req.qty is not None:
            self._qty(req.qty, closing=False)
        stop = req.stop_loss
        if stop is not None and (not stop.is_finite() or stop <= 0):
            raise Refused("C-2.6: an amend never removes or zeroes the native stop")
        async with self._call("amend"):
            return await self._port.amend_order(req)

    async def cancel_order(self, req: CancelOrderRequest) -> OrderAck:
        check_symbol(req.symbol)
        async with self._call("cancel"):
            return await self._port.cancel_order(req)

    async def cancel_all(self, account: AccountRef, symbol: Symbol | None) -> Sequence[OrderAck]:
        check_symbol(symbol or "")
        async with self._call("cancel_all"):
            return await self._port.cancel_all(account, symbol)

    async def open_orders(
        self,
        account: AccountRef,
        symbol: Symbol | None = None,
        *,
        order_link_id: OrderLinkId | None = None,
    ) -> Sequence[Order]:
        async with self._call("open_orders"):
            return await self._port.open_orders(account, symbol, order_link_id=order_link_id)

    async def order_history(
        self,
        account: AccountRef,
        *,
        order_link_id: OrderLinkId | None = None,
        start: TsUs | None = None,
        end: TsUs | None = None,
    ) -> Sequence[Order]:
        async with self._call("order_history"):
            return await self._port.order_history(
                account, order_link_id=order_link_id, start=start, end=end
            )

    async def positions(self, account: AccountRef) -> Sequence[Position]:
        async with self._call("positions"):
            return await self._port.positions(account)

    async def executions(self, account: AccountRef, start: TsUs, end: TsUs) -> Sequence[Execution]:
        async with self._call("executions"):
            return await self._port.executions(account, start, end)

    async def wallet(self, account: AccountRef) -> Wallet:
        async with self._call("wallet"):
            return await self._port.wallet(account)

    async def subscribe_private(self, account: AccountRef) -> PrivateStream:
        return await self._port.subscribe_private(account)


class Shutdown:
    """SIGINT, SIGTERM or an error ends the mode; the first reason is the one kept. `sleep` is
    the clock the pauses run on (a test's virtual one)."""

    def __init__(self, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.event = asyncio.Event()
        self.reason: str | None = None
        self._sleep = sleep

    def trip(self, reason: str) -> None:
        if self.reason is None:
            self.reason = reason
        self.event.set()

    def install(self, loop: asyncio.AbstractEventLoop) -> Callable[[], None]:
        signals = (signal.SIGINT, signal.SIGTERM)
        for sig in signals:
            loop.add_signal_handler(sig, self.trip, f"signal:{sig.name}")

        def remove() -> None:
            for sig in signals:
                loop.remove_signal_handler(sig)

        return remove

    async def pause(self, seconds: float) -> bool:
        """Wait `seconds` or until tripped; `True` when tripped."""
        if self.event.is_set():
            return True

        async def nap() -> None:
            await self._sleep(seconds)

        waiter = spawn(self.event.wait(), name="spike-shutdown-wait")
        timer = spawn(nap(), name="spike-shutdown-pause")
        try:
            await asyncio.wait({waiter, timer}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (waiter, timer):
                task.cancel()
            await asyncio.gather(waiter, timer, return_exceptions=True)
        return self.event.is_set()


async def flatten(
    port: GuardedPort,
    account: AccountRef,
    new_link: Callable[[], str],
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    attempts: int = 3,
    settle_s: float = 1.0,
) -> dict[str, object]:
    """Cancel every BTCUSDT order, then close any BTCUSDT position with a reduce-only market
    order, re-reading until flat; each failure is recorded by class, never raised. It needs M2
    and audit up (every signing is audited first), so it runs before they stop."""
    errors: list[str] = []
    cancel_calls = cancelled = closes = 0
    flat = False
    for _ in range(attempts):
        try:
            acks = await port.cancel_all(account, SYMBOL)
            cancel_calls += 1
            cancelled += sum(1 for a in acks if a.ok and a.order_link_id is not None)
        except Exception as exc:  # recorded by class; the flatten goes on
            errors.append(f"cancel_all:{type(exc).__name__}")
        try:
            if not await port.open_orders(account, SYMBOL):
                break
        except Exception as exc:
            errors.append(f"open_orders:{type(exc).__name__}")
    for _ in range(attempts):
        try:
            held = [p for p in await port.positions(account) if p.symbol == SYMBOL and p.qty > 0]
        except Exception as exc:
            errors.append(f"positions:{type(exc).__name__}")
            await sleep(settle_s)
            continue
        if not held:
            flat = True
            break
        for position in held:
            if position.side is None:
                continue
            close = PlaceOrderRequest(
                account=account,
                symbol=SYMBOL,
                side="sell" if position.side == "buy" else "buy",
                order_type="market",
                qty=position.qty,
                order_link_id=new_link(),
                reduce_only=True,
                position_idx=position.position_idx,
                lane="critical",
            )
            try:
                await port.place_order(close)
                closes += 1
            except Exception as exc:
                errors.append(f"close:{type(exc).__name__}")
        await sleep(settle_s)
    return {
        "cancel_all_calls": cancel_calls,
        "cancelled": cancelled,
        "flatten_orders": closes,
        "flat": flat,
        "errors": errors,
    }
