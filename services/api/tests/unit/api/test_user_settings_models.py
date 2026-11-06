"""`user_settings_models` (E02-T13, #5181): 22's `Settings` as the closed leaf table, a patch judged
whole before anything is written (only named leaves, `null` resets, every refusal listed), and the
effective document served with `_meta`. Pure logic: no store, no HTTP."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, get_args

import jsonschema
import pytest
from structlog.testing import capture_logs

from candleviewer.api import user_settings_models as m
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.audit.redact import REDACTION_MARKER, redact
from candleviewer.orderflow import limits as L
from candleviewer.orderflow.bigtrade_models import Mode
from candleviewer.storage.repositories.user_settings import UserSetting
from tests.openapi_helpers import deref

_SPEC: Any = load_openapi_spec()
_SETTINGS: Any = _SPEC["components"]["schemas"]["Settings"]
_T1, _T2 = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
_PRESETS = "trading.default_qty_presets"


def _judge(doc: object) -> dict[str, object]:
    return m.judge_patch(json.dumps(doc).encode())


def _refusal(raw: bytes) -> list[dict[str, str]]:
    with pytest.raises(m.PatchRefused) as refused:
        m.judge_patch(raw)
    return refused.value.errors


def _rules(doc: object) -> list[tuple[str, str]]:
    return [(e["field"], e["rule"]) for e in _refusal(json.dumps(doc).encode())]


def test_leaves_are_exactly_the_leaves_22s_settings_declares() -> None:
    declared = {
        f"{group}.{leaf}"
        for group, schema in _SETTINGS["properties"].items()
        if group != "_meta"
        for leaf in deref(_SPEC, schema)["properties"]
    }
    assert set(m.LEAVES) == declared
    assert {key for key in m.LEAVES if key.startswith("bigtrade.")} == {
        "bigtrade.threshold_mode",
        "bigtrade.threshold_value",
        "bigtrade.percentile_window_ms",
    }  # E22-D05 section 5's S02 keys (#715), each one leaf


def test_judge_patch_keeps_only_the_named_leaves() -> None:
    assert _judge({"appearance": {"theme": "light"}}) == {"appearance.theme": "light"}


def test_judge_patch_a_null_leaf_is_a_reset() -> None:
    patch = _judge({"appearance": {"theme": None}, "notifications": {"webhook_url": None}})
    assert patch == {"appearance.theme": None, "notifications.webhook_url": None}


def test_judge_patch_stores_each_value_as_its_generated_model_writes_it() -> None:
    patch = _judge(
        {
            "appearance": {"font_scale": 1},
            "orderflow": {"min_stack": 3.0},
            "trading": {"default_qty_presets": ["0.010", "1"], "default_environment": "demo"},
            "notifications": {"quiet_hours": {"from": "22:00", "days": [1, 2]}},
        }
    )
    assert patch == {
        "appearance.font_scale": 1.0,
        "orderflow.min_stack": 3,
        "trading.default_qty_presets": ["0.010", "1"],  # decimals stay strings (C6)
        "trading.default_environment": "demo",
        "notifications.quiet_hours": {"from": "22:00", "days": [1, 2]},
    }


def test_judge_patch_an_empty_body_object_changes_nothing() -> None:
    assert _judge({}) == {} and _judge({"appearance": {}}) == {}


def test_judge_patch_takes_each_bigtrade_leaf_as_its_whole_symbol_map() -> None:
    """E22-S02 (#715): the symbol sits inside the value, one leaf per key (E22-D05 section 5)."""
    patch = _judge(
        {
            "bigtrade": {
                "threshold_mode": {"BTCUSDT": "notional", "ETHUSDT": "percentile"},
                "threshold_value": {"BTCUSDT": "250000", "ETHUSDT": "99.5"},
                "percentile_window_ms": {"ETHUSDT": 3_600_000},
            }
        }
    )
    assert patch == {
        "bigtrade.threshold_mode": {"BTCUSDT": "notional", "ETHUSDT": "percentile"},
        "bigtrade.threshold_value": {"BTCUSDT": "250000", "ETHUSDT": "99.5"},  # strings (C6)
        "bigtrade.percentile_window_ms": {"ETHUSDT": 3_600_000},
    }


def _many(count: int, value: object) -> dict[str, object]:
    return {f"{i:020d}USDT": value for i in range(count)}


@pytest.mark.parametrize(
    ("leaf", "value", "symbol", "rule"),
    [
        ("threshold_mode", {"BTCUSDT": "absolute"}, "BTCUSDT", "literal_error"),
        ("threshold_mode", _many(201, "notional"), "", "too_long"),
        ("threshold_value", {"BTCUSDT": "-1"}, "BTCUSDT", "string_pattern_mismatch"),
        ("threshold_value", {"BTCUSDT": 250000}, "BTCUSDT", "string_type"),
        ("threshold_value", {"BTCUSDT": "1e6"}, "BTCUSDT", "string_pattern_mismatch"),
        ("percentile_window_ms", {"BTCUSDT": 59_999}, "BTCUSDT", "greater_than_equal"),
        ("percentile_window_ms", {"BTCUSDT": 86_400_001}, "BTCUSDT", "less_than_equal"),
    ],
)  # fmt: skip
def test_judge_patch_refuses_a_bigtrade_value_outside_the_engines_bounds(
    leaf: str, value: object, symbol: str, rule: str
) -> None:
    field = f"bigtrade.{leaf}.{symbol}" if symbol else f"bigtrade.{leaf}"
    assert _rules({"bigtrade": {leaf: value}}) == [(field, rule)]


def test_symbol_keyed_leaves_are_22s_with_their_symbol_pattern_and_200_cap() -> None:
    """22's `then.propertyNames` is the key pattern no generated model carries (E22-S02, #715):
    the server's `SYMBOL_KEYED` and `SYMBOL` are pinned to it, so dropping the `then` fails here."""
    keyed: dict[str, Any] = {}
    for group, schema in _SETTINGS["properties"].items():
        for leaf, member in deref(_SPEC, schema).get("properties", {}).items():
            if "propertyNames" in member.get("then", {}):
                keyed[f"{group}.{leaf}"] = member
    assert set(keyed) == m.SYMBOL_KEYED
    assert _SPEC["components"]["schemas"]["Symbol"]["pattern"] == f"^{m.SYMBOL.pattern}$"
    for member in keyed.values():
        assert member["maxProperties"] == L.THRESHOLD_SYMBOLS_PER_USER_MAX  # SR-E22-11
        assert member["then"]["propertyNames"]["pattern"] == f"^{m.SYMBOL.pattern}$"


def test_bigtrade_leaves_carry_the_engines_vocabulary_and_limits_bounds() -> None:
    """22's `bigtrade` values are `BigTradeConfig`'s mode enum and `limits.py`'s window bounds,
    never a copy that drifts from them (E22 threat model section 7, E22-S02 #715)."""
    leaves = deref(_SPEC, _SETTINGS["properties"]["bigtrade"])["properties"]
    values = {name: deref(_SPEC, leaf)["additionalProperties"] for name, leaf in leaves.items()}
    assert values["threshold_mode"]["enum"] == list(get_args(Mode))
    window = values["percentile_window_ms"]
    assert (window["minimum"], window["maximum"]) == (
        L.PERCENTILE_WINDOW_MS_MIN,
        L.PERCENTILE_WINDOW_MS_MAX,
    )


@pytest.mark.parametrize("key", ["btcusdt", "", "A" * 2044 + "USDT", "BTCUSDT\r\nX: 1", "<b>"])
@pytest.mark.parametrize("leaf", sorted(m.SYMBOL_KEYED))
def test_judge_patch_refuses_a_bigtrade_map_keyed_by_anything_but_a_symbol(
    leaf: str, key: str
) -> None:
    """The key is refused before the leaf's model reads it, so it is never echoed (E22-S02)."""
    good = {"bigtrade.threshold_mode": "notional", "bigtrade.threshold_value": "250000"}
    value = good.get(leaf, 3_600_000)
    group, _, name = leaf.partition(".")
    assert _rules({group: {name: {"BTCUSDT": value, key: value}}}) == [
        (leaf, "string_pattern_mismatch")
    ]


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        ({"appearance": {"glow": True}}, [("appearance.glow", "extra_forbidden")]),
        ({"bigtrade": {"k": 3}}, [("bigtrade.k", "extra_forbidden")]),
        ({"big_trade": {"k": 3}}, [("big_trade", "extra_forbidden")]),
        ({"appearance": {"theme": "neon"}}, [("appearance.theme", "literal_error")]),
        ({"appearance": {"font_scale": 3}}, [("appearance.font_scale", "less_than_equal")]),
        ({"appearance": {"reduce_motion": 1}}, [("appearance.reduce_motion", "bool_type")]),
        ({"data": {"default_depth": "200"}}, [("data.default_depth", "int_type")]),
        ({"trading": {"default_qty_presets": [0.1]}}, [(f"{_PRESETS}.0", "value_error")]),
        ({"trading": {"one_click_armed": True}}, [("trading.one_click_armed", "read_only")]),
        ({"trading": {"one_click_armed": None}}, [("trading.one_click_armed", "read_only")]),
        ({"_meta": {"overridden": []}}, [("_meta", "read_only")]),
        ({"appearance": "light"}, [("appearance", "model_type")]),
        ({"appearance": None}, [("appearance", "model_type")]),
    ],
)  # fmt: skip
def test_judge_patch_refuses_what_22s_settings_does_not_accept(
    doc: object, expected: list[tuple[str, str]]
) -> None:
    assert _rules(doc) == expected


