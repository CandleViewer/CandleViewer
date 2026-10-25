"""The venue cancel-all fold's port (E29-T04 #913 slice 4, S4-F; 24 Sec.8.7; the 21:11Z ruling):
`CancelAllCoalescer` around the in-memory venue (`FakeTradingPort`). Every call passes through as
it is but a fold member's `cancel_order`, which meets its fold: one venue `cancel-all` once every
member has arrived, else none, and each member its own cancel (the fail-safe). Nothing sleeps:
the gather's bound and the spacer's wait are injected and released by the test."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from prometheus_client import generate_latest
from prometheus_client.parser import text_string_to_metric_families
from structlog.testing import capture_logs

from candleviewer.domain.order_link import account_tag
from candleviewer.domain.primitives import AccountId, Symbol
from candleviewer.exchange.base.errors import OmsErrorCode, TransportError
from candleviewer.exchange.base.fakes import FakeReject, FakeTradingPort
from candleviewer.exchange.base.models import AccountRef, CancelOrderRequest, Order, OrderAck
from candleviewer.observability.logging import _redaction_processor
from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms.cancel_all import FOLD_MIN
from candleviewer.oms.cancel_all_coalescer import FOLD_OUTCOMES, CancelAllCoalescer, unfolded
from candleviewer.oms.cancel_all_fold import CancelAllSpacer, FoldRefused
from candleviewer.oms.routing import RoutedPort, TradingRouter
from candleviewer.storage.repositories.orders import OrderRow
from tests.unit.oms import command_rig as cr

_ACCOUNT = AccountId(UUID("5b1c9d2e-7f30-4a6b-8c4d-2e3f4a5b6c7d"))
_REF = AccountRef(account_id=_ACCOUNT, uid="100001", environment="demo", key_ref=str(UUID(int=1)))
_BTC = Symbol("BTCUSDT")
_NAMES = ("a", "b", "c", "d", "stop", "tp", "other")


@pytest.fixture(autouse=True)
async def _hang_guard() -> AsyncIterator[None]:
    """CR-S4F-17: a fold that never answers (a mutant's hang) fails its test within 5 s rather
    than hanging the run: every task of the test's loop still running then is cancelled."""
    loop = asyncio.get_running_loop()
    guard = loop.call_later(5.0, lambda: [task.cancel() for task in asyncio.all_tasks(loop)])
    yield
    guard.cancel()


def _id(name: str) -> str:
    """A link id the OMS's generator could have made (24 Sec.8.3), one per short name."""
    return f"cvd-0{_NAMES.index(name) + 1:021d}-{account_tag(_ACCOUNT)}-00en"


def _resting(name: str, kind: Any = "order", symbol: str = "BTCUSDT") -> Order:
    return Order(
        order_link_id=_id(name), exchange_order_id=f"x-{name}", account_id=_ACCOUNT, symbol=symbol,
        side="buy", order_type="limit", qty=Decimal("0.010"), price=Decimal("60000"), state="new",
        filled_qty=Decimal("0"), leaves_qty=Decimal("0.010"), avg_fill_price=None,
        created_at=1_790_000_000_000_000, terminal_at=None, order_kind=kind,
    )  # fmt: skip


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class _Sleeps:
    """Every injected wait: the gather's bound and the spacer's, each ended by the test."""

    def __init__(self) -> None:
        self.asked: list[float] = []
        self.passed = asyncio.Event()

    async def sleep(self, seconds: float) -> None:
        self.asked.append(seconds)
        await self.passed.wait()


def _venue(*links: str, kinds: dict[str, str] | None = None) -> FakeTradingPort:
    venue = FakeTradingPort()
    for link in links:
        venue.seed_order(_resting(link, (kinds or {}).get(link, "order")), uid=_REF.uid)
    return venue


def _port(venue: FakeTradingPort) -> tuple[CancelAllCoalescer, _Sleeps, _Clock]:
    clock, sleeps = _Clock(), _Sleeps()
    spacer = CancelAllSpacer(monotonic=clock, sleep=sleeps.sleep)
    port = CancelAllCoalescer(venue, spacer=spacer, monotonic=clock, sleep=sleeps.sleep)
    return port, sleeps, clock


def _ids(*names: str) -> list[str]:
    return [_id(name) for name in names]


def _cancel(name: str) -> CancelOrderRequest:
    return CancelOrderRequest(account=_REF, symbol=_BTC, order_link_id=_id(name))


def _methods(venue: FakeTradingPort) -> list[str]:
    return [call.method for call in venue.calls]


async def _settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


async def test_every_call_outside_a_fold_passes_through_as_it_is() -> None:
    venue = _venue("a", "b")
    port, _, _ = _port(venue)
    assert port.capabilities is venue.capabilities
    assert [o.order_link_id for o in await port.open_orders(_REF, _BTC)] == _ids("a", "b")
    assert (await port.cancel_order(_cancel("a"))).ok
    acks = await port.cancel_all(_REF, _BTC)
    assert [a.order_link_id for a in acks] == _ids("b")
    assert await port.positions(_REF) == []
    assert port.headroom(_REF, "critical") == venue.headroom(_REF, "critical")
    assert _methods(venue) == ["open_orders", "cancel_order", "cancel_all", "positions"]


_ANSWER, _A0, _A1, _A2, _A3, _A4 = (object() for _ in range(6))


class _Recorder:
    """An inner port that records each call as it is made and answers a sentinel of its own."""

    capabilities = object()

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def headroom(self, *args: object, **kwargs: object) -> object:
        self.calls.append(("headroom", args, kwargs))
        return _ANSWER

    def __getattr__(self, name: str) -> Callable[..., Awaitable[object]]:
        async def call(*args: object, **kwargs: object) -> object:
            self.calls.append((name, args, kwargs))
            return _ANSWER

        return call


#: Every call the coalescer passes through, with arguments it must forward as they are.
_PASS_THROUGHS: list[tuple[str, tuple[object, ...], dict[str, object]]] = [
    ("headroom", (_A0, _A1), {}),
    ("place_order", (_A0,), {}),
    ("place_batch", (_A0,), {}),
    ("amend_order", (_A0,), {}),
    ("cancel_all", (_A0, _A1), {}),
    ("set_trading_stop", (_A0,), {}),
    ("set_leverage", (_A0, _A1, _A2), {}),
    ("open_orders", (_A0, _A1), {"order_link_id": _A2}),
    (
        "order_history", (_A0,),
        {"order_link_id": _A1, "exchange_order_id": _A2, "start": _A3, "end": _A4},
    ),
    ("positions", (_A0,), {}),
    ("executions", (_A0, _A1, _A2), {}),
    ("closed_pnl", (_A0, _A1, _A2), {}),
    ("wallet", (_A0,), {}),
    ("fee_rate", (_A0, _A1), {}),
    ("account_info", (_A0,), {}),
    ("subscribe_private", (_A0,), {}),
]  # fmt: skip


def test_the_pass_throughs_are_every_call_but_the_folds_own() -> None:
    own = {"coverage", "fold", "cancel_order", "aclose"}
    public = {name for name in vars(CancelAllCoalescer) if not name.startswith("_")}
    assert public - own == {name for name, _, _ in _PASS_THROUGHS} and len(_PASS_THROUGHS) == 16


@pytest.mark.parametrize(
    ("name", "args", "kwargs"), _PASS_THROUGHS, ids=[name for name, _, _ in _PASS_THROUGHS]
)
async def test_each_pass_through_forwards_its_exact_arguments_and_answers_its_inner_result(
    name: str, args: tuple[object, ...], kwargs: dict[str, object]
) -> None:
    """CR-S4F-08: each call passes to the inner port once, with the arguments it was given, and
    answers what the inner port answered (`set_leverage` answers nothing, as its port's)."""
    inner = _Recorder()
    clock = _Clock()
    port = CancelAllCoalescer(
        cast(RoutedPort, inner), spacer=CancelAllSpacer(monotonic=clock), monotonic=clock
    )
    got = getattr(port, name)(*args, **kwargs)
    if inspect.isawaitable(got):
        got = await got
    assert inner.calls == [(name, args, kwargs)]
    assert got is (None if name == "set_leverage" else _ANSWER)
    assert port.capabilities is _Recorder.capabilities


async def test_coverage_holds_when_every_plain_order_resting_is_a_member() -> None:
    port, _, _ = _port(_venue("a", "b", "tp", kinds={"tp": "take_profit"}))
    assert await port.coverage(_REF, _BTC, _ids("a", "b"))  # the venue's call leaves the TP
    assert not await port.coverage(_REF, _BTC, _ids("a"))  # "b" rests unselected: per-order
    venue = _venue("a")
    port, _, _ = _port(venue)
    assert [(c.method, c.lane) for c in venue.calls] == []
    await port.coverage(_REF, _BTC, _ids("a"))
    assert [(c.method, c.lane) for c in venue.calls] == [("open_orders", "poll")]  # Q3


async def test_a_coverage_read_that_fails_is_no_coverage() -> None:
    venue = _venue("a")
    venue.script("open_orders", TransportError("the venue did not answer"))
    port, _, _ = _port(venue)
    assert not await port.coverage(_REF, _BTC, _ids("a"))


async def test_a_coverage_read_that_raises_any_error_is_no_coverage_and_is_logged() -> None:
    """C11 (CR-S4F-14): any failure of the read, a defect too, is no proof of coverage, logged by
    its type, never raised into the request."""
    venue = _venue("a")
    venue.script("open_orders", RuntimeError("a defect"))
    port, _, _ = _port(venue)
    with capture_logs() as logs:
        assert not await port.coverage(_REF, _BTC, _ids("a"))
    [unread] = [e for e in logs if e["event"] == "oms_cancel_all_coverage_unread"]
    assert unread["failure"] == "RuntimeError"


async def test_a_fold_left_by_an_error_no_longer_meets_its_members() -> None:
    """C5 (CR-S4F-14): the fold's members are let go however its block ends, an error too: a
    member's cancel then goes to the venue at once, and the members may fold again."""
    venue = _venue("a", "b")
    port, _, _ = _port(venue)
    with pytest.raises(RuntimeError, match="the block failed"):
        with port.fold(_REF, _BTC, _ids("a", "b")):
            raise RuntimeError("the block failed")
    async with asyncio.timeout(5):
        assert (await port.cancel_order(_cancel("a"))).ok
    with port.fold(_REF, _BTC, _ids("a", "b")):
        pass
    assert _methods(venue) == ["cancel_order"]


async def test_a_fold_meets_every_member_with_one_venue_call() -> None:
    venue = _venue("a", "b")
    port, _, _ = _port(venue)
    with port.fold(_REF, _BTC, _ids("a", "b")):
        first = asyncio.create_task(port.cancel_order(_cancel("a")))
        await _settle()
        assert _methods(venue) == []  # "a" waits for "b"
        second = await port.cancel_order(_cancel("b"))
        assert (await first).order_link_id == _id("a") and second.order_link_id == _id("b")
    assert _methods(venue) == ["cancel_all"]
    assert venue.cancel_all_scopes[0][:2] == (_ACCOUNT, _BTC)
    assert await venue.open_orders(_REF, _BTC) == []


async def test_a_member_the_venue_call_leaves_sends_its_own_cancel() -> None:
    """A conditional entry rests as a conditional order, which the venue's plain-order filter
    leaves (24 Sec.14.2 rule 12, SR-E29-06)."""
    venue = _venue("a", "stop", kinds={"stop": "conditional"})
    port, _, _ = _port(venue)
    with port.fold(_REF, _BTC, _ids("a", "stop")):
        first = asyncio.create_task(port.cancel_order(_cancel("a")))
        last = await port.cancel_order(_cancel("stop"))
        assert (await first).ok and last.ok
    assert _methods(venue) == ["cancel_all", "cancel_order"]
    assert venue.calls[1].request == _cancel("stop")


async def test_a_member_that_never_arrives_leaves_no_venue_call() -> None:
    """The fail-safe (the 21:11Z ruling): the gather's bound passes, nothing folded is sent, and
    each member that arrived sends its own cancel."""
    venue = _venue("a", "b")
    port, sleeps, _ = _port(venue)
    with port.fold(_REF, _BTC, _ids("a", "b")):
        first = asyncio.create_task(port.cancel_order(_cancel("a")))
        await _settle()
        sleeps.passed.set()  # "b" was refused before its send: it never comes
        assert (await first).ok
    assert _methods(venue) == ["cancel_order"]


async def test_a_member_that_leaves_ends_the_fold_at_once() -> None:
    venue = _venue("a", "b")
    port, sleeps, _ = _port(venue)
    with port.fold(_REF, _BTC, _ids("a", "b")) as join:
        first = asyncio.create_task(port.cancel_order(_cancel("a")))
        await _settle()
        join.leave(_id("b"))
        assert (await first).ok and not sleeps.passed.is_set()
    assert _methods(venue) == ["cancel_order"]


async def test_the_next_fold_on_a_uid_waits_out_its_second() -> None:
    venue = _venue("a", "b")
    port, sleeps, _ = _port(venue)
    with port.fold(_REF, _BTC, _ids("a", "b")):  # takes the UID's slot at 100
        first = asyncio.create_task(port.cancel_order(_cancel("a")))
        await port.cancel_order(_cancel("b"))
        await first
    for name in ("c", "d"):  # placed after the first call, so only the second covers them
        venue.seed_order(_resting(name), uid=_REF.uid)
    with port.fold(_REF, _BTC, _ids("c", "d")):  # its slot is 101, within the 2 s wait
        third = asyncio.create_task(port.cancel_order(_cancel("c")))
        fourth = asyncio.create_task(port.cancel_order(_cancel("d")))
        await _settle()
        assert sleeps.asked[-1] == pytest.approx(1.0)
        sleeps.passed.set()
        assert (await third).ok and (await fourth).ok
    assert _methods(venue) == ["cancel_all", "cancel_all"]


async def test_a_spacer_slot_past_its_wait_leaves_each_member_its_own_cancel() -> None:
    venue = _venue("a", "b")
    port, _, clock = _port(venue)
    port._spacer._free_at[_REF.uid] = clock.now + 5.0  # another fold took the next few seconds
    with port.fold(_REF, _BTC, _ids("a", "b")):
        first = asyncio.create_task(port.cancel_order(_cancel("a")))
        assert (await port.cancel_order(_cancel("b"))).ok and (await first).ok
    assert _methods(venue) == ["cancel_order", "cancel_order"]


async def test_a_refused_venue_call_leaves_each_member_its_own_cancel() -> None:
    venue = _venue("a", "b")
    venue.script("cancel_all", FakeReject(OmsErrorCode.RATE_LIMITED))
    port, _, _ = _port(venue)
    with port.fold(_REF, _BTC, _ids("a", "b")):
        first = asyncio.create_task(port.cancel_order(_cancel("a")))
        assert (await port.cancel_order(_cancel("b"))).ok and (await first).ok
    assert _methods(venue) == ["cancel_all", "cancel_order", "cancel_order"]


async def test_a_venue_call_that_raises_raises_for_every_member() -> None:
    venue = _venue("a", "b")
    venue.script("cancel_all", TransportError("the venue did not answer"))
    port, _, _ = _port(venue)
    with port.fold(_REF, _BTC, _ids("a", "b")):
        first = asyncio.create_task(port.cancel_order(_cancel("a")))
        with pytest.raises(TransportError):
            await port.cancel_order(_cancel("b"))
        with pytest.raises(TransportError):
            await first
    assert _methods(venue) == ["cancel_all"]  # never re-sent as per-order cancels


async def test_a_cancel_outside_the_fold_passes_through_while_it_is_open() -> None:
    venue = _venue("a", "b", "other")
    port, _, _ = _port(venue)
    with port.fold(_REF, _BTC, _ids("a", "b")):
        assert (await port.cancel_order(_cancel("other"))).ok
    assert _methods(venue) == ["cancel_order"]


async def test_a_closed_fold_no_longer_meets_its_members() -> None:
    venue = _venue("a", "b")
    port, _, _ = _port(venue)
    with port.fold(_REF, _BTC, _ids("a", "b")):
        pass
    assert (await port.cancel_order(_cancel("a"))).ok
    assert _methods(venue) == ["cancel_order"]


async def test_an_order_meets_one_open_fold_only() -> None:
    port, _, _ = _port(_venue("a", "b"))
    with port.fold(_REF, _BTC, _ids("a", "b")):
        with pytest.raises(FoldRefused, match="already a member"):
            with port.fold(_REF, _BTC, _ids("b", "c")):
                pass
        with port.fold(_REF, _BTC, _ids("c")):  # a disjoint fold opens beside it
            pass


async def test_an_order_placed_after_the_coverage_read_is_taken_and_logged() -> None:
    """The ruled residual: the venue's call takes every plain order resting on the symbol, those
    placed after the coverage read too. The coalescer names each in its own WARNING, under the one
    key the redactor lets an order link id through (CR-S4F-04): run through the real processor,
    each id survives, where a list of them is masked whole."""
    venue = _venue("a", "b")
    port, _, _ = _port(venue)
    assert await port.coverage(_REF, _BTC, _ids("a", "b"))
    for name in ("other", "c"):  # placed in the window
        venue.seed_order(_resting(name), uid=_REF.uid)
    with (
        capture_logs(processors=[_redaction_processor]) as logs,
        port.fold(_REF, _BTC, _ids("a", "b")),
    ):
        first = asyncio.create_task(port.cancel_order(_cancel("a")))
        assert (await port.cancel_order(_cancel("b"))).ok and (await first).ok
    taken = [e for e in logs if e["event"] == "oms_cancel_all_took_non_member"]
    assert [(e["symbol"], e["order_link_id"]) for e in taken] == [
        (_BTC, link) for link in sorted(_ids("other", "c"))
    ]
    assert all(e["log_level"] == "warning" for e in taken)


_SIZES = next(spec for spec in CATALOGUE if spec.name == "oms_cancel_all_fold_members")


def _fold_sizes(metrics: Metrics) -> BoundedMetric:
    """The histogram as the wiring registers it, from the catalogue."""
    return metrics.histogram(
        _SIZES.name, _SIZES.help, _SIZES.labels, buckets=_SIZES.buckets or (),
        max_series=_SIZES.max_series,
    )  # fmt: skip


def _observed(metrics: Metrics) -> dict[tuple[str, str], float]:
    """`oms_cancel_all_fold_members` as served: (count or sum, outcome) to its value."""
    seen: dict[tuple[str, str], float] = {}
    for family in text_string_to_metric_families(generate_latest(metrics.registry).decode()):
        for sample in family.samples:
            if sample.name in (f"{_SIZES.name}_count", f"{_SIZES.name}_sum"):
                seen[(sample.name.rsplit("_", 1)[1], sample.labels["outcome"])] = sample.value
    return seen


def test_the_fold_size_histogram_is_bounded_by_its_outcomes() -> None:
    """CR-S4F-06 (b): two series, one per outcome; the edges start at the fewest members a fold
    takes and hold the proposed cap of 32."""
    assert (_SIZES.kind, _SIZES.labels, _SIZES.max_series) == ("histogram", ("outcome",), 2)
    assert FOLD_OUTCOMES == ("sent", "abandoned")
    assert (_SIZES.buckets or ())[0] == FOLD_MIN and 32 in (_SIZES.buckets or ())


async def test_each_fold_is_counted_once_by_size_and_outcome_and_an_abandoned_one_logged() -> None:
    """CR-S4F-06 (b) and the abandoned fold's log signal (CR-S4F-20): each fold observes its
    members once, as it closes, sent or abandoned; an abandoned one also logs why."""
    metrics, venue = Metrics("dev"), _venue("a", "b")
    clock, sleeps = _Clock(), _Sleeps()
    port = CancelAllCoalescer(
        venue, spacer=CancelAllSpacer(monotonic=clock, sleep=sleeps.sleep), monotonic=clock,
        sleep=sleeps.sleep, fold_sizes=_fold_sizes(metrics),
    )  # fmt: skip
    async with asyncio.timeout(5):
        with port.fold(_REF, _BTC, _ids("a", "b")):  # sent
            first = asyncio.create_task(port.cancel_order(_cancel("a")))
            assert (await port.cancel_order(_cancel("b"))).ok and (await first).ok
        for name in ("c", "d"):  # placed after the first call, so only the second could take them
            venue.seed_order(_resting(name), uid=_REF.uid)
        with capture_logs() as logs, port.fold(_REF, _BTC, _ids("c", "d", "other")) as join:
            third = asyncio.create_task(port.cancel_order(_cancel("c")))
            await _settle()
            join.leave(_id("other"))  # refused before its send: abandoned, nothing sent
            assert (await third).ok
    assert _observed(metrics) == {
        ("count", "sent"): 1.0, ("sum", "sent"): 2.0,
        ("count", "abandoned"): 1.0, ("sum", "abandoned"): 3.0,
    }  # fmt: skip
    [abandoned] = [e for e in logs if e["event"] == "oms_cancel_all_fold_abandoned"]
    assert (abandoned["symbol"], abandoned["members"], abandoned["why"]) == (_BTC, 3, "left")
    assert _methods(venue) == ["cancel_all", "cancel_order"]


# --- L1 (CR-S4F-03): the call is the fold's own task -------------------------------------------


class _HeldVenue(FakeTradingPort):
    """The venue runs a cancel-all at once and holds its answer until `answered` is set: the call
    has left, its answer still out. `cut` counts the calls cut short while held."""

    def __init__(self) -> None:
        super().__init__()
        self.answered = asyncio.Event()
        self.cut = 0

    async def cancel_all(self, account: AccountRef, symbol: Symbol | None) -> Sequence[OrderAck]:
        acks = await super().cancel_all(account, symbol)
        try:
            await self.answered.wait()
        except asyncio.CancelledError:
            self.cut += 1
            raise
        return acks


async def _waiting(venue: FakeTradingPort) -> tuple[CancelAllCoalescer, _Sleeps]:
    """The coalescer over `venue`, the UID's slot at 100 spent by an earlier fold, so the next
    call waits in the spacer for its slot at 101 until the test lets the wait pass."""
    clock, sleeps = _Clock(), _Sleeps()
    spacer = CancelAllSpacer(monotonic=clock, sleep=sleeps.sleep)
    assert await spacer.turn(_REF.uid, deadline=clock.now + 5)
    return CancelAllCoalescer(venue, spacer=spacer, monotonic=clock, sleep=sleeps.sleep), sleeps


def _fold_tasks() -> list[str]:
    """The fold's own tasks still running: its call and its gather's watchdog."""
    return sorted(
        task.get_name()
        for task in asyncio.all_tasks()
        if task.get_name().startswith("oms-cancel-all-") and not task.done()
    )


async def test_a_leader_cut_short_before_the_call_leaves_abandons_the_fold() -> None:
    """L1 (the security look's probe E): the last member is cut short while the call waits for
    its spacer slot. Nothing has left, so the fold is abandoned and the other member sends its
    own cancel: no outcome is unknown, and no cancel-all leaves."""
    venue = _venue("a", "b")
    port, sleeps = await _waiting(venue)
    async with asyncio.timeout(5):
        with port.fold(_REF, _BTC, _ids("a", "b")):
            first = asyncio.create_task(port.cancel_order(_cancel("a")))
            await _settle()
            last = asyncio.create_task(port.cancel_order(_cancel("b")))  # the last: it leads
            await _settle()
            assert sleeps.asked == [1.0, 1.0] and _methods(venue) == []  # the spacer's wait
            last.cancel()
            with pytest.raises(asyncio.CancelledError):
                await last
            assert (await first).order_link_id == _id("a")  # its own cancel, answered
    assert _methods(venue) == ["cancel_order"]
    assert [o.order_link_id for o in await venue.open_orders(_REF, _BTC)] == _ids("b")


async def test_a_leader_cut_short_once_its_call_has_left_leaves_the_call_to_answer_each() -> None:
    """L1: once the call has left, no member's cancellation cuts it short. Its acks answer every
    member, the one cut short too should it ask again, and nothing is sent again."""
    venue = _HeldVenue()
    for name in ("a", "b"):
        venue.seed_order(_resting(name), uid=_REF.uid)
    port, sleeps = await _waiting(venue)
    async with asyncio.timeout(5):
        with port.fold(_REF, _BTC, _ids("a", "b")):
            first = asyncio.create_task(port.cancel_order(_cancel("a")))
            await _settle()
            last = asyncio.create_task(port.cancel_order(_cancel("b")))
            await _settle()
            sleeps.passed.set()  # the slot comes: the call leaves, its answer held
            await _settle()
            assert _methods(venue) == ["cancel_all"]
            last.cancel()
            with pytest.raises(asyncio.CancelledError):
                await last
            venue.answered.set()
            assert (await first).order_link_id == _id("a")
            again = await port.cancel_order(_cancel("b"))  # answered by its ack, never re-sent
            assert again.ok and again.order_link_id == _id("b")
    assert _methods(venue) == ["cancel_all"] and venue.cut == 0


async def test_a_call_every_member_left_runs_on_owned_until_aclose_ends_it() -> None:
    """L1: the call is the coalescer's own task, never fire-and-forget. Members all cut short
    once it left leave it running, answered to no one; `aclose` (the runtime's stop) ends it,
    and no fold task runs after."""
    venue = _HeldVenue()
    for name in ("a", "b"):
        venue.seed_order(_resting(name), uid=_REF.uid)
    port, sleeps = await _waiting(venue)
    async with asyncio.timeout(5):
        with port.fold(_REF, _BTC, _ids("a", "b")):
            first = asyncio.create_task(port.cancel_order(_cancel("a")))
            await _settle()
            last = asyncio.create_task(port.cancel_order(_cancel("b")))
            await _settle()
            sleeps.passed.set()
            await _settle()
            for member in (first, last):
                member.cancel()
            for member in (first, last):
                with pytest.raises(asyncio.CancelledError):
                    await member
        assert _fold_tasks() == ["oms-cancel-all-call"]  # still out, owned
        await port.aclose()
    assert _fold_tasks() == [] and venue.cut == 1
    assert _methods(venue) == ["cancel_all"]  # cut short at teardown, never re-sent


async def test_a_slot_wait_that_fails_abandons_the_fold_and_its_failure_is_logged() -> None:
    """A defect in the wait for the slot, before anything left: nothing was sent, so the fold is
    abandoned and each member sends its own cancel, never left waiting; the call task's failure
    is logged as the coalescer owns it."""
    venue, clock, gather = _venue("a", "b"), _Clock(), _Sleeps()

    async def broken(seconds: float) -> None:
        raise RuntimeError("the spacer's sleep broke")

    spacer = CancelAllSpacer(monotonic=clock, sleep=broken)
    assert await spacer.turn(_REF.uid, deadline=clock.now + 5)  # the next slot is 101: it waits
    port = CancelAllCoalescer(venue, spacer=spacer, monotonic=clock, sleep=gather.sleep)
    async with asyncio.timeout(5):
        with capture_logs() as logs, port.fold(_REF, _BTC, _ids("a", "b")) as join:
            first = asyncio.create_task(port.cancel_order(_cancel("a")))
            await _settle()
            assert (await port.cancel_order(_cancel("b"))).ok and (await first).ok
            await _settle()
    assert join.abandoned == "slot" and _methods(venue) == ["cancel_order", "cancel_order"]
    [failed] = [e for e in logs if e["event"] == "oms_cancel_all_task_failed"]
    assert (failed["task"], failed["failure"]) == ("oms-cancel-all-call", "RuntimeError")


# --- CR-S4F-12: a KILL's cancel never waits on a fold --------------------------------------------


async def _resting_row(rig: cr.Rig, seq: int) -> OrderRow:
    """The command rig's order `seq`, resting at the venue and stored `submitted`, bound."""
    order = cr.new_order(seq=seq)
    resting = cr.exchange_order(order)
    rig.demo.seed_order(resting, uid=cr.UIDS["demo"])
    bound = dataclasses.replace(order, exchange_order_id=resting.exchange_order_id)
    return await rig.stored(bound, lifecycle="submitted")


async def test_a_kills_cancel_of_a_fold_member_goes_out_at_once_and_b1s_own_meets_the_fold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-S4F-12: the command port marks a KILL's own cancel (B1's `issue_kill_cancel`, kind
    `kill_cancel`), so the coalescer sends it to the venue at once, though its order is a member
    of an open fold, never held by the gather, the spacer or the call. B1's own cancel of another
    member still meets the fold."""
    rig = cr.build_rig()
    killed, own = await _resting_row(rig, 1), await _resting_row(rig, 2)
    clock, sleeps = _Clock(), _Sleeps()  # the gather's bound never passes on its own here
    folds = CancelAllCoalescer(
        rig.demo, spacer=CancelAllSpacer(monotonic=clock, sleep=sleeps.sleep), monotonic=clock,
        sleep=sleeps.sleep,
    )  # fmt: skip
    router = TradingRouter({"demo": folds, "live": rig.live}, lane_waits=cr.LANE_WAITS)
    monkeypatch.setattr(rig.port, "_router", router)
    members = [killed.order_link_id, own.order_link_id]
    async with asyncio.timeout(5):
        with folds.fold(cr.ref(), Symbol(cr.SYMBOL), members) as join:
            answer = await rig.port.cancel(cr.command("kill_cancel", killed))
            assert answer["ok"] is True and rig.calls() == ["cancel_order"]
            waiting = asyncio.create_task(rig.port.cancel(cr.command("cancel", own)))
            await _settle()
            assert not waiting.done()  # B1's own cancel meets its fold
            join.leave(killed.order_link_id)  # its own cancel never comes once it is killed
            assert (await waiting)["ok"] is True
    assert rig.calls() == ["cancel_order", "cancel_order"]


async def test_a_cancel_sent_unfolded_never_meets_its_fold_and_the_mark_ends_with_it() -> None:
    """`unfolded`: a member's cancel so sent goes to the venue at once; the cancels after it, not
    so sent, meet the fold as before. Its own cancel never coming, the fold is abandoned."""
    venue = _venue("a", "b")
    port, _, _ = _port(venue)
    async with asyncio.timeout(5):
        with port.fold(_REF, _BTC, _ids("a", "b")) as join:
            assert (await unfolded(port.cancel_order(_cancel("a")))).order_link_id == _id("a")
            assert _methods(venue) == ["cancel_order"]
            second = asyncio.create_task(port.cancel_order(_cancel("b")))
            await _settle()
            assert not second.done()  # unmarked: it meets the fold and waits for "a"
            join.leave(_id("a"))
            assert (await second).ok and join.abandoned == "left"
    assert _methods(venue) == ["cancel_order", "cancel_order"]
