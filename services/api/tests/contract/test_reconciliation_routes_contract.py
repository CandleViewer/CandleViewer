"""Contract (E29-T06 #914 PR 1; 22-api-openapi.yaml, 24 Sec.8.5, Sec.8.10, 23 Sec.15.9): the
reconciliation contract before its code (C-6.1). The two Owner routes, `reconcileAccount` (an
on-demand pass, `SWEEP_DUE` with `trigger: manual`) and `resolveReconciliation` (the operator's
`OPERATOR_RESOLVED`, step-up `accounts`), their RBAC, idempotency, statuses, schemas and examples;
the `account_stale` refusal reason in the contract, the generated model and 24's closed table;
and 23's three `account_notice` rows. Neither route is mounted yet (the RBAC matrix row is
`not_mounted`), so no provider case runs until E29-T06's wiring serves them."""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from candleviewer.api._generated import openapi_models as api
from tests.contract._admin_support import (
    OWNER_ONLY,
    ROOT,
    SPEC,
    example_cases,
    text,
    validate_example,
)

_PASS = ("/admin/reconciliation/{accountId}", "post")
_RESOLVE = ("/admin/reconciliation/{accountId}/resolve", "post")
_STATUSES = {
    _PASS: {"202", "401", "403", "404", "409", "422", "501", "503"},
    _RESOLVE: {"200", "401", "403", "404", "409", "422", "501", "503"},
}
_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_MATRIX = ROOT / "services" / "api" / "tests" / "contract" / "rbac" / "matrix.yaml"


def _op(where: tuple[str, str]) -> dict[str, Any]:
    path, method = where
    operation: dict[str, Any] = SPEC["paths"][path][method]
    return operation


def _param_refs(where: tuple[str, str]) -> set[str]:
    item = SPEC["paths"][where[0]]
    return {p["$ref"].rsplit("/", 1)[1] for p in [*item["parameters"], *_op(where)["parameters"]]}


@pytest.mark.parametrize("where", [_PASS, _RESOLVE], ids=["reconcileAccount", "resolve"])
def test_each_route_is_owner_only_idempotent_and_declares_exactly_its_statuses(
    where: tuple[str, str],
) -> None:
    operation = _op(where)
    assert operation["x-rbac"] == {"permissions": ["admin:write"], "scope": "none"}
    assert operation["x-idempotency"] == "required" and operation["tags"] == ["admin"]
    assert _param_refs(where) == {"AccountId", "IdempotencyKeyRequired", "CsrfToken"}
    assert set(operation["responses"]) == _STATUSES[where]
    matrix = yaml.safe_load(_MATRIX.read_text(encoding="utf-8"))["operations"]
    row = matrix[f"POST {where[0]}"]
    assert (row["permissions"], row["state"], row["outcomes"]) == (
        ["admin:write"], "not_mounted", OWNER_ONLY,
    )  # fmt: skip


def test_the_pass_is_the_manual_sweep_answering_its_pass_and_starting_none_twice() -> None:
    """BQ-7: the manual trigger is `SWEEP_DUE` with `trigger: manual`; a running pass answers its
    own `pass_id` (`joined`); a stale account runs no pass until it is resolved."""
    operation = _op(_PASS)
    words = text(operation["description"])
    assert operation["operationId"] == "reconcileAccount" and "requestBody" not in operation
    for phrase in (
        "`SWEEP_DUE` with `trigger: manual`",
        "answers that pass's `pass_id` with `joined: true` and starts no second one",
        "`409 conflict` with rule `reconciliation_locked`",
        "`oms.reconcile` with `stage: requested` is written before the `202`",
        "answers `501 not_implemented` and starts nothing",
    ):
        assert phrase in words, phrase
    assert "step-up" not in words  # an on-demand pass re-opens nothing


