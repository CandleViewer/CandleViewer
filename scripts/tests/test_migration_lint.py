"""Unit tests for `tools/ci/migration_lint.py` (E03-T10).

Fixture migration files (destructive annotated, destructive unannotated,
additive, ambiguous batch operations) per the ticket's test plan.
"""

from __future__ import annotations

import ast
import codecs
import hashlib
import importlib.util
import itertools
import sys
import tracemalloc
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import tools.ci.migration_lint as migration_lint
from tools.ci.migration_lint import (
    _CHAIN_HARDENING_SHA256,
    _read_revision,
    _reads_as_utf8,
    check_audit_table_integrity,
    check_destructive_annotations,
    check_if_not_exists,
    check_security_sensitive,
    main,
)

_ADDITIVE = """
from alembic import op


def upgrade() -> None:
    op.add_column("orders", sa.Column("note", sa.Text(), nullable=True))
    op.create_index("ix_orders_note", "orders", ["note"])
"""

_DESTRUCTIVE_UNANNOTATED = """
from alembic import op


def upgrade() -> None:
    op.drop_column("orders", "legacy_status")
"""

_DESTRUCTIVE_ANNOTATED = """
from alembic import op


def upgrade() -> None:
    # cv:contract-phase: R2
    op.drop_column("orders", "legacy_status")
"""

_DESTRUCTIVE_FORBIDDEN_TABLE = """
from alembic import op


def upgrade() -> None:
    # cv:contract-phase: R2
    op.drop_column("audit_log", "note")
"""

_NON_NULLABLE_ADD_NO_DEFAULT = """
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("orders", sa.Column("qty", sa.Numeric(), nullable=False))
"""

_NON_NULLABLE_ADD_WITH_DEFAULT = """
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "orders", sa.Column("qty", sa.Numeric(), nullable=False, server_default="0")
    )
"""

_TYPE_NARROWING = """
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.alter_column("orders", "qty", type_=sa.Integer())
"""

_IF_NOT_EXISTS_SQL = """
from alembic import op


def upgrade() -> None:
    op.execute("CREATE TABLE IF NOT EXISTS widgets (id uuid primary key)")
"""

_SECURITY_SENSITIVE = """
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("label", sa.Text(), nullable=True))
"""


_RAW_SQL_DELETE_AUDIT_LOG = """
from alembic import op


def upgrade() -> None:
    op.execute("DELETE FROM audit_log WHERE event_ts < now() - interval '1 year'")
"""

_RAW_SQL_UPDATE_AUDIT_LOG = """
from alembic import op


def upgrade() -> None:
    op.execute("update audit_log set outcome = 'success'")
"""

_RAW_SQL_DROP_AUDIT_CHECKPOINTS = """
from alembic import op


def upgrade() -> None:
    op.execute("DROP TABLE audit_checkpoints")
"""

_RAW_SQL_TRUNCATE_AUDIT_LOG = """
from alembic import op


def upgrade() -> None:
    op.execute("TRUNCATE audit_log")
"""

_RAW_SQL_GRANT_UPDATE_AUDIT_LOG = """
from alembic import op


def upgrade() -> None:
    op.execute("GRANT UPDATE ON audit_log TO cv_app")
"""

_RAW_SQL_GRANT_DELETE_AUDIT_LOG = """
from alembic import op


def upgrade() -> None:
    op.execute("grant delete on audit_log to cv_app")
"""

_RENAME_AUDIT_LOG = """
from alembic import op


def upgrade() -> None:
    op.rename_table("audit_log", "audit_log_old")
"""

_ALTER_COLUMN_AUDIT_LOG = """
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.alter_column("audit_log", "outcome", type_=sa.Text())
"""

_RAW_SQL_DELETE_UPPERCASE_AUDIT_LOG = """
from alembic import op


def upgrade() -> None:
    op.execute("DELETE FROM AUDIT_LOG WHERE 1=1")
"""

_RAW_SQL_GRANT_ALL_AUDIT_LOG = """
from alembic import op


def upgrade() -> None:
    op.execute("GRANT ALL ON audit_log TO cv")
"""

_RAW_SQL_GRANT_TRUNCATE_AUDIT_LOG = """
from alembic import op


def upgrade() -> None:
    op.execute("GRANT TRUNCATE ON audit_log TO cv")
"""

_RAW_SQL_GRANT_LIST_AUDIT_LOG = """
from alembic import op


def upgrade() -> None:
    op.execute("GRANT SELECT, DELETE ON audit_log TO cv")
"""

_RAW_SQL_MULTILINE_DELETE_AUDIT_LOG = """
from alembic import op


def upgrade() -> None:
    op.execute(
        "DELETE FROM audit_log WHERE event_ts < now() - interval '1 year'"
    )
"""

_RAW_SQL_INDIRECTED_DELETE_AUDIT_LOG = """
from alembic import op

_SQL = "DELETE FROM audit_log"


def upgrade() -> None:
    op.execute(_SQL)
"""

_CREATE_TABLE_AUDIT_LOG = """
from alembic import op


def upgrade() -> None:
    op.execute(
        "CREATE TABLE audit_log (id bigserial primary key, event_ts timestamptz not null)"
    )
"""

_CREATE_INDEX_ON_AUDIT_LOG = """
from alembic import op


def upgrade() -> None:
    op.execute("CREATE INDEX ix_audit_log_event_ts ON audit_log (event_ts)")
"""

_GRANT_SELECT_INSERT_AUDIT_LOG = """
from alembic import op


def upgrade() -> None:
    op.execute("GRANT SELECT, INSERT ON audit_log TO cv")
"""

_RAW_SQL_DELETE_NON_AUDIT_TABLE = """
from alembic import op


def upgrade() -> None:
    op.execute("DELETE FROM stale_sessions WHERE expires_at < now()")
"""

_RENAME_NON_AUDIT_TABLE = """
from alembic import op


def upgrade() -> None:
    op.rename_table("orders", "orders_v2")
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_additive_migration_has_no_findings(tmp_path: Path) -> None:
    path = _write(tmp_path, "0002_additive.py", _ADDITIVE)
    assert check_destructive_annotations([path]) == []
    assert check_if_not_exists([path]) == []


def test_destructive_without_annotation_is_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, "0003_destructive.py", _DESTRUCTIVE_UNANNOTATED)
    findings = check_destructive_annotations([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-003"
    assert "cv:contract-phase" in findings[0].message


def test_destructive_with_annotation_passes(tmp_path: Path) -> None:
    path = _write(tmp_path, "0004_destructive_ok.py", _DESTRUCTIVE_ANNOTATED)
    assert check_destructive_annotations([path]) == []


def test_destructive_on_forbidden_audit_table_always_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, "0005_audit_drop.py", _DESTRUCTIVE_FORBIDDEN_TABLE)
    findings = check_destructive_annotations([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-003"
    assert "append-only" in findings[0].message


def test_non_nullable_add_column_without_default_is_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, "0006_add_col.py", _NON_NULLABLE_ADD_NO_DEFAULT)
    findings = check_destructive_annotations([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-003"


def test_non_nullable_add_column_with_server_default_passes(tmp_path: Path) -> None:
    path = _write(tmp_path, "0007_add_col_default.py", _NON_NULLABLE_ADD_WITH_DEFAULT)
    assert check_destructive_annotations([path]) == []


def test_type_narrowing_without_annotation_is_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, "0008_narrow.py", _TYPE_NARROWING)
    findings = check_destructive_annotations([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-003"


def test_if_not_exists_is_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, "0009_if_not_exists.py", _IF_NOT_EXISTS_SQL)
    findings = check_if_not_exists([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-005"


def test_security_sensitive_table_is_flagged_as_warning(tmp_path: Path) -> None:
    path = _write(tmp_path, "0010_api_keys.py", _SECURITY_SENSITIVE)
    findings = check_security_sensitive(
        [path], sensitive_tables=frozenset({"api_keys"})
    )
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-006"


def test_security_sensitive_returns_empty_when_no_table_list_given(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "0011_api_keys.py", _SECURITY_SENSITIVE)
    assert check_security_sensitive([path], sensitive_tables=frozenset()) == []


def test_main_exits_zero_on_clean_versions_dir(tmp_path: Path) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    _write(versions, "0001_additive.py", _ADDITIVE)
    assert main(["--versions-dir", str(versions)]) == 0


def test_main_exits_one_on_violations(tmp_path: Path) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    _write(versions, "0001_destructive.py", _DESTRUCTIVE_UNANNOTATED)
    assert main(["--versions-dir", str(versions)]) == 1


def test_main_exits_two_when_versions_dir_missing(tmp_path: Path) -> None:
    assert main(["--versions-dir", str(tmp_path / "nope")]) == 2


@pytest.mark.parametrize(
    "fixture",
    [
        _RAW_SQL_DELETE_AUDIT_LOG,
        _RAW_SQL_UPDATE_AUDIT_LOG,
        _RAW_SQL_DROP_AUDIT_CHECKPOINTS,
        _RAW_SQL_TRUNCATE_AUDIT_LOG,
        _RAW_SQL_GRANT_UPDATE_AUDIT_LOG,
        _RAW_SQL_GRANT_DELETE_AUDIT_LOG,
        _RENAME_AUDIT_LOG,
        _ALTER_COLUMN_AUDIT_LOG,
        "\ufeff" + _RAW_SQL_DELETE_AUDIT_LOG,  # a byte-order mark: Python loads it
    ],
)
def test_audit_table_mutation_is_always_flagged(tmp_path: Path, fixture: str) -> None:
    path = _write(tmp_path, "audit_mutation.py", fixture)
    findings = check_audit_table_integrity([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-003"
    assert "append-only" in findings[0].message


@pytest.mark.parametrize(
    "fixture",
    [
        _RAW_SQL_DELETE_UPPERCASE_AUDIT_LOG,
        _RAW_SQL_GRANT_ALL_AUDIT_LOG,
        _RAW_SQL_GRANT_TRUNCATE_AUDIT_LOG,
        _RAW_SQL_GRANT_LIST_AUDIT_LOG,
        _RAW_SQL_MULTILINE_DELETE_AUDIT_LOG,
        _RAW_SQL_INDIRECTED_DELETE_AUDIT_LOG,
    ],
)
def test_audit_table_mutation_variant_is_flagged(tmp_path: Path, fixture: str) -> None:
    """Round-2 review findings: uppercase identifier, GRANT ALL/TRUNCATE,
    a grant list naming DELETE alongside harmless privileges, a multi-line
    `op.execute(\\n "...")` call, and SQL held in a variable before
    `op.execute(SQL)` must all be caught (C-5.7)."""
    path = _write(tmp_path, "audit_mutation_variant.py", fixture)
    findings = check_audit_table_integrity([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-003"
    assert "append-only" in findings[0].message


@pytest.mark.parametrize(
    "fixture",
    [
        _RAW_SQL_DELETE_NON_AUDIT_TABLE,
        _RENAME_NON_AUDIT_TABLE,
        _CREATE_TABLE_AUDIT_LOG,
        _CREATE_INDEX_ON_AUDIT_LOG,
        _GRANT_SELECT_INSERT_AUDIT_LOG,
    ],
)
def test_non_audit_table_mutation_is_not_flagged(tmp_path: Path, fixture: str) -> None:
    path = _write(tmp_path, "non_audit_mutation.py", fixture)
    assert check_audit_table_integrity([path]) == []


def test_main_flags_raw_sql_audit_mutation_end_to_end(tmp_path: Path) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    _write(versions, "0001_bad.py", _RAW_SQL_DELETE_AUDIT_LOG)
    assert main(["--versions-dir", str(versions)]) == 1


@pytest.mark.parametrize(
    "fixture",
    [_ADDITIVE, _DESTRUCTIVE_ANNOTATED],
)
def test_multiple_clean_fixtures_never_flagged(tmp_path: Path, fixture: str) -> None:
    path = _write(tmp_path, "x.py", fixture)
    assert check_if_not_exists([path]) == []


# --- Round-3 review findings -------------------------------------------------

_RAW_SQL_DELETE_AUDIT_LOG_WITH_MARKER = """
from alembic import op


def upgrade() -> None:
    op.execute("DELETE FROM audit_log")  # cv:audit-exempt: cleanup
"""

_RAW_SQL_GRANT_DELETE_QUOTED_SCHEMA_AUDIT_CHECKPOINTS = """
from alembic import op


def upgrade() -> None:
    op.execute('GRANT SELECT, DELETE ON "public"."audit_checkpoints" TO x')
"""

_RAW_SQL_FSTRING_UPDATE_AUDIT_LOG_VIA_NAME = """
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    tbl = "audit_log"
    op.execute(sa.text(f"update {tbl} set a=1"))
"""

_RAW_SQL_FSTRING_UPDATE_NON_AUDIT_TABLE_VIA_NAME = """
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    tbl = "orders"
    op.execute(sa.text(f"update {tbl} set a=1"))
