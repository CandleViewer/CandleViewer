"""Postgres adapter for `AccountProfileStore` and `EffectiveProfileReads` (E28-T01 #905).

SQLAlchemy Core over `db.models.account_profiles` and `account_profile_revisions` (revision
`0037_account_profiles`): every value is a bound parameter and the column list is the allow-list
`PROFILE_COLUMNS`. The database owns `version`, `updated_at` and the revision row
(`trg_ap_version`, `trg_account_profiles_touch`, `trg_ap_revision`), so no statement writes them;
every UPDATE sets `updated_by`, which `trg_ap_revision` records as `changed_by`.

Scope (SR-051, C-12.4) is in the SQL of every read and write, never filtered afterwards: the
account must be live, and for an `OwnerScope` the caller a live owner (the accounts store's
predicate, checked first by `_OWNER_GATE` and again inside the statement), for a `GrantScope` a
granted account with a live `can_view` grant that is not frozen. An empty grant set runs no SQL.
Writes take an `OwnerScope` only. A write that matches no row reads the row again in the same
transaction to tell a stale `expected_version` (or a refused move) from a missing profile, which
answers `None` like every other not-found.

`tp_ladder` holds JSON numbers, which `trg_ap_ladder_sum` requires: it is bound as JSON text
rendered from `Decimal` (`format(d, "f")`) and read back as text with `parse_float=Decimal`, so
no float ever touches it; a NULL ladder binds SQL NULL, never JSON `null`, which
`ap_ladder_shape` would refuse.

A database refusal leaves as `AccountProfileStoreRuleError` (a CHECK or the ladder trigger,
which names itself with `USING CONSTRAINT`) or `AccountProfileStoreConflictError` (a unique
index), carrying only the name; any other failure as `StorageQueryFailed(sqlstate)`, and a
connection the store cannot get or loses as `StorageTierUnavailable`. None is chained (C-12.6),
and no statement, parameter or `DETAIL` leaves with it. Cancellation passes through.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError

from candleviewer.db.models import account_profile_revisions, account_profiles, exchange_accounts
from candleviewer.storage.errors import (
    StorageQueryFailed,
    StorageTierUnavailable,
    WriteAheadTimeout,
)
from candleviewer.storage.repositories.account_profiles import (
    DEFAULT_MOVES_ALONE,
    PROFILE_CONFLICTS,
    PROFILE_RULES,
    AccountProfileRevision,
    AccountProfileRow,
    AccountProfileStoreConflictError,
    AccountProfileStoreRuleError,
    AccountProfileStoreScopeDeniedError,
    AccountProfileStoreStaleError,
    AccountProfileValues,
    DefaultMove,
    LadderRung,
    ProfileWriteAhead,
)
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope, OwnerScope
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    SqlAlchemyUnitOfWork,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import (
    WRITE_AHEAD_TIMEOUT_S,
    bounded_write_ahead,
)

_P = account_profiles.c
_R = account_profile_revisions.c
_EA = exchange_accounts.c

#: The row's own columns, then the writable ones (`AccountProfileValues`), in that order.
ROW_FIELDS: Final = (
    "id", "exchange_account_id", "version", "created_by", "updated_by", "created_at", "updated_at",
    "deleted_at",
)  # fmt: skip
VALUE_FIELDS: Final = tuple(f.name for f in fields(AccountProfileValues))
#: The read allow-list; `tp_ladder` as text, so its numbers stay exact.
PROFILE_COLUMNS: Final = tuple(
    sa.cast(_P[name], sa.Text).label(name) if name == "tp_ladder" else _P[name]
    for name in ROW_FIELDS + VALUE_FIELDS
)
#: At most this many profiles answer one list; a deployment holds a few per account.
MAX_PROFILES: Final = 500

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
#: A live grant on the account the enclosing `exchange_accounts` row is (UL-F2: `can_view`).
_GRANT_PRED: Final = (
    "EXISTS (SELECT 1 FROM user_account_access uaa WHERE uaa.user_id = CAST(:caller AS uuid) "
    "AND uaa.exchange_account_id = exchange_accounts.id AND uaa.can_view AND NOT uaa.frozen)"
)
#: Serialises default moves on one account (`ux_ap_default` is checked per statement).
_LOCK_DEFAULT: Final = sa.text(
    "SELECT pg_advisory_xact_lock(hashtextextended('cv.profiles.default:' "
    "|| CAST(:account AS text), 0))"
)
#: SQLSTATEs that carry a constraint name: unique, check and foreign-key violations.
_NAMED_VIOLATIONS: Final = frozenset({"23505", "23514", "23503"})
#: A server that does not serve: shut down (57P01, 57P02), starting (57P03), full (53300).
_NOT_SERVING: Final = frozenset({"57P01", "57P02", "57P03", "53300"})


def _uuid(value: object) -> UUID:
    return UUID(str(value))


def _opt_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


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


@contextmanager
def _constraints() -> Iterator[None]:
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
        if name in PROFILE_RULES:
            raise AccountProfileStoreRuleError(name) from None
        if name in PROFILE_CONFLICTS:
            raise AccountProfileStoreConflictError(name) from None
        raise StorageQueryFailed(_sqlstate(exc)) from None
    except WriteAheadTimeout:
        raise  # the audit hook's bound, not the database's, although it is a `TimeoutError` too
    except (OSError, sa.exc.TimeoutError) as exc:
        raise StorageTierUnavailable(f"postgres unreachable ({type(exc).__name__})") from None


def _ladder_json(ladder: tuple[LadderRung, ...]) -> str:
    """JSON numbers rendered from `Decimal`, never through float (`trg_ap_ladder_sum` reads them
    as numbers); the values are `Decimal`s, so nothing else reaches the text."""
    for rung in ladder:
        if not (rung.pct.is_finite() and rung.r.is_finite()):
            raise ValueError("tp_ladder values must be finite")
    rungs = (f'{{"pct": {format(rung.pct, "f")}, "r": {format(rung.r, "f")}}}' for rung in ladder)
    return "[" + ", ".join(rungs) + "]"


def _ladder(value: object) -> tuple[LadderRung, ...] | None:
    """A ladder read as text (a column) or already parsed (a revision payload), numbers exact."""
    if value is None:
        return None
    rungs = json.loads(value, parse_float=Decimal) if isinstance(value, str) else value
    if not isinstance(rungs, list):
        raise TypeError("tp_ladder is not a JSON array")
    return tuple(LadderRung(pct=Decimal(str(r["pct"])), r=Decimal(str(r["r"]))) for r in rungs)


def _strings(value: object) -> tuple[str, ...] | None:
    """A `text[]` as a tuple; NULL stays `None`, distinct from an empty list."""
    if value is None:
        return None
    if not isinstance(value, list | tuple):
        raise TypeError("a symbol list is not an array")
    return tuple(str(v) for v in value)


def _value_params(values: AccountProfileValues) -> dict[str, Any]:
    """The writable columns, bound: the ladder as JSON text cast to jsonb (SQL NULL for none),
    the symbol lists as `text[]`."""
    out: dict[str, Any] = {name: getattr(values, name) for name in VALUE_FIELDS}
    ladder = values.tp_ladder
    out["tp_ladder"] = (
        sa.null() if ladder is None else sa.cast(sa.literal(_ladder_json(ladder), sa.Text), JSONB)
    )
    for name in ("allowed_symbols", "blocked_symbols"):
        listed = out[name]
        out[name] = None if listed is None else list(listed)
    return out


def _values(m: Mapping[Any, Any]) -> AccountProfileValues:
    decoded = {name: m[name] for name in VALUE_FIELDS}
    decoded["tp_ladder"] = _ladder(m["tp_ladder"])
    decoded["allowed_symbols"] = _strings(m["allowed_symbols"])
    decoded["blocked_symbols"] = _strings(m["blocked_symbols"])
    return AccountProfileValues(**decoded)


def _row(m: Mapping[Any, Any]) -> AccountProfileRow:
    return AccountProfileRow(
        id=_uuid(m["id"]),
        exchange_account_id=_uuid(m["exchange_account_id"]),
        version=int(m["version"]),
        values=_values(m),
        created_by=_opt_uuid(m["created_by"]),
        updated_by=_opt_uuid(m["updated_by"]),
        created_at=m["created_at"],
        updated_at=m["updated_at"],
        deleted_at=m["deleted_at"],
    )


#: The `numeric` columns: `parse_float=Decimal` already made them exact, `Decimal(str())` only
#: lifts an integral JSON number.
_NUMERIC: Final = frozenset(
    c.name for c in account_profiles.columns if isinstance(c.type, sa.Numeric)
)


def _payload_row(payload: Mapping[str, Any]) -> AccountProfileRow:
    """A revision's `payload` (`to_jsonb` of the row, read with `parse_float=Decimal`) as a row.
    A column added by a later revision is absent from older payloads: its decode needs a default
    here when it lands."""
    decoded: dict[str, Any] = dict(payload)
    for name in _NUMERIC:
        if decoded[name] is not None:
            decoded[name] = Decimal(str(decoded[name]))
    for name in ("created_at", "updated_at", "deleted_at"):
        if decoded[name] is not None:
            decoded[name] = datetime.fromisoformat(decoded[name])
    return _row(decoded)


def _require_owner(scope: object) -> OwnerScope:
    if not isinstance(scope, OwnerScope):
        raise AccountProfileStoreScopeDeniedError
    return scope


def account_visible(scope: AccountScope, account_id: UUID) -> sa.Exists:
    """The account is live and in `scope`: an `EXISTS` over its `exchange_accounts` row, which no
    enclosing statement correlates."""
    live = (
        sa.select(sa.literal(1))
        .select_from(exchange_accounts)
        .where(_EA.id == account_id, _EA.deleted_at.is_(None))
        .correlate(None)
    )
    if isinstance(scope, GrantScope):
        granted = sorted(scope.account_ids)
        caller = str(scope.user_id)
        live = live.where(_EA.id.in_(granted), sa.text(_GRANT_PRED).bindparams(caller=caller))
    else:
        live = live.where(sa.text(_OWNER_PRED).bindparams(caller=str(scope.user_id)))
    return live.exists()


def account_live(account_id: UUID) -> sa.Exists:
    """The account is live, with no principal: the system read's predicate."""
    live = (
        sa.select(sa.literal(1))
        .select_from(exchange_accounts)
        .where(_EA.id == account_id, _EA.deleted_at.is_(None))
        .correlate(None)
    )
    return live.exists()


