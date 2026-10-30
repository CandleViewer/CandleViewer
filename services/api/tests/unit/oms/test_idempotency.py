"""The replay anchor's answers (E29-T04 #913; 21-database-schema.md Sec.3.3.10 "Repeats") over
the in-memory stores, which keep the anchor store's contract (`submission_contract.py`): a key
never seen, a decided anchor replayed (its `202`, `429` or `502`, and no `Retry-After`), one in
flight and one past `CV_OMS_INFLIGHT_STUCK_S` decided once, a key reused with another body or for a
trade group, a store that does not answer, and log lines that never carry the key or the
fingerprint (21 Sec.12)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from structlog.testing import capture_logs

from candleviewer.oms.errors import Problem, StoreUnavailable, problem_for
from candleviewer.oms.fakes import InMemoryOrderStore
from candleviewer.oms.idempotency import (
    IN_FLIGHT_RETRY_S,
    STUCK_AFTER_S,
    AnchorService,
    Fresh,
    InFlight,
    KeyReuse,
    Replay,
)
from candleviewer.oms.repository import IdempotencyAnchorRepository
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.idempotency_anchors import AnchorOutcome, AnchorRow
from candleviewer.storage.repositories.submissions import FirstPersist
from tests.unit.oms.submission_contract import EVENT, SHA, T0, entry, reduce_only

OTHER_SHA = "cd" * 32


@dataclass
class Clock:
    now: datetime = T0

    def __call__(self) -> datetime:
        return self.now


class Spy:
    """The fake's anchor store, keeping each compare-and-set's result."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.decided = inner, list[bool]()

    async def find(self, *args: Any, **kw: Any) -> AnchorRow | None:
        found: AnchorRow | None = await self.inner.find(*args, **kw)
        return found

    async def record_outcome(self, anchor_id: UUID, outcome: AnchorOutcome) -> bool:
        done: bool = await self.inner.record_outcome(anchor_id, outcome)
        self.decided.append(done)
        return done


@dataclass
class Rig:
    db: InMemoryOrderStore
    spy: Spy
    clock: Clock
    service: AnchorService

    async def anchored(self, user: UUID, *, entry_key: bool = False) -> tuple[FirstPersist, UUID]:
        """A request's first persist under a new key, and that key."""
        if entry_key:
            first, order = entry(user, uuid4(), uuid4())
        else:
            first, order = reduce_only(user, uuid4())
        await self.db.submissions.create_first(first, order, EVENT)
        return first, UUID(first.anchor.client_ref)


@pytest.fixture
def rig() -> Rig:
    db, clock = InMemoryOrderStore(clock=lambda: T0), Clock()
    spy = Spy(db.anchors)
    service = AnchorService(IdempotencyAnchorRepository(cast(Any, spy)), clock=clock, timeout_s=1)
    return Rig(db, spy, clock, service)


async def test_a_key_never_seen_is_a_first_submission(rig: Rig) -> None:
    user = uuid4()
    _, key = await rig.anchored(user)
    assert await rig.service.lookup(user, uuid4(), SHA) == Fresh()
    assert await rig.service.lookup(uuid4(), key, SHA) == Fresh()  # another principal's (SR-E29-07)


@pytest.mark.parametrize(
    "outcome",
    [
        AnchorOutcome(status=202, decided_at=T0),
        AnchorOutcome(status=429, code="exchange_rate_limited", decided_at=T0),
        AnchorOutcome(status=502, code="exchange_error", ret_code=110007, decided_at=T0),
    ],
    ids=["accepted", "rate_limited", "rejected"],
)
async def test_a_decided_anchor_is_replayed_and_carries_no_retry_after(
    rig: Rig, outcome: AnchorOutcome
) -> None:
    """22 `placeOrder`: a recorded `429` is not retryable under its key, so a replay is that
    `429` again, and nothing it answers carries a delay."""
    user = uuid4()
    first, key = await rig.anchored(user)
    assert await rig.service.record(first.anchor.id, outcome) is True
    rig.clock.now = T0 + timedelta(days=400)  # a replay at any age
    answer = await rig.service.lookup(user, key, SHA)
    assert isinstance(answer, Replay) and [f.name for f in fields(answer)] == ["anchor"]
    replayed = answer.anchor
    assert (replayed.id, replayed.outcome_status) == (first.anchor.id, outcome.status)
    assert (replayed.outcome_code, replayed.outcome_ret_code) == (outcome.code, outcome.ret_code)
    assert rig.spy.decided == [True]


