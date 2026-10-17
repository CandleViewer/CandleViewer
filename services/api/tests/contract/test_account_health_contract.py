"""Contract (E27-T04): per-account health, wallet staleness and key-rotation fields. Additive only
(C-6.3): nothing pre-existing changes and nothing new is required; `connection_state` keeps its
enum (decision Q2 on #837); the documented example round-trips; `wallet` frames validate, with
health reported per account apart from balances, and every reason set is closed; the server's
`wallet` merge keeps the latest health of every account and still validates. The code that
serves these shapes agrees with them.
"""

from __future__ import annotations

import re
from typing import Any, get_args

import pytest
from pydantic import TypeAdapter

from candleviewer.accounts.health import (
    CONNECTION_STATE,
    AccountHealth,
    AccountHealthMonitor,
    HealthReason,
    HealthState,
)
from candleviewer.accounts.key_age import KeyRotation, KeyRotationPolicy, RotationState
from candleviewer.accounts.models import KeyStatus
from candleviewer.accounts.order_gate import AccountHealthCheck, DisabledReason, KeyStanding
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.domain.order_entry import REFUSAL_REASONS
from candleviewer.ws.coalescing import CoalescingQueue
from tests.contract.ws._harness import REPO, SCHEMAS, check_schema
from tests.unit.accounts._fakes import ACC, DAY, T0, Dms, FakeClock, Sizing, Standings

_SPEC: dict[str, Any] = load_openapi_spec()
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_LIST = _SPEC["paths"]["/exchange-accounts"]["get"]["responses"]["200"]["content"]
_WALLET = "cv://ws/v1/wallet.schema.json"
_WS_ENTRY: dict[str, Any] = SCHEMAS[_WALLET]["properties"]["health"]["items"]
_ACC = "a1000000-0000-4000-8000-000000000001"
_ACC_B = "a1000000-0000-4000-8000-000000000002"
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


def test_a_merged_wallet_window_keeps_every_account_health_and_validates() -> None:
    """Provider (C-6.2): the §8.2 `wallet` merge emits a frame the schema accepts, keeping the
    latest `health` entry of each account its window touched."""
    queue = CoalescingQueue("wallet")
    other = _ENTRY | {"exchange_account_id": _ACC_B}
    for delta in (
        {"balances": [_FULL]},
        {"balances": [], "health": [_ENTRY]},
        {"balances": [], "health": [other]},
    ):
        assert queue.offer(delta)
    [merged] = queue.take()
    assert merged.body == {"balances": [_FULL], "health": [_ENTRY, other]}
    disclosed = merged.body | {"coalesced": True, "coalesced_count": merged.coalesced_count}
    check_schema(_WALLET, disclosed, "wallet")


@pytest.mark.parametrize(
    ("state", "wire"),
    [
        (HealthState.HEALTHY, "connected"),
        (HealthState.DEGRADED, "degraded"),
        (HealthState.DOWN, "disconnected"),
    ],
)
def test_each_health_state_maps_to_its_documented_connection_state(
    state: HealthState, wire: str
) -> None:
    enum = _SCHEMAS["ExchangeAccount"]["properties"]["connection_state"]["enum"]
    assert CONNECTION_STATE[state] == wire and wire in enum


def _degraded_view() -> AccountHealth:
    """The monitor's view of an account that REST polling alone keeps up."""
    monitor = AccountHealthMonitor(FakeClock(), Dms())
    monitor.track(ACC)
    monitor.rest_ok(ACC)
    view = monitor.view(ACC)
    assert view is not None
    return view


def test_the_monitor_view_has_exactly_the_contract_fields_and_states() -> None:
    schema = _SCHEMAS["AccountHealth"]["properties"]
    assert set(_degraded_view().model_dump(mode="json")) == set(schema)
    assert [s.value for s in HealthState] == schema["state"]["enum"]


def test_the_monitor_reasons_are_the_closed_contract_set() -> None:
    reasons = _SCHEMAS["AccountHealth"]["properties"]["reason"]["enum"]
    assert list(get_args(HealthReason)) == reasons == _WS_ENTRY["properties"]["reason"]["enum"]


def test_the_monitor_view_validates_against_the_generated_rest_model() -> None:
    rest = _degraded_view().model_dump(mode="json")
    assert api.AccountHealth.model_validate(rest).state == "degraded"


def test_the_monitor_ws_entry_validates_against_the_wallet_schema() -> None:
    check_schema(_WALLET, {"balances": [], "health": [_degraded_view().ws_entry(ACC)]}, "wallet")


def test_the_account_check_asks_the_reasons_section_8_4_1_lists_in_order() -> None:
    """§8.4.1 owns only the account side of the gate; §8.10 (E42-T03) owns the closed set."""
    text = _GATE_DOC.read_text(encoding="utf-8")
    section = text[text.index("**8.4.1 Account checks") : text.index("### 8.5 ")]
    documented = re.findall(r"^\d\. `([a-z_]+)`:", section, flags=re.MULTILINE)
    unmonitored = AccountHealthMonitor(FakeClock(), Dms())
    asked = []
    for standing in (  # each refuses on every remaining check; the first one asked answers
        KeyStanding(False, DisabledReason.ACCOUNT_DISABLED),
        KeyStanding(has_active_key=False),
        KeyStanding(has_active_key=True),
    ):
        refusal = AccountHealthCheck(unmonitored, Standings({ACC: standing}), Sizing()).refusal(ACC)
        assert refusal is not None
        asked.append(refusal.reason)
    assert asked == documented and set(asked) < REFUSAL_REASONS


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
