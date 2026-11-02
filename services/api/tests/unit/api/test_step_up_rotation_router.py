"""SR-013 (#2101): a granted step-up rotates the session, at the router (the ruling's C-3 to C-8).

The `200` carries the new session's `tokens` and its rotated cookies, `no-store`, and
`X-CSRF-Token` under the desktop flag; the grants carry over and accumulate; the rotation is
audited after the grant, each record ahead of its change (`auth.session_revoked` through B16
`REVOKE`, then `auth.session_created`); the audit writer's readiness is checked before any
factor; a refused rotation or grant record ends the grant (`503`), and a void row names what it
ends; a lost claim, a failed mint or a failed family link voids the announced session (`401`),
the unlinked one revoked first; a void that is lost too is counted; a grant the claim no longer
holds is echoed and elevates nothing. Over
`test_step_up_router._build`: the real `StepUpService`, `SessionService` and B16 chart on the
in-memory rows.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api.cors import FLAG_STATE_KEY
from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfVerdict
from candleviewer.auth.metrics import normalise_outcome_action
from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.auth.session_chart import SessionChart
from candleviewer.auth.session_service import hash_access_token
from candleviewer.auth.step_up import GRACE_WINDOW
from candleviewer.statechart.gateway import GatewayOverloadedError
from tests.unit.api.test_step_up_challenge_router import _RELEASE
from tests.unit.api.test_step_up_challenge_router import _world as _challenge_world
from tests.unit.api.test_step_up_router import (
    _H,
    _PW,
    CSRF,
    _build,
    _code,
    _modal_body,
    _rotated,
)
from tests.unit.auth.session_fakes import FakeSessionRepository


def _rows(c: TestClient) -> FakeSessionRepository:
    rows: FakeSessionRepository = cast(FastAPI, c.app).state.rows
    return rows


def _chart(c: TestClient) -> SessionChart:
    """The B16 charts of the step-up service (`StepUpService.chart`)."""
    chart: SessionChart = cast(FastAPI, c.app).state.step_up_auth.step_up.chart
    return chart


def _lost() -> float:
    """`auth_audit_outcome_lost_total` under the label a step-up's lost void row counts on."""
    label = {"action": normalise_outcome_action("auth.step_up_failed")}
    return REGISTRY.get_sample_value("auth_audit_outcome_lost_total", label) or 0.0


def _live(c: TestClient, user: uuid.UUID) -> list[SessionRecord]:
    return [s for s in _rows(c).sessions.values() if s.user_id == user and s.revoked_at is None]


def _users_body(seed: bytes, clock: Any) -> dict[str, str]:
    return {"code": _code(seed, clock), "password": _PW, "action_class": "users"}


def _sid(c: TestClient, response: Any) -> str:
    """The session a step-up's new access token names."""
    jti = hash_access_token(response.json()["tokens"]["access_token"])
    (row,) = [s for s in _rows(c).sessions.values() if s.access_token_jti == jti]
    return str(row.id)


async def test_step_up_answers_with_the_rotated_session_its_cookies_and_no_store() -> None:
    c, _em, seed, clock, user = await _build()
    (old,) = _live(c, user)

    ok = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert ok.status_code == 200
    tokens = ok.json()["tokens"]
    assert (tokens["token_type"], tokens["refresh_token"]) == ("Bearer", None)
    assert ok.headers["cache-control"] == "no-store"
    (new,) = _live(c, user)
    assert new.id != old.id and new.id == uuid.UUID(_sid(c, ok))
    assert _rows(c).sessions[str(old.id)].revoked_reason == "rotated"
    csrf = ok.cookies.get(CSRF_COOKIE)
    assert csrf is not None and CSRF.verify(csrf, str(new.id)) is CsrfVerdict.OK
    assert CSRF.verify(csrf, str(old.id)) is not CsrfVerdict.OK  # bound to the new session only
    assert ok.cookies.get("cv_refresh")
    assert CSRF_HEADER not in ok.headers  # the desktop flag is off for this request


async def test_step_up_sends_the_new_csrf_token_in_the_header_under_the_desktop_flag() -> None:
    """C-4 (ADR-0038 F5): with the flag kept on for a listed `Origin`, the eighth issuing
    operation carries the token it set, as refresh does."""
    c, _em, seed, clock, user = await _build()
    app = cast(FastAPI, c.app)

    @app.middleware("http")
    async def listed(request: Request, call_next: Any) -> Response:
        request.scope.setdefault("state", {})[FLAG_STATE_KEY] = True
        response: Response = await call_next(request)
        return response

    ok = TestClient(app).post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert ok.status_code == 200
    assert ok.headers[CSRF_HEADER] == ok.cookies.get(CSRF_COOKIE)
    (new,) = _live(c, user)
    assert CSRF.verify(ok.headers[CSRF_HEADER], str(new.id)) is CsrfVerdict.OK