def _live_profile(account_id: UUID, profile_id: UUID) -> tuple[sa.ColumnElement[bool], ...]:
    return (_P.id == profile_id, _P.exchange_account_id == account_id, _P.deleted_at.is_(None))


def list_statement(scope: AccountScope, account_id: UUID) -> sa.Select[Any]:
    return (
        sa.select(*PROFILE_COLUMNS)
        .where(
            _P.exchange_account_id == account_id,
            _P.deleted_at.is_(None),
            account_visible(scope, account_id),
        )
        .order_by(_P.is_default.desc(), sa.func.lower(_P.name), _P.id)
        .limit(MAX_PROFILES)
    )


def get_statement(scope: AccountScope, account_id: UUID, profile_id: UUID) -> sa.Select[Any]:
    return sa.select(*PROFILE_COLUMNS).where(
        *_live_profile(account_id, profile_id), account_visible(scope, account_id)
    )


def lock_account_statement(scope: OwnerScope, account_id: UUID) -> sa.Select[Any]:
    """The live account in scope, `FOR SHARE`: a concurrent soft delete waits for the insert."""
    return (
        sa.select(_EA.id)
        .where(
            _EA.id == account_id,
            _EA.deleted_at.is_(None),
            sa.text(_OWNER_PRED).bindparams(caller=str(scope.user_id)),
        )
        .with_for_update(read=True)
    )


