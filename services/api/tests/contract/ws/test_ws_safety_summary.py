"""#2302 (E09-D06 rule 1): the `system` safety summary, contract first (C-6.1).

`23-ws-protocol.md` §15.9 gives `system` a `kind: "safety"` frame that a locked screen can show
as class, count and time only: by schema it carries exactly `kind`, `severity`, `safety_class`,
`environment`, `state`, `affected_count` and `since_ms`, so no account, symbol, size, user name or
free text. The `health` snap states each (class, environment)'s coverage in `safety_classes`:
`raised`, `clear` or `unknown`. These pin the schema the bundle derives from §15.9 and the
prose rules the publisher will be held to; the emitters land with #932, #955 and #1111."""

from __future__ import annotations

from typing import Any

import pytest

from tests.contract.ws._harness import PROTOCOL_DOC, SCHEMAS, _validator

_SYSTEM = "cv://ws/v1/system.schema.json"
_CLASSES = (
    "native_sl_missing",
    "sl_attach_failed",
    "liquidation_risk",
    "risk_auto_flatten",
    "risk_lockout",
    "unwind_incomplete",
    "order_entry_halted",
)
_RAISED: dict[str, Any] = {
    "kind": "safety",
    "severity": "critical",
    "safety_class": "native_sl_missing",
    "environment": "live",
    "state": "raised",
    "affected_count": 1,
    "since_ms": 1_789_132_262_000,
}
_CLEARED: dict[str, Any] = _RAISED | {"severity": "info", "state": "cleared", "affected_count": 0}
_UUID = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001"
_HEALTH: dict[str, Any] = {"kind": "health", "health": "healthy", "degraded_topics": []}


def _errors(body: Any) -> list[str]:
    return [e.message for e in _validator(_SYSTEM).iter_errors(body)]


@pytest.mark.parametrize("body", [_RAISED, _CLEARED], ids=["raised", "cleared"])
def test_safety_frame_validates_against_the_system_schema(body: dict[str, Any]) -> None:
    assert _errors(body) == []


@pytest.mark.parametrize("environment", ["live", "demo", "testnet"])
def test_safety_frame_carries_an_environment_of_the_common_enum(environment: str) -> None:
    assert _errors(_RAISED | {"environment": environment}) == []
    assert _errors(_RAISED | {"environment": "paper"})


@pytest.mark.parametrize("safety_class", _CLASSES)
def test_safety_frame_accepts_every_class_of_the_closed_enum(safety_class: str) -> None:
    assert _errors(_RAISED | {"safety_class": safety_class}) == []


def test_safety_class_enum_is_exactly_the_seven_classes_of_section_15_9() -> None:
    assert tuple(SCHEMAS[_SYSTEM]["$defs"]["safetyClass"]["enum"]) == _CLASSES
    assert "safety" in SCHEMAS[_SYSTEM]["properties"]["kind"]["enum"]


@pytest.mark.parametrize("safety_class", ["naked_position", "kill_switch", "", "NATIVE_SL_MISSING"])
def test_safety_frame_refuses_a_class_outside_the_enum(safety_class: str) -> None:
    assert _errors(_RAISED | {"safety_class": safety_class})


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({"exchange_account_ids": ["9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001"]}, id="ids"),
        pytest.param({"account_id": "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001"}, id="account_id"),
        pytest.param({"symbol": "BTCUSDT"}, id="symbol"),
        pytest.param({"affected_symbols": ["BTCUSDT"]}, id="affected_symbols"),
        pytest.param({"qty": "0.5"}, id="qty"),
        pytest.param({"username": "owner.alice"}, id="username"),
        pytest.param({"message": "BTCUSDT on account A has no stop."}, id="message"),
        pytest.param({"reason": "free text"}, id="reason"),
        pytest.param({"kill_switch": {"engaged": True, "scope": "global"}}, id="kill_switch"),
        pytest.param({"safety_classes": []}, id="safety_classes"),
        pytest.param({"_by_account": {}}, id="in-process-breakdown"),
        pytest.param({"_at_ms": 1}, id="in-process-time"),
    ],
)
def test_safety_frame_refuses_any_field_beyond_its_six(extra: dict[str, Any]) -> None:
    assert _errors(_RAISED | extra)


@pytest.mark.parametrize(
    "field", ["severity", "safety_class", "environment", "state", "affected_count", "since_ms"]
)
def test_safety_frame_requires_each_of_its_fields(field: str) -> None:
    assert _errors({k: v for k, v in _RAISED.items() if k != field})


