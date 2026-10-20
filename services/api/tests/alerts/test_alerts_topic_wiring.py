"""E40-T04 PR-B wiring: the firing store that wakes the dispatcher, the alerts module's topic
lifecycle, and `create_app()` serving the `alerts` family through the module's adapter."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from _alerts_ws import World

from candleviewer.alerts.ports import WakingFiringStore
from candleviewer.alerts.service import AlertsService
from candleviewer.alerts.ws_topic import AlertsTopic

_FIRED = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


class _Store:
    def __init__(self, ids: list[int] | None) -> None:
        self.ids, self.calls = ids, 0

    async def load_live(self) -> Sequence[Any]:
        return ["live"]

    async def get(self, alert_id: str) -> Any:
        return {"id": alert_id}

    async def record_firing(self, **kw: Any) -> list[int] | None:
        self.calls += 1
        return self.ids


async def _fire(store: WakingFiringStore, status: str = "queued") -> list[int] | None:
    return await store.record_firing(
        alert_id="a", user_id="u", channels=("in_app",), status=status, title="t", body="",
        context={}, fired_at=_FIRED, once=False, bump=True,
    )  # fmt: skip


async def test_a_committed_firing_with_queued_rows_wakes_the_dispatcher() -> None:
    woke: list[bool] = []
    store = WakingFiringStore(_Store([1, 2]), lambda: woke.append(True))
    assert await _fire(store) == [1, 2] and woke == [True]


@pytest.mark.parametrize(("ids", "status"), [(None, "queued"), ([], "queued"), ([3], "suppressed")])
async def test_nothing_to_deliver_wakes_nothing(ids: list[int] | None, status: str) -> None:
    woke: list[bool] = []
    store = WakingFiringStore(_Store(ids), lambda: woke.append(True))
    await _fire(store, status)
    assert woke == []


async def test_the_wrapper_passes_reads_through() -> None:
    store = WakingFiringStore(_Store([1]), lambda: None)
    assert await store.load_live() == ["live"] and await store.get("a") == {"id": "a"}


async def test_the_module_runs_the_topic_without_an_evaluator() -> None:
    topic = World().topic
    svc = AlertsService()
    svc.bind_topic(topic)
    await svc.start(None)  # type: ignore[arg-type]  # ctx is unused on this path
    assert topic._worker is not None and not topic._worker.done()
    await svc.stop(1.0)
    assert topic._worker is None


def test_create_app_serves_alerts_through_the_modules_adapter() -> None:
    from candleviewer.app import create_app
    from candleviewer.settings import Settings

    app = create_app(Settings(alerts_evaluator_enabled=False))
    topic = app.state.app_context.alerts.topic
    assert isinstance(topic, AlertsTopic)
    assert topic._reader is None  # the fake backend: no reader, no I/O, subscriptions pending
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
        seen["wake"] = kw.get("wake")
        return real_factory(*a, **kw)

    monkeypatch.setattr(app_mod, "_alert_dispatcher", dispatcher)
    monkeypatch.setattr(app_mod, "_alert_evaluator_factory", factory)
    app = app_mod.create_app(Settings(alerts_evaluator_enabled=True))
    topic = app.state.app_context.alerts.topic
    assert seen["on_change"] == topic.deliveries_changed
    assert seen["wake"] == seen["dispatcher"].notify
