"""The private-stream consumer (E29-T05 #848, S4c; 24-internal-schemas.md Sec.8.12): its
lifecycle, every status, the epoch rule, the wallet path, the position seam, the lag on dequeue and
the clock's re-sync (S8b), and the WS-is-the-truth case on the real facade. A fake stream port,
recording doubles and a ticked refresh: no sleeps, no network."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts.wallet import WalletSnapshot
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.exchange.base.models import (
    AccountRef,
    Position,
    PrivateEvent,
    PrivateStreamStatus,
    Wallet,
)
from candleviewer.exchange.base.ports import PrivateStream
from candleviewer.oms import positions, stream_consumer, stream_push
from candleviewer.oms.errors import OrderRefused, ReconciliationUnavailable
from candleviewer.oms.push_mapping import ForProtection
from candleviewer.oms.stream_consumer import STREAM_SILENCE_S, NoPositionRows, StreamConsumer
from tests.unit.exchange.bybit._trading import ACCOUNT_A, ACCOUNT_B, NOW_US, account
from tests.unit.oms.order_rig import ACCOUNT, build_rig, gated, order_of, placed
from tests.unit.oms.stream_rig import Rig as PushRig
from tests.unit.oms.test_stream_push import event

A, B = ACCOUNT_A, ACCOUNT_B
SENTINEL = "sentinel-1f3a9c"  # a message that must never reach a log or a page


def status(state: str, reason: str, epoch: int = 1, who: AccountId = A) -> PrivateStreamStatus:
    return PrivateStreamStatus.model_validate(
        {"account_id": who, "state": state, "reason": reason, "epoch": epoch, "ts": NOW_US}
    )


def wallet_event(who: AccountId = A, **over: Any) -> PrivateEvent:
    zero = Decimal(0)
    values: dict[str, Any] = {"account_id": who, "coin": "USDT", "equity": Decimal("1000.5")}
    values |= {"wallet_balance": Decimal("900"), "available_to_withdraw": None}
    values |= {"available_margin": Decimal("800.25"), "used_margin": zero, "updated_at": NOW_US}
    values |= {"unrealised_pnl": Decimal("-3.5"), "cum_realised_pnl": zero}
    values |= {"account_im_rate": Decimal("0.01"), "account_mm_rate": Decimal("0.005")}
    payload = Wallet(**(values | over))
    return PrivateEvent(
        kind="wallet", account_id=who, payload=payload, ts_event=NOW_US, ts_ingest=NOW_US
    )


def position_event(who: AccountId = A) -> PrivateEvent:
    payload = Position(
        account_id=who, symbol="BTCUSDT", position_idx=0, side=None, qty=Decimal(0),
        avg_entry_price=None, mark_price=None, liq_price=None, leverage=Decimal(10),
        unrealised_pnl=Decimal(0), cum_realised_pnl=Decimal(0), take_profit=None, stop_loss=None,
        trailing_stop_distance=None, updated_at=NOW_US,
    )  # fmt: skip
    return PrivateEvent(
        kind="position", account_id=who, payload=payload, ts_event=NOW_US, ts_ingest=NOW_US
    )


class Spy:
    """A stream that notes its `aclose`."""

    def __init__(
        self, inner: PrivateStream, closes: list[UUID], who: UUID, hang_close: bool = False
    ) -> None:
        self._inner, self._closes, self._who, self._hang_close = inner, closes, who, hang_close

    def __aiter__(self) -> Spy:
        return self

    async def __anext__(self) -> PrivateEvent | PrivateStreamStatus:
        return await self._inner.__anext__()

    async def aclose(self) -> None:
        self._closes.append(self._who)
        if self._hang_close:
            await asyncio.Event().wait()
        await self._inner.aclose()


@dataclass
class Rig:
    """Every collaborator of the consumer, recording into one ordered `log`."""

    streamed: set[UUID] = field(default_factory=lambda: {A})
    unresolvable: set[UUID] = field(default_factory=set)  # accounts whose resolve is refused
    read_fails: bool = False
    handle_error: dict[UUID, Exception] = field(default_factory=dict)
    hang: set[str] = field(default_factory=set)  # a port call that never answers, by name
    resync_error: Exception | None = None
    log: list[Any] = field(default_factory=list)
    closes: list[UUID] = field(default_factory=list)
    counts: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    started: asyncio.Event = field(default_factory=asyncio.Event)
    take_gate: asyncio.Event | None = None  # a take that answers once the test opens it
    cancelled: list[str] = field(default_factory=list)
    flushed: list[tuple[UUID, int]] = field(default_factory=list)  # (account, len(log) then)
    ticks: asyncio.Queue[None] = field(default_factory=asyncio.Queue)
    port: FakeTradingPort = field(default_factory=FakeTradingPort)
    now: int = NOW_US  # the exchange-synced clock (the wallet's check)
    host: int = NOW_US  # the host's own clock (the lag's)
    made: list[StreamConsumer] = field(default_factory=list)
    lagged: list[tuple[str, float]] = field(default_factory=list)
    resyncs: int = 0  # the clock's epoch: how often it has come back into sync
    reapply_gate: asyncio.Event | None = None  # a reapply that answers once the test opens it
    reapplied_in: list[asyncio.Task[Any] | None] = field(default_factory=list)

    def consumer(self, **kw: Any) -> StreamConsumer:
        ports = dict.fromkeys(("accounts", "trading", "streams", "health", "reconciliation"), self)
        ports |= dict.fromkeys(("notices", "credentials", "positions", "pushes", "counts"), self)
        ports |= dict.fromkeys(("pager", "lags", "epochs"), self)
        clocks = {"now_us": lambda: self.now, "host_us": lambda: self.host}
        return StreamConsumer(**(ports | clocks | {"sleep": self._tick} | kw))

    async def _tick(self, _seconds: float) -> None:
        await self.ticks.get()

    async def until(self, ready: Callable[[], bool]) -> None:
        """Yield to the loop until `ready`: a bound on the yields, never a wall-clock wait."""
        async with asyncio.timeout(5):
            while not ready():  # noqa: ASYNC110 - polls the consumer's own tasks, bounded above
                await asyncio.sleep(0)

    async def refresh(self) -> None:
        self.ticks.put_nowait(None)
        for _ in range(50):
            await asyncio.sleep(0)

    async def _stall(self, name: str) -> None:
        if name in self.hang:
            await asyncio.Event().wait()

    async def streamed_accounts(self) -> frozenset[UUID]:
        await self._stall("streamed")
        if self.read_fails:
            raise ConnectionError("the read failed")
        return frozenset(self.streamed)

    async def trading_account(self, account_id: AccountId) -> AccountRef:
        self.log.append(("resolve", account_id))
        await self._stall("resolve")
        if account_id in self.unresolvable:
            raise OrderRefused("no active key")
        return account(account_id)

    async def subscribe(self, ref: AccountRef) -> PrivateStream:
        self.log.append(("subscribe", ref.account_id))
        await self._stall("subscribe")
        inner = await self.port.subscribe_private(ref)
        return Spy(inner, self.closes, ref.account_id, "aclose" in self.hang)

    def ws_heartbeat(self, account_id: UUID) -> None:
        self.log.append(("hb", account_id))

    def ws_dropped(self, account_id: UUID) -> None:
        self.log.append(("drop", account_id))

    def wallet_pushed(self, account_id: UUID, snapshot: WalletSnapshot) -> bool:
        self.log.append(("wallet", snapshot))
        return False

    async def request_reconciliation(self, account_id: UUID, *, reason: str) -> None:
        self.log.append(("resync", reason))
        await self._stall("resync")
        if self.resync_error is not None:
            raise self.resync_error

    def publish(self, account_id: UUID, *, reason: str) -> None:
        self.log.append(("notice", reason))

    async def refused(
        self, account_id: UUID, *, error_code: str, exchange_ret_code: int | None
    ) -> None:
        self.log.append(("refused", error_code, exchange_ret_code))
        await self._stall("refused")

    async def take(self, account_id: UUID, position: Position, route: Any) -> None:
        self.log.append(("position", account_id))
        await self._stall("take")
        if self.take_gate is not None:
            await self.take_gate.wait()

    async def reapply(self, account_id: UUID) -> None:
        self.log.append(("reapply", account_id))
        self.reapplied_in.append(asyncio.current_task())
        await self._stall("reapply")
        if self.reapply_gate is not None:
            await self.reapply_gate.wait()

    def lag(self, topic: str, seconds: float) -> None:
        self.lagged.append((topic, seconds))

    def epoch(self) -> int:
        return self.resyncs

    async def handle(self, account_id: UUID, ev: PrivateEvent, r: Any) -> None:
        self.log.append(("handle", account_id))
        if account_id in self.handle_error:
            raise self.handle_error[account_id]
        if "handle" in self.hang:
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.append("handle")
                raise

    async def flush(self, account_id: UUID) -> None:
        self.flushed.append((account_id, len(self.log)))

    def count(self, outcome: str) -> None:
        self.counts.append(outcome)

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        self.pages.append(summary)


@pytest.fixture
async def rig() -> Any:
    r = Rig()
    yield r
    for c in r.made:
        await c.stop()


async def running(r: Rig, **kw: Any) -> StreamConsumer:
    c = r.consumer(**kw)
    r.made.append(c)
    c.start()
    await r.until(lambda: bool(entries(r, "subscribe")) or bool(r.counts))
    return c


def entries(r: Rig, kind: str) -> list[Any]:
    return [e for e in r.log if e[0] == kind]


async def test_consumer_one_accounts_defect_leaves_its_sibling_consuming(rig: Rig) -> None:
    rig.streamed, rig.handle_error = {A, B}, {A: RuntimeError(SENTINEL)}
    with capture_logs() as logs:
        c = await running(rig)
        await rig.until(lambda: ("subscribe", B) in rig.log)
        rig.port.push(event("order", orderStatus="Cancelled"))
        await rig.until(lambda: "defect" in rig.counts)
    rig.port.push(wallet_event(B))
    await rig.until(lambda: bool(entries(rig, "wallet")))
    assert c.accounts() == {B} and c.fault is None and len(rig.pages) == 1
    assert SENTINEL not in repr(logs) + repr(rig.pages)  # its type is named, never its message


async def test_consumer_refresh_adds_removes_and_restarts_accounts(rig: Rig) -> None:
    c = await running(rig)
    rig.streamed = {A, B}
    await rig.refresh()
    assert c.accounts() == {A, B}
    rig.streamed = {B}
    await rig.refresh()
    assert c.accounts() == {B} and rig.closes == [A]  # the removed account's stream is closed
    rig.port.push(status("closed", "shutdown", who=B))
    await rig.until(lambda: B in rig.closes)
    assert c.accounts() == set()
    await rig.refresh()  # its account is still streamed: restarted, the only backoff
    assert c.accounts() == {B} and entries(rig, "subscribe").count(("subscribe", B)) == 2


async def test_consumer_failed_refresh_keeps_the_set_and_reports_a_fault_after_four(
    rig: Rig,
) -> None:
    c = await running(rig)
    rig.read_fails = True
    for _ in range(3):
        await rig.refresh()
    assert c.accounts() == {A} and c.fault is None
    await rig.refresh()
    assert c.fault == "streamed accounts unreadable" and rig.counts.count("refresh_failed") == 4
    rig.read_fails = False
    await rig.refresh()
    assert c.fault is None


async def test_consumer_row_evidence_is_fed_before_the_rows_work(rig: Rig) -> None:
    rig.hang.add("handle")
    await running(rig)
    rig.port.push(event("order", orderStatus="Cancelled"))
    await asyncio.wait_for(rig.started.wait(), 5)
    assert rig.log[-2:] == [("hb", A), ("handle", A)]


async def test_consumer_rows_are_handled_in_arrival_order(rig: Rig) -> None:
    await running(rig)
    for item in (position_event(), event("order", orderStatus="Cancelled"), wallet_event()):
        rig.port.push(item)
    await rig.until(lambda: bool(entries(rig, "wallet")))
    kinds = [e[0] for e in rig.log if e[0] in ("position", "handle", "wallet")]
    assert kinds == ["position", "handle", "wallet"]  # a fired stop's position comes first, no hold


async def test_consumer_no_evidence_after_down_until_a_later_epoch(rig: Rig) -> None:
    await running(rig)
    for item in (status("down", "socket_closed", 1), status("heartbeat", "evidence", 1)):
        rig.port.push(item)
    rig.port.push(wallet_event())  # a straggler of the dead socket
    rig.port.push(status("resyncing", "reconnected", 2))
    rig.port.push(wallet_event())
    await rig.until(lambda: len(entries(rig, "wallet")) == 2)
    assert [e[0] for e in rig.log if e[0] in ("hb", "drop", "notice")] == ["drop", "notice", "hb"]


@pytest.mark.parametrize("reason", ["connected", "reconnected", "rejected_frame"])
async def test_consumer_resyncing_requests_reconciliation_with_its_reason(
    rig: Rig, reason: str
) -> None:
    await running(rig)
    rig.port.push(status("resyncing", reason))
    await rig.until(lambda: bool(entries(rig, "resync")))
    assert entries(rig, "resync") == [("resync", reason)]


async def test_consumer_unavailable_reconciliation_pages_once_per_episode(rig: Rig) -> None:
    rig.resync_error = ReconciliationUnavailable("no pass")
    await running(rig)
    for _ in range(2):
        rig.port.push(status("resyncing", "connected"))
    await rig.until(lambda: len(entries(rig, "resync")) == 2)
    assert len(rig.pages) == 1 and rig.counts == ["reconciliation_unavailable"] * 2
    rig.resync_error = None
    rig.port.push(status("resyncing", "connected"))
    await rig.until(lambda: len(entries(rig, "resync")) == 3)
    rig.resync_error = ReconciliationUnavailable("no pass")
    rig.port.push(status("resyncing", "connected"))
    await rig.until(lambda: len(rig.pages) == 2)  # a new episode pages again


async def test_consumer_heartbeat_status_feeds_health(rig: Rig) -> None:
    await running(rig)
    rig.port.push(status("heartbeat", "evidence"))
    await rig.until(lambda: bool(entries(rig, "hb")))
    assert entries(rig, "hb") == [("hb", A)] and not entries(rig, "drop")


async def test_consumer_flushes_the_accounts_due_terms_at_each_row_before_its_work(
    rig: Rig,
) -> None:
    """24 Sec.8.12 (S7a): a recorded stop's pending terms are sent at the account's next row,
    after the row's evidence and before its work, whatever the row is."""
    await running(rig)
    for item in (event("order", orderStatus="Cancelled"), wallet_event()):
        rig.port.push(item)
    await rig.until(lambda: bool(entries(rig, "wallet")))
    handled, wallet = rig.log.index(("handle", A)), rig.log.index(entries(rig, "wallet")[0])
    assert [who for who, _ in rig.flushed] == [A, A]
    assert [at for _, at in rig.flushed] == [handled, wallet]  # each row's work came right after
    assert rig.log[handled - 1] == ("hb", A)


