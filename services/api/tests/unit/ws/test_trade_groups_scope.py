"""E28-T05 (#909, slice S4b): the `trade_groups` topic on a real `SequencingHub`, as
`ws_wiring.trade_groups_topic` wires it (23 §6.2, §9.5, §15.5; SR-E28-21, AC 9): scope, narrowing,
the hub's viewer guard, the viewer, the frame counts, the seed's wake and the resync after a failed
publish."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from prometheus_client import generate_latest
from structlog.testing import capture_logs

from candleviewer.accounts.trade_group_topic import TradeGroupTopic
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.observability.metrics import Metrics
from candleviewer.ws.permissions import VersionedSnapshot
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody
from candleviewer.ws_wiring import (
    SnapshotRouter,
    TradeGroupFrameCounts,
    trade_group_frame_visible,
    trade_groups_topic,
)
from tests.unit.accounts.test_trade_group_topic import _A, _B, _C, _G1, _G2, _group, _leg, _stored
from tests.unit.ws._seq_support import Conn, Source, principal

type Topic = TradeGroupTopic[SnapshotBody, PrincipalSnapshot]


def _wired(*seed: Any, seeded: bool = True) -> tuple[SequencingHub, Topic, Metrics, SnapshotRouter]:
    """The hub, the topic seeded with `seed` (unless not `seeded`), its counts' registry and the
    snapshot router."""
    hub, metrics, counts = SequencingHub(), Metrics("demo"), TradeGroupFrameCounts()
    counts.bind(metrics)
    topic = trade_groups_topic(hub, counts)
    if seeded:
        topic.seed(seed)
    orders = Source()
    orders.bodies["orders"] = SnapshotBody({"orders": []})
    return hub, topic, metrics, SnapshotRouter({"trade_groups": topic, "orders": orders})


def _conn(hub: SequencingHub, router: SnapshotRouter, *grants: UUID) -> Conn:
    conn = Conn(cast(Source, router), *grants)
    hub.register(conn.authz, conn.emitter)
    return conn


def _entry(*accounts: UUID, ch: str = "trade_groups") -> dict[str, Any]:
    return {"ch": ch, "opts": {"exchange_account_ids": [str(a) for a in accounts]}}


def _ids(frame: dict[str, Any]) -> list[str]:
    return [item["id"] for item in frame["p"]["trade_groups"]]


def test_ac9_a_manager_granted_a_alone_is_narrowed_to_a_and_never_told_of_b_or_c() -> None:
    hub, topic, _, router = _wired(_stored(1, _A), _stored(2, _A, _B))
    conn = _conn(hub, router, _A)
    result, _ = conn.sub(_entry(_A, _B, _C))
    assert result["ok"] and result["effective"]["exchange_account_ids"] == [str(_A)]
    [snap] = conn.take()
    assert _ids(snap) == [_G1]  # the group on A and B is not covered
    topic.leg_changed(_leg(1, 0, _A, filled_qty=Decimal("0.004")))
    topic.leg_changed(_leg(2, 0, _A, filled_qty=Decimal("0.004")))  # a group with a leg on B
    topic.created(_stored(3, _A, _C))
    topic.group_changed(_group(2, "closed"))
    frames = conn.take()
    assert [_ids(frame) for frame in frames] == [[_G1]]
    seen = json.dumps([result, snap, *frames])
    assert str(_B) not in seen and str(_C) not in seen  # a denied id is never echoed


def test_ac9_without_orders_read_nothing_is_admitted_or_sent() -> None:
    """Refused at `sub`; a principal that loses it (§9.5 swaps it in first) is sent nothing."""
    hub, topic, _, router = _wired(_stored(1, _A))
    conn = _conn(hub, router, _A)
    no_read = replace(conn.authz.principal, permissions=frozenset())
    refused = Conn(cast(Source, router), _A)
    refused.authz.principal = no_read
    result, sub = refused.authz.admit(_entry(_A))
    assert sub is None and result["error"]["code"] == "forbidden"
    conn.sub(_entry(_A))
    conn.take()
    conn.authz.principal = no_read
    topic.leg_changed(_leg(1, 0, _A, filled_qty=Decimal("0.004")))
    assert conn.take() == []


def test_a_narrowed_subscriptions_reconfigure_snapshot_leaves_out_the_group_it_lost() -> None:
    """B's grant withdrawn: narrowed in place, the `reconfigure` snapshot leaves out the A and B
    group, which sends nothing more, its end included (S0's R1S-06, S4a's R1S-04)."""
    hub, topic, _, router = _wired(_stored(1, _A, _B), _stored(2, _A))
    conn = _conn(hub, router, _A, _B)
    _, sub = conn.sub(_entry(_A, _B))
    [snap] = conn.take()
    assert _ids(snap) == [_G1, _G2]
    assert conn.authz.apply_snapshot(VersionedSnapshot(principal(_A), 1), 7)
    assert sub.accounts == {_A}
    assert conn.emitter.snapshot(sub, "reconfigure")
    [snap] = conn.take()
    assert (snap["meta"]["reason"], _ids(snap)) == ("reconfigure", [_G2])
    topic.leg_changed(_leg(1, 1, _B, filled_qty=Decimal("0.004")))
    topic.group_changed(_group(1, "closed"))
    assert conn.take() == []


def test_the_wired_viewer_stops_what_select_lets_through_and_the_owner_is_sent_it() -> None:
    """S4b's R1S-01: the principal swapped in place (§9.5 swaps it first), `sub.accounts` still A
    and B. B's grant gone or frozen, the viewer alone stops the A and B group's frame; the Owner,
    who lists no grant, is sent it."""
    hub, topic, _, router = _wired(_stored(1, _A, _B))
    conn = _conn(hub, router, _A, _B)
    _, sub = conn.sub(_entry(_A, _B))
    conn.take()
    on_a = AccountGrant(_A, True, False, False)
    for grants in ((on_a,), (on_a, AccountGrant(_B, True, False, True))):
        conn.authz.principal = _manager(*grants)
        topic.leg_changed(_leg(1, 1, _B, filled_qty=Decimal("0.004")))
        assert sub.accounts == {_A, _B} and conn.take() == []
    conn.authz.principal = replace(_manager(), roles=frozenset({"owner"}))
    topic.leg_changed(_leg(1, 1, _B, filled_qty=Decimal("0.005")))
    assert [_ids(frame) for frame in conn.take()] == [[_G1]]


def test_a_sub_made_before_the_seed_is_sent_its_initial_snapshot_when_the_seed_lands() -> None:
    """S4b's R1C-01: the gateway serves before the OMS seeds the topic, so a `sub` may wait first,
    `snapshot_pending` (§7.7); the seed wakes it with one `initial` snapshot, then deltas flow."""
    hub, topic, _, router = _wired(seeded=False)
    conn = _conn(hub, router, _A)
    _, sub = conn.sub(_entry(_A))
    assert conn.take() == [] and sub.snapshot_pending
    topic.seed([_stored(1, _A)])
    [snap] = conn.take()
    assert (snap["t"], snap["meta"]["reason"], _ids(snap)) == ("snap", "initial", [_G1])
    topic.leg_changed(_leg(1, 0, _A, filled_qty=Decimal("0.004")))
    assert [(frame["t"], _ids(frame)) for frame in conn.take()] == [("d", [_G1])]


def test_the_hub_refuses_a_trade_groups_publish_without_a_viewer_before_any_frame() -> None:
    """S4a's R1S-02: never the account scope alone; an account event is refused whole."""
    hub, _, _, router = _wired(_stored(1, _A))
    conn = _conn(hub, router, _A)
    for ch in ("orders", "trade_groups"):
        conn.sub(_entry(_A, ch=ch))
    conn.take()
    body = {"trade_groups": [{"id": _G1, "status": "open", "updated_at_ms": 1}]}
    event = [("trade_groups", body), ("orders", {"orders": []})]
    with pytest.raises(ValueError, match="a trade_groups publish needs its viewer"):
        hub.publish("trade_groups", body, account=_A)
    with pytest.raises(ValueError, match="a trade_groups publish needs its viewer"):
        hub.publish_private(_A, event)
    assert conn.take() == []


