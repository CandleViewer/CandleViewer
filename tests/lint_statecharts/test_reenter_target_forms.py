"""tests/lint_statecharts/test_reenter_target_forms.py - #4267.

CV-LINT-REENTER must see a self-target written with the chart's own id
(`#<chart id>.<state>`) as a self-target, whatever form the target takes.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import lint_statecharts as lint


def _chart(target: str, *, reenter: bool = False) -> dict[str, Any]:
    arm: dict[str, Any] = {"target": target}
    if reenter:
        arm["reenter"] = True
    return {
        "id": "demo",
        "initial": "idle",
        "states": {
            "idle": {"on": {"GO": "busy"}},
            "busy": {"on": {"RETRY": arm}},
        },
    }


def _hits(chart: dict[str, Any]) -> list[lint.Finding]:
    return [f for f in lint.rule_reenter("demo.machine.json", chart) if f.rule == "CV-LINT-REENTER"]


@pytest.mark.parametrize("target", ["#demo.busy", "busy", ".busy", "#busy"])
def test_self_target_without_reenter_is_a_finding(target: str) -> None:
    assert len(_hits(_chart(target))) == 1


@pytest.mark.parametrize("target", ["#demo.busy", "busy", ".busy", "#busy"])
def test_self_target_with_reenter_is_clean(target: str) -> None:
    assert _hits(_chart(target, reenter=True)) == []


@pytest.mark.parametrize("target", ["#demo.idle", "idle", "#idle"])
def test_target_to_another_state_is_not_a_self_target(target: str) -> None:
    assert _hits(_chart(target)) == []


def test_id_qualified_nested_self_target_is_a_finding() -> None:
    chart = {
        "id": "demo",
        "initial": "a",
        "states": {
            "a": {
                "initial": "x",
                "states": {"x": {"on": {"E": {"target": "#demo.a.x"}}}, "y": {}},
            }
        },
    }
    assert len(_hits(chart)) == 1
