"""E42-T09 (#2649): `SqlAlchemyUserAdminStore` over a fake unit of work (Postgres:
tests/integration/admin/test_user_admin_pg.py).

`_Db` keeps `users` and their roles and answers each statement the user stores send by its
identity, applying their writes at the commit only; `SET CONSTRAINTS ALL IMMEDIATE` plays the
deferred owner-floor trigger (`trg_owner_floor_fn`, 23514). It keeps each user's purge columns
too (E42-T10 #2650): an enable refuses an anonymised user and cancels a pending purge (R6). The
property test drives the three stores that take the owner lock (roles, user admin, lifecycle)
through any sequence of role and status changes: at least one enabled owner always remains, and
every refusal is the stores' own check under the lock, never the trigger behind it.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.exc import IntegrityError

from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.owner_floor import OwnerFloorError, assert_owner_floor
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories import identity_sqlalchemy as identity
from candleviewer.storage.repositories import owner_floor_sqlalchemy as f
from candleviewer.storage.repositories import user_lifecycle_sqlalchemy as lifecycle
from candleviewer.storage.repositories import user_purge_sqlalchemy as purge
from candleviewer.storage.repositories import user_roles_sqlalchemy as role_store
from candleviewer.storage.repositories import users_sqlalchemy as m
from candleviewer.storage.repositories.user_lifecycle import UserPatch, UserUpdate
from candleviewer.storage.repositories.user_purge import PurgeUserAnonymisedError

_A, _B, _C = (uuid.UUID(int=n) for n in (0xA, 0xB, 0xC))
_ACTOR = uuid.UUID(int=0xF)
_T = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
_DUE = datetime(2027, 1, 17, 12, 0, tzinfo=UTC)  # a pending purge's `purge_after` (E42-T10)
_GUARD_S = 5.0  # ends a hang if the store stops bounding its audit hook


class _PgError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _floor(current: frozenset[str], new: frozenset[str], owners: int) -> None:
    assert_owner_floor(current_roles=current, new_roles=new, active_owner_count=owners)


class _Db:
    """`users` rows (status, roles, name, MFA flag) behind the statements of the user stores.
    Each unit of work edits a copy that its commit installs; `ran` orders every statement."""

    def __init__(self, **users: tuple[str, tuple[str, ...]]) -> None:
        self.users: dict[uuid.UUID, dict[str, Any]] = {
            uuid.UUID(int=int(k, 16)): {
                "status": status,
                "roles": frozenset(roles),
                "display_name": None,
                "mfa_required": True,
                "purge_after": None,
                "anonymised_at": None,
            }
            for k, (status, roles) in users.items()
        }
        self.ran: list[Any] = []
        self.commits = 0
        self.trigger_fired = False
        self.commit_error: BaseException | None = None
        self.raise_at: Any = None  # a statement that raises `IntegrityError(sqlstate)`
        self.sqlstate = "23503"
        self.read_misses = False  # the `User` read finds nothing (a row the read filters out)

    def owners(self, rows: Mapping[uuid.UUID, dict[str, Any]] | None = None) -> int:
        rows = self.users if rows is None else rows
        return sum(r["status"] == "active" and "owner" in r["roles"] for r in rows.values())

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        work = copy.deepcopy(self.users)

        def rows(found: list[Any]) -> Any:
            return SimpleNamespace(
                first=lambda: found[0] if found else None,
                all=lambda: found,
                scalar_one=lambda: found[0][0],
            )

        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> Any:
            self.ran.append(stmt)
            if stmt is self.raise_at:
                raise IntegrityError("statement", None, _PgError(self.sqlstate))
            p = params or {}
            user = work.get(uuid.UUID(p["id"])) if "id" in p else None
            if stmt is role_store._STATUS:
                return rows([] if user is None else [(user["status"],)])
            if stmt is f.LOCK_USER:
                return rows([] if user is None else [(user["status"],)])
            if stmt is f.LOCK_OWNERS:
                return rows([])
            if stmt is f.COUNT_OWNERS:
                return rows([(self.owners(work),)])
            if stmt is f.ROLES:
                return rows([] if user is None else [_mapping(roles=sorted(user["roles"]))])
            if stmt is identity._USER_SQL:
                found = user is not None and not self.read_misses
                return rows([_mapping(**_user_row(p["id"], user))] if found else [])
            if stmt is role_store.DROP_ROLES or stmt is role_store.GRANT_ROLES:
                assert user is not None
                user["roles"] = frozenset(p["roles"])
                return rows([])
            if stmt is m._PATCH_USER:
                assert user is not None
                if p["set_name"]:
                    user["display_name"] = p["name"]
                if p["require_mfa"]:
                    user["mfa_required"] = True
                if p["enable"] and user["status"] == "disabled":
                    user["status"] = "active"
                return rows([])
            if stmt is lifecycle._DISABLE:
                assert user is not None
                user["status"] = "disabled"
                return rows([])
            if stmt is purge._ANONYMISED:
                return rows([] if user is None else [(user["anonymised_at"] is not None,)])
            if stmt is purge._PENDING:  # a pending purge: scheduled and not run
                pending = user is not None and user["anonymised_at"] is None
                return rows([(user["purge_after"],)] if pending and user["purge_after"] else [])
            if stmt is purge._CANCEL:
                assert user is not None
                user["purge_after"] = None
                return rows([])
            if stmt in (
                lifecycle._REVOKE_SESSIONS,
                lifecycle._LIVE_GRANTS,
                lifecycle._REVOKE_GRANTS,
            ):
                return rows([])
            if stmt is f.CONSTRAINTS_NOW:  # the deferred trigger, fired now
                if self.owners(work) == 0:
                    self.trigger_fired = True
                    raise IntegrityError("SET CONSTRAINTS", None, _PgError("23514"))
                return rows([])
            raise AssertionError(f"a statement this fake does not model: {stmt}")

        async def commit() -> None:
            if self.commit_error is not None:
                raise self.commit_error
            self.users = work
            self.commits += 1
            self.ran.append("COMMIT")

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _mapping(**fields: Any) -> Any:
    return SimpleNamespace(_mapping=fields)


def _user_row(uid: str, user: dict[str, Any]) -> dict[str, Any]:
    name = f"u{uid[-4:]}"
    return {
        "id": uid,
        "username": name,
        "email": f"{name}@example.invalid",
        "display_name": user["display_name"],
        "status": user["status"],
        "mfa_required": user["mfa_required"],
        "last_login_at": None,
        "created_at": _T,
        "updated_at": _T,
        "roles": sorted(user["roles"]),
        "mfa_enabled": True,
    }


def _rel(db: _Db) -> Any:
    """The fake unit of work, in place of the store's relational repository."""
    return db


