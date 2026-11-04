"""E40-X01 Part B (#5696): the five alert writes that read a body bound it before any work.

Gherkin "an alert write is bounded before any work": over the byte cap is the declared 413, nested
past the depth cap or past the value bound the declared 422, decided before the body is decoded
(depth) or validated (values), with nothing stored or recorded. Inputs come from the constants of
`api/alert_body.py`, on the rule routes' template (#4197); the helpers are `_alert_write_env.py`'s.
"""

from __future__ import annotations

import codecs
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from candleviewer.alerts.compiler import MAX_DEPTH, AlertCompiler
from candleviewer.alerts.errors import AlertIrInvalid
from candleviewer.api import alert_body
from candleviewer.api.alert_body import MAX_ALERT_BODY_BYTES, MAX_ALERT_JSON_DEPTH, MAX_ALERT_VALUES
from candleviewer.rules.vocabulary import default_registry
from tests.alerts._alert_api_env import PRICE_CROSS, USER_B
from tests.alerts._alert_write_env import BODY_ROUTES, asgi, deep, padded, sized, target

#: 22's "256 KiB (262,144 bytes)" as a literal: a test sized from the constant would follow it.
CAP = 256 * 1024


def rules(r: httpx.Response) -> list[str]:
    return [e["rule"] for e in r.json().get("errors") or []]


def too_large(r: httpx.Response) -> None:
    assert (r.status_code, r.headers["content-type"]) == (413, "application/problem+json")
    detail = f"The request body exceeds {CAP} bytes."
    assert r.json() == {"type": "https://candleviewer.local/errors/payload_too_large",
                        "title": "Request body or batch exceeds the operation's size ceiling",
                        "status": 413, "code": "payload_too_large", "detail": detail}  # fmt: skip


def _chained(levels: int) -> dict[str, Any]:
    """A condition whose variable is an arithmetic chain *levels* walker levels deep, ending in
    a metric with `params`: at `MAX_DEPTH`, the deepest JSON the alert compiler takes."""
    node: dict[str, Any] = {"metric": "price", "params": {}}
    for i in range(levels - 1):
        node = {"node_id": f"a{i}", "op": "add", "operands": [node, {"const": 1}]}
    ir: dict[str, Any] = {**PRICE_CROSS["condition_ir"], "variables": {"v": node}}
    return ir


def _depth(v: Any) -> int:
    kids = list(v.values()) if isinstance(v, dict) else v if isinstance(v, list) else None
    return 0 if kids is None else 1 + max((_depth(k) for k in kids), default=0)


class _NoDecode:
    @staticmethod
    def loads(_text: str) -> Any:
        raise AssertionError("the body was decoded before its depth was checked")


ROUTES = pytest.mark.parametrize("op", BODY_ROUTES)


@ROUTES
def test_alert_body_at_the_cap_is_read(op: str) -> None:
    """A body of exactly the cap is read, and the write goes through (SR-E40-17)."""
    t = target(op)
    assert t.send(padded(t.body, CAP)).status_code == t.ok and t.env.refused == []


@ROUTES
def test_alert_body_one_byte_over_the_cap_is_413(op: str) -> None:
    """Gherkin "a body over the byte cap": the declared 413, nothing stored or recorded, counted
    (SR-E40-17)."""
    t = target(op)
    before = t.snapshot()
    too_large(t.send(padded(t.body, CAP + 1)))
    assert (t.snapshot(), t.env.refused) == (before, ["body_too_large"])


@ROUTES
async def test_alert_body_declared_length_over_the_cap_is_413_unread(op: str) -> None:
    """Gherkin "before parsing the body": a declared length over the cap is refused before any
    byte is read (SR-E40-17)."""
    t, pulled = target(op), []

    async def chunks() -> AsyncIterator[bytes]:
        pulled.append(1)
        yield json.dumps(t.body).encode()

    too_large(await asgi(t, chunks(), {"content-length": str(MAX_ALERT_BODY_BYTES + 1)}))
    assert pulled == [] and t.env.refused == ["body_too_large"]


