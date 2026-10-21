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
    ],
)
def test_audit_mutation_spelled_any_valid_way_is_flagged(
    tmp_path: Path, sql: str
) -> None:
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


@pytest.mark.parametrize("source", [_CORE_DELETE, _CORE_UPDATE_BY_NAME])
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
        "CREATE TRIGGER trg BEFORE UPDATE OR DELETE ON audit_log"
        " FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
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
        "DELETE FROM orders WHERE note = 'audit_log rows are kept'",
    ],
)
def test_a_statement_that_mutates_no_audit_table_is_not_flagged(
    tmp_path: Path, sql: str
) -> None:
    """The append-only guards themselves, reads, inserts and another table's rows."""
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
            "0099_other.py",
            'from alembic import op\n\nREV = "0099_other"\nrevision = REV\n'
            + _UPGRADE.replace(
                "-> None:\n", '-> None:\n    revision = "0003_audit_log"\n'
            ),
            id="a-function-scope-claim",
        ),
        pytest.param(
            "0099_other.py",
            'from alembic import op\n\nrevision = "0003_audit_log"\n'
            'revision = "0099_other"\n' + _UPGRADE,
            id="an-earlier-module-level-claim",
        ),
        pytest.param(
            "0099_other.py",
            'from alembic import op\n\nREV = "0099_other"\nrevision = REV\n\n\n'
            'class _Meta:\n    revision = "0003_audit_log"\n' + _UPGRADE,
            id="a-class-body-claim",
        ),
    ],
)
def test_no_other_revision_can_claim_the_owner_exemption(
    tmp_path: Path, name: str, source: str
) -> None:
    """The owner is the file the migrations lockfile pins by name and bytes, with the
    id Alembic reads: the last module-level `revision`, a string constant."""
    assert _audit_hits(tmp_path, source, name)


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
