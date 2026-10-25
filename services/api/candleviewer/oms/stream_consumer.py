"""The private-stream consumer (E29-T05 #848, S4c; 24-internal-schemas.md Sec.8.12). Plain code
on the hot-path contract (C-2.20). One task per streamed account in a `TaskGroup` (C-2.18), each
taking its stream's rows and statuses inline in arrival order, so the adapter's bounded buffer is
the only backpressure: a row is fed to account health as evidence first, then its work is done (a
pairing push, a position, a wallet), and each status has its Sec.8.12 effect. Every await is
bounded, the stream is closed on every exit, and a cancel is never swallowed. Loop-agnostic: it
never hops, and treats `AccountHealthFeed` and `AccountNotices` as synchronous and non-blocking.
Ids only in logs and no figure of a wallet in any (C-12.6).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, Protocol, cast

import structlog
from pydantic import ValidationError

from candleviewer.accounts.service import AccountHealthFeed
from candleviewer.accounts.wallet import WalletSnapshot
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import (
    AccountRef,
    Position,
    PrivateEvent,
    PrivateStreamStatus,
    Wallet,
)
from candleviewer.exchange.base.ports import PrivateStream
from candleviewer.observability import spawn, spawn_child

from .errors import OrderRefused, ReconciliationUnavailable
from .ports import (
    AccountNotices,
    CredentialRejections,
    ReconciliationRequests,
    ResyncReason,
    StreamedAccounts,
    TradingAccounts,
)
from .push_mapping import ForPairing, ForProtection, NoB1Event, route
from .stream_push import PORT_TIMEOUT_S, Pager

REFRESH_S: Final = 15.0  # health's tracking refresh: the set read again, a dead task restarted
STREAM_SILENCE_S: Final = 30.0  # no row or status this long: the socket is dead (the ruling, Q9)
STOP_TIMEOUT_S: Final = 2.0  # inside 20 Sec.6.2's 15 s grace
POSITION_TAKE_TIMEOUT_S: Final = 50.0  # a protection reading crosses the facade's 30 s push (Q1)
UNREADABLE_AFTER: Final = 4  # failed refreshes in a row: the consumer is not doing its job
MAX_FUTURE_SKEW_US: Final = 5_000_000  # 24 Sec.14.2 rule 10, as `positions.MAX_FUTURE_SKEW`

type Outcome = Literal[
    "refresh_failed", "defect", "silence", "resolve_refused", "reconciliation_unavailable",
    "wallet_ahead", "wallet_skipped", "wallet_invalid", "stop_timeout", "close_timeout",
]  # fmt: skip
type Verdict = Literal["go", "end", "rotate"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ConsumerCounts(Protocol):
    def count(self, outcome: Outcome) -> None: ...  # sync; S8 binds a catalogue series


class PrivateStreams(Protocol):
    """The account's stream on its environment's port, built on the loop that consumes it."""

    async def subscribe(self, account: AccountRef) -> PrivateStream: ...


class RowPushes(Protocol):  # `StreamPushes`
    async def handle(self, account_id: AccountId, event: PrivateEvent, r: ForPairing) -> None: ...


class PositionRows(Protocol):
    """S5's seam: the position projection and the protection readings (24 Sec.8.12)."""

    async def take(
        self, account_id: AccountId, position: Position, route: ForProtection
    ) -> None: ...


class NoPositionRows:
    """`PositionRows` until S5: nothing is projected and no reading is taken; S8 never binds it."""

    async def take(self, account_id: AccountId, position: Position, route: ForProtection) -> None:
        _log().debug("stream_position_pending", account_id=str(account_id))


@dataclass(slots=True)
class _Session:
    ref: AccountRef
    down: int | None = None  # the epoch a `down` status ended: its stragglers are no evidence


