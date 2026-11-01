"""E42-T10 (#2650, #965 O6): the surrogate, the "no usable password" value, and
`SqlAlchemyUserPurgeStore` over a fake unit of work: the schedule behind
`DELETE /users/{userId}?purge=true` (`users.delete` ahead), the reaper's bounded keyset read and its
per-user anonymisation (`users.anonymise` ahead, after a locked re-check, UL-F5), which revokes
every credential in the same transaction (orchestrator ruling, 2026-10-20), and the cancel
E42-T09's enable path calls (R6). Real Postgres: tests/integration/admin/test_user_purge_pg.py."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import re
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.audit.actions import UnknownAuditAction, validate_action
from candleviewer.audit.redact import redact
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.invite_service import placeholder_password_hash
from candleviewer.storage.errors import ActorNotAuthorised
from candleviewer.storage.repositories import owner_floor_sqlalchemy as f
from candleviewer.storage.repositories import user_purge as purge
from candleviewer.storage.repositories import user_purge_sqlalchemy as m
from candleviewer.storage.repositories.owner_floor_sqlalchemy import CONSTRAINTS_NOW

_UID, _ACTOR, _SESSION, _RID = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
_NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
_DUE_AT = _NOW - timedelta(seconds=1)  # a purge_after that has passed
#: Ends a hang if the store stops bounding its write-ahead; never reached when it does.
_GUARD_S = 5.0
#: What the store may write into a lifecycle record (UL-F1, O6): ids, status, times and counts.
_STATE_KEYS = {
    "status",
    "purge_after",
    "anonymised_at",
    "sessions_scrubbed",
    "credentials_revoked",
    "sessions_revoked",
    "mfa_methods_deleted",
    "recovery_rows_deleted",
}
#: The repo's "no usable password" value: an Argon2id head and a random 32-hex tail.
_UNUSABLE = re.compile(r"\$argon2id\$v=19\$m=65536,t=3,p=4\$[0-9a-f]{32}")
_PII = ("email", "username", "display_name", "last_login_ip", "user_agent", "device_label")
#: #2593: the owner lock and the actor's re-read, after the user row and before any answer.
_RECHECK = [f.LOCK_OWNERS, f.COUNT_OWNERS, f.ACTOR_IS_ACTIVE_OWNER]


class _DriverUUID(uuid.UUID):
    """Stands in for asyncpg's `uuid.UUID` subclass."""


class _Db:
    """Fake unit of work keyed by statement and audit emitter in one: statements (with their
    parameters), records and the commit share one log, so a test reads their order."""

    def __init__(
        self,
        user: tuple[Any, ...] | None = ("disabled", None, None),
        *,
        due: Sequence[uuid.UUID] = (),
        sessions: int = 2,
        live: Sequence[uuid.UUID] = (),
        mfa: int = 1,
        codes: int = 10,
        commit_error: BaseException | None = None,
        audit_error: BaseException | None = None,
        actor_owner: bool = True,
    ) -> None:
        self.rows: dict[Any, list[Any]] = {
            f.LOCK_OWNERS: [(uuid.uuid4(),)] * 2,
            f.COUNT_OWNERS: [(2,)],
            f.ACTOR_IS_ACTIVE_OWNER: [(1,)] if actor_owner else [],  # #2593
            m._LOCK_FOR_SCHEDULE: [user] if user is not None else [],
            m._LOCK_FOR_ANONYMISE: [user] if user is not None else [],
            m._DUE: [(_DriverUUID(str(u)), _DUE_AT) for u in due],
            m._REVOKE_SESSIONS: [(_DriverUUID(str(u)),) for u in live],
            m._SCRUB_SESSIONS: [(uuid.uuid4(),) for _ in range(sessions)],
            m._DROP_MFA: [(uuid.uuid4(),) for _ in range(mfa)],
            m._DROP_RECOVERY: [(uuid.uuid4(),) for _ in range(codes)],
        }
        self.commit_error, self.audit_error = commit_error, audit_error
        self.log: list[Any] = []
        self.records: list[dict[str, Any]] = []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: Any = None) -> Any:
            self.log.append((stmt, params))
            rows = self.rows.get(stmt, [])
            return SimpleNamespace(
                first=lambda: rows[0] if rows else None,
                all=lambda: rows,
                scalar_one=lambda: rows[0][0],
            )

        async def commit() -> None:
            if self.commit_error is not None:
                raise self.commit_error
            self.log.append("COMMIT")

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)

    async def emit(self, action: str, **fields: Any) -> None:
        self.log.append(f"AUDIT {action} {fields['outcome']}")
        if self.audit_error is not None and fields["outcome"] == "success":
            raise self.audit_error
        self.records.append({"action": action, **fields})

    def order(self) -> list[Any]:
        return [entry if isinstance(entry, str) else entry[0] for entry in self.log]

    def params(self, stmt: Any) -> list[Any]:
        return [p for s, p in (e for e in self.log if not isinstance(e, str)) if s is stmt]


