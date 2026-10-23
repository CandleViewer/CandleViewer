"""Integration: `0011_recorder` + `SqlAlchemyRecorderRepository` on real Postgres 16 (E16-T01).

Covers the ticket Gherkin: round-trip, duplicate active recording, most-specific-first
policy resolution, pinned override, degenerate gap. Not run locally (no docker);
exercised by the integration CI job.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.errors import StorageConstraintViolated
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import STREAM_BY_DB_KIND, RecordedGap
from candleviewer.storage.repositories.recorder_sqlalchemy import SqlAlchemyRecorderRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.testing import StaticGapReader
from tests.unit.recorder._fakes import FakeAudit

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]


def _alembic(psycopg_dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": psycopg_dsn},
        check=True,
    )


@pytest.fixture(scope="module")
def dsns() -> Iterator[tuple[str, str]]:
    with PostgresContainer("postgres:16-alpine") as c:
        base = c.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        _alembic(base, "upgrade", "head")
        _alembic(base, "downgrade", "-1")
        _alembic(base, "upgrade", "head")
        yield base.replace("+psycopg", ""), base.replace("+psycopg", "+asyncpg")


@pytest.fixture
def conn(dsns: tuple[str, str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(dsns[0], autocommit=True) as c:
        c.execute("TRUNCATE recording_gaps, recording_sessions, recorded_symbols CASCADE")
        c.execute("DELETE FROM retention_policies WHERE scope = 'symbol'")
        c.execute(
            "INSERT INTO instruments (symbol, base_coin, status, tick_size, qty_step, "
            "min_order_qty, max_order_qty, max_leverage, raw) SELECT s, 'X', 'Trading', 1, 1, "
            "1, 1, 1, '{}' FROM unnest(ARRAY['BTCUSDT','ETHUSDT']) s ON CONFLICT DO NOTHING"
        )
        yield c


def _add(conn: psycopg.Connection, sym: str, **kw: object) -> str:
    row = conn.execute(
        "INSERT INTO recorded_symbols (id, symbol, pinned) VALUES (gen_random_uuid(), %s, %s) "
        "RETURNING id::text",
        (sym, kw.get("pinned", False)),
    ).fetchone()
    assert row is not None
    return str(row[0])


def test_seed_has_one_default_row_per_stream(conn: psycopg.Connection) -> None:
    row = conn.execute("SELECT count(*) FROM retention_policies WHERE scope='default'").fetchone()
    assert row == (8,)


def test_duplicate_active_recording_fails_on_ux_rs_symbol(conn: psycopg.Connection) -> None:
    first = _add(conn, "BTCUSDT")
    with pytest.raises(psycopg.errors.UniqueViolation) as ei:
        _add(conn, "BTCUSDT")
    assert "ux_rs_symbol" in str(ei.value)
    conn.execute("UPDATE recorded_symbols SET removed_at = now() WHERE id = %s::uuid", (first,))
    _add(conn, "BTCUSDT")


def test_degenerate_gap_rejected_by_rg_window(conn: psycopg.Connection) -> None:
    rs = _add(conn, "BTCUSDT")
    sid = conn.execute(
        "INSERT INTO recording_sessions (id, recorded_symbol_id, symbol, streams, "
        "orderbook_depth, ws_endpoint) VALUES (gen_random_uuid(), %s::uuid, 'BTCUSDT', "
        "'{trades}', 200, 'x') RETURNING id::text",
        (rs,),
    ).fetchone()
    assert sid is not None
    with pytest.raises(psycopg.errors.CheckViolation) as ei:
        conn.execute(
            "INSERT INTO recording_gaps (recording_session_id, symbol, stream, gap_start, "
            "gap_end, cause) VALUES (%s::uuid, 'BTCUSDT', 'trades', now(), now(), 'seq_jump')",
            (sid[0],),
        )
    assert "rg_window" in str(ei.value)


async def test_policy_resolution_most_specific_then_pinned(
    dsns: tuple[str, str], conn: psycopg.Connection
) -> None:
    repo = SqlAlchemyRecorderRepository(SqlAlchemyRelationalRepository(dsns[1]))
    conn.execute(
        "INSERT INTO retention_policies (id, scope, symbol, stream, retain_days) "
        "VALUES (gen_random_uuid(), 'symbol', 'ETHUSDT', 'trades', 3)"
    )
    assert await repo.resolve_policy("ETHUSDT", "trades") == 3
    assert await repo.resolve_policy("BTCUSDT", "trades") == 30
    _add(conn, "BTCUSDT", pinned=True)
    assert await repo.resolve_policy("BTCUSDT", "trades") is None
    assert await repo.resolve_policy("BTCUSDT", "klines") is None


async def test_repository_lifecycle(dsns: tuple[str, str], conn: psycopg.Connection) -> None:
    repo = SqlAlchemyRecorderRepository(SqlAlchemyRelationalRepository(dsns[1]))
    ref = {"kind": "chart", "id": "c1"}
    rid = await repo.upsert_auto("BTCUSDT", "chart_open", ref)
    assert await repo.upsert_auto("BTCUSDT", "chart_open", ref) == rid
    await repo.add_reason_ref(rid, {"kind": "position", "id": "p1"})
    row = await repo.get_by_symbol("BTCUSDT")
    assert row is not None and len(row["reason_refs"]) == 2
    await repo.remove_reason_ref(rid, ref)
    row = await repo.get_by_symbol("BTCUSDT")
    assert row is not None and row["reason_refs"] == [{"kind": "position", "id": "p1"}]
    sid = await repo.open_session(
        recorded_symbol_id=rid,
        symbol="BTCUSDT",
        streams=["trades"],
        orderbook_depth=200,
        ws_endpoint="wss://example.invalid",
    )
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    await repo.record_gap(
        session_id=sid,
        symbol="BTCUSDT",
        stream="trades",
        gap_start=t0,
        gap_end=t1,
        cause="ws_disconnect",
    )
    assert await repo.close_session(sid, "manual_stop")
    assert await repo.soft_remove(rid)
    assert await repo.list_recorded() == []


async def test_e16_t04_session_gap_coverage_round_trip(
    dsns: tuple[str, str], conn: psycopg.Connection
) -> None:
    """E16-T04: crash-close + gap + coverage query against real Postgres (tiers: no watermark
    store wired here -> all `questdb`; tier split is unit-tested)."""
    from candleviewer.recorder.coverage import CoverageService
    from candleviewer.recorder.models import RecorderSetChanged
    from candleviewer.recorder.sessions import SessionManager, to_us

    repo = SqlAlchemyRecorderRepository(SqlAlchemyRelationalRepository(dsns[1]))
    t0 = to_us(datetime(2026, 9, 1, tzinfo=UTC))
    clock = [t0]
    dead = SessionManager(repo, now_us=lambda: clock[0], audit=FakeAudit())
    ev = RecorderSetChanged(symbol="BTCUSDT", change="added", reason="manual",
                            reasons=("manual",), priority=300, auto_evictable=False,
                            ts_event=t0)  # fmt: skip
    await dead.on_set_changed(ev)
    sid = dead.live_session("BTCUSDT")
    assert sid is not None
    await repo.touch_session_events(sid, first=datetime(2026, 9, 1, 0, 0, 1, tzinfo=UTC),
                                    last=datetime(2026, 9, 1, 1, tzinfo=UTC))  # fmt: skip
    restart = to_us(datetime(2026, 9, 1, 1, 5, tzinfo=UTC))
    clock[0] = restart
    audit = FakeAudit()
    fresh = SessionManager(repo, now_us=lambda: clock[0], audit=audit)
    assert await fresh.recover_on_startup(restart) == 1
    assert audit.actions() == ["recorder.stop"]  # C-2.9: the close is audited, never skipped
    assert await repo.list_live_sessions() == []
    svc = CoverageService(repo, now_us=lambda: clock[0])
    (cov,) = await svc.coverage("BTCUSDT", ["trades"], t0, restart)
    assert [(i.lo, i.hi, i.tier) for i in cov.intervals] == [
        (t0, to_us(datetime(2026, 9, 1, 1, tzinfo=UTC)), "questdb")
    ]
    assert [g.cause for g in cov.gaps] == ["process_restart"]
    assert await svc.recording_started_at_us("BTCUSDT") == t0 + 1_000_000
    row = conn.execute(
        "SELECT state::text, end_reason FROM recording_sessions WHERE id = %s", (sid,)
    ).fetchone()
    assert row == ("stopped", "process_restart")


async def test_replay_gap_read_answers_like_the_fake_over_the_same_rows(
    dsns: tuple[str, str], conn: psycopg.Connection
) -> None:
    """E26-T02 conformance: on real Postgres, `recording_gaps` keeps the half-open window, the
    asked streams and symbol only, each row's cause, and the earliest `limit` by start, rows
    that start together in the order they were written (`id`), as `StaticGapReader` does."""
    repo = SqlAlchemyRecorderRepository(SqlAlchemyRelationalRepository(dsns[1]))
    sid = await repo.open_session(
        recorded_symbol_id=_add(conn, "BTCUSDT"),
        symbol="BTCUSDT",
        streams=["trades", "tickers", "funding"],
        orderbook_depth=200,
        ws_endpoint="wss://example.invalid",
    )
    base = datetime(2026, 10, 1, tzinfo=UTC)
    stored = [  # (symbol, Postgres stream, start s, end s, cause): window [10 s, 20 s)
        ("BTCUSDT", "trades", 12, 13, "ws_disconnect"),
        ("BTCUSDT", "trades", 5, 10, "ws_disconnect"),  # ends at the window start
        ("BTCUSDT", "trades", 20, 25, "seq_jump"),  # starts at the window end
        ("BTCUSDT", "trades", 19, 30, "process_restart"),
        ("BTCUSDT", "trades", 8, 11, "backpressure_drop"),
        ("BTCUSDT", "tickers", 14, 15, "ws_disconnect"),  # a stream not asked for
        ("BTCUSDT", "funding", 11, 12, "exchange_outage"),
        ("ETHUSDT", "trades", 12, 13, "ws_disconnect"),  # another symbol
        ("BTCUSDT", "trades", 15, 16, "seq_jump"),  # these two start together: written order,
        ("BTCUSDT", "funding", 15, 18, "ws_disconnect"),  # not the stream's name, decides
    ]
    for symbol, stream, lo, hi, cause in stored:
        await repo.record_gap(
            session_id=sid,
            symbol=symbol,
            stream=stream,
            gap_start=base + timedelta(seconds=lo),
            gap_end=base + timedelta(seconds=hi),
            cause=cause,
        )

    def us(seconds: int) -> int:
        return (base + timedelta(seconds=seconds) - datetime(1970, 1, 1, tzinfo=UTC)) // (
            timedelta(microseconds=1)
        )

    fake = StaticGapReader(
        RecordedGap(symbol, STREAM_BY_DB_KIND[stream], us(lo), us(hi), cause)
        for symbol, stream, lo, hi, cause in stored
    )
    window = TimeRange(start_us=us(10), end_us=us(20))
    asked = (StreamKind.TRADES, StreamKind.FUNDING_RATES)

    got_by_limit: dict[int, list[tuple[StreamKind, int, str]]] = {}
    for limit in (10, 4, 2):
        got = await repo.recording_gaps("BTCUSDT", window, streams=asked, limit=limit)
        want = await fake.recording_gaps("BTCUSDT", window, streams=asked, limit=limit)
        assert got == want
        got_by_limit[limit] = [(g.stream, g.start_us, g.cause) for g in got]
    assert got_by_limit[4] == [
        (StreamKind.TRADES, us(8), "backpressure_drop"),
        (StreamKind.FUNDING_RATES, us(11), "exchange_outage"),
        (StreamKind.TRADES, us(12), "ws_disconnect"),
        (StreamKind.TRADES, us(15), "seq_jump"),  # the cut falls inside the tie: `id` decides
    ]
    assert got_by_limit[2] == got_by_limit[4][:2]
    assert len(got_by_limit[10]) == 6


# --- E16-F01 manual rows: upsert_manual, clear_manual, set_pinned --------------------------------
Repo = SqlAlchemyRecorderRepository
Conn = psycopg.Connection
_CHART = {"kind": "chart", "id": "c1"}
_STATE = (
    "SELECT reason::text AS reason, reason_refs, auto_added_at, pinned, removed_at, "
    "added_by::text AS added_by, streams::text[] AS streams, orderbook_depth, updated_at "
    "FROM recorded_symbols WHERE id = %s::uuid"
)
#: The reaper's pin predicate (21 Sec.6, line 4471): the active pinned rows of a symbol.
_PINNED = "SELECT 1 FROM recorded_symbols WHERE symbol = %s AND pinned AND removed_at IS NULL"


@pytest.fixture
async def repo(dsns: tuple[str, str], conn: Conn) -> AsyncIterator[Repo]:
    relational = SqlAlchemyRelationalRepository(dsns[1])
    yield Repo(relational)
    await relational.dispose()


def _state(conn: Conn, rid: str) -> dict[str, Any]:
    """The row as it stands, removed or not."""
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(_STATE, (rid,)).fetchone()
    assert row is not None
    return row


def _user(conn: Conn) -> str:
    uid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (%s, %s, %s, '$argon2id$fixture', 'active')",
        (uid, f"{uid[:8]}@example.invalid", f"rec{uid[:8]}"),
    )
    return uid


async def _manual(repo: Repo, env: str = "live") -> str:
    return str((await repo.upsert_manual("BTCUSDT", None, (), None, env))["id"])


async def test_upsert_manual_absent_inserts_a_manual_row(repo: Repo, conn: Conn) -> None:
    user = _user(conn)
    row = await repo.upsert_manual("BTCUSDT", user, ["trades", "tickers"], 50, "demo")
    assert (row["env"], row["reason"], row["added_by"]) == ("demo", "manual", user)
    assert (row["streams"], row["orderbook_depth"]) == (["trades", "tickers"], 50)
    assert (row["pinned"], row["reason_refs"], row["auto_added_at"]) == (False, [], None)
    assert await repo.get_by_symbol("BTCUSDT", "demo") == row
    assert await repo.get_by_symbol("BTCUSDT") is None  # the live row is another one


async def test_upsert_manual_naming_no_streams_or_depth_takes_the_column_defaults(
    repo: Repo, conn: Conn
) -> None:
    defaults = _state(conn, _add(conn, "ETHUSDT"))  # a row that names neither
    row = await repo.upsert_manual("BTCUSDT", None, (), None, "live")
    assert (row["streams"], row["orderbook_depth"]) == (
        defaults["streams"],
        defaults["orderbook_depth"],
    )


async def test_upsert_manual_auto_promotes_keeping_refs_stamp_and_pin(
    repo: Repo, conn: Conn
) -> None:
    user, rid = _user(conn), await repo.upsert_auto("BTCUSDT", "chart_open", _CHART)
    assert await repo.set_pinned(rid, True)
    stamped = _state(conn, rid)["auto_added_at"]
    assert stamped is not None  # a control: there is a stamp to keep
    row = await repo.upsert_manual("BTCUSDT", user, ["trades"], 500, "live")
    after = _state(conn, rid)
    assert (row["id"], after["reason"], after["added_by"]) == (rid, "manual", user)
    assert (after["reason_refs"], after["auto_added_at"]) == ([_CHART], stamped)
    assert (after["pinned"], after["streams"], after["orderbook_depth"]) == (True, ["trades"], 500)


async def test_upsert_manual_removed_inserts_a_new_row_and_leaves_the_old(
    repo: Repo, conn: Conn
) -> None:
    old = await _manual(repo)
    assert await repo.soft_remove(old)
    removed = _state(conn, old)
    new = await repo.upsert_manual("BTCUSDT", None, (), None, "live")
    assert new["id"] != old and new["removed_at"] is None
    assert _state(conn, old) == removed  # still removed, `updated_at` included


async def test_upsert_manual_again_changes_only_what_it_names(repo: Repo, conn: Conn) -> None:
    first, second = _user(conn), _user(conn)
    rid = (await repo.upsert_manual("BTCUSDT", first, ["trades"], 50, "live"))["id"]
    row = await repo.upsert_manual("BTCUSDT", second, (), None, "live")
    assert (row["id"], row["streams"], row["orderbook_depth"]) == (rid, ["trades"], 50)
    assert row["added_by"] == second
    assert (await repo.upsert_manual("BTCUSDT", None, (), None, "live"))["added_by"] == second


async def test_upsert_manual_unknown_symbol_raises_the_foreign_key_refusal(repo: Repo) -> None:
    with pytest.raises(StorageConstraintViolated) as refused:
        await repo.upsert_manual("NOPEUSDT", None, (), None, "live")
    assert refused.value.sqlstate == "23503"
    assert refused.value.constraint == "recorded_symbols_symbol_fkey"


@pytest.mark.parametrize(
    ("refs", "reason"),
    [
        ([_CHART], "chart_open"),
        ([_CHART, {"kind": "position", "id": "p1"}], "position_open"),
        ([{"kind": "recorder", "id": "session"}], "chart_open"),  # the legacy session ref
    ],
)
async def test_clear_manual_with_refs_demotes_to_the_reason_they_imply(
    repo: Repo, conn: Conn, refs: list[dict[str, str]], reason: str
) -> None:
    rid = await _manual(repo)
    for ref in refs:
        assert await repo.add_reason_ref(rid, ref)
    assert await repo.clear_manual("BTCUSDT", "live") == "demoted"
    row = _state(conn, rid)
    assert (row["reason"], row["reason_refs"], row["removed_at"]) == (reason, refs, None)
    assert row["auto_added_at"] is not None  # `rs_autoshape` refuses the UPDATE without it


async def test_clear_manual_keeps_the_auto_added_at_a_promoted_row_has(
    repo: Repo, conn: Conn
) -> None:
    rid = await repo.upsert_auto("BTCUSDT", "chart_open", _CHART)
    stamped = _state(conn, rid)["auto_added_at"]
    await repo.upsert_manual("BTCUSDT", None, (), None, "live")
    assert await repo.clear_manual("BTCUSDT", "live") == "demoted"
    assert _state(conn, rid)["auto_added_at"] == stamped


async def test_clear_manual_without_refs_soft_removes_the_row(repo: Repo, conn: Conn) -> None:
    rid = await _manual(repo)
    assert await repo.clear_manual("BTCUSDT", "live") == "removed"
    assert _state(conn, rid)["removed_at"] is not None  # soft: the row is still there
    assert await repo.get_by_symbol("BTCUSDT") is None


@pytest.mark.parametrize("held", ["nothing", "auto-row", "removed-manual", "other-env"])
async def test_clear_manual_without_an_active_manual_row_is_absent_and_changes_nothing(
    repo: Repo, conn: Conn, held: str
) -> None:
    rid = None
    if held == "auto-row":
        rid = await repo.upsert_auto("BTCUSDT", "chart_open", _CHART)
    elif held == "removed-manual":
        rid = await _manual(repo)
        assert await repo.soft_remove(rid)
    elif held == "other-env":
        rid = await _manual(repo, "demo")
    before = None if rid is None else _state(conn, rid)
    assert await repo.clear_manual("BTCUSDT", "live") == "absent"
    assert rid is None or _state(conn, rid) == before


async def test_clear_manual_leaves_the_other_envs_row_alone(repo: Repo, conn: Conn) -> None:
    live = await _manual(repo, "live")
    demo = await _manual(repo, "demo")
    before = _state(conn, live)
    assert await repo.clear_manual("BTCUSDT", "demo") == "removed"
    assert _state(conn, demo)["removed_at"] is not None
    assert _state(conn, live) == before


@pytest.mark.parametrize("ref", [None, _CHART], ids=["no-refs", "chart-ref"])
async def test_clear_manual_on_a_pinned_row_demotes_it_and_keeps_it_active(
    repo: Repo, conn: Conn, ref: dict[str, str] | None
) -> None:
    rid = await _manual(repo)
    assert await repo.set_pinned(rid, True)
    if ref is not None:
        assert await repo.add_reason_ref(rid, ref)
    assert await repo.clear_manual("BTCUSDT", "live") == "demoted"
    row = _state(conn, rid)
    assert (row["reason"], row["pinned"], row["removed_at"]) == ("chart_open", True, None)
    assert row["auto_added_at"] is not None  # `rs_autoshape` holds
    assert conn.execute(_PINNED, ("BTCUSDT",)).fetchone() is not None  # the reaper still sees it
    assert await repo.resolve_policy("BTCUSDT", "trades") is None  # so retention stays infinite


async def test_clear_manual_racing_upsert_auto_never_loses_the_ref(repo: Repo, conn: Conn) -> None:
    for _ in range(12):  # each round: a fresh manual row with no refs, the two statements racing
        conn.execute("TRUNCATE recorded_symbols CASCADE")
        await _manual(repo)
        await asyncio.gather(
            repo.clear_manual("BTCUSDT", "live"), repo.upsert_auto("BTCUSDT", "chart_open", _CHART)
        )
        assert [r["reason_refs"] for r in await repo.list_recorded()] == [[_CHART]]


async def test_set_pinned_toggles_by_id_and_bumps_updated_at(repo: Repo, conn: Conn) -> None:
    rid = await _manual(repo)
    inserted = _state(conn, rid)["updated_at"]
    assert await repo.set_pinned(rid, True)
    pinned = _state(conn, rid)
    assert pinned["pinned"] is True and pinned["updated_at"] > inserted
    assert await repo.set_pinned(rid, False)
    assert _state(conn, rid)["pinned"] is False


async def test_set_pinned_with_a_missing_id_returns_false(repo: Repo) -> None:
    assert await repo.set_pinned(str(uuid.uuid4()), True) is False


async def test_set_pinned_on_a_removed_row_returns_false_and_leaves_it(
    repo: Repo, conn: Conn
) -> None:
    rid = await _manual(repo)
    assert await repo.soft_remove(rid)
    removed = _state(conn, rid)
    assert await repo.set_pinned(rid, True) is False
    assert _state(conn, rid) == removed
