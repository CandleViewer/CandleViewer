"""E17-X02 AC-03 and AC-04 (#415, threat model `E17-ws-gateway.md` §7): a bad token of any kind is
refused the same way on a first `auth` and on an in-place re-`auth`, which keeps the prior
identity and its account: `err auth_failed` twice, then `bye auth_failed` + 4401, one
`auth.login_failed` row and `cv_ws_auth_failures_total`. The kinds: expired, altered (the first,
middle or last character changed, one appended or dropped), wrong class (the user's refresh token,
a token shaped like an `mfa_token` and a CSRF token presented as the access token) and
revoked-session. Access tokens are opaque handles (ADR-0020), so "tampered signature" is an
altered token and "wrong audience" is another class of token.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any

import pytest

from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL
from tests.security.ws._raw import Login, RawWorld, authenticated, hello, raw_connect, strike_out
from tests.unit.ws._seq_support import ACC_B

#: `kind(world, old, live)` is a bad token. `old` is a session of the user that has expired by now,
#: `live` one of the same user that is live and is what the socket authenticates with.
Kind = Callable[[RawWorld, Login, Login], str]
_CSRF = CsrfCodec(bytes(range(32)))  # the codec's own tokens, bound to a session id


def _logins(world: RawWorld) -> tuple[Login, Login]:
    """Two sessions of one user, minted half a TTL apart, then the clock moves past the first's."""
    ttl = ACCESS_TOKEN_TTL.total_seconds()
    old = world.login("alice")
    world.clock.now = ttl / 2
    live = world.login("alice")
    world.clock.now = ttl + 1
    return old, live


def _changed(token: str, at: float) -> str:
    """`token` with the character a fraction `at` of the way along it swapped for another."""
    i = round((len(token) - 1) * at)
    return token[:i] + ("B" if token[i] == "A" else "A") + token[i + 1 :]


def _revoked(world: RawWorld) -> str:
    spare = world.login("alice")
    world.revoke(spare)
    return spare.token


_KINDS: dict[str, Kind] = {
    "expired": lambda w, old, live: old.token,
    "first-character-changed": lambda w, old, live: _changed(live.token, 0),
    "middle-character-changed": lambda w, old, live: _changed(live.token, 0.5),
    "last-character-changed": lambda w, old, live: _changed(live.token, 1),
    "character-appended": lambda w, old, live: live.token + "A",
    "character-dropped": lambda w, old, live: live.token[:-1],
    "refresh-token": lambda w, old, live: live.minted.refresh_token,
    "mfa-token": lambda w, old, live: secrets.token_urlsafe(32),  # shaped like an `mfa_token`
    "csrf-token": lambda w, old, live: _CSRF.issue(str(live.minted.session_id)),
    "revoked-session": lambda w, old, live: _revoked(w),
}
_KIND = pytest.mark.parametrize("kind", _KINDS.values(), ids=_KINDS.keys())


def _frame(token: str) -> dict[str, Any]:
    return {"t": "auth", "p": {"access_token": token}}


def _closed_as(world: RawWorld, login: Login) -> None:
    """The socket was still `login`'s when it closed, and its close was audited as such."""
    (row,) = world.audit.of("ws.connection.closed")
    identity = (row["reason"], row["severity"], row["actor_user_id"], row["session_id"])
    assert identity == ("auth_failed", "warning", login.user_id, str(login.minted.session_id))


@_KIND
def test_x02_ac_03_a_bad_token_gets_two_errs_then_bye_4401(world: RawWorld, kind: Kind) -> None:
    old, live = _logins(world)
    bad = kind(world, old, live)
    with raw_connect(world) as c:
        hello(c)
        strike_out(world, c, [_frame(bad)] * 3, reason="rejected", user=None)
    assert [r["action"] for r in world.audit.records] == ["auth.login_failed"]  # no close row
    assert world.tokens_seen == [bad] * 3  # the verifier refused it each time
    assert "auth_ok" not in [f["t"] for f in c.seen]
    assert world.leaks(bad, c) == []


@_KIND
def test_x02_ac_04_a_bad_token_on_a_reauth_keeps_the_identity(world: RawWorld, kind: Kind) -> None:
    old, live = _logins(world)
    bad = kind(world, old, live)
    with raw_connect(world) as c:
        authenticated(c, live)
        strike_out(world, c, [_frame(bad)] * 3, reason="rejected", user=live.user_id)
    _closed_as(world, live)
    assert world.tokens_seen == [live.token, bad, bad, bad]
    assert [world.leaks(t, c) for t in (bad, live.token)] == [[], []]  # the live one too


def test_x02_ac_04_three_foreign_user_tokens_on_a_reauth_end_in_4401(world: RawWorld) -> None:
    alice = world.login("alice")  # may view ACC_A only; the others, ACC_B only
    tokens = [world.login(name, ACC_B).token for name in ("bob", "carol", "dave")]
    with raw_connect(world) as c:
        authenticated(c, alice)
        frames = [_frame(t) for t in tokens]
        strike_out(world, c, frames, reason="user_mismatch", user=alice.user_id)
    _closed_as(world, alice)
    assert world.tokens_seen == [alice.token, *tokens]  # the live one, then each refused
    assert [world.leaks(t, c) for t in (alice.token, *tokens)] == [[]] * 4
