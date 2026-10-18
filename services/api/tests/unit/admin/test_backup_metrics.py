"""Unit (E42-T05, #966 BK-5): the backup metrics. The freshness is now minus each kind's last
success, read at scrape from a cache that `start()` loads once, within its budget, and
`record_success()` moves forward; labels are closed sets; nothing is served until
`BACKUPS_CATALOGUED` is set."""

from __future__ import annotations

import asyncio
import inspect
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

import candleviewer.backups_wiring as wiring
from candleviewer.admin.backups import metrics
from candleviewer.admin.backups.catalogue import READ_BUDGET_S
from candleviewer.admin.backups.metrics import BackupFreshness
from candleviewer.app import create_app
from candleviewer.observability.metrics import (
    CollectorRegistry,
    Gauge,
    ReexportCollector,
    generate_latest,
)
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Settings
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from candleviewer.storage.repositories.system_settings_sqlalchemy import SqlAlchemySystemSettings
from tests.unit.admin._backup_fakes import NOW, row
from tests.unit.observability.test_auth_backstop_alert_rules import _route_for, _rule

_H = timedelta(hours=1)
_BOUND = 5.0  # the test's own bound: a load with no budget fails here, never hangs the run
_ALERTS = Path(__file__).resolve().parents[5] / "infra" / "prometheus" / "alerts"
_SHARED: Any = object()  # the admin area's one engine, as the settings store holds it


class _Clock:
    def __init__(self) -> None:
        self.at = NOW

    def __call__(self) -> datetime:
        return self.at


class _Last:
    """BK-3's `last_success_by_kind` in memory: an answer, an error, or a read that never ends."""

    def __init__(
        self, last: dict[str, datetime] | None = None, *, error: Exception | None = None
    ) -> None:
        self.last, self.error, self.calls = dict(last or {}), error, 0

    async def last_success_by_kind(self) -> dict[Any, datetime]:
        self.calls += 1
        if self.error is None:
            return self.last
        if isinstance(self.error, TimeoutError):  # stands for a read that never ends
            await asyncio.Event().wait()
        raise self.error


def _freshness(
    store: _Last | None = None, clock: _Clock | None = None, *, budget_s: float = 2.0
) -> tuple[BackupFreshness, Gauge]:
    """A freshness on a gauge of its own, registered nowhere: no test shares the module's."""
    gauge = Gauge("cv_backup_last_success_age_seconds", "age", ["kind"], registry=None)
    clock = clock or _Clock()
    return BackupFreshness(store, now=clock, budget_s=budget_s, gauge=gauge), gauge


def _ages(gauge: Gauge) -> dict[str, float]:
    return {s.labels["kind"]: s.value for family in gauge.collect() for s in family.samples}


async def test_age_is_now_minus_the_last_success_of_each_kind() -> None:
    freshness, gauge = _freshness(_Last({"pg_dump": NOW - 30 * _H}))
    await freshness.start()
    freshness.record_success(row(1, kind="questdb_snapshot", status="ok", finished_at=NOW - 2 * _H))
    assert _ages(gauge) == {"pg_dump": 108000.0, "questdb_snapshot": 7200.0}


@pytest.mark.parametrize("status", ["ok", "verified", "restored"])
def test_each_success_status_moves_the_age(status: str) -> None:
    freshness, gauge = _freshness()
    freshness.record_success(row(1, status=status, finished_at=NOW - _H))
    assert _ages(gauge) == {"pg_dump": 3600.0}


def test_the_age_follows_the_newest_success_and_never_moves_back() -> None:
    freshness, gauge = _freshness()
    for hours in (3, 1, 40):  # newer, newer again, then an older one that is kept back
        freshness.record_success(row(hours, finished_at=NOW - hours * _H))
    assert _ages(gauge) == {"pg_dump": 3600.0}


def test_the_age_is_computed_at_each_scrape() -> None:
    clock = _Clock()
    freshness, gauge = _freshness(clock=clock)
    freshness.record_success(row(1, finished_at=NOW - _H))
    at_now = _ages(gauge)
    clock.at = NOW + timedelta(minutes=15)  # never frozen at the record
    assert (at_now, _ages(gauge)) == ({"pg_dump": 3600.0}, {"pg_dump": 4500.0})


def test_a_naive_time_never_enters_the_cache() -> None:
    freshness, gauge = _freshness()
    freshness.record_success(row(1, finished_at=datetime(2026, 10, 18, 8)))  # no tzinfo
    assert _ages(gauge) == {}


def test_a_scrape_that_raises_stays_local_to_its_sample() -> None:
    clock = _Clock()
    freshness, gauge = _freshness(clock=clock)
    freshness.record_success(row(1))
    clock.at = cast(Any, None)  # the next age raises: None minus a datetime
    with capture_logs() as logs:
        ages = _ages(gauge)
    assert math.isnan(ages["pg_dump"])
    assert [(e["event"], e["kind"], e["error"]) for e in logs] == [
        ("backups.freshness_scrape_failed", "pg_dump", "TypeError")
    ]


