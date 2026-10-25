"""Integration: the bootstrap invite's Owner grant on real Postgres 16 (#4479 slice B, #4492).

Each test gets its own database, cloned from a migrated template (the `_fresh` pattern of
`test_audit_chain_hardening_migration.py`); marked invites are planted by SQL, as no API path can
write one. A lock wait is read from `pg_locks`, never from a timer (DC-13), and the wait case runs
in a database whose default isolation is REPEATABLE READ, so only the activation's own READ
COMMITTED lets it see the Owner committed while it waited (DC-12). The guards' mutants are killed
here: `COUNT_OWNERS`, `BOOTSTRAP_LOCK`, the marker, READ COMMITTED and the write-ahead hook. Not
run locally (no docker); exercised by CI `integration`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
import sqlalchemy as sa
from psycopg import sql

from candleviewer.auth.models import InviteRecord, SessionRecord
from candleviewer.storage.repositories import invites_sqlalchemy as store
from candleviewer.storage.repositories.invites_sqlalchemy import SqlAlchemyInviteRepository
from candleviewer.storage.repositories.owner_floor_sqlalchemy import COUNT_OWNERS
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from tests.integration import _refused

pytestmark = pytest.mark.integration
pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16 at head, on loopback
_TEMPLATE = "bootstrap_redemption_template"
_PH = "$argon2id$v=19$m=65536,t=3,p=4$pending"
_ARGON = {"m": 65536, "t": 3, "p": 4}
_WAITING = (
    "SELECT 1 FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
    "WHERE l.locktype = 'advisory' AND NOT l.granted AND a.datname = current_database()"
)
_EVENT = (
    "SELECT severity::text, details, resolved_at IS NOT NULL, resolved_by::text "
    "FROM system_events WHERE component = 'auth' AND kind = 'owner_bootstrapped'"
)
Audit = Callable[[uuid.UUID, uuid.UUID], Awaitable[None]]


def _sync(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg", "postgresql")


def _database(dsn: str, name: str) -> str:
    return f"{dsn.rsplit('/', 1)[0]}/{name}"


def _clone(dsn: str, name: str, source: str) -> psycopg.Connection[Any]:
    c = psycopg.connect(_database(_sync(dsn), "postgres"), autocommit=True)
    c.execute(
        sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(*map(sql.Identifier, (name, source)))
    )
    return c


@pytest.fixture(scope="module")
def template(pg_dsn: str) -> Iterator[str]:
    """`pg_dsn`'s migrated database, copied once as the template every test clones."""
    _clone(pg_dsn, _TEMPLATE, pg_dsn.rsplit("/", 1)[1]).close()
    yield pg_dsn


def _fresh(dsn: str, *, isolation: str | None = None) -> str:
    name = f"bt_{uuid.uuid4().hex[:12]}"
    with _clone(dsn, name, _TEMPLATE) as c:
        if isolation is not None:
            c.execute(
                sql.SQL("ALTER DATABASE {} SET default_transaction_isolation = {}").format(
                    sql.Identifier(name), sql.Literal(isolation)
                )
            )
    return _database(dsn, name)


def _one(dsn: str, query: str | sql.Composed, params: tuple[Any, ...] = ()) -> Any:
    with psycopg.connect(_sync(dsn), autocommit=True) as c:
        return c.execute(query, params).fetchone()


#: An active Owner in one statement, so the deferred floor trigger sees one at its commit.
_OWNER = (
    "WITH u AS (INSERT INTO users (id, email, username, password_hash, status) VALUES "
    "(%(id)s, %(email)s, %(name)s, '$argon2id$x', 'active') RETURNING id) "
    "INSERT INTO user_roles (user_id, role_id) SELECT u.id, r.id FROM u, roles r "
    "WHERE r.name = 'owner'"
)


def _owner(uid: str) -> dict[str, str]:
    return {"id": uid, "email": f"{uid[:8]}@x.invalid", "name": f"o{uid[:8]}"}


def _seed_owner(dsn: str) -> str:
    uid = str(uuid.uuid4())
    with psycopg.connect(_sync(dsn), autocommit=True) as c:
        c.execute(_OWNER, _owner(uid))
    return uid