async def test_step_up_grants_accumulate_across_two_rotations() -> None:
    """C-5: the second step-up's successor holds the first one's window and its own."""
    c, _em, seed, clock, user = await _build()
    keys = c.post(
        "/auth/step-up",
        headers=_H,
        json={"code": _code(seed, clock), "password": _PW, "action_class": "keys"},
    )
    clock.now = clock.now + timedelta(seconds=30)  # the next TOTP step: codes are single-use
    users = c.post("/auth/step-up", headers=_rotated(keys), json=_users_body(seed, clock))

    assert users.status_code == 200
    (new,) = _live(c, user)
    assert {"keys", "users"} <= set(new.step_up_elevations)
    h = _rotated(users)
    assert c.post("/exchange-accounts/a1/keys/k1/rotate", headers=h).status_code == 200
    assert c.post(f"/users/{uuid.uuid4()}/invite", headers=h).status_code == 200


async def test_step_up_rotation_drops_the_pending_challenge() -> None:
    c, _em, seed, clock, user = await _build()
    denied = c.post(f"/users/{uuid.uuid4()}/invite", headers=_H)

    ok = c.post("/auth/step-up", headers=_H, json=_modal_body(_code(seed, clock), denied))

    assert ok.status_code == 200
    (new,) = _live(c, user)
    assert not [k for k in new.step_up_elevations if k.startswith("pending:")]


async def test_step_up_echoes_a_grant_its_claim_no_longer_holds_and_the_next_call_is_challenged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `200` echoes the grant as the step-up made it. A grant the claimed row no longer
    holds (ended between the grant and the claim) is carried nowhere, and the server reads the
    session's row on every elevated request, so the next `users` call is challenged."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    rows, emit = _rows(c), em.emit

    async def ended_before_the_claim(action: str, **kw: Any) -> None:
        await emit(action, **kw)
        if action == "auth.session_created":  # the last record ahead of the claim
            await rows.update_step_up_state(str(old.id), lambda state: ({}, state[1], state[2]))

    monkeypatch.setattr(em, "emit", ended_before_the_claim)

    ok = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert ok.status_code == 200
    until = (clock.now + GRACE_WINDOW).isoformat()
    assert (ok.json()["elevated_until"], ok.json()["step_up_expires_at"]) == (until, until)
    (new,) = _live(c, user)
    assert new.step_up_elevations == {}
    r = c.post(f"/users/{uuid.uuid4()}/invite", headers=_rotated(ok))
    assert (r.status_code, r.json()["code"]) == (403, "step_up_required")


