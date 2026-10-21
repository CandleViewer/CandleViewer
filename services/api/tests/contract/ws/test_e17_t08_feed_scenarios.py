"""E17-T08 (#414): the three acceptance scenarios, on machines built through `statechart.factory`.

B1 `order` and B20 `risk_lockout` carry the real `CvStateFeedPlugin` into the real registry, hub and
authz behind `RegistryFeed`; every frame a client reads is validated against 23 §13-§15 (`Conn`).
The registry's clock and timers are fake (`_Loop`): a coalescing window is `advance`d, never slept.
"""

from __future__ import annotations

import copy
import json
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

import candleviewer.statechart as chart_package
from candleviewer.machine_state_wiring import RegistryFeed
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.bindings import b20_risk_lockout  # noqa: F401  (registers B20)
from candleviewer.statechart.config import Lane
from candleviewer.statechart.factory import BuildResult, default_clock
from candleviewer.statechart.lock import load_lock
from candleviewer.statechart.plugins import FeedBinding, feed_plugins
from candleviewer.ws.machines import MachineStateRegistry
from candleviewer.ws.permissions import VersionedSnapshot
from candleviewer.ws.sequencing import SequencingHub
from tests.unit.ws._seq_support import ACC_A, ACC_B, Conn, Source, principal
from tests.unit.ws.test_machines import OWNER, _attach, _Loop
from tests.xstate_contract._harness import settle
from tests.xstate_contract.b01_ports import Commands, Store

OID = "0a000000-0000-4000-8000-000000000001"
LOCK = Path(chart_package.__file__).parent / "machines" / "machine_hashes.lock"
ORDER = {
    "order_id": OID,
    "order_link_id": "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en",
    "account_id": str(ACC_A),
    "symbol": "BTCUSDT",
    "side": "buy",
    "qty": "1",
    "price": "63000",
    "stop_loss": "62000",
}
VALIDATE = {"gates": dict.fromkeys(b01.GATES, b01.PASSED), "order": ORDER, "rate_reservation": "r1"}
_SCOPE_MESSAGE = "None of the requested accounts are in scope."  # §6.2, whatever the cause


class Rig:
    """One gateway process: the registry on a fake loop, its hub and feed, and a manager on A."""

    def __init__(self) -> None:
        self.loop, self.hub, self.live = _Loop(), SequencingHub(), list[BuildResult]()
        self.registry = MachineStateRegistry(hub=self.hub, **self.loop.kw)
        self.feed = RegistryFeed(
            self.registry, environment="demo", now_ms=lambda: 1_789_132_262_000
        )
        self.conn = self.join(ACC_A)

    def join(self, *accounts: uuid.UUID) -> Conn:
        """A client of the gateway, holding a grant on each of `accounts`."""
        conn = Conn(Source(), *accounts)
        _attach(conn, self.registry, self.hub)
        return conn

    async def machine(self, chart: str, entity: str, lane: Lane, **scope: Any) -> Any:
        plugins = feed_plugins(self.feed, FeedBinding(chart, entity, **scope))
        built = await build(chart, clock=default_clock(), lane=lane, plugins=plugins)
        self.live.append(built)
        return built.interpreter

    async def order(self) -> Any:
        return await self.machine("order", OID, "order", accounts=frozenset({ACC_A}))


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    ports = b01.OrderPorts(persist=Store(), commands=Commands(), now_us=lambda: 1_000)
    monkeypatch.setattr(b01, "_ports", ports)  # B1's effects go to doubles, as in its own tests
    out = Rig()
    yield out
    for built in out.live:
        await built.interpreter.stop()


async def _send(interp: Any, event: str, **payload: Any) -> None:
    await interp.send(event, wait=True, **payload)
    await settle()


def _states(conn: Conn) -> list[tuple[str, int, str]]:
    return [(f["t"], f["s"], f["p"]["state"]) for f in conn.take()]