"""


def test_audit_exempt_marker_never_suppresses_a_mutation(tmp_path: Path) -> None:
    """Round-3 finding 1: the marker must never exempt a genuine mutation —
    there is no escape hatch at all for a mutation keyword against an audit
    table, regardless of any trailing comment (C-5.7)."""
    path = _write(
        tmp_path, "audit_exempt_marker.py", _RAW_SQL_DELETE_AUDIT_LOG_WITH_MARKER
    )
    findings = check_audit_table_integrity([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-003"
    assert "append-only" in findings[0].message


def test_grant_delete_quoted_schema_and_table_is_flagged(tmp_path: Path) -> None:
    """Round-3 finding 2: `"public"."audit_checkpoints"` (quoted schema and
    quoted table) must be caught, not just an unquoted or table-only-quoted
    form (C-5.7)."""
    path = _write(
        tmp_path,
        "audit_grant_quoted_schema.py",
        _RAW_SQL_GRANT_DELETE_QUOTED_SCHEMA_AUDIT_CHECKPOINTS,
    )
    findings = check_audit_table_integrity([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-003"
    assert "audit_checkpoints" in findings[0].message


def test_fstring_update_via_resolved_name_constant_is_flagged(tmp_path: Path) -> None:
    """Round-3 finding 3: `tbl = "audit_log"; f"update {tbl} ..."` must
    resolve the simple `Name` placeholder to its assigned string constant and
    still be caught (C-5.7)."""
    path = _write(
        tmp_path,
        "audit_fstring_resolved.py",
        _RAW_SQL_FSTRING_UPDATE_AUDIT_LOG_VIA_NAME,
    )
    findings = check_audit_table_integrity([path])
    assert len(findings) == 1
    assert findings[0].code == "CI-MIG-003"
    assert "audit_log" in findings[0].message


def test_fstring_update_via_resolved_non_audit_name_is_not_flagged(
    tmp_path: Path,
) -> None:
    """Negative for finding 3: when the resolved name constant is not an
    audit table, no finding is raised."""
    path = _write(
        tmp_path,
        "audit_fstring_resolved_non_audit.py",
        _RAW_SQL_FSTRING_UPDATE_NON_AUDIT_TABLE_VIA_NAME,
    )
    assert check_audit_table_integrity([path]) == []


# --- Round-4 finding: unresolvable placeholder in table position (fail-closed) ---

_UNRESOLVED_CASES = {
    "end_of_string": 'op.execute(f"delete from {t}")',
    "followed_by_space": 'op.execute(f"delete from {t} where 1=1")',
    "truncate": 'op.execute(f"TRUNCATE {t}")',
    "grant_list": 'op.execute(f"GRANT SELECT, DELETE ON {t} TO cv_app")',
    "after_a_prefix": 'op.execute(f"UPDATE audit_{t} SET note = 1")',
    "inside_a_name": 'op.execute(f"UPDATE audit_{t}_log SET note = 1")',
    "quoted_after_a_prefix": """op.execute(f'DELETE FROM "audit_{t}"')""",
    "qualified_and_quoted": """op.execute(f'TRUNCATE "public"."audit_{t}"')""",
    "grant_after_a_prefix": 'op.execute(f"GRANT DELETE ON audit_{t} TO cv_app")',
}


@pytest.mark.parametrize("case", sorted(_UNRESOLVED_CASES))
def test_unresolvable_dynamic_table_in_mutation_is_flagged(
    tmp_path: Path, case: str
) -> None:
    """A table name the lint cannot resolve at lint time must be treated as
    potentially an audit table (C-5.7, fail-closed) — including when the
    placeholder ends the string or is followed by whitespace, where a trailing
    `\b` after the NUL sentinel would never match."""
    src = (
        "from alembic import op\n\n\ndef get_name():\n    return 'x'\n\n\n"
        "def upgrade() -> None:\n    t = get_name()\n    "
        + _UNRESOLVED_CASES[case]
        + "\n"
    )
    path = _write(tmp_path, f"audit_dynamic_{case}.py", src)
    findings = check_audit_table_integrity([path])
    assert len(findings) == 1, findings
    assert findings[0].code == "CI-MIG-003"


def test_unresolvable_dynamic_table_in_create_is_not_flagged(tmp_path: Path) -> None:
    src = (
        "from alembic import op\n\n\ndef get_name():\n    return 'x'\n\n\n"
        'def upgrade() -> None:\n    t = get_name()\n    op.execute(f"CREATE INDEX ix ON {t} (id)")\n'
    )
    path = _write(tmp_path, "audit_dynamic_create.py", src)
    assert check_audit_table_integrity([path]) == []


def test_create_extension_if_not_exists_is_exempt(tmp_path: Path) -> None:
    """Extensions are cluster-level objects Alembic does not own; the idempotent
    `CREATE EXTENSION IF NOT EXISTS` idiom (used by merged migration 0001) is
    not the table/index/column state the CI-MIG-005 ban targets."""
    src = (
        "from alembic import op\n\n\ndef upgrade() -> None:\n"
        '    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")\n'
        '    op.execute("CREATE TABLE IF NOT EXISTS t (id int)")\n'
    )
    path = _write(tmp_path, "0011_ext.py", src)
    findings = check_if_not_exists([path])
    assert len(findings) == 1
    assert "line 6" in findings[0].message


# --- CI-MIG-006 (#3935): a table named as an identifier, quoted or not ------------

_VERSIONS_DIR = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "api"
    / "candleviewer"
    / "migrations"
    / "versions"
)


def _raw_sql_revision(sql: str) -> str:
    """A revision whose `upgrade()` runs `sql` through `op.execute`."""
    return (
        f"from alembic import op\n\n\ndef upgrade() -> None:\n    op.execute({sql!r})\n"
    )


def _flagged(tmp_path: Path, source: str, *sensitive: str) -> list[str]:
    """The tables CI-MIG-006 flags in the revision `source`, in report order."""
    path = _write(tmp_path, "0050_touch.py", source)
    findings = check_security_sensitive([path], sensitive_tables=frozenset(sensitive))
    assert {finding.code for finding in findings} <= {"CI-MIG-006"}
    return [finding.message.split("'")[1] for finding in findings]


# Each statement names `account_profiles` as an identifier and must be flagged exactly
# as the quoted `"account_profiles"` always was.
_TOUCHES_ACCOUNT_PROFILES = [
    pytest.param("CREATE TABLE account_profiles (id uuid PRIMARY KEY)", id="create"),
    pytest.param("ALTER TABLE account_profiles ADD COLUMN note text", id="alter"),
    pytest.param("ALTER TABLE ACCOUNT_PROFILES ADD COLUMN note text", id="upper-case"),
    pytest.param('ALTER TABLE "account_profiles" ADD COLUMN note text', id="quoted"),
    pytest.param("ALTER TABLE public.account_profiles ADD COLUMN n text", id="schema"),
    pytest.param(
        'ALTER TABLE "public"."account_profiles" ADD COLUMN n text', id="quoted-schema"
    ),
    pytest.param(
        'ALTER TABLE public."account_profiles" ADD COLUMN n text', id="half-quoted"
    ),
    pytest.param("COMMENT ON COLUMN account_profiles.name IS 'label'", id="column-ref"),
    pytest.param("LOCK TABLE users, account_profiles IN SHARE MODE", id="list-member"),
    pytest.param("CREATE TABLE t (p uuid REFERENCES account_profiles (id))", id="fk"),
    pytest.param(
        "ALTER TABLE\n    account_profiles\n    ADD COLUMN note text", id="multi-line"
    ),
    pytest.param("SELECT 'account_profiles'::regclass", id="regclass-literal"),
    pytest.param(
        "DO $BODY$ BEGIN EXECUTE 'REVOKE DELETE ON account_profiles FROM cv_app'; "
        "END $BODY$;",
        id="execute-dynamic-sql",
    ),
    pytest.param(
        "CREATE FUNCTION f() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "UPDATE account_profiles SET note = NULL; RETURN NEW; END $$",
        id="dollar-quoted-body",
    ),
    pytest.param("-- don't stop here\nDROP TABLE account_profiles", id="after-comment"),
    pytest.param("SELECT '--' FROM account_profiles", id="after-comment-marker"),
    pytest.param("SELECT 'C:\\' FROM account_profiles", id="after-backslash-literal"),
    pytest.param(
        "COMMENT ON COLUMN users.n IS $$the user's note$$; "
        "ALTER TABLE account_profiles ADD COLUMN n text; -- it's",
        id="after-dollar-quoted-apostrophe",
    ),
]

# Each statement mentions `account_profiles` without reading it as an identifier.
_MENTIONS_ACCOUNT_PROFILES = [
    pytest.param("ALTER TABLE account_profiles_history ADD COLUMN n text", id="suffix"),
    pytest.param("ALTER TABLE old_account_profiles ADD COLUMN n text", id="prefix"),
    pytest.param('ALTER TABLE "ACCOUNT_PROFILES" ADD COLUMN n text', id="quoted-case"),
    pytest.param(
        "ALTER TABLE users ADD COLUMN n text -- see account_profiles", id="line-comment"
    ),
    pytest.param(
        "/* account_profiles,\n  two lines */ ALTER TABLE users ADD n text",
        id="block-comment",
    ),
    pytest.param(
        "COMMENT ON COLUMN users.n IS 'copied from account_profiles'", id="comment-text"
    ),
    pytest.param(
        "DO $$ BEGIN RAISE EXCEPTION 'refused: account_profiles holds rows'; END $$",
        id="raise-message",
    ),
    pytest.param(
        "INSERT INTO permissions (code) VALUES ('account_profiles:read')",
        id="seed-code",
    ),
    pytest.param("SELECT E'it\\'s about account_profiles'", id="escape-string"),
]


@pytest.mark.parametrize("sql", _TOUCHES_ACCOUNT_PROFILES)
def test_security_sensitive_table_named_as_identifier_is_flagged(
    tmp_path: Path, sql: str
) -> None:
    flagged = _flagged(tmp_path, _raw_sql_revision(sql), "account_profiles")
    assert flagged == ["account_profiles"]


@pytest.mark.parametrize("sql", _MENTIONS_ACCOUNT_PROFILES)
def test_security_sensitive_table_not_read_as_identifier_is_not_flagged(
    tmp_path: Path, sql: str
) -> None:
    assert _flagged(tmp_path, _raw_sql_revision(sql), "account_profiles") == []


def test_security_sensitive_unquoted_finding_equals_the_quoted_one(
    tmp_path: Path,
) -> None:
    def findings(name: str, sql: str) -> list[tuple[str, str]]:
        path = _write(tmp_path, name, _raw_sql_revision(sql))
        found = check_security_sensitive(
            [path], sensitive_tables=frozenset({"account_profiles"})
        )
        return [(finding.code, finding.message) for finding in found]

    unquoted = findings("0050_a.py", "CREATE TABLE account_profiles (id uuid)")
    quoted = findings("0051_b.py", 'CREATE TABLE "account_profiles" (id uuid)')
    assert len(unquoted) == 1
    assert unquoted == quoted


_PYTHON_NAME_ARGUMENTS = """
from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("account_profiles", sa.Column("note", sa.Text()))
    op.create_foreign_key("fk_x", "x", "risk_lockouts", ["a"], ["id"])
    sa.Column("owner", sa.ForeignKey("exchange_accounts.id"))
"""

_NAMES_ONLY_IN_PROSE = '''
"""Reads "account_profiles" and `risk_lockouts`; never alters orders or positions."""
from alembic import op

# Touches 'account_profiles' and "orders" in a comment.


def upgrade() -> None:
    """Prose again: "account_profiles"."""
    op.execute("SELECT 1")
'''

_UNRESOLVED_FSTRING_TABLE = """
from alembic import op


def get_name():
    return "x"


def upgrade() -> None:
    t = get_name()
    op.execute(f"ALTER TABLE {t} ADD COLUMN note text")
"""


def test_security_sensitive_table_passed_as_a_python_name_is_flagged(
    tmp_path: Path,
) -> None:
    flagged = _flagged(
        tmp_path,
        _PYTHON_NAME_ARGUMENTS,
        "account_profiles",
        "risk_lockouts",
        "exchange_accounts",
    )
    assert flagged == ["account_profiles", "exchange_accounts", "risk_lockouts"]


_EXECUTE_COMMAND = """from alembic import op


def upgrade() -> None:
    op.execute(\"\"\"EXECUTE '%s "orders"'\"\"\")
"""

_ADDS_TO_ORDERS = """from alembic import op


def upgrade() -> None:
    op.add_column("orders", 1)
"""


# Each command word a single-quoted literal may open with and still be read as SQL.
# Listed here, not imported: a word dropped from the tool's list fails its case.
_COMMAND_WORDS = (
    "ALTER", "ANALYZE", "BEGIN", "CALL", "CLUSTER", "COMMENT", "COPY", "CREATE",
    "DECLARE", "DELETE", "DO", "DROP", "EXECUTE", "GRANT", "INSERT", "LOCK", "MERGE",
    "REFRESH", "REINDEX", "REVOKE", "SELECT", "SET", "TABLE", "TRUNCATE", "UPDATE",
    "VACUUM", "WITH",
)  # fmt: skip


@pytest.mark.parametrize("command", _COMMAND_WORDS)
def test_security_sensitive_literal_opening_with_a_command_is_read_as_sql(
    tmp_path: Path, command: str
) -> None:
    assert _flagged(tmp_path, _EXECUTE_COMMAND % command, "orders") == ["orders"]


@pytest.mark.parametrize(
    ("text", "flagged"), [("Update orders", ["orders"]), ("See orders", [])]
)
def test_security_sensitive_comment_text_is_read_as_sql_only_after_a_command(
    tmp_path: Path, text: str, flagged: list[str]
) -> None:
    """Prose opening with a command word reads as SQL: an extra flag, never a miss."""
    comment = f"op.execute(\"COMMENT ON TABLE users IS '{text}'\")"
    source = _ADDS_TO_ORDERS.replace('op.add_column("orders", 1)', comment)
    assert _flagged(tmp_path, source, "orders") == flagged


def test_security_sensitive_revision_with_a_byte_order_mark_is_read_as_python(
    tmp_path: Path,
) -> None:
    """Read as Python reads it: its docstring is prose, its argument a touch."""
    prose = '"""Mentions orders in prose only."""\n'
    assert _flagged(tmp_path, "\ufeff" + prose, "orders") == []
    assert _flagged(tmp_path, "\ufeff" + _ADDS_TO_ORDERS, "orders") == ["orders"]


@pytest.mark.parametrize(
    "body", ["    ALTER TABLE orders\n", '    op.execute("ALTER TABLE orders ADD x")\n']
)
def test_security_sensitive_revision_that_does_not_parse_has_every_word_read(
    tmp_path: Path, body: str
) -> None:
    """Fail-closed: with no Python to skip prose by, a listed name anywhere counts."""
    assert _flagged(tmp_path, "def upgrade(:\n" + body, "orders") == ["orders"]


def test_security_sensitive_revision_nested_too_deeply_has_every_word_read(
    tmp_path: Path,
) -> None:
    """#4032: a revision too deep to read is read as words, as one that does not parse."""
    source = _raw_sql_revision(_deep()) + "# then ALTER TABLE orders\n"
    assert _flagged(tmp_path, source, "orders") == ["orders"]


def test_security_sensitive_table_named_only_in_docstring_or_comment_is_not_flagged(
    tmp_path: Path,
) -> None:
    flagged = _flagged(
        tmp_path,
        _NAMES_ONLY_IN_PROSE,
        "account_profiles",
        "risk_lockouts",
        "orders",
        "positions",
    )
    assert flagged == []


def test_security_sensitive_unresolved_fstring_placeholder_is_not_a_table(
    tmp_path: Path,
) -> None:
    assert _flagged(tmp_path, _UNRESOLVED_FSTRING_TABLE, "account_profiles") == []


def test_security_sensitive_table_touched_repeatedly_is_flagged_once(
    tmp_path: Path,
) -> None:
    source = _raw_sql_revision(
        "CREATE TABLE account_profiles (id uuid);\n"
        'ALTER TABLE "account_profiles" ADD COLUMN note text;\n'
        "DROP TABLE public.account_profiles;"
    )
    assert _flagged(tmp_path, source, "account_profiles") == ["account_profiles"]


def test_security_sensitive_findings_are_ordered_by_table_name(tmp_path: Path) -> None:
    source = _raw_sql_revision("DROP TABLE risk_policy, account_profiles, orders")
    flagged = _flagged(tmp_path, source, "risk_policy", "orders", "account_profiles")
    assert flagged == ["account_profiles", "orders", "risk_policy"]


@pytest.mark.parametrize(
    ("revision", "touched", "named_only_in_prose"),
    [
        (
            "0037_account_profiles.py",
            {"account_profile_revisions", "account_profiles", "exchange_accounts"},
            "api_keys",
        ),
        (
            "0038_risk_state.py",
            {"exchange_accounts", "kill_switch_state", "risk_lockouts", "risk_policy"},
            "positions",
        ),
    ],
)
def test_security_sensitive_merged_raw_sql_revision_is_flagged(
    revision: str, touched: set[str], named_only_in_prose: str
) -> None:
    """The two merged revisions that wrote every table unquoted (immutable, C-5.4, so
    stable fixtures). `named_only_in_prose` is in their docstring or a COMMENT text."""
    findings = check_security_sensitive(
        [_VERSIONS_DIR / revision],
        sensitive_tables=frozenset(touched | {named_only_in_prose}),
    )
    assert sorted(f.message.split("'")[1] for f in findings) == sorted(touched)


def test_main_warns_for_unquoted_sensitive_table_without_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tables = _write(tmp_path, "tables.txt", "# sensitive\naccount_profiles\n")
    monkeypatch.setattr(
        "tools.ci.migration_lint._DEFAULT_SECURITY_SENSITIVE_TABLES_PATH", tables
    )
    versions = tmp_path / "versions"
    versions.mkdir()
    _write(
        versions,
        "0001_profiles.py",
        _raw_sql_revision("CREATE TABLE account_profiles (id uuid)"),
    )
    assert main(["--versions-dir", str(versions)]) == 0
    assert "WARN CI-MIG-006" in capsys.readouterr().err


# --- #4024: CI-MIG-003 reads statements, not one spelling per verb ---------------

_CORE_DELETE = """import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.execute(sa.table("audit_log").delete())
"""

_CORE_DELETE_BY_KEYWORD = """import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.execute(sa.table(name="audit_log").delete())
"""

_CORE_UPDATE_BY_NAME = """import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    log = sa.table("audit_log", sa.column("outcome"))
    op.execute(sa.update(log).values(outcome="x"))
"""

_WRAPPED_DROP = """from alembic import op


def upgrade() -> None:
    # cv:contract-phase: R2
    op.drop_table(
        "audit_log"
    )
"""


def _audit_hits(tmp_path: Path, source: str, name: str = "0050_audit.py") -> list[str]:
    """Each CI-MIG-003 message the revision `source`, saved as `name`, gives, in
    report order."""
    path = _write(tmp_path, name, source)
    findings = check_audit_table_integrity([path]) + check_destructive_annotations(
        [path]
    )
    assert {finding.code for finding in findings} <= {"CI-MIG-003"}
    return [finding.message for finding in findings]


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE IF EXISTS audit_log",
        "DELETE FROM ONLY audit_log",
        "UPDATE ONLY audit_log SET outcome = 'success'",
        "ALTER TABLE ONLY audit_log DROP COLUMN note",
        "TRUNCATE orders, audit_log",
        "DROP TABLE orders, audit_checkpoints",
        "MERGE INTO audit_log a USING x ON a.id = x.id WHEN MATCHED THEN DELETE",
        "DROP TRIGGER trg_audit_append ON audit_log",
        "DO $$ BEGIN EXECUTE format('DELETE FROM %I', 'audit_log'); END $$",
        "DELETE /* the old rows */ FROM audit_log",
        "DELETE FROM\n\naudit_log WHERE event_ts < now()",
        "WITH gone AS (DELETE FROM audit_log RETURNING id) SELECT count(*) FROM gone",
        "EXPLAIN ANALYZE DELETE FROM audit_log",
        "INSERT INTO audit_log (record_id) VALUES ('x')"
        " ON CONFLICT (record_id) DO UPDATE SET outcome = 'x'",
        "MERGE INTO audit_log a USING x ON a.id = x.id"
        " WHEN NOT MATCHED THEN INSERT (id) VALUES (x.id)",
        "WITH gone AS (UPDATE audit_log SET note = 'x' RETURNING id) SELECT 1",
        "DO $$ BEGIN EXECUTE format('DELETE FROM %s', 'audit_log'); END $$",
        "DO $$ BEGIN EXECUTE format('DELETE FROM %L', 'audit_log'); END $$",
        "DO $$ BEGIN EXECUTE 'DELETE FROM $1' USING 'audit_log'; END $$",
        "ALTER TABLE audit_log DISABLE TRIGGER ALL",
        "ALTER TABLE audit_log ENABLE REPLICA TRIGGER trg_audit_append",
        "ALTER TABLE audit_log ENABLE ALWAYS TRIGGER trg_audit_append",
        "ALTER TABLE audit_log DISABLE RULE r",
    ],
)
def test_audit_mutation_spelled_these_ways_is_flagged(tmp_path: Path, sql: str) -> None:
    """Each statement mutates an audit table, which C-5.7 forbids however it is spelled."""
    (message,) = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert "append-only table 'audit_" in message


