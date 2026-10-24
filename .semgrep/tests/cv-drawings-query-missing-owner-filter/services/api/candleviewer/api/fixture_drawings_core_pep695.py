# Fixture for cv-drawings-query-missing-owner-filter (E14-X03): the Core arm and the text arm in a
# file with PEP 695 generics (Semgrep parses it another way, #3549). A marker sits on the call's line.
import sqlalchemy as sa

from candleviewer.db.models import drawings, layouts


def first[T](rows: list[T]) -> T:
    return rows[0]


def core(did, owner, label):
    sa.select(drawings).where(drawings.c.id == did)  # ruleid: cv-drawings-query-missing-owner-filter
    sa.update(drawings).where(drawings.c.id == did).values(label=label)  # ruleid: cv-drawings-query-missing-owner-filter
    sa.delete(drawings).where(drawings.c.id == did)  # ruleid: cv-drawings-query-missing-owner-filter
    sa.select(drawings).where(drawings.c.owner_user_id != owner)  # ruleid: cv-drawings-query-missing-owner-filter
    sa.select(drawings).where(drawings.c.owner_user_id == owner, drawings.c.id == did)  # ok: cv-drawings-query-missing-owner-filter
    sa.delete(drawings).where(sa.and_(drawings.c.id == did, drawings.c.owner_user_id == owner))  # ok: cv-drawings-query-missing-owner-filter
    sa.select(layouts).where(layouts.c.id == did)  # ok: cv-drawings-query-missing-owner-filter


_COUNT = sa.text("SELECT count(*) FROM drawings WHERE symbol = :symbol")  # ruleid: cv-drawings-query-missing-owner-filter
_COUNT_OWN = sa.text("SELECT count(*) FROM drawings WHERE owner_user_id = :owner")  # ok: cv-drawings-query-missing-owner-filter
