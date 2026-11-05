"""Contract (E39-S01, #954, BQ-1 (a)): the order path's risk refusal codes, read from 22, 24 §8.4
and §8.11 and the regenerated registries, never from a copy. `account_locked` (403) and
`risk_state_unavailable` (503, with `Retry-After`) join the `x-error-codes` catalogue beside
`risk_limit_breached`, which stays 403 (#908 BQ-3 (a)); each internal `RiskRefusal` maps to exactly
one registered problem."""

from __future__ import annotations

import re
from typing import Any, get_args

import pytest

from candleviewer.risk.models import RiskRefusal
from candleviewer.storage.repositories.orders import OrderOrigin
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.contract._admin_support import ROOT, SPEC, text, validate_example

_CODES: dict[str, Any] = {entry["code"]: entry for entry in SPEC["x-error-codes"]}
_RESPONSES: dict[str, Any] = SPEC["components"]["responses"]
_PLACE: Any = SPEC["paths"]["/orders"]["post"]
_AMEND: Any = SPEC["paths"]["/orders/{orderId}"]["patch"]
_INTERNAL = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")

# The problem 24 §8.11 maps each refusal to, as (code, status).
_EXPECTED = {
    "risk_limit_breached": ("risk_limit_breached", 403),
    "symbol_not_allowed": ("risk_limit_breached", 403),
    "account_locked": ("account_locked", 403),
    "trading_disabled": ("trading_disabled", 403),
    "risk_state_unavailable": ("risk_state_unavailable", 503),
}


def _section_8_11() -> str:
    return _INTERNAL.split("### 8.11 Risk state and the gate's verdict (E39)", 1)[1].split(
        "\n### 8.12 ", 1
    )[0]


def _refusal_table() -> dict[str, tuple[str, int]]:
    """24 §8.11's `RiskRefusal` -> problem table, as {refusal: (code, status)}."""
    rows: dict[str, tuple[str, int]] = {}
    for line in _section_8_11().splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 3:
            continue
        refusal = re.fullmatch(r"`([a-z_]+)`", cells[0])
        problem = re.match(r"`(\d{3}) ([a-z_]+)`", cells[1])
        if refusal and problem:
            rows[refusal.group(1)] = (problem.group(2), int(problem.group(1)))
    return rows


@pytest.mark.parametrize(
    ("code", "status", "retryable"),
    [
        ("risk_limit_breached", 403, False),
        ("account_locked", 403, False),
        ("risk_state_unavailable", 503, True),
    ],
)
def test_x_error_codes_risk_refusal_registered_with_its_status(
    code: str, status: int, retryable: bool
) -> None:
    entry = _CODES[code]
    assert (entry["status"], entry["retryable"]) == (status, retryable)
    meta = ERROR_META[ErrorCode(code)]
    assert (meta.surfaces, meta.retryable, meta.title) == (("rest",), retryable, entry["title"])


def test_risk_refusal_table_maps_every_member_to_a_registered_problem() -> None:
    table = _refusal_table()
    assert set(table) == {member.value for member in RiskRefusal}
    assert table == _EXPECTED
    for code, status in table.values():
        assert _CODES[code]["status"] == status, code


def test_risk_refusal_row_points_at_the_table() -> None:
    row = next(line for line in _section_8_11().splitlines() if line.startswith("| `RiskRefusal`"))
    assert "as the table below maps it" in row
    assert "registered in `22-api-openapi.yaml` (E39-S01)" in row


def test_submission_pipeline_step_3_names_every_risk_answer() -> None:
    step = next(
        line for line in _INTERNAL.splitlines() if line.startswith("3. Risk checks the sized")
    )
    for answer in (
        "`403 risk_limit_breached`",
        "`403 account_locked`",
        "`403 trading_disabled` with no `reason`",
        "`503 risk_state_unavailable` with `Retry-After`",
    ):
        assert answer in step, answer
    assert "§8.11's table" in step


def test_place_order_states_the_risk_gate_answers() -> None:
    description = text(_PLACE["description"])
    bullet = description.split("The risk gate (24-internal-schemas.md sections 8.4 step 3", 1)[1]
    bullet = bullet.split(" * ", 1)[0]
    for answer in (
        "`403 risk_limit_breached`",
        "`403 account_locked`",
        "`403 trading_disabled` with no `reason`",
        "`503 risk_state_unavailable` with `Retry-After`",
        "never clamped",
        "fail closed",
    ):
        assert answer in bullet, answer


