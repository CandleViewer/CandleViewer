"""The stuck-order detector's three statements (E29-T08 #916; 24-internal-schemas.md Sec.8.13,
BQ-3), compiled with the PostgreSQL dialect as they run, each list a literal-execute parameter
rendered: every predicate a partial index names is a literal in the SQL, so the planner can match
`ix_orders_inflight`, `ix_orders_open` and `ix_pos_no_sl` whatever plan it caches, and the
caller's environment stays bound. The statements run on Postgres in
`tests/integration/oms/test_stuck_detection_pg.py` (CI)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.engine import Dialect, make_url

from candleviewer.domain.primitives import Environment
from candleviewer.storage.repositories.stuck_sqlalchemy import (
    in_flight_statement,
    naked_statement,
    open_stuck_statement,
)

_IN_FLIGHT = (
    "WHERE orders.idempotency_state = 'in_flight' AND (orders.state NOT IN "
    "('cancelled', 'expired', 'filled', 'killed', 'rejected'))"
)
_OPEN = "WHERE orders.state IN ('pending_amend', 'pending_cancel', 'unknown')"
_NAKED = "WHERE positions.size > 0 AND positions.stop_loss IS NULL"
#: The PostgreSQL dialect the stores run on, typed (`postgresql.dialect` is not).
_POSTGRES: Dialect = make_url("postgresql+psycopg://").get_dialect()()


def _sql(statement: Any) -> str:
    compiled = statement.compile(dialect=_POSTGRES, compile_kwargs={"render_postcompile": True})
    return " ".join(str(compiled).split())


@pytest.mark.parametrize(
    ("build", "predicate"),
    [(in_flight_statement, _IN_FLIGHT), (open_stuck_statement, _OPEN), (naked_statement, _NAKED)],
)
def test_each_statement_names_its_partial_indexs_predicate_in_literals(
    build: Callable[[Environment, int], Any], predicate: str
) -> None:
    sql = _sql(build("demo", 200))
    assert predicate in sql
    assert "exchange_accounts.env = %(env_1)s" in sql  # the environment bound, never inlined
    assert "'demo'" not in sql
