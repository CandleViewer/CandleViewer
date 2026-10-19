"""`0033_order_vocabulary` (E29-T03 #847, slice 2): offline render, plan-doc parity, the model
mirror, and a downgrade that restores 0029's types and indexes exactly.
Real Postgres: `tests/integration/storage/test_order_vocabulary_migration.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

from sqlalchemy import CheckConstraint

from candleviewer.db import models
from candleviewer.storage.repositories.orders import ORDER_STATE_OF

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0033_order_vocabulary", "0032_backups_write_once"
_ADDED_STATES = ("triggered", "unknown", "quarantined", "killed", "held")
_ADDED_KINDS = ("kill", "adopt")
_ADDS = [f"ALTER TYPE order_state ADD VALUE '{v}';" for v in _ADDED_STATES]
_ADDS += [f"ALTER TYPE order_event_kind ADD VALUE '{v}';" for v in _ADDED_KINDS]
_LIFECYCLE = (
    "CREATE TYPE order_lifecycle_state AS ENUM ("
    f"{','.join(repr(v) for v in models.ORDER_LIFECYCLE_STATES)});"
)


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#847)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments, collapse whitespace, the space after `(` and the `;` alembic appends to
    a statement that has one, so layout never matters."""
    return " ".join(re.sub(r"--[^\n]*", "", sql).split()).replace("( ", "(").replace(";;", ";")


@cache
def _render(direction: str, steps: str) -> str:
    return _norm(_alembic(direction, steps, "--sql"))


def _up() -> str:
    return _render("upgrade", f"{_PREV}:{_REV}")


def _down() -> str:
    return _render("downgrade", f"{_REV}:{_PREV}")


def _sql_blocks(heading: str) -> list[str]:
    """Every ```sql block of the doc section under `heading`, normalised, in order."""
    section = _DOC.read_text(encoding="utf-8").split(heading, 1)[1]
    section = re.split(r"\n#{2,4} ", section, maxsplit=1)[0]
    return [_norm(b.split("```", 1)[0]) for b in section.split("```sql")[1:]]


def _in_order(sql: str, steps: list[str]) -> bool:
    missing = [step for step in steps if step not in sql]
    assert not missing, f"not in the rendered SQL: {missing}"
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def test_revision_chains_onto_0032() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_the_revision_register_lists_the_revision() -> None:
    """21 Sec.9.4 keeps a row per landed revision (C-11.2: the docs reflect what ships)."""
    assert f"| `{_REV}` " in _DOC.read_text(encoding="utf-8").split("### 9.4 ", 1)[1]


def test_the_values_are_committed_before_the_transaction_that_uses_them() -> None:
    """Postgres 16 refuses an enum value in the transaction that added it (55P04), and the index
    names the new ones: the `ADD VALUE`s run in the autocommit block, then the rest runs in one
    transaction with the version stamp, each part under a bounded lock wait (C-5.6)."""
    assert _in_order(
        _up(),
        [
            "COMMIT; SET lock_timeout = '5s';",
            *_ADDS,
            "RESET lock_timeout; BEGIN; SET LOCAL lock_timeout = '5s';",
            _LIFECYCLE,
            "ALTER TABLE orders ADD COLUMN lifecycle_state order_lifecycle_state;",
            "ALTER TABLE orders ADD CONSTRAINT ord_lifecycle CHECK (",
            "DROP INDEX ix_orders_open; CREATE INDEX ix_orders_open ON orders",
            "SET LOCAL lock_timeout = DEFAULT; UPDATE alembic_version",
        ],
    )


def test_the_ddl_is_the_plan_doc_verbatim_and_touches_nothing_else() -> None:
    """Sec.1.2 carries the seven `ADD VALUE`s and the new type; Sec.3.3.4's second block is the
    column and the index. Nothing is granted, written, commented or built CONCURRENTLY."""
    enums = _sql_blocks("### 1.2 Enum types")[0]
    assert all(statement in enums for statement in [*_ADDS, _LIFECYCLE])
    orders_0029, orders_0033 = _sql_blocks("#### 3.3.4 `orders`")
    assert orders_0033 in _up() and "lifecycle_state" not in orders_0029
    for absent in ("CONCURRENTLY", "INSERT INTO", "GRANT ", "REVOKE ", "COMMENT ON", "NOT EXISTS"):
        assert absent not in _up()
    assert set(re.findall(r"\b(?:TABLE|ON) (\w+)", _up())) == {"orders"}