def _plant(
    dsn: str, *, inviter: str | None = "self", consumed: bool = True, revoked: bool = False
) -> tuple[uuid.UUID, uuid.UUID]:
    """An `invited` user with no role and its `owner` invite; `inviter="self"` is the marker."""
    uid = _refused.seed_user(_sync(dsn), status="invited")
    iid = str(uuid.uuid4())
    by = uid if inviter == "self" else inviter
    _one(
        dsn,
        "INSERT INTO user_invites (id, user_id, role, token_hash, invited_by, expires_at, "
        "consumed_at, pending_password_hash, revoked_at) VALUES (%s, %s, 'owner', %s, %s, "
        "now() + interval '4 hours', CASE WHEN %s THEN now() END, %s, "
        "CASE WHEN %s THEN now() END) RETURNING 1",
        (iid, uid, uuid.uuid4().hex * 2, by, consumed, _PH, revoked),
    )
    return uuid.UUID(iid), uuid.UUID(uid)


async def _accept(invite_id: uuid.UUID, user_id: uuid.UUID) -> None:
    return None


async def _activate(dsn: str, invite: tuple[uuid.UUID, uuid.UUID], audit: Audit = _accept) -> str:
    rel = SqlAlchemyRelationalRepository(dsn)
    repo = SqlAlchemyInviteRepository(rel, lambda **f: InviteRecord.model_validate(f))
    try:
        return await repo.activate_bootstrap_owner(
            *invite, password_hash=_PH, algo_params=_ARGON, now=datetime.now(UTC), audit=audit
        )
    finally:
        await rel.dispose()


def _owners(dsn: str) -> int:
    return int(_one(dsn, COUNT_OWNERS.text)[0])


# -- scenarios: each returns what the guard under test decides --------------------------------


async def _waits_then_sees_the_new_owner(template: str) -> tuple[str, bool]:
    """A holder takes the bootstrap lock and commits an Owner while the activation waits."""
    dsn = _fresh(template, isolation="repeatable read")
    invite = _plant(dsn)
    async with await psycopg.AsyncConnection.connect(_sync(dsn)) as holder:
        await holder.execute(store.BOOTSTRAP_LOCK.text)
        await holder.execute(_OWNER, _owner(str(uuid.uuid4())))
        task = asyncio.ensure_future(_activate(dsn, invite))
        waited = False
        async with await psycopg.AsyncConnection.connect(_sync(dsn), autocommit=True) as probe:
            async with asyncio.timeout(30):  # bounded: a missed wait fails, it never hangs
                while not task.done() and not waited:
                    waited = bool(await (await probe.execute(_WAITING)).fetchall())
        await holder.commit()
    return await task, waited


async def _unmarked_owner_invite(template: str) -> str:
    dsn = _fresh(template)
    return await _activate(dsn, _plant(dsn, inviter=None))


async def _refused_record(template: str) -> tuple[str, int, Any]:
    dsn = _fresh(template)
    invite = _plant(dsn)

    async def refuse(invite_id: uuid.UUID, user_id: uuid.UUID) -> None:
        raise RuntimeError("audit refused")

    try:
        outcome = await _activate(dsn, invite, refuse)
    except RuntimeError:
        outcome = "refused"
    status = _one(dsn, "SELECT status::text FROM users WHERE id = %s", (str(invite[1]),))[0]
    return outcome, _owners(dsn), (status, _one(dsn, _EVENT))


_EXPECTED: dict[str, Any] = {
    "lock": ("owner_exists", True),
    "marker": "not_bootstrap",
    "write_ahead": ("refused", 0, ("invited", None)),
}
_SCENARIOS: dict[str, Callable[[str], Awaitable[Any]]] = {
    "lock": _waits_then_sees_the_new_owner,
    "marker": _unmarked_owner_invite,
    "write_ahead": _refused_record,
}


@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
async def test_each_guard_decides_as_specified(template: str, scenario: str) -> None:
    assert await _SCENARIOS[scenario](template) == _EXPECTED[scenario]