@pytest.mark.parametrize("down", [False, True], ids=["live", "after_down"])
async def test_consumer_flushes_the_accounts_due_terms_at_each_heartbeat(
    rig: Rig, down: bool
) -> None:
    """24 Sec.8.12 (S7a): or at the account's `heartbeat` status, even one no evidence follows."""
    await running(rig)
    if down:
        rig.port.push(status("down", "pong_timeout", 1))
    rig.port.push(status("heartbeat", "evidence", 1))
    await rig.until(lambda: bool(rig.flushed))
    assert [who for who, _ in rig.flushed] == [A]
    assert bool(entries(rig, "hb")) is not down


async def test_consumer_down_status_drops_the_account_and_publishes_the_notice(rig: Rig) -> None:
    await running(rig)
    rig.port.push(status("down", "pong_timeout", 1))
    await rig.until(lambda: bool(entries(rig, "notice")))
    assert [e[0] for e in rig.log[-2:]] == ["drop", "notice"]
    assert entries(rig, "notice") == [("notice", "oms.account_resyncing")]


@pytest.mark.parametrize("reason", ["auth_refused", "key_unusable"])
async def test_consumer_closed_on_a_key_fault_reports_the_credential_without_a_code(
    rig: Rig, reason: str
) -> None:
    c = await running(rig)
    rig.port.push(status("closed", reason))
    await rig.until(lambda: rig.closes == [A])
    assert entries(rig, "refused") == [("refused", "AUTH_ERROR", None)]
    assert ("drop", A) in rig.log and c.accounts() == set()


