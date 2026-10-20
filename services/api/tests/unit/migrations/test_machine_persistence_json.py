"""The `machine_persistence_json` revision (#3857): the four seal- and digest-bearing columns
become `json`. The tests find it by its slug and read its id from the file, so its number lives
there alone.
Offline render both ways, the parent, the stamp-once function's text comparison, the models, the
revision register and the security-review flag. Real Postgres, with the byte-faithful round trip:
`tests/integration/storage/test_machine_persistence_json_migration.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import JSON, JSONB
from sqlalchemy.engine import Dialect, make_url

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_VERSIONS = _ROOT / "candleviewer" / "migrations" / "versions"
_CREATOR = "0033_machine_persistence"


def _find(slug: str) -> str:
    """The id of the one revision whose file ends with `slug`, read from its `revision` line."""
    (path,) = _VERSIONS.glob(f"[0-9][0-9][0-9][0-9]_{slug}.py")
    found = re.search(r'^revision: str = "(\w+)"$', path.read_text("utf-8"), re.M)
    assert found is not None and path.stem == found[1]
    return found[1]


_REV = _find("machine_persistence_json")
#: 24 Sec.17.6 "Payload columns are `json`, not `jsonb`".
_COLUMNS = {
    "machine_snapshots": ("snapshot",),
    "machine_drain_journal": ("payload",),
    "machine_events": ("payload", "fault"),
}
_TO_JSON = [
    "ALTER TABLE machine_snapshots ALTER COLUMN snapshot TYPE json USING snapshot::json;",
    "ALTER TABLE machine_drain_journal ALTER COLUMN payload TYPE json USING payload::json;",
    "ALTER TABLE machine_events ALTER COLUMN payload TYPE json USING payload::json, "
    "ALTER COLUMN fault TYPE json USING fault::json;",
]
_TO_JSONB = [
    "ALTER TABLE machine_events ALTER COLUMN fault TYPE jsonb USING fault::jsonb, "
    "ALTER COLUMN payload TYPE jsonb USING payload::jsonb;",
    "ALTER TABLE machine_drain_journal ALTER COLUMN payload TYPE jsonb USING payload::jsonb;",
    "ALTER TABLE machine_snapshots ALTER COLUMN snapshot TYPE jsonb USING snapshot::jsonb;",
]
_BY_VALUE = "WHEN NEW.payload IS DISTINCT FROM OLD.payload THEN 'payload'"
_LOCK = "LOCK TABLE machine_snapshots, machine_drain_journal, machine_events IN SHARE MODE;"
_BY_TEXT = "WHEN NEW.payload::text IS DISTINCT FROM OLD.payload::text THEN 'payload'"


def _parent(revision: str) -> str:
    """A revision's parent, read from its own file, so re-parenting never touches this module."""
    text = (_VERSIONS / f"{revision}.py").read_text("utf-8")
    found = re.search(r'^down_revision: str \| None = "(\w+)"$', text, re.M)
    assert found is not None
    return found[1]


def _revision_text() -> str:
    return (_VERSIONS / f"{_REV}.py").read_text("utf-8")


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#3857)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments, collapse whitespace and the space after `(`, so layout never matters."""
    return " ".join(re.sub(r"--[^\n]*", "", sql).split()).replace("( ", "(")


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", f"{_parent(_REV)}:{_REV}", "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", f"{_REV}:{_parent(_REV)}", "--sql"))


def _guard(sql: str) -> str:
    """The stamp-once function a render creates, from its header to the end of its body."""
    found = re.search(
        r"CREATE (?:OR REPLACE )?FUNCTION machine_drain_journal_stamp_once\(\).*?END \$BODY\$;", sql
    )
    assert found is not None
    return found[0]


@cache
def _as_created() -> str:
    """The function as `0033_machine_persistence` created it, from that revision's own render."""
    up = _norm(_alembic("upgrade", f"{_parent(_CREATOR)}:{_CREATOR}", "--sql"))
    return _guard(up).replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def _in_order(sql: str, steps: list[str]) -> bool:
    missing = [step for step in steps if step not in sql]
    assert not missing, f"not in the rendered SQL: {missing}"
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def test_revision_chains_onto_its_parent_as_its_only_child() -> None:
    """The parent lives in `down_revision` alone (0034 until E42-T10's 0035 lands), so a re-parent
    is a one-line change; nothing else branches off it (`test_single_head.py` is tip-agnostic)."""
    parent = _parent(_REV)
    assert re.fullmatch(r"\d{4}_\w+", parent) and parent < _REV
    children = re.findall(rf"^{parent} -> (\w+)", _alembic("history", "-r", f"{parent}:"), re.M)
    assert children == [_REV]
    head = _revision_text().split("\ndown_revision: ", 1)[0]
    assert parent not in head  # the docstring names no parent: one place to change