def insert_statement(
    scope: OwnerScope, account_id: UUID, profile_id: UUID, values: AccountProfileValues
) -> sa.Insert:
    caller = scope.user_id
    params = _value_params(values)
    return (
        sa.insert(account_profiles)
        .values(
            id=profile_id,
            exchange_account_id=account_id,
            created_by=caller,
            updated_by=caller,
            **params,
        )
        .returning(*PROFILE_COLUMNS)
    )


def update_statement(
    scope: OwnerScope,
    account_id: UUID,
    profile_id: UUID,
    values: AccountProfileValues,
    expected_version: int | None,
) -> sa.Update:
    params = _value_params(values)
    is_default = params.pop("is_default")
    stmt = sa.update(account_profiles).where(
        *_live_profile(account_id, profile_id),
        _P.is_default == is_default,
        account_visible(scope, account_id),
    )
    if expected_version is not None:
        stmt = stmt.where(_P.version == expected_version)
    return stmt.values(updated_by=scope.user_id, **params).returning(*PROFILE_COLUMNS)


def lock_profile_statement(scope: OwnerScope, account_id: UUID, profile_id: UUID) -> sa.Select[Any]:
    return (
        sa.select(*PROFILE_COLUMNS)
        .where(*_live_profile(account_id, profile_id), account_visible(scope, account_id))
        .with_for_update(of=account_profiles)
    )


