"""Integration (E42-T10 #2650): the deferred PII purge on real Postgres 16.

The schedule behind `DELETE /users/{userId}?purge=true` and the reaper run on a fake clock, with an
audit stand-in that appends each record to `audit_log` (as the writer's drain appends it) after it
reads, on a connection of its own, the user row the record names: that read shows whether the
change was still uncommitted when its record was written (R5, write-ahead). Covered: AC2 (the
history stays under the surrogate and every audit row about the user is byte-identical), only an
expired purge runs, every session's PII is nulled, every credential revoked in the same
transaction (the orchestrator's acceptance addition), a batch is bounded, a row that keeps failing
holds back no later user, the re-enable's cancel (R6) and the reaper's locked re-check (UL-F5),
and a Manager's or a Viewer's `?purge=true` refused and audited with nothing changed.
testcontainers: CI `integration` runs it.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from structlog.testing import capture_logs
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.user_disable import UserDisableService
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.users import make_users_router
from candleviewer.auth.hashing import Hasher
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_lifecycle import UserStatusChange
from candleviewer.storage.repositories.user_lifecycle_sqlalchemy import (
    SqlAlchemyUserLifecycleStore,
)
from candleviewer.storage.repositories.user_purge import anonymised_email, surrogate
from candleviewer.storage.repositories.user_purge_sqlalchemy import (
    MAX_ANONYMISE_BATCH,
    SqlAlchemyUserPurgeStore,
    cancel_pending_purge,
)
from candleviewer.storage.retention.users_purge_tasks import UsersPurgeTask
from tests.integration.admin.test_user_lifecycle_pg import _ACCOUNT, _GRANT, _ROLE, _floor
from tests.unit.api.test_users_delete import _Auth, _principal

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_WAIT_S = 30.0  # bounds every wait: a regression fails instead of hanging CI
_T0 = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
_DAY = timedelta(days=1)
_PURGE_AT = _T0 + timedelta(days=90)
_PHRASE = "correct horse battery staple"  # the test user's sign-in phrase, hashed below
# Enum, inet and jsonb parameters go in as text and are cast by Postgres, so no driver codec
# decides how they are sent.
_USER = sa.text(
    "INSERT INTO users (id, email, username, display_name, password_hash, status, last_login_ip) "
    "VALUES (CAST(:id AS uuid), :email, :name, :display, '$argon2id$fixture', "
    "CAST(CAST(:status AS text) AS user_status), CAST(CAST(:ip AS text) AS inet))"
)
_SESSION = sa.text(
    "INSERT INTO sessions (id, user_id, refresh_token_hash, expires_at, revoked_at, "
    "revoked_reason, ip, user_agent, device_label, tailscale_node) VALUES (CAST(:id AS uuid), "
    "CAST(:user AS uuid), :hash, now() + interval '1 day', :revoked_at, :reason, "
    "CAST(CAST(:ip AS text) AS inet), :agent, :device, :node)"
)
#: An audit row about the user as earlier writers left it: `auth.login` keeps the typed identifier
#: and the source address, an invite keeps the username (O6: rows keep the name they were written
#: with).
_HISTORY = sa.text(
    "INSERT INTO audit_log (record_id, actor_user_id, actor_label, actor_ip, action, object_kind, "
    "object_id, object_label, outcome, severity, after_state) VALUES (gen_random_uuid(), "
    "CAST(:actor AS uuid), :label, CAST(CAST(:ip AS text) AS inet), :action, :kind, :object, "
    ":object_label, 'success', 'info', CAST(CAST(:after AS text) AS jsonb))"
)
_RECORD = sa.text(
    "INSERT INTO audit_log (record_id, actor_user_id, actor_label, session_id, action, "
    "object_kind, object_id, outcome, severity, reason, before_state, after_state, request_id) "
    "VALUES (gen_random_uuid(), CAST(:actor AS uuid), :label, CAST(:session AS uuid), :action, "
    ":kind, :object, CAST(CAST(:outcome AS text) AS audit_outcome), "
    "CAST(CAST(:severity AS text) AS severity), :reason, CAST(CAST(:before AS text) AS jsonb), "
    "CAST(CAST(:after AS text) AS jsonb), CAST(:rid AS uuid))"
)
_ABOUT = sa.text(
    "SELECT id, row_to_json(a)::text FROM audit_log a "
    "WHERE actor_user_id = CAST(:id AS uuid) OR object_id = :sid ORDER BY id"
)
_ROW = sa.text(
    "SELECT username::text, email::text, display_name, host(last_login_ip), status::text, "
    "purge_after, anonymised_at FROM users WHERE id = CAST(:id AS uuid)"
)
_SESSIONS = sa.text(
    "SELECT id, host(ip), user_agent, device_label, tailscale_node, revoked_at, revoked_reason, "
    "expires_at FROM sessions WHERE user_id = CAST(:id AS uuid) ORDER BY id"
)
_ATTACHED = sa.text(
    "SELECT (SELECT count(*) FROM user_roles WHERE user_id = CAST(:id AS uuid)), "
    "(SELECT count(*) FROM user_account_access WHERE user_id = CAST(:id AS uuid)), "
    "(SELECT count(*) FROM sessions WHERE user_id = CAST(:id AS uuid))"
)
_SCHEDULE = sa.text(
    "UPDATE users SET status = 'disabled', purge_after = :at WHERE id = CAST(:id AS uuid)"
)
_ENABLE = sa.text("UPDATE users SET status = 'active' WHERE id = CAST(:id AS uuid)")
_LOCK = sa.text("SELECT 1 FROM users WHERE id = CAST(:id AS uuid) FOR NO KEY UPDATE")
_PASSWORD_HASH = sa.text("UPDATE users SET password_hash = :hash WHERE id = CAST(:id AS uuid)")
_MFA = sa.text(
    "INSERT INTO mfa_methods (id, user_id, kind, label, secret_enc, confirmed_at) "
    "VALUES (CAST(:id AS uuid), CAST(:user AS uuid), 'totp', 'phone', :seal, now())"
)
_RECOVERY = sa.text(
    "INSERT INTO recovery_codes (id, user_id, code_hash) "
    "VALUES (CAST(:id AS uuid), CAST(:user AS uuid), CAST(:digest AS text))"
)
#: What a sign-in could use: the password hash, the MFA methods, the recovery codes, the live
#: sessions.
_CREDENTIALS = sa.text(
    "SELECT (SELECT password_hash FROM users WHERE id = CAST(:id AS uuid)), "
    "(SELECT count(*) FROM mfa_methods WHERE user_id = CAST(:id AS uuid)), "
    "(SELECT count(*) FROM recovery_codes WHERE user_id = CAST(:id AS uuid)), "
    "(SELECT count(*) FROM sessions WHERE user_id = CAST(:id AS uuid) AND revoked_at IS NULL)"
)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg"),
            },
            check=True,
        )
        yield dsn


@pytest.fixture
async def db(pg_dsn: str) -> AsyncIterator[tuple[SqlAlchemyRelationalRepository, AsyncEngine]]:
    rel, engine = SqlAlchemyRelationalRepository(pg_dsn), create_async_engine(pg_dsn)
    try:
        yield rel, engine
    finally:
        await rel.dispose()
        await engine.dispose()


@dataclass
class _Clock:
    now: datetime = _T0

    def __call__(self) -> datetime:
        return self.now


class _Audit:
    """The audit writer's stand-in. Before it appends a record it reads, on a connection of its
    own, the row of the user the record names, so `seen` holds what was committed then."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine, self.seen = engine, list[tuple[str, tuple[Any, ...]]]()

    async def emit(self, action: str, **f: Any) -> None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(_ROW, {"id": f["object_id"]})).one()
        self.seen.append((action, tuple(row)))
        params = {
            "actor": None if f.get("actor_user_id") is None else str(f["actor_user_id"]),
            "label": f["actor_label"],
            "session": None if f.get("session_id") is None else str(f["session_id"]),
            "action": action,
            "kind": f["object_kind"],
            "object": f["object_id"],
            "outcome": str(f.get("outcome", "success")),
            "severity": str(f.get("severity", "info")),
            "reason": f.get("reason"),
            "before": None if f.get("before_state") is None else json.dumps(f["before_state"]),
            "after": None if f.get("after_state") is None else json.dumps(f["after_state"]),
            "rid": None if f.get("request_id") is None else str(f["request_id"]),
        }
        async with self.engine.begin() as conn:
            await conn.execute(_RECORD, params)


