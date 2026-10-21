"""E40-T04 PR-B wiring: the firing store that wakes the dispatcher, the alerts module's topic
lifecycle, and `create_app()` serving the `alerts` family through the module's adapter and telling
it of every change the inbox routes and the dispatcher commit."""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.alerts.ports import FiringStore, WakingFiringStore
from candleviewer.alerts.service import AlertsService
from candleviewer.alerts.ws_topic import AlertsTopic
from tests.alerts._alerts_ws import World, is_attached

_FIRED = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
#: Every argument of `FiringStore.record_firing`, each a distinct value: a swapped or dropped one
#: shows in what the inner store received.
_FIRING: dict[str, Any] = {
    "alert_id": "alert-1", "user_id": "user-1", "channels": ("in_app", "desktop"),
    "status": "queued", "title": "BTC reclaims 64k", "body": "BTCUSDT crossed 64000",
    "context": {"symbol": "BTCUSDT"}, "fired_at": _FIRED, "once": False, "bump": True,
    "disable": False,
}  # fmt: skip


class _Store:
    def __init__(self, ids: list[int] | None) -> None:
        self.ids = ids
        self.seen: list[dict[str, Any]] = []  # the arguments of each `record_firing`

    async def load_live(self) -> Sequence[Any]:
        return ["live"]

    async def get(self, alert_id: str) -> Any:
        return {"id": alert_id}

    async def record_firing(self, **kw: Any) -> list[int] | None:
        self.seen.append(kw)
        return self.ids


async def _fire(store: WakingFiringStore, **over: Any) -> list[int] | None:
    return await store.record_firing(**_FIRING | over)


async def test_a_committed_firing_with_queued_rows_wakes_the_dispatcher() -> None:
    woke: list[bool] = []
    store = WakingFiringStore(_Store([1, 2]), lambda: woke.append(True))
    assert await _fire(store) == [1, 2] and woke == [True]


@pytest.mark.parametrize(("ids", "status"), [(None, "queued"), ([], "queued"), ([3], "suppressed")])
async def test_nothing_to_deliver_wakes_nothing(ids: list[int] | None, status: str) -> None:
    woke: list[bool] = []
    store = WakingFiringStore(_Store(ids), lambda: woke.append(True))
    await _fire(store, status=status)
    assert woke == []


@pytest.mark.parametrize(
    "over",
    [{}, {"once": True}, {"disable": True}, {"bump": False},
     {"once": True, "disable": True, "bump": False}],
)  # fmt: skip
async def test_the_wrapper_forwards_every_argument_unchanged(over: dict[str, Any]) -> None:
    """`once` and `disable` carry the conditional-disarm semantics (the inner store's `UPDATE ...
    WHERE enabled` decides who won): a dropped or defaulted one changes what a firing does."""
    inner = _Store([1])
    assert await _fire(WakingFiringStore(inner, lambda: None), **over) == [1]
    assert inner.seen == [_FIRING | over]


async def test_a_firing_without_disable_forwards_the_protocols_default() -> None:
    inner = _Store([1])
    kw = {k: v for k, v in _FIRING.items() if k != "disable"}
    await WakingFiringStore(inner, lambda: None).record_firing(**kw)
    assert inner.seen == [kw | {"disable": False}]


def test_the_wrapper_has_every_parameter_of_the_store_protocol() -> None:
    """A parameter added to `FiringStore.record_firing` must be forwarded: this table, and so the
    forwarding test above, has to grow with it."""
    declared = set(inspect.signature(FiringStore.record_firing).parameters) - {"self"}
    assert set(_FIRING) == declared
    wrapped = set(inspect.signature(WakingFiringStore.record_firing).parameters) - {"self"}
    assert wrapped == declared


async def test_a_wake_that_raises_does_not_undo_a_committed_firing() -> None:
    def wake() -> None:
        raise RuntimeError("wake refused")

    with capture_logs() as logs:
        assert await _fire(WakingFiringStore(_Store([1, 2]), wake)) == [1, 2]
    assert [(e["event"], e["log_level"], e["error"]) for e in logs] == [
        ("alerts_dispatcher_wake_failed", "warning", "RuntimeError")
    ]
    assert "wake refused" not in repr(logs)  # the error's type, never its message (C-12.6)


async def test_the_wrapper_passes_reads_through() -> None:
    store = WakingFiringStore(_Store([1]), lambda: None)
    assert await store.load_live() == ["live"] and await store.get("a") == {"id": "a"}


async def test_the_module_runs_the_topic_without_an_evaluator() -> None:
    w = World()
    svc = AlertsService()
    svc.bind_topic(w.topic)
    await svc.start(None)  # type: ignore[arg-type]  # ctx is unused on this path
    assert w.running()
    await svc.stop(1.0)
    assert not w.running() and w.tasks() == []


def test_create_app_serves_alerts_through_the_modules_adapter() -> None:
    from candleviewer.app import create_app
    from candleviewer.settings import Settings

    app = create_app(Settings(alerts_evaluator_enabled=False))
    topic = app.state.app_context.alerts.topic
    assert isinstance(topic, AlertsTopic)
    assert not is_attached(topic)  # the fake backend: no reader, no I/O, subscriptions pending
    router = app.state.ws_registry.services.snapshots
    assert router._sources["alerts"] is topic


def test_the_dispatcher_and_the_evaluator_are_wired_to_the_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import candleviewer.app as app_mod
    from candleviewer.settings import Settings

    seen: dict[str, Any] = {}
    real_dispatcher, real_factory = app_mod._alert_dispatcher, app_mod._alert_evaluator_factory

    def dispatcher(*a: Any, **kw: Any) -> Any:
        seen["on_change"] = kw.get("on_change")
        d = real_dispatcher(*a, **kw)
        seen["dispatcher"] = d
        return d

    def factory(*a: Any, **kw: Any) -> Any:
        seen["wake"], seen["feed"] = kw.get("wake"), kw.get("feed")
        return real_factory(*a, **kw)

    monkeypatch.setattr(app_mod, "_alert_dispatcher", dispatcher)
    monkeypatch.setattr(app_mod, "_alert_evaluator_factory", factory)
    app = app_mod.create_app(Settings(alerts_evaluator_enabled=True))
    topic = app.state.app_context.alerts.topic
    assert seen["on_change"] == topic.deliveries_changed
    assert seen["wake"] == seen["dispatcher"].notify
    assert seen["feed"] is app.state.machine_feed  # E17-T08: the evaluator's charts publish (§6.4)


@pytest.mark.parametrize("evaluator_enabled", [False, True])
def test_the_inbox_routes_tell_the_topic_of_their_changes(
    monkeypatch: pytest.MonkeyPatch, evaluator_enabled: bool
) -> None:
    """An ack, an ack-all or a desktop report commits a change: only `on_change` carries it to the
    topic, and so to the user's other sockets. The router is mounted whatever the evaluator flag."""
    import candleviewer.app as app_mod
    from candleviewer.api.alert_deliveries import make_alert_deliveries_router
    from candleviewer.settings import Settings

    seen: dict[str, Any] = {}

    def router(*a: Any, **kw: Any) -> Any:
        seen["on_change"] = kw.get("on_change")
        return make_alert_deliveries_router(*a, **kw)

    monkeypatch.setattr(app_mod, "make_alert_deliveries_router", router)
    app = app_mod.create_app(Settings(alerts_evaluator_enabled=evaluator_enabled))
    assert seen["on_change"] == app.state.app_context.alerts.topic.deliveries_changed
