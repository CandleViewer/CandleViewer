"""Shared harness for the refused-write tests (#2748, C-12.6): a statement the database refuses must
leave its repository without the row the server's `DETAIL` quotes. `server_text` is the control: it
keeps the driver's own text of each error before the unit of work strips it, so a test shows the
planted value WAS in it (never a vacuous "absent"); `assert_no_row_values` then shows it is not in
what leaves. Modules share `pg_dsn` by import, as `test_alert_owner_gate_pg.py` does."""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import event
from sqlalchemy.engine import ExceptionContext
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

_ROOT = Path(__file__).resolve().parents[2]  # services/api: where `alembic.ini` lives


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg"),
            },
            check=True,
        )
        yield dsn


def seed_user(dsn: str, **planted: str) -> str:
    """An invited user (no role, so the owner floor is not involved); `planted` sets more `users`
    columns. Returns its id."""
    uid = str(uuid.uuid4())
    base = {"id": uid, "email": f"{uid[:8]}@x.io", "username": f"u{uid[:8]}"}
    row = base | {"password_hash": "$argon2id$x"} | planted
    insert = sql.SQL("INSERT INTO users ({}) VALUES ({})").format(
        sql.SQL(", ").join(map(sql.Identifier, row)),
        sql.SQL(", ").join(sql.Placeholder() for _ in row),
    )
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        c.execute(insert, list(row.values()))
    return uid


def rendered(exc: BaseException) -> str:
    """Everything a log line or a response could make of *exc*."""
    return "".join(traceback.format_exception(exc)) + str(exc) + repr(exc)


@contextmanager
def server_text(rel: SqlAlchemyRelationalRepository) -> Iterator[list[str]]:
    """Yields the driver's own text of every error the engine reports in the block, taken in its
    `handle_error` hook: before the unit of work strips it, from the statement the adapter ran."""
    seen: list[str] = []

    def keep(ctx: ExceptionContext) -> None:
        seen.append(rendered(ctx.original_exception))

    engine = rel.engine.sync_engine
    event.listen(engine, "handle_error", keep)
    try:
        yield seen
    finally:
        event.remove(engine, "handle_error", keep)


def assert_no_row_values(exc: BaseException, seen: list[str], *planted: str | bytes) -> None:
    """Every planted value (bytea as `\\x` + hex, as the server prints it) is in the server's text,
    and none of them, nor a `DETAIL` or statement marker, is in what left as *exc*. A typed error
    is raised `from None`, which hides its `__context__` from `traceback` but not from a walker of
    it, so that is rendered too. Plant by name: `traceback` prints the calling source line."""
    shown = [v if isinstance(v, str) else "\\x" + v.hex() for v in planted]
    server = "\n".join(seen)
    left = "\n".join(rendered(e) for e in (exc, exc.__context__) if e is not None)
    for value in shown:
        assert value in server, f"control: the server's text lacks {value!r}: {server!r}"
        assert value not in left, f"{value!r} left in the error: {left!r}"
    for marker in ("Failing row", "Key (", "[SQL"):
        assert marker not in left, f"{marker!r} left in the error: {left!r}"