@pytest.mark.parametrize("reason", ["key_revoked", "shutdown"])
async def test_consumer_closed_on_a_revoke_or_shutdown_reports_nothing(
    rig: Rig, reason: str
) -> None:
    await running(rig)
    rig.port.push(status("closed", reason))
    await rig.until(lambda: rig.closes == [A])
    assert entries(rig, "refused") == [] and ("drop", A) in rig.log


async def test_consumer_key_rotated_resolves_and_subscribes_again(rig: Rig) -> None:
    await running(rig)
    rig.port.push(status("closed", "key_rotated"))
    await rig.until(lambda: entries(rig, "subscribe").count(("subscribe", A)) == 2)
    assert rig.closes == [A] and entries(rig, "resolve") == [("resolve", A)] * 2
    rig.port.push(wallet_event())  # the new key's stream is consumed
    await rig.until(lambda: bool(entries(rig, "wallet")))


async def test_consumer_key_rotated_with_a_refused_resolve_ends_and_the_next_refresh_retries(
    rig: Rig,
) -> None:
    c = await running(rig)
    rig.unresolvable.add(A)
    rig.port.push(status("closed", "key_rotated"))
    await rig.until(lambda: not c.accounts())
    assert entries(rig, "subscribe") == [("subscribe", A)]
    rig.unresolvable.clear()
    await rig.refresh()
    assert c.accounts() == {A} and len(entries(rig, "subscribe")) == 2


