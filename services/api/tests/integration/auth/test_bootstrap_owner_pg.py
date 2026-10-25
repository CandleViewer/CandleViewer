"""Integration: the bootstrap Owner's mint on real Postgres 16 (#4479 C1).

One fresh database per test, cloned from a migrated template (as `test_bootstrap_redemption_pg`);
the mint runs through `BootstrapOwnerService` over the real store. A lock wait is read from
`pg_locks`, never from a timer (DC-4479-13), in a database whose default isolation is
REPEATABLE READ (DC-4479-12); the second run is for another email (DC-4479-07). Each guard of
the mint and each open predicate of the supersede and both candidate reads has a mutant killed
here; the eligibility predicate and the role-less insert are pinned by scenario and row asserts.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
import sqlalchemy as sa
from psycopg import sql
from psycopg.errors import CheckViolation

from candleviewer.auth.bootstrap_owner import (
    BootstrapInvite,
    BootstrapOwnerService,
    BootstrapTarget,
    bootstrap_identity,
)
from candleviewer.auth.errors import BootstrapOwnerRefused
from candleviewer.auth.invite_service import hash_token
from candleviewer.settings import Environment
from candleviewer.storage.repositories import bootstrap_owner_sqlalchemy as mint
from candleviewer.storage.repositories.invites_sqlalchemy import (
    BOOTSTRAP_LOCK,
    BOOTSTRAP_MARKER,
    INSERT_INVITE,
)
from candleviewer.storage.repositories.owner_floor_sqlalchemy import COUNT_OWNERS
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration import _refused

pytestmark = pytest.mark.integration
pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16 at head, on loopback
_TEMPLATE = "bootstrap_mint_template"
_NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
_EMAIL = "first.owner@x.invalid"  # its username: `first.owner`
_WAITING = (
    "SELECT 1 FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
    "WHERE l.locktype = 'advisory' AND NOT l.granted AND a.datname = current_database()"
)
#: The bootstrap invites a redemption could still use: open, or consumed with a parked password.
_USABLE_MARKED = sql.SQL(
    "SELECT i.id, i.user_id, i.token_hash, i.expires_at, i.created_at FROM user_invites i "
    "WHERE {} AND i.revoked_at IS NULL "
    "AND (i.consumed_at IS NULL OR i.pending_password_hash IS NOT NULL)"
).format(sql.SQL(BOOTSTRAP_MARKER))  # a static fragment of the store, not data
_COUNTS = (
    "SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM user_roles), "
    "(SELECT count(*) FROM user_invites), (SELECT count(*) FROM user_invites "
    "WHERE revoked_at IS NULL)"
)
#: An active Owner in one statement, so the deferred floor trigger sees one at its commit.
_OWNER = (
    "WITH u AS (INSERT INTO users (id, email, username, password_hash, status) VALUES "
    "(%(id)s, %(email)s, %(name)s, '$argon2id$x', 'active') RETURNING id) "
    "INSERT INTO user_roles (user_id, role_id) SELECT u.id, r.id FROM u, roles r "
    "WHERE r.name = 'owner'"
)
#: An `owner` invite: (id, user, token hash, inviter, consumed?, parked?, parked hash).
_INVITE = (
    "INSERT INTO user_invites (id, user_id, role, token_hash, invited_by, expires_at, "
    "consumed_at, pending_password_hash) VALUES (%s, %s, 'owner', %s, %s, "
    "now() + interval '4 hours', CASE WHEN %s THEN now() END, CASE WHEN %s THEN %s END)"
)
#: The roles the `invited` user `_EMAIL` names holds, by case: (role, expiring).
_ROLES = {
    "viewer": ("viewer", False),
    "manager": ("manager", False),
    "expiring_owner": ("owner", True),
    "owner_grant": ("owner", False),
}


def _sync(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg", "postgresql")


def _sql(dsn: str, query: str | sql.Composed, params: Any = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(_sync(dsn), autocommit=True) as c:
        cursor = c.execute(query, params)
        return cursor.fetchall() if cursor.description else []


def _create(dsn: str, name: str, source: str, isolation: str | None = None) -> None:
    with psycopg.connect(f"{_sync(dsn).rsplit('/', 1)[0]}/postgres", autocommit=True) as c:
        db = sql.Identifier(name)
        c.execute(sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(db, sql.Identifier(source)))
        if isolation is not None:
            alter = sql.SQL("ALTER DATABASE {} SET default_transaction_isolation = {}")
            c.execute(alter.format(db, sql.Literal(isolation)))


@pytest.fixture(scope="module")
def template(pg_dsn: str) -> str:
    """`pg_dsn`'s migrated database, copied once as the template every test clones."""
    _create(pg_dsn, _TEMPLATE, pg_dsn.rsplit("/", 1)[1])
    return pg_dsn


