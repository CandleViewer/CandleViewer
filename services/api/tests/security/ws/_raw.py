"""E17-X02 abuse rig (#415): the E17-Q01 conformance `World` with real sessions, per-user grants and
a gateway audit sink, driven by a raw client that keeps none of the web client's rules. `World`
keeps its production wiring and fake clock. Added: a real `SessionService` behind production's
`app._session_authenticator` (enrolment gate off; E09-X02 covers it), the grants `login` gives each
user, and E09-X02's `RegistryAudit` (the gateway's `emit` kwargs, checked for the action name only).
No code is shared with `apps/web`: frames are hand-built and sent unvalidated.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator, MutableMapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from types import SimpleNamespace
from typing import Any, NamedTuple
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY, generate_latest
from starlette.websockets import WebSocketDisconnect

from candleviewer.app import _session_authenticator
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MintedSession
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.session_service import SessionService
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from candleviewer.ws.gateway import make_ws_router
from tests.contract.ws import _harness
from tests.contract.ws._harness import WIRE_SUBPROTOCOL, Client, World, current_offer, current_wire
from tests.contract.ws._support import recv_json
from tests.security.auth._stack import RegistryAudit
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.ws._seq_support import ACC_A, ACC_B

SOURCE = "testclient"  # the test client's address, as the gateway records it


class Login(NamedTuple):
    user_id: uuid.UUID
    minted: MintedSession

    @property
    def token(self) -> str:
        return self.minted.access_token


class RawClient(Client):
    """A `Client` that keeps the close frame's reason, which `close_code` drops."""

    close_reason = ""

    def closed(self) -> int:
        try:
            recv_json(self.ws)
        except WebSocketDisconnect as exc:
            self.close_reason = exc.reason
            return int(exc.code)
        pytest.fail("a frame arrived, not a close")


class RawWorld(World):
    """`World` whose tokens are minted, expired and revoked by a real `SessionService`, and whose
    users hold the grants `login` gave them."""

    def __init__(self, log: pytest.LogCaptureFixture, std: pytest.CaptureFixture[str]) -> None:
        self.audit = RegistryAudit()
        self.events: list[MutableMapping[str, Any]] = []  # gateway log events (`world` fixture)
        self.log, self.std, self.printed = log, std, ""  # stdlib logging, stdout and stderr
        self.user_grants: dict[uuid.UUID, tuple[AccountGrant, ...]] = {}
        self.sessions = SessionService(FakeSessionRepository(), Hasher(), clock=self.utc_now)
        ctx: Any = SimpleNamespace(
            auth=SimpleNamespace(sessions=self.sessions, enrolment_gate_is_active=False)
        )
        self.verify = _session_authenticator(ctx, ctx)  # the refusals go unused: the gate is off
        with patch.object(_harness, "make_ws_router", partial(make_ws_router, audit=self.audit)):
            super().__init__()  # `World` builds its router with no audit sink

    def utc_now(self) -> datetime:
        return datetime.fromtimestamp(self.clock.wall_ms() / 1000, tz=UTC)

    async def _authenticate(self, token: str) -> tuple[str, uuid.UUID, datetime]:
        self.tokens_seen.append(token)  # what the verifier was asked, as `World` records it
        return await self.verify(token)

    async def _resolve(self, uid: uuid.UUID) -> PrincipalSnapshot:
        grants = self.user_grants.get(uid, ())  # a user `login` never made holds no account
        return PrincipalSnapshot(uid, frozenset({"manager"}), self.perms, grants)

    def login(self, name: str, account: uuid.UUID = ACC_A) -> Login:
        """A live session of the user `name` (one name, one user), minted now, who may view only
        `account`."""
        user = uuid.uuid5(uuid.NAMESPACE_OID, name)
        self.user_grants[user] = (AccountGrant(account, True, False, False),)  # view only
        return Login(user, self.call(self.sessions.mint, str(user)))

    def revoke(self, login: Login) -> None:
        self.call(partial(self.sessions.revoke, str(login.minted.session_id), reason="logout"))

    def leaks(self, secret: str, c: RawClient) -> list[str]:
        """The sinks holding any 16-character window of `secret` (the whole of a shorter one)."""
        shown = self.std.readouterr()  # a read empties the capture, so keep what it held
        self.printed += shown.out + shown.err
        texts = {
            "frames": json.dumps(c.seen, default=repr),
            "close reason": c.close_reason,
            "audit": repr(self.audit.records),
            "logs": repr(self.events),
            "stdlib logs": self.log.text,
            "stdout and stderr": self.printed,
            "metrics": generate_latest(REGISTRY).decode(),
        }
        windows = {secret[i : i + 16] for i in range(max(len(secret) - 15, 1))}
        return [name for name, text in texts.items() if any(w in text for w in windows)]


