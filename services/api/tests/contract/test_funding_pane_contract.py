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
from pydantic import ValidationError

from candleviewer.api import user_settings_models as settings_models
from candleviewer.api._generated import openapi_models as api
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
    oi_gaps = oi["properties"]["coverage"]["properties"]["gaps"]
    assert coverage["properties"]["gaps"] == {**oi_gaps, "maxItems": 64}  # Low 5: bounded
    assert coverage["required"] == [*liq_coverage["required"], "gaps"]


def test_funding_coverage_tells_not_recorded_from_none_settled() -> None:
    for phrase in (
        'an empty page there means "not recorded"',
        "An empty page with `no_coverage: false` means the window was covered and no funding "
        "settled in it",
        "in which a settlement was due and none is stored, so a missing settlement is reported "
        "and never filled",
        "A gap's `from` is the stored settlement before it, or `covered_from` when none is "
        "stored before it inside the covered part, and its `to` the stored settlement after it, "
        "or `covered_to` when none is; both edges are exclusive",
        "exceeds one `funding_interval_minutes`. At most 64",
        "At most 64 gaps are listed, oldest first; past the cap the oldest are joined into one "
        "span, which never leaves a missing settlement out",
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
    assert all("annualised_pct" in item for item in value["items"])  # the predicted one too


def test_every_funding_item_carries_the_servers_annualised_pct() -> None:
    """#779 ruling 6618709412: a server-computed `Decimal` percentage on every item."""
    item = _funding_body()["properties"]["items"]["items"]
    member = item["properties"]["annualised_pct"]
    assert member["$ref"] == "#/components/schemas/Decimal"
    assert "annualised_pct" not in item.get("required", [])  # optional until served (C-6.1)
    assert "Never computed by a client" in text(member["description"])
    for phrase in (
        "`annualised_pct`** (E24-S04, #779 ruling 6618709412) is on every item, the predicted one "
        "included",
        "the settlements per year from `funding_interval_minutes` (525 600 / "
        "`funding_interval_minutes`)",
        "a client displays it and never computes it",
    ):
        assert phrase in _FUNDING_DOC, phrase
    example = _FUNDING["responses"]["200"]["content"]["application/json"]["examples"]["funding"]
    for row in example["value"]["items"]:  # the example's arithmetic is the formula's
        rate = Decimal(row["funding_rate"])
        assert Decimal(row["annualised_pct"]) == rate * Decimal(525600) / Decimal(480) * 100


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
        "no operation of its own exists, a market-data read never carries it, and the other "
        "`Position` carriers send it absent",
        "money is never annualised on the client",
    ):
        assert phrase in doc, phrase
    amount = text(estimate["properties"]["amount"]["description"])
    assert "never negative" in amount
    assert (
        estimate["properties"]["amount"]["pattern"] == r"^[0-9]+(\.[0-9]+)?$"
    )  # the nit: contract
    assert "Quantised to 8 dp, `ROUND_HALF_UP`, as funding payments are (24 §1.5)" in amount
    assert "| Funding payments        | 8 dp, `ROUND_HALF_UP`  |" in _RAW_24
    member_doc = text(member["description"])
    for phrase in (
        '`null` here is the answer "no charge"',
        "the `setPositionLeverage` `200` and `AccountConsequenceSummary.open_positions`, never "
        "compute it and send it absent",
    ):
        assert phrase in member_doc, phrase


def _position_refs(node: Any) -> int:
    return repr(node).count("'#/components/schemas/Position'")


