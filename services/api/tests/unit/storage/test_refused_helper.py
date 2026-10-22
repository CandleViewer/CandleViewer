"""The refused-write helper has to be able to fail (#2748, C-12.6, C-13.2): each place a planted
value can hide, each log that can carry it and each contract is shown to trip it, with no
database. `server_text` only needs an engine to listen on, so the repository never connects."""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import AsyncIterator, Callable
from unittest.mock import MagicMock

import psycopg
import pytest
import pytest_asyncio
import structlog

from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.integration._refused import (
    Seen,
    assert_no_markers,
    assert_no_row_values,
    reachable,
    rendered_graph,
    seed_user,
    server_text,
)

_PLANTED, _BYTEA = "SECRET-LEAF", b"SECRET-URL-ENC"
Rel = SqlAlchemyRelationalRepository
Build = Callable[[], BaseException]


@pytest_asyncio.fixture
async def rel() -> AsyncIterator[Rel]:
    repo = Rel("postgresql+asyncpg://u:p@127.0.0.1:9/db", "unit")  # never connected
    yield repo
    await repo.dispose()


def _controlled(seen: Seen | None = None, printed: str = _PLANTED) -> Seen:
    """*seen* as the engine hook leaves it: the server's text holds the value and the engine's
    text a statement, the two controls the checks need."""
    seen = Seen() if seen is None else seen
    seen.append(f"the server said {printed}")
    seen.statements.append("[SQL: INSERT INTO t VALUES (...)]")
    return seen


def _leaks(exc: BaseException, seen: Seen, *planted: str | bytes) -> None:
    with pytest.raises(AssertionError, match="left in the error"):  # a leak, not a control
        assert_no_row_values(exc, seen, *planted)


def _hidden[E: BaseException](exc: E, inner: BaseException) -> E:
    """*exc* as a typed error raised `from None` over *inner*: `traceback` does not show it."""
    exc.__context__, exc.__suppress_context__ = inner, True
    return exc


class _Typed(ValueError):
    def __init__(self, orig: object) -> None:
        super().__init__("typed")
        self.orig = orig  # outside `args`, as `StatementError.orig`


def _two_deep(leaf: BaseException) -> BaseException:
    return _hidden(ValueError("typed"), _hidden(RuntimeError("mid"), leaf))


def _in_a_group_member() -> BaseException:
    member = _hidden(RuntimeError("member"), RuntimeError(_PLANTED))
    return _hidden(ValueError("typed"), ExceptionGroup("group", [member]))


def _behind_a_cycle() -> BaseException:
    a, b = RuntimeError("a"), RuntimeError(_PLANTED)
    return _hidden(ValueError("typed"), _hidden(a, _hidden(b, a)))


def _adapted() -> RuntimeError:
    """An error whose cause carries the value, as `StatementError.orig` does the driver's text."""
    adapted = RuntimeError("adapted")
    adapted.__cause__ = RuntimeError(_PLANTED)
    return adapted


_HIDDEN: dict[str, Build] = {
    "two-suppressed-links-deep": lambda: _two_deep(RuntimeError(_PLANTED)),
    "in-a-group-member": _in_a_group_member,
    "in-an-attribute": lambda: _Typed(_PLANTED),
    "behind-a-cycle": _behind_a_cycle,
    "exception-in-an-attribute": lambda: _Typed(_adapted()),
    "exception-in-a-list-attribute": lambda: _Typed([_adapted()]),
    "exception-in-a-tuple-attribute": lambda: _Typed((_adapted(),)),
}


@pytest.mark.parametrize("build", _HIDDEN.values(), ids=list(_HIDDEN))
def test_walk_a_value_out_of_traceback_reach_is_found_and_fails_the_check(build: Build) -> None:
    exc = build()
    _leaks(exc, _controlled(), _PLANTED)
    assert _PLANTED in rendered_graph(exc)  # and the walk is what shows it


def test_reachable_a_cycle_is_walked_once() -> None:
    nodes = reachable(_behind_a_cycle())
    assert len(nodes) == len({id(node) for node in nodes}) == 3


def _within_except(log: Callable[..., object], *args: object, **kwargs: object) -> None:
    """Call *log* while an exception holding the value is being handled."""
    try:
        raise RuntimeError(_PLANTED)
    except RuntimeError:
        log(*args, **kwargs)


class _Detailed(Exception):
    def __str__(self) -> str:  # the row is in the `str`, as a driver error's DETAIL, not `args`
        return f"{self.args[0]}: {_PLANTED}"


_LOGGED: dict[str, Callable[[], object]] = {
    "stdlib-warning": lambda: logging.getLogger("leak").warning("failed: %s", _PLANTED),
    "stdlib-debug": lambda: logging.getLogger("leak.sub").debug("failed: %s", _PLANTED),
    "stdlib-exception": lambda: _within_except(logging.getLogger("leak").exception, "failed"),
    "structlog-event": lambda: structlog.get_logger("leak").error("failed", error=_PLANTED),
    "structlog-exc-info": lambda: _within_except(
        structlog.get_logger("leak").error, "failed", exc_info=True
    ),
    "structlog-exception-value": lambda: structlog.get_logger("leak").error(
        "failed", error=_Detailed("primary")
    ),
}


