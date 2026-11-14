"""#782 (E24-S07) slice 0, contract first (C-6.1): the recorded liquidations by price in 22.

The orchestrator's ruling of 06:52Z 2026-11-04 on #782 (BQ list 6624070740): S07 ships K01's
method (b) only, served by a new read, `getLiquidationsByPrice` (BQ 4), over the UTC day clamped to
the store's coverage (BQ 5), with a required `estimated` flag (BQ 7) and its own settings leaf,
`deriv.liq_by_price` (BQ 3). Every statement is read from the spec, never a copy (AGENTS.md
section 6 rule 12). The operation is unserved until #782's backend slice.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError

from candleviewer.api import user_settings_models as settings_models
from candleviewer.api._generated import openapi_models as api
from tests.contract._admin_support import ROOT, SPEC, text, validate_example

_PATH = "/market/liquidations/by-price"
_OP: dict[str, Any] = SPEC["paths"][_PATH]["get"]
_DOC = text(_OP["description"])
_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_ANSWER = _SCHEMAS["LiquidationsByPrice"]
_BUCKET = _SCHEMAS["LiquidationPriceBucket"]
_DECIMAL = "#/components/schemas/Decimal"
_RAW_24 = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
_EXAMPLE: dict[str, Any] = _OP["responses"]["200"]["content"]["application/json"]["examples"][
    "byPrice"
]["value"]


def _params() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for param in _OP["parameters"]:
        if "$ref" in param:
            param = SPEC["components"]["parameters"][param["$ref"].rsplit("/", 1)[1]]
        out[param["name"]] = param
    return out


def _coverage(name: str) -> dict[str, Any]:
    schema = _SCHEMAS[name]
    own = next((p for p in schema.get("allOf", []) if "properties" in p), schema)
    coverage: dict[str, Any] = own["properties"]["coverage"]
    return coverage


def test_by_price_is_a_market_data_read_for_marketdata_read() -> None:
    """BQ 4: one `GET`, the name accepted by the ruling, the market-data RBAC row."""
    assert list(SPEC["paths"][_PATH]) == ["get"]
    assert _OP["operationId"] == "getLiquidationsByPrice"
    assert _OP["tags"] == ["market-data"]
    assert _OP["x-rbac"] == {"permissions": ["marketdata:read"], "scope": "none"}
    liquidations = SPEC["paths"]["/market/liquidations"]["get"]
    assert set(_OP["responses"]) == set(liquidations["responses"])  # the same answers


def test_by_price_takes_the_window_start_the_width_and_the_count() -> None:
    """BQ 4 / BQ 5 / K01 section 1: `symbol`, `from`, `bucket_ticks` 20, `top` 5; not paged."""
    params = _params()
    assert list(params) == ["symbol", "from", "bucket_ticks", "top"]
    assert params["symbol"]["required"] is True
    assert params["from"].get("required", False) is False
    assert params["from"]["schema"] == {"type": "string", "format": "date-time"}
    assert "default 00:00 UTC of the current UTC day" in text(params["from"]["description"])
    assert params["bucket_ticks"]["schema"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 1000,
        "default": 20,
    }
    assert params["top"]["schema"] == {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}
    assert _ANSWER["properties"]["items"]["maxItems"] == params["top"]["schema"]["maximum"]


def test_by_price_states_the_x01_g1_bounds() -> None:
    for phrase in (
        "**Bounds** (E24-X01 G1), checked before the store is read",
        "`from` must be before the server's now and at most 31 days before it (400 "
        "`invalid_time_range`)",
        "`bucket_ticks` is 1\u20131000, default 20, and `top` is 1\u201320, default 5, both 400 "
        "`validation_failed` when outside",
        "a well-formed symbol that is not listed is 422 `validation_failed`",
        "The defaults are K01's (§1 item 3); the two ranges are PROPOSED (24 §19.132), as no "
        "X01 G1 row names them.",
    ):
        assert phrase in _DOC, phrase
    for name in ("bucket_ticks", "top"):  # no ruled row names the ranges (the lens minor)
        assert "PROPOSED (24 §19.132)" in _params()[name]["description"], name
    codes = {entry["code"] for entry in SPEC["x-error-codes"]}
    assert {"invalid_time_range", "validation_failed"} <= codes


def test_the_answer_requires_the_estimated_flag_and_closes_its_members() -> None:
    """BQ 7: a required `estimated`, so a stripped flag is a refused answer, never a default."""
    assert _ANSWER["additionalProperties"] is False
    assert _ANSWER["required"] == [
        "symbol",
        "from",
        "to",
        "bucket_ticks",
        "tick_size",
        "estimated",
        "items",
        "meta",
    ]
    estimated = _ANSWER["properties"]["estimated"]
    assert estimated["type"] == "boolean" and "default" not in estimated
    for phrase in ("`false` on every answer of this read", "from this flag alone, never from a"):
        assert phrase in text(estimated["description"]), phrase
    assert _ANSWER["properties"]["tick_size"]["$ref"] == _DECIMAL
    assert _ANSWER["properties"]["meta"] == {"$ref": "#/components/schemas/LiquidationsByPriceMeta"}


def test_a_bucket_is_decimal_strings_per_liquidated_side() -> None:
    """BQ 4: Decimal strings; the side is the liquidated side (#780 `side.ts`, 24 section 2.5)."""
    assert _BUCKET["additionalProperties"] is False
    assert _BUCKET["required"] == [
        "price_lo",
        "price_hi",
        "long_notional_usd",
        "short_notional_usd",
        "prints",
    ]
    for member in ("price_lo", "price_hi", "long_notional_usd", "short_notional_usd"):
        assert _BUCKET["properties"][member]["$ref"] == _DECIMAL, member
    assert _BUCKET["properties"]["prints"] == {
        **_BUCKET["properties"]["prints"],
        "type": "integer",
        "minimum": 1,
    }
    assert "a `sell` print closed a long, a `buy` print closed a short" in text(
        _BUCKET["description"]
    )
    assert (
        "to `long_notional_usd` when it closed a long (a `sell` print) and to "
        "`short_notional_usd` when it closed a short (a `buy` print)" in _DOC
    )
    assert '`liquidated_side = "long" if side == "sell" else "short"`' in _RAW_24


def test_the_coverage_is_the_liquidation_reads_coverage_without_the_page() -> None:
    """BQ 5: the UTC day clamped to `meta.coverage`, in `LiquidationsPageMeta`'s four members."""
    meta = _SCHEMAS["LiquidationsByPriceMeta"]
    assert meta["required"] == ["coverage"] and meta["additionalProperties"] is False
    assert "allOf" not in meta  # not a page: no `next_cursor`, `has_more` or `count`
    assert _coverage("LiquidationsByPriceMeta") == _coverage("LiquidationsPageMeta")
    for phrase in (
        "one UTC day at most, never more",
        "to the end of the UTC day that contains `from` (the next 00:00 UTC), or to the server's "
        "now when that is earlier, and never spans two UTC days",
        "`from` may name any instant in the 31-day lookback, the same lookback as "
        "`getLiquidations` (E24-X01 G1)",
        'so an empty `items` there means "not recorded", never "no liquidations"',
        "the buckets hold the covered part only, and a client shows the partial-coverage state, "
        "never a full-day claim",
    ):
        assert phrase in _DOC, phrase


def test_the_server_buckets_and_ranks_and_no_rule_reads_it() -> None:
    for phrase in (
        "anchored at price 0",
        "`price_lo` = ⌊`p` / width⌋ \u00d7 width",
        "a tie going to the lower `price_lo`; a bucket with no print is never listed",
        "a client never re-buckets prints (the ruling on #781, 6618707867)",
        "then at most once every 5 s, and only after the liquidation feed has delivered a new "
        "print; never per frame",
        "No rule reads it: it is not in the rule vocabulary.",
        "The server groups the prints in the store query, one aggregate row per bucket, and never "
        "loads the window's prints into memory",
        "a row or time guard",
        "it is not a forecast",
    ):
        assert phrase in _DOC, phrase
    vocabulary = ROOT / "services/api/candleviewer/rules/vocabulary/metric_names.golden.txt"
    names = vocabulary.read_text(encoding="utf-8").split()
    assert names and not [n for n in names if "by_price" in n or "liq_hist" in n]


def test_the_200_example_validates_and_works_the_bucket_arithmetic() -> None:
    validate_example("/components/schemas/LiquidationsByPrice", _EXAMPLE)
    assert _EXAMPLE["estimated"] is False
    width = _EXAMPLE["bucket_ticks"] * Decimal(_EXAMPLE["tick_size"])
    totals = []
    for bucket in _EXAMPLE["items"]:
        lo, hi = Decimal(bucket["price_lo"]), Decimal(bucket["price_hi"])
        assert hi - lo == width and lo % width == 0
        totals.append(Decimal(bucket["long_notional_usd"]) + Decimal(bucket["short_notional_usd"]))
    assert totals == sorted(totals, reverse=True)
    api.LiquidationsByPrice.model_validate(_EXAMPLE)


def test_an_answer_without_the_flag_is_refused_by_schema_and_model() -> None:
    """BQ 7's negative: the stripped flag is refused, never read as `false`."""
    stripped = {k: v for k, v in _EXAMPLE.items() if k != "estimated"}
    with pytest.raises(jsonschema.ValidationError):
        validate_example("/components/schemas/LiquidationsByPrice", stripped)
    with pytest.raises(ValidationError):
        api.LiquidationsByPrice.model_validate(stripped)
    with pytest.raises(ValidationError):  # a string is not the flag
        api.LiquidationsByPrice.model_validate({**_EXAMPLE, "estimated": "false"})


@pytest.mark.parametrize(
    ("member", "value"),
    [("prints", 0), ("price_lo", 62880.0), ("long_notional_usd", "1e3"), ("side", "long")],
)
def test_a_malformed_bucket_is_refused(member: str, value: Any) -> None:
    bucket = {**_EXAMPLE["items"][0], member: value}
    with pytest.raises(jsonschema.ValidationError):
        validate_example("/components/schemas/LiquidationPriceBucket", bucket)


def test_the_recorded_layer_has_its_own_settings_leaf() -> None:
    """BQ 3: `deriv.liq_by_price`, boolean, client default `false`; `zones_enabled` is (a)'s."""
    leaves = _SCHEMAS["Settings"]["properties"]["deriv"]["properties"]
    leaf = leaves["liq_by_price"]
    assert leaf["type"] == "boolean"
    for phrase in (
        "client default `false`",
        "no acknowledgement and no estimated badge",
        "audited as `settings.change` like the other `deriv` keys",
    ):
        assert phrase in text(leaf["description"]), phrase
    zones = text(leaves["zones_enabled"]["description"])
    assert "Reserved for the estimated liquidation zones, K01's method (a)" in zones
    assert "no client reads or writes it" in zones and "client default `false`" in zones
    assert "deriv.liq_by_price" in settings_models.LEAVES
    assert settings_models.judge_patch(b'{"deriv": {"liq_by_price": true}}') == {
        "deriv.liq_by_price": True
    }
    for refused in (b'{"deriv": {"liq_by_price": "on"}}', b'{"deriv": {"liq_by_price": 1}}'):
        with pytest.raises(settings_models.PatchRefused):
            settings_models.judge_patch(refused)


def test_the_operation_is_pending_under_782_until_its_backend_slice() -> None:
    allowlist = ROOT / "services/api/tests/unit/architecture/composition_allowlist.json"
    pending = json.loads(allowlist.read_text(encoding="utf-8"))["openapi_pending"]
    assert pending[f"GET {_PATH}"]["ticket"] == "#782"


def test_24_carries_the_section_6_4_addendum_and_the_change_log_entry() -> None:
    section = _RAW_24.split("### 6.4 Liquidation heatmap (realized)", 1)[1].split("\n### ", 1)[0]
    for phrase in (
        "**Recorded liquidations by price (E24-S07, #782; §19.132).**",
        "`w = bucket_ticks \u00d7 tick_size`",
        "`[⌊p / w⌋ \u00d7 w, ⌊p / w⌋ \u00d7 w + w)`",
        "`deriv.zones_enabled` stays reserved for (a)",
        "`orderflow_liq_hist_recompute_seconds`, `orderflow_liq_hist_buckets`",
        "class LiquidationPriceBucket(BaseModel):",
    ):
        assert phrase in section, phrase
    title = (
        "### 19.132 2026-11-04 — §6.4, 22 `getLiquidationsByPrice` / `LiquidationsByPrice` / "
        "`LiquidationPriceBucket` / `LiquidationsByPriceMeta`, `Settings.deriv.liq_by_price`: "
        "the recorded liquidations by price, contract first (E24-S07, #782)"
    )
    assert _RAW_24.count(title) == 1
    entry = text(_RAW_24.split(title, 1)[1].split("\n### ", 1)[0])
    for phrase in (
        "This is the number the orchestrator assigned on #5812 (6640566578",
        "The orchestrator's ruling of 06:52Z 2026-11-04 on #782, on its BQ list (6624070740)",
        "none of method (a) is built",
        "`x-rbac` `marketdata:read`",
        "a required `estimated`",
        "The window is the UTC day clamped to `meta.coverage` (BQ 5)",
        "`deriv.zones_enabled` (§19.110) is not removed",
        "the ranges **PROPOSED**, `bucket_ticks` 1\u20131000 and `top` 1\u201320",
        "it is one UTC day at most and never spans two",
        "never loads them into memory, and the serving slice adds a row or time guard",
        "audited as `settings.change` like the other `deriv` keys",
        "No WS frame, table, column, chart or `machine_hash` change, and no migration.",
    ):
        assert phrase in entry, phrase
    numbered = [int(n) for n in re.findall(r"^### 19\.(\d+) ", _RAW_24, re.MULTILINE)]
    # Unique, increasing, and this entry present: survives later entries and a renumbering's
    # placement (the number is assigned, 6640566578; the title pin above carries it).
    assert numbered == sorted(set(numbered)) and numbered.count(132) == 1