async def _exec(engine: AsyncEngine, stmt: sa.TextClause, **params: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(stmt, params)


async def _user(engine: AsyncEngine, role: str, status: str = "active") -> uuid.UUID:
    """A user holding `role`, with the PII O6 nulls. The owner-floor trigger refuses a role row
    while no owner is active, so every test creates its acting owner first."""
    uid = uuid.uuid4()
    name = f"u-{uid.hex[:12]}"
    params = {"email": f"{name}@x.invalid", "name": name, "display": f"Display {name}"}
    async with engine.begin() as conn:
        await conn.execute(_USER, {"id": str(uid), **params, "status": status, "ip": "10.0.0.7"})
        await conn.execute(_ROLE, {"id": str(uid), "role": role})
    return uid


async def _session(engine: AsyncEngine, user: uuid.UUID, *, ended: bool = False) -> uuid.UUID:
    sid = uuid.uuid4()
    end = (_T0 - _DAY, "logout") if ended else (None, None)
    await _exec(
        engine, _SESSION, id=str(sid), user=str(user), hash=secrets.token_hex(32),
        revoked_at=end[0], reason=end[1], ip="192.0.2.10", agent="Mozilla/5.0 (fixture)",
        device="desk", node="node-fixture",
    )  # fmt: skip
    return sid


async def _history(engine: AsyncEngine, user: uuid.UUID) -> None:
    """Two audit rows about `user`: its login, by the typed identifier, and its invite."""
    async with engine.connect() as conn:
        name = (await conn.execute(_ROW, {"id": str(user)})).one()[0]
    for action, actor, kind in (
        ("auth.login", str(user), "session"),
        ("users.invited", None, "user"),
    ):
        await _exec(
            engine, _HISTORY, actor=actor, label=name, ip="10.0.0.7", action=action, kind=kind,
            object=str(user), object_label=name, after=json.dumps({"username": name}),
        )  # fmt: skip


async def _read(engine: AsyncEngine, stmt: sa.TextClause, user: uuid.UUID) -> list[Any]:
    async with engine.connect() as conn:
        return [tuple(r) for r in await conn.execute(stmt, {"id": str(user), "sid": str(user)})]


async def _scheduled(engine: AsyncEngine, at: datetime) -> uuid.UUID:
    """A manager disabled and scheduled for `at` directly in SQL (the route is tested apart)."""
    user = await _user(engine, "manager")
    await _exec(engine, _SCHEDULE, id=str(user), at=at)
    return user


def _purge(rel: SqlAlchemyRelationalRepository, audit: Any, clock: _Clock) -> Any:
    return SqlAlchemyUserPurgeStore(rel, audit=audit, clock=clock, audit_timeout_s=_WAIT_S)


class _Sessions:
    """The reaper's `SessionEnder` stand-in: it reads, on a connection of its own, whether the
    session it is asked to end is revoked already, so `ended` shows B16 follows the commit."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine, self.ended = engine, list[tuple[uuid.UUID, datetime, bool]]()

    async def end(self, session_id: uuid.UUID, now: datetime) -> None:
        stmt = sa.text("SELECT revoked_at IS NOT NULL FROM sessions WHERE id = CAST(:id AS uuid)")
        async with self.engine.connect() as conn:
            revoked = (await conn.execute(stmt, {"id": str(session_id)})).scalar_one()
        self.ended.append((session_id, now, revoked))


def _reaper(store: Any, engine: AsyncEngine) -> UsersPurgeTask:
    return UsersPurgeTask(store, sessions=_Sessions(engine))


async def test_history_under_surrogate_after_90d(db: Any) -> None:
    """AC2 (S14, UL-AC12): an Owner disables manager M (the E42-T04 store) and schedules M's purge
    at T0; at T0 + 90 days the reaper runs. M's username is the surrogate and M's email
    `<surrogate>@deleted.invalid`; M's display name, last login IP and every session's IP, user
    agent, device label and Tailscale node are null; every audit row about M from before is
    byte-identical, the new records only append; M's rows stay attached by foreign key."""
    rel, engine = db
    owner = await _user(engine, "owner")
    m = await _user(engine, "manager")
    live, ended = await _session(engine, m), await _session(engine, m, ended=True)
    account = uuid.uuid4()
    await _exec(engine, _ACCOUNT, id=str(account), uid=str(account.int % 10**12), label="ac2")
    await _exec(engine, _GRANT, user=str(m), account=str(account), view=True, trade=True)
    await _history(engine, m)
    before = await _read(engine, _ABOUT, m)
    audit, clock = _Audit(engine), _Clock()

    async def disable_ahead(change: UserStatusChange) -> None:
        await audit.emit(
            "users.disable", actor_label=str(owner), actor_user_id=owner, object_kind="user",
            object_id=str(m), outcome="success", severity="warning",
            before_state={"status": change.before}, after_state={"status": change.after},
        )  # fmt: skip

    lifecycle = SqlAlchemyUserLifecycleStore(rel, owner_floor=_floor, audit_timeout_s=_WAIT_S)
    assert await lifecycle.disable(m, actor=owner, now=_T0, audit=disable_ahead) is not None
    store = _purge(rel, audit, clock)
    scheduled = await store.schedule(m, actor_user_id=owner)
    assert (scheduled.purge_after, scheduled.changed) == (_PURGE_AT, True)
    clock.now = _PURGE_AT - timedelta(seconds=1)  # a second early: nothing runs
    await _reaper(store, engine).run_once()
    assert (await _read(engine, _ROW, m))[0][0] == f"u-{m.hex[:12]}"
    clock.now = _PURGE_AT
    await _reaper(store, engine).run_once()
    name = surrogate(m)
    (row,) = await _read(engine, _ROW, m)
    assert row == (name, anonymised_email(m), None, None, "disabled", _PURGE_AT, _PURGE_AT)
    sessions = await _read(engine, _SESSIONS, m)
    assert sorted(s[0] for s in sessions) == sorted((live, ended))
    assert {s[1:5] for s in sessions} == {(None, None, None, None)}
    after = await _read(engine, _ABOUT, m)
    assert after[: len(before)] == before  # byte-identical: never updated, never deleted
    actions = [json.loads(text)["action"] for _, text in after[len(before) :]]
    assert actions == ["users.disable", "users.delete", "users.anonymise"]
    assert await _read(engine, _ATTACHED, m) == [(1, 1, 2)]  # roles, the soft-revoked grant


async def test_users_delete_ahead(db: Any) -> None:
    """R5, UL4-R1 (S14): when `users.delete` is written, `purge_after` is not committed yet; it is
    once the call returns."""
    rel, engine = db
    owner = await _user(engine, "owner")
    m = await _user(engine, "manager", status="disabled")
    audit = _Audit(engine)
    await _purge(rel, audit, _Clock()).schedule(m, actor_user_id=owner)
    ((action, seen),) = audit.seen
    assert (action, seen[5]) == ("users.delete", None)
    assert (await _read(engine, _ROW, m))[0][5] == _PURGE_AT


async def test_users_anonymise_ahead(db: Any) -> None:
    """R5, UL4-R1 (S13): when `users.anonymise` is written, the user row still holds its own
    name, address and no mark; the commit then writes all of them at once."""
    rel, engine = db
    await _user(engine, "owner")
    m = await _scheduled(engine, _T0 - _DAY)
    original = (await _read(engine, _ROW, m))[0]
    audit = _Audit(engine)
    assert await _purge(rel, audit, _Clock()).anonymise(m) is not None
    ((action, seen),) = audit.seen
    assert (action, seen) == ("users.anonymise", original)
    assert (await _read(engine, _ROW, m))[0][:2] == (surrogate(m), anonymised_email(m))


async def test_only_past_purge_after(db: Any) -> None:
    """UL4-T2: at T0 only a disabled user whose `purge_after` has passed is anonymised; one due
    tomorrow, a disabled user never scheduled and an active user holding a stale date (a re-enable
    whose cancel never ran) are unchanged."""
    rel, engine = db
    await _user(engine, "owner")
    due, later = await _scheduled(engine, _T0 - _DAY), await _scheduled(engine, _T0 + _DAY)
    plain = await _user(engine, "manager", status="disabled")
    stale = await _scheduled(engine, _T0 - _DAY)
    await _exec(engine, _ENABLE, id=str(stale))
    kept = {u: await _read(engine, _ROW, u) for u in (later, plain, stale)}
    await _reaper(_purge(rel, _Audit(engine), _Clock()), engine).run_once()
    assert (await _read(engine, _ROW, due))[0][0] == surrogate(due)
    assert {u: await _read(engine, _ROW, u) for u in kept} == kept


async def test_nulls_session_pii(db: Any) -> None:
    """O6, UL4-I1: every session of the user, live or ended, loses its IP, user agent, device
    label and Tailscale node and keeps the rest, but for a live one's end (revoked at the
    anonymisation's instant, as a disable revokes it); another user's sessions are not touched."""
    rel, engine = db
    await _user(engine, "owner")
    m, other = await _scheduled(engine, _T0 - _DAY), await _user(engine, "manager")
    live = await _session(engine, m)
    await _session(engine, m, ended=True)
    await _session(engine, other)
    before, theirs = await _read(engine, _SESSIONS, m), await _read(engine, _SESSIONS, other)
    assert await _purge(rel, _Audit(engine), _Clock()).anonymise(m) is not None
    after = await _read(engine, _SESSIONS, m)
    ended = {live: (_T0, "user_disabled")}
    assert [s[:1] + (None,) * 4 + ended.get(s[0], s[5:7]) + s[7:] for s in before] == after
    assert await _read(engine, _SESSIONS, other) == theirs


async def test_batch_bounded(db: Any) -> None:
    """UL4-T2: one read returns at most the batch, oldest `purge_after` first; a run takes the
    backlog batch by batch."""
    rel, engine = db
    await _user(engine, "owner")
    users = [await _scheduled(engine, _T0 - _DAY * (i + 1)) for i in range(MAX_ANONYMISE_BATCH + 2)]
    store = _purge(rel, _Audit(engine), _Clock())
    batch = [d.user_id for d in await store.due(MAX_ANONYMISE_BATCH)]
    assert len(batch) == MAX_ANONYMISE_BATCH and users[-1] in batch  # the oldest is in the first
    await _reaper(store, engine).run_once()
    names = [(await _read(engine, _ROW, u))[0][0] for u in users]
    assert names == [surrogate(u) for u in users]


async def test_audit_byte_identical(db: Any) -> None:
    """AC2, UL4-T1 (S13): every audit row about M, as the actor or as the object, is
    byte-identical after the anonymisation (each row as `row_to_json`, in id order, its hash
    columns included); the rows keep the name and the address they were written with (O6), and
    the purge's own record only appends."""
    rel, engine = db
    await _user(engine, "owner")
    m = await _scheduled(engine, _T0 - _DAY)
    await _history(engine, m)
    before = await _read(engine, _ABOUT, m)
    assert len(before) == 2 and all(f"u-{m.hex[:12]}" in text for _, text in before)
    assert await _purge(rel, _Audit(engine), _Clock()).anonymise(m) is not None
    after = await _read(engine, _ABOUT, m)
    assert after[: len(before)] == before
    assert [json.loads(text)["action"] for _, text in after[len(before) :]] == ["users.anonymise"]


class _CredentialsAhead(_Audit):
    """`_Audit`, which also reads what a sign-in could use of the user the record names, on its
    own connection, before it appends: `credentials` shows what was committed then."""

    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(engine)
        self.credentials = list[tuple[Any, ...]]()

    async def emit(self, action: str, **f: Any) -> None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(_CREDENTIALS, {"id": f["object_id"]})).one()
        self.credentials.append(tuple(row))
        await super().emit(action, **f)


