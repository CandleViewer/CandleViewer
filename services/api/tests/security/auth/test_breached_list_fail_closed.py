"""SR-028 fails closed on an unusable breached-password list (#5269), through the real
`create_app()` routes over the in-memory auth stack of `_stack.py`. A list that is missing, empty
or the size of the former 8-entry seed is read at start; `PUT /auth/password` and
`POST /invites/{token}` then answer `503` and change nothing, whatever the password. No network,
no sleeps (C-13.5, C-13.7)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from candleviewer.api.password import BREACHED_LIST_DOWN
from candleviewer.auth import password_policy
from candleviewer.auth.invite_service import hash_token
from tests.csrf_helpers import csrf_headers

from ._stack import INVITE_PW, PW, Stack, open_stack
from .test_invite_http_abuse import _invite, _owner

#: Passes every rule of the policy, so only the unusable list can refuse it.
_GOOD = "correct horse battery staple"


def _list(directory: Path, kind: str) -> Path:
    path = directory / f"{kind}.sha1"
    if kind == "empty":
        path.write_text("")
    elif kind == "seed-sized":
        digests = (password_policy.digest(f"seed-{i}") for i in range(8))
        path.write_text("# seed\n" + "".join(f"{d}\n" for d in digests))
    return path


@pytest.fixture(params=["missing", "empty", "seed-sized"])
def closed(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Stack]:
    """The stack started over an unusable list."""
    monkeypatch.setattr(password_policy, "BREACHED_LIST_PATH", _list(tmp_path, request.param))
    with open_stack(monkeypatch) as s:
        yield s


def test_a_password_change_is_503_and_changes_nothing(closed: Stack) -> None:
    uid, _ = closed.add_user("zed")
    minted = closed.call(closed.auth.sessions.mint, str(uid))
    before, seen = closed.users.users[str(uid)].password_hash, len(closed.audit.records)
    headers = {
        "Authorization": f"Bearer {minted.access_token}",
        **csrf_headers(closed.state.csrf_codec, minted.session_id),
    }
    body = {"current_password": PW, "new_password": _GOOD}
    r = closed.client.put("/auth/password", headers=headers, json=body)
    assert (r.status_code, r.json()["code"]) == (503, "store_unavailable"), r.text
    assert r.json()["detail"] == BREACHED_LIST_DOWN
    assert closed.users.users[str(uid)].password_hash == before
    assert closed.users.users[str(uid)].failed_login_count == 0  # the current one never checked
    assert closed.audit.records[seen:] == []
    auth = {"Authorization": f"Bearer {minted.access_token}"}
    assert closed.client.get("/auth/session", headers=auth).status_code == 200  # not rotated


def test_an_invite_redemption_is_503_and_consumes_nothing(closed: Stack) -> None:
    token = _invite(closed, _owner(closed))
    r = closed.client.post(f"/invites/{token}", json={"password": INVITE_PW})
    assert r.status_code == 503, r.text
    assert r.json()["detail"] == "service temporarily unavailable"  # generic: no oracle
    repo: Any = closed.auth._invite_repository  # the in-memory fake
    row = repo.rows[hash_token(token)]
    assert row.consumed_at is None and row.pending_password_hash is None