def _store(
    db: Any, *, audit: Any = None, timeout_s: float = m.AUDIT_TIMEOUT_S
) -> m.SqlAlchemyUserPurgeStore:
    """`db` is the fake unit of work, typed `Any` in place of the real repository."""
    return m.SqlAlchemyUserPurgeStore(
        db, audit=audit or db, clock=lambda: _NOW, audit_timeout_s=timeout_s
    )


async def _schedule(db: _Db, **kw: Any) -> purge.PurgeSchedule:
    return await _store(db, **kw).schedule(
        _UID, actor_user_id=_ACTOR, request_id=_RID, session_id=_SESSION
    )


def _reference(user_id: uuid.UUID) -> str:
    """O6, written out: `deleted-user-` and the first 12 hex of SHA-256(prefix + the user id)."""
    digest = hashlib.sha256(f"cv-user-surrogate:{user_id}".encode()).hexdigest()
    return f"deleted-user-{digest[:12]}"


# --- the surrogate (O6, UL4-I2) ---------------------------------------------------------------


@given(st.uuids())
def test_surrogate_stable(user_id: uuid.UUID) -> None:
    """The same id gives the same surrogate on every call and every run (no salt, no clock), in
    a shape the `users` CHECKs admit: at most 32 characters, and an email with its `@`."""
    first = purge.surrogate(user_id)
    assert first == purge.surrogate(uuid.UUID(str(user_id))) == _reference(user_id)
    assert re.fullmatch(r"deleted-user-[0-9a-f]{12}", first) and len(first) <= 32
    assert purge.anonymised_email(user_id) == f"{first}@deleted.invalid"


def test_surrogate_known_answers_pin_the_formula_across_runs() -> None:
    """Two vectors computed once: a later run, process or host computes the same values."""
    pinned = uuid.UUID("6f1c9a2e-3b4d-4e5f-8a6b-7c8d9e0f1a2b")
    assert purge.surrogate(pinned) == "deleted-user-208695978d9d"
    assert purge.surrogate(uuid.UUID(int=0)) == "deleted-user-bfe8da5ae4de"


@given(st.uuids(), st.emails(), st.text(min_size=3, max_size=32), st.ip_addresses())
def test_surrogate_not_from_pii(user_id: uuid.UUID, email: str, name: str, ip: Any) -> None:
    """The surrogate is a function of the user id alone: the id is its only parameter and the
    hash input is the fixed prefix and the id, so whatever email, name or address the user held,
    the result is the same, and none of them can be read back from it."""
    assert list(inspect.signature(purge.surrogate).parameters) == ["user_id"]
    assert list(inspect.signature(purge.anonymised_email).parameters) == ["user_id"]
    held = {"email": email, "username": name, "last_login_ip": str(ip)}
    assert purge.surrogate(user_id) == _reference(user_id), held


