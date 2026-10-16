"""#2510 (C-2.9): the owner TOTP reset and invite create / reissue / revoke audit ahead of
the change: a refused WAL append answers 503 with nothing persisted (before: 500, unaudited)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from candleviewer.storage.errors import WriteAheadTimeout
from tests.unit.api.test_invites_router import _BODY, _elevate, _invite, _setup
from tests.unit.api.test_step_up_router import _H, _PW, _build, _code

_REFUSED = "audit unavailable; nothing was changed"


async def test_owner_totp_reset_refused_by_its_audit_append_changes_nothing() -> None:
    target = uuid.uuid4()
    c, em, seed, clock, _ = await _build(target=target)
    body = {"code": _code(seed, clock), "password": _PW, "action_class": "users"}
    assert c.post("/auth/step-up", headers=_H, json=body).status_code == 200
    em.fail_on = frozenset({"auth.mfa_reset_by_owner"})
    r = c.post(f"/users/{target}/mfa/reset", headers=_H)
    assert r.status_code == 503 and r.json()["detail"] == "audit unavailable"
    em.fail_on = frozenset()
    ok = c.post(f"/users/{target}/mfa/reset", headers=_H)  # the refused one revoked nothing
    counts = {"methods_revoked": 1, "sessions_revoked": 1}
    assert ok.json() == {"target_user_id": str(target), **counts}
    (rec,) = [x for x in em.calls if x["action"] == "auth.mfa_reset_by_owner"]
    assert rec["after_state"] == counts and rec["object_id"] == str(target)


async def test_owner_totp_reset_hook_bug_is_not_masked_as_audit_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only `AuditError` (or `RuntimeError`: audit not started) means 503; a bug propagates."""
    target = uuid.uuid4()
    c, em, seed, clock, _ = await _build(target=target)
    body = {"code": _code(seed, clock), "password": _PW, "action_class": "users"}
    assert c.post("/auth/step-up", headers=_H, json=body).status_code == 200
    emit = em.emit

    async def bug(action: str, **kw: Any) -> None:
        if action == "auth.mfa_reset_by_owner":
            raise ValueError("not an audit failure")
        await emit(action, **kw)

    monkeypatch.setattr(em, "emit", bug)
    with pytest.raises(ValueError, match="not an audit failure"):
        c.post(f"/users/{target}/mfa/reset", headers=_H)


async def test_invite_create_refused_by_its_audit_append_persists_nothing() -> None:
    c, em, seed, clock, repo, _ = await _setup()
    _elevate(c, seed, clock)
    em.fail_on = frozenset({"users.invited"})
    r = c.post("/users", headers=_H, json=_BODY)
    assert r.status_code == 503 and r.json()["detail"] == _REFUSED
    assert not repo.rows and not repo.emails


async def test_invite_create_maps_only_the_stores_write_ahead_timeout_to_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SQL store's bounded hook rolled back (503, nothing changed); any other
    `TimeoutError` (a driver or commit timeout: outcome unknown) is not answered so."""
    c, _em, seed, clock, repo, _ = await _setup()
    _elevate(c, seed, clock)

    async def hung(**_kw: Any) -> bool:
        raise WriteAheadTimeout("write-ahead audit exceeded 5.0 s")

    async def commit_timeout(**_kw: Any) -> bool:
        raise TimeoutError

    monkeypatch.setattr(repo, "create_user_with_invite", hung)
    r = c.post("/users", headers=_H, json=_BODY)
    assert r.status_code == 503 and r.json()["detail"] == _REFUSED
    monkeypatch.setattr(repo, "create_user_with_invite", commit_timeout)
    with pytest.raises(TimeoutError):
        c.post("/users", headers=_H, json=_BODY)


async def test_invite_reissue_refused_by_its_audit_append_keeps_the_old_link() -> None:
    c, em, seed, clock, repo, _ = await _setup()
    token = await _invite(c, seed, clock)
    (row,) = repo.rows.values()
    em.fail_on = frozenset({"users.invite_reissued"})
    r = c.post(f"/users/{row.user_id}/invite", headers=_H)
    assert r.status_code == 503 and r.json()["detail"] == _REFUSED
    assert c.get(f"/invites/{token}").status_code == 200 and len(repo.rows) == 1
    em.fail_on = frozenset()
    fresh = c.post(f"/users/{row.user_id}/invite", headers=_H)
    assert fresh.status_code == 201 and c.get(f"/invites/{token}").status_code == 404
    assert "users.invite_reissued" in em.actions()


async def test_invite_revoke_refused_by_its_audit_append_keeps_the_invite_open() -> None:
    c, em, seed, clock, repo, _ = await _setup()
    token = await _invite(c, seed, clock)
    (row,) = repo.rows.values()
    em.fail_on = frozenset({"users.invite_revoked"})
    r = c.delete(f"/users/{row.user_id}/invite", headers=_H)
    assert r.status_code == 503 and r.json()["detail"] == _REFUSED
    assert c.get(f"/invites/{token}").status_code == 200


async def test_invitee_gate_answers_a_generic_503_while_audit_is_down() -> None:
    c, *_ = await _setup(audit_ok=False)
    r = c.get(f"/invites/{'t' * 43}")
    assert r.status_code == 503 and "audit" not in r.json()["detail"]
