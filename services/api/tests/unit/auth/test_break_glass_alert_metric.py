"""The break-glass-use alert signal (#2496 item 3; SR-023: a use is "loudly surfaced").

`auth_break_glass_unresolved_events` is the number of `auth`/`break_glass_used` system events
that are unresolved: 0 when none. `BreakGlassNotice` sets it from every successful read (the
start-up read before cv-api serves, then each refresh), `export_auth_metrics` serves it on the
scraped registry with `env`, and `AuthBreakGlassUsed` (`infra/prometheus/alerts/system_page.yml`)
pages the Owner while it reads 1 or more. A count, so a second reset during a silence of the page
is visible to the Owner as 2 (#2496 review).

It is a gauge, not a counter of the records the boot fold-in moves, for two reasons. The CLI
flushes its records to `audit_log` before it exits, so a use folds nothing in at the next boot
(only refusals journaled while Postgres was down do); the unresolved event is what a use leaves.
And the fold-in runs inside `Supervisor.start_all()`, before the `/metrics` listener opens, so
the first scrape of such a counter already holds its final value and `increase()` over one
sample is empty. A gauge read at any scrape has neither blind spot.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from prometheus_client import REGISTRY, generate_latest

from candleviewer.app import AppContext, create_app
from candleviewer.auth.break_glass_notice import REFRESH_INTERVAL_S, BreakGlassNotice
from candleviewer.auth.metrics import (
    AUTH_EXPORTED_NAMES,
    auth_break_glass_unresolved_events,
    export_auth_metrics,
)
from candleviewer.auth.service import AuthService
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Environment, Settings

SERIES = "auth_break_glass_unresolved_events"
_API_ROOT = Path(__file__).resolve().parents[3]
_FRESH_PROBE = f"""
import json
from prometheus_client import REGISTRY
import candleviewer.auth.metrics  # noqa: F401  (the import is what binds the series)

print(json.dumps(REGISTRY.get_sample_value("{SERIES}")))
"""


class _Events:
    """`BreakGlassEvents` fake: the scripted count, or the error to raise."""

    def __init__(self, answer: int | BaseException) -> None:
        self.answer = answer

    async def unresolved_break_glass_count(self) -> int:
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer

    async def break_glass_attempt_count(self) -> int:
        return 0  # the attempts series has its own tests: test_break_glass_attempts_metric.py


@pytest.fixture(autouse=True)
def _clean_gauge() -> Iterator[None]:
    """The gauge is process-wide and any test that starts the auth module with a store moves it:
    every test here starts from 0 whatever ran before, and leaves 0 behind."""
    auth_break_glass_unresolved_events.set(0.0)
    yield
    auth_break_glass_unresolved_events.set(0.0)


def _reading() -> float | None:
    return REGISTRY.get_sample_value(SERIES)


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
    assert (spec.owner_epic, "AuthBreakGlassUsed" in spec.alert) == ("E09", True)
    assert SERIES in AUTH_EXPORTED_NAMES


def test_a_fresh_process_has_the_series_at_zero_before_any_read() -> None:
    """What Prometheus's first scrape of a healthy system sees, so the series'
    `ExpectedMetricMissing` guard (an `absent()` rule) stays quiet when nothing is unresolved.
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


async def test_a_read_that_finds_an_unresolved_event_sets_the_gauge_to_one() -> None:
    await BreakGlassNotice(_Events(1)).refresh()
    assert _reading() == 1.0


async def test_a_second_unresolved_reset_reads_as_two_not_as_one() -> None:
    """#2496 review: the page cannot tell a second reset from the first (same alert identity), so
    a silence on it hides the second. The gauge is the count, so the Owner who re-issues the
    silence sees 2 where the silence comment says 1."""
    events = _Events(1)
    notice = BreakGlassNotice(events)
    await notice.refresh()
    events.answer = 2  # a second reset, while the first is still unresolved
    await notice.refresh()
    assert (_reading(), notice.unresolved) == (2.0, True)


async def test_a_read_after_the_event_is_resolved_sets_the_gauge_back_to_zero() -> None:
    events = _Events(1)
    notice = BreakGlassNotice(events)
    await notice.refresh()
    events.answer = 0  # the Owner resolved it
    await notice.refresh()
    assert (_reading(), notice.unresolved) == (0.0, False)


async def test_a_failed_read_keeps_the_last_value() -> None:
    events = _Events(2)
    notice = BreakGlassNotice(events)
    await notice.refresh()
    events.answer = OSError("connection reset")
    await notice.refresh()
    assert (_reading(), notice.read_failures) == (2.0, 1)  # unknown never clears a page


async def test_a_failed_first_read_never_guesses_an_event() -> None:
    notice = BreakGlassNotice(_Events(OSError("db down")))
    await notice.refresh()
    assert (_reading(), notice.read_failures) == (0.0, 1)


async def test_without_a_store_the_gauge_stays_at_zero() -> None:
    notice = BreakGlassNotice(None)  # the fake backend: no `system_events` table to read
    await notice.start()
    await notice.refresh()
    assert _reading() == 0.0
    await notice.stop()


async def test_start_publishes_the_count_before_it_returns() -> None:
    """cv-api serves only after `start_all()`, so the first scrape must already see it."""

    async def sleep(_seconds: float) -> None:
        await asyncio.Event().wait()

    notice = BreakGlassNotice(_Events(1), sleep=sleep)
    await notice.start()
    assert _reading() == 1.0
    await notice.stop()


async def test_the_refresher_moves_the_gauge_when_the_event_is_resolved() -> None:
    events, parked, sleeps = _Events(1), asyncio.Event(), list[float]()

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:  # park the loop after its first periodic read
            parked.set()
            await asyncio.Event().wait()

    notice = BreakGlassNotice(events, sleep=sleep)
    await notice.start()
    assert _reading() == 1.0
    events.answer = 0
    async with asyncio.timeout(5):
        await parked.wait()
    assert (_reading(), sleeps) == (0.0, [REFRESH_INTERVAL_S] * 2)
    await notice.stop()


async def test_the_auth_module_publishes_the_count_when_it_starts() -> None:
    auth = AuthService(break_glass_events=_Events(1))
    await auth.start(cast(AppContext, None))  # the context is read only to wire MFA
    try:
        assert _reading() == 1.0
        assert f'{SERIES}{{env="live"}} 1.0' in _scraped("live")
    finally:
        await auth.stop(1.0)


def test_export_serves_the_gauge_with_the_env_label_and_its_help() -> None:
    auth_break_glass_unresolved_events.set(1.0)
    text = _scraped("demo")
    assert f'{SERIES}{{env="demo"}} 1.0' in text
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
