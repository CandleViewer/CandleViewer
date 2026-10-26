"""#906 slice D3d (E28-T02): every disallowed profile-write cell, and what a committed write tells,
through the routes `create_app()` mounts in `_profile_writes_world`'s world, whose facade here rings
the app's own bus as `wire_profiles` binds it (24 Sec.9.2). The step-up is the production
`StepUpService` and its B16 chart, never the pack's stand-in, so each refusal is recorded as
deployed. No network, no sleeps (C-13.5, C-13.7)."""

from __future__ import annotations

import functools
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast

import pytest

from candleviewer.accounts.profile_repository import ProfilesRepository
from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.step_up import GRACE_WINDOW, StepUpService
from candleviewer.bus import QueuePolicy, Subscription, TopicPattern
from candleviewer.bus.models import WILDCARD
from candleviewer.profiles_wiring import BusProfileChanges
from candleviewer.statechart.bindings import b16_session
from tests.contract._profile_writes_world import Writes, build
from tests.contract.rbac import rbac_harness as rbac
from tests.contract.rbac.test_scope_and_ws import _MARK, _auth, _recv
from tests.contract.test_account_profile_writes_provider import (
    _RISK,
    _WRITES,
    ALT,
    DEFAULT,
    DELETE,
    GRANTED,
    MOVE,
    REPLACE,
    Write,
    _new,
    answered,
    create,
    send,
)
from tests.unit.auth.auth_fakes import FakeUserRepository
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.test_profile_notices_wiring import _notice

_OTHERS = ("manager_with_grant", "manager_without_grant", "viewer")
_CELLS = [
    pytest.param(write, actor, live, id=f"{write.name}-{actor}-{'elevated' if live else 'plain'}")
    for write in _WRITES
    for actor in _OTHERS
    for live in (False, True)
]


@pytest.fixture(scope="module")
def _world() -> Iterator[Writes]:
    with pytest.MonkeyPatch.context() as mp:  # undone however the module ends
        w = build(mp)
        bus = w.world.app.state.app_context.bus.bus
        cache = cast(Any, SimpleNamespace(invalidate=w.invalidated.append))
        rings = ProfilesRepository(
            cast(Any, w.rows), cache=cache, changes=BusProfileChanges(bus, "demo")
        )
        object.__setattr__(w.writes, "profiles", rings)  # the frozen wiring, for this module
        yield w


@pytest.fixture
def w(_world: Writes, b16_audit: object) -> Writes:
    """B16's records land in the world's log, as `create_app` wires them (`tests/conftest.py`)."""
    _world.reset()
    b16_session.set_audit_sink(_world.world.audit)
    return _world


def _step_up(actor: str, live: bool) -> StepUpService:
    """The production service over `actor`'s session row, inside a `risk_caps` window or not."""
    sessions, row = FakeSessionRepository(), rbac.session_record(rbac.token_of(actor))
    window = {"risk_caps": row.issued_at + GRACE_WINDOW} if live else {}
    sessions.sessions[str(row.id)] = row.model_copy(update={"step_up_elevations": window})
    mfa, users, key = FakeMfaRepository(), FakeUserRepository(), TotpEncryptor(bytes(32))
    return StepUpService(mfa, sessions, key, users, Hasher())