def test_the_resolve_is_the_operators_unlock_under_a_fresh_accounts_code() -> None:
    """BQ-4, BQ-7: `OPERATOR_RESOLVED` is the one way out of `stale_lockout` (INV-B19-b), and it
    re-opens order entry, so it needs step-up class `accounts`, a no-grace class."""
    operation = _op(_RESOLVE)
    words = text(operation["description"])
    assert operation["operationId"] == "resolveReconciliation"
    for phrase in (
        "with step-up class `accounts`, a fresh code each time",
        "is sent `OPERATOR_RESOLVED`, the one event that leaves `stale_lockout` (INV-B19-b)",
        "`409 conflict` with rule `nothing_to_resolve`",
        "`oms.reconcile` with `stage: resolved` is written before the job is told",
    ):
        assert phrase in words, phrase
    body = operation["requestBody"]["content"]["application/json"]["schema"]
    assert body == {"$ref": "#/components/schemas/ReconciliationResolveRequest"}
    request = _SCHEMAS["ReconciliationResolveRequest"]
    assert request["required"] == ["reason"] and request["additionalProperties"] is False
    assert (
        request["properties"]["reason"]["minLength"],
        request["properties"]["reason"]["maxLength"],
    ) == (3, 280)


def test_the_answers_are_closed_and_their_generated_models_match() -> None:
    passed, resolved = _SCHEMAS["ReconciliationPass"], _SCHEMAS["ReconciliationResolved"]
    assert passed["required"] == ["pass_id", "exchange_account_id", "trigger", "joined"]
    assert passed["properties"]["trigger"] == {"const": "manual"}
    assert resolved["properties"]["resolved"]["enum"] == ["stale_lockout", "divergent"]
    for schema in (passed, resolved):
        assert schema["additionalProperties"] is False
    assert set(api.ReconciliationPass.model_fields) == set(passed["properties"])
    assert set(api.ReconciliationResolved.model_fields) == set(resolved["properties"])
    api.ReconciliationResolveRequest.model_validate({"reason": "checked by hand"})


@pytest.mark.parametrize(
    ("case", "pointer", "value"),
    example_cases([_PASS, _RESOLVE]),
    ids=[c[0] for c in example_cases([_PASS, _RESOLVE])],
)
def test_every_example_validates_against_its_schema(case: str, pointer: str, value: Any) -> None:
    validate_example(pointer, value)


def test_account_stale_is_a_closed_reason_in_the_contract_the_model_and_24() -> None:
    """24 Sec.8.10: adding a reason is a change to its table and to `OrderEntryRefusalReason`;
    open-ended for readers (C-6.3)."""
    reasons = _SCHEMAS["OrderEntryRefusalReason"]["enum"]
    assert reasons[-1] == "account_stale" and len(reasons) == 5
    api.TradingDisabledProblem.model_validate(
        {"type": "about:blank", "title": "Order entry refused", "status": 403,
         "code": "trading_disabled", "reason": "account_stale"}
    )  # fmt: skip
    gate = (ROOT / "docs" / "plan" / "24-internal-schemas.md").read_text(encoding="utf-8")
    section = gate.split("### 8.10 Order-entry gate", 1)[1].split("### 8.11", 1)[0]
    words = text(section)
    assert "| `account_stale` | reconciliation (E29-T06, #914) |" in words
    assert "never consult it (C-2.6)" in words


def test_23_lists_the_three_reconciliation_notices_with_their_severities() -> None:
    """BQ-6, BQ-9: desync `warning` (`critical` for a naked position with no record), stale
    `critical`, synced `info`; each with one message that names no account."""
    doc = (ROOT / "docs" / "plan" / "23-ws-protocol.md").read_text(encoding="utf-8")
    notices = doc.split("**Account notices (SR-E29-10", 1)[1]
    table = notices.split("| Reason ", 1)[1].split("\n\n", 1)[0]
    rows = {
        cells[0].strip("` "): (cells[1].strip(), cells[2].strip())
        for line in table.splitlines()[2:]
        if (cells := [c.strip() for c in line.strip("|").split("|")])
    }
    assert set(rows) == {
        "oms.account_resyncing", "oms.account_desync", "oms.account_stale", "oms.account_synced",
    }  # fmt: skip
    assert rows["oms.account_desync"][0].startswith("`warning`; `critical` for a pass that found")
    assert (
        rows["oms.account_stale"][0] == "`critical`" and rows["oms.account_synced"][0] == "`info`"
    )
    for _severity, message in rows.values():
        assert (
            message.startswith('"An account')
            or message.startswith('"Order entry on an')
            or (message.startswith('"Reconciliation found'))
        )
