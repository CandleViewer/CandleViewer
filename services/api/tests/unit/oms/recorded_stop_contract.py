"""What slice 3's complete read writes to the recorded stops (E29-T04 #913, S3-H; 21 Sec.3.3.11),
through `RecordedStopRepository`, on the fakes (`test_submission_fake.py`) and on Postgres
(`test_recorded_stop_resolution_pg.py`): `h` is the submission contract's harness."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import timedelta
from typing import Any, Final, Literal
from uuid import UUID, uuid4

import pytest

from candleviewer.oms.errors import AuditNotDurable
from candleviewer.oms.repository import RecordedStopRepository
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.recorded_stops import (
    FillPosition,
    RecordedStopRow,
    ResolveWriteAhead,
    StaleRecordedStop,
)
from tests.unit.oms import submission_contract as sc
from tests.unit.oms.submission_contract import T0, Harness

AT, LATER = T0 + timedelta(hours=1), T0 + timedelta(hours=2)
FAILING: Final[dict[str, tuple[Callable[[object], Awaitable[None]], type[Exception]]]] = {
    "refuses": (sc.refuses, RuntimeError),
    "hangs": (sc.hangs, AuditNotDurable),
    "unreachable": (sc.unreachable, StorageTierUnavailable),
}
ABSENT: Final = "entry_filled_stop_absent"
_Rows = tuple[RecordedStopRow, ...]
#: What a resolve's hook saw: the rows it was given, the rows as stored then, its position_state.
_Seen = tuple[_Rows, _Rows, FillPosition | None]
Outcome = Literal["answered", "replaced", "in_flight_resolved", "entry_filled_stop_absent"]
ANSWERED: Final = (sc.SEND, sc.ACK)
HELD: Final = (*ANSWERED, sc.to("submitted", "held"))  # the complete read resolves its rows


def resolving(hook: Callable[[object], Awaitable[None]]) -> ResolveWriteAhead:
    """`hook` as a resolve's write-ahead, which is also given the void's `position_state`."""

    async def write(rows: tuple[RecordedStopRow, ...], state: FillPosition | None) -> None:
        await hook(rows)

    return write


AUDITED: Final = resolving(sc.audited)


def repo(h: Harness, seconds: float | None = None) -> RecordedStopRepository:
    return RecordedStopRepository(h.stops if seconds is None else h.bounded(seconds).stops)


async def request(
    h: Harness, account: UUID, profile: UUID, *, answered: bool = True, moves: Any = ANSWERED
) -> tuple[RecordedStopRow, ...]:
    """An entry's stop-loss, then take-profit, rows on BTCUSDT 0: answered, or in flight."""
    first, order = sc.entry(h.new_user(), account, profile, take_profit=sc.TP)
    await h.submissions.create_first(first, order, sc.EVENT)
    for move in moves if answered else ():
        await move(h, order)
    return tuple(sorted(await h.stops.for_order(account, order.id), key=lambda r: r.kind))


async def now_of(h: Harness, rows: tuple[RecordedStopRow, ...]) -> tuple[RecordedStopRow, ...]:
    held: dict[UUID, RecordedStopRow] = {}
    for row in rows:
        assert row.order_id is not None
        held |= {r.id: r for r in await h.stops.for_order(row.exchange_account_id, row.order_id)}
    return tuple(held[row.id] for row in rows)


def shape(rows: tuple[RecordedStopRow, ...]) -> list[tuple[Any, ...]]:
    return [(r.status, r.answered_at, r.in_force_at, r.closed_at) for r in rows]