async def test_consumer_silence_past_the_bound_drops_closes_and_ends(rig: Rig) -> None:
    assert STREAM_SILENCE_S == 30.0
    c = await running(rig, silence_s=0.0)
    await rig.until(lambda: rig.closes == [A])
    assert ("drop", A) in rig.log and "silence" in rig.counts and not c.accounts()


async def test_consumer_stop_cancels_pushes_closes_streams_and_returns_in_bound(rig: Rig) -> None:
    rig.streamed, rig.hang = {A, B}, {"handle"}
    c = await running(rig)
    await rig.until(lambda: ("subscribe", B) in rig.log)
    rig.port.push(event("order", orderStatus="Cancelled"))
    await asyncio.wait_for(rig.started.wait(), 5)
    tasks = list(c._tasks.values())
    await asyncio.wait_for(c.stop(timeout_s=1.0), 5)
    assert all(t.cancelled() for t in tasks)  # a cancel is never swallowed
    assert rig.cancelled == ["handle"] and sorted(rig.closes) == sorted([A, B])
    assert c._task is not None and c._task.done() and c.fault is None


async def test_consumer_a_dead_task_is_a_fault(rig: Rig) -> None:
    c = await running(rig)
    assert c._task is not None
    c._task.cancel()  # not through stop(): the consumer ended unexpectedly
    await rig.until(lambda: c._task is not None and c._task.done())
    assert c.fault == "the consumer task ended"


