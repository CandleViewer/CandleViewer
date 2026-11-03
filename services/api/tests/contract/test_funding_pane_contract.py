"""#778 (E24-S03), contract first (C-6.1): the funding pane's contract in 22.

E24-D02 section 16's G5 (the interval and the rate bounds from instrument info), BQ 6 (the
coverage of the settled history), G11 (the per-account funding charge, computed by the server)
and G1's funding, basis and OI rows (the `deriv` settings group). Every statement is read from
the spec, never a copy (AGENTS.md section 6 rule 12). Each change is additive: the shipped
`getFundingHistory` answer still conforms, and no operation is added.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

import jsonschema
import pytest

from candleviewer.api import user_settings_models as settings_models
from candleviewer.api.funding import serialize_series
from candleviewer.domain.funding import PredictedFunding, SettledFunding
from candleviewer.orderflow.funding import FundingSeries
from tests.contract._admin_support import ROOT, SPEC, example_cases, text, validate_example
from tests.openapi_helpers import deref

_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_METHODS = frozenset({"get", "put", "post", "patch", "delete"})
_OPS: dict[str, dict[str, Any]] = {
    op["operationId"]: op
    for item in SPEC["paths"].values()
    for method, op in item.items()
    if method in _METHODS
}
_FUNDING = _OPS["getFundingHistory"]
_FUNDING_DOC = text(_FUNDING["description"])
_RAW_24 = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
_NULLABLE_DECIMAL = [{"$ref": "#/components/schemas/Decimal"}, {"type": "null"}]


def _funding_body() -> dict[str, Any]:
    """The inline object member of `getFundingHistory`'s `200` (`Page` plus its own members)."""
    schema = _FUNDING["responses"]["200"]["content"]["application/json"]["schema"]
    inline: dict[str, Any] = next(part for part in schema["allOf"] if "properties" in part)
    return inline


def _coverage() -> dict[str, Any]:
    own = next(p for p in _SCHEMAS["FundingPageMeta"]["allOf"] if "properties" in p)
    coverage: dict[str, Any] = own["properties"]["coverage"]
    return coverage


def test_funding_states_the_interval_and_the_bounds_from_instrument_info() -> None:
    """G5: the interval and the cap and floor, each nullable bound never served as 0."""
    body = _funding_body()["properties"]
    assert body["funding_interval_minutes"]["type"] == "integer"
    assert body["funding_interval_minutes"]["minimum"] == 1
    assert "(`fundingInterval`)" in text(body["funding_interval_minutes"]["description"])
    for member, venue in (
        ("upper_funding_rate", "upperFundingRate"),
        ("lower_funding_rate", "lowerFundingRate"),
    ):
        assert body[member]["oneOf"] == _NULLABLE_DECIMAL
        assert f"(`{venue}`)" in text(body[member]["description"])
        assert "`null` when it carries none" in text(body[member]["description"])
    for phrase in (
        "the instruments cache's `fundingInterval`, `upperFundingRate` and `lowerFundingRate`",
        "never the ticker and never the spacing of the items",
        "a countdown runs to the ticker's `nextFundingTime`, never to a multiple of the interval",
        "a missing bound is never served as `0`",
    ):
        assert phrase in _FUNDING_DOC, phrase


def test_funding_meta_is_the_coverage_shape_of_the_other_market_reads() -> None:
    """BQ 6: liquidations' four members plus open interest's `gaps[]`, optional for now."""
    meta = _funding_body()["properties"]["meta"]
    assert meta == {"$ref": "#/components/schemas/FundingPageMeta"}
    allof = _SCHEMAS["FundingPageMeta"]["allOf"]
    assert {"$ref": "#/components/schemas/PageMeta"} in allof
    own = next(p for p in allof if "properties" in p)
    assert "required" not in own  # optional until the handler serves it (C-6.1)
    coverage = _coverage()
    liq = next(p for p in _SCHEMAS["LiquidationsPageMeta"]["allOf"] if "properties" in p)
    liq_coverage = liq["properties"]["coverage"]
    for member in liq_coverage["required"]:
        assert coverage["properties"][member] == liq_coverage["properties"][member], member
    oi = next(p for p in _SCHEMAS["OpenInterestPageMeta"]["allOf"] if "properties" in p)
    assert coverage["properties"]["gaps"] == oi["properties"]["coverage"]["properties"]["gaps"]
    assert coverage["required"] == [*liq_coverage["required"], "gaps"]


def test_funding_coverage_tells_not_recorded_from_none_settled() -> None:
    for phrase in (
        'an empty page there means "not recorded"',
        "An empty page with `no_coverage: false` means the window was covered and no funding "
        "settled in it",
        "longer than one `funding_interval_minutes` between consecutive settlements, so a "
        "missing settlement is reported and never filled",
        'a client reads an absent member as unknown, never as `0` or as "covered"',
    ):
        assert phrase in _FUNDING_DOC, phrase


@pytest.mark.parametrize(
    ("case", "pointer", "value"),
    [c for c in example_cases([("/market/funding", "get")]) if " 200 " in c[0]],
    ids=lambda v: v if isinstance(v, str) and " " in v else "",
)
def test_funding_200_examples_validate_and_show_the_new_members(
    case: str, pointer: str, value: Any
) -> None:
    assert case
    validate_example(pointer, value)
    assert "coverage" in value["meta"] and "upper_funding_rate" in value