async def test_credentials_revoked(db: Any) -> None:
    """The acceptance addition (orchestrator ruling, 2026-10-20). In the anonymisation's own
    transaction M's password hash becomes the no-usable-password value, every MFA method and
    recovery code of M is deleted and M's live session is revoked (an ended one keeps its end), so
    no password, factor or session of M can sign in afterwards. `users.anonymise` is written ahead,
    while all of them still stand, and states the revocation in counts with no secret value; the
    revoked session then ends on B16, after the commit. Another user's credentials are untouched."""
    rel, engine = db
    await _user(engine, "owner")
    m, other = await _scheduled(engine, _T0 - _DAY), await _user(engine, "manager")
    hasher = Hasher("pepper")
    old_hash = await hasher.hash(_PHRASE)
    for user in (m, other):
        await _exec(engine, _PASSWORD_HASH, id=str(user), hash=old_hash)
        seal = secrets.token_bytes(44)  # stands in for a sealed seed: never opened here
        await _exec(engine, _MFA, id=str(uuid.uuid4()), user=str(user), seal=seal)
        for _ in range(3):
            digest = secrets.token_hex(32)
            await _exec(engine, _RECOVERY, id=str(uuid.uuid4()), user=str(user), digest=digest)
    live, ended = await _session(engine, m), await _session(engine, m, ended=True)
    await _session(engine, other)
    theirs = await _read(engine, _CREDENTIALS, other)
    assert await hasher.verify(old_hash, _PHRASE)  # the phrase signed in before the purge
    audit, sessions = _CredentialsAhead(engine), _Sessions(engine)
    await UsersPurgeTask(_purge(rel, audit, _Clock()), sessions=sessions).run_once()
    assert audit.credentials == [(old_hash, 1, 3, 1)]  # written ahead: all of them still stood
    ((unusable, mfa, codes, still_live),) = await _read(engine, _CREDENTIALS, m)
    assert (mfa, codes, still_live) == (0, 0, 0)
    assert unusable.startswith("$argon2id$") and unusable != old_hash
    assert not await hasher.verify(unusable, _PHRASE)
    ends = {s[0]: s[5:7] for s in await _read(engine, _SESSIONS, m)}
    assert ends == {live: (_T0, "user_disabled"), ended: (_T0 - _DAY, "logout")}
    assert sessions.ended == [(live, _T0, True)]  # B16, once the revoke had committed
    _, text = (await _read(engine, _ABOUT, m))[-1]
    record = json.loads(text)
    assert record["action"] == "users.anonymise"
    assert {k: record["after_state"][k] for k in ("credentials_revoked", "sessions_revoked")} == {
        "credentials_revoked": True,
        "sessions_revoked": 1,
    }
    assert (
        record["after_state"]["mfa_methods_deleted"],
        record["after_state"]["recovery_rows_deleted"],
    ) == (1, 3)
    assert old_hash not in text and unusable not in text  # no secret value in the record
    assert await _read(engine, _CREDENTIALS, other) == theirs