async def test_consumer_wallet_maps_each_field_to_the_health_snapshot(rig: Rig) -> None:
    await running(rig)
    rig.port.push(wallet_event())
    await rig.until(lambda: bool(entries(rig, "wallet")))
    [(_, snap)] = entries(rig, "wallet")
    assert (snap.coin, snap.equity, snap.wallet_balance) == (
        "USDT",
        Decimal("1000.5"),
        Decimal(900),
    )
    assert (snap.available_balance, snap.unrealised_pnl) == (Decimal("800.25"), Decimal("-3.5"))
    assert (snap.account_im_rate, snap.account_mm_rate) == (Decimal("0.01"), Decimal("0.005"))
    assert snap.updated_at.timestamp() * 1_000_000 == NOW_US


async def test_consumer_wallet_dated_past_the_skew_is_refused_and_counted(rig: Rig) -> None:
    await running(rig)
    rig.port.push(wallet_event(updated_at=NOW_US + 5_000_001))
    await rig.until(lambda: bool(rig.counts))
    assert rig.counts == ["wallet_ahead"] and not entries(rig, "wallet")


async def test_consumer_wallet_dated_at_the_skew_is_accepted(rig: Rig) -> None:
    await running(rig)
    rig.port.push(wallet_event(updated_at=NOW_US + 5_000_000))
    await rig.until(lambda: bool(entries(rig, "wallet")))
    assert rig.counts == []


async def test_consumer_wallet_of_a_non_usdt_coin_is_skipped_and_counted(rig: Rig) -> None:
    await running(rig)
    rig.port.push(wallet_event(coin="BTC"))
    await rig.until(lambda: bool(rig.counts))
    assert rig.counts == ["wallet_skipped"] and not entries(rig, "wallet")


async def test_consumer_wallet_validation_error_logs_its_type_and_no_figure(rig: Rig) -> None:
    await running(rig)
    with capture_logs() as logs:
        rig.port.push(wallet_event(equity=Decimal("1.2345E+41")))  # past the amount's exponent
        await rig.until(lambda: bool(rig.counts))
    assert rig.counts == ["wallet_invalid"] and not entries(rig, "wallet")
    assert logs[-1]["kind"] == "ValidationError" and "2345" not in repr(logs)