def _fresh(dsn: str, *, isolation: str | None = None) -> str:
    name = f"bm_{uuid.uuid4().hex[:12]}"
    _create(dsn, name, _TEMPLATE, isolation)
    return f"{dsn.rsplit('/', 1)[0]}/{name}"


def _owner() -> dict[str, str]:
    uid = str(uuid.uuid4())
    return {"id": uid, "email": f"{uid[:8]}@x.invalid", "name": f"o{uid[:8]}"}


def _plant(dsn: str, case: str) -> None:
    """What `_EMAIL`, and its username `first.owner`, meet in a fresh database. A role of an
    `invited` user is planted with the floor trigger off for its one transaction: the floor
    refuses any grant while no Owner is active (F1), as when the last Owner's grant lapsed with
    no write (0001's known gap)."""
    if case == "owner_exists":
        _sql(dsn, _OWNER, _owner())
    elif case == "taken_username":
        _refused.seed_user(dsn, username="first.owner")
    elif case in ("active", "disabled", "locked"):
        _refused.seed_user(dsn, email=_EMAIL, status=case)
    elif case != "create":  # `invited`, with no role or the ones `_ROLES` names
        uid = _refused.seed_user(dsn, email=_EMAIL, status="invited")
        if case in _ROLES:
            with psycopg.connect(_sync(dsn)) as c:
                c.execute("SET LOCAL session_replication_role = replica")
                c.execute(
                    "INSERT INTO user_roles (user_id, role_id, expires_at) SELECT %s, id, "
                    "CASE WHEN %s THEN now() + interval '1 day' END FROM roles WHERE name = %s",
                    (uid, _ROLES[case][1], _ROLES[case][0]),
                )


def _plant_invite(
    dsn: str, *, marked: bool, consumed: bool = False, parked: bool = False, user: str = ""
) -> uuid.UUID:
    """An `owner` invite of `user`, else of a new role-less `invited` user: marked (its own
    inviter) or a legacy one (no inviter); `consumed`, with a `parked` password (half redeemed)
    or none (redeemed)."""
    uid, iid = user or _refused.seed_user(dsn, status="invited"), uuid.uuid4()
    by, token_hash = uid if marked else None, uuid.uuid4().hex * 2
    _sql(dsn, _INVITE, (iid, uid, token_hash, by, consumed, parked, "$argon2id$v=19$pending"))
    return iid


@asynccontextmanager
async def _service(dsn: str) -> AsyncIterator[BootstrapOwnerService]:
    rel = SqlAlchemyRelationalRepository(dsn)
    try:
        store = mint.SqlAlchemyBootstrapOwnerRepository(rel)
        yield BootstrapOwnerService(store, environment=Environment.DEMO, clock=lambda: _NOW)
    finally:
        await rel.dispose()


async def _mint(dsn: str, email: str = _EMAIL) -> BootstrapInvite | str:
    """The mint alone (C2 checks first), so each refusal is its own transaction's."""
    identity = bootstrap_identity(email)
    assert identity is not None
    async with _service(dsn) as service:
        try:
            return await service.mint(BootstrapTarget(*identity, None))
        except BootstrapOwnerRefused as refused:
            return refused.reason


def _verdict(answer: object) -> object:
    """A check's or a mint's answer as one value: a refusal, or the user it names (None when the
    user is created)."""
    if isinstance(answer, BootstrapTarget):
        return answer.user_id
    if isinstance(answer, BootstrapInvite):
        return None if answer.created_user else answer.user_id
    return answer


