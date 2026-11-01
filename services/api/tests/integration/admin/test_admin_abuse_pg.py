"""Integration (E42-X03, #1026): the admin abuse cases that need real Postgres 16, through the
deployed app.

- AC-ADM-28: two enabled Owners demote each other at once (`PUT /users/{userId}/roles`), ten
  rounds.
- UL-AC03: an Owner disables the other (`DELETE /users/{userId}`) while the other demotes the
  first, ten rounds.
- UL-AC14: an Owner disables an invited user, who then presents the old invite.

The owner floor (each route's lock and the store's, and `0001`'s trigger) must leave exactly one
winner per round and an enabled Owner after every round. Each round starts from two fresh Owners,
the only enabled ones. A round counts only when the race occurred: both requests authorised before
either committed. Such a loser is refused after its authorisation: by the role route's floor
pre-check, 409 with one `rbac.denied` (`owner_floor`), or (#2593) by its store's re-read of its own
actor, whose owner role or status the winner has just taken, which answers the 403 the route gives
at entry with one `rbac.denied` (`actor_role_revoked`). A loser authorised after the winner's commit
is refused by its re-read role (403) or its revoked session (401) at entry instead; that round
changed nothing on the loser's side, is retried with a new pair, at most `_TRIES` rounds in all, and
is never counted. A single-threaded test would pass against a store with no lock, so both requests
of a round are in flight at once on the app's loop (ticket technical notes).

The app is `create_app()` with every store on the database; only the audit writer is a stand-in,
and the clock is the test's. The sessions carry a live `users` window, as after a completed
step-up (the path guard of SR-025 is not this test's subject). Needs Docker (testcontainers); CI
`integration` runs it.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.invite_service import InviteService
from candleviewer.auth.mfa_service import MfaService
from candleviewer.auth.models import SessionRecord
from candleviewer.settings import Settings
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from tests.integration.admin.test_user_disable_route_pg import _TOTP
from tests.integration.admin.test_user_lifecycle_pg import _ROLE, _USER
from tests.security.auth._stack import INVITE_PW
from tests.security.auth.test_disable_user_drill import _Clock
from tests.security.auth.test_disable_user_e2e import _owner_headers, _settings, deployed

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_ROUNDS = 10
#: Rounds in all, the retried ones included: a race that never interleaves fails, not hangs.
_TRIES = 5 * _ROUNDS
_ORIGIN = "http://testserver"
_OWNERS = sa.text(
    "SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN roles r "
    "ON r.id = ur.role_id WHERE r.name = 'owner' AND u.status = 'active' AND u.deleted_at IS NULL"
)
_UNOWN = sa.text(
    "DELETE FROM user_roles WHERE user_id = CAST(:id AS uuid) "
    "AND role_id = (SELECT id FROM roles WHERE name::text = 'owner')"
)
_STATUS = sa.text("SELECT status FROM users WHERE id = CAST(:id AS uuid)")
#: The change records of the lifecycle routes (UL-AC03): a loser writes none of them.
_CHANGES = frozenset({"users.disable", "roles.grant", "roles.revoke"})
_DEMOTE: dict[str, Any] = {"roles": ["viewer"]}
#: This world deploys no position source, so a disable must acknowledge unknown positions, or
#: every one is a 409 `positions_unknown` before the floor is reached.
_DISABLE = "?acknowledge_unknown_positions=true&purge=false"

Send = tuple[str, dict[str, str], str, dict[str, Any] | None]


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


async def _owners(dsn: str) -> set[uuid.UUID]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            return {row[0] for row in await conn.execute(_OWNERS)}
    finally:
        await engine.dispose()


async def _pair(dsn: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Two new Owners, each with a confirmed TOTP method (a full session, #2295), then made the
    only enabled Owners: every other one loses the role (the floor trigger allows it, as two
    remain)."""
    pair = (uuid.uuid4(), uuid.uuid4())
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            for uid in pair:
                name = f"x03{uid.hex[:12]}"
                await conn.execute(
                    _USER, {"id": str(uid), "email": f"{name}@x.invalid", "name": name}
                )
                await conn.execute(_ROLE, {"id": str(uid), "role": "owner"})
                await conn.execute(_TOTP, {"mid": str(uuid.uuid4()), "id": str(uid)})
        async with engine.begin() as conn:
            for (uid,) in (await conn.execute(_OWNERS)).all():
                if uid not in pair:
                    await conn.execute(_UNOWN, {"id": str(uid)})
    finally:
        await engine.dispose()
    return pair


