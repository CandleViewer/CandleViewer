"""Shared harness for the refused-write tests (#2748, C-12.6): a statement the database refuses
must leave its repository without the row the server's `DETAIL` quotes. `server_text` is the
control: for its block it keeps the driver's own text of each error before the unit of work strips
it, so a test shows the planted value WAS in it (never a vacuous "absent"), and the text of every
log line. `assert_no_row_values` then shows that what `traceback`, `str` and `repr` make of the
error and of every exception reachable from it, and the block's log text, hold none of the planted
values and no `DETAIL` or statement marker; `assert_no_markers` shows the markers alone, for a
refusal with no value to plant. Modules share `pg_dsn` by import, as `test_alert_owner_gate_pg.py`
does."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import traceback
import uuid
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
import structlog
import structlog.testing
from psycopg import sql
from sqlalchemy import event
from sqlalchemy.engine import ExceptionContext
from structlog.processors import format_exc_info
from structlog.typing import EventDict
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

_ROOT = Path(__file__).resolve().parents[2]  # services/api: where `alembic.ini` lives
# What the server's `DETAIL` and the engine's statement text carry; `DETAIL:` is asyncpg's own
# label for the former (`PostgresError.__str__`).
_MARKERS = ("Failing row", "Key (", "[SQL", "DETAIL:")


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    container = PostgresContainer("postgres:16-alpine")
    # Published on loopback only: testcontainers' `with_bind_ports` takes a host port and no
    # address, but `ports` goes to docker-py as it is, and docker-py takes `(address, port)`.
    ports: dict[Any, Any] = container.ports
    for port in ports:
        ports[port] = ("127.0.0.1", None)  # the port itself is docker's pick
    with container:
        # Read back, not assumed: a testcontainers that stopped passing `ports` to docker-py as it
        # is would leave the loop above a no-op, and the database on every interface.
        started = container.get_wrapped_container()
        started.reload()  # its `attrs` were read before the ports were published
        bound = {b["HostIp"] for binds in started.ports.values() for b in binds or []}
        assert bound == {"127.0.0.1"}, f"the Postgres port is published on {bound or 'nowhere'}"
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg"),
            },
            check=True,
            timeout=120,  # bounded, so a stuck migration fails the module instead of hanging it
        )
        yield dsn


def seed_user(dsn: str, **planted: str) -> str:
    """An invited user (no role, so the owner floor is not involved); `planted` sets more `users`
    columns (`email` and `username` default to values made from the id), but never `id`, which is
    the one returned. Returns its id."""
    if "id" in planted:
        raise TypeError("seed_user returns the id it makes: `id` is not for `planted`")
    uid = str(uuid.uuid4())
    base = {"id": uid, "email": f"{uid[:8]}@x.invalid", "username": f"u{uid[:8]}"}  # RFC 2606
    row = base | {"password_hash": "$argon2id$x"} | planted
    insert = sql.SQL("INSERT INTO users ({}) VALUES ({})").format(
        sql.SQL(", ").join(map(sql.Identifier, row)),
        sql.SQL(", ").join(sql.Placeholder() for _ in row),
    )
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        c.execute(insert, list(row.values()))
    return uid


def rendered(exc: BaseException) -> str:
    """What `traceback`, `str` and `repr` make of *exc*; `traceback` follows its chain, but not a
    suppressed link (`rendered_graph` follows those too)."""
    # The control depends on that chain: the adapted driver error's own message is only the
    # primary text, and its DETAIL reaches the rendering through `__cause__` (`raise ... from
    # error`), to asyncpg's `PostgresError.__str__`. `str(ctx.original_exception)` alone lacks it.
    return "".join(traceback.format_exception(exc)) + str(exc) + repr(exc)


def reachable(exc: BaseException) -> list[BaseException]:
    """*exc* first, then every exception reachable from it, each once: its `__cause__` and
    `__context__` even when `__suppress_context__` hides them from `traceback`, an exception
    group's members, and the exceptions its attributes hold (`StatementError.orig`), alone or in
    a list or tuple. Wider than the walk of `strip_driver_text`, the code this verifies, so a
    link the strip misses still shows."""
    nodes: list[BaseException] = []
    seen: set[int] = set()
    todo = deque([exc])
    while todo:
        node = todo.popleft()
        if id(node) in seen:
            continue
        seen.add(id(node))
        nodes.append(node)
        if isinstance(node, BaseExceptionGroup):
            todo.extend(node.exceptions)
        todo.extend(link for link in (node.__cause__, node.__context__) if link is not None)
        for value in vars(node).values():  # an attribute outside `args`
            held = value if isinstance(value, list | tuple) else [value]
            todo.extend(item for item in held if isinstance(item, BaseException))
    return nodes


def rendered_graph(exc: BaseException) -> str:
    """`rendered` and the `repr` of the attributes (an attribute outside `args` shows too) of every
    exception reachable from *exc*."""
    return "\n".join(rendered(node) + repr(vars(node)) for node in reachable(exc))


class Seen(list[str]):
    """What `server_text` kept. The list holds the driver's own text of each error in the block
    (the `DETAIL` among it); `statements` holds SQLAlchemy's text of each (the `[SQL: ...]`
    statement among it); `logs` holds the text of every log record and structlog event."""

    def __init__(self) -> None:
        super().__init__()
        self.statements: list[str] = []
        self.logs: list[str] = []


class _Records(logging.Handler):
    """Keeps the text of every record that reaches it: its message, and its traceback's text
    (`exc_info`, and the `exc_text` a formatter or a filter left when it cleared that). It fails
    closed: a record whose message cannot be formatted leaves the `repr` of the message and
    arguments."""

    def __init__(self, into: list[str]) -> None:
        super().__init__(logging.DEBUG)
        self._into = into

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
            if record.exc_info:
                text += "\n" + logging.Formatter().formatException(record.exc_info)
            if record.exc_text:
                text += "\n" + record.exc_text
            self._into.append(text)
        except Exception:  # the logging module reports it; its text is kept all the same
            self._into.append(repr((record.msg, record.args)))
            self.handleError(record)


def _event_text(event: EventDict) -> str:
    """An event as a renderer writes it: an exception value as its `str`, as production's
    redaction does (`_exception_text`); `repr` shows only its class and `args`."""
    return repr({key: str(v) if isinstance(v, BaseException) else v for key, v in event.items()})


@contextmanager
def _structlog_events() -> Iterator[list[EventDict]]:
    """The block's structlog events, each `exc_info` rendered to its traceback's text, as a
    renderer makes it. `capture_logs(processors=...)` needs structlog 25.5 and the floor is 24.1,
    so this does what it does: it keeps the processors list instance and restores it after."""
    cap = structlog.testing.LogCapture()
    processors = structlog.get_config()["processors"]
    kept = list(processors)
    try:
        processors[:] = [format_exc_info, cap]
        structlog.configure(processors=processors)
        yield cap.entries
    finally:
        processors[:] = kept
        structlog.configure(processors=processors)


@contextmanager
def server_text(rel: SqlAlchemyRelationalRepository) -> Iterator[Seen]:
    """Yields what the block's one refused statement leaves behind: the driver's own text of the
    error and SQLAlchemy's, both taken in the `handle_error` hook (before the unit of work strips
    the error, from the statement the adapter ran), and every log line of the block (stdlib
    records from the root logger at DEBUG, and structlog events). One refused statement per block:
    `seen` gathers every error in it, so another statement's text could satisfy a control."""
    seen = Seen()

    def keep(ctx: ExceptionContext) -> None:
        seen.append(rendered(ctx.original_exception))
        if ctx.sqlalchemy_exception is not None:
            seen.statements.append(rendered(ctx.sqlalchemy_exception))

    engine, root = rel.engine.sync_engine, logging.getLogger()
    level, handler = root.level, _Records(seen.logs)
    event.listen(engine, "handle_error", keep)
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        with _structlog_events() as events:
            try:
                yield seen
            finally:
                seen.logs.extend(_event_text(logged) for logged in events)
    finally:
        root.setLevel(level)
        root.removeHandler(handler)
        event.remove(engine, "handle_error", keep)


