"""The scanner's criteria catalogue and the filter rules (E08-T09, #4708): pure, shared by the
presets (PR 2a) and the scan (PR 2b). Pinned against 22 (`ScannerFilter`, `ScannerCriterion`,
`ScannerSortKey`), E08-D08 section 3.1 (the eight, their order, labels and coverage) and 21
section 4.11 (`orderflow_metrics.regime`, the classes the scan reads)."""

from __future__ import annotations

from typing import Any, get_args

import pytest

from candleviewer.api import scanner_criteria as sc
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.scanner_presets_models import SCANNER_PRESET_BODY_MAX_BYTES, ScannerSortKey
from candleviewer.storage.repositories import scanner_presets as store

SPEC: dict[str, Any] = load_openapi_spec()
SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]


def test_the_criteria_are_22s_filter_properties_in_order() -> None:
    assert [c.id for c in sc.CRITERIA] == list(SCHEMAS["ScannerFilter"]["properties"])


def test_each_descriptor_carries_22s_required_fields_with_listed_values() -> None:
    schema = SCHEMAS["ScannerCriterion"]
    for c in sc.CRITERIA:
        item = sc.describe(c)
        assert set(schema["required"]) <= set(item), c.id
        assert item["kind"] in schema["properties"]["kind"]["enum"]
        assert item["unit"] in schema["properties"]["unit"]["enum"]
        assert ("classes" in item) == (c.kind == "class_set")


def test_estimated_and_needs_recording_follow_e08_d08() -> None:
    assert {c.id for c in sc.CRITERIA if c.estimated} == {"tape_speed_zscore", "regime"}
    recorded = {c.id for c in sc.CRITERIA if c.needs_recording}
    assert recorded == {"oi_change_pct_24h", "tape_speed_zscore", "regime"}


def test_sortable_is_membership_of_the_sort_key_enum() -> None:
    keys = SCHEMAS["ScannerSortKey"]["enum"]
    assert list(sc.SORT_KEYS) == keys == list(get_args(ScannerSortKey))
    for c in sc.CRITERIA:
        assert c.sortable == (c.id in keys), c.id


def test_regime_classes_are_the_stored_vocabulary_and_fit_the_schema_pattern() -> None:
    assert sc.REGIME_CLASSES == ("trend_up", "trend_down", "range", "volatile", "calm")
    assert sc.CRITERIA_BY_ID["regime"].classes == sc.REGIME_CLASSES


def test_the_limits_are_the_contracts() -> None:
    assert SCANNER_PRESET_BODY_MAX_BYTES == 8192
    assert store.FILTER_MAX_BYTES == 4096 and store.MAX_PRESETS == 100 and store.NAME_MAX == 80
    assert SCHEMAS["ScannerClassSet"]["properties"]["classes"]["maxItems"] == sc.MAX_CLASSES


def test_check_filter_returns_the_filter_as_written() -> None:
    raw = {"spread_bps": {"max": "4"}, "funding_rate": {"max": "-0.0001"}}
    assert sc.check_filter(raw, root="filters") == raw


def test_check_filter_roots_each_field_at_the_given_name() -> None:
    with pytest.raises(sc.FilterInvalidError) as err:
        sc.check_filter({"spread_bps": {"min": "2", "max": "1"}, "x": 1}, root="filters")
    assert [(e["field"], e["rule"]) for e in err.value.errors] == [
        ("filters.spread_bps", "range_inverted"), ("filters", "unknown_criterion"),
    ]  # fmt: skip


@pytest.mark.parametrize("value", ["0", "-0.5", "12.000", "123456789012345678901234567890"])
def test_a_bound_is_any_decimal_string_of_22s_pattern(value: str) -> None:
    sc.check_filter({"turnover_24h": {"min": value}}, root="filter")


@pytest.mark.parametrize("value", ["", "1.", ".5", "+1", "1e3", "NaN", " 1", "0x1"])
def test_anything_else_is_invalid_decimal(value: str) -> None:
    with pytest.raises(sc.FilterInvalidError) as err:
        sc.check_filter({"turnover_24h": {"max": value}}, root="filter")
    assert err.value.errors[0]["rule"] == "invalid_decimal"


def test_too_many_classes_is_too_long() -> None:
    with pytest.raises(sc.FilterInvalidError) as err:
        sc.check_filter({"regime": {"classes": ["calm"] * 17}}, root="filter")
    assert err.value.errors[0]["rule"] == "too_long"


