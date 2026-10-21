"""#3085: the in-memory `ViewAsSessionStore` honours the contract the Postgres store will: each
write is one conditional write of the row, so of two racing writers exactly one applies."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from candleviewer.auth.view_as import ViewAsEndReason, ViewAsSessionStore, ViewAsState

from .session_fakes import FakeSessionRepository
from .test_step_up import _T0, _session

_VIEWER, _TARGET = UUID(int=1), UUID(int=2)
_GRACE, _US, _T20 = timedelta(minutes=1), timedelta(microseconds=1), _T0 + timedelta(minutes=20)
_BY_VIEWER, _BY_SWEEPER = ViewAsEndReason.ENDED, ViewAsEndReason.SESSION_ENDED


def _at(minutes: int) -> datetime:
    return _T0 + timedelta(minutes=minutes)


def _fresh(start: int = 0, target: UUID = _TARGET) -> ViewAsState:
    return ViewAsState.start(uuid4(), target, now=_at(start))


def _held(repo: FakeSessionRepository, sid: str) -> ViewAsState:
    held = repo.sessions[sid].view_as
    assert held is not None
    return held


async def _due(repo: FakeSessionRepository, now: datetime, limit: int = 9) -> list[str]:
    rows = await repo.list_view_as_due(now=now, rotated_grace=_GRACE, limit=limit)
    return [str(row.id) for row in rows]


async def _row(repo: FakeSessionRepository, steps: str = "s", at: int = 0, **changes: Any) -> str:
    """A viewer row (with `changes`) after `steps`, each applying: s start at `at`, r refresh (the
    row revoked `rotated`, the context carried to a new row the rest act on), e end, c clear, m mark
    recorded, R revoke."""
    record = _session(_VIEWER).model_copy(update=changes)
    assert await repo.create_session(record) is not None
    sid = str(record.id)
    if "s" in steps:
        assert await repo.start_view_as(sid, _fresh(at), now=_at(at)) is not None
    if "r" in steps:
        assert await repo.revoke(sid, reason="rotated", now=_at(at + 1)) is not None
        sid = await _row(repo, "", view_as=_held(repo, sid))
    if "e" in steps:
        held = _held(repo, sid)
        ended_at, reason = held.end_at(now=_at(10), reason=_BY_VIEWER)
        assert await repo.end_view_as(sid, held.context_id, ended_at=ended_at, reason=reason)
    if "c" in steps:
        assert await repo.clear_view_as(sid, _held(repo, sid).context_id, now=_at(11))
    if "m" in steps:
        assert await repo.mark_view_as_recorded(sid, _held(repo, sid).context_id, now=_at(12))
    if "R" in steps:
        assert await repo.revoke(sid, reason="logout", now=_at(13)) is not None
    return sid


async def _arrange(repo: FakeSessionRepository, steps: str) -> tuple[str, UUID]:
    """`_row`'s row and its context id; X an absolute-expired row, F a foreign id, ? no row."""
    if "?" in steps:
        return str(uuid4()), uuid4()
    expired: dict[str, Any] = {"expires_at": _T0} if "X" in steps else {}
    sid = await _row(repo, steps, **expired)
    held = repo.sessions[sid].view_as
    return sid, uuid4() if held is None or "F" in steps else held.context_id


_WRITES: dict[str, Callable[[FakeSessionRepository, str, UUID], Awaitable[object]]] = {
    "start": lambda r, s, c: r.start_view_as(s, _fresh(40), now=_at(40)),
    "end": lambda r, s, c: r.end_view_as(s, c, ended_at=_T20, reason=_BY_SWEEPER),
    "clear": lambda r, s, c: r.clear_view_as(s, c, now=_T20),
    "mark": lambda r, s, c: r.mark_view_as_recorded(s, c, now=_T20),
    "leave": lambda r, s, c: r.leave_view_as(s, c, ended_at=_T20, reason=_BY_VIEWER, now=_T20),
}
#: write -> (rows its condition holds on, rows it does not), as `_arrange`'s steps (n: none)
_CONDITIONS = {
    "start": ("secm", "s se sem sec R X ?"),
    "end": ("s sR", "se sF ?"),
    "clear": ("se", "s sec seF ?"),
    "mark": ("se sec", "s sem seF ?"),
    "leave": ("s se", "sec n sF ?"),
}
_CASES = [
    (write, steps, holds)
    for write, rows in _CONDITIONS.items()
    for holds, group in zip((True, False), rows, strict=True)
    for steps in group.split()
]


@pytest.mark.parametrize(("write", "steps", "holds"), _CASES)  # pytest's ids: write-steps-holds
async def test_a_write_applies_exactly_when_its_condition_holds(
    write: str, steps: str, holds: bool
) -> None:
    repo = FakeSessionRepository()
    sid, cid = await _arrange(repo, steps)
    before = dict(repo.sessions)
    result = await _WRITES[write](repo, sid, cid)
    assert (result is not None, repo.sessions != before) == (holds, holds)


async def test_two_starts_one_wins() -> None:
    repo = FakeSessionRepository()
    store: ViewAsSessionStore = repo  # mypy pins the fake to the store contract
    sid = await _row(repo, "")
    reads = await asyncio.gather(repo.find_by_id(sid), repo.find_by_id(sid))
    assert all(r is not None and r.view_as is None for r in reads)  # both read "no context"
    one, two = _fresh(), _fresh()
    results = await asyncio.gather(*(store.start_view_as(sid, x, now=_T0) for x in (one, two)))
    winners = [r.view_as for r in results if r is not None]
    assert len(winners) == 1 and winners[0] in (one, two) and _held(repo, sid) == winners[0]


