"""Contract of what slice 3's complete read writes to the recorded stops (E29-T04 #913, S3-H;
21 Sec.3.3.11): `put_in_force`, `resolve` and `waiting_keys` through `RecordedStopRepository`.
Run on the in-memory stores (`test_submission_fake.py`) and on Postgres
(`tests/integration/storage/test_recorded_stop_resolution_pg.py`); both supply `h`, the submission
contract's harness, on a clock that moves between writes. Every case uses accounts of its own."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import pytest

from candleviewer.oms.errors import AuditNotDurable
from candleviewer.oms.repository import RecordedStopRepository
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow, StaleRecordedStop
from tests.unit.oms import submission_contract as sc
from tests.unit.oms.submission_contract import T0, Harness

AT, LATER = T0 + timedelta(hours=1), T0 + timedelta(hours=2)
FAILING: Final[dict[str, tuple[Callable[[object], Awaitable[None]], type[Exception]]]] = {
    "refuses": (sc.refuses, RuntimeError),
    "hangs": (sc.hangs, AuditNotDurable),
    "unreachable": (sc.unreachable, StorageTierUnavailable),
}
ANSWERED: Final = (sc.SEND, sc.ACK)
HELD: Final = (*ANSWERED, sc.to("submitted", "held"))  # the complete read resolves its rows


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
        in force (keeping `in_force_at`) and older answered rows go `replaced` first, in the
        hook's rows too; a younger row and the other kind's rows stay."""
        account, profile = h.new_account()
        old = await request(h, account, profile, answered=False)
        await repo(h).put_in_force(account, old, at=AT)
        mid, new, young = [await request(h, account, profile) for _ in range(3)]
        seen: list[list[UUID]] = []

        async def audit(rows: tuple[RecordedStopRow, ...]) -> None:
            seen.append([row.id for row in rows])

        done = await repo(h).put_in_force(account, new[:1], at=LATER, write_ahead=audit)
        assert seen == [[r.id for r in (*done.replaced, *done.in_force)]]
        assert {r.id for r in done.replaced} == {old[0].id, mid[0].id}
        assert shape(await now_of(h, (*old, mid[1], *new, *young))) == [
            ("replaced", AT, AT, LATER), ("in_force", AT, AT, None), ("pending", T0, None, None),
            ("in_force", T0, LATER, None), ("pending", T0, None, None),
            ("pending", T0, None, None), ("pending", T0, None, None),
        ]  # fmt: skip

    async def test_a_lost_compare_and_set_writes_nothing(self, h: Harness) -> None:
        """A row answered or put in force since it was read, or another account's, is
        `StaleRecordedStop`, and no row of the request moves."""
        account, profile = h.new_account()
        rows = await request(h, account, profile, answered=False)
        await repo(h).resolve(account, rows[:1], "answered", at=AT)
        before = await now_of(h, rows)
        with pytest.raises(StaleRecordedStop):
            await repo(h).put_in_force(account, rows[:1], at=LATER)
        for writer in (account, uuid4()):
            with pytest.raises(StaleRecordedStop):
                await repo(h).resolve(writer, rows, "in_flight_resolved", at=LATER,
                                      write_ahead=sc.audited)  # fmt: skip
        assert await now_of(h, rows) == before
        await repo(h).put_in_force(account, before[:1], at=LATER)
        with pytest.raises(StaleRecordedStop):
            await repo(h).resolve(account, before, "answered", at=LATER)

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
                                        write_ahead=audit)  # fmt: skip
        assert await now_of(h, (*prior, *rows)) == before

    @pytest.mark.parametrize("outcome", ["answered", "in_flight_resolved",
                                         "entry_filled_stop_absent"])  # fmt: skip
    @pytest.mark.parametrize("answered", [False, True])
    async def test_a_resolve_answers_or_voids_whatever_answered_at(
        self, h: Harness, outcome: Any, answered: bool
    ) -> None:
        """Audited before the commit (inside the hook every reader still sees the rows as they
        were); an answer stamps only a NULL `answered_at`."""
        account, profile = h.new_account()
        rows = await request(h, account, profile, answered=answered)
        seen: list[tuple[tuple[RecordedStopRow, ...], tuple[RecordedStopRow, ...]]] = []

        async def audit(done: tuple[RecordedStopRow, ...]) -> None:
            seen.append((done, await now_of(h, rows)))

        if outcome != "answered":  # C-2.9: neither the facade nor the store voids unaudited
            for writer in (repo(h), h.stops):
                with pytest.raises(ValueError, match="audited write-ahead"):
                    await writer.resolve(account, rows, outcome, at=AT)
        done = await repo(h).resolve(account, rows, outcome, at=AT, write_ahead=audit)
        assert seen == [(done, rows)] and await now_of(h, rows) == done
        stamp = T0 if answered else (AT if outcome == "answered" else None)
        voided = outcome != "answered"
        assert (
            shape(done)
            == [("void" if voided else "pending", stamp, None, AT if voided else None)] * 2
        )

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
        with pytest.raises(ValueError, match="timezone-aware"):
            await repo(h).waiting_keys(account, now=sc.LATE.replace(tzinfo=None), bound_s=5.0)

    @pytest.mark.parametrize("end", ["in_force", "entry_filled_stop_absent", "replaced"])
    async def test_a_filled_entrys_rows_end_on_the_row_and_free_the_key(
        self, h: Harness, end: str
    ) -> None:
        """Q1: the held rows end durably, with no memo: in force, replaced by a later row of the
        kind, or void with reason `entry_filled_stop_absent`; the key waits no more."""
        account, profile = h.new_account()
        held = await request(h, account, profile, moves=HELD)
        absent = "entry_filled_stop_absent"
        if end == "replaced":
            [later] = await h.stops.insert([sc.trading_stop(account)])
            [later] = await repo(h).resolve(account, [later], "answered", at=AT)
            done = await repo(h).put_in_force(account, [later], at=LATER)
            assert [r.id for r in done.replaced] == [held[0].id]
            await repo(h).resolve(account, held[1:], absent, at=LATER, write_ahead=sc.audited)
        elif end == "in_force":
            await repo(h).put_in_force(account, held, at=AT)
        else:
            await repo(h).resolve(account, held, absent, at=AT, write_ahead=sc.audited)
        [first, _] = await now_of(h, held)
        assert first.status == {absent: "void"}.get(end, end)
        assert await repo(h).waiting_keys(account, now=sc.LATE, bound_s=5.0) == ()