async def test_step_up_audits_the_rotation_after_the_grant_each_record_ahead() -> None:
    """C-7: `auth.step_up_granted`, then `auth.session_revoked` (`rotated`, the old session),
    then `auth.session_created` naming the new session and the old one in `rotated_from`."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)

    ok = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    rows = [
        r
        for r in em.calls
        if r["action"] in ("auth.step_up_granted", "auth.session_revoked", "auth.session_created")
    ]
    assert [r["action"] for r in rows] == [
        "auth.step_up_granted",
        "auth.session_revoked",
        "auth.session_created",
    ]
    granted, revoked, created = rows
    new = _sid(c, ok)
    assert (granted["session_id"], revoked["session_id"]) == (str(old.id), str(old.id))
    assert revoked["reason"] == "rotated"
    assert str(created["session_id"]) == new
    assert created["after_state"] == {"rotated_from": str(old.id)}
    assert created["actor_user_id"] == user  # the cross-user case: the step-up's own user


async def test_step_up_with_the_audit_writer_down_is_503_before_any_factor() -> None:
    """C-7: no factor is checked, so no strike is counted and the code stays unspent."""
    c, em, seed, clock, user = await _build(audit_ok=False)
    code = _code(seed, clock)

    down = c.post("/auth/step-up", headers=_H, json={**_users_body(seed, clock), "code": code})

    assert (down.status_code, down.json()["code"]) == (503, "audit_unavailable")
    assert not em.calls
    (row,) = _live(c, user)
    assert row.step_up_failures == 0 and row.step_up_elevations == {}
    cast(FastAPI, c.app).state.audit_ok = True
    again = c.post("/auth/step-up", headers=_H, json={**_users_body(seed, clock), "code": code})
    assert again.status_code == 200  # the same code: the 503 spent none of it


@pytest.mark.parametrize("refused", ["auth.session_revoked", "auth.session_created"])
async def test_step_up_whose_rotation_record_is_refused_ends_the_grant_and_is_503(
    refused: str,
) -> None:
    """C-7: a rotation record refused after the grant: `503`, nothing elevated or rotated, and
    the old bearer still works, unelevated. One `auth.step_up_failed` row voids what stands
    (C-2.9): the grant, which it names, and the rotation's `auth.session_revoked` once B16 has
    written it (reason `unrotated`; `grant_ended` when the grant is all)."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    em.fail_on = frozenset({refused})

    r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert "tokens" not in r.json()
    assert [s.id for s in _live(c, user)] == [old.id]
    assert "users" not in _rows(c).sessions[str(old.id)].step_up_elevations
    (void,) = [x for x in em.calls if x["action"] == "auth.step_up_failed"]
    ended = {"action_class": "users", "elevated_until": (clock.now + GRACE_WINDOW).isoformat()}
    if refused == "auth.session_created":  # B16 wrote the revocation first: the row voids it
        expected = ("unrotated", {"voids_session_revoked": str(old.id), "grant_ended": ended})
    else:
        expected = ("grant_ended", {"grant_ended": ended})
    assert (void["reason"], void["after_state"]) == expected
    assert (void["session_id"], void["outcome"]) == (old.id, AuditOutcome.FAILURE)
    em.fail_on = frozenset()
    gated = c.post(f"/users/{uuid.uuid4()}/invite", headers=_H)
    assert (gated.status_code, gated.json()["code"]) == (403, "step_up_required")


async def test_step_up_whose_grant_record_is_refused_ends_the_grant_and_is_503() -> None:
    """#2101 (C-7): `auth.step_up_granted` refused once the grant is stored: the grant is ended,
    the chart dropped (rebuilt from the row on its next use), nothing rotated, and `503`, as for
    a refused rotation record. No record stands, so none is voided."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    em.fail_on = frozenset({"auth.step_up_granted"})

    r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert [s.id for s in _live(c, user)] == [old.id]
    assert "users" not in _rows(c).sessions[str(old.id)].step_up_elevations
    assert _chart(c).interpreter(str(old.id)) is None
    assert em.actions() == []
    em.fail_on = frozenset()
    gated = c.post(f"/users/{uuid.uuid4()}/invite", headers=_H)
    assert (gated.status_code, gated.json()["code"]) == (403, "step_up_required")


async def test_step_up_whose_revocation_the_gateway_refuses_is_503_as_a_refused_record() -> None:
    """A full inbox or a degraded chart (`GatewayError`) cannot record the rotation either: as
    for `SessionChartError` (`api/sessions.py` treats the two alike), the chart is dropped, the
    grant ended and voided, and the answer is `503`."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    chart = _chart(c)

    async def full(record: SessionRecord, now: Any, reason: str) -> None:
        raise GatewayOverloadedError(str(record.id), "control")

    chart.revoke = full  # type: ignore[method-assign]  # the gateway refuses B16 `REVOKE`

    r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert [s.id for s in _live(c, user)] == [old.id]
    assert "users" not in _rows(c).sessions[str(old.id)].step_up_elevations
    assert chart.interpreter(str(old.id)) is None  # the grant's chart, dropped
    voids = [x["reason"] for x in em.calls if x["action"] == "auth.step_up_failed"]
    assert voids == ["grant_ended"]


async def test_step_up_whose_grant_is_not_ended_voids_only_the_revocation() -> None:
    """The void names only what is true: a grant the store would not end is left out (its window
    bounds it, and the log names it); the rotation's `auth.session_revoked` is still voided."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    em.fail_on = frozenset({"auth.session_created"})

    async def down(session_id: str, grant: Any) -> None:
        raise OSError("the store is unreachable")

    service = cast(FastAPI, c.app).state.step_up_auth.step_up
    service.end_grant = down  # the grant's end is refused

    with capture_logs() as logs:
        r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert r.status_code == 503
    (void,) = [x for x in em.calls if x["action"] == "auth.step_up_failed"]
    assert (void["reason"], void["after_state"]) == (
        "unrotated",
        {"voids_session_revoked": str(old.id)},
    )
    assert [e["error"] for e in logs if e["event"] == "auth.step_up.grant_not_ended"] == ["OSError"]


async def test_step_up_whose_void_is_refused_too_counts_it_lost() -> None:
    """04-security-program.md section 8.3 rule 2: a void the writer refuses after the answer is
    decided is counted on `auth_audit_outcome_lost_total` (`AuthAuditOutcomeLost`) and logged
    with the session and the error class."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    em.fail_on = frozenset({"auth.session_created", "auth.step_up_failed"})
    before = _lost()

    with capture_logs() as logs:
        r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert _lost() == before + 1
    (line,) = [e for e in logs if e["event"] == "auth.step_up.outcome_lost"]
    assert (line["action"], line["session_id"], line["error"]) == (
        "auth.step_up_failed",
        str(old.id),
        "AuditUnavailable",
    )


