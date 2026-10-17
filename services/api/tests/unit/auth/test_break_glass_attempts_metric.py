"""The break-glass run-count signal (#2496 review; SR-023, and the E09 threat model's "alert on any
break-glass invocation").

`auth_break_glass_attempts` is the number of `auth.break_glass_attempt` rows `audit_log` holds:
one per CLI run (the write-ahead first record), whatever the run's outcome, so it only rises. A
run that was refused or cut short leaves audit rows and no `break_glass_used` system event, so
`auth_break_glass_unresolved_events` and its page never see it; `AuthBreakGlassAttempted`
(`infra/prometheus/alerts/system_page.yml`) pages on a rise of this gauge instead.
`BreakGlassNotice` sets it from every successful read (the start-up read before cv-api serves,
then each refresh) and `export_auth_metrics` serves it on the scraped registry with `env`.

It is read by its own statement: a failure of this read must not stop the unresolved-events
gauge, the WS notice or the page that reads them, and the other way round.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import structlog
from prometheus_client import REGISTRY, generate_latest

from candleviewer.admin.breakglass import ATTEMPT
from candleviewer.app import AppContext, create_app
from candleviewer.audit.journal import BREAK_GLASS_ACTIONS
from candleviewer.auth.break_glass_notice import REFRESH_INTERVAL_S, BreakGlassNotice
from candleviewer.auth.metrics import (
    AUTH_EXPORTED_NAMES,
    auth_break_glass_attempts,
    auth_break_glass_unresolved_events,
    export_auth_metrics,
)
from candleviewer.auth.service import AuthService
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.break_glass_sqlalchemy import SqlAlchemyBreakGlassEvents
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

SERIES = "auth_break_glass_attempts"
_API_ROOT = Path(__file__).resolve().parents[3]
_FRESH_PROBE = f"""
import json
from prometheus_client import REGISTRY
import candleviewer.auth.metrics  # noqa: F401  (the import is what binds the series)

