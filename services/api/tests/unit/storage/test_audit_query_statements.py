"""Per-shape audit page statements (design D4, risk R5), compiled with the asyncpg dialect.

One SQL text per combination of present filters, every value bound (never inlined), no
`IS NULL OR` placeholder, and the caller's scope in the SQL itself. The same statements run
against Postgres in `tests/integration/audit/test_audit_query_page.py` (CI).
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.dialects.postgresql import asyncpg

from candleviewer.storage.repositories.audit_sqlalchemy import FTS_DOCUMENT_SQL, _page_statement

_ME, _OTHER = uuid.UUID(int=1), uuid.UUID(int=2)
_T0, _T1 = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC)
_ORDER = "ORDER BY audit_log.event_ts DESC, audit_log.id DESC LIMIT"
_TZ = "TIMESTAMP WITH TIME ZONE"
_UNSET = dict.fromkeys(set(inspect.signature(_page_statement).parameters) - {"limit"})


def _compile(**kw: Any) -> tuple[str, list[Any]]:
    statement = _page_statement(**{**_UNSET, "limit": 101, **kw})
    compiled = statement.compile(dialect=asyncpg.dialect())
    return " ".join(str(compiled).split()), list(compiled.params.values())


def test_unfiltered_page_orders_by_time_then_id() -> None:
    sql, params = _compile()
    assert "WHERE" not in sql and sql.endswith(f"{_ORDER} $1::INTEGER")
    assert params == [101]


_FILTERS: dict[str, tuple[Any, str, Any]] = {
    "actor_user_id": (str(_OTHER), "audit_log.actor_user_id = $1::UUID", _OTHER),
    "actions": (["auth.login"], "audit_log.action = ANY ($1::TEXT[])", ["auth.login"]),
    "subject_type": ("order", "audit_log.object_kind = $1::VARCHAR", "order"),
    "subject_id": ("o'1", "audit_log.object_id = $1::VARCHAR", "o'1"),
    "severity": ("error", "audit_log.severity = $1::severity", "error"),
    "outcome": ("denied", "audit_log.outcome = $1::audit_outcome", "denied"),
    "ip": ("10.0.0.1", "audit_log.actor_ip = $1", "10.0.0.1"),
    "from_ts": (_T0, f"audit_log.event_ts >= $1::{_TZ}", _T0),
    "to_ts": (_T1, f"audit_log.event_ts < $1::{_TZ}", _T1),  # `to` is exclusive
    "q": ("a b", f"{FTS_DOCUMENT_SQL} @@ websearch_to_tsquery('simple', $1::VARCHAR)", "a b"),
}


@pytest.mark.parametrize("name", sorted(_FILTERS))
def test_each_filter_adds_only_its_own_bound_predicate(name: str) -> None:
    value, predicate, bound = _FILTERS[name]
    sql, params = _compile(**{name: value})
    assert f"WHERE {predicate} {_ORDER} $2::INTEGER" in sql
    assert params == [bound, 101]


def test_filters_are_anded_without_null_placeholders() -> None:
    sql, params = _compile(**{name: value for name, (value, _, _) in _FILTERS.items()})
    assert sql.count(" AND ") == len(_FILTERS) - 1 and "IS NULL" not in sql
    assert params == [bound for _, _, bound in _FILTERS.values()] + [101]
    assert "o'1" not in sql and "10.0.0.1" not in sql  # values are bound, never inlined


def test_one_sql_text_per_filter_combination() -> None:
    same_shape = _compile(subject_id="a", ip="10.0.0.1")[0]
    assert same_shape == _compile(subject_id="b", ip="10.0.0.2")[0]
    assert same_shape != _compile(subject_id="a")[0]


def test_restricted_scope_replaces_the_requested_actor() -> None:
    """Repository-level scoping (ticket AC): another user's id is narrowed to the caller's,
    never AND-ed with it."""
    sql, params = _compile(restrict_to_actor=str(_ME), actor_user_id=str(_OTHER))
    assert sql.count("audit_log.actor_user_id = ") == 1
    assert params == [_ME, 101]
    assert _compile(restrict_to_actor=str(_ME))[1] == [_ME, 101]


def test_keyset_resumes_strictly_after_the_cursor_position() -> None:
    sql, params = _compile(after=(_T0, 42))
    keyset = f"audit_log.event_ts <= $1::{_TZ} AND (audit_log.event_ts < $2::{_TZ} OR "
    assert f"WHERE {keyset}audit_log.id < $3::BIGINT) {_ORDER} $4::INTEGER" in sql
    assert params == [_T0, _T0, 42, 101]


def test_full_text_document_is_the_index_expression() -> None:
    """ADR-0025's full-text index must be built on this exact expression, with the text
    search configuration as a literal; a bound configuration would not match the index."""
    assert FTS_DOCUMENT_SQL == (
        "to_tsvector('simple', coalesce(before_state::text, '') || ' ' || "
        "coalesce(after_state::text, '') || ' ' || coalesce(object_label, ''))"
    )
    assert "'simple'" in _compile(q="x")[0]


#: The select list of every view's page statement, then what the Owner's raw view adds.
_PAGE_SELECT = [
    "audit_log.id", "audit_log.event_ts", "audit_log.actor_user_id", "audit_log.actor_label",
    "audit_log.action", "audit_log.object_kind", "audit_log.object_id", "audit_log.outcome",
    "audit_log.severity", "audit_log.request_id", "audit_log.entry_hash", "audit_log.prev_hash",
]  # fmt: skip
_RAW_SELECT = [
    "audit_log.actor_ip", "audit_log.session_id", "audit_log.object_label", "audit_log.reason",
    "audit_log.env", "audit_log.before_state IS NULL AS before_state_is_null",
    "audit_log.after_state IS NULL AS after_state_is_null",
]  # fmt: skip
_OWNER_ONLY = {
    f"audit_log.{c}" for c in ("actor_ip", "session_id", "object_label", "reason", "env")
}
#: Every per-shape statement: unfiltered, each filter alone, all of them, a continuation,
#: and a narrowed scope.
_SHAPES: dict[str, dict[str, Any]] = {
    "none": {},
    **{name: {name: value} for name, (value, _, _) in _FILTERS.items()},
    "all": {name: value for name, (value, _, _) in _FILTERS.items()},
    "after": {"after": (_T0, 42)},
    "scoped": {"restrict_to_actor": str(_ME)},
}


def _select_list(sql: str) -> list[str]:
    head, _, _ = sql.partition(" FROM audit_log")
    assert head.startswith("SELECT ")
    return head.removeprefix("SELECT ").split(", ")


@pytest.mark.parametrize("raw", [False, True], ids=["redacted", "raw"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_no_shape_selects_a_state_and_only_raw_selects_owner_only_columns(
    shape: str, raw: bool
) -> None:
    """The page select is bounded in SQL: no view fetches `before_state`/`after_state`
    (only, for the Owner, whether each is null), and the Owner-only columns are fetched for
    the raw view alone. The `q` document reads the states in the `WHERE` clause only."""
    columns = _select_list(_compile(raw=raw, **_SHAPES[shape])[0])
    states = [c for c in columns if "before_state" in c or "after_state" in c]
    assert all(" IS NULL AS " in c for c in states)
    if raw:
        assert _OWNER_ONLY <= set(columns)
    else:
        assert _OWNER_ONLY.isdisjoint(columns) and states == []
    assert columns == _PAGE_SELECT + (_RAW_SELECT if raw else [])
