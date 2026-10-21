"""Unit tests for `tools/ci/migration_lint.py` (E03-T10).

Fixture migration files (destructive annotated, destructive unannotated,
additive, ambiguous batch operations) per the ticket's test plan.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.migration_lint import (
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