def _store(db: _Db, timeout_s: float = 5.0) -> m.SqlAlchemyUserAdminStore:
    return m.SqlAlchemyUserAdminStore(_rel(db), owner_floor=_floor, audit_timeout_s=timeout_s)


class _Hook:
    def __init__(self, db: _Db, error: BaseException | None = None) -> None:
        self.db, self.error, self.calls = db, error, list[UserUpdate]()

    async def __call__(self, change: UserUpdate) -> None:
        self.db.ran.append("AUDIT")
        self.calls.append(change)
        if self.error is not None:
            raise self.error


def _no_check(_: Mapping[str, Any]) -> None:
    return None


async def _update(
    db: _Db, target: uuid.UUID, patch: UserPatch, hook: _Hook | None = None, **kw: Any
) -> UserUpdate | None:
    return await _store(db).update_user(
        target, patch, actor=_ACTOR, check=kw.get("check", _no_check), audit=hook or _Hook(db)
    )


_LOCKED = [f.LOCK_USER, f.LOCK_OWNERS, f.COUNT_OWNERS, identity._USER_SQL]


async def test_role_change_statement_order_lock_read_check_dml_constraints_read_audit_commit() -> (
    None
):
    db = _Db(a=("active", ("owner",)), b=("active", ("viewer",)))
    hook = _Hook(db)
    change = await _update(db, _B, UserPatch(roles=frozenset({"manager"})), hook)
    assert db.ran == [
        *_LOCKED,
        role_store.DROP_ROLES,
        role_store.GRANT_ROLES,
        f.CONSTRAINTS_NOW,
        identity._USER_SQL,
        "AUDIT",
        "COMMIT",
    ]
    assert change is not None and change.changed and hook.calls == [change]
    assert (change.before["roles"], change.after["roles"]) == (["viewer"], ["manager"])
    assert db.users[_B]["roles"] == {"manager"}


async def test_name_mfa_and_enable_are_one_update_of_the_user_row() -> None:
    db = _Db(a=("active", ("owner",)), b=("disabled", ("viewer",)))
    db.users[_B]["mfa_required"] = False
    patch = UserPatch(display_name="B", set_display_name=True, require_mfa=True, enable=True)
    change = await _update(db, _B, patch)
    after = [m._PATCH_USER, purge._PENDING, f.CONSTRAINTS_NOW, identity._USER_SQL, "AUDIT"]
    assert db.ran == [*_LOCKED, purge._ANONYMISED, *after, "COMMIT"]
    assert change is not None and change.purge_cancelled is None  # none was pending
    assert {k: change.after[k] for k in ("display_name", "mfa_required", "status")} == {
        "display_name": "B",
        "mfa_required": True,
        "status": "active",
    }


