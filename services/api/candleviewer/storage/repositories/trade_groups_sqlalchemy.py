"""Postgres adapter for `TradeGroupStore` and `TradeGroupReads` (E28-T01 #905; M10).

SQLAlchemy Core over `db.models.trade_groups` and `trade_group_legs` (revision `0039_trade_groups`,
21-database-schema.md Sec.3.3.2-3.3.3): every value is a bound parameter, and reads select the
allow-lists `GROUP_COLUMNS`, every group column but `client_body_sha256`, and `LEG_COLUMNS`, every
leg column but `profile_snapshot`, which only `leg_statement` adds. The builders are module
functions named `*_statement`, each in `SCOPED_STATEMENTS` or `SYSTEM_STATEMENTS` (unit-pinned).

The replay anchor is read only with its creator: `anchor_statement` matches `(created_by,
client_group_ref)` and returns whether the stored request fingerprint equals the one given, never
the fingerprint (G-6(b), SR-E29-07). `create_group` inserts the group `ON CONFLICT (created_by,
client_group_ref) DO NOTHING`: a replay, or a create racing the first one, waits for that one and
then writes nothing and answers `GroupExists`. The wait counts against the statement cap (below),
so a replay racing a first create slower than the cap (by default 2 s, while the write-ahead hook
alone may take 5 s) surfaces as the unknown-outcome `StorageQueryFailed('57014')`, having written
nothing, and is retried by the client. When the insert wrote the group, it locks `FOR SHARE`, in
this order, the definition the group names, the leg accounts by id and the leg profiles by id;
refuses (`TradeGroupStoreRefusedError`) a definition or account that is missing or soft-deleted
and a profile that is not live at its leg's account and `profile_version` (SR-E28-15); inserts
every leg in one statement; awaits the write-ahead hook (C-2.9) and commits. Any refusal rolls the
group back with its legs.

`update_leg` and `update_group` lock their row `FOR NO KEY UPDATE`, so orders and executions can
still reference it, compare the status when asked (`TradeGroupStoreStaleError`) and set the patch's
columns only; `submitted_at` and `opened_at` keep a time already stored (`COALESCE`). Before they
are bound, `rejection_code` and `rejection_message` pass `redact_exchange_text`, the code under
`MAX_CODE_CHARS` and the message with the message rule, as the order store's `ret_code` and
`ret_msg` do. A `jsonb` value is bound as `render_json` text cast to `jsonb`, and `None` as SQL
NULL, never JSON `null`.

`list_open_groups` and `list_unprotected_legs` bind their statuses as literals in sorted order
(`literal_execute`; a generic plan with a bound array cannot match a partial index) and test the
stop flag as `NOT native_sl_confirmed`, never `IS false`, so the planner can use `ix_tg_open` and
`ix_tgl_no_sl`; neither filters a soft delete, so the C-2.6 alarm sees every open leg. `get_group`
is the scoped read, its scope in the SQL (SR-051): an `OwnerScope` first passes the accounts
store's live-owner gate and sees every group; a `GrantScope` sees a group only when it has a leg
and every leg account is live, in the scope and under a live `can_view` grant that is not frozen
(`group_visible`, SR-E28-21); an empty `GrantScope` runs no SQL. It reads the group, then its legs,
each statement under the predicate: a grant frozen or revoked, or a leg account soft-deleted,
between the two leaves no leg to read, and a `GrantScope` then reads the group as missing, never as
a group without legs.
`list_groups` is that scope over a keyset page (`created_at DESC, id DESC`) and again over its
legs, in one unit of work; `leg_order_ids` reads a leg's orders under it too (`ix_orders_leg`).

Every unit of work caps each of its statements, lock waits included, at the store's
`statement_timeout` (`OMS_STATEMENT_TIMEOUT_MS` unless given: the store is on the order submit
path, 24 Sec.8.2 S7); the cap does not cover opening a connection or waiting for the pool. A
database refusal leaves as `TradeGroupStoreRuleError` or `TradeGroupStoreConflictError` carrying
only the name the database gives it (`.diag.constraint_name`), any other failure as
`StorageQueryFailed(sqlstate)`, and a connection the store cannot get or loses as
`StorageTierUnavailable`. None is chained, and no statement, parameter or `DETAIL`, which repeats
the failing row, leaves with it (C-12.6). The hook runs inside that mapping: its
`WriteAheadTimeout` passes as it is, and a raw `OSError` or driver error from it is mapped as the
database's own. Cancellation passes through.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import fields
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError

from candleviewer.db.models import (
    account_profiles,
    exchange_accounts,
    orders,
    trade_group_definitions,
    trade_group_legs,
    trade_groups,
)
from candleviewer.storage.errors import (
    StorageQueryFailed,
    StorageTierUnavailable,
    WriteAheadTimeout,
)
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope, OwnerScope
from candleviewer.storage.repositories.exchange_payload import MAX_CODE_CHARS, redact_exchange_text
from candleviewer.storage.repositories.orders import typed_fields
from candleviewer.storage.repositories.orders_sqlalchemy import OMS_STATEMENT_TIMEOUT_MS
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    SqlAlchemyUnitOfWork,
)
from candleviewer.storage.repositories.trade_groups import (
    ACCOUNT_NOT_LIVE,
    DEFINITION_NOT_LIVE,
    MAX_GROUP_PAGE,
    OPEN_GROUP_STATUSES,
    PROFILE_CHANGED,
    TRADE_GROUP_CONFLICTS,
    TRADE_GROUP_RULES,
    UNPROTECTED_LEG_STATUSES,
    GroupAnchor,
    GroupCreated,
    GroupExists,
    GroupPatch,
    GroupWriteAhead,
    JsonObject,
    LegPatch,
    LegSnapshotRow,
    LegStatus,
    NewTradeGroup,
    NewTradeGroupLeg,
    TradeGroupLegRow,
    TradeGroupRecord,
    TradeGroupRow,
    TradeGroupStatus,
    TradeGroupStoreConflictError,
    TradeGroupStoreRefusedError,
    TradeGroupStoreRuleError,
    TradeGroupStoreScopeDeniedError,
    TradeGroupStoreStaleError,
    UnprotectedLegRow,
    parse_json,
    render_json,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import (
    WRITE_AHEAD_TIMEOUT_S,
    bounded_write_ahead,
)

_G = trade_groups.c
_L = trade_group_legs.c
_EA = exchange_accounts.c
_P = account_profiles.c
_D = trade_group_definitions.c
_O = orders.c

#: The row dataclasses' fields, which are the read allow-lists' names in table order.
GROUP_FIELDS: Final = tuple(f.name for f in fields(TradeGroupRow))
LEG_FIELDS: Final = tuple(f.name for f in fields(TradeGroupLegRow))
#: Every group column but `client_body_sha256`; `algo_params` as text, so its integers stay exact.
GROUP_COLUMNS: Final = tuple(
    sa.cast(_G[name], sa.Text).label(name) if name == "algo_params" else _G[name]
    for name in GROUP_FIELDS
)
#: Every leg column but `profile_snapshot` (SR-E28-07: only `load_leg` returns it).
LEG_COLUMNS: Final = tuple(_L[name] for name in LEG_FIELDS)
#: What `list_unprotected_legs` reads of a leg's group, besides the leg.
UNPROTECTED_GROUP_COLUMNS: Final = (_G.symbol, _G.side, _G.env, _G.is_paper)
#: Set once: an update keeps a time already stored (`COALESCE`).
SET_ONCE_LEG_COLUMNS: Final = frozenset({"submitted_at"})
SET_ONCE_GROUP_COLUMNS: Final = frozenset({"submitted_at", "opened_at"})

#: The builders whose SQL carries `group_visible(scope)`; every other one is a system statement,
#: reached only through `TradeGroupStore` (unit-pinned, with the module's `*_statement` names).
SCOPED_STATEMENTS: Final = frozenset(
    {
        "scoped_group_statement", "scoped_legs_statement", "scoped_page_statement",
        "scoped_page_legs_statement", "scoped_leg_orders_statement",
    }
)  # fmt: skip
SYSTEM_STATEMENTS: Final = frozenset(
    {
        "anchor_statement", "insert_group_statement", "lock_definition_statement",
        "lock_accounts_statement", "lock_profiles_statement", "insert_legs_statement",
        "lock_leg_statement", "update_leg_statement", "lock_group_statement",
        "update_group_statement", "group_statement", "legs_statement", "leg_statement",
        "open_groups_statement", "unprotected_legs_statement",
    }
)  # fmt: skip

#: The live-owner check, as the accounts store spells it (`accounts_sqlalchemy._OWNER_GATE`).
_OWNER_GATE: Final = sa.text(
    "SELECT EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "JOIN users u ON u.id = ur.user_id WHERE ur.user_id = CAST(:caller AS uuid) "
    "AND r.name = 'owner' AND u.deleted_at IS NULL AND u.status = 'active' "
    "AND (ur.expires_at IS NULL OR ur.expires_at > now()))"
)
#: The same predicate inside a statement, so a path that skipped the gate stays scoped.
_OWNER_PRED: Final = (
    "EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "JOIN users u ON u.id = ur.user_id WHERE ur.user_id = CAST(:caller AS uuid) "
    "AND r.name = 'owner' AND u.deleted_at IS NULL AND u.status = 'active' "
    "AND (ur.expires_at IS NULL OR ur.expires_at > now()))"
)
#: SR-E28-21 over the enclosing `trade_groups` row: it has a leg, and no leg's account is outside
#: the scope, soft-deleted or without the caller's live `can_view` grant that is not frozen (UL-F2).
#: Parenthesised, so a caller may negate or combine it.
_GRANT_VISIBLE: Final = (
    "(EXISTS (SELECT 1 FROM trade_group_legs vl WHERE vl.trade_group_id = trade_groups.id) "
    "AND NOT EXISTS (SELECT 1 FROM trade_group_legs vl WHERE vl.trade_group_id = trade_groups.id "
    "AND NOT (vl.exchange_account_id = ANY(CAST(:granted AS uuid[])) "
    "AND EXISTS (SELECT 1 FROM exchange_accounts vea WHERE vea.id = vl.exchange_account_id "
    "AND vea.deleted_at IS NULL) "
    "AND EXISTS (SELECT 1 FROM user_account_access uaa WHERE uaa.user_id = CAST(:caller AS uuid) "
    "AND uaa.exchange_account_id = vl.exchange_account_id AND uaa.can_view AND NOT uaa.frozen))))"
)
_VISIBLE: Final = sa.text(_GRANT_VISIBLE)  # built once; `group_visible` binds a copy
#: Transaction-local (`true`), like the order store's cap.
_SET_TIMEOUT: Final = sa.text("SELECT set_config('statement_timeout', :timeout, true)")
#: Shared with the definitions store, which reuses the gate and the cap.
OWNER_GATE: Final = _OWNER_GATE
SET_TIMEOUT: Final = _SET_TIMEOUT
#: SQLSTATEs that carry a constraint name: unique, check and foreign-key violations.
_NAMED_VIOLATIONS: Final = frozenset({"23505", "23514", "23503"})
#: A server that does not serve: shut down (57P01, 57P02), starting (57P03), full (53300).
_NOT_SERVING: Final = frozenset({"57P01", "57P02", "57P03", "53300"})
_GROUP_UUIDS: Final = typed_fields(TradeGroupRow, UUID)
_LEG_UUIDS: Final = typed_fields(TradeGroupLegRow, UUID)


# -- binds -------------------------------------------------------------------------------------


def _jsonb(value: JsonObject | None) -> sa.ColumnElement[Any]:
    """`value` as `render_json` text cast to `jsonb`; `None` as SQL NULL, never JSON `null`."""
    if value is None:
        return sa.null()
    return sa.cast(sa.literal(render_json(value), sa.Text), JSONB)


def _set_once(column: sa.ColumnElement[Any], value: object) -> sa.ColumnElement[Any]:
    """`column` keeps a time already stored; `value`, typed as the column, sets it otherwise."""
    return sa.func.coalesce(column, sa.literal(value, column.type))


def _redacted_code(code: str | None) -> str | None:
    return redact_exchange_text(code, max_chars=MAX_CODE_CHARS)


def _redacted_message(message: str | None) -> str | None:
    return redact_exchange_text(message, message=True)


def _status_literals(name: str, statuses: Iterable[str]) -> sa.BindParameter[Any]:
    """Rendered as literals in sorted order, so the SQL text is stable and a partial index on the
    same statuses can serve it."""
    return sa.bindparam(name, sorted(statuses), expanding=True, literal_execute=True)


def _uuid_array(name: str, ids: Iterable[UUID]) -> sa.ColumnElement[Any]:
    """`CAST(:name AS uuid[])` over the ids' text, in sorted order."""
    bound = sa.bindparam(name, sorted({str(i) for i in ids}), type_=ARRAY(sa.Text))
    return sa.cast(bound, ARRAY(sa.Uuid))