@pytest.mark.parametrize(
    "run",
    [
        {"status": "failed", "error_message": "verify_failed"},
        {"status": "running", "finished_at": None, "verified_at": None},
        {"status": "verified", "deleted_at": NOW},  # its artefact was deleted
        {"status": "ok", "finished_at": None},  # never finished
    ],
    ids=["failed", "running", "deleted", "unfinished"],
)
def test_failed_running_and_deleted_runs_are_never_a_success(run: dict[str, Any]) -> None:
    freshness, gauge = _freshness()
    freshness.record_success(row(1, **run))
    assert _ages(gauge) == {}


async def test_a_kind_that_never_succeeded_has_no_sample() -> None:
    freshness, gauge = _freshness(_Last({"pg_dump": NOW - _H}))
    await freshness.start()
    freshness.record_success(row(1, kind="config_bundle", status="failed"))
    assert set(_ages(gauge)) == {"pg_dump"}  # no sample for the other four: not 0, not +Inf


def test_a_kind_outside_the_closed_set_never_makes_a_series() -> None:
    freshness, gauge = _freshness()
    freshness.record_success(row(1, kind=cast(Any, "pg_dumpall")))
    assert _ages(gauge) == {}


@pytest.mark.parametrize(
    ("catalogued", "served"), [(False, frozenset()), (True, metrics.EXPORTED_NAMES)]
)
def test_series_are_not_exported_until_catalogued(
    monkeypatch: pytest.MonkeyPatch, catalogued: bool, served: frozenset[str]
) -> None:
    monkeypatch.setattr(wiring, "BACKUPS_CATALOGUED", catalogued)
    app = create_app()
    text = generate_latest(app.state.app_context.metrics).decode()
    assert {name for name in metrics.EXPORTED_NAMES if f"# HELP {name} " in text} == served
    kept = (app.state.backup_metrics, app.state.backup_freshness)
    assert (isinstance(kept[0], ReexportCollector), isinstance(kept[1], BackupFreshness)) == (
        catalogued,
        catalogued,
    )


def test_a_recorded_success_is_served_on_the_scraped_registry_with_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production path: the app's freshness writes the module's gauge, which the exporter
    serves; the other tests own a gauge of their own."""
    monkeypatch.setattr(wiring, "BACKUPS_CATALOGUED", True)
    app = create_app()
    try:
        app.state.backup_freshness.record_success(row(1))
        text = generate_latest(app.state.app_context.metrics).decode()
    finally:
        metrics.last_success_age_seconds.clear()  # the module's series: leave none behind
    served = r'^cv_backup_last_success_age_seconds\{env="\w+",kind="pg_dump"\} '  # any value
    assert re.search(served, text, re.MULTILINE)


def _restores(registry: CollectorRegistry) -> dict[str, float]:
    """The served restore counts by result; each sample carries the facade's `env` label."""
    return {
        s.labels["result"]: s.value
        for family in registry.collect()
        for s in family.samples
        if s.name == "cv_restore_jobs_total" and s.labels["env"] == "demo"
    }


def test_restore_result_label_is_the_closed_set() -> None:
    registry = CollectorRegistry()
    collector = metrics.export_backup_metrics(registry, env="demo")
    refused = metrics.restore_jobs_total.labels("refused")
    was = refused._value.get()
    try:
        before = _restores(registry)
        metrics.count_restore("refused")  # Q17: a refusal counts, though it creates no job
        with pytest.raises(KeyError):
            metrics.count_restore(cast(Any, "rejected"))
        after = _restores(registry)
    finally:
        collector.close()
        refused._value.set(was)  # the module's counter, as this test found it
    assert metrics.RESTORE_RESULTS == ("refused", "succeeded", "failed", "cancelled")
    # every result is served from the start, and only those
    assert {result: after[result] - before[result] for result in after} == {
        "refused": 1.0,
        "succeeded": 0.0,
        "failed": 0.0,
        "cancelled": 0.0,
    }


def test_catalogue_caps_are_the_closed_label_sets() -> None:
    rows = {s.name: (s.labels, s.max_series, s.exported) for s in CATALOGUE}
    assert {name: rows[name] for name in metrics.EXPORTED_NAMES} == {
        "cv_backup_last_success_age_seconds": (("kind",), len(metrics.KINDS), True),
        "cv_backup_verify_failures_total": ((), 1, True),
        "cv_restore_jobs_total": (("result",), len(metrics.RESTORE_RESULTS), True),
    }
    assert len(metrics.KINDS) == 5


