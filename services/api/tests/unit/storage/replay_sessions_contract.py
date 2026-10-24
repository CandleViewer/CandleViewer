"""Behavioural contract of `ReplaySessionRepository` (E26-T01 slice 2/3).

One suite, two subjects: `test_replay_sessions_repository.py` runs it against the in-memory fake and
`tests/integration/storage/test_replay_sessions_repository_pg.py` against Postgres, so the fake the
slice-3 service tests rely on cannot drift from the real adapter. Time only moves when the test
advances the shared `FakeClock`: no sleeps, no wall clock (C-13.7). Not collected itself (no `test_`
module prefix, no `Test` class prefix); subclasses supply the `h` fixture.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

import pytest

from candleviewer.storage.repositories.recorded import REPLAYABLE_STREAMS
from candleviewer.storage.repositories.replay_sessions import (
    COVERING_STATES,
    LIVE_STATES,
    IdleReplaySession,
    ReplaySessionConstraintError,
    ReplaySessionCreate,
    ReplaySessionCursorError,
    ReplaySessionIllegalUpdateError,
    ReplaySessionNotFoundError,
    ReplaySessionRepository,
    ReplaySessionRow,
    ReplayState,
    SourceTier,
)
from tests.unit.storage.fakes_replay_sessions import FakeClock

S = ReplayState
T0 = FakeClock().now
T2H = T0 + timedelta(hours=2)
_US = timedelta(microseconds=1)
_ALL_STREAMS = tuple(s.value for s in REPLAYABLE_STREAMS)
_SOME_UUID = "00000000-0000-4000-8000-000000000001"  # literal: parametrize ids must be stable


def _cursor(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


@dataclass(frozen=True)
class Harness:
    repo: ReplaySessionRepository
    clock: FakeClock
    new_user: Callable[[], str]
    new_account: Callable[[], str]
    new_recording: Callable[[], str]

    async def make(self, user: str | None = None, **over: Any) -> ReplaySessionRow:
        fields: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "user_id": user or self.new_user(),
            "symbol": "BTCUSDT",
            "range_start": T0,
            "range_end": T2H,
        } | over
        return await self.repo.create(ReplaySessionCreate(**fields))

    async def in_state(
        self, state: ReplayState, user: str | None = None, **over: Any
    ) -> ReplaySessionRow:
        """A session of `user` moved straight to `state` (legality is the B12 machine's call)."""
        row = await self.make(user, **over)
        return await self.repo.update_state(row.user_id, row.id, state=state)


def _writes(h: Harness, uid: str, sid: str) -> dict[str, Callable[[], Awaitable[object]]]:
    repo = h.repo
    return {
        "update_state": lambda: repo.update_state(uid, sid, state=S.PLAYING),
        "update_cursor": lambda: repo.update_cursor(uid, sid, cursor_ts=T0 + timedelta(hours=1)),
        "update_speed": lambda: repo.update_speed(uid, sid, speed=Decimal(2)),
        "touch": lambda: repo.touch(uid, sid, h.clock.now),
    }


class ReplaySessionRepositoryContract:
    async def test_create_then_get_round_trips_every_column(self, h: Harness) -> None:
        user, acct = h.new_user(), h.new_account()
        mark = ({"ts": "2026-10-01T00:30:00+00:00", "label": "gap", "note": None},)
        made = await h.make(
            user, recording_session_id=h.new_recording(), cursor_ts=T0 + timedelta(hours=1),
            speed=Decimal("2.5"), source_tier=SourceTier.PARQUET, paper_trading=True,
            paper_account_id=acct, bookmarks=mark, loop_enabled=True,
        )  # fmt: skip
        assert (made.state, made.created_at, made.updated_at) == (S.CREATED, T0, T0)
        assert (made.events_emitted, made.gap_warnings, made.finished_at) == (0, 0, None)
        assert (made.speed, made.bookmarks, made.paper_account_id) == (Decimal("2.5"), mark, acct)
        assert (made.symbols, made.streams) == (("BTCUSDT",), _ALL_STREAMS)
        assert await h.repo.get(user, made.id) == made

    async def test_create_persists_every_symbol_and_stream_of_the_request(self, h: Harness) -> None:
        made = await h.make(symbols=("BTCUSDT", "ETHUSDT"), streams=("klines", "trades"))
        assert (made.symbol, made.symbols, made.streams) == (
            "BTCUSDT", ("BTCUSDT", "ETHUSDT"), ("klines", "trades"),
        )  # fmt: skip
        assert await h.repo.get(made.user_id, made.id) == made

    async def test_stored_bookmarks_do_not_alias_the_callers_objects(self, h: Harness) -> None:
        mark = {"ts": "2026-10-01T00:30:00+00:00", "label": "gap", "note": None}
        made = await h.make(bookmarks=(mark,))
        mark["label"] = "changed after create"
        got = await h.repo.get(made.user_id, made.id)
        assert got is not None and got.bookmarks[0]["label"] == "gap"

    async def test_another_users_session_is_invisible_to_every_method(self, h: Harness) -> None:
        mine, stranger = await h.in_state(S.PAUSED), h.new_user()
        assert await h.repo.get(stranger, mine.id) is None
        assert (await h.repo.list_page(stranger)).rows == ()
        assert await h.repo.count_active(stranger) == 0
        assert await h.repo.count_non_terminal(stranger) == 0
        assert await h.repo.delete(stranger, mine.id) is False
        for call in _writes(h, stranger, mine.id).values():
            with pytest.raises(ReplaySessionNotFoundError):
                await call()
        assert await h.repo.get(mine.user_id, mine.id) == mine

    async def test_malformed_and_unknown_ids_are_not_found_not_errors(self, h: Harness) -> None:
        user = h.new_user()
        for bad in ("not-a-uuid", "", str(uuid.uuid4())):
            assert await h.repo.get(user, bad) is None
            assert await h.repo.delete(user, bad) is False
            with pytest.raises(ReplaySessionNotFoundError):
                await h.repo.touch(user, bad, T0)
        assert await h.repo.get("not-a-uuid", str(uuid.uuid4())) is None

    async def test_not_found_never_echoes_the_callers_id_string(self, h: Harness) -> None:
        hostile = "<script>alert(1)</script>\r\nX-Injected: 1"
        unknown = str(uuid.uuid4())
        user = h.new_user()
        for sid, allowed in ((hostile, {""}), (unknown, {"", unknown})):
            for call in _writes(h, user, sid).values():
                with pytest.raises(ReplaySessionNotFoundError) as err:
                    await call()
                assert str(err.value) in allowed

    async def test_create_with_a_used_id_names_the_primary_key(self, h: Harness) -> None:
        row = await h.make()
        with pytest.raises(ReplaySessionConstraintError) as err:
            await h.make(row.user_id, id=row.id)
        assert err.value.constraint == "replay_sessions_pkey"

    # -- list_page -------------------------------------------------------------------------------

    async def test_list_page_pages_newest_first_without_gaps_or_repeats(self, h: Harness) -> None:
        user, made = h.new_user(), []
        for _ in range(7):
            h.clock.advance(seconds=1)
            made.append(await h.make(user))
        for row in made[::2]:
            await h.repo.update_state(user, row.id, state=S.PAUSED)
        seen: list[str] = []
        cursor, pages = None, 0
        while pages < 10:
            page = await h.repo.list_page(user, limit=3, cursor=cursor)
            seen += [r.id for r in page.rows]
            pages, cursor = pages + 1, page.next_cursor
            if cursor is None:
                break
        assert (pages, seen) == (3, [r.id for r in reversed(made)])
        paused = await h.repo.list_page(user, state=S.PAUSED, limit=3)
        rest = await h.repo.list_page(user, state=S.PAUSED, limit=3, cursor=paused.next_cursor)
        assert [r.id for r in paused.rows + rest.rows] == [r.id for r in reversed(made[::2])]
        assert (len(paused.rows), len(rest.rows), rest.next_cursor) == (3, 1, None)

    async def test_list_page_breaks_created_at_ties_by_id_descending(self, h: Harness) -> None:
        user = h.new_user()
        ids = sorted([(await h.make(user)).id for _ in range(5)], reverse=True)  # one clock tick
        first = await h.repo.list_page(user, limit=2)
        second = await h.repo.list_page(user, limit=2, cursor=first.next_cursor)
        third = await h.repo.list_page(user, limit=2, cursor=second.next_cursor)
        assert [r.id for p in (first, second, third) for r in p.rows] == ids
        assert third.next_cursor is None

    async def test_list_page_clamps_a_non_positive_limit_to_one(self, h: Harness) -> None:
        user = h.new_user()
        await h.make(user)
        await h.make(user)
        for limit in (0, -5):
            assert len((await h.repo.list_page(user, limit=limit)).rows) == 1

    async def test_list_page_refuses_an_unknown_state_filter(self, h: Harness) -> None:
        with pytest.raises(ValueError, match="bogus"):
            await h.repo.list_page(h.new_user(), state=cast(Any, "bogus"))

    @pytest.mark.parametrize(
        "cursor",
        [
            "!!!",
            "A" * 300,
            _cursor("not a pair"),
            _cursor([1, 2]),
            _cursor(["2026-10-01T00:00:00", _SOME_UUID]),  # naive timestamp
            _cursor(["2026-10-01T00:00:00+00:00", "not-a-uuid"]),
            base64.urlsafe_b64encode(b"\xff\xfe not json").decode(),
            # Well-formed and aware, but with no UTC equivalent: asyncpg cannot bind it, so every
            # backend must refuse it the same way instead of paging (fake) or a 500 (Postgres).
            pytest.param(
                _cursor(["0001-01-01T00:00:00+23:59", _SOME_UUID]),
                id="year-1-offset-overflows-utc",
            ),
            pytest.param(
                _cursor(["9999-12-31T23:59:59-23:59", _SOME_UUID]),
                id="year-9999-offset-overflows-utc",
            ),
        ],
    )
    async def test_list_page_refuses_a_garbage_cursor_cleanly(
        self, h: Harness, cursor: str
    ) -> None:
        with pytest.raises(ReplaySessionCursorError):
            await h.repo.list_page(h.new_user(), cursor=cursor)

    # -- counting and idle sweep -----------------------------------------------------------------

    async def test_count_active_counts_exactly_the_four_live_states(self, h: Harness) -> None:
        user = h.new_user()
        for state in ReplayState:
            await h.in_state(state, user)
        await h.in_state(S.PLAYING)  # someone else's live session
        assert await h.repo.count_active(user) == len(LIVE_STATES) == 4

    async def test_list_idle_since_returns_only_idle_live_sessions_oldest_first(
        self, h: Harness
    ) -> None:
        a = await h.in_state(S.PLAYING)
        h.clock.advance(minutes=1)
        b = await h.in_state(S.PAUSED)
        h.clock.advance(minutes=1)
        for quiet in (S.CREATED, S.FINISHED, S.ERROR, S.DESTROYED):  # old but not live
            await h.in_state(quiet)
        h.clock.advance(minutes=1)
        before = h.clock.now
        await h.in_state(S.BUFFERING)  # exactly at the boundary: not strictly older
        h.clock.advance(hours=2)
        await h.in_state(S.STEPPING)  # recent
        assert [i.id for i in await h.repo.list_idle_since(before, 10)] == [a.id, b.id]
        assert [i.id for i in await h.repo.list_idle_since(before, 1)] == [a.id]
        assert await h.repo.list_idle_since(T0 - timedelta(days=1), 10) == []

    async def test_count_non_terminal_counts_every_state_but_destroyed(self, h: Harness) -> None:
        user = h.new_user()
        for state in ReplayState:
            await h.in_state(state, user)
        await h.in_state(S.CREATED)  # someone else's open session
        assert await h.repo.count_non_terminal(user) == len(ReplayState) - 1 == 7
        assert await h.repo.count_non_terminal("not-a-uuid") == 0

    async def test_list_reclaimable_returns_every_idle_open_session_oldest_first(
        self, h: Harness
    ) -> None:
        old: list[ReplaySessionRow] = []
        for state in ReplayState:  # one a minute, so the order is the creation order
            row = await h.in_state(state)
            h.clock.advance(minutes=1)
            if state is not S.DESTROYED:
                old.append(row)
        before, born = h.clock.now, T0 - timedelta(days=1)  # no row is past the lifetime
        await h.in_state(S.CREATED)  # exactly at the boundary: not strictly older
        h.clock.advance(hours=2)
        await h.in_state(S.FINISHED)  # recent
        got = await h.repo.list_reclaimable(before, born, 10)
        assert [i.id for i in got] == [r.id for r in old]
        assert {i.state for i in got} == set(ReplayState) - {S.DESTROYED}
        two = await h.repo.list_reclaimable(before, born, 2)
        assert [i.id for i in two] == [r.id for r in old[:2]]
        assert await h.repo.list_reclaimable(born, born, 10) == []

    async def test_list_reclaimable_also_returns_open_sessions_created_before_the_lifetime(
        self, h: Harness
    ) -> None:
        old = await h.in_state(S.PLAYING)
        await h.in_state(S.DESTROYED)  # old, but terminal
        h.clock.advance(hours=25)
        await h.repo.touch(old.user_id, old.id, h.clock.now)  # active, but too old
        await h.in_state(S.PAUSED)  # young and active
        idle_before, born = h.clock.now - timedelta(hours=2), h.clock.now - timedelta(hours=24)
        (got,) = await h.repo.list_reclaimable(idle_before, born, 10)
        assert (got.id, got.created_at, got.updated_at) == (old.id, T0, h.clock.now)
        assert await h.repo.list_reclaimable(idle_before, T0, 10) == []  # strictly older only

    async def test_idle_projection_carries_what_the_sweep_needs_and_no_bookmarks(
        self, h: Harness
    ) -> None:
        row = await h.in_state(S.PAUSED, paper_trading=True, paper_account_id=h.new_account())
        (idle,) = await h.repo.list_idle_since(row.updated_at + timedelta(seconds=1), 10)
        want = IdleReplaySession(
            row.id, row.user_id, row.symbol, S.PAUSED, row.paper_account_id, row.updated_at,
            row.created_at,
        )  # fmt: skip
        assert idle == want
        assert not hasattr(idle, "bookmarks")

    # -- live_covering (retention guard, G7) -----------------------------------------------------

    async def _covering(
        self, h: Harness, symbol: str = "BTCUSDT", stream: str = "trades", lo: Any = T0,
        hi: Any = T2H, created_after: Any = None,
    ) -> str | None:  # fmt: skip
        born = T0 - timedelta(days=1) if created_after is None else created_after
        return await h.repo.live_covering(symbol, stream, lo, hi, created_after=born)

    @pytest.mark.parametrize("state", sorted(COVERING_STATES))
    async def test_live_covering_names_a_session_in_every_live_state_created_included(
        self, h: Harness, state: ReplayState
    ) -> None:
        row = await h.in_state(state)
        assert await self._covering(h) == row.id

    @pytest.mark.parametrize("state", sorted(set(ReplayState) - COVERING_STATES))
    async def test_live_covering_ignores_a_session_in_each_ended_state(
        self, h: Harness, state: ReplayState
    ) -> None:
        await h.in_state(state)
        assert await self._covering(h) is None

    async def test_live_covering_sees_every_symbol_and_stream_of_a_session(
        self, h: Harness
    ) -> None:
        row = await h.in_state(
            S.PLAYING, symbols=("BTCUSDT", "ETHUSDT"), streams=("trades", "klines")
        )
        assert await self._covering(h, "ETHUSDT", "klines") == row.id
        assert await self._covering(h, "ETHUSDT", "trades") == row.id
        assert await self._covering(h, "ETHUSDT", "tickers") is None
        assert await self._covering(h, "SOLUSDT", "trades") is None

    async def test_live_covering_takes_every_stream_of_a_session_made_without_a_list(
        self, h: Harness
    ) -> None:
        row = await h.in_state(S.PAUSED)
        for stream in _ALL_STREAMS:
            assert await self._covering(h, stream=stream) == row.id

    @pytest.mark.parametrize(
        ("lo", "hi", "covered"),
        [
            pytest.param(T0, T2H, True, id="same-window"),
            pytest.param(T0 - timedelta(hours=1), T0 + _US, True, id="overlaps-the-start"),
            pytest.param(T2H - _US, T2H + timedelta(hours=1), True, id="overlaps-the-end"),
            pytest.param(T0 + _US, T2H - _US, True, id="inside"),
            pytest.param(T0 - timedelta(days=1), T2H + timedelta(days=1), True, id="around"),
            pytest.param(T0 - timedelta(hours=1), T0, False, id="ends-at-the-start"),
            pytest.param(T2H, T2H + timedelta(hours=1), False, id="starts-at-the-end"),
            pytest.param(T2H + timedelta(days=1), T2H + timedelta(days=2), False, id="after"),
        ],
    )
    async def test_live_covering_takes_a_session_whose_window_overlaps_the_range(
        self, h: Harness, lo: Any, hi: Any, covered: bool
    ) -> None:
        row = await h.in_state(S.PLAYING)
        assert await self._covering(h, lo=lo, hi=hi) == (row.id if covered else None)

    async def test_live_covering_ignores_a_session_created_at_or_before_the_lifetime_bound(
        self, h: Harness
    ) -> None:
        row = await h.in_state(S.PLAYING)
        assert await self._covering(h, created_after=row.created_at - _US) == row.id
        assert await self._covering(h, created_after=row.created_at) is None
        assert await self._covering(h, created_after=row.created_at + _US) is None

    async def test_live_covering_names_the_oldest_of_several_and_any_users_session(
        self, h: Harness
    ) -> None:
        older = await h.in_state(S.PAUSED)
        h.clock.advance(minutes=1)
        await h.in_state(S.PLAYING)  # another user's, younger
        assert await self._covering(h) == older.id

    async def test_live_covering_refuses_naive_datetimes(self, h: Harness) -> None:
        naive = T0.replace(tzinfo=None)
        for kw in ({"lo": naive}, {"hi": naive}, {"created_after": naive}):
            with pytest.raises(ValueError, match="timezone-aware"):
                await self._covering(h, **kw)

    # -- update_state ----------------------------------------------------------------------------

    async def test_update_state_compare_and_set_refuses_a_stale_expected_state(
        self, h: Harness
    ) -> None:
        row = await h.in_state(S.PAUSED)
        with pytest.raises(ReplaySessionIllegalUpdateError) as lost:
            await h.repo.update_state(
                row.user_id, row.id, state=S.PLAYING, expected_state=S.BUFFERING
            )
        assert (lost.value.current, lost.value.expected) == (S.PAUSED, S.BUFFERING)
        assert await h.repo.get(row.user_id, row.id) == row
        h.clock.advance(seconds=5)
        won = await h.repo.update_state(
            row.user_id, row.id, state=S.PLAYING, expected_state=S.PAUSED
        )
        assert (won.state, won.updated_at) == (S.PLAYING, h.clock.now)

    async def test_terminal_rows_refuse_every_update_but_the_owner_may_delete(
        self, h: Harness
    ) -> None:
        row = await h.in_state(S.DESTROYED)
        writes = _writes(h, row.user_id, row.id) | {
            "second_destroy": lambda: h.repo.update_state(row.user_id, row.id, state=S.DESTROYED)
        }
        for call in writes.values():
            with pytest.raises(ReplaySessionIllegalUpdateError) as err:
                await call()
            assert err.value.current is S.DESTROYED
        assert await h.repo.get(row.user_id, row.id) == row
        assert await h.repo.delete(row.user_id, row.id) is True
        assert await h.repo.get(row.user_id, row.id) is None
        assert await h.repo.delete(row.user_id, row.id) is False

    async def test_finished_at_is_stamped_on_finished_and_destroyed_and_cleared_on_exit(
        self, h: Harness
    ) -> None:
        row = await h.make()
        uid, sid = row.user_id, row.id
        h.clock.advance(minutes=1)
        assert (await h.repo.update_state(uid, sid, state=S.FINISHED)).finished_at == h.clock.now
        h.clock.advance(minutes=1)
        assert (await h.repo.update_state(uid, sid, state=S.BUFFERING)).finished_at is None  # SEEK
        h.clock.advance(minutes=1)
        gone = await h.repo.update_state(uid, sid, state=S.DESTROYED)
        assert (gone.finished_at, gone.updated_at) == (h.clock.now, h.clock.now)

    async def test_error_message_lives_only_while_the_session_is_in_error(self, h: Harness) -> None:
        row = await h.make()
        uid, sid = row.user_id, row.id
        failed = await h.repo.update_state(uid, sid, state=S.ERROR, error_message="source gone")
        assert (failed.error_message, failed.finished_at) == ("source gone", None)
        forced = await h.repo.update_state(uid, sid, state=S.ERROR, finished=True)
        assert (forced.error_message, forced.finished_at) == (None, h.clock.now)
        back = await h.repo.update_state(uid, sid, state=S.BUFFERING)
        assert (back.error_message, back.finished_at) == (None, None)
        with pytest.raises(ValueError, match="error_message"):
            await h.repo.update_state(uid, sid, state=S.PAUSED, error_message="stale")

    # -- cursor, speed, touch --------------------------------------------------------------------

    async def test_update_cursor_persists_position_and_counters_without_touching_updated_at(
        self, h: Harness
    ) -> None:
        row = await h.in_state(S.PLAYING)
        h.clock.advance(minutes=5)
        at = T0 + timedelta(minutes=30)
        await h.repo.update_cursor(
            row.user_id, row.id, cursor_ts=at, events_emitted=9, gap_warnings=2
        )
        await h.repo.update_cursor(row.user_id, row.id, cursor_ts=at + timedelta(seconds=1))
        got = await h.repo.get(row.user_id, row.id)
        assert got is not None
        assert (got.cursor_ts, got.events_emitted, got.gap_warnings) == (
            at + timedelta(seconds=1), 9, 2,
        )  # fmt: skip
        assert got.updated_at == row.updated_at

    async def test_update_speed_returns_the_row_and_counts_as_control_activity(
        self, h: Harness
    ) -> None:
        row = await h.in_state(S.PAUSED)
        h.clock.advance(minutes=5)
        sped = await h.repo.update_speed(row.user_id, row.id, speed=Decimal(4))
        assert (sped.speed, sped.updated_at) == (Decimal(4), h.clock.now)
        assert await h.repo.get(row.user_id, row.id) == sped

    async def test_a_change_the_client_did_not_make_leaves_updated_at_alone(
        self, h: Harness
    ) -> None:
        row = await h.in_state(S.PLAYING)
        h.clock.advance(minutes=5)
        sped = await h.repo.update_speed(row.user_id, row.id, speed=Decimal(2), activity=False)
        moved = await h.repo.update_state(row.user_id, row.id, state=S.FINISHED, activity=False)
        assert (sped.speed, moved.state, moved.finished_at) == (Decimal(2), S.FINISHED, h.clock.now)
        assert sped.updated_at == moved.updated_at == row.updated_at

    async def test_touch_moves_updated_at_forward_and_never_backwards(self, h: Harness) -> None:
        row = await h.in_state(S.PAUSED)
        later = row.updated_at + timedelta(minutes=10)
        await h.repo.touch(row.user_id, row.id, later)
        await h.repo.touch(row.user_id, row.id, later - timedelta(minutes=30))
        got = await h.repo.get(row.user_id, row.id)
        assert got is not None and got.updated_at == later

    # -- constraints -----------------------------------------------------------------------------

    @pytest.mark.parametrize(
        ("constraint", "over"),
        [
            ("rps_range", {"range_end": T0}),
            ("rps_range", {"range_end": T0 - timedelta(hours=1)}),
            ("rps_speed", {"speed": Decimal(0)}),
            ("rps_speed", {"speed": Decimal("0.09")}),
            ("rps_speed", {"speed": Decimal(101)}),
            ("rps_speed", {"speed": Decimal(12_345)}),
            ("rps_speed", {"speed": Decimal("9999.995")}),  # rounds up to 10000.00: overflows
            ("rps_speed", {"speed": Decimal("NaN")}),  # storable, so the CHECK rejects it
            ("rps_speed", {"speed": Decimal("Infinity")}),  # never storable: numeric overflow
            ("rps_range", {"speed": Decimal("NaN"), "range_end": T0}),  # CHECKs run in name order
            ("rps_tier", {"source_tier": "bogus"}),
            ("rps_cursor", {"cursor_ts": T0 - timedelta(seconds=1)}),
            ("rps_cursor", {"cursor_ts": T2H + timedelta(seconds=1)}),
            ("rps_paper", {"paper_trading": True}),
            ("symbol_code_check", {"symbol": "btc-usdt"}),
            ("symbol_code_check", {"symbols": ("BTCUSDT", "eth-usdt")}),
            ("rps_symbols", {"symbols": ("ETHUSDT", "BTCUSDT")}),  # `symbol` is the first
            ("rps_symbols", {"symbols": ("BTCUSDT", *(f"SYM{i}USDT" for i in range(8)))}),
            ("rps_streams", {"streams": ("trades", "bars")}),  # derived: rebuilt, not replayed
            ("rps_streams", {"streams": ("funding",)}),  # the DB kind, not the stream name
        ],
    )
    async def test_create_surfaces_each_check_by_its_constraint_name(
        self, h: Harness, constraint: str, over: dict[str, Any]
    ) -> None:
        user = h.new_user()
        with pytest.raises(ReplaySessionConstraintError) as err:
            await h.make(user, **over)
        assert err.value.constraint == constraint
        assert (await h.repo.list_page(user)).rows == ()

    @pytest.mark.parametrize(
        ("given", "stored"),
        [("0.095", "0.10"), ("100.004", "100.00"), ("2.345", "2.35"), ("1", "1.00")],
    )
    async def test_speed_is_stored_as_numeric_6_2_half_up(
        self, h: Harness, given: str, stored: str
    ) -> None:
        made = await h.make(speed=Decimal(given))
        assert made.speed == Decimal(stored)
        assert (await h.repo.get(made.user_id, made.id)) == made

    async def test_updates_surface_cursor_and_speed_violations_by_name(self, h: Harness) -> None:
        row = await h.in_state(S.PLAYING)
        uid, sid = row.user_id, row.id
        for cursor in (T0 - timedelta(seconds=1), T2H + timedelta(seconds=1)):
            with pytest.raises(ReplaySessionConstraintError) as bad_cursor:
                await h.repo.update_cursor(uid, sid, cursor_ts=cursor)
            assert bad_cursor.value.constraint == "rps_cursor"
        for speed in (Decimal("0.09"), Decimal(101)):
            with pytest.raises(ReplaySessionConstraintError) as bad_speed:
                await h.repo.update_speed(uid, sid, speed=speed)
            assert bad_speed.value.constraint == "rps_speed"
        assert await h.repo.get(uid, sid) == row

    @pytest.mark.parametrize(
        "speed",
        [Decimal(12_345), Decimal("9999.995"), Decimal("Infinity"), Decimal("-Infinity")],
    )
    async def test_an_unstorable_speed_is_rps_speed_on_the_row_and_not_found_on_a_bad_id(
        self, h: Harness, speed: Decimal
    ) -> None:
        # On the owned row an unstorable speed is the `rps_speed` check, whatever plan Postgres
        # uses. Ids are parsed before anything reaches the database, so a malformed id is "not
        # found" even then. (Whether Postgres coerces the speed before matching an unknown but
        # well-formed id depends on the plan, so that case is deliberately not pinned.)
        row = await h.in_state(S.PAUSED)
        with pytest.raises(ReplaySessionConstraintError) as err:
            await h.repo.update_speed(row.user_id, row.id, speed=speed)
        assert err.value.constraint == "rps_speed"
        for uid, sid in ((row.user_id, "not-a-uuid"), ("not-a-uuid", row.id)):
            with pytest.raises(ReplaySessionNotFoundError):
                await h.repo.update_speed(uid, sid, speed=speed)
        assert await h.repo.get(row.user_id, row.id) == row

    async def test_nan_speed_is_an_ordinary_check_failure_not_a_coercion_error(
        self, h: Harness
    ) -> None:
        nan = Decimal("NaN")
        row = await h.in_state(S.PAUSED)
        with pytest.raises(ReplaySessionConstraintError) as own:  # the CHECK, on a matching row
            await h.repo.update_speed(row.user_id, row.id, speed=nan)
        assert own.value.constraint == "rps_speed"
        for uid, sid in ((row.user_id, str(uuid.uuid4())), (h.new_user(), row.id)):  # no match
            with pytest.raises(ReplaySessionNotFoundError):
                await h.repo.update_speed(uid, sid, speed=nan)
        assert await h.repo.get(row.user_id, row.id) == row

    # -- uuid columns ----------------------------------------------------------------------------

    async def test_create_stores_uuid_columns_in_canonical_lower_case_form(
        self, h: Harness
    ) -> None:
        acct, rec = h.new_account(), h.new_recording()
        made = await h.make(
            paper_trading=True, paper_account_id=acct.upper(), recording_session_id="{" + rec + "}"
        )
        assert (made.paper_account_id, made.recording_session_id) == (acct, rec)
        assert await h.repo.get(made.user_id, made.id) == made

    @pytest.mark.parametrize("field", ["id", "user_id", "recording_session_id", "paper_account_id"])
    async def test_create_refuses_a_garbage_uuid_before_any_constraint_is_checked(
        self, h: Harness, field: str
    ) -> None:
        with pytest.raises(ValueError, match="hexadecimal"):
            await h.make(symbol="btc-usdt", **{field: "garbage"})  # not `symbol_code_check`