def test_both_records_are_registered_audit_actions() -> None:
    """R5: `users.delete` and `users.anonymise` are in the one audit vocabulary, registered in the
    change that first emits them, so the writer accepts them; an unregistered one is refused."""
    assert [validate_action(a) for a in (m._DELETE, m._ANONYMISE_ACTION)] == [
        "users.delete",
        "users.anonymise",
    ]
    with pytest.raises(UnknownAuditAction):
        validate_action("users.erase")


def test_the_store_reads_no_pii_column() -> None:
    """No statement the store runs selects or filters on a PII column or a secret: what it writes
    for a user can only come from the id (the surrogate), be the no-usable-password value, or be
    NULL."""
    read = (m._LOCK_FOR_SCHEDULE, m._LOCK_FOR_ANONYMISE, m._DUE, m._PENDING)
    for stmt in read:
        assert not [column for column in _PII if column in str(stmt)], str(stmt)
        assert "password_hash" not in str(stmt) and "secret" not in str(stmt), str(stmt)
    for stmt in (m._REVOKE_SESSIONS, m._SCRUB_SESSIONS, m._DROP_MFA, m._DROP_RECOVERY):
        assert str(stmt).rstrip().endswith("RETURNING id"), str(stmt)  # ids only, to count


# --- the no-usable-password value (orchestrator ruling, 2026-10-20) ---------------------------


@settings(max_examples=25, deadline=None)
@given(st.text(max_size=64))
def test_no_password_verifies_against_the_unusable_hash(password: str) -> None:
    """The anonymised row's password hash: `users_pwd_argon` admits it, the hasher refuses every
    password against it (with or without the pepper), and each call draws a fresh random tail, so
    it is the invite placeholder's shape and keeps nothing of the old hash."""
    unusable = purge.unusable_password_hash()
    assert _UNUSABLE.fullmatch(unusable) and unusable.startswith("$argon2id$")
    assert _UNUSABLE.fullmatch(placeholder_password_hash())  # the same value `InviteService` parks
    assert unusable != purge.unusable_password_hash()

    async def verified() -> list[bool]:
        return [await Hasher(pepper).verify(unusable, password) for pepper in ("", "pepper")]

    assert asyncio.run(verified()) == [False, False]


# --- the schedule (S14: `users.delete` ahead, 90 days out) ------------------------------------


async def test_schedule_sets_purge_after_90_days_out_and_writes_users_delete_ahead() -> None:
    """R5: the lock, the one write, the deferred constraints, `users.delete`, then the commit;
    `purge_after` is the injected clock plus 90 days."""
    db = _Db()
    result = await _schedule(db)
    due = _NOW + timedelta(days=90)
    assert result == purge.PurgeSchedule(_UID, due, changed=True)
    assert db.order() == [
        m._LOCK_TIMEOUT,
        m._LOCK_FOR_SCHEDULE,
        *_RECHECK,
        m._SCHEDULE,
        CONSTRAINTS_NOW,
        "AUDIT users.delete success",
        "COMMIT",
    ]
    assert db.params(m._SCHEDULE) == [{"id": str(_UID), "purge_after": due}]
    assert db.params(m._LOCK_TIMEOUT) == [{"timeout": "5000ms"}]
    (record,) = db.records
    assert record == {
        "action": "users.delete",
        "actor_label": str(_ACTOR),
        "actor_user_id": _ACTOR,
        "session_id": _SESSION,
        "request_id": _RID,
        "object_kind": "user",
        "object_id": str(_UID),
        "outcome": "success",
        "severity": "warning",
        "reason": None,
        "before_state": {"status": "disabled", "purge_after": None},
        "after_state": {"status": "disabled", "purge_after": due.isoformat()},
    }