# -- statements ----------------------------------------------------------------------------------


def group_visible(scope: AccountScope, *, grant_visible: sa.TextClause = _VISIBLE) -> sa.TextClause:
    """The enclosing `trade_groups` row is in `scope`: for an `OwnerScope` the caller is a live
    owner (who sees every group, soft-deleted leg accounts included); for a `GrantScope` the
    SR-E28-21 predicate (`grant_visible`: the definitions store passes it over members), under
    which a group with no leg is invisible. E28-T05's list reuses it."""
    caller = str(scope.user_id)
    if isinstance(scope, OwnerScope):
        return sa.text(_OWNER_PRED).bindparams(caller=caller)
    granted = sa.bindparam(
        "granted", sorted(str(i) for i in scope.account_ids), type_=ARRAY(sa.Text)
    )
    return grant_visible.bindparams(granted, caller=caller)


def anchor_statement(
    created_by: UUID, client_group_ref: str, client_body_sha256: str
) -> sa.Select[Any]:
    """The group the creator's ref anchors and whether its fingerprint is the one given. The
    `sha256_hex` domain is compared as text (SQLAlchemy has no operator class for a DOMAIN)."""
    matches = sa.type_coerce(_G.client_body_sha256, sa.Text) == client_body_sha256
    return sa.select(_G.id, matches.label("body_matches")).where(
        _G.created_by == created_by, _G.client_group_ref == client_group_ref
    )


