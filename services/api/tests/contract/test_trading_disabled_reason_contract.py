"""Contract (#837 Q5, E42-T03): the `403 trading_disabled` problem carries the order-entry gate's
`reason`, from the closed server set `OrderEntryRefusalReason` (`24-internal-schemas.md` 8.10;
open-ended for readers). `TradingDisabledProblem` is `Problem` with `code` pinned plus a required
`reason`; `Forbidden` is `anyOf: [Problem, TradingDisabledProblem]`. Additive (C-6.3)."""

from __future__ import annotations

from typing import Any

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec

_SPEC = load_openapi_spec()
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_BODY = _SPEC["components"]["responses"]["Forbidden"]["content"]["application/problem+json"]
_EXAMPLE: dict[str, Any] = _BODY["examples"]["tradingDisabled"]["value"]
_REASONS = ["maintenance", "account_disabled_by_policy", "no_active_key", "account_unhealthy"]
_DOC = OPENAPI_SPEC_PATH.parent / "24-internal-schemas.md"


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def test_the_reason_set_is_closed_for_the_server_and_open_for_readers() -> None:
    reason = _SCHEMAS["OrderEntryRefusalReason"]
    assert reason["enum"] == _REASONS
    assert "Open-ended for readers" in " ".join(reason["description"].split())


def test_trading_disabled_problem_is_problem_plus_a_required_reason() -> None:
    problem, extra = _SCHEMAS["TradingDisabledProblem"]["allOf"]
    assert (problem, extra["required"]) == (_ref("Problem"), ["reason"])
    assert extra["properties"]["code"] == {"const": "trading_disabled"}
    assert extra["properties"]["reason"] == _ref("OrderEntryRefusalReason")
    assert "reason" not in _SCHEMAS["Problem"]["properties"]
    assert set(api.TradingDisabledProblem.model_fields) == set(api.Problem.model_fields) | {
        "reason"
    }
    assert _BODY["schema"] == {"anyOf": [_ref("Problem"), _ref("TradingDisabledProblem")]}


def test_the_example_round_trips_with_the_neutral_registry_title() -> None:
    model = api.TradingDisabledProblem.model_validate(_EXAMPLE)
    assert model.model_dump(mode="json", exclude_unset=True) == _EXAMPLE
    entry = next(e for e in _SPEC["x-error-codes"] if e["code"] == "trading_disabled")
    # Neutral (C-6.3 note): the code also covers the account reasons, not only maintenance.
    assert entry["title"] == _EXAMPLE["title"] == "Order entry refused"
    assert (_EXAMPLE["status"], _EXAMPLE["code"]) == (403, "trading_disabled")
    # Neutral too: the order kill switch and an unreadable store engage the gate.
    assert _EXAMPLE["detail"] == "Order entry is paused."


def test_the_internal_schema_lists_the_same_closed_set() -> None:
    section = _DOC.read_text(encoding="utf-8").split("### 8.10 Order-entry gate", 1)[1]
    table = section.split("\n\n", 3)[3].split("\n\n", 1)[0]
    rows = [line.split("|")[1].strip() for line in table.splitlines()[2:]]
    assert rows == [f"`{r}`" for r in _REASONS]
