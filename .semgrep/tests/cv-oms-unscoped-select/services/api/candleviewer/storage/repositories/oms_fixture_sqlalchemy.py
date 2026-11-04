# Fixture for cv-oms-unscoped-select (E29-X02): selects of `orders`, `positions` and `executions`
# rows in an OMS store, with and without the account in SQL. A marker sits on the select's line.
import sqlalchemy as sa
from sqlalchemy import select

from candleviewer.db import models as m
from candleviewer.db.models import executions, orders, positions, trade_group_legs
from candleviewer.storage.repositories.executions_sqlalchemy import EXECUTION_COLUMNS
from candleviewer.storage.repositories.orders_sqlalchemy import ORDER_COLUMNS, scope_clause
from candleviewer.storage.repositories.positions_sqlalchemy import POSITION_COLUMNS

_O, _X, _P, _L = orders.c, executions.c, positions.c, trade_group_legs.c
_Q = positions.c


def unscoped(order_id, position_id, link, account_id):
    sa.select(*ORDER_COLUMNS).where(_O.id == order_id)  # ruleid: cv-oms-unscoped-select
    sa.select(_P.exchange_account_id).where(_P.id == position_id)  # ruleid: cv-oms-unscoped-select
    sa.select(_Q.symbol, _Q.size)  # ruleid: cv-oms-unscoped-select
    sa.select(orders.c.id).where(orders.c.order_link_id == link)  # ruleid: cv-oms-unscoped-select
    sa.select(m.executions.c.exec_id)  # ruleid: cv-oms-unscoped-select
    sa.select(sa.exists().where(_O.order_link_id == link))  # ruleid: cv-oms-unscoped-select
    select(*EXECUTION_COLUMNS).where(_X.order_id == order_id)  # ruleid: cv-oms-unscoped-select
    orders.select().where(orders.c.id == order_id)  # ruleid: cv-oms-unscoped-select
    sa.select(*POSITION_COLUMNS).where(_P.exchange_account_id != account_id)  # ruleid: cv-oms-unscoped-select
    held = orders.alias("held")
    sa.select(held.c.exchange_account_id).where(held.c.id == order_id)  # ruleid: cv-oms-unscoped-select
    o, p = orders.c, positions.c
    sa.select(p.symbol).where(p.size > 0)  # ruleid: cv-oms-unscoped-select
    # the account belongs in the select's own chain: a `where` on another statement is not seen
    stmt = sa.select(*ORDER_COLUMNS)  # ruleid: cv-oms-unscoped-select
    return stmt.where(o.exchange_account_id == account_id)


def scoped(scope, environment, account_id, accounts, order_id):
    sa.select(*ORDER_COLUMNS).where(_O.exchange_account_id == account_id, _O.id == order_id)  # ok: cv-oms-unscoped-select
    sa.select(_O.id).where(_O.id == order_id, account_id == _O.exchange_account_id)  # ok: cv-oms-unscoped-select
    sa.select(*POSITION_COLUMNS).where(_P.exchange_account_id.in_(accounts))  # ok: cv-oms-unscoped-select
    sa.select(*EXECUTION_COLUMNS).where(_X.exchange_account_id == sa.any_(accounts))  # ok: cv-oms-unscoped-select
    sa.select(*ORDER_COLUMNS, _L.trade_group_id).select_from(orders).where(  # ok: cv-oms-unscoped-select
        scope_clause(scope, environment, _O.exchange_account_id, trade=False)
    )
    sa.select(orders.c.id).filter(orders.c.exchange_account_id == account_id)  # ok: cv-oms-unscoped-select
    sa.select(sa.literal(1)).where(_O.id == order_id, _O.cum_exec_qty > 0)  # ok: cv-oms-unscoped-select
    sa.select(_L.trade_group_id).where(_L.id == order_id)  # ok: cv-oms-unscoped-select
    sa.select(m.exchange_accounts.c.id)  # ok: cv-oms-unscoped-select


def position_holder_statement(position_id):
    """Unscoped by design: the marker placement the store's reviewed exceptions use."""
    # nosemgrep: cv-oms-unscoped-select reason=holder-probe owner=@CandleViewer/security review=2027-02-04
    return sa.select(_P.exchange_account_id).where(_P.id == position_id)  # ok: cv-oms-unscoped-select
