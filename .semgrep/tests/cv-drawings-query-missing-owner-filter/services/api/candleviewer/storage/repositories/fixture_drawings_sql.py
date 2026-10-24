# Fixture for cv-drawings-query-missing-owner-filter (E14-X03): the text-SQL arm. A marker sits on the
# line a finding starts on: the call (`text(`, `execute(`) or assignment that opens the statement.
import sqlalchemy as sa

# --- fires: a statement on `drawings` with no `owner_user_id = :owner` predicate ----------------
_SELECT = sa.text(  # ruleid: cv-drawings-query-missing-owner-filter
    "SELECT id::text AS id FROM drawings WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
)
_UPDATE = sa.text("UPDATE drawings SET label = :label WHERE id = CAST(:id AS uuid)")  # ruleid: cv-drawings-query-missing-owner-filter
_OTHER_OWNER = sa.text(  # ruleid: cv-drawings-query-missing-owner-filter
    "SELECT 1 FROM drawings WHERE id = CAST(:id AS uuid) AND owner_user_id <> CAST(:owner AS uuid)"
)
_COLUMN_ONLY = sa.text("SELECT owner_user_id FROM drawings WHERE id = :id")  # ruleid: cv-drawings-query-missing-owner-filter
_SPLIT_NAME = sa.text(  # ruleid: cv-drawings-query-missing-owner-filter
    "SELECT id FROM "
    "drawings WHERE symbol = :symbol"
)
_JOINED = sa.text(  # ruleid: cv-drawings-query-missing-owner-filter
    "SELECT d.id FROM layouts l JOIN drawings d ON d.layout_id = l.id WHERE l.id = :lid"
)
_CORRELATED = sa.text(  # ruleid: cv-drawings-query-missing-owner-filter
    "DELETE FROM layouts WHERE id IN (SELECT id FROM layouts WHERE deleted_at IS NOT NULL "
    "AND NOT EXISTS (SELECT 1 FROM drawings d WHERE d.layout_id = layouts.id))"
)
_TRANSFER = sa.text("UPDATE drawings SET owner_user_id = CAST(:owner AS uuid), label = :label WHERE id = CAST(:id AS uuid)")  # ruleid: cv-drawings-query-missing-owner-filter
_COPY = sa.text("INSERT INTO drawings (id, owner_user_id) SELECT :new, CAST(:owner AS uuid) FROM drawings WHERE id = :id")  # ruleid: cv-drawings-query-missing-owner-filter
_RAW = sa.text(r"SELECT id FROM drawings WHERE id = :id")  # ruleid: cv-drawings-query-missing-owner-filter
_PREFIXED = sa.text(u"SELECT id FROM drawings WHERE id = :id")  # ruleid: cv-drawings-query-missing-owner-filter


async def raw(conn):
    await conn.execute("DELETE FROM drawings WHERE id = :id", {"id": 1})  # ruleid: cv-drawings-query-missing-owner-filter


# --- quiet: scoped, another table, or not a SELECT, UPDATE or DELETE ---------------------------
_SCOPED = sa.text(  # ok: cv-drawings-query-missing-owner-filter
    "SELECT id FROM drawings WHERE id = CAST(:id AS uuid) AND owner_user_id = CAST(:owner AS uuid)"
)
_ALIASED = sa.text(  # ok: cv-drawings-query-missing-owner-filter
    "UPDATE drawings d SET label = :label WHERE d.id = :id AND d.owner_user_id = :owner"
)
_QUALIFIED = sa.text(  # ok: cv-drawings-query-missing-owner-filter
    "UPDATE drawings SET geometry = r.n_geometry FROM jsonb_to_recordset(CAST(:rows AS jsonb)) "
    "AS r(n_id uuid, n_geometry jsonb) WHERE drawings.id = r.n_id "
    "AND drawings.owner_user_id = CAST(:owner AS uuid)"
)
_PREDICATE_SPLIT = sa.text(  # ok: cv-drawings-query-missing-owner-filter
    "DELETE FROM drawings WHERE id = ANY(CAST(:ids AS uuid[])) AND owner_user_id = "
    "CAST(:owner AS uuid)"
)
_RAW_SCOPED = sa.text(r"SELECT id FROM drawings WHERE id = :id AND owner_user_id = CAST(:owner AS uuid)")  # ok: cv-drawings-query-missing-owner-filter
_INSERT_MANY = sa.text(  # ok: cv-drawings-query-missing-owner-filter
    "INSERT INTO drawings (id, owner_user_id) SELECT n_id, CAST(:owner AS uuid) "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(n_id uuid)"
)
_OTHER_TABLES = sa.text(  # ok: cv-drawings-query-missing-owner-filter
    "SELECT id FROM layouts WHERE owner_user_id = :owner AND id NOT IN (SELECT id FROM drawing_templates)"
)
_NOT_SQL = "the drawings table: DELETE FROM it only in the purge"  # ok: cv-drawings-query-missing-owner-filter
# SELECT 1 FROM drawings WHERE id = :id is only quoted in this comment  # ok: cv-drawings-query-missing-owner-filter

# The reviewed annotation, on the line above the statement's first line, suppresses the finding.
# nosemgrep: cv-drawings-query-missing-owner-filter reason=fixture-purge owner=@basiltt review=2027-03-25
_PURGE = sa.text(  # ok: cv-drawings-query-missing-owner-filter
    "DELETE FROM drawings WHERE id IN (SELECT id FROM drawings WHERE deleted_at < now() LIMIT :n)"
)