async def test_an_undecided_anchor_is_in_flight_until_it_is_stuck(rig: Rig) -> None:
    user = uuid4()
    _, key = await rig.anchored(user)
    rig.clock.now = T0 + timedelta(seconds=STUCK_AFTER_S) - timedelta(microseconds=1)
    answer = await rig.service.lookup(user, key, SHA)
    assert isinstance(answer, InFlight) and answer == InFlight(IN_FLIGHT_RETRY_S) == InFlight(1)
    assert problem_for(answer.refusal()) == Problem(409, "idempotency_in_flight", retry_after=True)
    assert answer.refusal().retry_after_s == 1 and rig.spy.decided == []


async def test_a_stuck_anchor_is_decided_accepted_once_and_replayed(rig: Rig) -> None:
    """Its request ended without recording an answer: the repeat decides it `202`, by
    compare-and-set from none; of two repeats at once, one decides and the other replays it."""
    user = uuid4()
    first, key = await rig.anchored(user)
    rig.clock.now = T0 + timedelta(seconds=STUCK_AFTER_S)
    answers = await asyncio.gather(*(rig.service.lookup(user, key, SHA) for _ in "ab"))
    assert sorted(rig.spy.decided) == [False, True]
    for answer in answers:
        assert isinstance(answer, Replay) and answer.anchor.id == first.anchor.id
        assert (answer.anchor.outcome_status, answer.anchor.decided_at) == (202, rig.clock.now)
    later = await rig.service.lookup(user, key, SHA)
    assert isinstance(later, Replay) and later.anchor.outcome_status == 202
    assert len(rig.spy.decided) == 2


async def test_a_key_reused_with_another_body_is_refused_decided_or_not(rig: Rig) -> None:
    user = uuid4()
    first, key = await rig.anchored(user)
    assert await rig.service.lookup(user, key, OTHER_SHA) == KeyReuse()
    await rig.service.record(first.anchor.id, AnchorOutcome(status=202, decided_at=T0))
    answer = await rig.service.lookup(user, key, OTHER_SHA)
    assert isinstance(answer, KeyReuse)
    assert problem_for(answer.refusal()) == Problem(409, "idempotency_key_reuse")


async def test_a_persist_that_met_its_key_is_answered_from_the_anchor(rig: Rig) -> None:
    """`AnchorTaken`: a concurrent first persist committed the key first, on the anchor or, for an
    entry, on its group; the answer is that anchor's."""
    user = uuid4()
    _, key = await rig.anchored(user)
    _, entry_key = await rig.anchored(user, entry_key=True)
    for constraint, held in (("ux_ia_principal_ref", key), ("ux_tg_creator_ref", entry_key)):
        answer = await rig.service.after_taken(cast(Any, constraint), user, held, SHA)
        assert answer == InFlight(IN_FLIGHT_RETRY_S)
    reused = await rig.service.after_taken("ux_ia_principal_ref", user, key, OTHER_SHA)
    assert reused == KeyReuse()


async def test_a_key_held_by_a_trade_group_is_key_reuse(rig: Rig) -> None:
    """21 Sec.3.3.10: a key the principal used for `createTradeGroup` holds the group's twin of
    the key and no `placeOrder` anchor; read off the constraint, with no trade-group read."""
    answer = await rig.service.after_taken("ux_tg_creator_ref", uuid4(), uuid4(), SHA)
    assert answer == KeyReuse()


async def test_an_anchor_the_store_held_but_does_not_return_is_store_unavailable(
    rig: Rig,
) -> None:
    """Its own index refused the key, yet no read finds it: nothing was sent, so `503`."""
    with capture_logs() as logs, pytest.raises(StoreUnavailable):
        await rig.service.after_taken("ux_ia_principal_ref", uuid4(), uuid4(), SHA)
    assert [line["log_level"] for line in logs] == ["error"]


class LostDecision:
    """An anchor store whose compare-and-set says another repeat decided first, yet whose next
    read shows no decision, or, `vanished`, no anchor at all."""

    def __init__(self, inner: Any, *, vanished: bool) -> None:
        self.inner, self.vanished, self.reads = inner, vanished, 0

    async def find(self, *args: Any, **kw: Any) -> AnchorRow | None:
        self.reads += 1
        if self.vanished and self.reads > 1:
            return None
        found: AnchorRow | None = await self.inner.find(*args, **kw)
        return found

    async def record_outcome(self, anchor_id: UUID, outcome: AnchorOutcome) -> bool:
        return False


