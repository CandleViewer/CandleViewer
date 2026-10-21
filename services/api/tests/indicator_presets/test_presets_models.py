"""`api/indicator_presets_models.py` (E13-T03, #427): the closed `IndicatorPresetInput` DTO and
`preset_fields()` (size caps, registry membership, `validate_params`, the style vocabulary).

The rules' details (types, the name, the codes, canonical params, messages, every numeric
parameter of the catalogue, the measures); the refusals through the router, with nothing stored,
and the 413 body cap are `test_presets_validation.py`.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from _presets_env import body
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.api import indicator_style_vocabulary as vocab
from candleviewer.api.indicator_presets_models import (
    PresetInput,
    PresetInvalidError,
    json_depth,
    jsonb_text_bytes,
    preset_fields,
)
from candleviewer.orderflow.indicators import limits
from candleviewer.orderflow.indicators.catalogue import (
    IndicatorDef,
    ParamSpec,
    default_catalogue,
)

CATALOGUE = default_catalogue()


def _parse(data: dict[str, Any]) -> PresetInput:
    return PresetInput.model_validate_json(json.dumps(data))


def _types(data: dict[str, Any]) -> list[tuple[str, str]]:
    """(field, rule) of every DTO error `data` raises."""
    with pytest.raises(ValidationError) as err:
        _parse(data)
    return [(".".join(map(str, e["loc"])), e["type"]) for e in err.value.errors()]


def _refused(data: dict[str, Any]) -> list[dict[str, str]]:
    with pytest.raises(PresetInvalidError) as err:
        preset_fields(_parse(data), CATALOGUE)
    return err.value.errors


# --- the closed DTO (IR-10, AC-04) --------------------------------------------------------------


def test_defaults_fill_the_optional_fields() -> None:
    got = _parse({"name": "x", "indicator_code": "ema", "params": {}})
    assert (got.style, got.pane_target, got.is_favourite) == ({}, "overlay", False)


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ({"style": None}, ("style", "dict_type")),
        ({"pane_target": "main"}, ("pane_target", "literal_error")),
        ({"pane_target": None}, ("pane_target", "literal_error")),
        ({"is_favourite": "true"}, ("is_favourite", "bool_type")),
        ({"is_favourite": 1}, ("is_favourite", "bool_type")),
        ({"params": []}, ("params", "dict_type")),
        ({"name": 5}, ("name", "string_type")),
        ({"indicator_code": 5}, ("indicator_code", "string_type")),
    ],
)
def test_types_are_strict(over: dict[str, Any], expected: tuple[str, str]) -> None:
    assert _types(body(**over)) == [expected]


def test_name_is_80_characters_as_sent_then_sanitised_and_trimmed() -> None:
    assert _parse(body(name="x" * 80)).name == "x" * 80
    assert _types(body(name="x" * 81)) == [("name", "string_too_long")]
    assert _parse(body(name="  Fast\u202e\x07 ")).name == "Fast"  # bidi + control + trim
    assert _types(body(name=" \u200f\t ")) == [("name", "string_too_short")]
    assert _types(body(name="")) == [("name", "string_too_short")]


def test_a_lone_surrogate_name_is_invalid_unicode() -> None:
    with pytest.raises(ValidationError) as err:
        PresetInput.model_validate(body(name="a\ud800"))  # a bundle item decoded by json.loads
    assert err.value.errors()[0]["type"] == "invalid_unicode"


@pytest.mark.parametrize("code", ["a", "x" * 33, "ATR", "../x", "ema;drop", "", "ema "])
def test_ac06_badly_formed_codes_are_invalid_indicator_code_without_echo(code: str) -> None:
    with pytest.raises(ValidationError) as err:
        _parse(body(indicator_code=code))
    (e,) = err.value.errors(include_input=False)
    assert (e["loc"], e["type"]) == (("indicator_code",), "invalid_indicator_code")
    assert e["msg"] == "indicator_code must be 2 to 32 lowercase letters, digits or underscores"


@pytest.mark.parametrize("code", ["nope", "atr_trail", "delta", "volume_profile"])
def test_ac06_well_formed_codes_outside_the_catalogue_are_unknown_indicator(code: str) -> None:
    (error,) = _refused(body(indicator_code=code, params={}))
    assert (error["field"], error["rule"]) == ("indicator_code", "unknown_indicator")
    assert code not in error["message"]


# --- params: validate_params, the first defect, never clamped (A3, AC-05, IR-07) ----------------


def test_ac05_an_extra_key_is_additional_properties_on_params_without_echo() -> None:
    (error,) = _refused(body(params={"n": 14, "x": 1}))
    assert (error["field"], error["rule"]) == ("params", "additionalProperties")
    assert error["message"] == "atr takes only these parameters: n." and "x" not in error["message"]


def test_ac24_stop_parameters_cannot_ride_in_params() -> None:
    (error,) = _refused(body(params={"n": 14, "sl_atr_period": 14, "sl_atr_multiple": 2}))
    assert (error["field"], error["rule"]) == ("params", "additionalProperties")


def test_params_are_stored_complete_and_canonical() -> None:
    """Defaults filled (a later default change never alters a saved preset); a fractional value
    stays the float it was sent as; an integral one becomes an integer."""
    stored = preset_fields(_parse(body(indicator_code="bollinger", params={"mult": 2.5})),
                           CATALOGUE).params  # fmt: skip
    assert stored == {"n": 20, "mult": 2.5}
    psar = preset_fields(_parse(body(indicator_code="psar", params={"step": 0.03})), CATALOGUE)
    assert psar.params == {"step": 0.03, "max_step": 0.2}
    keltner = preset_fields(_parse(body(indicator_code="keltner", params={"mult": 3.0})), CATALOGUE)
    assert keltner.params == {"n": 20, "mult": 3, "atr_n": 10}
    assert type(keltner.params["mult"]) is int
    assert preset_fields(_parse(body(params={"n": 14.0})), CATALOGUE).params == {"n": 14}


def test_enum_and_step_messages_use_the_title_and_the_bound() -> None:
    (enum,) = _refused(body(indicator_code="cvd", params={"anchor": "since_load"}))
    assert enum == {"field": "params.anchor", "rule": "enum",
                    "message": "Reset anchor must be one of: session, utc_day."}  # fmt: skip
    (step,) = _refused(body(indicator_code="bollinger", params={"mult": 2.05}))
    assert step == {"field": "params.mult", "rule": "multipleOf",
                    "message": "Standard deviations must be a multiple of 0.1."}  # fmt: skip
    (fraction,) = _refused(body(indicator_code="bollinger", params={"mult": "2"}))
    assert fraction["message"] == "Standard deviations must be a number."


def _numeric_specs() -> list[tuple[IndicatorDef, ParamSpec]]:
    return [(d, p) for d in CATALOGUE for p in d.params if p.type != "string"]


@pytest.mark.parametrize(
    ("definition", "spec"), _numeric_specs(), ids=lambda x: getattr(x, "id", getattr(x, "name", ""))
)
def test_every_numeric_param_of_all_28_indicators_rejects_min_minus_step_and_max_plus_step(
    definition: IndicatorDef, spec: ParamSpec
) -> None:
    step = spec.multiple_of if spec.multiple_of is not None else Decimal(1)
    assert spec.minimum is not None and spec.maximum is not None
    outside: list[tuple[Decimal | int, str]] = [
        (spec.minimum - step, "minimum"), (spec.maximum + step, "maximum"),
    ]  # fmt: skip
    for value, rule in outside:
        data = body(indicator_code=definition.id, params={spec.name: _number(value)})
        (error,) = _refused(data)
        assert (error["field"], error["rule"]) == (f"params.{spec.name}", rule)
        assert error["message"].startswith(spec.title)
    for bound in (spec.minimum, spec.maximum):
        data = body(indicator_code=definition.id, params={spec.name: _number(bound)})
        assert preset_fields(_parse(data), CATALOGUE).params[spec.name] == _number(bound)


def _number(value: Decimal | int) -> int | float:
    return int(value) if value == int(value) else float(value)


@settings(max_examples=150, deadline=None)
@given(n=st.integers(min_value=-(10**6), max_value=10**6))
def test_property_a_period_is_stored_exactly_when_in_bounds(n: int) -> None:
    data = _parse(body(indicator_code="ema", params={"n": n}))
    if limits.PERIOD_MIN <= n <= limits.PERIOD_MAX:
        assert preset_fields(data, CATALOGUE).params == {"n": n}  # never clamped
    else:
        with pytest.raises(PresetInvalidError):
            preset_fields(data, CATALOGUE)


# --- style (AC-07, SR-E13-08, IR-09, IR-14) ------------------------------------------------


def test_an_empty_style_is_stored_as_is() -> None:
    assert preset_fields(_parse(body(style={})), CATALOGUE).style == {}


def test_a_published_vocabulary_admits_its_keys_and_tokens_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Data-driven: filling `STYLE_VOCABULARY` is all E13-D04 needs to change."""
    monkeypatch.setattr(vocab, "STYLE_VOCABULARY", {"line": frozenset({"color.indicator.1"})})
    ok = preset_fields(_parse(body(style={"line": "color.indicator.1"})), CATALOGUE)
    assert ok.style == {"line": "color.indicator.1"}
    assert vocab.style_defect({"fill": "color.indicator.1"}) == (
        "style has a key outside the indicator style vocabulary."
    )
    assert vocab.style_defect({"line": "#ff0000"}) == "style.line must be one of its design tokens."
    assert vocab.style_defect({"line": 1}) == "style.line must be one of its design tokens."