def insert_group_statement(group: NewTradeGroup) -> sa.Insert:
    """Writes nothing, and returns no row, when the creator's ref already anchors a group."""
    values: dict[str, Any] = {f.name: getattr(group, f.name) for f in fields(group)}
    values["algo_params"] = _jsonb(group.algo_params)
    stmt = pg_insert(trade_groups).values(values)
    stmt = stmt.on_conflict_do_nothing(index_elements=[_G.created_by, _G.client_group_ref])
    return stmt.returning(*GROUP_COLUMNS)


def lock_definition_statement(definition_id: UUID) -> sa.Select[Any]:
    """The live definition, `FOR SHARE`: a soft delete racing the create waits for its commit
    (21 Sec.3.3.3a)."""
    stmt = sa.select(_D.id).where(_D.id == definition_id, _D.deleted_at.is_(None))
    return stmt.with_for_update(read=True)


def lock_accounts_statement(account_ids: Iterable[UUID]) -> sa.Select[Any]:
    """The live accounts among `account_ids`, locked `FOR SHARE` in id order."""
    stmt = sa.select(_EA.id).where(_EA.id.in_(sorted(set(account_ids))), _EA.deleted_at.is_(None))
    return stmt.order_by(_EA.id).with_for_update(read=True)


def lock_profiles_statement(profile_ids: Iterable[UUID]) -> sa.Select[Any]:
    """The live profiles among `profile_ids` with their account and version, locked `FOR SHARE`
    in id order: a profile update racing the create commits first or waits for it."""
    stmt = sa.select(_P.id, _P.exchange_account_id, _P.version).where(
        _P.id.in_(sorted(set(profile_ids))), _P.deleted_at.is_(None)
    )
    return stmt.order_by(_P.id).with_for_update(read=True)