@pytest.mark.parametrize(
    "sql",
    [
        "DO $$ BEGIN DELETE FROM audit_log; END $$",
        "DO $$ BEGIN IF true THEN DELETE FROM audit_log; END IF; END $$",
        "DO $$ BEGIN IF false THEN NULL; ELSE DELETE FROM audit_log; END IF; END $$",
        "DO $$ BEGIN FOR i IN 1..2 LOOP UPDATE audit_log SET note = 'x'; END LOOP; END $$",
        "DO $$ BEGIN PERFORM 1; EXCEPTION WHEN others THEN DELETE FROM audit_log; END $$",
        "DO $$ DECLARE r record; BEGIN"
        " FOR r IN DELETE FROM audit_log RETURNING id LOOP END LOOP; END $$",
        "DO $$ BEGIN WITH gone AS (DELETE FROM audit_log RETURNING id)"
        " INSERT INTO orders_archive SELECT * FROM gone; END $$",
        "CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql"
        " AS $$ BEGIN DELETE FROM audit_log; END $$; SELECT f()",
        "CREATE FUNCTION f() RETURNS SETOF audit_log LANGUAGE plpgsql"
        " AS $$ BEGIN RETURN QUERY DELETE FROM audit_log RETURNING *; END $$",
        "CREATE PROCEDURE p() LANGUAGE plpgsql"
        " AS $$ DECLARE n int; BEGIN TRUNCATE audit_log; END $$; CALL p()",
        "CREATE FUNCTION f() RETURNS void LANGUAGE sql"
        " BEGIN ATOMIC DELETE FROM audit_log; END",
        "PREPARE purge AS DELETE FROM audit_log; EXECUTE purge",
        "CREATE RULE r AS ON INSERT TO orders DO ALSO DELETE FROM audit_log",
        "CREATE RULE r AS ON INSERT TO orders DO INSTEAD UPDATE audit_log SET note = 'x'",
        "COPY (DELETE FROM audit_log RETURNING *) TO STDOUT",
    ],
)
def test_a_mutation_a_body_or_rule_starts_mid_statement_is_flagged(
    tmp_path: Path, sql: str
) -> None:
    """plpgsql and SQL-standard bodies, rules, prepared statements and `COPY` start
    the mutation after another word, with no `;` before it."""
    (message,) = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert "append-only table 'audit_log'" in message


def test_a_chunk_of_many_block_openers_is_read_in_linear_memory(tmp_path: Path) -> None:
    """Each opener starts a clause; they are read one at a time, never all held."""
    sql = "DO $$ " + "BEGIN " * 4000 + "DELETE FROM audit_log; END $$"
    tracemalloc.start()
    try:
        (message,) = _audit_hits(tmp_path, _raw_sql_revision(sql))
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert "append-only table 'audit_log'" in message
    assert peak < 16 * 2**20


def test_a_mutating_grant_on_every_table_of_a_schema_is_flagged(tmp_path: Path) -> None:
    """It names no table, and reaches the audit ones all the same."""
    sql = "GRANT DELETE ON ALL TABLES IN SCHEMA public TO cv_app"
    (message,) = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert "every table of a schema" in message


@pytest.mark.parametrize(
    "source", [_CORE_DELETE, _CORE_DELETE_BY_KEYWORD, _CORE_UPDATE_BY_NAME]
)
def test_a_core_delete_or_update_of_an_audit_table_is_flagged(
    tmp_path: Path, source: str
) -> None:
    (message,) = _audit_hits(tmp_path, source)
    assert "append-only table 'audit_log'" in message


def test_a_drop_whose_table_name_is_on_the_next_line_is_flagged(tmp_path: Path) -> None:
    """The call's arguments, not its first line, name the table."""
    (message,) = _audit_hits(tmp_path, _WRAPPED_DROP)
    assert "append-only table 'audit_log'" in message


@pytest.mark.parametrize(
    "sql",
    [
        "REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM cv_app",
        "DO $$ BEGIN EXECUTE 'REVOKE UPDATE, DELETE ON audit_log FROM cv_ro'; END $$",
        "COMMENT ON COLUMN audit_log.note IS 'Update and delete are refused'",
        "INSERT INTO audit_log (record_id) VALUES ('x') ON CONFLICT DO NOTHING",
        "CREATE INDEX ix_audit_time ON audit_log (event_ts DESC)",
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM audit_log) THEN"
        " RAISE EXCEPTION 'audit_log holds rows'; END IF; END $$",
        "SELECT id FROM audit_log WHERE outcome = 'x' FOR UPDATE",
        "SELECT count(*) FROM audit_log",
        "LOCK TABLE audit_log IN SHARE MODE",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO cv_ro",
        "GRANT SELECT, INSERT ON audit_log TO cv_app",
        "DELETE FROM orders WHERE note = 'audit_log rows are kept'",
        "CREATE TRIGGER trg_oe_append BEFORE UPDATE OR DELETE ON order_events"
        " FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
        "CREATE CONSTRAINT TRIGGER trg_owner_floor AFTER DELETE ON user_roles"
        " DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION owner_floor()",
        "COMMENT ON TRIGGER trg_audit_append ON audit_log IS 'refuses updates'",
        "CREATE FUNCTION pad(s text, length int) RETURNS text"
        " LANGUAGE sql AS $$ SELECT rpad(s, length) $$",
        "CREATE FUNCTION fingerprint(v text) RETURNS text LANGUAGE sql"
        " AS $$ SELECT encode(digest(v, 'sha256'), 'hex') $$",
        "ALTER FUNCTION touch_updated_at() SET search_path = pg_catalog, pg_temp",
        "ALTER ROLE cv_app SET statement_timeout = '5s'",
        "CREATE EXTENSION IF NOT EXISTS pgcrypto",
        "DROP SCHEMA staging",
        "INSERT INTO verbs (v) VALUES ('create')",  # a bare word: no statement
        "DROP EXTENSION citext",  # not the extension the chain hashes with
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO cv_ro",
        "ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO cv_app",
        "ALTER DEFAULT PRIVILEGES REVOKE DELETE ON TABLES FROM cv_app",
        "ALTER DEFAULT PRIVILEGES GRANT UPDATE ON SEQUENCES TO cv_app",
        "SET LOCAL lock_timeout = '5s'",
        "SET CONSTRAINTS ALL DEFERRED",
        "RESET lock_timeout",
        "ALTER TABLE orders DISABLE TRIGGER ALL",
        "ALTER TABLE orders ALTER COLUMN note SET DEFAULT 'x'",
        "UPDATE orders SET note = 'x'",
        "CREATE FUNCTION f() RETURNS void LANGUAGE sql"
        " SET search_path = pg_catalog, pg_temp AS $$ SELECT 1 $$",
        "CREATE ROLE cv_ro NOLOGIN",
        "CREATE USER cv_reader LOGIN",
        "ALTER ROLE cv_app NOSUPERUSER",
        "ALTER ROLE cv_app NOCREATEROLE",
        "CREATE PROCEDURE p() LANGUAGE sql SET search_path FROM CURRENT"
        " AS $$ SELECT 1 $$",
    ],
)
def test_a_statement_that_mutates_no_audit_table_is_not_flagged(
    tmp_path: Path, sql: str
) -> None:
    """Reads, inserts, another table's rows and triggers, a parameter or a body that
    shares a name with a function the hash chain calls, and another function's or
    role's settings."""
    assert _audit_hits(tmp_path, _raw_sql_revision(sql)) == []


@pytest.mark.parametrize(
    ("revision", "flagged"), [("0003_audit_log", False), ("0099_other", True)]
)
def test_only_the_revision_that_creates_the_audit_tables_may_drop_them(
    tmp_path: Path, revision: str, flagged: bool
) -> None:
    """0003's downgrade drops what its upgrade created, behind its refusal to drop a
    table that holds a row; any other revision dropping them is a finding."""
    sql = "DROP TRIGGER IF EXISTS trg_audit_append ON audit_log; DROP TABLE audit_log"
    source = f'revision: str = "{revision}"\n' + _raw_sql_revision(sql)
    assert bool(_audit_hits(tmp_path, source, f"{revision}.py")) is flagged


def test_the_owner_revision_may_not_change_audit_rows(tmp_path: Path) -> None:
    source = 'revision = "0003_audit_log"\n' + _raw_sql_revision(
        "DELETE FROM audit_log"
    )
    assert len(_audit_hits(tmp_path, source, "0003_audit_log.py")) == 1


_OWNER_DROPS = (
    "DROP TRIGGER IF EXISTS trg_audit_append ON audit_log; DROP TABLE audit_log;"
    " DROP FUNCTION IF EXISTS forbid_mutation()"
)
_UPGRADE = f"\n\ndef upgrade() -> None:\n    op.execute({_OWNER_DROPS!r})\n"


@pytest.mark.parametrize(
    ("name", "source"),
    [
        pytest.param(
            "0099_other.py",
            'from alembic import op\n\nrevision = "0003_audit_log"\n' + _UPGRADE,
            id="the-owner-id-in-another-file",
        ),
        pytest.param(
            "0003_audit_log.py",
            'from alembic import op\n\nrevision = "0099_other"\n' + _UPGRADE,
            id="the-owner-file-name-with-another-id",
        ),
        pytest.param(
            "0003_audit_log.py",
            'from alembic import op\n\nREV = "0099_other"\nrevision = REV\n'
            + _UPGRADE.replace(
                "-> None:\n", '-> None:\n    revision = "0003_audit_log"\n'
            ),
            id="a-function-scope-claim",
        ),
        pytest.param(
            "0003_audit_log.py",
            'from alembic import op\n\nrevision = "0003_audit_log"\n'
            'revision = "0099_other"\n' + _UPGRADE,
            id="an-earlier-module-level-claim",
        ),
        pytest.param(
            "0003_audit_log.py",
            'from alembic import op\n\nREV = "0099_other"\nrevision = REV\n\n\n'
            'class _Meta:\n    revision = "0003_audit_log"\n' + _UPGRADE,
            id="a-class-body-claim",
        ),
        pytest.param(
            "0003_audit_log.py",
            'from alembic import op\n\nrevision = "0003_audit_log"\n'
            'revision = str("0003_audit_log")\n' + _UPGRADE,
            id="a-later-claim-that-is-not-a-constant",
        ),
    ],
)
def test_no_other_revision_can_claim_the_owner_exemption(
    tmp_path: Path, name: str, source: str
) -> None:
    """The owner is the file the migrations lockfile pins by name and bytes, with the
    id Alembic reads: the last module-level `revision`, a string constant."""
    assert _audit_hits(tmp_path, source, name)


def test_a_revision_the_rule_cannot_parse_is_refused(tmp_path: Path) -> None:
    """#4032: a file the audit rule cannot read is a finding, never a skip."""
    (message,) = _audit_hits(
        tmp_path, "def upgrade(:\n    op.execute('DELETE FROM audit_log')\n"
    )
    assert "is not Python the rule can parse" in message


def _deep(levels: int = 1500) -> str:
    """SQL nested past the interpreter's recursion limit: `DO $t0$ DO $t1$ ... $t1$ $t0$`."""
    opening = "".join(f"DO $t{i}$ " for i in range(levels))
    return opening + "SELECT 1" + "".join(f" $t{i}$" for i in reversed(range(levels)))


def test_a_revision_nested_too_deeply_is_refused_and_the_others_still_report(
    tmp_path: Path,
) -> None:
    deep = _write(tmp_path, "0050_deep.py", _raw_sql_revision(_deep()))
    other = _write(
        tmp_path, "0051_other.py", _raw_sql_revision("DELETE FROM audit_log")
    )
    findings = check_audit_table_integrity([deep, other])
    assert [(f.path.name, "nests too deeply" in f.message) for f in findings] == [
        ("0050_deep.py", True),
        ("0051_other.py", False),
    ]


@pytest.mark.parametrize(
    "body",
    [
        "t = 'audit_log'\n    op.execute(f'DELETE FROM {t}')\n    t = 'orders'\n",
        "t = 'orders'\n    t = 'audit_log'\n    op.execute(f'DELETE FROM {t}')\n",
        "for t in ('orders', 'audit_log'):\n        op.execute(f'DELETE FROM {t}')\n",
        "t = 'audit_log'\n    op.drop_table(t)  # cv:contract-phase: R2\n    t = 'orders'\n",
        "purge('audit_log')\n\n\nt = 'orders'\n\n\ndef purge(t: str) -> None:\n"
        "    op.execute(f'DELETE FROM {t}')\n",
    ],
    ids=[
        "rebound-after",
        "rebound-before",
        "a-loop-target",
        "an-op-argument",
        "a-parameter",
    ],
)
def test_a_name_bound_to_more_than_one_value_reads_as_unresolved(
    tmp_path: Path, body: str
) -> None:
    """Which value a statement sees depends on the order the code runs in, so a name
    bound more than once is unresolved, and an unresolved name where a table goes is
    refused."""
    source = f"from alembic import op\n\n\ndef upgrade() -> None:\n    {body}"
    assert _audit_hits(tmp_path, source)