class StreamConsumer:
    def __init__(
        self, *, accounts: StreamedAccounts, trading: TradingAccounts, streams: PrivateStreams,
        health: AccountHealthFeed, reconciliation: ReconciliationRequests,
        notices: AccountNotices, credentials: CredentialRejections, positions: PositionRows,
        pushes: RowPushes, counts: ConsumerCounts, pager: Pager, now_us: Callable[[], int],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        refresh_s: float = REFRESH_S, silence_s: float = STREAM_SILENCE_S,
    ) -> None:  # fmt: skip
        self._accounts, self._trading, self._streams = accounts, trading, streams
        self._health, self._recon, self._notices = health, reconciliation, notices
        self._credentials, self._positions, self._pushes = credentials, positions, pushes
        self._counts, self._pager, self._now_us, self._sleep = counts, pager, now_us, sleep
        self._refresh_s, self._silence_s = refresh_s, silence_s
        self._task: asyncio.Task[None] | None = None
        self._tasks: dict[AccountId, asyncio.Task[None]] = {}
        self._failures, self._stopped = 0, False
        self._paged: set[AccountId] = set()  # accounts whose defect or refused resync paged
        self._unavailable: set[AccountId] = set()

    def start(self) -> None:
        if self._task is None:
            self._task = spawn(self._run(), name="oms-stream-consumer")

    async def stop(self, timeout_s: float = STOP_TIMEOUT_S) -> None:
        """Cancel the consumer, which cancels every account's task and closes its stream."""
        self._stopped = True
        if self._task is None:
            return
        self._task.cancel()
        done, _ = await asyncio.wait({self._task}, timeout=timeout_s)
        if not done:
            _log().error("stream_consumer_stop_timeout")
            self._counts.count("stop_timeout")
        elif not self._task.cancelled():
            self._task.exception()  # retrieved, never raised: stopping ends it

    @property
    def fault(self) -> str | None:
        """Why the consumer is not doing its job, None while it is (S8 feeds `/readyz`)."""
        if self._task is not None and self._task.done() and not self._stopped:
            return "the consumer task ended"
        return "streamed accounts unreadable" if self._failures >= UNREADABLE_AFTER else None

    def accounts(self) -> frozenset[AccountId]:
        return frozenset(a for a, t in self._tasks.items() if not t.done())

    async def _run(self) -> None:
        async with asyncio.TaskGroup() as group:
            while True:
                await self._refresh(group)
                await self._sleep(self._refresh_s)

    async def _refresh(self, group: asyncio.TaskGroup) -> None:
        try:
            wanted = await self._bounded(self._accounts.streamed_accounts())
        except Exception as exc:  # keep the current set: no stream is closed for a failed read
            self._failures += 1
            _log().error("stream_accounts_unreadable", kind=type(exc).__name__)
            self._counts.count("refresh_failed")
            return
        self._failures = 0
        for gone in set(self._tasks) - wanted:
            self._tasks.pop(gone).cancel()
            self._paged.discard(gone)
            self._unavailable.discard(gone)
        for account_id in wanted:  # a task that ended restarts here: the only backoff
            task = self._tasks.get(account_id)
            if task is None or task.done():
                name = f"oms-stream-{account_id}"
                self._tasks[account_id] = spawn_child(group, self._account(account_id), name=name)

    async def _account(self, account_id: AccountId) -> None:
        """One account's stream, from its resolve to its end; nothing but a cancel leaves it."""
        try:
            ref = await self._resolve(account_id)
            while ref is not None:
                ref = await self._session(account_id, ref)
        except Exception as exc:  # a sibling's stream must survive this one's defect
            _log().error(
                "stream_account_defect", account_id=str(account_id), kind=type(exc).__name__
            )
            self._counts.count("defect")
            if account_id not in self._paged:
                self._paged.add(account_id)
                self._page(f"an account's private-stream consumer ended: {type(exc).__name__}")

    async def _resolve(self, account_id: AccountId) -> AccountRef | None:
        try:
            return await self._bounded(self._trading.trading_account(account_id))
        except (OrderRefused, TimeoutError):  # no active key yet, or a slow store: it retries
            _log().info("stream_account_unresolved", account_id=str(account_id))
            self._counts.count("resolve_refused")
            return None

    async def _session(self, account_id: AccountId, ref: AccountRef) -> AccountRef | None:
        """One stream until it ends; the account's next `AccountRef` after a `key_rotated`."""
        session = _Session(ref)
        stream = await self._bounded(self._streams.subscribe(ref))
        try:
            return await self._consume(account_id, session, stream)
        finally:
            await self._close(account_id, stream)

    async def _consume(
        self, account_id: AccountId, session: _Session, stream: PrivateStream
    ) -> AccountRef | None:
        while True:
            try:
                async with asyncio.timeout(self._silence_s):
                    item = await anext(stream)
            except StopAsyncIteration:
                return None
            except TimeoutError:  # a silent socket is down: the refresh restarts the task
                _log().warning("stream_silent", account_id=str(account_id))
                self._counts.count("silence")
                self._health.ws_dropped(account_id)
                return None
            if isinstance(item, PrivateStreamStatus):
                verdict = await self._status(account_id, session, item)
                if verdict == "rotate":  # closed first, then the new key's stream
                    return await self._resolve(account_id)
                if verdict == "end":
                    return None
            else:
                await self._row(account_id, session, item)
                self._paged.discard(account_id)  # only a handled row re-arms the page (L-2)

    async def _close(self, account_id: AccountId, stream: PrivateStream) -> None:
        try:
            async with asyncio.timeout(PORT_TIMEOUT_S):
                await stream.aclose()
        except TimeoutError:  # the task ends anyway: the next refresh restarts it
            _log().error("stream_close_timeout", account_id=str(account_id))
            self._counts.count("close_timeout")

    async def _row(self, account_id: AccountId, session: _Session, event: PrivateEvent) -> None:
        if session.down is None:  # evidence on dequeue, before the row's work
            self._health.ws_heartbeat(account_id)
        r, p = route(event), event.payload
        if isinstance(r, ForPairing):
            await self._pushes.handle(account_id, event, r)
        elif isinstance(r, ForProtection) and isinstance(p, Position):
            await self._bounded(self._positions.take(account_id, p, r), POSITION_TAKE_TIMEOUT_S)
        elif isinstance(r, NoB1Event) and r.reason == "wallet" and isinstance(p, Wallet):
            self._wallet(account_id, p)

    async def _status(
        self, account_id: AccountId, session: _Session, status: PrivateStreamStatus
    ) -> Verdict:
        if session.down is not None and status.epoch > session.down:
            session.down = None  # a later socket: its evidence counts again
        match status.state:
            case "heartbeat":
                if session.down is None:
                    self._health.ws_heartbeat(account_id)
            case "resyncing":
                await self._resync(account_id, cast(ResyncReason, status.reason))
            case "down":
                session.down = status.epoch
                self._health.ws_dropped(account_id)
                self._notices.publish(account_id, reason="oms.account_resyncing")
            case "closed":  # the session ends here: nothing after it is read
                self._health.ws_dropped(account_id)
                if status.reason in ("auth_refused", "key_unusable"):
                    await self._bounded(
                        self._credentials.refused(
                            account_id, error_code="AUTH_ERROR", exchange_ret_code=None
                        )
                    )
                return "rotate" if status.reason == "key_rotated" else "end"
        return "go"

    async def _resync(self, account_id: AccountId, reason: ResyncReason) -> None:
        try:
            await self._bounded(self._recon.request_reconciliation(account_id, reason=reason))
        except (ReconciliationUnavailable, TimeoutError) as exc:  # until E29-T06
            _log().warning(
                "stream_resync_refused", account_id=str(account_id), kind=type(exc).__name__
            )
            self._counts.count("reconciliation_unavailable")
            if account_id not in self._unavailable:  # one page per episode
                self._unavailable.add(account_id)
                self._page("an account's reconciliation request was refused")
        else:
            self._unavailable.discard(account_id)

    def _wallet(self, account_id: AccountId, w: Wallet) -> None:
        if w.updated_at > self._now_us() + MAX_FUTURE_SKEW_US:  # it would block every refresh
            _log().warning("stream_wallet_ahead", account_id=str(account_id))
            self._counts.count("wallet_ahead")
            return
        if w.coin != "USDT":
            self._counts.count("wallet_skipped")
            return
        stamp = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=w.updated_at)
        try:
            snapshot = WalletSnapshot(
                coin="USDT", equity=w.equity, wallet_balance=w.wallet_balance,
                available_balance=w.available_margin, unrealised_pnl=w.unrealised_pnl,
                account_im_rate=w.account_im_rate, account_mm_rate=w.account_mm_rate,
                updated_at=stamp,
            )  # fmt: skip
        except ValidationError as exc:  # its type only: balances are Confidential (C-12.6)
            _log().warning(
                "stream_wallet_invalid", account_id=str(account_id), kind=type(exc).__name__
            )
            self._counts.count("wallet_invalid")
            return
        self._health.wallet_pushed(account_id, snapshot)  # a notify hop answers nothing: ignored

    async def _bounded[T](self, call: Awaitable[T], seconds: float | None = None) -> T:
        async with asyncio.timeout(PORT_TIMEOUT_S if seconds is None else seconds):
            return await call

    def _page(self, summary: str) -> None:
        self._pager.raise_alert("page", summary, machine_kind="oms.stream_consumer")
