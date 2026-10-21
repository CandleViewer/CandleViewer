"""tests/xstate_contract/test_state_feed.py — E17-T08 PR 2b: `CvStateFeedPlugin` (23 §6.4) on the
library runtime, through `factory.build` and `factory.restore` only (C-2.19): what each hook
publishes, the §15.10 projection of every stable state of the 16 public charts (equal to
`admin.inspector.published_state`), the restore bring-up (CV-C66') and the `SUMMARY` allow-list."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from xstate_statemachine import Interpreter, SimulatedClock

import candleviewer.statechart.bindings.b16_session  # noqa: F401  (registers "session")
from candleviewer.admin.inspector import published_state
from candleviewer.statechart import build, persistence
from candleviewer.statechart import factory as cv_factory
from candleviewer.statechart.plugins import CvStateFeedPlugin, FeedBinding, feed_plugins
from candleviewer.statechart.registry import Registry
from candleviewer.ws.machine_payload import check_machine_payload
from candleviewer.ws.topics import MACHINE_ENTITY_KIND
from tests.xstate_contract import _harness as h
from tests.xstate_contract.plugin_fixtures import binding_plugins  # noqa: F401 - registers bindings

KIND, SID = "test.plugins_min", "0a000000-0000-4000-8000-000000000016"
_FIXTURE = Registry(machines_dir=Path(__file__).resolve().parent / "plugin_fixtures")
_COMMITTED = Registry()  # the charts as committed, apart from the one `feed_plugins` falls back to


class Port:
    """A `MachineStatePort` that is its own handle: what the feed published, as JSON carries it."""

    environment = "demo"

    def __init__(self) -> None:
        self.published, self.lasts, self.ops = list[dict[str, Any]](), list[bool](), list[str]()
        self.bound, self._ms = list[FeedBinding](), 0

    def now_ms(self) -> int:
        self._ms += 1
        return self._ms

    def bind(self, binding: FeedBinding) -> Port:
        self.bound.append(binding)
        return self

    def publish(self, payload: Mapping[str, Any], *, last: bool) -> None:
        self.published.append(json.loads(json.dumps(payload)))
        self.lasts.append(last)
        self.ops.append("publish")

    def remove(self) -> None:
        self.ops.append("remove")


def _stub(value: Any, tags: Iterable[str] = (), trips: int = 0, **context: Any) -> SimpleNamespace:
    """The public attributes the feed reads, on a non-parallel machine."""
    machine = SimpleNamespace(type="compound")
    return SimpleNamespace(
        value=value, tags=set(tags), chain_trips=trips, context=context, machine=machine
    )


async def _fixture_machine(port: Port) -> tuple[Interpreter[Any], CvStateFeedPlugin]:
    (feed,) = feed_plugins(port, FeedBinding(KIND), registry=_FIXTURE)
    res = await build(
        KIND, clock=SimulatedClock(), lane="platform", registry=_FIXTURE, plugins=(feed,)
    )
    return res.interpreter, feed


async def _send(interp: Interpreter[Any], event: str) -> None:
    await interp.send(event, wait=True)
    await h.settle()


async def test_the_init_record_and_every_transition_publish_and_a_rollback_does_not() -> None:
    port = Port()
    interp, feed = await _fixture_machine(port)
    try:
        (first,) = port.published
        keys = "machine_kind state tags degraded machine_hash environment updated_at_ms"
        assert set(first) == set(
            keys.split()
        )  # no `regions` (flat), no `context_summary` (no list)
        assert (first["machine_kind"], first["state"], first["tags"]) == (KIND, "idle", [])
        assert (first["degraded"], first["environment"]) == (False, "demo")
        assert (first["updated_at_ms"], first["machine_hash"]) == (1, _FIXTURE.hash(KIND))
        assert port.bound == [FeedBinding(KIND)] and port.lasts == [False]
        for event in ("GO", "BACK", "NOOP"):  # external, external, internal with no state change
            await _send(interp, event)
        assert [p["state"] for p in port.published] == ["idle", "busy", "idle", "idle"]
        await _send(interp, "FAIL")  # its action raises under `actionErrorPolicy: rollback`
        assert len(port.published) == 4 and interp.current_state_ids == {f"{KIND}.idle"}
        assert feed.hook_errors == 0
    finally:
        await interp.stop()


async def test_a_chain_trip_flips_degraded_once_and_a_stop_removes_the_entry_once() -> None:
    port = Port()
    interp, feed = await _fixture_machine(port)
    interp.send("PING")  # re-sends itself until `maxIterations`
    await h.settle()
    degraded = [p["degraded"] for p in port.published]
    assert interp.chain_trips == 1 and degraded == [False] * (len(degraded) - 1) + [True]
    before, trip = port.published[-2:]
    assert trip["state"] == before["state"] and trip["updated_at_ms"] > before["updated_at_ms"]
    await interp.stop()
    await interp.stop()
    assert port.ops.count("remove") == 1 and feed.hook_errors == 0


def test_an_error_status_removes_the_entry() -> None:
    port = Port()
    (feed,) = feed_plugins(port, FeedBinding("session", SID))
    feed.on_error(None, RuntimeError("boom"))
    assert port.ops == ["remove"] and feed.hook_errors == 0


async def test_a_session_publishes_regions_and_every_terminal_payload_is_a_last() -> None:
    """B16 `REVOKE` fires two transitions, `elevation` normal then dead, and both hold `terminal`:
    the entity's final payload is the second."""
    port = Port()
    plugins = feed_plugins(port, FeedBinding("session", SID))
    res = await build("session", clock=SimulatedClock(), lane="platform", plugins=plugins)
    interp = res.interpreter
    try:
        (first,) = port.published
        assert (first["state"], first["tags"]) == ("pending_mfa", ["not_elevated"])
        assert first["regions"] == {"auth": "pending_mfa", "elevation": "normal"}
        assert first["context_summary"] == {"mfa_satisfied": False, "step_up_failures": 0}
        assert first["machine_hash"] == _COMMITTED.hash("session")
        await _send(interp, "MFA_OK")
        await _send(interp, "REVOKE")
        states = [p["state"] for p in port.published]
        assert states == ["pending_mfa", "active", "revoked", "revoked"]
        assert port.lasts == [False, False, True, True]
        assert port.published[-2]["tags"] == ["not_elevated", "terminal"]
        assert port.published[-1]["regions"] == {"auth": "revoked", "elevation": "dead"}
    finally:
        await interp.stop()
    assert port.ops[-1] == "remove"  # the registry keeps a terminal entry