# --- size caps (SR-E13-06, AC-08) ----------------------------------------------------------


def _sized(total: int) -> dict[str, str]:
    """`{"k": "v..."}` whose jsonb text is exactly `total` bytes (9 around the value)."""
    return {"k": "v" * (total - 9)}


def test_jsonb_text_bytes_measures_what_postgres_prints() -> None:
    assert jsonb_text_bytes({"a": 1, "b": [1, 2]}) == len('{"a": 1, "b": [1, 2]}')
    assert jsonb_text_bytes({"\u00e9": "\u03c3"}) == len('{"\u00e9": "\u03c3"}'.encode())  # UTF-8
    assert jsonb_text_bytes(_sized(4096)) == 4096
    assert jsonb_text_bytes({"n": float("nan")}) == len('{"n": NaN}')  # measured, not refused


def test_json_depth_counts_containers() -> None:
    values: list[object] = [1, {}, {"a": 1}, {"a": [1]}, {"a": {"b": {"c": {}}}}]
    assert [json_depth(v) for v in values] == [0, 1, 1, 2, 4]


@pytest.mark.parametrize(
    ("style", "message"),
    [
        ({f"k{i}": "t" for i in range(65)}, "style must have at most 64 keys."),
        ({"a": {"b": {"c": {"d": {"e": 1}}}}}, "style must nest at most 4 levels deep."),
        (_sized(4097), "style must be at most 4096 bytes."),
    ],
)
def test_style_past_a_bound_is_style_not_allowed_naming_the_bound(
    style: dict[str, Any], message: str
) -> None:
    (error,) = _refused(body(style=style))
    assert error == {"field": "style", "rule": "style_not_allowed", "message": message}


def test_one_error_per_field_reported_together_and_rooted_at_the_prefix() -> None:
    data = _parse(body(indicator_code="nope", style={"x": 1}))
    with pytest.raises(PresetInvalidError) as err:
        preset_fields(data, CATALOGUE, prefix="indicator_presets.3")
    assert [(e["field"], e["rule"]) for e in err.value.errors] == [
        ("indicator_presets.3.indicator_code", "unknown_indicator"),
        ("indicator_presets.3.style", "style_not_allowed"),
    ]


def test_an_oversize_params_is_not_validated_against_the_descriptor() -> None:
    errors = _refused(body(indicator_code="nope", params=_sized(5000)))
    assert [(e["field"], e["rule"]) for e in errors] == [
        ("params", "params_too_large"),
        ("indicator_code", "unknown_indicator"),
    ]