async def _no_write_ahead(hook: Awaitable[Any], timeout_s: float) -> None:
    hook.close()  # type: ignore[attr-defined]  # the mutant: the record's coroutine never runs


#: `store._BOOTSTRAP_ROW` with its marker replaced by `true`: the mutant that must be killed.
_ROW_MARKER_TRUE = sa.text(
    "SELECT true AS bootstrap, (i.consumed_at IS NOT NULL AND i.revoked_at IS NULL) AS usable, "
    "u.status::text AS status FROM user_invites i JOIN users u ON u.id = i.user_id "
    "AND u.deleted_at IS NULL WHERE i.id = CAST(:iid AS uuid) "
    "AND i.user_id = CAST(:id AS uuid) FOR NO KEY UPDATE OF i, u"
)

_MUTANTS: dict[str, tuple[str, Any, str]] = {
    "count_owners_zero": ("COUNT_OWNERS", sa.text("SELECT 0"), "lock"),
    "no_bootstrap_lock": ("BOOTSTRAP_LOCK", sa.text("SELECT 1"), "lock"),
    "no_read_committed": ("_READ_COMMITTED", sa.text("SELECT 1"), "lock"),
    "marker_true": ("_BOOTSTRAP_ROW", _ROW_MARKER_TRUE, "marker"),
    "no_write_ahead": ("bounded_write_ahead", _no_write_ahead, "write_ahead"),
}