async def test_a_restore_publishes_the_restored_state_once_after_start_before_the_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restored `start()` enters no state, so no `on_transition` fires (CV-C66')."""
    keys, repo, key = h.Keys(), h.Repo(), persistence.MachineKey("session", SID, "demo")
    source = (await build("session", clock=SimulatedClock(), lane="platform")).interpreter
    await _send(source, "MFA_OK")
    await _send(source, "STEP_UP_OK")
    source.chain_trips = 1
    journal = persistence.InMemoryDrainJournal()
    await persistence.Persister(
        repo=repo,
        journal=journal,
        audit=h.Audit(),
        seal=persistence.hmac_sealer(keys, _COMMITTED.get("session")),
        machine_hash_of=_COMMITTED.hash,
        pager=h.Pager(),
    ).persist(source, key=key)
    port, replay, seen = Port(), journal.replay_once, list[int]()

    async def spy(*args: Any) -> persistence.ReplayReport:
        seen.append(len(port.published))  # what was out when the replay began
        return await replay(*args)

    monkeypatch.setattr(journal, "replay_once", spy)
    latch, no_plugins, clock = persistence.ChainTripLatch(), lambda _key: [], SimulatedClock()
    restorer = persistence.Restorer(
        _COMMITTED, keys, journal, h.Audit(), h.Pager(), latch, no_plugins, clock, "platform"
    )
    feed = feed_plugins(port, FeedBinding("session", SID), registry=_COMMITTED)
    res = await cv_factory.restore(restorer, key, repo.rows[key], extra_plugins=feed)
    try:
        (payload,) = port.published
        assert seen == [1] and res.degraded and payload["degraded"] is True
        assert payload["regions"] == {"auth": "active", "elevation": "elevated"}
        assert (payload["state"], payload["tags"]) == ("active", ["elevated"])
        assert payload["machine_hash"] == _COMMITTED.hash("session") == res.machine_hash
        await _send(res.interpreter, "ELEVATION_DEADLINE")  # the plugin stays attached
        assert [p["regions"]["elevation"] for p in port.published] == ["elevated", "normal"]
    finally:
        await res.interpreter.stop()


def test_a_bring_up_that_raises_is_contained_and_a_plugin_without_one_is_skipped() -> None:
    class Refusing(Port):
        def publish(self, payload: Mapping[str, Any], *, last: bool) -> None:
            raise RuntimeError("the registry is gone")

    plugin = CvStateFeedPlugin(
        Refusing(), FeedBinding("leg"), machine_hash="0" * 64, environment="demo", now_ms=lambda: 1
    )
    interp = _stub("open")
    interp.plugins = [object(), plugin]
    cv_factory.cv_bring_up_restored(interp)  # nothing escapes into the restore
    assert plugin.hook_errors == 1


_ORDER = {"symbol": "BTCUSDT", "halted_by_kill": False, "recon_misses": 2}
_OFF = {"symbol": None, "halted_by_kill": 0, "recon_misses": True}
_ALERT = {"severity": "critical", "delivery_attempts": 3, "storm_count": -1}
_BOOK = {"symbol": "BTCUSDT", "resync_count": 0}
_BAD = {"symbol": "btcusdt", "gap_count_24h": 1.5}
_KILL = {"scope": "accounts", "cancel_working": True}
_SESSION = {"mfa_satisfied": True, "step_up_failures": 0}
#: id: chart, entity id, context, what is sent (`None`: no field)
_SUMMARIES = {
    "order-allow-list": ("order", None, {**_ORDER, "_fault": 1, "sl_deadline_us": 5}, _ORDER),
    "order-off-type": ("order", None, _OFF, None),
    "alert-no-severity": ("alert", None, _ALERT, {"delivery_attempts": 3}),
    "book-entity-symbol": ("book", "BTCUSDT", {**_BOOK, "symbol": None}, _BOOK),
    "recording-off-type": ("recording", "ETHUSDT", _BAD, None),
    "kill_switch-off-type": ("kill_switch", None, {**_KILL, "flatten": "yes"}, _KILL),
    "kill_switch-bad-scope": ("kill_switch", None, {"scope": "all"}, None),
    "leg-none": ("leg", None, {"symbol": "BTCUSDT"}, None),
    "session-no-user": ("session", None, {**_SESSION, "user_id": SID}, _SESSION),
}


@pytest.mark.parametrize(
    ("chart", "entity", "context", "sent"), _SUMMARIES.values(), ids=list(_SUMMARIES)
)
def test_the_summary_is_allow_listed_and_typed_per_chart(
    chart: str, entity: str | None, context: dict[str, Any], sent: Any
) -> None:
    port = Port()
    (feed,) = feed_plugins(port, FeedBinding(chart, entity))
    feed.on_transition(_stub("x", **context), None, None, None)
    assert [p.get("context_summary") for p in port.published] == [sent] and feed.hook_errors == 0


def test_a_terminal_payload_is_always_a_last_and_a_trip_before_the_first_payload_waits() -> None:
    port = Port()
    (feed,) = feed_plugins(port, FeedBinding("leg"))
    feed.on_chain_budget_exceeded(_stub("open", trips=1), RuntimeError("trip"), None)
    assert port.published == []  # nothing to re-send yet: the next payload carries the flag
    feed.on_transition(_stub("open", trips=1), None, None, None)
    assert [p["degraded"] for p in port.published] == [True] and port.lasts == [False]
    ended = _stub("filled", ["terminal"])
    feed.on_transition(ended, None, None, None)
    feed.on_transition(_stub("filled", ["protected", "terminal"]), None, None, None)
    assert port.lasts == [False, True, True]
    for _ in range(2):  # a trip after the end re-sends that payload with the flag, once
        feed.on_chain_budget_exceeded(ended, RuntimeError("trip"), None)
    assert port.lasts == [False, True, True, True] and port.published[-1]["degraded"] is True
    assert port.published[-1]["tags"] == ["protected", "terminal"] and feed.hook_errors == 0
    assert feed_plugins(None, FeedBinding("leg")) == ()  # without a port: no plugin


@pytest.mark.parametrize("machine", sorted(MACHINE_ENTITY_KIND))
async def test_every_stable_state_projects_the_inspectors_state_and_a_valid_payload(
    machine: str, charts: h.Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    h.instrument(machine, monkeypatch, "async_def")
    chart, entity = _COMMITTED.get(machine), "BTCUSDT" if machine in ("book", "recording") else None
    for source in h.stable_states(chart):
        port, reg = Port(), charts.registry(machine, chart, source)
        feed = feed_plugins(port, FeedBinding(machine, entity), registry=reg)
        lane = h.lane_of(machine)
        res = await build(machine, clock=SimulatedClock(), lane=lane, registry=reg, plugins=feed)
        try:
            parts = [i.split(".") for i in res.interpreter.current_state_ids]  # leaves + ancestors
            active = {".".join(p[:n]) for p in parts for n in range(1, len(p) + 1)}
            payload = port.published[-1]
            assert payload["state"] == published_state(chart, frozenset(active)), (machine, source)
            assert check_machine_payload(MACHINE_ENTITY_KIND[machine], payload) is None, source
            assert payload["machine_hash"] == reg.hash(machine) == res.machine_hash
        finally:
            await res.interpreter.stop()
