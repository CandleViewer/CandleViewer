"""E14-X02 (#474) abuse cases, part B: payload exhaustion on /drawings (threat model DR30-DR33,
section 4 "Numeric bounds"). Every case has one deterministic status and the problem envelope."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from _drawings_api_env import BATCH, TRENDLINE, USER_A, USER_B, Env, wire
from fastapi.testclient import TestClient

from candleviewer.api.drawings import IDEMPOTENCY_USER_MAX_ENTRIES
from candleviewer.api.drawings_models import (
    MAX_BATCH_BODY_BYTES,
    MAX_SINGLE_BODY_BYTES,
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
def env() -> Env:
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


def test_a_chunked_body_without_a_length_is_capped_while_streaming(env: Env) -> None:
    chunks = (b" " * 1024 for _ in range(MAX_SINGLE_BODY_BYTES // 1024 + 1))
    _problem(env.c.post("/drawings", content=chunks), 413)
    assert env.repo.calls == []


def test_json_depth_16_is_parsed_and_17_is_refused_before_parsing(env: Env) -> None:
    def deep(n: int) -> bytes:  # n nested objects
        return b'{"a":' * n + b"1" + b"}" * n

    _problem(env.c.post("/drawings", content=deep(16)), 422)  # parsed, then unknown key
    r = env.c.post("/drawings", content=deep(17))
    _problem(r, 422, "json_too_deep")
    assert env.repo.calls == []


@pytest.mark.parametrize(("tool", "hi"), [("brush", 500), ("polyline", 100)])
def test_point_arrays_at_the_bound_pass_and_one_beyond_is_422(env: Env, tool: str, hi: int) -> None:
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


@pytest.mark.parametrize(
    "literal",
    ["1e999", "-1e999", "NaN", "Infinity", "-Infinity", "9" * 5000, "1" + "0" * 400 + ".5"],
)
def test_huge_and_non_finite_numbers_are_a_bounded_422_never_a_500(env: Env, literal: str) -> None:
    body = _raw(wire(FIB | {"geometry": {"points": [PT, PT], "levels": [0.5]}}))
    r = env.c.post("/drawings", content=body.replace("[0.5]", f"[{literal}]"))
    _problem(r, 422)
    assert len(r.content) < 4096 and literal[:40] not in r.text  # no echo, no amplification
    r = env.c.post(
        "/drawings", content=_raw(wire(TRENDLINE)).replace('"p":"61200.10"', f'"p":{literal}')
    )
    _problem(r, 422)
    assert env.repo.rows == {}


def test_a_numeric_p_where_a_string_is_specified_is_refused(env: Env) -> None:
    body = _raw(wire(TRENDLINE)).replace('"p":"61200.10"', '"p":61200.1')
    _problem(env.c.post("/drawings", content=body), 422)


def test_duplicate_json_keys_are_last_wins_pinned_per_the_threat_model(env: Env) -> None:
    """Section 4: accepted, not an error. Pinned so a parser swap cannot silently change it."""
    base = _raw(wire(TRENDLINE | {"label": "first"}))
    dup = base[:-1] + ',"label":"second","locked":false,"locked":true}'
    r = env.c.post("/drawings", content=dup)
    assert r.status_code == 201 and r.json()["label"] == "second" and r.json()["locked"] is True
    op = {"op": "create", "drawing": json.loads(dup)}
    batch = '{"operations":[' + json.dumps(op) + '],"operations":[]}'
    _problem(env.c.post("/drawings/batch", content=batch), 422)  # last-wins: the empty list


def test_a_batch_of_maximum_size_geometry_is_413_before_validation(env: Env) -> None:
    op = {"op": "create", "drawing": {"symbol": "BTCUSDT", "tool": "brush",
          "geometry": {"points": [{"t": PT["t"], "p": "1"}] * 500}}}  # fmt: skip
    r = env.c.post("/drawings/batch", content=json.dumps({"operations": [op] * 200}))
    _problem(r, 413)
    assert env.repo.calls == []


def _fill(c: TestClient, n: int) -> list[str]:
    keys = [str(uuid.uuid4()) for _ in range(n)]
    for k in keys:
        assert (
            c.post("/drawings", json=wire(TRENDLINE), headers={"Idempotency-Key": k}).status_code
            == 201
        )
    return keys


def test_idempotency_pressure_evicts_the_oldest_key_of_the_flooding_user_only() -> None:
    env = Env()
    env.user = USER_B
    b_key = _fill(env.c, 1)[0]
    env.user = USER_A
    keys = _fill(env.c, IDEMPOTENCY_USER_MAX_ENTRIES + 1)
    before = len(env.repo.rows)
    replay = env.c.post("/drawings", json=wire(TRENDLINE), headers={"Idempotency-Key": keys[-1]})
    assert replay.headers.get("idempotency-replayed") == "true" and len(env.repo.rows) == before
    evicted = env.c.post("/drawings", json=wire(TRENDLINE), headers={"Idempotency-Key": keys[0]})
    assert evicted.status_code == 201 and "idempotency-replayed" not in evicted.headers  # re-ran
    env.user = USER_B
    kept = env.c.post("/drawings", json=wire(TRENDLINE), headers={"Idempotency-Key": b_key})
    assert kept.headers.get("idempotency-replayed") == "true"  # B was never evicted by A
