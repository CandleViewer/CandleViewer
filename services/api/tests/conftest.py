"""Shared pytest fixtures for services/api.

Provides a placeholder `AppContext`-fake fixture per E02-T02's scope; the real
composition-root `AppContext` lands in E02-T05. No network, no filesystem
access outside `tmp_path` (Constitution C-13.5/C-13.7).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

# Re-exported so the autouse fixture is picked up for every test under
# services/api/tests/** (E03-T03 network guard, ADR-0012 / SR-140). Import
# has a side effect of registering the fixture with pytest; do not remove
# even though `_cv_network_guard` looks unused to a linter.
from tests._ci_network_guard import _cv_network_guard  # noqa: F401
from tests._duckdb_guard import _cv_no_duckdb_install  # noqa: F401
from tests._hypothesis_profiles import load_active_profile

# Behavioural-contract mixins are not `test_*` modules, so pytest would not rewrite their asserts
# and a failure would print a bare `AssertionError` with no values (C-13.7). Register them before
# any test module imports them; the fake and the Postgres suites both subclass this one.
pytest.register_assert_rewrite("tests.unit.storage.replay_sessions_contract")

load_active_profile()


@dataclass(frozen=True)
class FakeAppContext:
    """Stand-in for the future composition-root `AppContext`.

    Real modules (bus, exchange, storage, ...) are wired in E02-T05; this
    fake exists only so downstream tickets' tests can depend on the fixture
    name without churn once the real context lands.
    """

    environment: str = "test"


@pytest.fixture
def app_context() -> Iterator[FakeAppContext]:
    yield FakeAppContext()


class RecordingAuditSink:
    """In-memory B16 audit sink (the M19 writer stands in for it in prod)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit(self, action: str, **kwargs: Any) -> None:
        self.calls.append({"action": action, **kwargs})

    def actions(self) -> list[str]:
        return [c["action"] for c in self.calls]


@pytest.fixture(autouse=True)
def b16_audit() -> Iterator[RecordingAuditSink]:
    """Every test gets a fresh B16 audit sink; a test that needs the
    "no sink wired" path clears it itself."""
    from candleviewer.statechart.bindings import b16_session

    sink = RecordingAuditSink()
    b16_session.set_audit_sink(sink)
    yield sink
    b16_session.set_audit_sink(None)


@pytest.fixture(autouse=True)
def _reset_structlog_state() -> Iterator[None]:
    """C-13.7: `configure_logging()` pins renderers via `cache_logger_on_first_use=True`, installs a
    QueueListener and root handler, and binds contextvars. Undo all of it after every test so no
    ordering can leak it into a later module-level-logger test (#2049, #2057)."""
    from candleviewer.observability.logging import reset_logging

    yield
    reset_logging()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Tag the E09 regression pack so `pytest -m e09_regression` selects it (#2148)."""
    from tests._e09_regression_pack import tag_pack

    tag_pack(items)