def _left(exc: BaseException, seen: Seen) -> str:
    """What left: the text of every exception reachable from *exc*, and of the block's logs."""
    return "\n".join([rendered_graph(exc), *seen.logs])


def _check_markers(left: str, seen: Seen) -> None:
    statements = "\n".join(seen.statements)
    assert "[SQL" in statements, f"control: the engine's text has no statement: {statements!r}"
    for marker in _MARKERS:
        assert marker not in left, f"{marker!r} left in the error: {left!r}"


def assert_no_markers(exc: BaseException, seen: Seen) -> None:
    """No `DETAIL` or statement marker is in what left as *exc* (`rendered_graph`) or in the
    block's logs. For a refusal with no value to plant (a domain CHECK, a trigger's fixed text).
    The `[SQL` marker is controlled: the engine's own text of the error must hold it. Limits:
    `Failing row` is case-sensitive, `DETAIL:` matches only asyncpg's `__str__`, and the `[SQL`
    control cannot hold for a refusal at COMMIT, where SQLAlchemy's `statement` is None."""
    _check_markers(_left(exc, seen), seen)


def _forms(value: str | bytes) -> tuple[str, tuple[str, ...]]:
    """The form the server prints (the control), and the forms that must not leave: a bytea is
    `\\x` + hex, as `repr` shows it, and as text."""
    if isinstance(value, str):
        return value, (value,)
    printed = "\\x" + value.hex()
    return printed, (printed, repr(value), value.decode("latin-1"))


def assert_no_row_values(exc: BaseException, seen: Seen, *planted: str | bytes) -> None:
    """Every planted value is in the server's text (a bytea as `\\x` + hex, as the server prints
    it), and none of them, nor a `DETAIL` or statement marker, is in what left as *exc*
    (`rendered_graph`: a typed error is raised `from None`, which hides its `__context__` from
    `traceback` but not from the walk) or in the block's logs. A bytea is looked for as hex, as
    `repr` shows it and as text. Plant distinctive values, by name: `traceback` prints the calling
    source line."""
    if not planted:
        raise TypeError("nothing planted, so no control: use assert_no_markers")
    server = "\n".join(seen)
    left = _left(exc, seen)
    for value in planted:
        printed, forms = _forms(value)
        assert printed in server, f"control: the server's text lacks {printed!r}: {server!r}"
        for form in forms:
            assert form not in left, f"{form!r} left in the error: {left!r}"
    _check_markers(left, seen)
