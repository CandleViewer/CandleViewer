"""#571 (E17-T06, #2521 review): a delta the publish-time check denies is counted and logged.

`SequencingHub.publish` asks `in_scope` of every subscription of the channel. A subscription a
connection still holds while its current principal lacks the family's permission (or, for
`machines`, fails its kind's §6.4 row) is sent nothing, as before; now each such denial adds one to
`cv_ws_publish_denied_total{topic=<family>}` and logs `ws delta denied at publish` at most once per
connection per `DENIED_LOG_INTERVAL_S`, with a `suppressed` count. A subscription the event is
simply not for (another account, another user's alert) is not a denial and moves nothing.
"""

from __future__ import annotations

from dataclasses import replace

from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.ws.machines import MachineEntity
from candleviewer.ws.sequencing import (
    DENIED_LOG_INTERVAL_S,
    PUBLISH_DENIED_FAMILIES,
    SequencingHub,
)
from candleviewer.ws.topics import FAMILIES
from tests.unit.ws._seq_support import ACC_A, ACC_B, USER, Clock, Conn, Source
from tests.unit.ws.test_machines import OID, ON_A, _payload, _world
from tests.unit.ws.test_sequencing import _ALERT, _OTHER_USER, _RECORDER, _scoped

DENIED = "ws delta denied at publish"
LOST = frozenset({Permission.ALERTS_READ, Permission.RECORDING_READ, Permission.POSITIONS_READ})


def _denied(family: str) -> float:
    return REGISTRY.get_sample_value("cv_ws_publish_denied_total", {"topic": family}) or 0.0


def _all_denied() -> dict[str, float]:
    return {family: _denied(family) for family in PUBLISH_DENIED_FAMILIES}


def _positions(hub: SequencingHub) -> Conn:
    conn = Conn(Source(), ACC_A)
    hub.register(conn.authz, conn.emitter)
    _, sub = conn.authz.admit({"ch": "positions", "opts": {"exchange_account_ids": [str(ACC_A)]}})
    assert sub is not None
    sub.snapshot_pending = False
    return conn


def _strip(conn: Conn) -> None:
    """A principal swapped in without its subscriptions being removed (§9.5 part-way)."""
    principal = conn.authz.principal
    conn.authz.principal = replace(principal, permissions=principal.permissions - LOST)


def test_a_denied_delta_is_counted_under_its_family() -> None:
    hub = SequencingHub(clock=Clock())
    conns = [_scoped(hub, "alerts"), _scoped(hub, "recorder"), _positions(hub)]
    for conn in conns:
        _strip(conn)
    before = _all_denied()
    assert hub.publish("alerts", _ALERT, user=USER) == 0
    assert hub.publish("recorder", _RECORDER) == 0
    assert hub.publish("positions", {"positions": []}, account=ACC_A) == 0
    moved = {f: n - before[f] for f, n in _all_denied().items() if n != before[f]}
    assert moved == {"alerts": 1.0, "recorder": 1.0, "positions": 1.0}
    assert all(conn.take() == [] for conn in conns)  # still sent nothing


def test_a_denied_machines_delta_is_counted_under_machines() -> None:
    conn, registry, _ = _world()
    order = MachineEntity("order", OID, ON_A)
    registry.publish(order, _payload())
    conn.sub(order.ch)
    conn.take()
    conn.authz.principal = replace(conn.authz.principal, permissions=frozenset())
    before = _all_denied()
    registry.publish(order, _payload(state="filled"))
    assert conn.take() == []
    moved = {f: n - before[f] for f, n in _all_denied().items() if n != before[f]}
    assert moved == {"machines": 1.0}


def test_the_allowed_path_and_routine_routing_count_nothing() -> None:
    hub = SequencingHub(clock=Clock())
    mine, theirs = _scoped(hub, "alerts"), _scoped(hub, "alerts", _OTHER_USER)
    recorder, positions = _scoped(hub, "recorder"), _positions(hub)
    before = _all_denied()
    with capture_logs() as logs:
        assert hub.publish("alerts", _ALERT, user=USER) == 1  # `theirs`: another user's alert
        assert hub.publish("alerts", _ALERT) == 0  # names no owner: nobody, not a denial
        assert hub.publish("recorder", _RECORDER) == 1
        assert hub.publish("positions", {"positions": []}, account=ACC_A) == 1
        assert hub.publish("positions", {"positions": []}, account=ACC_B) == 0  # not its account
    assert _all_denied() == before
    assert [e for e in logs if e["event"] == DENIED] == []
    assert theirs.take() == [] and mine.take() and recorder.take() and positions.take()


def test_the_warning_is_capped_per_connection_with_a_suppressed_count() -> None:
    clock = Clock()
    hub = SequencingHub(clock=clock)
    first, second = _scoped(hub, "recorder"), _scoped(hub, "recorder", _OTHER_USER)
    for conn in (first, second):
        _strip(conn)
    with capture_logs() as logs:
        for _ in range(5):
            hub.publish("recorder", _RECORDER)
        clock.now += DENIED_LOG_INTERVAL_S - 0.001
        hub.publish("recorder", _RECORDER)  # still inside each connection's window
        clock.now += 0.001
        hub.publish("recorder", _RECORDER)  # the window ended: one line each, with the held count
    lines = [e for e in logs if e["event"] == DENIED]
    ids = [first.authz.connection_id, second.authz.connection_id]
    expected = [
        {
            "event": DENIED,
            "log_level": "warning",
            "connection_id": cid,
            "family": "recorder",
            "suppressed": held,
        }
        for held in (0, 5)
        for cid in ids
    ]
    assert lines == expected  # ids-safe: no account, user, channel text or payload


def test_unregister_forgets_the_connections_log_window() -> None:
    hub = SequencingHub(clock=Clock())
    conn = _scoped(hub, "recorder")
    _strip(conn)
    hub.publish("recorder", _RECORDER)
    assert len(hub._denied_log) == 1
    hub.unregister(conn.authz)
    assert hub._denied_log == {}  # bounded by the live connections


def test_every_private_family_is_bound_at_zero_and_the_label_is_closed() -> None:
    private = {f.family for f in FAMILIES.values() if f.private}
    assert set(PUBLISH_DENIED_FAMILIES) == private
    for family in private:  # a series exists from import, so increase() sees the first denial
        assert (
            REGISTRY.get_sample_value("cv_ws_publish_denied_total", {"topic": family}) is not None
        )
    spec = next(s for s in CATALOGUE if s.name == "cv_ws_publish_denied_total")
    assert (spec.kind, spec.labels, spec.status) == ("counter", ("topic",), "live")
    assert spec.max_series >= len(private)
