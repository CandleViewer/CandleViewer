"""E21-X02 (#652; the model's G-06; the ticket's SAST deliverable): the rule
`cv-marketdata-path-from-request` looks where the market-data read path lives. Every module behind
`GET /market/heatmap` and the other market-data routes matches one of the rule's `paths.include`
globs, and so does its fixture, so the rule cannot quietly stop covering a module; the fixture's
firing and clean lines are checked by `tools/ci/check_semgrep_rule_tests.py`."""

from __future__ import annotations

import fnmatch
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[5]
_RULE = _REPO / ".semgrep" / "cv-marketdata-path-from-request.yml"
_API = _REPO / "services" / "api" / "candleviewer"


def test_the_path_rule_covers_every_market_data_read_module() -> None:
    (rule,) = yaml.safe_load(_RULE.read_text(encoding="utf-8"))["rules"]
    globs = rule["paths"]["include"]
    modules = sorted(
        str(p.relative_to(_REPO))
        for p in (
            *_API.glob("api/market*.py"),
            *_API.glob("orderflow/heatmap*.py"),
            _API / "heatmap_wiring.py",
        )
    )
    assert {"services/api/candleviewer/api/market_heatmap.py",
            "services/api/candleviewer/orderflow/heatmap_history.py",
            "services/api/candleviewer/heatmap_wiring.py"} <= set(modules)  # fmt: skip
    uncovered = [m for m in modules if not any(fnmatch.fnmatch(m, g) for g in globs)]
    assert uncovered == []
    fixture = ".semgrep/tests/cv-marketdata-path-from-request.py"
    assert any(fnmatch.fnmatch(fixture, g) for g in globs)
    assert rule["metadata"]["cwe"].startswith("CWE-22:")
    assert rule["severity"] == "ERROR"
