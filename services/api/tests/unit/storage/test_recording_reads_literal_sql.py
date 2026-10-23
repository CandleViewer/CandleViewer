"""The recording reads' SQL is complete literal text with bound parameters only (CI-SEC-001,
python.sqlalchemy.security.audit.avoid-sqlalchemy-text): no statement is built by concatenating
a constant. The page and the by-id read repeat one column list and JOIN, pinned here to one tuple
of column expressions (the drawings repository's approach)."""

from __future__ import annotations

import ast
import inspect

import sqlalchemy as sa

import candleviewer.storage.repositories.recording_reads_sqlalchemy as mod

_STATEMENTS = {n: v for n, v in vars(mod).items() if isinstance(v, sa.TextClause)}

RECORDED_COLUMNS = (
    "rs.id::text AS id",
    "rs.symbol::text AS symbol",
    "rs.reason::text AS reason",
    "rs.pinned",
    "rs.streams::text[] AS streams",
    "rs.orderbook_depth AS depth",
    "rs.retention_days",
    "rs.added_by::text AS added_by",
    "ls.state AS session_state",
    "ls.started_at AS session_started_at",
)
_FROM = (
    "FROM recorded_symbols rs LEFT JOIN LATERAL ("
    "SELECT s.state::text AS state, s.started_at FROM recording_sessions s "
    "WHERE s.symbol = rs.symbol AND s.recorded_symbol_id = rs.id "
    "ORDER BY s.started_at DESC, s.id DESC LIMIT 1) ls ON true "
)
_WHERE = "WHERE rs.env = CAST(:env AS exchange_env) AND rs.removed_at IS NULL "
_PREFIX = "SELECT " + ", ".join(RECORDED_COLUMNS) + " " + _FROM + _WHERE


def test_statements_are_the_three_reads() -> None:
    assert set(_STATEMENTS) == {"_PAGE", "_ONE", "_SESSIONS"}


def test_no_text_call_is_built_from_a_non_literal() -> None:
    calls = [
        n
        for n in ast.walk(ast.parse(inspect.getsource(mod)))
        if isinstance(n, ast.Call) and ast.unparse(n.func) in {"sa.text", "text"}
    ]
    assert len(calls) == len(_STATEMENTS)
    for call in calls:
        assert len(call.args) == 1
        arg = call.args[0]
        assert isinstance(arg, ast.Constant) and isinstance(arg.value, str)


def test_page_and_by_id_share_the_pinned_column_list_and_join() -> None:
    assert str(mod._PAGE).startswith(_PREFIX)
    assert str(mod._ONE) == _PREFIX + "AND rs.id = CAST(:id AS uuid)"


def test_no_module_level_sql_string_remains() -> None:
    strings = [
        n for n, v in vars(mod).items() if isinstance(v, str) and "SELECT" in v and n != "__doc__"
    ]
    assert strings == []