def test_the_update_only_ever_sets_mfa_required() -> None:
    """O3 (C-12.2), the store's own line behind the contract's `Literal[True]` and the route's
    refusals: `_PATCH_USER` ORs the flag in and never assigns it, so no `UserPatch` (a rename
    sends `require_mfa` false) can clear `mfa_required`. `_Db` applies the OR itself, so this
    pins the statement; Postgres runs it (`test_a_rename_never_clears_mfa_required`)."""
    sql = " ".join(str(m._PATCH_USER).split())
    assert "mfa_required = mfa_required OR CAST(:require_mfa AS boolean)" in sql
    assert sql.count("mfa_required =") == 1


async def test_a_patch_that_changes_nothing_writes_audits_and_commits_nothing() -> None:
    db = _Db(a=("active", ("owner",)), b=("active", ("viewer",)))
    patch = UserPatch(roles=frozenset({"viewer"}), require_mfa=True, enable=True)
    hook = _Hook(db)
    change = await _update(db, _B, patch, hook)
    assert change is not None and not change.changed and change.before == change.after
    assert db.ran == _LOCKED and hook.calls == [] and db.commits == 0


async def test_a_refused_precondition_rolls_back_before_any_write() -> None:
    db = _Db(a=("active", ("owner",)), b=("active", ("viewer",)))

    def stale(_: Mapping[str, Any]) -> None:
        raise LookupError("stale")

    with pytest.raises(LookupError):
        await _update(db, _B, UserPatch(roles=frozenset({"manager"})), check=stale)
    assert db.ran == _LOCKED and db.commits == 0 and db.users[_B]["roles"] == {"viewer"}


async def test_the_precondition_sees_the_representation_read_under_the_lock() -> None:
    db = _Db(a=("active", ("owner",)), b=("active", ("viewer",)))
    seen: list[Mapping[str, Any]] = []
    await _update(db, _B, UserPatch(display_name="x", set_display_name=True), check=seen.append)
    (read,) = seen
    assert (
        read["roles"] == ["viewer"] and read["status"] == "active" and "password_hash" not in read
    )


async def test_the_last_active_owner_is_not_demoted_and_nothing_is_written() -> None:
    db = _Db(a=("active", ("owner",)), b=("active", ("viewer",)))
    hook = _Hook(db)
    with pytest.raises(OwnerFloorError) as refused:
        await _update(db, _A, UserPatch(roles=frozenset({"manager"})), hook)
    assert refused.value.__context__ is None  # the locked count refused it, not the trigger
    assert db.ran == _LOCKED and hook.calls == [] and db.users[_A]["roles"] == {"owner"}


async def test_a_non_active_owner_is_demoted_while_one_other_owner_is_active() -> None:
    """The floor counts an owner grant of an active target only (`counted_roles`)."""
    for status in ("disabled", "locked", "invited"):
        db = _Db(a=("active", ("owner",)), b=(status, ("owner",)))
        change = await _update(db, _B, UserPatch(roles=frozenset({"viewer"})))
        assert change is not None and db.users[_B]["roles"] == {"viewer"}


async def test_a_trigger_violation_maps_onto_the_floor_refusal() -> None:
    """Defence in depth: a floor check that let it through is caught by the deferred trigger
    (23514), which the store maps onto the floor's own refusal."""
    db = _Db(a=("active", ("owner",)), b=("active", ("viewer",)))
    store = m.SqlAlchemyUserAdminStore(_rel(db), owner_floor=_lenient_then_strict())
    with pytest.raises(OwnerFloorError) as refused:
        await store.update_user(
            _A,
            UserPatch(roles=frozenset({"viewer"})),
            actor=_ACTOR,
            check=_no_check,
            audit=_Hook(db),
        )
    assert isinstance(refused.value.__context__, IntegrityError) and db.trigger_fired
    assert db.commits == 0 and db.users[_A]["roles"] == {"owner"}


def _lenient_then_strict() -> Any:
    calls = {"n": 0}

    def floor(current: frozenset[str], new: frozenset[str], owners: int) -> None:
        calls["n"] += 1
        if calls["n"] > 1:  # the mapping call: the trigger saw no active owner left
            _floor(current, new, owners)

    return floor