@pytest.mark.parametrize(
    "row",
    [("disabled", _DUE_AT, None), ("disabled", _DUE_AT, _NOW)],
    ids=["already-scheduled", "already-anonymised"],
)
async def test_schedule_repeat_is_a_noop_that_keeps_the_first_date(row: tuple[Any, ...]) -> None:
    """A second delete with purge postpones nothing and writes no second `users.delete`."""
    db = _Db(row)
    assert await _schedule(db) == purge.PurgeSchedule(_UID, _DUE_AT, changed=False)
    assert db.order() == [m._LOCK_TIMEOUT, m._LOCK_FOR_SCHEDULE, *_RECHECK] and db.records == []


@pytest.mark.parametrize(
    ("row", "error"),
    [
        (None, purge.PurgeUserNotFoundError),
        (("active", None, None), purge.PurgeUserNotDisabledError),
        (("invited", None, None), purge.PurgeUserNotDisabledError),
    ],
    ids=["missing", "re-enabled", "invited"],
)
async def test_schedule_refuses_a_user_that_is_not_disabled(
    row: tuple[Any, ...] | None, error: type[Exception]
) -> None:
    """Only a disabled user is scheduled: a re-enable that won the race keeps the user active."""
    db = _Db(row)
    with pytest.raises(error):
        await _schedule(db)
    assert db.order() == [m._LOCK_TIMEOUT, m._LOCK_FOR_SCHEDULE, *_RECHECK] and db.records == []


@pytest.mark.parametrize(
    "row",
    [("disabled", None, None), ("disabled", _DUE_AT, None), ("active", None, None), None],
    ids=["schedule", "repeat", "re-enabled", "missing"],
)
async def test_schedule_by_an_actor_no_longer_an_owner_is_refused_before_any_answer(
    row: tuple[Any, ...] | None,
) -> None:
    """#2593: the actor is re-read under the owner lock, after the user row and ahead of the
    not-found, not-disabled and repeat answers; nothing is written, recorded or committed."""
    db = _Db(row, actor_owner=False)
    with pytest.raises(ActorNotAuthorised) as caught:
        await _schedule(db)
    assert caught.value.actor_id == str(_ACTOR)
    assert db.order() == [m._LOCK_TIMEOUT, m._LOCK_FOR_SCHEDULE, *_RECHECK] and db.records == []
    assert db.params(f.ACTOR_IS_ACTIVE_OWNER) == [{"id": str(_ACTOR)}]


async def test_schedule_with_audit_down_changes_nothing() -> None:
    """AC8 for the purge: a refused `users.delete` rolls the write back (no commit)."""
    db = _Db(audit_error=RuntimeError("audit writer not started"))
    with pytest.raises(purge.PurgeAuditUnavailableError):
        await _schedule(db)
    assert "COMMIT" not in db.order() and db.records == []


async def test_schedule_bounds_its_write_ahead() -> None:
    """A write-ahead that outlives `audit_timeout_s` is refused like one the writer refused."""
    db = _Db()

    class _Hung:
        async def emit(self, action: str, **fields: Any) -> None:
            await asyncio.Event().wait()

    call = asyncio.create_task(_schedule(db, audit=_Hung(), timeout_s=0))
    done, _ = await asyncio.wait({call}, timeout=_GUARD_S)
    assert call in done and isinstance(call.exception(), purge.PurgeAuditUnavailableError)
    assert "COMMIT" not in db.order()


async def test_schedule_commit_failure_closes_its_record_as_outcome_unknown() -> None:
    """C-2.9: the commit was sent and failed, so it may have landed; the record written ahead is
    closed with a `failure` naming that, with no after state, and the error leaves."""
    db = _Db(commit_error=OSError("connection reset"))
    with pytest.raises(OSError, match="connection reset"):
        await _schedule(db)
    assert [(r["outcome"], r["reason"]) for r in db.records] == [
        ("success", None),
        ("failure", "outcome_unknown"),
    ]
    closing = db.records[-1]
    assert (closing["action"], closing["severity"], closing["after_state"]) == (
        "users.delete",
        "error",
        None,
    )