async def test_poisoned_row_skipped(db: Any) -> None:
    """Ruling 4 (UL4-D1): the oldest due user cannot be anonymised on any run, as its surrogate is
    another user's username (the username pattern admits the prefix). The reaper rolls it back,
    counts it by its class and anonymises every later due user in the same run; the poisoned row
    is unchanged, and the next run retries it."""
    rel, engine = db
    await _user(engine, "owner")
    poisoned = await _scheduled(engine, _T0 - 3 * _DAY)
    later = [await _scheduled(engine, _T0 - _DAY) for _ in range(3)]
    name = surrogate(poisoned)
    await _exec(
        engine, _USER, id=str(uuid.uuid4()), email=f"{name}@x.invalid", name=name, display=None,
        status="active", ip=None,
    )  # fmt: skip
    kept = await _read(engine, _ROW, poisoned)
    with capture_logs() as logs:
        await _reaper(_purge(rel, _Audit(engine), _Clock()), engine).run_once()
    assert await _read(engine, _ROW, poisoned) == kept
    names = [(await _read(engine, _ROW, u))[0][0] for u in later]
    assert names == [surrogate(u) for u in later]
    (line,) = [e for e in logs if e["event"] == "users_anonymised"]
    counts = (line["anonymised"], line["failed"], line["errors"], line["outcome"])
    assert counts == (3, 1, {"IntegrityError": 1}, "partial")
    assert str(poisoned) not in repr(logs) and name not in repr(logs)