def test_split_stored_keeps_known_criteria_and_lists_the_rest_sorted() -> None:
    known, unknown = sc.split_stored({"zeta": {}, "spread_bps": {"max": "1"}, "alpha": {}},
                                     sort="turnover_24h")  # fmt: skip
    assert (known, unknown) == ({"spread_bps": {"max": "1"}}, ["alpha", "zeta"])


#: 22 `ScannerCriterion.available`: no source feeds these yet (E10, the recorded OI baseline).
_UNAVAILABLE_CRITERIA = {"tape_speed_zscore", "regime", "oi_change_pct_24h"}
#: 22 `runScanner` `sort`: the keys read from `orderflow_metrics`, plus the unavailable criteria.
_UNAVAILABLE_SORT_KEYS = {"cvd", "tape_speed", "liquidation_intensity"} | (
    _UNAVAILABLE_CRITERIA & set(sc.SORT_KEYS)
)


def test_available_is_false_exactly_for_the_criteria_no_source_feeds_yet() -> None:
    assert {c.id for c in sc.CRITERIA if not c.available} == _UNAVAILABLE_CRITERIA
    for c in sc.CRITERIA:
        assert sc.describe(c)["available"] is c.available, c.id


def test_sort_keys_list_every_key_in_order_with_its_availability() -> None:
    listed = sc.sort_keys()
    assert [k["id"] for k in listed] == list(sc.SORT_KEYS)
    assert all(set(k) == {"id", "available"} for k in listed)
    assert {k["id"] for k in listed if not k["available"]} == _UNAVAILABLE_SORT_KEYS
    for c in sc.CRITERIA:  # a criterion's key carries that criterion's `available`
        if c.sortable:
            assert sc.SORT_KEY_AVAILABLE[c.id] is c.available, c.id


@pytest.mark.parametrize(
    ("cid", "value"),
    [("tape_speed_zscore", {"min": "2"}), ("oi_change_pct_24h", {"max": "0.1"}),
     ("regime", {"classes": ["calm"]})],
)  # fmt: skip
def test_a_well_formed_unavailable_criterion_is_criterion_unavailable(
    cid: str, value: dict[str, Any]
) -> None:
    with pytest.raises(sc.FilterInvalidError) as err:
        sc.check_filter({cid: value, "spread_bps": {"max": "1"}}, root="filters")
    assert [(e["field"], e["rule"]) for e in err.value.errors] == [
        (f"filters.{cid}", "criterion_unavailable")
    ]


def test_a_malformed_unavailable_criterion_reports_its_shape_defect_first() -> None:
    with pytest.raises(sc.FilterInvalidError) as err:
        sc.check_filter({"regime": {"classes": []}}, root="filter")
    assert [(e["field"], e["rule"]) for e in err.value.errors] == [
        ("filter.regime", "classes_empty")
    ]


@pytest.mark.parametrize("key", sorted(_UNAVAILABLE_SORT_KEYS))
def test_an_unavailable_sort_key_is_criterion_unavailable_on_sort(key: str) -> None:
    assert sc.sort_defect(key) == {
        "field": "sort", "rule": "criterion_unavailable",
        "message": "That ranking is not available yet.",
    }  # fmt: skip


@pytest.mark.parametrize("key", sorted(set(sc.SORT_KEYS) - _UNAVAILABLE_SORT_KEYS))
def test_an_available_sort_key_has_no_defect(key: str) -> None:
    assert sc.sort_defect(key) is None


def test_split_stored_flags_unavailable_criteria_and_an_unavailable_stored_sort() -> None:
    stored = {"regime": {"classes": ["calm"]}, "funding_rate": {"min": "0"},
              "tape_speed_zscore": {"min": "1"}}  # fmt: skip
    known, flagged = sc.split_stored(stored, sort="cvd")
    assert known == {"funding_rate": {"min": "0"}}
    assert flagged == ["cvd", "regime", "tape_speed_zscore"]


def test_split_stored_lists_a_sort_that_is_also_a_flagged_criterion_once() -> None:
    _, flagged = sc.split_stored({"oi_change_pct_24h": {"min": "0"}}, sort="oi_change_pct_24h")
    assert flagged == ["oi_change_pct_24h"]


def test_messages_never_echo_a_value_or_an_unknown_key() -> None:
    with pytest.raises(sc.FilterInvalidError) as err:
        sc.check_filter({"leaky_key": {}, "funding_rate": {"min": "9", "max": "1"},
                         "regime": {"classes": ["secretclass"]}}, root="filter")  # fmt: skip
    text = repr(err.value.errors)
    assert "leaky_key" not in text and "secretclass" not in text and "'9'" not in text