def test_a_name_bound_to_one_constant_in_two_functions_still_resolves(
    tmp_path: Path,
) -> None:
    """The same table named in `upgrade()` and `downgrade()` is one value, not two."""
    fn = "    tbl = 'orders'\n    op.execute(f'ALTER TABLE {tbl} ADD COLUMN note text')\n"
    source = (
        "from alembic import op\n\n\ndef upgrade() -> None:\n"
        + fn
        + "\n\ndef downgrade() -> None:\n"
        + fn
    )
    assert _audit_hits(tmp_path, source) == []


_UNRESOLVED_OP = (
    "from alembic import op\nimport sqlalchemy as sa\n\n\n"
    "def upgrade(t: str) -> None:\n    {}\n"
)


@pytest.mark.parametrize(
    "source",
    [
        _UNRESOLVED_OP.format("op.drop_table(t)  # cv:contract-phase: R2"),
        _UNRESOLVED_OP.format(
            "u = 'audit_log'\n    op.rename_table(u, 'x')\n    u = 'orders'"
        ),
        _UNRESOLVED_OP.format("op.alter_column(t, 'note', nullable=True)"),
        _UNRESOLVED_OP.format(
            "op.drop_index('ix', table_name=t)  # cv:contract-phase: R2"
        ),
        _UNRESOLVED_OP.format("op.drop_index('ix', t)  # cv:contract-phase: R2"),
        "from alembic import op\nimport sqlalchemy as sa\n\nT = 'audit_log'\nT = 'orders'\n\n\n"
        "def upgrade() -> None:\n    op.execute(sa.table(T).delete())\n",
        _UNRESOLVED_OP.format("op.execute(sa.table(name=t).delete())"),
        _UNRESOLVED_OP.format("op.execute(sa.table(*[t]).delete())"),
        _UNRESOLVED_OP.format("op.drop_table(*[t])  # cv:contract-phase: R2"),
        _UNRESOLVED_OP.format("op.drop_column(t, 'x')  # cv:contract-phase: R2"),
        _UNRESOLVED_OP.format("op.drop_constraint('c', t)  # cv:contract-phase: R2"),
        _UNRESOLVED_OP.format("op.execute(sa.Table(t, sa.MetaData()).delete())"),
        _UNRESOLVED_OP.format("op.execute(sa.table('audit_' + t).delete())"),
        _UNRESOLVED_OP.format("op.execute(sa.table(f'audit_{t}').delete())"),
        _UNRESOLVED_OP.format("op.execute(sa.table(cfg.table).delete())"),
        _UNRESOLVED_OP.format("op.execute(sa.table(names[0]).delete())"),
        _UNRESOLVED_OP.format("op.execute(sa.table(name_of()).delete())"),
        _UNRESOLVED_OP.format("op.drop_table('audit_' + t)  # cv:contract-phase: R2"),
        _UNRESOLVED_OP.format("op.drop_table(table_name=t)  # cv:contract-phase: R2"),
        _UNRESOLVED_OP.format(
            "op.drop_column(table_name=t, column_name='x')  # cv:contract-phase: R2"
        ),
        _UNRESOLVED_OP.format("op.rename_table(old_table_name=t, new_table_name='x')"),
        _UNRESOLVED_OP.format(
            "op.alter_column(table_name=t, column_name='x', nullable=True)"
        ),
        _UNRESOLVED_OP.format(
            "op.drop_constraint('c', table_name=t)  # cv:contract-phase: R2"
        ),
        _UNRESOLVED_OP.format(
            "args = ['c', 'audit_log']\n    op.drop_constraint(*args)  # cv:contract-phase: R2"
        ),
        _UNRESOLVED_OP.format(
            "args = ['ix', 'audit_log']\n    op.drop_index(*args)  # cv:contract-phase: R2"
        ),
        _UNRESOLVED_OP.format(
            "kw = {'table_name': 'audit_log'}\n    op.drop_table(**kw)  # cv:contract-phase: R2"
        ),
        _UNRESOLVED_OP.format(
            "kw = {'name': 'audit_log'}\n    op.execute(sa.table(**kw).delete())"
        ),
    ],
    ids=[
        "a-drop",
        "a-name-bound-twice",
        "an-alter-column",
        "a-drop-index-by-keyword",
        "a-drop-index-by-position",
        "a-core-table-of-a-constant-bound-twice",
        "a-core-table-by-keyword",
        "a-starred-core-table",
        "a-starred-drop",
        "a-drop-column",
        "a-drop-constraint-by-position",
        "a-core-Table",
        "a-core-table-built-with-plus",
        "a-core-table-from-an-f-string",
        "a-core-table-from-an-attribute",
        "a-core-table-from-a-subscript",
        "a-core-table-from-a-call",
        "a-drop-built-with-plus",
        "a-drop-by-keyword",
        "a-drop-column-by-keyword",
        "a-rename-by-keyword",
        "an-alter-column-by-keyword",
        "a-drop-constraint-by-keyword",
        "a-starred-list-before-the-slot",
        "a-starred-index-list",
        "a-drop-from-kwargs",
        "a-core-table-from-kwargs",
    ],
)
def test_an_operation_whose_table_the_rule_cannot_resolve_is_refused(
    tmp_path: Path, source: str
) -> None:
    """A drop, a reshape or a Core table given a name bound to more than one value, or a
    parameter, may be an audit table at run time (#4032)."""
    hits = _audit_hits(tmp_path, source)
    assert any("a table it names only at run time" in hit for hit in hits)


_REBOUND = (
    "from alembic import op\n\nT = 'audit_log'\n{}\n\n\n"
    "def upgrade() -> None:\n    op.drop_table(T)  # cv:contract-phase: R2\n"
)


@pytest.mark.parametrize(
    "binding",
    [
        "from m import T",
        "def T() -> None: ...",
        "class T: ...",
        "try:\n    pass\nexcept Exception as T:\n    pass",
        "match 1:\n    case T:\n        pass",
        "match []:\n    case [*T]:\n        pass",
        "match {}:\n    case {**T}:\n        pass",
        "def f() -> None:\n    global T",
        "from m import *",
        "from m import x as T",
        "import T.sub",
        "async def T() -> None: ...",
    ],
    ids=[
        "an-import",
        "a-function",
        "a-class",
        "an-except-target",
        "a-match-capture",
        "a-match-star",
        "a-match-rest",
        "a-global",
        "a-star-import",
        "an-import-alias",
        "a-dotted-import",
        "an-async-function",
    ],
)
def test_a_name_another_binding_may_rebind_does_not_resolve(
    tmp_path: Path, binding: str
) -> None:
    """Each binding of a name counts, and a star import may bind any: the table the
    name holds when the drop runs is not the constant, so it is refused (#4032)."""
    hits = _audit_hits(tmp_path, _REBOUND.format(binding))
    assert any("a table it names only at run time" in hit for hit in hits)


@pytest.mark.parametrize(
    "body",
    [
        "tbl = 'orders'\n    op.drop_column(tbl, 'note')  # cv:contract-phase: R2",
        "u: str = 'orders'\n    op.drop_column(u, 'note')  # cv:contract-phase: R2",
        "op.drop_index('ix_orders_note')  # cv:contract-phase: R2",
        "op.drop_index(t)  # cv:contract-phase: R2",  # an index name, no table
        "op.execute(sa.table('orders').delete())",
        "op.execute(sa.table(name='orders').delete())",
        "op.execute(sa.select(sa.func.now()))",
        "op.execute(sa.table('orders' '_archive').delete())",
    ],
)
def test_an_operation_whose_table_resolves_to_another_is_not_flagged(
    tmp_path: Path, body: str
) -> None:
    assert _audit_hits(tmp_path, _UNRESOLVED_OP.format(body)) == []


def test_a_revision_whose_tree_cannot_be_dumped_is_read_by_the_cli(
    tmp_path: Path,
) -> None:
    """A long hex literal compiles, but its decimal `repr` exceeds Python's digit limit: the
    revision is still read, and a clean one passes, with no traceback."""
    versions = tmp_path / "versions"
    versions.mkdir()
    _write(
        versions,
        "0050_big.py",
        _raw_sql_revision("SELECT 1") + "N = 0x" + "f" * 3600 + "\n",
    )
    assert main(["--versions-dir", str(versions)]) == 0


def test_if_not_exists_after_a_form_feed_is_numbered_as_the_ast_numbers_it(
    tmp_path: Path,
) -> None:
    """A form feed is no line break to Python: the finding names the line it reads."""
    source = (
        "from alembic import op\n\x0c\n\ndef upgrade() -> None:\n"
        '    op.execute("CREATE TABLE IF NOT EXISTS t (id int)")\n'
    )
    path = _write(tmp_path, "0050_if_not_exists.py", source)
    (finding,) = check_if_not_exists([path])
    assert finding.message.startswith("line 5:")


def test_a_drop_after_a_form_feed_is_paired_with_its_own_line(tmp_path: Path) -> None:
    """Lines are numbered as the AST numbers them, so a form feed earlier in the file
    cannot move a drop away from the call the rule read."""
    source = (
        'from alembic import op\n\x0c\nt = "audit_log"\n\n\ndef upgrade() -> None:\n'
        "    # cv:contract-phase: R2\n    op.drop_table(\n        t\n    )\n"
    )
    assert any(
        "append-only table 'audit_log'" in h for h in _audit_hits(tmp_path, source)
    )


@pytest.mark.parametrize(
    "name",
    [
        "0050_audit.pyc",
        "0050_audit.pth",
        "sub/0050_audit.py",
        "0050_audit.sql",
        "__init__.py",
    ],
)
def test_a_file_that_is_not_a_revisions_source_is_refused_by_the_cli(
    tmp_path: Path, name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    versions = tmp_path / "versions"
    (versions / name).parent.mkdir(parents=True, exist_ok=True)
    (versions / name).write_bytes(b"x")
    (versions / ".gitkeep").write_bytes(b"")
    (versions / "__pycache__").mkdir()
    (versions / "__pycache__" / "0001.cpython-312.pyc").write_bytes(b"x")
    assert main(["--versions-dir", str(versions)]) == 1
    (line,) = capsys.readouterr().err.splitlines()
    assert name.split("/")[-1] in line and "not a revision's Python source" in line


def test_a_python_revision_nested_too_deeply_is_refused_by_the_cli_with_its_sibling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI runs every check over the revisions: one too deep for Python's own parser
    stops none of them, and both revisions are reported."""
    versions = tmp_path / "versions"
    versions.mkdir()
    deep = "x = " + "+".join(["1"] * 60_000) + "\n"
    _write(versions, "0050_deep.py", deep)
    _write(versions, "0051_other.py", _raw_sql_revision("DELETE FROM audit_log"))
    assert main(["--versions-dir", str(versions)]) == 1
    err = capsys.readouterr().err  # findings go to stderr
    assert (
        "0050_deep.py" in err and "nests too deeply" in err and "0051_other.py" in err
    )


def _chain_texts() -> tuple[str, str]:
    """0003's `audit_chain()` with the two changes #889 S3 makes (its own `search_path`,
    its row id drawn under the chain lock), and 0003's text as `CREATE OR REPLACE`."""
    source = (_VERSIONS_DIR / "0003_audit_log.py").read_text(encoding="utf-8")
    start = source.index("CREATE FUNCTION audit_chain()")
    end = source.index("END $BODY$;", start) + len("END $BODY$;")
    restored = source[start:end].replace("CREATE", "CREATE OR REPLACE", 1)
    lock = "  PERFORM pg_advisory_xact_lock(hashtext('audit_log'));\n"
    hardened = restored.replace(
        " AS $BODY$", "\n  SET search_path = pg_catalog, public, pg_temp AS $BODY$", 1
    ).replace(lock, lock + "  NEW.id := nextval('audit_log_id_seq');\n", 1)
    return hardened, restored


_HARDENED, _RESTORED = _chain_texts()
_HARDENING = "0045_audit_chain_hardening.py"
_DEVIATES = "0045_audit_chain_hardening may hold nothing but"


def _hardening_source(hardened: str = _HARDENED, restored: str = _RESTORED) -> str:
    return (
        '"""Harden audit_chain() (#889 S3)."""\n\n'
        "from __future__ import annotations\n\n"
        "from collections.abc import Sequence\n\n"
        "from alembic import op\n\n"
        'revision: str = "0045_audit_chain_hardening"\n'
        'down_revision: str | None = "0044_account_no_hard_delete"\n'
        "branch_labels: str | Sequence[str] | None = None\n"
        "depends_on: str | Sequence[str] | None = None\n\n\n"
        "def upgrade() -> None:\n"
        f'    op.execute(\n        """\n{hardened}\n"""\n    )\n\n\n'
        "def downgrade() -> None:\n"
        f'    op.execute(\n        """\n{restored}\n"""\n    )\n'
    )


def test_the_chain_hardening_pins_are_0003s_function_with_the_agreed_changes() -> None:
    assert {
        "upgrade": hashlib.sha256(_HARDENED.encode()).hexdigest(),
        "downgrade": hashlib.sha256(_RESTORED.encode()).hexdigest(),
    } == _CHAIN_HARDENING_SHA256
    assert _HARDENED.count("\n") == _RESTORED.count("\n") + 2


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(_hardening_source(), id="as-agreed"),
        pytest.param(
            _hardening_source()
            .replace("-> None:\n", '-> None:\n    """Replace audit_chain()."""\n')
            .replace("revision: str =", "revision =")
            .replace("down_revision: str | None =", "down_revision ="),
            id="with-function-docstrings-and-bare-identifiers",
        ),
    ],
)
def test_the_chain_hardening_revision_holding_only_its_pins_is_exempt(
    tmp_path: Path, source: str
) -> None:
    assert _audit_hits(tmp_path, source, _HARDENING) == []