@pytest.fixture
def tight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every port bound is zero: a call that never answers is cut at once (no wall-clock wait)."""
    monkeypatch.setattr(stream_consumer, "PORT_TIMEOUT_S", 0.0)


async def test_consumer_bounded_cuts_a_never_answering_call_by_its_own_bound(
    rig: Rig, tight: None
) -> None:
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(2) as guard:
            await rig.consumer()._bounded(asyncio.Event().wait())
    assert not guard.expired()  # the consumer's bound fired, not this guard


async def test_consumer_hung_refresh_read_is_cut_counted_and_the_next_refresh_goes_on(
    rig: Rig, tight: None
) -> None:
    rig.hang.add("streamed")
    c = await running(rig)
    assert rig.counts == ["refresh_failed"] and c.accounts() == set()
    rig.hang.clear()
    await rig.refresh()
    assert c.accounts() == {A} and c.fault is None


async def test_consumer_hung_resolve_is_a_refused_resolve_not_a_defect_and_retries(
    rig: Rig, tight: None
) -> None:
    rig.hang.add("resolve")
    c = await running(rig)
    assert rig.counts == ["resolve_refused"] and not rig.pages and c.accounts() == set()
    rig.hang.clear()
    await rig.refresh()
    assert c.accounts() == {A} and entries(rig, "subscribe") == [("subscribe", A)]


async def test_consumer_hung_subscribe_is_cut_and_ends_the_account_as_a_defect(
    rig: Rig, tight: None
) -> None:
    rig.hang.add("subscribe")
    c = await running(rig)
    await rig.until(lambda: "defect" in rig.counts)
    assert rig.counts == ["defect"] and len(rig.pages) == 1 and c.accounts() == set()


async def test_consumer_hung_position_take_is_cut_and_ends_the_account_closing_its_stream(
    rig: Rig, tight: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stream_consumer, "POSITION_TAKE_TIMEOUT_S", 0.0)
    rig.hang.add("take")
    c = await running(rig)
    rig.port.push(position_event())
    await rig.until(lambda: "defect" in rig.counts)
    assert rig.closes == [A] and len(rig.pages) == 1 and c.accounts() == set()


async def test_consumer_position_take_outlasts_the_port_bound_up_to_its_own(
    rig: Rig, tight: None
) -> None:
    """Q1: a protection reading crosses the facade's 30 s push, so `take` has its own, longer
    bound; the 5 s port bound (zero here) never cuts it."""
    assert stream_consumer.POSITION_TAKE_TIMEOUT_S > stream_push.PUSH_TIMEOUT_S
    rig.take_gate = asyncio.Event()
    c = await running(rig)
    rig.port.push(position_event())
    await rig.until(lambda: ("position", A) in rig.log)
    await rig.refresh()  # loop turns only: a port-bound cut would land here
    rig.take_gate.set()
    rig.port.push(wallet_event())
    await rig.until(lambda: bool(entries(rig, "wallet")))
    assert "defect" not in rig.counts and c.accounts() == {A}


async def test_consumer_cancel_during_a_hung_close_is_not_swallowed(rig: Rig) -> None:
    rig.hang.add("aclose")
    c = await running(rig, silence_s=0.0)
    await rig.until(lambda: rig.closes == [A])  # the close hangs under its real bound
    tasks = list(c._tasks.values())
    await asyncio.wait_for(c.stop(timeout_s=1.0), 5)
    assert tasks and all(t.cancelled() for t in tasks)


async def test_consumer_hung_reconciliation_request_counts_unavailable_and_goes_on(
    rig: Rig, tight: None
) -> None:
    rig.hang.add("resync")
    c = await running(rig)
    rig.port.push(status("resyncing", "connected"))
    await rig.until(lambda: bool(rig.counts))
    assert rig.counts == ["reconciliation_unavailable"] and len(rig.pages) == 1
    rig.port.push(wallet_event())  # the stream is still consumed
    await rig.until(lambda: bool(entries(rig, "wallet")))
    assert c.accounts() == {A}


async def test_consumer_reconciliation_timeout_error_is_unavailable_like_a_refusal(
    rig: Rig,
) -> None:
    rig.resync_error = TimeoutError()
    await running(rig)
    rig.port.push(status("resyncing", "connected"))
    await rig.until(lambda: bool(rig.counts))
    assert rig.counts == ["reconciliation_unavailable"] and len(rig.pages) == 1


async def test_consumer_hung_credential_report_is_cut_and_ends_the_account(
    rig: Rig, tight: None
) -> None:
    rig.hang.add("refused")
    c = await running(rig)
    rig.port.push(status("closed", "auth_refused"))
    await rig.until(lambda: "defect" in rig.counts)
    assert rig.closes == [A] and len(rig.pages) == 1 and c.accounts() == set()


async def test_consumer_hung_close_is_cut_counted_and_the_account_task_ends(
    rig: Rig, tight: None
) -> None:
    rig.hang.add("aclose")
    c = await running(rig, silence_s=0.0)
    await rig.until(lambda: "close_timeout" in rig.counts)
    await rig.until(lambda: not c.accounts())
    assert rig.counts == ["silence", "close_timeout"] and rig.closes == [A]


async def test_consumer_a_defect_pages_once_until_the_account_handles_another_row(
    rig: Rig,
) -> None:
    rig.handle_error = {A: RuntimeError("x")}
    await running(rig)
    rig.port.push(event("order", orderStatus="Cancelled"))
    await rig.until(lambda: rig.counts.count("defect") == 1)
    rig.handle_error.clear()
    await rig.refresh()  # the task restarts
    rig.port.push(wallet_event())
    await rig.until(lambda: bool(entries(rig, "wallet")))
    rig.handle_error[A] = RuntimeError("x")
    rig.port.push(event("order", orderStatus="Cancelled"))
    await rig.until(lambda: rig.counts.count("defect") == 2)
    assert len(rig.pages) == 2  # a handled row re-armed the page


def defects_reach(r: Rig, n: int) -> Callable[[], bool]:
    return lambda: r.counts.count("defect") == n


async def test_consumer_a_persistent_defect_pages_once_through_every_restart_and_status(
    rig: Rig,
) -> None:
    rig.handle_error = {A: RuntimeError("x")}
    await running(rig)
    for n in (1, 2, 3):
        rig.port.push(status("resyncing", "reconnected", n))  # a status never re-arms the page
        rig.port.push(event("order", orderStatus="Cancelled"))
        await rig.until(defects_reach(rig, n))
        await rig.refresh()
    assert len(rig.pages) == 1


async def test_consumer_an_account_leaving_the_set_forgets_its_page(rig: Rig) -> None:
    rig.handle_error = {A: RuntimeError("x")}
    c = await running(rig)
    rig.port.push(event("order", orderStatus="Cancelled"))
    await rig.until(lambda: rig.counts.count("defect") == 1)
    rig.streamed = set()
    await rig.refresh()
    rig.streamed = {A}
    await rig.refresh()
    rig.port.push(event("order", orderStatus="Cancelled"))
    await rig.until(lambda: rig.counts.count("defect") == 2)
    assert len(rig.pages) == 2 and c.fault is None


async def test_consumer_an_account_leaving_the_set_forgets_its_reconciliation_episode(
    rig: Rig,
) -> None:
    rig.resync_error = ReconciliationUnavailable("no pass")
    await running(rig)
    rig.port.push(status("resyncing", "connected"))
    await rig.until(lambda: len(rig.pages) == 1)
    rig.streamed = set()
    await rig.refresh()
    rig.streamed = {A}
    await rig.refresh()
    rig.port.push(status("resyncing", "connected"))
    await rig.until(lambda: len(rig.pages) == 2)


async def test_consumer_stand_in_position_rows_take_a_row_and_do_nothing() -> None:
    position = cast(Position, position_event().payload)  # the event builder types it as a union
    await NoPositionRows().take(A, position, cast(ForProtection, None))
    await NoPositionRows().reapply(A)  # it holds nothing to apply again


async def turns() -> None:
    """Loop turns only: work the consumer could start beside another would land here."""
    for _ in range(50):
        await asyncio.sleep(0)


async def test_consumer_start_after_a_stop_starts_nothing(rig: Rig) -> None:
    """S8b (20 Sec.6.2): a stop that overtook its start, the runtime's stop beside its start,
    leaves no consumer running into the facade's stop: `start` refuses once stopped, and answers
    whether it started the consumer, once."""
    stopped = rig.consumer()
    rig.made.append(stopped)
    await stopped.stop()
    assert stopped.start() is False and stopped._task is None and stopped.fault is None
    fresh = rig.consumer()
    rig.made.append(fresh)
    assert fresh.start() is True and fresh.start() is False


async def test_lag_is_observed_per_topic_from_ts_ingest(rig: Rig) -> None:
    """24 Sec.8.12 "Its metrics" (S8b): each row's lag, on its dequeue, by its kind, from its
    ingest on the host's own clock (`ts_ingest`): never the venue's time (`ts_event`), nor the
    exchange-synced clock, so the venue's skew never makes it negative; a status is no row."""
    rig.now, rig.host = NOW_US + 9_000_000, NOW_US + 250_000  # the exchange clock 9 s ahead
    await running(rig)
    early = wallet_event().model_copy(update={"ts_event": NOW_US - 7_000_000})
    for item in (status("heartbeat", "evidence"), early, position_event()):
        rig.port.push(item)
    await rig.until(lambda: ("position", A) in rig.log)
    assert rig.lagged == [("wallet", 0.25), ("position", 0.25)]


