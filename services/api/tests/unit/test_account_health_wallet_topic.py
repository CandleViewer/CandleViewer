"""E27-T04 (#837) W4b: the account health runtime publishes on the `wallet` topic. The start of an
account's monitoring and each state transition are one health-only delta each, and the ticks in
between send none (the discrete transition of the issue's accessibility note); a pushed and a
reconciled refresh are one balance delta each, and a refreshed balance turning stale one more.
AC1, AC2 and AC5 as served payloads, and a fan-out that fails reaches neither the feed nor the
loops. The runtime `create_app` wires (`wire_account_health`), on a fake clock and sleeper and a
fake private socket: no Docker, no network, no wall-clock wait."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from uuid import UUID

from structlog.testing import capture_logs

from candleviewer.accounts.health import HealthState, epoch_ms
from candleviewer.accounts.status import AccountStatusReader
from tests.unit.accounts._fakes import ACC, T0
from tests.unit.accounts._runtime_rig import Rig, snapshot
from tests.unit.accounts._wallet_ws import Conn, manager

Frames = list[tuple[str, dict[str, Any]]]


def _subscriber(rig: Rig) -> Conn:
    conn = Conn(rig.hub, rig.topic, manager(ACC), rig.clock)
    conn.sub(ACC)
    return conn


def _health(frames: Frames) -> list[tuple[str, str, bool]]:
    entries = [entry for _, body in frames for entry in body.get("health", [])]
    return [(entry["state"], entry["reason"], entry["rest_only"]) for entry in entries]


class _FailingFanOut:
    """A hub's `publish` that raises, and counts the deltas it was asked to send."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, ch: str, body: Mapping[str, Any], *, account: UUID) -> int:
        self.calls += 1
        raise RuntimeError("fan-out bug")


async def test_monitoring_start_and_each_transition_are_the_only_health_deltas() -> None:
    rig = Rig()
    conn = _subscriber(rig)
    assert conn.take() == [("snap", {"balances": [], "health": []})]  # not monitored yet
    await rig.boot()  # the tracking loop's first pass: its monitoring starts
    await rig.run(1)
    rig.ws.connect()
    await rig.run(60)  # 120 ticks and 13 pongs
    rig.ws.drop()
    await rig.run(60)  # degraded, then down 30 s after the last pong
    frames = conn.take()
    await rig.close()
    assert [(kind, body["balances"], len(body["health"])) for kind, body in frames] == [
        ("d", [], 1)
    ] * 4
    assert _health(frames) == [
        ("down", "never_connected", False),
        ("healthy", "ws_heartbeat", False),
        ("degraded", "ws_silent", True),
        ("down", "no_success", False),
    ]
    changed = [body["health"][0]["changed_at_ms"] for _, body in frames]
    assert changed == sorted(set(changed))  # each a transition of its own


async def test_a_push_a_turn_to_stale_and_a_read_refresh_are_one_balance_delta_each() -> None:
    rig = Rig(rest=True)
    await rig.boot()
    rig.ws.connect()
    await rig.run(1)
    conn = _subscriber(rig)
    conn.take()
    assert rig.accounts.account_health.wallet_pushed(ACC, snapshot(rig.clock.now()))  # at 1 s
    assert not rig.accounts.account_health.wallet_pushed(ACC, snapshot(T0))  # older: no refresh
    await rig.run(65)  # stale after 11 s; the truth-check at 61 s refreshes it
    frames = conn.take()
    await rig.close()
    stale = [[item["stale"] for item in body["balances"]] for _, body in frames]
    assert stale == [[False], [True], [False]] and len(rig.rest.calls) == 1
    assert [(kind, "health" in body) for kind, body in frames] == [("d", False)] * 3


