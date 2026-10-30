"""E17-X02 abuse rig (#415): the E17-Q01 conformance `World` with real sessions, per-user grants and
a gateway audit sink, driven by a raw client that keeps none of the web client's rules. `World`
keeps its production wiring and fake clock. Added: a real `SessionService` behind production's
`app._session_authenticator` (enrolment gate off; E09-X02 covers it), the grants `login` gives each
user, and E09-X02's `RegistryAudit` (the gateway's `emit` kwargs, checked for the action name only).
Slice b2 adds the outbound budget, `races` (a change landing while a principal read is parked)
and `positions` and `orders` snapshots that name their accounts.
No code is shared with `apps/web`: frames are hand-built and sent unvalidated.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import (
    Awaitable,
    Callable,
    Collection,
    Iterable,
    Iterator,
    MutableMapping,
    Sequence,
)
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final, NamedTuple
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY, generate_latest
from starlette.websockets import WebSocketDisconnect

from candleviewer.app import _session_authenticator
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.models import MintedSession
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.session_service import SessionService
from candleviewer.observability.correlation import CorrelationMiddleware
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.lifecycle import bye_frame
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import SnapshotBody
from candleviewer.ws.topics import FAMILIES
from candleviewer.ws_wiring import trade_group_frame_visible
from tests.contract.ws import _harness
from tests.contract.ws._harness import WIRE_SUBPROTOCOL, Client, World, current_offer, current_wire
from tests.contract.ws._support import SAMPLES, recv_json
from tests.security.auth._stack import RegistryAudit
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.ws._seq_support import ACC_A, ACC_B, Source
from tests.unit.ws._system_snap import SYSTEM_ROLES

SOURCE = "testclient"  # the test client's address, as the gateway records it
#: Every account-scoped family (23-ws-protocol.md §6.2), by the registry: a new one is covered too.
SCOPED = tuple(sorted(name for name, fam in FAMILIES.items() if fam.account_scoped))
_ROLES = json.loads(
    (Path(__file__).resolve().parents[3] / "candleviewer/auth/rbac_seed.json").read_text("utf-8")
)["role_permissions"]


def role_permissions(role: str) -> frozenset[Permission]:
    """What the seeded RBAC matrix (`auth/rbac_seed.json`) gives `role`, as a deployment has it."""
    return frozenset(p for p in Permission if {"*", p.value} & set(_ROLES[role]))


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


class NamingSource(Source):
    """The harness's snapshot `Source`, its `positions` and `orders` bodies naming each account the
    subscription holds, a row apiece as the owning module's would (the stock bodies are empty): a
    snapshot built under a scope that still holds a withdrawn account then names it."""

    def build(self, sub: Subscription) -> SnapshotBody | None:
        body = super().build(sub)
        family = sub.topic.family.family
        if body is None or family not in {"positions", "orders"}:
            return body
        rows = [row for a in sorted(sub.accounts) for row in delta_naming(family, a)[family]]
        return replace(body, structured={family: rows})


class RawWorld(World):
    """`World` whose tokens are minted, expired and revoked by a real `SessionService`, and whose
    users hold the grants `login` gave them."""

    def __init__(
        self,
        log: pytest.LogCaptureFixture,
        std: pytest.CaptureFixture[str],
        backpressure: BackpressureConfig = _harness.ON,
    ) -> None:
        self.audit = RegistryAudit()
        self.reads = 0  # principal reads so far; `races[n]` runs while read n is parked
        self.races: dict[int, Callable[[], Awaitable[None]]] = {}
        self.events: list[MutableMapping[str, Any]] = []  # gateway log events (`world` fixture)
        self.log, self.std, self.printed = log, std, ""  # stdlib logging, stdout and stderr
        self.user_grants: dict[uuid.UUID, tuple[AccountGrant, ...]] = {}  # `login` gave each user
        self.user_access: dict[uuid.UUID, tuple[str, frozenset[Permission] | None]] = {}
        self.sessions = SessionService(FakeSessionRepository(), Hasher(), clock=self.utc_now)
        ctx: Any = SimpleNamespace(
            auth=SimpleNamespace(sessions=self.sessions, enrolment_gate_is_active=False)
        )
        self.verify = _session_authenticator(ctx, ctx)  # the refusals go unused: the gate is off
        with (
            patch.object(_harness, "make_ws_router", partial(make_ws_router, audit=self.audit)),
            patch.object(_harness, "Source", NamingSource),
        ):
            super().__init__(backpressure=backpressure)  # `World`: no audit sink on its router
        self.registry.services.audit = self.audit  # production's one sink also takes `sub`'s rows
        self.app.add_middleware(CorrelationMiddleware)  # as `create_app`: a socket's own id

    def utc_now(self) -> datetime:
        return datetime.fromtimestamp(self.clock.wall_ms() / 1000, tz=UTC)

    async def _authenticate(self, token: str) -> tuple[str, uuid.UUID, datetime]:
        self.tokens_seen.append(token)  # what the verifier was asked, as `World` records it
        return await self.verify(token)

    async def _resolve(self, uid: uuid.UUID) -> PrincipalSnapshot:
        role, perms = self.user_access.get(uid, ("manager", None))  # a user `login` never made
        if perms is None:
            perms = self.perms if role == "manager" else role_permissions(role)
        principal = PrincipalSnapshot(uid, frozenset({role}), perms, self.user_grants.get(uid, ()))
        self.reads += 1
        if (race := self.races.pop(self.reads, None)) is not None:
            await race()  # the grant changes after this read took its snapshot, before it returns
        return principal

    def login(
        self,
        name: str,
        *accounts: uuid.UUID,
        role: str = "manager",
        perms: frozenset[Permission] | None = None,
        frozen: Collection[uuid.UUID] = (),
    ) -> Login:
        """A live session of the user `name` (one name, one user), minted now, who may view only
        `accounts` (default: A), the `frozen` ones frozen. Their `perms`, read at each load, are the
        world's for a manager, else the role's seeded set."""
        user = uuid.uuid5(uuid.NAMESPACE_OID, name)
        self.user_access[user] = (role, perms)
        self.user_grants[user] = tuple(
            AccountGrant(a, True, False, a in frozen) for a in accounts or (ACC_A,)
        )
        return Login(user, self.call(self.sessions.mint, str(user)))

    async def amended(
        self,
        login: Login,
        *,
        drop: Collection[uuid.UUID] = (),
        freeze: Collection[uuid.UUID] = (),
    ) -> None:
        """The owner withdraws (`drop`) or freezes (`freeze`) grants of the user: the grant store
        first, then the registry's notice, as production does."""
        grants = (
            replace(g, frozen=g.frozen or g.exchange_account_id in freeze)
            for g in self.user_grants[login.user_id]
        )
        kept = tuple(g for g in grants if g.exchange_account_id not in drop)
        self.user_grants[login.user_id] = kept
        await self.registry.grants_changed(login.user_id)

    def revoke(self, login: Login) -> None:
        self.call(partial(self.sessions.revoke, str(login.minted.session_id), reason="logout"))

    def named_by(self, login: Login) -> dict[str, Any]:
        """What a `ws.subscribe.denied` row names of the socket it came from (#415, E17-R-16): the
        session in `session_id` and the connection in `after_state` (its upgrade's `request_id`,
        #3990, is pinned by the request-id suites). Read off the socket's own
        close row, so call it after the socket has closed: that row's `object_id` is the connection,
        and its `session_id` must be the login's."""
        (closed,) = self.audit.of("ws.connection.closed")
        assert closed["session_id"] == str(login.minted.session_id)
        return {
            "session_id": closed["session_id"],
            "after_state": {"connection_id": closed["object_id"]},
            "request_id": CONNECTION_REQUEST_ID,  # the upgrade's (#3990)
        }

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


