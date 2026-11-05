"""E29-X02 (#982): the OMS's private topics' scope, end to end through `create_app()`'s gateway.

`tests/security/ws/test_account_scope.py` proves narrowing, refusal and the no-frame rule for every
account-scoped family on the conformance gateway; the matrix pack the `sub` outcome on an app with
no OMS. This runs them on the app as composed with its OMS (`_world`): the `orders`, `executions`
and `positions` topics the runtime holds (their snapshots read on its order lane), `wallet`, and
B1's `machines.order`, for every actor of the matrix:

- the topic row of `matrix.yaml` holds for each actor, asking for the granted, the foreign and an
  absent account at once: the Owner's `sub` is all three, `manager_with_grant`'s is narrowed
  silently (an `ok` result whose `effective` names its grant alone, the narrowing audited
  `ws.subscribe.denied` and counted in `cv_ws_subscribe_narrowed_total`, never answered), the
  others are refused as the row says; `cv_ws_subscribe_total{topic,result}` counts each result
  under its own `result`;
- no frame, the `sub_ok`, the snapshot and every delta included, ever names an account the caller
  does not hold: the OMS's frames of each account are published as its step publisher hands them
  to the gateway (`OmsTopics.published`, the Sec.15 items), the foreign one first, to every
  signed-in socket, a refused one too, once a served one has its `snap` (no `d` precedes it), and
  read up to a marker; only the granted one reaches a narrowed socket, waited for as its own
  delta (a paced family's delta can trail the marker);
- a B1 order machine's state on a foreign account is refused by entity and never sent; each
  refusal is audited `ws.subscribe.denied` (its topic, reason `foreign`) and counted under its
  code.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Final

import pytest

from candleviewer.oms import ws_topics as wt
from candleviewer.ws.machines import MachineEntity
from candleviewer.ws.metrics import cv_ws_subscribe_narrowed_total
from candleviewer.ws.permissions import cv_ws_subscribe_total
from candleviewer.ws.topics import EntityScope
from tests.contract.rbac.rbac_harness import ABSENT, FOREIGN, GRANTED, seed_payload
from tests.contract.rbac.test_scope_and_ws import _MARK, _auth, _recv
from tests.security.oms import _cells as cells
from tests.security.oms._world import FILL, OPEN, ORDER, OmsWorld, tally
from tests.unit.oms.test_oms_runtime import T0

_ASKED: Final = (GRANTED, FOREIGN, ABSENT)
_FAMILIES: Final = ("orders", "executions", "positions", "wallet")
#: Later than any snapshot the lane stamps (at `T0`), so no delta is discarded as stale.
_STAMP: Final = wt.epoch_ms(T0 + timedelta(minutes=5))


def _change(family: str, account: Any) -> wt.Change:
    """The Sec.15 item the step publisher builds for the account's row of `family`."""
    if family == "orders":
        order = ORDER[account]
        item = wt.order_item(order, environment="demo", stamp=_STAMP, change="ack")
        return wt.Change("orders", item, str(order.id), order.symbol, _STAMP)
    if family == "executions":
        fill = FILL[account]
        item = wt.execution_item(fill, environment="demo") or {}
        return wt.Change("executions", item, str(fill.id), fill.symbol, _STAMP)
    held = OPEN[account]
    item = wt.position_item(held, environment="demo", stamp=_STAMP)
    return wt.Change("positions", item, str(held.id), held.symbol, _STAMP)


def _publish(world: OmsWorld, family: str, account: Any) -> None:
    """One frame of `account` on `family`, on the serving loop, as its producer sends it."""
    if family == "wallet":
        balance = {"exchange_account_id": str(account), "coin": "USDT", "equity": "1"}
        body = {"balances": [balance | {"updated_at_ms": _STAMP}]}
        seq = world.app.state.ws_registry.services.sequencing
        world.call(lambda: seq.publish("wallet", body, account=account))
    else:
        world.call(world.topics.published, account, [_change(family, account)])


