"""E40-X01 Part B (#5696): the five alert writes that read a body bound it before any work.

Gherkin "an alert write is bounded before any work": over the byte cap is the declared 413, nested
past the depth cap or past the value bound the declared 422, decided before the body is decoded
(depth) or validated (values), with nothing stored or recorded; the widest alert the bounds admit is
saved within the loop budget (C-2.17). The byte cap and the value bound are 22's numbers, the
depth `api/alert_body.py`'s, on the rule routes' template (#4197); the helpers are
`_alert_write_env.py`'s.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import time
from dataclasses import replace
from typing import Any

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from candleviewer.alerts.compiler import MAX_DEPTH, AlertCompiler, validate_template
from candleviewer.alerts.errors import AlertIrInvalid
from candleviewer.api import alert_body
from candleviewer.api.alert_body import MAX_ALERT_BODY_BYTES, MAX_ALERT_JSON_DEPTH
from candleviewer.api.alerts import AlertInput
from candleviewer.rules.compiler.common import count_values
from candleviewer.rules.ir.accounts import collect_account_ids
from candleviewer.rules.vocabulary import default_registry
from tests.alerts._alert_api_env import PRICE_CROSS, USER_B
from tests.alerts._alert_write_env import BODY_ROUTES, asgi, deep, padded, sized, target
from tests.rules.test_validator_endpoints import _assert_median_within

#: 22's "64 KiB (65,536 bytes)" and "2,048 values" as literals, which a moved constant fails.
CAP, VALUES = 64 * 1024, 2048


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
    t = target(op)
    r, pulled = await asgi(t, [json.dumps(t.body).encode()], {"content-length": str(CAP + 1)})
    too_large(r)
    assert pulled == [] and t.env.refused == ["body_too_large"]


async def test_alert_body_streamed_past_the_cap_stops_one_chunk_past_it() -> None:
    """Gherkin "before parsing the body": with no length, the stream is read one chunk past the
    cap, never to its end (SR-E40-17)."""
    t = target("create")
    parts = [json.dumps(t.body)[:-1].encode(), *[b" " * (CAP // 16)] * 32, b"}"]
    r, pulled = await asgi(t, parts)
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
    r = t.send(json.dumps(sized(t.body, shape, VALUES + 1)).encode())
    assert (r.status_code, rules(r)) == (422, ["too_many_values"]), r.text[:300]
    assert (t.snapshot(), t.env.refused) == (before, ["too_many_values"])


@SHAPES
def test_alert_body_at_the_value_bound_reaches_validation(op: str, shape: str) -> None:
    """At the value bound the reader passes the body to the route's own checks (SR-E40-17)."""
    t = target(op)
    r = t.send(json.dumps(sized(t.body, shape, VALUES)).encode())
    assert "too_many_values" not in r.text and t.env.refused == []


def _widest(width: int, extra: int = 0) -> dict[str, Any]:
    """The costliest admissible shape measured (#5696): 83 comparisons in groups of 32, each
    metric with 16 decimal `params` (the first with *extra* more), keys *width* characters wide."""

    def params(i: int) -> dict[str, float]:
        n = 16 + (extra if i == 0 else 0)
        return {f"k{i:03d}{j:04d}".ljust(width, "p"): j + 0.125 for j in range(n)}

    comps = [{"node_id": f"c{i}", "op": "gt", "left": {"metric": "price", "params": params(i)},
              "right": {"const": 1}} for i in range(83)]  # fmt: skip
    groups = [{"node_id": f"g{g}", "op": "all_of", "children": comps[g : g + 32]}
              for g in range(0, 83, 32)]  # fmt: skip
    root = {"node_id": "root", "op": "all_of", "children": groups}
    return PRICE_CROSS | {"condition_ir": {**PRICE_CROSS["condition_ir"], "conditions": root}}


@pytest.mark.perf
def test_alert_save_of_the_widest_admissible_body_is_within_the_loop_budget() -> None:
    """C-2.17: the costliest alert measured at the byte cap and the value bound is saved (the
    reader, the model, the compile with its `condition_hash`, the template and the account walk,
    with no await once the body is read) in under 50 ms of CPU, the median of 7 (SR-E40-17)."""
    extra, width = VALUES - count_values(_widest(8)), 8
    while len(json.dumps(_widest(width + 1, extra))) <= CAP:
        width += 1
    raw = padded(_widest(width, extra), CAP)
    assert count_values(json.loads(raw)) == VALUES and target("create").send(raw).status_code == 201
    compiler, refused = AlertCompiler(default_registry()), list[str]()
    scope = {"type": "http", "headers": [(b"content-length", str(CAP).encode())]}

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": raw}

    with asyncio.Runner() as runner:

        def save() -> None:
            doc = runner.run(alert_body.read_alert_body(Request(scope, receive), refused.append))
            body = AlertInput.model_validate(doc)
            compiled = compiler.compile(body.condition_ir)
            validate_template(body.message_template, compiled.metrics)
            collect_account_ids(compiled.condition_ir)

        _assert_median_within(save, budget_ms=50, clock=time.process_time)
    assert refused == []


@pytest.mark.parametrize(("codec", "mark"), [("utf-16", b""), ("utf-8", codecs.BOM_UTF8)])
@ROUTES
def test_alert_body_not_utf8_or_with_a_byte_order_mark_is_the_routes_not_json_422(
    op: str, codec: str, mark: bytes
) -> None:
    """22: UTF-8 without a byte order mark. In another encoding (RFC 8259 section 8.1), or with the
    mark, the body is the route's own 422 for one that is not JSON: nothing changed, nothing
    counted (SR-E40-17)."""
    t = target(op)
    before = t.snapshot()
    r = t.send(mark + json.dumps(t.body).encode(codec))
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


@pytest.mark.parametrize("op", ["create", "update", "enabled"])
def test_alert_bounds_answer_before_the_armed_alert_cap(op: str) -> None:
    """22: the bounds come before the body is validated, the armed-alert cap (#1864) at the write.
    At the cap, a create, a replace and an enable that would arm one, sent over the byte cap, are
    the 413: the bound's refusal is counted, never the cap's, and nothing changes (SR-E40-17)."""
    t = target(op)
    t.env.repo.rows = {k: replace(a, enabled=False) for k, a in t.env.repo.rows.items()}
    t.env.repo.max_armed = 0  # none armed, and the caller is at the cap: the write would arm one
    before = t.snapshot()
    r = t.send(padded(t.body | {"enabled": True}, CAP + 1))
    assert (r.status_code, t.snapshot(), t.env.refused) == (413, before, ["body_too_large"])
    assert t.env.cap_refusals == []