print(json.dumps(REGISTRY.get_sample_value("{SERIES}")))
"""


class _Events:
    """`BreakGlassEvents` fake: each count scripted, or the error to raise."""

    def __init__(self, attempts: int | BaseException, unresolved: int | BaseException = 0) -> None:
        self.attempts = attempts
        self.unresolved = unresolved

    async def unresolved_break_glass_count(self) -> int:
        if isinstance(self.unresolved, BaseException):
            raise self.unresolved
        return self.unresolved

    async def break_glass_attempt_count(self) -> int:
        if isinstance(self.attempts, BaseException):
            raise self.attempts
        return self.attempts


@pytest.fixture(autouse=True)
def _clean_gauges() -> Iterator[None]:
    """Both gauges are process-wide and any test that starts the auth module with a store moves
    them: every test here starts from 0 whatever ran before, and leaves 0 behind."""
    for gauge in (auth_break_glass_attempts, auth_break_glass_unresolved_events):
        gauge.set(0.0)
    yield
    for gauge in (auth_break_glass_attempts, auth_break_glass_unresolved_events):
        gauge.set(0.0)


def _reading(series: str = SERIES) -> float | None:
    return REGISTRY.get_sample_value(series)


def _scraped(env: str = "demo") -> str:
    """What Prometheus reads: the exposition of a registry serving the auth series."""
    metrics = Metrics(env)
    collector = export_auth_metrics(metrics.registry, env=env)
    try:
        return generate_latest(metrics.registry).decode()
    finally:
        collector.close()


def test_catalogue_declares_the_gauge_live_exported_and_owned_by_e09() -> None:
    spec = next(s for s in CATALOGUE if s.name == SERIES)
    assert (spec.kind, spec.labels, spec.status, spec.exported) == ("gauge", (), "live", True)
    assert (spec.owner_epic, "AuthBreakGlassAttempted" in spec.alert) == ("E09", True)
    assert SERIES in AUTH_EXPORTED_NAMES


def test_a_fresh_process_has_the_series_at_zero_before_any_read() -> None:
    """What Prometheus's first scrape of a healthy system sees, so the series'
    `ExpectedMetricMissing` guard (an `absent()` rule) stays quiet when no run is on record.
    (Another test in this process may already have set it: only a fresh interpreter proves it.)"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(_API_ROOT)
    done = subprocess.run(  # noqa: S603 -- fixed argv: this interpreter and a literal probe
        [sys.executable, "-c", _FRESH_PROBE],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=_API_ROOT,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == 0.0


async def test_a_read_sets_the_gauge_to_the_number_of_runs_on_record() -> None:
    await BreakGlassNotice(_Events(attempts=3)).refresh()
    assert _reading() == 3.0


async def test_a_later_run_raises_the_gauge_at_the_next_refresh() -> None:
    events = _Events(attempts=3)
    notice = BreakGlassNotice(events)
    await notice.refresh()
    events.attempts = 4  # a refused run was recorded while cv-api was up
    await notice.refresh()
    assert _reading() == 4.0


async def test_a_refused_run_moves_this_gauge_and_not_the_unresolved_one() -> None:
    """The case `AuthBreakGlassUsed` cannot see: a run that changed nothing leaves no event."""
    events = _Events(attempts=1, unresolved=0)
    notice = BreakGlassNotice(events)
    await notice.refresh()
    assert (_reading(), _reading("auth_break_glass_unresolved_events")) == (1.0, 0.0)
    assert notice.notices() == []  # nor does the WS notice say anything: no reset happened


async def test_a_failed_read_keeps_the_last_value_and_is_counted() -> None:
    events = _Events(attempts=2)
    notice = BreakGlassNotice(events)
    await notice.refresh()
    events.attempts = OSError("connection reset")
    with structlog.testing.capture_logs() as logs:
        await notice.refresh()
    assert (_reading(), notice.read_failures) == (2.0, 1)  # unknown never lowers the count
    failed = [e for e in logs if e["event"] == "auth.break_glass_state_read_failed"]
    assert [(e["series"], e["error"], e["failures"]) for e in failed] == [
        ("attempts", "OSError", 1)
    ]


async def test_a_failed_first_read_never_guesses_a_run() -> None:
    notice = BreakGlassNotice(_Events(attempts=OSError("db down")))
    await notice.refresh()
    assert (_reading(), notice.read_failures) == (0.0, 1)


async def test_a_failed_attempts_read_does_not_stop_the_unresolved_events_series() -> None:
    """A broken statement here (a grant, a renamed column) must not blind the page that reads
    the system event, nor the WS notice."""
    notice = BreakGlassNotice(_Events(attempts=OSError("denied"), unresolved=2))
    await notice.refresh()
    assert _reading("auth_break_glass_unresolved_events") == 2.0
    assert (notice.unresolved, len(notice.notices()), notice.read_failures) == (True, 1, 1)


async def test_a_failed_unresolved_read_does_not_stop_the_attempts_series() -> None:
    notice = BreakGlassNotice(_Events(attempts=5, unresolved=OSError("denied")))
    await notice.refresh()
    assert (_reading(), notice.unresolved, notice.read_failures) == (5.0, None, 1)


async def test_without_a_store_the_gauge_stays_at_zero() -> None:
    notice = BreakGlassNotice(None)  # the fake backend: no `audit_log` table to read
    await notice.start()
    await notice.refresh()
    assert _reading() == 0.0
    await notice.stop()


async def test_start_publishes_the_count_before_it_returns() -> None:
    """cv-api serves only after `start_all()`, so the first scrape already holds the count of the
    restart that follows a run: the page compares it with what Prometheus held before."""

    async def sleep(_seconds: float) -> None:
        await asyncio.Event().wait()

    notice = BreakGlassNotice(_Events(attempts=7), sleep=sleep)
    await notice.start()
    assert _reading() == 7.0
    await notice.stop()


async def test_the_refresher_publishes_a_run_recorded_while_cv_api_is_up() -> None:
    """The CLI refuses at once when cv-api runs and still writes its two records straight to
    `audit_log`: the next minute's read finds them."""
    events, parked, sleeps = _Events(attempts=1), asyncio.Event(), list[float]()

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:  # park the loop after its first periodic read
            parked.set()
            await asyncio.Event().wait()

    notice = BreakGlassNotice(events, sleep=sleep)
    await notice.start()
    assert _reading() == 1.0
    events.attempts = 2
    async with asyncio.timeout(5):
        await parked.wait()
    assert (_reading(), sleeps) == (2.0, [REFRESH_INTERVAL_S] * 2)
    await notice.stop()


async def test_the_auth_module_publishes_the_count_when_it_starts() -> None:
    auth = AuthService(break_glass_events=_Events(attempts=4))
    await auth.start(cast(AppContext, None))  # the context is read only to wire MFA
    try:
        assert _reading() == 4.0
        assert f'{SERIES}{{env="live"}} 4.0' in _scraped("live")
    finally:
        await auth.stop(1.0)


def test_export_serves_the_gauge_with_the_env_label_and_its_help() -> None:
    auth_break_glass_attempts.set(2.0)
    text = _scraped("demo")
    assert f'{SERIES}{{env="demo"}} 2.0' in text
    assert f"# HELP {SERIES} " in text


def test_create_app_serves_the_gauge_on_the_scraped_registry() -> None:
    app = create_app(Settings(environment=Environment.DEMO))
    text = generate_latest(app.state.app_context.metrics).decode()
    assert any(ln.startswith(f'{SERIES}{{env="demo"}} ') for ln in text.splitlines())


def test_the_series_carries_no_label_but_the_exporters_env() -> None:
    """SR-125: no user, IP, run id or path. The Owner reads the audit rows for who and when."""
    own = [s for family in REGISTRY.collect() for s in family.samples if s.name == SERIES]
    assert [s.labels for s in own] == [{}]  # `env` is added only by the exporter
    served = [ln for ln in _scraped("demo").splitlines() if ln.startswith(f"{SERIES}{{")]
    assert served == [f'{SERIES}{{env="demo"}} {_reading()}']


class _Rel:
    """One-statement unit of work answering `row`; records the SQL."""

    def __init__(self, row: int) -> None:
        self.row, self.sql = row, list[str]()

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[SimpleNamespace]:
        async def execute(stmt: object) -> SimpleNamespace:
            self.sql.append(" ".join(str(stmt).split()))
            return SimpleNamespace(scalar_one=lambda: self.row)

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


@pytest.mark.parametrize("row", [0, 1, 6])
async def test_store_reads_one_count_over_the_cli_attempt_rows(row: int) -> None:
    rel = _Rel(row)
    # cast: `_Rel` is a structural fake of the one method the reader calls.
    store = SqlAlchemyBreakGlassEvents(cast(SqlAlchemyRelationalRepository, rel))
    assert await store.break_glass_attempt_count() == row
    assert rel.sql == ["SELECT count(*) FROM audit_log WHERE action = 'auth.break_glass_attempt'"]


def test_the_counted_action_is_the_cli_write_ahead_record() -> None:
    """The SQL above names the action by literal (`storage` imports no `admin`); this pins the
    literal to the CLI's constant, which the journal admits."""
    assert ATTEMPT == "auth.break_glass_attempt"
    assert ATTEMPT in BREAK_GLASS_ACTIONS
