"""Trade-group repository: the M13 facades over the trade-group store (E28-T01 #905;
24-internal-schemas.md Sec.9.1).

`TradeGroupRepository` is the system surface over the M10 `TradeGroupStore`: it takes no principal,
and no route or WS topic reaches it (an architecture test pins its callers, C-12.4). The OMS
(E29-T04, E34-S02), the lifecycle (E34-T01) and the safety monitor (E32-T02) call it after their
own admission: `decide(orders:write, GRANTED_ACCOUNTS, requires_trade=True)` on every leg account,
the kill switch and the live gate (SR-E28-27). `TradeGroupReader` is the principal-scoped read
over `TradeGroupReads` for routes and WS topics: the store applies the scope in SQL (SR-051,
SR-E28-21), so a group the caller may not see reads as missing, like one that does not exist.

Rows map to the Sec.9.1 models through `candleviewer.accounts.trade_groups`, the one adapter, and
store errors to the accounts domain errors, raised `from None` (a driver error can carry
parameter values). A refusal is logged by its name; no log carries a note, a rejection text, the
ref, the fingerprint, a snapshot or a money value. A stored row the store cannot decode, or the
adapter or a model refuses, fails closed as `AccountsError("stored trade group unreadable")`,
logged with the ids and the error class only (an error the write-ahead hook raises is never read
as one). A `StorageError` passes unmapped: after `WriteAheadTimeout` nothing was written, and
after any other (the tier unavailable, a failed query) the outcome of a write may be unknown, so
the caller reconciles.

The replay anchor is read only by its creator's `(created_by, client_group_ref)` (G-6(b),
SR-E29-07): `find_replay`, and a `create` that meets an existing anchor, answer a `GroupReplay`
when the request fingerprint matches and raise `TradeGroupKeyReuseError` when it does not,
writing nothing; another user's ref reads as missing.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Final
from uuid import UUID

import structlog

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountNotFoundError,
    AccountRuleError,
    AccountScopeDeniedError,
    AccountsError,
    ProfileChangedError,
    TradeGroupKeyReuseError,
    TradeGroupStaleError,
)
from candleviewer.accounts.trade_groups import (
    GroupReplay,
    GroupUpdate,
    LegDraft,
    LegUpdate,
    LegWithProfile,
    ScopedTradeGroup,
    TradeGroup,
    TradeGroupDraft,
    TradeGroupLeg,
    TradeGroupWithLegs,
    UnprotectedLeg,
    group_from_row,
    group_patch,
    group_values,
    leg_from_row,
    leg_patch,
    leg_profile_snapshot,
    leg_values,
    record_from_rows,
    shows_private_fields,
    unprotected_leg_from_row,
)
from candleviewer.domain.primitives import GroupId, UserId
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.accounts import AccountScope
from candleviewer.storage.repositories.trade_groups import (
    ACCOUNT_NOT_LIVE,
    DEFINITION_NOT_LIVE,
    PROFILE_CHANGED,
    GroupAnchor,
    GroupExists,
    GroupWriteAhead,
    LegSnapshotRow,
    LegStatus,
    TradeGroupReads,
    TradeGroupRecord,
    TradeGroupStatus,
    TradeGroupStore,
    TradeGroupStoreConflictError,
    TradeGroupStoreError,
    TradeGroupStoreRefusedError,
    TradeGroupStoreRuleError,
    TradeGroupStoreScopeDeniedError,
    TradeGroupStoreStaleError,
)

#: The request fingerprint the store compares verbatim (`sha256_hex`).
_SHA256_HEX: Final = re.compile(r"[0-9a-f]{64}")
#: What the store's decoder, the adapter or a model raises for a stored row it refuses
#: (`parse_json` and `pydantic.ValidationError` raise a `ValueError`; an unknown label is a
#: `KeyError`).
_UNREADABLE: Final = (ValueError, TypeError, KeyError, ArithmeticError)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _map(exc: TradeGroupStoreError, **ids: str) -> AccountsError:
    """The accounts domain error of a store error. `ids` (never a value) go with the one INFO a
    `profile_changed` refusal logs."""
    if isinstance(exc, TradeGroupStoreScopeDeniedError):
        return AccountScopeDeniedError()
    if isinstance(exc, TradeGroupStoreConflictError):
        _log().warning("trade_group.constraint_violation", constraint=exc.constraint)
        return AccountConflictError(exc.constraint)
    if isinstance(exc, TradeGroupStoreRuleError):
        _log().warning("trade_group.constraint_violation", constraint=exc.rule)
        return AccountRuleError(exc.rule)
    if isinstance(exc, TradeGroupStoreRefusedError):
        if exc.reason == ACCOUNT_NOT_LIVE:
            return AccountNotFoundError("account")
        if exc.reason == DEFINITION_NOT_LIVE:
            return AccountNotFoundError("definition")
        if exc.reason == PROFILE_CHANGED:
            _log().info("trade_group.profile_changed", **ids)
            return ProfileChangedError()
    if isinstance(exc, TradeGroupStoreStaleError):
        return TradeGroupStaleError()
    return AccountsError("store error")


def _unreadable(exc: Exception, **ids: str) -> AccountsError:
    """A stored row refused on read: a schema drift, logged with `ids` and the error class, never
    a value; the call fails closed with the returned `AccountsError`."""
    _log().warning("trade_group.read_failed_closed", error=type(exc).__name__, **ids)
    return AccountsError("stored trade group unreadable")


def _read[R, T](adapt: Callable[[R], T], row: R, **ids: str) -> T:
    """`adapt(row)`, or `_unreadable` when the adapter or a model refuses the stored row."""
    try:
        return adapt(row)
    except _UNREADABLE as exc:
        raise _unreadable(exc, **ids) from None


async def _call[T](call: Awaitable[T], **ids: str) -> T:
    """One store call: a store error raised as its domain error, a `StorageError` as it is, and
    a stored row the store cannot decode as `_unreadable`, logged with `ids`."""
    try:
        return await call
    except TradeGroupStoreError as exc:
        raise _map(exc) from None
    except StorageError:
        raise  # never relabelled, although a few are a `ValueError` or a `KeyError` too
    except _UNREADABLE as exc:
        raise _unreadable(exc, **ids) from None


def _replay(anchor: GroupAnchor) -> GroupReplay:
    """The group a creator's key anchors with the same fingerprint, or `TradeGroupKeyReuseError`
    (logged with the group id only: never the ref or the fingerprint)."""
    if anchor.body_matches:
        return GroupReplay(GroupId(anchor.group_id))
    _log().warning("trade_group.key_reuse", group_id=str(anchor.group_id))
    raise TradeGroupKeyReuseError()


def _require_fingerprint(client_body_sha256: str) -> None:
    """The store compares the fingerprint verbatim: a malformed one would turn every replay into
    a key reuse, so it is refused before any statement."""
    if _SHA256_HEX.fullmatch(client_body_sha256) is None:
        raise ValueError("client_body_sha256 must be 64 lower-case hex digits")


def _leg_with_profile(row: LegSnapshotRow) -> LegWithProfile:
    return LegWithProfile(leg=leg_from_row(row.leg), profile=leg_profile_snapshot(row))


class TradeGroupRepository:
    """Trade groups and their legs over a `TradeGroupStore`: the system surface, with no
    principal; never reached from a route."""

    def __init__(self, store: TradeGroupStore) -> None:
        self._store = store

    async def find_replay(
        self, created_by: UserId, client_group_ref: UUID, client_body_sha256: str
    ) -> GroupReplay | None:
        """The group this creator's `Idempotency-Key` anchors when its request fingerprint
        matches; `None` when the creator has no such key (another user's reads as missing).
        `TradeGroupKeyReuseError` when the key anchors a group with another fingerprint.
        `created_by` is the authenticated principal, or the rule owner (M15), never a client
        value."""
        _require_fingerprint(client_body_sha256)
        ref = str(client_group_ref)
        anchor = await _call(self._store.find_anchor(created_by, ref, client_body_sha256))
        return None if anchor is None else _replay(anchor)

    async def create(
        self,
        group: TradeGroupDraft,
        legs: Sequence[LegDraft],
        *,
        write_ahead: GroupWriteAhead,
    ) -> TradeGroupWithLegs | GroupReplay:
        """Store `group` with every leg in one transaction, after the caller's admission, and
        return them as stored; `write_ahead` (C-2.9) is awaited in that transaction before it
        commits, with the rows in stored units.

        Refused before any statement (`ValueError`): no leg, or two legs with one
        `sequence_no`. When the creator's key already anchors a group, nothing is written and the
        hook is not called: a `GroupReplay` when the fingerprint matches, else
        `TradeGroupKeyReuseError`. Under the store's share locks, a soft-deleted or missing leg
        account or definition is `AccountNotFoundError("account")` or `("definition")`, and a
        leg profile no longer live at the leg's `profile_version` is `ProfileChangedError`
        (SR-E28-15); any refusal writes nothing."""
        if write_ahead is None:  # typed out; a dynamic caller is refused too (C-2.9)
            raise TypeError("a trade group is created with its write-ahead record (C-2.9)")
        if not legs:
            raise ValueError("a trade group needs at least one leg")
        if len({leg.sequence_no for leg in legs}) != len(legs):
            raise ValueError("two legs of a trade group share a sequence_no")
        values, new_legs = group_values(group), [leg_values(leg) for leg in legs]
        hooked = False

        def hook(record: TradeGroupRecord) -> Awaitable[None]:
            nonlocal hooked
            hooked = True
            return write_ahead(record)

        try:
            outcome = await self._store.create_group(values, new_legs, write_ahead=hook)
        except TradeGroupStoreError as exc:
            accounts = ",".join(sorted(str(leg.exchange_account_id) for leg in new_legs))
            raise _map(exc, group_id=str(group.group_id), account_ids=accounts) from None
        except StorageError:
            raise
        except _UNREADABLE as exc:
            if hooked:  # the store decodes the rows before the hook: this is the hook's own
                raise
            raise _unreadable(exc, group_id=str(group.group_id)) from None
        if isinstance(outcome, GroupExists):
            return _replay(outcome.anchor)
        return _read(record_from_rows, outcome.record, group_id=str(group.group_id))

    async def update_leg(
        self,
        group_id: GroupId,
        leg_id: UUID,
        update: LegUpdate,
        *,
        expected_status: LegStatus | None = None,
    ) -> TradeGroupLeg:
        """Write `update`'s absolute values on this group's leg and return it as stored;
        `TradeGroupStaleError`, with nothing written, when `expected_status` is given and the leg
        holds another. A leg of another group, or none, is `AccountNotFoundError("leg")`."""
        patch, ids = leg_patch(update), {"group_id": str(group_id), "leg_id": str(leg_id)}
        call = self._store.update_leg(group_id, leg_id, patch, expected_status=expected_status)
        row = await _call(call, **ids)
        if row is None:
            raise AccountNotFoundError("leg")
        return _read(leg_from_row, row, **ids)

    async def update_group(
        self,
        group_id: GroupId,
        update: GroupUpdate,
        *,
        expected_status: TradeGroupStatus | None = None,
    ) -> TradeGroup:
        """Write `update`'s absolute values on the group and return it as stored;
        `TradeGroupStaleError`, with nothing written, when `expected_status` is given and the
        group holds another. A missing group is `AccountNotFoundError("trade_group")`."""
        patch = group_patch(update)
        call = self._store.update_group(group_id, patch, expected_status=expected_status)
        row = await _call(call, group_id=str(group_id))
        if row is None:
            raise AccountNotFoundError("trade_group")
        return _read(group_from_row, row, group_id=str(group_id))

    async def get(self, group_id: GroupId) -> TradeGroupWithLegs:
        """The group with its legs; `AccountNotFoundError("trade_group")` when there is none."""
        record = await _call(self._store.load_group(group_id), group_id=str(group_id))
        if record is None:
            raise AccountNotFoundError("trade_group")
        return _read(record_from_rows, record, group_id=str(group_id))

    async def leg_with_profile(self, leg_id: UUID) -> LegWithProfile:
        """The leg with the `AccountProfile` it was sized from, validated from its snapshot
        (SR-E28-07); `AccountNotFoundError("leg")` when there is none."""
        row = await _call(self._store.load_leg(leg_id), leg_id=str(leg_id))
        if row is None:
            raise AccountNotFoundError("leg")
        return _read(_leg_with_profile, row, leg_id=str(leg_id))

    async def open_groups(self) -> tuple[TradeGroupWithLegs, ...]:
        """Every group in an open status with its legs, oldest first (`ix_tg_open`), with no
        soft-delete filter: the lifecycle reloads them at restart."""
        records = await _call(self._store.list_open_groups())
        return tuple(
            _read(record_from_rows, record, group_id=str(record.group.id)) for record in records
        )

    async def unprotected_legs(self) -> tuple[UnprotectedLeg, ...]:
        """Every open leg whose native stop is not confirmed (C-2.6, `ix_tgl_no_sl`), a leg of a
        soft-deleted account included. A scan that raises is itself an alarm condition for the
        watchdog (E32-T02)."""
        rows = await _call(self._store.list_unprotected_legs())
        return tuple(_read(unprotected_leg_from_row, row, leg_id=str(row.leg.id)) for row in rows)


class TradeGroupReader:
    """The principal-scoped group read for routes and WS topics, over `TradeGroupReads`."""

    def __init__(self, store: TradeGroupReads) -> None:
        self._store = store

    async def get(self, scope: AccountScope, group_id: GroupId) -> ScopedTradeGroup:
        """The group when `scope` sees it (SR-E28-21): an Owner sees every group; anyone else a
        group that has a leg and whose every leg account is live and under their `can_view`
        grant that is not frozen. Every miss is the same `AccountNotFoundError("trade_group")`;
        an `OwnerScope` held by a non-owner is `AccountScopeDeniedError`."""
        record = await _call(self._store.get_group(scope, group_id), group_id=str(group_id))
        if record is None:
            raise AccountNotFoundError("trade_group")
        found = _read(record_from_rows, record, group_id=str(group_id))
        return ScopedTradeGroup(
            record=found, shows_private_fields=shows_private_fields(scope, found.group)
        )
