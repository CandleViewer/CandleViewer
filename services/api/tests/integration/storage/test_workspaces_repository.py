"""Integration: `SqlAlchemyWorkspaceRepository` on real Postgres 16 (E15-T01, migration 0022).

CI-only (testcontainers; no docker socket locally).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories import workspaces_sqlalchemy as mod
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.workspaces import (
    LayoutFields,
    PaneFields,
    WorkspaceConflictError,
    WorkspaceFields,
    WorkspaceNotFoundError,
    WorkspaceVersionConflictError,
)
from candleviewer.storage.repositories.workspaces_sqlalchemy import SqlAlchemyWorkspaceRepository

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_KINDS = ("chart", "dom", "tape", "positions")
_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", None)


def _alembic(dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        check=True,
    )


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        _alembic(dsn, "upgrade", "head")
        yield dsn


def _sync(dsn: str) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _user(dsn: str) -> str:
    uid = str(uuid.uuid4())
    with _sync(dsn) as c:
        c.execute(
            "INSERT INTO users (id, email, username, password_hash) "
            "VALUES (%s, %s, %s, '$argon2id$x')",
            (uid, f"{uid[:8]}@x.io", f"user_{uid[:8]}"),
        )
    return uid


def _ws(name: str | None = None, *, default: bool = False) -> WorkspaceFields:
    return WorkspaceFields(name or f"ws-{uuid.uuid4()}", default, "workspace.default", 0)


def _pane(slot: int, **over: object) -> PaneFields:
    base: dict[str, object] = {
        "slot_index": slot, "pane_kind": _KINDS[slot % 4], "symbol": _SYMBOLS[slot % 4],
        "interval_code": "time:1" if slot % 4 != 3 else None, "chart_template_id": None,
        "indicator_preset_ids": (), "pane_config": {"sync_group": "A", "settings": {"n": 1}},
        "scale_mode": "auto",
    }  # fmt: skip
    base.update(over)
    return PaneFields(**base)  # type: ignore[arg-type]  # kwargs built from the dataclass's own fields


def _lay(
    name: str | None = None, panes: int = 4, *, default: bool = False, hotkey: int | None = None
) -> LayoutFields:
    return LayoutFields(
        name or f"lay-{uuid.uuid4()}", "2x2", None, True, False, False, hotkey, default,
        tuple(_pane(i) for i in range(panes)),
    )  # fmt: skip


def _lay_with(*panes: PaneFields) -> LayoutFields:
    return LayoutFields("L", "2x2", None, True, False, False, None, False, panes)


@pytest_asyncio.fixture
async def repo(pg_dsn: str) -> AsyncIterator[SqlAlchemyWorkspaceRepository]:
    rel = SqlAlchemyRelationalRepository(pg_dsn, "workspaces-it")
    try:
        yield SqlAlchemyWorkspaceRepository(rel)
    finally:
        await rel.dispose()


async def _new_ws(repo: SqlAlchemyWorkspaceRepository, owner: str) -> str:
    wid = str(uuid.uuid4())
    await repo.create_workspace(owner, wid, _ws())
    return wid


async def test_round_trip_four_panes_with_identical_fields(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    wid, lid = await _new_ws(repo, a), str(uuid.uuid4())
    made = await repo.create_layout(a, wid, lid, _lay())
    detail = await repo.get_workspace_detail(a, wid)
    assert detail is not None and detail.workspace.layout_count == 1
    assert detail.layouts == (made,)
    assert made.panes == tuple(_pane(i) for i in range(4)) and made.grid_spec is None


async def test_custom_grid_spec_and_empty_pane_set_round_trip(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    wid, lid = await _new_ws(repo, a), str(uuid.uuid4())
    spec = {"version": 1, "root": {"type": "leaf", "slot": 0}}
    fields = LayoutFields("c", "custom", spec, True, False, False, None, False, ())
    got = await repo.create_layout(a, wid, lid, fields)
    assert got.grid_spec == spec and got.panes == ()


async def test_replace_swaps_the_pane_set_and_bumps_the_token(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    wid, lid = await _new_ws(repo, a), str(uuid.uuid4())
    first = await repo.create_layout(a, wid, lid, _lay("L", 4))
    res = await repo.replace_layout(a, wid, lid, _lay("L", 2), if_match=first.updated_at)
    assert res.changed and len(res.row.panes) == 2 and res.row.updated_at > first.updated_at
    assert (await repo.get_layout(a, wid, lid)) == res.row


async def test_noop_put_with_stale_token_returns_unchanged_without_writing(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    wid, lid = await _new_ws(repo, a), str(uuid.uuid4())
    pane = _pane(0, pane_config={"settings": {"n": 1, "x": 1.5, "on": True}})
    made = await repo.create_layout(a, wid, lid, _lay_with(pane))
    same = _lay_with(_pane(0, pane_config={"settings": {"on": True, "x": 1.5, "n": 1}}))
    stale = made.updated_at - timedelta(seconds=5)
    res = await repo.replace_layout(a, wid, lid, same, if_match=stale)
    assert not res.changed and res.row.updated_at == made.updated_at


@pytest.mark.parametrize(("old", "new"), [(1, True), (1, 1.0), (True, 1), (0, False)])
async def test_number_kind_change_in_pane_config_is_written_not_a_noop(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str, old: object, new: object
) -> None:
    a = _user(pg_dsn)
    wid, lid = await _new_ws(repo, a), str(uuid.uuid4())
    made = await repo.create_layout(
        a, wid, lid, _lay_with(_pane(0, pane_config={"settings": {"n": old}}))
    )
    res = await repo.replace_layout(
        a, wid, lid, _lay_with(_pane(0, pane_config={"settings": {"n": new}})), if_match=None
    )
    assert res.changed and res.row.updated_at > made.updated_at
    stored = await repo.get_layout(a, wid, lid)
    assert stored is not None
    assert json.dumps(stored.panes[0].pane_config) == json.dumps({"settings": {"n": new}})


async def test_stale_token_raises_412_and_keeps_the_layout(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    wid, lid = await _new_ws(repo, a), str(uuid.uuid4())
    made = await repo.create_layout(a, wid, lid, _lay("L", 4))
    with pytest.raises(WorkspaceVersionConflictError):
        await repo.replace_layout(
            a, wid, lid, _lay("L", 1), if_match=made.updated_at - timedelta(seconds=1)
        )
    assert await repo.get_layout(a, wid, lid) == made


async def test_two_puts_with_one_token_give_exactly_one_winner(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    wid, lid = await _new_ws(repo, a), str(uuid.uuid4())
    made = await repo.create_layout(a, wid, lid, _lay("L", 4))
    results = await asyncio.gather(
        repo.replace_layout(a, wid, lid, _lay("L", 1), if_match=made.updated_at),
        repo.replace_layout(a, wid, lid, _lay("L", 2), if_match=made.updated_at),
        return_exceptions=True,
    )
    wins = [r for r in results if not isinstance(r, BaseException)]
    losses = [r for r in results if isinstance(r, WorkspaceVersionConflictError)]
    assert len(wins) == 1 and len(losses) == 1, results


async def test_failed_replace_rolls_back_leaving_the_old_pane_set(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    wid, lid, other = await _new_ws(repo, a), str(uuid.uuid4()), str(uuid.uuid4())
    await repo.create_layout(a, wid, other, _lay("Other", 1, hotkey=3))
    made = await repo.create_layout(a, wid, lid, _lay("L", 4))
    with pytest.raises(WorkspaceConflictError) as exc:
        await repo.replace_layout(a, wid, lid, _lay("L", 1, hotkey=3), if_match=None)
    assert (exc.value.rule, exc.value.field) == ("hotkey_slot_taken", "hotkey_slot")
    assert await repo.get_layout(a, wid, lid) == made


async def test_duplicate_slot_in_one_set_is_refused_whole(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    wid, lid = await _new_ws(repo, a), str(uuid.uuid4())
    made = await repo.create_layout(a, wid, lid, _lay("L", 4))
    dup = LayoutFields("L", "2x2", None, True, False, False, None, False, (_pane(3), _pane(3)))
    with pytest.raises(IntegrityError, match="ux_lp_slot"):
        await repo.replace_layout(a, wid, lid, dup, if_match=None)
    assert await repo.get_layout(a, wid, lid) == made


async def test_names_are_unique_case_insensitively_per_owner(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a, b = _user(pg_dsn), _user(pg_dsn)
    await repo.create_workspace(a, str(uuid.uuid4()), _ws("Scalping"))
    with pytest.raises(WorkspaceConflictError) as exc:
        await repo.create_workspace(a, str(uuid.uuid4()), _ws("scalping"))
    assert exc.value.rule == "name_taken"
    await repo.create_workspace(b, str(uuid.uuid4()), _ws("scalping"))


async def test_setting_a_new_default_clears_the_old_one_atomically(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    w1, w2 = str(uuid.uuid4()), str(uuid.uuid4())
    await repo.create_workspace(a, w1, _ws(default=True))
    await repo.create_workspace(a, w2, _ws(default=True))
    rows = {r.id: r for r in await repo.list_workspaces(a, after=None, limit=10)}
    assert not rows[w1].is_default and rows[w2].is_default
    res = await repo.update_workspace(
        a, w1, WorkspaceFields("n1", True, "workspace.default", 0), if_match=None
    )
    assert res.row.is_default
    rows = {r.id: r for r in await repo.list_workspaces(a, after=None, limit=10)}
    assert not rows[w2].is_default


async def test_idor_matrix_other_owner_sees_and_changes_nothing(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a, b = _user(pg_dsn), _user(pg_dsn)
    wid, lid = await _new_ws(repo, a), str(uuid.uuid4())
    made = await repo.create_layout(a, wid, lid, _lay("L"))
    wb = await _new_ws(repo, b)
    assert await repo.get_workspace_detail(b, wid) is None
    assert await repo.get_layout(b, wid, lid) is None
    assert await repo.list_layouts(b, wid, after_id=None, limit=10) is None
    with pytest.raises(WorkspaceNotFoundError):
        await repo.update_workspace(b, wid, _ws("x"), if_match=None)
    with pytest.raises(WorkspaceNotFoundError):
        await repo.replace_layout(b, wid, lid, _lay("x"), if_match=None)
    with pytest.raises(WorkspaceNotFoundError):
        await repo.create_layout(b, wid, str(uuid.uuid4()), _lay("x"))
    with pytest.raises(WorkspaceNotFoundError):
        await repo.soft_delete_layout(b, wid, lid)
    with pytest.raises(WorkspaceNotFoundError):
        await repo.soft_delete_workspace(b, wid)
    assert await repo.exists_for_other_owner(b, "workspace", wid)
    assert await repo.exists_for_other_owner(b, "layout", lid)
    assert not await repo.exists_for_other_owner(a, "layout", lid)
    assert await repo.get_layout(a, wid, lid) == made
    # §11.3: another owner's layout addressed under the caller's OWN workspace path
    lb = str(uuid.uuid4())
    made_b = await repo.create_layout(b, wb, lb, _lay("LB"))
    assert await repo.get_layout(a, wid, lb) is None
    with pytest.raises(WorkspaceNotFoundError):
        await repo.replace_layout(a, wid, lb, _lay("hijack"), if_match=None)
    with pytest.raises(WorkspaceNotFoundError):
        await repo.soft_delete_layout(a, wid, lb)
    assert await repo.get_layout(b, wb, lb) == made_b
    assert await repo.get_layout(a, wid, lid) == made
    detail = await repo.get_workspace_detail(a, wid)
    assert detail is not None and [x.id for x in detail.layouts] == [lid]


async def test_layout_under_another_workspace_of_the_same_owner_is_not_found(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    w1, w2, lid = await _new_ws(repo, a), await _new_ws(repo, a), str(uuid.uuid4())
    await repo.create_layout(a, w1, lid, _lay("L"))
    assert await repo.get_layout(a, w2, lid) is None
    with pytest.raises(WorkspaceNotFoundError):
        await repo.replace_layout(a, w2, lid, _lay("L2"), if_match=None)


async def test_last_workspace_is_protected(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    wid = await _new_ws(repo, a)
    with pytest.raises(WorkspaceConflictError) as exc:
        await repo.soft_delete_workspace(a, wid)
    assert (exc.value.rule, exc.value.field) == ("last_workspace", "workspaceId")
    assert [r.id for r in await repo.list_workspaces(a, after=None, limit=10)] == [wid]


async def test_concurrent_delete_of_the_last_two_gives_one_204_and_one_409(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    w1, w2 = await _new_ws(repo, a), await _new_ws(repo, a)
    results = await asyncio.gather(
        repo.soft_delete_workspace(a, w1), repo.soft_delete_workspace(a, w2), return_exceptions=True
    )
    conflicts = [r for r in results if isinstance(r, WorkspaceConflictError)]
    assert len(conflicts) == 1 and results.count(None) == 1, results
    assert len(await repo.list_workspaces(a, after=None, limit=10)) == 1


async def test_soft_delete_cascades_and_purge_hard_deletes_panes_and_drawings(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    keep, gone = await _new_ws(repo, a), await _new_ws(repo, a)
    lids = [str(uuid.uuid4()), str(uuid.uuid4())]
    for lid in lids:
        await repo.create_layout(a, gone, lid, _lay(None, 4))
    did = str(uuid.uuid4())
    with _sync(pg_dsn) as c:
        c.execute(
            "INSERT INTO drawings (id, owner_user_id, symbol, layout_id, tool, geometry) "
            "VALUES (%s, %s, 'BTCUSDT', %s, 'trendline', %s::jsonb)",
            (did, a, lids[0], json.dumps({"points": []})),
        )
    await repo.soft_delete_workspace(a, gone)
    assert await repo.get_workspace_detail(a, gone) is None
    assert await repo.list_layouts(a, gone, after_id=None, limit=10) is None
    assert not await repo.is_live_layout(a, lids[0])
    with _sync(pg_dsn) as c:
        row = c.execute("SELECT deleted_at FROM drawings WHERE id = %s", (did,)).fetchone()
        assert row is not None and row[0] is not None
        assert await repo.purge_deleted(1, 100) == 0  # not old enough
        c.execute(
            "UPDATE workspaces SET deleted_at = now() - interval '2 days' WHERE id = %s", (gone,)
        )
        c.execute(
            "UPDATE layouts SET deleted_at = now() - interval '2 days' WHERE workspace_id = %s",
            (gone,),
        )
    assert await repo.purge_deleted(1, 100) == 3
    with _sync(pg_dsn) as c:
        assert c.execute(
            "SELECT count(*) FROM layout_panes WHERE layout_id = ANY(%s::uuid[])", (lids,)
        ).fetchone() == (0,)
        assert c.execute("SELECT 1 FROM drawings WHERE id = %s", (did,)).fetchone() is None
    assert (await repo.get_workspace_detail(a, keep)) is not None


async def test_purge_never_touches_another_owners_rows(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a, b = _user(pg_dsn), _user(pg_dsn)
    await _new_ws(repo, a)
    wa, wb = await _new_ws(repo, a), await _new_ws(repo, b)
    await _new_ws(repo, b)
    la, lb = str(uuid.uuid4()), str(uuid.uuid4())
    await repo.create_layout(a, wa, la, _lay(None, 2))
    await repo.create_layout(b, wb, lb, _lay(None, 2))
    await repo.soft_delete_workspace(b, wb)
    with _sync(pg_dsn) as c:
        c.execute(
            "UPDATE workspaces SET deleted_at = now() - interval '2 days' WHERE id = %s", (wb,)
        )
        c.execute("UPDATE layouts SET deleted_at = now() - interval '2 days' WHERE id = %s", (lb,))
    await repo.purge_deleted(1, 100)
    assert await repo.get_layout(a, wa, la) is not None


async def test_chart_open_probe_ignores_deleted_layouts(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    wid, lid = await _new_ws(repo, a), str(uuid.uuid4())
    symbol = "ZZZ" + uuid.uuid4().hex[:6].upper() + "USDT"
    pane = _pane(0, symbol=symbol, pane_kind="chart", interval_code="time:1")
    fields = LayoutFields("L", "1x1", None, True, False, False, None, False, (pane,))
    await repo.create_layout(a, wid, lid, fields)
    assert await repo.is_chart_open(symbol) and symbol in await repo.chart_open_symbols()
    await repo.soft_delete_layout(a, wid, lid)
    assert not await repo.is_chart_open(symbol)
    assert symbol not in await repo.chart_open_symbols()


async def test_limits_are_enforced_under_the_lock(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    wid = await _new_ws(repo, a)
    for _ in range(31):
        await _new_ws(repo, a)
    with pytest.raises(WorkspaceConflictError) as exc:
        await repo.create_workspace(a, str(uuid.uuid4()), _ws())
    assert exc.value.rule == "limit_reached"
    for _ in range(32):
        await repo.create_layout(a, wid, str(uuid.uuid4()), _lay(None, 0))
    with pytest.raises(WorkspaceConflictError) as lay:
        await repo.create_layout(a, wid, str(uuid.uuid4()), _lay(None, 0))
    assert lay.value.rule == "limit_reached"


async def test_update_workspace_with_stale_token_raises_412_and_keeps_it(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a, wid = _user(pg_dsn), str(uuid.uuid4())
    made = await repo.create_workspace(a, wid, _ws("W"))
    stale = made.updated_at - timedelta(seconds=1)
    with pytest.raises(WorkspaceVersionConflictError):
        await repo.update_workspace(
            a, wid, WorkspaceFields("X", False, "workspace.default", 0), if_match=stale
        )
    assert (await repo.get_workspace_detail(a, wid)) is not None
    fresh = await repo.update_workspace(
        a, wid, WorkspaceFields("X", False, "workspace.default", 0), if_match=made.updated_at
    )
    assert fresh.changed and fresh.row.name == "X"


async def test_cursor_paging_walks_workspaces_and_layouts_without_gaps(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    wids = [await _new_ws(repo, a) for _ in range(5)]
    seen, after = [], None
    while True:
        page = await repo.list_workspaces(a, after=after, limit=2)
        seen += [w.id for w in page]
        if len(page) < 2:
            break
        after = (page[-1].sort_order, page[-1].id)
    assert sorted(seen) == sorted(wids) and len(seen) == 5
    lids = sorted(str(uuid.uuid4()) for _ in range(5))
    for lid in lids:
        await repo.create_layout(a, wids[0], lid, _lay(None, 1))
    got: list[str] = []
    last: str | None = None
    while True:
        lay_page = await repo.list_layouts(a, wids[0], after_id=last, limit=2) or []
        got += [lay.id for lay in lay_page]
        if len(lay_page) < 2:
            break
        last = lay_page[-1].id
    assert got == lids


async def test_get_workspace_detail_runs_exactly_three_statements(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a = _user(pg_dsn)
    wid = await _new_ws(repo, a)
    for _ in range(4):
        await repo.create_layout(a, wid, str(uuid.uuid4()), _lay(None, 8))
    engine = repo._relational._engine.sync_engine
    seen: list[str] = []

    def count(conn: object, cursor: object, statement: str, *rest: object) -> None:
        if (
            statement.lstrip().upper().startswith(("SELECT", "WITH"))
            and "set_config" not in statement
        ):
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        detail = await repo.get_workspace_detail(a, wid)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert detail is not None and len(detail.layouts) == 4 and len(detail.layouts[0].panes) == 8
    assert len(seen) == 3, seen


async def test_recorder_probe_statements_use_ix_lp_symbol_at_scale(
    repo: SqlAlchemyWorkspaceRepository, pg_dsn: str
) -> None:
    a, b = _user(pg_dsn), _user(pg_dsn)
    wa, wb = await _new_ws(repo, a), await _new_ws(repo, b)
    with _sync(pg_dsn) as c:
        for owner, wid in ((a, wa), (b, wb)):
            c.execute(
                "INSERT INTO layouts (id, workspace_id, owner_user_id, name) "
                "SELECT gen_random_uuid(), %s, %s, 'ac7-' || %s || '-' || g "
                "FROM generate_series(1, 500) g",
                (wid, owner, owner[:8]),
            )
        c.execute(
            "INSERT INTO layout_panes (id, layout_id, slot_index, pane_kind, symbol) "
            "SELECT gen_random_uuid(), l.id, s, 'chart', "
            "'AC7S' || (abs(hashtext(l.id::text || s::text)) %% 200) || 'USDT' "
            "FROM layouts l CROSS JOIN generate_series(0, 15) s "
            "WHERE l.owner_user_id = ANY(%s::uuid[]) AND l.name LIKE 'ac7-%%'",
            ([a, b],),
        )
    three = [str(uuid.uuid4()) for _ in range(3)]
    fresh = {a: await _new_ws(repo, a), b: await _new_ws(repo, b)}  # bulk rows filled wa/wb's cap
    for i, lid in enumerate(three):
        owner = a if i < 2 else b
        wid = fresh[owner]
        pane = _pane(0, symbol="BTCUSDT", pane_kind="chart", interval_code="time:1")
        await repo.create_layout(
            owner,
            wid,
            lid,
            LayoutFields(f"btc-{i}", "1x1", None, True, False, False, None, False, (pane,)),
        )
    with _sync(pg_dsn) as c:
        c.execute("ANALYZE layouts")
        c.execute("ANALYZE layout_panes")
        n = c.execute(
            "SELECT count(*) FROM layouts "
            "WHERE owner_user_id = ANY(%s::uuid[]) AND name LIKE 'ac7-%%'",
            ([a, b],),
        ).fetchone()
        assert n is not None and isinstance(n[0], int) and n[0] >= 1000
        rows = c.execute(
            "SELECT lp.layout_id::text, lp.slot_index FROM layout_panes lp JOIN layouts l "
            "ON l.id = lp.layout_id WHERE lp.symbol = 'BTCUSDT' AND l.deleted_at IS NULL "
            "AND l.owner_user_id = ANY(%s::uuid[])",
            ([a, b],),
        ).fetchall()
        assert sorted(str(r[0]) for r in rows) == sorted(three)
        probe = str(mod._CHART_OPEN)
        plan = c.execute(
            "EXPLAIN (FORMAT JSON) " + probe.replace(":symbol", "'BTCUSDT'")
        ).fetchone()
        assert plan is not None
        text = json.dumps(plan[0])
        assert '"Index Name": "ix_lp_symbol"' in text, text
        assert '"Node Type": "Seq Scan"' not in text, text
        print("AC7_PLAN_JSON=" + text)
    assert await repo.is_chart_open("BTCUSDT")
    assert "BTCUSDT" in await repo.chart_open_symbols()
    assert not await repo.is_chart_open("NOPEUSDT")
