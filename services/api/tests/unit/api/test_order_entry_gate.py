"""#837 Q5: the shared synchronous order-entry gate. A frozen composed gate puts the maintenance
check first and never runs dry; every call names the account; the first refusal wins; a refusal
uses the closed reason set and renders as the 403 `trading_disabled` problem with its `reason`,
logged and counted only when it refuses; nothing fails open (no maintenance check, an account
check in the maintenance slot, a non-check, a missing or mistyped account id, a raising check)."""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.flags import MaintenanceGate, order_entry_refusals_total
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.order_entry_gate import (
    REFUSAL_REASONS,
    OrderEntryCheck,
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


def test_the_reason_set_is_closed() -> None:
    assert REFUSAL_REASONS == {
        "maintenance",
        "account_disabled_by_policy",
        "no_active_key",
        "account_unhealthy",
    }


def test_an_unknown_reason_is_refused_when_the_refusal_is_built() -> None:
    with pytest.raises(ValueError, match="unknown order-entry refusal reason"):
        OrderEntryRefusal("balance_stale", "x")  # type: ignore[arg-type]  # the runtime guard


def test_the_reason_set_is_the_contract_enum() -> None:
    schemas = load_openapi_spec()["components"]["schemas"]
    if "OrderEntryRefusalReason" not in schemas:
        pytest.skip("the contract enum lands with #2592, which merges before this gate")
    assert set(schemas["OrderEntryRefusalReason"]["enum"]) == REFUSAL_REASONS


def test_a_refusal_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _NO_KEY.reason = "maintenance"  # type: ignore[misc]  # proves the dataclass is frozen


@pytest.mark.parametrize(
    "detail",
    [
        " ",
        "x" * 201,
        "Account a1000000-0000-4000-8000-000000000001 refused",
        "deadbeefcafe0123babe",
        "Account ABCDEF01-ABCD-4BCD-8BCD-ABCDEF012345 refused",
        "DEADBEEFCAFEBABEFACE",
    ],
)
def test_a_refusal_detail_is_short_text_without_ids(detail: str) -> None:
    with pytest.raises(ValueError, match="detail"):
        OrderEntryRefusal("account_unhealthy", detail)
    assert OrderEntryRefusal("account_unhealthy", "x" * 200)


def test_a_gate_is_frozen() -> None:
    gate = OrderEntryGate(_maintenance(False))
    with pytest.raises(dataclasses.FrozenInstanceError):
        gate.checks = ()  # type: ignore[misc]  # proves the composed gate is frozen


def test_a_gate_cannot_be_built_without_its_maintenance_check() -> None:
    with pytest.raises(ValueError, match="maintenance check"):
        OrderEntryGate(None)  # type: ignore[arg-type]  # the runtime guard for an untyped caller


def test_the_maintenance_check_is_a_required_argument() -> None:
    with pytest.raises(TypeError, match="maintenance"):
        OrderEntryGate()  # type: ignore[call-arg]  # mypy rejects the call too, so this is pinned


@pytest.mark.parametrize(
    "bad", [_Check(), SimpleNamespace(scope="account", refusal=lambda account_id: None), object()]
)
def test_only_the_global_maintenance_check_takes_the_maintenance_slot(bad: object) -> None:
    with pytest.raises(TypeError, match="global maintenance check"):
        OrderEntryGate(bad)  # type: ignore[arg-type]  # the runtime guard


def test_the_maintenance_slot_is_validated_like_every_other_check() -> None:
    with pytest.raises(TypeError, match="not an order-entry check"):
        OrderEntryGate(SimpleNamespace(scope="global"))


def test_a_check_whose_refusal_is_not_callable_is_rejected() -> None:
    not_callable = SimpleNamespace(refusal="no")
    with pytest.raises(TypeError, match="not an order-entry check"):
        OrderEntryGate(_maintenance(False), not_callable)


@pytest.mark.parametrize("bad", [{1, 2}, (c for c in [_Check()]), None])
def test_anything_but_a_check_is_rejected_when_the_gate_is_built(bad: object) -> None:
    with pytest.raises(TypeError, match="not an order-entry check"):
        OrderEntryGate(_maintenance(False), bad)  # type: ignore[arg-type]  # the runtime guard


def test_a_gate_built_from_a_generator_never_runs_dry() -> None:
    gate = OrderEntryGate(_maintenance(False), *(c for c in [_Check(_NO_KEY)]))
    assert gate.refusal(_ACCOUNT) == gate.refusal(_ACCOUNT) == _NO_KEY


@pytest.mark.parametrize("reverse", [False, True])
def test_maintenance_comes_first_and_wins_whatever_the_account_check_order(reverse: bool) -> None:
    maintenance, first, second = _maintenance(True), _Check(_NO_KEY), _Check()
    accounts = (second, first) if reverse else (first, second)
    gate = OrderEntryGate(maintenance, *accounts)
    assert gate.checks == (maintenance, *accounts)
    refusal = gate.refusal(_ACCOUNT)
    assert refusal is not None and refusal.reason == "maintenance"
    assert (first.seen, second.seen) == ([], [])


def test_a_middle_check_refuses_when_the_first_lets_the_order_through() -> None:
    passing, refusing, later = _Check(), _Check(_NO_KEY), _Check()
    gate = OrderEntryGate(_maintenance(False), passing, refusing, later)
    assert gate.refusal(_ACCOUNT) == _NO_KEY
    assert (passing.seen, later.seen) == ([_ACCOUNT], [])


def test_every_check_gets_the_account_id_through_both_entry_points() -> None:
    first, second = _Check(), _Check()
    gate = OrderEntryGate(_maintenance(False), first, second)
    assert gate.refusal(_ACCOUNT) is None
    assert order_entry_refusal(gate, _ACCOUNT) is None
    assert first.seen == second.seen == [_ACCOUNT, _ACCOUNT]


@pytest.mark.parametrize("bad", [None, str(_ACCOUNT), _ACCOUNT.int])
def test_the_account_id_is_required(bad: object) -> None:
    with pytest.raises(TypeError, match="target account id"):
        OrderEntryGate(_maintenance(False)).refusal(bad)  # type: ignore[arg-type]  # the guard


def test_a_raising_check_propagates_and_never_admits() -> None:
    gate = OrderEntryGate(_maintenance(False), _Raising())
    with pytest.raises(RuntimeError):
        gate.refusal(_ACCOUNT)
    with pytest.raises(RuntimeError):
        order_entry_refusal(gate, _ACCOUNT)


def test_a_refusal_is_the_problem_with_its_own_reason_and_detail() -> None:
    body = _body(OrderEntryGate(_maintenance(False), _Check(_NO_KEY)))
    assert {k: body[k] for k in ("status", "code", "reason", "detail")} == {
        "status": 403,
        "code": "trading_disabled",
        "reason": "no_active_key",
        "detail": "No active API key for this account.",
    }
    assert body["type"] == "https://candleviewer.local/errors/trading_disabled"


def test_the_problem_title_is_the_registry_title() -> None:
    entry = next(e for e in load_openapi_spec()["x-error-codes"] if e["code"] == "trading_disabled")
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


@pytest.mark.parametrize("engaged", [True, False])
def test_the_maintenance_gate_is_an_order_entry_check(engaged: bool) -> None:
    check: OrderEntryCheck = _maintenance(engaged)
    refusal = check.refusal(_ACCOUNT)
    expected = OrderEntryRefusal("maintenance", "Order entry is paused.") if engaged else None
    assert refusal == expected
