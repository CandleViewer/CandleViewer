"""E42-T05 BK-1 (#2799): the no-grace gate hands the grant it spent to the handler.

`spend_bound_grant` answers the `SpentGrant` this request used, the one the conditional write
removed from the session row, so a backups handler (link issue, delete, restore) can name the
spent `challenge_id` in its audit record. `require_bound_elevation` is its handler gate, mapped as
`require_elevation_for` is. `consume_bound_grant` still answers None on use (`api.rules_actor`).
Harness: `test_step_up_challenge_router`; the requests are deleteBackup's (BK-12)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.responses import JSONResponse
from structlog.testing import capture_logs

from candleviewer.api.step_up import (
    SpentGrant,
    consume_bound_grant,
    require_bound_elevation,
    require_elevation_for,
    require_session_elevation,
    spend_bound_grant,
)
from candleviewer.api.step_up_challenge import ChallengeText, request_fingerprint
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.step_up import READONLY_WINDOW, StepUpChallenge
from tests.unit.api.test_step_up_challenge_router import _World, _world

#: deleteBackup's binding (`DELETE`, its target, no body) for the held request and another one.
_HELD, _OTHER = (
    request_fingerprint("DELETE", f"/admin/backups/{uuid.UUID(int=n)}".encode(), None)
    for n in (1, 2)
)
_TEXT = ChallengeText(f"Delete the artefact of backup {uuid.UUID(int=1)} (pg_dump)")


def _problem(answer: object, status: int) -> dict[str, Any]:
    assert isinstance(answer, JSONResponse) and answer.status_code == status
    body: dict[str, Any] = json.loads(bytes(answer.body))
    return body


async def _gate(
    w: _World, fingerprint: str, text: ChallengeText | None = None
) -> JSONResponse | SpentGrant:
    sid = w.sessions["tok"].id
    return await require_bound_elevation(
        w.auth, sid, "backups", fingerprint=fingerprint, emitter=w.audit, text=text
    )


async def _granted(w: _World, fingerprint: str, action_class: str = "backups") -> StepUpChallenge:
    """Step up for the request `fingerprint` names: the session then holds its one-shot grant."""
    sid = str(w.sessions["tok"].id)
    issued = await spend_bound_grant(w.auth.step_up, w.audit, sid, action_class, fingerprint)
    assert isinstance(issued, StepUpChallenge)
    assert w.step_up(challenge_id=str(issued.challenge_id)).status_code == 200
    return issued


async def test_spend_returns_the_grant_this_request_used(monkeypatch: pytest.MonkeyPatch) -> None:
    w = await _world()
    removed: list[str] = []
    write = w.rows.consume_step_up_key

    async def conditional_write(sid: str, *, key: str, now: datetime) -> SessionRecord | None:
        used = await write(sid, key=key, now=now)
        removed.extend([key] if used is not None else [])
        return used

    monkeypatch.setattr(w.rows, "consume_step_up_key", conditional_write)
    challenge = _problem(await _gate(w, _HELD, _TEXT), 403)
    assert challenge["action_summary"] == _TEXT.action_summary
    assert w.step_up(challenge_id=challenge["challenge_id"]).status_code == 200
    # Another request is challenged afresh: the session's live challenge is no longer the one
    # the grant answered, so a grant read back from the session would name the wrong one.
    assert _problem(await _gate(w, _OTHER), 403)["challenge_id"] != challenge["challenge_id"]
    spent = await _gate(w, _HELD)
    assert isinstance(spent, SpentGrant)
    assert (str(spent.challenge_id), spent.action_class) == (challenge["challenge_id"], "backups")
    assert removed == [f"once:backups:{spent.challenge_id}:{_HELD}"]


async def test_spend_issues_a_challenge_bound_to_this_request_when_none_is_held() -> None:
    w = await _world()
    sid = str(w.sessions["tok"].id)
    issued = await spend_bound_grant(w.auth.step_up, w.audit, sid, "backups", _HELD)
    assert isinstance(issued, StepUpChallenge)
    assert (issued.action_class, issued.fingerprint) == ("backups", _HELD)
    assert await w.auth.step_up.live_challenge(sid) == issued
    (required,) = w.of("auth.step_up_required")
    assert required["object_id"] == str(issued.challenge_id) and not w.of("auth.step_up_mismatch")


async def test_a_grant_bound_to_another_request_is_audited_ahead_and_stays_bound() -> None:
    w = await _world()
    sid = str(w.sessions["tok"].id)
    held = await _granted(w, _HELD)
    before = len(w.audit.calls)
    refused = await spend_bound_grant(w.auth.step_up, w.audit, sid, "backups", _OTHER)
    assert isinstance(refused, StepUpChallenge) and refused.fingerprint == _OTHER
    # The mismatch is recorded before the challenge for this request is issued (C-2.9).
    recorded = [call["action"] for call in w.audit.calls[before:]]
    assert recorded == ["auth.step_up_mismatch", "auth.step_up_required"]
    (mismatch,) = w.of("auth.step_up_mismatch")
    assert mismatch["object_id"] == str(held.challenge_id)
    assert mismatch["after_state"] == {
        "bound_request_sha256": _HELD,
        "refused_request_sha256": _OTHER,
    }
    spent = await spend_bound_grant(w.auth.step_up, w.audit, sid, "backups", _HELD)
    assert isinstance(spent, SpentGrant) and spent.challenge_id == held.challenge_id


async def _read_only(w: _World) -> None:
    until = w.clock.now + READONLY_WINDOW
    sid = str(w.sessions["tok"].id)
    await w.rows.save_step_up_state(sid, elevations={}, failures=3, readonly_until=until)


async def _revoked(w: _World) -> None:
    await w.rows.revoke(str(w.sessions["tok"].id), reason="logout", now=w.clock.now)


async def _audit_down(w: _World) -> None:
    """The session holds a grant bound to another request, and its mismatch record fails."""
    await _granted(w, _HELD)
    w.audit.fail_on = frozenset({"auth.step_up_mismatch"})


@pytest.mark.parametrize(
    ("arrange", "status", "code"),
    [
        (_read_only, 403, "session_read_only"),
        (_revoked, 401, "unauthenticated"),
        (_audit_down, 503, "audit_unavailable"),
    ],
    ids=["read-only", "revoked", "audit-refused"],
)
async def test_require_bound_elevation_maps_read_only_revoked_and_audit_refusal(
    arrange: Callable[[_World], Awaitable[None]], status: int, code: str
) -> None:
    w = await _world()
    await arrange(w)
    issued = len(w.of("auth.step_up_required"))
    bound = _problem(await _gate(w, _OTHER), status)
    sid = str(w.sessions["tok"].id)
    plain = await require_elevation_for(w.auth, sid, "backups", fingerprint=_OTHER, emitter=w.audit)
    assert bound["code"] == code and bound == _problem(plain, status)
    assert len(w.of("auth.step_up_required")) == issued  # no challenge is issued


@pytest.mark.parametrize(
    ("session", "wired", "status", "code"),
    [(False, True, 401, "unauthenticated"), (True, False, 503, "service_unavailable")],
    ids=["no-session", "step-up-not-wired"],
)
async def test_require_bound_elevation_is_401_without_a_session_and_503_unwired(
    session: bool, wired: bool, status: int, code: str
) -> None:
    """As `require_session_elevation`: nothing to challenge, or no service to issue one."""
    w = await _world()
    w.auth.step_up_is_active = wired
    sid = w.sessions["tok"].id if session else None
    bound = await require_bound_elevation(
        w.auth, sid, "backups", fingerprint=_HELD, emitter=w.audit
    )
    plain = await require_session_elevation(w.auth, sid, "backups")
    assert _problem(bound, status)["code"] == code
    assert _problem(bound, status) == _problem(plain, status)
    assert not w.of("auth.step_up_required")


async def test_require_bound_elevation_fails_closed_on_a_class_it_cannot_bind() -> None:
    """A grace class binds no request (its step-up opens a window, never a grant): a defect, not
    a challenge no step-up could answer, raised before any answer so that no 401 or 503 hides it.
    An unregistered class is the logged 500 of `require_elevation_for`."""
    w = await _world()
    sid = w.sessions["tok"].id
    with pytest.raises(TypeError, match="binds no request"):
        await require_bound_elevation(w.auth, sid, "keys", fingerprint=_HELD, emitter=w.audit)
    with capture_logs() as logs:
        bogus = await require_bound_elevation(
            w.auth, sid, "bogus", fingerprint=_HELD, emitter=w.audit
        )
    plain = await require_elevation_for(w.auth, str(sid), "bogus")
    assert _problem(bogus, 500) == _problem(plain, 500)
    assert logs == [
        {"event": "auth.step_up_unregistered_class", "log_level": "error", "action_class": "bogus"}
    ]
    assert not w.of("auth.step_up_required")
    w.auth.step_up_is_active = False
    with pytest.raises(TypeError, match="binds no request"):  # no session, step-up not wired
        await require_bound_elevation(w.auth, None, "keys", fingerprint=_HELD, emitter=w.audit)


async def test_consume_bound_grant_still_returns_none_on_use() -> None:
    """`api.rules_actor`'s gate: None when the bound grant was used, else the challenge. The
    `SpentGrant` of the same class names that grant: its class and its challenge."""
    w = await _world()
    sid, step_up = str(w.sessions["tok"].id), w.auth.step_up
    held = await _granted(w, _HELD, "live_enablement")
    spent = await spend_bound_grant(step_up, w.audit, sid, "live_enablement", _HELD)
    assert isinstance(spent, SpentGrant)
    assert (spent.action_class, spent.challenge_id) == ("live_enablement", held.challenge_id)
    w.clock.now += timedelta(seconds=30)  # the next TOTP step: each code is accepted once
    second = await _granted(w, _HELD, "live_enablement")
    assert await consume_bound_grant(step_up, w.audit, sid, "live_enablement", _HELD) is None
    again = await consume_bound_grant(step_up, w.audit, sid, "live_enablement", _HELD)
    assert isinstance(again, StepUpChallenge) and again.fingerprint == _HELD
    assert again.challenge_id != second.challenge_id  # spent: the re-send is challenged afresh
