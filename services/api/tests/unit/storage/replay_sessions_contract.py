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

from candleviewer.storage.repositories.replay_sessions import (
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
        assert await h.repo.get(user, made.id) == made

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

    async def test_idle_projection_carries_what_the_sweep_needs_and_no_bookmarks(
        self, h: Harness
    ) -> None:
        row = await h.in_state(S.PAUSED, paper_trading=True, paper_account_id=h.new_account())
        (idle,) = await h.repo.list_idle_since(row.updated_at + timedelta(seconds=1), 10)
        want = IdleReplaySession(
            row.id, row.user_id, row.symbol, S.PAUSED, row.paper_account_id, row.updated_at
        )
        assert idle == want
        assert not hasattr(idle, "bookmarks")

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
    async def test_an_unstorable_speed_fails_by_name_even_when_no_row_matches(
        self, h: Harness, speed: Decimal
    ) -> None:
        # Postgres coerces the value to numeric(6,2) before it matches a row, so a missing or
        # foreign row is still `rps_speed`, not "not found".
        row = await h.in_state(S.PAUSED)
        for uid, sid in ((row.user_id, str(uuid.uuid4())), (h.new_user(), row.id)):
            with pytest.raises(ReplaySessionConstraintError) as err:
                await h.repo.update_speed(uid, sid, speed=speed)
            assert err.value.constraint == "rps_speed"
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
