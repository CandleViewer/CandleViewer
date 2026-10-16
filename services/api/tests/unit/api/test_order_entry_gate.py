"""#837 Q5: the order-entry gate at the API edge and the admin maintenance gate in its first slot.
The kernel itself (`candleviewer.domain.order_entry`, its reason set, refusal, composition and
fail-closed guards) is tested in `tests/unit/domain/test_order_entry.py`; this file keeps what the
API edge adds (the 403 `trading_disabled` problem with its `reason`, logged and counted only when
it refuses), the `MaintenanceGate` as the kernel's `GlobalOrderEntryCheck`, and the scope text."""

from __future__ import annotations

import json
from types import ModuleType
from typing import Any, cast
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.flags import MaintenanceGate, order_entry_refusals_total
from candleviewer.api import order_entry_gate
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.order_entry_gate import (
    REFUSAL_REASONS,
    GlobalOrderEntryCheck,
    OrderEntryGate,
    OrderEntryRefusal,
    order_entry_refusal,
    refusal_problem,
)

_ACCOUNT = UUID("a1000000-0000-4000-8000-000000000001")
_NO_KEY = OrderEntryRefusal("no_active_key", "No active API key for this account.")


class _Check:
    def __init__(self, refusal: OrderEntryRefusal | None = None) -> None:
        self._refusal = refusal
        self.seen: list[UUID] = []

    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        self.seen.append(account_id)
        return self._refusal


class _Raising:
    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        raise RuntimeError("monitor state unreadable")


def _maintenance(engaged: bool) -> MaintenanceGate:
    gate = MaintenanceGate()
    gate.set(engaged)
    return gate


def _body(gate: OrderEntryGate) -> dict[str, object]:
    response = order_entry_refusal(gate, _ACCOUNT)
    assert response is not None and response.status_code == 403
    assert response.media_type == "application/problem+json"
    body: dict[str, object] = json.loads(bytes(response.body))
    return body


def _refusal_counts() -> dict[str, float]:
    """Every series of the refusal counter now, by reason, whichever reason created it."""
    return {
        sample.labels["reason"]: sample.value
        for family in order_entry_refusals_total.collect()
        for sample in family.samples
        if sample.name.endswith("_total")
    }


def test_the_reason_set_is_the_contract_enum() -> None:
    schemas = cast(dict[str, Any], load_openapi_spec())["components"]["schemas"]
    assert set(schemas["OrderEntryRefusalReason"]["enum"]) == REFUSAL_REASONS


@pytest.mark.parametrize("engaged", [True, False])
def test_the_maintenance_gate_is_the_global_order_entry_check(engaged: bool) -> None:
    check: GlobalOrderEntryCheck = _maintenance(engaged)  # mypy pins the slot type too
    assert MaintenanceGate.scope == "global"
    expected = OrderEntryRefusal("maintenance", "Order entry is paused.") if engaged else None
    assert check.refusal(_ACCOUNT) == expected
    assert OrderEntryGate(check).refusal(_ACCOUNT) == expected


@pytest.mark.parametrize("reverse", [False, True])
def test_maintenance_comes_first_and_wins_whatever_the_account_check_order(reverse: bool) -> None:
    maintenance, first, second = _maintenance(True), _Check(_NO_KEY), _Check()
    accounts = (second, first) if reverse else (first, second)
    gate = OrderEntryGate(maintenance, *accounts)
    assert gate.checks == (maintenance, *accounts)
    refusal = gate.refusal(_ACCOUNT)
    assert refusal is not None and refusal.reason == "maintenance"
    assert (first.seen, second.seen) == ([], [])


def test_every_check_gets_the_account_id_through_the_api_edge() -> None:
    first, second = _Check(), _Check()
    assert order_entry_refusal(OrderEntryGate(_maintenance(False), first, second), _ACCOUNT) is None
    assert first.seen == second.seen == [_ACCOUNT]


def test_a_raising_check_propagates_through_the_api_edge_and_never_admits() -> None:
    with pytest.raises(RuntimeError):
        order_entry_refusal(OrderEntryGate(_maintenance(False), _Raising()), _ACCOUNT)


def test_a_refusal_is_the_problem_with_its_own_reason_and_detail() -> None:
    body = _body(OrderEntryGate(_maintenance(False), _Check(_NO_KEY)))
    assert {k: body[k] for k in ("status", "code", "reason", "detail")} == {
        "status": 403,
        "code": "trading_disabled",
        "reason": "no_active_key",
        "detail": "No active API key for this account.",
    }
    assert body["type"] == "https://candleviewer.local/errors/trading_disabled"


def test_a_maintenance_refusal_is_the_contract_example() -> None:
    body = _body(OrderEntryGate(_maintenance(True)))
    assert (body["reason"], body["detail"]) == ("maintenance", "Order entry is paused.")


def test_the_problem_title_is_the_registry_title() -> None:
    codes = cast(list[dict[str, Any]], load_openapi_spec()["x-error-codes"])
    entry = next(e for e in codes if e["code"] == "trading_disabled")
    body = json.loads(bytes(refusal_problem(_NO_KEY).body))
    assert body["title"] == entry["title"] and entry["status"] == 403


def test_a_refusal_is_logged_and_counted_without_its_detail() -> None:
    counter = order_entry_refusals_total.labels(reason="no_active_key")
    before = counter._value.get()
    with capture_logs() as logs:
        _body(OrderEntryGate(_maintenance(False), _Check(_NO_KEY)))
    assert counter._value.get() == before + 1
    [event] = [e for e in logs if e["event"] == "order_entry_refused"]
    assert (event["reason"], event["account_id"], event["log_level"]) == (
        "no_active_key",
        str(_ACCOUNT),
        "info",
    )
    assert "detail" not in event


def test_an_admitted_order_is_neither_logged_nor_counted() -> None:
    gate = OrderEntryGate(_maintenance(False), _Check())
    before = _refusal_counts()
    with capture_logs() as logs:
        assert order_entry_refusal(gate, _ACCOUNT) is None
    assert "order_entry_refused" not in [event["event"] for event in logs]
    assert _refusal_counts() == before


_NEVER_GATED = (
    "Attaching a missing native SL, tightening a stop, or re-arming a protective trigger is never "
    'gated; "trigger re-armed" above means an exposure-increasing (entry) trigger. An amend with '
    "any risk-increasing component is gated."
)


@pytest.mark.parametrize("module", [order_entry_gate])
def test_the_scope_never_gates_attaching_a_missing_native_sl(module: ModuleType) -> None:
    assert _NEVER_GATED in " ".join((module.__doc__ or "").split())