def test_every_position_carrier_is_named_and_the_others_send_the_estimate_absent() -> None:
    """m3: `Position` rides four answers; only the two position reads serve the estimate."""
    paths = SPEC["paths"]
    carriers = {
        "listPositions": _position_refs(paths["/positions"]["get"]["responses"]["200"]),
        "getPosition": _position_refs(paths["/positions/{positionId}"]["get"]["responses"]),
        "setPositionLeverage": _position_refs(
            paths["/positions/{positionId}/leverage"]["put"]["responses"]["200"]
        ),
        "AccountConsequenceSummary": _position_refs(_SCHEMAS["AccountConsequenceSummary"]),
    }
    assert all(count == 1 for count in carriers.values()), carriers
    total = _position_refs(SPEC["paths"]) + _position_refs(_SCHEMAS)
    assert total == len(carriers)  # no fifth carrier appeared unnamed
    assert "send it absent" in text(
        _SCHEMAS["Position"]["properties"]["funding_estimate"]["description"]
    )


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
    "oi_mode": ["absolute", "delta"],  # the ruling on #777 (6618708569), with the next one
    "oi_quadrant_colouring": None,
    "funding_style": ["line", "bars"],
    "funding_annualised": None,
    "basis_source": ["last", "mark"],  # the ruling on #783 (6612480577)
    "liq_mode": ["bars", "heatmap"],  # 6612964585 Q1, with the next two
    "liq_min_notional_usd": "decimal",
    "zones_enabled": None,
    "liq_by_price": None,  # #782 (24 §19.132); the recorded layer's own leaf
}
_NOTIONAL_PATTERN = r"^((0|[1-9][0-9]{0,8})(\.[0-9]{1,2})?|1000000000(\.0{1,2})?)$"


def test_settings_gain_the_deriv_group() -> None:
    """G1: eight of D02 section 10's nine keys (6618708569, 6612480577, 6612964585 Q1), one level
    deep, closed; `basis_annualised` is the one dropped. #782 adds `liq_by_price` (24 §19.132)."""
    group = _SCHEMAS["Settings"]["properties"]["deriv"]
    assert group["additionalProperties"] is False
    assert (
        "refuses an undeclared key or a value outside a leaf's enum, type or range with "
        "`422 validation_failed`" in text(group["description"])
    )
    assert "a money amount (`FundingEstimate.amount`) is never annualised on the client" in text(
        group["description"]
    )
    leaves = group["properties"]
    assert list(leaves) == list(_DERIV)
    for leaf, enum in _DERIV.items():
        if enum is None:
            assert leaves[leaf]["type"] == "boolean", leaf
        elif enum == "decimal":
            assert leaves[leaf]["$ref"] == "#/components/schemas/Decimal", leaf
            assert leaves[leaf]["pattern"] == _NOTIONAL_PATTERN, leaf
        else:
            assert leaves[leaf] == {**leaves[leaf], "type": "string", "enum": enum}, leaf
        assert "client default" in leaves[leaf]["description"], leaf
    assert "client default `last`" in leaves["basis_source"]["description"]
    assert 'client default `"0"`' in leaves["liq_min_notional_usd"]["description"]
    assert "client default `bars`" in leaves["liq_mode"]["description"]
    assert "client default `false`" in leaves["zones_enabled"]["description"]
    assert "client default `absolute`" in leaves["oi_mode"]["description"]
    assert "client default `true`" in leaves["oi_quadrant_colouring"]["description"]
    assert "basis_annualised" not in leaves