_UP = "def upgrade() -> None:\n"
_CALL = "    op.execute(\n"
_DOWN_DEF = "\n\ndef downgrade() -> None:\n"
_END_UP = '"""\n    )\n' + _DOWN_DEF
_REVISION = 'revision: str = "0045_audit_chain_hardening"'
_DEPENDS = "depends_on: str | Sequence[str] | None = None\n"
_SET = "\n  SET search_path = pg_catalog, public, pg_temp"
_ID = "  NEW.id := nextval('audit_log_id_seq');\n"


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            _hardening_source(hardened=_HARDENED.replace(_SET, "")), id="no-search-path"
        ),
        pytest.param(
            _hardening_source(hardened=_HARDENED.replace(_ID, "")),
            id="no-id-under-lock",
        ),
        pytest.param(
            _hardening_source(
                hardened=_HARDENED.replace("pg_catalog, public", "public, pg_catalog")
            ),
            id="another-path-order",
        ),
        pytest.param(
            _hardening_source(
                hardened=_HARDENED + "\nDROP TRIGGER trg_audit_append ON audit_log;"
            ),
            id="a-second-statement-in-the-literal",
        ),
        pytest.param(
            _hardening_source(
                restored="ALTER FUNCTION audit_chain() RESET search_path;"
            ),
            id="an-alter-for-the-restore",
        ),
        pytest.param(
            _hardening_source(
                restored=_RESTORED.replace("audit_chain()", "forbid_mutation()", 1)
            ),
            id="another-guard-function",
        ),
        pytest.param(
            _hardening_source().replace(
                _UP, _UP + "    op.execute(\"SET LOCAL lock_timeout = '5s'\")\n", 1
            ),
            id="a-lock-timeout-line",
        ),
        pytest.param(
            _hardening_source()
            .replace(
                _UP + '    op.execute(\n        """',
                '_SQL = """',
                1,
            )
            .replace(
                '"""\n    )\n\n\ndef downgrade',
                '"""\n\n\n' + _UP + "    op.execute(_SQL)\n\n\ndef downgrade",
                1,
            ),
            id="a-named-constant",
        ),
        pytest.param(
            _hardening_source().replace(
                "from alembic import op\n",
                "from alembic import op\nimport sqlalchemy\n",
            ),
            id="another-import",
        ),
        pytest.param(
            _hardening_source().replace(
                "from alembic import op\n",
                "from alembic import op\nfrom os import system\n",
            ),
            id="another-from-import",
        ),
        pytest.param(
            _hardening_source().replace(
                "from alembic import op\n", "from alembic import op as op\n"
            ),
            id="an-aliased-import",
        ),
        pytest.param(
            _hardening_source().replace(_UP, "@print\n" + _UP), id="a-decorator"
        ),
        pytest.param(
            _hardening_source().replace(_UP, "def upgrade(x: int = 0) -> None:\n"),
            id="an-argument",
        ),
        pytest.param(
            _hardening_source().replace(_UP, "def upgrade() -> int:\n"),
            id="a-return-annotation",
        ),
        pytest.param(
            _hardening_source().replace(_UP, "async " + _UP), id="an-async-upgrade"
        ),
        pytest.param(
            _hardening_source()[: _hardening_source().index("\n\ndef downgrade")]
            + "\n",
            id="no-downgrade",
        ),
        pytest.param(
            _hardening_source()
            + "\n\n"
            + _UP
            + '    op.execute("DROP TRIGGER trg_audit_append ON audit_log")\n',
            id="a-second-upgrade",
        ),
        pytest.param(
            _hardening_source()
            + "\n\n"
            + _hardening_source()[_hardening_source().index(_UP) :].split("\n\n\n")[0]
            + "\n",
            id="a-repeated-upgrade",
        ),
        pytest.param(
            _hardening_source() + '\nop.execute("SELECT 1")\n', id="a-module-level-call"
        ),
        pytest.param(
            _hardening_source().replace("revision: str =", 'revision: print("x") =', 1),
            id="an-annotation-that-runs",
        ),
        pytest.param(
            _hardening_source().replace(
                '    op.execute(\n        """', '    op.execute(\n        f"""', 1
            ),
            id="an-f-string",
        ),
        pytest.param(
            _hardening_source().replace(_UP, "def upgrade(x: int = 0, /) -> None:\n"),
            id="a-positional-only-parameter",
        ),
        pytest.param(
            _hardening_source().replace(_UP, "def upgrade(*args: int) -> None:\n"),
            id="a-star-args-parameter",
        ),
        pytest.param(
            _hardening_source().replace(_UP, "def upgrade(*, x: int = 0) -> None:\n"),
            id="a-keyword-only-parameter",
        ),
        pytest.param(
            _hardening_source().replace(_UP, "def upgrade(**kwargs: int) -> None:\n"),
            id="a-star-star-kwargs-parameter",
        ),
        pytest.param(
            _hardening_source().replace(_UP, "def upgrade[T]() -> None:\n"),
            id="a-type-parameter",
        ),
        pytest.param(
            _hardening_source().replace(
                _DEPENDS, _DEPENDS.replace("= None", '= print("x")')
            ),
            id="a-call-as-an-identifiers-value",
        ),
        pytest.param(
            _hardening_source().replace(_DEPENDS, _DEPENDS.replace("= None", "= 5")),
            id="a-number-as-an-identifiers-value",
        ),
        pytest.param(
            _hardening_source().replace(
                _REVISION, 'revision = alias = "0045_audit_chain_hardening"'
            ),
            id="a-chained-assignment",
        ),
        pytest.param(
            _hardening_source().replace(_DEPENDS, _DEPENDS + "op.revision = None\n"),
            id="an-attribute-assignment",
        ),
        pytest.param(
            _hardening_source().replace(_DEPENDS, _DEPENDS + "EXTRA = None\n"),
            id="another-module-level-name",
        ),
        pytest.param(
            _hardening_source().replace(
                "from alembic import op\n", "from .alembic import op\n"
            ),
            id="a-relative-import",
        ),
        pytest.param(
            _hardening_source() + '\n"a stray string"\n', id="a-second-module-string"
        ),
        pytest.param(
            _hardening_source().replace(_CALL, "    op.run(\n", 1), id="another-method"
        ),
        pytest.param(
            _hardening_source().replace(_CALL, "    connection.execute(\n", 1),
            id="another-receiver",
        ),
        pytest.param(
            _hardening_source().replace(_CALL, "    alembic.op.execute(\n", 1),
            id="a-qualified-receiver",
        ),
        pytest.param(
            _hardening_source().replace(_CALL, "    return op.execute(\n", 1),
            id="a-returned-call",
        ),
        pytest.param(
            _hardening_source().replace(_CALL, "    _ = op.execute(\n", 1),
            id="an-assigned-call",
        ),
        pytest.param(
            _hardening_source().replace(
                _CALL + '        """', _CALL + '        b"""', 1
            ),
            id="a-bytes-literal",
        ),
        pytest.param(
            _hardening_source().replace(
                _END_UP, '""",\n        "x",\n    )\n' + _DOWN_DEF, 1
            ),
            id="an-extra-argument",
        ),
        pytest.param(
            _hardening_source().replace(
                _END_UP, '""",\n        execution_options=None,\n    )\n' + _DOWN_DEF, 1
            ),
            id="a-keyword-argument",
        ),
        pytest.param(
            _hardening_source().replace(
                _END_UP,
                '"""\n    )\n    op.execute("DROP TRIGGER trg_audit_append ON audit_log")\n'
                + _DOWN_DEF,
                1,
            ),
            id="a-statement-after-the-pin",
        ),
        pytest.param(
            _hardening_source().replace(_UP, 'def upgrade() -> "None":\n', 1),
            id="a-string-return-annotation",
        ),
        pytest.param(
            _hardening_source().replace(
                "from alembic import op\n", "from alembic import op, context\n"
            ),
            id="a-second-imported-name",
        ),
        pytest.param(
            _hardening_source().replace(
                _CALL + '        """\n' + _HARDENED + "\n" + _END_UP,
                "    5\n" + _DOWN_DEF,
                1,
            ),
            id="a-bare-constant-body",
        ),
        pytest.param(
            _hardening_source().replace(_CALL, "    execute(\n", 1), id="a-bare-execute"
        ),
    ],
)
def test_a_chain_hardening_revision_holding_anything_else_is_refused(
    tmp_path: Path, source: str
) -> None:
    # Each case is Python: refused for what it holds, never as unreadable.
    ast.parse(source)
    assert any(_DEVIATES in hit for hit in _audit_hits(tmp_path, source, _HARDENING))


def test_an_unparsable_chain_hardening_revision_is_read_as_any_revision(
    tmp_path: Path,
) -> None:
    source = _hardening_source() + "\ndef broken(:\n"
    with pytest.raises(SyntaxError):
        ast.parse(source)
    hits = _audit_hits(tmp_path, source, _HARDENING)
    assert hits == _audit_hits(tmp_path, source, "0050_audit.py")
    assert not any(_DEVIATES in hit for hit in hits)


def test_a_refused_chain_hardening_revision_is_read_as_any_revision(
    tmp_path: Path,
) -> None:
    """Once it deviates, its guard function DDL is a finding as any revision's is."""
    hits = _audit_hits(
        tmp_path, _hardening_source(hardened=_HARDENED.replace(_SET, "")), _HARDENING
    )
    assert any(_DEVIATES in hit for hit in hits)
    assert any("guard function 'audit_chain'" in hit for hit in hits)


_NOT_UTF8 = "does not read as UTF-8 source"
_ASCII_REVISION = _raw_sql_revision("SELECT 1").encode()
_ENDINGS = {"lf": b"\n", "crlf": b"\r\n", "cr": b"\r"}


def _messages(tmp_path: Path, source: bytes, name: str = "0050_audit.py") -> list[str]:
    path = tmp_path / name
    path.write_bytes(source)
    return [finding.message for finding in check_audit_table_integrity([path])]


def test_the_gate_and_the_rules_read_one_text(tmp_path: Path) -> None:
    body = _raw_sql_revision("SELECT 'caf\u00e9'").encode().replace(b"\n", b"\r")
    path = tmp_path / "0050_audit.py"
    path.write_bytes(b"# one\r# two\r# -*- coding: latin-1 -*-\r" + body)
    compiled = ast.dump(ast.parse(path.read_bytes()))  # line 3 declares nothing
    assert (
        _reads_as_utf8(path) and ast.dump(ast.parse(_read_revision(path))) == compiled
    )


def test_the_audit_rule_reads_the_text_the_gate_read(tmp_path: Path) -> None:
    shape = b"\t\r\r\n# coding: utf-16\n"
    source = shape + _raw_sql_revision("DELETE FROM audit_log").encode()
    (hit,) = _messages(tmp_path, source)
    assert "append-only table 'audit_log'" in hit


@pytest.mark.parametrize("name", [_HARDENING, "0050_audit.py", "0003_audit_log.py"])
@pytest.mark.parametrize(
    ("declared", "refused"),
    [
        ("latin-1", True),
        ("utf-7", True),
        ("utf-16", True),
        ("utf-32", True),
        ("no-such-codec", True),
        ("utf-8", False),
        ("UTF-8", False),
        ("utf8", False),
        ("u8", False),
    ],
)
def test_a_revision_declaring_another_source_encoding_is_refused(
    tmp_path: Path, name: str, declared: str, refused: bool
) -> None:
    """Another declared encoding gives one refusal; UTF-8 under any name is read."""
    source = f"# -*- coding: {declared} -*-\n" + _hardening_source()
    hits = _messages(tmp_path, source.encode(), name)
    if refused:
        (hit,) = hits
        assert _NOT_UTF8 in hit
    else:
        assert not any(_NOT_UTF8 in hit for hit in hits)
        assert (hits == []) is (name == _HARDENING)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(b"# \xff\n" + _ASCII_REVISION, id="an-invalid-byte-on-line-1"),
        pytest.param(_ASCII_REVISION + b"# \xff\n", id="an-invalid-byte-later"),
        pytest.param(
            codecs.BOM_UTF8 + b"# -*- coding: latin-1 -*-\n" + _ASCII_REVISION,
            id="a-byte-order-mark-and-another-declaration",
        ),
        pytest.param(
            b"# -*- coding: latin-1 -*-\n"
            + _raw_sql_revision("DELETE FROM audit_log").encode(),
            id="a-refused-revision-that-mutates-an-audit-table",
        ),
    ],
)
def test_a_revision_that_is_not_utf8_source_gets_one_refusal(
    tmp_path: Path, source: bytes
) -> None:
    (hit,) = _messages(tmp_path, source)
    assert _NOT_UTF8 in hit


@pytest.mark.parametrize("first", sorted(_ENDINGS))
@pytest.mark.parametrize("second", sorted(_ENDINGS))
@pytest.mark.parametrize(
    "lead",
    [None, b"", b"#!/usr/bin/env python"],
    ids=["on-line-1", "after-a-blank-line", "after-a-comment"],
)
@pytest.mark.parametrize(
    ("declared", "refused"), [(b"latin-1", True), (b"utf-8", False), (None, False)]
)
def test_a_declaration_is_read_whatever_the_line_endings(
    tmp_path: Path,
    first: str,
    second: str,
    lead: bytes | None,
    declared: bytes | None,
    refused: bool,
) -> None:
    line = b"# a revision" if declared is None else b"# -*- coding: %s -*-" % declared
    one, two = (line, b"# a revision") if lead is None else (lead, line)
    source = one + _ENDINGS[first] + two + _ENDINGS[second] + _ASCII_REVISION
    hits = _messages(tmp_path, source)
    assert hits == ([hits[0]] if refused else [])
    assert all(_NOT_UTF8 in hit for hit in hits)


def test_a_revision_the_lint_reads_as_utf8_is_one_python_compiles_as_utf8(
    tmp_path: Path,
) -> None:
    """Whatever two-line head the lint reads as UTF-8, Python compiles as UTF-8."""
    names = [b"utf-8", b"utf8", b"latin-1", b"cp1252", b"utf-7", b"no-such-codec"]
    kinds = [b"", b"# a comment", b"x = 1", *(b"# coding: %s" % n for n in names)]
    endings = list(_ENDINGS.values())
    path = tmp_path / "0050_probe.py"
    read = 0
    for bom, one, end_one, two, end_two in itertools.product(
        [b"", codecs.BOM_UTF8], kinds, endings, kinds, endings
    ):
        source = (
            bom + one + end_one + two + end_two + "PROBE = '\u00e9\u20ac'\n".encode()
        )
        path.write_bytes(source)
        if not _reads_as_utf8(path):
            continue
        read += 1
        (probe,) = [
            node.value
            for node in ast.parse(source).body
            if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "PROBE"
        ]
        assert isinstance(probe, ast.Constant) and probe.value == "\u00e9\u20ac", source
    assert 0 < read < 2 * len(kinds) ** 2 * len(endings) ** 2


def test_a_revision_whose_text_is_not_the_code_python_compiles_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importlib.util, "decode_source", lambda source: "x = 1\n")
    (hit,) = _messages(tmp_path, _ASCII_REVISION)
    assert _NOT_UTF8 in hit


def test_the_other_readers_read_a_revision_in_the_encoding_it_declares(
    tmp_path: Path,
) -> None:
    path = tmp_path / "0050_latin.py"
    path.write_bytes(b"# -*- coding: latin-1 -*-\n# caf\xe9\n" + _ASCII_REVISION)
    assert check_if_not_exists([path]) == []
    assert check_destructive_annotations([path]) == []


def test_the_cli_reports_a_revision_that_is_not_utf8_source_once_and_reads_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "0050_codec.py").write_bytes(b"# coding: nope\n" + _ASCII_REVISION)
    (versions / "0051_bytes.py").write_bytes(_ASCII_REVISION + b"# \xff\n")
    _write(versions, "0052_destructive.py", _DESTRUCTIVE_UNANNOTATED)
    assert main(["--versions-dir", str(versions)]) == 1
    lines = [
        [*line.split(": ")[:2], _NOT_UTF8 in line]
        for line in capsys.readouterr().err.splitlines()
        if not line.startswith("WARN ")
    ]
    assert lines == [
        ["CI-MIG-003", str(versions / "0052_destructive.py"), False],
        ["CI-MIG-003", str(versions / "0050_codec.py"), True],
        ["CI-MIG-003", str(versions / "0051_bytes.py"), True],
    ]


@pytest.mark.parametrize(
    ("name", "source"),
    [
        pytest.param(
            "0046_audit_chain_hardening.py", _hardening_source(), id="another-file-name"
        ),
        pytest.param(
            _HARDENING,
            _hardening_source().replace(
                '"0045_audit_chain_hardening"', '"0046_other"', 1
            ),
            id="another-revision-id",
        ),
        pytest.param(
            _HARDENING,
            _hardening_source().replace(
                "depends_on: str | Sequence[str] | None = None\n",
                "depends_on: str | Sequence[str] | None = None\n"
                'revision = "0046_other"\n',
                1,
            ),
            id="a-later-module-level-revision",
        ),
    ],
)
def test_no_other_revision_can_claim_the_chain_hardening_exemption(
    tmp_path: Path, name: str, source: str
) -> None:
    hits = _audit_hits(tmp_path, source, name)
    assert any("guard function 'audit_chain'" in hit for hit in hits)
    assert not any(_DEVIATES in hit for hit in hits)


