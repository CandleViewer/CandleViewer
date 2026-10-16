"""Contract (E27-T04): per-account health, wallet staleness and key-rotation fields. Additive only
(C-6.3): nothing pre-existing changes and nothing new is required; `connection_state` keeps its
enum (decision Q2 on #837); the documented example round-trips; `wallet` items validate.
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from tests.contract.ws._harness import check_schema

_SPEC = load_openapi_spec()
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_LIST = _SPEC["paths"]["/exchange-accounts"]["get"]["responses"]["200"]["content"]
_WALLET = "cv://ws/v1/wallet.schema.json"
_ACC = "a1000000-0000-4000-8000-000000000001"
_ITEM = {"exchange_account_id": _ACC, "coin": "USDT", "equity": "1", "updated_at_ms": 1}
_WS_HEALTH = dict(state="degraded", reason="rest_only", heartbeat_age_ms=None, rest_only=True)
_FULL = _ITEM | {"stale": True, "stale_since_ms": 1, "health": _WS_HEALTH | {"changed_at_ms": 1}}
#: name -> (fields this change adds, the `required` list as it stood before it)
_ADDED = {
    "ExchangeAccount": (
        {"health", "balance_stale_since"},
        ["id", "exchange", "environment", "kind", "label", "exchange_uid"],
    ),
    "ApiKey": (
        {"rotation_due_at", "rotation_state"},
        ["id", "exchange_account_id", "key_id_masked", "status"],
    ),
}


def test_account_health_requires_exactly_its_five_fields() -> None:
    schema = _SCHEMAS["AccountHealth"]
    fields = {"state", "reason", "heartbeat_age_ms", "rest_only", "changed_at"}
    assert set(schema["required"]) == fields == set(schema["properties"])
    assert schema["properties"]["state"]["enum"] == ["healthy", "degraded", "down"]


@pytest.mark.parametrize("name", sorted(_ADDED))
def test_new_fields_are_optional_additions(name: str) -> None:
    added, required = _ADDED[name]
    assert added <= set(_SCHEMAS[name]["properties"]) and _SCHEMAS[name]["required"] == required


def test_connection_state_enum_is_unchanged() -> None:
    enum = _SCHEMAS["ExchangeAccount"]["properties"]["connection_state"]["enum"]
    assert enum == ["pending", "connected", "degraded", "disconnected", "disabled"]


def test_rotation_fields_accept_null_and_the_three_states() -> None:
    base = dict(id=_ACC, exchange_account_id=_ACC, key_id_masked="...AbC1", status="active")
    assert api.ApiKey.model_validate(base | {"rotation_state": None}).rotation_due_at is None
    for state in ("ok", "warn", "overdue"):
        assert api.ApiKey.model_validate(base | {"rotation_state": state}).rotation_state == state


def test_documented_example_round_trips() -> None:
    item = _LIST["application/json"]["examples"]["twoAccounts"]["value"]["items"][0]
    account = api.ExchangeAccount.model_validate(item)
    assert account.health is not None and account.health.state == "healthy"
    dumped = account.model_dump(mode="json", exclude_unset=True)
    assert api.ExchangeAccount.model_validate(dumped) == account


@pytest.mark.parametrize("item", [_ITEM, _FULL])
def test_wallet_items_validate_with_and_without_the_new_fields(
    item: dict[str, Any],
) -> None:
    check_schema(_WALLET, {"balances": [item]}, "wallet")


@pytest.mark.parametrize("health", [_WS_HEALTH, _WS_HEALTH | {"changed_at_ms": 1, "state": "up"}])
def test_wallet_health_refuses_a_partial_or_unknown_state(
    health: dict[str, Any],
) -> None:
    with pytest.raises(AssertionError, match="violates"):
        check_schema(_WALLET, {"balances": [_ITEM | {"health": health}]}, "wallet")