async def test_alert_body_streamed_past_the_cap_stops_one_chunk_past_it() -> None:
    """Gherkin "before parsing the body": with no length, the stream is read one chunk past the
    cap, never to its end (SR-E40-17)."""
    t, pulled = target("create"), []
    parts = [json.dumps(t.body)[:-1].encode(), *[b" " * (MAX_ALERT_BODY_BYTES // 16)] * 32, b"}"]

    async def chunks() -> AsyncIterator[bytes]:
        for part in parts:
            pulled.append(part)
            yield part

    r = await asgi(t, chunks())
    too_large(r)
    assert "content-length" not in r.request.headers
    assert len(pulled) <= 16 + 2 < len(parts) and t.state() == ({}, set())


@ROUTES
def test_alert_body_nested_past_the_bound_is_422_before_any_decode(
    op: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gherkin "nested past the depth cap": the declared 422 "before parsing the body", nothing
    stored or recorded, counted (SR-E40-17)."""
    t = target(op)
    before = t.snapshot()
    with monkeypatch.context() as patch:
        patch.setattr(alert_body, "json", _NoDecode())
        r = t.send(deep(MAX_ALERT_JSON_DEPTH + 1))
    assert (r.status_code, rules(r)) == (422, ["json_too_deep"]), r.text[:300]
    assert (t.snapshot(), t.env.refused) == (before, ["json_too_deep"])


@ROUTES
def test_alert_body_nested_at_the_bound_passes_the_depth_scan(op: str) -> None:
    """A body nested exactly at the bound reaches the route's own checks (SR-E40-17)."""
    t = target(op)
    r = t.send(deep(MAX_ALERT_JSON_DEPTH))
    assert "json_too_deep" not in r.text and t.env.refused == []


def test_alert_body_brackets_inside_a_string_are_not_nesting() -> None:
    """The depth scan reads strings: a name of 100 `[`, one level down, is no nesting, and the
    alert is stored (SR-E40-17)."""
    t = target("create")
    r = t.send(json.dumps(PRICE_CROSS | {"name": "[" * 100}).encode())
    assert (r.status_code, t.env.refused) == (201, []), r.text[:300]


@ROUTES
def test_alert_body_nested_past_the_decoder_limit_is_422_never_500(op: str) -> None:
    """Gherkin "nested past the depth cap": the declared 422, never a 500, even past what the
    decoder can recurse (SR-E40-17)."""
    t = target(op)
    c = TestClient(t.env.c.app, raise_server_exceptions=False)
    r = c.request(t.method, t.path, content=deep(MAX_ALERT_BODY_BYTES // 2 - 16))
    assert (r.status_code, rules(r)) == (422, ["json_too_deep"]), r.text[:300]


def test_alert_reader_takes_the_deepest_condition_the_compiler_admits() -> None:
    """The depth cap refuses no alert the compiler takes: 67 levels, where the rule routes take
    66 (BQ-3, SR-E40-17); one walker level deeper is the compiler's own refusal."""
    body = PRICE_CROSS | {"condition_ir": _chained(MAX_DEPTH)}
    assert _depth(body) == MAX_ALERT_JSON_DEPTH
    assert target("create").send(json.dumps(body).encode()).status_code == 201
    with pytest.raises(AlertIrInvalid):
        AlertCompiler(default_registry()).compile(_chained(MAX_DEPTH + 1))


SHAPES = pytest.mark.parametrize(
    ("op", "shape"),
    [("create", "params"), ("create", "set_values"), ("create", "padding"), ("update", "params"),
     ("enabled", "padding"), ("snooze", "padding"), ("desktop", "padding")],
)  # fmt: skip


@SHAPES
def test_alert_body_over_the_value_bound_is_422_before_validation_or_compile(
    op: str, shape: str
) -> None:
    """One value past the bound (in `params`, `set_values` or anywhere): the declared 422 before
    validation or compile, nothing stored or recorded, counted (SR-E40-17)."""
    t = target(op)
    before = t.snapshot()
    r = t.send(json.dumps(sized(t.body, shape, MAX_ALERT_VALUES + 1)).encode())
    assert (r.status_code, rules(r)) == (422, ["too_many_values"]), r.text[:300]
    assert (t.snapshot(), t.env.refused) == (before, ["too_many_values"])


@SHAPES
def test_alert_body_at_the_value_bound_reaches_validation(op: str, shape: str) -> None:
    """At the value bound the reader passes the body to the route's own checks (SR-E40-17)."""
    t = target(op)
    r = t.send(json.dumps(sized(t.body, shape, MAX_ALERT_VALUES)).encode())
    assert "too_many_values" not in r.text and t.env.refused == []


@ROUTES
def test_alert_body_not_utf8_is_the_routes_not_json_422(op: str) -> None:
    """A body in another encoding is the route's own 422 for one that is not JSON (RFC 8259
    section 8.1): nothing changed, nothing counted (SR-E40-17)."""
    t = target(op)
    before = t.snapshot()
    r = t.send(json.dumps(t.body).encode("utf-16"))
    assert (r.status_code, r.json()["code"]) == (422, "validation_failed")
    assert (t.snapshot(), t.env.refused) == (before, [])


def test_alert_name_in_latin_1_is_not_json_and_nothing_is_stored() -> None:
    """Strict UTF-8: a name sent in Latin-1 is a body that is not JSON, never a name stored with
    a replacement character; nothing changed, nothing counted (SR-E40-17)."""
    t = target("create")
    before = t.snapshot()
    body = json.dumps(PRICE_CROSS | {"name": "café"}, ensure_ascii=False).encode("latin-1")
    r = t.send(body)
    assert (r.status_code, r.json()["detail"]) == (422, "Body is not JSON.")
    assert (t.snapshot(), t.env.refused) == (before, [])


@ROUTES
def test_alert_body_with_a_byte_order_mark_is_the_routes_not_json_422(op: str) -> None:
    """22: UTF-8 without a byte order mark; with one, the route's 422 for a body that is not JSON,
    nothing changed, nothing counted (SR-E40-17)."""
    t = target(op)
    before = t.snapshot()
    r = t.send(codecs.BOM_UTF8 + json.dumps(t.body).encode())
    assert (r.status_code, r.json()["code"], t.snapshot(), t.env.refused) == (
        422, "validation_failed", before, []
    )  # fmt: skip


@ROUTES
def test_alert_bounds_answer_after_the_permission_check(op: str) -> None:
    """C-12.4 first: without `alerts:write` a 403 before the body is read, so no bound is reached
    (SR-E40-17)."""
    t = target(op)
    t.env.perms = frozenset({"alerts:read"})
    assert t.send(padded(t.body, CAP + 1)).status_code == 403 and t.env.refused == []


@pytest.mark.parametrize("op", [op for op in BODY_ROUTES if op != "create"])
def test_alert_bounds_answer_after_the_ownership_check(op: str) -> None:
    """Another user's alert or delivery is a 404 before the body is read, so no bound is reached
    (SR-E40-17)."""
    t = target(op)
    t.env.user = USER_B
    assert t.send(padded(t.body, CAP + 1)).status_code == 404 and t.env.refused == []