def _leg_values(group_id: UUID, leg: NewTradeGroupLeg) -> dict[str, Any]:
    values: dict[str, Any] = {f.name: getattr(leg, f.name) for f in fields(leg)}
    values["trade_group_id"] = group_id
    values["profile_snapshot"] = _jsonb(leg.profile_snapshot)
    values["rejection_code"] = _redacted_code(leg.rejection_code)
    values["rejection_message"] = _redacted_message(leg.rejection_message)
    return values


def insert_legs_statement(group_id: UUID, legs: Sequence[NewTradeGroupLeg]) -> sa.Insert:
    """Every leg of the group in one multi-row INSERT, the rejection texts redacted."""
    if not legs:
        raise ValueError("a trade group is written with at least one leg")
    rows = [_leg_values(group_id, leg) for leg in legs]
    return sa.insert(trade_group_legs).values(rows).returning(*LEG_COLUMNS)


def lock_leg_statement(group_id: UUID, leg_id: UUID) -> sa.Select[Any]:
    """The group's leg, `FOR NO KEY UPDATE`: inserts that reference it keep their FK check."""
    stmt = sa.select(_L.status).where(_L.trade_group_id == group_id, _L.id == leg_id)
    return stmt.with_for_update(key_share=True)


def update_leg_statement(group_id: UUID, leg_id: UUID, patch: LegPatch) -> sa.Update:
    changes = patch.changes()
    if "rejection_code" in changes:
        changes["rejection_code"] = _redacted_code(patch.rejection_code)
    if "rejection_message" in changes:
        changes["rejection_message"] = _redacted_message(patch.rejection_message)
    values = {
        name: _set_once(_L[name], value) if name in SET_ONCE_LEG_COLUMNS else value
        for name, value in changes.items()
    }
    stmt = sa.update(trade_group_legs).where(_L.trade_group_id == group_id, _L.id == leg_id)
    return stmt.values(values).returning(*LEG_COLUMNS)


def lock_group_statement(group_id: UUID) -> sa.Select[Any]:
    """The group, `FOR NO KEY UPDATE`: its legs and orders keep their FK checks."""
    return sa.select(_G.status).where(_G.id == group_id).with_for_update(key_share=True)


def update_group_statement(group_id: UUID, patch: GroupPatch) -> sa.Update:
    values = {
        name: _set_once(_G[name], value) if name in SET_ONCE_GROUP_COLUMNS else value
        for name, value in patch.changes().items()
    }
    stmt = sa.update(trade_groups).where(_G.id == group_id)
    return stmt.values(values).returning(*GROUP_COLUMNS)


def group_statement(group_id: UUID) -> sa.Select[Any]:
    return sa.select(*GROUP_COLUMNS).where(_G.id == group_id)


def legs_statement(group_ids: Iterable[UUID]) -> sa.Select[Any]:
    """The legs of these groups, by group, `sequence_no` and id (`ix_tgl_group`)."""
    stmt = sa.select(*LEG_COLUMNS).where(
        _L.trade_group_id == sa.any_(_uuid_array("group_ids", group_ids))
    )
    return stmt.order_by(_L.trade_group_id, _L.sequence_no, _L.id)


def leg_statement(leg_id: UUID) -> sa.Select[Any]:
    """The leg with its `profile_snapshot` as text, so its integers stay exact."""
    snapshot = sa.cast(_L.profile_snapshot, sa.Text).label("profile_snapshot")
    return sa.select(*LEG_COLUMNS, snapshot).where(_L.id == leg_id)