async def test_no_grace_step_up_whose_rotation_record_is_refused_ends_its_bound_grant() -> None:
    """A no-grace class's grant is its bound one-shot `once:` key (#2304), not the class key: a
    refused rotation record ends that key, so the held request re-sent is challenged again and
    never runs, and the void names the challenge the grant answered."""
    w = await _challenge_world()
    challenge_id = w.send(_RELEASE).json()["challenge_id"]
    w.audit.fail_on = frozenset({"auth.session_created"})

    r = w.step_up(challenge_id=challenge_id)

    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    row = w.rows.sessions[str(w.sessions["tok"].id)]
    assert not [key for key in row.step_up_elevations if key.startswith("once:")]
    (void,) = w.of("auth.step_up_failed")
    ended = void["after_state"]["grant_ended"]
    assert (ended["action_class"], ended["challenge_id"]) == ("killswitch", challenge_id)
    w.audit.fail_on = frozenset()
    resent = w.send(_RELEASE)
    assert (resent.status_code, resent.json()["code"]) == (403, "step_up_required")
    assert w.executed == []


async def test_step_up_that_loses_the_claim_voids_the_announced_session_and_is_401() -> None:
    """C-8: another request ended the session between the grant and the claim (a refresh, a
    logout): exactly one wins, so the step-up mints nothing and answers `401`."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    rows = _rows(c)
    claim = rows.revoke

    async def raced(session_id: str, *, reason: str, now: Any) -> Any:
        await claim(session_id, reason="logout", now=now)  # the other request won
        return await claim(session_id, reason=reason, now=now)

    rows.revoke = raced  # type: ignore[method-assign]  # one claim, raced by a logout

    r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    assert not _live(c, user)
    (created,) = [x for x in em.calls if x["action"] == "auth.session_created"]
    (void,) = [x for x in em.calls if x["action"] == "auth.step_up_failed"]
    assert void["after_state"] == {
        "voids_session_created": str(created["session_id"]),
        "rotated_from": str(old.id),
    }
    assert void["session_id"] == created["session_id"]


async def test_step_up_whose_mint_is_refused_after_the_claim_voids_and_is_401() -> None:
    """C-7: the user was disabled after the claim: the claim stands, no successor exists."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    _rows(c).user_statuses[str(user)] = UserStatus.DISABLED

    r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    assert _rows(c).sessions[str(old.id)].revoked_reason == "rotated"
    assert len(_rows(c).sessions) == 1
    assert [x["reason"] for x in em.calls if x["action"] == "auth.step_up_failed"] == ["unrotated"]


