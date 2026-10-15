"""E14-X02 (#474) abuse cases, part B: payload exhaustion on /drawings.

Pins threat-model DR29-DR31 and DR34 and the section 4 "Numeric bounds" rows. DR32 (no quota) and
DR33 (retry storm) are residuals (RR4), not pinned. Each case has one deterministic status and
the problem envelope."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from _drawings_api_env import BATCH, TRENDLINE, USER_A, USER_B, Env, wire

from candleviewer.api.drawings import IDEMPOTENCY_USER_MAX_ENTRIES
from candleviewer.api.drawings_models import (
    MAX_BATCH_BODY_BYTES,
    MAX_BATCH_OPS,
    MAX_JSON_DEPTH,
    MAX_SINGLE_BODY_BYTES,
    POINT_COUNTS,
)

PT = TRENDLINE["geometry"]["points"][0]
FIB = {"symbol": "BTCUSDT", "tool": "fib_retracement"}
CODES = {413: "payload_too_large", 422: "validation_failed"}


def _problem(r: Any, status: int, rule: str | None = None) -> None:
    assert r.status_code == status, r.text
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["code"] == CODES[status] and "detail" in r.json()
    if rule is not None:
        assert rule in [e["rule"] for e in r.json()["errors"]], r.text


def _raw(d: dict[str, Any]) -> str:
    return json.dumps(d, separators=(",", ":"))


def _pad_to(text: str, size: int) -> bytes:
    """`text` plus trailing JSON whitespace so the body is exactly `size` bytes."""
    raw = text.encode()
    assert len(raw) <= size
    return raw + b" " * (size - len(raw))


@pytest.fixture
def env() -> Env:  # each drawings test module defines its own; no shared one exists
    return Env()


def test_single_body_at_the_cap_is_served_and_one_byte_over_is_413(env: Env) -> None:
    body = _raw(wire(TRENDLINE))
    ok = env.c.post("/drawings", content=_pad_to(body, MAX_SINGLE_BODY_BYTES))
    assert ok.status_code == 201, ok.text
    _problem(env.c.post("/drawings", content=_pad_to(body, MAX_SINGLE_BODY_BYTES + 1)), 413)
    assert len(env.repo.rows) == 1


def test_batch_body_at_the_cap_is_served_and_one_byte_over_is_413(env: Env) -> None:
    body = _raw(wire({"operations": [{"op": "create", "drawing": TRENDLINE}]}, BATCH))
    assert (
        env.c.post("/drawings/batch", content=_pad_to(body, MAX_BATCH_BODY_BYTES)).status_code
        == 200
    )
    _problem(env.c.post("/drawings/batch", content=_pad_to(body, MAX_BATCH_BODY_BYTES + 1)), 413)
    assert len(env.repo.rows) == 1


def _deep(n: int) -> bytes:  # n nested objects
    return b'{"a":' * n + b"1" + b"}" * n


def test_json_at_the_depth_limit_reaches_the_model_and_fails_only_on_its_own_rules(
    env: Env,
) -> None:
    r = env.c.post("/drawings", content=_deep(MAX_JSON_DEPTH))
    _problem(r, 422)
    rules = {e["rule"] for e in r.json()["errors"]}
    assert "json_too_deep" not in rules and rules == {"extra_forbidden", "missing"}


def test_json_one_beyond_the_depth_limit_is_refused_before_parsing(env: Env) -> None:
    r = env.c.post("/drawings", content=_deep(MAX_JSON_DEPTH + 1))
    _problem(r, 422)
    assert [(e["field"], e["rule"]) for e in r.json()["errors"]] == [("", "json_too_deep")]
    assert env.repo.calls == []


@pytest.mark.parametrize("tool", ["brush", "polyline"])
def test_point_arrays_at_the_bound_pass_and_one_beyond_is_422(env: Env, tool: str) -> None:
    hi = POINT_COUNTS[tool][1]

    def make(n: int) -> dict[str, Any]:
        pts = [{"t": PT["t"], "p": str(i)} for i in range(n)]
        return {"symbol": "BTCUSDT", "tool": tool, "geometry": {"points": pts}}

    assert env.c.post("/drawings", json=make(hi)).status_code == 201
    _problem(env.c.post("/drawings", json=make(hi + 1)), 422, "tool_point_count")


def test_a_hundred_thousand_points_hit_the_body_cap_not_the_validator(env: Env) -> None:
    pts = [{"t": PT["t"], "p": "1"}] * 100_000
    r = env.c.post(
        "/drawings", json={"symbol": "BTCUSDT", "tool": "brush", "geometry": {"points": pts}}
    )
    _problem(r, 413)


LITERALS = ["1e999", "-1e999", "NaN", "Infinity", "-Infinity", "9" * 5000, "1" + "0" * 400 + ".5"]


@pytest.mark.parametrize("literal", LITERALS)
def test_a_huge_or_non_finite_level_is_a_bounded_422_never_a_500(env: Env, literal: str) -> None:
    body = _raw(wire(FIB | {"geometry": {"points": [PT, PT], "levels": [0.5]}}))
    r = env.c.post("/drawings", content=body.replace("[0.5]", f"[{literal}]"))
    _problem(r, 422)
    assert len(r.content) < 4096 and literal[:40] not in r.text  # no echo, no amplification
    assert env.repo.rows == {}


@pytest.mark.parametrize("literal", LITERALS)
def test_a_huge_or_non_finite_price_is_a_bounded_422_never_a_500(env: Env, literal: str) -> None:
    body = _raw(wire(TRENDLINE)).replace('"p":"61200.10"', f'"p":{literal}')
    r = env.c.post("/drawings", content=body)
    _problem(r, 422)
    assert len(r.content) < 4096 and literal[:40] not in r.text
    assert env.repo.rows == {}


def test_a_numeric_p_where_a_string_is_specified_is_refused(env: Env) -> None:
    body = _raw(wire(TRENDLINE)).replace('"p":"61200.10"', '"p":61200.1')
    _problem(env.c.post("/drawings", content=body), 422)


def test_duplicate_keys_in_a_single_body_are_last_wins(env: Env) -> None:
    """Threat model section 4: accepted, not an error. Pinned so a parser swap cannot change it."""
    base = _raw(wire(TRENDLINE | {"label": "first"}))
    dup = base[:-1] + ',"label":"second","locked":false,"locked":true}'
    r = env.c.post("/drawings", content=dup)
    assert r.status_code == 201 and r.json()["label"] == "second" and r.json()["locked"] is True


def test_duplicate_keys_in_a_batch_are_last_wins_too(env: Env) -> None:
    op = {"op": "create", "drawing": wire(TRENDLINE)}
    batch = '{"operations":[' + json.dumps(op) + '],"operations":[]}'
    _problem(env.c.post("/drawings/batch", content=batch), 422, "too_short")  # the empty list wins
    assert env.repo.rows == {}


def test_a_batch_of_maximum_size_geometry_is_413_before_validation(env: Env) -> None:
    points = [{"t": PT["t"], "p": "1"}] * POINT_COUNTS["brush"][1]
    op = {"op": "create", "drawing": {"symbol": "BTCUSDT", "tool": "brush",
                                      "geometry": {"points": points}}}  # fmt: skip
    r = env.c.post("/drawings/batch", content=json.dumps({"operations": [op] * MAX_BATCH_OPS}))
    _problem(r, 413)
    assert env.repo.calls == []


def _post(env: Env, key: str) -> Any:
    return env.c.post("/drawings", json=wire(TRENDLINE), headers={"Idempotency-Key": key})


def _fill(env: Env, n: int) -> list[str]:
    keys = [str(uuid.UUID(int=i + 1, version=4)) for i in range(n)]
    for k in keys:
        r = _post(env, k)
        assert r.status_code == 201 and "idempotency-replayed" not in r.headers
    return keys


def test_idempotency_pressure_evicts_the_oldest_key_of_the_flooding_user_only() -> None:
    env = Env()
    first_key = str(uuid.UUID(int=1, version=4))  # shared with A on purpose
    env.user = USER_B
    b_first = _post(env, first_key).json()
    env.user = USER_A
    keys = _fill(env, IDEMPOTENCY_USER_MAX_ENTRIES + 1)  # A's first post must not replay B's
    assert keys[0] == first_key
    before = len(env.repo.rows)
    replay = _post(env, keys[-1])
    assert replay.headers.get("idempotency-replayed") == "true" and len(env.repo.rows) == before
    evicted = _post(env, keys[0])
    assert evicted.status_code == 201 and "idempotency-replayed" not in evicted.headers  # re-ran
    env.user = USER_B
    kept = _post(env, first_key)
    assert kept.headers.get("idempotency-replayed") == "true"  # B was never evicted by A
    assert kept.json()["id"] == b_first["id"]  # B's own response, not A's under the shared key
    assert kept.json()["owner_user_id"] == str(USER_B)  # fails if the cache ignored the user