def test_the_shipped_funding_answer_still_conforms() -> None:
    """Additive (C-6.3): the handler's answer today, with no bound and no coverage, still holds."""
    series = FundingSeries(
        symbol="BTCUSDT",
        funding_interval_minutes=240,
        settled=(
            SettledFunding(
                ts_us=1_789_372_800_000_000,
                symbol="BTCUSDT",
                funding_rate=Decimal("0.0001"),
                interval_min=240,
                annualised_pct=Decimal("21.9"),
            ),
        ),
        predicted=PredictedFunding(
            ts_us=1_789_387_200_000_000, symbol="BTCUSDT", funding_rate=Decimal("0.00012")
        ),
        next_funding_time_us=1_789_387_200_000_000,
        next_cursor=None,
        has_more=False,
    )
    schema = deref(SPEC, _FUNDING["responses"]["200"]["content"]["application/json"]["schema"])
    jsonschema.validate(serialize_series(series), schema)


def test_position_carries_a_server_computed_funding_estimate() -> None:
    """G11: one optional member on `Position`, the `FundingEstimate` carrier, never a sum."""
    member = _SCHEMAS["Position"]["properties"]["funding_estimate"]
    assert member["oneOf"] == [{"$ref": "#/components/schemas/FundingEstimate"}, {"type": "null"}]
    assert "funding_estimate" not in _SCHEMAS["Position"]["required"]
    assert "funding_estimate" not in _SCHEMAS["AggregatePosition"]["properties"]
    assert "never a zero" in text(member["description"])
    estimate = _SCHEMAS["FundingEstimate"]
    assert estimate["required"] == [
        "amount",
        "direction",
        "funding_rate",
        "settles_at",
        "computed_at",
    ]
    assert estimate["properties"]["direction"]["enum"] == ["pay", "receive", "none"]
    doc = text(estimate["description"])
    for phrase in (
        "computed server-side only (C-2.12)",
        "the position's value at mark times the symbol's accruing rate",
        "a client formats it and never multiplies",
        "every account for the Owner and the assigned ones for a Manager (C-12.4)",
        "no operation of its own exists and a market-data read never carries it",
    ):
        assert phrase in doc, phrase


@pytest.mark.parametrize("operation", ["listPositions", "getPosition"])
def test_the_estimate_rides_the_account_scoped_position_reads(operation: str) -> None:
    assert _OPS[operation]["x-rbac"] == {
        "permissions": ["positions:read"],
        "scope": "granted_accounts",
    }


def test_only_position_references_the_estimate() -> None:
    """The carrier has one home: no market-data answer or other schema names it."""
    ref = '"#/components/schemas/FundingEstimate"'
    holders = [name for name, schema in _SCHEMAS.items() if ref in repr(schema).replace("'", '"')]
    assert holders == ["Position"]
    for operation_id, op in _OPS.items():
        if "market-data" in op.get("tags", []):
            assert ref not in repr(op).replace("'", '"'), operation_id


_DERIV = {
    "oi_mode": ["absolute", "delta"],
    "oi_quadrant_colouring": None,
    "funding_style": ["line", "bars"],
    "funding_annualised": None,
    "basis_source": ["mark", "last"],
    "basis_annualised": None,
}


def test_settings_gain_the_deriv_group() -> None:
    """G1: E24-D02 section 10's funding, basis and OI keys, one level deep, no liquidation key."""
    leaves = _SCHEMAS["Settings"]["properties"]["deriv"]["properties"]
    assert list(leaves) == list(_DERIV)
    for leaf, enum in _DERIV.items():
        if enum is None:
            assert leaves[leaf]["type"] == "boolean", leaf
        else:
            assert leaves[leaf] == {**leaves[leaf], "type": "string", "enum": enum}, leaf
        assert "client default" in leaves[leaf]["description"], leaf
    assert not any(leaf.startswith("liq") for leaf in leaves)


def test_the_settings_leaf_table_takes_the_deriv_leaves() -> None:
    """`/settings` reads its leaves off the regenerated models, so the group is writable."""
    assert {f"deriv.{leaf}" for leaf in _DERIV} <= set(settings_models.LEAVES)
    patch = settings_models.judge_patch(
        b'{"deriv": {"funding_style": "bars", "basis_annualised": true, "oi_mode": null}}'
    )
    assert patch == {
        "deriv.funding_style": "bars",
        "deriv.basis_annualised": True,
        "deriv.oi_mode": None,
    }
    with pytest.raises(settings_models.PatchRefused):
        settings_models.judge_patch(b'{"deriv": {"funding_style": "area"}}')


def test_the_change_log_names_the_change() -> None:
    title = (
        "### 19.110 2026-11-03 — 22 `getFundingHistory` / `FundingPageMeta`, "
        "`Position.funding_estimate` / `FundingEstimate`, `Settings.deriv`: the funding pane's "
        "contract, contract first (E24-S03, #778)"
    )
    assert _RAW_24.count(title) == 1
    entry = text(_RAW_24.split(title, 1)[1].split("\n### ", 1)[0])
    for phrase in (
        "Assigned by the orchestrator on #778 (6610230823)",
        "BQ items 3, 6, 7 and 8 as recommended, scope D02 §16 rec. 9",
        "Display preferences have no local-storage fallback, so the contract carries them.",
        "`upper_funding_rate` and `lower_funding_rate`",
        "`FundingPageMeta`",
        "its RBAC is theirs, `positions:read` over the granted accounts (C-12.4)",
        "(`deriv.funding.style` is the leaf `deriv.funding_style`)",
        "No WS frame, table, column, chart or `machine_hash` change, and no migration.",
    ):
        assert phrase in entry, phrase
    numbered = [int(n) for n in re.findall(r"^### 19\.(\d+) ", _RAW_24, re.MULTILINE)]
    assert numbered == sorted(set(numbered))  # unique and increasing, by number
    assert 110 in numbered