def test_the_served_help_is_the_catalogues() -> None:
    registry = CollectorRegistry()
    collector = metrics.export_backup_metrics(registry, env="demo")
    try:
        served = {family.name: family.documentation for family in registry.collect()}
    finally:
        collector.close()
    names = metrics.EXPORTED_NAMES
    assert served == {s.name.removesuffix("_total"): s.help for s in CATALOGUE if s.name in names}


def test_the_boot_load_waits_at_most_the_reads_2_s_budget() -> None:
    """C-2.18: a hung catalogue holds the boot no longer (the store caps its statement at 1 s)."""
    budget = inspect.signature(BackupFreshness).parameters["budget_s"].default
    assert budget == READ_BUDGET_S == 2.0


async def test_start_loads_once_and_a_scrape_never_reads_the_store() -> None:
    store = _Last({"pg_dump": NOW - 30 * _H, "config_bundle": NOW - 100 * _H})
    freshness, gauge = _freshness(store)
    await freshness.start()
    scrapes = [_ages(gauge) for _ in range(3)]
    assert scrapes == [{"pg_dump": 108000.0, "config_bundle": 360000.0}] * 3
    assert store.calls == 1


@pytest.mark.parametrize(
    "error",
    [StorageTierUnavailable("driver text"), StorageQueryFailed("42501"), TimeoutError()],
    ids=["outage", "refused", "over-budget"],
)
async def test_a_failed_load_never_fails_boot_and_logs_only_the_class(error: Exception) -> None:
    freshness, gauge = _freshness(_Last(error=error), budget_s=0.05)
    with capture_logs() as logs:
        async with asyncio.timeout(_BOUND):
            await freshness.start()
    assert [(e["event"], e["log_level"], e["error"]) for e in logs] == [
        ("backups.freshness_not_loaded", "error", type(error).__name__)
    ]
    assert "driver text" not in repr(logs)
    freshness.record_success(row(1))  # a later success still counts
    assert set(_ages(gauge)) == {"pg_dump"}


@pytest.mark.parametrize(
    ("backend", "system_settings", "engines"),
    [
        ("fake", None, []),
        ("real", None, ["admin"]),
        ("real", SqlAlchemySystemSettings(_SHARED), [_SHARED]),  # never a second engine
    ],
    ids=["fake", "real", "real-shared"],
)
async def test_the_freshness_reads_the_catalogue_on_the_admin_engine(
    monkeypatch: pytest.MonkeyPatch, backend: Any, system_settings: Any, engines: list[Any]
) -> None:
    built: list[Any] = []

    def store(relational: Any) -> _Last:
        built.append(relational)
        return _Last()

    monkeypatch.setattr(wiring, "BACKUPS_CATALOGUED", True)
    monkeypatch.setattr(wiring, "SqlAlchemyBackups", store)
    monkeypatch.setattr(wiring, "SqlAlchemyRelationalRepository", lambda dsn, suffix: suffix)
    settings = Settings(storage_backend=backend)
    freshness = wiring.build_backup_freshness(settings, system_settings=system_settings)
    assert freshness is not None
    await freshness.start()  # the fake backend has no catalogue: nothing to load, nothing raised
    assert built == engines


def test_the_stale_backup_alert_is_a_ticket_pending_page_promotion() -> None:
    """Q16's thresholds and hold at ticket severity (ruling READY-27), filed and routed as a
    ticket, until the owner promotes it to a page (#2701). Promtool proves when it fires."""
    rule = _rule("BackupLastSuccessStale")
    assert rule["expr"] == (
        'cv_backup_last_success_age_seconds{kind!="config_bundle"} > 26*3600 '
        'or cv_backup_last_success_age_seconds{kind="config_bundle"} > 8*86400'
    )
    assert (rule["for"], rule["labels"]) == ("15m", {"severity": "ticket", "component": "backup"})
    url = rule["annotations"]["runbook_url"]
    assert url == "docs/plan/07-release-and-prr.md#alert-backuplastsuccessstale"
    route = _route_for({**rule["labels"], "alertname": "BackupLastSuccessStale", "env": "live"})
    assert route["receiver"] == "ticket" and route["mute_time_intervals"] == ["quiet_hours"]
    text = (_ALERTS / "system_ticket.yml").read_text(encoding="utf-8")
    block = text[text.index("- alert: BackupLastSuccessStale\n") :].split("- alert: ")[1]
    assert "page promotion pending owner approval (#2701)" in block


def test_flipping_backups_catalogued_needs_an_absent_guard_per_kind() -> None:
    """#3319 sets `BACKUPS_CATALOGUED`; a kind that never succeeds, or a failed boot load, has no
    sample and raises nothing, so the flip ships with an `absent()` guard for every kind."""
    text = "".join(f.read_text(encoding="utf-8") for f in sorted(_ALERTS.glob("*.yml")))
    pattern = r'absent\(cv_backup_last_success_age_seconds\{kind="(\w+)"\}\)'
    assert not wiring.BACKUPS_CATALOGUED or set(re.findall(pattern, text)) == metrics.KINDS