async def test_rest_polling_taking_over_is_one_degraded_rest_only_delta_then_a_balance() -> None:
    rig = Rig(rest=True)
    conn = _subscriber(rig)
    conn.take()
    await rig.boot()  # monitored from here: down, never connected, so read every 10 s
    await rig.run(10.2)  # the read at 10 s succeeds: REST polling has taken over
    frames = conn.take()
    served = _subscriber(rig)
    [(_, snap)] = served.take()
    await rig.close()
    assert _health(frames) == [("down", "never_connected", False), ("degraded", "rest_only", True)]
    assert [len(body["balances"]) for _, body in frames] == [0, 0, 1]
    assert _health([("snap", snap)]) == [("degraded", "rest_only", True)]
    assert [item["stale"] for item in snap["balances"]] == [False]


async def test_a_dropped_stream_with_rest_polling_working_is_one_degraded_ws_silent_delta() -> None:
    rig = Rig(rest=True)
    await rig.boot()
    rig.ws.connect()
    await rig.run(7)  # pongs at 0 and 5 s
    conn = _subscriber(rig)
    conn.take()
    rig.ws.drop()
    await rig.run(14)  # REST polling takes over: its reads at 10 and 20 s succeed
    frames = conn.take()
    [(_, snap)] = _subscriber(rig).take()
    await rig.close()
    # one health delta, at the drop: the transition's reason, `rest_only` true; each read then sends
    # its balance and no health. A new subscriber is told the derived reason, `rest_only`.
    assert _health(frames) == [("degraded", "ws_silent", True)]
    assert [len(body["balances"]) for _, body in frames] == [0, 1, 1]
    assert _health([("snap", snap)]) == [("degraded", "rest_only", True)]


async def test_a_connected_account_is_served_healthy_with_its_heartbeat_age() -> None:
    rig = Rig()
    await rig.boot()
    rig.ws.connect()
    await rig.run(7)  # pongs at 0 and 5 s
    [(_, snap)] = _subscriber(rig).take()
    await rig.close()
    [entry] = snap["health"]
    assert (entry["state"], entry["heartbeat_age_ms"]) == ("healthy", 2000)
    assert entry["rest_only"] is False


async def test_with_the_stream_and_the_truth_check_failed_the_served_balance_is_stale() -> None:
    rig = Rig()  # the production REST port: every truth-check is a failed attempt
    await rig.boot()
    rig.ws.connect()
    await rig.run(0)
    early = _subscriber(rig)
    assert rig.accounts.account_health.wallet_pushed(ACC, snapshot(rig.clock.now()))  # at 0 s
    rig.ws.drop()  # the stream is gone too: a read every 10 s, each one failing
    await rig.run(21)
    [(_, snap)] = _subscriber(rig).take()
    status = AccountStatusReader(rig.runtime.monitor, rig.runtime.wallets).status(ACC)
    frames = early.take()[1:]  # after its snapshot
    await rig.close()
    since = T0 + timedelta(seconds=10)
    [item] = snap["balances"]
    assert (item["stale"], item["stale_since_ms"]) == (True, epoch_ms(since))
    assert (status.balance_stale, status.balance_stale_since) == (True, since)
    assert rig.runtime.wallets.risk_sizing_available(ACC) is False
    # the push, the drop and the turn to stale; the failed reads at 10 and 20 s send nothing
    shape = [([i["stale"] for i in body["balances"]], "health" in body) for _, body in frames]
    assert shape == [([False], False), ([], True), ([True], False)]


async def test_a_failing_fan_out_reaches_neither_the_evidence_calls_nor_the_loops() -> None:
    rig = Rig()
    fan_out = _FailingFanOut()
    rig.topic._publish = fan_out
    with capture_logs() as logs:
        await rig.boot()  # its monitoring starts: a health delta, which fails
        moved = rig.accounts.account_health.ws_heartbeat(ACC)
        await rig.run(31)  # no evidence since: degraded at 10 s, down at 30 s
        fault = rig.runtime.fault
    await rig.close()
    failed = [entry for entry in logs if entry["event"] == "wallet_topic.publish_failed"]
    assert moved is not None and moved.to_state is HealthState.HEALTHY
    # four deltas failed (start, healthy, degraded, down): one line, the rest held back
    assert (fault, fan_out.calls, len(failed)) == (None, 4, 1)
    assert rig.dms.calls == [(ACC, "no_success")]