async def test_schedule_and_anonymise_records_carry_no_pii() -> None:
    """UL-F1, O6: the records name ids, status, times and a count only; the actor is an id or the
    reaper's system label, and no source address is written."""
    scheduled, reaped = _Db(), _Db(("disabled", _DUE_AT, None))
    await _schedule(scheduled)
    assert await _store(reaped).anonymise(_UID) is not None
    for record in (*scheduled.records, *reaped.records):
        assert set(record["before_state"]) | set(record["after_state"] or {}) <= _STATE_KEYS
        assert "actor_ip" not in record and "object_label" not in record
    assert scheduled.records[0]["actor_label"] == str(_ACTOR)
    assert reaped.records[0]["actor_label"] == "system:user-purge"


# --- the reaper's reads and writes (S13) ------------------------------------------------------


async def test_due_reads_one_bounded_batch_of_expired_purges() -> None:
    """UL4-T2: only a disabled user whose `purge_after` has passed and who is not anonymised yet,
    oldest first, at most `limit`, from the start; ids come back as plain `uuid.UUID`s."""
    a, b = uuid.uuid4(), uuid.uuid4()
    db = _Db(due=(a, b))
    assert await _store(db).due(m.MAX_ANONYMISE_BATCH) == (
        purge.DuePurge(_DUE_AT, a),
        purge.DuePurge(_DUE_AT, b),
    )
    first = {"now": _NOW, "limit": m.MAX_ANONYMISE_BATCH, "after_at": None, "after_id": None}
    assert db.params(m._DUE) == [first]
    sql = " ".join(str(m._DUE).split())
    for clause in ("status = 'disabled'", "anonymised_at IS NULL", "purge_after <= :now"):
        assert clause in sql
    assert sql.endswith("ORDER BY purge_after, id LIMIT :limit")
    assert all(type(d.user_id) is uuid.UUID for d in await _store(db).due(1))


async def test_due_reads_on_after_the_last_user_of_the_previous_batch() -> None:
    """The keyset: the next read starts strictly after the last user it was given, in the batch
    order (`purge_after`, then the id), so a run never reads a user twice, whether it was
    anonymised, skipped or failed."""
    db, last = _Db(due=()), purge.DuePurge(_DUE_AT, uuid.uuid4())
    assert await _store(db).due(3, after=last) == ()
    after = {"now": _NOW, "limit": 3, "after_at": _DUE_AT, "after_id": str(last.user_id)}
    assert db.params(m._DUE) == [after]
    sql = " ".join(str(m._DUE).split())
    assert "(CAST(:after_id AS uuid) IS NULL OR (purge_after, id) > (" in sql


