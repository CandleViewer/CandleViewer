"""E29-X02 (#982): the live-target guard, the suite's one world per module and its PR-path budget.

The guard is E28-X03's (`tests/security/e28/conftest.py`, which alone may spell C-13.5's deny-listed
hosts): it aborts the whole run, at collection and again before each module, when the target is
live (a live switch, any exchange-key variable, a host list naming the venue). It names a
variable, never a value.

The budget is the ticket's performance note: the suite stays under 5 minutes on the PR path. Each
of its items is timed from its setup to its teardown (its module's world included) in CPU seconds
of the process, which a loaded runner's queueing does not move; a session whose items spent more
than `BUDGET_S` fails at its end, naming the total. CPU seconds exclude waiting: a test that slept
or blocked would spend wall time the budget never sees. That is sound only because the suite may
not wait: its sleep ban, `test_suite_meta.py::
test_the_suite_keeps_the_pr_path_budget_on_injected_clocks_and_bounded_runs`, refuses every real
sleep and every governor on a real clock. The last item is counted too: the session's own
teardown, where the total is checked, runs inside that item's teardown, so its time up to then is
added; what follows the check is pytest's own.
"""

from __future__ import annotations

import time
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Final

import pytest

from candleviewer.statechart.bindings import b16_session
from tests.security.e28.conftest import live_target_refusal, target_env
from tests.security.oms._world import OmsWorld, oms_world

BUDGET_S: Final = 300.0
SPENT: Final = pytest.StashKey[list[float]]()
#: When the item of this suite now running started, in CPU seconds; absent between items.
RUNNING: Final = pytest.StashKey[float]()
_HERE: Final = Path(__file__).parent


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, object, object]:
    """Each item of this suite (every conftest sees every item: the path picks ours), timed."""
    ours = _HERE in item.path.parents
    if ours:
        item.session.stash[RUNNING] = time.process_time()
    try:
        return (yield)
    finally:
        if ours:
            started = item.session.stash[RUNNING]
            del item.session.stash[RUNNING]
            item.session.stash.setdefault(SPENT, []).append(time.process_time() - started)


@pytest.fixture(scope="session", autouse=True)
def _pr_path_budget(request: pytest.FixtureRequest) -> Iterator[None]:
    yield
    timed: list[float] = request.session.stash.get(SPENT, [])
    # Session fixtures end inside the last item's teardown, before that item's time is appended:
    # its time so far (its call, its module's world stopped) is counted here.
    started = request.session.stash.get(RUNNING, None)
    spent = sum(timed) + (0.0 if started is None else time.process_time() - started)
    assert spent <= BUDGET_S, f"the OMS suite spent {spent:.0f} CPU s, over its {BUDGET_S:.0f} s"


def _abort_if_live() -> None:
    if (why := live_target_refusal(target_env())) is not None:
        pytest.exit(f"E29-X02 security suite refused to run: {why}", returncode=4)


_abort_if_live()  # at collection, before any module of this suite is imported


@pytest.fixture(scope="module", autouse=True)
def _live_guard() -> None:
    """Again before each module: a variable set since collection aborts the run as well."""
    _abort_if_live()


@pytest.fixture(scope="module")
def _oms(_live_guard: None, tmp_path_factory: pytest.TempPathFactory) -> Iterator[OmsWorld]:
    with oms_world(tmp_path_factory.mktemp("bars-state")) as world:
        yield world


@pytest.fixture
def world(_oms: OmsWorld, b16_audit: object) -> OmsWorld:
    """The module's world, its audit index emptied; B16's records land in its audit too."""
    _oms.reset()
    b16_session.set_audit_sink(_oms.pack.audit)
    return _oms