#: The correlation id each raw socket's upgrade sends, which its audit rows carry (#3990).
CONNECTION_REQUEST_ID: Final = uuid.UUID("5d3e2f8a-4c1b-4e6f-9a2d-7b8c9d0e1f2a")


@contextmanager
def raw_connect(world: RawWorld, query: str = "") -> Iterator[RawClient]:
    """A socket on `/ws?<query>` in the running test's wire, sending what it likes unvalidated."""
    url = f"/ws?{query}" if query else "/ws"
    headers = {"x-correlation-id": str(CONNECTION_REQUEST_ID)}  # what its rows carry
    with world.client.websocket_connect(url, subprotocols=current_offer(), headers=headers) as ws:
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


def authenticated(c: Client, login: Login) -> dict[str, Any]:
    """`hello`, then `auth` with `login`'s token: the `auth_ok` frame. The `system` snap that
    follows it for a principal with a role (§12.1, #4992) is read into `c.system_snap`."""
    hello(c)
    c.send({"t": "auth", "id": "a", "p": {"access_token": login.token}})
    auth_ok = c.recv()
    assert auth_ok["t"] == "auth_ok"
    if not SYSTEM_ROLES.isdisjoint(auth_ok["p"]["roles"]):
        snap = c.recv()
        assert (snap["t"], snap["ch"], snap["s"]) == ("snap", "system", 1), snap
        c.system_snap = snap
    return auth_ok


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
    meta = ERROR_META[ErrorCode.AUTH_FAILED]
    failures = delta("cv_ws_auth_failures_total", reason=reason)
    errors = delta("cv_ws_errors_total", code="auth_failed")  # in process only (#2747)
    closes = delta("cv_ws_closes_total", reason="auth_failed")
    for n, frame in enumerate(frames[:2], 1):
        c.send({**frame, "id": f"a{n}"})
        err = c.recv_err()
        assert err["id"] == f"a{n}"  # the whole payload: no field, request id or cause beside it
        assert err["p"] == {
            "code": "auth_failed",
            "message": meta.title,
            "retryable": meta.retryable,
            "close": False,
        }
        if user is not None:
            served(c)
    c.send({**frames[2], "id": "a3"})
    bye, code = c.bye_then_close()
    assert (bye["p"], code) == (bye_frame("auth_failed")["p"], 4401)  # the catalogue's, whole
    assert (failures(), errors(), closes()) == (3, 2, 1)
    (row,) = world.audit.of("auth.login_failed")
    got = (row["reason"], row["severity"], row["actor_ip"], row["actor_user_id"])
    assert got == ("ws_auth_failed", "warning", SOURCE, user)
    logged = [e for e in world.events if e["event"] == "ws auth failed"]
    attempts = [(e["reason"], e["attempt"], e["reauth"], e["source_ip"]) for e in logged]
    assert attempts == [(reason, n, user is not None, SOURCE) for n in (1, 2, 3)]