def test_judge_patch_refuses_the_whole_patch_and_lists_every_refusal() -> None:
    doc = {
        "appearance": {"theme": "light", "font_scale": 9},  # one good leaf, one bad
        "trading": {"one_click_armed": False},
        "big_trade": {},
    }
    assert _rules(doc) == [
        ("appearance.font_scale", "less_than_equal"),
        ("trading.one_click_armed", "read_only"),
        ("big_trade", "extra_forbidden"),
    ]


def test_judge_patch_lists_at_most_twenty_refusals() -> None:
    assert len(_refusal(json.dumps({"appearance": {f"x{i}": 1 for i in range(30)}}).encode())) == 20


def test_judge_patch_echoes_no_key_that_has_no_leaf_names_shape() -> None:
    assert _rules({"appearance": {"<b>x</b>": 1}, "Ünknown": {}}) == [
        ("appearance", "extra_forbidden"),
        ("", "extra_forbidden"),
    ]


def test_judge_patch_never_echoes_a_value() -> None:
    errors = _refusal(json.dumps({"appearance": {"theme": "canary-5181"}}).encode())
    assert "canary-5181" not in json.dumps(errors)


@pytest.mark.parametrize(
    ("raw", "rule"),
    [
        (b"{", "json_invalid"),
        (b"\xff\xfe", "json_invalid"),
        (b'{"appearance": {"font_scale": NaN}}', "json_invalid"),
        (b'{"orderflow": {"imbalance_ratio": 1e999}}', "json_invalid"),
        (b'{"notifications": {"quiet_hours": ' + b"[" * 10 + b"]" * 10 + b"}}", "json_invalid"),
        (b"[" * 100_000 + b"]" * 100_000, "json_invalid"),
        (b'{"chart": {"default_param": "a\\u0000b"}}', "invalid_character"),
        (b'{"notifications": {"quiet_hours": {"\\ud800": 1}}}', "invalid_character"),
        (b'["appearance"]', "model_type"),
        (b"null", "model_type"),
    ],
)
def test_judge_patch_refuses_a_body_no_setting_can_store(raw: bytes, rule: str) -> None:
    assert [(e["field"], e["rule"]) for e in _refusal(raw)] == [("", rule)]


