"""Postgres reads of the stuck-order detector (E29-T08 #916; 24-internal-schemas.md Sec.8.13;
21-database-schema.md Sec.3.3.4, Sec.3.3.5, Sec.3.3.7; the ruling of record on #916, BQ-3, BQ-4).

Three statements, each of one environment's accounts (C-2.11), at most `limit` rows, under the
store's statement cap (`CappedStore`), with no migration (BQ-3): candidates from the partial
indexes their predicates name, never an index-only read.

* `in_flight_statement`: rows whose create is in flight (`ix_orders_inflight`, `idempotency_state =
  'in_flight'`) in a state that is not final, oldest first;
* `open_stuck_statement`: rows in `unknown` or with a cancel or an amend pending (`ix_orders_open`);
* `naked_statement`: open positions with no exchange-side stop (`ix_pos_no_sl`) that no live
  `recorded_stop` row protects on their closing side (a Partial-mode stop is an order; BQ-4), and
  not paper.

An order's age is read in its statement: the `recv_ts` of its latest `order_events` row (the
highest `seq`, a lateral read over the `(order_id, seq)` key) against the database's `now()`, so
the host's clock never skews it. Each predicate a partial index names is rendered as a literal,
so the planner can match the index whatever plan it caches. A failure leaves as the store's
`StorageError`, unchained and with no value (C-12.6); the caller bounds each call (C-2.18).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa

from candleviewer.db.models import exchange_accounts, order_events, orders, positions
from candleviewer.domain.primitives import Environment
from candleviewer.storage.repositories.orders_sqlalchemy import CappedStore
from candleviewer.storage.repositories.stuck import (
    FINAL_STATES,
    OPEN_STUCK_STATES,
    NakedPositionRow,
    StuckOrderRow,
)

__all__ = [
    "PROTECTING_STATES",
    "SqlAlchemyStuckReads",
    "in_flight_statement",
    "naked_statement",
    "open_stuck_statement",
]

#: The persisted states in which a materialised recorded stop's row rests at the exchange and so
#: protects its position (21 Sec.3.3.4): accepted, triggered, part filled, or with its own cancel
#: or amend pending. One in `unknown` protects nothing the scan can show (C-2.6).
PROTECTING_STATES: Final = frozenset(
    {"accepted", "triggered", "partially_filled", "pending_cancel", "pending_amend"}
)
_O, _E, _P, _A = orders.c, order_events.c, positions.c, exchange_accounts.c


def _literal(name: str, states: Collection[str]) -> sa.BindParameter[Any]:
    return sa.bindparam(name, sorted(states), expanding=True, literal_execute=True)


def _ordered(
    environment: Environment, limit: int, *where: sa.ColumnElement[bool]
) -> sa.Select[Any]:
    """The order columns, its create's flag and its age, of the environment's rows `where` names,
    oldest first, at most `limit`."""
    last = (
        sa.select(_E.recv_ts)
        .where(_E.order_id == _O.id)
        .order_by(_E.seq.desc())
        .limit(1)
        .lateral("last_event")
    )
    in_flight = _O.idempotency_state == sa.literal_column("'in_flight'")
    age = sa.func.extract("epoch", sa.func.now() - last.c.recv_ts)
    joined = orders.join(last, sa.true()).join(exchange_accounts, _A.id == _O.exchange_account_id)
    columns = (_O.id, _O.exchange_account_id, _O.order_link_id, _O.symbol)
    stmt = sa.select(*columns, sa.cast(_O.state, sa.Text).label("state"))
    stmt = stmt.add_columns(in_flight.label("in_flight"), age.label("age_s")).select_from(joined)
    return stmt.where(*where, _A.env == environment).order_by(_O.created_ts, _O.id).limit(limit)


def in_flight_statement(environment: Environment, limit: int) -> sa.Select[Any]:
    """The rows whose create is in flight and whose state is not final (`ix_orders_inflight`)."""
    in_flight = _O.idempotency_state == sa.literal_column("'in_flight'")
    return _ordered(environment, limit, in_flight, _O.state.not_in(_literal("final", FINAL_STATES)))


def open_stuck_statement(environment: Environment, limit: int) -> sa.Select[Any]:
    """The rows in `unknown`, `pending_cancel` or `pending_amend` (`ix_orders_open`)."""
    return _ordered(environment, limit, _O.state.in_(_literal("stuck", OPEN_STUCK_STATES)))


def naked_statement(environment: Environment, limit: int) -> sa.Select[Any]:
    """The open positions with no stop (`ix_pos_no_sl`) that no live recorded-stop row bound to an
    exchange order protects on their closing side, not paper, by key."""
    stop = orders.alias("stop_row")
    closing = sa.case((_P.side == "Buy", "Sell"), (_P.side == "Sell", "Buy"), else_=sa.null())
    protected = sa.exists().where(
        stop.c.exchange_account_id == _P.exchange_account_id,
        stop.c.symbol == _P.symbol,
        stop.c.position_idx == _P.position_idx,
        stop.c.provenance == sa.literal_column("'recorded_stop'"),
        stop.c.exchange_order_id.is_not(None),
        stop.c.state.in_(_literal("protecting", PROTECTING_STATES)),
        stop.c.side == closing,
    )
    joined = positions.join(exchange_accounts, _A.id == _P.exchange_account_id)
    stmt = sa.select(_P.exchange_account_id, _P.symbol, _P.position_idx, _P.side).select_from(
        joined
    )
    stmt = stmt.where(
        _P.size > sa.literal_column("0"),
        _P.stop_loss.is_(None),
        sa.not_(_P.is_paper),
        _A.env == environment,
        ~protected,
    )
    return stmt.order_by(_P.exchange_account_id, _P.symbol, _P.position_idx).limit(limit)


def _order_row(row: Mapping[str, Any]) -> StuckOrderRow:
    return StuckOrderRow(
        order_id=UUID(str(row["id"])),
        account_id=UUID(str(row["exchange_account_id"])),
        order_link_id=str(row["order_link_id"]),
        symbol=str(row["symbol"]),
        state=str(row["state"]),
        in_flight=bool(row["in_flight"]),
        age_s=max(0.0, float(row["age_s"])),
    )


def _limited(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("a read's limit is an int of at least 1")
    return limit


class SqlAlchemyStuckReads(CappedStore):
    """`StuckReadStore` over one relational repository (module docstring)."""

    async def stuck_orders(
        self, environment: Environment, *, limit: int
    ) -> tuple[tuple[StuckOrderRow, ...], bool]:
        """The in-flight and the open stuck candidates, each read at most `limit`, an order in
        both (an `unknown` row keeps `in_flight`) once; complete while neither read was cut."""
        limit = _limited(limit)
        async with self._unit_of_work() as uow:
            flight = (await uow.session.execute(in_flight_statement(environment, limit))).mappings()
            in_flight = flight.all()
            stuck = (await uow.session.execute(open_stuck_statement(environment, limit))).mappings()
            open_stuck = stuck.all()
        found: dict[UUID, StuckOrderRow] = {}
        for raw in (*in_flight, *open_stuck):
            row = _order_row(raw)
            found.setdefault(row.order_id, row)
        complete = len(in_flight) < limit and len(open_stuck) < limit
        return tuple(found.values()), complete

    async def naked_positions(
        self, environment: Environment, *, limit: int
    ) -> tuple[tuple[NakedPositionRow, ...], bool]:
        limit = _limited(limit)
        async with self._unit_of_work() as uow:
            read = (await uow.session.execute(naked_statement(environment, limit))).mappings()
            rows = read.all()
        naked = tuple(
            NakedPositionRow(
                account_id=UUID(str(r["exchange_account_id"])),
                symbol=str(r["symbol"]),
                position_idx=int(r["position_idx"]),
                side=None if r["side"] is None else str(r["side"]),
            )
            for r in rows
        )
        return naked, len(rows) < limit