async def test_step_up_whose_claim_meets_a_store_outage_ends_the_grant_and_is_401() -> None:
    """Whether the claim landed is unknown: the announced session is voided, the grant ended on
    the row the claim may have left live, and the answer is `401`."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    rows = _rows(c)

    async def down(session_id: str, *, reason: str, now: Any) -> Any:
        raise OSError("the store is unreachable")

    rows.revoke = down  # type: ignore[method-assign]  # the claim's store is down

    r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    assert "users" not in rows.sessions[str(old.id)].step_up_elevations
    assert [x["reason"] for x in em.calls if x["action"] == "auth.step_up_failed"] == ["unrotated"]


async def test_step_up_whose_family_link_fails_revokes_the_new_session_so_its_void_holds() -> None:
    """The new session was minted, then could not be linked into the family: it is revoked
    (`rotation_unlinked`) before the void is written, so no live session stands under the
    `auth.session_created` the void cancels; the store is down, so `401`."""
    c, em, seed, clock, user = await _build()
    rows = _rows(c)

    async def down(*, prev_session_id: str, next_session_id: str) -> None:
        raise OSError("the store is unreachable")

    rows.link_rotation = down  # type: ignore[method-assign]  # the link's unit of work fails

    r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    assert not _live(c, user)
    (void,) = [x for x in em.calls if x["action"] == "auth.step_up_failed"]
    unlinked = rows.sessions[void["after_state"]["voids_session_created"]]
    assert unlinked.revoked_reason == "rotation_unlinked"


async def test_step_up_whose_claim_raises_a_defect_voids_ends_the_grant_and_lets_it_raise() -> None:
    """A claim or mint failure that is no store outage is a defect: the void is written and the
    grant ended, and the error propagates (the `500` stands, never a `401`)."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    rows = _rows(c)

    async def defect(session_id: str, *, reason: str, now: Any) -> Any:
        raise ValueError("a defect, not an outage")

    rows.revoke = defect  # type: ignore[method-assign]  # the claim raises a defect

    with pytest.raises(ValueError, match="a defect"):
        c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert [s.id for s in _live(c, user)] == [old.id]  # nothing was claimed
    assert "users" not in rows.sessions[str(old.id)].step_up_elevations
    assert [x["reason"] for x in em.calls if x["action"] == "auth.step_up_failed"] == ["unrotated"]


async def test_step_up_cancelled_in_the_claim_counts_its_void_lost_and_stays_cancelled() -> None:
    """A request cancelled in the claim, the mint or the link (a shutdown) can no longer write the
    announced session's void: counted lost and logged `cancelled`, as a cancelled refresh's
    record is, and the cancellation goes on."""
    c, em, seed, clock, _user = await _build()
    rows, parked = _rows(c), asyncio.Event()

    async def hang(session_id: str, *, reason: str, now: Any) -> Any:
        parked.set()
        await asyncio.wait_for(asyncio.Event().wait(), timeout=5)  # bounded: fails, not hangs

    rows.revoke = hang  # type: ignore[method-assign]  # the claim waits for the cancel
    before = _lost()
    transport = httpx.ASGITransport(app=c.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        request = asyncio.create_task(
            http.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))
        )
        await asyncio.wait_for(parked.wait(), timeout=5)
        with capture_logs() as logs:
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request

    assert _lost() == before + 1
    (created,) = [x for x in em.calls if x["action"] == "auth.session_created"]
    (line,) = [e for e in logs if e["event"] == "auth.step_up.outcome_lost"]
    assert (line["session_id"], line["error"]) == (str(created["session_id"]), "cancelled")


@pytest.mark.parametrize("password", ["wrong", _PW])
async def test_step_up_refused_rotates_nothing(password: str) -> None:
    """A wrong factor, or a wrong code: `401`, no rotation, the old bearer keeps working."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    body = {"code": "000000" if password == _PW else _code(seed, clock), "password": password}

    r = c.post("/auth/step-up", headers=_H, json={**body, "action_class": "users"})

    assert r.status_code == 401 and r.json()["code"] == "mfa_invalid"
    assert [s.id for s in _live(c, user)] == [old.id]
    assert "auth.session_created" not in em.actions()


async def test_read_only_session_step_up_rotates_nothing() -> None:
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    wrong = {"code": "000000", "password": _PW, "action_class": "users"}
    for _ in range(3):
        c.post("/auth/step-up", headers=_H, json=wrong)

    r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert (r.status_code, r.json()["code"]) == (403, "session_read_only")
    assert [s.id for s in _live(c, user)] == [old.id]
    assert "auth.session_created" not in em.actions()


async def test_a_non_owner_step_up_rotates_and_the_owner_route_still_refuses_403() -> None:
    """The forbidden-role case: a step-up proves who the caller is and grants no authority."""
    c, _em, seed, clock, user = await _build(owner_role=False)

    ok = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert ok.status_code == 200
    r = c.post(f"/users/{uuid.uuid4()}/mfa/reset", headers=_rotated(ok))
    assert (r.status_code, r.json()["code"]) == (403, "forbidden")
    assert len(_live(c, user)) == 1


async def test_a_step_up_leaves_another_users_sessions_alone() -> None:
    """The cross-user case: only the caller's session rotates."""
    other = uuid.uuid4()
    c, em, seed, clock, user = await _build(target=other)
    (theirs,) = _live(c, other)

    ok = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert ok.status_code == 200
    assert [s.id for s in _live(c, other)] == [theirs.id]
    assert {x["actor_user_id"] for x in em.calls if x["action"] == "auth.session_created"} == {user}