@pytest.mark.parametrize("log", _LOGGED.values(), ids=list(_LOGGED))
def test_server_text_a_value_in_a_log_fails_the_check(rel: Rel, log: Callable[[], object]) -> None:
    with server_text(rel) as seen:
        log()
        _controlled(seen)  # as the engine hook would
    _leaks(ValueError("typed"), seen, _PLANTED)


def test_server_text_logs_without_the_value_pass_the_check(rel: Rel) -> None:
    with server_text(rel) as seen:
        logging.getLogger("leak").warning("failed: %s", "nothing")
        structlog.get_logger("leak").error("failed", error="nothing")
        _controlled(seen)
    assert sum("nothing" in line for line in seen.logs) == 2  # both were kept; neither trips it
    assert_no_row_values(ValueError("typed"), seen, _PLANTED)


def test_server_text_a_log_that_cannot_be_formatted_keeps_its_text(
    rel: Rel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(logging, "raiseExceptions", False)  # pytest's handler re-raises a bad one
    with server_text(rel) as seen:
        logging.getLogger("leak").warning("failed: %s %s", _PLANTED)  # one argument short
        _controlled(seen)
    _leaks(ValueError("typed"), seen, _PLANTED)


def test_server_text_a_log_whose_exc_info_was_cleared_keeps_its_exc_text(rel: Rel) -> None:
    record = logging.LogRecord("leak", logging.ERROR, __file__, 1, "failed", None, None)
    record.exc_text = f"Traceback (most recent call last):\nRuntimeError: {_PLANTED}"
    with server_text(rel) as seen:
        logging.getLogger("leak").handle(record)  # as a filter that cleared `exc_info` leaves it
        _controlled(seen)
    _leaks(ValueError("typed"), seen, _PLANTED)


def test_server_text_structlog_processors_are_restored_when_entering_them_fails(
    rel: Rel, monkeypatch: pytest.MonkeyPatch
) -> None:
    processors = structlog.get_config()["processors"]
    kept = list(processors)
    monkeypatch.setattr(structlog, "configure", MagicMock(side_effect=[RuntimeError("no"), None]))
    with pytest.raises(RuntimeError, match="no"), server_text(rel):
        pytest.fail("the block must not run")
    assert processors == kept


@pytest.mark.parametrize("fails", [False, True], ids=["after-the-block", "when-it-raises"])
def test_server_text_block_ends_and_the_logging_state_is_restored(rel: Rel, fails: bool) -> None:
    root, processors = logging.getLogger(), structlog.get_config()["processors"]
    level, handlers, kept = root.level, list(root.handlers), list(processors)
    with contextlib.suppress(RuntimeError), server_text(rel):
        assert (root.level, processors != kept) == (logging.DEBUG, True)  # both set inside
        if fails:
            raise RuntimeError("the block failed")
    assert (root.level, root.handlers) == (level, handlers)
    assert structlog.get_config()["processors"] is processors  # the same instance
    assert processors == kept  # and the same contents


@pytest.mark.parametrize(
    "leak",
    ["\\x" + _BYTEA.hex(), repr(_BYTEA), _BYTEA.decode("latin-1")],
    ids=["hex", "repr", "latin-1"],
)
def test_assert_no_row_values_a_bytea_in_each_form_fails(leak: str) -> None:
    _leaks(ValueError(f"typed {leak}"), _controlled(printed="\\x" + _BYTEA.hex()), _BYTEA)


def test_assert_no_row_values_nothing_planted_raises_type_error() -> None:
    with pytest.raises(TypeError, match="nothing planted"):
        assert_no_row_values(ValueError("typed"), _controlled())


def test_assert_no_row_values_a_value_missing_from_the_servers_text_fails_the_control() -> None:
    seen = Seen()
    seen.statements.append("[SQL: INSERT INTO t VALUES (...)]")
    with pytest.raises(AssertionError, match="control: the server's text lacks"):
        assert_no_row_values(ValueError("typed"), seen, _PLANTED)


_CHECKS: dict[str, Callable[[BaseException, Seen], None]] = {
    "assert_no_markers": assert_no_markers,
    "assert_no_row_values": lambda exc, seen: assert_no_row_values(exc, seen, _PLANTED),
}


@pytest.mark.parametrize("marker", ["Failing row", "Key (", "[SQL", "DETAIL:"])
@pytest.mark.parametrize("check", _CHECKS.values(), ids=list(_CHECKS))
def test_the_checks_a_marker_in_what_left_fails(
    check: Callable[[BaseException, Seen], None], marker: str
) -> None:
    with pytest.raises(AssertionError, match=re.escape(f"{marker!r} left in the error")):
        check(_two_deep(RuntimeError(marker)), _controlled())


def test_assert_no_markers_no_statement_seen_fails_the_control() -> None:
    with pytest.raises(AssertionError, match="control: the engine's text has no statement"):
        assert_no_markers(ValueError("typed"), Seen())


def test_seed_user_synthetic_email_is_on_a_reserved_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    connect = MagicMock()
    monkeypatch.setattr(psycopg, "connect", connect)
    seed_user("postgresql+asyncpg://u:p@127.0.0.1:9/db")  # no database: `connect` is a stand-in
    values = connect.return_value.__enter__.return_value.execute.call_args.args[1]
    assert [v.rsplit("@", 1)[1] for v in values if "@" in v] == ["x.invalid"]  # RFC 2606