def _row(key: str, value: object, at: datetime = _T1) -> UserSetting:
    return UserSetting(key, value, at)


def test_effective_of_no_rows_is_the_empty_settings() -> None:
    assert m.effective((), viewing=False) == {"_meta": {"overridden": []}}


def test_effective_overlays_the_rows_and_meta_names_them_with_the_latest_write() -> None:
    doc = m.effective(
        [
            _row("appearance.density", "compact"),
            _row("appearance.font_scale", 1, _T2),
            _row("trading.default_qty_presets", ["0.01"]),
        ],
        viewing=False,
    )
    assert doc == {
        "appearance": {"density": "compact", "font_scale": 1.0},
        "trading": {"default_qty_presets": ["0.01"]},
        "_meta": {
            "overridden": [
                "appearance.density",
                "appearance.font_scale",
                "trading.default_qty_presets",
            ],
            "updated_at": "2026-10-02T09:30:00Z",
        },
    }
    jsonschema.validate(doc, deref(_SPEC, {"$ref": "#/components/schemas/Settings"}))


@pytest.mark.parametrize(
    "row",
    [
        _row("bigtrade.k", 3),  # a leaf 22 does not declare
        _row("appearance.theme", "neon"),  # a value 22 no longer accepts
        _row("appearance.density", None),  # a JSON null is no value
        _row("bigtrade.threshold_mode", {"btcusdt": "notional"}),  # a key that is no `Symbol`
    ],
    ids=["undeclared", "refused", "null", "unsymbolled"],
)
def test_effective_never_serves_a_row_22s_settings_refuses_and_logs_only_its_key(
    row: UserSetting,
) -> None:
    with capture_logs() as logs:
        doc = m.effective([row, _row("chart.crosshair_sync", True)], viewing=False)
    assert doc == {
        "chart": {"crosshair_sync": True},
        "_meta": {"overridden": ["chart.crosshair_sync"], "updated_at": "2026-10-01T00:00:00Z"},
    }
    assert logs == [
        {"event": "user_settings_row_not_served", "key": row.key, "log_level": "warning"}
    ]


