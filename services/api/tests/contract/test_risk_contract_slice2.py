"""Contract (E39-S01, #954, second contract slice): the risk gate's port text in 24 §8.11, the
`RiskSummary` staleness markers, `EffectiveLimits.risk_caps` realigned to `ProfileRiskCaps` and
the ticket's amended acceptance criteria, read from 22, 24 and the backlog twin, never a copy."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.api._generated.openapi_models import RiskSummary
from tests.contract._admin_support import ROOT, SPEC, text

_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_INTERNAL = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
_RAW_SPEC = (ROOT / "docs/plan/22-api-openapi.yaml").read_text(encoding="utf-8")
_ALLOWLIST = ROOT / "services/api/tests/unit/architecture/composition_allowlist.json"
_BACKLOG = ROOT / "docs/plan/backlog/E39.json"
_PORT_HEADING = (
    "**The gate's port: `check`, `admit`, `release` and `admit_group` (E39-S01, #954).**"
)


def _section_8_11() -> str:
    return _INTERNAL.split("### 8.11 Risk state and the gate's verdict (E39)", 1)[1].split(
        "\n### 8.12 ", 1
    )[0]


def _port_text() -> str:
    return _section_8_11().split(_PORT_HEADING, 1)[1].split("\n\nThe `jsonb` keys", 1)[0]


def _summary_account() -> Any:
    return _SCHEMAS["RiskSummary"]["properties"]["accounts"]["items"]


def test_effective_limits_risk_caps_is_the_profile_caps() -> None:
    risk_caps = _SCHEMAS["EffectiveLimits"]["properties"]["risk_caps"]
    assert risk_caps["$ref"] == "#/components/schemas/ProfileRiskCaps"
    assert '$ref: "#/components/schemas/RiskCaps"' not in _RAW_SPEC


def test_risk_caps_is_kept_deprecated_and_unreferenced() -> None:
    """The orchestrator's ruling (b): `RiskCaps` stays for the E39-D02 records, no operation or
    schema reaches it, and its description says so."""
    assert "RiskCaps" in _SCHEMAS
    assert text(_SCHEMAS["RiskCaps"]["description"]).startswith("Deprecated: no operation")
    assert _RAW_SPEC.count('#/components/schemas/RiskCaps"') == 0


def test_risk_reads_are_served_by_no_route_yet() -> None:
    """BQ-1: the type change is on an operation no route serves (contract-first allow-list)."""
    pending = json.loads(_ALLOWLIST.read_text(encoding="utf-8"))["openapi_pending"]
    wanted = {"GET /me/limits", "GET /risk/summary", "POST /risk/lockouts/{accountId}/override"}
    assert wanted <= set(pending)


@pytest.mark.parametrize("marker", ["stale", "provisional"])
def test_risk_summary_account_marker_is_a_required_boolean(marker: str) -> None:
    account = _summary_account()
    assert account["properties"][marker]["type"] == "boolean"
    assert marker in account["required"]


def test_risk_summary_totals_stale_is_required() -> None:
    totals = _SCHEMAS["RiskSummary"]["properties"]["totals"]
    assert totals["properties"]["stale"]["type"] == "boolean"
    assert totals["required"] == ["stale"]


def test_stale_account_is_never_a_clean_zero_without_native_stop() -> None:
    totals = _SCHEMAS["RiskSummary"]["properties"]["totals"]["properties"]
    description = text(totals["positions_without_native_stop"]["description"])
    assert "reported `stale` and is never counted as a clean 0" in description


def test_staleness_bound_is_the_one_t01_setting() -> None:
    description = text(_summary_account()["properties"]["stale"]["description"])
    assert "`risk_state_max_age_seconds` (the one staleness bound)" in description
    assert "`503 risk_state_unavailable`" in description


def test_generated_risk_summary_refuses_an_account_without_markers() -> None:
    body: dict[str, Any] = {
        "scope": "accounts",
        "accounts": [{"exchange_account_id": "0193f2bb-dde0-7c3e-9a11-2f8e4b1c9e11"}],
    }
    with pytest.raises(ValidationError):
        RiskSummary.model_validate(body)
    body["accounts"][0].update(stale=True, provisional=False)
    assert RiskSummary.model_validate(body).accounts[0].stale is True


def test_my_limits_rows_are_scoped_at_query_construction() -> None:
    description = text(SPEC["paths"]["/me/limits"]["get"]["description"])
    assert "the scope is applied when the query is built" in description
    assert "SR-E39-14" in description


@pytest.mark.parametrize(
    "phrase",
    [
        "`check(order, *, profile) -> RiskDecision` is the pure verdict",
        "a preview never reserves",
        "`admit(order, *, profile, context, ref) -> RiskDecision` evaluates and",
        "the M17 service call `admit` wraps",
        "never awaits (C-2.21)",
        "`release(ref) -> None`",
        "It is idempotent",
        "`finally` releases the reservation only when the pipeline ends without the order accepted",
        "An accepted order (submitted, adopted, held, unknown) keeps its reservation until a fill",
        "an accepted working order still holds its reservation after the request returns",
        "`admit_group(legs) -> list[RiskDecision]` is a plain synchronous function (C-2.20)",
        "each leg judged and reserved against its own account's counters",
    ],
)
def test_section_8_11_states_the_port(phrase: str) -> None:
    assert phrase in _port_text()


def test_port_text_sits_under_the_risk_tables_not_at_the_section_tail() -> None:
    section = _section_8_11()
    assert section.index("**The gate's caller kind, `RiskOrigin`") < section.index(_PORT_HEADING)
    assert section.index(_PORT_HEADING) < section.index("The `jsonb` keys")
    assert _INTERNAL.count(_PORT_HEADING) == 1


def test_change_log_records_the_second_slice() -> None:
    title = (
        r"^### 19\.127 2026-11-04 — §8\.11 and 22: the risk gate's port, the risk "
        r"reads' markers and `EffectiveLimits\.risk_caps` \(E39-S01, #954\)$"
    )
    assert re.search(title, _INTERNAL, re.MULTILINE)


def test_e39_s01_acceptance_criteria_follow_the_ruling() -> None:
    tickets = json.loads(_BACKLOG.read_text(encoding="utf-8"))
    body = next(t["body"] for t in tickets if t["key"] == "E39-S01")
    criteria = body.split("## Acceptance criteria", 1)[1].split("## Technical notes", 1)[0]
    assert "422" not in criteria
    assert "Then the response is 403 with code risk_limit_breached" in criteria
    assert "each server-derived RiskOrigin" in criteria
    assert "never counted as a clean 0 in positions_without_native_stop" in criteria
    assert "`risk_limit_breached` (422)" not in body
