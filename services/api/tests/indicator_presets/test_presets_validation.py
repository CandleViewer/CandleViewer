"""`/indicator-presets` validation through the router (E13-T03, #427): A3 (invalid params are
refused at the boundary and nothing is persisted), AC-04..AC-08 and the 413 body cap. The rules
themselves are pinned at the model level in `test_presets_models.py`."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from _presets_env import Env, body

from candleviewer.orderflow.indicators.limits import PRESET_BODY_MAX_BYTES

_BOUND = "Period must be between 1 and 5000."


def _post(env: Env, data: dict[str, Any]) -> Any:
    return env.c.post("/indicator-presets", json=data)


def _post_raw(env: Env, text: str) -> Any:
    return env.c.post("/indicator-presets", content=text.encode(),
                      headers={"content-type": "application/json"})  # fmt: skip


def _no_write(env: Env) -> None:
    assert not any(name in ("create", "update", "import_many") for name, _ in env.repo.calls)
    assert env.mine() == [] and env.audit.actions() == []


@pytest.mark.parametrize("code", ["ema", "sma", "atr"])
@pytest.mark.parametrize(("n", "rule"), [(0, "minimum"), (10000, "maximum")])
def test_n_zero_and_10000_are_422_naming_params_n(code: str, n: int, rule: str) -> None:
    """A3: 422 with the offending field named, and nothing persisted."""
    env = Env()
    r = _post(env, body(indicator_code=code, params={"n": n}))
    assert (r.status_code, r.json()["code"]) == (422, "validation_failed")
    assert r.json()["errors"] == [{"field": "params.n", "rule": rule, "message": _BOUND}]
    _no_write(env)
    made = env.create(indicator_code=code, params={"n": 5000})
    assert made["params"] == {"n": 5000}


@pytest.mark.parametrize(
    ("raw", "field", "rule"),
    [("-1", "params.n", "minimum"), ("5001", "params.n", "maximum"),
     ("1e9", "params.n", "maximum"), ('"14"', "params.n", "type"), ("null", "params.n", "type"),
     ("NaN", "params.n", "type"), ("Infinity", "params.n", "type"),
     ("-Infinity", "params.n", "type"), ("1e400", "params.n", "type"),
     ("1.5", "params.n", "type"), ("true", "params.n", "type"),
     ("9" * 5000, "", "json_invalid"), ('14, "x": 1', "params", "additionalProperties")],
)  # fmt: skip
def test_ac05_values_are_422(raw: str, field: str, rule: str) -> None:
    env = Env()
    text = json.dumps(body()).replace('{"n": 14}', '{"n": ' + raw + "}")
    r = _post_raw(env, text)
    assert r.status_code == 422
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [(field, rule)]
    assert raw not in r.json()["errors"][0]["message"]  # the bound, never the value
    _no_write(env)


@pytest.mark.parametrize("code", ["nope", "atr_trail", "a" * 33, "ATR", "../x", "ema;drop"])
def test_ac06_codes_are_422_without_echo(code: str) -> None:
    env = Env()
    r = _post(env, body(indicator_code=code))
    assert r.status_code == 422
    (error,) = r.json()["errors"]
    assert error["field"] == "indicator_code"
    assert error["rule"] in ("unknown_indicator", "invalid_indicator_code")
    assert code not in r.text
    _no_write(env)


@pytest.mark.parametrize(
    "field",
    ["is_builtin", "owner_user_id", "id", "deleted_at", "created_at", "updated_at", "compute",
     "is_default", "sl_atr_period"],
)  # fmt: skip
def test_unknown_top_level_fields_are_422(field: str) -> None:
    """AC-04, IR-10: never ignored, so a body cannot forge a built-in, an owner or a row."""
    env = Env()
    value = {"is_builtin": True, "owner_user_id": "00000000-0000-4000-8000-00000000000b"}.get(
        field, "0193f2bb-9c11-7a3d-88f1-0d2e3f4a5b6c"
    )
    r = _post(env, body(**{field: value}))
    assert r.status_code == 422
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [(field, "extra_forbidden")]
    _no_write(env)


@pytest.mark.parametrize(
    "style",
    [{"line": "#ff0000"}, {"line": "url(javascript:1)"}, {"__proto__": {"x": 1}}, {"w": 1e308},
     {"constructor": "x"}, {"color.indicator.1": "color.indicator.1"}],
)  # fmt: skip
def test_style_must_be_empty_until_vocabulary_ships(style: dict[str, Any]) -> None:
    """AC-07: refused, never stripped (strip == fail)."""
    env = Env()
    r = _post(env, body(indicator_code="ema", params={"n": 9}, style=style))
    assert r.status_code == 422
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [("style", "style_not_allowed")]
    assert all(key not in r.json()["errors"][0]["message"] for key in style)
    _no_write(env)


@pytest.mark.parametrize("pane", ["main", "", "OVERLAY", None])
def test_pane_target_enum(pane: Any) -> None:
    env = Env()
    r = _post(env, body(pane_target=pane))
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [
        ("pane_target", "literal_error")
    ]
    assert env.create(pane_target="overlay")["pane_target"] == "overlay"


def _sized(total: int) -> dict[str, str]:
    return {"k": "v" * (total - 9)}  # `{"k": "..."}`: 9 bytes around the value


@pytest.mark.parametrize(
    ("params", "rule"),
    [(_sized(4096), "additionalProperties"), (_sized(4097), "params_too_large"),
     ({"a": {"b": {"c": {"d": 1}}}}, "additionalProperties"),
     ({"a": {"b": {"c": {"d": {"e": 1}}}}}, "params_too_deep"),
     ({f"k{i}": 1 for i in range(64)}, "additionalProperties"),
     ({f"k{i}": 1 for i in range(65)}, "params_too_many_keys")],
)  # fmt: skip
def test_size_caps_at_and_over(params: dict[str, Any], rule: str) -> None:
    """AC-08: at the bound the size check passes (and the descriptor refuses the keys); one
    past it the size rule fires first."""
    env = Env()
    r = _post(env, body(params=params))
    assert (r.status_code, [e["rule"] for e in r.json()["errors"]]) == (422, [rule])
    _no_write(env)


def test_a_body_at_16_kib_is_read_and_one_byte_more_is_413_before_parsing() -> None:
    env = Env()
    base = json.dumps(body())
    at_cap = base[:-1] + " " * (PRESET_BODY_MAX_BYTES - len(base)) + "}"
    assert len(at_cap.encode()) == PRESET_BODY_MAX_BYTES
    assert _post_raw(env, at_cap).status_code == 201
    r = _post_raw(env, at_cap[:-1] + " }")
    assert (r.status_code, r.json()["code"]) == (413, "payload_too_large")
    assert r.json()["detail"] == f"The request body exceeds {PRESET_BODY_MAX_BYTES} bytes."


def test_a_2_mib_streamed_body_stops_being_read_past_the_cap() -> None:
    """AC-08: no `Content-Length`, so the streaming cap stops the read one chunk past 16 KiB."""
    env, sent = Env(), []

    def chunks() -> Iterator[bytes]:
        for _ in range(2 * 1024 // 4):  # 512 chunks of 4 KiB = 2 MiB
            sent.append(1)
            yield b" " * 4096

    r = env.c.post("/indicator-presets", content=chunks(),
                   headers={"content-type": "application/json"})  # fmt: skip
    assert (r.status_code, r.json()["code"]) == (413, "payload_too_large")
    _no_write(env)


def test_a_declared_length_over_the_cap_is_refused_without_reading() -> None:
    env = Env()
    r = env.c.put("/indicator-presets/00000000-0000-4000-8000-0000000000ff",
                  content=b"{}", headers={"content-length": str(2 * 1024 * 1024),
                                          "content-type": "application/json"})  # fmt: skip
    assert r.status_code == 413


@pytest.mark.parametrize(
    ("raw", "rule"),
    [(b"\xff\xfe", "json_invalid"), (b'{"name": ', "json_invalid"),
     (("[" * 17 + "]" * 17).encode(), "json_too_deep")],
)  # fmt: skip
def test_a_body_that_is_not_utf8_json_or_nests_too_deep_is_422(raw: bytes, rule: str) -> None:
    env = Env()
    r = env.c.post("/indicator-presets", content=raw, headers={"content-type": "application/json"})
    assert (r.status_code, r.json()["errors"][0]["rule"]) == (422, rule)


def test_validation_errors_are_bounded_and_echo_no_client_text() -> None:
    env = Env()
    hostile = {f"<script>{'x' * 100}{i}": i for i in range(30)}
    r = _post(env, body(**hostile))
    errors = r.json()["errors"]
    assert r.status_code == 422 and len(errors) == 20
    assert all(len(e["field"]) <= 65 and "x" * 100 not in e["field"] for e in errors)