@pytest.mark.parametrize(("write", "actor", "live"), _CELLS)
def test_every_disallowed_profile_write_cell_is_403_audited_and_changes_nothing(
    w: Writes, write: Write, actor: str, live: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gherkin 8, P9 (E28-X03's cells): the profile writes are handler-gated (#2304 slice 3c), so
    the handler's RBAC check runs before it demands the step-up. A Manager or Viewer is refused
    `accounts:write` with `rbac.denied` / `403 forbidden` whether or not a `risk_caps` window is
    live: no challenge (`auth.step_up_required`) and no use of the window
    (`auth.step_up_grace_used`) is recorded. Nothing is read, written, invalidated or noticed, and
    the one refusal record names the actor and session (#4174)."""
    step_up = _step_up(actor, live)
    monkeypatch.setattr(w.world.app.state.app_context.auth, "_step_up", step_up)
    with w.world.client as client:  # one loop, so B16's chart outlives the request
        assert client.portal is not None
        resp = send(w, write, actor)
        client.portal.call(step_up.stop)
    assert (resp.status_code, answered(resp, write)["code"]) == (403, "forbidden")
    records = w.world.audit.records
    assert [(r["action"], r["outcome"]) for r in records] == [("rbac.denied", AuditOutcome.DENIED)]
    named = [(str(r["actor_user_id"]), str(r["session_id"])) for r in records]
    assert named == [(str(rbac.user_id_of(actor)), str(rbac.session_id_of(actor)))] * len(records)
    assert (w.rows.seen, _new(w), w.rows.notices, w.invalidated) == ([], [], [], [])


def _heard(probe: Subscription) -> list[tuple[Any, ...]]:
    """What the probe holds, drained on the app's loop: each change's account, kind, rows and
    binding version."""
    events = []
    while not probe.queue.empty():
        e = probe.queue.get_nowait()
        rows = tuple((p.profile_id, p.version) for p in e.profiles)
        events.append((e.exchange_account_id, e.change, rows, e.binding_version))
    return events


def _told(hub: Any, *socks: Any) -> list[list[Any]]:
    """The `system` bodies each socket was sent before one marker, broadcast to all on the app's
    loop after the bridge's own offer (`test_scope_and_ws._until_mark`, for several sockets)."""
    socks[0].portal.call(hub.broadcast_system, _MARK)
    told = []
    for sock in socks:
        bodies = []
        while (body := _recv(sock).get("p")) != _MARK:
            bodies.append(body)
        told.append(bodies)
    return told


def test_a_committed_profile_write_rings_its_accounts_doorbell_and_a_refused_one_does_not(
    w: Writes,
) -> None:
    """A committed create, replace, move and delete each publish one `ProfilesChanged` on
    `demo.profiles.<account>.changed` (D3a) and reach the Owner's socket and a Manager's granted
    the account as `profiles.changed`, through D3e's bridge, never a Manager's granted another
    account (23 Sec.15.9). A refused, a stale and a no-op write publish nothing, so tell no one."""
    new, app = uuid.UUID(int=99), w.world.app
    w.minted.append(new)  # the id the create takes
    bus, hub, notices = app.state.app_context.bus.bus, app.state.ws_hub, app.state.profile_notices
    pattern = TopicPattern(env="demo", domain="profiles", symbol=WILDCARD, detail="changed")
    probe = bus.subscribe("d3d-probe", pattern, QueuePolicy.NEVER_DROP, maxsize=16)
    seen: list[tuple[int, list[tuple[Any, ...]], list[list[Any]]]] = []
    with w.world.client as client:
        connect = functools.partial(client.websocket_connect, "/ws", subprotocols=["cv.v1.json"])
        portal = client.portal
        assert portal is not None  # one loop for the requests, the sockets and the bridge
        portal.call(notices.start)
        try:
            with connect() as owner, connect() as granted, connect() as other:
                actors = ("owner", "manager_with_grant", "manager_without_grant")
                sockets = (owner, granted, other)
                authed = [_auth(s, a)["t"] for s, a in zip(sockets, actors, strict=True)]
                assert authed == ["auth_ok"] * 3
                for resp in _writes(w):
                    told = _told(hub, owner, granted, other)
                    seen.append((resp.status_code, portal.call(_heard, probe), told))
        finally:
            portal.call(notices.stop)
            bus.unsubscribe(probe)
    none: list[list[Any]] = [[], [], []]  # what the Owner's, the granted and the other socket hear
    one = [[_notice(GRANTED)], [_notice(GRANTED)], []]
    assert seen == [
        (422, [], none),
        (201, [(GRANTED, "created", ((new, 1),), None)], one),
        (412, [], none),
        (200, [(GRANTED, "updated", ((ALT, 3),), None)], one),
        (200, [], none),
        (200, [(GRANTED, "default_moved", ((DEFAULT, 4), (ALT, 4)), 2)], one),
        (204, [(GRANTED, "deleted", ((DEFAULT, 5),), None)], one),
    ]


def _writes(w: Writes) -> Iterator[Any]:
    """In order: a refused create, a create, a stale replace, a replace, a move onto the current
    default (no change), a move, and the delete of the demoted default."""
    yield create(w, {**_RISK, "require_native_stop": False})
    yield create(w, _RISK)
    yield send(w, REPLACE, tags=[f'W/"{ALT}:1"'])
    yield send(w, REPLACE)
    yield send(w, MOVE, body={"profile_id": str(DEFAULT)})
    yield send(w, MOVE)
    yield send(w, DELETE, profile=DEFAULT, tags=[f'W/"{DEFAULT}:4"'])
