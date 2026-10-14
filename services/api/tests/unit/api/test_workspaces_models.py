"""Unit + property tests for the workspace and pane request models (E15-T01 S2b-i)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.api import workspaces_models as wm
from candleviewer.api.drawings_models import format_errors
from candleviewer.api.workspaces_models import (
    LayoutPaneIn,
    PaneConfigIn,
    WorkspaceIn,
    canonical_json,
)

_MIGRATION = (
    Path(__file__).resolve().parents[3] / "candleviewer/migrations/versions/0022_workspaces.py"
)


def pane(slot: int = 0, **kw: Any) -> dict[str, Any]:
    return {"slot_index": slot, "pane_kind": "chart", **kw}


def errs(model: Any, body: dict[str, Any]) -> list[dict[str, str]]:
    with pytest.raises(ValidationError) as ei:
        model.model_validate(body)
    return format_errors(ei.value)


def rules(model: Any, body: dict[str, Any]) -> set[tuple[str, str]]:
    return {(e["field"], e["rule"]) for e in errs(model, body)}


# --- enums == DDL CHECK lists ---------------------------------------------------------------
def _ddl() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def _check_list(ddl: str, name: str) -> tuple[str, ...]:
    m = re.search(rf"CONSTRAINT {name}\s+CHECK \(\w+ IN \(([^)]*)\)", ddl)
    assert m, name
    return tuple(re.findall(r"'([^']+)'", m.group(1)))


@pytest.mark.parametrize(
    ("check", "values"),
    [("lp_kind", wm.PANE_KINDS), ("lp_scale", wm.SCALE_MODES), ("lay_preset", wm.GRID_PRESETS)],
)
def test_enum_equals_db_check_list(check: str, values: tuple[str, ...]) -> None:
    assert _check_list(_ddl(), check) == values


def test_slot_and_hotkey_bounds_equal_db_checks() -> None:
    ddl = _ddl()
    assert "slot_index BETWEEN 0 AND 15" in ddl
    assert "hotkey_slot BETWEEN 1 AND 9" in ddl


# --- names ----------------------------------------------------------------------------------
def test_name_is_sanitised_then_trimmed() -> None:
    assert WorkspaceIn.model_validate({"name": " ‮Sca\x00lp "}).name == "Scalp"


def test_name_empty_after_sanitise_is_string_too_short() -> None:
    got = errs(WorkspaceIn, {"name": " \x00 "})
    assert got[0]["rule"] == "string_too_short"


def test_name_raw_length_over_40_with_control_char_is_string_too_long() -> None:
    assert ("name", "string_too_long") in rules(WorkspaceIn, {"name": "a" * 40 + "\x00"})


def test_name_exactly_40_is_accepted() -> None:
    assert len(WorkspaceIn.model_validate({"name": "a" * 40}).name) == 40


def test_name_lone_surrogate_is_invalid_unicode() -> None:
    assert ("name", "invalid_unicode") in rules(WorkspaceIn, {"name": "\ud800"})


def test_workspace_defaults_and_db_values_keys() -> None:
    v = WorkspaceIn.model_validate({"name": "A"}).db_values()
    assert v == {
        "name": "A", "is_default": False, "icon_token": "workspace.default", "sort_order": 0,
    }  # fmt: skip


@pytest.mark.parametrize("key", ["is_default", "icon_token", "sort_order"])
def test_workspace_explicit_null_is_rejected(key: str) -> None:
    assert (key, "null_not_allowed") in rules(WorkspaceIn, {"name": "A", key: None})


@pytest.mark.parametrize(
    "extra", [{"icon_token": "https://x"}, {"sort_order": 32768}, {"sort_order": -1}, {"x": 1}]
)
def test_workspace_bad_fields_rejected(extra: dict[str, Any]) -> None:
    errs(WorkspaceIn, {"name": "A", **extra})


# --- panes ----------------------------------------------------------------------------------
def test_slot_index_bounds() -> None:
    LayoutPaneIn.model_validate(pane(15))
    assert ("slot_index", "less_than_equal") in rules(LayoutPaneIn, pane(16))
    assert ("slot_index", "greater_than_equal") in rules(LayoutPaneIn, pane(-1))


def test_pane_kind_outside_enum_rejected() -> None:
    assert errs(LayoutPaneIn, {"slot_index": 0, "pane_kind": "footprint"})


@pytest.mark.parametrize("key", ["pane_config", "scale_mode", "indicator_preset_ids"])
def test_pane_explicit_null_is_rejected(key: str) -> None:
    assert (key, "null_not_allowed") in rules(LayoutPaneIn, pane(**{key: None}))


@pytest.mark.parametrize("sym", ["BTCUSDT", "1000PEPEUSDT", "ABUSDT"])
def test_symbol_pattern_accepts(sym: str) -> None:
    assert LayoutPaneIn.model_validate(pane(symbol=sym)).symbol == sym


@pytest.mark.parametrize("sym", ["btcusdt", "USDT", "BTCUSD", "A" * 17 + "USDT", "BTC-USDT", ""])
def test_symbol_pattern_rejects(sym: str) -> None:
    assert errs(LayoutPaneIn, pane(symbol=sym))


@pytest.mark.parametrize(
    "code",
    ["time:1", "time:D", "heikin_ashi:240", "tick:500", "range:1", "volume:50", "delta:0.5",
     "volume:0.000000000001", "volume:12345678901.123456789012", "renko:10", "renko:atr:14",
     "pnf:10:3"],
)  # fmt: skip
def test_interval_grammar_accepts(code: str) -> None:
    assert LayoutPaneIn.model_validate(pane(interval_code=code)).interval_code == code


def test_volume_zero_matches_the_pattern_but_is_not_positive() -> None:
    assert ("interval_code", "interval_not_positive") in rules(
        LayoutPaneIn, pane(interval_code="volume:0")
    )


@pytest.mark.parametrize(
    "code",
    ["1m", "time:2", "tick:0", "tick:01", "volume:007", "volume:123456789012", "volume:1.",
     "renko:atr:0", "pnf:10", "time:1 ", "x" * 40, "volume:0.0000000000001"],
)  # fmt: skip
def test_interval_grammar_rejects(code: str) -> None:
    assert errs(LayoutPaneIn, pane(interval_code=code))


@pytest.mark.parametrize("code", ["volume:0.50", "volume:1.0", "delta:0.0"])
def test_interval_non_canonical_fraction_is_pattern_mismatch(code: str) -> None:
    got = errs(LayoutPaneIn, pane(interval_code=code))
    assert [(e["field"], e["rule"]) for e in got] == [("interval_code", "string_pattern_mismatch")]


def test_delta_zero_is_not_positive() -> None:
    assert ("interval_code", "interval_not_positive") in rules(
        LayoutPaneIn, pane(interval_code="delta:0")
    )


@pytest.mark.parametrize("kind", ["positions", "journal", "watchlist", "alerts"])
def test_account_pane_with_symbol_or_interval_is_not_allowed(kind: str) -> None:
    got = rules(
        LayoutPaneIn,
        {"slot_index": 0, "pane_kind": kind, "symbol": "BTCUSDT", "interval_code": "time:1"},
    )
    assert {("symbol", "property_not_allowed_for_kind"),
            ("interval_code", "property_not_allowed_for_kind")} <= got  # fmt: skip


def test_market_pane_may_carry_symbol_and_interval() -> None:
    p = LayoutPaneIn.model_validate(pane(symbol="BTCUSDT", interval_code="time:1"))
    assert p.db_values()["symbol"] == "BTCUSDT"


def test_chart_template_and_indicator_presets_are_refused() -> None:
    got = rules(
        LayoutPaneIn,
        pane(
            chart_template_id="15000000-0000-4000-8000-000000000001",
            indicator_preset_ids=["15000000-0000-4000-8000-000000000002"],
        ),
    )
    assert ("chart_template_id", "chart_template_not_found") in got
    assert ("indicator_preset_ids", "indicator_preset_not_found") in got


def test_indicator_preset_ids_over_16_or_duplicate_rejected() -> None:
    u = "15000000-0000-4000-8000-000000000002"
    assert errs(LayoutPaneIn, pane(indicator_preset_ids=[u, u]))
    assert errs(LayoutPaneIn, pane(indicator_preset_ids=[u] * 17))


# --- pane_config ----------------------------------------------------------------------------
def test_settings_preserve_int_and_float_exactly() -> None:
    s = {"a": 50, "b": 50.0, "c": True, "d": None, "e": "x", "f": [1, 2.5, False, "s"]}
    out = LayoutPaneIn.model_validate(pane(pane_config={"settings": s})).db_values()
    got = out["pane_config"]["settings"]
    assert got == s
    assert type(got["a"]) is int and type(got["b"]) is float and type(got["c"]) is bool
    assert [type(x) for x in got["f"]] == [int, float, bool, str]


@given(
    st.dictionaries(
        st.from_regex(r"[a-z][a-z0-9_]{0,31}", fullmatch=True),
        st.one_of(
            st.integers(-(10**15), 10**15),
            st.floats(min_value=-1e15, max_value=1e15, allow_nan=False).filter(lambda x: x != 0),
        ),
        max_size=32,
    )
)
@settings(max_examples=60, deadline=None)
def test_settings_numbers_round_trip_unchanged(s: dict[str, int | float]) -> None:
    out = LayoutPaneIn.model_validate(pane(pane_config={"settings": s})).db_values()
    got = out["pane_config"].get("settings", {})
    assert got == s
    assert all(type(got[k]) is type(v) for k, v in s.items())


def test_canonical_json_keeps_number_spelling() -> None:
    assert canonical_json({"b": 1.0, "a": 1}) == '{"a":1,"b":1.0}'


@pytest.mark.parametrize(
    "settings_",
    [{"a": {"x": 1}}, {"a": [[1]]}, {"a": "x" * 257}, {"a": ["x" * 257]}, {"a": [0] * 33},
     {"a": float("nan")}, {"a": float("inf")}],
)  # fmt: skip
def test_settings_value_shapes_rejected(settings_: dict[str, Any]) -> None:
    assert errs(LayoutPaneIn, pane(pane_config={"settings": settings_}))


def test_settings_over_32_keys_rejected() -> None:
    s = {f"k{i}": 1 for i in range(33)}
    assert errs(LayoutPaneIn, pane(pane_config={"settings": s}))


def test_settings_bad_key_is_invalid_setting_key_without_echo() -> None:
    e = errs(LayoutPaneIn, pane(pane_config={"settings": {"Bad Key": 1}}))
    assert e[0]["rule"] == "invalid_setting_key"
    assert "Bad Key" not in e[0]["message"]


def test_pane_config_over_4096_bytes_is_too_large() -> None:
    s = {f"k{i}": "x" * 200 for i in range(21)}
    assert ("pane_config", "pane_config_too_large") in rules(
        LayoutPaneIn, pane(pane_config={"settings": s})
    )


def test_pane_config_exactly_at_limit_is_accepted_and_one_over_is_not() -> None:
    def cfg(last: int) -> dict[str, Any]:
        s = {f"k{i:02d}": "x" * 256 for i in range(15)}
        s["k99"] = "y" * last
        return {"settings": s}

    base = len(canonical_json(cfg(0)).encode())
    fit = wm.MAX_PANE_CONFIG_BYTES - base
    assert 0 < fit <= 256
    LayoutPaneIn.model_validate(pane(pane_config=cfg(fit)))
    assert ("pane_config", "pane_config_too_large") in rules(
        LayoutPaneIn, pane(pane_config=cfg(fit + 1))
    )


def test_sync_group_values_and_unknown_config_key() -> None:
    assert LayoutPaneIn.model_validate(pane(pane_config={"sync_group": "B"})).db_values()[
        "pane_config"
    ] == {"sync_group": "B"}
    assert errs(LayoutPaneIn, pane(pane_config={"sync_group": "D"}))
    assert errs(LayoutPaneIn, pane(pane_config={"other": 1}))


def test_empty_pane_config_forms_normalise_equal() -> None:
    a = LayoutPaneIn.model_validate(pane()).db_values()["pane_config"]
    b = LayoutPaneIn.model_validate(pane(pane_config={"settings": {}, "sync_group": None}))
    assert a == b.db_values()["pane_config"] == {}


# --- settings hardening (security review) ---------------------------------------------------
def setting_pane(value: Any) -> dict[str, Any]:
    return pane(pane_config={"settings": {"k": value}})


def stored(value: Any) -> Any:
    out = LayoutPaneIn.model_validate(setting_pane(value)).db_values()
    return out["pane_config"]["settings"]["k"]


def test_more_than_32_settings_keys_refused_before_values_are_validated() -> None:
    s = {f"k{i}": [{}] * 32 for i in range(33)}
    with pytest.raises(ValidationError) as ei:
        LayoutPaneIn.model_validate(pane(pane_config={"settings": s}))
    assert ei.value.error_count() == 1
    assert ei.value.errors()[0]["type"] == "too_long"


def test_pane_config_32_keys_of_32_bad_items_yield_exactly_32_errors() -> None:
    """Amplification pin at the layer that owns the fix (C-13.7): each array stops at its first
    bad item, so the worst case is one error per key (before: 32 * 32 * 4 = 4,096)."""
    s = {f"k{i}": [{}] * 32 for i in range(32)}
    with pytest.raises(ValidationError) as ei:
        PaneConfigIn.model_validate({"settings": s})
    assert ei.value.error_count() == 32


def test_pane_config_40_keys_is_a_single_too_long_before_any_value_is_validated() -> None:
    s = {f"k{i}": [{}] * 32 for i in range(40)}
    with pytest.raises(ValidationError) as ei:
        PaneConfigIn.model_validate({"settings": s})
    assert [(e["loc"], e["type"]) for e in ei.value.errors()] == [(("settings",), "too_long")]


def test_array_over_32_items_refused_without_validating_items() -> None:
    with pytest.raises(ValidationError) as ei:
        LayoutPaneIn.model_validate(setting_pane([{}] * 33))
    assert ei.value.error_count() == 1


def test_array_with_many_bad_items_reports_one_error() -> None:
    with pytest.raises(ValidationError) as ei:
        LayoutPaneIn.model_validate(setting_pane([{}] * 32))
    assert ei.value.error_count() == 1


@pytest.mark.parametrize("raw", ["a\x00b", "a\x01b", "a\u202eb", "a\u2028b", "a\x7fb"])
def test_setting_strings_are_sanitised_scalar_and_array(raw: str) -> None:
    assert stored(raw) == "ab"
    assert stored([raw, "ok"]) == ["ab", "ok"]


def test_setting_string_is_trimmed_like_a_name_and_empty_is_kept() -> None:
    assert stored(" a\nb ") == "ab"
    assert stored(["  ", "\x00"]) == ["", ""]
    assert stored("\x00") == ""


def test_setting_string_256_boundary_is_raw_length() -> None:
    assert stored("a" * 256) == "a" * 256
    assert ("pane_config.settings.k", "string_too_long") in rules(
        LayoutPaneIn, setting_pane("a" * 256 + "\x00")
    )
    assert stored("a" * 255 + "\x00") == "a" * 255  # raw length 256: fits, then sanitised


def test_setting_array_item_over_256_is_string_too_long_with_clean_path() -> None:
    got = rules(LayoutPaneIn, setting_pane(["a" * 257]))
    assert got == {("pane_config.settings.k.0", "string_too_long")}


@pytest.mark.parametrize("value", ["\ud800", ["ok", "\udfff"]])
def test_setting_lone_surrogate_is_invalid_unicode(value: Any) -> None:
    got = {e["rule"] for e in errs(LayoutPaneIn, setting_pane(value))}
    assert got == {"invalid_unicode"}


def test_setting_non_scalar_is_a_type_error() -> None:
    assert errs(LayoutPaneIn, setting_pane({"x": 1}))
    assert errs(LayoutPaneIn, setting_pane([[1]]))


def test_setting_numbers_are_limited_to_1e15() -> None:
    assert stored(1e15) == 1e15 and stored(-(10**15)) == -(10**15) and stored([10**15]) == [10**15]
    for bad in (1e16, 10**15 + 1, [1e16], -1e16):
        assert any(
            e["rule"] == "number_out_of_range" for e in errs(LayoutPaneIn, setting_pane(bad))
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_setting_non_finite_is_refused(bad: float) -> None:
    assert errs(LayoutPaneIn, setting_pane(bad))


def test_negative_zero_is_normalised_to_zero() -> None:
    got = stored(-0.0)
    assert got == 0.0 and str(got) == "0.0"
    assert canonical_json({"a": stored(-0.0)}) == '{"a":0.0}'
    assert str(stored([-0.0])[0]) == "0.0"


def test_non_string_name_is_a_type_error_not_a_crash() -> None:
    assert errs(WorkspaceIn, {"name": 5})


def test_account_pane_without_symbol_and_volume_threshold_positive() -> None:
    LayoutPaneIn.model_validate({"slot_index": 0, "pane_kind": "journal"})
    LayoutPaneIn.model_validate(pane(interval_code="delta:0.5"))
