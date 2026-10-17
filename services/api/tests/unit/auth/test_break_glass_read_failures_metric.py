"""The detector's own health signal (#2496 review; SR-125, detection health).

A failed read of the break-glass state keeps the last value of `auth_break_glass_unresolved_events`
and `auth_break_glass_attempts`, which is 0 in a fresh process, and the `absent()` guards on those
series cannot see it (the series exist). Without a signal of its own, a reader that cannot read
(a revoked grant, a renamed column, a timeout under load) leaves `AuthBreakGlassUsed` and
`AuthBreakGlassAttempted` silent and nothing says so. `auth_break_glass_state_read_failures_total`
counts one per failed statement, and `AuthBreakGlassStateReadFailing` raises a ticket on it.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from prometheus_client import REGISTRY, generate_latest

from candleviewer.app import create_app
from candleviewer.auth.break_glass_notice import BreakGlassNotice
from candleviewer.auth.metrics import (
    AUTH_EXPORTED_NAMES,
    auth_break_glass_attempts,
    auth_break_glass_unresolved_events,
    export_auth_metrics,
)
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Environment, Settings

SERIES = "auth_break_glass_state_read_failures_total"
_API_ROOT = Path(__file__).resolve().parents[3]
_FRESH_PROBE = f"""
import json
from prometheus_client import REGISTRY
import candleviewer.auth.metrics  # noqa: F401  (the import is what binds the series)

print(json.dumps(REGISTRY.get_sample_value("{SERIES}")))
"""


class _Events:
    """`BreakGlassEvents` fake: each count scripted, or the error to raise."""

    def __init__(
        self, unresolved: int | BaseException = 0, attempts: int | BaseException = 0
    ) -> None:
        self.unresolved = unresolved
        self.attempts = attempts

    async def unresolved_break_glass_count(self) -> int:
        if isinstance(self.unresolved, BaseException):
            raise self.unresolved
        return self.unresolved

    async def break_glass_attempt_count(self) -> int:
        if isinstance(self.attempts, BaseException):
            raise self.attempts
        return self.attempts


@pytest.fixture(autouse=True)
def _clean_gauges() -> None:
    """The gauges are process-wide: start from 0 (the counter only rises, so tests compare it
    before and after)."""
    auth_break_glass_attempts.set(0.0)
    auth_break_glass_unresolved_events.set(0.0)


def _failures() -> float:
    value = REGISTRY.get_sample_value(SERIES)
    assert value is not None
    return value


def _scraped(env: str = "demo") -> str:
    metrics = Metrics(env)
    collector = export_auth_metrics(metrics.registry, env=env)
    try:
        return generate_latest(metrics.registry).decode()
    finally:
        collector.close()


def test_catalogue_declares_the_counter_live_exported_and_owned_by_e09() -> None:
    spec = next(s for s in CATALOGUE if s.name == SERIES)
    assert (spec.kind, spec.labels, spec.status, spec.exported) == ("counter", (), "live", True)
    assert (spec.owner_epic, "AuthBreakGlassStateReadFailing" in spec.alert) == ("E09", True)
    assert SERIES in AUTH_EXPORTED_NAMES


def test_a_fresh_process_has_the_counter_at_zero() -> None:
    """The first failure after a restart is then a visible 0 -> 1 `increase()`. (Another test in
    this process has moved it: only a fresh interpreter proves it.)"""
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


async def test_a_successful_refresh_counts_nothing() -> None:
    before = _failures()
    notice = BreakGlassNotice(_Events(unresolved=1, attempts=2))
    await notice.refresh()
    assert (_failures() - before, notice.read_failures) == (0.0, 0)


async def test_a_failed_unresolved_read_counts_one() -> None:
    before = _failures()
    notice = BreakGlassNotice(_Events(unresolved=OSError("db down")))
    await notice.refresh()
    assert (_failures() - before, notice.read_failures) == (1.0, 1)


async def test_a_failed_attempts_read_counts_one() -> None:
    """The statement that is new (a grant on `audit_log`, a column) is the one that can break
    without anything else breaking: it is counted on its own."""
    before = _failures()
    notice = BreakGlassNotice(_Events(attempts=OSError("permission denied")))
    await notice.refresh()
    assert (_failures() - before, notice.read_failures) == (1.0, 1)


async def test_each_failed_statement_counts_and_the_counter_follows_the_property() -> None:
    before = _failures()
    events = _Events(unresolved=OSError("db down"), attempts=OSError("db down"))
    notice = BreakGlassNotice(events)
    await notice.refresh()  # both statements fail
    events.unresolved = 1
    await notice.refresh()  # one fails
    events.attempts = 3
    await notice.refresh()  # none
    assert (_failures() - before, notice.read_failures) == (3.0, 3)


async def test_a_read_that_times_out_is_counted() -> None:
    class _Hung:
        async def unresolved_break_glass_count(self) -> int:
            await asyncio.Event().wait()
            return 1

        async def break_glass_attempt_count(self) -> int:
            return 0

    before = _failures()
    notice = BreakGlassNotice(_Hung(), timeout_s=0.0)  # a deadline already due
    async with asyncio.timeout(5):
        await notice.refresh()
    assert _failures() - before == 1.0


async def test_a_cancelled_read_is_not_a_failure() -> None:
    before = _failures()
    notice = BreakGlassNotice(_Events(unresolved=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await notice.refresh()
    assert (_failures() - before, notice.read_failures) == (0.0, 0)


async def test_without_a_store_nothing_is_read_so_nothing_fails() -> None:
    before = _failures()
    await BreakGlassNotice(None).refresh()
    assert _failures() - before == 0.0


def test_export_serves_the_counter_with_the_env_label_and_its_help() -> None:
    text = _scraped("demo")
    assert f'{SERIES}{{env="demo"}} ' in text
    assert f"# HELP {SERIES} " in text


def test_create_app_serves_the_counter_on_the_scraped_registry() -> None:
    app = create_app(Settings(environment=Environment.DEMO))
    text = generate_latest(app.state.app_context.metrics).decode()
    assert any(ln.startswith(f'{SERIES}{{env="demo"}} ') for ln in text.splitlines())


def test_the_counter_carries_no_label_but_the_exporters_env() -> None:
    """SR-125: the log line names the statement and the error class; the series names neither."""
    own = [s for family in REGISTRY.collect() for s in family.samples if s.name == SERIES]
    assert [s.labels for s in own] == [{}]  # `env` is added only by the exporter