def default_statement(scope: OwnerScope, account_id: UUID) -> sa.Select[Any]:
    """The account's live default, locked: the before-state a default move hands `write_ahead`."""
    return (
        sa.select(*PROFILE_COLUMNS)
        .where(
            _P.exchange_account_id == account_id,
            _P.is_default.is_(True),
            _P.deleted_at.is_(None),
            account_visible(scope, account_id),
        )
        .with_for_update(of=account_profiles)
    )


def unset_default_statement(scope: OwnerScope, account_id: UUID) -> sa.Update:
    return (
        sa.update(account_profiles)
        .where(
            _P.exchange_account_id == account_id,
            _P.is_default.is_(True),
            _P.deleted_at.is_(None),
            account_visible(scope, account_id),
        )
        .values(is_default=False, updated_by=scope.user_id)
        .returning(*PROFILE_COLUMNS)
    )


def set_default_statement(scope: OwnerScope, account_id: UUID, profile_id: UUID) -> sa.Update:
    return (
        sa.update(account_profiles)
        .where(*_live_profile(account_id, profile_id), account_visible(scope, account_id))
        .values(is_default=True, updated_by=scope.user_id)
        .returning(*PROFILE_COLUMNS)
    )


def delete_statement(
    scope: OwnerScope, account_id: UUID, profile_id: UUID, expected_version: int | None
) -> sa.Update:
    stmt = sa.update(account_profiles).where(
        *_live_profile(account_id, profile_id),
        _P.is_default.is_(False),
        account_visible(scope, account_id),
    )
    if expected_version is not None:
        stmt = stmt.where(_P.version == expected_version)
    return stmt.values(deleted_at=sa.func.now(), updated_by=scope.user_id).returning(
        *PROFILE_COLUMNS
    )


def revision_statement(
    scope: AccountScope, account_id: UUID, profile_id: UUID, version: int
) -> sa.Select[Any]:
    """The revision of a profile of this account, whose payload names the account (the history
    outlives the profile row, so the account is read from the payload)."""
    return sa.select(
        _R.id, _R.version, sa.cast(_R.payload, sa.Text).label("payload"), _R.changed_by,
        _R.changed_at,
    ).where(
        _R.profile_id == profile_id,
        _R.version == version,
        _R.payload["exchange_account_id"].astext == str(account_id),
        account_visible(scope, account_id),
    )  # fmt: skip


def effective_statement(account_id: UUID, profile_id: UUID | None) -> sa.Select[Any]:
    chosen = _P.is_default.is_(True) if profile_id is None else _P.id == profile_id
    return sa.select(*PROFILE_COLUMNS).where(
        _P.exchange_account_id == account_id,
        _P.deleted_at.is_(None),
        chosen,
        account_live(account_id),
    )


