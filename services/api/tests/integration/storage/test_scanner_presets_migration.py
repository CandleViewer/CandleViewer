"""Integration: `0054_scanner_presets` on real Postgres 16 (E08-T09 PR 2a, #4708).

The CHECKs at their boundaries, `ux_sp_name` (case-insensitive per user, by Postgres's
`lower()`), `ux_sp_default` (one default per user), the widened `lp_kind`, the user cascade, and
the round trip with both refused downgrades. `testcontainers`; CI's `integration` job.
"""

from __future__ import annotations

import importlib.util
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
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_REVISION_FILE = _ROOT / "candleviewer" / "migrations" / "versions" / "0054_scanner_presets.py"

Conn = psycopg.Connection[tuple[Any, ...]]


def _down_revision() -> str:
    spec = importlib.util.spec_from_file_location("rev_0054_it", _REVISION_FILE)
    assert spec is not None and spec.loader is not None
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return str(revision.down_revision)


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#4708)
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
    c: Conn, owner: str, name: str = "Momentum", *, flt: str = "{}", sort: str = "turnover_24h",
    default: bool = False, version: int = 1,
) -> str:  # fmt: skip
    pid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO scanner_presets (id, user_id, name, filter, sort, is_default, version) "
        "VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)",
        (pid, owner, name, flt, sort, default, version),
    )
    return pid


def test_defaults_fill_an_insert_that_names_only_the_owner_and_the_name(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        owner, pid = _user(c), str(uuid.uuid4())
        c.execute("INSERT INTO scanner_presets (id, user_id, name) VALUES (%s, %s, 'x')",
                  (pid, owner))  # fmt: skip
        row = c.execute("SELECT filter, sort, is_default, version FROM scanner_presets "
                        "WHERE id = %s", (pid,)).fetchone()  # fmt: skip
        assert row == ({}, "turnover_24h", False, 1)


def test_the_checks_refuse_their_boundaries(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        owner = _user(c)
        _preset(c, owner, "é" * 80)  # characters, not bytes
        for kw in (
            {"name": ""},
            {"name": "x" * 81},
            {"flt": "[]"},
            {"flt": '"x"'},
            {"sort": "Turnover"},
            {"sort": "a" * 41},
            {"sort": "1x"},
            {"version": 0},
        ):
            with pytest.raises(pgerr.CheckViolation):
                _preset(c, owner, **{"name": "ok", **kw})  # type: ignore[arg-type]  # per case
        _preset(c, owner, "sort at 40", sort="a" * 40)


def test_sp_filter_shape_takes_4096_bytes_of_jsonb_text_and_refuses_4097(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        owner = _user(c)
        pid = _preset(c, owner, "at cap", flt=json.dumps({"k": "v" * (4096 - 9)}))
        size = c.execute("SELECT octet_length(filter::text) FROM scanner_presets WHERE id = %s",
                         (pid,)).fetchone()  # fmt: skip
        assert size == (4096,)
        with pytest.raises(pgerr.CheckViolation):
            _preset(c, owner, "over cap", flt=json.dumps({"k": "v" * (4096 - 8)}))


def test_ux_sp_name_is_case_insensitive_per_user(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        a, b = _user(c), _user(c)
        _preset(c, a, "Momentum")
        with pytest.raises(pgerr.UniqueViolation) as err:
            _preset(c, a, "MOMENTUM")
        assert err.value.diag.constraint_name == "ux_sp_name"
        _preset(c, b, "momentum")


def test_ux_sp_default_keeps_one_default_per_user(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        a, b = _user(c), _user(c)
        _preset(c, a, "First", default=True)
        with pytest.raises(pgerr.UniqueViolation) as err:
            _preset(c, a, "Second", default=True)
        assert err.value.diag.constraint_name == "ux_sp_default"
        _preset(c, a, "Third")
        _preset(c, b, "Theirs", default=True)


def test_lp_kind_admits_scanner_and_still_refuses_an_unknown_kind(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        cons = c.execute("SELECT pg_get_constraintdef(oid), convalidated FROM pg_constraint "
                         "WHERE conname = 'lp_kind'").fetchone()  # fmt: skip
        assert cons is not None and "'scanner'::text" in cons[0] and cons[1] is True
        assert "'nope'" not in cons[0]


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


def test_a_user_delete_cascades_their_presets(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _active_owner(c)
        owner = _user(c)
        pid = _preset(c, owner, "cascade")
        c.execute("DELETE FROM users WHERE id = %s", (owner,))
        assert c.execute("SELECT 1 FROM scanner_presets WHERE id = %s", (pid,)).fetchone() is None


def _layout_pane(c: Conn, owner: str, kind: str) -> None:
    ws, lay = str(uuid.uuid4()), str(uuid.uuid4())
    c.execute("INSERT INTO workspaces (id, user_id, name) VALUES (%s, %s, %s)", (ws, owner, ws[:8]))
    c.execute(
        "INSERT INTO layouts (id, workspace_id, owner_user_id, name) VALUES (%s, %s, %s, %s)",
        (lay, ws, owner, lay[:8]),
    )
    c.execute(
        "INSERT INTO layout_panes (id, layout_id, slot_index, pane_kind) VALUES (%s, %s, 0, %s)",
        (str(uuid.uuid4()), lay, kind),
    )


def test_round_trip_up_down_up_with_both_refused_downgrades(pg_dsn: str) -> None:
    """C-5.2 and C-5.5: a stored preset refuses the downgrade, then a scanner pane does; with
    neither, it drops the table and narrows `lp_kind` back, and `upgrade head` restores both."""
    prev = _down_revision()
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM scanner_presets")
        owner = _user(c)
        _preset(c, owner, "blocks the downgrade")
        refused = _alembic(pg_dsn, "downgrade", prev)
        assert refused.returncode != 0 and "downgrade refused: scanner_presets" in refused.stderr
        c.execute("DELETE FROM scanner_presets")
        _layout_pane(c, owner, "scanner")
        refused = _alembic(pg_dsn, "downgrade", prev)
        assert refused.returncode != 0 and "downgrade refused: a layout" in refused.stderr
        assert c.execute("SELECT to_regclass('scanner_presets')").fetchone() == ("scanner_presets",)
        c.execute("DELETE FROM layout_panes WHERE pane_kind = 'scanner'")
        assert _alembic(pg_dsn, "downgrade", prev).returncode == 0
        assert c.execute("SELECT to_regclass('scanner_presets')").fetchone() == (None,)
        with pytest.raises(pgerr.CheckViolation):
            _layout_pane(c, owner, "scanner")
        assert _alembic(pg_dsn, "upgrade", "head").returncode == 0
        _layout_pane(c, owner, "scanner")
        _preset(c, owner, "after the round trip")