async def _enable(rel: SqlAlchemyRelationalRepository, user: uuid.UUID) -> datetime | None:
    """E42-T09's enable path as R6 has it call the cancel: in its own transaction, under the
    user-row lock, beside the status change."""
    async with rel.unit_of_work() as uow:
        await uow.session.execute(_LOCK, {"id": str(user)})
        await uow.session.execute(_ENABLE, {"id": str(user)})
        cancelled = await cancel_pending_purge(uow.session, user)
        await uow.commit()
    return cancelled


async def test_reenable_cancels_purge(db: Any) -> None:
    """R6, UL4-E1 (S14): re-enabled before `purge_after`, M's purge is cleared, and the reaper never
    anonymises M, at the old date or after it. A cancel after the purge ran restores nothing."""
    rel, engine = db
    owner = await _user(engine, "owner")
    m = await _user(engine, "manager", status="disabled")
    clock, audit = _Clock(), _Audit(engine)
    store = _purge(rel, audit, clock)
    await store.schedule(m, actor_user_id=owner)
    assert await _enable(rel, m) == _PURGE_AT
    clock.now = _PURGE_AT + _DAY
    assert m not in [d.user_id for d in await store.due(MAX_ANONYMISE_BATCH)]
    assert await store.anonymise(m) is None
    (row,) = await _read(engine, _ROW, m)
    assert row[:2] == (f"u-{m.hex[:12]}", f"u-{m.hex[:12]}@x.invalid") and row[4:] == (
        "active",
        None,
        None,
    )
    gone = await _scheduled(engine, _T0 - _DAY)
    assert await _purge(rel, audit, _Clock()).anonymise(gone) is not None
    assert await _enable(rel, gone) is None  # nothing pending: no write, the mark stays
    assert (await _read(engine, _ROW, gone))[0][5:] == (_T0 - _DAY, _T0)


