"""#415 (E17-X02): a WS connection stays on the user its token names (`23-ws-protocol.md` §4.3,
threat model WS-S04). A re-`auth` that would move it to another user is refused the same way by
either of its two checks: the gateway's check of the token's user, and the connection's own check
of the permission snapshot's user (`ConnectionAuthz.apply_snapshot`). A new socket's first `auth`
whose snapshot names another user than the token's is refused the same way, and nothing is
registered. Through a real socket, under both subprotocols, on the conformance harness's fake
clock. Attempts 1 and 2 get `err auth_failed` (an authenticated socket keeps serving its user);
the 3rd gets `bye auth_failed` + 4401 and one `auth.login_failed` row (and an authenticated
socket's close row); each attempt is counted and logged as `user_mismatch`.

The first test is refused by the gateway's check and the second by the connection's: each control
alone gives the client, the audit trail, the metrics and the log the same refusal.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import partial
from typing import Any
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import Severity
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from candleviewer.ws.gateway import make_ws_router
from tests.contract.ws import _harness
from tests.contract.ws._harness import OFFERS, Client, World, connect
from tests.unit.ws._seq_support import ACC_A, ACC_B

ALICE, BOB = uuid.UUID(int=0xA11CE), uuid.UUID(int=0xB0B)
TOKEN = {ALICE: "alice-" + "a" * 20, BOB: "bob-" + "b" * 20}  # test-only literals
_ACCOUNT = {ALICE: ACC_A, BOB: ACC_B}  # the one account each user may view
_METRICS = (  # the counters a refusal moves (or must not)
    ("cv_ws_auth_failures_total", {"reason": "user_mismatch"}),
    ("cv_ws_auth_failures_total", {"reason": "rejected"}),
    ("cv_ws_errors_total", {"code": "auth_failed"}),
    ("cv_ws_closes_total", {"reason": "auth_failed"}),
    ("cv_ws_permission_snapshots_refused_total", {"event": "reauth"}),
)
_ERR = {
    "code": "auth_failed",
    "message": ERROR_META[ErrorCode.AUTH_FAILED].title,
    "retryable": False,
    "close": False,
}
_GRANTED = ("ws.subscribe.granted", ALICE, None, Severity.INFO)  # each `orders` sub's (`_scope`)
#: ... after the record of its narrowing, B taken away (§6.2; #415, E17-R-15)
_NARROWED = ("ws.subscribe.denied", ALICE, "narrowed", Severity.WARNING)
#: What either check leaves: the client's frames, the audit rows, the metric deltas, the log.
_REFUSED = (
    [("err", "a1", _ERR, [str(ACC_A)]), ("err", "a2", _ERR, [str(ACC_A)]), ("auth_failed", 4401)],
    [
        *(_NARROWED, _GRANTED) * 2,
        ("auth.login_failed", ALICE, "ws_auth_failed", Severity.WARNING),
        ("ws.connection.closed", ALICE, "auth_failed", Severity.WARNING),
    ],
    [3.0, 0.0, 2.0, 1.0, 0.0],
    [("user_mismatch", n, True, "testclient") for n in (1, 2, 3)],
)
#: The same refusal of a new socket's first `auth`s: nothing is registered, and with no identity
#: yet the row names no user and there is no close row.
_FIRST_REFUSED = (
    [("err", "a1", _ERR, {}), ("err", "a2", _ERR, {}), ("auth_failed", 4401)],
    [("auth.login_failed", None, "ws_auth_failed", Severity.WARNING)],
    _REFUSED[2],
    [("user_mismatch", n, False, "testclient") for n in (1, 2, 3)],
)
_OFFER = pytest.mark.parametrize("offer", list(OFFERS.values()), ids=list(OFFERS))


class _Audit(list[dict[str, Any]]):
    async def emit(self, action: str, **row: Any) -> None:
        validate_action(action)  # a row production's writer would refuse fails the test
        self.append({"action": action, **row})


class _World(World):
    """The conformance `World` with an audit sink and two users, each with its own token, session
    and account. Once `answers_for` is set, the principal store returns that user's principal
    whoever is asked (a store fault). `read` lists the users the store was asked for; `on_read`
    runs inside a read. A user's id is equal each time, never the same object, as from a store."""

    def __init__(self) -> None:
        self.audit = _Audit()
        self.answers_for: uuid.UUID | None = None
        self.read: list[uuid.UUID] = []
        self.on_read: Callable[[], Awaitable[None]] | None = None
        with patch.object(_harness, "make_ws_router", partial(make_ws_router, audit=self.audit)):
            super().__init__()  # `World` builds its router with no audit sink
        self.registry.services.audit = self.audit  # one writer for both, as `create_app` wires

    async def _authenticate(self, token: str) -> tuple[str, uuid.UUID, datetime]:
        user = {t: u for u, t in TOKEN.items()}[token]  # any other token: a failed `auth`
        expires = (self.clock.wall_ms() + self.token_ttl_s * 1000) / 1000
        return f"sess-{user}", uuid.UUID(str(user)), datetime.fromtimestamp(expires, tz=UTC)

    async def _resolve(self, uid: uuid.UUID) -> PrincipalSnapshot:
        self.read.append(uid)
        user = uuid.UUID(str(self.answers_for or uid))
        if self.on_read is not None:
            await self.on_read()
        grant = AccountGrant(_ACCOUNT[user], True, False, False)
        return PrincipalSnapshot(user, frozenset({"manager"}), self.perms, (grant,))