_ENDED_STATE = _fresh().model_copy(update={"ended_at": _at(5), "end_reason": "ended"})
_SELF_TARGET = _fresh(target=_VIEWER)


@pytest.mark.parametrize(("state", "error"), [(_ENDED_STATE, "fresh"), (_SELF_TARGET, "own user")])
async def test_start_raises_on_a_state_the_row_cannot_take(state: ViewAsState, error: str) -> None:
    repo = FakeSessionRepository()
    sid = await _row(repo, "")
    with pytest.raises(ValueError, match=error):
        await repo.start_view_as(sid, state, now=_T0)
    assert repo.sessions[sid].view_as is None


async def test_end_applies_exactly_once() -> None:
    repo = FakeSessionRepository()
    sid, cid = await _arrange(repo, "s")
    ends = (repo.end_view_as(sid, cid, ended_at=_T20, reason=r) for r in (_BY_VIEWER, _BY_SWEEPER))
    results = await asyncio.gather(*ends)
    winners = [r.view_as for r in results if r is not None]
    assert len(winners) == 1 and _held(repo, sid) == winners[0]


async def test_clear_never_drops_pending_end() -> None:
    repo = FakeSessionRepository()
    sid, cid = await _arrange(repo, "se")  # its record could not be written: pending
    assert await repo.clear_view_as(sid, cid, now=_at(11)) is not None
    cleared = _held(repo, sid)
    assert (cleared.ended_at, cleared.end_reason, cleared.end_pending) == (_at(10), "ended", True)
    assert await _due(repo, _at(11)) == [sid]
    assert await repo.mark_view_as_recorded(sid, cid, now=_at(12)) is not None
    assert await _due(repo, _at(12)) == []


@pytest.mark.parametrize(("steps", "ends_here", "end_min"), [("s", True, 20), ("se", False, 10)])
async def test_leave_clears_in_the_one_write_that_ends_a_live_context(
    steps: str, ends_here: bool, end_min: int
) -> None:
    repo = FakeSessionRepository()
    sid, cid = await _arrange(repo, steps)
    left = await repo.leave_view_as(sid, cid, ended_at=_at(20), reason=_BY_VIEWER, now=_at(21))
    held = _held(repo, sid)
    assert left == (repo.sessions[sid], ends_here)
    assert (held.ended_at, held.cleared_at, held.end_pending) == (_at(end_min), _at(21), True)


async def test_list_view_as_due_lists_unrecorded_ends_earliest_expiry_first() -> None:
    repo, now = FakeSessionRepository(), _at(40)
    ended = await _row(repo, "se", 30)  # expires at +60, ended, not recorded
    absolute = await _row(repo, "s", 25, expires_at=now)  # in time on an absolute-expired row
    await _row(repo, "s", 15)  # live and in time: not due
    revoked = await _row(repo, "sR", 20)  # in time (expires at +50) on a revoked row
    past_expiry = await _row(repo, "s", -10)  # expired at +20
    await _row(repo, "sem")  # expired at +30, but its end is recorded
    await _row(repo, "")  # no context
    due = await _due(repo, now)
    assert due == [past_expiry, revoked, absolute, ended]
    assert await _due(repo, now, limit=2) == due[:2]


async def test_a_rotated_row_is_due_only_once_every_copy_of_its_context_is_past_the_grace() -> None:
    """Carried copies never clog the head of the list; an orphan (a refresh that never inserted
    its successor) is due, `session_ended`, once the grace is over, and so is its whole chain."""
    repo = FakeSessionRepository()
    for start in (-50, -45, -40):  # finished contexts, each carried to a successor by a refresh
        await _row(repo, "srem", start)
    await _row(repo, "sr", -20)  # live on its successor until +10
    expired = await _row(repo, "s", -35)  # expired at -5, after every carried copy's expiry
    assert await _due(repo, _T0, limit=1) == [expired]
    second = await _row(repo, "sr", 0)  # refreshed at +1; the next refresh fails at +24:
    assert await repo.revoke(second, reason="rotated", now=_at(24)) is not None
    chain = {sid for sid, row in repo.sessions.items() if row.view_as == _held(repo, second)}
    assert chain.isdisjoint(await _due(repo, _at(25) - _US))  # the second's grace covers both
    assert chain <= set(await _due(repo, _at(25)))


async def test_live_lists_hold_unended_contexts_on_unrevoked_rows_earliest_expiry_first() -> None:
    repo = FakeSessionRepository()
    late, held = await _row(repo, "s", 10), await _row(repo, "s", -40)  # held by the clock
    for steps in ("se", "sR", ""):  # ended, revoked, none
        await _row(repo, steps)
    other = await _row(repo, "", view_as=_fresh(0, UUID(int=7)))  # another target
    live = [str(r.id) for r in await repo.list_live_view_as(limit=9)]
    assert live == [held, other, late]
    assert [str(r.id) for r in await repo.list_live_view_as(limit=2)] == live[:2]
    by_target = await repo.list_live_view_as_by_target(_TARGET)
    assert sorted(str(r.id) for r in by_target) == sorted([late, held])  # phases are the caller's
