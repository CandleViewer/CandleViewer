"""Integration: SQL user/MFA repositories against real Postgres 16 (QA #1658).

Covers lockout after N failures, challenge round trip, replay guard and
single-use recovery codes. Not run locally (no docker); exercised by CI.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MfaChallengeRecord, MfaMethodRecord, UserRecord
from candleviewer.storage.repositories.mfa_sqlalchemy import SqlAlchemyMfaRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserRepository
from scripts.seed_fixture_user import seed

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
# Track real time: rows carry DB-stamped `created_at` (now()) and CHECKs such as
# `expires_at > created_at` make a frozen date a time bomb once the wall clock passes it.
_NOW = datetime.now(UTC).replace(microsecond=0)


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


def _rec(model: Any) -> Callable[..., Any]:
    return lambda **f: model.model_validate(f)


async def test_login_lockout_and_reset_round_trip(pg_dsn: str) -> None:
    await seed(pg_dsn, "alice", "correct horse battery")
    rel = SqlAlchemyRelationalRepository(pg_dsn)
    users = SqlAlchemyUserRepository(rel, _rec(UserRecord), clock=lambda: _NOW)
    try:
        user = await users.find_by_identifier("ALICE")
        assert user is not None and user.status == "active"
        assert await Hasher(pepper="").verify(user.password_hash, "correct horse battery")
        locked = None
        for _ in range(5):
            locked = await users.record_login_failure(
                str(user.id), lockout_threshold=5, lock_duration=timedelta(minutes=15), now=_NOW
            )
        assert locked == _NOW + timedelta(minutes=15)
        await users.record_login_success(str(user.id))
        again = await users.find_by_identifier("alice")
        assert again is not None and again.failed_login_count == 0 and again.locked_until is None
    finally:
        await rel.dispose()


async def test_mfa_challenge_replay_and_single_use_recovery_code(pg_dsn: str) -> None:
    await seed(pg_dsn, "bob", "correct horse battery")
    rel = SqlAlchemyRelationalRepository(pg_dsn)
    users = SqlAlchemyUserRepository(rel, _rec(UserRecord), clock=lambda: _NOW)
    mfa = SqlAlchemyMfaRepository(rel, _rec(MfaMethodRecord), _rec(MfaChallengeRecord))
    try:
        uid = str((await users.find_by_identifier("bob")).id)
        method = await mfa.create_pending_method(
            uid, secret_enc=b"enc", **{"secret_key_ref": "k"}, label="phone"
        )
        await mfa.confirm_method(str(method.id), now=_NOW)
        assert [m.id for m in await mfa.find_active_totp_methods(uid)] == [method.id]
        assert await mfa.record_time_step(str(method.id), time_step=10) is True
        assert await mfa.record_time_step(str(method.id), time_step=10) is False
        ch = await mfa.create_challenge(
            uid,
            purpose="login",
            mfa_token_hash="abc" + uuid.uuid4().hex,
            expires_at=_NOW + timedelta(minutes=5),
        )
        found = await mfa.find_open_challenge_by_token_hash(ch.mfa_token_hash)
        assert found is not None and found.id == ch.id
        assert await mfa.record_challenge_attempt(str(ch.id)) == 1
        assert await mfa.satisfy_challenge(str(ch.id), now=_NOW) is True
        assert await mfa.satisfy_challenge(str(ch.id), now=_NOW) is False
        h = "a" * 64
        await mfa.replace_recovery_codes(uid, code_hashes=(h,))
        cid = await mfa.find_unused_recovery_code(uid, code_hash=h)
        assert cid is not None
        assert await mfa.consume_recovery_code(cid, now=_NOW) is True
        assert await mfa.consume_recovery_code(cid, now=_NOW) is False
        assert await mfa.count_unused_recovery_codes(uid) == 0
    finally:
        await rel.dispose()


async def test_enrolment_completes_in_one_transaction_and_only_the_latest_method(
    pg_dsn: str,
) -> None:
    """#2295 (Q8, Q9): a method a recovery sign-in un-confirmed never confirms again; a new
    enrolment supersedes the pending one; completion confirms, revokes the other TOTP methods and
    swaps the codes in one transaction; a second completion changes nothing."""
    await seed(pg_dsn, "carol", "correct horse battery", allow_no_mfa=True)
    rel = SqlAlchemyRelationalRepository(pg_dsn)
    users = SqlAlchemyUserRepository(rel, _rec(UserRecord), clock=lambda: _NOW)
    mfa = SqlAlchemyMfaRepository(rel, _rec(MfaMethodRecord), _rec(MfaChallengeRecord))
    ref = {"secret_key_ref": "k"}
    old_codes, new_codes = ("a" * 64,), ("b" * 64,)
    try:
        uid = str((await users.find_by_identifier("carol")).id)
        old = await mfa.create_pending_method(uid, secret_enc=b"0", **ref, label="")
        assert await mfa.complete_enrollment(
            uid, method_id=str(old.id), time_step=1, now=_NOW, code_hashes=old_codes
        )
        await mfa.set_mfa_required_reenroll(uid)  # a recovery sign-in un-confirms it
        assert await mfa.find_pending_method(str(old.id), uid) is None
        first = await mfa.create_pending_method(uid, secret_enc=b"1", **ref, label="")
        await mfa.supersede_pending_methods(uid, now=_NOW)
        new = await mfa.create_pending_method(uid, secret_enc=b"2", **ref, label="")
        assert await mfa.find_pending_method(str(first.id), uid) is None

        got = await mfa.complete_enrollment(
            uid, method_id=str(new.id), time_step=2, now=_NOW, code_hashes=new_codes
        )

        assert got is not None and (got.id, got.last_accepted_time_step) == (new.id, 2)
        assert [m.id for m in await mfa.find_active_totp_methods(uid)] == [new.id]
        assert await mfa.find_unused_recovery_code(uid, code_hash=old_codes[0]) is None
        assert await mfa.find_unused_recovery_code(uid, code_hash=new_codes[0]) is not None
        again = await mfa.complete_enrollment(
            uid, method_id=str(new.id), time_step=3, now=_NOW, code_hashes=("c" * 64,)
        )
        assert again is None
        assert await mfa.find_unused_recovery_code(uid, code_hash=new_codes[0]) is not None
        await users.set_mfa_required(uid)
        carol = await users.find_by_id(uid)
        assert carol is not None and carol.mfa_required is True
    finally:
        await rel.dispose()