def test_amend_order_risk_increasing_names_the_new_codes() -> None:
    description = text(_AMEND["description"])
    assert (
        "(`403 risk_limit_breached`, SR-E29-04), which may also refuse it with "
        "`403 account_locked` or `503 risk_state_unavailable` with `Retry-After`, as on "
        "`placeOrder` (E39-S01)"
    ) in description


@pytest.mark.parametrize("operation", [_PLACE, _AMEND], ids=["placeOrder", "amendOrder"])
def test_order_operations_declare_the_refusal_responses(operation: Any) -> None:
    responses = operation["responses"]
    assert responses["403"] == {"$ref": "#/components/responses/Forbidden"}
    assert responses["503"] == {"$ref": "#/components/responses/ServiceUnavailable"}
    assert "Retry-After" in _RESPONSES["ServiceUnavailable"]["headers"]


def test_forbidden_names_account_locked_on_the_order_path() -> None:
    description = text(_RESPONSES["Forbidden"]["description"])
    assert (
        "On `placeOrder` and on an `amendOrder` that increases exposure it may also be the risk "
        "gate's refusal of the sized order"
    ) in description
    assert "`code: account_locked`" in description


@pytest.mark.parametrize(
    ("response", "example", "code", "status"),
    [
        ("Forbidden", "accountLocked", "account_locked", 403),
        ("ServiceUnavailable", "riskStateUnavailable", "risk_state_unavailable", 503),
    ],
)
def test_risk_refusal_example_meets_problem_and_registry(
    response: str, example: str, code: str, status: int
) -> None:
    value = _RESPONSES[response]["content"]["application/problem+json"]["examples"][example][
        "value"
    ]
    validate_example("/components/schemas/Problem", value)
    assert (value["code"], value["status"], value["title"]) == (
        code,
        status,
        _CODES[code]["title"],
    )
    assert value["type"] == f"https://candleviewer.local/errors/{code}"


def test_account_locked_example_names_a_lockout_reason() -> None:
    examples = _RESPONSES["Forbidden"]["content"]["application/problem+json"]["examples"]
    reasons = re.search(r"\| `LockoutReason`\s+\| ([^|]+)\|", _section_8_11())
    assert reasons is not None
    allowed = set(re.findall(r"`([a-z_]+)`", reasons.group(1)))
    assert {e["rule"] for e in examples["accountLocked"]["value"]["errors"]} <= allowed


def test_account_locked_title_names_the_protective_class() -> None:
    """The lockout refuses every submission; only protective operations pass (BQ-5)."""
    title = _CODES["account_locked"]["title"]
    assert "open or increase exposure" not in title
    assert "every order submission is refused" in title
    assert "cancels, position closes and stop tightening are never refused" in title


def test_preview_leg_codes_keep_both_codes() -> None:
    preview = SPEC["components"]["schemas"]["TradeGroupPreview"]
    leg = preview["properties"]["legs"]["items"]["properties"]
    enum = leg["rejection"]["properties"]["code"]["enum"]
    assert {"account_locked", "risk_state_unavailable"} <= set(enum)


def test_change_log_records_the_risk_refusal_codes() -> None:
    title = (
        r"^### 19\.125 2026-11-04 — §8\.4, §8\.11 and 22: the order path's risk "
        r"refusal codes \(E39-S01, #954\)$"
    )
    assert re.search(title, _INTERNAL, re.MULTILINE)


def test_risk_origin_maps_every_stored_order_origin() -> None:
    """BQ-4 rider: the gate's closed caller kind, mapped from every `OrderOrigin`."""
    section = _section_8_11()
    row = re.search(r"^\| `RiskOrigin`\s*\| ([^|]+)\|", section, re.MULTILINE)
    assert row is not None
    members = set(re.findall(r"`([a-z_]+)`", row.group(1)))
    assert members == {"manual", "rule", "algo_child", "amend", "fanout_leg"}
    mapping = section.split("**The gate's caller kind, `RiskOrigin`", 1)[1].split("\n\n", 1)[0]
    for label in get_args(OrderOrigin):
        assert f"`{label}`" in mapping, label


def test_account_scope_denied_names_the_risk_summary() -> None:
    """BQ-9 rider: a missing and a foreign account read alike on `getRiskSummary` (SR-E39-14)."""
    description = _RESPONSES["AccountScopeDenied"]["description"]
    assert "`getRiskSummary`" in description
    assert "that does not exist the same way" in description
    assert "SR-E39-14" in description