def _scope(c: Client) -> list[str]:
    """The accounts the socket serves: an `orders` sub for A and B is narrowed to them (§6.2)."""
    entry = {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC_A), str(ACC_B)]}}
    (result,) = c.sub(entry)["p"]["results"]
    c.send({"t": "unsub", "id": "u", "p": {"topics": ["orders"]}})
    c.next_of("unsub_ok")
    return list(result["effective"]["exchange_account_ids"])


def _sample(name: str, labels: dict[str, str]) -> float:
    return float(REGISTRY.get_sample_value(name, labels) or 0.0)


def _three_reauths(
    offer: list[str], token: str, *, store_answers_for: uuid.UUID | None, first: bool = False
) -> tuple[Any, list[uuid.UUID]]:
    """Alice's socket re-`auth`s once with her own token, then three times with `token`; with
    `first`, a new socket's first three `auth`s. What they left, and the users the store was asked
    for. After each refusal: the accounts the socket serves, or (`first`) the registry's entries."""
    world, seen = _World(), list[tuple[Any, ...]]()
    before = [_sample(*m) for m in _METRICS]
    with capture_logs() as logs, connect(world, offer, authed=not first, token=TOKEN[ALICE]) as c:
        if not first:
            c.send({"t": "auth", "id": "a0", "p": {"access_token": TOKEN[ALICE]}})
            assert c.recv()["t"] == "auth_ok"  # her own: applied as before
        world.answers_for = store_answers_for
        for n in (1, 2, 3):
            c.send({"t": "auth", "id": f"a{n}", "p": {"access_token": token}})
            if n < 3:
                err = c.recv()
                assert err["t"] == "err", err  # never `auth_ok`, whatever the identity it names
                served = dict(world.registry._conns) if first else _scope(c)
                seen.append((err["t"], err.get("id"), err["p"], served))
        bye, code = c.bye_then_close()
        seen.append((bye["p"]["reason"], code))
    rows = [
        (r["action"], r["actor_user_id"], r.get("reason"), r.get("severity")) for r in world.audit
    ]
    moved = [_sample(*m) - b for m, b in zip(_METRICS, before, strict=True)]
    failed = [
        (e["reason"], e["attempt"], e["reauth"], e["source_ip"])
        for e in logs
        if e["event"] == "ws auth failed"
    ]
    return (seen, rows, moved, failed), world.read


@_OFFER
def test_reauth_with_another_users_token_is_refused_as_a_failed_auth(offer: list[str]) -> None:
    refused, read = _three_reauths(offer, TOKEN[BOB], store_answers_for=None)
    assert refused == _REFUSED
    assert BOB not in read  # the gateway's check refuses before Bob's principal is read


@_OFFER
def test_reauth_whose_snapshot_names_another_user_is_refused_the_same_way(offer: list[str]) -> None:
    """Alice's own token passes the gateway's check; the store answers for Bob, so the snapshot is
    Bob's and the connection's check refuses it."""
    assert _three_reauths(offer, TOKEN[ALICE], store_answers_for=BOB)[0] == _REFUSED


@_OFFER
def test_first_auth_whose_snapshot_names_another_user_is_refused_the_same_way(
    offer: list[str],
) -> None:
    """A new socket's `auth` with Alice's token while the store answers for Bob: never `auth_ok`,
    and the connection is never built from Bob's principal."""
    refused, read = _three_reauths(offer, TOKEN[ALICE], store_answers_for=BOB, first=True)
    assert (refused, read) == (_FIRST_REFUSED, [ALICE, ALICE, ALICE])


@_OFFER
def test_first_auth_whose_recheck_names_another_user_is_refused_the_same_way(
    offer: list[str],
) -> None:
    """SR-189: a grant change lands while a first `auth` reads Alice's principal, so the store is
    read again before `auth_ok`, and it answers for Bob. The connection's check refuses that
    snapshot and the registration is undone: the same failed `auth`."""
    world = _World()

    async def grant_change_meanwhile() -> None:
        world.on_read, world.answers_for = None, BOB
        await world.registry.grants_changed(BOB)  # no socket of Bob's: only the version moves

    world.on_read = grant_change_meanwhile
    with capture_logs() as logs, connect(world, offer, authed=False) as c:
        c.send({"t": "auth", "id": "a1", "p": {"access_token": TOKEN[ALICE]}})
        err = c.recv()
        assert (err["t"], err["p"], dict(world.registry._conns)) == ("err", _ERR, {})
    failed = [(e["reason"], e["reauth"]) for e in logs if e["event"] == "ws auth failed"]
    assert (failed, world.read) == ([("user_mismatch", False)], [ALICE, ALICE])