def test_the_shipped_migrations_have_no_audit_mutation() -> None:
    paths = sorted(p for p in _VERSIONS_DIR.glob("*.py") if p.name != "__init__.py")
    assert len(paths) > 40
    assert check_audit_table_integrity(paths) == []
    assert check_destructive_annotations(paths) == []


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger"
        " LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$",
        "DROP FUNCTION audit_refuse_truncate() CASCADE",
        "CREATE OR REPLACE FUNCTION public.audit_chain() RETURNS trigger"
        " LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$",
        "DROP FUNCTION IF EXISTS audit_field(text)",
        'ALTER FUNCTION "forbid_mutation"() OWNER TO cv_app',
        "DO $$ BEGIN EXECUTE 'DROP FUNCTION audit_chain()'; END $$",
        "DO $$ BEGIN DROP FUNCTION forbid_mutation() CASCADE; END $$",
        "DO $$ BEGIN IF true THEN DROP FUNCTION IF EXISTS audit_chain() CASCADE;"
        " END IF; END $$",
        "DO $$ BEGIN ALTER FUNCTION audit_field(text) RENAME TO x; END $$",
        "DO $o$ BEGIN CREATE OR REPLACE FUNCTION audit_refuse_truncate()"
        " RETURNS trigger LANGUAGE plpgsql AS $i$ BEGIN RETURN NULL; END $i$; END $o$",
        "ALTER ROUTINE audit_chain() SECURITY DEFINER",
        "DROP ROUTINE forbid_mutation() CASCADE",
        "DROP PROCEDURE IF EXISTS audit_refuse_truncate()",
    ],
)
def test_redefining_or_dropping_an_audit_guard_function_is_flagged(
    tmp_path: Path, sql: str
) -> None:
    """The append-only triggers and the hash chain run these: replacing one neuters
    them without naming an audit table."""
    (message,) = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert "append-only guard function '" in message


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE FUNCTION rule_events_forbid_mutation() RETURNS trigger"
        " LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$",
        "CREATE OR REPLACE FUNCTION audit_view() RETURNS int"
        " LANGUAGE sql AS $$ SELECT audit_field('x')::int $$",
        "CREATE TRIGGER trg BEFORE TRUNCATE ON orders"
        " FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate()",
    ],
)
def test_a_function_that_only_shares_or_calls_a_guard_function_is_not_flagged(
    tmp_path: Path, sql: str
) -> None:
    """A sibling's name, a body that calls one, and a trigger that runs one."""
    assert _audit_hits(tmp_path, _raw_sql_revision(sql)) == []


@pytest.mark.parametrize(
    ("revision", "flagged"), [("0003_audit_log", False), ("0099_other", True)]
)
def test_only_the_revision_that_defines_the_guard_functions_may_drop_them(
    tmp_path: Path, revision: str, flagged: bool
) -> None:
    sql = "DROP FUNCTION IF EXISTS forbid_mutation()"
    source = f'revision: str = "{revision}"\n' + _raw_sql_revision(sql)
    assert bool(_audit_hits(tmp_path, source, f"{revision}.py")) is flagged


@pytest.mark.parametrize(
    ("sql", "table"),
    [
        (
            "CREATE OR REPLACE TRIGGER trg_audit_append BEFORE UPDATE OR DELETE"
            " ON audit_log FOR EACH ROW WHEN (false) EXECUTE FUNCTION forbid_mutation()",
            "audit_log",
        ),
        (
            "CREATE TRIGGER trg_skip BEFORE INSERT ON audit_log"
            " FOR EACH ROW EXECUTE FUNCTION skip_row()",
            "audit_log",
        ),
        (
            "CREATE CONSTRAINT TRIGGER trg_late AFTER INSERT ON audit_checkpoints"
            " FOR EACH ROW EXECUTE FUNCTION refuse()",
            "audit_checkpoints",
        ),
        ("CREATE RULE r AS ON INSERT TO audit_log DO INSTEAD NOTHING", "audit_log"),
        (
            "CREATE OR REPLACE RULE r AS ON INSERT TO audit_checkpoints"
            " DO INSTEAD NOTHING",
            "audit_checkpoints",
        ),
        ("GRANT TRIGGER ON audit_log TO cv_app", "audit_log"),
        (
            "DO $$ BEGIN EXECUTE 'CREATE TRIGGER t BEFORE INSERT ON audit_log"
            " FOR EACH ROW EXECUTE FUNCTION skip_row()'; END $$",
            "audit_log",
        ),
    ],
)
def test_a_trigger_or_rule_on_an_audit_table_is_flagged(
    tmp_path: Path, sql: str, table: str
) -> None:
    """A trigger or a rule can discard or rewrite each row written after it, and the
    `TRIGGER` privilege lets its grantee add one (#4032)."""
    (message,) = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert f"append-only table '{table}'" in message


def test_a_trigger_grant_on_every_table_of_a_schema_is_flagged(tmp_path: Path) -> None:
    sql = "GRANT TRIGGER ON ALL TABLES IN SCHEMA public TO cv_app"
    (message,) = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert "every table of a schema" in message


@pytest.mark.parametrize(
    ("sql", "callee"),
    [
        (
            "CREATE FUNCTION DIGEST(bytea, text) RETURNS bytea"
            " LANGUAGE sql AS $$ SELECT $1 $$",
            "digest",
        ),
        (
            "CREATE FUNCTION digest(bytea, text) RETURNS bytea"
            " LANGUAGE sql AS $$ SELECT $1 $$",
            "digest",
        ),
        (
            "CREATE OR REPLACE FUNCTION public.encode(bytea, text) RETURNS text"
            " LANGUAGE sql AS $$ SELECT 'x' $$",
            "encode",
        ),
        (
            'CREATE FUNCTION cv_app . "length" /* x */ (text) RETURNS int'
            " LANGUAGE sql AS $$ SELECT 1 $$",
            "length",
        ),
        ("CREATE AGGREGATE to_char(text) (SFUNC = textcat, STYPE = text)", "to_char"),
        ("ALTER FUNCTION my_hash(bytea, text) RENAME TO digest", "digest"),
        ("DROP FUNCTION IF EXISTS public.hashtext(text)", "hashtext"),
        (
            "DO $o$ BEGIN CREATE FUNCTION pg_advisory_xact_lock(bigint) RETURNS void"
            " LANGUAGE sql AS $i$ SELECT $i$; END $o$",
            "pg_advisory_xact_lock",
        ),
        (
            "CREATE PROCEDURE repeat(text, int) LANGUAGE sql AS $$ SELECT 1 $$",
            "repeat",
        ),
    ],
)
def test_a_routine_named_as_a_function_the_hash_chain_calls_is_flagged(
    tmp_path: Path, sql: str, callee: str
) -> None:
    """`audit_chain` resolves these through the inserting session's `search_path`:
    another routine of the name, in a schema searched first or with a closer
    signature, forges or breaks the chain (#4032)."""
    (message,) = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert f"the function '{callee}' the audit hash chain calls" in message


_DEFAULT_GRANT = "a mutating privilege every table created later gets"
_TRIGGERS_OFF = "the setting that turns the append-only tables' triggers off"
_SETTING = "a setting set through set_config() or under a computed name"


@pytest.mark.parametrize(
    ("body", "target"),
    [
        pytest.param("op.execute(f'SET {name} = replica')", _SETTING, id="an-f-string"),
        pytest.param(
            "op.execute('SET ' + name + ' = replica')", _SETTING, id="a-concatenation"
        ),
        pytest.param(  # read whole, the string names the setting
            "op.execute('SET session_' + 'replication_role = replica')",
            _TRIGGERS_OFF,
            id="a-split-name",
        ),
        pytest.param(
            "v = 'SET'\n    op.execute(f'{v} {name} = replica')",
            _SETTING,
            id="a-resolved-verb",
        ),
        pytest.param(
            "op.execute('SET {} = replica'.format(name))", _SETTING, id="a-format-field"
        ),
        pytest.param(
            "op.execute(f'ALTER USER cv_app SET {name} = replica')",
            _SETTING,
            id="an-alter-user",
        ),
        pytest.param(
            "op.execute(f'ALTER DATABASE cv SET {name} = replica')",
            _SETTING,
            id="an-alter-database",
        ),
        pytest.param(
            "op.execute(f'ALTER FUNCTION f() SET {name} = replica')",
            _SETTING,
            id="an-alter-function",
        ),
        pytest.param(
            "op.execute(f'ALTER PROCEDURE p() SET {name} TO replica')",
            _SETTING,
            id="an-alter-procedure",
        ),
        pytest.param(
            "op.execute(f'CREATE FUNCTION f() RETURNS void LANGUAGE sql"
            " SET {name} = replica AS $$ SELECT 1 $$')",
            _SETTING,
            id="a-routine-header",
        ),
        pytest.param(
            "op.execute('CREATE OR REPLACE PROCEDURE p() LANGUAGE sql"
            " SET {} TO replica AS $$ SELECT 1 $$'.format(name))",
            _SETTING,
            id="a-procedure-header-format-field",
        ),
        pytest.param(
            "op.execute(f'ALTER USER cv_app SET {name} = replica')",
            _SETTING,
            id="an-alter-user",
        ),
        pytest.param(
            "op.execute(f'ALTER DATABASE cv SET {name} = replica')",
            _SETTING,
            id="an-alter-database",
        ),
        pytest.param(
            "op.execute(f'ALTER FUNCTION f() SET {name} = replica')",
            _SETTING,
            id="an-alter-function",
        ),
        pytest.param(
            "op.execute(f'ALTER PROCEDURE p() SET {name} TO replica')",
            _SETTING,
            id="an-alter-procedure",
        ),
        pytest.param(
            "op.execute(f'ALTER SYSTEM SET {name} = replica')",
            _SETTING,
            id="an-alter-system",
        ),
        pytest.param(
            "op.execute(f'ALTER ROUTINE f() SET {name} = replica')",
            _SETTING,
            id="an-alter-routine",
        ),
        pytest.param(
            "op.execute('SET session_{} = replica'.format(name))",
            _SETTING,
            id="a-format-field-after-a-prefix",
        ),
        pytest.param(
            "op.execute('SET session_%s = replica' % name)",
            _SETTING,
            id="a-percent-field-after-a-prefix",
        ),
        pytest.param(
            "op.execute('ALTER ROLE cv_app SET session_{} TO replica'.format(name))",
            _SETTING,
            id="an-alter-role-field-after-a-prefix",
        ),
        pytest.param(
            "op.execute(f'CREATE FUNCTION f() RETURNS void LANGUAGE sql"
            " SET {name} = replica AS $$ SELECT 1 $$')",
            _SETTING,
            id="a-routine-header",
        ),
        pytest.param(
            "op.execute('CREATE OR REPLACE PROCEDURE p() LANGUAGE sql"
            " SET {} TO replica AS $$ SELECT 1 $$'.format(name))",
            _SETTING,
            id="a-procedure-header-format-field",
        ),
        pytest.param(
            "op.execute('CREATE FUNCTION f() RETURNS void LANGUAGE sql"
            " SET session_{} = replica AS $$ SELECT 1 $$'.format(name))",
            _SETTING,
            id="a-routine-header-field-after-a-prefix",
        ),
    ],
)
def test_a_setting_python_computes_the_name_of_is_flagged(
    tmp_path: Path, body: str, target: str
) -> None:
    source = (
        f"from alembic import op\n\n\ndef upgrade(name: str) -> None:\n    {body}\n"
    )
    hits = _audit_hits(tmp_path, source)
    assert hits and all(target in hit for hit in hits)


@pytest.mark.parametrize(
    "sql",
    [
        "DO $$ BEGIN EXECUTE 'SET session_' || 'replication_role = replica'; END $$",
        "DO $$ BEGIN EXECUTE 'ALTER ROLE cv_app SET ' || n || ' = replica'; END $$",
    ],
)
def test_a_body_that_builds_a_settings_name_is_flagged(
    tmp_path: Path, sql: str
) -> None:
    """Its `EXECUTE` of a concatenation is refused as well."""
    assert any(_SETTING in hit for hit in _audit_hits(tmp_path, _raw_sql_revision(sql)))


@pytest.mark.parametrize(
    ("body", "target"),
    [
        (
            "op.execute(sa.select(sa.func.set_config("
            "'session_replication_role', 'replica', False)))",
            _SETTING,
        ),
        (
            "f = sa.func.set_config\n    op.execute(sa.select("
            "f('session_replication_role', 'replica', False)))",
            _TRIGGERS_OFF,
        ),
    ],
    ids=["through-core", "through-a-name"],
)
def test_a_setting_python_sets_past_the_sql_reader_is_flagged(
    tmp_path: Path, body: str, target: str
) -> None:
    """`set_config` through SQLAlchemy Core, and the name of the setting that turns the
    tables' triggers off wherever Python passes it, as SQL would be read (#4032)."""
    hits = _audit_hits(tmp_path, _UNRESOLVED_OP.format(body))
    assert hits and all(target in hit for hit in hits)


@pytest.mark.parametrize(
    "sql",
    [
        "DO $$ BEGIN EXECUTE format('SET session_%s = replica', 'replication_role'); END $$",
        "DO $$ BEGIN EXECUTE format('CREATE FUNCTION f() RETURNS void LANGUAGE sql"
        " SET session_%s = replica AS $x$ SELECT 1 $x$', 'replication_role'); END $$",
    ],
    ids=["a-set", "a-routine-header"],
)
def test_a_setting_dynamic_sql_completes_after_a_prefix_is_flagged(
    tmp_path: Path, sql: str
) -> None:
    """The placeholder may follow the literal start of the setting's name: the rule
    cannot read the name either way (#4032)."""
    hits = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert hits and all(_SETTING in hit for hit in hits)


def test_a_routine_created_by_dynamic_sql_with_a_computed_setting_is_flagged(
    tmp_path: Path,
) -> None:
    """A routine's own `SET` clause under a placeholder: its body runs under a setting
    the rule cannot name, wherever the routine is created (#4032)."""
    sql = (
        "DO $$ BEGIN EXECUTE format('CREATE FUNCTION f() RETURNS void LANGUAGE sql"
        " SET %I = replica AS $x$ SELECT 1 $x$', 'session_replication_role'); END $$"
    )
    hits = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert hits and all(_SETTING in hit for hit in hits)