async def test_clock_resync_reapplies_held_rows_inside_the_accounts_task(rig: Rig) -> None:
    """24 Sec.8.12 "Protection readings" (S8b, the orchestrator's Q7): a row the store held as
    dated ahead of its clock is applied again once the clock is back in sync. Each item an
    account's task takes reads the clock's epoch, and one that moved since the account's last
    item re-applies the account's held rows, once a move, in that account's own task."""
    rig.streamed = {A, B}
    c = await running(rig)
    await rig.until(lambda: ("subscribe", B) in rig.log)
    rig.port.push(wallet_event())
    await rig.until(lambda: bool(entries(rig, "wallet")))
    assert entries(rig, "reapply") == []  # no move yet
    rig.resyncs = 1
    for item in (wallet_event(), wallet_event(), status("heartbeat", "evidence", who=B)):
        rig.port.push(item)
    await rig.until(lambda: len(entries(rig, "wallet")) == 3 and len(entries(rig, "hb")) == 4)
    assert sorted(entries(rig, "reapply")) == sorted([("reapply", A), ("reapply", B)])
    assert sorted(map(id, rig.reapplied_in)) == sorted(id(c._tasks[a]) for a in (A, B))


async def test_reapply_never_runs_beside_a_take_of_the_same_account(rig: Rig) -> None:
    """The account's reapply and its next position row's take are one after the other in its own
    task, never side by side: the projection's held rows are that task's alone."""
    rig.reapply_gate = asyncio.Event()
    await running(rig)
    rig.resyncs = 1
    rig.port.push(wallet_event())  # its epoch read starts the reapply, which waits
    rig.port.push(position_event())
    await rig.until(lambda: ("reapply", A) in rig.log)
    await turns()
    assert ("position", A) not in rig.log
    rig.reapply_gate.set()
    await rig.until(lambda: ("position", A) in rig.log)


