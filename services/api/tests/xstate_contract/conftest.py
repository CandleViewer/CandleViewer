"""Contract-suite membership (29-statechart-adoption-plan.md §1.7, E50-T31).

Every committed `machines/*.machine.json` must have a contract module
`tests/xstate_contract/test_bNN_<id>*.py`; a chart without one fails
**collection** (not a test), so the gate cannot go green with a machine
silently outside it. The generated per-arm / per-quiescence-point suites
(`test_contract_*.py`) cover every chart automatically on top of that.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import pytest

from candleviewer.statechart.bindings import b01_order as b01
from tests.xstate_contract._harness import Charts
from tests.xstate_contract.membership import missing_contract_modules

_HERE = Path(__file__).resolve().parent
_MACHINES = _HERE.parents[1] / "candleviewer" / "statechart" / "machines"


def check_membership(machines: Path, suite: Path) -> None:
    missing = missing_contract_modules(machines, suite)
    if missing:
        raise pytest.UsageError(
            "xstate_contract membership (29 §1.7): no contract module for "
            + ", ".join(missing)
            + " — add tests/xstate_contract/test_bNN_<id>.py"
        )


def pytest_collectstart(collector: pytest.Collector) -> None:
    if isinstance(collector, pytest.Package) and Path(collector.path) == _HERE:
        check_membership(_MACHINES, _HERE)


@pytest.fixture(scope="session")
def charts(tmp_path_factory: pytest.TempPathFactory) -> Charts:
    return Charts(tmp_path_factory.mktemp("xstate_contract_charts"))


@pytest.fixture(autouse=True)
def _b01_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    """B1's command attempts and replays are process memory (`b01_order._ATTEMPTS`, `_REPLAYS`):
    each test starts with none, so no test reads an attempt another left (C-13.7). A Hypothesis
    test resets them per example itself, as this runs once per test."""
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    monkeypatch.setattr(b01, "_REPLAYS", {})