def _read(ws: Any, world: OmsWorld, done: Callable[[list[dict[str, Any]]], bool]) -> list[Any]:
    """Every frame until `done` holds of those read, then up to a marker broadcast after the one
    that made it hold, so whatever was queued behind it is read too; pings are answered."""
    frames: list[dict[str, Any]] = []
    hub, marks, sent = world.app.state.ws_hub, 0, 0

    def mark() -> None:
        nonlocal sent
        world.call(hub.broadcast_system, _MARK)
        sent += 1

    mark()
    while not done(frames) or marks < sent:
        frame = _recv(ws)
        if frame["t"] == "ping":
            ws.send_json({"t": "pong", "id": frame["id"]})
        elif frame.get("p") == _MARK:
            marks += 1
        else:
            frames.append(frame)
            if done([frame]):
                mark()
    return frames


def _snapped(ws: Any, family: str) -> list[dict[str, Any]]:
    """Every frame up to the sub's own `snap` (its last chunk, the one with `s`), pings answered:
    until then the sub is `snapshot_pending` and is sent no `d`, so a frame published sooner is
    lost to it."""
    frames: list[dict[str, Any]] = []
    while True:
        frame = _recv(ws)
        if frame["t"] == "ping":
            ws.send_json({"t": "pong", "id": frame["id"]})
            continue
        frames.append(frame)
        if frame["t"] == "snap" and frame.get("ch") == family and frame.get("s") is not None:
            return frames


def _granted(frames: list[dict[str, Any]], family: str) -> bool:
    """The granted account's own delta (`t` "d", carrying `_STAMP` where the family's items carry
    a stamp; an execution carries its fill's time), never its snapshot: `positions` and `wallet`
    are paced on the normal lane, which the marker's priority lane overtakes."""
    stamp = "" if family == "executions" else str(_STAMP)
    return any(
        f.get("t") == "d" and f.get("ch") == family
        and str(GRANTED) in (body := json.dumps(f.get("p"))) and stamp in body
        for f in frames
    )  # fmt: skip


def _code(reply: dict[str, Any]) -> str:
    if reply["t"] != "sub_ok":
        return str(reply["p"]["code"])
    codes = [r["error"]["code"] for r in reply["p"]["results"] if not r["ok"]]
    return codes[0] if codes else "sub_ok"


@contextmanager
def _socket(world: OmsWorld, actor: str) -> Iterator[Any]:
    """A socket of `actor`'s, signed in (a `hello` alone for the unauthenticated caller)."""
    with world.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        if actor == "unauthenticated":
            ws.send_json({"t": "hello", "id": "h"})
            assert _recv(ws)["t"] == "welcome"
        else:
            assert _auth(ws, actor)["t"] == "auth_ok"
        yield ws


def _counts(topic: str) -> dict[str, float]:
    """`cv_ws_subscribe_total` of `topic`, by its `result`, and the narrowings."""
    counts = {
        f"result={s.labels['result']}": s.value for metric in cv_ws_subscribe_total.collect()
        for s in metric.samples
        if s.name == "cv_ws_subscribe_total" and s.labels["topic"] == topic
    }  # fmt: skip
    narrowed = tally(cv_ws_subscribe_narrowed_total, "cv_ws_subscribe_narrowed_total")
    return counts | {"narrowed": narrowed}


