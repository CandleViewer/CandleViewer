"""Contract (#837 Q5, E42-T03): the `403 trading_disabled` problem carries the order-entry gate's
`reason` extension member. `OrderEntryRefusalReason` is the closed server set that
`24-internal-schemas.md` 8.10 lists, open-ended for readers; `TradingDisabledProblem` is `Problem`
plus a required `reason`; the shared `Forbidden` response documents and exemplifies it. Additive
only (C-6.3): two new schemas, one new example, and `Problem` itself is unchanged."""

from __future__ import annotations

from typing import Any

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import REPO_ROOT, load_openapi_spec

_SPEC = load_openapi_spec()
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_FORBIDDEN = _SPEC["components"]["responses"]["Forbidden"]
_REASONS = [
    "maintenance",
    "account_disabled_by_policy",
    "no_active_key",
    "account_unhealthy",
    "balance_stale",
]
_DOC = REPO_ROOT / "docs/plan/24-internal-schemas.md"


def _example() -> dict[str, Any]:
    value: dict[str, Any] = _FORBIDDEN["content"]["application/problem+json"]["examples"][
        "tradingDisabled"
    ]["value"]
    return value


def test_the_reason_set_is_closed_for_the_server_and_open_for_readers() -> None:
    reason = _SCHEMAS["OrderEntryRefusalReason"]
    assert reason["enum"] == _REASONS
    assert "Open-ended for readers" in " ".join(reason["description"].split())


def test_trading_disabled_problem_is_problem_plus_a_required_reason() -> None:
    problem, extra = _SCHEMAS["TradingDisabledProblem"]["allOf"]
    assert problem == {"$ref": "#/components/schemas/Problem"}
    assert extra["required"] == ["reason"]
    assert extra["properties"]["reason"] == {"$ref": "#/components/schemas/OrderEntryRefusalReason"}
    assert "reason" not in _SCHEMAS["Problem"]["properties"]


def test_the_forbidden_response_documents_the_gate_refusal() -> None:
    assert "`TradingDisabledProblem`" in _FORBIDDEN["description"]
    assert "`code: trading_disabled`" in _FORBIDDEN["description"]


def test_the_example_round_trips_and_uses_the_registry_title() -> None:
    example = _example()
    model = api.TradingDisabledProblem.model_validate(example)
    assert model.model_dump(mode="json", exclude_unset=True) == example
    entry = next(e for e in _SPEC["x-error-codes"] if e["code"] == "trading_disabled")
    assert (example["title"], example["status"], example["code"]) == (
        entry["title"],
        403,
        entry["code"],
    )


def test_the_generated_model_mirrors_the_schema() -> None:
    assert set(api.TradingDisabledProblem.model_fields) == set(api.Problem.model_fields) | {
        "reason"
    }


def test_the_internal_schema_lists_the_same_closed_set() -> None:
    section = _DOC.read_text(encoding="utf-8").split("### 8.10 Order-entry gate", 1)[1]
    table = section.split("\n\n", 3)[3].split("\n\n", 1)[0]
    rows = [line.split("|")[1].strip() for line in table.splitlines()[2:]]
    assert rows == [f"`{r}`" for r in _REASONS]
