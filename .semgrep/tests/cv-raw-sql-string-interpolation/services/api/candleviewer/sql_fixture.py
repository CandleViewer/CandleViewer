"""Fixtures for cv-raw-sql-string-interpolation.
Run with: python tools/ci/check_semgrep_rule_tests.py (covers cv-raw-sql-string-interpolation)
"""

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy import text as sql_text
from sqlalchemy.sql import text as sub_text
from sqlalchemy.sql.expression import text as expr_text
from tests.contract._admin_support import text as _text

BOOTSTRAP_MARKER = "(i.role = CAST('owner' AS role_name) AND i.invited_by = i.user_id)"
TEMPLATE = "SELECT @M@ FROM orders"


def bad_fstring(conn: object, account_id: str) -> None:
    conn.execute(f"SELECT * FROM orders WHERE account_id = {account_id}")  # ruleid: cv-raw-sql-string-interpolation


def bad_percent(conn: object, account_id: str) -> None:
    conn.execute("SELECT * FROM orders WHERE account_id = %s" % account_id)  # ruleid: cv-raw-sql-string-interpolation


def bad_format(conn: object, account_id: str) -> None:
    conn.execute("SELECT * FROM orders WHERE account_id = {}".format(account_id))  # ruleid: cv-raw-sql-string-interpolation


def bad_concat(conn: object, account_id: str) -> None:
    conn.execute("SELECT * FROM orders WHERE account_id = " + account_id)  # ruleid: cv-raw-sql-string-interpolation


def ok_parameterised(conn: object, account_id: str) -> None:
    params = {"account_id": account_id}
    query = "SELECT * FROM orders WHERE account_id = :account_id"
    conn.execute(query, params)  # ok: cv-raw-sql-string-interpolation


def bad_sa_text(account_id: str, fragment: str) -> None:
    sa.text(f"SELECT * FROM orders WHERE account_id = {account_id}")  # ruleid: cv-raw-sql-string-interpolation
    sa.text("SELECT * FROM orders WHERE account_id = %s" % account_id)  # ruleid: cv-raw-sql-string-interpolation
    sa.text("SELECT * FROM orders WHERE account_id = {}".format(account_id))  # ruleid: cv-raw-sql-string-interpolation
    sa.text("SELECT @M@ FROM orders".replace("@M@", fragment))  # ruleid: cv-raw-sql-string-interpolation
    text("SELECT @M@ FROM orders".replace("@M@", fragment))  # ruleid: cv-raw-sql-string-interpolation
    sql_text(f"SELECT * FROM orders WHERE account_id = {account_id}")  # ruleid: cv-raw-sql-string-interpolation
    sa.text(TEMPLATE.replace("@M@", fragment))  # ruleid: cv-raw-sql-string-interpolation
    sa.text("SELECT @C@ FROM orders @W@".replace("@C@", BOOTSTRAP_MARKER).replace("@W@", TEMPLATE))  # ruleid: cv-raw-sql-string-interpolation


def bad_sql_paths(account_id: str) -> None:
    # `sa.sql.text`, `sa.sql.expression.text` and renamed imports of them are SQLAlchemy's `text`.
    sa.sql.text(f"SELECT * FROM orders WHERE account_id = {account_id}")  # ruleid: cv-raw-sql-string-interpolation
    sub_text("SELECT * FROM orders WHERE account_id = %s" % account_id)  # ruleid: cv-raw-sql-string-interpolation
    sa.sql.expression.text("SELECT * FROM orders WHERE account_id = {}".format(account_id))  # ruleid: cv-raw-sql-string-interpolation
    expr_text("SELECT @C@ FROM orders @W@".replace("@C@", BOOTSTRAP_MARKER).replace("@W@", TEMPLATE))  # ruleid: cv-raw-sql-string-interpolation


def bad_helper_receiver(template: str, fragment: str) -> None:
    # A helper's template is a variable, so the literal is out of sight: the replacement is what counts.
    sa.text(template.replace("@C@", fragment, 1))  # ruleid: cv-raw-sql-string-interpolation
    sa.text(template.replace("@C@", BOOTSTRAP_MARKER).replace("@W@", fragment))  # ruleid: cv-raw-sql-string-interpolation


def bad_by_name(text: object, template: str, fragment: str) -> None:
    # A `text` that is not SQLAlchemy's (a parameter, a local helper) is matched by its name alone.
    text("SELECT @C@ FROM orders @W@".replace("@C@", BOOTSTRAP_MARKER).replace("@W@", TEMPLATE))  # ruleid: cv-raw-sql-string-interpolation
    text(template.replace("@C@", fragment, 1))  # ruleid: cv-raw-sql-string-interpolation


def bad_splice_helper(marker: str) -> sa.TextClause:
    """A helper splicing a fragment into a whole literal: the form Bandit B608 caught."""
    return sa.text(  # ruleid: cv-raw-sql-string-interpolation
        "SELECT @M@ AS bootstrap, (i.consumed_at IS NOT NULL) AS usable FROM user_invites i "
        "WHERE i.id = CAST(:iid AS uuid) FOR NO KEY UPDATE OF i".replace("@M@", marker)
    )


def bad_first_build() -> sa.TextClause:
    """The first build of the bootstrap mint: `.replace` inside an UPDATE ... OR (@M@) literal."""
    return sa.text(  # ruleid: cv-raw-sql-string-interpolation
        "UPDATE user_invites i SET revoked_at = :now WHERE i.revoked_at IS NULL "
        "AND (i.user_id = CAST(:id AS uuid) OR (@M@)) RETURNING i.id".replace("@M@", BOOTSTRAP_MARKER)
    )


def ok_whole_literals(dsn: str, name: str, template: str) -> str:
    sa.text("SELECT * FROM orders WHERE account_id = :account_id")  # ok: cv-raw-sql-string-interpolation
    # BOOTSTRAP_MARKER written out in the statement, never spliced into it.
    sa.text(  # ok: cv-raw-sql-string-interpolation
        "SELECT (i.role = CAST('owner' AS role_name) AND i.invited_by = i.user_id) "
        "FROM user_invites i WHERE i.id = CAST(:iid AS uuid)"
    )
    dsn.replace("postgresql+asyncpg", "postgresql")  # ok: cv-raw-sql-string-interpolation
    sa.text("SELECT :x").bindparams(x="a".replace("a", "b"))  # ok: cv-raw-sql-string-interpolation
    # A helper splicing module constants only: the shape of the reviewed `_sql(template)` helpers.
    sa.text(template.replace("@M@", BOOTSTRAP_MARKER, 1).replace("@T@", TEMPLATE))  # ok: cv-raw-sql-string-interpolation
    # A helper imported as `text` under another name is not SQLAlchemy's `text`.
    _text("%s summary" % name)  # ok: cv-raw-sql-string-interpolation
    _text("{} summary".format(name))  # ok: cv-raw-sql-string-interpolation
    _text("@ summary".replace("@", name))  # ok: cv-raw-sql-string-interpolation
    return _text(f"{name} summary")  # ok: cv-raw-sql-string-interpolation
