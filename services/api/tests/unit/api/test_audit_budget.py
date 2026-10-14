"""`AuditRecordBudget` (contract #2392 "Audit budget"): fake clock and fake writer, no sleeps."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.api.audit_budget import (
    DENIAL_ACTION,
    FILTER_SETS_PER_USER,
    READ_ACTION,
    AuditRecordBudget,
    BudgetActor,
    BudgetWriteFailed,
    filters_digest,
)
from candleviewer.audit.models import AuditOutcome
from candleviewer.audit.redact import redact


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Writer:
    """Keeps (action, fields, clock at the call). `mode`: ok, fail, or hang until `resolve`."""

    def __init__(self, clock: _Clock) -> None:
        self.clock, self.mode = clock, "ok"
        self.records: list[tuple[str, dict[str, Any], float]] = []
        self.hanging: list[tuple[asyncio.Future[None], asyncio.Event, str, dict[str, Any]]] = []
        self.entered = asyncio.Event()

    async def emit(self, action: str, **kw: Any) -> None:
        at = self.clock()
        if self.mode == "fail":
            raise RuntimeError("audit down")
        if self.mode == "hang":
            fut, done = asyncio.get_running_loop().create_future(), asyncio.Event()
            self.hanging.append((fut, done, action, kw))
            self.entered.set()
            try:
                await fut
            finally:
                done.set()  # the budget settles in this same step, before the waiter resumes
        self.records.append((action, kw, at))

    async def resolve(self, ok: bool) -> None:
        fut, done, _, _ = self.hanging.pop(0)
        if ok:
            fut.set_result(None)
        else:
            fut.set_exception(RuntimeError("audit down"))
        await done.wait()


ACTOR = BudgetActor("u1", "manager", "u1", owner=False)
OTHER = BudgetActor("u2", "manager2", "u2", owner=False)
DENY = {"actor_label": "manager", "actor_user_id": "u1", "outcome": AuditOutcome.DENIED}
REQUEST = {"session_id": "s1", "actor_ip": "10.0.0.1", "request_id": "r1"}


def _setup(**kw: Any) -> tuple[_Clock, _Writer, AuditRecordBudget]:
    clock = _Clock()
    args = {"per_hour": 3, "owner_per_hour": 5, "flush_pages": 3, **kw}
    return clock, _Writer(clock), AuditRecordBudget(clock=clock, **args)


async def _read(b: AuditRecordBudget, w: _Writer, actor: BudgetActor, digest: str) -> str:
    """One read as the router runs it; returns the plan."""
    res = b.plan_read(actor, digest)
    try:
        if res.action == "record":
            fields = {"actor_label": actor.label, "actor_user_id": actor.user_id, **REQUEST}
            await b.write_read(res, w, fields, {"returned_count": 0})
        res.commit()
    finally:
        res.release()
    return res.action


def _pages(record: tuple[str, dict[str, Any], float]) -> dict[str, int]:
    return {p["filters_sha256"]: p["pages"] for p in record[1]["after_state"].get("pages", [])}


def _carried_pages(fields: dict[str, Any]) -> int:
    after = fields.get("after_state") or {}
    return sum(p["pages"] for p in after.get("pages", [])) + after.get("other_pages", 0)


def _recorded_pages(w: _Writer) -> int:
    return sum(_carried_pages(kw) for _, kw, _ in w.records)


async def test_only_admin_audit_denied_is_budgeted() -> None:
    _, w, b = _setup(per_hour=1)
    em = b.emitter(w, ACTOR)
    for _ in range(3):
        await em.emit("orders.submit", **DENY)
    await em.emit(DENIAL_ACTION, **DENY)
    await em.emit(DENIAL_ACTION, **DENY)
    assert [a for a, _, _ in w.records] == ["orders.submit"] * 3 + [DENIAL_ACTION]
    assert em.suppressed and b.retry_after("u1") == 3600 and b.retry_after("nobody") == 1


async def test_refusals_over_the_cap_are_counted_and_carried() -> None:
    clock, w, b = _setup()
    em = b.emitter(w, ACTOR)
    for _ in range(5):
        await em.emit(DENIAL_ACTION, **DENY)
    assert len(w.records) == 3
    clock.now += 3600
    await em.emit(DENIAL_ACTION, **DENY)
    assert w.records[-1][1]["after_state"] == {"suppressed": 2}


async def test_owner_cap_is_separate() -> None:
    _, w, b = _setup()
    owner = BudgetActor("o1", "owner", "o1", owner=True)
    for _ in range(7):
        await b.write_denial(owner, w, DENY)
    assert len(w.records) == 5


@pytest.mark.parametrize("cause", ["inflight", "writer"])
async def test_unwritable_refusal_raises_and_gives_everything_back(cause: str) -> None:
    _, w, b = _setup(inflight_cap=0 if cause == "inflight" else 64)
    b.count_suppressed(ACTOR)
    w.mode = "fail"
    with pytest.raises(BudgetWriteFailed):
        await b.emitter(w, ACTOR).emit(DENIAL_ACTION, **DENY)
    st = b._users["u1"]
    assert (st.reserved, st.stamps, st.suppressed, b.inflight, w.records) == (0, [], 1, 0, [])


@pytest.mark.parametrize("ok", [True, False])
async def test_timed_out_write_keeps_its_slot_until_it_finishes(ok: bool) -> None:
    _, w, b = _setup(per_hour=1, write_timeout_s=0)
    b.count_suppressed(ACTOR)
    w.mode = "hang"
    with pytest.raises(BudgetWriteFailed):
        await b.write_denial(ACTOR, w, DENY)
    st = b._users["u1"]
    assert (st.reserved, st.suppressed, b.inflight) == (1, 0, 1)
    assert not await b.write_denial(ACTOR, w, DENY)  # the slow write still holds the slot
    await w.resolve(ok)
    assert (st.reserved, b.inflight, len(st.stamps), st.suppressed) == (0, 0, ok, 2 - ok)


@pytest.mark.parametrize("ok", [True, False])
async def test_cancelled_caller_neither_loses_nor_doubles_the_carried_count(ok: bool) -> None:
    _, w, b = _setup()
    b.count_suppressed(ACTOR)
    w.mode = "hang"
    caller = asyncio.ensure_future(b.write_denial(ACTOR, w, DENY))
    await w.entered.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    await w.resolve(ok)
    recorded = sum(r[1]["after_state"].get("suppressed", 0) for r in w.records)
    assert recorded + b._users["u1"].suppressed == 1


async def test_untracked_user_writes_nothing_and_its_429s_are_held() -> None:
    clock, w, b = _setup(tracked_users=1)
    await b.write_denial(ACTOR, w, DENY)  # u1 has a record this hour: it cannot be evicted
    with pytest.raises(BudgetWriteFailed):
        await b.write_denial(OTHER, w, DENY)
    assert b.plan_read(OTHER, "f").action == "unwritable"
    b.count_suppressed(OTHER)
    assert (b._untracked, len(w.records)) == (1, 1)
    clock.now += 3600  # u1's hour has passed and it holds nothing: evictable
    assert b.plan_read(OTHER, "f").action == "record" and list(b._users) == ["u2"]


async def test_read_records_one_per_filter_set_and_carry_continuation_pages() -> None:
    clock, w, b = _setup(per_hour=10)
    assert [await _read(b, w, ACTOR, "A") for _ in range(4)] == [
        "record",
        "count",
        "count",
        "record",
    ]
    assert [_pages(r) for r in w.records] == [{"A": 1}, {"A": 3}]
    clock.now += 300
    assert await _read(b, w, ACTOR, "A") == "record"  # due by time
    assert _pages(w.records[-1]) == {"A": 1}
    assert w.records[-1][1]["after_state"]["filters_sha256"] == "A"


async def test_switching_filter_sets_keeps_every_page() -> None:
    _, w, b = _setup(per_hour=100, flush_pages=50)
    for _ in range(10):
        await _read(b, w, ACTOR, "A")
    await _read(b, w, ACTOR, "B")
    assert [_pages(r) for r in w.records] == [{"A": 1}, {"A": 9, "B": 1}]


async def test_refusals_between_pages_keep_every_page() -> None:
    _, w, b = _setup(per_hour=1000, flush_pages=50)
    em = b.emitter(w, ACTOR)
    for i in range(980):
        await _read(b, w, ACTOR, "A")
        if i % 49 == 48:
            await em.emit(DENIAL_ACTION, **DENY)
    assert _recorded_pages(w) + b._users["u1"].pending_pages() == 980


async def test_filter_sets_beyond_the_per_user_window_fold_into_other_pages() -> None:
    _, w, b = _setup(per_hour=100, flush_pages=1000)
    await _read(b, w, ACTOR, "F0")
    held = b.plan_read(ACTOR, "F0")
    assert held.action == "count"
    for d in range(1, FILTER_SETS_PER_USER + 1):
        await _read(b, w, ACTOR, f"F{d}")
    assert "F0" not in b._users["u1"].pages
    held.commit()
    await _read(b, w, ACTOR, "G")
    assert w.records[-1][1]["after_state"]["other_pages"] == 1


async def test_read_over_the_cap_is_refused_and_counted() -> None:
    _, w, b = _setup(per_hour=1)
    assert [await _read(b, w, ACTOR, d) for d in "AB"] == ["record", "refuse"]
    assert b._users["u1"].suppressed == 1 and b.retry_after("u1") == 3600


async def test_unwritable_read_record_gives_its_page_and_counts_back() -> None:
    _, w, b = _setup(per_hour=10)
    await _read(b, w, ACTOR, "A")
    await _read(b, w, ACTOR, "A")
    b.count_suppressed(ACTOR)
    w.mode = "fail"
    with pytest.raises(BudgetWriteFailed):
        await _read(b, w, ACTOR, "B")
    st = b._users["u1"]
    assert (st.pages["A"], st.suppressed, st.reserved, st.reading, len(st.stamps)) == (
        1,
        1,
        0,
        0,
        1,
    )
    assert "B" not in st.pages


async def test_reservations_release_once_and_a_record_is_served_only_by_its_write() -> None:
    _, w, b = _setup(per_hour=10)
    rec = b.plan_read(ACTOR, "A")
    rec.commit()  # never written: released, not served
    st = b._users["u1"]
    assert (st.reserved, st.reading) == (0, 0)
    with pytest.raises(ValueError, match="open `record`"):
        await b.write_read(rec, w, {}, {})
    await _read(b, w, ACTOR, "A")
    cnt = b.plan_read(ACTOR, "A")
    cnt.release()
    cnt.release()
    cnt.commit()
    assert (st.reading, st.pages["A"]) == (0, 0)


async def test_a_user_holding_a_reservation_is_never_evicted() -> None:
    clock, w, b = _setup(tracked_users=1, per_hour=10)
    res = b.plan_read(ACTOR, "A")
    clock.now += 7200
    assert b.plan_read(OTHER, "B").action == "unwritable"
    await b.write_read(res, w, {"actor_label": "manager", "actor_user_id": "u1"}, {})
    res.commit()
    assert _pages(w.records[-1]) == {"A": 1}


def test_filters_digest_ignores_key_order() -> None:
    assert filters_digest({"a": 1, "b": [2]}) == filters_digest({"b": [2], "a": 1})
    assert filters_digest({"a": 1}) != filters_digest({"a": 2})


async def test_budget_records_pass_audit_redaction_unchanged() -> None:
    clock, w, b = _setup(per_hour=10)
    for d in ("A", "A", "B"):
        await _read(b, w, ACTOR, d)
    b.count_suppressed(ACTOR)
    clock.now += 300
    await _read(b, w, ACTOR, "C")
    await b.write_denial(ACTOR, w, {**DENY, "after_state": {"requested_actor": "u9"}})
    assert all(redact(kw["after_state"]) == kw["after_state"] for _, kw, _ in w.records)


# ---- property: any interleaving keeps the record bound and every count ---------------------

_ACTORS = [BudgetActor(f"p{i}", f"user{i}", f"p{i}", owner=i == 0) for i in range(3)]
_CAPS, _WINDOW = {"p0": 3, "p1": 2, "p2": 2}, 300.0
_KINDS = ("read", "start_read", "finish_read", "refuse", "limit_429", "advance", "writer")
_KINDS += ("resolve",)


def _ops(kinds: frozenset[str]) -> st.SearchStrategy[list[tuple[str, int, str, bool, int, str]]]:
    """(kind, user or open-read index, filter set, query or resolve ok, seconds, writer mode).
    Each example draws from its own subset of kinds (swarm testing), so rare mixes such as
    only 429s and flush ticks, or only hanging refusals, are explored too."""
    return st.lists(
        st.tuples(
            st.sampled_from(sorted(kinds)),
            st.sampled_from([0, 1, 1, 2]),
            st.sampled_from("AB"),
            st.booleans(),
            st.sampled_from([1, 60, 299, 300, 900, 3600]),
            st.sampled_from(["ok", "ok", "fail", "hang"]),
        ),
        min_size=30,  # without a floor most drawn lists are too short to interleave
        max_size=150,
    )


def _assert_bound(w: _Writer) -> None:
    """Per user and in any hour: at most the cap."""
    for a in _ACTORS:
        mine = [at for _, kw, at in w.records if kw["actor_user_id"] == a.user_id]
        for start in mine:
            assert len([at for at in mine if start <= at < start + 3600]) <= _CAPS[a.key]


@settings(max_examples=500)
@given(kinds=st.frozensets(st.sampled_from(_KINDS), min_size=2), data=st.data())
async def test_bounded_record_count_and_no_lost_count_under_any_interleaving(
    kinds: frozenset[str], data: st.DataObject
) -> None:
    ops = data.draw(_ops(kinds | {"read"}))
    clock = _Clock()
    w = _Writer(clock)
    b = AuditRecordBudget(
        per_hour=2, owner_per_hour=3, tracked_users=2, inflight_cap=2, flush_pages=3,
        flush_seconds=_WINDOW, write_timeout_s=0, clock=clock,
    )  # fmt: skip
    reads: list[tuple[BudgetActor, Any]] = []
    served = suppressed = unserved_recorded = 0

    async def finish(actor: BudgetActor, res: Any, ok: bool) -> int:
        try:
            if ok and res.action == "record":
                fields = {"actor_label": actor.label, "actor_user_id": actor.user_id}
                await b.write_read(res, w, fields, {})
            if ok:
                res.commit()
                return 1
        except BudgetWriteFailed:
            pass
        finally:
            res.release()
        return 0

    for kind, n, digest, ok, seconds, mode in ops:
        actor = _ACTORS[n]
        if kind in ("read", "start_read") and len(reads) < 4:
            res = b.plan_read(actor, digest)
            suppressed += res.action == "refuse"
            if res.action in ("count", "record"):
                if kind == "read":
                    served += await finish(actor, res, ok)
                else:
                    reads.append((actor, res))
        elif kind == "finish_read" and reads:
            served += await finish(*reads.pop(n % len(reads)), ok)
        elif kind == "refuse":
            fields = {"actor_label": actor.label, "actor_user_id": actor.user_id}
            with contextlib.suppress(BudgetWriteFailed):
                suppressed += not await b.write_denial(actor, w, fields)
        elif kind == "limit_429":
            b.count_suppressed(actor)
            suppressed += 1
        elif kind == "advance":
            clock.now += seconds
        elif kind == "writer":
            w.mode = mode
        elif kind == "resolve" and w.hanging:
            action = w.hanging[0][2]
            await w.resolve(ok)
            # A read record that timed out: its caller served nothing, yet it is recorded.
            unserved_recorded += ok and action == READ_ACTION

        _assert_bound(w)
        assert len(b) <= 2 and b.inflight <= 2
        users = b._users.values()
        hanging = [kw for _, _, _, kw in w.hanging]
        unserved_hanging = sum(1 for _, _, a, _ in w.hanging if a == READ_ACTION)
        pending = sum(u.pending_pages() for u in users)
        in_flight = sum(_carried_pages(kw) for kw in hanging)
        assert _recorded_pages(w) + pending + in_flight == (
            served + unserved_recorded + unserved_hanging
        )
        carried = sum((kw.get("after_state") or {}).get("suppressed", 0) for _, kw, _ in w.records)
        held = sum(u.suppressed for u in users) + b._untracked
        in_flight_s = sum((kw.get("after_state") or {}).get("suppressed", 0) for kw in hanging)
        assert carried + held + in_flight_s == suppressed
    while w.hanging:
        await w.resolve(True)
