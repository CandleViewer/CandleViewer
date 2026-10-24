"""Postgres order and order-event store (E29-T01 #845, migration `0029_oms_core`).

SQLAlchemy Core over `db.models.orders` and `db.models.order_events`: every value is a bound
parameter and nothing is built from strings. Reads select the explicit allow-lists `ORDER_COLUMNS`
and `EVENT_COLUMNS`, never `*`. Every statement filters on `orders.exchange_account_id` (C-12.4),
or for the entry-stop settle on `recorded_stops.exchange_account_id`, except those in `UNSCOPED`:
the insert, which writes the account it is given, the 24 Sec.8.3 rule 5 yes/no over the global
`ux_orders_link`, and E29-T04's startup hydration read (21 Sec.13.1 row 49), whose two statements
read one environment's accounts, then their unfinished orders. A unit test pins that set. The exit
routes' two reads (E29-T04 slice 4) hold the principal's scope instead, `scope_clause`, the one
predicate both take.

`create` writes the order and its first event (`seq` 0) in one statement, a data-modifying CTE:
one round trip in one transaction (#845 performance notes). `append` first locks the order row
inside the account, then inserts the event with the next `seq` in a second statement, whose fresh
snapshot sees every committed event; the lock serialises appends to one order, so `seq` stays
dense and `UNIQUE (order_id, seq)` is only the backstop. Inside the statement builders, before
anything is bound, `payload` passes `redact_exchange_payload()` and `ret_msg` and `ret_code` pass
`redact_exchange_text()`, `ret_msg` with the message rule (21 Sec.3.3.5; the #845 security notes).

A write-ahead step (E29-T03: `transition`; `commit_fill` in `executions_sqlalchemy.py`) locks its
order row in the account, runs the compare-and-set UPDATE, appends the event with both states and
commits; a missed compare-and-set raises `StaleOrderState` and rolls back (24 Sec.8.2 S7, S8). The
send's step counts `submit_attempts` up in SQL, and a step that names `entry_stops` settles its
entry's recorded stops (`settle_entry_stops_statement`, scoped by `recorded_stops`' account and the
order) before that commit, in the same transaction (E29-T04, 21 Sec.3.3.11); a void there also
needs the order to hold no recorded fill, read after the step's own update (SEC-2A-01).
Before any statement, `transition` refuses a fill's event and `filled`, `append` a fill's event
(`require_no_fill`): a fill comes with its execution.

Every unit of work first caps each of its statements, lock waits included, at the store's
`statement_timeout` (`OMS_STATEMENT_TIMEOUT_MS`, the #845 default of `CV_OMS_STATEMENT_TIMEOUT_MS`,
instead of the repository-wide 30 s), so a blocked order write fails within it and the OMS can
refuse the order (24 Sec.8.2 S7) rather than hold the submit path. The cap does not cover opening
a connection or waiting for the pool; the OMS bounds each call itself (`orders.py`).

A failure of any call, read or write, never leaves with its statement, parameters or `DETAIL`,
which carry P1 money values (21 Sec.12), and is never chained (C-12.6). A database error is
re-raised `from None` as `OrderConstraintError(name)` or `StorageQueryFailed(sqlstate)`; a
connection the store cannot get or loses (an `OSError` from the driver, connect timeouts
included, the pool's checkout `TimeoutError`, or a `DBAPIError` that is `connection_invalidated`,
of SQLSTATE class 08, as asyncpg reports a connection lost mid-statement, or of a server that
does not serve, `_NOT_SERVING`) as `StorageTierUnavailable` (24 Sec.8.2 S7: Postgres is
unavailable). A write-ahead hook's `WriteAheadTimeout` (E29-T04's first persist) passes as it is:
the unit of work rolled back, so it is no outcome in doubt. Cancellation passes through unchanged.
So a caller meets `OrderStoreError` or `StorageError`, never a driver or pool exception.
"""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Collection, Iterable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, fields
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import DBAPIError