def test_the_models_mirror_the_types_the_column_and_the_index() -> None:
    assert models.ORDER_STATES[12:] == _ADDED_STATES  # appended (21 Sec.9.3 rule 7)
    assert models.ORDER_EVENT_KINDS[14:] == _ADDED_KINDS
    assert _LIFECYCLE in _up() and models.order_lifecycle_state.create_type is False
    column = models.orders.c.lifecycle_state
    assert column.type is models.order_lifecycle_state and column.nullable
    assert (column.server_default, column.comment) == (None, None)
    assert list(models.orders.c)[-1] is column  # added last, as the ALTER TABLE adds it
    index = next(ix for ix in models.orders.indexes if ix.name == "ix_orders_open")
    where = index.dialect_options["postgresql"]["where"]
    assert f"ON orders (exchange_account_id, symbol) WHERE {where};" in _up()


def test_ord_lifecycle_admits_exactly_the_pairs_of_order_state_of() -> None:
    """`lifecycle_state` never contradicts `state`: the CHECK's pairs are `ORDER_STATE_OF`
    (24 Sec.8.2), in chart order, and the model carries the same body."""
    check = re.search(r"ADD CONSTRAINT ord_lifecycle CHECK \((.*?)\);", _up())
    assert check is not None and check[1].startswith("lifecycle_state IS NULL OR ")
    assert re.findall(r"\('(\w+)','(\w+)'\)", check[1]) == list(ORDER_STATE_OF.items())
    checks = [c for c in models.orders.constraints if isinstance(c, CheckConstraint)]
    assert [str(c.sqltext) for c in checks if str(c.name).endswith("_ord_lifecycle")] == [check[1]]


def test_the_downgrade_refuses_while_a_row_holds_an_added_value() -> None:
    """C-5.2: every added value, in every column of its type, and any `lifecycle_state`."""
    refuse = _down().split("RAISE EXCEPTION", 1)[0]
    states = "IN (" + ",".join(f"'{v}'" for v in _ADDED_STATES) + ")"
    for column in ("WHERE lifecycle_state IS NOT NULL OR state", "OR from_state", "OR to_state"):
        assert f"{column} {states}" in refuse
    assert "WHERE kind IN ('kill','adopt')" in refuse
    assert _in_order(
        _down(),
        [
            "SET LOCAL lock_timeout = '5s'; LOCK TABLE orders, order_events IN SHARE MODE;",
            f"RAISE EXCEPTION '{_REV} downgrade refused:",
            "Fix forward with a new revision instead (C-5.2)';",
            "DROP INDEX ix_orders_open; DROP INDEX ix_orders_untracked;",
            "ALTER TABLE orders DROP COLUMN lifecycle_state; DROP TYPE order_lifecycle_state;",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )


def test_the_downgrade_restores_the_types_and_indexes_0029_created() -> None:
    """0029's own `CREATE TYPE` and `CREATE INDEX` statements, each column cast back through
    text after the rename, and no renamed type left behind."""
    up_0029 = _render("upgrade", "0028_incidents_backups:0029_oms_core")
    types = re.findall(r"CREATE TYPE order_(?:state|event_kind) AS ENUM \([^)]*\);", up_0029)
    indexes = re.findall(r"CREATE INDEX ix_orders_(?:open|untracked) [^;]*;", up_0029)
    casts = [
        f"{col} TYPE {kind} USING {col}::text::{kind}"
        for col, kind in (("state", "order_state"), ("from_state", "order_state"),
                          ("to_state", "order_state"), ("kind", "order_event_kind"))
    ]  # fmt: skip
    assert len(types) == len(indexes) == 2
    assert _in_order(_down(), ["RENAME TO order_state_0033;", types[0], *casts[:3]])
    assert _in_order(_down(), ["RENAME TO order_event_kind_0033;", types[1], casts[3], *indexes])
    for name in ("order_state", "order_event_kind"):
        assert _in_order(_down(), [f"RENAME TO {name}_0033;", f"DROP TYPE {name}_0033;"])