class SqlAlchemyAccountProfileStore:
    """`AccountProfileStore` and `EffectiveProfileReads` over one relational repository."""

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        audit_timeout_s: float = WRITE_AHEAD_TIMEOUT_S,
    ) -> None:
        self._relational = relational
        self._audit_timeout_s = audit_timeout_s

    async def _ahead(
        self,
        write_ahead: ProfileWriteAhead | None,
        before: AccountProfileRow | None,
        after: AccountProfileRow,
    ) -> None:
        """The write-ahead audit hook, in the write's transaction and before its commit."""
        if write_ahead is not None:
            await bounded_write_ahead(write_ahead(before, after), self._audit_timeout_s)

    @staticmethod
    async def _locked(
        uow: SqlAlchemyUnitOfWork, scope: OwnerScope, account_id: UUID, profile_id: UUID
    ) -> AccountProfileRow | None:
        stmt = lock_profile_statement(scope, account_id, profile_id)
        m = (await uow.session.execute(stmt)).mappings().first()
        return None if m is None else _row(m)

    @asynccontextmanager
    async def _unit_of_work(
        self, scope: AccountScope | None
    ) -> AsyncIterator[SqlAlchemyUnitOfWork]:
        """One transaction, its failures mapped; an `OwnerScope` checks the live owner first."""
        with _constraints():
            async with self._relational.unit_of_work() as uow:
                if isinstance(scope, OwnerScope):
                    gate = await uow.session.execute(_OWNER_GATE, {"caller": str(scope.user_id)})
                    if not gate.scalar_one():
                        raise AccountProfileStoreScopeDeniedError
                yield uow

    @staticmethod
    def _fails_closed(scope: AccountScope) -> bool:
        """A grant scope with no account sees nothing and runs no SQL."""
        return isinstance(scope, GrantScope) and not scope.account_ids

    async def list_profiles(
        self, scope: AccountScope, account_id: UUID
    ) -> tuple[AccountProfileRow, ...]:
        if self._fails_closed(scope):
            return ()
        async with self._unit_of_work(scope) as uow:
            rows = (await uow.session.execute(list_statement(scope, account_id))).mappings()
            return tuple(_row(m) for m in rows)

    async def get_profile(
        self, scope: AccountScope, account_id: UUID, profile_id: UUID
    ) -> AccountProfileRow | None:
        if self._fails_closed(scope):
            return None
        async with self._unit_of_work(scope) as uow:
            stmt = get_statement(scope, account_id, profile_id)
            m = (await uow.session.execute(stmt)).mappings().first()
        return None if m is None else _row(m)

    async def create_profile(
        self,
        scope: OwnerScope,
        account_id: UUID,
        profile_id: UUID,
        values: AccountProfileValues,
        *,
        write_ahead: ProfileWriteAhead | None = None,
    ) -> AccountProfileRow | None:
        owner = _require_owner(scope)
        async with self._unit_of_work(owner) as uow:
            locked = await uow.session.execute(lock_account_statement(owner, account_id))
            if locked.first() is None:
                return None
            stmt = insert_statement(owner, account_id, profile_id, values)
            created = _row((await uow.session.execute(stmt)).mappings().one())
            await self._ahead(write_ahead, None, created)
            await uow.commit()
        return created

    async def update_profile(
        self,
        scope: OwnerScope,
        account_id: UUID,
        profile_id: UUID,
        values: AccountProfileValues,
        *,
        expected_version: int | None,
        write_ahead: ProfileWriteAhead | None = None,
    ) -> AccountProfileRow | None:
        owner = _require_owner(scope)
        async with self._unit_of_work(owner) as uow:
            before = None
            if write_ahead is not None:  # the before-state, locked until the write commits
                before = await self._locked(uow, owner, account_id, profile_id)
            stmt = update_statement(owner, account_id, profile_id, values, expected_version)
            m = (await uow.session.execute(stmt)).mappings().first()
            if m is None:
                live = await self._live(uow, owner, account_id, profile_id)
                if live is None:
                    return None
                if expected_version is None or live.version == expected_version:
                    if live.values.is_default != values.is_default:
                        raise AccountProfileStoreRuleError(DEFAULT_MOVES_ALONE)
                raise AccountProfileStoreStaleError
            updated = _row(m)
            await self._ahead(write_ahead, before, updated)
            await uow.commit()
        return updated

    async def set_default_profile(
        self,
        scope: OwnerScope,
        account_id: UUID,
        profile_id: UUID,
        *,
        expected_version: int | None,
        write_ahead: ProfileWriteAhead | None = None,
    ) -> DefaultMove | None:
        owner = _require_owner(scope)
        async with self._unit_of_work(owner) as uow:
            await uow.session.execute(_LOCK_DEFAULT, {"account": str(account_id)})
            stmt = lock_profile_statement(owner, account_id, profile_id)
            current = (await uow.session.execute(stmt)).mappings().first()
            if current is None:
                return None
            target = _row(current)
            if expected_version is not None and target.version != expected_version:
                raise AccountProfileStoreStaleError
            if target.values.is_default:
                return DefaultMove(profile=target, previous=None, written=False)
            old = None
            if write_ahead is not None:  # the previous default's before-state, locked
                found = await uow.session.execute(default_statement(owner, account_id))
                m_old = found.mappings().first()
                old = None if m_old is None else _row(m_old)
            unset = await uow.session.execute(unset_default_statement(owner, account_id))
            m_prev = unset.mappings().first()
            previous = None if m_prev is None else _row(m_prev)
            moved = set_default_statement(owner, account_id, profile_id)
            profile = _row((await uow.session.execute(moved)).mappings().one())
            if previous is not None:
                await self._ahead(write_ahead, old, previous)
            await self._ahead(write_ahead, target, profile)
            await uow.commit()
        return DefaultMove(profile=profile, previous=previous, written=True)

    async def delete_profile(
        self,
        scope: OwnerScope,
        account_id: UUID,
        profile_id: UUID,
        *,
        expected_version: int | None,
        write_ahead: ProfileWriteAhead | None = None,
    ) -> AccountProfileRow | None:
        owner = _require_owner(scope)
        async with self._unit_of_work(owner) as uow:
            before = None
            if write_ahead is not None:  # the before-state, locked until the write commits
                before = await self._locked(uow, owner, account_id, profile_id)
            stmt = delete_statement(owner, account_id, profile_id, expected_version)
            m = (await uow.session.execute(stmt)).mappings().first()
            if m is None:
                live = await self._live(uow, owner, account_id, profile_id)
                if live is None:
                    return None
                if expected_version is None or live.version == expected_version:
                    if live.values.is_default:
                        raise AccountProfileStoreConflictError("default_profile")
                raise AccountProfileStoreStaleError
            deleted = _row(m)
            await self._ahead(write_ahead, before, deleted)
            await uow.commit()
        return deleted

    async def get_revision(
        self, scope: AccountScope, account_id: UUID, profile_id: UUID, version: int
    ) -> AccountProfileRevision | None:
        if self._fails_closed(scope):
            return None
        async with self._unit_of_work(scope) as uow:
            stmt = revision_statement(scope, account_id, profile_id, version)
            m = (await uow.session.execute(stmt)).mappings().first()
        if m is None:
            return None
        payload = json.loads(str(m["payload"]), parse_float=Decimal)
        return AccountProfileRevision(
            id=int(m["id"]),
            version=int(m["version"]),
            profile=_payload_row(payload),
            changed_by=_opt_uuid(m["changed_by"]),
            changed_at=m["changed_at"],
        )

    async def effective_profile(
        self, account_id: UUID, profile_id: UUID | None
    ) -> AccountProfileRow | None:
        async with self._unit_of_work(None) as uow:
            m = (await uow.session.execute(effective_statement(account_id, profile_id))).mappings()
            first = m.first()
        return None if first is None else _row(first)

    @staticmethod
    async def _live(
        uow: SqlAlchemyUnitOfWork, scope: OwnerScope, account_id: UUID, profile_id: UUID
    ) -> AccountProfileRow | None:
        m = (await uow.session.execute(get_statement(scope, account_id, profile_id))).mappings()
        first = m.first()
        return None if first is None else _row(first)