async def test_a_refused_audit_record_rolls_the_change_back() -> None:
    db = _Db(a=("active", ("owner",)), b=("active", ("viewer",)))
    with pytest.raises(AuditUnavailable):
        await _update(
            db, _B, UserPatch(roles=frozenset({"manager"})), _Hook(db, AuditUnavailable("x"))
        )
    assert db.commits == 0 and db.users[_B]["roles"] == {"viewer"}


async def test_an_audit_hook_that_never_returns_times_out_and_rolls_back() -> None:
    db = _Db(a=("active", ("owner",)), b=("active", ("viewer",)))

    async def hang(_: UserUpdate) -> None:
        await asyncio.Event().wait()

    store = _store(db, timeout_s=0.01)
    async with asyncio.timeout(_GUARD_S):
        with pytest.raises(WriteAheadTimeout):
            await store.update_user(
                _B,
                UserPatch(roles=frozenset({"manager"})),
                actor=_ACTOR,
                check=_no_check,
                audit=hang,
            )
    assert db.commits == 0 and db.users[_B]["roles"] == {"viewer"}


async def test_a_missing_user_is_none_and_get_user_reads_the_representation() -> None:
    db = _Db(a=("active", ("owner",)))
    assert await _update(db, _B, UserPatch(display_name="x", set_display_name=True)) is None
    store = _store(db)
    assert await store.get_user(_B) is None
    found = await store.get_user(_A)
    assert found is not None and found["roles"] == ["owner"] and "password_hash" not in found
    assert found["created_at"] == _T.isoformat()


async def test_enable_restores_nothing_but_the_status() -> None:
    """R6: an enable flips `status` only; roles stay as they were, nothing else is written."""
    db = _Db(a=("active", ("owner",)), b=("disabled", ("manager",)))
    change = await _update(db, _B, UserPatch(enable=True))
    assert change is not None and db.users[_B] == {
        "status": "active",
        "roles": frozenset({"manager"}),
        "display_name": None,
        "mfa_required": True,
        "purge_after": None,
        "anonymised_at": None,
    }
    assert [s for s in db.ran if s is m._PATCH_USER] == [m._PATCH_USER]
    assert role_store.GRANT_ROLES not in db.ran


async def test_enable_never_lifts_an_invited_or_locked_status() -> None:
    """R6 in SQL too: `active` only from `disabled`, whatever the caller checked."""
    for status in ("invited", "locked"):
        db = _Db(a=("active", ("owner",)), b=(status, ("viewer",)))
        change = await _update(db, _B, UserPatch(enable=True))
        assert change is not None and not change.changed and db.users[_B]["status"] == status


async def test_enable_cancels_a_pending_purge_ahead_of_its_record() -> None:
    """E42-T10 (#2650, #965 R6): an enable clears a pending purge in its own transaction, under the
    user-row lock, before its write-ahead record, which is handed the cancelled date."""
    db = _Db(a=("active", ("owner",)), b=("disabled", ("manager",)))
    db.users[_B]["purge_after"] = _DUE
    hook = _Hook(db)
    change = await _update(db, _B, UserPatch(enable=True), hook)
    writes = [m._PATCH_USER, purge._PENDING, purge._CANCEL, f.CONSTRAINTS_NOW]
    assert db.ran == [*_LOCKED, purge._ANONYMISED, *writes, identity._USER_SQL, "AUDIT", "COMMIT"]
    assert change is not None and change.purge_cancelled == _DUE and hook.calls == [change]
    assert db.users[_B]["purge_after"] is None and db.users[_B]["status"] == "active"


async def test_an_anonymised_user_is_refused_before_any_write() -> None:
    """#2650 (the orchestrator's 2026-10-20 ruling, second line): once the purge has run, an enable
    raises `PurgeUserAnonymisedError` under the lock, before any write or record; nothing
    commits and the row keeps its purge columns."""
    db = _Db(a=("active", ("owner",)), b=("disabled", ("manager",)))
    db.users[_B].update(purge_after=_T, anonymised_at=_DUE)
    kept, hook = copy.deepcopy(db.users), _Hook(db)
    patch = UserPatch(enable=True, display_name="back", set_display_name=True)
    with pytest.raises(PurgeUserAnonymisedError):
        await _update(db, _B, patch, hook)
    assert db.ran == [*_LOCKED, purge._ANONYMISED] and hook.calls == []
    assert db.commits == 0 and db.users == kept


async def test_a_refused_enable_record_keeps_the_purge_pending() -> None:
    """#2650: the cancel is in the enable's transaction, so a refused `users.enable` record rolls
    it back with the status: the user stays disabled and the purge stays pending."""
    db = _Db(a=("active", ("owner",)), b=("disabled", ("manager",)))
    db.users[_B]["purge_after"] = _DUE
    with pytest.raises(AuditUnavailable):
        await _update(db, _B, UserPatch(enable=True), _Hook(db, AuditUnavailable("x")))
    assert purge._CANCEL in db.ran and db.commits == 0
    assert (db.users[_B]["status"], db.users[_B]["purge_after"]) == ("disabled", _DUE)


