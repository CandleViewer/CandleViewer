"""Mutation self-tests for the E04 regression pack (E04-Q02, #257, BQ-09 (b)).

Each test mutates the input of one pack suite in memory and asserts the suite then fails (or, for
the dashboard lint, reports). That proves the check can catch the breakage it names, with no
docker, no network and no wall clock beyond one bounded timeout (P2). The suite bodies are the real
ones, loaded by path, never copies. P7 and P8 carry their own `test_self_test_*` cases beside them.
Not covered here: P3 (promtool needs the binary), P6 (a vitest suite); the pack index names the
single scratch CI run that proves the wiring.

| Pack suite | Mutation | Test |
| P1 canary-secret | redaction bypassed on the structlog and stdlib paths | g01 |
| P2 health matrix | probe deadline raised past the bound | h03 |
| P4 dashboard lint | one panel's metric renamed | lint |
| P5 cardinality guard | series cap lifted | facade |
"""

from __future__ import annotations

import importlib.util
import json
import logging
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from candleviewer.api import health_report
from candleviewer.observability import logging as logging_mod
from candleviewer.observability.metrics import Metrics
from tests._alert_rules import lint_module

HERE = Path(__file__).resolve().parent
UNIT_OBS = HERE.parent / "unit" / "observability"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _must_fail(case: Callable[[], None]) -> None:
    with pytest.raises(AssertionError):
        case()


def test_self_test_p1_canary_check_fails_when_redaction_is_bypassed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blackbox = _load(HERE / "test_e04_q01_blackbox.py", "e04_q01_blackbox_p1")
    blackbox.test_g01_canaries_never_reach_output_via_four_logging_paths()  # green unmutated
    monkeypatch.setattr(logging_mod, "_redaction_processor", lambda _l, _m, event: event)
    monkeypatch.setattr(logging_mod.RedactionFilter, "filter", lambda _self, _record: True)
    _must_fail(blackbox.test_g01_canaries_never_reach_output_via_four_logging_paths)
    logging.getLogger().handlers = []


def test_self_test_p2_probe_deadline_check_fails_when_the_deadline_is_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blackbox = _load(HERE / "test_e04_q01_blackbox.py", "e04_q01_blackbox_p2")
    real = health_report.make_health_report_router

    def late(**kwargs: Any) -> Any:
        kwargs["ready_timeout_s"] = 2.3  # past h03's 2.0 s bound, still bounded for the run
        return real(**kwargs)

    blackbox.test_h03_slow_probe_is_bounded_and_does_not_block_liveness()  # green unmutated
    monkeypatch.setattr(blackbox, "make_health_report_router", late)
    _must_fail(blackbox.test_h03_slow_probe_is_bounded_and_does_not_block_liveness)


def test_self_test_p4_dashboard_lint_reports_a_renamed_metric(tmp_path: Path) -> None:
    lint = lint_module()
    known = lint.catalogue_names()
    rules = lint.recorded_rules()
    source = sorted(lint.DASH.glob("*.json"))[0]
    assert lint.lint_dashboard(source, known, rules) == []  # green unmutated
    board = json.loads(source.read_text("utf-8"))
    renamed = False
    for panel in board["panels"]:
        for target in panel.get("targets", []):
            for metric in sorted(lint.metrics_in(target["expr"])):
                if not renamed and metric in known:
                    target["expr"] = target["expr"].replace(metric, f"{metric}_typo")
                    renamed = True
    assert renamed, "no catalogue metric found to rename"
    mutated = tmp_path / source.name
    mutated.write_text(json.dumps(board), "utf-8")
    errors = lint.lint_dashboard(mutated, known, rules)
    assert any("unknown metric" in e and e.endswith("_typo'") for e in errors)


def test_self_test_p5_cardinality_test_fails_when_the_series_cap_is_lifted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facade = _load(UNIT_OBS / "test_metrics_facade.py", "e04_metrics_facade_p5")
    case = facade.test_cardinality_guard_caps_series_counts_breach_and_logs
    case()  # green unmutated
    real = Metrics.counter

    def uncapped(self: Metrics, name: str, help_text: str, *args: Any, **kwargs: Any) -> Any:
        kwargs["max_series"] = 10_000
        return real(self, name, help_text, *args, **kwargs)

    monkeypatch.setattr(Metrics, "counter", uncapped)
    _must_fail(case)