async def test_reenable_racing_reaper_keeps_user(db: Any) -> None:
    """UL-F5, UL-AC13: the reaper reads M as due, then M is re-enabled before its transaction
    starts; under the user-row lock the re-check sees it, and M stays active and unchanged, with
    no `users.anonymise`."""
    rel, engine = db
    await _user(engine, "owner")
    m = await _scheduled(engine, _T0 - _DAY)
    audit = _Audit(engine)
    store = _purge(rel, audit, _Clock())
    assert m in [d.user_id for d in await store.due(MAX_ANONYMISE_BATCH)]
    assert await _enable(rel, m) == _T0 - _DAY
    kept = await _read(engine, _ROW, m)
    assert await store.anonymise(m) is None
    assert await _read(engine, _ROW, m) == kept and audit.seen == []


def test_forbidden_manager_viewer_audited(pg_dsn: str) -> None:
    """UL4-E1, UL-AC06 (S14): a Manager and a Viewer calling `DELETE /users/{userId}?purge=true`
    over the Postgres stores get 403, each attempt recorded as `rbac.denied` naming the target,
    and M's row is unchanged: still active, nothing scheduled."""
    spec = load_openapi_spec()

    async def seed(dsn: str) -> uuid.UUID:
        engine = create_async_engine(dsn)
        try:
            await _user(engine, "owner")
            return await _user(engine, "manager")
        finally:
            await engine.dispose()

    async def row(dsn: str, user: uuid.UUID) -> list[Any]:
        engine = create_async_engine(dsn)
        try:
            return await _read(engine, _ROW, user)
        finally:
            await engine.dispose()

    m = asyncio.run(seed(pg_dsn))
    before = asyncio.run(row(pg_dsn, m))
    rel = SqlAlchemyRelationalRepository(pg_dsn, "it-purge-route")
    records: list[dict[str, Any]] = []

    class _Recorder:
        async def emit(self, action: str, **fields: Any) -> None:
            records.append({"action": action, **fields})

    unused = cast(Any, SimpleNamespace())  # a refused caller never reaches another port
    disable = UserDisableService(
        SqlAlchemyUserLifecycleStore(rel, owner_floor=_floor), _Recorder(), positions=unused,
        orders=unused, sessions=unused, session_rows=unused, chart=unused,
        publish_revocation=unused, close_user_sockets=unused, invites=unused, rules=unused,
        scope=unused,
    )  # fmt: skip
    statuses: list[int] = []
    for role in ("manager", "viewer"):
        app = FastAPI()
        app.include_router(
            make_users_router(
                None,
                _Recorder(),
                SimpleNamespace(resolve=lambda request, r=role: _principal(r, spec)),
                cast(Any, object()),
                auth=cast(Any, _Auth([])),
                user_disable=disable,
                user_purge=UsersPurgeTask(_purge(rel, _Recorder(), _Clock()), sessions=unused),
            )
        )
        with TestClient(app, headers={"Authorization": "Bearer tok"}) as client:
            statuses.append(client.delete(f"/users/{m}?purge=true").status_code)
            assert client.portal is not None
            client.portal.call(rel.dispose)
    assert statuses == [403, 403]
    assert [(r["action"], r["object_id"]) for r in records] == [("rbac.denied", str(m))] * 2
    assert asyncio.run(row(pg_dsn, m)) == before
