"""Unit (E42-T05, #966 BK-15): `cv_incidents_open`, the unresolved incidents (`open` or
`acknowledged`) of the read model: the count the overview shows as `incidents_open`. A bounded
refresher reads it into memory and a scrape serves it from there, with `env`. The series has no
sample before a read has succeeded, after one has failed, or once the last good read is older than
three intervals: never a stale value, and never a 0 that was not read."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, ClassVar

import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

import candleviewer.admin_wiring as wiring
from candleviewer.admin.ops.incident_metrics import (
    EXPORTED_NAMES,
    OpenIncidentsGauge,
    export_incident_metrics,
)
from candleviewer.app import create_app
from candleviewer.observability.metrics import CollectorRegistry, generate_latest
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Settings
from candleviewer.storage.repositories.system_settings_sqlalchemy import SqlAlchemySystemSettings

SPEC = next(s for s in CATALOGUE if s.name == "cv_incidents_open")
HANG: Any = object()  # a read that never returns
DEMO = {"env": "demo"}


class _Source:
    """The overview's `open_incidents` count: each call serves the next answer, raises it when it
    is an exception, or never returns for `HANG`."""

    def __init__(self, *answers: Any) -> None:
        self._answers = list(answers)

    async def open_incidents(self) -> int:
        answer = self._answers.pop(0)
        if answer is HANG:
            await asyncio.Event().wait()
        if isinstance(answer, BaseException):
            raise answer
        return int(answer)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _family(gauge: OpenIncidentsGauge) -> Any:
    registry = CollectorRegistry()
    collector = export_incident_metrics(registry, env="demo", gauge=gauge)
    try:
        (family,) = registry.collect()
    finally:
        collector.close()
    return family


def _served(gauge: OpenIncidentsGauge) -> list[tuple[dict[str, str], float]]:
    return [(s.labels, s.value) for s in _family(gauge).samples]


def test_the_series_is_the_catalogues_unlabelled_gauge() -> None:
    assert EXPORTED_NAMES == {"cv_incidents_open"}
    assert (SPEC.kind, SPEC.labels, SPEC.status, SPEC.owner_epic) == ("gauge", (), "live", "E42")
    assert (SPEC.exported, SPEC.max_series) == (True, 1)  # served by its collector, one series
    family = _family(OpenIncidentsGauge(None))
    assert (family.name, family.type, family.documentation) == (
        "cv_incidents_open",
        "gauge",
        SPEC.help,
    )


async def test_a_read_serves_the_overviews_unresolved_count_with_env() -> None:
    gauge = OpenIncidentsGauge(_Source(3))
    await gauge.refresh()
    assert _served(gauge) == [(DEMO, 3.0)]


async def test_a_count_of_zero_is_a_sample_unlike_no_read() -> None:
    gauge = OpenIncidentsGauge(_Source(0))
    assert _served(gauge) == []  # never read: not a 0
    await gauge.refresh()
    assert _served(gauge) == [(DEMO, 0.0)]  # read, and none unresolved


@pytest.mark.parametrize(
    "failure",
    [OSError("store down"), RuntimeError("refused"), TimeoutError()],
    ids=["os", "runtime", "timeout"],
)
async def test_a_failed_read_drops_the_sample_and_never_keeps_the_last_value(
    failure: Exception,
) -> None:
    gauge = OpenIncidentsGauge(_Source(3, failure, 5))
    seen = []
    for _ in range(3):
        await gauge.refresh()
        seen.append(_served(gauge))
    assert seen == [[(DEMO, 3.0)], [], [(DEMO, 5.0)]]  # back with the next good read


async def test_a_failed_read_is_logged_by_its_class_only() -> None:
    gauge = OpenIncidentsGauge(_Source(RuntimeError("postgresql://cv:" + "hunter2" + "@db/cv")))
    with capture_logs() as logs:
        await gauge.refresh()
    assert [(e["event"], e["error"], e["log_level"]) for e in logs] == [
        ("incidents.open_gauge_read_failed", "RuntimeError", "warning")
    ]
    assert "hunter2" not in repr(logs)


async def test_a_read_that_never_returns_is_a_failed_read() -> None:
    gauge = OpenIncidentsGauge(_Source(3, HANG), timeout_s=0.05)
    await gauge.refresh()
    await gauge.refresh()  # outlasts its bound, so it is a failed read: the 3 is not kept
    assert _served(gauge) == []


async def test_a_sample_older_than_three_intervals_is_not_served() -> None:
    clock = _Clock()
    gauge = OpenIncidentsGauge(_Source(3, 4), clock=clock, interval_s=30.0)
    await gauge.refresh()
    clock.now += 90.0
    assert _served(gauge) == [(DEMO, 3.0)]  # three intervals old: still the latest read
    clock.now += 0.5
    assert _served(gauge) == []  # a stopped or stuck refresher must not leave a value to lie
    await gauge.refresh()
    assert _served(gauge) == [(DEMO, 4.0)]


async def test_a_cancelled_read_is_never_swallowed() -> None:
    gauge = OpenIncidentsGauge(_Source(asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await gauge.refresh()


async def test_without_a_store_there_is_never_a_sample_and_no_loop() -> None:
    gauge = OpenIncidentsGauge(None)
    await gauge.refresh()
    gauge.start()
    assert _served(gauge) == [] and not gauge.running


async def test_the_loop_reads_at_once_then_every_interval_until_stopped() -> None:
    sleeps: list[float] = []
    parked = asyncio.Event()

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            parked.set()
            await asyncio.Event().wait()  # the third read waits for the test
        await asyncio.sleep(0)

    gauge = OpenIncidentsGauge(_Source(1, 2), sleep=sleep, interval_s=30.0)
    gauge.start()
    gauge.start()  # idempotent: one loop
    await asyncio.wait_for(parked.wait(), 2)
    assert (sleeps, _served(gauge), gauge.running) == ([30.0, 30.0], [(DEMO, 2.0)], True)
    await gauge.stop()
    assert not gauge.running
    await gauge.stop()  # stopped: a no-op


def _real_settings() -> Settings:
    return Settings(  # test-only values, not credentials
        storage_backend="real",
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
        auth_pepper=SecretStr("pepper"),
    )


class _Counts:
    """`SqlAlchemyAdminCounts` stand-in: remembers its engine and environment, counts four."""

    built: ClassVar[list[tuple[Any, str]]] = []

    def __init__(self, relational: Any, *, env: str) -> None:
        self.built.append((relational, env))

    async def open_incidents(self) -> int:
        return 4


@pytest.fixture
def counts(monkeypatch: pytest.MonkeyPatch) -> type[_Counts]:
    _Counts.built = []
    monkeypatch.setattr(wiring, "SqlAlchemyAdminCounts", _Counts)
    return _Counts


async def test_the_fake_backend_has_no_store_so_the_series_has_no_sample(
    counts: type[_Counts],
) -> None:
    gauge = wiring.build_open_incidents_gauge(Settings(storage_backend="fake"))
    await gauge.refresh()
    assert _served(gauge) == [] and counts.built == []  # no reader, no engine


async def test_the_real_backend_reads_the_overviews_count_on_the_admin_engine(
    monkeypatch: pytest.MonkeyPatch, counts: type[_Counts]
) -> None:
    monkeypatch.setattr(wiring, "SqlAlchemyRelationalRepository", lambda dsn, suffix: suffix)
    gauge = wiring.build_open_incidents_gauge(Settings(storage_backend="real"))
    await gauge.refresh()
    assert _served(gauge) == [(DEMO, 4.0)] and counts.built == [("admin", "demo")]


def test_the_real_backend_shares_the_settings_stores_engine(counts: type[_Counts]) -> None:
    shared: Any = object()
    store = SqlAlchemySystemSettings(shared)
    wiring.build_open_incidents_gauge(Settings(storage_backend="real"), system_settings=store)
    assert counts.built == [(shared, "demo")]  # not a second engine


async def test_the_app_serves_its_gauge_on_the_scraped_registry(counts: type[_Counts]) -> None:
    """The production path: `create_app` builds the gauge and its collector; no sample until a
    read, then the count with `env`, under the catalogue's HELP."""
    app = create_app(_real_settings())
    registry = app.state.app_context.metrics
    before = generate_latest(registry).decode()
    assert f"# HELP cv_incidents_open {SPEC.help}\n# TYPE cv_incidents_open gauge\n" in before
    assert "\ncv_incidents_open{" not in before
    await app.state.incidents_open_gauge.refresh()
    assert 'cv_incidents_open{env="demo"} 4.0\n' in generate_latest(registry).decode()


def test_the_fake_app_serves_the_series_without_a_sample_and_without_a_loop() -> None:
    app = create_app()
    assert not app.state.incidents_open_gauge.running
    text = generate_latest(app.state.app_context.metrics).decode()
    assert "# TYPE cv_incidents_open gauge\n" in text and "\ncv_incidents_open{" not in text


def test_the_lifespan_starts_the_apps_gauge() -> None:
    from candleviewer import main

    assert '"incidents_open_gauge"' in inspect.getsource(main._lifespan)
