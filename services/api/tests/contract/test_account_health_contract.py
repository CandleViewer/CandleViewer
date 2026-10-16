"""Contract (E27-T04): per-account health, wallet staleness and key-rotation fields. Additive only
(C-6.3): nothing pre-existing changes and nothing new is required; `connection_state` keeps its
enum (decision Q2 on #837); the documented example round-trips; `wallet` frames validate, with
health reported per account apart from balances; every reason set is closed and agrees with code.
"""

from __future__ import annotations

import re
from typing import Any, get_args

import pytest
from pydantic import TypeAdapter

from candleviewer.accounts.health import (
    CONNECTION_STATE,
    AccountHealthMonitor,
    HealthReason,
    HealthState,
)
from candleviewer.accounts.key_age import KeyRotation, KeyRotationPolicy, RotationState
from candleviewer.accounts.models import KeyStatus
from candleviewer.accounts.order_gate import OrderEntryReason
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from tests.contract.ws._harness import REPO, SCHEMAS, check_schema
from tests.unit.accounts._fakes import ACC, DAY, T0, Dms, FakeClock

_SPEC = load_openapi_spec()
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_LIST = _SPEC["paths"]["/exchange-accounts"]["get"]["responses"]["200"]["content"]
_WALLET = "cv://ws/v1/wallet.schema.json"
_WS_ENTRY: dict[str, Any] = SCHEMAS[_WALLET]["properties"]["health"]["items"]
_ACC = "a1000000-0000-4000-8000-000000000001"
_ITEM = {"exchange_account_id": _ACC, "coin": "USDT", "equity": "1", "updated_at_ms": 1}
_FULL = _ITEM | {"stale": True, "stale_since_ms": 1}
_HEALTH = dict(exchange_account_id=_ACC, state="degraded", reason="rest_only", rest_only=True)
_ENTRY = _HEALTH | {"heartbeat_age_ms": None, "changed_at_ms": 1}
_GATE_DOC = REPO / "docs" / "plan" / "24-internal-schemas.md"
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
    assert set(_WS_ENTRY["required"]) == fields - {"changed_at"} | {
        "exchange_account_id",
        "changed_at_ms",
    }


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


@pytest.mark.parametrize(
    "frame",
    [{"balances": [_ITEM]}, {"balances": [_FULL], "health": [_ENTRY]}],
    ids=["pre_existing", "with_health"],
)
def test_wallet_frames_validate_with_and_without_the_new_fields(frame: dict[str, Any]) -> None:
    check_schema(_WALLET, frame, "wallet")


def test_a_health_only_wallet_frame_covers_an_account_with_no_snapshot() -> None:
    down = _ENTRY | {"state": "down", "reason": "never_connected", "rest_only": False}
    check_schema(_WALLET, {"balances": [], "health": [down]}, "wallet")


@pytest.mark.parametrize(
    "frame",
    [
        {"balances": [], "health": [_HEALTH | {"changed_at_ms": 1}]},
        {"balances": [], "health": [_ENTRY | {"state": "up"}]},
        {"balances": [], "health": [_ENTRY | {"reason": "retCode 10003: API key is invalid"}]},
        {"balances": [_ITEM | {"health": _ENTRY}]},
    ],
    ids=["partial", "unknown_state", "open_reason", "on_a_balance_item"],
)
def test_wallet_health_refuses_a_partial_entry_an_open_code_or_a_balance_item(
    frame: dict[str, Any],
) -> None:
    with pytest.raises(AssertionError, match="violates"):
        check_schema(_WALLET, frame, "wallet")


def test_the_monitor_serves_exactly_the_contract_shapes() -> None:
    monitor = AccountHealthMonitor(FakeClock(), Dms())
    monitor.track(ACC)
    monitor.rest_ok(ACC)
    view = monitor.view(ACC)
    assert view is not None
    rest, schema = view.model_dump(mode="json"), _SCHEMAS["AccountHealth"]["properties"]
    assert set(rest) == set(schema) and [s.value for s in HealthState] == schema["state"]["enum"]
    reasons = list(get_args(HealthReason))
    assert reasons == schema["reason"]["enum"] == _WS_ENTRY["properties"]["reason"]["enum"]
    assert api.AccountHealth.model_validate(rest).state == "degraded"
    assert CONNECTION_STATE[view.state] == "degraded"
    check_schema(_WALLET, {"balances": [], "health": [view.ws_entry(ACC)]}, "wallet")


def test_the_order_entry_reasons_are_the_documented_closed_set() -> None:
    text = _GATE_DOC.read_text(encoding="utf-8")
    section = text[text.index("**8.4.1 Order-entry gate") : text.index("### 8.5 ")]
    documented = re.findall(r"^\| `([a-z_]+)` +\| E\d\d-", section, flags=re.MULTILINE)
    assert documented == list(get_args(OrderEntryReason))


@pytest.mark.parametrize("status", [KeyStatus.ACTIVE, KeyStatus.REVOKED])
def test_the_key_age_evaluator_serves_exactly_the_api_key_fields(status: KeyStatus) -> None:
    schema = _SCHEMAS["ApiKey"]["properties"]
    assert [*(s.value for s in RotationState), None] == schema["rotation_state"]["enum"]
    rotation = KeyRotationPolicy().evaluate(T0, status, now=T0 + 80 * DAY)
    wire = TypeAdapter(KeyRotation).dump_python(rotation, mode="json")
    assert set(wire) == {"rotation_due_at", "rotation_state"} <= set(schema)
    base = dict(id=_ACC, exchange_account_id=_ACC, key_id_masked="...AbC1", status=status.value)
    key = api.ApiKey.model_validate(base | wire)
    assert (key.rotation_due_at, key.rotation_state) == (
        (T0 + 90 * DAY, "warn") if status is KeyStatus.ACTIVE else (None, None)
    )
