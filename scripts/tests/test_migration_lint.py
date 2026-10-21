"""Unit tests for `tools/ci/migration_lint.py` (E03-T10).

Fixture migration files (destructive annotated, destructive unannotated,
additive, ambiguous batch operations) per the ticket's test plan.
"""

from __future__ import annotations

import sys
import tracemalloc
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


_PIN = "0045_audit_search_path"
_PIN_SOURCE = f'''"""Pin the audit guard functions' search_path (#4032)."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "{_PIN}"
down_revision: str | None = "0044_account_no_hard_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Each guard function resolves its calls through the pinned path."""
    op.execute("ALTER FUNCTION audit_chain() SET search_path = pg_catalog, public, pg_temp")
    op.execute(
        "ALTER FUNCTION audit_field(text) SET search_path = pg_catalog,public,pg_temp;"
        " ALTER FUNCTION forbid_mutation() SET search_path TO pg_catalog, public, pg_temp;"
        " ALTER FUNCTION public.audit_refuse_truncate()"
        "   SET search_path = pg_catalog, public, pg_temp;"
    )


def downgrade() -> None:
    op.execute("ALTER FUNCTION audit_chain() RESET search_path")
    op.execute(
        "ALTER FUNCTION audit_field(text) RESET search_path;"
        " ALTER FUNCTION forbid_mutation() RESET search_path;"
        " ALTER FUNCTION audit_refuse_truncate() RESET search_path"
    )
'''
_PIN_SET = (
    'op.execute("ALTER FUNCTION audit_chain() SET search_path = pg_catalog, public, '
    'pg_temp")'
)
_PIN_RESET = 'op.execute("ALTER FUNCTION audit_chain() RESET search_path")'


def test_the_search_path_pin_revision_holding_only_its_pin_is_exempt(
    tmp_path: Path,
) -> None:
    assert _PIN_SET in _PIN_SOURCE and _PIN_RESET in _PIN_SOURCE
    assert _audit_hits(tmp_path, _PIN_SOURCE, f"{_PIN}.py") == []


@pytest.mark.parametrize(
    ("name", "source"),
    [
        pytest.param(
            "0099_other.py",
            _PIN_SOURCE.replace(_PIN, "0099_other"),
            id="the-pin-in-another-revision",
        ),
        pytest.param(
            f"{_PIN}.py",
            _PIN_SOURCE.replace(f'revision: str = "{_PIN}"', 'revision = "0099_other"'),
            id="the-pin-file-name-with-another-id",
        ),
    ],
)
def test_no_other_revision_can_claim_the_pin_exemption(
    tmp_path: Path, name: str, source: str
) -> None:
    """Its statements are then read as any revision's: each pins a guard function."""
    hits = _audit_hits(tmp_path, source, name)
    assert len(hits) == 8
    assert all("append-only guard function '" in hit for hit in hits)


_PIN_DEVIATIONS = {
    "another-statement": (
        _PIN_SET,
        _PIN_SET.replace(
            'pg_temp")', 'pg_temp; DROP TRIGGER trg_audit_append ON audit_log")'
        ),
    ),
    "another-path": (
        _PIN_SET,
        _PIN_SET.replace("pg_catalog, public", "public, pg_catalog"),
    ),
    "no-pg_temp": (_PIN_SET, _PIN_SET.replace(", pg_temp", "")),
    "another-function": (_PIN_SET, _PIN_SET.replace("audit_chain", "touch_updated_at")),
    "a-quoted-name": (_PIN_SET, _PIN_SET.replace("audit_chain", '\\"audit_chain\\"')),
    "a-comment": (_PIN_SET, _PIN_SET.replace("() SET", "() /* x */ SET")),
    "reset-in-the-upgrade": (_PIN_SET, _PIN_RESET),
    "set-in-the-downgrade": (_PIN_RESET, _PIN_SET),
    "another-call": (_PIN_SET, _PIN_SET + '\n    op.drop_table("audit_log")'),
    "a-name-not-a-constant": (
        _PIN_SET,
        "op.execute(_SQL)",
    ),
    "an-f-string": (_PIN_SET, _PIN_SET.replace('op.execute("', 'op.execute(f"')),
    "another-import": ("from alembic import op", "from alembic import op, context"),
    "an-annotation-that-runs-code": (
        "down_revision: str | None",
        "down_revision: print() or str",
    ),
    "a-decorator": ("def upgrade()", "@print\ndef upgrade()"),
    "a-default-argument": ("def upgrade()", "def upgrade(x=print())"),
    "a-module-statement": ("\n\ndef upgrade()", "\nprint()\n\n\ndef upgrade()"),
}


@pytest.mark.parametrize("case", sorted(_PIN_DEVIATIONS))
def test_a_pin_revision_holding_anything_else_is_refused(
    tmp_path: Path, case: str
) -> None:
    """It may hold only its pin: anything else is refused, and its statements are
    read as any revision's (#4032)."""
    old, new = _PIN_DEVIATIONS[case]
    assert _PIN_SOURCE.count(old) == 1
    hits = _audit_hits(tmp_path, _PIN_SOURCE.replace(old, new), f"{_PIN}.py")
    assert any("the search_path pin revision may hold only" in hit for hit in hits)
    assert any("append-only guard function 'audit_field'" in hit for hit in hits)


def test_a_pin_revision_refusal_names_the_line_that_deviates(tmp_path: Path) -> None:
    source = _PIN_SOURCE.replace(_PIN_RESET, _PIN_SET)
    line = source.splitlines().index("def downgrade() -> None:") + 2  # its first call
    refusals = [
        hit
        for hit in _audit_hits(tmp_path, source, f"{_PIN}.py")
        if "the search_path pin revision" in hit
    ]
    assert [hit.split(":")[0] for hit in refusals] == [f"line {line}"]


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