async def test_a_reapply_cut_at_its_bound_is_counted_and_the_stream_goes_on(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reapply past its bound (`REAPPLY_TIMEOUT_S`, above the projection's own deadline) is cut
    and counted `reapply_timeout`, and the account's stream goes on: no defect and no page, its
    rows still held for its next take; a cut reapply is not tried again until the next move."""
    assert stream_consumer.REAPPLY_TIMEOUT_S > positions.REAPPLY_BOUND_S
    monkeypatch.setattr(stream_consumer, "REAPPLY_TIMEOUT_S", 0.0)
    rig.hang.add("reapply")
    c = await running(rig)
    rig.resyncs = 1
    rig.port.push(wallet_event())
    await rig.until(lambda: "reapply_timeout" in rig.counts)
    rig.port.push(wallet_event())
    await rig.until(lambda: len(entries(rig, "wallet")) == 2)
    assert rig.counts == ["reapply_timeout"] and not rig.pages and c.accounts() == {A}
    assert entries(rig, "reapply") == [("reapply", A)]


@pytest.fixture
async def facade() -> Any:
    out = build_rig()
    yield out
    await out.facade.stop()  # the facade holds B1's ports: one per process


class Settled:
    """The facade's order, submitting, with the stream's fill and end pushed (a `Rig` consumer)."""

    def __init__(self, rig: Rig, out: Any) -> None:
        self.rig, self.out = rig, out
        self.order = order_of()
        self.xid = f"x{self.order.id.int}"
        self.link = self.order.order_link_id
        self.consumer: StreamConsumer | None = None

    def seen(self, ev: PrivateEvent, **over: Any) -> PrivateEvent:
        who = {"account_id": ACCOUNT}
        update = who | {"exchange_order_id": self.xid, "order_link_id": self.link} | over
        return ev.model_copy(update=who | {"payload": ev.payload.model_copy(update=update)})

    def state(self) -> str:
        return (self.out.facade.state(self.order.id) or ("",))[0]

    @property
    def fill(self) -> PrivateEvent:
        return self.seen(
            event("execution", execType="Trade"),
            qty=Decimal(1), price=Decimal(63000), exec_id="e1", side="buy",
        )  # fmt: skip

    async def submitting(self) -> None:
        out, rig = self.out, self.rig
        outer = self

        class Reads:
            async def get_by_exchange_order_id(self, a: UUID, x: str) -> Any:
                return await out.orders.get_by_exchange_order_id(a, x)

            async def get_by_link_id(self, a: UUID, link: str) -> Any:
                return await out.orders.get_by_link_id(a, link)

            async def live_for_key(self, *a: Any) -> tuple[()]:
                return ()

        pushes = PushRig().streams(target=out.facade, reads=Reads())
        self.gate, out.commands.on_place = gated({"ok": True, "exchange_order_id": self.xid})
        await out.start(self.order)
        await out.facade.command(ACCOUNT, self.order.id, "SEND", actor="user")
        await out.quiet()
        assert outer.state() == "submitting"
        rig.streamed = {ACCOUNT}
        self.consumer = await running(rig, pushes=pushes)
        rig.port.push(self.fill)  # during `submitting`: deferred
        rig.port.push(self.seen(event("order", orderStatus="Filled")))
        await rig.refresh()

    async def acked(self) -> None:
        self.out.commands.on_place = placed
        self.gate.set()
        await self.out.quiet()
        await self.rig.refresh()


@pytest.fixture
async def settled(rig: Rig, facade: Any) -> Settled:
    s = Settled(rig, facade)
    await s.submitting()
    return s


async def test_consumer_a_fill_during_submitting_waits_for_the_ack(settled: Settled) -> None:
    assert settled.state() == "submitting"


async def test_consumer_the_acked_orders_stream_fill_and_end_finish_it(settled: Settled) -> None:
    await settled.acked()
    row = await settled.out.orders.get_by_link_id(ACCOUNT, settled.link)  # its machine is evicted
    assert row is not None and row.state == "filled" and row.exchange_order_id == settled.xid


async def test_consumer_a_repeated_exec_id_writes_one_fill_row(settled: Settled) -> None:
    await settled.acked()
    settled.rig.port.push(settled.fill)  # the same exec_id again
    await settled.rig.refresh()
    await settled.out.quiet()
    assert len(settled.out.store._fills) == 1
    assert settled.consumer is not None and settled.consumer.fault is None
