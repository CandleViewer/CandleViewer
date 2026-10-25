"""Contract of a recorded stop's end (E29-T05 #848, S2d; 21 Sec.3.3.11 "Ends with its position"),
through `RecordedStopRepository`. A mixin beside `StoreReadsContract`, on its `h`, run on the
in-memory stores (`test_submission_fake.py`) and on Postgres
(`test_order_submission_contract_pg.py`), so the fake ends what Postgres ends (C-13.3). The caller
names the rows it ends, as it read them; the store compares and sets each, writes `status` and
`closed_at` only, and keeps the binding."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import pytest

from candleviewer.storage.repositories.recorded_stops import RecordedStopRow, StaleRecordedStop
from tests.unit.oms import submission_contract as sc
from tests.unit.oms.recorded_stop_contract import (
    ANSWERED,
    AT,
    AUDITED,
    FAILING,
    LATER,
    now_of,
    repo,
    request,
)
from tests.unit.oms.submission_contract import T0, Harness

#: An entry that filled and no longer rests: its rows are the "entry's row whose entry filled" of
#: 21, which wait no more (`WAITING["filled_then_cancelled"]`). One per account: the fill is fixed.
FILLED: Final = (*ANSWERED, sc.partial, sc.to("partially_filled", "cancelled"))
KEY: Final = ("BTCUSDT", 0)


class StopEndContract:
    async def test_end_closes_rows_in_force_and_answered_rows_and_writes_status_and_closed_at_only(
        self, h: Harness
    ) -> None:
        """A row in force ends `in_force`, an answered pending one `answered_unread` (its
        `in_force_at` stays NULL); nothing else changes, so both keep their times, marker and
        binding and the fills of a stop that closed its position still pair (R-5). The hook runs
        before the commit, where every reader still sees the rows live; a row not named stays."""
        account, _ = h.new_account()
        sl, tp = await h.stops.insert(
            [sc.trading_stop(account), sc.trading_stop(account, kind="take_profit")]
        )
        sl, tp = await h.stops.settle(account, [sl.id, tp.id], "answered", at=T0)
        await repo(h).put_in_force(account, [sl], at=AT)
        h.bind_stop(sl.id, "x-sl")
        h.bind_stop(tp.id, "x-tp")
        [flight] = await h.stops.insert([sc.trading_stop(account)])  # unanswered: never named
        live = await h.stops.live_for_key(account, *KEY)
        named = [r for r in live if r.id != flight.id]
        seen: list[tuple[tuple[RecordedStopRow, ...], tuple[RecordedStopRow, ...]]] = []

        async def audit(rows: tuple[RecordedStopRow, ...]) -> None:
            seen.append((rows, await h.stops.live_for_key(account, *KEY)))

        done = await repo(h).end(account, named, at=LATER, write_ahead=audit)
        assert done == tuple(replace(r, status="ended", closed_at=LATER) for r in named)
        ends = {r.kind: r.end for r in done}
        assert ends == {"stop_loss": "in_force", "take_profit": "answered_unread"}
        assert seen == [(done, live)]
        assert await h.stops.live_for_key(account, *KEY) == (flight,)
        ended = {r.kind: r for r in done}
        assert await h.stops.for_exchange_order(account, "x-sl") == (ended["stop_loss"],)
        assert await h.stops.for_exchange_order(account, "x-tp") == (ended["take_profit"],)

    async def test_end_refuses_a_row_the_guard_keeps_or_a_malformed_call_before_any_statement(
        self, h: Harness
    ) -> None:
        """`ValueError`, nothing written: no rows or one twice, an unanswered row (the guard keeps
        it pending), a row closed as read, rows of two keys, another account's, a naive `at`."""
        account, profile = h.new_account()
        rows = await request(h, account, profile, moves=FILLED)
        await repo(h).put_in_force(account, rows[:1], at=AT)
        sl, tp = await now_of(h, rows)
        [flight] = await h.stops.insert([sc.trading_stop(account)])
        before = (await now_of(h, rows), await h.stops.live_for_key(account, *KEY))
        refused: list[tuple[UUID, tuple[RecordedStopRow, ...], datetime, str]] = [
            (account, (), AT, "named once"),
            (account, (sl, sl), AT, "named once"),
            (account, (flight,), AT, "pending and answered"),
            (account, (replace(sl, status="replaced"),), AT, "pending and answered"),
            (account, (sl, replace(tp, position_idx=1)), AT, "of one key"),
            (uuid4(), (sl,), AT, "of one key"),
            (account, (sl,), LATER.replace(tzinfo=None), "timezone-aware"),
        ]
        for who, named, at, reason in refused:
            with pytest.raises(ValueError, match=reason):
                await repo(h).end(who, named, at=at)
        assert (await now_of(h, rows), await h.stops.live_for_key(account, *KEY)) == before

    @pytest.mark.parametrize(
        "moved",
        ["replaced", "in_force", "void", "ended", "another_account", "another_key", "forged"],
    )
    async def test_end_of_rows_moved_since_read_is_stale_and_writes_nothing(
        self, h: Harness, moved: str
    ) -> None:
        """SEC-BND-02: a row replaced, put in force, voided or ended since it was read, or read on
        another account or key, or read as answered when it is in flight (a forged `answered_at`:
        the guard would refuse it, so the compare must), is `StaleRecordedStop`, and its sibling,
        still as read, is not ended either. A put in force never revives a row an end closed."""
        account, profile = h.new_account()
        rows = await request(h, account, profile, moves=FILLED)
        await repo(h).put_in_force(account, rows[:1], at=AT)
        live = await h.stops.live_for_key(account, *KEY)  # the stop-loss in force, the take-profit
        who, named = account, live
        if moved == "replaced":  # a later request's stop-loss took its place
            later = await request(h, account, profile)
            await repo(h).put_in_force(account, later[:1], at=AT)
        elif moved == "in_force":
            await repo(h).put_in_force(account, rows[1:], at=AT)
        elif moved == "void":
            await repo(h).resolve(account, rows[1:], "in_flight_resolved", at=AT,
                                  write_ahead=AUDITED)  # fmt: skip
        elif moved == "ended":  # the replay of a committed end
            await repo(h).end(account, live, at=AT)
        elif moved == "another_account":
            who = uuid4()
            named = tuple(replace(r, exchange_account_id=who) for r in live)
        elif moved == "forged":  # a stop-loss still in flight, read as answered
            [flight] = await h.stops.insert([sc.trading_stop(account)])
            named = (replace(flight, answered_at=T0),)
        else:
            named = tuple(replace(r, symbol="ETHUSDT") for r in live)
        before = (await now_of(h, rows), await h.stops.live_for_key(account, *KEY))
        with pytest.raises(StaleRecordedStop):
            await repo(h).end(who, named, at=LATER)
        assert (await now_of(h, rows), await h.stops.live_for_key(account, *KEY)) == before
        if moved == "ended":
            with pytest.raises(StaleRecordedStop):
                await repo(h).put_in_force(account, rows[1:], at=LATER)

    @pytest.mark.parametrize("hook", sorted(FAILING))
    async def test_end_whose_hook_fails_or_is_late_leaves_every_row_as_it_was(
        self, h: Harness, hook: str
    ) -> None:
        """`AuditNotDurable` past the bound: both rows keep the status they were read with."""
        account, profile = h.new_account()
        rows = await request(h, account, profile, moves=FILLED)
        await repo(h).put_in_force(account, rows[:1], at=AT)
        before, (audit, raised) = await now_of(h, rows), FAILING[hook]
        with pytest.raises(raised):
            await repo(h, 0.05).end(account, before, at=LATER, write_ahead=audit)
        assert await now_of(h, rows) == before