@contextmanager
def raw_connect(world: RawWorld, query: str = "") -> Iterator[RawClient]:
    """A socket on `/ws?<query>` in the running test's wire, sending what it likes unvalidated."""
    url = f"/ws?{query}" if query else "/ws"
    with world.client.websocket_connect(url, subprotocols=current_offer()) as ws:
        assert ws.accepted_subprotocol == WIRE_SUBPROTOCOL[current_wire()]
        yield RawClient(ws, conform=False)


def hello(c: Client) -> None:
    c.send({"t": "hello", "id": "h", "p": {"client": "raw"}})
    assert c.recv()["t"] == "welcome"


def delta(name: str, **labels: str) -> Callable[[], float]:
    """`name{labels}` counted from now: call the result for the change since."""

    def read() -> float:
        return float(REGISTRY.get_sample_value(name, labels) or 0.0)

    start = read()
    return lambda: read() - start


def authenticated(c: Client, login: Login) -> None:
    hello(c)
    c.send({"t": "auth", "id": "a", "p": {"access_token": login.token}})
    assert c.recv()["t"] == "auth_ok"


def served(c: Client) -> None:
    """The socket still serves its identity, alice's: a private topic of her account is granted
    (and let go again, so the next call grants it afresh), another account's is refused."""

    def result(account: uuid.UUID) -> tuple[bool, str | None]:
        topic = {"ch": "orders", "opts": {"exchange_account_ids": [str(account)]}}
        (r,) = c.sub(topic)["p"]["results"]
        return r["ok"], r.get("error", {}).get("code")

    assert result(ACC_A) == (True, None)
    c.send({"t": "unsub", "id": "u", "p": {"topics": ["orders"]}})
    c.next_of("unsub_ok")
    assert result(ACC_B) == (False, "account_scope_denied")


def strike_out(
    world: RawWorld,
    c: Client,
    frames: Sequence[dict[str, Any]],
    *,
    reason: str,
    user: uuid.UUID | None,
) -> None:
    """Send three failing `auth` frames: the first two get `err auth_failed` (the catalogue's
    title, whatever the token's fault; a socket's identity, `user`, is still served after each),
    the third `bye auth_failed` + 4401. Asserts what `23-ws-protocol.md` §4.3 documents: the codes,
    the metrics, one `auth.login_failed` row with the source address and one `ws auth failed` log
    event per attempt."""
    assert len(frames) == 3
    title = ERROR_META[ErrorCode.AUTH_FAILED].title
    failures = delta("cv_ws_auth_failures_total", reason=reason)
    errors = delta("cv_ws_errors_total", code="auth_failed")  # in process only (#2747)
    closes = delta("cv_ws_closes_total", reason="auth_failed")
    for n, frame in enumerate(frames[:2], 1):
        c.send({**frame, "id": f"a{n}"})
        err = c.recv_err()
        got = (err["id"], err["p"]["code"], err["p"]["message"], err["p"]["close"])
        assert got == (f"a{n}", "auth_failed", title, False)
        if user is not None:
            served(c)
    c.send({**frames[2], "id": "a3"})
    bye, code = c.bye_then_close()
    assert (bye["p"]["reason"], bye["p"]["code"], code) == ("auth_failed", 4401, 4401)
    assert (failures(), errors(), closes()) == (3, 2, 1)
    (row,) = world.audit.of("auth.login_failed")
    got = (row["reason"], row["severity"], row["actor_ip"], row["actor_user_id"])
    assert got == ("ws_auth_failed", "warning", SOURCE, user)
    logged = [e for e in world.events if e["event"] == "ws auth failed"]
    attempts = [(e["reason"], e["attempt"], e["reauth"], e["source_ip"]) for e in logged]
    assert attempts == [(reason, n, user is not None, SOURCE) for n in (1, 2, 3)]
