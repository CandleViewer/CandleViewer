"""#3641: the root conftest's stub of the startup heap freeze, and its leak guard.

`main._lifespan` and the bench's `build_app` each collect, then freeze, the whole process. The stub
makes both a no-op in a test that does not check them (a real one costs a full collection of the
pytest process, and leaves it frozen), and the guard unfreezes what a test left frozen. A test that
asks for nothing is the canary: were the stub to stop patching, nothing else would fail, the suite
would only slow down and leak."""

from __future__ import annotations

import gc
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from bench.ingestion import fixture_app
from candleviewer import main
from candleviewer.observability import metrics_runtime
from tests._gc_freeze import Marker, is_frozen
from tests.conftest import stub_startup_freeze, undo_a_leaked_freeze


def test_a_test_that_asks_for_nothing_gets_a_no_op_lifespan_freeze() -> None:
    marker = Marker()
    vars(main)["freeze_startup_heap"]()  # `main` imports it, and mypy sees no such export
    assert not is_frozen(marker)


async def test_a_test_that_asks_for_nothing_gets_a_no_op_bench_freeze(tmp_path: Path) -> None:
    marker = Marker()
    await fixture_app.build_app(tmp_path)  # the call that ends in `freeze_startup_heap`
    assert not is_frozen(marker)


def _request(*fixtures: str, perf: bool = False) -> pytest.FixtureRequest:
    """The two things the stub reads of `request`."""
    node = SimpleNamespace(
        get_closest_marker=lambda name: object() if perf and name == "perf" else None
    )
    return cast("pytest.FixtureRequest", SimpleNamespace(fixturenames=list(fixtures), node=node))


@pytest.mark.parametrize(
    ("fixtures", "perf", "stubbed"),
    [((), False, True), (("real_startup_freeze",), False, False), ((), True, False)],
    ids=["a test that asks for nothing", "a test that asks for the real one", "a perf test"],
)
def test_the_stub_leaves_the_real_freeze_to_a_test_that_asks_for_it_or_measures(
    real_startup_freeze: None, fixtures: tuple[str, ...], perf: bool, stubbed: bool
) -> None:
    """Both call sites are stubbed, or neither: a `perf` test is the Budget #13 rig, which reads
    the heap the app serves from. (This test asks for the real freeze itself, so that nothing has
    patched the two modules before the stub's choice is made here.)"""
    stub = stub_startup_freeze(_request(*fixtures, perf=perf))
    next(stub)  # the test begins
    try:
        for module in (main, fixture_app):
            real = module.freeze_startup_heap is metrics_runtime.freeze_startup_heap
            assert real is not stubbed
    finally:
        next(stub, None)  # the test ends
    for module in (main, fixture_app):  # and the stub has put back what it patched
        assert module.freeze_startup_heap is metrics_runtime.freeze_startup_heap


def test_the_autouse_stub_does_not_set_monkeypatch_up_first(request: pytest.FixtureRequest) -> None:
    """A test that asks for nothing gets no `monkeypatch`: an autouse fixture that requested it
    would set it up before every other fixture, so it would undo a test's own patches only after a
    module's guard had checked the shared state at teardown (`test_rbac_generator.py`'s)."""
    assert "monkeypatch" not in request.fixturenames


def test_the_leak_guard_unfreezes_what_a_test_left_frozen(clean_freeze: None) -> None:
    marker = Marker()
    guard = undo_a_leaked_freeze()
    next(guard)  # the test begins
    gc.freeze()  # and leaves the process frozen
    assert is_frozen(marker)

    next(guard, None)  # the test ends

    assert not is_frozen(marker)


def test_the_leak_guard_keeps_a_freeze_that_was_there_before_the_test(clean_freeze: None) -> None:
    marker = Marker()
    gc.freeze()  # another caller's
    guard = undo_a_leaked_freeze()
    next(guard)  # the test begins
    next(guard, None)  # and ends, having frozen nothing

    assert is_frozen(marker)