def test_an_invited_owner_grant_cannot_commit_without_an_active_owner(template: str) -> None:
    """F1: the deferred owner floor refuses, at COMMIT, a grant that leaves no active Owner, so
    the mint's user holds no role and only B's activation grants `owner`."""
    dsn, uid = _fresh(template), str(uuid.uuid4())
    with psycopg.connect(_sync(dsn), autocommit=True) as c, pytest.raises(CheckViolation):
        with c.transaction():
            c.execute(
                "INSERT INTO users (id, email, username, password_hash) "
                "VALUES (%s, %s, 'seeded', '$argon2id$x')",
                (uid, _EMAIL),
            )
            c.execute(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT %s, id FROM roles WHERE name = 'owner'",
                (uid,),
            )
    assert _sql(dsn, "SELECT count(*) FROM users WHERE id = %s", (uid,)) == [(0,)]


async def test_mint_creates_the_invited_user_and_one_marked_invite(template: str) -> None:
    dsn = _fresh(template)
    invite = await _mint(dsn)
    assert isinstance(invite, BootstrapInvite)
    assert (invite.created_user, invite.superseded) == (True, 0)
    user = (
        "SELECT username::text, status::text, mfa_required, invited_by, "
        "password_hash LIKE '$argon2id$%%' FROM users WHERE id = %s"
    )
    assert _sql(dsn, user, (invite.user_id,)) == [("first.owner", "invited", True, None, True)]
    assert _sql(dsn, "SELECT count(*) FROM user_roles") == [(0,)]  # F1: no role row
    marked = (invite.invite_id, invite.user_id, hash_token(invite.token))
    assert _sql(dsn, _USABLE_MARKED) == [(*marked, _NOW + timedelta(hours=4), _NOW)]


async def test_mint_reuses_an_invited_user_without_roles(template: str) -> None:
    dsn = _fresh(template)
    uid = uuid.UUID(_refused.seed_user(dsn, email=_EMAIL, status="invited"))
    invite = await _mint(dsn)
    assert isinstance(invite, BootstrapInvite)
    assert (invite.user_id, invite.created_user) == (uid, False)
    assert [row[:2] for row in _sql(dsn, _USABLE_MARKED)] == [(invite.invite_id, uid)]
    assert _sql(dsn, _COUNTS) == [(1, 0, 1, 1)]  # one user, no role, one open invite


@pytest.mark.parametrize(
    "case",
    ["active", "disabled", "locked", "viewer", "manager", "expiring_owner", "taken_username"],
)
async def test_mint_refuses_a_user_that_is_not_a_candidate(template: str, case: str) -> None:
    dsn = _fresh(template)
    _plant(dsn, case)
    before = _sql(dsn, _COUNTS)
    assert (await _mint(dsn), _sql(dsn, _COUNTS)) == ("not_candidate", before)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("create", None),
        ("invited", "user"),
        ("owner_grant", "user"),  # an unexpiring `owner` grant only: still a candidate
        ("owner_exists", "owner_exists"),
        ("viewer", "not_candidate"),
        ("taken_username", "not_candidate"),
    ],
)
async def test_state_read_agrees_with_the_mint(
    template: str, case: str, expected: str | None
) -> None:
    dsn = _fresh(template)
    _plant(dsn, case)
    async with _service(dsn) as service:
        verdict = _verdict(await service.check(_EMAIL))
    assert _verdict(await _mint(dsn)) == verdict
    assert ("user" if isinstance(verdict, uuid.UUID) else verdict) == expected


#: COUNT_OWNERS behind a data-modifying CTE that records the transaction's isolation level. A whole
#: literal: Semgrep's `avoid-sqlalchemy-text` refuses SQL built inside `sa.text`, tests included;
#: the test pins that it still ends with the real count.
_ISOLATION_SPY = sa.text(
    "WITH s AS (INSERT INTO isolation_seen VALUES "
    "(current_setting('transaction_isolation'))) SELECT count(*) FROM user_roles ur JOIN "
    "roles r ON r.id = ur.role_id JOIN users u ON u.id = ur.user_id WHERE r.name = "
    "'owner' AND u.deleted_at IS NULL AND u.status = 'active' AND (ur.expires_at IS NULL "
    "OR ur.expires_at > now())"
)


