"""Shared pytest fixtures for services/api.

Provides a placeholder `AppContext`-fake fixture per E02-T02's scope; the real
composition-root `AppContext` lands in E02-T05. No network, no filesystem
access outside `tmp_path` (Constitution C-13.5/C-13.7).
"""

from __future__ import annotations

import gc
import sys
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from types import ModuleType
from typing import Any

import pytest

# Re-exported so the autouse fixtures are picked up for every test under
# services/api/tests/** (E03-T03 network guard, ADR-0012 / SR-140; #3826 per-test
# verdict). Import has a side effect of registering the fixtures with pytest; do not
# remove even though they look unused to a linter.
from tests._ci_network_guard import _cv_network_guard, _cv_network_guard_verdict  # noqa: F401
from tests._duckdb_guard import _cv_no_duckdb_install  # noqa: F401
from tests._hypothesis_profiles import load_active_profile

# Behavioural-contract mixins are not `test_*` modules, so pytest would not rewrite their asserts
# and a failure would print a bare `AssertionError` with no values (C-13.7). Register them before
# any test module imports them; the fake and the Postgres suites both subclass this one.
pytest.register_assert_rewrite("tests.unit.storage.replay_sessions_contract")
pytest.register_assert_rewrite("tests.unit.oms.write_ahead_contract")
pytest.register_assert_rewrite("tests.unit.oms.store_reads_contract")

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


@pytest.fixture
def real_startup_freeze() -> None:
    """Ask for it to run the real startup heap freeze: see `_stub_startup_freeze`."""


#: The modules that call `freeze_startup_heap`: the lifespan, and the bench's fixture app, whose
#: `build_app` ends with the same call.
_FREEZING_MODULES = ("candleviewer.main", "bench.ingestion.fixture_app")


def _no_freeze() -> None:
    """The stub's `freeze_startup_heap`: it freezes nothing."""


def stub_startup_freeze(request: pytest.FixtureRequest) -> Iterator[None]:
    """Make the startup heap freeze a no-op in `main._lifespan` and the bench's `build_app`.

    A real one is a full collection of everything the pytest process holds so far, 0.2 to 1 s
    each time (enough to use up a test's own time bound: `test_key_import`'s 1 s spans the
    lifespan's boot), and it freezes the whole process until something unfreezes it. What it
    freezes is not what the tests that boot the lifespan or build the app check, so they get a
    no-op. Two kinds of test keep the real one: a test that asks for `real_startup_freeze` (the
    freeze's own tests), and a `perf` test, because the Budget #13 rig reads the heap the app
    serves from (`undo_a_leaked_freeze` ends its freeze).

    Only a module the run has already imported is patched, so no test pays for an import it did
    not make; a freeze through a module imported inside a test escapes the stub, and the guard
    undoes it. With the stub, the lifespan still sets `frozen = True`, so its teardown still runs
    the real `unfreeze_startup_heap()`: a `gc.unfreeze()` that finds nothing of its own to move.

    It patches and restores by hand rather than through `monkeypatch`: an autouse fixture that
    requests `monkeypatch` sets it up before every other fixture of the test, so it undoes the
    test's own patches only after the other fixtures' teardowns, and a module's guard that checks
    shared state at teardown (`tests/contract/test_rbac_generator.py`'s) would see them still in
    place.
    """
    asked = "real_startup_freeze" in request.fixturenames
    patched: list[tuple[ModuleType, object]] = []
    if not asked and request.node.get_closest_marker("perf") is None:
        for name in _FREEZING_MODULES:
            module = sys.modules.get(name)
            if module is not None:
                patched.append((module, vars(module)["freeze_startup_heap"]))
                vars(module)["freeze_startup_heap"] = _no_freeze
    try:
        yield
    finally:
        for module, original in reversed(patched):
            vars(module)["freeze_startup_heap"] = original


@pytest.fixture(autouse=True)
def _stub_startup_freeze(request: pytest.FixtureRequest) -> Iterator[None]:
    """#3641: `main._lifespan` and the bench's `build_app` collect, then freeze, the heap of the
    whole process. A test that does not check that runs a no-op; one that does asks for
    `real_startup_freeze`, and a `perf` test keeps the real one (`stub_startup_freeze` says why).
    The lifespan still sets `frozen = True` around the no-op, so its teardown still runs the real
    unfreeze."""
    yield from stub_startup_freeze(request)


def undo_a_leaked_freeze() -> Iterator[None]:
    """The body of the autouse guard below: after a test, the permanent generation holds no more
    than before it.

    A test that freezes the process and never undoes it (a `build_app` its module imported late, a
    boot whose lifespan was not stubbed) would leave every later test running with its heap out of
    the collector. `gc.unfreeze()` undoes every freeze in the process, so it runs only where the
    count grew: a freeze that was already there is its caller's own. (A plain collection after an
    unfreeze puts a few hundred immortal objects back, which counts as growth, and is harmless.)
    """
    before = gc.get_freeze_count()
    yield
    if gc.get_freeze_count() > before:
        gc.unfreeze()


@pytest.fixture(autouse=True)
def _undo_a_leaked_freeze() -> Iterator[None]:
    """#3641: what the real freeze or a freeze this suite did not stub leaves behind is undone
    after every test, as `_reset_structlog_state` undoes the logging: no ordering can leave a
    later test running on a frozen heap (`undo_a_leaked_freeze` says how)."""
    yield from undo_a_leaked_freeze()


@pytest.fixture
def clean_freeze(real_startup_freeze: None) -> Iterator[None]:
    """For a test that freezes for real, through the lifespan, the bench's `build_app` or the
    helpers themselves: a clean slate whatever ran before, and nothing left frozen after."""
    gc.unfreeze()
    yield
    gc.unfreeze()


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(
    collector: pytest.Collector,
) -> Generator[None, pytest.CollectReport, pytest.CollectReport]:
    """C-13.7 (#3357, #2519): the reset above, after each collected node. Importing a module can
    configure logging before any fixture runs (`candleviewer.main` calls `configure_logging()` at
    import). Left in place, the first test would run under it, and pytest's `__test__` probe of
    the next module collected would pin that module's module-level structlog loggers to the
    cached chain for good."""
    from candleviewer.observability.logging import reset_logging

    try:
        return (yield)
    finally:
        reset_logging()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Tag the E09 and E08 regression packs so `pytest -m e09_regression` (#2148) and
    `pytest -m e08_regression` (#283) select them."""
    from tests._e08_regression_pack import tag_pack as tag_e08_pack
    from tests._e09_regression_pack import tag_pack as tag_e09_pack

    tag_e09_pack(items)
    tag_e08_pack(items)