# -- Q3, as ruled: the credential-class leaf leaves its owner masked -------------------------------

_HOOK = "notifications.webhook_url"


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        ("https://hooks.example.test/services/T000/B000/x", "https://hooks.example.test/…"),
        ("https://u:pw@hooks.example.test:8443/p?q=1#f", "https://hooks.example.test/…"),
        ("https://hooks.example.test", "https://hooks.example.test/…"),
        ("HTTPS://Hooks.Example.TEST/x", "https://hooks.example.test/…"),
        ("http://[2001:db8::1]:8080/hook", "http://[2001:db8::1]/…"),
        ("https://user:p@ss@hooks.example.test/x", "https://hooks.example.test/…"),
        ("hooks.example.test/x", "…"),  # no scheme
        ("//hooks.example.test/x", "…"),
        ("mailto:ops@example.test", "…"),  # no host
        ("https:///x", "…"),
        ("https://u@:8443/x", "…"),
        ("https://[::1/x", "…"),  # unclosed bracket: `urlsplit` refuses it
        ("https://[hooks]/x", "…"),  # a bracketed host that is no IP address
        ("https://192.0.2.1:8443/x", "https://192.0.2.1/…"),  # an IPv4 address
        ("https://hooks-1.example.test/x", "https://hooks-1.example.test/…"),
        ("https://bücher.example.test/x", "…"),  # a label of letters other than a to z
        # A malformed authority: its host is no DNS name and no IP address free of a zone.
        ("https://hooks.example.test\\services\\T000\\TOKEN", "…"),  # WHATWG: `\` starts a path
        ("https://hooks.example.test TOKEN/x", "…"),
        ("https://hooks.example.test;TOKEN/x", "…"),
        ("https://hooks.example.test%2FTOKEN/x", "…"),
        ("https://[fe80::1%25TOKEN]/x", "…"),  # a zone
        ("https://[v1.TOKEN]/x", "…"),  # IPvFuture: its host would read as `v1.token`
        ("https://hooks.example.test\tTOKEN/x", "…"),  # `urlsplit` deletes the tab
        ("https://hooks.example.test\r\nTOKEN/x", "…"),
        (42, "…"),  # not a string
        (["https://hooks.example.test/x"], "…"),
        (None, None),  # no override
        ("", ""),
    ],
)
def test_masked_keeps_a_webhook_urls_scheme_and_host_only(value: object, shown: object) -> None:
    assert m.masked(_HOOK, value) == shown


def test_masked_leaves_every_other_leaf_as_it_is() -> None:
    url = "https://u:pw@hooks.example.test/x"
    assert {key: m.masked(key, url) for key in m.LEAVES if key != _HOOK} == dict.fromkeys(
        set(m.LEAVES) - {_HOOK}, url
    )
    assert m.MASKED_LEAVES == {_HOOK} and m.MASKED_LEAVES <= set(m.LEAVES)


@pytest.mark.parametrize("viewing", [False, True], ids=["owner", "viewing"])
def test_effective_masks_the_webhook_url_for_a_viewer_only(viewing: bool) -> None:
    url = "https://u:pw@hooks.example.test:8443/T000/canary?k=canary#canary"
    doc = m.effective(
        [_row(_HOOK, url), _row("notifications.email_enabled", True)], viewing=viewing
    )
    shown = "https://hooks.example.test/…" if viewing else url
    assert doc["notifications"] == {"webhook_url": shown, "email_enabled": True}
    assert doc["_meta"]["overridden"] == ["notifications.email_enabled", _HOOK]
    jsonschema.validate(doc, deref(_SPEC, {"$ref": "#/components/schemas/Settings"}))


def test_the_audit_redactor_masks_only_orderflow_big_trade_k_among_the_leaves() -> None:
    """Every leaf's key through the real `audit.redact`, as a `settings.change` state passes it.
    Its name rules are by fragment, and `orderflowbigtradek` holds "dek" ("tra-dek"), so that one
    leaf's change is recorded with no values. A new leaf the redactor masks, or a redactor change
    that masks another or stops masking this one, fails here; a carve-out is `audit/redact.py`'s
    own, security-reviewed change, not this module's."""
    redacted = redact(dict.fromkeys(m.LEAVES, "kept"))
    assert redacted is not None and set(redacted) == set(m.LEAVES)
    masked = {key: value for key, value in redacted.items() if value != "kept"}
    assert masked == {"orderflow.big_trade_k": REDACTION_MARKER}
