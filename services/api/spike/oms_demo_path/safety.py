"""The harness's safety checks (#843 A4 brief item 6). Online they guard a real demo account;
every one is proven offline (`tests/test_safety.py`).

- `check_environment`: `Settings.environment` is demo (C-2.11); `check_venue_urls`: the adapter's
  demo entries are the pinned allow-list, which the recording seams enforce on every request and
  dial (`recorder.py`).
- `check_online_args` and `confirm`: `--demo` needs `--i-understand-this-places-demo-orders`, the
  account and key ids, the ticket's floors and a typed confirmation.
- `check_audit_dir`: the harness's audit WAL is never the stack's (brief item 2).
- `check_flat`: a run that touches orders starts with no open order on any USDT perpetual and no
  position, both read account-wide (the adapter's `settleCoin` reads), and with no row of those
  reads set aside by the adapter (`check_none_set_aside`, R3-04: an order of ours naming another
  account or environment, which the reads drop); until that holds the run is not armed, and a
  refusal touches nothing (ruling R1C-02 (a)).
- `key_mismatch` (fold 3): the key's live rights, read through the adapter's own signed key-info
  read (`harness.Harness.check_key`, the first signed call of every mode that signs anything:
  the coordinator's ruling 2 of fold 4), against what M2's import admitted it with (C-2.8): no
  withdrawal or transfer right, no right outside the import's allow-list, write access with both
  trade rights, and an IP allow-list of host addresses. Any mismatch refuses the run, and
  nothing is touched.
- `GuardedPort`: the only trading surface the modes see. BTCUSDT only; no size above the cap;
  a native `stop_loss` on the protective side of every position-opening order (C-2.6); a close
  is a reduce-only market order with no stop (the venue refuses a stop on one), so it never
  opens; no amend removes a stop; an amend or a cancel names one of the run's own orders; no
  cancel-all, batch, leverage, stop write, withdrawal or transfer (C-2.8). No row, no order: each
  create's intent is written and fsynced to the run's ledger (`ledger.IntentLedger`) before it
  is sent, outside its measured window, and a create whose row is not on disk is not sent.
- `RunScope` and `flatten` (ruling R1C-02 (b)): what the run owns is the orders its intent ledger
  lists and the fills of those orders, never what an id's form suggests. SIGINT, SIGTERM, SIGHUP
  (the owner's terminal closing) or an unhandled error ends an armed mode, then the flatten
  cancels the run's own open orders one by one and closes, reduce-only, the quantity its own
  fills hold open, before M2 and audit stop (`run.py`). It never cancels or closes anything else:
  a foreign order or position is left. A stop that arrives before the run is armed ends it
  unarmed (`Stopped`): nothing touched.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import signal
import time
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from ipaddress import ip_network
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal
from uuid import UUID

from candleviewer.accounts.verification import ALLOWED_RIGHTS, TRADE_GROUP, TRADE_RIGHTS
from candleviewer.domain import key_permissions
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
from candleviewer.exchange.bybit.metrics import bybit_rows_refused_total
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
    from uuid import UUID as AccountUuid

    from candleviewer.accounts.verification import KeyFacts
    from candleviewer.domain.events import Instrument
    from candleviewer.domain.primitives import OrderLinkId, Side, Symbol, TsUs
    from candleviewer.exchange.base.ports import PrivateStream, TradingPort
    from candleviewer.settings import Settings
    from spike.oms_demo_path.ledger import IntentLedger

#: Written into the harness's own WAL directory at its first start: a WAL without it is another
#: writer's, and the harness refuses it.
WAL_MARKER: Final = "SPIKE-E29-K01.harness-wal"
_DAY_MS: Final = 86_400_000
#: The characters of one of our `orderLinkId`s that name its run: `cv`, the environment letter,
#: `-` and the run's trade group (24 §8.3: `{prefix}{env}-{group22}-{acct4}-{seq2}{suffix}`). The
#: owner finds a run's orders by it in the venue's UI; what the run owns is its ledger's alone.
LINK_PREFIX_LEN: Final = 26
#: The flatten's whole budget: inside the container's `stop_grace_period` (60 s), so a stop
#: never ends in a kill before the summary is written (R1C-14).
FLATTEN_DEADLINE_S: Final = 40.0
#: How long a close the venue accepted counts as filled before its fill is listed: a slow
#: execution list never makes the flatten close twice; past it, the list is believed.
PENDING_S: Final = 10.0
_ZERO: Final = Decimal(0)


class Refused(RuntimeError):
    """A safety check refused the run or a request; nothing was sent."""


class Stopped(RuntimeError):
    """A stop (SIGINT, SIGTERM, SIGHUP) arrived before the run was armed: it ends `stopped`
    with nothing on the account touched (R2-06)."""


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
    """The run's arguments: the size bounds for every run, and `flatten`'s failed run; for
    `--demo`, consent, the ids and the ticket's floors (`cycles` >=200 over >=4 h; `retention`
    on day 8 or later; `flatten` has none)."""
    if cfg.max_qty_multiple > QTY_MULTIPLE_CEILING:
        raise Refused(f"--max-qty-multiple is above its ceiling of {QTY_MULTIPLE_CEILING}")
    if not 1 <= cfg.qty_multiple <= cfg.max_qty_multiple:
        raise Refused("--qty-multiple must be between 1 and --max-qty-multiple")
    if cfg.mode == "flatten" and cfg.run_dir is None:
        raise Refused("flatten needs --run-dir, the failed run's directory (its summary's scope)")
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
    """Ruling R1C-02 (a): a flat account, from reads of every USDT perpetual (`open_orders` with
    no symbol and `positions`, both the adapter's `settleCoin` form): no open order, no
    position."""
    if orders:
        raise Refused("the account has an open order: a run starts flat; nothing was touched")
    if any(p.qty > 0 for p in positions):
        raise Refused("the account holds a position: a run starts flat; nothing was touched")


def rows_set_aside() -> dict[str, float]:
    """The adapter's `bybit_rows_refused_total` in this process, by reason: the rows its trading
    reads dropped (`trading_parse.refuse_row`, logged as `bybit_row_refused`). Read, never set."""
    return {
        sample.labels["reason"]: sample.value
        for family in bybit_rows_refused_total.collect()
        for sample in family.samples
        if sample.name.endswith("_total")
    }


def check_none_set_aside(before: Mapping[str, float], after: Mapping[str, float]) -> None:
    """R3-04: the flat check's reads hid no row. The adapter drops a row whose `orderLinkId` is
    one of ours naming another account or environment (`trading_parse.owner_refusal`), so
    `check_flat` cannot see such an order; `rows_set_aside` moving across those reads (`before`,
    `after`) refuses the run, and nothing was touched."""
    moved = {r: int(n - before.get(r, 0.0)) for r, n in after.items() if n > before.get(r, 0.0)}
    if moved:
        counts = ", ".join(f"{reason} +{n}" for reason, n in sorted(moved.items()))
        raise Refused(
            f"the flat check's reads held rows the adapter set aside ({counts}): an order of ours"
            " naming another account or environment is invisible to it; nothing was touched"
        )


def _one_host(entry: str) -> bool:
    """A single host address (bare, or a /32 or /128 network): never a wildcard or a range."""
    try:
        net = ip_network(entry, strict=True)
    except ValueError:
        return False
    return net.prefixlen == net.max_prefixlen


def _allow_listed(permissions: Mapping[str, object]) -> bool:
    """Every group a list of rights the import's allow-list admits for it (SR-030, #2270)."""
    return all(
        isinstance(rights, list)
        and all(isinstance(r, str) and r in ALLOWED_RIGHTS.get(group, frozenset()) for r in rights)
        for group, rights in permissions.items()
    )


def key_mismatch(facts: KeyFacts) -> str | None:
    """The first way the key's live rights differ from what M2's import admitted it with (C-2.8):
    a withdrawal or transfer right (the shared deny-list the import applies; rights it cannot judge
    count, fail closed); a right outside the import's allow-list (a fund group's, a spot right);
    read-only; a trade right missing; no IP allow-list; an entry that is no host address (a
    wildcard or a range). `None` when it matches. Fund rights first, as M13 judges a key."""
    try:
        funds = key_permissions.grants_fund_right(facts.permissions)
    except key_permissions.PermissionsUnreadable:
        funds = True
    if funds:
        return "the key holds a withdrawal or transfer right (C-2.8)"
    if not _allow_listed(facts.permissions):
        return "the key holds a right the import's allow-list refuses (SR-030)"
    if facts.read_only:
        return "the key is read-only: it cannot trade"
    trade = facts.permissions.get(TRADE_GROUP)
    if not isinstance(trade, list) or not set(TRADE_RIGHTS) <= set(trade):
        return "the key lacks a trade right (ContractTrade Order and Position)"
    if not facts.ip_whitelist:
        return "the key has no IP allow-list (C-2.8)"
    if not all(_one_host(entry) for entry in facts.ip_whitelist):
        return "the key's IP allow-list holds a wildcard or a range, not host addresses"
    return None


def key_record(facts: KeyFacts, mismatch: str | None) -> dict[str, object]:
    """The summary's `key_check`: what was judged and why, never a value (no UID, address or key
    id)."""
    return {
        "read": "GET /v5/user/query-api: the adapter's key-info read, signed by M2 (key_verify)",
        "verdict": "compliant" if mismatch is None else "refused",
        "reason": mismatch,
        "read_only": facts.read_only,
        "ip_allow_list_entries": len(facts.ip_whitelist),
    }


def digest(value: str) -> str:
    """A run's handle on a value it never writes: the first 16 hex characters of its sha256."""
    return hashlib.sha256(value.encode()).hexdigest()[:16]


class RunScope:
    """What a run owns on the account (ruling R1C-02 (b)): the orders its intent ledger lists
    (`ledger.IntentLedger`: each create's row, written before it was sent), and the trade fills
    of those orders, from `start_us` (the venue's clock, when it was armed). Nothing is owned by
    the form of its id: an order the ledger does not list is never the run's, whatever its prefix.
    `net` is what the run's own fills hold open. A `flatten` run adopts a failed run's scope
    (`adopt`): its window from that run's summary, its orders from that run's ledger. The BTCUSDT
    fills in the window that are not the run's are counted by type (`not_ours`, R2-12): a native
    stop's close is a `trade` no ledger lists (as a manual trade is, which a run forbids), a
    liquidation a `bust_trade`, an ADL an `adl_trade`; such a close leaves the run's own net as it
    was, since its order is in no ledger."""

    def __init__(
        self,
        ledger: IntentLedger,
        account_id: AccountUuid,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ledger = ledger
        self.account = digest(str(account_id))
        self.start_us: int | None = None
        self._monotonic = monotonic
        #: Each own fill: its exec id, to its order's link and its signed quantity (buy > 0).
        self.fills: dict[str, tuple[str, Decimal]] = {}
        #: Each reduce-only close the venue accepted: its link, to its size and when it was sent.
        self.closes: dict[str, tuple[Decimal, float]] = {}
        #: Each BTCUSDT fill in the window that is not the run's: its exec id, to its type.
        self.not_ours: dict[str, str] = {}

    def owns(self, link: str | None) -> bool:
        return self.ledger.owns(link)

    def add(self, fills: Iterable[Execution]) -> None:
        for fill in fills:
            if fill.symbol != SYMBOL:
                continue
            if not self.owns(fill.order_link_id):
                self.not_ours[fill.exec_id] = fill.exec_type
            elif fill.exec_type == "trade":
                signed = fill.qty if fill.side == "buy" else -fill.qty
                self.fills[fill.exec_id] = (fill.order_link_id, signed)

    def not_ours_by_type(self) -> dict[str, int]:
        """The window's BTCUSDT fills that are not the run's, counted by type (see the class)."""
        return dict(sorted(Counter(self.not_ours.values()).items()))

    def net(self) -> Decimal:
        return sum((qty for _, qty in self.fills.values()), _ZERO)

    def sent_close(self, link: str, qty: Decimal) -> None:
        self.closes[link] = (qty, self._monotonic())

    def unconfirmed(self) -> Decimal:
        """The closes accepted in the last `PENDING_S` whose fill no read has listed yet."""
        listed = {owner for owner, _ in self.fills.values()}
        now = self._monotonic()
        return sum(
            (
                qty
                for link, (qty, at) in self.closes.items()
                if link not in listed and now - at < PENDING_S
            ),
            _ZERO,
        )

    async def adopt(self, record: Mapping[str, object], ledger: Path) -> None:
        """A failed run's scope: its window from its summary's `run_scope` (refused when it names
        none: that run was never armed), then its orders from its intent ledger at `ledger`
        (`IntentLedger.adopt`); the window reaches back to its start."""
        start_ms = record.get("window_start_ms")
        if not isinstance(start_ms, int):
            raise Refused("that summary names no run scope: nothing to flatten from it")
        await self.ledger.adopt(ledger)
        start = start_ms * 1000
        self.start_us = start if self.start_us is None else min(self.start_us, start)

    def record(self) -> dict[str, object]:
        """The summary's `run_scope`: the ledger's file, a digest and a time, never an id."""
        return {
            "ledger": self.ledger.path.name,
            "account_digest": self.account,
            "window_start_ms": None if self.start_us is None else self.start_us // 1000,
        }


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
    (`Timings`), so the recording transport can split our overhead from the venue's RTT. With a
    `scope` (the harness sets the run's), an amend or a cancel of another order is refused. A
    create is sent only once its intent row is in `ledger` (the harness sets the run's): with no
    ledger, or a row not written, it is refused before anything leaves (no row, no order)."""

    def __init__(self, port: TradingPort, timings: Timings | None = None) -> None:
        self._port = port
        self.timings = timings if timings is not None else Timings()
        self.limits: QtyLimits | None = None
        self.scope: RunScope | None = None
        self.ledger: IntentLedger | None = None
        self.openers = 0
        self.closes = 0

    def _own(self, link: str | None) -> None:
        if self.scope is not None and not self.scope.owns(link):
            raise Refused("not one of the run's orders: the harness touches only its own")

    async def _intend(self, req: PlaceOrderRequest) -> None:
        """No row, no order: `req`'s intent is on disk in the ledger (written and fsynced)
        before it is sent, and before its measured window opens (`_call`)."""
        if self.ledger is None:
            raise Refused("no row, no order: no intent ledger; nothing was sent")
        await self.ledger.record(req)

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
        await self._intend(req)
        async with self._call("create"):
            ack = await self._port.place_order(req)
        if req.reduce_only:
            self.closes += 1
            if ack.ok and self.scope is not None:
                self.scope.sent_close(req.order_link_id, req.qty)
        else:
            self.openers += 1
        return ack

    async def amend_order(self, req: AmendOrderRequest) -> OrderAck:
        check_symbol(req.symbol)
        self._own(req.order_link_id)
        if req.qty is not None:
            self._qty(req.qty, closing=False)
        stop = req.stop_loss
        if stop is not None and (not stop.is_finite() or stop <= 0):
            raise Refused("C-2.6: an amend never removes or zeroes the native stop")
        async with self._call("amend"):
            return await self._port.amend_order(req)

    async def cancel_order(self, req: CancelOrderRequest) -> OrderAck:
        check_symbol(req.symbol)
        self._own(req.order_link_id)
        async with self._call("cancel"):
            return await self._port.cancel_order(req)

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
    """SIGINT, SIGTERM, SIGHUP (the owner's terminal closing: its default would kill the run
    where it stands, an order resting and nothing written) or an error ends the mode; the first
    reason is the one kept. `sleep` is the clock the pauses run on (a test's virtual one)."""

    def __init__(self, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.event = asyncio.Event()
        self.reason: str | None = None
        self._sleep = sleep

    def trip(self, reason: str) -> None:
        if self.reason is None:
            self.reason = reason
        self.event.set()

    def install(self, loop: asyncio.AbstractEventLoop) -> Callable[[], None]:
        signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
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


def _held(positions: Sequence[Position], side: Side) -> tuple[Decimal, Literal[0, 1, 2]]:
    """The venue's BTCUSDT position on `side`: its size and `positionIdx`."""
    rows = [p for p in positions if p.symbol == SYMBOL and p.side == side and p.qty > 0]
    return sum((p.qty for p in rows), _ZERO), (rows[0].position_idx if rows else 0)


def _text(qty: Decimal) -> str:
    """A quantity as plain decimal text, its trailing zeros dropped (`0.000` is `0`)."""
    return format(qty.normalize(), "f")


def _signed(positions: Sequence[Position]) -> Decimal:
    rows = [p for p in positions if p.symbol == SYMBOL and p.side is not None]
    return sum((p.qty if p.side == "buy" else -p.qty for p in rows), _ZERO)


async def flatten(
    port: GuardedPort,
    account: AccountRef,
    scope: RunScope,
    new_link: Callable[[], str],
    *,
    venue_now_us: Callable[[], int],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    attempts: int = 3,
    settle_s: float = 1.0,
    deadline_s: float = FLATTEN_DEADLINE_S,
) -> dict[str, object]:
    """Ruling R1C-02 (b): the run's own state, and nothing else, made flat. What is the run's is
    what its intent ledger lists (`scope.owns`), never a guess from an id's form.

    1. Its own open orders (each one its ledger lists) are cancelled one by one, re-read until
       none is left; no cancel-all, so a foreign order is never touched.
    2. Its net, what its own fills hold open (the fills of orders its ledger lists), is read again
       from the venue's execution list over its window (`scope.start_us` to `venue_now_us()`),
       and closed by a reduce-only market order of at most the venue's position on that side
       (its row written first, as every create's); re-read until the net is zero. A close the
       venue accepted but no read has listed yet counts (`RunScope.unconfirmed`), so a slow list
       never makes it close twice.

    Every failure is recorded by class, never raised; the whole stays within `deadline_s`. It
    needs M2 and audit up (every signing is audited first), so it runs before they stop."""
    errors: list[str] = []
    began = monotonic()

    def late() -> bool:
        if monotonic() - began <= deadline_s:
            return False
        errors.append("deadline")
        return True

    cancelled = foreign_orders = 0
    own_left: int | None = None  # unknown until a read succeeds
    for attempt in range(attempts + 1):
        if late():
            break
        try:
            orders = await port.open_orders(account, SYMBOL)
        except Exception as exc:  # recorded by class; the flatten goes on
            errors.append(f"open_orders:{type(exc).__name__}")
            await sleep(settle_s)
            continue
        own = [o for o in orders if scope.owns(o.order_link_id)]
        own_left, foreign_orders = len(own), len(orders) - len(own)
        if not own or attempt == attempts:
            break
        for order in own:
            cancel = CancelOrderRequest(
                account=account,
                symbol=SYMBOL,
                order_link_id=order.order_link_id,
                exchange_order_id=order.exchange_order_id,
            )
            try:
                if (await port.cancel_order(cancel)).ok:
                    cancelled += 1
                    scope.closes.pop(order.order_link_id, None)  # a close it ends never fills
            except Exception as exc:
                errors.append(f"cancel:{type(exc).__name__}")
        await sleep(settle_s)
    closes = 0
    closed, net, net_before, venue = _ZERO, _ZERO, None, None
    flat = False
    for _ in range(attempts + 1):
        if late():
            break
        try:
            if scope.start_us is not None:
                scope.add(await port.executions(account, scope.start_us, venue_now_us()))
            positions = await port.positions(account)
        except Exception as exc:
            errors.append(f"read:{type(exc).__name__}")
            await sleep(settle_s)
            continue
        net, venue = scope.net(), _signed(positions)
        net_before = net if net_before is None else net_before
        if net == 0:
            flat = own_left == 0
            break
        side: Side = "buy" if net > 0 else "sell"
        held, idx = _held(positions, side)
        unconfirmed = scope.unconfirmed()
        qty = min(abs(net) - unconfirmed, held)
        if qty <= 0:
            if not unconfirmed:  # own fills the venue's position no longer holds on that side
                errors.append("net_not_held")
                break
            await sleep(settle_s)
            continue
        link = new_link()
        close = PlaceOrderRequest(
            account=account,
            symbol=SYMBOL,
            side="sell" if side == "buy" else "buy",
            order_type="market",
            qty=qty,
            order_link_id=link,
            reduce_only=True,
            position_idx=idx,
            lane="critical",
        )
        try:
            if (await port.place_order(close)).ok:
                closes += 1
                closed += qty
        except Exception as exc:
            errors.append(f"close:{type(exc).__name__}")
        await sleep(settle_s)
    return {
        "scope": "the run's own orders and fills",
        "cancelled": cancelled,
        "own_open_orders_left": own_left,
        "own_net_qty": _text(net_before if net_before is not None else _ZERO),
        "closed_qty": _text(closed),
        "flatten_orders": closes,
        "own_net_after": _text(net),
        "flat": flat,
        "not_ours_left": {
            "open_orders": foreign_orders,
            "venue_position_less_own_net": None if venue is None else _text(venue - net),
        },
        "fills_not_ours_in_window": scope.not_ours_by_type(),
        "errors": errors,
    }