class RecordedStopContract:
    async def test_put_in_force_replaces_first_the_row_in_force_and_older_answered_rows(
        self, h: Harness
    ) -> None:
        """A shown row goes in force, answered at the read if in flight. Of its kind only, the row
        in force (keeping `in_force_at`) and older answered rows go `replaced` first; a younger row
        and the other kind's rows stay."""
        account, profile = h.new_account()
        old = await request(h, account, profile, answered=False)
        await repo(h).put_in_force(account, old, at=AT)
        mid, new, young = [await request(h, account, profile) for _ in range(3)]
        done = await repo(h).put_in_force(account, new[:1], at=LATER, write_ahead=sc.audited)
        assert {r.id for r in done.replaced} == {old[0].id, mid[0].id}
        shown = await repo(h).in_force_for_key(account, "BTCUSDT", 0)  # by kind, of the account
        assert [r.id for r in shown] == [new[0].id, old[1].id]
        assert await repo(h).in_force_for_key(h.new_account()[0], "BTCUSDT", 0) == ()
        assert shape(await now_of(h, (*old, mid[1], *new, *young))) == [
            ("replaced", AT, AT, LATER), ("in_force", AT, AT, None), ("pending", T0, None, None),
            ("in_force", T0, LATER, None), ("pending", T0, None, None),
            ("pending", T0, None, None), ("pending", T0, None, None),
        ]  # fmt: skip

    async def test_two_reads_racing_on_one_key_leave_one_row_in_force(self, h: Harness) -> None:
        """The key lock (id order) serialises them: the second replaces the first's row or finds
        its own replaced (`StaleRecordedStop`); `ux_rs_in_force` is never met."""
        account, profile = h.new_account()
        older, newer = await request(h, account, profile), await request(h, account, profile)
        calls = (repo(h).put_in_force(account, rows[:1], at=AT) for rows in (older, newer))
        got = await asyncio.gather(*calls, return_exceptions=True)
        assert all(not isinstance(r, Exception) or isinstance(r, StaleRecordedStop) for r in got)
        statuses = sorted(r.status for r in await now_of(h, (older[0], newer[0])))
        assert statuses == ["in_force", "replaced"]

    async def test_a_lost_compare_and_set_writes_nothing(self, h: Harness) -> None:
        """SEC-BND-02: a late answer (`settle`) and a resolution never both win: a row answered or
        put in force since it was read, or another account's, is `StaleRecordedStop`."""
        account, profile = h.new_account()
        rows = await request(h, account, profile, answered=False)
        await h.stops.settle(account, [rows[0].id], "answered", at=AT)
        before = await now_of(h, rows)
        with pytest.raises(StaleRecordedStop):
            await repo(h).put_in_force(account, rows[:1], at=LATER)
        for writer in (account, uuid4()):
            with pytest.raises(StaleRecordedStop):
                await repo(h).resolve(writer, rows, "in_flight_resolved", at=LATER,
                                      write_ahead=AUDITED)  # fmt: skip
        assert await now_of(h, rows) == before
        await repo(h).put_in_force(account, before[1:], at=LATER)
        with pytest.raises(StaleRecordedStop):
            await h.stops.settle(account, [rows[1].id], "answered", at=LATER)

    @pytest.mark.parametrize("hook", sorted(FAILING))
    async def test_a_hook_that_fails_leaves_every_row_as_it_was(
        self, h: Harness, hook: str
    ) -> None:
        """`AuditNotDurable` past the bound: nothing is put in force, replaced or voided."""
        account, profile = h.new_account()
        prior = await request(h, account, profile)
        await repo(h).put_in_force(account, prior, at=AT)
        rows = await request(h, account, profile, answered=False)
        before, (audit, raised) = await now_of(h, (*prior, *rows)), FAILING[hook]
        with pytest.raises(raised):
            await repo(h, 0.05).put_in_force(account, rows, at=LATER, write_ahead=audit)
        with pytest.raises(raised):
            await repo(h, 0.05).resolve(account, rows, "in_flight_resolved", at=LATER,
                                        write_ahead=resolving(audit))  # fmt: skip
        assert await now_of(h, (*prior, *rows)) == before

    @pytest.mark.parametrize("outcome", ["answered", "replaced", "in_flight_resolved", ABSENT])
    @pytest.mark.parametrize("answered", [False, True])
    async def test_a_resolve_answers_replaces_or_voids_whatever_answered_at(
        self, h: Harness, outcome: Outcome, answered: bool
    ) -> None:
        """Audited before the commit, when hooked (inside the hook every reader still sees the rows
        as they were; a void needs it); `position_state` is required for the
        `entry_filled_stop_absent` void (CR-S3H0-08), optional for `in_flight_resolved` (the 06:38Z
        ruling: an unseen entry's void on a position with no stop carries it) and refused for an
        answer or a replace; the hook is given it; an answer, and a replace, stamp only a NULL
        `answered_at`."""
        account, profile = h.new_account()
        rows = await request(h, account, profile, answered=answered)
        seen: list[_Seen] = []

        async def audit(done: tuple[RecordedStopRow, ...], given: FillPosition | None) -> None:
            seen.append((done, await now_of(h, rows), given))

        states: dict[str, FillPosition | None] = {ABSENT: "flat", "in_flight_resolved": "open"}
        state = states.get(outcome)
        wrong: FillPosition | None = None if outcome == ABSENT else "open"
        for writer in (repo(h), h.stops):  # refused before anything, by the facade and the store
            if outcome != "in_flight_resolved":  # optional there: either is accepted
                with pytest.raises(ValueError, match="position_state"):
                    await writer.resolve(account, rows, outcome, at=AT, position_state=wrong,
                                         write_ahead=audit)  # fmt: skip
            if outcome in ("in_flight_resolved", ABSENT):  # C-2.9: no void unaudited
                with pytest.raises(ValueError, match="audited write-ahead"):
                    await writer.resolve(account, rows, outcome, at=AT, position_state=state)
        done = await repo(h).resolve(account, rows, outcome, at=AT, position_state=state,
                                     write_ahead=audit)  # fmt: skip
        assert seen == [(done, rows, state)] and await now_of(h, rows) == done
        stamp = T0 if answered else (None if outcome in ("in_flight_resolved", ABSENT) else AT)
        status = {"answered": "pending", "replaced": "replaced"}.get(outcome, "void")
        assert shape(done) == [(status, stamp, None, None if status == "pending" else AT)] * 2

    async def test_a_row_read_on_another_key_is_stale_and_writes_nothing(self, h: Harness) -> None:
        """The compare-and-set holds each row on its key as read too (symbol and index), so a
        caller's row of another key never moves a stored one, nor picks the key to replace."""
        account, profile = h.new_account()
        rows = await request(h, account, profile)
        before = await now_of(h, rows)
        for moved in ({"symbol": "ETHUSDT"}, {"position_idx": 1}):
            other = tuple(replace(r, **moved) for r in rows)
            with pytest.raises(StaleRecordedStop):
                await repo(h).put_in_force(account, other[:1], at=AT)
            with pytest.raises(StaleRecordedStop):
                await repo(h).resolve(account, other, "in_flight_resolved", at=AT,
                                      write_ahead=AUDITED)  # fmt: skip
            with pytest.raises(StaleRecordedStop):
                await repo(h).resolve(account, other, "answered", at=AT)
        assert await now_of(h, rows) == before

    async def test_the_waiting_keys_are_the_keys_waiting_for_key_lists(self, h: Harness) -> None:
        """Oldest row's key first; never a row inside its bound, an answered one, or another
        account's."""
        account, profile = h.new_account()
        [eth] = await h.stops.insert([sc.trading_stop(account, symbol="ETHUSDT", position_idx=2)])
        await request(h, account, profile, moves=HELD)
        [sol] = await h.stops.insert([sc.trading_stop(account, symbol="SOLUSDT")])
        await repo(h).resolve(account, [sol], "answered", at=AT)
        await h.stops.insert([sc.trading_stop(h.new_account()[0])])
        keys = await repo(h).waiting_keys(account, now=sc.LATE, bound_s=5.0)
        assert keys == (("ETHUSDT", 2), ("BTCUSDT", 0))
        inside = await repo(h).waiting_keys(account, now=eth.created_at, bound_s=5.0)
        assert inside == (("BTCUSDT", 0),)

    @pytest.mark.parametrize(
        "ends",
        [("in_force", "in_force"), ("in_force", ABSENT), (ABSENT, ABSENT), ("replaced", ABSENT)],
    )
    async def test_a_filled_entrys_rows_end_on_the_row_each_side_on_its_own(
        self, h: Harness, ends: tuple[str, str]
    ) -> None:
        """Q1, CR-S3H0-02: each held side ends on the row on its own, no memo: in force, replaced by
        a later row of its kind, or void `entry_filled_stop_absent`; the key waits no more."""
        account, profile = h.new_account()
        held = await request(h, account, profile, moves=HELD)
        if ends[0] == "replaced":
            [later] = await h.stops.insert([sc.trading_stop(account)])
            [later] = await repo(h).resolve(account, [later], "answered", at=AT)
            done = await repo(h).put_in_force(account, [later], at=LATER)
            assert [r.id for r in done.replaced] == [held[0].id]
        for side, end in zip(held, ends, strict=True):
            if end == "in_force":
                await repo(h).put_in_force(account, [side], at=AT)
            elif end == ABSENT:
                await repo(h).resolve(account, [side], ABSENT, at=AT, position_state="open",
                                      write_ahead=AUDITED)  # fmt: skip
        statuses = [{ABSENT: "void"}.get(end, end) for end in ends]
        assert [r.status for r in await now_of(h, held)] == statuses
        assert await repo(h).waiting_keys(account, now=sc.LATE, bound_s=5.0) == ()
