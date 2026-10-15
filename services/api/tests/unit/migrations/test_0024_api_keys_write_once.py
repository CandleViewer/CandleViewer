"""`0024_api_keys_write_once` (#2336): offline render, guarded columns, refusal text, downgrade.

Real-Postgres behaviour (refusals, M10 writes, cv_app privileges, round trip) is covered by
`tests/integration/auth/test_0024_api_keys_write_once_migration.py`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import LargeBinary

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_REV, _PREV = "0024_api_keys_write_once", "0023_replay_sessions"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"
#: The ticket's six columns plus `key_id_last4`, the display tail derived from the sealed key id.
PROTECTED = frozenset(
    {
        "id",
        "exchange_account_id",
        "key_id_enc",
        "key_id_last4",
        "secret_enc",
        "enc_nonce",
        "enc_alg",
    }
)


def _sql(direction: str, span: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", direction, span, "--sql"],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return " ".join(r.stdout.split())


def _in_order(sql: str, steps: list[str]) -> bool:
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def test_upgrade_creates_the_guard_and_revokes_delete_under_a_bounded_lock_wait() -> None:
    assert _in_order(
        _sql("upgrade", _UP),
        [
            "SET LOCAL lock_timeout = '5s';",
            "CREATE FUNCTION api_keys_write_once_check() RETURNS trigger LANGUAGE plpgsql "
            "SET search_path = pg_catalog, pg_temp AS $BODY$",
            "CREATE TRIGGER trg_api_keys_write_once BEFORE UPDATE ON api_keys "
            "FOR EACH ROW EXECUTE FUNCTION api_keys_write_once_check();",
            "ALTER TABLE api_keys ENABLE ALWAYS TRIGGER trg_api_keys_write_once;",
            "IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') "
            "THEN EXECUTE 'REVOKE DELETE ON api_keys FROM cv_app';",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )


def test_trigger_compares_exactly_the_protected_columns() -> None:
    arms = re.findall(
        r"WHEN NEW\.(\w+) IS DISTINCT FROM OLD\.(\w+) THEN '(\w+)'", _sql("upgrade", _UP)
    )
    assert all(new == old == named for new, old, named in arms)
    assert sorted(new for new, _, _ in arms) == sorted(PROTECTED)


def test_every_bytea_column_of_api_keys_is_protected() -> None:
    """Tripwire: a new sealed column fails here until it is reviewed into the write-once set."""
    sealed = {c.name for c in models.api_keys.columns if isinstance(c.type, LargeBinary)}
    assert sealed
    assert sealed <= PROTECTED


def test_refusal_names_the_column_and_never_a_value() -> None:
    """The only RAISE formats `changed`, a column-name literal; OLD and NEW values (SECRET
    class) never reach the message."""
    sql = _sql("upgrade", _UP)
    assert sql.count("RAISE") == 1
    assert re.findall(r"RAISE EXCEPTION (.+? USING ERRCODE = '\w+');", sql) == [
        "'trg_api_keys_write_once: api_keys.% is write-once; store a new row (SR-003)', "
        "changed USING ERRCODE = 'check_violation'"
    ]


def test_downgrade_regrants_delete_then_drops_the_trigger_and_function() -> None:
    assert _in_order(
        _sql("downgrade", _DOWN),
        [
            "SET LOCAL lock_timeout = '5s';",
            "THEN EXECUTE 'GRANT DELETE ON api_keys TO cv_app';",
            "DROP TRIGGER IF EXISTS trg_api_keys_write_once ON api_keys;",
            "DROP FUNCTION IF EXISTS api_keys_write_once_check();",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )


@pytest.mark.parametrize(("direction", "span"), [("upgrade", _UP), ("downgrade", _DOWN)])
def test_touches_only_api_keys_and_no_audit_table(direction: str, span: str) -> None:
    sql = _sql(direction, span)
    assert set(re.findall(r"\b(?:ON|TABLE) (\w+)", sql)) == {"api_keys"}
    assert "audit" not in sql