async def _status(dsn: str, user_id: str) -> str:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            return str((await conn.execute(_STATUS, {"id": user_id})).scalar_one())
    finally:
        await engine.dispose()


async def _race(app: FastAPI, sends: list[Send]) -> list[httpx.Response]:
    """Each (method, headers, target, body), all in flight at once on the app's loop."""
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url=_ORIGIN) as client:
        return await asyncio.gather(
            *(
                client.request(method, target, json=body, headers={"origin": _ORIGIN, **headers})
                for method, headers, target, body in sends
            )
        )


@contextmanager
def _deployed(dsn: str) -> Iterator[tuple[Any, TestClient, SimpleNamespace, list[dict[str, Any]]]]:
    """The deployed app on `dsn`, its client, its world and its audit records."""
    w = SimpleNamespace(clock=_Clock())
    w.clock.now = datetime.now(UTC).replace(microsecond=0)  # one time base with the database's
    settings: Settings = _settings().model_copy(update={"pg_dsn": SecretStr(dsn)})
    relational = SqlAlchemyRelationalRepository(dsn, "it-x03")
    w.repo = SqlAlchemySessionRepository(relational, lambda **f: SessionRecord.model_validate(f))
    with pytest.MonkeyPatch.context() as mp, deployed(mp, settings, w) as (app, client):
        portal = client.portal
        assert portal is not None
        try:
            yield app, client, w, app.state.app_context.audit._writer.records
        finally:
            portal.call(relational.dispose)


def _wire_invites(app: Any, w: SimpleNamespace) -> None:
    """The invite service, as `AuthService.start()` wires it over the app's own stores:
    `create_app()` starts no module supervisor (`main.py`'s lifespan does), so this world wires
    what it uses, as `deployed()` does the sessions and the step-up."""
    auth = app.state.app_context.auth
    mfa, invites = auth._mfa_repository, auth._invite_repository
    assert mfa is not None and invites is not None
    keys = TotpEncryptor(bytes(range(32)))
    mfa_service = MfaService(mfa, keys, recovery_code_key=bytes(range(32, 64)), clock=w.clock)
    pepper = _settings().auth_pepper.get_secret_value()
    auth._invites = InviteService(invites, Hasher(pepper=pepper), mfa_service, clock=w.clock)


def _of(records: list[dict[str, Any]], user: uuid.UUID) -> list[dict[str, Any]]:
    return [r for r in records if str(r.get("actor_user_id")) == str(user)]


def _raced(lost: httpx.Response, denied: list[str], *, floor_denial: list[str]) -> bool:
    """Whether the loser was authorised before the winner's commit, checking its refusal: the
    floor's 409 (`floor_denial` its records), or #2593's refusal at the effect, the entry's 403
    with one `rbac.denied` (`actor_role_revoked`). Else it was refused at entry (401 or 403)."""
    if lost.status_code == 409:
        assert lost.json()["code"] == "conflict", lost.text  # the floor's 409, no other
        assert denied == floor_denial, denied
        return True
    if denied == ["actor_role_revoked"]:
        assert lost.status_code == 403 and lost.json()["code"] == "forbidden", lost.text
        return True
    assert lost.status_code in (401, 403), lost.text  # authorised after the winner's commit
    return False


def _rounds(dsn: str, play: Callable[[uuid.UUID, uuid.UUID], bool]) -> int:
    """Run `play(a, b)` on fresh pairs until `_ROUNDS` of them raced; the number of tries."""
    counted = tries = 0
    while counted < _ROUNDS:
        tries += 1
        assert tries <= _TRIES, f"the race interleaved in {counted} of {_TRIES} rounds"
        a, b = asyncio.run(_pair(dsn))
        counted += 1 if play(a, b) else 0
        assert len(asyncio.run(_owners(dsn))) == 1  # the floor held, raced or not
    return tries