@pytest.mark.parametrize("mutant", sorted(_MUTANTS))
async def test_activation_mutants_are_killed(
    template: str, mutant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, value, scenario = _MUTANTS[mutant]
    monkeypatch.setattr(store, name, value)
    assert await _SCENARIOS[scenario](template) != _EXPECTED[scenario]


# -- the activation, end to end -----------------------------------------------------------------


async def test_bootstrap_invite_activates_the_owner_once_and_resolves_at_first_sign_in(
    template: str,
) -> None:
    dsn = _fresh(template)
    invite = _plant(dsn)
    assert await _activate(dsn, invite) == "activated"
    assert await _activate(dsn, invite) == "not_invited"  # a double confirm: rejected `redeemed`
    uid = str(invite[1])
    assert _owners(dsn) == 1
    row = _one(dsn, "SELECT pending_password_hash FROM user_invites WHERE user_id = %s", (uid,))
    assert row == (None,)
    details = {"invite_id": str(invite[0]), "user_id": uid}
    assert _one(dsn, _EVENT) == ("critical", details, False, None)
    incident = "SELECT severity::text FROM incidents WHERE component = 'auth'"
    assert _one(dsn, incident) == ("critical",)
    rel = SqlAlchemyRelationalRepository(dsn)
    sessions = SqlAlchemySessionRepository(rel, lambda **f: SessionRecord.model_validate(f))
    try:
        for satisfied in (None, datetime.now(UTC)):  # enrolment-only first: not a sign-in
            await sessions.create_session(_session(invite[1], mfa_satisfied_at=satisfied))
            resolved = _one(dsn, _EVENT)[2:]
            assert resolved == ((True, uid) if satisfied else (False, None))
    finally:
        await rel.dispose()


def _session(user_id: uuid.UUID, *, mfa_satisfied_at: datetime | None) -> SessionRecord:
    now = datetime.now(UTC)
    return SessionRecord(
        id=uuid.uuid4(), user_id=user_id, refresh_token_hash=uuid.uuid4().hex * 2,
        access_token_jti=uuid.uuid4(), issued_at=now, last_seen_at=now,
        expires_at=now + timedelta(hours=12), revoked_at=None, revoked_reason=None, ip=None,
        user_agent=None, device_label=None, is_electron=False, mfa_satisfied_at=mfa_satisfied_at,
    )  # fmt: skip


async def test_concurrent_bootstrap_activations_make_one_owner(template: str) -> None:
    dsn = _fresh(template)
    invites = [_plant(dsn), _plant(dsn)]
    got = await asyncio.gather(*(_activate(dsn, i) for i in invites))
    assert (sorted(got), _owners(dsn)) == (["activated", "owner_exists"], 1)


@pytest.mark.parametrize(
    ("inviter", "consumed", "revoked", "expected"),
    [
        ("stale", True, False, "owner_exists"),  # marked, another Owner first: rejected `revoked`
        ("other", True, False, "not_bootstrap"),  # another user's id is not the marker
        ("self", False, False, "not_invited"),  # never consumed
        ("self", True, True, "not_invited"),  # revoked (superseded)
    ],
)
async def test_stale_unmarked_or_unusable_invites_activate_nothing(
    template: str, inviter: str, consumed: bool, revoked: bool, expected: str
) -> None:
    dsn = _fresh(template)
    owner = _seed_owner(dsn) if inviter in ("stale", "other") else None
    by = owner if inviter == "other" else "self"
    invite = _plant(dsn, inviter=by, consumed=consumed, revoked=revoked)
    assert await _activate(dsn, invite) == expected
    status = _one(dsn, "SELECT status::text FROM users WHERE id = %s", (str(invite[1]),))
    assert (status, _one(dsn, _EVENT), _owners(dsn)) == (("invited",), None, int(bool(owner)))


async def test_create_and_reissue_never_write_the_marker(template: str) -> None:
    """DC-07: both API writers name the acting Owner as the inviter, never the invited user."""
    dsn = _fresh(template)
    owner = uuid.UUID(_seed_owner(dsn))
    rel = SqlAlchemyRelationalRepository(dsn)
    repo = SqlAlchemyInviteRepository(rel, lambda **f: InviteRecord.model_validate(f))
    uid, now = uuid.uuid4(), datetime.now(UTC)

    async def ok(user_id: uuid.UUID, role: str) -> None:
        return None

    try:
        assert await repo.create_user_with_invite(
            user_id=uid, invite_id=uuid.uuid4(), email="m@x.invalid", username="marker",
            display_name=None, role="viewer", placeholder_password_hash="$argon2id$x",  # noqa: S106 - placeholder
            invited_by=owner, token_hash="a" * 64, expires_at=now + timedelta(hours=72), audit=ok,
        )  # fmt: skip
        _one(dsn, "UPDATE user_invites SET role = 'owner' RETURNING 1")  # as a legacy row
        reissued = await repo.reissue(
            uid, invite_id=uuid.uuid4(), token_hash="b" * 64, invited_by=owner,
            expires_at=now + timedelta(hours=72), now=now, audit=ok,
        )  # fmt: skip
        assert reissued is not None
    finally:
        await rel.dispose()
    marked = sql.SQL("SELECT count(*) FROM user_invites i WHERE {}").format(
        sql.SQL(store.BOOTSTRAP_MARKER)  # a static fragment of the store, not data
    )
    assert (_one(dsn, marked), _one(dsn, "SELECT count(*) FROM user_invites")) == ((0,), (2,))


async def test_bootstrap_offer_reads_open_stale_and_unmarked(template: str) -> None:
    """DC-09: what `GET /invites/{token}` and the password step read; `stale` is refused there."""
    dsn = _fresh(template)
    marked, unmarked = _plant(dsn, consumed=False), _plant(dsn, inviter=None, consumed=False)
    rel = SqlAlchemyRelationalRepository(dsn)
    repo = SqlAlchemyInviteRepository(rel, lambda **f: InviteRecord.model_validate(f))
    try:
        before = [await repo.bootstrap_offer(i[0]) for i in (marked, unmarked)]
        _seed_owner(dsn)
        after = await repo.bootstrap_offer(marked[0])
    finally:
        await rel.dispose()
    assert (before, after) == (["open", "unmarked"], "stale")


def test_both_bootstrap_statements_carry_the_marker_verbatim() -> None:
    """The statements are whole literals (no splicing); this keeps them in step with the marker,
    and the mutant row with `store._BOOTSTRAP_ROW` but for the marker."""
    for statement in (store._BOOTSTRAP_ROW, store._IS_MARKED):
        assert store.BOOTSTRAP_MARKER in str(statement)
    assert str(_ROW_MARKER_TRUE).replace(
        "true AS bootstrap", f"{store.BOOTSTRAP_MARKER} AS bootstrap"
    ) == str(store._BOOTSTRAP_ROW)
