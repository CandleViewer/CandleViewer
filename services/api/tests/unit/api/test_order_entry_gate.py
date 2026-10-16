"""#837 Q5: the shared synchronous order-entry gate. Refusals use the closed reason set, the first
refusal wins in the given order (maintenance first), and a refusal renders as the 403
`trading_disabled` problem with its `reason` member."""

from __future__ import annotations

import json
from uuid import UUID

import pytest
import yaml

from candleviewer.admin.flags import MaintenanceGate
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH
from candleviewer.api.order_entry_gate import (
    REFUSAL_REASONS,
    OrderEntryCheck,
    OrderEntryRefusal,
    order_entry_refusal,
    refusal_problem,
)
from candleviewer.domain.order_entry import first_refusal

_ACCOUNT = UUID("a1000000-0000-4000-8000-000000000001")


class _Check:
    def __init__(self, refusal: OrderEntryRefusal | None) -> None:
        self._refusal, self.calls = refusal, 0

    def refusal(self, account_id: UUID | None) -> OrderEntryRefusal | None:
        self.calls += 1
        return self._refusal


def _gate(engaged: bool) -> MaintenanceGate:
    gate = MaintenanceGate()
    gate.set(engaged)
    return gate


def test_the_reason_set_is_closed() -> None:
    assert REFUSAL_REASONS == {"maintenance", "account_unhealthy", "key_rotation_overdue"}
    with pytest.raises(ValueError, match="unknown order-entry refusal reason"):
        OrderEntryRefusal("kill_switch", "x")  # type: ignore[arg-type]  # proves the runtime guard


def test_a_refusal_needs_a_detail() -> None:
    with pytest.raises(ValueError, match="detail"):
        OrderEntryRefusal("maintenance", " ")


def test_the_first_refusal_wins_and_later_checks_are_not_consulted() -> None:
    unhealthy = _Check(OrderEntryRefusal("account_unhealthy", "Account is not connected."))
    refusal = first_refusal((_gate(True), unhealthy), _ACCOUNT)
    assert refusal is not None and refusal.reason == "maintenance"
    assert unhealthy.calls == 0


def test_a_later_check_refuses_when_the_earlier_ones_pass() -> None:
    passing, overdue = _Check(None), _Check(OrderEntryRefusal("key_rotation_overdue", "Rotate."))
    refusal = first_refusal((_gate(False), passing, overdue), _ACCOUNT)
    assert refusal is not None and refusal.reason == "key_rotation_overdue"
    assert (passing.calls, overdue.calls) == (1, 1)


def test_no_refusal_lets_the_order_through() -> None:
    assert order_entry_refusal((_gate(False), _Check(None)), _ACCOUNT) is None


def test_a_refusal_is_the_trading_disabled_problem_with_its_reason() -> None:
    response = order_entry_refusal((_gate(True),), None)
    assert response is not None
    body = json.loads(bytes(response.body))
    assert (response.status_code, response.media_type) == (403, "application/problem+json")
    assert {k: body[k] for k in ("code", "reason", "status")} == {
        "code": "trading_disabled",
        "reason": "maintenance",
        "status": 403,
    }
    assert body["type"] == "https://candleviewer.local/errors/trading_disabled"
    assert body["detail"] == "Maintenance mode is on; order entry is paused."


def test_the_problem_title_is_the_registry_title() -> None:
    spec = yaml.safe_load(OPENAPI_SPEC_PATH.read_text(encoding="utf-8"))
    entry = next(e for e in spec["x-error-codes"] if e["code"] == "trading_disabled")
    refusal = OrderEntryRefusal("account_unhealthy", "Account is not connected.")
    body = json.loads(bytes(refusal_problem(refusal).body))
    assert body["title"] == entry["title"] and entry["status"] == 403


@pytest.mark.parametrize(("engaged", "reason"), [(True, "maintenance"), (False, None)])
def test_the_maintenance_gate_is_an_order_entry_check(engaged: bool, reason: str | None) -> None:
    check: OrderEntryCheck = _gate(engaged)
    refusal = check.refusal(_ACCOUNT)
    assert (refusal.reason if refusal else None) == reason