async def test_mint_runs_read_committed(template: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """DC-4479-12, in a database whose default is REPEATABLE READ: the Owner count, the read that
    must see a commit made while the mint waited, runs READ COMMITTED (the spy keeps the count)."""
    dsn = _fresh(template, isolation="repeatable read")
    _sql(dsn, "CREATE TABLE isolation_seen (level text)")
    assert _ISOLATION_SPY.text.endswith(COUNT_OWNERS.text)  # the spy keeps the count
    monkeypatch.setattr(mint, "COUNT_OWNERS", _ISOLATION_SPY)
    assert isinstance(await _mint(dsn), BootstrapInvite)
    assert _sql(dsn, "SELECT level FROM isolation_seen") == [("read committed",)]


# -- the guards: each scenario returns what the guard under test decides ------------------------


async def _owner_exists(template: str) -> tuple[Any, bool]:
    """An active Owner and a stale marked invite: the mint refuses and writes nothing."""
    dsn = _fresh(template)
    _sql(dsn, _OWNER, _owner())
    _plant_invite(dsn, marked=True)
    before = _sql(dsn, _COUNTS)
    return await _mint(dsn), _sql(dsn, _COUNTS) == before


async def _waits_then_sees_the_new_owner(template: str) -> tuple[Any, bool]:
    """A holder takes the bootstrap lock and commits an Owner while the mint waits for it."""
    dsn = _fresh(template, isolation="repeatable read")
    async with await psycopg.AsyncConnection.connect(_sync(dsn)) as holder:
        await holder.execute(BOOTSTRAP_LOCK.text)  # B's key, whatever a mutant puts in the store
        await holder.execute(_OWNER, _owner())
        task = asyncio.ensure_future(_mint(dsn))
        waited = False
        async with await psycopg.AsyncConnection.connect(_sync(dsn), autocommit=True) as probe:
            async with asyncio.timeout(30):  # bounded: a missed wait fails, it never hangs
                while not task.done() and not waited:
                    waited = bool(await (await probe.execute(_WAITING)).fetchall())
        await holder.commit()
    return await task, waited


async def _second_run_for_another_email(template: str) -> tuple[Any, bool, bool]:
    """DC-4479-07: an earlier run's open invite and a half-redeemed one, for other users, are
    reached only through the supersede's marker arm; an unmarked (legacy) owner invite is not."""
    dsn = _fresh(template)
    await _mint(dsn, "earlier.run@x.invalid")
    _plant_invite(dsn, marked=True, consumed=True, parked=True)
    legacy = _plant_invite(dsn, marked=False)
    second = await _mint(dsn)
    minted = second if isinstance(second, BootstrapInvite) else None
    usable = [row[0] for row in _sql(dsn, _USABLE_MARKED)]
    kept = "SELECT revoked_at IS NULL FROM user_invites WHERE id = %s"
    return (
        minted and minted.superseded,
        minted is not None and usable == [minted.invite_id],  # exactly one usable marked invite
        _sql(dsn, kept, (legacy,)) == [(True,)],
    )


async def _rerun(template: str) -> tuple[Any, ...]:
    """A run for another email, then two for this one: each run revokes only what is still
    usable, so an invite already revoked is neither revoked again nor counted."""
    dsn = _fresh(template)
    await _mint(dsn, "earlier.run@x.invalid")
    runs = [await _mint(dsn) for _ in range(2)]
    return tuple(run.superseded if isinstance(run, BootstrapInvite) else run for run in runs)


async def _redeemed_kept_own_revoked(template: str) -> tuple[Any, bool]:
    """A finished redemption's marked invite (consumed, no parked password) is left alone; the
    reused user's own unmarked open invite is revoked, through the supersede's user arm."""
    dsn = _fresh(template)
    _plant_invite(dsn, marked=True, consumed=True)
    own = _plant_invite(dsn, marked=False, user=_refused.seed_user(dsn, email=_EMAIL))
    minted = await _mint(dsn)
    revoked = _sql(dsn, "SELECT id FROM user_invites WHERE revoked_at IS NOT NULL")
    return minted.superseded if isinstance(minted, BootstrapInvite) else minted, revoked == [(own,)]


async def _soft_deleted_holders(template: str) -> tuple[Any, Any]:
    """Soft-deleted users holding the email and the username are no one: the state read and the
    mint both create the user."""
    dsn = _fresh(template)
    _refused.seed_user(dsn, email=_EMAIL, deleted_at="2026-10-01 00:00:00+00")
    _refused.seed_user(dsn, username="first.owner", deleted_at="2026-10-01 00:00:00+00")
    async with _service(dsn) as service:
        checked = await service.check(_EMAIL)
    return _verdict(checked), _verdict(await _mint(dsn))


_EXPECTED: dict[str, Any] = {
    "owner": ("owner_exists", True),  # refused; nothing written, the stale invite not revoked
    "lock": ("owner_exists", True),  # waited for the lock, then saw the Owner committed meanwhile
    "supersede": (2, True, True),  # both earlier invites revoked, one left, the legacy one kept
    "rerun": (1, 1),  # the earlier run's invite, then the second run's: one each
    "redeemed": (1, True),  # the user's own invite alone
    "deleted": (None, None),  # the state read and the mint both create the user
}
_SCENARIOS: dict[str, Callable[[str], Awaitable[Any]]] = {
    "owner": _owner_exists,
    "lock": _waits_then_sees_the_new_owner,
    "supersede": _second_run_for_another_email,
    "rerun": _rerun,
    "redeemed": _redeemed_kept_own_revoked,
    "deleted": _soft_deleted_holders,
}


async def test_mint_refuses_owner_exists(template: str) -> None:
    assert await _owner_exists(template) == _EXPECTED["owner"]


async def test_mint_waits_for_the_bootstrap_lock(template: str) -> None:
    assert await _waits_then_sees_the_new_owner(template) == _EXPECTED["lock"]


async def test_second_mint_revokes_open_and_half_redeemed_invites(template: str) -> None:
    assert await _second_run_for_another_email(template) == _EXPECTED["supersede"]


@pytest.mark.parametrize("scenario", ["rerun", "redeemed", "deleted"])
async def test_supersede_and_reads_skip_what_is_gone(template: str, scenario: str) -> None:
    assert await _SCENARIOS[scenario](template) == _EXPECTED[scenario]


_USABLE = "AND (i.consumed_at IS NULL OR i.pending_password_hash IS NOT NULL) "
#: Predicates cut out of the store's statements: (statement, the fragment cut, scenario).
_CUTS = {
    "no_marker_arm": ("_SUPERSEDE", f" OR {BOOTSTRAP_MARKER}", "supersede"),
    "no_revoked_filter": ("_SUPERSEDE", "i.revoked_at IS NULL AND ", "rerun"),
    "no_usable_guard": ("_SUPERSEDE", _USABLE, "redeemed"),
    "no_user_arm": ("_SUPERSEDE", "i.user_id = CAST(:id AS uuid) OR ", "redeemed"),
    "locked_read_sees_deleted": ("_LOCK_CANDIDATE", " AND u.deleted_at IS NULL", "deleted"),
    "state_read_sees_deleted": ("_READ_CANDIDATE", " AND u.deleted_at IS NULL", "deleted"),
    "username_sees_deleted": ("_USERNAME_TAKEN", " AND deleted_at IS NULL", "deleted"),
}
#: Each mutant is a whole-literal statement (Semgrep's `avoid-sqlalchemy-text`); the two tests below
#: pin that each is exactly its statement with the named fragment cut, so none can drift.
_CUT_SQL: dict[str, sa.TextClause] = {
    "no_marker_arm": sa.text(
        "UPDATE user_invites i SET revoked_at = :now WHERE i.revoked_at IS NULL AND "
        "(i.consumed_at IS NULL OR i.pending_password_hash IS NOT NULL) AND (i.user_id = "
        "CAST(:id AS uuid)) RETURNING i.id"
    ),
    "no_revoked_filter": sa.text(
        "UPDATE user_invites i SET revoked_at = :now WHERE (i.consumed_at IS NULL OR "
        "i.pending_password_hash IS NOT NULL) AND (i.user_id = CAST(:id AS uuid) OR (i.role = "
        "CAST('owner' AS role_name) AND i.invited_by = i.user_id)) RETURNING i.id"
    ),
    "no_usable_guard": sa.text(
        "UPDATE user_invites i SET revoked_at = :now WHERE i.revoked_at IS NULL AND "
        "(i.user_id = CAST(:id AS uuid) OR (i.role = CAST('owner' AS role_name) AND "
        "i.invited_by = i.user_id)) RETURNING i.id"
    ),
    "no_user_arm": sa.text(
        "UPDATE user_invites i SET revoked_at = :now WHERE i.revoked_at IS NULL AND "
        "(i.consumed_at IS NULL OR i.pending_password_hash IS NOT NULL) AND ((i.role = "
        "CAST('owner' AS role_name) AND i.invited_by = i.user_id)) RETURNING i.id"
    ),
    "locked_read_sees_deleted": sa.text(
        "SELECT u.id::text AS id, (u.status = 'invited' AND NOT EXISTS (SELECT 1 FROM "
        "user_roles ur JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = u.id AND (r.name "
        "<> 'owner' OR ur.expires_at IS NOT NULL))) AS eligible FROM users u WHERE u.email = "
        ":email FOR UPDATE OF u"
    ),
    "state_read_sees_deleted": sa.text(
        "SELECT u.id::text AS id, (u.status = 'invited' AND NOT EXISTS (SELECT 1 FROM "
        "user_roles ur JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = u.id AND (r.name "
        "<> 'owner' OR ur.expires_at IS NOT NULL))) AS eligible FROM users u WHERE u.email = "
        ":email"
    ),
    "username_sees_deleted": sa.text("SELECT 1 FROM users WHERE username = :username LIMIT 1"),
}
_NULL_MARKER = sa.text(
    "INSERT INTO user_invites (id, user_id, role, token_hash, invited_by, expires_at, "
    "created_at) VALUES (CAST(:iid AS uuid), CAST(:id AS uuid), CAST(:role AS role_name), "
    ":th, NULL, :exp, :now)"
)
_MUTANTS: dict[str, tuple[str, sa.TextClause, str]] = {
    "count_owners_zero": ("COUNT_OWNERS", sa.text("SELECT 0"), "owner"),
    "no_bootstrap_lock": ("BOOTSTRAP_LOCK", sa.text("SELECT 1"), "lock"),
    "no_read_committed": ("_READ_COMMITTED", sa.text("SELECT 1"), "lock"),
    "null_marker": ("INSERT_INVITE", _NULL_MARKER, "supersede"),
} | {mutant: (name, _CUT_SQL[mutant], scenario) for mutant, (name, _cut, scenario) in _CUTS.items()}


@pytest.mark.parametrize("mutant", sorted(_CUTS))
def test_each_mutant_is_its_statement_less_the_cut(mutant: str) -> None:
    name, cut, _scenario = _CUTS[mutant]
    statement: str = getattr(mint, name).text
    assert statement.count(cut) == 1
    assert _CUT_SQL[mutant].text == statement.replace(cut, "")


def test_the_null_marker_mutant_is_the_insert_with_a_null_inviter() -> None:
    assert _NULL_MARKER.text == INSERT_INVITE.text.replace("CAST(:by AS uuid)", "NULL")


@pytest.mark.parametrize("mutant", sorted(_MUTANTS))
async def test_mint_mutants_are_killed(
    template: str, mutant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    name, value, scenario = _MUTANTS[mutant]
    assert value.text != getattr(mint, name).text  # each mutant changes the statement
    monkeypatch.setattr(mint, name, value)
    assert await _SCENARIOS[scenario](template) != _EXPECTED[scenario]