@pytest.mark.parametrize("vanished", [False, True], ids=["undecided", "vanished"])
async def test_a_lost_decision_no_read_returns_is_store_unavailable(
    rig: Rig, vanished: bool
) -> None:
    """CR-2B1-02 (a): the compare-and-set says the stuck anchor is decided, yet the re-read shows
    no decision: the store is not serving what it holds, so `503 store_unavailable`, nothing
    sent, its line at ERROR naming neither the key nor the fingerprint."""
    user = uuid4()
    _, key = await rig.anchored(user)
    store = LostDecision(rig.db.anchors, vanished=vanished)
    repository = IdempotencyAnchorRepository(cast(Any, store))
    service = AnchorService(repository, clock=rig.clock, timeout_s=1)
    rig.clock.now = T0 + timedelta(seconds=STUCK_AFTER_S)
    with capture_logs() as logs, pytest.raises(StoreUnavailable) as err:
        await service.lookup(user, key, SHA)
    assert problem_for(err.value) == Problem(503, "store_unavailable") and store.reads == 2
    unread = [line["log_level"] for line in logs if line["event"] == "oms_anchor_decision_unread"]
    assert unread == ["error"] and str(key) not in repr(logs) and SHA not in repr(logs)


class Hanging:
    async def find(self, *args: Any) -> AnchorRow | None:
        await asyncio.Event().wait()
        return None

    async def record_outcome(self, *args: Any) -> bool:
        await asyncio.Event().wait()
        return False


class Down:
    async def find(self, *args: Any) -> AnchorRow | None:
        raise StorageTierUnavailable("postgres unreachable (OSError)")

    async def record_outcome(self, *args: Any) -> bool:
        raise StorageTierUnavailable("postgres unreachable (OSError)")


def _calls(service: AnchorService) -> list[Callable[[], Awaitable[object]]]:
    outcome = AnchorOutcome(status=202, decided_at=T0)
    return [
        lambda: service.lookup(uuid4(), uuid4(), SHA),
        lambda: service.after_taken("ux_tg_creator_ref", uuid4(), uuid4(), SHA),
        lambda: service.record(uuid4(), outcome),
    ]


@pytest.mark.parametrize("store", [Hanging, Down])
async def test_a_store_that_does_not_answer_in_time_is_store_unavailable(store: type) -> None:
    """Each store call is bounded (C-2.18): past its bound, or failed, `503 store_unavailable`,
    nothing having been sent, the store's error never chained to it (C-12.6)."""
    repository = IdempotencyAnchorRepository(cast(Any, store()))
    service = AnchorService(repository, clock=Clock(), timeout_s=0.01)
    for call in _calls(service):
        with pytest.raises(StoreUnavailable) as err:
            await call()
        assert err.value.__cause__ is None
        assert problem_for(err.value) == Problem(503, "store_unavailable")


@pytest.mark.parametrize("bound", [0, -1, float("nan"), float("inf"), True])
def test_every_bound_is_a_finite_number_of_seconds(bound: Any) -> None:
    repository = IdempotencyAnchorRepository(cast(Any, Down()))
    with pytest.raises(ValueError, match="finite number of seconds"):
        AnchorService(repository, clock=Clock(), timeout_s=bound)
    with pytest.raises(ValueError, match="finite number of seconds"):
        AnchorService(repository, clock=Clock(), timeout_s=1, stuck_after_s=bound)


async def test_no_line_carries_the_key_or_the_fingerprint(rig: Rig) -> None:
    """21 Sec.12: the key and the fingerprint are P1, read for the lookup and never written out."""
    user = uuid4()
    first, key = await rig.anchored(user)
    with capture_logs() as logs:
        await rig.service.lookup(user, key, SHA)
        await rig.service.lookup(user, key, OTHER_SHA)
        rig.clock.now = T0 + timedelta(minutes=5)
        await rig.service.lookup(user, key, SHA)
        await rig.service.lookup(user, key, SHA)
        await rig.service.after_taken("ux_tg_creator_ref", user, uuid4(), SHA)
    events = [line["event"] for line in logs]
    assert events[:2] == ["oms_anchor_in_flight", "oms_idempotency_key_reuse"]
    assert "oms_anchor_decided_stale" in events and "oms_anchor_replayed" in events
    text = repr(logs)
    assert str(key) not in text and SHA not in text and OTHER_SHA not in text
    assert str(first.anchor.id) in text
