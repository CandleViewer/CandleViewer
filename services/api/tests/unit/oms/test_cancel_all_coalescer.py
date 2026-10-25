"""The venue cancel-all fold's port (E29-T04 #913 slice 4, S4-F; 24 Sec.8.7; the 21:11Z ruling):
`CancelAllCoalescer` around the in-memory venue (`FakeTradingPort`). Every call passes through as
it is but a fold member's `cancel_order`, which meets its fold: one venue `cancel-all` once every
member has arrived, else none, and each member its own cancel (the fail-safe). Nothing sleeps:
the gather's bound and the spacer's wait are injected and released by the test."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.order_link import account_tag
from candleviewer.domain.primitives import AccountId, Symbol
from candleviewer.exchange.base.errors import OmsErrorCode, TransportError
from candleviewer.exchange.base.fakes import FakeReject, FakeTradingPort
from candleviewer.exchange.base.models import AccountRef, CancelOrderRequest, Order
from candleviewer.oms.cancel_all_coalescer import CancelAllCoalescer
from candleviewer.oms.cancel_all_fold import CancelAllSpacer

_ACCOUNT = AccountId(UUID("5b1c9d2e-7f30-4a6b-8c4d-2e3f4a5b6c7d"))
_REF = AccountRef(account_id=_ACCOUNT, uid="100001", environment="demo", key_ref=str(UUID(int=1)))
_BTC = Symbol("BTCUSDT")
_NAMES = ("a", "b", "c", "d", "stop", "tp", "other")


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
        with pytest.raises(ValueError, match="already a member"):
            with port.fold(_REF, _BTC, _ids("b", "c")):
                pass
        with port.fold(_REF, _BTC, _ids("c")):  # a disjoint fold opens beside it
            pass


async def test_an_order_placed_after_the_coverage_read_is_taken_and_logged() -> None:
    """The ruled residual: the venue's call takes every plain order resting on the symbol, one
    placed after the coverage read too; the coalescer names each such order in a WARNING."""
    venue = _venue("a", "b")
    port, _, _ = _port(venue)
    assert await port.coverage(_REF, _BTC, _ids("a", "b"))
    venue.seed_order(_resting("other"), uid=_REF.uid)  # placed in the window
    with capture_logs() as logs, port.fold(_REF, _BTC, _ids("a", "b")):
        first = asyncio.create_task(port.cancel_order(_cancel("a")))
        assert (await port.cancel_order(_cancel("b"))).ok and (await first).ok
    [taken] = [e for e in logs if e["event"] == "oms_cancel_all_took_non_member"]
    assert (taken["count"], taken["order_link_ids"]) == (1, _ids("other"))