@pytest.mark.parametrize(
    ("sql", "target"),
    [
        ("GRANT cv_owner TO cv_app", "a role's membership"),
        ("GRANT pg_write_all_data TO cv_app WITH ADMIN OPTION", "a role's membership"),
        (
            "DO $$ BEGIN IF true THEN GRANT cv_owner TO cv_app; END IF; END $$",
            "a role's membership",
        ),
        ("DROP SCHEMA public CASCADE", "a schema"),
        ("DROP SCHEMA IF EXISTS staging, public CASCADE", "a schema"),
        ("ALTER SCHEMA public OWNER TO cv_app", "a schema"),
        ("ALTER SCHEMA public RENAME TO old_public", "a schema"),
        ("DROP OWNED BY cv_owner", "every object a role owns"),
        ("REASSIGN OWNED BY cv_owner TO cv_app", "every object a role owns"),
        ("DROP EXTENSION pgcrypto CASCADE", "the extension"),
        ('DROP EXTENSION IF EXISTS "pgcrypto"', "the extension"),
        ("ALTER EXTENSION pgcrypto SET SCHEMA archive", "the extension"),
        ("ALTER ROLE cv_app SET search_path = shadow, public", "the search_path"),
        (
            "ALTER DATABASE candleviewer SET search_path TO shadow, public",
            "the search_path",
        ),
        (
            'ALTER USER cv_app IN DATABASE candleviewer SET "search_path" = shadow',
            "the search_path",
        ),
        ("ALTER ROLE cv_app RESET search_path", "the search_path"),
        ("ALTER ROLE cv_app RESET ALL", "the search_path"),
        (
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT DELETE ON TABLES TO cv_app",
            _DEFAULT_GRANT,
        ),
        (
            "ALTER DEFAULT PRIVILEGES FOR ROLE cv_owner GRANT ALL ON TABLES TO cv_app",
            _DEFAULT_GRANT,
        ),
        ("SET session_replication_role = replica", _TRIGGERS_OFF),
        ("SET LOCAL session_replication_role TO replica", _TRIGGERS_OFF),
        ('SET "SESSION_REPLICATION_ROLE" = replica', _TRIGGERS_OFF),
        ("DO $$ BEGIN SET session_replication_role = replica; END $$", _TRIGGERS_OFF),
        (
            "DO $$ BEGIN EXECUTE 'SET session_replication_role = replica'; END $$",
            _TRIGGERS_OFF,
        ),
        ("ALTER ROLE cv_app SET session_replication_role = replica", _TRIGGERS_OFF),
        ("ALTER FUNCTION f() SET session_replication_role = replica", _TRIGGERS_OFF),
        ("SELECT set_config('session_replication_role', 'replica', false)", _SETTING),
        ("SELECT set_config('lock_timeout', '5s', true)", _SETTING),
        (
            "DO $$ BEGIN EXECUTE format('SET %I = %L', 'session_replication_role',"
            " 'replica'); END $$",
            _SETTING,
        ),
        (
            "DO $$ BEGIN EXECUTE format('SET LOCAL %I = %L', 'session_replication_role',"
            " 'replica'); END $$",
            _SETTING,
        ),
        (
            "CREATE EVENT TRIGGER et ON ddl_command_start EXECUTE FUNCTION f()",
            "an event trigger",
        ),
        ("ALTER EVENT TRIGGER et DISABLE", "an event trigger"),
        (
            "CREATE FUNCTION purge() RETURNS void LANGUAGE plpgsql"
            " SET session_replication_role = replica AS $$ BEGIN NULL; END $$",
            _TRIGGERS_OFF,
        ),
        (
            "CREATE OR REPLACE PROCEDURE p() LANGUAGE sql"
            " SET session_replication_role = replica AS $$ SELECT 1 $$",
            _TRIGGERS_OFF,
        ),
        ("ALTER GROUP cv_owner ADD USER cv_app", "a role's membership"),
        ("CREATE ROLE evil LOGIN IN ROLE cv_owner", "a role's membership"),
        ("CREATE USER evil IN GROUP cv_owner", "a role's membership"),
        ("CREATE ROLE evil SUPERUSER", "a role's membership"),
        ("ALTER ROLE evil SUPERUSER", "a role's membership"),
        ("ALTER USER cv_app WITH SUPERUSER", "a role's membership"),
        ("CREATE GROUP g IN ROLE cv_owner", "a role's membership"),
        ("CREATE ROLE evil CREATEROLE", "a role's membership"),
        ("ALTER ROLE cv_app CREATEROLE", "a role's membership"),
    ],
)
def test_a_statement_that_reaches_the_audit_tables_without_naming_one_is_flagged(
    tmp_path: Path, sql: str, target: str
) -> None:
    """A role's privileges, a schema, a role's objects, the extension the chain hashes
    with and the path it resolves its calls through each hold or reach the audit
    tables or their guards without naming them (#4032)."""
    (message,) = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert f"targets {target}" in message


@pytest.mark.parametrize(
    ("revision", "flagged"), [("0003_audit_log", False), ("0099_other", True)]
)
def test_only_the_revision_that_creates_the_audit_tables_may_add_their_triggers(
    tmp_path: Path, revision: str, flagged: bool
) -> None:
    sql = (
        "CREATE TRIGGER trg_audit_append BEFORE UPDATE OR DELETE ON audit_log"
        " FOR EACH ROW EXECUTE FUNCTION forbid_mutation()"
    )
    source = f'revision: str = "{revision}"\n' + _raw_sql_revision(sql)
    assert bool(_audit_hits(tmp_path, source, f"{revision}.py")) is flagged


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE OR REPLACE TRIGGER trg_audit_append BEFORE UPDATE OR DELETE"
        " ON audit_log FOR EACH ROW WHEN (false) EXECUTE FUNCTION forbid_mutation()",
        "CREATE CONSTRAINT TRIGGER trg_late AFTER INSERT ON audit_log"
        " FOR EACH ROW EXECUTE FUNCTION refuse()",
        "DROP RULE r ON audit_log",
        "CREATE RULE r AS ON INSERT TO audit_log DO INSTEAD NOTHING",
        "GRANT cv_owner TO cv_app",
        "CREATE FUNCTION digest(bytea, text) RETURNS bytea"
        " LANGUAGE sql AS $$ SELECT $1 $$",
    ],
)
def test_the_owner_revision_may_add_no_other_trigger_rule_or_reach(
    tmp_path: Path, sql: str
) -> None:
    """Its exemption covers the `CREATE TRIGGER`s it holds, nothing more."""
    source = 'revision = "0003_audit_log"\n' + _raw_sql_revision(sql)
    assert len(_audit_hits(tmp_path, source, "0003_audit_log.py")) == 1


@pytest.mark.parametrize(
    "source",
    [
        "import sqlalchemy as sa\nfrom alembic import op\n\n\ndef upgrade() -> None:\n"
        '    op.execute(sa.delete(sa.Table("audit_log", sa.MetaData())))\n',
        'import sqlalchemy as sa\nfrom alembic import op\n\nT = "audit_log"\n\n\n'
        "def upgrade() -> None:\n    op.execute(sa.table(T).delete())\n",
        'from alembic import op\n\nT = "audit_log"\n\n\n'
        'def upgrade() -> None:\n    op.alter_column(T, "note", nullable=True)\n',
    ],
    ids=[
        "a-core-Table",
        "a-core-table-through-a-name",
        "an-alembic-table-through-a-name",
    ],
)
def test_an_audit_table_given_through_a_name_or_a_core_table_is_flagged(
    tmp_path: Path, source: str
) -> None:
    (message,) = _audit_hits(tmp_path, source)
    assert "append-only table 'audit_log'" in message


@pytest.mark.parametrize(
    "sql",
    [
        'DROP TABLE U&"audit\\005flog"',
        'DROP TABLE u&"audit\\005flog"',
        "DROP TABLE U&\"audit!005flog\" UESCAPE '!'",
        "DO $$ BEGIN EXECUTE U&'\\0044ELETE FROM audit_log'; END $$",
    ],
)
def test_a_name_or_string_spelled_with_unicode_escapes_is_refused(
    tmp_path: Path, sql: str
) -> None:
    """The rule cannot read them, and they can name an audit table (#4032)."""
    hits = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert any("spelled with Unicode escapes" in hit for hit in hits)


@pytest.mark.parametrize(
    "sql",
    [
        "DO '<<b>> BEGIN DELETE FROM audit_log; END'",
        "DO $$ BEGIN EXECUTE '; DELETE FROM audit_log'; END $$",
        "DO $$ BEGIN EXECUTE '/* x */ DELETE FROM audit_log'; END $$",
        "DO $$ BEGIN EXECUTE '; ALTER TABLE audit_log DISABLE TRIGGER ALL'; END $$",
        "DO $$ DECLARE c refcursor; BEGIN OPEN c FOR DELETE FROM audit_log RETURNING *;"
        " END $$",
        "DO $$ DECLARE c CURSOR FOR DELETE FROM audit_log RETURNING *; BEGIN NULL; END $$",
        'DO LANGUAGE plperl $$ spi_exec_query("DELETE FROM audit_log"); $$',
        "DO LANGUAGE plperl $$ spi_exec_query(q{DELETE FROM audit_log}); $$",
        "CREATE FUNCTION f() RETURNS void LANGUAGE plpython3u"
        " AS $$ plpy.execute('TRUNCATE ' + 'audit_log') $$",
        "DO $$ BEGIN EXECUTE E'\\x44ELETE FROM audit_log'; END $$",
        "DO $$ BEGIN EXECUTE E'DELETE FROM audit\\137log'; END $$",
        "DO $$ BEGIN EXECUTE E'DELETE\\tFROM audit_log'; END $$",
        "DO $$ BEGIN EXECUTE E'\\u0044ELETE FROM audit_log'; END $$",
        "DO $$ BEGIN EXECUTE E'\\U00000044ELETE FROM audit_log'; END $$",
        "DO $$ BEGIN EXECUTE E'DELETE FROM audit_log WHERE note = ''x'''; END $$",
        "DO $$ BEGIN EXECUTE E'DELETE FROM audit_log WHERE note = \\'x\\''; END $$",
        "DO LANGUAGE plperl 'spi_exec_query(\"DELETE FROM audit_log\")'",
        "DO $$ BEGIN PERFORM dblink_exec('DELETE FROM audit_log'); END $$",
        'CREATE FUNCTION f() RETURNS void LANGUAGE "plperl" AS $$ return audit_log; $$',
        "CREATE FUNCTION f() RETURNS void LANGUAGE 'plperl' AS $$ return audit_log; $$",
        "CREATE FUNCTION f() RETURNS void LANGUAGE E'plperl' AS $$ return audit_log; $$",
        "CREATE FUNCTION f() RETURNS void LANGUAGE /* c */ plperl"
        " AS $$ return audit_log; $$",
        "CREATE FUNCTION f() RETURNS void AS $$ return audit_log; $$ LANGUAGE",
        "DO LANGUAGE plperl $$ return audit_log; $$",
    ],
)
def test_sql_a_literal_reader_would_miss_is_read(tmp_path: Path, sql: str) -> None:
    """A literal `EXECUTE` or `DO` runs is read whatever it opens with; a cursor's query
    starts a statement; a body in another language counts by its names; an `E'...'`
    literal is read with its escapes decoded (#4032)."""
    (message,) = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert "append-only table 'audit_log'" in message


@pytest.mark.parametrize(
    ("sql", "target"),
    [
        (
            "DO $$ DECLARE t text := 'audit_log';"
            " BEGIN EXECUTE format('DELETE FROM %I', t); END $$",
            "append-only table 'audit_log'",
        ),
        (
            "DO $$ BEGIN EXECUTE 'DELETE FROM ' || 'audit_log'; END $$",
            "append-only table 'audit_log'",
        ),
        (
            "DO $$ BEGIN EXECUTE format('%s FROM %I', 'DELETE', 'audit_log'); END $$",
            "append-only table 'audit_log'",
        ),
        (
            "DO $$ BEGIN EXECUTE format('DELETE FROM public.%I', 'audit_log'); END $$",
            "append-only table 'audit_log'",
        ),
        (
            "DO $$ DECLARE q text := 'DELE' || 'TE FROM audit_log';"
            " BEGIN EXECUTE q; END $$",
            "a table it names only at run time",
        ),
        (
            "DO $$ BEGIN EXECUTE 'DELETE' || ' FROM audit_log'; END $$",
            "a table it names only at run time",
        ),
        (
            "DO $$ BEGIN EXECUTE format('DROP FUNCTION %I()', 'audit_chain'); END $$",
            "the append-only guard function 'audit_chain'",
        ),
        (
            "DO $$ BEGIN EXECUTE 'DROP FUNCTION ' || 'audit_chain()'; END $$",
            "a table it names only at run time",
        ),
        (
            "DO $$ BEGIN PERFORM dblink_exec('UPDATE' || ' audit_log SET x = 1'); END $$",
            "a table it names only at run time",
        ),
        (
            "DO $$ BEGIN PERFORM dblink_exec('DELETE FROM'); END $$",
            "a table it names only at run time",
        ),
    ],
)
def test_dynamic_sql_whose_target_is_built_is_flagged(
    tmp_path: Path, sql: str, target: str
) -> None:
    """A target passed in, concatenated or held in a variable is the audit table the
    statement names, or refused when it names none (#4032)."""
    (message,) = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert f"targets {target}" in message


@pytest.mark.parametrize(
    "sql",
    [
        "format('UPDATE %I SET x = 1', t)",
        "format('TRUNCATE %I', t)",
        "format('TRUNCATE ONLY %I', t)",
        "format('DELETE FROM %I', t)",
        "format('DROP TABLE IF EXISTS %I', t)",
        "format('ALTER TABLE ONLY %I ADD COLUMN x int', t)",
        "format('MERGE INTO %I USING s ON true WHEN MATCHED THEN DELETE', t)",
        "format('DROP FUNCTION %I()', t)",
        "format('CREATE RULE r AS ON INSERT TO %I DO INSTEAD NOTHING', t)",
        "format('GRANT DELETE ON %I TO cv_app', t)",
        "format('CREATE TRIGGER g BEFORE DELETE ON %I FOR EACH ROW"
        " EXECUTE FUNCTION f()', t)",
        "format('DROP TRIGGER g ON %I', t)",
        "format('UPDATE public.%I SET x = 1', t)",
        "format('DELETE FROM db.public.%I', t)",
        "format('UPDATE' || ' %I SET x = 1', t)",
        "format('UPDATE ' || '%I SET x = 1', t)",
        "format(v_template, t)",
    ],
)
def test_each_target_slot_left_to_run_time_is_refused(tmp_path: Path, sql: str) -> None:
    """Whatever the verb, its target, a grant's or a trigger's `ON` and a rule's `TO`
    hold a name the statement gives, or the statement is refused; so is one whose
    template is not one literal (#4032)."""
    source = _raw_sql_revision(f"DO $$ BEGIN EXECUTE {sql}; END $$")
    (message,) = _audit_hits(tmp_path, source)
    assert "a table it names only at run time" in message


_VALUE = "from alembic import op\nimport sqlalchemy as sa\n\n\ndef upgrade() -> None:\n    {}\n"


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            _raw_sql_revision(
                "CREATE FUNCTION trg() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN"
                " IF TG_OP = 'UPDATE' THEN RETURN NEW; END IF; RETURN OLD; END $$"
            ),
            id="a-trigger-op",
        ),
        pytest.param(
            _raw_sql_revision(
                "CREATE FUNCTION trg() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN"
                " IF TG_OP IN ('UPDATE', 'DELETE') THEN RETURN NULL; END IF;"
                " RETURN NEW; END $$"
            ),
            id="a-list-of-trigger-ops",
        ),
        pytest.param(
            _raw_sql_revision(
                "CREATE TABLE ev (action text CHECK (action IN ('insert', 'update')))"
            ),
            id="a-check",
        ),
        pytest.param(
            _raw_sql_revision("CREATE TYPE act AS ENUM ('create', 'update', 'delete')"),
            id="an-enum",
        ),
        pytest.param(
            _raw_sql_revision("INSERT INTO verbs (v) VALUES ('update')"), id="a-value"
        ),
        pytest.param(
            _raw_sql_revision(
                "ALTER TABLE ev ALTER COLUMN action SET DEFAULT 'update'"
            ),
            id="a-default",
        ),
        pytest.param(
            _raw_sql_revision("SELECT 1 FROM ev WHERE kind = 'truncate'"), id="a-where"
        ),
        pytest.param(
            _VALUE.format(
                "op.create_table('ev', sa.Column('kind',"
                " sa.Enum('create', 'update', name='k')))"
            ),
            id="a-python-enum",
        ),
        pytest.param(
            _VALUE.format(
                "op.add_column('ev', sa.Column('k', sa.Text(), server_default='update'))"
            ),
            id="a-server-default",
        ),
        pytest.param(
            _VALUE.format("op.add_column('ev', sa.Column('update', sa.Text()))"),
            id="a-column",
        ),
        pytest.param(_VALUE.format("kinds = {'update': 1}"), id="a-dict-key"),
        pytest.param(
            _raw_sql_revision(
                "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cv_app')"
                " THEN GRANT EXECUTE ON FUNCTION f() TO cv_app; END IF; END $$"
            ),
            id="a-guarded-grant",
        ),
        pytest.param(
            _raw_sql_revision(
                "DO $$ BEGIN EXECUTE 'REVOKE EXECUTE ON FUNCTION f() FROM PUBLIC'; END $$"
            ),
            id="a-revoke-run-by-execute",
        ),
        pytest.param(
            _raw_sql_revision(
                "DO $$ BEGIN GRANT USAGE, EXECUTE ON FUNCTION f() TO cv_app; END $$"
            ),
            id="a-privilege-list",
        ),
        pytest.param(
            _raw_sql_revision(
                "DO $$ BEGIN REVOKE GRANT OPTION FOR EXECUTE ON FUNCTION f()"
                " FROM cv_app; END $$"
            ),
            id="a-privilege-before-on",
        ),
        pytest.param(
            _raw_sql_revision(
                "DO $$ BEGIN GRANT EXECUTE, USAGE ON FUNCTION f() TO cv_app; END $$"
            ),
            id="a-privilege-after-grant",
        ),
        pytest.param(
            _raw_sql_revision(
                "DO $$ BEGIN GRANT USAGE, EXECUTE, SELECT ON FUNCTION f() TO cv_app;"
                " END $$"
            ),
            id="a-privilege-in-a-list",
        ),
        pytest.param(
            _raw_sql_revision(
                "DO $$ BEGIN REVOKE EXECUTE, USAGE ON FUNCTION f() FROM PUBLIC; END $$"
            ),
            id="a-privilege-after-revoke",
        ),
        pytest.param(
            _raw_sql_revision(
                "CREATE FUNCTION f(a text) RETURNS text LANGUAGE sql"
                " AS $$ SELECT CASE WHEN true THEN $1 ELSE $1 END $$"
            ),
            id="a-parameter-after-then",
        ),
        pytest.param(
            _raw_sql_revision("SELECT u.language FROM audit_log u"),
            id="a-column-named-language",
        ),
    ],
)
def test_a_value_or_a_privilege_that_reads_as_a_verb_is_not_flagged(
    tmp_path: Path, source: str
) -> None:
    """A verb on its own is a value, `EXECUTE` after `GRANT` or before `ON` is a
    privilege, `$1` is a parameter, and a body's language is read only where a
    body is declared (#4032)."""
    assert _audit_hits(tmp_path, source) == []