from candleviewer.db.models import (
    exchange_accounts,
    idempotency_anchors,
    order_events,
    orders,
    recorded_stops,
    roles,
    trade_group_legs,
    trade_groups,
    user_account_access,
    user_roles,
    users,
)
from candleviewer.domain.primitives import Environment
from candleviewer.storage.errors import (
    StorageQueryFailed,
    StorageTierUnavailable,
    WriteAheadTimeout,
)
from candleviewer.storage.repositories.accounts import AccountScope, OwnerScope
from candleviewer.storage.repositories.exchange_payload import (
    MAX_CODE_CHARS,
    redact_exchange_payload,
    redact_exchange_text,
)
from candleviewer.storage.repositories.executions import OrderFill
from candleviewer.storage.repositories.orders import (
    EVENT_FIELDS,
    MAX_EVENT_PAGE,
    OPEN_STATES,
    UNFINISHED_STATES,
    CommittedStep,
    EntryStopSettle,
    NewOrder,
    NewOrderEvent,
    OrderConstraintError,
    OrderEventRow,
    OrderNotFoundError,
    OrderRow,
    OrderTransition,
    OutOfScope,
    ScopedOrder,
    StaleOrderState,
    require_exchange_order_id,
    require_exchange_record,
    require_limit,
    require_no_fill,
    settle_accounts,
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
UNSCOPED: Final = frozenset({
    "create_statement", "link_taken_statement", "environment_accounts_statement",
    "list_unfinished_statement",
})  # fmt: skip
#: The default per-statement cap of the order store, in ms (#845 technical notes).
OMS_STATEMENT_TIMEOUT_MS: Final = 2000
#: Transaction-local (`true`), like the repository's `SET LOCAL`; the admin read model's form.
_SET_TIMEOUT: Final = sa.text("SELECT set_config('statement_timeout', :timeout, true)")
#: SQLSTATEs that carry a constraint name: unique, check and foreign-key violations.
_NAMED_VIOLATIONS: Final = frozenset({"23505", "23514", "23503"})
#: A server that does not serve: shut down (57P01, 57P02), starting (57P03), full (53300).
_NOT_SERVING: Final = frozenset({"57P01", "57P02", "57P03", "53300"})


def require_audit_bound(seconds: float) -> float:
    """A store's write-ahead audit bound, in seconds: finite and above zero, as a NaN or an
    infinity would leave the hook unbounded (C-2.18); `ValueError` otherwise. The OMS stores that
    await a caller's audit hook (`submissions_sqlalchemy`, `recorded_stops_sqlalchemy`) share it."""
    if isinstance(seconds, bool) or not (
        isinstance(seconds, int | float) and math.isfinite(seconds) and seconds > 0
    ):
        raise ValueError("audit_timeout_s must be a finite number of seconds above zero")
    return seconds


def _event_values(event: NewOrderEvent) -> dict[str, Any]:
    return {
        "kind": event.kind,
        "source": event.source,
        "payload": redact_exchange_payload(event.payload),
        "ret_code": redact_exchange_text(event.ret_code, max_chars=MAX_CODE_CHARS),
        "ret_msg": redact_exchange_text(event.ret_msg, message=True),
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


def get_by_exchange_statement(account_id: UUID, exchange_order_id: str) -> sa.Select[Any]:
    """21 Sec.13.1 row 12: `ux_orders_exch_id` serves it."""
    return sa.select(*ORDER_COLUMNS).where(
        _O.exchange_account_id == account_id, _O.exchange_order_id == exchange_order_id
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


def environment_accounts_statement(environment: Environment) -> sa.Select[Any]:
    """Every account of `environment`, a disabled or soft-deleted one too (20 Sec.6.2)."""
    accounts = exchange_accounts.c
    return sa.select(accounts.id).where(accounts.env == environment)


def list_unfinished_statement(account_ids: Iterable[UUID], limit: int) -> sa.Select[Any]:
    """21 Sec.13.1 row 49: these accounts' orders in `UNFINISHED_STATES`, oldest first, at most
    `limit`; the states rendered as literals, as `list_open_statement`'s are."""
    states: sa.BindParameter[Any] = sa.bindparam(
        "unfinished", sorted(UNFINISHED_STATES), expanding=True, literal_execute=True
    )
    ids = sa.bindparam("accounts", sorted({str(a) for a in account_ids}), type_=ARRAY(sa.Text))
    stmt = sa.select(*ORDER_COLUMNS).where(
        _O.exchange_account_id == sa.any_(sa.cast(ids, ARRAY(sa.Uuid))), _O.state.in_(states)
    )
    return stmt.order_by(_O.created_ts, _O.id).limit(limit)


def scope_clause(
    scope: AccountScope, environment: Environment, *, trade: bool
) -> sa.ColumnElement[bool]:
    """C-12.4, written once for the exit routes (E29-T04 slice 4): the `exchange_accounts` rows
    `scope` reaches in `environment`, not deleted. An Owner's while its user holds a live owner
    role; a grant's among the scope's ids while the user's `user_account_access` row lets it view,
    unfrozen, and trade too when `trade`: SR-051's predicates (`accounts_sqlalchemy`), so a stale
    snapshot only narrows. A grant scope with no id reaches nothing."""
    ea = exchange_accounts.c
    live = (ea.deleted_at.is_(None), ea.env == environment)
    if isinstance(scope, OwnerScope):
        ur, role, user = user_roles.c, roles.c, users.c
        held = user_roles.join(roles, role.id == ur.role_id).join(users, user.id == ur.user_id)
        owner = sa.select(ur.user_id).select_from(held).where(
            ur.user_id == scope.user_id, role.name == "owner", user.deleted_at.is_(None),
            user.status == "active", sa.or_(ur.expires_at.is_(None), ur.expires_at > sa.func.now()),
        )  # fmt: skip
        return sa.and_(*live, owner.exists())
    if not scope.account_ids:
        return sa.false()
    access = user_account_access.c
    grant = [access.user_id == scope.user_id, access.exchange_account_id == ea.id, access.can_view]
    grant += [sa.not_(access.frozen), *([access.can_trade] if trade else [])]
    granted = ea.id.in_(sorted(scope.account_ids))
    return sa.and_(*live, granted, sa.select(access.user_id).where(*grant).exists())


def in_scope_statement(
    scope: AccountScope, order_id: UUID, environment: Environment
) -> sa.Select[Any]:
    """`get_in_scope`'s one statement: the order with its leg's group and profile, its creator
    (its group's, else its anchor's, which `COALESCE` reads for an order with no group only) and
    whether the scope may trade its account, only where `scope_clause` holds; beside it, the
    account of the order holding the id, whatever the scope, for the refusal's audit (ruling Q12).
    So one row answers, and no column of an order outside the scope leaves the database."""
    legs, groups, anchors = trade_group_legs.c, trade_groups.c, idempotency_anchors.c
    anchored = sa.select(anchors.created_by).where(anchors.order_id == _O.id).limit(1)
    tree = (
        orders.join(exchange_accounts, exchange_accounts.c.id == _O.exchange_account_id)
        .outerjoin(trade_group_legs, legs.id == _O.trade_group_leg_id)
        .outerjoin(trade_groups, groups.id == legs.trade_group_id)
    )
    scoped = (
        sa.select(
            *ORDER_COLUMNS, legs.trade_group_id, legs.account_profile_id.label("profile_id"),
            sa.func.coalesce(groups.created_by, anchored.scalar_subquery()).label("created_by"),
            scope_clause(scope, environment, trade=True).label("can_trade"),
        )
        .select_from(tree)
        .where(_O.id == order_id, scope_clause(scope, environment, trade=False))
        .subquery("scoped")
    )  # fmt: skip
    held = orders.alias("held")
    holder = sa.select(held.c.exchange_account_id).where(held.c.id == order_id).scalar_subquery()
    probe = sa.select(holder.label("holder")).subquery("probe")
    return sa.select(probe.c.holder, *scoped.c).select_from(probe.outerjoin(scoped, sa.true()))


def accounts_in_scope_statement(
    scope: AccountScope, environment: Environment, requested: Collection[UUID]
) -> sa.Select[Any]:
    """`accounts_in_scope`'s one statement: the accounts of `environment` the scope may trade
    (`scope_clause`), among `requested` when it names any, by id."""
    ea = exchange_accounts.c
    stmt = sa.select(ea.id).where(scope_clause(scope, environment, trade=True))
    if requested:
        stmt = stmt.where(ea.id.in_(sorted(set(requested))))
    return stmt.order_by(ea.id)


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


def transition_statement(step: OrderTransition) -> sa.Update:
    """The compare-and-set: the row moves only while it holds `step.from_state`. The send's step
    counts an attempt in SQL, from the stored count."""
    held = (_O.exchange_account_id == step.account_id, _O.id == step.order_id)
    values: dict[str, Any] = step.changes()
    if step.bump_submit_attempts:
        values["submit_attempts"] = _O.submit_attempts + 1
    stmt = sa.update(orders).where(*held, _O.state == step.from_state).values(values)
    return stmt.returning(*ORDER_COLUMNS)


def fill_statement(fill: OrderFill) -> sa.Update:
    """The step's compare-and-set with the totals, holding only while the stored `cum_exec_qty`
    plus this fill's `exec_qty` is the new one: totals computed from an older row write nothing."""
    held = _O.cum_exec_qty + fill.execution.exec_qty == fill.totals.cum_exec_qty
    return transition_statement(fill.step).values(asdict(fill.totals)).where(held)


def settle_entry_stops_statement(
    account_id: UUID, order_id: UUID, settle: EntryStopSettle, at: datetime
) -> sa.Update:
    """The entry's attach rows still pending (21 Sec.3.3.11): `answered` stamps the ones in flight,
    `void` ends every one; a row in force or ended is left as it is. `void` also needs the order to
    hold no recorded fill (SEC-2A-01): `commit_step` runs it after the step's own compare-and-set
    and a fill's totals, in the same transaction, so a fill the store holds is never voided,
    whatever the caller decided."""
    rs = recorded_stops.c
    stmt = sa.update(recorded_stops).where(
        rs.exchange_account_id == account_id,
        rs.order_id == order_id,
        rs.source == "entry_attach",
        rs.status == "pending",
    )
    if settle == "answered":
        return stmt.where(rs.answered_at.is_(None)).values(answered_at=at)
    filled = sa.select(sa.literal(1)).where(_O.id == rs.order_id, _O.cum_exec_qty > 0)
    return stmt.where(~sa.exists(filled)).values(status="void", closed_at=at)


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


async def lock_order(uow: SqlAlchemyUnitOfWork, account_id: UUID, order_id: UUID) -> sa.RowMapping:
    """Lock the order row in its account and read what a fill is checked against, `qty` and
    `is_paper`, or raise `OrderNotFoundError`."""
    stmt = lock_statement(account_id, order_id).add_columns(_O.qty, _O.is_paper)
    row = (await uow.session.execute(stmt)).mappings().first()
    if row is None:
        raise OrderNotFoundError
    return row


async def commit_step(
    uow: SqlAlchemyUnitOfWork, change: OrderTransition | OrderFill
) -> CommittedStep:
    """A step once `lock_order` holds its row: the compare-and-set, its event, the commit."""
    if isinstance(change, OrderFill):
        step, cas = change.step, fill_statement(change)
    else:
        step, cas = change, transition_statement(change)
    row = (await uow.session.execute(cas)).mappings().first()
    if row is None:
        raise StaleOrderState(step.order_id, step.from_state)
    stmt = append_statement(step.account_id, step.order_id, step.event)
    states = {"from_state": step.from_state, "to_state": step.to_state}
    event = (await uow.session.execute(stmt.values(states))).mappings().one()
    if step.entry_stops is not None:
        settle = settle_entry_stops_statement(
            step.account_id, step.order_id, step.entry_stops, step.event.event_ts
        )
        await uow.session.execute(settle)
    await uow.commit()
    return CommittedStep(order_row(row), _event(event, row["order_link_id"]))


def order_row(row: Mapping[Any, Any]) -> OrderRow:
    """An `orders` row as read (`ORDER_COLUMNS`); the first persist reuses it."""
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
    """A database refusal leaves as a named constraint or a SQLSTATE, and a connection the store
    cannot get or loses as `StorageTierUnavailable` naming only the error's type; never chained
    (C-12.6). `CancelledError` is no `Exception`, so cancellation passes through."""
    try:
        yield
    except DBAPIError as exc:
        state = _sqlstate(exc) or ""
        if exc.connection_invalidated or state.startswith("08") or state in _NOT_SERVING:
            raise StorageTierUnavailable(f"postgres unreachable ({type(exc).__name__})") from None
        name = _violated_constraint(exc)
        if name is None:
            raise StorageQueryFailed(_sqlstate(exc)) from None
        raise OrderConstraintError(name) from None
    except WriteAheadTimeout:
        raise  # a write-ahead hook's bound, not the database's, although it is a `TimeoutError` too
    except (OSError, sa.exc.TimeoutError) as exc:
        raise StorageTierUnavailable(f"postgres unreachable ({type(exc).__name__})") from None


class CappedStore:
    """Base of the OMS stores over one relational repository (asyncpg): each unit of work caps its
    statements and maps its failures as the module docstring says."""

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
        """One transaction whose statements the store's cap bounds; a failure leaves it as
        `OrderConstraintError`, `StorageQueryFailed` or `StorageTierUnavailable`, unchained."""
        with _constraints():
            async with self._relational.unit_of_work() as uow:
                await uow.session.execute(_SET_TIMEOUT, {"timeout": self._timeout})
                yield uow


class SqlAlchemyOrderStore(CappedStore):
    """`OrderStore` and `OrderEventStore` over one relational repository (asyncpg)."""

    async def create(self, order: NewOrder, first_event: NewOrderEvent) -> OrderRow:
        require_exchange_record(first_event)
        stmt = create_statement(order, first_event)
        async with self._unit_of_work() as uow:
            row = (await uow.session.execute(stmt)).mappings().one()
            await uow.commit()
        return order_row(row)

    async def transition(self, step: OrderTransition) -> CommittedStep:
        require_no_fill(step.event, step.to_state)
        async with self._unit_of_work() as uow:
            await lock_order(uow, step.account_id, step.order_id)
            return await commit_step(uow, step)

    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None:
        return await self._one(get_statement(account_id, order_id))

    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> OrderRow | None:
        return await self._one(get_by_link_statement(account_id, order_link_id))

    async def get_by_exchange_order_id(
        self, account_id: UUID, exchange_order_id: str
    ) -> OrderRow | None:
        require_exchange_order_id(exchange_order_id)
        return await self._one(get_by_exchange_statement(account_id, exchange_order_id))

    async def list_open(
        self, account_id: UUID, *, symbol: str | None = None
    ) -> tuple[OrderRow, ...]:
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(list_open_statement(account_id, symbol))
            return tuple(order_row(row) for row in result.mappings())

    async def list_unfinished(
        self, environment: Environment, *, limit: int
    ) -> tuple[OrderRow, ...]:
        """`UnfinishedOrders`: the environment's accounts, then their unfinished orders, in one
        unit of work; no account reads no orders."""
        require_limit(limit)
        async with self._unit_of_work() as uow:
            found = await uow.session.execute(environment_accounts_statement(environment))
            accounts = [row["id"] for row in found.mappings()]
            if not accounts:
                return ()
            result = await uow.session.execute(list_unfinished_statement(accounts, limit))
            return tuple(order_row(row) for row in result.mappings())

    async def environment_accounts(self, environment: Environment) -> tuple[UUID, ...]:
        """`UnfinishedOrders`: every account of the environment, whatever its status."""
        async with self._unit_of_work() as uow:
            found = await uow.session.execute(environment_accounts_statement(environment))
            return tuple(UUID(str(row["id"])) for row in found.mappings())

    async def link_id_taken(self, order_link_id: str) -> bool:
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(link_taken_statement(order_link_id))
            return bool(result.scalar_one())

    async def get_in_scope(
        self, scope: AccountScope, order_id: UUID, *, environment: Environment
    ) -> ScopedOrder | OutOfScope:
        stmt = in_scope_statement(scope, order_id, environment)
        async with self._unit_of_work() as uow:
            row = (await uow.session.execute(stmt)).mappings().one()
        if row["id"] is None:
            return OutOfScope(row["holder"])
        found = (row["trade_group_id"], row["profile_id"], row["created_by"], row["can_trade"])
        return ScopedOrder(order_row(row), found[0], found[1], found[2], bool(found[3]))

    async def accounts_in_scope(
        self, scope: AccountScope, environment: Environment, requested: Collection[UUID]
    ) -> tuple[UUID, ...]:
        stmt = accounts_in_scope_statement(scope, environment, requested)
        async with self._unit_of_work() as uow:
            found = await uow.session.execute(stmt)
            reach = [UUID(str(row["id"])) for row in found.mappings()]
        return settle_accounts(reach, requested)

    async def append(self, account_id: UUID, order_id: UUID, event: NewOrderEvent) -> OrderEventRow:
        require_no_fill(event)
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
        return None if row is None else order_row(row)


__all__ = [
    "EVENT_COLUMNS", "OMS_STATEMENT_TIMEOUT_MS", "ORDER_COLUMNS", "UNSCOPED", "CappedStore",
    "SqlAlchemyOrderStore", "accounts_in_scope_statement", "append_statement", "commit_step",
    "create_statement", "environment_accounts_statement", "fill_statement",
    "get_by_exchange_statement", "get_by_link_statement", "get_statement", "in_scope_statement",
    "link_taken_statement", "list_events_statement", "list_open_statement",
    "list_unfinished_statement", "lock_order", "lock_statement", "order_row",
    "require_audit_bound", "scope_clause", "settle_entry_stops_statement", "transition_statement",
]  # fmt: skip
