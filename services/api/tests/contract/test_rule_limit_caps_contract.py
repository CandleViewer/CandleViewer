"""#3232: the contract's `x-cv-limit-caps` on `RuleIr` mirrors `candleviewer.rules.limits`.

The caps live once, in the limits module (C-16.5); the contract states them for clients, so the
two must not drift. The defaults the caps sit above are the `RuleLimits` ones on both sides.
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.rules.limits import BUDGET_FIELDS, LIMIT_CAPS, LIMIT_DEFAULTS


@pytest.fixture(scope="module")
def schemas() -> dict[str, Any]:
    components = load_openapi_spec()["components"]
    assert isinstance(components, dict)
    found = components["schemas"]
    assert isinstance(found, dict)
    return found


def test_contract_limit_caps_match_rules_limits(schemas: dict[str, Any]) -> None:
    assert schemas["RuleIr"]["x-cv-limit-caps"] == dict(LIMIT_CAPS)


def test_contract_limit_defaults_match_rules_limits_and_sit_below_the_caps(
    schemas: dict[str, Any],
) -> None:
    limits = schemas["RuleLimits"]["properties"]
    assert {f: limits[f]["default"] for f in BUDGET_FIELDS} == dict(LIMIT_DEFAULTS)
    assert all(LIMIT_DEFAULTS[f] < LIMIT_CAPS[f] for f in BUDGET_FIELDS)
