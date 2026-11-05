"""The two `503` slugs #2828 adds to `x-error-codes` (rulings BQ-01, BQ-06): contract pins.

No route emits them yet; the routers move onto them in the ticket's second change (C-6.1).
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.ws._generated.error_codes import ERROR_META, WS_ERROR_CODES, ErrorCode

#: code -> (status, retryable, words its title must carry)
_SLUGS = {
    "step_up_unavailable": (503, False, ("step-up", "not wired", "nothing was done")),
    "lifecycle_unavailable": (503, True, ("inbox full", "degraded", "nothing was done")),
}


@pytest.fixture(scope="module")
def codes() -> dict[str, dict[str, Any]]:
    spec: dict[str, Any] = load_openapi_spec()
    return {e["code"]: e for e in spec["x-error-codes"]}


@pytest.mark.parametrize("code", sorted(_SLUGS))
def test_slug_is_a_rest_only_503_and_the_registry_mirrors_it(
    codes: dict[str, dict[str, Any]], code: str
) -> None:
    status, retryable, words = _SLUGS[code]
    entry = codes[code]
    assert (entry["status"], entry["retryable"]) == (status, retryable)
    assert entry.get("surface", ["rest"]) == ["rest"]
    for word in words:
        assert word in entry["title"].lower(), (code, word)
    meta = ERROR_META[ErrorCode(code)]
    assert (meta.surfaces, meta.retryable, meta.title) == (("rest",), retryable, entry["title"])
    assert ErrorCode(code) not in WS_ERROR_CODES


def test_no_generic_service_unavailable_slug_is_added(codes: dict[str, dict[str, Any]]) -> None:
    """BQ-01 option A: the narrow slug, never a catch-all (t04's pin stays true)."""
    assert "service_unavailable" not in codes
    assert "gateway_overloaded" not in codes  # BQ-06: one slug covers overload and degraded
