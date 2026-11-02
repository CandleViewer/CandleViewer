"""Pin the E11-X02 engine guardrail Semgrep rules: ids and severities (#392).

An ERROR -> WARNING edit would silently turn a blocking gate advisory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

RULES_DIR = Path(__file__).resolve().parents[2] / ".semgrep"

PINNED = {
    "cv-engine-html-sink": "ERROR",
    "cv-engine-proto-pollution": "ERROR",
    "cv-engine-shader-source-dynamic": "ERROR",
    "cv-ws-wire-count-alloc-ts": "ERROR",
    "cv-engine-typed-array-index-unchecked": "WARNING",
    "cv-engine-decoded-nonfinite": "WARNING",
}


@pytest.mark.parametrize(("rule_id", "severity"), sorted(PINNED.items()))
def test_engine_guardrail_rule_has_pinned_severity(rule_id: str, severity: str) -> None:
    doc = yaml.safe_load((RULES_DIR / f"{rule_id}.yml").read_text(encoding="utf-8"))
    rules = {r["id"]: r for r in doc["rules"]}
    assert set(rules) == {rule_id}
    assert rules[rule_id]["severity"] == severity