_BUILT = "from alembic import op\n\n\ndef upgrade() -> None:\n    op.execute({})\n"


@pytest.mark.parametrize(
    ("built", "target"),
    [
        ('"DELETE FROM %s" % "audit_log"', "append-only table 'audit_log'"),
        ('"DELETE FROM {}".format("audit_log")', "append-only table 'audit_log'"),
        ('"DELETE FROM {t}".format(t="audit_log")', "append-only table 'audit_log'"),
        ('"DELETE FROM " + "audit_log"', "append-only table 'audit_log'"),
        ('"".join(["DELETE FROM ", "audit_log"])', "append-only table 'audit_log'"),
        ('"DELETE FROM %s" % get()', "dynamic table name"),
        ('"DELETE FROM {t}".format(t=get())', "dynamic table name"),
        ('"DELETE FROM " + get()', "dynamic table name"),
    ],
)
def test_a_string_built_in_python_is_read_whole(
    tmp_path: Path, built: str, target: str
) -> None:
    """`%`, `.format`, `+` and `.join` build their SQL as an f-string does (#4032)."""
    (message,) = _audit_hits(tmp_path, _BUILT.format(built))
    assert target in message


@pytest.mark.parametrize(
    "source",
    [
        _BUILT.format('"DELETE FROM orders WHERE id = %s" % get()'),
        _BUILT.format('"UPDATE orders SET note = {}".format(get())'),
        _BUILT.format('"".join(part for part in get())'),
        'from alembic import op\n\n_T = "x"\n\n\ndef upgrade() -> None:\n'
        '    """Then update."""\n    op.execute("SELECT 1")\n',
        'def upgrade() -> None:\n    raise RuntimeError("update failed: " + get())\n',
        _raw_sql_revision(
            "DO $$ DECLARE n int; BEGIN"
            " EXECUTE 'SELECT count(*) FROM orders' INTO n; END $$"
        ),
        _raw_sql_revision(
            "DO $$ DECLARE r record; BEGIN FOR r IN EXECUTE"
            " format('SELECT * FROM %I', 'orders') LOOP NULL; END LOOP; END $$"
        ),
        _raw_sql_revision("PREPARE q AS SELECT 1; EXECUTE q"),
        _raw_sql_revision(
            "CREATE FUNCTION f() RETURNS text LANGUAGE sql AS $$ SELECT 'x' $$"
        ),
        _raw_sql_revision(
            "DO $$ BEGIN EXECUTE format('UPDATE public.orders SET x = %L', v); END $$"
        ),
        _raw_sql_revision(
            "DO $$ BEGIN EXECUTE format('DELETE FROM db.public.orders WHERE x = %L', v);"
            " END $$"
        ),
        _raw_sql_revision("DO $$ BEGIN EXECUTE format('TRUNCATE ONLY orders'); END $$"),
        _raw_sql_revision(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'g')"
            " THEN CREATE TRIGGER g BEFORE INSERT ON orders FOR EACH ROW"
            " EXECUTE FUNCTION f(); END IF; END $$"
        ),
        _raw_sql_revision(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'g')"
            " THEN CREATE TRIGGER g BEFORE INSERT ON orders FOR EACH ROW"
            " EXECUTE PROCEDURE f(); END IF; END $$"
        ),
        _raw_sql_revision(
            "DO $$ BEGIN EXECUTE 'UPDATE orders SET note = $1' USING 'x'; END $$"
        ),
        _raw_sql_revision("DO $$ BEGIN EXECUTE 'SELECT 1'; END $$"),
        _raw_sql_revision(
            "DO $$ DECLARE y text; BEGIN EXECUTE format('SELECT %L', (x)) INTO y;"
            " END $$"
        ),
        _raw_sql_revision(
            "CREATE FUNCTION f() RETURNS bigint LANGUAGE 'plpgsql'"
            " AS $$ BEGIN RETURN (SELECT count(*) FROM audit_log); END $$"
        ),
        _raw_sql_revision(
            "CREATE MATERIALIZED VIEW mv AS"
            " WITH x AS (SELECT * FROM audit_log FOR UPDATE) SELECT * FROM x"
        ),
    ],
)
def test_sql_that_names_its_targets_or_mutates_nothing_is_not_flagged(
    tmp_path: Path, source: str
) -> None:
    """A value built in, prose, a read run by `EXECUTE`, a prepared statement and an
    SQL body (#4032)."""
    assert _audit_hits(tmp_path, source) == []


_OPS = "from alembic import op\n\n\ndef upgrade() -> None:\n    {}\n"


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (
            _OPS.format(
                'with op.batch_alter_table("audit_log") as b:\n'
                '        b.drop_column("note")'
            ),
            "append-only table 'audit_log'",
        ),
        (
            "from alembic import op as o\n\n\ndef upgrade() -> None:\n"
            '    o.drop_table("audit_log")\n',
            "append-only table 'audit_log'",
        ),
        (
            "from alembic import op as o\n\n\ndef upgrade() -> None:\n"
            '    o.drop_table(\n        "audit_log"\n    )  # cv:contract-phase: R2\n',
            "append-only table 'audit_log'",
        ),
        (
            _OPS.format('getattr(op, "drop_table")("audit_log")'),
            "append-only table 'audit_log'",
        ),
        (
            _OPS.format('getattr(op, name)("orders")'),
            "an Alembic operation picked at run time",
        ),
        (
            "from alembic import op\nfrom x import T\n\n\ndef upgrade() -> None:\n"
            "    op.drop_table(T)  # cv:contract-phase: R2\n",
            "a table it names only at run time",
        ),
        (
            _OPS.format('op.drop_table(f"audit_{n}")  # cv:contract-phase: R2'),
            "a table it names only at run time",
        ),
        (
            "import sqlalchemy as sa\nfrom alembic import op\n\n\n"
            "def upgrade() -> None:\n"
            '    t = sa.table("audit_log")\n    a = t.alias()\n'
            "    op.execute(sa.delete(a))\n",
            "append-only table 'audit_log'",
        ),
        (
            _OPS.format('op.execute(metadata.tables["audit_log"].delete())'),
            "append-only table 'audit_log'",
        ),
        (
            "import sqlalchemy as sa\nfrom alembic import op\n\n\n"
            "def upgrade() -> None:\n"
            '    op.execute(sa.schema.DropTable(sa.table("audit_log")))\n',
            "append-only table 'audit_log'",
        ),
        (
            "from alembic import op\nfrom sqlalchemy import delete as d, table\n\n\n"
            'def upgrade() -> None:\n    op.execute(d(table("audit_log")))\n',
            "append-only table 'audit_log'",
        ),
        (
            "import sqlalchemy as sa\nfrom alembic import op\n\n\n"
            "def upgrade() -> None:\n    sa.MetaData().drop_all(op.get_bind())\n",
            "every table a MetaData holds",
        ),
        (
            _OPS.format('op.add_column("audit_log", sa.Column("x", sa.Text()))'),
            "append-only table 'audit_log'",
        ),
    ],
)
def test_an_alembic_or_core_operation_on_an_audit_table_is_flagged(
    tmp_path: Path, source: str, target: str
) -> None:
    """However `op` is reached or the table is given, and whichever Core object stands
    for it (#4032)."""
    (message,) = _audit_hits(tmp_path, source)
    assert f"targets {target}" in message


@pytest.mark.parametrize(
    "source",
    [
        _OPS.format('op.drop_column("orders", "legacy")  # cv:contract-phase: R2'),
        _OPS.format('op.drop_index("ix_orders_note")  # cv:contract-phase: R2'),
        _OPS.format('op.add_column("orders", sa.Column("x", sa.Text()))'),
    ],
)
def test_an_alembic_operation_on_another_table_is_not_flagged(
    tmp_path: Path, source: str
) -> None:
    assert _audit_hits(tmp_path, source) == []


def test_alembic_op_drop_on_an_audit_table_is_flagged_once(tmp_path: Path) -> None:
    """The line reader and the call reader each see it; only one reports it."""
    source = 'import alembic\n\n\ndef upgrade() -> None:\n    alembic.op.drop_table("audit_log")\n'
    (message,) = _audit_hits(tmp_path, source)
    assert "append-only table 'audit_log'" in message


@pytest.mark.parametrize(
    ("sql", "flagged"),
    [
        ("CREATE VIEW audit_v AS SELECT * FROM audit_log", True),
        (
            "CREATE OR REPLACE TEMP VIEW audit_v AS SELECT id FROM audit_checkpoints",
            True,
        ),
        (
            "CREATE VIEW audit_v WITH (security_invoker = false)"
            " AS SELECT * FROM audit_log",
            True,
        ),
        (
            "CREATE VIEW audit_v WITH (security_invoker = true)"
            " AS SELECT * FROM audit_log",
            False,
        ),
        (
            "CREATE VIEW audit_v WITH (security_invoker) AS SELECT * FROM audit_log",
            False,
        ),
        ("CREATE TEMPORARY VIEW audit_v AS SELECT * FROM audit_log", True),
        ("CREATE RECURSIVE VIEW audit_v (id) AS SELECT id FROM audit_log", True),
        (
            "CREATE VIEW audit_v WITH (security_invoker = off)"
            " AS SELECT * FROM audit_log",
            True,
        ),
        (
            "CREATE VIEW audit_v WITH (security_invoker = 0) AS SELECT * FROM audit_log",
            True,
        ),
        (
            "CREATE VIEW audit_v WITH (security_invoker = on) AS SELECT * FROM audit_log",
            False,
        ),
        (
            "CREATE VIEW audit_v WITH (security_invoker = 1) AS SELECT * FROM audit_log",
            False,
        ),
        (
            "CREATE VIEW audit_v WITH (security_invoker = yes)"
            " AS SELECT * FROM audit_log",
            False,
        ),
        ("CREATE VIEW open_orders AS SELECT * FROM orders", False),
        (
            "CREATE MATERIALIZED VIEW audit_daily AS SELECT count(*) FROM audit_log",
            False,
        ),
    ],
)
def test_a_view_over_an_audit_table_must_run_as_its_invoker(
    tmp_path: Path, sql: str, flagged: bool
) -> None:
    """A view checks its tables with its owner's privileges unless `security_invoker`
    is set, so a grant on it would reach the audit table past its revoked grants
    (#4032)."""
    hits = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert any("a view over an append-only table" in hit for hit in hits) is flagged


@pytest.mark.parametrize(
    "sql",
    [
        "DO $$ " + "BEGIN DELETE " * 4000 + "FROM audit_log; END $$",
        "DO $$ " + "BEGIN DROP FUNCTION " * 4000 + "audit_chain(); END $$",
        "DO $$ " + "THEN GRANT DELETE " * 4000 + "ON audit_log TO cv_app; END $$",
    ],
    ids=["every-clause-mutates", "every-clause-is-guard-ddl", "every-clause-grants"],
)
def test_a_chunk_whose_every_clause_counts_is_read_in_linear_memory(
    tmp_path: Path, sql: str
) -> None:
    """Each clause start is a position in one index of the chunk, never a copy of the
    rest of it (#4032)."""
    tracemalloc.start()
    try:
        hits = _audit_hits(tmp_path, _raw_sql_revision(sql))
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert hits
    assert peak < 16 * 2**20


def test_a_chunks_names_are_read_once_however_many_clauses_it_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its names are read once, not once per clause (#4032)."""
    calls: list[int] = []
    real = migration_lint._head_identifiers

    def counted(statement: str) -> set[str]:
        calls.append(len(statement))
        return real(statement)

    monkeypatch.setattr(migration_lint, "_head_identifiers", counted)
    sql = "DO $$ " + "BEGIN DROP FUNCTION " * 2000 + "audit_chain(); END $$"
    assert _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert len(calls) <= 4


@pytest.mark.parametrize(
    "sql",
    [
        "-- note\rDELETE FROM audit_log",
        "-- note\rDROP TABLE audit_log",
        "DO $$ BEGIN -- note\rDELETE FROM audit_log; END $$",
    ],
)
def test_a_mutation_after_a_comment_ended_by_a_return_is_flagged(
    tmp_path: Path, sql: str
) -> None:
    """A line comment ends at a return as at a line feed (#4032)."""
    (message,) = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert "append-only table 'audit_log'" in message


_GONE = " AS WITH gone AS (DELETE FROM audit_log RETURNING *) SELECT * FROM gone"


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TEMP TABLE kept" + _GONE,
        "CREATE TEMPORARY TABLE kept" + _GONE,
        "CREATE UNLOGGED TABLE kept" + _GONE,
        "CREATE GLOBAL TEMPORARY TABLE kept" + _GONE,
        "CREATE LOCAL TEMP TABLE kept" + _GONE,
        "DO $$ BEGIN CREATE TABLE kept" + _GONE + "; END $$",
    ],
)
def test_a_table_created_as_a_writing_query_is_flagged(
    tmp_path: Path, sql: str
) -> None:
    """A table created `AS` a query carries that query's writes (#4032)."""
    (message,) = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert "append-only table 'audit_log'" in message


def test_a_nested_block_comment_is_refused(tmp_path: Path) -> None:
    """Postgres nests block comments; the reader would end the outer one early."""
    sql = "/* a /* b */ c */ DELETE FROM audit_log"
    hits = _audit_hits(tmp_path, _raw_sql_revision(sql))
    assert any("a block comment nested in another" in hit for hit in hits)


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE kept AS SELECT * FROM orders",
        "CREATE TABLE notes (id int REFERENCES audit_log (id) ON DELETE CASCADE)",
        "/* one comment */ SELECT 1",
    ],
)
def test_a_created_table_or_a_comment_that_writes_nothing_is_not_flagged(
    tmp_path: Path, sql: str
) -> None:
    assert _audit_hits(tmp_path, _raw_sql_revision(sql)) == []
