"""Integration: SQL user/MFA repositories against real Postgres 16 (QA #1658).

Covers lockout after N failures, challenge round trip, replay guard and
single-use recovery codes, and (#2748) that a refused write leaves without the row's values
(C-12.6). Not run locally (no docker); exercised by CI.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa

from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MfaChallengeRecord, MfaMethodRecord, UserRecord
from candleviewer.storage.repositories.mfa_sqlalchemy import SqlAlchemyMfaRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    constraint_of,
    sqlstate_of,
)
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserRepository
from scripts.seed_fixture_user import seed
from tests.integration import _refused
from tests.integration._refused import assert_no_row_values, seed_user, server_text

pytestmark = pytest.mark.integration
pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16 at head, on loopback
# Track real time: rows carry DB-stamped `created_at` (now()) and CHECKs such as
# `expires_at > created_at` make a frozen date a time bomb once the wall clock passes it.
_NOW = datetime.now(UTC).replace(microsecond=0)
# Planted by name (a traceback prints the calling line): the P1 columns of a users row, the S hash
# `users_pwd_argon` refuses, and a challenge's S nonce (under 31 bytes: its hex fits DETAIL's cut).
_USER = {"email": "secret-mail@x.invalid", "display_name": "SECRET-NOTE name"}
_PLAIN = "plain-SECRET-HASH"
_TOKEN, _PURPOSE = "SECRET-MFA-TOKEN", "SECRET-purpose"
_TYPED = (None, True)  # `(__cause__, __suppress_context__)` of a stripped driver error


def _rec(model: Any) -> Callable[..., Any]:
    return lambda **f: model.model_validate(f)


async def _login_challenge(mfa: SqlAlchemyMfaRepository, uid: str) -> str:
    """The id of a new, open login challenge of *uid*."""
    challenge = await mfa.create_challenge(
        uid,
        purpose="login",
        mfa_token_hash="rc" + uuid.uuid4().hex,
        expires_at=_NOW + timedelta(minutes=5),
    )
    return str(challenge.id)


async def _rows(rel: SqlAlchemyRelationalRepository, statement: str, **params: str) -> list[Any]:
    """The rows of the static *statement*, run in its own committed unit of work."""
    async with rel.unit_of_work() as uow:
        rows = (await uow.session.execute(sa.text(statement), params)).all()
        await uow.commit()
    return list(rows)


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
        # Confirmed the one way production confirms (#2295): accepted at step 9, no codes.
        confirmed = await mfa.complete_enrollment(
            uid, method_id=str(method.id), time_step=9, now=_NOW, code_hashes=()
        )
        assert confirmed is not None and confirmed.last_accepted_time_step == 9
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
        fresh = await _login_challenge(mfa, uid)
        assert await mfa.complete_recovery(uid, challenge_id=fresh, code_id=cid, now=_NOW) is True
        assert await mfa.complete_recovery(uid, challenge_id=fresh, code_id=cid, now=_NOW) is False
        assert await mfa.count_unused_recovery_codes(uid) == 0
    finally:
        await rel.dispose()


async def test_enrolment_completes_in_one_transaction_and_only_the_latest_method(
    pg_dsn: str,
) -> None:
    """#2295 (Q8, Q9): a method a recovery sign-in revoked (#2344) never confirms again; a new
    enrolment supersedes the pending one; completion confirms, revokes the other TOTP methods and
    swaps the codes in one transaction; a second completion changes nothing, and neither does one
    for a user disabled since (#2911: `False`, read under the user-row lock)."""
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
        spent = await mfa.find_unused_recovery_code(uid, code_hash=old_codes[0])
        assert spent is not None
        challenge = await _login_challenge(mfa, uid)
        assert await mfa.complete_recovery(uid, challenge_id=challenge, code_id=spent, now=_NOW)
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

        pending = await mfa.create_pending_method(uid, secret_enc=b"3", **ref, label="")
        disable = "UPDATE users SET status = 'disabled' WHERE id = CAST(:u AS uuid) RETURNING id"
        await _rows(rel, disable, u=uid)
        refused = await mfa.complete_enrollment(
            uid, method_id=str(pending.id), time_step=4, now=_NOW, code_hashes=("c" * 64,)
        )
        assert refused is False
        assert await mfa.find_pending_method(str(pending.id), uid) is not None
        assert await mfa.find_unused_recovery_code(uid, code_hash=new_codes[0]) is not None
    finally:
        await rel.dispose()


async def test_recovery_spends_once_revokes_every_method_and_rolls_back_a_lost_race(
    pg_dsn: str,
) -> None:
    """#2344, one transaction: the code is spent and its challenge satisfied at most once, only
    as the user's own, and every method of the user is revoked with them, with one
    `security.mfa_recovery_used` system event; a lost race (a spent code, a satisfied challenge,
    another user's code) changes nothing, and neither does the user's disable (#2911)."""
    await seed(pg_dsn, "dave", "correct horse battery")
    await seed(pg_dsn, "erin", "correct horse battery")
    rel = SqlAlchemyRelationalRepository(pg_dsn)
    users = SqlAlchemyUserRepository(rel, _rec(UserRecord), clock=lambda: _NOW)
    mfa = SqlAlchemyMfaRepository(rel, _rec(MfaMethodRecord), _rec(MfaChallengeRecord))
    try:
        uid = str((await users.find_by_identifier("dave")).id)
        erin = str((await users.find_by_identifier("erin")).id)
        ref = {"secret_key_ref": "k"}
        method = await mfa.create_pending_method(uid, secret_enc=b"0", **ref, label="")
        codes = ("d" * 64, "e" * 64)
        assert await mfa.complete_enrollment(
            uid, method_id=str(method.id), time_step=1, now=_NOW, code_hashes=codes
        )
        await mfa.replace_recovery_codes(erin, code_hashes=("f" * 64,))
        first, second = await _login_challenge(mfa, uid), await _login_challenge(mfa, uid)
        code = await mfa.find_unused_recovery_code(uid, code_hash=codes[0])
        other = await mfa.find_unused_recovery_code(uid, code_hash=codes[1])
        foreign = await mfa.find_unused_recovery_code(erin, code_hash="f" * 64)
        assert code is not None and other is not None and foreign is not None

        assert await mfa.complete_recovery(uid, challenge_id=first, code_id=code, now=_NOW)

        assert await mfa.find_active_methods(uid) == ()
        assert await mfa.find_pending_method(str(method.id), uid) is None
        for challenge_id, code_id in ((second, code), (first, other), (second, foreign)):
            lost = await mfa.complete_recovery(
                uid, challenge_id=challenge_id, code_id=code_id, now=_NOW
            )
            assert lost is False, (challenge_id, code_id)
        assert await mfa.count_unused_recovery_codes(uid) == 1
        assert await mfa.count_unused_recovery_codes(erin) == 1
        assert await mfa.satisfy_challenge(second, now=_NOW) is True  # still open
        events = await _rows(
            rel,
            "SELECT details->>'challenge_id' AS c FROM system_events WHERE component = 'auth' "
            "AND kind = 'security.mfa_recovery_used' AND details->>'user_id' = :u",
            u=uid,
        )
        assert [row.c for row in events] == [first]

        disable = "UPDATE users SET status = 'disabled' WHERE id = CAST(:u AS uuid) RETURNING id"
        await _rows(rel, disable, u=uid)
        third = await _login_challenge(mfa, uid)
        assert await mfa.complete_recovery(uid, challenge_id=third, code_id=other, now=_NOW) is None
        assert await mfa.count_unused_recovery_codes(uid) == 1
        assert await mfa.satisfy_challenge(third, now=_NOW) is True  # still open
    finally:
        await rel.dispose()


@pytest_asyncio.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    rel = SqlAlchemyRelationalRepository(pg_dsn, "auth-refused-it")
    try:
        yield rel
    finally:
        await rel.dispose()


async def test_a_rehash_to_a_non_argon_hash_leaves_without_the_users_row(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str
) -> None:
    uid = seed_user(pg_dsn, **_USER)
    users = SqlAlchemyUserRepository(rel, _rec(UserRecord), clock=lambda: _NOW)
    with server_text(rel) as seen, pytest.raises(sa.exc.IntegrityError) as err:
        await users.rehash_password(uid, password_hash=_PLAIN, algo_params={"m": 1})
    assert (sqlstate_of(err.value), constraint_of(err.value)) == ("23514", "users_pwd_argon")
    assert (err.value.__cause__, err.value.__suppress_context__) == _TYPED
    assert_no_row_values(err.value, seen, _PLAIN, *_USER.values())  # untouched columns too


async def test_a_challenge_of_an_unknown_purpose_leaves_without_its_nonce(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str
) -> None:
    uid, exp = seed_user(pg_dsn), _NOW + timedelta(minutes=5)
    mfa = SqlAlchemyMfaRepository(rel, _rec(MfaMethodRecord), _rec(MfaChallengeRecord))
    with server_text(rel) as seen, pytest.raises(sa.exc.IntegrityError) as err:
        await mfa.create_challenge(uid, purpose=_PURPOSE, mfa_token_hash=_TOKEN, expires_at=exp)
    assert (sqlstate_of(err.value), constraint_of(err.value)) == ("23514", "mfa_ch_purpose")
    assert (err.value.__cause__, err.value.__suppress_context__) == _TYPED
    assert_no_row_values(err.value, seen, _PURPOSE, _TOKEN.encode())  # the nonce, as `\x<hex>`
