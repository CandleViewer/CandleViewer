"""The private-stream consumer (E29-T05 #848, S4c; 24-internal-schemas.md Sec.8.12). Plain code
on the hot-path contract (C-2.20). One task per streamed account in a `TaskGroup` (C-2.18), each
taking its stream's rows and statuses inline in arrival order, so the adapter's bounded buffer is
the only backpressure: a row's lag is observed on its dequeue, by its kind, from its ingest on the
host's clock (S8b), then it is fed to account health as evidence, then the account's due pending
terms are flushed (S7a), then its work is done (a pairing push, a position, a wallet), and each
status has its Sec.8.12 effect, a `heartbeat` flushing those terms too. After each item the
account's task reads the exchange clock's epoch: one that moved since its last item re-applies the
account's held position rows there, bounded, never beside one of its takes (S8b, Q7). Every await
is bounded, the stream is closed on every exit, and a cancel is never swallowed. Loop-agnostic: it
never hops, and treats `StreamEvidence` (account health's feed), `AccountNotices`, the lag and the
epoch as synchronous and non-blocking. Ids only in logs and no figure of a wallet in any (C-12.6).
The composition root (`oms_stream_wiring`) binds it, a live build refusing `NoReconciliation` and
`NoPositionRows`; the OMS runtime starts it once `ready` and stops it first (20 Sec.6.2), and a
start after a stop starts nothing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, Protocol, cast

import structlog
from pydantic import ValidationError

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
from candleviewer.settings import Environment as ProcessEnvironment
from candleviewer.storage.repositories.positions import MAX_FUTURE_SKEW

from .errors import OrderRefused, ProtectionReadingsUnavailable, ReconciliationUnavailable
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
#: S8b: the bound on a re-sync's re-apply of an account's held rows, above the projection's own
#: one deadline across them (`positions.REAPPLY_BOUND_S`, 4 s); a test pins the order.
REAPPLY_TIMEOUT_S: Final = PORT_TIMEOUT_S
#: 24 Sec.14.2 rule 10: the store's `MAX_FUTURE_SKEW`, in us, derived and never copied (one owner)
MAX_FUTURE_SKEW_US: Final = MAX_FUTURE_SKEW // timedelta(microseconds=1)

type Outcome = Literal[
    "refresh_failed", "defect", "silence", "resolve_refused", "reconciliation_unavailable",
    "wallet_ahead", "wallet_skipped", "wallet_invalid", "stop_timeout", "close_timeout",
    "reapply_timeout",
]  # fmt: skip
type Verdict = Literal["go", "end", "rotate"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ConsumerCounts(Protocol):
    def count(self, outcome: Outcome) -> None: ...  # sync; `oms_stream_wiring.StageCounts`


class StreamLags(Protocol):
    """A row's lag, in seconds, by its kind (24 Sec.8.12 `oms_stream_event_lag_seconds`): sync and
    non-blocking; S8b binds the catalogue histogram."""

    def lag(self, topic: str, seconds: float) -> None: ...


class ClockEpochs(Protocol):
    """How often the exchange clock has come back into sync (S8b, Q7): read in place on each item,
    sync, non-blocking and never raising."""

    def epoch(self) -> int: ...


class StreamEvidence(Protocol):
    """The three calls of account health's `AccountHealthFeed` the consumer makes (24 Sec.8.12):
    synchronous and non-blocking; what each answers is never read."""

    def ws_heartbeat(self, account_id: AccountId) -> object: ...
    def ws_dropped(self, account_id: AccountId) -> object: ...
    def wallet_pushed(self, account_id: AccountId, snapshot: WalletSnapshot) -> object: ...


class PrivateStreams(Protocol):
    """The account's stream on its environment's port, built on the loop that consumes it."""

    async def subscribe(self, account: AccountRef) -> PrivateStream: ...


class RowPushes(Protocol):  # `StreamPushes`
    async def handle(self, account_id: AccountId, event: PrivateEvent, r: ForPairing) -> None: ...
    async def flush(self, account_id: AccountId) -> None: ...  # its recorded stops' due terms


class PositionRows(Protocol):
    """S5's seam: the position projection and the protection readings (24 Sec.8.12), and the
    re-apply of the account's rows held as dated ahead of the store's clock (S8b)."""

    async def take(
        self, account_id: AccountId, position: Position, route: ForProtection
    ) -> None: ...

    async def reapply(self, account_id: AccountId) -> None: ...


class NoPositionRows:
    """`PositionRows` until S5: nothing is projected and no reading is taken; the composition
    root never binds it."""

    async def take(self, account_id: AccountId, position: Position, route: ForProtection) -> None:
        _log().debug("stream_position_pending", account_id=str(account_id))

    async def reapply(self, account_id: AccountId) -> None:
        return None  # it holds no row


def refuse_live_without_position_rows(
    environment: ProcessEnvironment, positions: PositionRows
) -> None:
    """The live start-up self-check of the position seam (S5b carry I-4), beside
    `ports.refuse_live_without_reconciliation`, run on the binding as bound: a live process with
    `NoPositionRows` would project no position and hand on no protection reading (C-2.6), so it is
    `ProtectionReadingsUnavailable`. The environment compares by value."""
    if environment == ProcessEnvironment.LIVE and isinstance(positions, NoPositionRows):
        raise ProtectionReadingsUnavailable("a live process needs the position projection")


@dataclass(slots=True)
class _Session:
    ref: AccountRef
    down: int | None = None  # the epoch a `down` status ended: its stragglers are no evidence


class StreamConsumer:
    """`now_us` is the exchange-synced clock (the wallet's check), `host_us` the host's own, on
    which the adapter stamps `ts_ingest` (the lag's)."""

    def __init__(
        self, *, accounts: StreamedAccounts, trading: TradingAccounts, streams: PrivateStreams,
        health: StreamEvidence, reconciliation: ReconciliationRequests,
        notices: AccountNotices, credentials: CredentialRejections, positions: PositionRows,
        pushes: RowPushes, counts: ConsumerCounts, pager: Pager, now_us: Callable[[], int],
        lags: StreamLags, host_us: Callable[[], int], epochs: ClockEpochs,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        refresh_s: float = REFRESH_S, silence_s: float = STREAM_SILENCE_S,
    ) -> None:  # fmt: skip
        self._accounts, self._trading, self._streams = accounts, trading, streams
        self._health, self._recon, self._notices = health, reconciliation, notices
        self._credentials, self._positions, self._pushes = credentials, positions, pushes
        self._counts, self._pager, self._now_us, self._sleep = counts, pager, now_us, sleep
        self._lags, self._host_us, self._epochs = lags, host_us, epochs
        self._refresh_s, self._silence_s = refresh_s, silence_s
        self._task: asyncio.Task[None] | None = None
        self._tasks: dict[AccountId, asyncio.Task[None]] = {}
        self._failures, self._stopped = 0, False
        self._paged: set[AccountId] = set()  # accounts whose defect or refused resync paged
        self._unavailable: set[AccountId] = set()
        self._resynced: dict[AccountId, int] = {}  # the clock's epoch each account last read
        #: an account its disable closed, and health's tracking read in place then (`_hold`)
        self._disabled: dict[AccountId, frozenset[AccountId]] = {}

    def start(self) -> bool:
        """Start consuming; True when this call started it. Once, and never after `stop()`: a stop
        that overtook the start leaves no consumer running into the facade's stop (S8b)."""
        if self._task is not None or self._stopped:
            return False
        self._task = spawn(self._run(), name="oms-stream-consumer")
        return True

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
        """Why the consumer is not doing its job, None while it is (`/readyz` reads it through
        `oms_stream_wiring.StreamReadiness`)."""
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
            self._resynced.pop(gone, None)
            self._disabled.pop(gone, None)
        for account_id in wanted:  # a task that ended restarts here: the only backoff
            task = self._tasks.get(account_id)
            if task is None or task.done():
                if self._disabled.get(account_id) is wanted:  # held while that read stays
                    continue
                self._disabled.pop(account_id, None)
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
            await self._clock_resynced(account_id)

    async def _close(self, account_id: AccountId, stream: PrivateStream) -> None:
        try:
            async with asyncio.timeout(PORT_TIMEOUT_S):
                await stream.aclose()
        except TimeoutError:  # the task ends anyway: the next refresh restarts it
            _log().error("stream_close_timeout", account_id=str(account_id))
            self._counts.count("close_timeout")

    async def _row(self, account_id: AccountId, session: _Session, event: PrivateEvent) -> None:
        # its lag on dequeue (S8b): the host's clock stamped `ts_ingest`, never the venue's time
        self._lags.lag(event.kind, (self._host_us() - event.ts_ingest) / 1_000_000)
        if session.down is None:  # evidence on dequeue, before the row's work
            self._health.ws_heartbeat(account_id)
        await self._pushes.flush(account_id)  # 24 Sec.8.12: at the account's next row
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
                await self._pushes.flush(account_id)  # 24 Sec.8.12: or at its `heartbeat`
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
                elif status.reason == "account_disabled":
                    await self._hold(account_id)
                return "rotate" if status.reason == "key_rotated" else "end"
        return "go"

    async def _hold(self, account_id: AccountId) -> None:
        """24 Sec.8.12: the account's disable closed its stream, and its key refuses a subscribe
        until the re-enable lifts it, while health's tracking read in place may still list it. So
        the refresh does not restart it while that read stays in place (a subscribe it would
        refuse is a defect and pages): health's next read, which lists it again only once it is
        re-enabled, equal to the last or not, decides. The read is taken here, never the last
        refresh's, which health may have replaced since; one that fails is this account's defect.
        Keyed on this status alone, never on a refused subscribe, which still pages."""
        self._disabled[account_id] = await self._bounded(self._accounts.streamed_accounts())

    async def _clock_resynced(self, account_id: AccountId) -> None:
        """S8b (24 Sec.8.12 "Protection readings", the orchestrator's Q7): the exchange clock came
        back into sync since the account's last item, so the rows the store refused as dated ahead
        of its clock are applied again, here in the account's own task, never beside one of its
        takes, once a move; past `REAPPLY_TIMEOUT_S` the reapply is cut and counted, its rows held
        for the account's next take, and the stream goes on."""
        epoch = self._epochs.epoch()
        if epoch == self._resynced.get(account_id, 0):
            return
        self._resynced[account_id] = epoch  # a cut reapply waits for the next move, never loops
        try:
            await self._bounded(self._positions.reapply(account_id), REAPPLY_TIMEOUT_S)
        except TimeoutError:
            _log().warning("stream_reapply_timeout", account_id=str(account_id))
            self._counts.count("reapply_timeout")

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
