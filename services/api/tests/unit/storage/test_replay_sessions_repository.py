"""`ReplaySessionRepository` (E26-T01 slice 2/3): fake, port helpers and the adapter's pure parts.

The behavioural contract (`replay_sessions_contract.py`) runs here against the in-memory fake and in
`tests/integration/storage/test_replay_sessions_repository_pg.py` against real Postgres 16. The
adapter is also driven through a scripted unit of work (like `test_alerts_repository_sqlalchemy.py`)
for its control flow, error mapping and statement scoping; real-database behaviour is CI-only.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import CheckConstraint
from sqlalchemy.exc import DataError, DBAPIError, IntegrityError

from candleviewer.db import models
from candleviewer.storage.repositories import replay_sessions_sqlalchemy as mod
from candleviewer.storage.repositories.replay_sessions import (
    FINISHED_STATES,
    LIVE_STATES,
    MAX_PAGE_LIMIT,
    TERMINAL_STATES,
    IdleReplaySession,
    ReplaySessionConstraintError,
    ReplaySessionCreate,
    ReplaySessionCursorError,
    ReplaySessionIllegalUpdateError,
    ReplaySessionNotFoundError,
    ReplaySessionRow,
    ReplayState,
    SourceTier,
    clamp_limit,
    decode_cursor,
    encode_cursor,
    require_aware,
    state_columns,
)
from tests.unit.storage.fakes_replay_sessions import FakeClock, FakeReplaySessionRepository
from tests.unit.storage.replay_sessions_contract import (
    Harness,
    ReplaySessionRepositoryContract,
)

S = ReplayState
T0 = datetime(2026, 10, 1, tzinfo=UTC)
_B12 = (
    Path(__file__).resolve().parents[3] / "candleviewer/statechart/machines/B12.replay.machine.json"
)


def _new_id() -> str:
    return str(uuid.uuid4())


class TestFakeRepository(ReplaySessionRepositoryContract):
    @pytest.fixture
    def h(self) -> Harness:
        clock = FakeClock()
        return Harness(FakeReplaySessionRepository(clock), clock, _new_id, _new_id, _new_id)


# -- property: pagination is a partition of the user's rows, in order ---------------------------

_ROWS = st.lists(
    st.tuples(st.integers(0, 4), st.uuids(), st.sampled_from([S.PAUSED, S.PLAYING])),
    unique_by=lambda t: t[1],
    max_size=25,
)


async def _paginate_everything(rows: list[tuple[int, uuid.UUID, ReplayState]], size: int) -> None:
    clock = FakeClock()
    repo, user = FakeReplaySessionRepository(clock), _new_id()
    made: dict[str, ReplaySessionRow] = {}
    for offset, rid, state in rows:
        clock.now = T0 + timedelta(seconds=offset)  # few distinct values: plenty of ties
        row = await repo.create(
            ReplaySessionCreate(str(rid), user, "BTCUSDT", T0, T0 + timedelta(hours=1))
        )
        made[row.id] = await repo.update_state(user, row.id, state=state)
    for wanted in (None, S.PAUSED):
        pool = [r for r in made.values() if wanted is None or r.state is wanted]
        want = [r.id for r in sorted(pool, key=lambda r: (r.created_at, r.id), reverse=True)]
        seen: list[str] = []
        cursor = None
        for _ in range(len(pool) + 2):
            page = await repo.list_page(user, state=wanted, limit=size, cursor=cursor)
            seen += [r.id for r in page.rows]
            if (cursor := page.next_cursor) is None:
                break
        assert seen == want


@given(rows=_ROWS, size=st.integers(1, 7))
def test_pagination_yields_each_row_exactly_once_in_order(
    rows: list[tuple[int, uuid.UUID, ReplayState]], size: int
) -> None:
    asyncio.run(_paginate_everything(rows, size))


# -- port: enums, sets, helpers ------------------------------------------------------------------


def test_replay_state_mirrors_the_database_enum_and_the_b12_chart() -> None:
    chart = json.loads(_B12.read_text(encoding="utf-8"))
    assert [s.value for s in ReplayState] == list(models.replay_state.enums)
    assert {s.value for s in ReplayState} == set(chart["states"])
    assert [k for k, v in chart["states"].items() if v.get("type") == "final"] == ["destroyed"]


def test_live_and_terminal_sets_follow_the_partial_index_and_the_final_state() -> None:
    index = next(i for i in models.replay_sessions.indexes if i.name == "ix_rps_live")
    predicate = str(index.dialect_options["postgresql"]["where"])
    assert {s.value for s in LIVE_STATES} == set(re.findall(r"'(\w+)'", predicate))
    assert TERMINAL_STATES == {S.DESTROYED}
    assert FINISHED_STATES == {S.FINISHED, S.DESTROYED}


def test_source_tier_mirrors_the_closed_check() -> None:
    check = next(
        c
        for c in models.replay_sessions.constraints
        if isinstance(c, CheckConstraint) and str(c.name).endswith("rps_tier")
    )
    assert {t.value for t in SourceTier} == set(re.findall(r"'(\w+)'", str(check.sqltext)))


def test_cursor_round_trips_and_is_url_safe() -> None:
    ts, rid = (
        datetime(2026, 10, 1, 12, 0, 0, 123456, tzinfo=timezone(timedelta(hours=5))),
        _new_id(),
    )
    token = encode_cursor(ts, rid)
    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)
    assert decode_cursor(token) == (ts, rid)
    assert decode_cursor(token + "=" * (-len(token) % 4)) == (ts, rid)  # padding is tolerated


@pytest.mark.parametrize(
    ("given", "clamped"),
    [(-1, 1), (0, 1), (1, 1), (50, 50), (MAX_PAGE_LIMIT, MAX_PAGE_LIMIT), (201, 200), (10**9, 200)],
)
def test_clamp_limit_keeps_one_to_the_page_maximum(given: int, clamped: int) -> None:
    assert clamp_limit(given) == clamped


@pytest.mark.parametrize(
    ("state", "finished", "message", "expected"),
    [
        (S.PLAYING, False, None, (None, None)),
        (S.FINISHED, False, None, (T0, None)),
        (S.DESTROYED, False, None, (T0, None)),
        (S.ERROR, False, "boom", (None, "boom")),
        (S.ERROR, True, None, (T0, None)),
    ],
)
def test_state_columns_stamp_on_entry_and_default_to_cleared(
    state: ReplayState, finished: bool, message: str | None, expected: tuple[Any, Any]
) -> None:
    assert state_columns(state, now=T0, finished=finished, error_message=message) == expected


def test_state_columns_refuse_an_error_message_outside_the_error_state() -> None:
    with pytest.raises(ValueError, match="error_message"):
        state_columns(S.PAUSED, now=T0, error_message="stale")


def test_naive_datetimes_are_refused_everywhere_they_could_misorder() -> None:
    naive = datetime(2026, 10, 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        require_aware(naive, "x")
    with pytest.raises(ValueError, match="range_end"):
        ReplaySessionCreate(_new_id(), _new_id(), "BTCUSDT", T0, naive)
    repo = FakeReplaySessionRepository()
    for call in (
        repo.touch("u", "s", naive),
        repo.list_idle_since(naive, 1),
        repo.update_cursor("u", "s", cursor_ts=naive),
    ):
        with pytest.raises(ValueError, match="timezone-aware"):
            asyncio.run(call)


def test_illegal_update_error_says_what_it_found_and_what_it_expected() -> None:
    lost = ReplaySessionIllegalUpdateError("sid", S.PAUSED, S.PLAYING)
    assert (lost.current, lost.expected) == (S.PAUSED, S.PLAYING)
    assert "paused" in str(lost) and "expected playing" in str(lost)
    assert "expected" not in str(ReplaySessionIllegalUpdateError("sid", S.DESTROYED))


# -- adapter: statements ---------------------------------------------------------------------------

_UID, _SID = uuid.uuid4(), uuid.uuid4()


def _sql(stmt: Any) -> str:
    return str(stmt.compile(compile_kwargs={"render_postcompile": True}))


_STATEMENTS = {
    "get_statement": mod.get_statement(_UID, _SID),
    "list_statement": mod.list_statement(_UID, S.PAUSED, (T0, str(_SID)), 51),
    "count_statement": mod.count_statement(_UID),
    "idle_statement": mod.idle_statement(T0, 10),
    "update_statement": mod.update_statement(_UID, _SID, {"cursor_ts": T0}, S.PAUSED),
}


def test_the_statement_set_is_pinned() -> None:
    # Self-discovering: a statement builder added later cannot dodge the scoping guard below.
    assert {n for n in vars(mod) if n.endswith("_statement")} == set(_STATEMENTS)


@pytest.mark.parametrize("name", sorted(_STATEMENTS))
def test_every_statement_is_owner_scoped_except_the_unscoped_sweep(name: str) -> None:
    assert ("replay_sessions.user_id = " in _sql(_STATEMENTS[name])) is (name not in mod.UNSCOPED)


def test_only_the_idle_sweep_is_unscoped() -> None:
    assert mod.UNSCOPED == {"idle_statement"}


def test_live_states_are_rendered_as_literals_for_the_partial_index() -> None:
    live = "IN ('buffering', 'paused', 'playing', 'stepping')"
    assert live in _sql(_STATEMENTS["count_statement"])
    assert live in _sql(_STATEMENTS["idle_statement"])


def test_updates_can_never_match_a_terminal_row() -> None:
    stmt = _STATEMENTS["update_statement"]
    assert "replay_sessions.state NOT IN (" in _sql(stmt)
    assert "replay_sessions.state = " in _sql(stmt)  # the compare-and-set
    assert ["destroyed"] in stmt.compile().params.values()


def test_list_statement_orders_for_the_keyset_and_bounds_the_index_range() -> None:
    sql = _sql(_STATEMENTS["list_statement"])
    assert "ORDER BY replay_sessions.created_at DESC, replay_sessions.id DESC" in sql
    assert "replay_sessions.created_at <= " in sql and "replay_sessions.created_at < " in sql


def test_read_allow_lists_follow_the_dataclasses_and_the_sweep_never_selects_bookmarks() -> None:
    assert [c.name for c in mod.ROW_COLUMNS] == list(ReplaySessionRow.__dataclass_fields__)
    assert [c.name for c in mod.IDLE_COLUMNS] == list(IdleReplaySession.__dataclass_fields__)
    assert "bookmarks" not in _sql(_STATEMENTS["idle_statement"])
    assert "*" not in _sql(_STATEMENTS["get_statement"])


# -- adapter: row mapping and error mapping -----------------------------------------------------


def _db_row(**over: Any) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(), "user_id": uuid.uuid4(), "recording_session_id": None,
        "symbol": "BTCUSDT", "range_start": T0, "range_end": T0 + timedelta(hours=2),
        "cursor_ts": None, "speed": Decimal("1.00"), "state": "paused", "source_tier": "auto",
        "paper_trading": False, "paper_account_id": None, "bookmarks": [], "loop_enabled": False,
        "events_emitted": 0, "gap_warnings": 0, "error_message": None, "created_at": T0,
        "updated_at": T0, "finished_at": None,
    } | over  # fmt: skip


def test_to_row_stringifies_ids_maps_enums_and_decodes_text_bookmarks() -> None:
    account = uuid.uuid4()
    row = mod._to_row(_db_row(paper_account_id=account, bookmarks='[{"label": "x"}]'))
    assert (row.state, row.source_tier) == (S.PAUSED, SourceTier.AUTO)
    assert (row.paper_account_id, row.recording_session_id) == (str(account), None)
    assert row.bookmarks == ({"label": "x"},)
    assert mod._to_row(_db_row(bookmarks=[{"label": "y"}])).bookmarks == ({"label": "y"},)


class _Driver(Exception):
    def __init__(self, constraint_name: str) -> None:
        super().__init__("driver")
        self.constraint_name = constraint_name


class _PgError(Exception):
    """What the asyncpg wrapper raises: `sqlstate` here, the name on `__cause__` or `diag`."""

    def __init__(self, sqlstate: str, *, cause: str | None = None, diag: str | None = None) -> None:
        super().__init__("pg")
        self.sqlstate = sqlstate
        self.diag = None if diag is None else SimpleNamespace(constraint_name=diag)
        if cause is not None:
            self.__cause__ = _Driver(cause)


@pytest.mark.parametrize(
    ("orig", "name"),
    [
        (_PgError("23514", cause="rps_range"), "rps_range"),  # asyncpg: on __cause__
        (_PgError("23503", diag="replay_sessions_user_id_fkey"), "replay_sessions_user_id_fkey"),
        (_PgError("23505", cause="replay_sessions_pkey"), "replay_sessions_pkey"),
        (_PgError("22003"), "rps_speed"),  # numeric(6,2) overflow
        (_PgError("23502", cause="not_null"), None),  # not a constraint this repository maps
        (_PgError("23514"), None),  # named violation without a name: do not guess
        (_PgError("40001"), None),
    ],
)
def test_violated_constraint_reads_the_name_wherever_the_driver_puts_it(
    orig: Exception, name: str | None
) -> None:
    assert mod._violated_constraint(DBAPIError("stmt", {}, orig)) == name


# -- adapter: control flow over a scripted unit of work -------------------------------------------


class _Result:
    def __init__(self, rows: Sequence[Any] = (), scalar: Any = None) -> None:
        self.rows, self.scalar = rows, scalar

    def mappings(self) -> _Result:
        return self

    def first(self) -> Any:
        return self.rows[0] if self.rows else None

    def one(self) -> Any:
        return self.rows[0]

    def scalar_one(self) -> Any:
        return self.scalar

    def scalar_one_or_none(self) -> Any:
        return self.scalar

    def __iter__(self) -> Any:
        return iter(self.rows)


class _Rel:
    """Scripted `SqlAlchemyRelationalRepository`: records statements, replays canned results."""

    def __init__(self, *script: _Result | Exception) -> None:
        self.script: list[_Result | Exception] = list(script)
        self.statements: list[Any] = []
        self.commits = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any) -> _Result:
            self.statements.append(stmt)
            step = self.script.pop(0)
            if isinstance(step, Exception):
                raise step
            return step

        async def commit() -> None:
            self.commits += 1

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)

    def params(self, i: int = 0) -> Any:
        return self.statements[i].compile().params


def _repo(rel: _Rel) -> mod.SqlAlchemyReplaySessionRepository:
    clock = FakeClock()
    return mod.SqlAlchemyReplaySessionRepository(cast(Any, rel), clock=clock)  # structural fake


def _create(**over: Any) -> ReplaySessionCreate:
    return ReplaySessionCreate(
        _new_id(), _new_id(), "BTCUSDT", T0, T0 + timedelta(hours=1), **over
    )  # fmt: skip


def test_the_default_clock_is_timezone_aware_utc() -> None:
    assert mod._utc_now().utcoffset() == timedelta(0)


async def test_get_maps_a_found_row_and_returns_none_for_a_missing_one() -> None:
    rel = _Rel(_Result([_db_row(state="playing")]), _Result())
    repo = _repo(rel)
    found = await repo.get(str(_UID), str(_SID))
    assert found is not None and found.state is S.PLAYING
    assert await repo.get(str(_UID), str(_SID)) is None
    assert "replay_sessions.user_id = " in _sql(rel.statements[0])


async def test_create_binds_every_value_and_commits_once() -> None:
    rel = _Rel(_Result([_db_row()]))
    row = await _repo(rel).create(_create(bookmarks=({"label": "x"},), speed=Decimal("2.5")))
    p = rel.params()
    assert (p["speed"], p["bookmarks"], p["created_at"], p["updated_at"]) == (
        Decimal("2.5"), [{"label": "x"}], T0, T0,
    )  # fmt: skip
    assert (rel.commits, row.state) == (1, S.PAUSED)


@pytest.mark.parametrize(
    ("error", "constraint"),
    [
        (IntegrityError("INSERT", {}, _PgError("23514", cause="rps_paper")), "rps_paper"),
        (DataError("INSERT", {}, _PgError("22003")), "rps_speed"),
    ],
)
async def test_create_maps_database_rejections_to_the_constraint_name(
    error: DBAPIError, constraint: str
) -> None:
    rel = _Rel(error)
    with pytest.raises(ReplaySessionConstraintError) as err:
        await _repo(rel).create(_create())
    assert (err.value.constraint, rel.commits) == (constraint, 0)


async def test_create_lets_an_unrelated_database_error_through_untouched() -> None:
    boom = IntegrityError("INSERT", {}, _PgError("23502"))
    with pytest.raises(IntegrityError) as err:
        await _repo(_Rel(boom)).create(_create())
    assert err.value is boom


async def test_malformed_ids_never_reach_the_database() -> None:
    rel = _Rel()
    repo = _repo(rel)
    assert await repo.get("nope", _new_id()) is None
    assert await repo.get(_new_id(), "nope") is None
    assert await repo.delete("nope", "nope") is False
    assert await repo.count_active("nope") == 0
    assert (await repo.list_page("nope")).rows == ()
    for write in (
        repo.update_state("nope", _new_id(), state=S.PAUSED),
        repo.update_cursor(_new_id(), "nope", cursor_ts=T0),
        repo.update_speed("nope", "nope", speed=Decimal(1)),
        repo.touch(_new_id(), "nope", T0),
    ):
        with pytest.raises(ReplaySessionNotFoundError):
            await write
    assert rel.statements == []


async def test_a_write_that_matches_nothing_is_not_found_for_a_missing_row() -> None:
    rel = _Rel(_Result(), _Result(scalar=None))
    with pytest.raises(ReplaySessionNotFoundError):
        await _repo(rel).update_state(_new_id(), _new_id(), state=S.PLAYING)
    assert (len(rel.statements), rel.commits) == (2, 0)  # the UPDATE, then the lookup


@pytest.mark.parametrize(("current", "expected"), [("destroyed", None), ("paused", S.BUFFERING)])
async def test_a_write_that_matches_nothing_is_illegal_for_a_terminal_or_stale_row(
    current: str, expected: ReplayState | None
) -> None:
    rel = _Rel(_Result(), _Result(scalar=current))
    with pytest.raises(ReplaySessionIllegalUpdateError) as err:
        await _repo(rel).update_state(
            _new_id(), _new_id(), state=S.PLAYING, expected_state=expected
        )
    assert (err.value.current, err.value.expected, rel.commits) == (S(current), expected, 0)


async def test_update_state_writes_the_derived_columns_and_the_compare_and_set() -> None:
    rel = _Rel(_Result([_db_row(state="error")]))
    row = await _repo(rel).update_state(
        _new_id(), _new_id(), state=S.ERROR, expected_state=S.PLAYING, error_message="source gone"
    )
    p = rel.params()
    assert (p["state"], p["error_message"], p["finished_at"]) == ("error", "source gone", None)
    assert "playing" in p.values()  # the compare-and-set value
    assert (row.state, rel.commits) == (S.ERROR, 1)


async def test_update_cursor_sets_only_what_it_was_given_and_returns_only_the_id() -> None:
    rel = _Rel(_Result([{"id": _SID}]), _Result([{"id": _SID}]))
    repo = _repo(rel)
    await repo.update_cursor(_new_id(), str(_SID), cursor_ts=T0, events_emitted=5)
    await repo.update_cursor(_new_id(), str(_SID), cursor_ts=T0, gap_warnings=1)
    first, second = rel.params(0), rel.params(1)
    assert "gap_warnings" not in first and first["events_emitted"] == 5
    assert "events_emitted" not in second and second["gap_warnings"] == 1
    assert "updated_at" not in first  # leaves the last-control-activity stamp alone
    assert "RETURNING replay_sessions.id\n" in _sql(rel.statements[0]) + "\n"
    with pytest.raises(ValueError, match="counters"):
        await repo.update_cursor(_new_id(), str(_SID), cursor_ts=T0, events_emitted=-1)


async def test_touch_and_update_speed_bump_updated_at_through_greatest() -> None:
    rel = _Rel(_Result([{"id": _SID}]), _Result([_db_row()]))
    repo = _repo(rel)
    await repo.touch(_new_id(), str(_SID), T0 + timedelta(minutes=1))
    await repo.update_speed(_new_id(), str(_SID), speed=Decimal(4))
    assert "greatest(replay_sessions.updated_at" in _sql(rel.statements[0])
    assert "greatest(replay_sessions.updated_at" in _sql(rel.statements[1])
    assert rel.params(1)["speed"] == Decimal(4)


async def test_list_page_fetches_one_extra_row_to_know_whether_a_next_page_exists() -> None:
    rows = [_db_row(created_at=T0 - timedelta(seconds=i)) for i in range(3)]
    rel = _Rel(_Result(rows))
    page = await _repo(rel).list_page(_new_id(), limit=2)
    assert (len(page.rows), rel.params()["param_1"]) == (2, 3)
    assert page.next_cursor is not None
    assert decode_cursor(page.next_cursor) == (page.rows[-1].created_at, page.rows[-1].id)
    last = await _repo(_Rel(_Result(rows[:2]))).list_page(_new_id(), limit=2)
    assert last.next_cursor is None


async def test_list_page_rejects_a_bad_cursor_and_clamps_the_limit_before_the_database() -> None:
    rel = _Rel(_Result([]))
    repo = _repo(rel)
    with pytest.raises(ReplaySessionCursorError):
        await repo.list_page(_new_id(), cursor="garbage!")
    assert rel.statements == []
    await repo.list_page(_new_id(), limit=10**6)
    assert rel.params()["param_1"] == MAX_PAGE_LIMIT + 1


async def test_list_idle_since_clamps_the_limit_and_maps_the_projection() -> None:
    rel = _Rel(_Result([{"id": _SID, "user_id": _UID, "symbol": "BTCUSDT", "state": "playing",
                         "paper_account_id": None, "updated_at": T0}]))  # fmt: skip
    (idle,) = await _repo(rel).list_idle_since(T0, 10**6)
    assert idle == IdleReplaySession(str(_SID), str(_UID), "BTCUSDT", S.PLAYING, None, T0)
    assert rel.params()["param_1"] == MAX_PAGE_LIMIT


async def test_delete_and_count_report_what_the_database_said() -> None:
    rel = _Rel(_Result([{"id": _SID}]), _Result(), _Result(scalar=3))
    repo = _repo(rel)
    assert await repo.delete(str(_UID), str(_SID)) is True
    assert await repo.delete(str(_UID), str(_SID)) is False
    assert await repo.count_active(str(_UID)) == 3
    assert rel.commits == 2