def test_ac_adm_28_mutual_demotions_leave_one_winner_and_an_owner_every_round(
    pg_dsn: str,
) -> None:
    with _deployed(pg_dsn) as (app, client, w, records):
        portal = client.portal
        assert portal is not None

        def play(a: uuid.UUID, b: uuid.UUID) -> bool:
            heads = {u: _owner_headers(app, portal.call, w, str(u)) for u in (a, b)}
            mark = len(records)
            sends: list[Send] = [
                ("PUT", heads[a], f"/users/{b}/roles", _DEMOTE),
                ("PUT", heads[b], f"/users/{a}/roles", _DEMOTE),
            ]
            answers = portal.call(_race, app, sends)
            won = [i for i, r in enumerate(answers) if r.is_success]
            assert len(won) == 1, [(r.status_code, r.text) for r in answers]
            winner, loser = (a, b) if won[0] == 0 else (b, a)
            lost, seen = answers[1 - won[0]], records[mark:]
            demoted = [r["reason"] for r in _of(seen, winner) if r["action"] == "roles.revoke"]
            assert demoted == ["owner"]  # the winner's one change record
            assert not [r for r in _of(seen, loser) if r["action"] in _CHANGES]
            denied = [r["reason"] for r in _of(seen, loser) if r["action"] == "rbac.denied"]
            return _raced(lost, denied, floor_denial=["owner_floor"])

        _rounds(pg_dsn, play)


def test_ul_ac03_a_disable_racing_a_demotion_leaves_one_winner_and_an_owner_every_round(
    pg_dsn: str,
) -> None:
    with _deployed(pg_dsn) as (app, client, w, records):
        portal = client.portal
        assert portal is not None

        def play(a: uuid.UUID, b: uuid.UUID) -> bool:
            """A disables B while B demotes A."""
            heads = {u: _owner_headers(app, portal.call, w, str(u)) for u in (a, b)}
            mark = len(records)
            sends: list[Send] = [
                ("DELETE", heads[a], f"/users/{b}{_DISABLE}", None),
                ("PUT", heads[b], f"/users/{a}/roles", _DEMOTE),
            ]
            disable, demote = portal.call(_race, app, sends)
            answers = [disable, demote]
            assert [r.is_success for r in answers].count(True) == 1, [
                (r.status_code, r.text) for r in answers
            ]
            seen = records[mark:]
            if disable.is_success:  # B is disabled, and its demotion lost
                winner, loser, lost = a, b, demote
                changes = [r["action"] for r in _of(seen, a) if r["action"] in _CHANGES]
                assert changes == ["users.disable"]
            else:  # A is demoted, and its disable lost
                winner, loser, lost = b, a, disable
                changes = [r["reason"] for r in _of(seen, b) if r["action"] == "roles.revoke"]
                assert changes == ["owner"]
            assert not [r for r in _of(seen, loser) if r["action"] in _CHANGES]
            denied = [r["reason"] for r in _of(seen, loser) if r["action"] == "rbac.denied"]
            # A losing demotion's floor writes one `rbac.denied` (owner_floor), a losing
            # disable's none (UL-F13: refused under the lock, unaudited).
            raced = _raced(lost, denied, floor_denial=["owner_floor"] if loser == b else [])
            assert winner in asyncio.run(_owners(pg_dsn))
            return raced

        _rounds(pg_dsn, play)


def test_ul_ac14_a_disabled_invitee_cannot_complete_the_old_invite(pg_dsn: str) -> None:
    with _deployed(pg_dsn) as (app, client, w, records):
        portal = client.portal
        assert portal is not None
        _wire_invites(app, w)
        owner, _ = asyncio.run(_pair(pg_dsn))
        heads = _owner_headers(app, portal.call, w, str(owner))
        invite = {"email": "x03invitee@example.com", "username": "x03invitee", "roles": ["viewer"]}
        created = client.post("/users", headers=heads, json=invite)
        assert created.status_code == 201, created.text
        uid, token = created.json()["id"], str(created.json()["invite_url"]).rsplit("/", 1)[1]
        assert client.get(f"/invites/{token}").status_code == 200  # the link was live
        gone = client.delete(f"/users/{uid}{_DISABLE}", headers=heads)
        assert gone.status_code == 204, gone.text
        confirm = {"method_id": str(uuid.uuid4()), "code": "000000"}
        for method, suffix, body in (
            ("GET", "", None),  # validate
            ("POST", "", {"password": INVITE_PW}),  # redeem: set the password, start enrolment
            ("POST", "/confirm", confirm),  # confirm the enrolment
        ):
            answer = client.request(method, f"/invites/{token}{suffix}", json=body)
            assert answer.status_code == 404, (method, suffix, answer.status_code, answer.text)
        assert asyncio.run(_status(pg_dsn, uid)) == "disabled"  # the user stays disabled
        revoked = [r for r in records if r["action"] == "users.invite_revoked"]
        assert [str(r.get("actor_user_id")) for r in revoked] == [str(owner)]
        assert not [r for r in records if r["action"] == "users.invite_redeemed"]