async def test_subscribe_to_a_machines_live_state(rig: Rig) -> None:
    """AC1: a valid subscription to `machines.order:{id}.state`, then B1 moves: a `snap` first, then
    a `d` with the new state at once from a quiet window and a burst as one `d` with the latest."""
    ch = f"machines.order:{OID}.state"
    order = await rig.order()
    result, _ = rig.conn.sub(ch)
    assert result["effective"] == {"throttle_ms": 100, "encoding": "structured", "coalesce": True}
    (snap,) = rig.conn.take()  # validated against the envelope and §15.10
    body = snap["p"]
    assert (snap["t"], snap["s"], snap["meta"]["reason"]) == ("snap", 1, "initial")
    assert (body["state"], body["tags"]) == ("draft", [])
    assert body["regions"] == {"lifecycle": "draft", "protection": "not_required"}
    assert body["machine_hash"] == load_lock(LOCK)["order"]["hash"]
    rig.loop.advance(1.0)  # a quiet window: the next payload leaves at once
    await _send(order, "VALIDATE", **VALIDATE)
    assert _states(rig.conn) == [("d", 2, "validated")]
    await _send(order, "SEND")  # `submitting`, then `submitted`: inside the window
    assert rig.conn.take() == [] and rig.loop.armed() == 1
    late = rig.join(ACC_A)  # a `sub` mid-burst is snapped with the latest, not the last sent
    late.sub(ch)
    assert _states(late) == [("snap", 1, "submitted")]
    rig.loop.advance(1.2)  # the window closes: one `d`, and `submitting` was never sent
    assert _states(rig.conn) == [("d", 3, "submitted")]
    rig.loop.advance(2.0)
    await _send(order, "KILL")  # terminal: its tags are sorted, and `halted_by_kill` is summarised
    last = rig.conn.take()[-1]["p"]
    assert (last["state"], last["tags"]) == ("killed", ["halted_by_kill", "terminal"])
    assert last["context_summary"] == {
        "symbol": "BTCUSDT",
        "halted_by_kill": True,
        "recon_misses": 0,
    }


def _tap(registry: MachineStateRegistry, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """What the hook hands the registry, copied as the hook built it."""
    seen: list[dict[str, Any]] = []
    for name in ("publish", "terminal"):
        real = getattr(registry, name)

        def tap(entity: Any, payload: Any, *, owner: object = None, _real: Any = real) -> bool:
            seen.append(copy.deepcopy(dict(payload)))
            return bool(_real(entity, payload, owner=owner))

        monkeypatch.setattr(registry, name, tap)
    return seen


async def test_no_interpreter_query_on_the_hot_path(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2: every frame is the hook's payload and JSON-native; serving them (a `sub`, a resync, a
    window's `d`) reads no attribute of the interpreter; a stopped machine is still snapped."""
    ch, hooked = f"machines.order:{OID}.state", _tap(rig.registry, monkeypatch)
    order = await rig.order()
    rig.conn.sub(ch)
    rig.loop.advance(1.0)
    await _send(order, "VALIDATE", **VALIDATE)
    await _send(order, "SEND")
    rig.conn.take()
    reads: Counter[str] = Counter()
    real_get = type(order).__getattribute__

    def counting(self: Any, name: str) -> Any:
        if self is order:
            reads[name] += 1
        return real_get(self, name)

    late = rig.join(ACC_A)
    with monkeypatch.context() as spy:
        spy.setattr(type(order), "__getattribute__", counting)
        late.sub(ch)
        resync = {"t": "resync", "ch": ch, "p": {"reason": "sequence_gap", "last_seq": 1}}
        rig.conn.emitter.client_resync(rig.conn.authz, resync)
        rig.loop.advance(2.0)
    served = [f["p"] for f in late.take() + rig.conn.take()]
    assert sum(reads.values()) == 0 and len(served) == 4  # two `snap`s, two `d`s
    assert all(p == hooked[-1] and json.loads(json.dumps(p)) == p for p in served)
    await _send(order, "KILL")  # terminal: its last state is kept for 60 s
    await order.stop()
    gone = rig.join(ACC_A)
    gone.sub(ch)
    assert _states(gone) == [("snap", 1, "killed")]


async def test_rbac_blocks_cross_account_subscription(rig: Rig) -> None:
    """AC3: a manager on A is refused B's lockout with the fixed §6.2 answer, and reads A's own; the
    Owner reads any account's; a lost grant ends a subscription already held."""
    mine, theirs = f"machines.risk_lockout:{ACC_A}.state", f"machines.risk_lockout:{ACC_B}.state"
    for account in (ACC_A, ACC_B):  # each account's lockout, scoped to it as its module binds it
        await rig.machine("risk_lockout", str(account), "control", accounts=frozenset({account}))
    refused, sub = rig.conn.authz.admit(theirs)
    error = {"code": "account_scope_denied", "message": _SCOPE_MESSAGE, "retryable": False}
    assert sub is None and refused["error"] == error
    held = rig.join(ACC_A)
    held.sub(mine)
    assert [f["p"]["state"] for f in held.take()] == ["clear"]
    rig.conn.authz.principal = OWNER
    assert rig.conn.authz.admit(theirs)[0]["ok"]  # the Owner reads any account's scoped entry
    frames = held.authz.apply_snapshot(VersionedSnapshot(principal(), 2), 8) or []
    assert [(f["t"], f["p"].get("reason")) for f in frames] == [
        ("permission_change", None),
        ("revoked", "account_scope_changed"),
    ]
    assert held.authz.find(mine) is None
