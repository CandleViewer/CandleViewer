"""Fixtures for cv-storage-sql-construction (E07-X02, SR-097 neighbourhood)."""
import sqlalchemy as sa
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy import text as sql_text
from sqlalchemy.sql import text as sub_text
from sqlalchemy.sql.expression import text as expr_text

BOOTSTRAP_MARKER = "(i.role = CAST('owner' AS role_name) AND i.invited_by = i.user_id)"
TEMPLATE = "SELECT @M@ FROM t"


async def bad(conn, sym, parts):
    await conn.execute(f"SELECT * FROM t WHERE s = '{sym}'")  # ruleid: cv-storage-sql-construction
    await conn.execute("SELECT * FROM t WHERE s = '%s'" % sym)  # ruleid: cv-storage-sql-construction
    await conn.fetch("SELECT * FROM t WHERE s = '" + sym + "'")  # ruleid: cv-storage-sql-construction
    return text(f"DELETE FROM t WHERE s = '{sym}'")  # ruleid: cv-storage-sql-construction


async def bad_sa_text(sym, fragment, marker):
    sa.text(f"DELETE FROM t WHERE s = '{sym}'")  # ruleid: cv-storage-sql-construction
    sa.text(f"SELECT {sym}" " FROM t WHERE a = :a")  # ruleid: cv-storage-sql-construction
    sa.text("DELETE FROM t WHERE s = '" + sym + "'")  # ruleid: cv-storage-sql-construction
    sa.text("DELETE FROM t WHERE s = '%s'" % sym)  # ruleid: cv-storage-sql-construction
    sa.text("DELETE FROM t WHERE s = '{}'".format(sym))  # ruleid: cv-storage-sql-construction
    sa.text("SELECT @M@ FROM t".replace("@M@", fragment))  # ruleid: cv-storage-sql-construction
    text("SELECT @M@ FROM t".replace("@M@", fragment))  # ruleid: cv-storage-sql-construction
    sql_text(f"DELETE FROM t WHERE s = '{sym}'")  # ruleid: cv-storage-sql-construction
    sa.text(TEMPLATE.replace("@M@", fragment))  # ruleid: cv-storage-sql-construction
    sa.text("SELECT @C@ FROM t @W@".replace("@C@", BOOTSTRAP_MARKER).replace("@W@", TEMPLATE))  # ruleid: cv-storage-sql-construction
    # A helper splicing a fragment into a whole literal: the form Bandit B608 caught.
    sa.text(  # ruleid: cv-storage-sql-construction
        "SELECT @M@ AS bootstrap, (i.consumed_at IS NOT NULL) AS usable FROM user_invites i "
        "WHERE i.id = CAST(:iid AS uuid) FOR NO KEY UPDATE OF i".replace("@M@", marker)
    )
    # The first build of the bootstrap mint: `.replace` inside an UPDATE ... OR (@M@) literal.
    return sa.text(  # ruleid: cv-storage-sql-construction
        "UPDATE user_invites i SET revoked_at = :now WHERE i.revoked_at IS NULL "
        "AND (i.user_id = CAST(:id AS uuid) OR (@M@)) RETURNING i.id".replace("@M@", BOOTSTRAP_MARKER)
    )


async def bad_sql_paths(sym):
    # `sa.sql.text`, `sa.sql.expression.text` and renamed imports of them are SQLAlchemy's `text`.
    sa.sql.text(f"SELECT {sym}" " FROM t")  # ruleid: cv-storage-sql-construction
    sub_text("DELETE FROM t WHERE s = '" + sym + "'")  # ruleid: cv-storage-sql-construction
    sa.sql.expression.text("DELETE FROM t WHERE s = '%s'" % sym)  # ruleid: cv-storage-sql-construction
    expr_text("DELETE FROM t WHERE s = '{}'".format(sym))  # ruleid: cv-storage-sql-construction
    sa.sql.text("SELECT @C@ FROM t @W@".replace("@C@", BOOTSTRAP_MARKER).replace("@W@", TEMPLATE))  # ruleid: cv-storage-sql-construction


async def bad_helper_receiver(template, fragment):
    # A helper's template is a variable, so the literal is out of sight: the replacement is what counts.
    sa.text(template.replace("@C@", fragment, 1))  # ruleid: cv-storage-sql-construction
    sa.text(template.replace("@C@", BOOTSTRAP_MARKER).replace("@W@", fragment))  # ruleid: cv-storage-sql-construction


async def bad_by_name(text, template, sym, fragment):
    # A `text` that is not SQLAlchemy's (a parameter, a local helper) is matched by its name alone.
    text(f"SELECT {sym}" " FROM t")  # ruleid: cv-storage-sql-construction
    text("SELECT @C@ FROM t @W@".replace("@C@", BOOTSTRAP_MARKER).replace("@W@", TEMPLATE))  # ruleid: cv-storage-sql-construction
    text(template.replace("@C@", fragment, 1))  # ruleid: cv-storage-sql-construction


async def good(conn, sym):
    await conn.execute("SELECT * FROM t WHERE s = $1", sym)  # ok: cv-storage-sql-construction
    return text("SELECT 1 WHERE s = :s")  # ok: cv-storage-sql-construction


async def good_sa_text(dsn, sym, template):
    sa.text("DELETE FROM t WHERE s = :s")  # ok: cv-storage-sql-construction
    # BOOTSTRAP_MARKER written out in the statement, never spliced into it.
    sa.text(  # ok: cv-storage-sql-construction
        "SELECT (i.role = CAST('owner' AS role_name) AND i.invited_by = i.user_id) "
        "FROM user_invites i WHERE i.id = CAST(:iid AS uuid)"
    )
    dsn.replace("postgresql+asyncpg", "postgresql")  # ok: cv-storage-sql-construction
    sa.text("SELECT :x").bindparams(x="a".replace("a", "b"))  # ok: cv-storage-sql-construction
    # A helper splicing module constants only: the shape of the reviewed `_sql(template)` helpers.
    sa.text(template.replace("@M@", BOOTSTRAP_MARKER, 1).replace("@T@", TEMPLATE))  # ok: cv-storage-sql-construction
    st.text(f"abc {sym}")  # ok: cv-storage-sql-construction
    st.text("abc {}".format(sym))  # ok: cv-storage-sql-construction
    st.text("abc %s" % sym)  # ok: cv-storage-sql-construction
    st.text("ab".replace("a", sym))  # ok: cv-storage-sql-construction
    return st.text("abc" + sym)  # ok: cv-storage-sql-construction