def open_groups_statement() -> sa.Select[Any]:
    """`ix_tg_open`'s predicate, oldest first; no soft-delete filter."""
    statuses = _status_literals("open_statuses", OPEN_GROUP_STATUSES)
    stmt = sa.select(*GROUP_COLUMNS).where(_G.status.in_(statuses))
    return stmt.order_by(_G.created_at, _G.id)


def unprotected_legs_statement() -> sa.Select[Any]:
    """`ix_tgl_no_sl`'s predicate, with what the alarm needs of the group; no soft-delete filter
    (C-2.6)."""
    statuses = _status_literals("unprotected_statuses", UNPROTECTED_LEG_STATUSES)
    joined = trade_group_legs.join(trade_groups, _G.id == _L.trade_group_id)
    stmt = sa.select(*LEG_COLUMNS, *UNPROTECTED_GROUP_COLUMNS).select_from(joined)
    stmt = stmt.where(_L.status.in_(statuses), sa.not_(_L.native_sl_confirmed))
    return stmt.order_by(_L.trade_group_id, _L.sequence_no, _L.id)


def scoped_group_statement(scope: AccountScope, group_id: UUID) -> sa.Select[Any]:
    return sa.select(*GROUP_COLUMNS).where(_G.id == group_id, group_visible(scope))


def scoped_legs_statement(scope: AccountScope, group_id: UUID) -> sa.Select[Any]:
    joined = trade_group_legs.join(trade_groups, _G.id == _L.trade_group_id)
    stmt = sa.select(*LEG_COLUMNS).select_from(joined)
    stmt = stmt.where(_G.id == group_id, group_visible(scope))
    return stmt.order_by(_L.sequence_no, _L.id)


