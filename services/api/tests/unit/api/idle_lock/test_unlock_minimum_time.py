"""`POST /auth/unlock` (#4664): a refused password returns no sooner than the minimum time after
the check began, and only once everything a wrong password changes is written: the account
failure count, the unlock count, its records and, on the last attempt, the revoke and its
publication. The same single wait for a wrong password, one that locks the account and the
last attempt; a right password is never held. The wait is recorded, never slept (C-13.7).
"""

from __future__ import annotations

import uuid

from candleviewer.auth.login_service import LOCKOUT_THRESHOLD
from candleviewer.auth.session_service import MAX_UNLOCK_ATTEMPTS

from ._world import _PW, _WRONG, World, _bearer, _unlock

Seen = tuple[float, tuple[str, ...], int, int]


def _record_waits(w: World, uid: uuid.UUID) -> list[Seen]:
    """Each wait the route starts: its length and what was written when it began."""
    seen: list[Seen] = []

    async def wait(delay: float) -> None:
        seen.append(
            (delay, tuple(w.audit.writer.actions()), w.failed_logins(uid), len(w.published))
        )

    hold = w.step_up.failure_hold
    hold._sleep = wait
    hold._monotonic = lambda: 0.0  # a clock that stands still: every refusal waits the minimum
    return seen


async def test_unlock_wrong_password_waits_once_after_its_writes(w: World) -> None:
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.lock()
    seen = _record_waits(w, uid)

    r = await _unlock(w, _bearer(minted), _WRONG)

    assert (r.status_code, r.json()["code"]) == (401, "unlock_invalid")
    assert len(seen) == 1
    delay, written, failures, _ = seen[0]
    assert delay == w.step_up.failure_hold.minimum.total_seconds()
    assert (written, failures) == (("auth.unlock_failed",), 1)


async def test_unlock_wrong_password_that_locks_the_account_waits_after_both_records(
    w: World,
) -> None:
    uid = await w.add_user()
    w.users.users[str(uid)] = w.users.users[str(uid)].model_copy(
        update={"failed_login_count": LOCKOUT_THRESHOLD - 1}
    )
    minted = await w.mint(uid)
    w.lock()
    seen = _record_waits(w, uid)

    r = await _unlock(w, _bearer(minted), _WRONG)

    assert (r.status_code, r.json()["code"]) == (401, "unlock_invalid")
    assert [s[1] for s in seen] == [("auth.unlock_failed", "auth.account_locked")]


async def test_unlock_last_wrong_password_waits_after_the_revoke_is_written(w: World) -> None:
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.lock()
    seen = _record_waits(w, uid)

    for _ in range(MAX_UNLOCK_ATTEMPTS):
        last = await _unlock(w, _bearer(minted), _WRONG)

    assert (last.status_code, last.json()["code"]) == (401, "session_revoked")
    assert len(seen) == MAX_UNLOCK_ATTEMPTS  # one wait per refusal, never two
    _, written, _, published = seen[-1]
    assert written[-1] == "auth.session_revoked"
    assert published == 1


async def test_unlock_with_the_right_password_is_never_held(w: World) -> None:
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.lock()
    seen = _record_waits(w, uid)

    r = await _unlock(w, _bearer(minted), _PW)

    assert r.status_code == 200, r.text
    assert seen == []