async def test_another_integrity_error_is_raised_as_it_is_and_nothing_commits() -> None:
    """Only the trigger's 23514 is the floor's refusal; any other integrity error is a defect."""
    db = _Db(a=("active", ("owner",)), b=("active", ("viewer",)))
    db.raise_at = role_store.DROP_ROLES
    with pytest.raises(IntegrityError):
        await _update(db, _B, UserPatch(roles=frozenset({"manager"})))
    assert db.commits == 0 and db.users[_B]["roles"] == {"viewer"}


async def test_a_row_the_user_read_misses_under_the_lock_is_none() -> None:
    db = _Db(a=("active", ("owner",)), b=("active", ("viewer",)))
    db.read_misses = True
    assert await _update(db, _B, UserPatch(display_name="x", set_display_name=True)) is None
    assert db.commits == 0


async def test_the_role_store_reads_a_users_status_for_the_route_pre_check() -> None:
    db = _Db(a=("active", ("owner",)), b=("disabled", ("owner",)))
    store = role_store.SqlAlchemyUserRoleStore(_rel(db), owner_floor=_floor)
    assert (await store.get_status(_A), await store.get_status(_B)) == ("active", "disabled")
    assert await store.get_status(_C) is None


# -- the owner floor holds across any sequence of role and status changes ------------------------

_ROLE_SETS = st.frozensets(st.sampled_from(("owner", "manager", "viewer")), min_size=1)
_STATUSES = st.sampled_from(("active", "disabled", "locked", "invited"))
_OPS = st.lists(
    st.one_of(
        st.tuples(st.just("put_roles"), st.sampled_from((_A, _B, _C)), _ROLE_SETS),
        st.tuples(st.just("patch_roles"), st.sampled_from((_A, _B, _C)), _ROLE_SETS),
        st.tuples(st.just("enable"), st.sampled_from((_A, _B, _C)), st.none()),
        st.tuples(st.just("disable"), st.sampled_from((_A, _B, _C)), st.none()),
    ),
    max_size=25,
)


async def _apply(db: _Db, op: str, target: uuid.UUID, roles: frozenset[str] | None) -> None:
    hook = _Hook(db)
    try:
        if op == "put_roles":  # `PUT /users/{userId}/roles` (#2508)
            assert roles is not None
            store = role_store.SqlAlchemyUserRoleStore(_rel(db), owner_floor=_floor)
            await store.apply_roles(target, roles, actor=_ACTOR, audit=lambda _: _noop())
        elif op == "patch_roles":  # `PATCH /users/{userId}` with roles (#2649)
            await _update(db, target, UserPatch(roles=roles), hook)
        elif op == "enable":  # `PATCH` to `active` (#2649)
            await _update(db, target, UserPatch(enable=True), hook)
        else:  # `DELETE /users/{userId}` or `PATCH` to `disabled` (E42-T04 S3)
            store_l = lifecycle.SqlAlchemyUserLifecycleStore(_rel(db), owner_floor=_floor)
            await store_l.disable(target, actor=_ACTOR, now=_T, audit=lambda _: _noop())
    except OwnerFloorError as exc:
        assert exc.__context__ is None, "the trigger refused what the store's check let through"


async def _noop() -> None:
    return None


@settings(max_examples=150, deadline=None)
@given(
    initial=st.tuples(
        st.tuples(_STATUSES, _ROLE_SETS),
        st.tuples(_STATUSES, _ROLE_SETS),
        st.tuples(_STATUSES, _ROLE_SETS),
    ),
    ops=_OPS,
)
def test_owner_always_remains(
    initial: tuple[tuple[str, frozenset[str]], ...],
    ops: list[tuple[str, uuid.UUID, frozenset[str] | None]],
) -> None:
    """SR-055 (D6): from any start with an enabled owner, no sequence of role and status changes
    through the three stores leaves none, and only the stores' own check ever refuses."""
    db = _Db(**{k: (s, tuple(r)) for k, (s, r) in zip(("a", "b", "c"), initial, strict=True)})
    if db.owners() == 0:
        db.users[_A] = {**db.users[_A], "status": "active", "roles": frozenset({"owner"})}

    async def run() -> None:
        for op, target, roles in ops:
            await _apply(db, op, target, roles)
            assert db.owners() >= 1, (op, target, roles, db.users)

    asyncio.run(run())
    assert not db.trigger_fired
