"""Postgres order and order-event store (E29-T01 #845 slice 2/3, migration `0029_oms_core`).

SQLAlchemy Core over `db.models.orders` and `db.models.order_events`: every value is a bound
parameter and nothing is built from strings. Reads select the explicit allow-lists `ORDER_COLUMNS`
and `EVENT_COLUMNS`, never `*`. Every statement filters on `orders.exchange_account_id` (C-12.4)
except the two in `UNSCOPED`: the insert, which writes the account it is given, and the 24 Sec.8.3
rule 5 yes/no over the global `ux_orders_link`. A unit test pins that set.

`create` writes the order and its first event (`seq` 0) in one statement, a data-modifying CTE:
one round trip in one transaction (#845 performance notes). `append` first locks the order row
inside the account, then inserts the event with the next `seq` in a second statement, whose fresh
snapshot sees every committed event; the lock serialises appends to one order, so `seq` stays
dense and `UNIQUE (order_id, seq)` is only the backstop. Inside the statement builders, before
anything is bound, `payload` passes `redact_exchange_payload()` and `ret_msg` and `ret_code` pass
`redact_exchange_text()` (21 Sec.3.3.5; the #845 security notes).

Every unit of work first caps each of its statements, lock waits included, at the store's
`statement_timeout` (`OMS_STATEMENT_TIMEOUT_MS`, the #845 default of `CV_OMS_STATEMENT_TIMEOUT_MS`,
instead of the repository-wide 30 s), so a blocked order write fails within it and the OMS can
refuse the order (24 Sec.8.2 S7) rather than hold the submit path.

A database error of any call, read or write, never leaves with its statement, parameters or
`DETAIL`, which carry P1 money values (21 Sec.12): it is re-raised `from None` as
`OrderConstraintError(name)` or `StorageQueryFailed(sqlstate)` (C-12.6), so callers handle one
error family.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import fields
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from candleviewer.db.models import order_events, orders
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.exchange_payload import (
    MAX_CODE_CHARS,
    redact_exchange_payload,
    redact_exchange_text,
)
from candleviewer.storage.repositories.orders import (
    EVENT_FIELDS,
    MAX_EVENT_PAGE,
    OPEN_STATES,
    NewOrder,
    NewOrderEvent,
    OrderConstraintError,
    OrderEventRow,
    OrderNotFoundError,
    OrderRow,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    SqlAlchemyUnitOfWork,
)

_O = orders.c
_E = order_events.c
ORDER_COLUMNS: Final = tuple(_O[f.name] for f in fields(OrderRow))
EVENT_COLUMNS: Final = tuple(_E[name] for name in EVENT_FIELDS)
#: Statements without an `orders.exchange_account_id` filter (see the module docstring); tested.
UNSCOPED: Final = frozenset({"create_statement", "link_taken_statement"})
#: The default per-statement cap of the order store, in ms (#845 technical notes).
OMS_STATEMENT_TIMEOUT_MS: Final = 2000
#: Transaction-local (`true`), like the repository's `SET LOCAL`; the admin read model's form.
_SET_TIMEOUT: Final = sa.text("SELECT set_config('statement_timeout', :timeout, true)")
#: SQLSTATEs that carry a constraint name: unique, check and foreign-key violations.
_NAMED_VIOLATIONS: Final = frozenset({"23505", "23514", "23503"})


def _event_values(event: NewOrderEvent) -> dict[str, Any]:
    return {
        "kind": event.kind,
        "source": event.source,
        "payload": redact_exchange_payload(event.payload),
        "ret_code": redact_exchange_text(event.ret_code, max_chars=MAX_CODE_CHARS),
        "ret_msg": redact_exchange_text(event.ret_msg),
        "latency_ms": event.latency_ms,
        "event_ts": event.event_ts,
    }


def create_statement(order: NewOrder, event: NewOrderEvent) -> sa.Select[Any]:
    values = {f.name: getattr(order, f.name) for f in fields(NewOrder)}
    inserted = sa.insert(orders).values(values).returning(*ORDER_COLUMNS).cte("inserted_order")
    first = (
        sa.insert(order_events)
        .values(
            order_id=sa.select(inserted.c.id).scalar_subquery(),
            seq=sa.literal_column("0"),  # the first event of an order, a constant in the SQL
            to_state=sa.select(inserted.c.state).scalar_subquery(),
            **_event_values(event),
        )
        .cte("first_event")
    )
    return sa.select(*inserted.c).add_cte(first)


def get_statement(account_id: UUID, order_id: UUID) -> sa.Select[Any]:
    return sa.select(*ORDER_COLUMNS).where(_O.exchange_account_id == account_id, _O.id == order_id)


def get_by_link_statement(account_id: UUID, order_link_id: str) -> sa.Select[Any]:
    return sa.select(*ORDER_COLUMNS).where(
        _O.exchange_account_id == account_id, _O.order_link_id == order_link_id
    )


def list_open_statement(account_id: UUID, symbol: str | None) -> sa.Select[Any]:
    """Rendered with the states as literals, so the planner can match `ix_orders_open`."""
    states: sa.BindParameter[Any] = sa.bindparam(
        "open", sorted(OPEN_STATES), expanding=True, literal_execute=True
    )
    stmt = sa.select(*ORDER_COLUMNS).where(
        _O.exchange_account_id == account_id, _O.state.in_(states)
    )
    if symbol is not None:  # compared as text: SQLAlchemy 2.1 has no operator class for DOMAIN
        stmt = stmt.where(sa.type_coerce(_O.symbol, sa.Text) == symbol)
    return stmt.order_by(_O.created_ts, _O.id)


def link_taken_statement(order_link_id: str) -> sa.Select[Any]:
    return sa.select(sa.exists().where(_O.order_link_id == order_link_id))


def lock_statement(account_id: UUID, order_id: UUID) -> sa.Select[Any]:
    stmt = sa.select(_O.order_link_id).where(
        _O.exchange_account_id == account_id, _O.id == order_id
    )
    return stmt.with_for_update(key_share=True)  # FOR NO KEY UPDATE: inserts keep their FK check


def append_statement(account_id: UUID, order_id: UUID, event: NewOrderEvent) -> sa.Insert:
    """No state transition: `from_state` and `to_state` stay NULL."""
    prior = order_events.alias("prior")
    owned = sa.select(_O.id).where(_O.exchange_account_id == account_id, _O.id == order_id)
    next_seq = sa.select(sa.func.coalesce(sa.func.max(prior.c.seq) + 1, 0)).where(
        prior.c.order_id == order_id
    )
    return (
        sa.insert(order_events)
        .values(
            order_id=owned.scalar_subquery(),
            seq=next_seq.scalar_subquery(),
            **_event_values(event),
        )
        .returning(*EVENT_COLUMNS)
    )


def list_events_statement(
    account_id: UUID, order_id: UUID, after_seq: int, limit: int
) -> sa.Select[Any]:
    return (
        sa.select(*EVENT_COLUMNS, _O.order_link_id)
        .join(orders, _O.id == _E.order_id)
        .where(_O.exchange_account_id == account_id, _E.order_id == order_id, _E.seq > after_seq)
        .order_by(_E.seq)
        .limit(limit)
    )


def _order(row: Mapping[Any, Any]) -> OrderRow:
    return OrderRow(**{f.name: row[f.name] for f in fields(OrderRow)})


def _event(row: Mapping[Any, Any], order_link_id: str) -> OrderEventRow:
    return OrderEventRow(order_link_id=order_link_id, **{name: row[name] for name in EVENT_FIELDS})


def _sqlstate(exc: DBAPIError) -> str | None:
    value = getattr(exc.orig, "sqlstate", None)
    return value if isinstance(value, str) else None


def _violated_constraint(exc: DBAPIError) -> str | None:
    """The constraint a unique, check or FK violation names, wherever the driver puts it."""
    if _sqlstate(exc) not in _NAMED_VIOLATIONS:
        return None
    orig: Any = exc.orig
    for source in (orig, getattr(orig, "__cause__", None), getattr(orig, "driver_exception", None)):
        name = getattr(source, "constraint_name", None)
        if name:
            return str(name)
    return None


@contextmanager
def _constraints() -> Iterator[None]:
    """A database refusal leaves as a named constraint or a SQLSTATE, never chained (C-12.6)."""
    try:
        yield
    except DBAPIError as exc:
        name = _violated_constraint(exc)
        if name is None:
            raise StorageQueryFailed(_sqlstate(exc)) from None
        raise OrderConstraintError(name) from None


class SqlAlchemyOrderStore:
    """`OrderStore` and `OrderEventStore` over one relational repository (asyncpg)."""

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        statement_timeout_ms: int = OMS_STATEMENT_TIMEOUT_MS,
    ) -> None:
        # Postgres reads 0 as "no cap", and a bool is an int: neither is a cap.
        if (
            isinstance(statement_timeout_ms, bool)
            or not isinstance(statement_timeout_ms, int)
            or statement_timeout_ms < 1
        ):
            raise ValueError("statement_timeout_ms must be an int of at least 1")
        self._relational = relational
        self._timeout = str(statement_timeout_ms)

    @asynccontextmanager
    async def _unit_of_work(self) -> AsyncIterator[SqlAlchemyUnitOfWork]:
        """One transaction whose statements the store's cap bounds; a database error leaves it
        as `OrderConstraintError` or `StorageQueryFailed`, unchained."""
        with _constraints():
            async with self._relational.unit_of_work() as uow:
                await uow.session.execute(_SET_TIMEOUT, {"timeout": self._timeout})
                yield uow

    async def create(self, order: NewOrder, first_event: NewOrderEvent) -> OrderRow:
        stmt = create_statement(order, first_event)
        async with self._unit_of_work() as uow:
            row = (await uow.session.execute(stmt)).mappings().one()
            await uow.commit()
        return _order(row)

    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None:
        return await self._one(get_statement(account_id, order_id))

    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> OrderRow | None:
        return await self._one(get_by_link_statement(account_id, order_link_id))

    async def list_open(
        self, account_id: UUID, *, symbol: str | None = None
    ) -> tuple[OrderRow, ...]:
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(list_open_statement(account_id, symbol))
            return tuple(_order(row) for row in result.mappings())

    async def link_id_taken(self, order_link_id: str) -> bool:
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(link_taken_statement(order_link_id))
            return bool(result.scalar_one())

    async def append(self, account_id: UUID, order_id: UUID, event: NewOrderEvent) -> OrderEventRow:
        async with self._unit_of_work() as uow:
            lock = await uow.session.execute(lock_statement(account_id, order_id))
            order_link_id = lock.scalar_one_or_none()
            if order_link_id is None:
                raise OrderNotFoundError
            stmt = append_statement(account_id, order_id, event)
            row = (await uow.session.execute(stmt)).mappings().one()
            await uow.commit()
        return _event(row, order_link_id)

    async def list_for_order(
        self, account_id: UUID, order_id: UUID, *, after_seq: int = -1, limit: int = MAX_EVENT_PAGE
    ) -> tuple[OrderEventRow, ...]:
        if after_seq < -1 or not 1 <= limit <= MAX_EVENT_PAGE:
            raise ValueError(f"after_seq must be >= -1 and limit 1..{MAX_EVENT_PAGE}")
        stmt = list_events_statement(account_id, order_id, after_seq, limit)
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(stmt)
            return tuple(_event(row, row["order_link_id"]) for row in result.mappings())

    async def _one(self, stmt: sa.Select[Any]) -> OrderRow | None:
        async with self._unit_of_work() as uow:
            row = (await uow.session.execute(stmt)).mappings().first()
        return None if row is None else _order(row)


__all__ = [
    "EVENT_COLUMNS", "OMS_STATEMENT_TIMEOUT_MS", "ORDER_COLUMNS", "UNSCOPED",
    "SqlAlchemyOrderStore", "append_statement", "create_statement", "get_by_link_statement",
    "get_statement", "link_taken_statement", "list_events_statement", "list_open_statement",
    "lock_statement",
]  # fmt: skip