def test_the_settings_leaf_table_takes_the_deriv_leaves() -> None:
    """`/settings` reads its leaves off the regenerated models, so the group is writable."""
    assert {f"deriv.{leaf}" for leaf in _DERIV} <= set(settings_models.LEAVES)
    patch = settings_models.judge_patch(
        b'{"deriv": {"funding_style": "bars", "funding_annualised": true, "basis_source": null,'
        b' "liq_mode": "heatmap", "liq_min_notional_usd": "50000.5", "zones_enabled": true,'
        b' "oi_mode": "delta", "oi_quadrant_colouring": false}}'
    )
    assert patch == {
        "deriv.oi_mode": "delta",
        "deriv.oi_quadrant_colouring": False,
        "deriv.funding_style": "bars",
        "deriv.funding_annualised": True,
        "deriv.basis_source": None,
        "deriv.liq_mode": "heatmap",
        "deriv.liq_min_notional_usd": "50000.5",
        "deriv.zones_enabled": True,
    }
    for edge in ("0", "1000000000", "1000000000.00", "999999999.99"):
        body = b'{"deriv": {"liq_min_notional_usd": "%s"}}' % edge.encode()
        assert settings_models.judge_patch(body) == {"deriv.liq_min_notional_usd": edge}
    for refused in (
        b'{"deriv": {"liq_min_notional_usd": "1000000000.01"}}',  # over the range
        b'{"deriv": {"liq_min_notional_usd": "-1"}}',  # negative
        b'{"deriv": {"liq_min_notional_usd": "1.234"}}',  # three fractional digits
        b'{"deriv": {"liq_min_notional_usd": "007"}}',  # padded
        b'{"deriv": {"liq_min_notional_usd": 50000}}',  # a JSON number, not the Decimal string
        b'{"deriv": {"liq_mode": "dots"}}',
        b'{"deriv": {"liq_zones_enabled": true}}',  # spelled `zones_enabled`, as ruled
        b'{"deriv": {"funding_style": "area"}}',
        b'{"deriv": {"basis_annualised": true}}',
        b'{"deriv": {"oi_mode": "relative"}}',  # outside the enum
        b'{"deriv": {"oi_quadrant_colouring": "on"}}',  # not a boolean
    ):
        with pytest.raises(settings_models.PatchRefused):
            settings_models.judge_patch(refused)


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
        "the basis key follows the ruling on #783 (6612480577), and the liquidation keys",
        "follow the ruling 6612964585 (Q1",
        "`liq_mode` (`bars | heatmap`, client default `bars`)",
        "`zones_enabled` (client default `false`)",
        "`liq_min_notional_usd` meets D02 §10's \"number, USDT\", and supersedes E24-D03's "
        "PROPOSED integer row (D03-G3",
        "gains `minimum: 1`, a response-side narrowing",
        "the OI keys follow the ruling on #777 (6618708569)",
        "items gain `annualised_pct` (the ruling on #779, 6618709412)",
        "a client displays it and never computes it",
        "eight leaves: `oi_mode` (`absolute | delta`, client default `absolute`)",
        "`deriv.basis.annualised` (dropped by 6612480577) is the one key of D02 §10's nine not "
        "in it",
        "§1 `InstrumentInfo`'s `upper_funding_rate` / `lower_funding_rate` become "
        "`Decimal | None` (PROPOSED)",
        "(`exchange/bybit/instruments.py:202-210`) is the serving slice's to change",
        "a Manager reading an unassigned account's position",
        "a caller without `positions:read`",
        "Annualising is a display transform of a rate only; money is never annualised on the "
        "client.",
        "Display preferences have no local-storage fallback, so the contract carries them.",
        "`upper_funding_rate` and `lower_funding_rate`",
        "`FundingPageMeta`",
        "its RBAC is theirs, `positions:read` over the granted accounts (C-12.4)",
        "(`deriv.funding.style` is the leaf `deriv.funding_style`)",
        "No WS frame, table, column, chart or `machine_hash` change, and no migration.",
    ):
        assert phrase in entry, phrase
    block = _RAW_24.split(title, 1)[1].split("\n### ", 1)[0]
    assert "class FundingEstimate(BaseModel):" in block
    for field in (
        "amount: Decimal          # >= 0",
        'direction: Literal["pay", "receive", "none"]',
        "settles_at: TsUs",
        "computed_at: TsUs",
        "Position.funding_estimate: FundingEstimate | None",
    ):
        assert field in block, field
    assert "the three `deriv.liq.*` keys are not in it" not in entry
    numbered = [int(n) for n in re.findall(r"^### 19\.(\d+) ", _RAW_24, re.MULTILINE)]
    assert numbered == sorted(set(numbered))  # unique and increasing, by number
    assert 110 in numbered


@pytest.mark.parametrize(
    ("amount", "valid"),
    [("0", True), ("12.40", True), ("-12.40", False), ("1e3", False), ("+1", False)],
)
def test_the_estimate_amount_is_never_negative_by_contract(amount: str, valid: bool) -> None:
    """The nit: "never negative" is the schema's, not only prose."""
    sample = {
        "amount": amount,
        "direction": "pay",
        "funding_rate": "0.0001",
        "settles_at": "2026-09-14T16:00:00Z",
        "computed_at": "2026-09-14T15:55:48Z",
    }
    # Against the spec itself (`$ref` with a sibling `pattern`, OpenAPI 3.1), not `deref`, which
    # inlines a `$ref` and drops its siblings.
    pointer = "/components/schemas/FundingEstimate"
    if valid:
        validate_example(pointer, sample)
    else:
        with pytest.raises(jsonschema.ValidationError):
            validate_example(pointer, sample)
    model = api.FundingEstimate
    if valid:
        model.model_validate(sample)
    else:
        with pytest.raises(ValidationError):
            model.model_validate(sample)