def scoped_page_statement(
    scope: AccountScope, *, symbol: str | None, statuses: Collection[TradeGroupStatus],
    created_from: datetime | None, created_to: datetime | None,
    after: tuple[datetime, UUID] | None, limit: int,
) -> sa.Select[Any]:  # fmt: skip
    """One page of the groups in `scope`, newest first, strictly past the `after` cursor."""
    stmt = sa.select(*GROUP_COLUMNS).where(group_visible(scope))
    if symbol is not None:
        stmt = stmt.where(sa.type_coerce(_G.symbol, sa.Text) == symbol)  # no DOMAIN operator class
    if statuses:
        stmt = stmt.where(_G.status.in_(sorted(statuses)))
    if created_from is not None:
        stmt = stmt.where(_G.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(_G.created_at < created_to)
    if after is not None:
        stmt = stmt.where(sa.tuple_(_G.created_at, _G.id) < after)
    return stmt.order_by(_G.created_at.desc(), _G.id.desc()).limit(limit)


def scoped_page_legs_statement(scope: AccountScope, group_ids: Iterable[UUID]) -> sa.Select[Any]:
    """The legs of a page's groups under the same predicate: all of a group's, or none."""
    joined = trade_group_legs.join(trade_groups, _G.id == _L.trade_group_id)
    stmt = sa.select(*LEG_COLUMNS).select_from(joined)
    stmt = stmt.where(_G.id == sa.any_(_uuid_array("group_ids", group_ids)), group_visible(scope))
    return stmt.order_by(_L.trade_group_id, _L.sequence_no, _L.id)


def scoped_leg_orders_statement(scope: AccountScope, leg_ids: Iterable[UUID]) -> sa.Select[Any]:
    """The ids of these legs' orders, oldest first, for legs of groups in `scope`."""
    joined = orders.join(trade_group_legs, _L.id == _O.trade_group_leg_id)
    joined = joined.join(trade_groups, _G.id == _L.trade_group_id)
    stmt = sa.select(_O.trade_group_leg_id, _O.id).select_from(joined)
    stmt = stmt.where(
        _O.trade_group_leg_id == sa.any_(_uuid_array("leg_ids", leg_ids)),
        _O.exchange_account_id == _L.exchange_account_id,
        group_visible(scope),
    )
    return stmt.order_by(_O.trade_group_leg_id, _O.created_ts, _O.id)


# -- rows ----------------------------------------------------------------------------------------


def _uuid(value: object) -> UUID:
    return UUID(str(value))


def _opt_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def group_row(m: Mapping[Any, Any]) -> TradeGroupRow:
    values: dict[str, Any] = {name: m[name] for name in GROUP_FIELDS}
    for name in _GROUP_UUIDS:
        values[name] = _opt_uuid(values[name])
    params = values["algo_params"]
    values["algo_params"] = None if params is None else parse_json(str(params))
    return TradeGroupRow(**values)


def leg_row(m: Mapping[Any, Any]) -> TradeGroupLegRow:
    values: dict[str, Any] = {name: m[name] for name in LEG_FIELDS}
    for name in _LEG_UUIDS:
        values[name] = _opt_uuid(values[name])
    return TradeGroupLegRow(**values)


def in_order(legs: Iterable[TradeGroupLegRow]) -> tuple[TradeGroupLegRow, ...]:
    return tuple(sorted(legs, key=lambda leg: (leg.sequence_no, leg.id)))


def _records(
    groups: Iterable[Mapping[Any, Any]], legs: Iterable[Mapping[Any, Any]]
) -> tuple[TradeGroupRecord, ...]:
    """Each group with its legs, in the groups' order."""
    by_group: dict[UUID, list[TradeGroupLegRow]] = {}
    for m in legs:
        leg = leg_row(m)
        by_group.setdefault(leg.trade_group_id, []).append(leg)
    rows = (group_row(m) for m in groups)
    return tuple(TradeGroupRecord(row, in_order(by_group.get(row.id, ()))) for row in rows)


def _anchor(m: Mapping[Any, Any]) -> GroupAnchor:
    return GroupAnchor(group_id=_uuid(m["id"]), body_matches=bool(m["body_matches"]))


# -- the share-locked re-check ---------------------------------------------------------------------


async def require_live(
    uow: SqlAlchemyUnitOfWork, group: NewTradeGroup, legs: Sequence[NewTradeGroupLeg]
) -> None:
    """Lock, in order, the definition, the leg accounts and the leg profiles `FOR SHARE`, and
    refuse the create unless each is live (a profile at its leg's account and version). Also the
    first persist of an entry's one-leg group (E29-T04, `submissions_sqlalchemy.py`)."""
    if group.definition_id is not None:
        found = await uow.session.execute(lock_definition_statement(group.definition_id))
        if found.mappings().first() is None:
            raise TradeGroupStoreRefusedError(DEFINITION_NOT_LIVE)
    accounts = {leg.exchange_account_id for leg in legs}
    locked = await uow.session.execute(lock_accounts_statement(accounts))
    if {_uuid(m["id"]) for m in locked.mappings()} != accounts:
        raise TradeGroupStoreRefusedError(ACCOUNT_NOT_LIVE)
    profiles = await uow.session.execute(
        lock_profiles_statement(leg.account_profile_id for leg in legs)
    )
    live = {
        _uuid(m["id"]): (_uuid(m["exchange_account_id"]), int(m["version"]))
        for m in profiles.mappings()
    }
    for leg in legs:
        if live.get(leg.account_profile_id) != (leg.exchange_account_id, leg.profile_version):
            raise TradeGroupStoreRefusedError(PROFILE_CHANGED)


# -- failures ------------------------------------------------------------------------------------


def _sqlstate(exc: DBAPIError) -> str | None:
    value = getattr(exc.orig, "sqlstate", None)
    return value if isinstance(value, str) else None


def _violated_constraint(exc: DBAPIError) -> str | None:
    """The constraint a unique, check or FK violation names, wherever the driver puts it."""
    if _sqlstate(exc) not in _NAMED_VIOLATIONS:
        return None
    orig: Any = exc.orig
    for source in (orig, getattr(orig, "__cause__", None), getattr(orig, "driver_exception", None)):
        name = getattr(source, "constraint_name", None) or getattr(
            getattr(source, "diag", None), "constraint_name", None
        )
        if name:
            return str(name)
    return None


#: The group store's refusals by name, each with the error it leaves as.
_GROUP_REFUSALS: Final[Mapping[str, type[Exception]]] = dict.fromkeys(
    TRADE_GROUP_CONFLICTS, TradeGroupStoreConflictError
) | dict.fromkeys(TRADE_GROUP_RULES, TradeGroupStoreRuleError)


@contextmanager
def _constraints(refusals: Mapping[str, type[Exception]] = _GROUP_REFUSALS) -> Iterator[None]:
    """A refusal leaves as its rule or constraint name, a lost connection as
    `StorageTierUnavailable` naming only the error's type, anything else as
    `StorageQueryFailed(sqlstate)`; never chained (C-12.6)."""
    try:
        yield
    except DBAPIError as exc:
        state = _sqlstate(exc) or ""
        if exc.connection_invalidated or state.startswith("08") or state in _NOT_SERVING:
            raise StorageTierUnavailable(f"postgres unreachable ({type(exc).__name__})") from None
        name = _violated_constraint(exc)
        if name is not None and name in refusals:
            raise refusals[name](name) from None
        raise StorageQueryFailed(_sqlstate(exc)) from None
    except WriteAheadTimeout:
        raise  # the audit hook's bound, not the database's, although it is a `TimeoutError` too
    except (OSError, sa.exc.TimeoutError) as exc:
        raise StorageTierUnavailable(f"postgres unreachable ({type(exc).__name__})") from None


constraints = _constraints  # the definitions store passes its own refusals


# -- the store -----------------------------------------------------------------------------------


class SqlAlchemyTradeGroupStore:
    """`TradeGroupStore` and `TradeGroupReads` over one relational repository (asyncpg)."""

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        statement_timeout_ms: int = OMS_STATEMENT_TIMEOUT_MS,
        audit_timeout_s: float = WRITE_AHEAD_TIMEOUT_S,
    ) -> None:
        # Postgres reads 0 as "no cap", and a bool is an int: neither is a cap (`CappedStore`).
        if (
            isinstance(statement_timeout_ms, bool)
            or not isinstance(statement_timeout_ms, int)
            or statement_timeout_ms < 1
        ):
            raise ValueError("statement_timeout_ms must be an int of at least 1")
        self._relational = relational
        self._timeout = str(statement_timeout_ms)
        self._audit_timeout_s = audit_timeout_s

    @asynccontextmanager
    async def _unit_of_work(
        self, scope: AccountScope | None = None
    ) -> AsyncIterator[SqlAlchemyUnitOfWork]:
        """One capped transaction, its failures mapped; an `OwnerScope` checks the live owner
        before anything else is read."""
        with _constraints():
            async with self._relational.unit_of_work() as uow:
                await uow.session.execute(_SET_TIMEOUT, {"timeout": self._timeout})
                if isinstance(scope, OwnerScope):
                    gate = await uow.session.execute(_OWNER_GATE, {"caller": str(scope.user_id)})
                    if not gate.scalar_one():
                        raise TradeGroupStoreScopeDeniedError
                yield uow

    @staticmethod
    def _fails_closed(scope: AccountScope) -> bool:
        """A grant scope with no account sees nothing and runs no SQL."""
        return isinstance(scope, GrantScope) and not scope.account_ids

    async def find_anchor(
        self, created_by: UUID, client_group_ref: str, client_body_sha256: str
    ) -> GroupAnchor | None:
        stmt = anchor_statement(created_by, client_group_ref, client_body_sha256)
        async with self._unit_of_work() as uow:
            m = (await uow.session.execute(stmt)).mappings().first()
        return None if m is None else _anchor(m)

    async def create_group(
        self,
        group: NewTradeGroup,
        legs: Sequence[NewTradeGroupLeg],
        *,
        write_ahead: GroupWriteAhead | None = None,
    ) -> GroupCreated | GroupExists:
        if not legs:
            raise ValueError("a trade group is written with at least one leg")
        async with self._unit_of_work() as uow:
            inserted = (await uow.session.execute(insert_group_statement(group))).mappings().first()
            if inserted is None:  # the anchor exists: nothing was written, nothing to commit
                anchor = anchor_statement(
                    group.created_by, group.client_group_ref, group.client_body_sha256
                )
                found = (await uow.session.execute(anchor)).mappings().first()
                if found is None:  # the conflicting row is gone again: not ours to answer
                    raise TradeGroupStoreConflictError("ux_tg_creator_ref")
                return GroupExists(_anchor(found))
            await require_live(uow, group, legs)
            stmt = insert_legs_statement(_uuid(inserted["id"]), legs)
            rows = list((await uow.session.execute(stmt)).mappings())
            record = TradeGroupRecord(group_row(inserted), in_order(leg_row(m) for m in rows))
            if write_ahead is not None:
                await bounded_write_ahead(write_ahead(record), self._audit_timeout_s)
            await uow.commit()
        return GroupCreated(record)

    async def update_leg(
        self,
        group_id: UUID,
        leg_id: UUID,
        patch: LegPatch,
        *,
        expected_status: LegStatus | None = None,
    ) -> TradeGroupLegRow | None:
        async with self._unit_of_work() as uow:
            held = await uow.session.execute(lock_leg_statement(group_id, leg_id))
            current = held.mappings().first()
            if current is None:
                return None
            if expected_status is not None and current["status"] != expected_status:
                raise TradeGroupStoreStaleError
            stmt = update_leg_statement(group_id, leg_id, patch)
            m = (await uow.session.execute(stmt)).mappings().one()
            await uow.commit()
        return leg_row(m)

    async def update_group(
        self,
        group_id: UUID,
        patch: GroupPatch,
        *,
        expected_status: TradeGroupStatus | None = None,
    ) -> TradeGroupRow | None:
        async with self._unit_of_work() as uow:
            held = await uow.session.execute(lock_group_statement(group_id))
            current = held.mappings().first()
            if current is None:
                return None
            if expected_status is not None and current["status"] != expected_status:
                raise TradeGroupStoreStaleError
            stmt = update_group_statement(group_id, patch)
            m = (await uow.session.execute(stmt)).mappings().one()
            await uow.commit()
        return group_row(m)

    async def load_group(self, group_id: UUID) -> TradeGroupRecord | None:
        async with self._unit_of_work() as uow:
            group = (await uow.session.execute(group_statement(group_id))).mappings().first()
            if group is None:
                return None
            legs = list((await uow.session.execute(legs_statement((group_id,)))).mappings())
        return _records((group,), legs)[0]

    async def load_leg(self, leg_id: UUID) -> LegSnapshotRow | None:
        async with self._unit_of_work() as uow:
            m = (await uow.session.execute(leg_statement(leg_id))).mappings().first()
        if m is None:
            return None
        return LegSnapshotRow(leg_row(m), parse_json(str(m["profile_snapshot"])))

    async def list_open_groups(self) -> tuple[TradeGroupRecord, ...]:
        async with self._unit_of_work() as uow:
            groups = list((await uow.session.execute(open_groups_statement())).mappings())
            if not groups:
                return ()
            stmt = legs_statement(_uuid(m["id"]) for m in groups)
            legs = list((await uow.session.execute(stmt)).mappings())
        return _records(groups, legs)

    async def list_unprotected_legs(self) -> tuple[UnprotectedLegRow, ...]:
        async with self._unit_of_work() as uow:
            rows = list((await uow.session.execute(unprotected_legs_statement())).mappings())
        return tuple(
            UnprotectedLegRow(
                leg=leg_row(m),
                symbol=str(m["symbol"]),
                side=m["side"],
                env=m["env"],
                is_paper=bool(m["is_paper"]),
            )
            for m in rows
        )

    async def get_group(self, scope: AccountScope, group_id: UUID) -> TradeGroupRecord | None:
        if self._fails_closed(scope):
            return None
        async with self._unit_of_work(scope) as uow:
            stmt = scoped_group_statement(scope, group_id)
            group = (await uow.session.execute(stmt)).mappings().first()
            if group is None:
                return None
            scoped = scoped_legs_statement(scope, group_id)
            legs = list((await uow.session.execute(scoped)).mappings())
        if isinstance(scope, GrantScope) and not legs:  # the scope changed in between: all or none
            return None
        return _records((group,), legs)[0]

    async def list_groups(
        self, scope: AccountScope, *, symbol: str | None, statuses: Collection[TradeGroupStatus],
        created_from: datetime | None, created_to: datetime | None,
        after: tuple[datetime, UUID] | None, limit: int,
    ) -> tuple[TradeGroupRecord, ...]:  # fmt: skip
        if isinstance(limit, bool) or not 1 <= limit <= MAX_GROUP_PAGE:
            raise ValueError(f"limit must be 1 to {MAX_GROUP_PAGE}")
        times = (created_from, created_to, None if after is None else after[0])
        if any(t is not None and t.utcoffset() is None for t in times):
            raise ValueError("a time must be timezone-aware")
        if self._fails_closed(scope):
            return ()
        page = scoped_page_statement(
            scope, symbol=symbol, statuses=statuses, created_from=created_from,
            created_to=created_to, after=after, limit=limit,
        )  # fmt: skip
        async with self._unit_of_work(scope) as uow:
            groups = list((await uow.session.execute(page)).mappings())
            if not groups:
                return ()
            scoped = scoped_page_legs_statement(scope, (_uuid(m["id"]) for m in groups))
            legs = list((await uow.session.execute(scoped)).mappings())
        records = _records(groups, legs)
        if isinstance(scope, GrantScope):  # all or none: a group left without legs is dropped
            return tuple(record for record in records if record.legs)
        return records

    async def leg_order_ids(
        self, scope: AccountScope, leg_ids: Collection[UUID]
    ) -> Mapping[UUID, tuple[UUID, ...]]:
        ids = frozenset(leg_ids)
        if not ids or self._fails_closed(scope):
            return {}
        async with self._unit_of_work(scope) as uow:
            stmt = scoped_leg_orders_statement(scope, ids)
            rows = list((await uow.session.execute(stmt)).mappings())
        found: dict[UUID, list[UUID]] = {}
        for m in rows:
            found.setdefault(_uuid(m["trade_group_leg_id"]), []).append(_uuid(m["id"]))
        return {leg: tuple(order_ids) for leg, order_ids in found.items()}


__all__ = [
    "GROUP_COLUMNS", "GROUP_FIELDS", "LEG_COLUMNS", "LEG_FIELDS", "SCOPED_STATEMENTS",
    "SET_ONCE_GROUP_COLUMNS", "SET_ONCE_LEG_COLUMNS", "SYSTEM_STATEMENTS",
    "UNPROTECTED_GROUP_COLUMNS", "SqlAlchemyTradeGroupStore", "anchor_statement",
    "group_row", "group_statement", "group_visible", "in_order", "insert_group_statement",
    "insert_legs_statement", "leg_row", "leg_statement", "legs_statement",
    "lock_accounts_statement", "lock_definition_statement", "lock_group_statement",
    "lock_leg_statement", "lock_profiles_statement", "open_groups_statement", "require_live",
    "scoped_group_statement", "scoped_leg_orders_statement", "scoped_legs_statement",
    "scoped_page_legs_statement", "scoped_page_statement", "unprotected_legs_statement",
    "update_group_statement", "update_leg_statement",
]  # fmt: skip