def _moved(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    return {k: v - before.get(k, 0.0) for k, v in after.items() if v != before.get(k, 0.0)}


@pytest.mark.parametrize("actor", list(cells.ws_outcomes("orders")))
@pytest.mark.parametrize("family", _FAMILIES)
def test_a_private_sub_beyond_the_grants_is_narrowed_or_refused_and_never_echoed(
    world: OmsWorld, family: str, actor: str
) -> None:
    want, held = (
        cells.ws_outcomes(family)[actor],
        cells.held(actor) | ({ABSENT} if actor == "owner" else set()),
    )
    before, logged = _counts(family), len(world.pack.audit.records)
    entry = {"ch": family, "opts": {"exchange_account_ids": [str(a) for a in _ASKED]}}
    served = want == "sub_ok"
    with _socket(world, actor) as socket:
        socket.send_json({"t": "sub", "id": "s", "p": {"topics": [entry]}})
        frames = [reply := _recv(socket)]
        assert _code(reply) == want, reply
        if served:
            effective = reply["p"]["results"][0]["effective"]["exchange_account_ids"]
            assert {str(a) for a in effective} == {str(a) for a in _ASKED if a in held}
            frames += _snapped(socket, family)  # its `snap` first: no `d` goes out before it
        if actor != "unauthenticated":  # every signed-in socket, a refused one too
            for account in (FOREIGN, ABSENT, GRANTED):  # the granted one last
                if account != ABSENT or family == "wallet":
                    _publish(world, family, account)
            frames += _read(socket, world, lambda read: not served or _granted(read, family))
            assert not served or _granted(frames, family), "the granted account's delta never came"
    sent = json.dumps(frames)
    assert not [a for a in _ASKED if a not in held and str(a) in sent], "a denied id was echoed"
    records = world.pack.audit.records[logged:]
    reasons = [r["reason"] for r in records if r["action"] == "ws.subscribe.denied"]
    narrowed = actor == "manager_with_grant"
    assert reasons == (["account_scope_denied"] if want == "account_scope_denied" else
                       ["narrowed"] * narrowed)  # fmt: skip
    result = {f"result={'ok' if served else want}": 1.0} if actor != "unauthenticated" else {}
    assert _moved(before, _counts(family)) == result | ({"narrowed": 2.0} if narrowed else {})


def _on(frames: list[dict[str, Any]], ch: str) -> bool:
    return any(f.get("ch") == ch for f in frames)


@pytest.mark.parametrize("actor", list(cells.ws_outcomes("machines.order")))
def test_an_order_machine_on_a_foreign_account_is_refused_by_entity_and_never_sent(
    world: OmsWorld, actor: str
) -> None:
    """23 Sec.6.4: a `machines.order` entity is scoped by its own account, bound by the OMS from
    its record; the granted order's machine is served as the row says, the foreign one's is
    refused `account_scope_denied` for anyone not holding it, and its state never reaches them.
    Each entity refusal is one `ws.subscribe.denied` naming the topic (reason `foreign`) and one
    `cv_ws_subscribe_total{topic="machines",result="account_scope_denied"}`."""
    registry, held = world.app.state.ws_registry.services.machines, cells.held(actor)
    entities = {
        a: MachineEntity("order", str(ORDER[a].id), EntityScope(accounts=frozenset({a})))
        for a in (GRANTED, FOREIGN)
    }
    world.call(registry._entries.clear)
    for entity in entities.values():
        assert world.call(registry.publish, entity, seed_payload("order"))
    want = cells.ws_outcomes("machines.order")[actor]
    before, logged = _counts("machines"), len(world.pack.audit.records)
    frames: list[dict[str, Any]] = []
    with _socket(world, actor) as socket:
        for account, entity in entities.items():
            socket.send_json({"t": "sub", "id": entity.ch, "p": {"topics": [{"ch": entity.ch}]}})
            while (reply := _recv(socket)).get("id") != entity.ch:  # its snapshot comes after
                frames.append(reply)
            expected = want if account in held or want != "sub_ok" else "account_scope_denied"
            assert _code(reply) == expected, (account, reply)
        changed = seed_payload("order") | {"state": "moved", "updated_at_ms": 2}
        for entity in (entities[FOREIGN], entities[GRANTED]):
            world.call(registry.publish, entity, changed)
        if actor != "unauthenticated":  # a refused socket too, read up to a marker
            ch, served = entities[GRANTED].ch, want == "sub_ok"
            frames += _read(socket, world, lambda read: not served or _on(read, ch))
    foreign = FOREIGN not in held and str(ORDER[FOREIGN].id) in json.dumps(frames)
    assert not foreign, "a foreign order's machine reached the socket"
    refused = [e.ch for a, e in entities.items() if a not in held and want != "not_authenticated"]
    records = [r for r in world.pack.audit.records[logged:] if r["action"] == "ws.subscribe.denied"]
    assert [(r["object_id"], r["reason"]) for r in records] == [(ch, "foreign") for ch in refused]
    counted = {"result=ok": 2.0 - len(refused), "result=account_scope_denied": len(refused)}
    wanted = {} if want == "not_authenticated" else {k: v for k, v in counted.items() if v}
    assert _moved(before, _counts("machines")) == wanted