@pytest.mark.parametrize("count", [-1, 1.5, "1", None])
def test_safety_frame_refuses_a_count_that_is_not_a_non_negative_integer(count: Any) -> None:
    assert _errors(_RAISED | {"affected_count": count})
    assert _errors(_CLEARED | {"affected_count": count})


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_RAISED | {"affected_count": 0}, id="raised-with-none-affected"),
        pytest.param(_RAISED | {"severity": "warning"}, id="raised-not-critical"),
        pytest.param(_CLEARED | {"affected_count": 1}, id="cleared-with-one-affected"),
        pytest.param(_CLEARED | {"severity": "critical"}, id="cleared-still-critical"),
        pytest.param(_RAISED | {"state": "acknowledged"}, id="unknown-state"),
    ],
)
def test_safety_frame_ties_severity_and_count_to_its_state(body: dict[str, Any]) -> None:
    assert _errors(body)


@pytest.mark.parametrize(
    "field", ["safety_class", "environment", "state", "affected_count", "since_ms"]
)
def test_safety_fields_appear_on_no_other_kind(field: str) -> None:
    assert _errors(_HEALTH | {field: _RAISED[field]})


def test_health_snap_carries_the_safety_coverage() -> None:
    items = [
        {
            "safety_class": "native_sl_missing",
            "environment": "live",
            "state": "raised",
            "affected_count": 1,
            "since_ms": 1,
        },
        {"safety_class": "risk_lockout", "environment": "live", "state": "clear"},
        {"safety_class": "order_entry_halted", "environment": "demo", "state": "unknown"},
    ]
    assert _errors(_HEALTH | {"safety_classes": items}) == []


_ITEM = {"safety_class": "risk_lockout", "environment": "live"}


@pytest.mark.parametrize(
    "item",
    [
        pytest.param(_ITEM | {"state": "raised", "affected_count": 0, "since_ms": 1}, id="zero"),
        pytest.param(_ITEM | {"state": "raised", "since_ms": 1}, id="raised-no-count"),
        pytest.param(_ITEM | {"state": "raised", "affected_count": 1}, id="raised-no-time"),
        pytest.param(_ITEM | {"state": "clear", "affected_count": 1}, id="clear-with-count"),
        pytest.param(_ITEM | {"state": "unknown", "since_ms": 1}, id="unknown-with-time"),
        pytest.param(_ITEM | {"state": "cleared"}, id="frame-state"),
        pytest.param({"safety_class": "risk_lockout", "state": "clear"}, id="no-environment"),
        pytest.param(_ITEM | {"state": "clear", "_by_account": {}}, id="breakdown"),
        pytest.param(_ITEM | {"state": "clear", "exchange_account_ids": [_UUID]}, id="account-ids"),
    ],
)
def test_health_snap_refuses_an_item_that_is_not_class_environment_state_count_and_time(
    item: dict[str, Any],
) -> None:
    assert _errors(_HEALTH | {"safety_classes": [item]})


def test_safety_classes_appears_only_on_health() -> None:
    assert _errors({"kind": "notice", "reason": "x", "safety_classes": []})


def _section() -> str:
    text = " ".join(PROTOCOL_DOC.read_text(encoding="utf-8").split())
    return text.split("### 15.9 `SystemUpdate`", 1)[1].split("### 15.10", 1)[0]


@pytest.mark.parametrize(
    "sentence",
    [
        # M2: the flapping bound the publisher (24 §8.13) will be held to.
        "A raise is sent at once, never delayed. A clear waits a **dwell** of 1 000 ms",
        "So there is at most one `raised`/`cleared` pair per class and environment per 1 000 ms.",
        # H1: the per-connection cut, existence included.
        "so a connection whose scoped count stays 0 is sent nothing at all for that class, "
        "neither a frame nor a boolean, since existence leaks too.",
        # M1: no false all-clear.
        "A class is `clear` only once its emitter has finished its first pass since start-up; "
        "until then it is `unknown`.",
        "The lock card never draws an all-clear while any `safety_classes` item is `unknown`, "
        "and draws nothing, not an all-clear, when the field is absent.",
        # L3: one item per key; the producer's test comes with the producer.
        "The producer emits exactly one item per (`safety_class`, `environment`)",
    ],
)
def test_section_15_9_pins_the_safety_rules(sentence: str) -> None:
    assert sentence in _section()


def test_section_8_2_bounds_safety_flapping() -> None:
    text = " ".join(PROTOCOL_DOC.read_text(encoding="utf-8").split())
    section = text.split("### 8.2 Coalescing rules per topic family", 1)[1].split("### 8.3", 1)[0]
    assert (
        "a clear waits a 1 000 ms dwell, so at most one raised/cleared pair per class and "
        "environment per 1 000 ms"
    ) in section


def test_section_15_9_states_the_lock_card_consumer_rule() -> None:
    assert (
        "the client renders only frames of `kind` `kill_switch`, `exchange_state`, `health`, "
        "`degraded_data`, `clock_drift`, `shutdown_notice` and `safety`. From each it renders "
        "only an icon, the class label, the count, the since-time and the environment badge; "
        "every other field is dropped"
    ) in _section()