def _manager(*grants: AccountGrant) -> PrincipalSnapshot:
    return replace(principal(), account_grants=grants)


def test_the_viewer_needs_every_leg_and_fails_closed_on_none() -> None:
    owner = PrincipalSnapshot(UUID(int=1), frozenset({"owner"}), frozenset())
    on_a, frozen_b = AccountGrant(_A, True, False, False), AccountGrant(_B, True, False, True)
    assert trade_group_frame_visible(frozenset({_A, _B}), owner)
    assert trade_group_frame_visible(frozenset({_A}), _manager(on_a))
    assert not trade_group_frame_visible(frozenset({_A, _B}), _manager(on_a))
    assert not trade_group_frame_visible(frozenset({_A, _B}), _manager(on_a, frozen_b))
    assert not trade_group_frame_visible(frozenset(), owner)  # no leg: no one's (R1S-03)
    assert not trade_group_frame_visible(frozenset(), _manager())


def test_frames_are_counted_by_kind_alone() -> None:
    """A snapshot per subscription built and a delta per subscription a publish reached (none,
    then two), each a series of `kind`; no account in any label (C-12.6)."""
    hub, topic, metrics, router = _wired(_stored(1, _A), _stored(2, _A, _B))
    for grant in (_A, _A, _B):
        _conn(hub, router, grant).sub(_entry(grant))

    def counted() -> dict[str, str]:
        text = generate_latest(metrics.registry).decode()
        assert str(_A) not in text and str(_B) not in text
        prefix = 'cv_tradegroup_ws_frames_total{env="demo",kind="'
        rows = (line.removeprefix(prefix) for line in text.splitlines() if line.startswith(prefix))
        return dict(row.split('"} ') for row in rows)

    topic.leg_changed(_leg(2, 0, _A, filled_qty=Decimal("0.004")))  # no one holds A and B
    assert counted() == {"snapshot": "3.0", "delta": "0.0"}
    topic.leg_changed(_leg(1, 0, _A, filled_qty=Decimal("0.004")))  # the two on A
    assert counted() == {"snapshot": "3.0", "delta": "2.0"}


def test_a_frame_lost_to_a_failed_publish_is_made_up_by_a_resync_from_the_model() -> None:
    """A `select` that raises stops the fan-out part-way (§10.1): the other subscriber misses
    the terminal frame and is re-snapshotted (`upstream_desync`) from the model, group gone."""
    hub, topic, _, router = _wired(_stored(1, _A))
    broken, healthy = _conn(hub, router, _A), _conn(hub, router, _A)
    _, bad = broken.sub(_entry(_A))
    for ch in ("trade_groups", "orders"):  # `orders` is not re-snapshotted
        healthy.sub(_entry(_A, ch=ch))
    broken.take()
    healthy.take()
    bad.effective["status"] = 7  # a corrupt option: its `select` raises
    with capture_logs():
        topic.group_changed(_group(1, "closed"))
    [snap] = healthy.take()  # the `trade_groups` one alone
    assert (snap["t"], snap["meta"]["reason"], _ids(snap)) == ("snap", "upstream_desync", [])
