# Fixture for cv-oms-unscoped-select in a store with PEP 695 syntax, which Semgrep parses another
# way (#3549).
import sqlalchemy as sa

from candleviewer.db.models import orders

_O = orders.c

type Row = dict[str, object]


def first[R](rows: list[R]) -> R:
    return rows[0]


def holder(order_id):
    return sa.select(_O.exchange_account_id).where(_O.id == order_id)  # ruleid: cv-oms-unscoped-select


def scoped(account_id, order_id):
    return sa.select(_O.id).where(_O.exchange_account_id == account_id, _O.id == order_id)  # ok: cv-oms-unscoped-select