def delta_naming(family: str, account: uuid.UUID, *also: uuid.UUID) -> dict[str, Any]:
    """The contract suite's sample delta of an account-scoped `family`, its rows renamed to
    `account` (a trade group's sample names none, so it gets a leg there, and one on each of
    `also`; a rule's rows never do): schema-valid, and the account's id is in the data the owning
    module would publish for it."""
    stock = SAMPLES["orders"][1]["orders"][0]["exchange_account_id"]  # the account the samples name
    body: dict[str, Any] = json.loads(json.dumps(SAMPLES[family][1]).replace(stock, str(account)))
    if family == "trade_groups":
        leg = {"id": body["trade_groups"][0]["id"]}
        legs = [leg | {"exchange_account_id": str(a), "status": "open"} for a in (account, *also)]
        body["trade_groups"][0]["legs"] = legs
    return body


def publish(world: RawWorld, family: str, account: uuid.UUID, *also: uuid.UUID) -> int:
    """One delta of `family` naming `account` (a trade group with a leg on each of `also` too),
    through the real hub on the app's loop: the number of subscriptions it reached. A trade group's
    is judged as production judges it, on every leg's account (SR-E28-21)."""
    body = delta_naming(family, account, *also)
    viewer = (lambda _p: True) if family == "rules" else None  # #3488: judged in test_ws_rules_*
    if family == "trade_groups":  # production's viewer, on every leg's account
        viewer = partial(trade_group_frame_visible, frozenset({account, *also}))
    return int(world.call(lambda: world.hub.publish(family, body, account=account, viewer=viewer)))


def drained(c: Client) -> list[dict[str, Any]]:
    """The frames sent to `c` before the `pong` of a `ping` sent now. That `pong` rides the
    priority lane (23 §8.4), so a normal-lane frame still held in its pacing window follows it."""
    c.send({"t": "ping", "id": "drain"})
    frames: list[dict[str, Any]] = []
    while (frame := c.recv())["t"] != "pong":
        frames.append(frame)
    return frames


def topic(family: str, *accounts: uuid.UUID) -> dict[str, Any]:
    """A `sub` entry for `family` naming `accounts`."""
    return {"ch": family, "opts": {"exchange_account_ids": [str(a) for a in accounts]}}


def answers(c: Client, *topics: dict[str, Any]) -> list[dict[str, Any]]:
    """The per-topic results of one `sub` frame, in request order."""
    found: list[dict[str, Any]] = c.sub(*topics)["p"]["results"]
    return found


def naming(frames: Iterable[dict[str, Any]], account: uuid.UUID) -> list[dict[str, Any]]:
    """The frames that carry `account`'s id anywhere: a row, a scope list or a refusal."""
    return [f for f in frames if str(account) in json.dumps(f, default=repr)]