def test_upgrade_alters_the_four_columns_then_compares_payload_by_its_text() -> None:
    """`json` has no equality operator, so the stamp-once function's `IS DISTINCT FROM` on
    `payload` would fail every journal UPDATE (42883); its replacement compares the text."""
    up = _up()
    assert _in_order(
        up,
        [
            "SET LOCAL lock_timeout = '5s';",
            *_TO_JSON,
            "CREATE OR REPLACE FUNCTION machine_drain_journal_stamp_once()",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )
    assert _BY_VALUE in _as_created()
    assert _guard(up) == _as_created().replace(_BY_VALUE, _BY_TEXT)


def test_downgrade_restores_0033s_function_then_casts_the_columns_back() -> None:
    """An empty database is downgraded symmetrically, once the populated-table guard passed."""
    down = _down()
    assert _in_order(
        down,
        [
            "SET LOCAL lock_timeout = '5s';",
            _LOCK,
            "CREATE OR REPLACE FUNCTION machine_drain_journal_stamp_once()",
            *_TO_JSONB,
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )
    assert _guard(down) == _as_created()


def test_the_downgrade_refuses_naming_the_table_while_any_table_holds_a_row() -> None:
    """0033's guard (C-5.2): the cast back to `jsonb` would re-render sealed numbers, so a
    populated database fixes forward. Each refusal names its table, never a value."""
    down = _down()
    guards = re.findall(
        r"IF EXISTS \(SELECT 1 FROM (\w+)\) THEN RAISE EXCEPTION "
        r"'machine_persistence_json downgrade refused: (\w+) holds rows;[^']*\(C-5\.2\)';",
        down,
    )
    assert guards == [(name, name) for name in _COLUMNS]
    assert _in_order(down, [_LOCK, "DO $BODY$", *(f"FROM {name})" for name in _COLUMNS)])
    assert down.index("END $BODY$;") < down.index("CREATE OR REPLACE FUNCTION")
    guard = down.split("CREATE OR REPLACE", 1)[0]  # the function after it raises its own refusal
    assert guard.count("RAISE EXCEPTION") == 3 and "%" not in guard


def test_each_direction_touches_only_the_four_columns_and_the_function() -> None:
    """No other DDL, no data statement, no grant: comments, CHECKs, keys and indexes stay; the
    downgrade's one addition is the guard, which reads and locks."""
    assert _LOCK not in _up() and _down().count("LOCK TABLE ") == 1
    for sql in (_up(), _down()):
        assert sql.count("ALTER TABLE ") == 3 and sql.count("ALTER COLUMN ") == 4
        assert sql.count("CREATE ") == 1 and sql.count("FUNCTION ") == 1
        for absent in (
            "DROP ", "INSERT ", "DELETE ", "TRUNCATE", "GRANT ", "REVOKE ", "COMMENT ON",
            "CREATE TABLE", "CREATE INDEX", "CREATE TRIGGER", "IF NOT EXISTS",
        ):  # fmt: skip
            assert absent not in sql, absent


def test_the_models_type_the_four_columns_json_and_no_other_column_of_the_tables() -> None:
    """`alembic check` diffs the database against `db.models`, so the models carry the type."""
    for name, columns in _COLUMNS.items():
        table = getattr(models, name)
        assert isinstance(table, Table)
        json_columns = [c.name for c in table.columns if isinstance(c.type, JSON | JSONB)]
        assert json_columns == list(columns)
        assert all(type(table.c[column].type) is JSON for column in columns), name


def test_fault_binds_python_none_as_sql_null_and_the_payloads_never_do() -> None:
    """`me_fault_phase` holds a row with no fault only when `fault` IS NULL, and the JSON type binds
    Python None as JSON `null` unless `none_as_null`: so `fault` sets it, on the driver the stores
    use, and the three NOT NULL payload columns keep the default."""
    asyncpg: Dialect = make_url("postgresql+asyncpg://").get_dialect()()

    def bound(table: str, column: str, value: object) -> object:
        column_type = getattr(models, table).c[column].type
        process = column_type.dialect_impl(asyncpg).bind_processor(asyncpg)
        assert process is not None
        return process(value)

    assert bound("machine_events", "fault", None) is None
    assert bound("machine_events", "fault", {"failed": []}) == '{"failed": []}'
    for table, column in (
        ("machine_snapshots", "snapshot"),
        ("machine_drain_journal", "payload"),
        ("machine_events", "payload"),
    ):
        assert bound(table, column, None) == "null", (table, column)


def test_the_revision_register_lists_the_revision() -> None:
    """21 Sec.9.4 keeps a row per landed revision (C-11.2: the docs reflect what ships)."""
    doc = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
    assert f"| `{_REV}` " in doc.read_text(encoding="utf-8").split("### 9.4 ", 1)[1]


def test_the_revision_is_flagged_for_security_review_on_each_table() -> None:
    """CI-MIG-006 (`tools/ci/security-sensitive-tables.txt`): signed state and audit-class
    storage, so the revision raises the security-review flag for each of the three tables. The
    lint matches quoted names only, so the revision lists the tables its SQL alters."""
    declared = re.search(r"^ALTERED_TABLES: Final = (\(.*\))$", _revision_text(), re.M)
    assert declared is not None
    assert sorted(re.findall(r'"(\w+)"', declared[1])) == sorted(_COLUMNS)
    assert sorted(set(re.findall(r"ALTER TABLE (\w+)", _up()))) == sorted(_COLUMNS)
    lint = _ROOT.parents[1] / "tools" / "ci" / "migration_lint.py"
    r = subprocess.run(  # noqa: S603 -- fixed argv, the repo's own lint script, no shell (#3857)
        [sys.executable, str(lint), "--versions-dir", str(_VERSIONS)],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    for table in _COLUMNS:
        warning = f"WARN CI-MIG-006: {_VERSIONS / f'{_REV}.py'}: touches security-sensitive table"
        assert f"{warning} '{table}'" in r.stderr