@pytest.mark.parametrize("limit", [0, -1, m.MAX_ANONYMISE_BATCH + 1])
async def test_due_refuses_an_unbounded_or_empty_batch(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        await _store(_Db()).due(limit)


async def test_anonymise_writes_the_surrogate_and_nulls_pii_with_users_anonymise_ahead() -> None:
    """O6, R5: under the user-row lock, the re-check, the surrogate, the nulls and the unusable
    password, every live session revoked, every session's PII nulled, every MFA method and
    recovery code deleted, the deferred constraints, `users.anonymise`, then the commit: one
    transaction (orchestrator ruling, 2026-10-20)."""
    live = sorted((uuid.uuid4(), uuid.uuid4()))
    db = _Db(("disabled", _DUE_AT, None), sessions=3, live=live, mfa=2, codes=8)
    done = await _store(db).anonymise(_UID)
    assert done == purge.Anonymised(_UID, _NOW, tuple(live))
    assert all(type(i) is uuid.UUID for i in done.revoked_session_ids)
    assert db.order() == [
        m._LOCK_TIMEOUT,
        m._LOCK_FOR_ANONYMISE,
        m._ANONYMISE,
        m._REVOKE_SESSIONS,
        m._SCRUB_SESSIONS,
        m._DROP_MFA,
        m._DROP_RECOVERY,
        CONSTRAINTS_NOW,
        "AUDIT users.anonymise success",
        "COMMIT",
    ]
    surrogate = _reference(_UID)
    ((params),) = db.params(m._ANONYMISE)
    unusable = params.pop("unusable")
    assert params == {
        "id": str(_UID),
        "username": surrogate,
        "email": f"{surrogate}@deleted.invalid",
        "now": _NOW,
    }
    assert _UNUSABLE.fullmatch(unusable)
    sql = " ".join(str(m._ANONYMISE).split())
    assert (
        "display_name = NULL, last_login_ip = NULL, password_hash = :unusable, "
        "anonymised_at = :now" in sql
    )
    ended = {"id": str(_UID), "now": _NOW, "reason": "user_disabled"}
    assert db.params(m._REVOKE_SESSIONS) == [ended]
    revoke = " ".join(str(m._REVOKE_SESSIONS).split())
    assert "SET revoked_at = :now, revoked_reason = :reason" in revoke
    assert "WHERE user_id = CAST(:id AS uuid) AND revoked_at IS NULL" in revoke  # the live ones
    scrub = " ".join(str(m._SCRUB_SESSIONS).split())
    assert "SET ip = NULL, user_agent = NULL, device_label = NULL, tailscale_node = NULL" in scrub
    assert "WHERE user_id = CAST(:id AS uuid)" in scrub  # every session of the user, live or not
    dropped = (
        (m._DROP_MFA, "DELETE FROM mfa_methods WHERE user_id = CAST(:id AS uuid)"),
        (m._DROP_RECOVERY, "DELETE FROM recovery_codes WHERE user_id = CAST(:id AS uuid)"),
    )
    for stmt, sql in dropped:
        assert sql in str(stmt) and db.params(stmt) == [{"id": str(_UID)}]
    (record,) = db.records
    assert record == {
        "action": "users.anonymise",
        "actor_label": "system:user-purge",
        "actor_user_id": None,
        "session_id": None,
        "request_id": None,
        "object_kind": "user",
        "object_id": str(_UID),
        "outcome": "success",
        "severity": "warning",
        "reason": None,
        "before_state": {
            "status": "disabled",
            "purge_after": _DUE_AT.isoformat(),
            "anonymised_at": None,
        },
        "after_state": {
            "status": "disabled",
            "purge_after": _DUE_AT.isoformat(),
            "anonymised_at": _NOW.isoformat(),
            "sessions_scrubbed": 3,
            "credentials_revoked": True,
            "sessions_revoked": 2,
            "mfa_methods_deleted": 2,
            "recovery_rows_deleted": 8,
        },
    }
    # The writer's redaction keeps every key and value: none is secret-shaped, and none is a value
    # of a credential (counts and a flag), so the record states the revocation as it happened.
    assert redact(record["after_state"]) == record["after_state"]
    assert unusable not in repr(db.records)


@pytest.mark.parametrize(
    "row",
    [
        ("active", _DUE_AT, None),
        ("disabled", None, None),
        ("disabled", _NOW + timedelta(seconds=1), None),
        ("disabled", _DUE_AT, _DUE_AT),
        None,
    ],
    ids=["re-enabled", "cancelled", "not-due", "already-anonymised", "gone"],
)
async def test_reenable_racing_reaper_keeps_user(row: tuple[Any, ...] | None) -> None:
    """UL-F5, UL-AC13: the batch read is not trusted. Under the user-row lock the reaper re-reads
    the status and the dates; a user re-enabled (or whose purge was cancelled, is not due, or was
    anonymised by another run) since the read is left as it is: no write, no credential revoked,
    no record."""
    db = _Db(row, live=(uuid.uuid4(),))
    assert await _store(db).anonymise(_UID) is None
    assert db.order() == [m._LOCK_TIMEOUT, m._LOCK_FOR_ANONYMISE] and db.records == []


async def test_anonymise_with_audit_down_changes_nothing() -> None:
    db = _Db(("disabled", _DUE_AT, None), audit_error=TimeoutError())
    with pytest.raises(purge.PurgeAuditUnavailableError):
        await _store(db).anonymise(_UID)
    assert "COMMIT" not in db.order() and db.records == []


async def test_anonymise_commit_failure_closes_its_record_as_outcome_unknown() -> None:
    db = _Db(("disabled", _DUE_AT, None), commit_error=TimeoutError("commit lost"))
    with pytest.raises(TimeoutError):
        await _store(db).anonymise(_UID)
    assert [(r["action"], r["outcome"], r["reason"]) for r in db.records] == [
        ("users.anonymise", "success", None),
        ("users.anonymise", "failure", "outcome_unknown"),
    ]


async def test_a_closing_record_that_fails_is_logged_and_the_commit_error_still_leaves() -> None:
    db = _Db(("disabled", _DUE_AT, None), commit_error=OSError("reset"))

    class _OnceOnly:
        async def emit(self, action: str, **fields: Any) -> None:
            if fields["outcome"] == "failure":
                raise RuntimeError("audit writer stopped")
            db.records.append(fields)

    with capture_logs() as logs, pytest.raises(OSError, match="reset"):
        await _store(db, audit=_OnceOnly()).anonymise(_UID)
    assert len(db.records) == 1
    (line,) = [e for e in logs if e["event"] == "user purge closing audit record not written"]
    assert (line["action"], line["log_level"]) == ("users.anonymise", "error")


# --- the cancel (R6, for E42-T09's enable path) -----------------------------------------------


class _Session:
    def __init__(self, pending: datetime | None) -> None:
        self.pending, self.ran = pending, list[Any]()

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        self.ran.append((stmt, params))
        row = (self.pending,) if stmt is m._PENDING and self.pending is not None else None
        return SimpleNamespace(first=lambda: row)


async def test_cancel_pending_purge_clears_it_and_returns_the_cancelled_date() -> None:
    """In the caller's transaction (no commit of its own): the pending date, locked and read, then
    cleared, so the enable's own record can name it."""
    session = _Session(_DUE_AT)
    assert await m.cancel_pending_purge(cast(Any, session), _UID) == _DUE_AT
    assert session.ran == [(m._PENDING, {"id": str(_UID)}), (m._CANCEL, {"id": str(_UID)})]
    pending = " ".join(str(m._PENDING).split())
    assert "purge_after IS NOT NULL AND anonymised_at IS NULL FOR NO KEY UPDATE" in pending


async def test_cancel_is_a_noop_when_no_purge_is_pending_or_it_already_ran() -> None:
    """Nothing pending (never scheduled, cancelled, or run: nothing is restored): no write."""
    session = _Session(None)
    assert await m.cancel_pending_purge(cast(Any, session), _UID) is None
    assert session.ran == [(m._PENDING, {"id": str(_UID)})]


@pytest.mark.parametrize(("mark", "expected"), [(True, True), (False, False), (None, False)])
async def test_anonymised_reads_the_mark_under_the_callers_lock(
    mark: bool | None, expected: bool
) -> None:
    """The enable path's refusal (#2650, second line): one read in the caller's transaction, under
    its lock; `anonymised_at` set is True, unset or no row (deleted under the lock) is False."""

    class _Mark:
        def __init__(self) -> None:
            self.ran = list[Any]()

        async def execute(self, stmt: Any, params: Any = None) -> Any:
            self.ran.append((stmt, params))
            return SimpleNamespace(first=lambda: None if mark is None else (mark,))

    session = _Mark()
    assert await m.anonymised(cast(Any, session), _UID) is expected
    assert session.ran == [(m._ANONYMISED, {"id": str(_UID)})]
    assert "anonymised_at IS NOT NULL" in " ".join(str(m._ANONYMISED).split())
