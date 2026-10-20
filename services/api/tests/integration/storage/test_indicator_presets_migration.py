"""Integration: `0040_indicator_presets` on real Postgres 16 (E13-T03, #427).

The CHECKs at their boundaries, `ux_ip_name` (case-insensitive per owner and code, the NULL-owner
namespace, a name free again after a soft delete), the 18 built-ins and their idempotent re-seed,
and the round trip with the refused downgrade. `testcontainers` in CI; not run on the laptop (no
docker socket in WSL).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.db.builtin_indicator_presets import BUILTIN_PRESETS
from candleviewer.db.seed import upsert_builtin_indicator_presets

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_BUILTINS = (
    "SELECT id::text, owner_user_id, indicator_code, name, params, style, pane_target, "
    "is_builtin, is_favourite, created_at, updated_at, deleted_at FROM indicator_presets "
    "WHERE is_builtin ORDER BY id"
)

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#427)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _user(c: Conn) -> str:
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, '$argon2id$x')",
        (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}"),
    )
    return uid


def _preset(
    c: Conn,
    owner: str | None,
    *,
    code: str = "ema",
    name: str = "Fast",
    params: str = '{"n": 9}',
    style: str = "{}",
    pane: str = "overlay",
    builtin: bool | None = None,
) -> str:
    pid, is_builtin = str(uuid.uuid4()), owner is None if builtin is None else builtin
    c.execute(
        "INSERT INTO indicator_presets (id, owner_user_id, indicator_code, name, params, style, "
        "pane_target, is_builtin) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)",
        (pid, owner, code, name, params, style, pane, is_builtin),
    )
    return pid


def test_upgrade_seeds_the_18_builtins_with_no_owner(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        rows = c.execute(_BUILTINS).fetchall()
    expected = sorted(BUILTIN_PRESETS, key=lambda p: p.id)
    assert [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[11]) for r in rows] == [
        (p.id, None, p.indicator_code, p.name, dict(p.params), {}, p.pane_target, True, False, None)
        for p in expected
    ]


async def test_reseed_is_a_noop_rows_and_updated_at_unchanged(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        before = c.execute(_BUILTINS).fetchall()
    engine = create_async_engine(pg_dsn)
    try:
        for _ in range(2):  # re-runnable: every run after the migration's inserts nothing
            async with engine.begin() as conn:
                await upsert_builtin_indicator_presets(conn)
    finally:
        await engine.dispose()
    with _conn(pg_dsn) as c:
        assert c.execute(_BUILTINS).fetchall() == before
        assert c.execute("SELECT count(*) FROM indicator_presets WHERE is_builtin").fetchone() == (
            18,
        )


def test_ip_target_and_ip_code_refuse_values_outside_their_sets(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        owner = _user(c)
        with pytest.raises(pgerr.CheckViolation):
            _preset(c, owner, name="pane", pane="main")
        for code in ("EMA", "a", "x" * 33, "ema;drop"):
            with pytest.raises(pgerr.CheckViolation):
                _preset(c, owner, code=code, name=f"code {code}")
        _preset(c, owner, code="x" * 32, name="longest code", pane="subpane")


def test_ip_builtin_owner_check_rejects_owned_builtin_and_ownerless_user_row(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        owner = _user(c)
        with pytest.raises(pgerr.CheckViolation):
            _preset(c, owner, name="owned built-in", builtin=True)
        with pytest.raises(pgerr.CheckViolation):
            _preset(c, None, name="ownerless user row", builtin=False)


def test_ip_name_len_is_1_to_80_characters(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        owner = _user(c)
        _preset(c, owner, name="é" * 80)  # characters, not bytes
        for name in ("", "x" * 81):
            with pytest.raises(pgerr.CheckViolation):
                _preset(c, owner, name=name)


_SIZE = {
    "params": "SELECT octet_length(params::text) FROM indicator_presets WHERE id = %s",
    "style": "SELECT octet_length(style::text) FROM indicator_presets WHERE id = %s",
}


@pytest.mark.parametrize("column", sorted(_SIZE))
def test_shape_checks_take_4096_bytes_of_jsonb_text_and_refuse_4097(
    pg_dsn: str, column: str
) -> None:
    """The DB half of SR-E13-06: `octet_length(<col>::text)`, Postgres's own print of the jsonb
    (`{"k": "..."}`: 9 bytes around the value), which is what the API measures too."""
    with _conn(pg_dsn) as c:
        owner = _user(c)

        def save(value: str, name: str) -> str:
            if column == "params":
                return _preset(c, owner, name=name, params=value)
            return _preset(c, owner, name=name, style=value)

        pid = save(json.dumps({"k": "v" * (4096 - 9)}), "at cap")
        assert c.execute(_SIZE[column], (pid,)).fetchone() == (4096,)
        with pytest.raises(pgerr.CheckViolation):
            save(json.dumps({"k": "v" * (4096 - 8)}), "over cap")
        for not_object in ("[]", '"x"', "1", "null"):
            with pytest.raises(pgerr.CheckViolation):
                save(not_object, f"not {not_object}")


def test_ux_ip_name_is_case_insensitive_per_owner_and_code(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        a, b = _user(c), _user(c)
        first = _preset(c, a, name="Fast")
        with pytest.raises(pgerr.UniqueViolation) as err:
            _preset(c, a, name="fast")
        assert err.value.diag.constraint_name == "ux_ip_name"
        _preset(c, b, name="fast")  # another owner
        _preset(c, a, code="sma", name="fast", params='{"n": 20}')  # another indicator
        row = c.execute("SELECT name FROM indicator_presets WHERE id = %s", (first,)).fetchone()
        assert row == ("Fast",)  # the first is untouched


def test_a_soft_deleted_name_can_be_used_again(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        a = _user(c)
        gone = _preset(c, a, name="Reuse")
        c.execute("UPDATE indicator_presets SET deleted_at = now() WHERE id = %s", (gone,))
        _preset(c, a, name="reuse")
        assert c.execute("SELECT 1 FROM indicator_presets WHERE id = %s", (gone,)).fetchone()


def test_builtins_share_one_namespace_that_a_user_copy_does_not_collide_with(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        owner = _user(c)
        _preset(c, owner, name="ema(9)")  # a user copy keeps the built-in's name
        with pytest.raises(pgerr.UniqueViolation):
            _preset(c, None, name="EMA(9)")  # a second built-in may not


def test_user_delete_cascades_their_presets_and_keeps_the_builtins(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _active_owner(c)
        owner = _user(c)
        pid = _preset(c, owner, name="cascade")
        c.execute("DELETE FROM users WHERE id = %s", (owner,))
        assert c.execute("SELECT 1 FROM indicator_presets WHERE id = %s", (pid,)).fetchone() is None
        assert c.execute("SELECT count(*) FROM indicator_presets WHERE is_builtin").fetchone() == (
            18,
        )


def _active_owner(c: Conn) -> None:
    """Keep one active owner so `trg_owner_floor_fn` allows deleting other users."""
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, display_name, password_hash, status) "
        "VALUES (%s, %s, %s, 'o', '$argon2id$x', 'active')",
        (uid, f"{uid}@example.test", f"o{uid[:12]}"),
    )
    c.execute(
        "INSERT INTO user_roles (user_id, role_id) SELECT %s, id FROM roles WHERE name = 'owner'",
        (uid,),
    )


def test_round_trip_up_down_up_with_the_refused_downgrade(pg_dsn: str) -> None:
    """C-5.2 and C-5.5: a user preset, live or soft-deleted, refuses the downgrade; the
    built-ins alone do not; `upgrade head` seeds them again."""
    prev = "0038_risk_state"
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM indicator_presets WHERE NOT is_builtin")
        owner = _user(c)
        pid = _preset(c, owner, name="blocks the downgrade")
        c.execute("UPDATE indicator_presets SET deleted_at = now() WHERE id = %s", (pid,))
        refused = _alembic(pg_dsn, "downgrade", prev)
        assert refused.returncode != 0 and "downgrade refused" in refused.stderr
        assert c.execute("SELECT to_regclass('indicator_presets')").fetchone() == (
            "indicator_presets",
        )
        c.execute("DELETE FROM indicator_presets WHERE NOT is_builtin")
        assert _alembic(pg_dsn, "downgrade", prev).returncode == 0  # built-ins alone: allowed
        assert c.execute("SELECT to_regclass('indicator_presets')").fetchone() == (None,)
        assert _alembic(pg_dsn, "upgrade", "head").returncode == 0
        assert c.execute("SELECT count(*) FROM indicator_presets WHERE is_builtin").fetchone() == (
            18,
        )
